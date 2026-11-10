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
    @Published private(set) var pending: NativeJSON = .null
    @Published var error: String?
    private weak var session: NativeSession?
    private var task: Task<Void,Never>?
    private var bound = false
    var needsVerification: Bool { !pending.isNull }

    func attach(_ session:NativeSession,conversationID:String? = nil) async {
        guard !bound else { return }; bound = true; self.session = session
        pending = session.local?.draft("ai-pending")["value"] ?? .null
        let selected = conversationID ?? session.local?.draft("ai-current")["value"].text ?? ""
        do {
            if !selected.isEmpty { try await open(selected) }
            else if !pending["conversation_id"].text.isEmpty { try await open(pending["conversation_id"].text) }
            else { restoreInput() }
            if !pending.isNull { error = "上次回复尚未核实，请先核实结果，避免重复发送。" }
        } catch { self.error = NativeSession.readable(error) }
    }
    func open(_ id:String) async throws {
        guard !busy else { throw NativeAPIError.message("请等待当前回复结束。") }
        if !pending.isNull,pending["conversation_id"].text != id { throw NativeAPIError.message("请先核实上次回复，再切换对话。") }
        guard let session else { return }
        saveInput()
        let next = try await session.api("agent/conversations/"+id)
        guard next["status"].text == "active" else { throw NativeAPIError.message("这段对话已归档，请先在历史中恢复。") }
        conversation = next; messages = []; reply = ""; confirmations = []
        try session.local?.saveDraft("ai-current",label:"当前 AI 会话",value:.string(id))
        restoreInput(); try await history()
    }
    func newConversation() async throws {
        guard let session,!busy,pending.isNull else { throw NativeAPIError.message("请先完成或核实当前回复。") }
        saveInput(); conversation = try await session.api("agent/conversations",method:"POST",body:["title":.null])
        messages = []; confirmations = []; input = ""; images = []; reply = ""; error = nil
        try session.local?.saveDraft("ai-current",label:"当前 AI 会话",value:.string(conversation.id))
    }
    private var inputKey:String { "ai-input-"+(conversation.id.isEmpty ? "new" : conversation.id) }
    func saveInput() {
        do { try session?.local?.saveDraft(inputKey,label:"AI 提问",value:input.isEmpty && images.isEmpty ? .null : .object(["text":.string(input),"images":.strings(images)])) }
        catch { self.error = NativeSession.readable(error) }
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
    func send() {
        guard !busy,pending.isNull,(!input.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty || !images.isEmpty) else { return }
        busy = true; error = nil
        task = Task {
            do {
                guard let session else { return }
                if conversation.id.isEmpty {
                    conversation = try await session.api("agent/conversations",method:"POST",body:["title":.null])
                    try session.local?.saveDraft("ai-current",label:"当前 AI 会话",value:.string(conversation.id))
                }
                let text = input.trimmingCharacters(in:.whitespacesAndNewlines)
                pending = .object(["conversation_id":.string(conversation.id),"body":.object(["message":.string(text.isEmpty ? "请分析这些图片" : text),"image_asset_ids":.strings(images),"client_turn_id":.string(UUID().uuidString),"context_hints":.object(["occurred_at":.string(NativeDates.timestamp())])])])
                try persistPending()
                input = ""; images = []; saveInput()
                try await consume()
            } catch { self.error = NativeSession.readable(error)+" 请先核实上次结果。" }
            busy = false; activity = nil
        }
    }
    private func persistPending() throws { try session?.local?.saveDraft("ai-pending",label:"待核实的 AI 请求",value:pending) }
    private func consume() async throws {
        guard let session else { return }
        reply = ""; activity = "正在读取相关资料"; var terminal = false
        try await session.streamConversation(pending["conversation_id"].text,body:pending["body"].fields) { event,payload in
            switch event {
            case "run_started":
                var value = self.pending.fields; value["run_id"] = payload["run_id"]; self.pending = .object(value); try self.persistPending()
            case "node_completed":
                self.activity = ["plan_request":"正在制定回答思路","execute_branches":"正在读取相关数据","validate_safety":"正在检查建议","synthesize_response":"正在组织回复"][payload["node"].text] ?? "正在处理"
            case "message_delta": self.reply += payload["delta"].text; self.activity = "正在回复"
            case "completed":
                terminal = true
                let response = payload["response"]
                guard !response["message"].isNull else { throw NativeAPIError.message("回复结果不完整，请核实结果。") }
                self.reply = response["message"].text; self.confirmations = response["confirmation_cards"].values
                if ["partial","failed"].contains(response["status"].text) { self.error = "部分处理未完成，请查看回复和草稿后再决定是否重试。" }
            case "cancelled": terminal = true; self.error = "本次回复已取消，请核对已保存的草稿和记录。"
            case "failed":
                terminal = payload["error_code"].text != "AGENT_TURN_IN_PROGRESS"
                self.error = ["VISION_MODEL_BUSY":"视觉服务繁忙，照片已保留。","VISION_ASSESSMENT_INVALID":"视觉评估不完整，照片已保留。"][payload["error_code"].text] ?? "AI 私人教练暂时未能完成处理，请核对结果后重试。"
            default: break
            }
        }
        guard terminal else { throw NativeAPIError.message("连接中断，收到的内容已保留。") }
        try await resolve()
    }
    private func resolve() async throws {
        try await history()
        if error != nil,!pending.isNull {
            if input.isEmpty { input = pending["body"]["message"].text }
            if images.isEmpty { images = pending["body"]["image_asset_ids"].strings }; saveInput()
        }
        pending = .null; try persistPending(); activity = nil
    }
    func verify() {
        guard !busy,!pending.isNull else { return }; busy = true; error = nil
        task = Task {
            defer { busy = false; activity = nil }
            do {
                guard let session else { return }
                let id = pending["run_id"].text
                if id.isEmpty { try await consume(); return } // Same persisted client_turn_id; server replays, never a fresh turn.
                let run = try await session.api("agent/runs/"+id)
                guard run.id == id,run["conversation_id"].text == pending["conversation_id"].text else { throw NativeAPIError.message("处理状态不一致，请重新打开这段对话。") }
                if ["running","cancel_requested"].contains(run["status"].text) { error = "请求仍在处理中，稍后再核实；可以取消本次处理。"; return }
                if run["status"].text == "succeeded" { reply = run["result_payload"]["message"].text }
                else { error = "上次处理"+(run["status"].text == "cancelled" ? "已取消" : "未完成")+"，请核对已保存的内容。" }
                try await resolve()
            } catch { self.error = NativeSession.readable(error) }
        }
    }
    func cancel() async throws {
        guard let session,!pending["run_id"].text.isEmpty else { throw NativeAPIError.message("尚未收到处理编号，请先核实结果。") }
        let id = pending["run_id"].text
        let run = try await session.api("agent/runs/"+id)
        if ["running","cancel_requested"].contains(run["status"].text) { _ = try await session.api("agent/runs/"+id+":cancel",method:"POST",body:["expected_version":.int(run.version)]) }
        error = "已请求取消，稍后核实最终结果。"
    }
}
