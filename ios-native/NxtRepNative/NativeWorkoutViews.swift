import SwiftUI

struct NativeWorkoutStart: View {
    @EnvironmentObject private var session: NativeSession
    var event: NativeJSON = .null
    @State private var sleep = 3
    @State private var energy = 3
    @State private var minutes = 45
    @State private var workoutID: String?
    @State private var startedAt = Date()
    var body: some View {
        Form {
            Section("训练前状态") {
                Text(event.isNull ? "自主训练" : event["title"].text).font(.headline)
                Stepper("睡眠质量 \(sleep) / 5",value:$sleep,in:1...5)
                Stepper("当前精力 \(energy) / 5",value:$energy,in:1...5)
                Stepper("可用时间 \(minutes) 分钟",value:$minutes,in:5...300,step:5)
            }
            NativeActionButton(title:"开始训练并保存状态") { key in
                let workout = try await session.api("workouts",method:"POST",body:["calendar_event_id":event.isNull ? .null : event["id"],"plan_day_id":event["plan_day_id"],"started_at":.string(NativeDates.timestamp(startedAt)),"pre_check":.object(["sleep_quality":.int(sleep),"energy":.int(energy),"available_minutes":.int(minutes),"pain":.array([])])],key:key)
                workoutID = workout.id
            }
        }.navigationTitle("开始训练")
            .navigationDestination(item:$workoutID) { NativeWorkoutScreen(workoutID:$0) }
    }
}

struct NativeWorkoutHistory: View {
    @EnvironmentObject private var session: NativeSession
    @StateObject private var resource = NativeResource()
    var body: some View {
        ScrollView {
            VStack(alignment:.leading,spacing:12) {
                NativeErrorText(message:resource.error)
                ForEach(resource.value.records,id:\.id) { item in
                    NavigationLink { NativeWorkoutScreen(workoutID:item.id) } label: {
                        NativeCard {
                            Text(item["date"].text+" · "+NativeLabels.status(item["status"].text)).font(.headline)
                            Text("\(item["completed_sets"].text) 组 · 总训练量 \(item["total_volume_kg"].text) kg · \(item["pr_count"].text) 个个人纪录").font(.caption).foregroundStyle(NativeTheme.muted)
                        }
                    }.buttonStyle(.plain)
                }
                if !resource.loading && resource.value.records.isEmpty { ContentUnavailableView("还没有训练历史",systemImage:"dumbbell") }
            }.nativePage()
        }.navigationTitle("训练历史")
            .task { await resource.load { .array(try await session.allPages("workouts")) } }
            .refreshable { await resource.load { .array(try await session.allPages("workouts")) } }
    }
}

struct NativeWorkoutScreen: View {
    @EnvironmentObject private var session: NativeSession
    let workoutID: String
    @StateObject private var resource = NativeResource()
    @State private var selectingExercise = false
    @State private var replacementID: String?
    @State private var revision = 0
    @State private var finish = false
    @State private var abandon = false
    @State private var summary: NativeJSON = .null
    @State private var choosing = false

