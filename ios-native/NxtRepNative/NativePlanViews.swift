import SwiftUI

struct NativePlanHub: View {
    @EnvironmentObject private var session: NativeSession
    @StateObject private var templates = NativeResource()
    @State private var active: NativeJSON = .null
    @State private var profile: NativeJSON = .null
    @State private var preferences: NativeJSON = .null
    @State private var usePreferences = true
    @State private var keyword = ""
    @State private var error: String?
    @State private var revision = 0
    @State private var calendarRefresh = 0

    private var ranked: [NativeJSON] {
        let all = templates.value.records.filter { keyword.isEmpty || $0["name"].text.localizedCaseInsensitiveContains(keyword) }
        guard usePreferences, !preferences.isNull else { return all }
        let gear = Set(preferences["constraints"]["equipment"].strings)
        let compatible = all.filter { item in gear.isEmpty || item["equipment"].strings.allSatisfy { $0 == "bodyweight" || gear.contains($0) } }
        let goal = compatible.filter { $0["goal_types"].strings.contains(preferences["goal"]["goal_type"].text) }
        let selected = goal.isEmpty ? compatible : goal
        let days = profile["weekly_training_days"].integer == 0 ? 3 : profile["weekly_training_days"].integer
        let duration = profile["session_duration_minutes"].integer
        return selected.sorted {
            let left = abs($0["days_per_week"].integer-days), right = abs($1["days_per_week"].integer-days)
            if left != right { return left < right }
            if duration > 0 {
                let a = abs($0["duration_minutes"].integer-duration), b = abs($1["duration_minutes"].integer-duration)
                if a != b { return a < b }
            }
            return $0["name"].text < $1["name"].text
        }
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                NativePlanSchedule(revision: revision + calendarRefresh)
                NativeErrorText(message: error)
                if !active.isNull {
                    currentPlan
                }
                HStack(spacing: 10) {
                    NavigationLink {
                        NativePlanCreation(onActivate: { revision += 1 })
                    } label: {
                        NativeIconTile(title: "自建 / 导入", icon: "folder.badge.plus", tint: AppTab.plan.tint)
                    }
                    NavigationLink {
                        NativeExerciseLibrary()
                    } label: {
                        NativeIconTile(title: "动作库", icon: "figure.strengthtraining.traditional", tint: NativeTheme.accent)
                    }
                }
                .buttonStyle(PreviewPressStyle())

                templateList
            }.nativePage()
        }
        .background(NativeTheme.background)
        .navigationTitle("计划")
        .navigationBarTitleDisplayMode(.inline)
        .task(id: revision) { await load() }
        .refreshable {
            calendarRefresh += 1
            await load()
        }
    }

    private var currentPlan: some View {
        NavigationLink {
            NativePlanContents(plan: active)
        } label: {
            NativeCard {
                HStack(spacing: 12) {
                    NativeActionIcon(symbol: "checklist", tint: AppTab.plan.tint, size: 38)
                    VStack(alignment: .leading, spacing: 3) {
                        Text(active["name"].text).font(.headline)
                        Text("当前计划 · 每周 \(active["weekly_frequency"].text) 天")
                            .font(.caption)
                            .foregroundStyle(NativeTheme.muted)
                    }
                    Spacer(minLength: 4)
                    planChevron
                }
            }
        }
        .foregroundStyle(NativeTheme.ink)
        .buttonStyle(PreviewPressStyle())
    }

    private var templateList: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("官方训练模板")
                .font(.title3.weight(.bold))
                .accessibilityAddTraits(.isHeader)
            HStack(spacing: 8) {
                Image(systemName: "magnifyingglass")
                    .foregroundStyle(NativeTheme.muted)
                    .accessibilityHidden(true)
                TextField("搜索计划", text: $keyword)
            }
            .padding(.horizontal, 14)
            .frame(minHeight: 46)
            .background(NativeTheme.surface, in: RoundedRectangle(cornerRadius: 14))
            .overlay(RoundedRectangle(cornerRadius: 14).strokeBorder(NativeTheme.line))

            Toggle(isOn: $usePreferences) {
                Label("按我的偏好筛选", systemImage: "line.3.horizontal.decrease")
                    .font(.subheadline)
            }
            .padding(.horizontal, 2)

            NativeErrorText(message: templates.error)
            if templates.loading { ProgressView().frame(maxWidth: .infinity, minHeight: 44) }
            LazyVStack(spacing: 8) {
                ForEach(ranked, id: \.id) { item in
                    NavigationLink {
                        NativeTemplateDetail(templateID: item.id) { revision += 1 }
                    } label: {
                        NativeCard {
                            HStack(spacing: 12) {
                                NativeActionIcon(symbol: "dumbbell", tint: AppTab.plan.tint, size: 38)
                                VStack(alignment: .leading, spacing: 5) {
                                    Text(item["name"].text).font(.subheadline.weight(.semibold))
                                    Label("\(item["days_per_week"].text) 天 / 周 · \(item["duration_minutes"].text) 分钟", systemImage: "clock")
                                        .font(.caption)
                                        .foregroundStyle(NativeTheme.muted)
                                    let equipment = item["equipment"].strings.map(NativeLabels.tool).joined(separator: "、")
                                    if !equipment.isEmpty {
                                        Text(equipment).font(.caption2).foregroundStyle(AppTab.plan.tint)
                                    }
                                }
                                Spacer(minLength: 4)
                                planChevron
                            }
                        }
                    }
                    .foregroundStyle(NativeTheme.ink)
                    .buttonStyle(PreviewPressStyle())
                }
            }
            if !templates.loading && ranked.isEmpty && templates.error == nil {
                Text("没有匹配的模板").font(.subheadline).foregroundStyle(NativeTheme.muted)
            }
        }
        .foregroundStyle(NativeTheme.ink)
    }

    private var planChevron: some View {
        Image(systemName: "chevron.right")
            .font(.caption2.weight(.semibold))
            .foregroundStyle(NativeTheme.muted)
            .accessibilityHidden(true)
    }

    private func load() async {
        error = nil
        await templates.load { try await session.api("training/templates") }
        do { active = try await session.api("training/plans/active") }
        catch NativeAPIError.response(_, let code) where code == "ACTIVE_PLAN_NOT_FOUND" { active = .null }
        catch { self.error = NativeSession.readable(error) }
        do { profile = try await session.api("profile"); preferences = try await session.api("profile/goals-and-constraints") }
        catch { self.error = NativeSession.readable(error) }
    }
}

