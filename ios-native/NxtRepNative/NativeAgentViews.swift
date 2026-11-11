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
                            Text(activity).font(.subheadline).foregroundStyle(NativeTheme.muted)
                        }
                    }
                    ForEach(agent.confirmations, id: \.id) { card in
                        NativeConfirmationView(card: card) { try await agent.history() }.disabled(agent.busy)
                    }
                    NativeErrorText(message: agent.error)
                    if agent.needsVerification && !agent.busy {
                        Button("核实上次回复") { agent.verify() }
                            .buttonStyle(.borderedProminent)
                    }
                    if agent.needsVerification && !agent.pending["run_id"].text.isEmpty {
                        NativeActionButton(title: "取消本次处理") { _ in try await agent.cancel() }
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

                Button {
                    composerFocused = false
                    Task { await agent.send() }
                } label: {
                    Image(systemName: "arrow.up")
                        .font(.system(size: 17, weight: .semibold))
                        .frame(width: 44, height: 44)
                        .foregroundStyle(.white)
                        .background(agent.canSend ? NativeTheme.accent : NativeTheme.muted.opacity(0.45), in: Circle())
                }
                .accessibilityLabel("发送消息")
                .disabled(!agent.canSend)
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

struct NativeConfirmationView: View {
    @EnvironmentObject private var session:NativeSession
    let card:NativeJSON
    let onChange:() async throws -> Void
    @State private var decision:String?
    @State private var portions = false
    @State private var newPortions = ""
    private var id:String { card["confirmation_id"].text.isEmpty ? card.id : card["confirmation_id"].text }
    private var pending:Bool { card["status"].text == "pending" }
    var body: some View {
        NativeCard {
            Label(NativeLabels.status(card["status"].text),systemImage:"checklist").font(.headline)
            Text(card["impact"].text.isEmpty ? "请核对以下内容后决定是否执行。" : card["impact"].text)
            if !card["before"].isNull { DisclosureGroup("变更前") { NativeBusinessSummary(value:card["before"]) } }
            if !card["after"].isNull { DisclosureGroup("变更后") { NativeBusinessSummary(value:card["after"]) } }
            if !card["draft"].isNull { DisclosureGroup("查看草稿") { NativeBusinessSummary(value:card["draft"]) } }
            if pending {
                if card["operation_type"].text.contains("nutrition") {
                    DisclosureGroup("调整食品份量",isExpanded:$portions) {
                        Text("按食品顺序输入克数，用逗号分隔；仅修改需要调整的项。").font(.caption)
                        TextField("例如 150, 80",text:$newPortions).keyboardType(.numbersAndPunctuation)
                        NativeActionButton(title:"更新份量草稿") { _ in
                            let values = NativeLabels.split(newPortions).compactMap(Double.init)
                            guard !values.isEmpty,values.allSatisfy({$0 > 0}) else { throw NativeAPIError.message("请输入有效份量。") }
                            let changes = values.enumerated().map { NativeJSON.object(["item_index":.int($0.offset),"amount_g":.number($0.element)]) }
                            _ = try await session.api("nutrition/pending-entries/"+id+"/portions",method:"POST",body:["expected_version":.int(card.version),"changes":.array(changes)])
                            try await onChange()
                        }
                    }
                }
                HStack { Button("批准并执行") { decision = "approve" }.buttonStyle(.borderedProminent); Button("拒绝",role:.destructive) { decision = "reject" }.buttonStyle(.bordered) }
            }
        }.sheet(isPresented:Binding(get:{decision != nil},set:{if !$0 { decision = nil }})) {
            NavigationStack { VStack(spacing:20) {
                Text(decision == "approve" ? "确认执行上述改动？" : "拒绝这份确认单？").font(.title3.bold())
                Text(card["impact"].text)
                NativeActionButton(title:decision == "approve" ? "确认执行" : "确认拒绝") { _ in
                    let action = decision ?? "reject"
                    let detail = try await session.api("confirmations/"+id)
                    guard detail["status"].text == "pending",detail.version == card.version else { try await onChange(); throw NativeAPIError.message("确认单状态已更新，请返回重新核对。") }
                    var body: [String:NativeJSON] = ["expected_version":.int(card.version)]
                    if action == "reject" { body["reason"] = .string("用户在 iPhone 拒绝") }
                    let result = try await session.api("confirmations/"+id+"/"+action,method:"POST",body:body,key:NativeIDs.stable("confirmation:"+action+":"+id+":"+String(card.version)))
                    guard result.id == id,result.version > card.version,result["status"].text == (action == "approve" ? "succeeded" : "rejected") else { throw NativeAPIError.message("执行结果尚未确认，请重新读取确认单状态。") }
                    try await onChange(); await session.reload(); decision = nil
                }
                Button("返回") { decision = nil }
            }.padding(24).navigationTitle("核对确认单") }.presentationDetents([.medium,.large])
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
            NavigationLink("会话、草稿和确认记录") { NativeAgentDraftsView() }
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
        }.navigationTitle("草稿与确认").task { await resource.load { .array(try await session.allPages("agent/conversations",query:["status":"active"])) } }
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
            ForEach(resource.value["confirmation_cards"].values + resource.value["completed_cards"].values,id:\.id) { card in NativeConfirmationView(card:card) { revision += 1 } }
            if resource.value["confirmation_cards"].values.isEmpty { Text("没有待确认的改动").foregroundStyle(NativeTheme.muted) }
            ForEach(resource.value["resolved_counts"].fields.keys.sorted(),id:\.self) { key in Text(NativeLabels.status(key)+"："+resource.value["resolved_counts"][key].text).font(.caption) }
            NavigationLink("打开这段对话") { NativeCoachView(conversationID:id) }
        }.nativePage() }.navigationTitle("确认记录").task(id:revision) { await resource.load { try await session.api("agent/conversations/"+id+"/confirmations") } }
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
