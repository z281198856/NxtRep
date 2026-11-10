import SwiftUI
import Charts

struct NativeProgressView: View {
    @EnvironmentObject private var session: NativeSession
    @StateObject private var measurements = NativeResource()
    @StateObject private var overview = NativeResource()
    @StateObject private var trend = NativeResource()
    @StateObject private var records = NativeResource()
    @State private var days = 30
    @State private var metric = "weight"
    @State private var adding = false
    @State private var revision = 0
    var body: some View {
        ScrollView {
            VStack(alignment:.leading,spacing:14) {
                Picker("日期范围",selection:$days) { Text("近 7 天").tag(7); Text("近 30 天").tag(30); Text("近 90 天").tag(90) }.pickerStyle(.segmented)
                NativeErrorText(message:overview.error)
                if !overview.value.isNull {
                    NativeCard {
                        Text("训练概览").font(.headline)
                        LabeledContent("训练次数",value:overview.value["training"]["workout_count"].text)
                        LabeledContent("训练时长",value:overview.value["training"]["total_duration_minutes"].text+" 分钟")
                        LabeledContent("个人纪录",value:overview.value["training"]["pr_count"].text)
                        NavigationLink("查看训练历史") { NativeWorkoutHistory() }
                    }
                }
                HStack { Button("新增身体测量") { adding = true }; Spacer(); NavigationLink("围度法体脂") { NativeNavyBodyFat() } }.buttonStyle(.bordered)
                NavigationLink { NativeBodyPhotoLibrary() } label: { Label("身体照片与阶段报告",systemImage:"photo.stack").frame(maxWidth:.infinity,minHeight:44) }.buttonStyle(.borderedProminent)
                NativeCard {
                    Text("身体趋势").font(.headline)
                    Picker("指标",selection:$metric) { Text("体重").tag("weight"); Text("腰围").tag("waist"); Text("体脂率").tag("body_fat") }.pickerStyle(.segmented)
                    NativeErrorText(message:trend.error)
                    if trend.value["points"].values.isEmpty { Text("这个时间范围内还没有足够记录").foregroundStyle(NativeTheme.muted) }
                    else {
                        Chart(Array(trend.value["points"].values.enumerated()),id:\.offset) { _, point in
                            if let date = NativeDates.parse(point["date"].text) {
                                LineMark(x:.value("日期",date),y:.value("趋势",converted(point["smoothed_value"].double))).foregroundStyle(NativeTheme.accent)
                                PointMark(x:.value("日期",date),y:.value("原始记录",converted(point["raw_value"].double))).foregroundStyle(NativeTheme.accent.opacity(0.5))
                            }
                        }.frame(height:190).chartYAxisLabel(metric == "body_fat" ? "%" : (metric == "weight" ? session.weightUnit : session.lengthUnit))
                    }
                }
                Text("身体记录").font(.headline)
                NativeErrorText(message:measurements.error)
                ForEach(measurements.value.records,id:\.id) { measurement in
                    NavigationLink { NativeMeasurementForm(existing:measurement) { revision += 1 } } label: {
                        NativeCard {
                            Text(NativeDates.display(measurement["measured_at"].text)).font(.subheadline.weight(.semibold))
                            if !measurement["weight_kg"].isNull { Text("体重 "+session.weightText(measurement["weight_kg"].double)).font(.subheadline) }
                            if !measurement["waist_cm"].isNull { Text("腰围 "+session.lengthText(measurement["waist_cm"].double)).font(.caption) }
                            if !measurement["body_fat_percent"].isNull { Text("体脂 "+measurement["body_fat_percent"].text+"%").font(.caption) }
                        }
                    }.buttonStyle(.plain)
                }
                NativeCard {
                    Text("个人纪录").font(.headline)
                    NativeErrorText(message:records.error)
                    ForEach(records.value.records,id:\.id) { record in
                        NavigationLink { NativeWorkoutScreen(workoutID:record["workout_id"].text) } label: {
                            VStack(alignment:.leading,spacing:5) { Text(record["exercise_name"].text); Text(record["record_type"].text+" · "+record["value"].text+" · "+NativeDates.display(record["occurred_at"].text)).font(.caption).foregroundStyle(NativeTheme.muted) }
                        }
                    }
                    if records.value.records.isEmpty { Text("还没有个人纪录").foregroundStyle(NativeTheme.muted) }
                }
            }.nativePage()
        }.navigationTitle("进展")
            .task(id:"\(days)|\(revision)") { await load() }
            .task(id:metric) { await loadTrend() }
            .refreshable { await load() }
            .sheet(isPresented:$adding) { NavigationStack { NativeMeasurementForm { revision += 1 } }.environmentObject(session) }
    }
    private func converted(_ value:Double) -> Double { metric == "weight" ? session.displayWeight(value) : (metric == "waist" ? session.displayLength(value) : value) }
    private var range: [String:String] { ["start_date":NativeDates.day(Date().addingTimeInterval(-Double(days-1)*86400)),"end_date":NativeDates.day()] }
    private func loadTrend() async { await trend.load { var query = range; query["metric"] = metric; query["window"] = days >= 60 ? "14d" : "7d"; return try await session.api("progress/body-trend",query:query) } }
    private func load() async {
        await overview.load { try await session.api("progress/overview",query:range) }
        await measurements.load { .array(try await session.allPages("body/measurements")) }
        await records.load { .array(try await session.allPages("progress/prs")) }
        await loadTrend()
    }
}

