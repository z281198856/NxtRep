import Foundation

struct NativeChangePreview {
    struct Row {
        let label: String
        let value: String
        var previous: String? = nil
    }

    struct Section {
        let title: String
        let rows: [Row]
    }

    struct Portion: Identifiable {
        let id: Int
        let name: String
        let grams: String
    }

    let title: String
    let icon: String
    let approveLabel: String
    let destructive: Bool
    let sections: [Section]
    let portions: [Portion]
    let impact: String?

    init(card: NativeJSON, imperial: Bool) {
        let operation = card["operation_type"].text
        let presentation = Self.presentation(for: operation)
        title = presentation.title
        icon = presentation.icon
        approveLabel = presentation.button
        destructive = presentation.destructive
        impact = operation == "body_measurement_create" ? nil : Self.readable(card["impact"])

        var builder = Builder(card: card, imperial: imperial)
        builder.build(operation)
        sections = builder.sections
        portions = builder.portions
    }

    private static func presentation(for operation: String) -> (title: String, icon: String, button: String, destructive: Bool) {
        switch operation {
        case "body_measurement_create": ("保存身体记录", "figure.stand", "保存记录", false)
        case "body_measurement_delete": ("移除身体记录", "figure.stand", "移除记录", true)
        case "water_entry_create": ("记录饮水", "drop.fill", "保存记录", false)
        case "nutrition_entry_create": ("记录这餐", "fork.knife", "保存这餐", false)
        case "nutrition_entry_update": ("更正这餐", "fork.knife", "保存更正", false)
        case "nutrition_entry_delete": ("移除这餐", "fork.knife", "移除这餐", true)
        case "nutrition_entries_date_change": ("调整饮食日期", "calendar", "保存日期", false)
        case "nutrition_target_activate": ("更新饮食目标", "target", "启用目标", false)
        case "food_create": ("添加自定义食品", "carrot", "添加食品", false)
        case "food_update": ("更新自定义食品", "carrot", "保存修改", false)
        case "food_delete": ("移除自定义食品", "carrot", "移除食品", true)
        case "training_plan_activate": ("启用训练计划", "list.clipboard", "启用计划", false)
        case "training_plan_archive": ("归档训练计划", "archivebox", "归档计划", true)
        case "calendar_reschedule": ("调整训练日程", "calendar", "更新日程", false)
        case "training_progression_apply": ("调整训练强度", "chart.line.uptrend.xyaxis", "应用调整", false)
        case "workout_record_create": ("保存训练记录", "dumbbell", "保存记录", false)
        case "workout_record_update", "workout_set_update": ("更正训练记录", "dumbbell", "保存更正", false)
        case "workout_record_void", "workout_set_void": ("作废训练记录", "dumbbell", "作废记录", true)
        case "profile_update": ("更新个人资料", "person.crop.circle", "保存修改", false)
        case "memory_create": ("让教练记住这项偏好", "bookmark", "保存记忆", false)
        case "memory_update": ("更新教练记忆", "bookmark", "保存修改", false)
        case "memory_delete": ("移除教练记忆", "bookmark", "移除记忆", true)
        default: ("查看建议的改动", "checklist", "应用改动", false)
        }
    }

    private static func readable(_ value: NativeJSON) -> String? {
        guard case let .string(raw) = value else { return nil }
        let text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !text.hasPrefix("{"), !text.hasPrefix("["),
              !text.contains("```"), UUID(uuidString: text) == nil else { return nil }
        return text
    }

    private struct Builder {
        let card: NativeJSON
        let imperial: Bool
        var sections: [Section] = []
        var portions: [Portion] = []

        private var before: NativeJSON { card["before"] }
        private var after: NativeJSON { card["after"] }
        private var draft: NativeJSON { card["draft"] }
        private var preview: NativeJSON { after["preview"] }

