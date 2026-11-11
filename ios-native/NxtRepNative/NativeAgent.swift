import Foundation
import Combine
import CryptoKit

enum NativeIDs {
    static func stable(_ text:String) -> String {
        var b = Array(SHA256.hash(data:Data(text.utf8)).prefix(16)); b[6] = (b[6] & 15) | 80; b[8] = (b[8] & 63) | 128
        let h = b.map {String(format:"%02x",$0)}.joined()
        return [String(h.prefix(8)),String(h.dropFirst(8).prefix(4)),String(h.dropFirst(12).prefix(4)),String(h.dropFirst(16).prefix(4)),String(h.suffix(12))].joined(separator:"-")
    }
}

@MainActor
final class NativeAgent: ObservableObject {
    @Published private(set) var conversation: NativeJSON = .null
    @Published private(set) var messages: [NativeJSON] = []
    @Published private(set) var confirmations: [NativeJSON] = []
    @Published var input = ""
    @Published var images: [String] = []
    @Published private(set) var reply = ""
    @Published private(set) var activity: String?
    @Published private(set) var busy = false
    @Published private(set) var loadingConversation = false
    @Published private(set) var receivingReply = false
    @Published private(set) var stopping = false
    @Published private(set) var pending: NativeJSON = .null
    @Published var error: String?
    @Published private(set) var notice: String?
    private weak var session: NativeSession?
    private var bound = false
    private var stoppingRunID: String?
    var needsVerification: Bool { !pending.isNull }
    var canCompose: Bool { session != nil && !busy && !loadingConversation && !needsVerification }
    var canSend: Bool {
        canCompose && (!input.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || !images.isEmpty)
    }

    func attach(_ session:NativeSession,conversationID:String? = nil) async {
        guard !bound else { return }
        bound = true
        self.session = session
        pending = session.local?.draft("ai-pending")["value"] ?? .null
        restoreInput()
        let pendingID = pending["conversation_id"].text
        let selected = pendingID.isEmpty
            ? (conversationID ?? session.local?.draft("ai-current")["value"].text ?? "")
            : pendingID
        do {
            if !selected.isEmpty { try await open(selected) }
            if !pending.isNull { error = "上次回复尚未核实，请先核实结果，避免重复发送。" }
        } catch { self.error = NativeSession.readable(error) }
    }
    func open(_ id:String) async throws {
        guard !busy,!loadingConversation else { throw NativeAPIError.message("请等待当前对话加载完成。") }
        if !pending.isNull,pending["conversation_id"].text != id { throw NativeAPIError.message("请先核实上次回复，再切换对话。") }
        guard let session else { return }
        loadingConversation = true
        defer { loadingConversation = false }
        try persistInput()
        let next = try await session.api("agent/conversations/"+id)
        guard next["status"].text == "active" else { throw NativeAPIError.message("这段对话已归档，请先在历史中恢复。") }
        try rememberConversation(id)
        showConversation(next)
        try await history()
    }
    func startNewConversation() throws {
        guard canCompose else { throw NativeAPIError.message("请先完成或核实当前回复。") }
        try persistInput()
        try rememberConversation(nil)
        showConversation(.null)
    }

    private func rememberConversation(_ id: String?) throws {
        try session?.local?.saveDraft("ai-current",label:"当前 AI 会话",value:id.map(NativeJSON.string) ?? .null)
    }

