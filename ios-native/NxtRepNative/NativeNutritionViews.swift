import SwiftUI

private enum NativeMealSlot: String, CaseIterable, Identifiable {
    case breakfast, lunch, dinner, snack, other

    var id: String { rawValue }
    var title: String { NativeLabels.meals[rawValue] ?? rawValue }
    var icon: String {
        switch self {
        case .breakfast: "sunrise.fill"
        case .lunch: "sun.max.fill"
        case .dinner: "moon.stars.fill"
        case .snack: "cup.and.saucer.fill"
        case .other: "fork.knife"
        }
    }

    var tint: Color {
        switch self {
        case .breakfast: NativeTheme.color(0xA05E18)
        case .lunch: NativeTheme.color(0xAD5738)
        case .dinner: NativeTheme.color(0x6351A4)
        case .snack: NativeTheme.color(0x9B4B6B)
        case .other: NativeTheme.accent
        }
    }
}

private struct NativeMealEntryIntent: Identifiable {
    var meal: NativeMealSlot? = nil
    var id: String { meal?.id ?? "manual" }
}

struct NativeNutritionView: View {
    @EnvironmentObject private var session: NativeSession
    @Environment(\.dynamicTypeSize) private var typeSize
    @StateObject private var resource = NativeResource()
    @StateObject private var weekly = NativeResource()
    @State private var entryIntent: NativeMealEntryIntent?
    @State private var revision = 0

