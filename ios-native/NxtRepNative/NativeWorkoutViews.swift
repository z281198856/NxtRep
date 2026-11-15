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
            Section {
                HStack(spacing: 12) {
                    Image(systemName: "dumbbell.fill")
                        .font(.title3.weight(.semibold))
                        .foregroundStyle(AppTab.plan.tint)
                        .frame(width: 46, height: 46)
                        .background(AppTab.plan.tint.opacity(0.12), in: RoundedRectangle(cornerRadius: 14))
                        .accessibilityHidden(true)
                    Text(event.isNull ? "自主训练" : event["title"].text)
                        .font(.title2.bold())
                        .foregroundStyle(NativeTheme.ink)
                        .accessibilityAddTraits(.isHeader)
                }
                .padding(.vertical, 4)
            }
            Section("训练前状态") {
                Stepper(value: $sleep, in: 1...5) {
                    Label("睡眠 \(sleep)/5", systemImage: "moon.zzz").monospacedDigit()
                }
                Stepper(value: $energy, in: 1...5) {
                    Label("精力 \(energy)/5", systemImage: "bolt").monospacedDigit()
                }
                Stepper(value: $minutes, in: 5...300, step: 5) {
                    Label("可用 \(minutes) 分钟", systemImage: "clock").monospacedDigit()
                }
                .accessibilityLabel("可用时间")
                .accessibilityValue("\(minutes) 分钟")
            }
            NativeActionButton(title:"开始训练") { key in
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
                if resource.loading && resource.value.records.isEmpty {
                    ProgressView().frame(maxWidth: .infinity)
                }
                ForEach(resource.value.records,id:\.id) { item in
                    NavigationLink { NativeWorkoutScreen(workoutID:item.id) } label: {
                        NativeCard {
                            HStack(spacing: 10) {
                                Image(systemName: "dumbbell")
                                    .font(.subheadline.weight(.semibold))
                                    .foregroundStyle(AppTab.plan.tint)
                                    .frame(width: 36, height: 36)
                                    .background(AppTab.plan.tint.opacity(0.10), in: RoundedRectangle(cornerRadius: 11))
                                    .accessibilityHidden(true)
                                VStack(alignment: .leading, spacing: 3) {
                                    Text(item["date"].text).font(.headline).foregroundStyle(NativeTheme.ink)
                                    Text(NativeWorkoutLabel.status(item["status"].text))
                                        .font(.caption).foregroundStyle(NativeTheme.muted)
                                }
                                Spacer(minLength: 4)
                                Image(systemName: "chevron.right")
                                    .font(.caption.weight(.semibold))
                                    .foregroundStyle(NativeTheme.muted)
                                    .accessibilityHidden(true)
                            }
                            LazyVGrid(columns: [GridItem(.adaptive(minimum: 88), alignment: .leading)], alignment: .leading, spacing: 10) {
                                NativeWorkoutMetric("组数", value: item["completed_sets"].text, icon: "square.stack")
                                NativeWorkoutMetric("总训练量", value: session.weightText(item["total_volume_kg"].double), icon: "scalemass")
                                NativeWorkoutMetric("个人纪录", value: item["pr_count"].text, icon: "trophy")
                            }
                        }
                    }.buttonStyle(PreviewPressStyle())
                }
                if !resource.loading && resource.value.records.isEmpty { ContentUnavailableView("还没有训练历史",systemImage:"dumbbell") }
            }.nativePage()
        }.background(NativeTheme.background).navigationTitle("训练历史")
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

    private var status: String { resource.value["status"].text }
    private var paused: Bool { status == "paused" }
    private var running: Bool { ["active", "in_progress"].contains(status) }
    private var writable: Bool { running || paused }
    private var exercises: [NativeJSON] { resource.value["exercises"].values }
    private var recordedSets: Int {
        exercises.reduce(0) { count, exercise in count + exercise["sets"].values.filter { $0["voided_at"].isNull }.count }
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                NativeErrorText(message:resource.error)
                if resource.loading && resource.value.isNull { ProgressView("正在恢复训练…") }
                if !resource.value.isNull {
                    sessionOverview
                    if !resource.value["rest_timer"].isNull {
                        NativeRestTimer(timer: resource.value["rest_timer"], paused: paused)
                    }
                    if writable {
                        NativeActionButton(title: paused ? "继续训练" : "暂停训练") { key in
                            _ = try await session.api("workouts/" + workoutID + (paused ? "/resume" : "/pause"), method: "POST", body: [
                                "expected_version": .int(resource.value.version),
                                (paused ? "resumed_at" : "paused_at"): .string(NativeDates.timestamp())
                            ], key: key)
                            revision += 1
                        }
                    }
                    if !exercises.isEmpty {
                        Text("训练动作").font(.headline).foregroundStyle(NativeTheme.ink).accessibilityAddTraits(.isHeader)
                    }
                    ForEach(exercises,id:\.id) { exercise in
                        NativeWorkoutExerciseCard(workout:resource.value,exercise:exercise,onChanged:{revision += 1},onReplace:{replacementID = exercise.id; selectingExercise = true})
                    }
                    if writable {
                        workoutActions
                    }
                    if !summary.isNull { NativeWorkoutSummary(summary:summary) }
                }
            }.nativePage()
        }.background(NativeTheme.background).navigationTitle("训练记录").navigationBarTitleDisplayMode(.inline)
            .toolbar {
                if writable {
                    ToolbarItem(placement: .topBarTrailing) {
                        NavigationLink { NativeWorkoutPrecheck(workout: resource.value) { revision += 1 } } label: {
                            Image(systemName: "slider.horizontal.3")
                        }
                        .accessibilityLabel("更新训练前状态")
                    }
                }
            }
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

    private var sessionOverview: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 6) {
                Image(systemName: NativeWorkoutLabel.icon(status)).accessibilityHidden(true)
                Text(NativeWorkoutLabel.status(status))
            }
            .font(.subheadline.weight(.semibold))
            .padding(.horizontal, 11)
            .padding(.vertical, 6)
            .background(Color.white.opacity(0.14), in: Capsule())

            TimelineView(.periodic(from: .now, by: 1)) { clock in
                let elapsed = resource.value["elapsed_seconds"].integer
                let delta = running ? max(0, Int(clock.date.timeIntervalSince(resource.loadedAt ?? clock.date))) : 0
                let seconds = elapsed + delta
                Text("\(seconds / 60):\(String(format: "%02d", seconds % 60))")
                    .font(.system(.largeTitle, design: .rounded).weight(.bold))
                    .monospacedDigit()
                    .accessibilityLabel("训练时长")
                    .accessibilityValue("\(seconds / 60) 分 \(seconds % 60) 秒")
            }

            ViewThatFits(in: .horizontal) {
                HStack(spacing: 14) { sessionMetrics }.fixedSize(horizontal: true, vertical: false)
                VStack(alignment: .leading, spacing: 8) { sessionMetrics }
            }
            .font(.subheadline.weight(.medium))
            .foregroundStyle(Color.white.opacity(0.84))
            Text(NativeDates.display(resource.value["started_at"].text))
                .font(.caption)
                .foregroundStyle(Color.white.opacity(0.75))
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(18)
        .foregroundStyle(.white)
        .background(
            LinearGradient(colors: [NativeTheme.hero, NativeTheme.accent], startPoint: .topLeading, endPoint: .bottomTrailing),
            in: RoundedRectangle(cornerRadius: 22)
        )
    }

    @ViewBuilder private var sessionMetrics: some View {
        Label("\(exercises.count) 个动作", systemImage: "dumbbell")
        Label("已记录 \(recordedSets) 组", systemImage: "checkmark.circle")
    }

    private var workoutActions: some View {
        VStack(alignment: .leading, spacing: 8) {
            Button { replacementID = nil; selectingExercise = true } label: {
                Label("添加动作", systemImage: "plus")
                    .frame(maxWidth: .infinity, minHeight: 44)
            }
            .buttonStyle(.bordered)
            Button { finish = true } label: {
                Label("结束训练", systemImage: "checkmark.circle")
                    .frame(maxWidth: .infinity, minHeight: 44)
            }
            .buttonStyle(.borderedProminent)
            Button("放弃本次训练", role: .destructive) { abandon = true }
                .font(.subheadline)
                .frame(minHeight: 44)
        }
    }

    private func load() async { await resource.load { try await session.api("workouts/"+workoutID) } }
}

