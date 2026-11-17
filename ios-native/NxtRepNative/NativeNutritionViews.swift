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
    var kcal = ""
    var protein = ""
    var carbs = ""
    var fat = ""
    var source = "user_provided"
    var confidence = "confirmed"
    var assumptions = ""

    init() {}

    init(_ item: NativeJSON) {
        versionID = item["food_version_id"]
        name = item["name"].text
        amount = item["amount_g"].isNull ? item["basis_amount_g"].text : item["amount_g"].text
        basis = item["basis_amount_g"].text
        kcal = item["kcal"].text
        protein = item["protein_g"].text
        carbs = item["carbs_g"].text
        fat = item["fat_g"].text
        source = item["source"].text
        confidence = item["confidence"].text
        assumptions = item["estimate_assumptions"].text
    }

    var estimated: Bool { ["model_estimated", "vision_estimate"].contains(source) }
    var manual: Bool { versionID.isNull && !estimated }
    var legacyPlaceholder: Bool {
        manual && name.isEmpty && amount == "100" && basis == "100" && [kcal, carbs, protein, fat].allSatisfy { $0 == "0" }
    }

    private var basisValues: [Double]? {
        let values = [basis, kcal, carbs, protein, fat].compactMap(NativeQuantity.number)
        guard values.count == 5, values[0] > 0, values.allSatisfy({ $0 >= 0 }) else { return nil }
        return values
    }

    var total: [Double]? {
        guard let basisValues, let grams = NativeQuantity.number(amount), (0.001...99_999.999).contains(grams) else { return nil }
        let scaled = basisValues.dropFirst().map { $0 * grams / basisValues[0] }
        return scaled.allSatisfy(\.isFinite) ? scaled : nil
    }

    func payload() throws -> NativeJSON {
        guard let grams = NativeQuantity.number(amount), (0.001...99_999.999).contains(grams) else {
            throw NativeAPIError.message("请填写有效的食品份量。")
        }
        if !versionID.isNull {
            return .object(["food_version_id": versionID, "amount_g": .number(grams)])
        }
        let cleanName = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !cleanName.isEmpty, let values = basisValues else {
            throw NativeAPIError.message("请补全食品名称和包装营养数据。")
        }
        return .object([
            "food_version_id": .null, "name": .string(cleanName), "amount_g": .number(grams),
            "basis_amount_g": .number(values[0]), "kcal": .number(values[1]), "carbs_g": .number(values[2]),
            "protein_g": .number(values[3]), "fat_g": .number(values[4]), "source": .string(source),
            "confidence": .string(confidence), "estimate_assumptions": assumptions.isEmpty ? .null : .string(assumptions)
        ])
    }

    var draft: NativeJSON {
        .object([
            "food_version_id": versionID, "name": .string(name), "amount_g": .string(amount),
            "basis_amount_g": .string(basis), "kcal": .string(kcal), "protein_g": .string(protein),
            "carbs_g": .string(carbs), "fat_g": .string(fat), "source": .string(source),
            "confidence": .string(confidence), "estimate_assumptions": .string(assumptions)
        ])
    }
}