    private func showConversation(_ next: NativeJSON) {
        conversation = next
        messages = []
        confirmations = []
        reply = ""
        error = nil
        notice = nil
        restoreInput()
    }
    private var inputKey:String { "ai-input-"+(conversation.id.isEmpty ? "new" : conversation.id) }
    func saveInput() {
        do { try persistInput() }
        catch { self.error = NativeSession.readable(error) }
    }
    private func persistInput() throws {
        let draft: NativeJSON = input.isEmpty && images.isEmpty
            ? .null
            : .object(["text":.string(input),"images":.strings(images)])
        try session?.local?.saveDraft(inputKey,label:"AI 提问",value:draft)
    }
    private func restoreInput() { let v = session?.local?.draft(inputKey)["value"] ?? .null; input = v["text"].text; images = v["images"].strings }
    func history() async throws {
        guard let session,!conversation.id.isEmpty else { return }
        var result: [NativeJSON] = [],cursor = 0
        while true {
            let page = try await session.api("agent/conversations/"+conversation.id+"/messages",query:["after_sequence":String(cursor),"limit":"100"])
            let items = page["list"].values
            var last = cursor
            for item in items { guard item["sequence"].integer > last else { throw NativeAPIError.message("聊天记录分页异常，请重新打开对话。") }; last = item["sequence"].integer }
            result += items
            if !page["has_more"].flag { break }
            guard !items.isEmpty,page["next_sequence"].integer == last,last > cursor else { throw NativeAPIError.message("聊天记录分页不完整，请重新加载。") }
            cursor = last
        }
        messages = result
        if result.last?["role"].text == "assistant",result.last?["content"].text == reply { reply = "" }
        let cards = try await session.api("agent/conversations/"+conversation.id+"/confirmations")
        confirmations = cards["confirmation_cards"].values + cards["completed_cards"].values
    }
    func send() async {
        guard let session,canSend else { return }
        if session.local?.localOnly == true {
            error = "AI 对话需要联网。请在「我的 → 离线记录与草稿」关闭仅保存在本机后重试。"
            return
        }
        let text = input.trimmingCharacters(in:.whitespacesAndNewlines)
        let sourceDraftKey = inputKey
        busy = true
        receivingReply = true
        error = nil
        notice = nil
        activity = "正在发送"
        defer { finishActivity() }
        do {
            if conversation.id.isEmpty {
                let created = try await session.api("agent/conversations",method:"POST",body:["title":.null])
                guard UUID(uuidString:created.id) != nil else {
                    throw NativeAPIError.message("创建对话后没有收到有效编号，请打开历史检查。")
                }
                conversation = created
                try rememberConversation(created.id)
            }
            if stopping {
                notice = "已停止发送。"
                return
            }
            let request: [String:NativeJSON] = [
                "message":.string(text.isEmpty ? "请分析这些图片" : text),
                "image_asset_ids":.strings(images),
                "client_turn_id":.string(UUID().uuidString),
                "context_hints":.object(["occurred_at":.string(NativeDates.timestamp())])
            ]
            try updatePending(.object(["conversation_id":.string(conversation.id),"body":.object(request)]))
            input = ""
            images = []
            try? session.local?.saveDraft(sourceDraftKey,label:"AI 提问",value:.null)
            try await consume()
        } catch {
            let message = NativeSession.readable(error)
            self.error = needsVerification ? message + " 请点「核实上次回复」。" : message
        }
    }
    private func updatePending(_ next: NativeJSON) throws {
        try session?.local?.saveDraft("ai-pending",label:"待核实的 AI 请求",value:next)
        pending = next
    }
    private func consume() async throws {
        guard let session else { return }
        receivingReply = true
        reply = ""; activity = "正在读取相关资料"; var terminal = false
        var cancelled = false
        try await session.streamConversation(pending["conversation_id"].text,body:pending["body"].fields) { event,payload in
            switch event {
            case "run_started":
                var value = self.pending.fields
                value["run_id"] = payload["run_id"]
                try self.updatePending(.object(value))
                self.submitStopIfReady()
            case "node_completed":
                self.activity = ["plan_request":"正在制定回答思路","execute_branches":"正在读取相关数据","validate_safety":"正在检查建议","synthesize_response":"正在组织回复"][payload["node"].text] ?? "正在处理"
            case "message_delta":
                if !self.stopping { self.reply += payload["delta"].text }
                self.activity = "正在回复"
            case "completed":
                terminal = true
                self.receivingReply = false
                let response = payload["response"]
                guard !response["message"].isNull else { throw NativeAPIError.message("回复结果不完整，请核实结果。") }
                self.reply = response["message"].text; self.confirmations = response["confirmation_cards"].values
                if ["partial","failed"].contains(response["status"].text) { self.error = "部分处理未完成，请查看回复和草稿后再决定是否重试。" }
            case "cancelled":
                terminal = true
                cancelled = true
                self.receivingReply = false
                self.notice = "已停止回复。"
            case "failed":
                terminal = payload["error_code"].text != "AGENT_TURN_IN_PROGRESS"
                self.receivingReply = false
                self.error = ["VISION_MODEL_BUSY":"视觉服务繁忙，照片已保留。","VISION_ASSESSMENT_INVALID":"视觉评估不完整，照片已保留。"][payload["error_code"].text] ?? "AI 私人教练暂时未能完成处理，请核对结果后重试。"
            default: break
            }
        }
        guard terminal else { throw NativeAPIError.message("连接中断，收到的内容已保留。") }
        try await resolve(restoreDraft: cancelled)
    }
    private func resolve(restoreDraft: Bool = false) async throws {
        try await history()
        if (restoreDraft || error != nil),!pending.isNull {
            if input.isEmpty { input = pending["body"]["message"].text }
            if images.isEmpty { images = pending["body"]["image_asset_ids"].strings }; saveInput()
        }
        try updatePending(.null)
        activity = nil
    }
    func verify() {
        guard !busy,!pending.isNull else { return }
        busy = true; error = nil; notice = nil
        Task {
            defer { finishActivity() }
            do {
                guard let session else { return }
                let id = pending["run_id"].text
                if id.isEmpty { try await consume(); return } // Same persisted client_turn_id; server replays, never a fresh turn.
                let run = try await session.api("agent/runs/"+id)
                guard run.id == id,run["conversation_id"].text == pending["conversation_id"].text else { throw NativeAPIError.message("处理状态不一致，请重新打开这段对话。") }
                if ["running","cancel_requested"].contains(run["status"].text) { error = "请求仍在处理中，稍后再核实；可以取消本次处理。"; return }
                let cancelled = run["status"].text == "cancelled"
                if run["status"].text == "succeeded" { reply = run["result_payload"]["message"].text }
                else if cancelled { notice = "已停止回复。" }
                else { error = "上次处理未完成，请核对已保存的内容。" }
                try await resolve(restoreDraft: cancelled)
            } catch { self.error = NativeSession.readable(error) }
        }
    }
    private func finishActivity() {
        busy = false
        activity = nil
        receivingReply = false
        stopping = false
    }