    private var selectedDay: String { NativeDates.day(session.selectedDate) }
    private var summary: DailySummary? { session.summary?.date == selectedDay ? session.summary : nil }
    private var entries: [NativeJSON] {
        resource.value["for_date"].text == selectedDay ? resource.value["entries"].records : []
    }
    private var recentSummary: NativeJSON {
        weekly.value["for_date"].text == selectedDay ? weekly.value["summary"] : .null
    }
    private var tileColumns: [GridItem] {
        Array(repeating: GridItem(.flexible(), spacing: 8), count: typeSize >= .xLarge ? 3 : 5)
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                dayPicker
                NativeErrorText(message: session.error ?? resource.error ?? weekly.error)
                NativeDailyNutritionCard(summary: summary, showTargets: true)
                quickActions
                foodTools
                mealHistory
                if !recentSummary.isNull { weeklyCard }
            }
            .nativePage()
        }
        .background(NativeTheme.background)
        .navigationTitle("饮食")
        .navigationBarTitleDisplayMode(.inline)
        .task(id: "\(selectedDay)|\(revision)") { await load() }
        .refreshable { await load() }
        .sheet(item: $entryIntent) { intent in
            NavigationStack {
                NativeMealEditor(initialMeal: intent.meal?.id) { revision += 1 }
            }
            .environmentObject(session)
        }
    }

    private var dayPicker: some View {
        HStack(spacing: 10) {
            Image(systemName: "calendar")
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(NativeTheme.accent)
                .accessibilityHidden(true)
            DatePicker("记录日期", selection: $session.selectedDate, displayedComponents: .date)
                .labelsHidden()
                .datePickerStyle(.compact)
                .environment(\.timeZone, NativeDates.china)
            Spacer(minLength: 0)
            if selectedDay != NativeDates.day() {
                Button("回到今天") { session.selectedDate = .now }
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(NativeTheme.accent)
                    .frame(minHeight: 44)
            }
        }
    }

    private var quickActions: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("快捷记录").font(.headline).accessibilityAddTraits(.isHeader)
            LazyVGrid(columns: tileColumns, spacing: 8) {
                NavigationLink { NativeMeasurementForm(onSave: {}) } label: {
                    NativeIconTile(title: "体重", icon: "scalemass.fill", tint: NativeTheme.color(0x375E93))
                }
                .accessibilityLabel("记录体重")

                ForEach([NativeMealSlot.breakfast, .lunch, .dinner]) { meal in
                    Button { entryIntent = NativeMealEntryIntent(meal: meal) } label: {
                        NativeIconTile(title: meal.title, icon: meal.icon, tint: meal.tint)
                    }
                    .accessibilityLabel("记录\(meal.title)")
                }

                NavigationLink { NativeWaterView() } label: {
                    NativeIconTile(title: "饮水", icon: "drop.fill", tint: NutrientKind.water.labelColor)
                }
                .accessibilityLabel("饮水记录")
            }
            .buttonStyle(PreviewPressStyle())
        }
    }

    private var foodTools: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("饮食工具").font(.headline).accessibilityAddTraits(.isHeader)
            LazyVGrid(columns: tileColumns, spacing: 8) {
                NavigationLink { NativeFoodLibrary() } label: {
                    NativeIconTile(title: "食品库", icon: "fork.knife", tint: NativeTheme.accent)
                }
                Button { entryIntent = NativeMealEntryIntent() } label: {
                    NativeIconTile(title: "手动记", icon: "square.and.pencil", tint: NativeTheme.accent)
                }
                .accessibilityLabel("手动记录饮食")
                NavigationLink { NativeNutritionPhotoView() } label: {
                    NativeIconTile(title: "拍照", icon: "camera.fill", tint: NativeTheme.accent)
                }
                .accessibilityLabel("拍照记一餐")
                NavigationLink { NativeRecentMeals() } label: {
                    NativeIconTile(title: "复制", icon: "doc.on.doc", tint: NativeTheme.accent)
                }
                .accessibilityLabel("复制最近餐食")
                NavigationLink { NativeNutritionTools() } label: {
                    NativeIconTile(title: "更多", icon: "ellipsis", tint: NativeTheme.accent)
                }
                .accessibilityLabel("更多饮食工具")
            }
            .buttonStyle(PreviewPressStyle())
        }
    }

    private var mealHistory: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("餐食记录").font(.headline).accessibilityAddTraits(.isHeader)
            if entries.isEmpty {
                if resource.loading || (resource.value["for_date"].text != selectedDay && resource.error == nil) {
                    ProgressView().frame(maxWidth: .infinity, minHeight: 56).accessibilityLabel("正在读取餐食")
                } else if resource.error == nil {
                    NativeCard {
                        Label("当天还没有餐食记录", systemImage: "fork.knife")
                            .font(.subheadline)
                            .foregroundStyle(NativeTheme.muted)
                    }
                }
            } else {
                ForEach(entries, id: \.id) { entry in
                    NavigationLink { NativeMealEditor(existing: entry) { revision += 1 } } label: {
                        NativeMealRow(entry: entry, showsDate: false, showsChevron: true)
                    }
                    .buttonStyle(PreviewPressStyle())
                }
            }
        }
    }

    private var weeklyCard: some View {
        NativeCard {
            DisclosureGroup {
                VStack(alignment: .leading, spacing: 8) {
                    Text("日均营养").font(.subheadline.weight(.semibold))
                    NativeNutrientValues(value: recentSummary["daily_average"])
                }
                .padding(.top, 12)
            } label: {
                HStack(spacing: 10) {
                    Image(systemName: "chart.bar.xaxis").foregroundStyle(NativeTheme.accent).accessibilityHidden(true)
                    VStack(alignment: .leading, spacing: 4) {
                        Text("最近七天").font(.subheadline.weight(.semibold)).foregroundStyle(NativeTheme.ink)
                        Text("\(recentSummary["recorded_days"].text) 天有记录 · \(recentSummary["total_entries"].text) 餐")
                            .font(.caption)
                            .foregroundStyle(NativeTheme.muted)
                    }
                }
            }
        }
    }

    private func load() async {
        let date = session.selectedDate
        let day = NativeDates.day(date)
        await session.reload()
        guard !Task.isCancelled, selectedDay == day else { return }
        await resource.load {
            let entries = try await session.api("nutrition/entries", query: ["date": day])
            return .object(["for_date": .string(day), "entries": entries])
        }
        guard !Task.isCancelled, selectedDay == day else { return }
        await weekly.load {
            let start = NativeDates.day(date.addingTimeInterval(-6 * 86_400))
            let summary = try await session.api("nutrition/weekly-summary", query: ["start_date": start])
            return .object(["for_date": .string(day), "summary": summary])
        }
    }
}