        mutating func build(_ operation: String) {
            switch operation {
            case "body_measurement_create", "body_measurement_delete":
                let record = operation.hasSuffix("delete") ? before : after["measurement"]
                add("测量数据", [
                    row("体重", weight(record["weight_kg"])),
                    row("腰围", length(record["waist_cm"])),
                    row("颈围", length(record["neck_cm"])),
                    row("臀围", length(record["hip_cm"])),
                    row("体脂率", amount(record["body_fat_percent"], unit: "%")),
                    row("测量时间", date(record["measured_at"])),
                    row("测量条件", readable(record["conditions"])),
                    row("备注", readable(record["notes"]))
                ])
            case "water_entry_create":
                let water = after["water"]
                add("饮水", [
                    row("饮水量", amount(water["amount_ml"], unit: " ml")),
                    row("饮水时间", date(water["consumed_at"]))
                ])
            case "nutrition_entry_create":
                meal()
            case "nutrition_entry_update", "nutrition_entry_delete":
                mealChanges(deleting: operation.hasSuffix("delete"))
            case "nutrition_entries_date_change":
                add("日期", [comparison("记录日期", date(preview["source_date"]), date(preview["target_date"]))])
                add("涉及餐食", preview["entries"].values.map { entry in
                    row(mealName(entry["meal_type"]) ?? "餐食", entry["foods"].values.compactMap(readable).joined(separator: "、"))
                })
            case "nutrition_target_activate":
                let values = firstObject(draft["values"], preview["values"], after["values"])
                add("每日目标", [
                    row("热量", range(values["kcal_min"], values["kcal_max"], unit: " 千卡")),
                    row("蛋白质", range(values["protein_min_g"], values["protein_max_g"], unit: " 克")),
                    row("碳水", range(values["carbs_min_g"], values["carbs_max_g"], unit: " 克")),
                    row("脂肪", range(values["fat_min_g"], values["fat_max_g"], unit: " 克"))
                ])
            case "food_create", "food_update", "food_delete":
                food()
            case "training_plan_activate", "training_plan_archive":
                plan()
            case "calendar_reschedule":
                schedule()
            case "training_progression_apply":
                add("强度调整", draft["suggestions"].values.map { item in
                    comparison(
                        readable(item["exercise_name"]) ?? "训练动作",
                        weight(item["current_target"]["weight_kg"]),
                        weight(item["proposed_target"]["weight_kg"])
                    )
                })
            case "workout_record_create", "workout_record_update", "workout_record_void", "workout_set_update", "workout_set_void":
                workout(operation)
            case "profile_update":
                profile()
            case "memory_create", "memory_update", "memory_delete":
                let old = firstObject(before["memory"], before)
                let updated = firstObject(after["memory"], after["changes"], after)
                if operation.hasSuffix("delete") {
                    add("记忆内容", [row("内容", readable(old["content"]))])
                } else {
                    add("记忆内容", [comparison("内容", readable(old["content"]), readable(updated["content"]))])
                }
            default:
                break
            }
        }

        private mutating func meal() {
            let entry = firstObject(after["entry"], draft)
            let details = draft["items"].values.isEmpty ? firstObject(preview, entry) : draft
            add("这餐饮食", [
                row("餐次", mealName(entry["meal_type"])),
                row("用餐时间", date(entry["eaten_at"])),
                row("备注", readable(entry["notes"]))
            ])
            let items = details["items"].values
            let saved = card["status"].text == "succeeded"
            if !saved {
                portions = items.enumerated().compactMap { index, item in
                    guard let name = readable(item["name"]), let grams = amount(item["amount_g"]) else { return nil }
                    return Portion(id: index, name: name, grams: grams)
                }
            }
            add("食物份量", items.map { item in
                let estimate = item["source"].text == "model_estimated" ? " · 估算" : ""
                return row(readable(item["name"]) ?? "食物", amount(item["amount_g"], unit: " 克" + estimate))
            })
            nutrients(firstObject(details["totals"], entry["totals"]))
        }

        private mutating func mealChanges(deleting: Bool) {
            let meal = firstObject(preview, before)
            add("原餐食", [
                row("餐次", mealName(meal["meal_type"])),
                row("用餐时间", date(meal["eaten_at"]))
            ])
            if deleting {
                add("食物份量", meal["items"].values.map { item in
                    row(readable(item["name"]) ?? "食物", amount(item["amount_g"], unit: " 克"))
                })
            } else {
                let updated = preview["changes"].values.map { item in
                    let previous = readable(item["name"]) ?? "食物"
                    let replacement = readable(item["replacement_name"])
                    let label = replacement.map { previous + " → " + $0 } ?? previous
                    return comparison(label, amount(item["old_amount_g"], unit: " 克"), amount(item["amount_g"], unit: " 克"))
                }
                let removed = preview["removed_items"].values.map { item in
                    comparison(readable(item["name"]) ?? "食物", amount(item["amount_g"], unit: " 克"), "移除")
                }
                add("份量调整", updated + removed)
            }
            nutrients(meal["totals_after"], previous: firstObject(meal["totals_before"], before["totals"]))
        }