private enum NativeWorkoutLabel {
    static func status(_ status: String) -> String {
        status == "in_progress" ? "训练中" : NativeLabels.status(status)
    }

    static func icon(_ status: String) -> String {
        switch status {
        case "active", "in_progress": "play.fill"
        case "paused": "pause.fill"
        case "completed": "checkmark"
        case "abandoned": "stop.fill"
        default: "clock"
        }
    }

    static func targetSetCount(_ snapshot: NativeJSON) -> Int {
        (snapshot["sets"].isNull ? snapshot["target_sets"] : snapshot["sets"]).integer
    }
}

private struct NativeWorkoutMetric: View {
    let title: String
    let value: String
    let icon: String

    init(_ title: String, value: String, icon: String) {
        self.title = title
        self.value = value
        self.icon = icon
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Label(title, systemImage: icon).font(.caption).foregroundStyle(NativeTheme.muted)
            Text(value).font(.subheadline.weight(.semibold)).monospacedDigit().foregroundStyle(NativeTheme.ink)
        }
        .accessibilityElement(children: .combine)
    }
}

private struct NativeRestTimer: View {
    let timer: NativeJSON
    let paused: Bool
    var body: some View {
        TimelineView(.periodic(from:.now,by:1)) { clock in
            let end = NativeDates.parse(timer["ends_at"].text) ?? clock.date
            let remaining = paused ? timer["remaining_seconds"].integer : max(0,Int(end.timeIntervalSince(clock.date).rounded(.up)))
            Label(remaining == 0 ? "休息结束，可以开始下一组" : "组间休息 \(remaining/60):\(String(format:"%02d",remaining%60))",systemImage:"timer")
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(NativeTheme.accent)
                .monospacedDigit()
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(12)
                .background(NativeTheme.softAccent, in: RoundedRectangle(cornerRadius: 14))
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
    private var skipped: Bool { exercise["skipped"].flag }
    private var writable: Bool { ["active", "in_progress"].contains(workout["status"].text) && !skipped }
    private var sets: [NativeJSON] { exercise["sets"].values.filter { $0["voided_at"].isNull } }
    private var target: NativeJSON { exercise["target_snapshot"] }
    private var targetSets: Int { NativeWorkoutLabel.targetSetCount(target) }
    private var workingSets: Int { sets.filter { !$0["tags"].strings.contains("warmup") }.count }
    private var repTarget: String {
        let low = target["rep_min"].text
        let high = target["rep_max"].text
        return low == high ? low : "\(low)–\(high)"
    }

    var body: some View {
        NativeCard {
            exerciseHeading
            if targetSets > 0 && !skipped {
                workoutProgress
            }
            ForEach(sets, id: \.id) { set in setRow(set) }
            if writable {
                Button { selectedSet = .null; editingSet = true } label: {
                    Label("记录一组", systemImage: "plus")
                        .frame(maxWidth: .infinity, minHeight: 44)
                }
                .buttonStyle(.borderedProminent)
                exerciseOptions
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

    private var exerciseHeading: some View {
        HStack(spacing: 8) {
            let title = Text(exercise["name_snapshot"].text)
                .font(.headline)
                .foregroundStyle(NativeTheme.ink)
            if exercise["exercise_id"].text.isEmpty {
                title
            } else {
                NavigationLink { NativeExerciseDetail(exerciseID: exercise["exercise_id"].text) } label: {
                    HStack(spacing: 6) {
                        title
                        Image(systemName: "chevron.right")
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(NativeTheme.muted)
                            .accessibilityHidden(true)
                    }
                    .frame(minHeight: 44, alignment: .leading)
                }
                .buttonStyle(PreviewPressStyle())
            }
            Spacer(minLength: 0)
            if skipped {
                Text("已跳过").font(.caption).foregroundStyle(NativeTheme.muted)
            }
        }
    }

    private var workoutProgress: some View {
        VStack(alignment: .leading, spacing: 6) {
            ViewThatFits(in: .horizontal) {
                HStack { progressLabels }.fixedSize(horizontal: true, vertical: false)
                VStack(alignment: .leading, spacing: 4) { progressLabels }
            }
            .font(.caption.weight(.medium))
            .foregroundStyle(NativeTheme.muted)
            .monospacedDigit()
            ProgressView(value: Double(min(workingSets, targetSets)), total: Double(targetSets))
                .tint(AppTab.plan.tint)
                .accessibilityHidden(true)
        }
    }

    @ViewBuilder private var progressLabels: some View {
        Text("正式组 \(workingSets)/\(targetSets)")
        if !repTarget.isEmpty { Text("每组 \(repTarget) 次") }
    }

    private func setRow(_ set: NativeJSON) -> some View {
        let efforts = [
            set["rir"].isNull ? nil : "RIR \(set["rir"].text)",
            set["rpe"].isNull ? nil : "RPE \(set["rpe"].text)"
        ].compactMap { $0 }

        return HStack(spacing: 8) {
            Text(set["set_index"].text)
                .font(.caption.weight(.semibold))
                .foregroundStyle(AppTab.plan.tint)
                .padding(8)
                .background(AppTab.plan.tint.opacity(0.10), in: RoundedRectangle(cornerRadius: 8))
                .accessibilityLabel("第 \(set["set_index"].text) 组")

            VStack(alignment: .leading, spacing: 3) {
                Text("\(session.weightText(set["weight_kg"].double)) × \(set["reps"].text) 次")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(NativeTheme.ink)
                if !efforts.isEmpty {
                    Text(efforts.joined(separator: " · ")).font(.caption).foregroundStyle(NativeTheme.muted)
                }
                if set["tags"].strings.contains("warmup") {
                    Text("热身").font(.caption).foregroundStyle(NativeTheme.muted)
                }
                if set["pending_local"].flag {
                    Label("待同步", systemImage: "icloud.and.arrow.up")
                        .font(.caption)
                        .foregroundStyle(AppTab.plan.tint)
                }
            }
            .monospacedDigit()
            Spacer(minLength: 0)
            if writable && !set["pending_local"].flag {
                Button { selectedSet = set; editingSet = true } label: {
                    Image(systemName: "pencil").frame(width: 44, height: 44)
                }
                .buttonStyle(.borderless)
                .accessibilityLabel("编辑第 \(set["set_index"].text) 组")
                Button(role: .destructive) { deleting = set } label: {
                    Image(systemName: "trash").frame(width: 44, height: 44)
                }
                .buttonStyle(.borderless)
                .accessibilityLabel("删除第 \(set["set_index"].text) 组")
            }
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 4)
        .background(NativeTheme.background, in: RoundedRectangle(cornerRadius: 12))
    }

    private var exerciseOptions: some View {
        DisclosureGroup {
            VStack(alignment: .leading, spacing: 6) {
                Button { targets = true } label: {
                    Label("组数与休息", systemImage: "timer").frame(minHeight: 44)
                }
                Button(action: onReplace) {
                    Label("替换动作", systemImage: "arrow.left.arrow.right").frame(minHeight: 44)
                }
                NativeActionButton(title: "跳过这个动作") { key in
                    _ = try await session.api("workouts/" + workout.id + "/exercises/" + exercise.id + "/skip", method: "POST", body: [
                        "reason": .string("用户在训练中跳过动作"),
                        "expected_workout_version": .int(workout.version)
                    ], key: key)
                    onChanged()
                }
            }
            .font(.subheadline)
        } label: {
            Label("动作选项", systemImage: "slider.horizontal.3").font(.subheadline).frame(minHeight: 44)
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
        }.navigationTitle("本次训练目标").onAppear {
            let snapshot = exercise["target_snapshot"]
            sets = max(1, NativeWorkoutLabel.targetSetCount(snapshot))
            rest = snapshot["rest_seconds"].integer
        }
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
    @EnvironmentObject private var session: NativeSession
    let summary: NativeJSON

    var body: some View {
        NativeCard {
            Label("训练完成", systemImage: "checkmark.circle.fill")
                .font(.title3.bold())
                .foregroundStyle(NativeTheme.ink)
                .accessibilityAddTraits(.isHeader)
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 112), alignment: .leading)], alignment: .leading, spacing: 12) {
                NativeWorkoutMetric("时长", value: "\(summary["duration_seconds"].integer / 60) 分钟", icon: "clock")
                NativeWorkoutMetric("组数", value: summary["completed_sets"].text, icon: "square.stack")
                NativeWorkoutMetric("总训练量", value: session.weightText(summary["total_volume_kg"].double), icon: "scalemass")
                NativeWorkoutMetric("个人纪录", value: String(summary["prs"].values.count), icon: "trophy")
            }
        }
    }
}