struct NativeMealRow: View {
    let entry: NativeJSON
    var showsDate = true
    var showsChevron = false

    private var meal: NativeMealSlot { NativeMealSlot(rawValue: entry["meal_type"].text) ?? .other }
    private var when: String {
        let raw = entry["eaten_at"].text
        guard !showsDate, let date = NativeDates.parse(raw) else { return NativeDates.display(raw) }
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "zh_CN")
        formatter.timeZone = NativeDates.china
        formatter.dateFormat = "HH:mm"
        return formatter.string(from: date)
    }

    var body: some View {
        NativeCard {
            HStack(alignment: .top, spacing: 10) {
                Image(systemName: meal.icon)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(meal.tint)
                    .frame(width: 36, height: 36)
                    .background(meal.tint.opacity(0.12), in: RoundedRectangle(cornerRadius: 11))
                    .accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 4) {
                    let names = entry["items"].values.map { $0["name"].text }.filter { !$0.isEmpty }
                    Text(names.isEmpty ? meal.title : names.joined(separator: "、"))
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(NativeTheme.ink)
                        .lineLimit(2)
                    Text("\(meal.title) · \(when)")
                        .font(.caption)
                        .foregroundStyle(NativeTheme.muted)
                }
                Spacer(minLength: 0)
                Text("\(entry["totals"]["kcal"].text) 千卡")
                    .font(.caption.weight(.semibold))
                    .monospacedDigit()
                    .foregroundStyle(AppTab.meals.tint)
                if showsChevron {
                    Image(systemName: "chevron.right").font(.caption2.weight(.semibold))
                        .foregroundStyle(NativeTheme.muted).accessibilityHidden(true)
                }
            }
            ViewThatFits(in: .horizontal) {
                HStack(spacing: 12) { macros }
                VStack(alignment: .leading, spacing: 6) { macros }
            }
        }
        .accessibilityElement(children: .combine)
    }

    @ViewBuilder private var macros: some View {
        macro(.carbs, key: "carbs_g")
        macro(.protein, key: "protein_g")
        macro(.fat, key: "fat_g")
    }

    private func macro(_ kind: NutrientKind, key: String) -> some View {
        Label {
            Text("\(kind.title) \(entry["totals"][key].text)g")
        } icon: {
            Circle().fill(kind.labelColor).frame(width: 5, height: 5).accessibilityHidden(true)
        }
        .font(.caption2.weight(.medium))
        .foregroundStyle(kind.labelColor)
    }
}

private struct NativeMealLine: Identifiable {
    let id = UUID()
    var versionID: NativeJSON = .null
    var name = ""
    var amount = "100"
    var basis = "100"
    var kcal = "0"
    var protein = "0"
    var carbs = "0"
    var fat = "0"
    var source = "user"
    var confidence = "confirmed"
    init() {}
    init(_ item: NativeJSON) {
        versionID = item["food_version_id"]; name = item["name"].text; amount = item["amount_g"].text
        basis = item["basis_amount_g"].text; kcal = item["kcal"].text; protein = item["protein_g"].text
        carbs = item["carbs_g"].text; fat = item["fat_g"].text
        source = item["source"].text; confidence = item["confidence"].text
    }
    func payload() throws -> NativeJSON {
        guard let grams = Double(amount), grams > 0 else { throw NativeAPIError.message("每项食品的份量必须大于 0。") }
        if !versionID.isNull { return .object(["food_version_id":versionID,"amount_g":.number(grams)]) }
        guard !name.trimmingCharacters(in:.whitespaces).isEmpty, let b = Double(basis), b > 0,
              let k = Double(kcal), let p = Double(protein), let c = Double(carbs), let f = Double(fat),
              [k,p,c,f].allSatisfy({$0 >= 0}) else { throw NativeAPIError.message("请填写食品名称、基准份量和有效营养数值。") }
        return .object(["food_version_id":.null,"name":.string(name),"amount_g":.number(grams),"basis_amount_g":.number(b),"kcal":.number(k),"protein_g":.number(p),"carbs_g":.number(c),"fat_g":.number(f),"source":.string(source),"confidence":.string(confidence)])
    }
    var draft:NativeJSON { .object(["food_version_id":versionID,"name":.string(name),"amount_g":.string(amount),"basis_amount_g":.string(basis),"kcal":.string(kcal),"protein_g":.string(protein),"carbs_g":.string(carbs),"fat_g":.string(fat),"source":.string(source),"confidence":.string(confidence)]) }
}