struct NativeMealEditor: View {
    @EnvironmentObject private var session: NativeSession
    @Environment(\.dismiss) private var dismiss
    let existing: NativeJSON
    let initialMeal: String?
    let onSave: () -> Void
    @State private var lines: [NativeMealLine] = []
    @State private var meal: String
    @State private var eatenAt = Date()
    @State private var flexible = false
    @State private var notes = ""
    @State private var showLibrary = false
    @State private var showPhoto = false
    @State private var initialized = false
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
        initialMeal.flatMap { NativeLabels.meals[$0] }.map { "记" + $0 } ?? "记一餐"
    }

    private var totals: [Double]? {
        let values = lines.compactMap(\.total)
        guard !values.isEmpty, values.count == lines.count else { return nil }
        let result = (0..<4).map { index in values.reduce(0.0) { $0 + $1[index] } }
        return result.allSatisfy(\.isFinite) ? result : nil
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                mealSelector
                HStack(spacing: 10) {
                    Button { showLibrary = true } label: {
                        NativeIconTile(title: "从食品库选择", icon: "plus.circle.fill", tint: AppTab.meals.tint)
                    }
                    Button { showPhoto = true } label: {
                        NativeIconTile(title: "AI 拍照估算", icon: "camera.fill", tint: NutrientKind.protein.labelColor)
                    }
                }
                .buttonStyle(PreviewPressStyle())
                if let totals { NativeMealTotalCard(values: totals, estimated: lines.contains(where: \.estimated)) }
                ForEach($lines) { $line in
                    let id = line.id
                    NativeMealPortionCard(line: $line) { lines.removeAll { $0.id == id } }
                }
                optionalDetails
                NativeErrorText(message: mutationError)
            }.nativePage()
        }
        .background(NativeTheme.background)
        .scrollDismissesKeyboard(.interactively)
        .safeAreaInset(edge: .bottom, spacing: 0) {
            NativeActionButton(title: "保存这餐", action: save)
                .disabled(totals == nil || lines.contains { $0.name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty })
                .padding(.horizontal, 18).padding(.vertical, 7).background(.regularMaterial)
        }
        .navigationTitle(existing.isNull ? draftTitle : "编辑这餐")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar { ToolbarItem(placement: .cancellationAction) { Button("取消") { dismiss() } } }
        .onAppear(perform: prepare)
        .nativeDraft(draftKey, label: draftTitle, value: snapshot, restore: restore)
        .sheet(isPresented: $showLibrary) {
            NavigationStack {
                NativeFoodLibrary(onSelect: { food in
                    lines.append(NativeMealLine(food))
                    showLibrary = false
                })
                .toolbar { ToolbarItem(placement: .cancellationAction) { Button("关闭") { showLibrary = false } } }
            }.environmentObject(session)
        }
        .sheet(isPresented: $showPhoto) {
            NavigationStack {
                NativeNutritionPhotoView(initialMeal: meal, initialDate: eatenAt) { items in
                    lines += items.map(NativeMealLine.init)
                    showPhoto = false
                }
                .toolbar { ToolbarItem(placement: .cancellationAction) { Button("关闭") { showPhoto = false } } }
            }.environmentObject(session)
        }
        .confirmationDialog("删除这条饮食记录？", isPresented: $deleteDialog, titleVisibility: .visible) {
            Button("确认删除", role: .destructive) { Task { await deleteMeal() } }
        }
    }

    private var mealSelector: some View {
        ScrollView(.horizontal) {
            HStack(spacing: 8) {
                ForEach(NativeMealSlot.allCases) { slot in
                    Button { meal = slot.id } label: {
                        Label(slot.title, systemImage: slot.icon)
                            .font(.subheadline.weight(.semibold))
                            .foregroundStyle(meal == slot.id ? .white : slot.tint)
                            .padding(.horizontal, 12).frame(minHeight: 44)
                            .background(meal == slot.id ? slot.tint : slot.tint.opacity(0.10), in: Capsule())
                    }
                    .buttonStyle(PreviewPressStyle())
                    .accessibilityAddTraits(meal == slot.id ? .isSelected : [])
                }
            }
        }
        .scrollIndicators(.hidden)
    }

    private var optionalDetails: some View {
        NativeCard {
            DisclosureGroup("时间与更多选项") {
                VStack(alignment: .leading, spacing: 12) {
                    if existing.isNull {
                        DatePicker("进食时间", selection: $eatenAt).environment(\.timeZone, NativeDates.china)
                    } else {
                        LabeledContent("进食时间", value: NativeDates.display(existing["eaten_at"].text))
                    }
                    Toggle("灵活餐", isOn: $flexible)
                    NativeField(title: "备注", text: $notes)
                    Button("按包装营养表手动添加") { lines.append(NativeMealLine()) }.frame(minHeight: 44)
                    if !existing.isNull {
                        Button("删除这条饮食记录", role: .destructive) { deleteDialog = true }.frame(minHeight: 44)
                    }
                }.padding(.top, 10)
            }.font(.subheadline)
        }
    }

    private func prepare() {
        guard !initialized else { return }
        initialized = true
        if existing.isNull {
            eatenAt = NativeDates.day(session.selectedDate) == NativeDates.day() ? .now : session.selectedDate
        } else {
            lines = existing["items"].values.map(NativeMealLine.init)
            meal = existing["meal_type"].text
            eatenAt = NativeDates.parse(existing["eaten_at"].text) ?? .now
            flexible = existing["is_flexible_meal"].flag
            notes = existing["notes"].text
        }
    }

    private func restore(_ value: NativeJSON) {
        guard existing.isNull else { return }
        initialized = true
        lines = value["lines"].values.map(NativeMealLine.init).filter { !$0.legacyPlaceholder }
        meal = value["meal"].text
        eatenAt = NativeDates.parse(value["time"].text) ?? .now
        flexible = value["flexible"].flag
        notes = value["notes"].text
    }

    private var snapshot: NativeJSON {
        .object(["lines": .array(lines.map(\.draft)), "meal": .string(meal), "time": .string(NativeDates.timestamp(eatenAt)),
                 "flexible": .bool(flexible), "notes": .string(notes)])
    }

    private func save(_ key: String) async throws {
        let creating = existing.isNull
        var body: [String: NativeJSON] = [
            "meal_type": .string(meal), "items": .array(try lines.map { try $0.payload() }),
            "is_flexible_meal": .bool(flexible), "notes": notes.isEmpty ? .null : .string(notes)
        ]
        if creating {
            body["eaten_at"] = .string(NativeDates.timestamp(eatenAt))
        } else {
            body["expected_version"] = .int(existing.version)
            body["reason"] = .string("用户在 iPhone 编辑饮食记录")
        }
        _ = try await session.api(creating ? "nutrition/entries" : "nutrition/entries/" + existing.id,
                                  method: creating ? "POST" : "PATCH", body: body, key: key, draftKey: creating ? draftKey : nil)
        await session.reload()
        onSave()
        dismiss()
    }

    private func deleteMeal() async {
        do {
            let submitted = try await session.api("nutrition/entries/" + existing.id, method: "DELETE", body: [
                "expected_version": .int(existing.version), "reason": .string("用户在 iPhone 删除饮食记录")
            ])
            _ = try await session.approve(submitted["confirmation_id"].text)
            await session.reload()
            onSave()
            dismiss()
        } catch { mutationError = NativeSession.readable(error) }
    }
}

