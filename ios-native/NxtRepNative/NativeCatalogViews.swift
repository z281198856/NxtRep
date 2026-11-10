import SwiftUI

struct NativeFoodLibrary: View {
    @EnvironmentObject private var session: NativeSession
    @StateObject private var resource = NativeResource()
    @State private var keyword = ""
    @State private var frequent = false
    @State private var category = "全部"
    @State private var barcode = ""
    @State private var barcodeFood: NativeJSON = .null
    @State private var showCreate = false
    @State private var revision = 0
    private let categories = ["全部", "蛋白质", "主食", "蔬菜", "水果", "乳品", "饮品", "加餐"]

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                Picker("食品来源", selection: $frequent) { Text("全部食品").tag(false); Text("常用食品").tag(true) }.pickerStyle(.segmented)
                TextField("搜索食品或品牌", text: $keyword).textFieldStyle(.roundedBorder).submitLabel(.search)
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack { ForEach(categories, id: \.self) { name in
                        Button(name) { category = name }.buttonStyle(.bordered).tint(category == name ? NativeTheme.accent : .secondary)
                    } }
                }
                DisclosureGroup("按条码查询") {
                    NativeField(title: "食品包装条码", text: $barcode, keyboard: .asciiCapable)
                    NativeActionButton(title: "查询条码") { _ in barcodeFood = try await session.api("foods/barcodes/" + barcode.trimmingCharacters(in: .whitespaces)) }
                    if !barcodeFood.isNull { foodLink(barcodeFood) }
                }
                NativeErrorText(message: resource.error)
                if resource.loading { ProgressView("正在读取食品库…") }
                let items = resource.value.records.filter { category == "全部" || NativeFoodCategory.of($0["name"].text) == category }
                Text("\(items.count) 项食品").font(.caption).foregroundStyle(NativeTheme.muted)
                LazyVStack(spacing: 10) { ForEach(items, id: \.id) { foodLink($0) } }
                if !resource.loading && items.isEmpty { ContentUnavailableView("没有找到食品", systemImage: "fork.knife", description: Text("换个关键词，或添加自定义食品。")) }
                Button("添加自定义食品") { showCreate = true }.frame(minHeight: 44)
            }.nativePage()
        }
        .navigationTitle("食品库").navigationBarTitleDisplayMode(.inline)
        .task(id: "\(keyword)|\(frequent)|\(revision)") {
            do { try await Task.sleep(for: .milliseconds(300)) } catch { return }
            await resource.load {
                if frequent {
                    let items = try await session.api("foods/frequent", query: ["limit":"10"])
                    return .array(items.records.filter { keyword.isEmpty || ($0["name"].text + $0["brand"].text).localizedCaseInsensitiveContains(keyword) })
                }
                return .array(try await session.allPages("foods/search", query: ["keyword":keyword.trimmingCharacters(in: .whitespacesAndNewlines)]))
            }
        }
        .refreshable { revision += 1 }
        .sheet(isPresented: $showCreate) { NavigationStack { NativeCustomFoodForm { revision += 1 } }.environmentObject(session) }
    }

    private func foodLink(_ food: NativeJSON) -> some View {
        NavigationLink { NativeFoodDetail(food: food) } label: {
            NativeCard {
                HStack {
                    Image(systemName: NativeFoodCategory.icon(food["name"].text)).foregroundStyle(AppTab.meals.tint).frame(width: 34)
                    VStack(alignment: .leading, spacing: 5) {
                        Text(food["name"].text).font(.headline)
                        Text([food["brand"].text, food["state"].text].filter { !$0.isEmpty }.joined(separator: " · "))
                            .font(.caption).foregroundStyle(NativeTheme.muted)
                        Text("每 \(food["basis_amount_g"].text) 克 · \(food["kcal"].text) 千卡").font(.caption).foregroundStyle(NativeTheme.muted)
                    }
                    Spacer()
                    Image(systemName: "chevron.right").font(.caption)
                }
            }
        }.buttonStyle(.plain)
    }
}