struct NativeMealEditor: View {
    @EnvironmentObject private var session: NativeSession
    @Environment(\.dismiss) private var dismiss
    let existing: NativeJSON
    let initialMeal: String?
    let onSave: () -> Void
    @State private var lines = [NativeMealLine()]
    @State private var meal: String
    @State private var eatenAt = Date()
    @State private var flexible = false
    @State private var notes = ""
    @State private var deleteDialog = false
    @State private var mutationError: String?

    init(existing: NativeJSON = .null, initialMeal: String? = nil, onSave: @escaping () -> Void) {
        self.existing = existing
        self.initialMeal = initialMeal
        self.onSave = onSave
        _meal = State(initialValue: existing.isNull ? initialMeal ?? "lunch" : existing["meal_type"].text)
    }

    private var draftKey: String {
        if !existing.isNull { return "nutrition-manual-" + existing.id }
        let base = "nutrition-manual-" + NativeDates.day(session.selectedDate)
        return base + (initialMeal.map { "-" + $0 } ?? "")
    }

    private var draftTitle: String {
        initialMeal.flatMap { NativeLabels.meals[$0] }.map { "记录" + $0 } ?? "手动饮食记录"
    }

    var body: some View {
        Form {
            Section("进食信息") {
                NativeMealPicker(selection:$meal)
                if existing.isNull { DatePicker("进食时间",selection:$eatenAt) }
                else { Text(NativeDates.display(existing["eaten_at"].text)) }
                Toggle("灵活餐",isOn:$flexible)
                NativeField(title:"备注",text:$notes)
            }
            ForEach($lines) { $line in
                Section(line.name.isEmpty ? "食品" : line.name) {
                    NativeField(title:"名称",text:$line.name).disabled(!line.versionID.isNull)
                    NativeField(title:"食用份量（克）",text:$line.amount,keyboard:.decimalPad)
                    if line.versionID.isNull {
                        NativeField(title:"以下营养数值对应的基准份量（克）",text:$line.basis,keyboard:.decimalPad)
                        NativeField(title:"热量（千卡）",text:$line.kcal,keyboard:.decimalPad)
                        NativeField(title:"蛋白质（克）",text:$line.protein,keyboard:.decimalPad)
                        NativeField(title:"碳水（克）",text:$line.carbs,keyboard:.decimalPad)
                        NativeField(title:"脂肪（克）",text:$line.fat,keyboard:.decimalPad)
                    }
                    if lines.count > 1 { Button("移除此项",role:.destructive) { lines.removeAll { $0.id == line.id } } }
                }
            }
            Button("添加一项食品") { lines.append(NativeMealLine()) }
            NativeActionButton(title:"保存饮食记录") { key in
                var body: [String:NativeJSON] = ["meal_type":.string(meal),"items":.array(try lines.map { try $0.payload() }),"is_flexible_meal":.bool(flexible),"notes":notes.isEmpty ? .null : .string(notes)]
                if existing.isNull { body["eaten_at"] = .string(NativeDates.timestamp(eatenAt)) }
                else { body["expected_version"] = .int(existing.version); body["reason"] = .string("用户在 iPhone 编辑饮食记录") }
                _ = try await session.api(existing.isNull ? "nutrition/entries" : "nutrition/entries/" + existing.id,method:existing.isNull ? "POST" : "PATCH",body:body,key:key,draftKey:existing.isNull ? draftKey : nil)
                await session.reload(); onSave(); dismiss()
            }
            if !existing.isNull { Button("删除这条饮食记录",role:.destructive) { deleteDialog = true } }
            NativeErrorText(message:mutationError)
        }
        .navigationTitle(existing.isNull ? draftTitle : "编辑饮食")
        .toolbar { ToolbarItem(placement:.cancellationAction) { Button("取消") { dismiss() } } }
        .onAppear {
            eatenAt = NativeDates.day(session.selectedDate) == NativeDates.day() ? .now : session.selectedDate
            if !existing.isNull { lines = existing["items"].values.map(NativeMealLine.init); meal = existing["meal_type"].text; flexible = existing["is_flexible_meal"].flag; notes = existing["notes"].text }
        }
        .nativeDraft(draftKey,label:draftTitle,value:.object(["lines":.array(lines.map(\.draft)),"meal":.string(meal),"time":.string(NativeDates.timestamp(eatenAt)),"flexible":.bool(flexible),"notes":.string(notes)])) { value in
            if existing.isNull { lines = value["lines"].values.map(NativeMealLine.init); meal = value["meal"].text; eatenAt = NativeDates.parse(value["time"].text) ?? .now; flexible = value["flexible"].flag; notes = value["notes"].text }
        }
        .confirmationDialog("删除这条饮食记录？",isPresented:$deleteDialog,titleVisibility:.visible) {
            Button("确认删除",role:.destructive) { Task {
                do {
                    let submitted = try await session.api("nutrition/entries/" + existing.id,method:"DELETE",body:["expected_version":.int(existing.version),"reason":.string("用户在 iPhone 删除饮食记录")])
                    _ = try await session.approve(submitted["confirmation_id"].text)
                    onSave(); dismiss()
                } catch { mutationError = NativeSession.readable(error) }
            } }
        }
    }
}

