import SwiftUI

struct NativeAppShell: View {
    @EnvironmentObject private var session:NativeSession
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @ObservedObject private var reminders = NativeReminders.shared
    @State private var selection:AppTab = .today
    @State private var notificationSheet:String?
    @State private var showLocal = false
    var body: some View {
        VStack(spacing: 0) {
            TabView(selection:$selection) {
                ForEach(AppTab.allCases) { tab in
                    NavigationStack { page(tab) }.tag(tab).toolbar(.hidden,for:.tabBar)
                }
            }
            .toolbar(.hidden,for:.tabBar)
            .frame(maxHeight: .infinity)

            VStack(spacing:0) {
                if let local = session.local { NativeSyncBanner(store:local,onOpen:{showLocal = true}) }
                TabDock(selection:selection) { tab in withAnimation(reduceMotion ? nil : .smooth(duration:0.25)) { selection = tab } }.padding(.horizontal,10).padding(.vertical,5)
            }
        }
        .background(NativeTheme.background)
        .sheet(isPresented:Binding(get:{notificationSheet != nil},set:{if !$0 { notificationSheet = nil }})) {
            NavigationStack { if notificationSheet == "water" { NativeWaterView() } else { NativeMeasurementForm(onSave:{notificationSheet = nil}) } }
        }
        .sheet(isPresented:$showLocal) { NavigationStack { NativeLocalRecordsView() } }
        .onChange(of:reminders.route) { _,route in
            guard let route else { return }; session.selectedDate = .now
            switch route { case "training":selection = .plan; case "nutrition":selection = .meals; case "progress":selection = .progress; notificationSheet = "progress"; case "water":selection = .meals; notificationSheet = "water"; default:break }
            reminders.route = nil
        }
        .onChange(of:session.selectedDate) { _,_ in Task { await session.reload() } }
        .onChange(of:scenePhase) { _,phase in if phase == .active { Task { await session.reload(); _ = await session.syncLocal(); if let local = session.local { await reminders.activate(local) } } } }
        .task {
            if let local = session.local { await reminders.activate(local) }
            while !Task.isCancelled && session.signedIn {
                _ = await session.syncLocal()
                do { try await Task.sleep(for:.seconds(30)) } catch { break }
            }
        }
        .tint(NativeTheme.accent)
    }
    @ViewBuilder private func page(_ tab:AppTab)->some View {
        switch tab {
        case .today:NativeHomeView()
        case .plan:NativePlanHub()
        case .meals:NativeNutritionView()
        case .progress:NativeProgressView()
        case .coach:NativeCoachView()
        case .account:NativeProfileView()
        }
    }
}

private struct NativeSyncBanner: View {
    @ObservedObject var store:NativeLocalStore
    let onOpen:()->Void
    var body: some View {
        if !store.pending.isEmpty || store.usingCache || store.storageError != nil {
            Button(action:onOpen) {
                HStack { Image(systemName:store.syncing ? "arrow.triangle.2.circlepath" : "icloud.and.arrow.up"); Text(store.storageError ?? (store.pending.isEmpty ? "正在显示本机缓存" : "\(store.pending.count) 条记录待同步")); Spacer(); Image(systemName:"chevron.right") }.font(.caption).padding(8)
            }
        }
    }
}