enum NativeFoodCategory {
    static func of(_ name: String) -> String {
        let groups: [(String,[String])] = [("饮品",["水","茶","咖啡","果汁","饮料"]),("乳品",["奶","乳","酸奶","芝士"]),("水果",["苹果","香蕉","橙","梨","桃","葡萄","草莓","西瓜","柚","芒果"]),("蛋白质",["肉","鸡","鸭","鱼","虾","蛋","牛","猪","豆腐","豆干"]),("主食",["米","饭","面","麦","饼","薯","玉米","馒头","粥"]),("蔬菜",["菜","笋","瓜","茄","菇","菌","萝卜","番茄","菠菜"])]
        return groups.first { $0.1.contains { name.contains($0) } }?.0 ?? "加餐"
    }
    static func icon(_ name: String) -> String {
        switch of(name) { case "水果": "carrot"; case "蔬菜": "leaf"; case "乳品", "饮品": "mug"; case "蛋白质": "fish"; default: "fork.knife" }
    }
}

struct NativeFoodDetail: View {
    @EnvironmentObject private var session: NativeSession
    let food: NativeJSON
    @State private var amount = "100"
    @State private var meal = "lunch"
    @State private var eatenAt = Date()
    @State private var flexible = false
    @State private var notes = ""
    @State private var saved = false

    var body: some View {
        Form {
            Section(food["name"].text) {
                Text(food["brand"].text)
                Text("每 \(food["basis_amount_g"].text) 克的营养数据")
                NativeNutrientValues(value: food)
                if !food["state"].text.isEmpty { LabeledContent("状态", value: food["state"].text) }
                LabeledContent("数据来源", value: ["catalog":"食品数据库","user":"个人食品","user_provided":"用户填写","user_confirmed":"用户确认","model_estimated":"模型估算","web_reference":"网络参考"][food["source"].text] ?? food["source"].text)
            }
            Section("按份量记录") {
                NativeField(title: "食用份量（克）", text: $amount, keyboard: .decimalPad)
                NativeMealPicker(selection: $meal)
                DatePicker("进食时间", selection: $eatenAt)
                Toggle("灵活餐", isOn: $flexible)
                NativeField(title: "备注", text: $notes)
                let factor = (Double(amount) ?? 0) / max(0.001, food["basis_amount_g"].double)
                Text("本次约 \((food["kcal"].double * factor).formatted(.number.precision(.fractionLength(0...1)))) 千卡")
                NativeActionButton(title: saved ? "再记录一份" : "保存饮食记录") { key in
                    guard let grams = Double(amount), grams > 0 else { throw NativeAPIError.message("请填写大于 0 的份量。") }
                    _ = try await session.api("nutrition/entries", method: "POST", body: [
                        "meal_type":.string(meal), "eaten_at":.string(NativeDates.timestamp(eatenAt)),
                        "items":.array([.object(["food_version_id":food["food_version_id"],"amount_g":.number(grams)])]),
                        "is_flexible_meal":.bool(flexible), "notes": notes.isEmpty ? .null : .string(notes)
                    ], key: key,draftKey:"food-"+food.id+"-"+NativeDates.day(session.selectedDate))
                    saved = true
                    await session.reload()
                }
                if saved { Label("记录已保存", systemImage: "checkmark.circle.fill").foregroundStyle(.green) }
            }
        }
        .navigationTitle("食品详情").navigationBarTitleDisplayMode(.inline)
        .onAppear { eatenAt = session.selectedDate }
        .nativeDraft("food-"+food.id+"-"+NativeDates.day(session.selectedDate),label:"食品份量 · "+food["name"].text,value:.object(["amount":.string(amount),"meal":.string(meal),"time":.string(NativeDates.timestamp(eatenAt)),"flexible":.bool(flexible),"notes":.string(notes)])) { v in amount = v["amount"].text; meal = v["meal"].text; eatenAt = NativeDates.parse(v["time"].text) ?? .now; flexible = v["flexible"].flag; notes = v["notes"].text }
    }
}