private struct NativeMealPortionCard: View {
    @Binding var line: NativeMealLine
    let remove: () -> Void

    var body: some View {
        NativeCard {
            HStack(spacing: 10) {
                NativeActionIcon(symbol: NativeFoodCategory.icon(line.name), tint: AppTab.meals.tint)
                VStack(alignment: .leading, spacing: 4) {
                    Text(line.name.isEmpty ? "手动添加的食品" : line.name).font(.headline)
                    if let calories = line.total?.first {
                        Text((line.estimated ? "AI 估算约 " : "") + NativeQuantity.format(calories, decimals: 1) + " 千卡")
                            .font(.caption).foregroundStyle(NativeTheme.muted)
                    }
                }
                Spacer(minLength: 0)
                Button(role: .destructive, action: remove) {
                    Image(systemName: "xmark.circle.fill").font(.title3).foregroundStyle(NativeTheme.muted)
                        .frame(width: 44, height: 44)
                }
                .buttonStyle(.plain)
                .accessibilityLabel("移除" + (line.name.isEmpty ? "这项食品" : line.name))
            }
            if line.manual {
                NativeField(title: "食品名称", text: $line.name)
                DisclosureGroup("包装营养数据") {
                    VStack(alignment: .leading, spacing: 8) {
                        NativeField(title: "基准份量（克）", text: $line.basis, keyboard: .decimalPad)
                        NativeField(title: "热量（千卡）", text: $line.kcal, keyboard: .decimalPad)
                        NativeField(title: "碳水（克）", text: $line.carbs, keyboard: .decimalPad)
                        NativeField(title: "蛋白质（克）", text: $line.protein, keyboard: .decimalPad)
                        NativeField(title: "脂肪（克）", text: $line.fat, keyboard: .decimalPad)
                    }.padding(.top, 8)
                }.font(.subheadline)
            }
            HStack {
                Text("吃了多少").font(.subheadline.weight(.medium))
                Spacer()
                TextField("份量", text: $line.amount).keyboardType(.decimalPad)
                    .multilineTextAlignment(.trailing).font(.title3.bold()).monospacedDigit()
                    .frame(width: 84, minHeight: 44)
                    .accessibilityLabel(line.name + "份量")
                Text("克").font(.subheadline).foregroundStyle(NativeTheme.muted)
            }
            NativeQuantityChoices(values: [50, 100, 150, 200], unit: "克", value: $line.amount, tint: AppTab.meals.tint)
        }
    }
}

struct NativeMealTotalCard: View {
    let values: [Double]
    let estimated: Bool

    var body: some View {
        NativeCard {
            HStack(spacing: 10) {
                NativeActionIcon(symbol: "flame.fill", tint: NutrientKind.carbs.labelColor, size: 42)
                VStack(alignment: .leading, spacing: 2) {
                    Text(estimated ? "这餐约" : "这餐合计").font(.caption).foregroundStyle(NativeTheme.muted)
                    Text(NativeQuantity.format(values[0], decimals: 1) + " 千卡")
                        .font(.system(.title2, design: .rounded, weight: .bold)).monospacedDigit()
                }
            }
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 78), spacing: 8)], spacing: 8) {
                macro(.carbs, value: values[1])
                macro(.protein, value: values[2])
                macro(.fat, value: values[3])
            }
        }
    }

    private func macro(_ kind: NutrientKind, value: Double) -> some View {
        VStack(spacing: 2) {
            Text(kind.title).font(.caption)
            Text(NativeQuantity.format(value, decimals: 1) + " 克").font(.footnote.weight(.semibold)).monospacedDigit()
        }
        .foregroundStyle(kind.labelColor)
        .frame(maxWidth: .infinity)
        .padding(.vertical, 7)
        .background(kind.color.opacity(0.12), in: RoundedRectangle(cornerRadius: 10))
        .accessibilityElement(children: .combine)
    }
}