struct NativePlanContents: View {
    let plan: NativeJSON
    var body: some View {
        ScrollView { VStack(alignment:.leading,spacing:14) { Text(plan["name"].text).font(.title2.bold()); NativePlanDays(days:plan["days"].values) }.nativePage() }
            .navigationTitle("计划详情").navigationBarTitleDisplayMode(.inline)
    }
}

struct NativePlanDays: View {
    let days: [NativeJSON]
    var body: some View {
        ForEach(Array(days.enumerated()), id: \.offset) { index, day in
            NativeCard {
                HStack(spacing: 10) {
                    NativeActionIcon(symbol: "dumbbell", tint: AppTab.plan.tint, size: 38)
                    VStack(alignment: .leading, spacing: 3) {
                        Text(day["name"].text.isEmpty ? "训练日 \(index + 1)" : day["name"].text)
                            .font(.headline)
                            .accessibilityAddTraits(.isHeader)
                        if !day["estimated_minutes"].text.isEmpty {
                            Label("约 \(day["estimated_minutes"].text) 分钟", systemImage: "clock")
                                .font(.caption)
                                .foregroundStyle(NativeTheme.muted)
                        }
                    }
                }
                ForEach(Array(day["exercises"].values.enumerated()), id: \.offset) { _, item in
                    Divider()
                    NavigationLink {
                        NativeExerciseDetail(exerciseID: item["exercise_id"].text)
                    } label: {
                        HStack(spacing: 8) {
                            VStack(alignment: .leading, spacing: 4) {
                                Text(item["exercise_name"].text.isEmpty ? "查看动作详情" : item["exercise_name"].text)
                                    .font(.subheadline.weight(.semibold))
                                Text("\(item["target_sets"].text) 组 × \(item["rep_min"].text)–\(item["rep_max"].text) 次 · 休息 \(item["rest_seconds"].text) 秒")
                                    .font(.caption)
                                    .foregroundStyle(NativeTheme.muted)
                            }
                            Spacer(minLength: 4)
                            Image(systemName: "chevron.right")
                                .font(.caption2.weight(.semibold))
                                .foregroundStyle(NativeTheme.muted)
                                .accessibilityHidden(true)
                        }
                        .frame(minHeight: 44)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(PreviewPressStyle())
                }
            }
            .foregroundStyle(NativeTheme.ink)
        }
    }
}

struct NativeTemplateDetail: View {
    @EnvironmentObject private var session: NativeSession
    let templateID: String
    let onActivate: () -> Void
    @StateObject private var resource = NativeResource()
    @State private var draft: NativeJSON = .null
    var body: some View {
        ScrollView {
            VStack(alignment:.leading,spacing:14) {
                NativeErrorText(message:resource.error)
                Text(resource.value["name"].text).font(.title2.bold())
                NativePlanDays(days:resource.value["days"].values)
                NativeActionButton(title:"以此模板创建我的计划") { key in
                    draft = try await session.api("training/plan-drafts/from-template",method:"POST",body:["template_id":.string(templateID),"name":resource.value["name"]],key:key)
                }
                if !draft.isNull { NativePlanDraftReview(initial:draft,onActivate:onActivate) }
            }.nativePage()
        }.navigationTitle("模板详情").navigationBarTitleDisplayMode(.inline)
            .task { await resource.load { try await session.api("training/templates/"+templateID) } }
    }
}

struct NativePlanDraftReview: View {
    @EnvironmentObject private var session: NativeSession
    let initial: NativeJSON
    var onActivate: () -> Void = {}
    @State private var activated = false
    var body: some View {
        NativeCard {
            Text(activated ? "计划已启用" : "核对训练计划").font(.headline)
            Text(initial["name"].text)
            NativePlanDays(days:initial["days"].values)
            if !initial["recognized_text"].text.isEmpty { DisclosureGroup("识别出的原文") { Text(initial["recognized_text"].text).font(.caption) } }
            if !activated {
                NativeActionButton(title:"校验并启用此计划") { key in
                    let validated = try await session.api("training/plan-drafts/"+initial.id+"/validate",method:"POST",body:["expected_version":.int(initial.version)])
                    guard validated["valid"].flag else { throw NativeAPIError.message("计划未通过校验："+validated["errors"].values.map { $0["message"].text }.joined(separator:"；")) }
                    let submitted = try await session.api("training/plan-drafts/"+initial.id+"/submit",method:"POST",body:["expected_version":.int(initial.version)],key:key)
                    _ = try await session.approve(submitted["confirmation_id"].text)
                    activated = true; onActivate()
                }
            }
        }
    }
}

private struct NativePlanExerciseDraft: Identifiable,Codable {
    var id = UUID()
    let exercise: NativeJSON
    var sets = 3
    var repsMin = 8
    var repsMax = 12
    var rest = 90
    func json(order: Int) -> NativeJSON { .object(["exercise_id":exercise["id"],"order_no":.int(order),"target_sets":.int(sets),"rep_min":.int(repsMin),"rep_max":.int(repsMax),"target_load_kg":.null,"target_rir":.int(2),"rest_seconds":.int(rest)]) }
}
private struct NativePlanDayDraft: Identifiable,Codable {
    var id = UUID()
    var name = "训练日"
    var minutes = 45
    var exercises: [NativePlanExerciseDraft] = []
}

struct NativePlanCreation: View {
    @EnvironmentObject private var session: NativeSession
    var onActivate: () -> Void = {}
    @State private var mode = "manual"
    @State private var name = "我的训练计划"
    @State private var text = ""
    @State private var days = [NativePlanDayDraft()]
    @State private var selectingDay: UUID?
    @State private var pickExercise = false
    @State private var goal = "muscle_gain"
    @State private var frequency = 3
    @State private var equipment = "bodyweight"
    @State private var imageID = ""
    @State private var draft: NativeJSON = .null
    var body: some View {
        ScrollView {
            VStack(alignment:.leading,spacing:16) {
                Picker("创建方式",selection:$mode) { Text("自建").tag("manual"); Text("文字").tag("text"); Text("图片").tag("image"); Text("AI").tag("ai") }.pickerStyle(.segmented)
                NativeField(title:"计划名称",text:$name)
                if mode == "manual" {
                    ForEach($days) { $day in
                        NativeCard {
                            NativeField(title:"训练日名称",text:$day.name)
                            Stepper("预计 \(day.minutes) 分钟",value:$day.minutes,in:5...300,step:5)
                            ForEach($day.exercises) { $exercise in
                                VStack(alignment:.leading,spacing:5) {
                                    Text(exercise.exercise["name_zh"].text).font(.headline)
                                    Stepper("\(exercise.sets) 组",value:$exercise.sets,in:1...20)
                                    Stepper("最低 \(exercise.repsMin) 次",value:$exercise.repsMin,in:1...100)
                                    Stepper("最高 \(exercise.repsMax) 次",value:$exercise.repsMax,in:1...100)
                                    Stepper("休息 \(exercise.rest) 秒",value:$exercise.rest,in:0...1800,step:15)
                                    Button("移除此动作",role:.destructive) { day.exercises.removeAll { $0.id == exercise.id } }
                                }.font(.subheadline).padding(.vertical,5)
                            }
                            Button("从动作库添加") { selectingDay = day.id; pickExercise = true }
                            if days.count > 1 { Button("移除此训练日",role:.destructive) { days.removeAll { $0.id == day.id } } }
                        }
                    }
                    if days.count < 7 { Button("添加训练日") { days.append(NativePlanDayDraft()) } }
                } else if mode == "text" {
                    TextField("粘贴完整训练安排，包含训练日、动作、组数和次数",text:$text,axis:.vertical).lineLimit(6...15).padding().background(NativeTheme.surface,in:RoundedRectangle(cornerRadius:16))
                } else if mode == "image" {
                    NativeImageSelector(purpose:"training_plan") { imageID = $0 }
                    if !imageID.isEmpty { Label("训练计划图片已上传",systemImage:"checkmark.circle").foregroundStyle(.green) }
                } else {
                    Picker("目标",selection:$goal) { Text("增肌塑形").tag("muscle_gain"); Text("减脂保肌").tag("fat_loss_retain"); Text("力量提升").tag("strength") }
                    Stepper("每周 \(frequency) 天",value:$frequency,in:1...7)
                    Picker("器械",selection:$equipment) { ForEach(["bodyweight","dumbbell","barbell","machine","cable"],id:\.self) { Text(NativeLabels.tool($0)).tag($0) } }
                }
                NativeActionButton(title:"生成待核对计划") { key in
                    var body: [String:NativeJSON] = ["name":.string(name)]
                    let path: String
                    switch mode {
                    case "text": path = "training/plan-drafts:parse-text"; body["text"] = .string(text); body["template_id"] = .null
                    case "image":
                        guard !imageID.isEmpty else { throw NativeAPIError.message("请先选择并上传计划图片。") }
                        path = "training/plan-drafts:parse-image"; body["image_asset_id"] = .string(imageID)
                    case "ai": path = "training/plan-drafts:generate"; body["goal_type"] = .string(goal); body["days_per_week"] = .int(frequency); body["equipment"] = .string(equipment)
                    default:
                        guard days.allSatisfy({!$0.exercises.isEmpty && $0.exercises.allSatisfy {$0.repsMin <= $0.repsMax}}) else { throw NativeAPIError.message("每个训练日需有动作，最低次数不能大于最高次数。") }
                        path = "training/plan-drafts"
                        body["weekly_frequency"] = .int(days.count)
                        body["days"] = .array(days.enumerated().map { index, day in .object(["day_index":.int(index+1),"name":.string(day.name),"estimated_minutes":.int(day.minutes),"exercises":.array(day.exercises.enumerated().map {$0.element.json(order:$0.offset+1)})]) })
                    }
                    draft = try await session.api(path,method:"POST",body:body,key:key)
                }
                if !draft.isNull {
                    if !draft["recognized_text"].text.isEmpty { Button("编辑识别文字后重新生成") { text = draft["recognized_text"].text; mode = "text"; draft = .null } }
                    NativePlanDraftReview(initial: draft, onActivate: onActivate)
                }
            }.nativePage()
        }.navigationTitle("创建训练计划").navigationBarTitleDisplayMode(.inline)
            .nativeDraft("plan-create",label:"训练计划创建",value:planSnapshot) { v in
                mode = v["mode"].text; name = v["name"].text; text = v["text"].text; goal = v["goal"].text; frequency = v["frequency"].integer; equipment = v["equipment"].text; imageID = v["image"].text; draft = v["draft"]
                if let restored = try? JSONDecoder().decode([NativePlanDayDraft].self,from:JSONEncoder().encode(v["days"])) { days = restored }
            }
            .sheet(isPresented:$pickExercise) { NavigationStack { NativeExerciseLibrary(onSelect:{ exercise in
                if let index = days.firstIndex(where:{$0.id == selectingDay}) { days[index].exercises.append(NativePlanExerciseDraft(exercise:exercise)) }
                pickExercise = false
            }).toolbar { ToolbarItem(placement:.cancellationAction) { Button("完成") { pickExercise = false } } } }.environmentObject(session) }
    }
    private var planSnapshot:NativeJSON {
        let storedDays = (try? JSONDecoder().decode(NativeJSON.self,from:JSONEncoder().encode(days))) ?? .null
        return .object(["mode":.string(mode),"name":.string(name),"text":.string(text),"days":storedDays,"goal":.string(goal),"frequency":.int(frequency),"equipment":.string(equipment),"image":.string(imageID),"draft":draft])
    }
}

struct NativeCalendarView: View {
    @State private var revision = 0