struct NativeNutrientValues: View {
    let value: NativeJSON
    var body: some View {
        LabeledContent("热量", value: value["kcal"].text + " 千卡")
        LabeledContent("碳水", value: value["carbs_g"].text + " 克")
        LabeledContent("蛋白质", value: value["protein_g"].text + " 克")
        LabeledContent("脂肪", value: value["fat_g"].text + " 克")
    }
}

struct NativeCustomFoodForm: View {
    @EnvironmentObject private var session: NativeSession
    @Environment(\.dismiss) private var dismiss
    let onSave: () -> Void
    @State private var name = ""
    @State private var brand = ""
    @State private var basis = "100"
    @State private var kcal = ""
    @State private var protein = ""
    @State private var carbs = ""
    @State private var fat = ""
    var body: some View {
        Form {
            Section("食品信息") { NativeField(title: "名称", text: $name); NativeField(title: "品牌（可选）", text: $brand); NativeField(title: "营养基准（克）", text: $basis, keyboard: .decimalPad) }
            Section("该基准份量的营养") {
                NativeField(title: "热量（千卡）", text: $kcal, keyboard: .decimalPad)
                NativeField(title: "蛋白质（克）", text: $protein, keyboard: .decimalPad)
                NativeField(title: "碳水（克）", text: $carbs, keyboard: .decimalPad)
                NativeField(title: "脂肪（克）", text: $fat, keyboard: .decimalPad)
            }
            NativeActionButton(title: "保存食品") { key in
                guard !name.trimmingCharacters(in: .whitespaces).isEmpty, let base = Double(basis), base > 0,
                      let k = Double(kcal), let p = Double(protein), let c = Double(carbs), let f = Double(fat), [k,p,c,f].allSatisfy({ $0 >= 0 }) else { throw NativeAPIError.message("请填写食品名称和有效的营养数值。") }
                _ = try await session.api("foods", method: "POST", body: ["name":.string(name),"brand":brand.isEmpty ? .null : .string(brand),"barcode":.null,"basis_amount_g":.number(base),"kcal":.number(k),"protein_g":.number(p),"carbs_g":.number(c),"fat_g":.number(f)], key:key)
                onSave(); dismiss()
            }
        }.navigationTitle("自定义食品").toolbar { ToolbarItem(placement: .cancellationAction) { Button("取消") { dismiss() } } }
    }
}

struct NativeExerciseLibrary: View {
    @EnvironmentObject private var session: NativeSession
    @StateObject private var resource = NativeResource()
    @State private var keyword = ""
    @State private var equipment = ""
    @State private var muscle = ""
    @State private var create = false
    @State private var revision = 0
    var onSelect: ((NativeJSON) -> Void)? = nil
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                TextField("搜索动作或别名", text: $keyword).textFieldStyle(.roundedBorder)
                HStack {
                    Picker("器械", selection: $equipment) { Text("全部器械").tag(""); ForEach(NativeLabels.equipment.keys.sorted(), id: \.self) { Text(NativeLabels.tool($0)).tag($0) } }
                    Picker("肌群", selection: $muscle) { Text("全部肌群").tag(""); ForEach(["chest","back","shoulders","biceps","triceps","quadriceps","hamstrings","gluteus","calves","core"], id: \.self) { Text(NativeLabels.muscle($0)).tag($0) } }
                }
                NativeErrorText(message: resource.error)
                if resource.loading { ProgressView("正在读取动作库…") }
                Text("\(resource.value.records.count) 个动作").font(.caption).foregroundStyle(NativeTheme.muted)
                LazyVStack(spacing: 10) { ForEach(resource.value.records, id: \.id) { exercise in
                    if let onSelect { Button { onSelect(exercise) } label: { row(exercise) }.buttonStyle(.plain) }
                    else { NavigationLink { NativeExerciseDetail(exerciseID: exercise.id) } label: { row(exercise) }.buttonStyle(.plain) }
                } }
                if !resource.loading && resource.value.records.isEmpty { ContentUnavailableView("没有找到动作", systemImage:"dumbbell", description:Text("试试其他器械、肌群或关键词。")) }
            }.nativePage()
        }
        .navigationTitle("动作库").navigationBarTitleDisplayMode(.inline)
        .toolbar { ToolbarItem(placement:.primaryAction) { Button("新增") { create = true } } }
        .task(id:"\(keyword)|\(equipment)|\(muscle)|\(revision)") {
            do { try await Task.sleep(for:.milliseconds(300)) } catch { return }
            await resource.load {
                let q = NativeQueries.exercises(keyword:keyword,equipment:equipment,muscle:muscle)
                return .array(try await session.allPages("exercises", query:q))
            }
        }
        .refreshable { revision += 1 }
        .sheet(isPresented:$create) { NavigationStack { NativeExerciseForm { revision += 1 } }.environmentObject(session) }
    }
    private func row(_ item: NativeJSON) -> some View {
        NativeCard {
            HStack {
                Image(systemName:"dumbbell").foregroundStyle(AppTab.plan.tint).frame(width:34)
                VStack(alignment:.leading, spacing:5) {
                    Text(item["name_zh"].text).font(.headline)
                    Text(NativeLabels.tool(item["equipment"].text) + " · " + item["primary_muscles"].strings.map(NativeLabels.muscle).joined(separator:"、")).font(.caption).foregroundStyle(NativeTheme.muted)
                }
                Spacer()
                Image(systemName:onSelect == nil ? "chevron.right" : "plus.circle")
            }
        }
    }
}

