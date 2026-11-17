import SwiftUI
import Charts

struct NativeProgressView: View {
    @EnvironmentObject private var session: NativeSession
    @Environment(\.dynamicTypeSize) private var typeSize
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @StateObject private var measurements = NativeResource()
    @StateObject private var overview = NativeResource()
    @StateObject private var trend = NativeResource()
    @StateObject private var records = NativeResource()
    @State private var days = 30
    @State private var metric = "weight"
    @State private var adding = false
    @State private var revision = 0

    private var metricName: String {
        switch metric {
        case "waist": "腰围"
        case "body_fat": "体脂率"
        default: "体重"
        }
    }
    private var metricUnit: String {
        switch metric {
        case "waist": session.lengthUnit
        case "body_fat": "%"
        default: session.weightUnit
        }
    }
    private var metricTint: Color {
        switch metric {
        case "waist": NutrientKind.protein.labelColor
        case "body_fat": NutrientKind.fat.labelColor
        default: NativeTheme.accent
        }
    }
    private var trendPoints: [NativeJSON] { trend.value["points"].values }

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 15) {
                trendCard
                shortcuts
                trainingOverview
                Text("身体记录").font(.headline).accessibilityAddTraits(.isHeader)
                NativeErrorText(message:measurements.error)
                if measurements.value.records.isEmpty && measurements.loadedAt != nil {
                    Label("还没有身体记录", systemImage: "scalemass").font(.subheadline).foregroundStyle(NativeTheme.muted)
                        .padding(.vertical, 10)
                }
                ForEach(measurements.value.records,id:\.id) { measurement in
                    NavigationLink { NativeMeasurementForm(existing:measurement) { revision += 1 } } label: {
                        measurementRow(measurement)
                    }
                    .buttonStyle(PreviewPressStyle())
                }
                NativeCard {
                    Label("个人纪录", systemImage: "trophy.fill").font(.headline).accessibilityAddTraits(.isHeader)
                    NativeErrorText(message:records.error)
                    ForEach(records.value.records,id:\.id) { record in
                        NavigationLink { NativeWorkoutScreen(workoutID:record["workout_id"].text) } label: {
                            HStack {
                                VStack(alignment: .leading, spacing: 3) {
                                    Text(record["exercise_name"].text).font(.subheadline.weight(.semibold)).foregroundStyle(NativeTheme.ink)
                                    Text(NativeDates.display(record["occurred_at"].text)).font(.caption).foregroundStyle(NativeTheme.muted)
                                }
                                Spacer(minLength: 5)
                                Text(personalRecordValue(record)).font(.subheadline.weight(.semibold)).monospacedDigit()
                                Image(systemName: "chevron.right").font(.caption).accessibilityHidden(true)
                            }
                            .frame(minHeight: 44).contentShape(Rectangle())
                        }
                        .buttonStyle(PreviewPressStyle())
                    }
                    if records.value.records.isEmpty && records.loadedAt != nil {
                        Text("还没有个人纪录").font(.subheadline).foregroundStyle(NativeTheme.muted)
                    }
                }
            }.nativePage()
        }.background(NativeTheme.background).navigationTitle("进展").navigationBarTitleDisplayMode(.inline)
            .task(id: "\(days)|\(revision)") { await load() }
            .task(id: "\(metric)|\(days)|\(revision)") { await loadTrend() }
            .refreshable { await loadTrend(); await load() }
            .sheet(isPresented:$adding) { NavigationStack { NativeMeasurementForm { revision += 1 } }.environmentObject(session) }
    }

    private var trendCard: some View {
        NativeCard {
            HStack {
                Text("身体趋势").font(.headline).accessibilityAddTraits(.isHeader)
                Spacer()
                Picker("日期范围", selection: $days) {
                    Text("近 7 天").tag(7)
                    Text("近 30 天").tag(30)
                    Text("近 90 天").tag(90)
                }
                .pickerStyle(.menu)
            }
            Picker("指标", selection: $metric) {
                Text("体重").tag("weight")
                Text("腰围").tag("waist")
                Text("体脂率").tag("body_fat")
            }
            .pickerStyle(.segmented)
            NativeErrorText(message: trend.error)
            if trend.loading || trend.value["metric"].text != metric {
                if trend.error == nil {
                    ProgressView().frame(maxWidth: .infinity, minHeight: 145).accessibilityLabel("正在读取身体趋势")
                }
            } else if let latest = trendPoints.last, !latest["raw_value"].isNull {
                HStack(alignment: .firstTextBaseline, spacing: 5) {
                    Text(converted(latest["raw_value"].double).formatted(.number.precision(.fractionLength(0...2))))
                        .font(.system(.largeTitle, design: .rounded, weight: .bold)).monospacedDigit().foregroundStyle(metricTint)
                    Text(metricUnit).font(.subheadline.weight(.semibold)).foregroundStyle(NativeTheme.muted)
                    Spacer(minLength: 4)
                    Text(latest["date"].text).font(.caption).foregroundStyle(NativeTheme.muted)
                }
                .accessibilityElement(children: .combine)
                Chart(Array(trendPoints.enumerated()), id: \.offset) { _, point in
                    if let date = NativeDates.parse(point["date"].text) {
                        LineMark(x: .value("日期", date), y: .value(metricName, converted(point["smoothed_value"].double)))
                            .foregroundStyle(metricTint)
                            .lineStyle(StrokeStyle(lineWidth: 2.5, lineCap: .round, lineJoin: .round))
                        PointMark(x: .value("日期", date), y: .value(metricName, converted(point["raw_value"].double)))
                            .foregroundStyle(metricTint.opacity(0.72))
                    }
                }
                .chartYScale(domain: .automatic(includesZero: false))
                .chartYAxis { AxisMarks(position: .leading) }
                .frame(height: 160)
                .animation(reduceMotion ? nil : .easeInOut(duration: 0.24), value: trendPoints.count)
            } else {
                Label("这段时间还没有\(metricName)记录", systemImage: "chart.xyaxis.line")
                    .font(.subheadline).foregroundStyle(NativeTheme.muted)
                    .frame(maxWidth: .infinity, minHeight: 100)
            }
        }
    }

    private var shortcuts: some View {
        LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 9), count: typeSize.isAccessibilitySize ? 2 : 3), spacing: 9) {
            Button { adding = true } label: {
                NativeIconTile(title: "记体重", icon: "scalemass.fill", tint: NativeTheme.accent)
            }
            NavigationLink { NativeNavyBodyFat() } label: {
                NativeIconTile(title: "围度估脂", icon: "ruler", tint: NutrientKind.protein.labelColor)
            }
            NavigationLink { NativeBodyPhotoLibrary() } label: {
                NativeIconTile(title: "照片与报告", icon: "photo.stack", tint: NutrientKind.fat.labelColor)
            }
        }
        .buttonStyle(PreviewPressStyle())
    }

    private var trainingOverview: some View {
        NativeCard {
            NativeErrorText(message: overview.error)
            HStack {
                Text("训练概览").font(.headline).accessibilityAddTraits(.isHeader)
                Spacer(minLength: 5)
                NavigationLink("训练历史") { NativeWorkoutHistory() }
                    .font(.footnote.weight(.semibold))
                    .frame(minHeight: 44)
            }
            if !overview.value.isNull {
                let training = overview.value["training"]
                LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 8), count: typeSize.isAccessibilitySize ? 2 : 3), spacing: 8) {
                    statistic("训练次数", value: training["workout_count"].text, symbol: "dumbbell", tint: NativeTheme.accent)
                    statistic("训练分钟", value: training["total_duration_minutes"].text, symbol: "timer", tint: NutrientKind.protein.labelColor)
                    statistic("个人纪录", value: training["pr_count"].text, symbol: "trophy", tint: NutrientKind.carbs.labelColor)
                }
            } else if overview.loading {
                ProgressView().accessibilityLabel("正在读取训练概览")
            }
        }
    }

    private func statistic(_ title: String, value: String, symbol: String, tint: Color) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Image(systemName: symbol).font(.footnote.weight(.semibold)).foregroundStyle(tint).accessibilityHidden(true)
            Text(value.isEmpty ? "—" : value).font(.system(.title3, design: .rounded, weight: .bold)).monospacedDigit()
            Text(title).font(.caption).foregroundStyle(NativeTheme.muted)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(10)
        .background(tint.opacity(0.08), in: RoundedRectangle(cornerRadius: 13))
        .accessibilityElement(children: .combine)
    }

    private func measurementRow(_ measurement: NativeJSON) -> some View {
        NativeCard {
            HStack(alignment: .center, spacing: 11) {
                NativeActionIcon(symbol: "scalemass", tint: NativeTheme.accent)
                VStack(alignment: .leading, spacing: 4) {
                    Text(measurement["weight_kg"].isNull ? "身体测量" : session.weightText(measurement["weight_kg"].double))
                        .font(.headline).monospacedDigit()
                    Text(NativeDates.display(measurement["measured_at"].text))
                        .font(.caption).foregroundStyle(NativeTheme.muted)
                }
                Spacer(minLength: 0)
                Image(systemName: "chevron.right").font(.caption).foregroundStyle(NativeTheme.muted).accessibilityHidden(true)
            }
            if !measurement["waist_cm"].isNull || !measurement["body_fat_percent"].isNull {
                let waist = measurement["waist_cm"]
                let fat = measurement["body_fat_percent"]
                let values = [
                    waist.isNull ? nil : "腰围 " + session.lengthText(waist.double),
                    fat.isNull ? nil : "体脂 " + fat.text + "%"
                ].compactMap { $0 }
                Text(values.joined(separator: " · ")).font(.caption).foregroundStyle(NativeTheme.muted)
            }
        }
        .foregroundStyle(NativeTheme.ink)
    }

    private func personalRecordValue(_ record: NativeJSON) -> String {
        switch record["record_type"].text {
        case "max_weight": return session.weightText(record["value"].double)
        case "max_reps": return record["value"].text + " 次"
        default: return record["value"].text
        }
    }

    private func converted(_ value:Double) -> Double { metric == "weight" ? session.displayWeight(value) : (metric == "waist" ? session.displayLength(value) : value) }
    private var range: [String:String] { ["start_date":NativeDates.day(Date().addingTimeInterval(-Double(days-1)*86400)),"end_date":NativeDates.day()] }
    private func loadTrend() async { await trend.load { var query = range; query["metric"] = metric; query["window"] = days >= 60 ? "14d" : "7d"; return try await session.api("progress/body-trend",query:query) } }
    private func load() async {
        await overview.load { try await session.api("progress/overview",query:range) }
        await measurements.load { .array(try await session.allPages("body/measurements")) }
        await records.load { .array(try await session.allPages("progress/prs")) }
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
    @State private var lastWeight: Double?
    @State private var initialized = false

    var body: some View {
        ScrollView {
            VStack(spacing: 14) {
                weightCard
                NativeCard {
                    DatePicker("测量时间", selection: $date).environment(\.timeZone, NativeDates.china)
                }
                NativeCard {
                    DisclosureGroup("围度、体脂和备注") {
                        VStack(spacing: 10) {
                            NativeField(title: "腰围（\(session.lengthUnit)）", text: $waist, keyboard: .decimalPad)
                            NativeField(title: "颈围（\(session.lengthUnit)）", text: $neck, keyboard: .decimalPad)
                            NativeField(title: "臀围（\(session.lengthUnit)）", text: $hip, keyboard: .decimalPad)
                            NativeField(title: "体脂率（%）", text: $fat, keyboard: .decimalPad)
                            NativeField(title: "测量条件", text: $conditions)
                            NativeField(title: "备注", text: $notes)
                        }.padding(.top, 8)
                    }.font(.subheadline)
                }
            }.nativePage()
        }
        .background(NativeTheme.background)
        .scrollDismissesKeyboard(.interactively)
        .safeAreaInset(edge: .bottom, spacing: 0) {
            NativeActionButton(title: "保存身体记录", action: save)
                .disabled([weight, waist, neck, hip, fat].allSatisfy { $0.isEmpty })
                .padding(.horizontal, 18).padding(.vertical, 7).background(.regularMaterial)
        }
        .navigationTitle(existing.isNull ? "记体重" : "编辑测量")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear(perform: prepare)
        .task { await readLastWeight() }
        .nativeDraft("measurement" + (existing.isNull ? "" : "-" + existing.id), label: "身体测量", value: formDraft, restore: restore)
    }

    private var weightCard: some View {
        NativeCard {
            VStack(spacing: 10) {
                NativeActionIcon(symbol: "scalemass.fill", tint: NativeTheme.accent, size: 48)
                Text("体重").font(.subheadline.weight(.semibold)).foregroundStyle(NativeTheme.muted)
                HStack(spacing: 8) {
                    weightStep(-0.1)
                    HStack(alignment: .firstTextBaseline, spacing: 4) {
                        TextField("—", text: $weight)
                            .keyboardType(.decimalPad)
                            .multilineTextAlignment(.trailing)
                            .font(.system(.largeTitle, design: .rounded, weight: .bold))
                            .monospacedDigit()
                            .frame(maxWidth: 130, minHeight: 48)
                            .accessibilityLabel("体重，" + session.weightUnit)
                        Text(session.weightUnit).font(.subheadline.weight(.semibold)).foregroundStyle(NativeTheme.muted)
                    }
                    weightStep(0.1)
                }
                if let lastWeight, weight.isEmpty {
                    Button {
                        weight = NativeQuantity.format(lastWeight, decimals: 3)
                    } label: {
                        Label("用上次的 \(NativeQuantity.format(lastWeight, decimals: 2)) \(session.weightUnit)", systemImage: "clock.arrow.circlepath")
                            .font(.footnote.weight(.semibold)).frame(minHeight: 44)
                    }.buttonStyle(PreviewPressStyle())
                }
            }.frame(maxWidth: .infinity).padding(.vertical, 10)
        }
    }

    private func weightStep(_ change: Double) -> some View {
        Button {
            guard let current = NativeQuantity.number(weight), current + change > 0 else { return }
            weight = NativeQuantity.format(current + change, decimals: 3)
        } label: {
            NativeActionIcon(symbol: change < 0 ? "minus" : "plus", tint: NativeTheme.accent, size: 44)
        }
        .buttonStyle(PreviewPressStyle())
        .disabled(NativeQuantity.number(weight) == nil)
        .accessibilityLabel((change < 0 ? "减去 0.1 " : "增加 0.1 ") + session.weightUnit)
    }

    private func prepare() {
        guard !initialized else { return }
        initialized = true
        guard !existing.isNull else { return }
        date = NativeDates.parse(existing["measured_at"].text) ?? .now
        if !existing["weight_kg"].isNull { weight = NativeQuantity.format(session.displayWeight(existing["weight_kg"].double), decimals: 3) }
        if !existing["waist_cm"].isNull { waist = NativeQuantity.format(session.displayLength(existing["waist_cm"].double), decimals: 3) }
        if !existing["neck_cm"].isNull { neck = NativeQuantity.format(session.displayLength(existing["neck_cm"].double), decimals: 3) }
        if !existing["hip_cm"].isNull { hip = NativeQuantity.format(session.displayLength(existing["hip_cm"].double), decimals: 3) }
        fat = existing["body_fat_percent"].text
        conditions = existing["conditions"].text
        notes = existing["notes"].text
    }

    private func readLastWeight() async {
        guard existing.isNull,
              let result = try? await session.api("body/measurements", query: ["page_size": "10"]),
              let recent = result.records.first(where: { !$0["weight_kg"].isNull })
        else { return }
        lastWeight = session.displayWeight(recent["weight_kg"].double)
    }

    private func restore(_ value: NativeJSON) {
        guard existing.isNull else { return }
        initialized = true
        date = NativeDates.parse(value["time"].text) ?? .now
        weight = value["weight"].text
        waist = value["waist"].text
        neck = value["neck"].text
        hip = value["hip"].text
        fat = value["fat"].text
        conditions = value["conditions"].text
        notes = value["notes"].text
    }

    private func measurement(_ text: String, title: String, limit: Double, convert: (Double) -> Double = { $0 }) throws -> NativeJSON {
        if text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { return .null }
        guard let value = NativeQuantity.number(text), value > 0, convert(value) <= limit else {
            throw NativeAPIError.message("请填写有效的\(title)。")
        }
        return .number(convert(value))
    }

    private func save(_ key: String) async throws {
        let measuredWeight = try measurement(weight, title: "体重", limit: 500, convert: session.toKG)
        let measuredWaist = try measurement(waist, title: "腰围", limit: 400, convert: session.toCM)
        let measuredNeck = try measurement(neck, title: "颈围", limit: 200, convert: session.toCM)
        let measuredHip = try measurement(hip, title: "臀围", limit: 400, convert: session.toCM)
        let measuredFat = try measurement(fat, title: "体脂率", limit: 70)
        guard [measuredWeight, measuredWaist, measuredNeck, measuredHip, measuredFat].contains(where: { !$0.isNull }) else {
            throw NativeAPIError.message("请至少填写一项测量值。")
        }
        let unchangedFat = measuredFat.double == existing["body_fat_percent"].double
        let method = unchangedFat && !existing["body_fat_method"].isNull ? existing["body_fat_method"] : .string("manual")
        let creating = existing.isNull
        var body: [String: NativeJSON] = [
            "measured_at": .string(NativeDates.timestamp(date)), "weight_kg": measuredWeight,
            "waist_cm": measuredWaist, "neck_cm": measuredNeck, "hip_cm": measuredHip,
            "body_fat_percent": measuredFat, "body_fat_method": measuredFat.isNull ? .null : method,
            "source": existing["source"].isNull ? .string("manual") : existing["source"],
            "conditions": conditions.isEmpty ? .null : .string(conditions), "notes": notes.isEmpty ? .null : .string(notes)
        ]
        if !creating {
            body["expected_version"] = .int(existing.version)
            body["reason"] = .string("用户修改身体测量记录")
        }
        _ = try await session.api(creating ? "body/measurements" : "body/measurements/" + existing.id,
                                  method: creating ? "POST" : "PATCH", body: body, key: key, draftKey: creating ? "measurement" : nil)
        onSave()
        dismiss()
    }

    private var formDraft: NativeJSON {
        .object(["time": .string(NativeDates.timestamp(date)), "weight": .string(weight),
                 "waist": .string(waist), "neck": .string(neck), "hip": .string(hip), "fat": .string(fat),
                 "conditions": .string(conditions), "notes": .string(notes)])
    }
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