struct NativeMeasurementForm: View {
    @EnvironmentObject private var session: NativeSession
    @Environment(\.dismiss) private var dismiss
    var existing: NativeJSON = .null
    let onSave: () -> Void
    @State private var date = Date()
    @State private var weight = ""
    @State private var waist = ""
    @State private var neck = ""
    @State private var hip = ""
    @State private var fat = ""
    @State private var conditions = ""
    @State private var notes = ""
    var body: some View {
        Form {
            DatePicker("测量时间",selection:$date)
            NativeField(title:"体重（\(session.weightUnit)，可留空）",text:$weight,keyboard:.decimalPad)
            NativeField(title:"腰围（\(session.lengthUnit)，可留空）",text:$waist,keyboard:.decimalPad)
            NativeField(title:"颈围（\(session.lengthUnit)，可留空）",text:$neck,keyboard:.decimalPad)
            NativeField(title:"臀围（\(session.lengthUnit)，可留空）",text:$hip,keyboard:.decimalPad)
            NativeField(title:"体脂率（%，可留空）",text:$fat,keyboard:.decimalPad)
            NativeField(title:"测量条件",text:$conditions)
            NativeField(title:"备注",text:$notes)
            NativeActionButton(title:"保存身体记录") { key in
                let entries = [weight,waist,neck,hip,fat]
                guard entries.contains(where:{!$0.isEmpty}), entries.filter({!$0.isEmpty}).allSatisfy({ (Double($0) ?? -1) > 0 }) else { throw NativeAPIError.message("请至少填写一个有效测量值。") }
                var body: [String:NativeJSON] = ["measured_at":.string(NativeDates.timestamp(date)),"weight_kg":weight.isEmpty ? .null : .number(session.toKG(Double(weight)!)),"waist_cm":waist.isEmpty ? .null : .number(session.toCM(Double(waist)!)),"neck_cm":neck.isEmpty ? .null : .number(session.toCM(Double(neck)!)),"hip_cm":hip.isEmpty ? .null : .number(session.toCM(Double(hip)!)),"body_fat_percent":fat.isEmpty ? .null : .number(Double(fat)!),"body_fat_method":fat.isEmpty ? .null : .string("manual"),"source":.string("manual"),"conditions":conditions.isEmpty ? .null : .string(conditions),"notes":notes.isEmpty ? .null : .string(notes)]
                if !existing.isNull { body["expected_version"] = .int(existing.version); body["reason"] = .string("用户修改身体测量记录") }
                _ = try await session.api(existing.isNull ? "body/measurements" : "body/measurements/"+existing.id,method:existing.isNull ? "POST" : "PATCH",body:body,key:key,draftKey:existing.isNull ? "measurement" : nil)
                onSave(); dismiss()
            }
        }.navigationTitle(existing.isNull ? "身体测量" : "编辑测量")
            .nativeDraft("measurement"+(existing.isNull ? "" : "-"+existing.id),label:"身体测量",value:formDraft) { value in
                guard existing.isNull else { return }
                date = NativeDates.parse(value["time"].text) ?? .now; weight = value["weight"].text; waist = value["waist"].text; neck = value["neck"].text; hip = value["hip"].text; fat = value["fat"].text; conditions = value["conditions"].text; notes = value["notes"].text
            }
            .onAppear { if !existing.isNull {
                date = NativeDates.parse(existing["measured_at"].text) ?? .now
                weight = existing["weight_kg"].isNull ? "" : session.displayWeight(existing["weight_kg"].double).formatted(.number.precision(.fractionLength(0...3)))
                waist = existing["waist_cm"].isNull ? "" : session.displayLength(existing["waist_cm"].double).formatted(.number.precision(.fractionLength(0...3)))
                neck = existing["neck_cm"].isNull ? "" : session.displayLength(existing["neck_cm"].double).formatted(.number.precision(.fractionLength(0...3)))
                hip = existing["hip_cm"].isNull ? "" : session.displayLength(existing["hip_cm"].double).formatted(.number.precision(.fractionLength(0...3)))
                fat = existing["body_fat_percent"].text; conditions = existing["conditions"].text; notes = existing["notes"].text
            } }
    }
    private var formDraft:NativeJSON { .object(["time":.string(NativeDates.timestamp(date)),"weight":.string(weight),"waist":.string(waist),"neck":.string(neck),"hip":.string(hip),"fat":.string(fat),"conditions":.string(conditions),"notes":.string(notes)]) }
}