struct NativeExerciseDetail: View {
    @EnvironmentObject private var session: NativeSession
    @Environment(\.dismiss) private var dismiss
    let exerciseID: String
    @StateObject private var resource = NativeResource()
    @State private var history: [NativeJSON] = []
    @State private var editing = false
    @State private var deleting = false
    @State private var revision = 0
    var body: some View {
        ScrollView {
            VStack(alignment:.leading, spacing:16) {
                NativeErrorText(message:resource.error)
                if resource.loading { ProgressView() }
                if !resource.value.isNull {
                    let item = resource.value
                    Text(item["name_zh"].text).font(.title2.bold())
                    Text(NativeLabels.tool(item["equipment"].text)).foregroundStyle(NativeTheme.muted)
                    NativeAnatomyMotion(exercise:item)
                    ForEach(["instructions","breathing","common_errors","safety_notes"], id:\.self) { key in
                        if !item[key].values.isEmpty {
                            NativeCard {
                                Text(["instructions":"动作步骤","breathing":"呼吸节奏","common_errors":"常见错误","safety_notes":"安全提示"][key]!).font(.headline)
                                ForEach(Array(item[key].strings.enumerated()), id:\.offset) { index, text in Text("\(index + 1). \(text)").font(.subheadline) }
                            }
                        }
                    }
                    if !item["notes"].text.isEmpty { NativeCard { Text(item["notes"].text) } }
                    if !item["substitutions"].values.isEmpty {
                        NativeCard {
                            Text("替代动作").font(.headline)
                            ForEach(item["substitutions"].values, id:\.id) { alternative in
                                NavigationLink { NativeExerciseDetail(exerciseID:alternative.id) } label: {
                                    VStack(alignment:.leading) { Text(alternative["name_zh"].text); Text(alternative["reason"].text).font(.caption).foregroundStyle(NativeTheme.muted) }
                                }
                            }
                        }
                    }
                    NativeCard {
                        Text("最近训练").font(.headline)
                        if history.isEmpty { Text("还没有这个动作的训练记录").foregroundStyle(NativeTheme.muted) }
                        ForEach(Array(history.enumerated()), id: \.offset) { _, entry in
                            Text(NativeDates.display(entry["started_at"].text)).font(.subheadline.weight(.semibold))
                            ForEach(Array(entry["sets"].values.enumerated()), id:\.offset) { _, set in
                                Text("第 \(set["set_index"].integer) 组 · \(session.weightText(set["weight_kg"].double)) × \(set["reps"].text) 次").font(.caption)
                            }
                        }
                    }
                    if item["is_custom"].flag {
                        Button("编辑自定义动作") { editing = true }.frame(minHeight:44)
                        Button("删除自定义动作", role:.destructive) { deleting = true }.frame(minHeight:44)
                    }
                }
            }.nativePage()
        }
        .navigationTitle("动作解析").navigationBarTitleDisplayMode(.inline)
        .task(id:revision) {
            await resource.load { try await session.api("exercises/" + exerciseID) }
            do { history = try await session.api("exercises/" + exerciseID + "/history", query:["limit":"10"])["history"].values }
            catch { resource.error = NativeSession.readable(error) }
        }
        .sheet(isPresented:$editing) { NavigationStack { NativeExerciseForm(existing:resource.value) { revision += 1 } }.environmentObject(session) }
        .confirmationDialog("删除后无法恢复这个自定义动作", isPresented:$deleting, titleVisibility:.visible) {
            Button("删除动作", role:.destructive) { Task {
                do { _ = try await session.api("exercises/" + exerciseID, method:"DELETE", query:["expected_version":String(resource.value.version)]); dismiss() }
                catch { resource.error = NativeSession.readable(error) }
            } }
        }
    }
}