struct NativeWaterView: View {
    @EnvironmentObject private var session: NativeSession
    @StateObject private var resource = NativeResource()
    @State private var amount = "250"
    @State private var consumedAt = Date()
    @State private var revision = 0
    @State private var deleting: NativeJSON = .null
    @State private var initialized = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                NativeCard {
                    HStack {
                        NativeActionIcon(symbol: "drop.fill", tint: NutrientKind.water.labelColor, size: 46)
                        VStack(alignment: .leading, spacing: 4) {
                            Text("喝了多少？").font(.headline)
                            Text("选择常用杯量，或输入毫升数。").font(.caption).foregroundStyle(NativeTheme.muted)
                        }
                    }
                    NativeQuantityChoices(values: [150, 250, 350, 500], unit: "毫升", value: $amount, tint: NutrientKind.water.labelColor)
                    HStack {
                        Text("饮水量").font(.subheadline)
                        Spacer()
                        TextField("毫升", text: $amount).keyboardType(.numberPad)
                            .multilineTextAlignment(.trailing).font(.title2.bold()).monospacedDigit()
                            .frame(width: 90, minHeight: 44).accessibilityLabel("饮水量，毫升")
                        Text("毫升").font(.subheadline).foregroundStyle(NativeTheme.muted)
                    }
                    DisclosureGroup("饮水时间") {
                        DatePicker("饮水时间", selection: $consumedAt).environment(\.timeZone, NativeDates.china)
                    }.font(.subheadline)
                    NativeActionButton(title: "记录 \(Int(amount).map { "\($0) 毫升" } ?? "饮水")") { key in
                        guard let ml = Int(amount), (1...5000).contains(ml) else { throw NativeAPIError.message("饮水量应为 1–5000 毫升的整数。") }
                        _ = try await session.api("nutrition/water", method: "POST", body: [
                            "amount_ml": .int(ml), "consumed_at": .string(NativeDates.timestamp(consumedAt))
                        ], key: key, draftKey: draftKey)
                        revision += 1
                        await session.reload()
                    }
                }
                NativeCard {
                    Text("当日饮水 · \(resource.value.records.reduce(0) { $0 + $1["amount_ml"].integer }) 毫升").font(.headline)
                    NativeErrorText(message: resource.error)
                    ForEach(resource.value.records, id: \.id) { entry in
                        HStack {
                            VStack(alignment: .leading, spacing: 4) {
                                Text("\(entry["amount_ml"].integer) 毫升").font(.subheadline.weight(.semibold))
                                Text(NativeDates.display(entry["consumed_at"].text)).font(.caption).foregroundStyle(NativeTheme.muted)
                            }
                            Spacer()
                            Button(role: .destructive) { deleting = entry } label: {
                                Image(systemName: "trash").frame(width: 44, height: 44)
                            }.buttonStyle(.plain).accessibilityLabel("删除这条饮水记录")
                        }
                    }
                    if resource.value.records.isEmpty && resource.loadedAt != nil {
                        Text("当天还没有饮水记录").font(.subheadline).foregroundStyle(NativeTheme.muted)
                    }
                }
            }.nativePage()
        }
        .background(NativeTheme.background)
        .scrollDismissesKeyboard(.interactively)
        .navigationTitle("记饮水").navigationBarTitleDisplayMode(.inline)
        .onAppear {
            guard !initialized else { return }
            initialized = true
            consumedAt = NativeDates.day(session.selectedDate) == NativeDates.day() ? .now : session.selectedDate
        }
        .nativeDraft(draftKey,label:"饮水记录",value:.object(["amount":.string(amount),"time":.string(NativeDates.timestamp(consumedAt))])) { value in
            initialized = true
            amount = value["amount"].text
            consumedAt = NativeDates.parse(value["time"].text) ?? .now
        }
        .task(id:revision) { await resource.load { try await session.api("nutrition/water",query:["date":NativeDates.day(session.selectedDate)]) } }
        .confirmationDialog("删除这条饮水记录？",isPresented:Binding(get:{!deleting.isNull},set:{if !$0 { deleting = .null }}),titleVisibility:.visible) {
            Button("删除",role:.destructive) { let id = deleting.id; Task { do { _ = try await session.api("nutrition/water/"+id,method:"DELETE"); revision += 1; await session.reload() } catch { resource.error = NativeSession.readable(error) } }; deleting = .null }
        }
    }

    private var draftKey: String { "water-" + NativeDates.day(session.selectedDate) }
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