        private mutating func food() {
            let old = before["food"]
            let updated = firstObject(after["food"], old)
            add("食品信息", [
                comparison("名称", readable(old["name"]), readable(updated["name"])),
                comparison("品牌", readable(old["brand"]), readable(updated["brand"])),
                comparison("条码", readable(old["barcode"]), readable(updated["barcode"])),
                comparison("参考份量", amount(old["basis_amount_g"], unit: " 克"), amount(updated["basis_amount_g"], unit: " 克")),
                row("数据说明", updated["source"].text == "model_estimated" ? "营养值为估算" : nil),
                row("备注", readable(updated["notes"]))
            ])
            nutrients(updated, previous: old)
        }

        private mutating func plan() {
            let plan = firstObject(draft, preview, after["plan"], before)
            add("训练计划", [
                row("计划", readable(plan["name"])),
                row("训练频率", amount(plan["weekly_frequency"], unit: " 次／周"))
            ])
            for (index, day) in plan["days"].values.enumerated() {
                let rows = day["exercises"].values.map { item in
                    let name = readable(item["exercise_name"]) ?? readable(item["name_zh"]) ?? "动作"
                    let sets = amount(item["target_sets"], unit: " 组")
                    let reps = range(item["rep_min"], item["rep_max"], unit: " 次")
                    return row(name, join(sets, reps, weight(item["target_load_kg"])))
                }
                add(readable(day["name"]) ?? "训练日 \(index + 1)", rows.isEmpty ? [row("预计时长", amount(day["estimated_minutes"], unit: " 分钟"))] : rows)
            }
        }

        private mutating func schedule() {
            let old = draft["before_events"].values.isEmpty ? before["events"].values : draft["before_events"].values
            let updated = draft["after_events"].values
            add("原安排", eventRows(old))
            add("调整后", eventRows(updated))
            add("本次调整", [
                row("时长变化", amount(draft["duration_change_minutes"], unit: " 分钟")),
                row("预计训练量变化", amount(draft["volume_change_percent"], unit: "%"))
            ])
        }

        private func eventRows(_ events: [NativeJSON]) -> [Row?] {
            events.map { event in
                let label = readable(event["title"]) ?? "训练"
                let status = event["status"].text == "skipped" ? "跳过" : amount(event["estimated_minutes"], unit: " 分钟")
                return row(label, join(date(event["scheduled_date"]), status))
            }
        }

        private mutating func workout(_ operation: String) {
            let details = firstObject(preview, after["request"], draft)
            add("训练记录", [
                row("动作", readable(details["exercise_name"])),
                row("日期", date(details["date"]) ?? date(details["workout_date"]) ?? date(details["started_at"])),
                row("记录", join(weight(details["weight_kg"]), amount(details["sets"], unit: " 组"), amount(details["reps"], unit: " 次／组")))
            ])
            let old = details["before_sets"].values
            let updated = details["after_sets"].values
            if !old.isEmpty || !updated.isEmpty {
                let rows = old.map { item in
                    let next = updated.first { !$0["set_id"].isNull && $0["set_id"] == item["set_id"] }
                    let label = setLabel(item)
                    return comparison(label, setDetails(item), next.flatMap(setDetails) ?? "作废")
                }
                let added = updated.filter { $0["added"].flag }.map { row(setLabel($0), setDetails($0)) }
                add("训练组", rows + added)
            }
            if !details["before_set"].isNull {
                add("训练组", [
                    comparison(setLabel(details), setDetails(details["before_set"]),
                               operation.hasSuffix("void") ? "作废" : setDetails(details["after_set"]))
                ])
            }
        }

        private mutating func profile() {
            let old = before["profile"]
            let updated = after["changes"]
            let fields = [
                ("display_name", "昵称"), ("sex", "性别"), ("birth_date", "出生日期"),
                ("height_cm", "身高"), ("weight_kg", "体重"), ("experience_level", "训练经验"),
                ("weekly_training_days", "每周训练天数"), ("session_duration_minutes", "单次训练时长")
            ]
            add("修改资料", fields.compactMap { key, label in
                guard let changed = updated.fields[key] else { return nil }
                return comparison(label, profileValue(key, old[key]), profileValue(key, changed))
            })
        }