    private var writable: Bool { ["active","paused","in_progress"].contains(resource.value["status"].text) }
    var body: some View {
        ScrollView {
            VStack(alignment:.leading,spacing:14) {
                NativeErrorText(message:resource.error)
                if resource.loading && resource.value.isNull { ProgressView("正在恢复训练…") }
                if !resource.value.isNull {
                    NativeCard {
                        HStack {
                            Text(NativeLabels.status(resource.value["status"].text)).font(.headline)
                            Spacer()
                            TimelineView(.periodic(from:.now,by:1)) { clock in
                                let running = ["active","in_progress"].contains(resource.value["status"].text)
                                let seconds = resource.value["elapsed_seconds"].integer + (running ? max(0,Int(clock.date.timeIntervalSince(resource.loadedAt ?? clock.date))) : 0)
                                Text("\(seconds/60):\(String(format:"%02d",seconds%60))").monospacedDigit()
                            }
                        }
                        Text(NativeDates.display(resource.value["started_at"].text)).font(.caption).foregroundStyle(NativeTheme.muted)
                        if !resource.value["rest_timer"].isNull { NativeRestTimer(timer:resource.value["rest_timer"],paused:resource.value["status"].text == "paused") }
                        if writable {
                            let paused = resource.value["status"].text == "paused"
                            NativeActionButton(title:paused ? "继续训练" : "暂停训练") { key in
                                _ = try await session.api("workouts/"+workoutID+(paused ? "/resume" : "/pause"),method:"POST",body:["expected_version":.int(resource.value.version),(paused ? "resumed_at" : "paused_at"):.string(NativeDates.timestamp())],key:key)
                                revision += 1
                            }
                            NavigationLink("更新训练前状态") { NativeWorkoutPrecheck(workout:resource.value) { revision += 1 } }
                        }
                    }
                    ForEach(resource.value["exercises"].values,id:\.id) { exercise in
                        NativeWorkoutExerciseCard(workout:resource.value,exercise:exercise,onChanged:{revision += 1},onReplace:{replacementID = exercise.id; selectingExercise = true})
                    }
                    if writable {
                        Button("从动作库增加动作") { replacementID = nil; selectingExercise = true }.buttonStyle(.bordered).frame(minHeight:44)
                        Button("结束训练") { finish = true }.buttonStyle(.borderedProminent).frame(minHeight:44)
                        Button("放弃本次训练",role:.destructive) { abandon = true }.frame(minHeight:44)
                    }
                    if !summary.isNull { NativeWorkoutSummary(summary:summary) }
                }
            }.nativePage()
        }.navigationTitle("训练记录").navigationBarTitleDisplayMode(.inline)
            .task(id:revision) { await load() }.refreshable { await load() }
            .sheet(isPresented:$selectingExercise) { NavigationStack {
                NativeExerciseLibrary(onSelect:{ selected in
                    guard !choosing else { return }; choosing = true
                    Task {
                        do {
                            if let replacementID {
                                _ = try await session.api("workouts/"+workoutID+"/exercises/"+replacementID+"/replace",method:"POST",body:["replacement_exercise_id":selected["id"],"reason":.string("用户在训练中替换动作"),"expected_workout_version":.int(resource.value.version)])
                            } else {
                                _ = try await session.api("workouts/"+workoutID+"/exercises",method:"POST",body:["exercise_id":selected["id"],"target_sets":.int(3),"rep_min":.int(8),"rep_max":.int(12),"target_load_kg":.null,"target_rir":.int(2),"rest_seconds":.int(90),"expected_workout_version":.int(resource.value.version)])
                            }
                            selectingExercise = false; revision += 1
                        } catch { resource.error = NativeSession.readable(error); selectingExercise = false }
                        choosing = false
                    }
                }).toolbar { ToolbarItem(placement:.cancellationAction) { Button("取消") { selectingExercise = false } } }
            }.environmentObject(session) }
            .sheet(isPresented:$finish) { NavigationStack { NativeWorkoutFinish(workout:resource.value) { result in summary = result; revision += 1 } }.environmentObject(session) }
            .confirmationDialog("放弃本次训练？已保存的组记录仍保留。",isPresented:$abandon,titleVisibility:.visible) {
                Button("确认放弃",role:.destructive) { Task {
                    do { _ = try await session.api("workouts/"+workoutID+"/abandon",method:"POST",body:["ended_at":.string(NativeDates.timestamp()),"reason":.string("用户主动放弃本次训练"),"expected_version":.int(resource.value.version)]); revision += 1 }
                    catch { resource.error = NativeSession.readable(error) }
                } }
            }
    }
    private func load() async { await resource.load { try await session.api("workouts/"+workoutID) } }
}