    var body: some View {
        ScrollView {
            NativePlanSchedule(expanded: true, revision: revision).nativePage()
        }
        .background(NativeTheme.background)
        .navigationTitle("训练日历")
        .navigationBarTitleDisplayMode(.inline)
        .refreshable { revision += 1 }
    }
}

private enum NativeCalendarStatus: String, CaseIterable, Identifiable {
    case planned, completed, missed, skipped

    var id: String { rawValue }

    var label: String {
        switch self {
        case .planned: "待训练"
        case .completed: "已完成"
        case .missed: "未完成"
        case .skipped: "已跳过"
        }
    }

    var tint: Color {
        switch self {
        case .planned: NativeTheme.accent
        case .completed: NativeTheme.color(0x2C715C)
        case .missed: AppTab.plan.tint
        case .skipped: NativeTheme.muted
        }
    }

    var icon: String {
        switch self {
        case .planned: "dumbbell.fill"
        case .completed: "checkmark"
        case .missed: "clock.arrow.circlepath"
        case .skipped: "forward.end"
        }
    }
}

private struct NativePlanSchedule: View {
    @EnvironmentObject private var session: NativeSession
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @StateObject private var resource = NativeResource()
    @State private var expanded: Bool
    @State private var adding = false
    @State private var changes = 0
    @ScaledMetric(relativeTo: .subheadline) private var dayHeight: CGFloat = 46
    let revision: Int

