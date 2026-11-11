import SwiftUI

struct NativeCoachView: View {
    @EnvironmentObject private var session: NativeSession
    @StateObject private var agent = NativeAgent()
    var conversationID: String? = nil
    @State private var showHistory = false
    @State private var showAttachment = false
    @FocusState private var composerFocused: Bool

    private var title: String {
        if agent.conversation.id.isEmpty { return "新对话" }
        let savedTitle = agent.conversation["title"].text
        return savedTitle.isEmpty ? "AI 私人教练" : savedTitle
    }

    var body: some View {
        VStack(spacing: 0) {
            transcript
            Divider()
            composer
        }
        .background(NativeTheme.background)
        .navigationTitle(title)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItemGroup(placement: .topBarTrailing) {
                Button {
                    composerFocused = false
                    showHistory = true
                } label: {
                    Image(systemName: "clock.arrow.circlepath")
                }
                .accessibilityLabel("对话历史")
                .disabled(!agent.canCompose)

                Button {
                    do {
                        try agent.startNewConversation()
                        composerFocused = true
                    } catch {
                        agent.error = NativeSession.readable(error)
                    }
                } label: {
                    Image(systemName: "square.and.pencil")
                }
                .accessibilityLabel("新对话")
                .disabled(!agent.canCompose)
            }
        }
        .sheet(isPresented: $showHistory) {
            NavigationStack {
                NativeConversationHistory { id in
                    Task {
                        showHistory = false
                        do { try await agent.open(id) }
                        catch { agent.error = NativeSession.readable(error) }
                    }
                }
            }
        }
        .sheet(isPresented: $showAttachment) {
            NavigationStack {
                NativeChatAttachment { id in
                    if !agent.images.contains(id) { agent.images.append(id) }
                }
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) {
                        Button("取消") { showAttachment = false }
                    }
                }
            }
        }
        .task { await agent.attach(session, conversationID: conversationID) }
        .onChange(of: agent.input) { _, _ in agent.saveInput() }
        .onChange(of: agent.images) { _, _ in agent.saveInput() }
        .onDisappear { agent.saveInput() }
    }

    private var transcript: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 18) {
                    if agent.loadingConversation {
                        ProgressView("正在读取对话").frame(maxWidth: .infinity).padding(24)
                    } else if agent.messages.isEmpty && !agent.needsVerification && agent.activity == nil {
                        emptyConversation
                    }

                    ForEach(agent.messages, id: \.id) { NativeChatMessage(message: $0) }
                    if let outgoingMessage { NativeChatMessage(message: outgoingMessage) }
                    if !agent.reply.isEmpty {
                        NativeChatMessage(message: .object(["role": .string("assistant"), "content": .string(agent.reply)]))
                    }
                    if let activity = agent.activity {
                        HStack(spacing: 8) {
                            ProgressView()
                            Text(agent.stopping ? "正在停止" : activity).font(.subheadline).foregroundStyle(NativeTheme.muted)
                        }
                    }
                    ForEach(agent.confirmations, id: \.id) { card in
                        NativeChangePreviewCard(card: card) { try await agent.history() }.disabled(agent.busy)
                    }
                    NativeErrorText(message: agent.error)
                    if let notice = agent.notice {
                        Text(notice).font(.footnote).foregroundStyle(NativeTheme.muted)
                    }
                    if agent.needsVerification && !agent.busy {
                        Button("核实上次回复") { agent.verify() }
                            .buttonStyle(.borderedProminent)
                    }
                    if agent.needsVerification && !agent.busy && !agent.pending["run_id"].text.isEmpty {
                        Button("停止上次处理") { agent.requestStop() }.disabled(agent.stopping)
                    }
                    Color.clear.frame(height: 1).id("end").accessibilityHidden(true)
                }
                .padding(.horizontal, 18)
                .padding(.vertical, 14)
                .frame(maxWidth: 680)
                .frame(maxWidth: .infinity)
            }
            .scrollDismissesKeyboard(.interactively)
            .refreshable {
                guard agent.canCompose else { return }
                do { try await agent.history() }
                catch { agent.error = NativeSession.readable(error) }
            }
            .onChange(of: agent.messages.count) { _, _ in proxy.scrollTo("end", anchor: .bottom) }
            .onChange(of: agent.reply) { _, _ in proxy.scrollTo("end", anchor: .bottom) }
            .onChange(of: agent.activity) { _, _ in proxy.scrollTo("end", anchor: .bottom) }
            .onChange(of: agent.error) { _, error in if error != nil { proxy.scrollTo("end", anchor: .bottom) } }
            .onChange(of: agent.notice) { _, notice in if notice != nil { proxy.scrollTo("end", anchor: .bottom) } }
        }
        .frame(maxHeight: .infinity)
    }

    private var emptyConversation: some View {
        VStack(spacing: 10) {
            Image(systemName: "sparkles")
                .font(.title2.weight(.semibold))
                .foregroundStyle(NativeTheme.accent)
                .frame(width: 52, height: 52)
                .background(NativeTheme.softAccent, in: RoundedRectangle(cornerRadius: 18))
                .accessibilityHidden(true)
            Text("今天想聊什么？").font(.title2.bold()).foregroundStyle(NativeTheme.ink)
            Text("训练安排、饮食记录和身体进展，都可以直接问我。")
                .font(.subheadline)
                .foregroundStyle(NativeTheme.muted)
                .multilineTextAlignment(.center)
            NavigationLink("查看主动教练建议") { NativeCoachNoticesView() }
                .font(.footnote.weight(.medium))
                .padding(.top, 4)
        }
        .frame(maxWidth: .infinity)
        .padding(.top, 52)
        .padding(.bottom, 18)
    }

    private var outgoingMessage: NativeJSON? {
        guard agent.needsVerification else { return nil }
        let body = agent.pending["body"]
        let lastUser = agent.messages.last { $0["role"].text == "user" }
        if lastUser?["content"] == body["message"] && lastUser?["image_asset_ids"] == body["image_asset_ids"] {
            return nil
        }
        return .object(["role": .string("user"), "content": body["message"], "image_asset_ids": body["image_asset_ids"]])
    }

    private var composer: some View {
        VStack(alignment: .leading, spacing: 8) {
            if !agent.images.isEmpty {
                ScrollView(.horizontal) {
                    HStack(spacing: 10) {
                        ForEach(agent.images, id: \.self) { id in
                            VStack(spacing: 4) {
                                NativeRemoteImage(assetID: id)
                                    .frame(width: 64, height: 64)
                                    .clipped()
                                Button("移除") { agent.images.removeAll { $0 == id } }
                                    .font(.caption)
                                    .disabled(!agent.canCompose)
                            }
                        }
                    }
                }
            }
            HStack(alignment: .bottom, spacing: 8) {
                Button {
                    composerFocused = false
                    showAttachment = true
                } label: {
                    Image(systemName: "plus")
                        .font(.system(size: 18, weight: .semibold))
                        .frame(width: 44, height: 44)
                }
                .accessibilityLabel("添加图片")
                .disabled(!agent.canCompose || agent.images.count >= 4)

                TextField("给私人教练发消息", text: $agent.input, axis: .vertical)
                    .focused($composerFocused)
                    .lineLimit(1...5)
                    .padding(.vertical, 10)
                    .frame(minHeight: 44)
                    .disabled(!agent.canCompose)
                    .accessibilityIdentifier("coach-message-input")

                composerAction
            }
            .buttonStyle(.plain)
            .padding(5)
            .background(NativeTheme.surface, in: RoundedRectangle(cornerRadius: 25))
            .overlay {
                RoundedRectangle(cornerRadius: 25)
                    .strokeBorder(composerFocused ? NativeTheme.accent : NativeTheme.line)
                    .allowsHitTesting(false)
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .frame(maxWidth: 680)
        .frame(maxWidth: .infinity)
        .background(NativeTheme.background)
    }

    private var composerAction: some View {
        Button {
            if agent.receivingReply {
                agent.requestStop()
            } else {
                composerFocused = false
                Task { await agent.send() }
            }
        } label: {
            Group {
                if agent.receivingReply {
                    RoundedRectangle(cornerRadius: 2).frame(width: 13, height: 13)
                } else {
                    Image(systemName: "arrow.up").font(.system(size: 17, weight: .semibold))
                }
            }
            .frame(width: 44, height: 44)
            .foregroundStyle(.white)
            .background((agent.receivingReply && !agent.stopping) || agent.canSend
                        ? NativeTheme.accent : NativeTheme.muted.opacity(0.45), in: Circle())
        }
        .accessibilityLabel(agent.receivingReply ? "停止回复" : "发送消息")
        .disabled(agent.receivingReply ? agent.stopping : !agent.canSend)
    }
}

private struct NativeChatAttachment: View {
    @Environment(\.dismiss) private var dismiss
    let select:(String)->Void
    init(onSelect:@escaping (String)->Void) { select = onSelect }
    var body: some View { VStack { NativeImageSelector(purpose:"chat_attachment") { if !$0.isEmpty { select($0); dismiss() } }; Spacer() }.padding().navigationTitle("添加照片") }
}

private struct NativeChatMessage: View {
    let message: NativeJSON
    private var fromUser: Bool { message["role"].text == "user" }

    var body: some View {
        HStack(alignment: .top, spacing: 0) {
            if fromUser { Spacer(minLength: 36) }
            VStack(alignment: .leading, spacing: 8) {
                ForEach(message["image_asset_ids"].strings, id: \.self) {
                    NativeRemoteImage(assetID: $0).frame(maxHeight: 240)
                }
                if fromUser {
                    Text(message["content"].text).textSelection(.enabled)
                } else {
                    NativeReplyText(content: message["content"].text)
                }
            }
            .padding(.horizontal, fromUser ? 14 : 0)
            .padding(.vertical, fromUser ? 10 : 0)
            .foregroundStyle(NativeTheme.ink)
            .background(fromUser ? NativeTheme.softAccent : .clear, in: RoundedRectangle(cornerRadius: 18))
            if !fromUser { Spacer(minLength: 0) }
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel(fromUser ? "你" : "私人教练")
    }
}

struct NativeReplyText: View {
    let content:String
    var body: some View {
        Text(.init(cleaned)).textSelection(.enabled)
        ForEach(Array(links.enumerated()),id:\.offset) { _,url in Link(destination:url) { Label(url.host ?? "查看来源",systemImage:"link").font(.caption) } }
    }
    private var links:[URL] {
        let detector = try? NSDataDetector(types:NSTextCheckingResult.CheckingType.link.rawValue)
        let found = detector?.matches(in:content,range:NSRange(content.startIndex...,in:content)).compactMap(\.url) ?? []
        var seen = Set<String>()
        return Array(found.filter { ["http","https"].contains($0.scheme) && $0.host != nil && $0.user == nil && $0.password == nil && seen.insert($0.absoluteString).inserted }.prefix(5))
    }
    private var cleaned:String {
        content.components(separatedBy:"\n").filter { line in !["tool_call_id","cache_hit","cache_age_seconds","searched_at","cache_ttl_seconds"].contains(where:line.trimmingCharacters(in:.whitespaces).hasPrefix) }.joined(separator:"\n")
    }
}

struct NativeConversationHistory: View {
    @EnvironmentObject private var session: NativeSession
    @StateObject private var resource = NativeResource()
    let onSelect:(String)->Void
    @State private var archived = false
    @State private var renaming:NativeJSON = .null
    @State private var title = ""
    @State private var deleting:NativeJSON = .null
    @State private var revision = 0
    var body: some View {
        List {
            Toggle("查看已归档",isOn:$archived)
            NativeErrorText(message:resource.error)
            if resource.loading { ProgressView() }
            ForEach(resource.value.records,id:\.id) { conversation in
                VStack(alignment:.leading,spacing:8) {
                    Button(conversation["title"].text.isEmpty ? "新对话" : conversation["title"].text) { onSelect(conversation.id) }.disabled(archived)
                    Text(NativeDates.display(conversation["last_message_at"].text.isEmpty ? conversation["created_at"].text : conversation["last_message_at"].text)).font(.caption).foregroundStyle(NativeTheme.muted)
                    HStack {
                        Button("重命名") { renaming = conversation; title = conversation["title"].text }
                        NativeActionButton(title:archived ? "恢复" : "归档") { _ in _ = try await session.api("agent/conversations/"+conversation.id,method:"PATCH",body:["status":.string(archived ? "active" : "archived"),"expected_version":.int(conversation.version)]); revision += 1 }
                        Button("删除",role:.destructive) { deleting = conversation }
                    }.font(.caption)
                }.padding(.vertical,5)
            }
        }.navigationTitle("对话历史").task(id:"\(archived)|\(revision)") { await resource.load { .array(try await session.allPages("agent/conversations",query:["status":archived ? "archived" : "active"])) } }
        .alert("重命名对话",isPresented:Binding(get:{!renaming.isNull},set:{if !$0 { renaming = .null }})) {
            TextField("标题",text:$title)
            Button("保存") { let item = renaming; Task { do { _ = try await session.api("agent/conversations/"+item.id,method:"PATCH",body:["title":.string(title),"expected_version":.int(item.version)]); revision += 1 } catch { resource.error = NativeSession.readable(error) } }; renaming = .null }
            Button("取消",role:.cancel) { renaming = .null }
        }
        .confirmationDialog("永久删除这段对话及消息？",isPresented:Binding(get:{!deleting.isNull},set:{if !$0 { deleting = .null }}),titleVisibility:.visible) {
            Button("删除",role:.destructive) { let item = deleting; deleting = .null; Task { do { _ = try await session.api("agent/conversations/"+item.id,method:"DELETE",body:["expected_version":.int(item.version)]); revision += 1 } catch { resource.error = NativeSession.readable(error) } } }
        }
    }
}

struct NativeChangePreviewCard: View {
    @EnvironmentObject private var session: NativeSession
    let card: NativeJSON
    let onChange: () async throws -> Void
    @State private var showingPreview = false
    @State private var submitting = false
    @State private var error: String?
    @State private var receiptStatus: String?
    @State private var revisedCard: NativeJSON?
    @State private var portionEdits: [Int: String] = [:]

    private var current: NativeJSON {
        guard let revisedCard, revisedCard.version > card.version else { return card }
        return revisedCard
    }

    private var preview: NativeChangePreview {
        NativeChangePreview(card: current, imperial: session.imperial)
    }

    private var status: String { receiptStatus ?? current["status"].text }
    private var pending: Bool { status == "pending" }
    private var tint: Color { preview.destructive ? .red : NativeTheme.accent }

    private var statusText: String {
        switch status {
        case "pending": "待确认"
        case "succeeded": "已应用"
        case "rejected": "未采纳"
        case "cancelled": "已取消"
        case "expired": "已过期"
        default: "查看结果"
        }
    }

    var body: some View {
        NativeCard {
            HStack(alignment: .top, spacing: 10) {
                Image(systemName: preview.icon)
                    .font(.system(size: 17, weight: .semibold))
                    .foregroundStyle(tint)
                    .frame(width: 38, height: 38)
                    .background(tint.opacity(0.10), in: RoundedRectangle(cornerRadius: 12))
                    .accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 4) {
                    Text(preview.title).font(.headline).foregroundStyle(NativeTheme.ink)
                    Text(statusText)
                        .font(.caption.weight(.medium))
                        .foregroundStyle(pending ? tint : NativeTheme.muted)
                }
                Spacer(minLength: 0)
            }

            let highlights = Array(preview.sections.flatMap(\.rows).prefix(3))
            if highlights.isEmpty {
                Text(preview.impact ?? "详细内容暂时不可用。").font(.subheadline).foregroundStyle(NativeTheme.muted)
            } else {
                ForEach(Array(highlights.enumerated()), id: \.offset) { _, row in
                    previewRow(row)
                }
            }

            Button {
                error = nil
                portionEdits = [:]
                showingPreview = true
            } label: {
                HStack {
                    Text(pending ? "查看改动" : "查看详情").fontWeight(.semibold)
                    Spacer()
                    Image(systemName: "chevron.right").font(.caption.weight(.semibold))
                }
                .frame(minHeight: 44)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .foregroundStyle(tint)
        }
        .sheet(isPresented: $showingPreview) {
            NavigationStack {
                VStack(spacing: 0) {
                    ScrollView {
                        VStack(alignment: .leading, spacing: 16) {
                            Text(preview.title).font(.title2.bold())
                            if !pending {
                                Text(statusText).font(.subheadline).foregroundStyle(NativeTheme.muted)
                                NativeErrorText(message: error)
                            }
                            if let impact = preview.impact {
                                Text(impact).font(.subheadline).foregroundStyle(NativeTheme.muted)
                            }
                            ForEach(Array(preview.sections.enumerated()), id: \.offset) { _, section in
                                NativeCard {
                                    Text(section.title).font(.subheadline.weight(.semibold)).foregroundStyle(NativeTheme.muted)
                                    ForEach(Array(section.rows.enumerated()), id: \.offset) { index, row in
                                        if index > 0 { Divider() }
                                        previewRow(row)
                                    }
                                }
                            }
                            if pending && !preview.portions.isEmpty { portionEditor }
                        }
                        .padding(18)
                    }
                    .scrollDismissesKeyboard(.interactively)
                    if pending { decisionButtons }
                }
                .background(NativeTheme.background)
                .navigationTitle("改动预览")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) {
                        Button("关闭") { showingPreview = false }.disabled(submitting)
                    }
                }
            }
            .presentationDetents([.large])
            .interactiveDismissDisabled(submitting)
        }
    }

    private func previewRow(_ row: NativeChangePreview.Row) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            Text(row.label).foregroundStyle(NativeTheme.muted)
            Spacer(minLength: 0)
            VStack(alignment: .trailing, spacing: 2) {
                if let previous = row.previous {
                    Text("原 \(previous)").font(.caption).foregroundStyle(NativeTheme.muted)
                }
                Text(row.value).fontWeight(.semibold).foregroundStyle(NativeTheme.ink)
            }
            .multilineTextAlignment(.trailing)
        }
        .font(.subheadline)
        .accessibilityElement(children: .combine)
    }

    private var portionEditor: some View {
        NativeCard {
            DisclosureGroup("调整份量") {
                ForEach(preview.portions) { portion in
                    HStack {
                        Text(portion.name)
                        Spacer()
                        TextField(portion.grams, text: Binding(
                            get: { portionEdits[portion.id] ?? "" },
                            set: { portionEdits[portion.id] = $0 }
                        ))
                        .keyboardType(.decimalPad)
                        .multilineTextAlignment(.trailing)
                        .accessibilityLabel(portion.name + "份量")
                        Text("克").foregroundStyle(NativeTheme.muted)
                    }
                    .frame(minHeight: 44)
                }
                Button("更新份量预览") { Task { await revisePortions() } }
                    .buttonStyle(.bordered)
                    .disabled(!hasPortionEdits || submitting)
            }
        }
    }

    private var hasPortionEdits: Bool {
        portionEdits.values.contains { !$0.trimmingCharacters(in: .whitespaces).isEmpty }
    }

    private var decisionButtons: some View {
        VStack(alignment: .leading, spacing: 8) {
            NativeErrorText(message: error)
            if hasPortionEdits {
                Text("先更新份量预览，再保存。").font(.footnote).foregroundStyle(NativeTheme.muted)
            }
            HStack(spacing: 12) {
                Button("不采纳", role: .cancel) { Task { await decide(approve: false) } }
                    .buttonStyle(.bordered)
                    .disabled(submitting)
                Button(role: preview.destructive ? .destructive : nil) {
                    Task { await decide(approve: true) }
                } label: {
                    HStack {
                        if submitting { ProgressView() }
                        Text(submitting ? "正在处理" : preview.approveLabel)
                    }
                    .frame(maxWidth: .infinity, minHeight: 30)
                }
                .buttonStyle(.borderedProminent)
                .tint(tint)
                .disabled(submitting || hasPortionEdits)
            }
            .controlSize(.large)
        }
        .padding(16)
        .background(NativeTheme.surface)
    }

    @MainActor private func revisePortions() async {
        guard !submitting else { return }
        submitting = true
        defer { submitting = false }
        error = nil
        do {
            var changes: [NativeJSON] = []
            for item in preview.portions {
                let text = (portionEdits[item.id] ?? "").trimmingCharacters(in: .whitespaces)
                guard !text.isEmpty else { continue }
                guard let grams = Double(text.replacingOccurrences(of: ",", with: ".")), grams.isFinite, grams > 0 else {
                    throw NativeAPIError.message("请输入 \(item.name) 的有效克数。")
                }
                changes.append(.object(["item_index": .int(item.id), "amount_g": .number(grams)]))
            }
            guard !changes.isEmpty else { return }
            let updated = try await session.api("nutrition/pending-entries/" + current.id + "/portions", method: "POST", body: [
                "expected_version": .int(current.version), "changes": .array(changes)
            ])
            guard updated.id == current.id, updated.version > current.version else {
                throw NativeAPIError.message("份量预览未能核实，请重新打开这段对话。")
            }
            revisedCard = updated
            portionEdits = [:]
            try await onChange()
        } catch {
            self.error = NativeSession.readable(error)
        }
    }

    @MainActor private func decide(approve: Bool) async {
        guard !submitting, pending, !(approve && hasPortionEdits) else { return }
        submitting = true
        defer { submitting = false }
        error = nil
        let id = current.id
        let version = current.version
        let action = approve ? "approve" : "reject"
        do {
            let detail = try await session.api("confirmations/" + id)
            guard detail["status"].text == "pending", detail.version == version else {
                try await onChange()
                throw NativeAPIError.message("这项改动已更新，请重新打开预览。")
            }
            var body: [String: NativeJSON] = ["expected_version": .int(version)]
            if !approve { body["reason"] = .string("用户在 iPhone 选择不采纳") }
            let result = try await session.api("confirmations/" + id + "/" + action, method: "POST", body: body,
                key: NativeIDs.stable("confirmation:" + action + ":" + id + ":" + String(version)))
            let expectedStatus = approve ? "succeeded" : "rejected"
            guard result.id == id, result.version > version, result["status"].text == expectedStatus else {
                throw NativeAPIError.message("改动结果尚未核实，请重新打开预览。")
            }
            receiptStatus = expectedStatus
            showingPreview = false
            await session.reload()
            try? await onChange()
        } catch {
            self.error = NativeSession.readable(error)
        }
    }
}