private struct NativeRestTimer: View {
    let timer: NativeJSON
    let paused: Bool
    var body: some View {
        TimelineView(.periodic(from:.now,by:1)) { clock in
            let end = NativeDates.parse(timer["ends_at"].text) ?? clock.date
            let remaining = paused ? timer["remaining_seconds"].integer : max(0,Int(end.timeIntervalSince(clock.date).rounded(.up)))
            Label(remaining == 0 ? "休息结束，可以开始下一组" : "组间休息 \(remaining/60):\(String(format:"%02d",remaining%60))",systemImage:"timer")
                .font(.subheadline.weight(.semibold)).foregroundStyle(remaining == 0 ? .green : NativeTheme.accent).monospacedDigit()
        }
    }
}

private struct NativeWorkoutExerciseCard: View {
    @EnvironmentObject private var session: NativeSession
    let workout: NativeJSON
    let exercise: NativeJSON
    let onChanged: () -> Void
    let onReplace: () -> Void
    @State private var editingSet = false
    @State private var selectedSet: NativeJSON = .null
    @State private var targets = false
    @State private var deleting: NativeJSON = .null
    @State private var error: String?
    private var writable: Bool { ["active","in_progress"].contains(workout["status"].text) && !exercise["skipped"].flag }
    var body: some View {
        NativeCard {
            HStack {
                NavigationLink { NativeExerciseDetail(exerciseID:exercise["exercise_id"].text) } label: { Text(exercise["name_snapshot"].text).font(.headline) }
                Spacer()
                if exercise["skipped"].flag { Text("已跳过").font(.caption).foregroundStyle(NativeTheme.muted) }
            }
            Text("目标 \(exercise["target_snapshot"]["target_sets"].text) 组 × \(exercise["target_snapshot"]["rep_min"].text)–\(exercise["target_snapshot"]["rep_max"].text) 次").font(.caption).foregroundStyle(NativeTheme.muted)
            ForEach(exercise["sets"].values.filter {$0["voided_at"].isNull},id:\.id) { set in
                HStack {
                    VStack(alignment:.leading,spacing:4) {
                        Text("第 \(set["set_index"].text) 组 · \(set["weight_kg"].text) kg × \(set["reps"].text) 次").monospacedDigit()
                        if !set["rir"].isNull || !set["rpe"].isNull { Text("RIR \(set["rir"].text) · RPE \(set["rpe"].text)").font(.caption).foregroundStyle(NativeTheme.muted) }
                    }
                    Spacer()
                    if set["pending_local"].flag { Text("待同步").font(.caption).foregroundStyle(.orange) }
                    if writable && !set["pending_local"].flag {
                        Button { selectedSet = set; editingSet = true } label:{Image(systemName:"pencil")}.buttonStyle(.borderless).frame(width:44,height:44)
                        Button(role:.destructive) { deleting = set } label:{Image(systemName:"trash")}.buttonStyle(.borderless).frame(width:44,height:44)
                    }
                }.font(.subheadline)
            }
            if writable {
                Button("记录一组") { selectedSet = .null; editingSet = true }.buttonStyle(.borderedProminent)
                HStack { Button("调整组数与休息") { targets = true }; Spacer(); Button("替换动作",action:onReplace) }.font(.caption).frame(minHeight:44)
                NativeActionButton(title:"跳过这个动作") { key in
                    _ = try await session.api("workouts/"+workout.id+"/exercises/"+exercise.id+"/skip",method:"POST",body:["reason":.string("用户在训练中跳过动作"),"expected_workout_version":.int(workout.version)],key:key)
                    onChanged()
                }
            }
            NativeErrorText(message:error)
        }
        .sheet(isPresented:$editingSet) { NavigationStack { NativeWorkoutSetForm(workout:workout,exercise:exercise,existing:selectedSet,onSave:onChanged) }.environmentObject(session) }
        .sheet(isPresented:$targets) { NavigationStack { NativeWorkoutTargetForm(workout:workout,exercise:exercise,onSave:onChanged) }.environmentObject(session) }
        .confirmationDialog("删除这一组？",isPresented:Binding(get:{!deleting.isNull},set:{if !$0 {deleting = .null}}),titleVisibility:.visible) {
            Button("删除",role:.destructive) { let item = deleting; Task {
                do { _ = try await session.api("workouts/"+workout.id+"/sets/"+item.id,method:"DELETE",body:["expected_version":.int(item.version),"reason":.string("用户删除训练组")]); onChanged() }
                catch { self.error = NativeSession.readable(error) }
            }; deleting = .null }
        }
    }
}