    private static let calendar: Calendar = {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = NativeDates.china
        calendar.firstWeekday = 2
        return calendar
    }()
    private static let weekdays = ["一", "二", "三", "四", "五", "六", "日"]
    private let columns = Array(repeating: GridItem(.flexible(), spacing: 3), count: 7)

    init(expanded: Bool = false, revision: Int) {
        _expanded = State(initialValue: expanded)
        self.revision = revision
    }

    private var calendar: Calendar { Self.calendar }
    private var component: Calendar.Component { expanded ? .month : .weekOfYear }
    private var selectedDay: String { NativeDates.day(session.selectedDate) }
    private var window: DateInterval {
        calendar.dateInterval(of: component, for: session.selectedDate)
            ?? DateInterval(start: calendar.startOfDay(for: session.selectedDate), duration: 86400)
    }

    private var windowStart: String { NativeDates.day(window.start) }
    private var windowEnd: String { NativeDates.day(window.end.addingTimeInterval(-1)) }
    private var hasWindow: Bool {
        resource.value["start"].text == windowStart && resource.value["end"].text == windowEnd
    }

    private var eventsByDate: [String: [NativeJSON]] {
        guard hasWindow else { return [:] }
        return Dictionary(grouping: resource.value["events"].records) { $0["scheduled_date"].text }
    }