/// Readable business fields for structured drafts and reports; implementation IDs stay out of the flow.
struct NativeBusinessSummary: View {
    let value:NativeJSON
    var depth = 0
    private var entries:[String] { value.fields.keys.sorted().filter { !["id","version","user_id","confirmation_id","created_by","request_id","operation_type"].contains($0) && !$0.hasSuffix("_id") && !$0.hasSuffix("_ids") } }
    var body: some View {
        VStack(alignment:.leading,spacing:6) {
            if !value.text.isEmpty { Text(value.text).textSelection(.enabled) }
            if depth < 8 {
                ForEach(Array(value.values.enumerated()),id:\.offset) { index,item in NativeBusinessSummary(value:item,depth:depth+1).padding(.leading,8) }
                ForEach(entries,id:\.self) { key in
                    VStack(alignment:.leading,spacing:3) {
                        Text(Self.labels[key] ?? "补充内容").font(.caption.bold()).foregroundStyle(NativeTheme.muted)
                        if value[key].values.isEmpty && value[key].fields.isEmpty { Text(Self.labelValue(value[key],key:key)).font(.subheadline) }
                        else { NativeBusinessSummary(value:value[key],depth:depth+1).padding(.leading,8) }
                    }
                }
            }
        }
    }
    private static func labelValue(_ value:NativeJSON,key:String) -> String {
        if case .bool(let flag) = value { return flag ? "是" : "否" }
        if value.isNull { return "未填写" }
        if key == "equipment" { return NativeLabels.tool(value.text) }
        return NativeLabels.meals[value.text] ?? NativeLabels.statuses[value.text] ?? value.text
    }
    static let labels = ["name":"名称","name_zh":"动作","title":"标题","content":"内容","message":"说明","summary":"概述","status":"状态","goal":"目标","goal_type":"目标类型","target":"目标","items":"食品","amount_g":"份量（克）","basis_amount_g":"营养基准（克）","kcal":"热量（千卡）","protein_g":"蛋白质（克）","carbs_g":"碳水（克）","fat_g":"脂肪（克）","days":"训练日","exercises":"训练动作","day_index":"训练日序号","exercise_name":"动作","target_sets":"目标组数","rep_min":"最少次数","rep_max":"最多次数","rest_seconds":"休息（秒）","target_load_kg":"参考重量（kg）","weekly_frequency":"每周频率","estimated_minutes":"时长（分钟）","scheduled_date":"日期","meal_type":"餐次","eaten_at":"进食时间","notes":"备注","reason":"原因","warnings":"注意事项","nutrition":"饮食","training":"训练","body":"身体数据","workout_count":"训练次数","total_duration_minutes":"训练时长（分钟）","pr_count":"个人纪录","total_volume_kg":"训练量（kg）","weight_kg":"体重（kg）","waist_cm":"腰围（cm）","body_fat_percent":"体脂率（%）","recommendations":"建议","source":"来源","confidence":"可信程度","calculation":"营养计算","totals":"合计","nutrients":"营养","draft":"草稿","after":"调整后","before":"调整前","impact":"影响范围","changes":"变更","period_start":"开始日期","period_end":"结束日期","date":"日期","average_kcal":"平均热量","recorded_days":"记录天数","evidence":"依据"]
}

