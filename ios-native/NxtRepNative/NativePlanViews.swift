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
            VStack(alignment:.leading,spacing:14) {
                NativeErrorText(message:error)
                if !active.isNull {
                    NativeCard {
                        Text("正在使用").font(.caption).foregroundStyle(NativeTheme.muted)
                        Text(active["name"].text).font(.title3.bold())
                        Text("每周 \(active["weekly_frequency"].text) 天")
                        NavigationLink("查看当前计划") { NativePlanContents(plan:active) }
                    }
                }
                HStack {
                    NavigationLink("训练日历") { NativeCalendarView() }
                    Spacer()
                    NavigationLink("自建 / 导入计划") { NativePlanCreation() }
                }.buttonStyle(.bordered)
                NavigationLink { NativeExerciseLibrary() } label: { Label("动作库与动态解析",systemImage:"figure.strengthtraining.traditional").frame(maxWidth:.infinity,minHeight:44) }.buttonStyle(.borderedProminent)
                Text("官方训练模板").font(.headline)
                TextField("搜索计划",text:$keyword).textFieldStyle(.roundedBorder)
                Toggle("按我的目标、器械和训练频率推荐",isOn:$usePreferences).font(.subheadline)
                NativeErrorText(message:templates.error)
                if templates.loading { ProgressView() }
                LazyVStack(spacing:10) {
                    ForEach(ranked,id:\.id) { item in
                        NavigationLink { NativeTemplateDetail(templateID:item.id) { revision += 1 } } label: {
                            NativeCard {
                                Text(item["name"].text).font(.headline)
                                Text("每周 \(item["days_per_week"].text) 天 · 每次约 \(item["duration_minutes"].text) 分钟").font(.caption).foregroundStyle(NativeTheme.muted)
                                Text(item["equipment"].strings.map(NativeLabels.tool).joined(separator:"、")).font(.caption).foregroundStyle(AppTab.plan.tint)
                            }
                        }.buttonStyle(.plain)
                    }
                }
                if !templates.loading && ranked.isEmpty { Text("当前条件没有匹配模板，可关闭条件筛选查看全部计划。").foregroundStyle(NativeTheme.muted) }
            }.nativePage()
        }.navigationTitle("计划")
            .task(id:revision) { await load() }.refreshable { await load() }
    }
    private func load() async {
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
        ForEach(Array(days.enumerated()),id:\.offset) { index, day in
            NativeCard {
                Text(day["name"].text.isEmpty ? "训练日 \(index+1)" : day["name"].text).font(.headline)
                Text("约 \(day["estimated_minutes"].text) 分钟").font(.caption).foregroundStyle(NativeTheme.muted)
                ForEach(Array(day["exercises"].values.enumerated()),id:\.offset) { _, item in
                    VStack(alignment:.leading,spacing:4) {
                        NavigationLink { NativeExerciseDetail(exerciseID:item["exercise_id"].text) } label:{ Text(item["exercise_name"].text.isEmpty ? "查看动作详情" : item["exercise_name"].text) }
                        Text("\(item["target_sets"].text) 组 × \(item["rep_min"].text)–\(item["rep_max"].text) 次 · 休息 \(item["rest_seconds"].text) 秒").font(.caption).foregroundStyle(NativeTheme.muted)
                    }.padding(.vertical,4)
                }
            }
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
                if !draft.isNull { NativePlanDraftReview(initial:draft) }
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
    @EnvironmentObject private var session: NativeSession
    @StateObject private var resource = NativeResource()
    @State private var adding = false
    @State private var revision = 0
    var body: some View {
        ScrollView {
            VStack(alignment:.leading,spacing:14) {
                DatePicker("查看日期",selection:$session.selectedDate,displayedComponents:.date).datePickerStyle(.graphical).environment(\.timeZone,NativeDates.china)
                NativeErrorText(message:resource.error)
                ForEach(resource.value.records,id:\.id) { event in
                    NavigationLink { NativeCalendarEvent(eventID:event.id) } label: {
                        NativeCard { Text(event["title"].text).font(.headline); Text(event["scheduled_date"].text+" · "+NativeLabels.status(event["status"].text)+" · "+event["estimated_minutes"].text+" 分钟").font(.caption).foregroundStyle(NativeTheme.muted) }
                    }.buttonStyle(.plain)
                }
                if resource.value.records.isEmpty && !resource.loading { Text("这个日期范围内没有训练安排").foregroundStyle(NativeTheme.muted) }
            }.nativePage()
        }.navigationTitle("训练日历")
            .toolbar { ToolbarItem(placement:.primaryAction) { Button("新建") { adding = true } } }
            .task(id:"\(NativeDates.day(session.selectedDate))|\(revision)") { await resource.load { try await session.api("calendar",query:["start_date":NativeDates.day(session.selectedDate.addingTimeInterval(-7*86400)),"end_date":NativeDates.day(session.selectedDate.addingTimeInterval(7*86400))]) } }
            .sheet(isPresented:$adding) { NavigationStack { NativeCalendarNewEvent { revision += 1 } }.environmentObject(session) }
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
                            _ = try await session.approve(submitted["confirmation_id"].text); adjustment = .null; revision += 1
                        }
                    }
                }
            }.nativePage()
        }.navigationTitle("训练安排").navigationBarTitleDisplayMode(.inline)
            .task(id:revision) { await resource.load { try await session.api("calendar/events/"+eventID) } }
    }
}