private struct NativeWorkoutSetForm: View {
    @EnvironmentObject private var session: NativeSession
    @Environment(\.dismiss) private var dismiss
    let workout: NativeJSON
    let exercise: NativeJSON
    let existing: NativeJSON
    let onSave: () -> Void
    @State private var weight = "0"
    @State private var reps = "10"
    @State private var rir = ""
    @State private var rpe = ""
    @State private var notes = ""
    @State private var warmup = false
    @State private var completedAt = Date()
    var body: some View {
        Form {
            Text(exercise["name_snapshot"].text).font(.headline)
            NativeField(title:"重量（\(session.weightUnit)）",text:$weight,keyboard:.decimalPad)
            NativeField(title:"次数",text:$reps,keyboard:.numberPad)
            NativeField(title:"RIR：还可完成几次（可选，0–10）",text:$rir,keyboard:.numberPad)
            NativeField(title:"RPE：主观强度（可选，1–10）",text:$rpe,keyboard:.decimalPad)
            Toggle("热身组",isOn:$warmup)
            NativeField(title:"备注",text:$notes)
            NativeActionButton(title:"保存这一组") { key in
                guard let kg = Double(weight), kg >= 0, let count = Int(reps), (0...1000).contains(count) else { throw NativeAPIError.message("请输入有效重量和次数。") }
                var body: [String:NativeJSON] = ["weight_kg":.number(session.toKG(kg)),"reps":.int(count),"rir":rir.isEmpty ? .null : .int(Int(rir) ?? -1),"rpe":rpe.isEmpty ? .null : .number(Double(rpe) ?? -1),"tags":.strings([warmup ? "warmup" : "working"]),"notes":notes.isEmpty ? .null : .string(notes)]
                if !existing.isNull { body["tags"] = .strings(existing["tags"].strings.filter { !["warmup","working"].contains($0) } + [warmup ? "warmup" : "working"]) }
                if existing.isNull {
                    body["client_generated_id"] = .string(key); body["workout_exercise_id"] = exercise["id"]
                    body["set_index"] = .int((exercise["sets"].values.map {$0["set_index"].integer}.max() ?? 0)+1)
                    body["completed_at"] = .string(NativeDates.timestamp(completedAt))
                } else { body["expected_version"] = .int(existing.version); body["reason"] = .string("用户修改训练组") }
                _ = try await session.api("workouts/"+workout.id+"/sets"+(existing.isNull ? "" : "/"+existing.id),method:existing.isNull ? "POST" : "PATCH",body:body,key:key,draftKey:existing.isNull ? "set-"+workout.id+"-"+exercise.id : nil)
                onSave(); dismiss()
            }
        }.navigationTitle(existing.isNull ? "记录一组" : "编辑训练组")
            .nativeDraft("set-"+workout.id+"-"+exercise.id+(existing.isNull ? "" : "-"+existing.id),label:"训练组 · "+exercise["name_snapshot"].text,value:formDraft) { value in
                guard existing.isNull else { return }; weight = value["weight"].text; reps = value["reps"].text; rir = value["rir"].text; rpe = value["rpe"].text; notes = value["notes"].text; warmup = value["warmup"].flag; completedAt = NativeDates.parse(value["time"].text) ?? .now
            }
            .onAppear {
                if !existing.isNull { weight = String(session.displayWeight(existing["weight_kg"].double)); reps = existing["reps"].text; rir = existing["rir"].text; rpe = existing["rpe"].text; notes = existing["notes"].text; warmup = existing["tags"].strings.contains("warmup") }
            }
    }
    private var formDraft:NativeJSON { .object(["weight":.string(weight),"reps":.string(reps),"rir":.string(rir),"rpe":.string(rpe),"notes":.string(notes),"warmup":.bool(warmup),"time":.string(NativeDates.timestamp(completedAt))]) }
}