    func requestStop() {
        guard !stopping, receivingReply || (!busy && !pending["run_id"].text.isEmpty) else { return }
        stopping = true
        error = nil
        submitStopIfReady()
    }

    private func submitStopIfReady() {
        let id = pending["run_id"].text
        let conversationID = pending["conversation_id"].text
        guard let session, stopping, UUID(uuidString: id) != nil, stoppingRunID != id else { return }
        stoppingRunID = id
        Task {
            defer { if stoppingRunID == id { stoppingRunID = nil } }
            do {
                let result = try await stopRun(id, conversationID: conversationID, session: session)
                guard pending["run_id"].text == id else { return }
                if !receivingReply && !busy {
                    if ["succeeded", "cancelled", "failed"].contains(result["status"].text) {
                        verify()
                    } else {
                        notice = "停止请求已提交，请核实本次结果。"
                        stopping = false
                    }
                }
            } catch {
                guard pending["run_id"].text == id else { return }
                stopping = false
                self.error = "未能停止。" + NativeSession.readable(error)
            }
        }
    }

    private func stopRun(_ id: String, conversationID: String, session: NativeSession) async throws -> NativeJSON {
        let path = "agent/runs/" + id
        for attempt in 0..<3 {
            let run = try await session.api(path)
            guard run.id == id, run["conversation_id"].text == conversationID, run.version > 0 else {
                throw NativeAPIError.message("无法核实本次处理状态。")
            }
            guard run["status"].text == "running" else { return run }
            do {
                return try await session.api(path + ":cancel", method: "POST", body: ["expected_version": .int(run.version)])
            } catch NativeAPIError.response(409, _) where attempt < 2 {
                continue
            }
        }
        throw NativeAPIError.message("处理状态正在更新，请重试。")
    }
}