struct NativeHomeView: View {
    @EnvironmentObject private var session: NativeSession
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.dynamicTypeSize) private var typeSize
    @StateObject private var resource = NativeResource()
    @State private var revision = 0
    @State private var showNutrition = false
    @State private var showWater = false

    private var day: String { NativeDates.day(session.selectedDate) }
    private var summary: DailySummary? { session.summary?.date == day ? session.summary : nil }
    private var workout: NativeJSON { resource.value["workout"] }
    private var events: [NativeJSON] {
        resource.value["date"].text == day ? resource.value["events"].records : []
    }
    private var shortcutColumns: [GridItem] {
        Array(repeating: GridItem(.flexible(), spacing: 9), count: typeSize.isAccessibilitySize ? 2 : 3)
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                heading
                NativeErrorText(message:session.error ?? resource.error)
                NativeDailyNutritionCard(summary: summary, onNutrient: { kind in
                    if kind == .water { showWater = true }
                    else { showNutrition = true }
                })
                LazyVGrid(columns: shortcutColumns, spacing: 9) {
                    entry("记一餐", icon: "fork.knife", color: NutrientKind.carbs.labelColor) { NativeMealEditor(onSave: {}) }
                    Button { showWater = true } label: {
                        NativeIconTile(title: "记饮水", icon: "drop.fill", tint: NutrientKind.water.labelColor)
                    }
                    .buttonStyle(PreviewPressStyle())
                    entry("记体重", icon: "scalemass.fill", color: NativeTheme.accent) { NativeMeasurementForm(onSave: {}) }
                }
                if !workout.isNull {
                    NavigationLink { NativeWorkoutScreen(workoutID: workout.id) } label: { activeWorkout }
                        .buttonStyle(PreviewPressStyle())
                }
                agenda
                Text("常用工具").font(.headline).accessibilityAddTraits(.isHeader)
                LazyVGrid(columns: shortcutColumns, spacing: 9) {
                    entry("食品库", icon: "carrot.fill", color: NutrientKind.carbs.labelColor) { NativeFoodLibrary() }
                    entry("动作库", icon: "figure.strengthtraining.traditional", color: NativeTheme.accent) { NativeExerciseLibrary() }
                    entry("拍照记餐", icon: "camera.fill", color: NutrientKind.protein.labelColor) { NativeNutritionPhotoView() }
                    entry("训练历史", icon: "clock.arrow.circlepath", color: NativeTheme.accent) { NativeWorkoutHistory() }
                    entry("照片与报告", icon: "photo.on.rectangle", color: NutrientKind.fat.labelColor) { NativeBodyPhotoLibrary() }
                    entry("离线记录", icon: "icloud.and.arrow.up", color: NutrientKind.water.labelColor) { NativeLocalRecordsView() }
                }
            }.nativePage()
        }.background(NativeTheme.background).navigationBarHidden(true)
        .task(id:"\(day)|\(revision)") { await load() }
        .refreshable { await session.reload(); await load() }
        .onChange(of:scenePhase) { _,phase in if phase == .active { revision += 1 } }
        .sheet(isPresented:$showNutrition) { NavigationStack { NativeNutritionView() } }
        .sheet(isPresented:$showWater) { NavigationStack { NativeWaterView() } }
    }
    private var heading: some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack(spacing: 8) {
                Image("BrandMark").resizable().scaledToFit()
                    .frame(width: 26, height: 26).clipShape(RoundedRectangle(cornerRadius: 7))
                    .accessibilityHidden(true)
                Text("NxtRep").font(.subheadline.weight(.semibold))
                Spacer()
                NavigationLink { NativeCoachNoticesView() } label: {
                    NativeActionIcon(symbol: "bell.badge", tint: NativeTheme.accent, size: 44)
                }
                .buttonStyle(PreviewPressStyle())
                .accessibilityLabel("主动教练建议")
            }
            HStack(alignment: .center, spacing: 8) {
                Text(day == NativeDates.day() ? "今天" : "记录总览")
                    .font(.system(.largeTitle, design: .rounded, weight: .bold))
                    .accessibilityAddTraits(.isHeader)
                Spacer(minLength: 0)
                NativeDayPicker().labelsHidden().fixedSize()
            }
        }
        .foregroundStyle(NativeTheme.ink)
    }

    private var activeWorkout: some View {
        HStack(spacing: 12) {
            NativeActionIcon(symbol: "dumbbell.fill", tint: .white, size: 44)
            VStack(alignment: .leading, spacing: 4) {
                Text("继续训练").font(.headline)
                Text("\(workout["exercises"].values.count) 个动作")
                    .font(.footnote).foregroundStyle(.white.opacity(0.75))
            }
            Spacer(minLength: 0)
            Image(systemName: "arrow.up.right").font(.subheadline.weight(.semibold)).accessibilityHidden(true)
        }
        .foregroundStyle(.white)
        .padding(14)
        .background(NativeTheme.hero, in: RoundedRectangle(cornerRadius: 20))
    }

    private var agenda: some View {
        NativeCard {
            HStack {
                Text("当天安排").font(.headline).accessibilityAddTraits(.isHeader)
                Spacer()
                NavigationLink { NativeCalendarView() } label: {
                    Label("日历", systemImage: "calendar").font(.footnote.weight(.semibold))
                        .frame(minHeight: 44)
                }
            }
            ForEach(events, id: \.id) { event in
                NavigationLink { NativeCalendarEvent(eventID: event.id) } label: {
                    HStack(spacing: 10) {
                        NativeActionIcon(symbol: "dumbbell", tint: NativeTheme.accent)
                        VStack(alignment: .leading, spacing: 3) {
                            Text(event["title"].text).font(.subheadline.weight(.semibold)).foregroundStyle(NativeTheme.ink)
                            Text(NativeLabels.status(event["status"].text) + " · " + event["estimated_minutes"].text + " 分钟")
                                .font(.caption).foregroundStyle(NativeTheme.muted)
                        }
                        Spacer(minLength: 0)
                        Image(systemName: "chevron.right").font(.caption).foregroundStyle(NativeTheme.muted)
                    }
                    .frame(minHeight: 44).contentShape(Rectangle())
                }
                .buttonStyle(PreviewPressStyle())
            }
            if events.isEmpty && resource.loading {
                ProgressView().accessibilityLabel("正在读取日程")
            } else if events.isEmpty && resource.error == nil {
                Label("这一天没有训练安排", systemImage: "moon.stars")
                    .font(.subheadline).foregroundStyle(NativeTheme.muted)
            }
            NavigationLink { NativeWorkoutStart() } label: {
                Label("自主开练", systemImage: "play.fill").frame(maxWidth: .infinity, minHeight: 32)
            }
            .buttonStyle(.borderedProminent)
        }
    }

    private func entry<Destination: View>(_ name: String, icon: String, color: Color, @ViewBuilder destination: () -> Destination) -> some View {
        NavigationLink(destination: destination) { NativeIconTile(title: name, icon: icon, tint: color) }
            .buttonStyle(PreviewPressStyle())
    }
    private func load() async {
        await resource.load {
            let day = self.day
            let events = try await session.api("calendar",query:["start_date":day,"end_date":day])
            let current:NativeJSON
            do { current = try await session.api("workouts/active") }
            catch NativeAPIError.response(let code,let name) where code == 404 && name == "WORKOUT_NOT_FOUND" { current = .null }
            return .object(["date": .string(day), "events": events, "workout": current])
        }
    }
}
