import SwiftUI

struct NativeNutritionView: View {
    @EnvironmentObject private var session: NativeSession
    @StateObject private var resource = NativeResource()
    @State private var weekly: NativeJSON = .null
    @State private var create = false
    @State private var revision = 0
    var body: some View {
        ScrollView {
            VStack(alignment:.leading, spacing:14) {
                NativeDayPicker()
                NativeErrorText(message:resource.error)
                if let summary = session.summary {
                    NativeCard {
                        Text("当日营养").font(.headline)
                        NativeNutrientValues(value:.object(["kcal":.number(summary.consumed.kcal.value),"carbs_g":.number(summary.consumed.carbsG.value),"protein_g":.number(summary.consumed.proteinG.value),"fat_g":.number(summary.consumed.fatG.value)]))
                        Text("饮水 \(summary.waterMl) 毫升").foregroundStyle(NutrientKind.water.labelColor)
                    }
                }
                LazyVGrid(columns:[GridItem(.flexible()),GridItem(.flexible())],spacing:10) {
                    NavigationLink { NativeFoodLibrary() } label: { Label("食品库",systemImage:"fork.knife") }
                    Button { create = true } label: { Label("手动记录",systemImage:"square.and.pencil") }
                    NavigationLink { NativeWaterView() } label: { Label("饮水记录",systemImage:"drop") }
                    NavigationLink { NativeRecentMeals() } label: { Label("复制最近餐食",systemImage:"doc.on.doc") }
                    NavigationLink { NativeNutritionPhotoView() } label: { Label("拍照记一餐",systemImage:"camera") }
                    NavigationLink { NativeNutritionTools() } label: { Label("饮食工具",systemImage:"wand.and.stars") }
                }.buttonStyle(.bordered).font(.subheadline)
                if resource.loading { ProgressView() }
                ForEach(["breakfast","lunch","dinner","snack","other"],id:\.self) { meal in
                    let entries = resource.value.records.filter { $0["meal_type"].text == meal }
                    if !entries.isEmpty {
                        Text(NativeLabels.meals[meal]!).font(.headline).padding(.top,4)
                        ForEach(entries,id:\.id) { entry in
                            NavigationLink { NativeMealEditor(existing:entry) { revision += 1 } } label: { NativeMealRow(entry:entry) }.buttonStyle(.plain)
                        }
                    }
                }
                if !resource.loading && resource.value.records.isEmpty { ContentUnavailableView("当天还没有饮食记录",systemImage:"fork.knife",description:Text("可从食品库选择、手动记录，或拍照估算后核对。")) }
                if !weekly.isNull {
                    NativeCard {
                        Text("最近七天").font(.headline)
                        Text("已记录 \(weekly["recorded_days"].text) 天 · \(weekly["total_entries"].text) 条饮食")
                        Text("日均营养").font(.subheadline.weight(.semibold))
                        NativeNutrientValues(value:weekly["daily_average"])
                    }
                }
            }.nativePage()
        }
        .navigationTitle("饮食").navigationBarTitleDisplayMode(.inline)
        .task(id:"\(NativeDates.day(session.selectedDate))|\(revision)") { await load() }
        .refreshable { await load() }
        .sheet(isPresented:$create) { NavigationStack { NativeMealEditor { revision += 1 } }.environmentObject(session) }
    }
    private func load() async {
        await session.reload()
        await resource.load { try await session.api("nutrition/entries",query:["date":NativeDates.day(session.selectedDate)]) }
        do { weekly = try await session.api("nutrition/weekly-summary",query:["start_date":NativeDates.day(session.selectedDate.addingTimeInterval(-6*86400))]) }
        catch { resource.error = NativeSession.readable(error) }
    }
}

struct NativeMealRow: View {
    let entry: NativeJSON
    var body: some View {
        NativeCard {
            HStack {
                Text(entry["items"].values.map { $0["name"].text }.joined(separator:"、")).font(.subheadline.weight(.semibold))
                Spacer()
                Text(entry["totals"]["kcal"].text + " 千卡").font(.subheadline).foregroundStyle(AppTab.meals.tint)
            }
            Text(NativeDates.display(entry["eaten_at"].text)).font(.caption).foregroundStyle(NativeTheme.muted)
            Text("碳水 \(entry["totals"]["carbs_g"].text)g · 蛋白质 \(entry["totals"]["protein_g"].text)g · 脂肪 \(entry["totals"]["fat_g"].text)g").font(.caption).foregroundStyle(NativeTheme.muted)
        }
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
}

struct NativeMealEditor: View {
    @EnvironmentObject private var session: NativeSession
    @Environment(\.dismiss) private var dismiss
    var existing: NativeJSON = .null
    let onSave: () -> Void
    @State private var lines = [NativeMealLine()]
    @State private var meal = "lunch"
    @State private var eatenAt = Date()
    @State private var flexible = false
    @State private var notes = ""
    @State private var deleteDialog = false
    @State private var mutationError: String?
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
                _ = try await session.api(existing.isNull ? "nutrition/entries" : "nutrition/entries/" + existing.id,method:existing.isNull ? "POST" : "PATCH",body:body,key:key)
                await session.reload(); onSave(); dismiss()
            }
            if !existing.isNull { Button("删除这条饮食记录",role:.destructive) { deleteDialog = true } }
            NativeErrorText(message:mutationError)
        }
        .navigationTitle(existing.isNull ? "手动记录" : "编辑饮食")
        .toolbar { ToolbarItem(placement:.cancellationAction) { Button("取消") { dismiss() } } }
        .onAppear {
            eatenAt = session.selectedDate
            if !existing.isNull { lines = existing["items"].values.map(NativeMealLine.init); meal = existing["meal_type"].text; flexible = existing["is_flexible_meal"].flag; notes = existing["notes"].text }
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
                    _ = try await session.api("nutrition/water",method:"POST",body:["amount_ml":.int(ml),"consumed_at":.string(NativeDates.timestamp(consumedAt))],key:key)
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