struct NativeNavyBodyFat: View {
    @EnvironmentObject private var session: NativeSession
    @State private var sex = "male"
    @State private var height = ""
    @State private var waist = ""
    @State private var neck = ""
    @State private var hip = ""
    @State private var result: NativeJSON = .null
    @State private var save = false
    @StateObject private var history = NativeResource()
    @State private var revision = 0
    var body: some View {
        Form {
            Section("美军围度法") {
                Picker("公式性别",selection:$sex) { Text("男性公式").tag("male"); Text("女性公式").tag("female") }
                NativeField(title:"身高（\(session.lengthUnit)）",text:$height,keyboard:.decimalPad)
                NativeField(title:"腰围（\(session.lengthUnit)）",text:$waist,keyboard:.decimalPad)
                NativeField(title:"颈围（\(session.lengthUnit)）",text:$neck,keyboard:.decimalPad)
                if sex == "female" { NativeField(title:"臀围（\(session.lengthUnit)）",text:$hip,keyboard:.decimalPad) }
                Toggle("保存这次估算",isOn:$save)
                NativeActionButton(title:"计算体脂估计范围") { key in
                    guard let h = Double(height), let w = Double(waist), let n = Double(neck), h > 0, w > 0, n > 0 else { throw NativeAPIError.message("请填写有效身高、腰围和颈围。") }
                    result = try await session.api("body/body-fat/navy",method:"POST",body:["sex":.string(sex),"height_cm":.number(session.toCM(h)),"waist_cm":.number(session.toCM(w)),"neck_cm":.number(session.toCM(n)),"hip_cm":sex == "female" ? .number(session.toCM(Double(hip) ?? 0)) : .null,"save":.bool(save)],key:key)
                    revision += 1
                }
                if !result.isNull { Text("估计 \(result["value_percent"].text)%（\(result["range_min_percent"].text)–\(result["range_max_percent"].text)%）").font(.headline); Text(result["disclaimer"].text).font(.caption).foregroundStyle(NativeTheme.muted) }
            }
            Section("历史估算") {
                NativeErrorText(message:history.error)
                ForEach(history.value.records,id:\.id) { item in LabeledContent(NativeDates.display(item["calculated_at"].text),value:item["value_percent"].text+"%") }
            }
        }.navigationTitle("体脂估算")
            .task {
                do { let profile = try await session.api("profile"); if ["male","female"].contains(profile["sex"].text) { sex = profile["sex"].text }; if !profile["height_cm"].isNull { height = String(session.displayLength(profile["height_cm"].double)) } }
                catch { history.error = NativeSession.readable(error) }
            }
            .task(id:revision) { await history.load { .array(try await session.allPages("body/body-fat")) } }
    }
}