    private var days: [Date?] {
        let count = calendar.dateComponents([.day], from: window.start, to: window.end).day ?? 0
        let leading = expanded ? (calendar.component(.weekday, from: window.start) + 5) % 7 : 0
        return Array(repeating: nil, count: leading) + (0..<count).map {
            calendar.date(byAdding: .day, value: $0, to: window.start)
        }
    }

    var body: some View {
        let events = eventsByDate
        VStack(alignment: .leading, spacing: 14) {
            NativeCard {
                calendarHeader
                LazyVGrid(columns: columns, spacing: 4) {
                    ForEach(Self.weekdays, id: \.self) { day in
                        Text(day)
                            .font(.caption.weight(.medium))
                            .foregroundStyle(NativeTheme.muted)
                            .frame(maxWidth: .infinity)
                            .accessibilityHidden(true)
                    }
                    ForEach(Array(days.enumerated()), id: \.offset) { _, date in
                        if let date {
                            dayCell(date, events: events[NativeDates.day(date)] ?? [])
                        } else {
                            Color.clear.frame(height: dayHeight).accessibilityHidden(true)
                        }
                    }
                }
                if expanded && !events.isEmpty { calendarLegend }
            }
            selectedSchedule(events[selectedDay] ?? [])
        }
        .task(id: "\(windowStart)|\(windowEnd)|\(revision)|\(changes)") {
            let start = windowStart
            let end = windowEnd
            await resource.load {
                let events = try await session.api("calendar", query: ["start_date": start, "end_date": end])
                return .object(["start": .string(start), "end": .string(end), "events": events])
            }
        }
        .sheet(isPresented: $adding) {
            NavigationStack { NativeCalendarNewEvent { changes += 1 } }
                .environmentObject(session)
        }
    }