struct NativeWaterView: View {
    @EnvironmentObject private var session: NativeSession
    @StateObject private var resource = NativeResource()
    @State private var amount = "250"
    @State private var consumedAt = Date()
    @State private var revision = 0
    @State private var deleting: NativeJSON = .null
    var body: some View {
        Form {
            Section("记录饮水") {
                NativeField(title:"饮水量（毫升，1–5000）",text:$amount,keyboard:.numberPad)
                DatePicker("饮水时间",selection:$consumedAt)
                HStack { ForEach([150,250,350,500],id:\.self) { ml in Button("\(ml)") { amount = String(ml) }.buttonStyle(.bordered) } }
                NativeActionButton(title:"保存饮水记录") { key in
                    guard let ml = Int(amount), (1...5000).contains(ml) else { throw NativeAPIError.message("饮水量应为 1–5000 毫升的整数。") }
                    _ = try await session.api("nutrition/water",method:"POST",body:["amount_ml":.int(ml),"consumed_at":.string(NativeDates.timestamp(consumedAt))],key:key,draftKey:"water-"+NativeDates.day(session.selectedDate))
                    revision += 1; await session.reload()
                }
            }
            Section("\(NativeDates.day(session.selectedDate)) · \(resource.value.records.reduce(0) {$0+$1["amount_ml"].integer}) 毫升") {
                NativeErrorText(message:resource.error)
                ForEach(resource.value.records,id:\.id) { entry in
                    HStack {
                        VStack(alignment:.leading) { Text("\(entry["amount_ml"].integer) 毫升"); Text(NativeDates.display(entry["consumed_at"].text)).font(.caption).foregroundStyle(NativeTheme.muted) }
                        Spacer()
                        Button(role:.destructive) { deleting = entry } label: { Image(systemName:"trash") }.buttonStyle(.borderless)
                    }
                }
                if resource.value.records.isEmpty { Text("当天还没有饮水记录").foregroundStyle(NativeTheme.muted) }
            }
        }.navigationTitle("饮水记录")
        .onAppear { consumedAt = session.selectedDate }
        .nativeDraft("water-"+NativeDates.day(session.selectedDate),label:"饮水记录",value:.object(["amount":.string(amount),"time":.string(NativeDates.timestamp(consumedAt))])) { value in amount = value["amount"].text; consumedAt = NativeDates.parse(value["time"].text) ?? .now }
        .task(id:revision) { await resource.load { try await session.api("nutrition/water",query:["date":NativeDates.day(session.selectedDate)]) } }
        .confirmationDialog("删除这条饮水记录？",isPresented:Binding(get:{!deleting.isNull},set:{if !$0 { deleting = .null }}),titleVisibility:.visible) {
            Button("删除",role:.destructive) { let id = deleting.id; Task { do { _ = try await session.api("nutrition/water/"+id,method:"DELETE"); revision += 1; await session.reload() } catch { resource.error = NativeSession.readable(error) } }; deleting = .null }
        }
    }
}