struct NativeAgentManagementView: View {
    var body: some View {
        List {
            NavigationLink("会话、草稿和改动记录") { NativeAgentDraftsView() }
            NavigationLink("长期记忆") { NativeMemoriesView() }
        }.navigationTitle("AI 管理")
    }
}

private struct NativeAgentDraftsView: View {
    @EnvironmentObject private var session:NativeSession
    @StateObject private var resource = NativeResource()
    var body: some View {
        List {
            NativeErrorText(message:resource.error)
            ForEach(resource.value.records,id:\.id) { conversation in NavigationLink(conversation["title"].text.isEmpty ? "新对话" : conversation["title"].text) { NativeConversationConfirmations(id:conversation.id) } }
        }.navigationTitle("草稿与改动").task { await resource.load { .array(try await session.allPages("agent/conversations",query:["status":"active"])) } }
    }
}

private struct NativeConversationConfirmations: View {
    @EnvironmentObject private var session:NativeSession
    let id:String
    @StateObject private var resource = NativeResource()
    @State private var revision = 0
    var body: some View {
        ScrollView { VStack(alignment:.leading,spacing:14) {
            NativeErrorText(message:resource.error)
            ForEach(resource.value["confirmation_cards"].values + resource.value["completed_cards"].values,id:\.id) { card in NativeChangePreviewCard(card:card) { revision += 1 } }
            if resource.value["confirmation_cards"].values.isEmpty { Text("没有待确认的改动").foregroundStyle(NativeTheme.muted) }
            ForEach(resource.value["resolved_counts"].fields.keys.sorted(),id:\.self) { key in Text(NativeLabels.status(key)+"："+resource.value["resolved_counts"][key].text).font(.caption) }
            NavigationLink("打开这段对话") { NativeCoachView(conversationID:id) }
        }.nativePage() }.navigationTitle("改动记录").task(id:revision) { await resource.load { try await session.api("agent/conversations/"+id+"/confirmations") } }
    }
}