        private func profileValue(_ key: String, _ value: NativeJSON) -> String? {
            if value.isNull { return "未填写" }
            switch key {
            case "weight_kg": return weight(value)
            case "height_cm": return length(value)
            case "weekly_training_days": return amount(value, unit: " 天")
            case "session_duration_minutes": return amount(value, unit: " 分钟")
            case "birth_date": return date(value)
            case "sex": return ["male": "男", "female": "女", "other": "其他", "unspecified": "未填写"][value.text]
            case "experience_level": return ["beginner": "新手", "intermediate": "有一定经验", "advanced": "经验丰富"][value.text]
            default: return readable(value)
            }
        }

        private mutating func nutrients(_ current: NativeJSON, previous: NativeJSON = .null) {
            let metrics = [("kcal", "热量", " 千卡"), ("protein_g", "蛋白质", " 克"), ("carbs_g", "碳水", " 克"), ("fat_g", "脂肪", " 克")]
            add("营养合计", metrics.map { key, label, unit in
                comparison(label, amount(previous[key], unit: unit), amount(current[key], unit: unit))
            })
        }

        private mutating func add(_ title: String, _ rows: [Row?]) {
            let visible = rows.compactMap { $0 }
            if !visible.isEmpty { sections.append(Section(title: title, rows: visible)) }
        }

        private func row(_ label: String, _ value: String?) -> Row? {
            guard let value, !value.isEmpty else { return nil }
            return Row(label: label, value: value)
        }

        private func comparison(_ label: String, _ old: String?, _ new: String?) -> Row? {
            guard let new, !new.isEmpty else { return nil }
            return Row(label: label, value: new, previous: old == new ? nil : old)
        }

        private func firstObject(_ values: NativeJSON...) -> NativeJSON {
            values.first { !$0.fields.isEmpty } ?? .null
        }

        private func amount(_ value: NativeJSON, unit: String = "", scale: Double = 1) -> String? {
            let number: Double?
            switch value {
            case let .int(integer): number = Double(integer)
            case let .number(decimal): number = decimal
            case let .string(text): number = Double(text)
            default: number = nil
            }
            guard let number, number.isFinite else { return nil }
            return (number * scale).formatted(.number.precision(.fractionLength(0...2))) + unit
        }

        private func range(_ low: NativeJSON, _ high: NativeJSON, unit: String) -> String? {
            guard let lower = amount(low), let upper = amount(high) else { return nil }
            return (lower == upper ? lower : lower + "–" + upper) + unit
        }

        private func date(_ value: NativeJSON) -> String? {
            guard let text = readable(value), let date = NativeDates.parse(text) else { return nil }
            if text.count == 10 { return NativeDates.day(date) }
            let formatter = DateFormatter()
            formatter.locale = Locale(identifier: "zh_CN")
            formatter.timeZone = NativeDates.china
            formatter.dateFormat = "yyyy-MM-dd HH:mm"
            return formatter.string(from: date)
        }

        private func weight(_ value: NativeJSON) -> String? {
            amount(value, unit: imperial ? " lb" : " kg", scale: imperial ? 2.2046226218 : 1)
        }

        private func length(_ value: NativeJSON) -> String? {
            amount(value, unit: imperial ? " in" : " cm", scale: imperial ? 1 / 2.54 : 1)
        }

        private func mealName(_ value: NativeJSON) -> String? {
            ["breakfast": "早餐", "lunch": "午餐", "dinner": "晚餐", "snack": "加餐", "other": "其他餐食"][value.text]
        }

        private func setLabel(_ value: NativeJSON) -> String {
            amount(value["set_index"]).map { "第 " + $0 + " 组" } ?? "训练组"
        }

        private func setDetails(_ value: NativeJSON) -> String? {
            join(weight(value["weight_kg"]), amount(value["reps"], unit: " 次"))
        }

        private func join(_ values: String?...) -> String? {
            let parts = values.compactMap { $0 }
            return parts.isEmpty ? nil : parts.joined(separator: " · ")
        }

        private func readable(_ value: NativeJSON) -> String? {
            NativeChangePreview.readable(value)
        }
    }
}