struct NativeRecentMeals: View {
    @EnvironmentObject private var session: NativeSession
    @StateObject private var resource = NativeResource()
    var body: some View {
        ScrollView {
            VStack(alignment:.leading,spacing:12) {
                NativeErrorText(message:resource.error)
                ForEach(resource.value.records,id:\.id) { entry in NavigationLink { NativeCopyMeal(entry:entry) } label:{ NativeMealRow(entry:entry) }.buttonStyle(.plain) }
                if resource.value.records.isEmpty && !resource.loading { ContentUnavailableView("没有最近餐食",systemImage:"doc.on.doc") }
            }.nativePage()
        }.navigationTitle("复制最近餐食")
            .task { await resource.load { try await session.api("nutrition/entries/recent",query:["date":NativeDates.day(session.selectedDate)]) } }
    }
}

struct NativeCopyMeal: View {
    @EnvironmentObject private var session: NativeSession
    @Environment(\.dismiss) private var dismiss
    let entry: NativeJSON
    @State private var date = Date()
    @State private var meal = "lunch"
    var body: some View {
        Form {
            NativeMealRow(entry:entry)
            DatePicker("复制到",selection:$date)
            NativeMealPicker(selection:$meal)
            NativeActionButton(title:"确认复制") { key in
                _ = try await session.api("nutrition/entries/"+entry.id+"/copy",method:"POST",body:["expected_version":.int(entry.version),"meal_type":.string(meal),"eaten_at":.string(NativeDates.timestamp(date))],key:key)
                await session.reload(); dismiss()
            }
        }.navigationTitle("复制餐食").onAppear { date = session.selectedDate; meal = entry["meal_type"].text }
    }
}