    private var calendarHeader: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack {
                Text("训练日历")
                    .font(.headline)
                    .accessibilityAddTraits(.isHeader)
                Spacer()
                Button {
                    withAnimation(reduceMotion ? nil : .easeInOut(duration: 0.22)) { expanded.toggle() }
                } label: {
                    Label(expanded ? "周视图" : "月视图", systemImage: expanded ? "calendar" : "calendar.badge.plus")
                        .font(.caption.weight(.semibold))
                        .padding(.horizontal, 10)
                        .frame(minHeight: 44)
                }
                .buttonStyle(PreviewPressStyle())
                .foregroundStyle(NativeTheme.accent)
            }
            HStack(spacing: 3) {
                Text(monthTitle)
                    .font(.system(.title3, design: .rounded).weight(.bold))
                    .accessibilityAddTraits(.isHeader)
                Spacer(minLength: 4)
                if !calendar.isDateInToday(session.selectedDate) {
                    Button("今天") { select(.now) }
                        .font(.caption.weight(.semibold))
                        .padding(.horizontal, 4)
                        .frame(minHeight: 44)
                        .buttonStyle(PreviewPressStyle())
                        .foregroundStyle(NativeTheme.accent)
                }
                calendarStep(-1)
                calendarStep(1)
            }
        }
        .foregroundStyle(NativeTheme.ink)
    }

    private var monthTitle: String {
        let year = calendar.component(.year, from: session.selectedDate)
        let month = calendar.component(.month, from: session.selectedDate)
        return "\(year) 年 \(month) 月"
    }

    private func calendarStep(_ offset: Int) -> some View {
        Button {
            let value = expanded ? offset : offset * 7
            if let next = calendar.date(byAdding: expanded ? .month : .day, value: value, to: session.selectedDate) {
                select(next)
            }
        } label: {
            Image(systemName: offset < 0 ? "chevron.left" : "chevron.right")
                .font(.system(size: 12, weight: .semibold))
                .foregroundStyle(NativeTheme.ink)
                .frame(width: 29, height: 29)
                .background(NativeTheme.background, in: Circle())
                .frame(width: 44, height: 44)
                .contentShape(Rectangle())
        }
        .buttonStyle(PreviewPressStyle())
        .accessibilityLabel(expanded ? (offset < 0 ? "上个月" : "下个月") : (offset < 0 ? "上一周" : "下一周"))
    }

    private func select(_ date: Date) {
        guard !calendar.isDate(date, inSameDayAs: session.selectedDate) else { return }
        session.selectedDate = calendar.isDateInToday(date) ? .now : calendar.startOfDay(for: date)
    }

    private func dayCell(_ date: Date, events: [NativeJSON]) -> some View {
        let isSelected = calendar.isDate(date, inSameDayAs: session.selectedDate)
        let isToday = calendar.isDateInToday(date)
        let day = calendar.component(.day, from: date)
        let month = calendar.component(.month, from: date)
        let eventStatuses = Set(events.map { $0["status"].text })
        let statuses = NativeCalendarStatus.allCases.filter { eventStatuses.contains($0.rawValue) }
        return Button {
            select(date)
        } label: {
            VStack(spacing: 3) {
                Text(day, format: .number)
                    .font(.system(.subheadline, design: .rounded).weight(.semibold))
                    .monospacedDigit()
                HStack(spacing: 2) {
                    ForEach(statuses) { status in
                        Circle().fill(isSelected ? Color.white : status.tint).frame(width: 4, height: 4)
                    }
                }
                .frame(height: 4)
                .accessibilityHidden(true)
            }
            .foregroundStyle(isSelected ? .white : NativeTheme.ink)
            .frame(maxWidth: .infinity, minHeight: dayHeight)
            .background(isSelected ? NativeTheme.accent : Color.clear, in: RoundedRectangle(cornerRadius: 12))
            .overlay {
                if isToday && !isSelected {
                    RoundedRectangle(cornerRadius: 12).strokeBorder(NativeTheme.accent.opacity(0.45))
                }
            }
            .contentShape(Rectangle())
            .animation(reduceMotion ? nil : .easeOut(duration: 0.18), value: isSelected)
        }
        .buttonStyle(PreviewPressStyle())
        .accessibilityLabel("\(isToday ? "今天，" : "")\(month)月\(day)日")
        .accessibilityValue(statuses.map(\.label).joined(separator: "、"))
        .accessibilityAddTraits(isSelected ? .isSelected : [])
    }

    private var calendarLegend: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 12) { legendLabels }
            VStack(alignment: .leading, spacing: 6) { legendLabels }
        }
        .foregroundStyle(NativeTheme.muted)
        .accessibilityHidden(true)
    }

    private var legendLabels: some View {
        ForEach(NativeCalendarStatus.allCases) { status in
            HStack(spacing: 4) {
                Circle().fill(status.tint).frame(width: 5, height: 5)
                Text(status.label).font(.caption2)
            }.fixedSize(horizontal: true, vertical: false)
        }
    }

    private func selectedSchedule(_ events: [NativeJSON]) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(calendar.isDateInToday(session.selectedDate) ? "今天的安排" : "\(calendar.component(.month, from: session.selectedDate)) 月 \(calendar.component(.day, from: session.selectedDate)) 日")
                    .font(.headline)
                    .accessibilityAddTraits(.isHeader)
                Spacer()
                Button {
                    adding = true
                } label: {
                    Label("新建", systemImage: "plus")
                        .font(.subheadline.weight(.semibold))
                        .frame(minHeight: 44)
                }
                .buttonStyle(PreviewPressStyle())
                .foregroundStyle(NativeTheme.accent)
                .accessibilityLabel("新建训练安排")
            }
            NativeErrorText(message: resource.error)
            ForEach(events, id: \.id) { event in
                NavigationLink {
                    NativeCalendarEvent(eventID: event.id, onChange: { changes += 1 })
                } label: {
                    eventRow(event)
                }
                .buttonStyle(PreviewPressStyle())
            }
            if events.isEmpty {
                if resource.loading || !hasWindow && resource.error == nil {
                    ProgressView().frame(maxWidth: .infinity, minHeight: 44)
                } else if resource.error == nil && hasWindow {
                    NativeCard {
                        Label("没有训练安排", systemImage: "moon.stars")
                            .font(.subheadline.weight(.medium))
                            .foregroundStyle(NativeTheme.muted)
                    }
                }
            }
        }
        .foregroundStyle(NativeTheme.ink)
    }

    private func eventRow(_ event: NativeJSON) -> some View {
        let status = NativeCalendarStatus(rawValue: event["status"].text) ?? .planned
        return NativeCard {
            HStack(spacing: 12) {
                NativeActionIcon(symbol: status.icon, tint: status.tint, size: 40)
                VStack(alignment: .leading, spacing: 4) {
                    Text(event["title"].text).font(.subheadline.weight(.semibold))
                    Text("\(status.label) · \(event["estimated_minutes"].text) 分钟")
                        .font(.caption)
                        .foregroundStyle(NativeTheme.muted)
                }
                Spacer(minLength: 4)
                Image(systemName: "chevron.right")
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(NativeTheme.muted)
                    .accessibilityHidden(true)
            }
        }
        .foregroundStyle(NativeTheme.ink)
    }
}