struct NativeExerciseForm: View {
    @EnvironmentObject private var session: NativeSession
    @Environment(\.dismiss) private var dismiss
    var existing: NativeJSON = .null
    let onSave: () -> Void
    @State private var name = ""
    @State private var equipment = "dumbbell"
    @State private var primary: Set<String> = []
    @State private var secondary: Set<String> = []
    @State private var notes = ""
    var body: some View {
        Form {
            NativeField(title:"动作名称", text:$name)
            Picker("器械", selection:$equipment) { ForEach(NativeLabels.equipment.keys.sorted(), id:\.self) { Text(NativeLabels.tool($0)).tag($0) } }
            Section("主练肌群") { muscles(selection:$primary, excluding:secondary) }
            Section("辅助肌群") { muscles(selection:$secondary, excluding:primary) }
            NativeField(title:"备注", text:$notes)
            NativeActionButton(title:"保存动作") { key in
                guard !name.trimmingCharacters(in:.whitespaces).isEmpty, !primary.isEmpty else { throw NativeAPIError.message("请填写名称并选择至少一个主练肌群。") }
                var body: [String:NativeJSON] = ["name_zh":.string(name),"equipment":.string(equipment),"primary_muscles":.strings(primary.sorted()),"secondary_muscles":.strings(secondary.sorted()),"notes":notes.isEmpty ? .null : .string(notes)]
                if !existing.isNull { body["expected_version"] = .int(existing.version) }
                _ = try await session.api(existing.isNull ? "exercises" : "exercises/" + existing.id, method:existing.isNull ? "POST" : "PATCH", body:body, key:key)
                onSave(); dismiss()
            }
        }.navigationTitle(existing.isNull ? "新增动作" : "编辑动作")
            .toolbar { ToolbarItem(placement:.cancellationAction) { Button("取消") { dismiss() } } }
            .onAppear { if !existing.isNull { name = existing["name_zh"].text; equipment = existing["equipment"].text; primary = Set(existing["primary_muscles"].strings); secondary = Set(existing["secondary_muscles"].strings); notes = existing["notes"].text } }
    }
    private func muscles(selection: Binding<Set<String>>, excluding: Set<String>) -> some View {
        ForEach(["chest","back","shoulders","biceps","triceps","quadriceps","hamstrings","gluteus","calves","core","forearms","trapezius","hip_flexors","adductors"], id:\.self) { code in
            Toggle(NativeLabels.muscle(code), isOn:Binding(get:{selection.wrappedValue.contains(code)}, set:{ if $0 { selection.wrappedValue.insert(code) } else { selection.wrappedValue.remove(code) } })).disabled(excluding.contains(code))
        }
    }
}