struct NativeNutritionTools: View {
    @EnvironmentObject private var session: NativeSession
    @State private var text = ""
    @State private var meal = "lunch"
    @State private var draft: NativeJSON = .null
    @State private var adviceName = ""
    @State private var advice: NativeJSON = .null
    @State private var flexibleLabel = ""
    @StateObject private var flexible = NativeResource()
    @StateObject private var recipes = NativeResource()
    @State private var revision = 0
    var body: some View {
        Form {
            Section("文字记一餐") {
                NativeMealPicker(selection:$meal)
                TextField("例如：米饭 150 克、鸡胸肉 100 克",text:$text,axis:.vertical).lineLimit(3...7)
                NativeActionButton(title:"识别并生成待确认记录") { key in
                    draft = try await session.api("nutrition/entry-drafts:parse-text",method:"POST",body:["text":.string(text),"meal_type":.string(meal),"eaten_at":.string(NativeDates.timestamp(session.selectedDate)),"is_flexible_meal":.bool(false),"notes":.null],key:key)
                }
                if !draft.isNull {
                    NativeBusinessSummary(value:.array(draft["items"].values))
                    NativeNutrientValues(value:draft["totals"])
                    ForEach(draft["questions"].strings,id:\.self) { Text($0).foregroundStyle(.orange) }
                    ForEach(draft["missing_items"].strings,id:\.self) { Text("待补充："+$0).foregroundStyle(.orange) }
                    NativeActionButton(title:"确认保存这餐") { key in
                        let submitted = try await session.api("nutrition/entry-drafts/"+draft.id+"/submit",method:"POST",body:["expected_version":.int(draft.version)],key:key)
                        _ = try await session.approve(submitted["confirmation_id"].text)
                        draft = .null; text = ""
                    }
                }
            }
            Section("饮食建议") {
                NativeField(title:"想了解的食物",text:$adviceName)
                NativeActionButton(title:"获取建议") { _ in advice = try await session.api("nutrition/advice",method:"POST",body:["food_name":.string(adviceName),"amount_g":.null,"on_date":.string(NativeDates.day(session.selectedDate))]) }
                if !advice.isNull { Text(advice["recommendation"].text); ForEach(advice["cautions"].strings,id:\.self) { Text($0).font(.caption).foregroundStyle(.orange) } }
            }
            Section("灵活餐安排") {
                NativeField(title:"安排名称",text:$flexibleLabel)
                NativeActionButton(title:"添加到选中日期") { key in
                    _ = try await session.api("nutrition/flexible-meals",method:"POST",body:["scheduled_date":.string(NativeDates.day(session.selectedDate)),"label":.string(flexibleLabel),"notes":.null],key:key)
                    flexibleLabel = ""; revision += 1
                }
                NativeErrorText(message:flexible.error)
                ForEach(flexible.value.records,id:\.id) { item in LabeledContent(item["label"].text,value:item["scheduled_date"].text) }
            }
            Section("我的食谱") {
                NavigationLink("新增食谱") { NativeRecipeForm { revision += 1 } }
                NativeErrorText(message:recipes.error)
                ForEach(recipes.value.records,id:\.id) { item in
                    DisclosureGroup(item["name"].text+" · "+item["servings"].text+" 份") { NativeNutrientValues(value:item["totals"]) }
                }
            }
        }.navigationTitle("饮食工具")
            .nativeDraft("nutrition-tools",label:"文字饮食与工具",value:.object(["text":.string(text),"meal":.string(meal),"draft":draft,"advice":.string(adviceName),"flexible":.string(flexibleLabel)])) { v in text = v["text"].text; meal = v["meal"].text; draft = v["draft"]; adviceName = v["advice"].text; flexibleLabel = v["flexible"].text }
            .task(id:revision) {
                await flexible.load { try await session.api("nutrition/flexible-meals") }
                await recipes.load { try await session.api("recipes",query:["page":"1","page_size":"50"]) }
            }
    }
}

struct NativeRecipeForm: View {
    @EnvironmentObject private var session: NativeSession
    @Environment(\.dismiss) private var dismiss
    let onSave: () -> Void
    @State private var name = ""
    @State private var servings = "1"
    @State private var amount = "100"
    @State private var keyword = ""
    @State private var selected: NativeJSON = .null
    @StateObject private var foods = NativeResource()
    var body: some View {
        Form {
            NativeField(title:"食谱名称",text:$name)
            NativeField(title:"份数",text:$servings,keyboard:.decimalPad)
            NativeField(title:"搜索食品",text:$keyword)
            NativeErrorText(message:foods.error)
            ForEach(foods.value.records,id:\.id) { food in Button { selected = food } label: { HStack { Text(food["name"].text); Spacer(); if selected.id == food.id { Image(systemName:"checkmark") } } } }
            NativeField(title:"食品份量（克）",text:$amount,keyboard:.decimalPad)
            NativeActionButton(title:"保存食谱") { key in
                guard !selected.isNull, let count = Double(servings), count > 0, let grams = Double(amount), grams > 0 else { throw NativeAPIError.message("请选择食品并填写有效份量和份数。") }
                _ = try await session.api("recipes",method:"POST",body:["name":.string(name),"servings":.number(count),"items":.array([.object(["food_version_id":selected["food_version_id"],"amount_g":.number(grams)])]),"notes":.null],key:key)
                onSave(); dismiss()
            }
        }.navigationTitle("新增食谱")
            .task(id:keyword) { do { try await Task.sleep(for:.milliseconds(300)) } catch { return }; await foods.load { try await session.api("foods/search",query:["keyword":keyword,"page_size":"50"]) } }
    }
}