private struct NativeMemoriesView: View {
    @EnvironmentObject private var session:NativeSession
    @StateObject private var resource = NativeResource()
    @State private var editing:NativeJSON?
    @State private var deleting:NativeJSON = .null
    @State private var revision = 0
    var body: some View {
        List {
            NativeErrorText(message:resource.error)
            ForEach(resource.value.records,id:\.id) { item in VStack(alignment:.leading,spacing:8) {
                Text(item["content"].text)
                Text(NativeDates.display(item["saved_at"].text)).font(.caption).foregroundStyle(NativeTheme.muted)
                HStack { Button("编辑") { editing = item }; Button("删除",role:.destructive) { deleting = item } }
            } }
        }.navigationTitle("长期记忆").toolbar { Button("新增") { editing = .null } }
        .task(id:revision) { await resource.load { try await session.api("memories",query:["limit":"50"]) } }
        .sheet(isPresented:Binding(get:{editing != nil},set:{if !$0 { editing = nil }})) { NavigationStack { NativeMemoryForm(existing:editing ?? .null) { editing = nil; revision += 1 } } }
        .confirmationDialog("删除这条长期记忆？",isPresented:Binding(get:{!deleting.isNull},set:{if !$0 { deleting = .null }}),titleVisibility:.visible) { Button("删除",role:.destructive) { let item = deleting; deleting = .null; Task { do { _ = try await session.api("memories/"+item.id,method:"DELETE",body:["expected_version":.int(item.version)]); revision += 1 } catch { resource.error = NativeSession.readable(error) } } } }
    }
}