private struct NativeWorkoutTargetForm: View {
    @EnvironmentObject private var session: NativeSession
    @Environment(\.dismiss) private var dismiss
    let workout: NativeJSON
    let exercise: NativeJSON
    let onSave: () -> Void
    @State private var sets = 3
    @State private var rest = 90
    var body: some View {
        Form {
            Stepper("目标 \(sets) 组",value:$sets,in:1...20)
            Stepper("组间休息 \(rest) 秒",value:$rest,in:0...1800,step:15)
            NativeActionButton(title:"保存本次训练目标") { _ in
                _ = try await session.api("workouts/"+workout.id+"/exercises/"+exercise.id+"/target",method:"PATCH",body:["target_sets":.int(sets),"rest_seconds":.int(rest),"expected_workout_version":.int(workout.version)])
                onSave(); dismiss()
            }
        }.navigationTitle("本次训练目标").onAppear { sets = max(1,exercise["target_snapshot"]["target_sets"].integer); rest = exercise["target_snapshot"]["rest_seconds"].integer }
    }
}

struct NativeWorkoutPrecheck: View {
    @EnvironmentObject private var session: NativeSession
    @Environment(\.dismiss) private var dismiss
    let workout: NativeJSON
    let onSave: () -> Void
    @State private var sleep = 3
    @State private var energy = 3
    @State private var minutes = 45
    var body: some View {
        Form {
            Stepper("睡眠质量 \(sleep) / 5",value:$sleep,in:1...5)
            Stepper("当前精力 \(energy) / 5",value:$energy,in:1...5)
            Stepper("可用 \(minutes) 分钟",value:$minutes,in:5...300,step:5)
            NativeActionButton(title:"更新训练状态") { _ in
                _ = try await session.api("workouts/"+workout.id+"/pre-check",method:"PATCH",body:["sleep_quality":.int(sleep),"energy":.int(energy),"available_minutes":.int(minutes),"pain":workout["pre_check"]["pain"].isNull ? .array([]) : workout["pre_check"]["pain"],"expected_version":.int(workout.version)])
                onSave(); dismiss()
            }
        }.navigationTitle("训练前状态").onAppear {
            sleep = max(1,workout["pre_check"]["sleep_quality"].integer)
            energy = max(1,workout["pre_check"]["energy"].integer)
            minutes = max(5,workout["pre_check"]["available_minutes"].integer)
        }
    }
}

private struct NativeWorkoutFinish: View {
    @EnvironmentObject private var session: NativeSession
    @Environment(\.dismiss) private var dismiss
    let workout: NativeJSON
    let onSave: (NativeJSON) -> Void
    @State private var difficulty = 3
    @State private var fatigue = 3
    @State private var endedAt = Date()
    var body: some View {
        Form {
            Stepper("总体难度 \(difficulty) / 5",value:$difficulty,in:1...5)
            Stepper("疲劳程度 \(fatigue) / 5",value:$fatigue,in:1...5)
            NativeActionButton(title:"确认结束并生成总结") { key in
                let result = try await session.api("workouts/"+workout.id+"/finish",method:"POST",body:["ended_at":.string(NativeDates.timestamp(endedAt)),"overall_difficulty":.int(difficulty),"fatigue":.int(fatigue),"pain":.array([]),"interruption_reason":.null,"expected_version":.int(workout.version)],key:key)
                onSave(result); dismiss()
            }
        }.navigationTitle("结束训练")
    }
}

struct NativeWorkoutSummary: View {
    let summary: NativeJSON
    var body: some View {
        NativeCard {
            Text("训练完成").font(.title3.bold())
            LabeledContent("时长",value:"\(summary["duration_seconds"].integer/60) 分钟")
            LabeledContent("完成组数",value:summary["completed_sets"].text)
            LabeledContent("总训练量",value:summary["total_volume_kg"].text+" kg")
            LabeledContent("个人纪录",value:"\(summary["prs"].values.count) 项")
        }
    }
}