struct NativeBodyPhotoLibrary: View {
    @EnvironmentObject private var session: NativeSession
    @StateObject private var photos = NativeResource()
    @StateObject private var reports = NativeResource()
    @State private var adding = false
    @State private var revision = 0
    @State private var beforeID = ""
    @State private var afterID = ""
    @State private var comparison: NativeJSON = .null
    @State private var days = 30
    var body: some View {
        ScrollView {
            VStack(alignment:.leading,spacing:16) {
                Button("添加身体进展照片") { adding = true }.buttonStyle(.borderedProminent)
                NativeErrorText(message:photos.error)
                ForEach(photos.value.records,id:\.id) { photo in NavigationLink { NativeBodyPhotoDetail(photo:photo) } label: {
                    NativeCard { Text(NativeDates.display(photo["captured_at"].text)).font(.headline); Text(["front":"正面","side":"侧面","back":"背面","unknown":"未标注"][photo["view"].text] ?? "未标注").font(.caption); Text(photo["notes"].text).font(.caption).foregroundStyle(NativeTheme.muted) }
                }.buttonStyle(.plain) }
                if photos.value.records.count >= 2 {
                    NativeCard {
                        Text("前后对比").font(.headline)
                        Picker("之前",selection:$beforeID) { Text("选择照片").tag(""); ForEach(photos.value.records,id:\.id) { Text(NativeDates.display($0["captured_at"].text)).tag($0.id) } }
                        Picker("之后",selection:$afterID) { Text("选择照片").tag(""); ForEach(photos.value.records,id:\.id) { Text(NativeDates.display($0["captured_at"].text)).tag($0.id) } }
                        NativeActionButton(title:"比较两张照片") { _ in
                            guard !beforeID.isEmpty, !afterID.isEmpty, beforeID != afterID else { throw NativeAPIError.message("请选择两张不同时间的照片。") }
                            comparison = try await session.api("body/progress-photos/compare",method:"POST",body:["before_photo_id":.string(beforeID),"after_photo_id":.string(afterID),"question":.string("请比较可观察到的训练变化，说明局限并给出后续建议。")])
                        }
                        if !comparison.isNull { NativePhotoAssessment(value:comparison) }
                    }
                }
                NativeCard {
                    Text("阶段报告").font(.headline)
                    Stepper("最近 \(days) 天",value:$days,in:7...180,step:7)
                    NativeActionButton(title:"生成阶段报告") { _ in
                        _ = try await session.api("reports/phase",method:"POST",body:["period_start":.string(NativeDates.day(Date().addingTimeInterval(-Double(days-1)*86400))),"period_end":.string(NativeDates.day())])
                        revision += 1
                    }
                    NativeErrorText(message:reports.error)
                    ForEach(reports.value.records,id:\.id) { report in NavigationLink { NativeReportDetail(report:report) } label:{ Text(report["period_start"].text+" — "+report["period_end"].text) } }
                }
            }.nativePage()
        }.navigationTitle("照片与阶段报告")
            .task(id:revision) { await photos.load { try await session.api("body/progress-photos",query:["limit":"50"]) }; await reports.load { .array(try await session.allPages("reports")) } }
            .sheet(isPresented:$adding) { NavigationStack { NativeBodyPhotoCreate { revision += 1 } }.environmentObject(session) }
    }
}

private struct NativeBodyPhotoCreate: View {
    @EnvironmentObject private var session: NativeSession
    @Environment(\.dismiss) private var dismiss
    let onSave: () -> Void
    @State private var assetID = ""
    @State private var date = Date()
    @State private var view = "front"
    @State private var notes = ""
    var body: some View {
        ScrollView { VStack(alignment:.leading,spacing:16) {
            NativeImageSelector(purpose:"body_progress") { assetID = $0 }
            DatePicker("拍摄时间",selection:$date)
            Picker("拍摄视角",selection:$view) { Text("正面").tag("front"); Text("侧面").tag("side"); Text("背面").tag("back"); Text("其他").tag("unknown") }
            NativeField(title:"备注",text:$notes)
            NativeActionButton(title:"保存进展照片") { key in
                guard !assetID.isEmpty else { throw NativeAPIError.message("请先选择并上传照片。") }
                _ = try await session.api("body/progress-photos",method:"POST",body:["image_asset_id":.string(assetID),"captured_at":.string(NativeDates.timestamp(date)),"view":.string(view),"notes":notes.isEmpty ? .null : .string(notes),"assessment":.null],key:key)
                try session.local?.saveDraft("body-photo",label:"",value:.null)
                onSave(); dismiss()
            }
        }.nativePage() }.navigationTitle("添加进展照片")
            .nativeDraft("body-photo",label:"身体进展照片",value:.object(["asset":.string(assetID),"time":.string(NativeDates.timestamp(date)),"view":.string(view),"notes":.string(notes)])) { v in assetID = v["asset"].text; date = NativeDates.parse(v["time"].text) ?? .now; view = v["view"].text; notes = v["notes"].text }
    }
}