private struct NativeCalendarNewEvent: View {
    @EnvironmentObject private var session: NativeSession
    @Environment(\.dismiss) private var dismiss
    let onSave: () -> Void
    @State private var title = ""
    @State private var minutes = 45
    var body: some View {
        Form {
            NativeField(title:"训练名称",text:$title)
            NativeDayPicker()
            Stepper("预计 \(minutes) 分钟",value:$minutes,in:5...300,step:5)
            NativeActionButton(title:"创建训练安排") { key in
                _ = try await session.api("calendar/events",method:"POST",body:["scheduled_date":.string(NativeDates.day(session.selectedDate)),"title":.string(title),"estimated_minutes":.int(minutes),"exercises":.array([])],key:key)
                onSave(); dismiss()
            }
        }.navigationTitle("新建训练")
    }
}

struct NativeCalendarEvent: View {
    @EnvironmentObject private var session: NativeSession
    let eventID: String
    var onChange: () -> Void = {}
    @StateObject private var resource = NativeResource()
    @State private var strategy = "shift"
    @State private var targetDate = Date()
    @State private var minutes = 30
    @State private var reason = ""
    @State private var adjustment: NativeJSON = .null
    @State private var revision = 0
    var body: some View {
        ScrollView {
            VStack(alignment:.leading,spacing:16) {
                NativeErrorText(message:resource.error)
                Text(resource.value["title"].text).font(.title2.bold())
                Text(resource.value["scheduled_date"].text+" · "+NativeLabels.status(resource.value["status"].text))
                if !resource.value["content_snapshot"].isNull { NativePlanDays(days:[resource.value["content_snapshot"]]) }
                NavigationLink("按此安排开始训练") { NativeWorkoutStart(event:resource.value) }.buttonStyle(.borderedProminent)
                if !resource.value["actual_workout_id"].isNull { NavigationLink("查看实际训练记录") { NativeWorkoutScreen(workoutID:resource.value["actual_workout_id"].text) } }
                NativeCard {
                    Text("改期 / 压缩训练").font(.headline)
                    Picker("调整方式",selection:$strategy) { Text("改到指定日期").tag("shift"); Text("合并训练").tag("merge"); Text("跳过这次").tag("skip"); Text("压缩时长").tag("compress") }
                    if strategy == "compress" { Stepper("目标 \(minutes) 分钟",value:$minutes,in:10...120,step:5) }
                    else if strategy != "skip" { DatePicker("目标日期",selection:$targetDate,displayedComponents:.date) }
                    NativeField(title:"原因（可选）",text:$reason)
                    NativeActionButton(title:"生成调整方案") { key in
                        let body: [String:NativeJSON]
                        if strategy == "compress" { body = ["event_id":.string(eventID),"target_minutes":.int(minutes),"reason":reason.isEmpty ? .null : .string(reason)] }
                        else { body = ["missed_event_id":.string(eventID),"strategy":.string(strategy),"target_date":strategy == "skip" ? .null : .string(NativeDates.day(targetDate)),"reason":reason.isEmpty ? .null : .string(reason)] }
                        adjustment = try await session.api(strategy == "compress" ? "calendar/compression-drafts" : "calendar/reschedule-drafts",method:"POST",body:body,key:key)
                    }
                    if !adjustment.isNull {
                        Text("预计时长变化 \(adjustment["duration_change_minutes"].text) 分钟；训练量变化 \(adjustment["volume_change_percent"].text)%").font(.subheadline)
                        ForEach(adjustment["warnings"].strings,id:\.self) { Text($0).foregroundStyle(.orange) }
                        NativeActionButton(title:"确认执行调整") { key in
                            let submitted = try await session.api("calendar/reschedule-drafts/"+adjustment.id+"/submit",method:"POST",body:["expected_version":.int(adjustment.version)],key:key)
                            _ = try await session.approve(submitted["confirmation_id"].text)
                            adjustment = .null
                            revision += 1
                            onChange()
                        }
                    }
                }
            }.nativePage()
        }.navigationTitle("训练安排").navigationBarTitleDisplayMode(.inline)
            .task(id:revision) { await resource.load { try await session.api("calendar/events/"+eventID) } }
    }
}