private struct NativeMemoryForm: View {
    @EnvironmentObject private var session:NativeSession
    let existing:NativeJSON
    let onSave:()->Void
    @State private var content = ""
    @State private var category = "other"
    var body: some View { Form {
        Picker("分类",selection:$category) { Text("长期目标").tag("long_term_goal"); Text("可用器械").tag("equipment"); Text("训练时间").tag("schedule"); Text("过敏信息").tag("allergy"); Text("饮食偏好").tag("dietary_preference"); Text("动作限制").tag("exercise_limit"); Text("沟通偏好").tag("communication_preference"); Text("其他").tag("other") }
        TextField("你希望教练记住什么",text:$content,axis:.vertical)
        NativeActionButton(title:"保存记忆") { key in
            guard !content.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty else { throw NativeAPIError.message("请填写记忆内容。") }
            var body: [String:NativeJSON] = ["category":.string(category),"content":.string(content)]
            if !existing.isNull { body["expected_version"] = .int(existing.version) }
            _ = try await session.api("memories"+(existing.isNull ? "" : "/"+existing.id),method:existing.isNull ? "POST" : "PATCH",body:body,key:key); onSave()
        }
    }.navigationTitle("编辑记忆").onAppear { if !existing.isNull { content = existing["content"].text; category = existing["category"].text } } }
}