private struct NativeBodyPhotoDetail: View {
    @EnvironmentObject private var session: NativeSession
    let photo: NativeJSON
    @State private var assessment: NativeJSON = .null
    var body: some View {
        ScrollView { VStack(alignment:.leading,spacing:16) {
            NativeRemoteImage(assetID:photo["image_asset_id"].text)
            Text(NativeDates.display(photo["captured_at"].text)).font(.headline)
            Text(photo["notes"].text)
            NativeActionButton(title:"评估训练相关体态与肌肉平衡") { _ in assessment = try await session.api("body/progress-photos/"+photo.id+"/analysis-drafts",method:"POST",body:["question":.string("请评估训练相关的体态和肌肉平衡，并给出可执行的训练建议。")]) }
            if !assessment.isNull { NativePhotoAssessment(value:assessment) }
            else if !photo["assessment"].isNull { NativePhotoAssessment(value:photo["assessment"]) }
        }.nativePage() }.navigationTitle("进展照片")
    }
}

struct NativePhotoAssessment: View {
    let value: NativeJSON
    var body: some View {
        NativeCard {
            Text(value["summary"].text).font(.headline)
            ForEach(Array(value["observations"].values.enumerated()),id:\.offset) { _, item in Text(item["observation"].text); if !item["visual_evidence"].text.isEmpty { Text(item["visual_evidence"].text).font(.caption).foregroundStyle(NativeTheme.muted) } }
            ForEach(["training_considerations","recommended_next_steps","follow_up_questions"],id:\.self) { key in
                if !value[key].values.isEmpty { Text(["training_considerations":"训练注意事项","recommended_next_steps":"后续建议","follow_up_questions":"待补充信息"][key]!).font(.subheadline.bold()); ForEach(value[key].strings,id:\.self) { Text("• "+$0).font(.subheadline) } }
            }
            Text(value["disclaimer"].text).font(.caption).foregroundStyle(NativeTheme.muted)
        }
    }
}

struct NativeReportDetail: View {
    let report: NativeJSON
    var body: some View {
        ScrollView { VStack(alignment:.leading,spacing:16) {
            Text(report["period_start"].text+" — "+report["period_end"].text).font(.headline)
            NativeCard {
                Text("训练事实").font(.headline)
                LabeledContent("训练次数",value:report["facts"]["training"]["workout_count"].text)
                LabeledContent("训练时长",value:report["facts"]["training"]["total_duration_minutes"].text+" 分钟")
                LabeledContent("个人纪录",value:report["facts"]["training"]["pr_count"].text)
                if !report["facts"]["body"]["smoothed_change_kg"].isNull { LabeledContent("体重平滑变化",value:report["facts"]["body"]["smoothed_change_kg"].text+" kg") }
            }
            NativeCard { Text("建议").font(.headline); ForEach(report["recommendations"].strings,id:\.self) { Text("• "+$0) } }
            if !report["facts"]["nutrition"].isNull { NativeCard { Text("饮食事实").font(.headline); NativeBusinessSummary(value:report["facts"]["nutrition"]) } }
            if !report["evidence"].isNull { NativeCard { Text("报告依据").font(.headline); NativeBusinessSummary(value:report["evidence"]) } }
            if !report["missing_data"].values.isEmpty { NativeCard { Text("数据局限").font(.headline); ForEach(report["missing_data"].strings,id:\.self) { Text($0).foregroundStyle(NativeTheme.muted) } } }
        }.nativePage() }.navigationTitle("阶段报告")
    }
}
