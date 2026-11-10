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
        TabView(selection:$selection) {
            ForEach(AppTab.allCases) { tab in
                NavigationStack { page(tab) }.tag(tab).toolbar(.hidden,for:.tabBar)
            }
        }
        .toolbar(.hidden,for:.tabBar)
        .safeAreaInset(edge:.bottom,spacing:0) {
            VStack(spacing:0) {
                if let local = session.local { NativeSyncBanner(store:local,onOpen:{showLocal = true}) }
                TabDock(selection:selection) { tab in withAnimation(reduceMotion ? nil : .smooth(duration:0.25)) { selection = tab } }.padding(.horizontal,10).padding(.vertical,5)
            }.background(NativeTheme.background)
        }
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
    @EnvironmentObject private var session:NativeSession
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var resource = NativeResource()
    @State private var revision = 0
    @State private var showNutrition = false
    @State private var showWater = false
    private var workout:NativeJSON { resource.value["workout"] }
    private var events:[NativeJSON] { resource.value["events"].records }
    var body: some View {
        ScrollView {
            VStack(alignment:.leading,spacing:18) {
                HStack {
                    Image("BrandMark").resizable().scaledToFit().frame(width:30,height:30).clipShape(RoundedRectangle(cornerRadius:8))
                    Text("NxtRep").font(.title2.bold()); Spacer()
                    NavigationLink { NativeCoachNoticesView() } label: { Image(systemName:"bell.badge").frame(width:44,height:44) }.accessibilityLabel("主动教练建议")
                }
                Text("每一次，向前一点。").font(.system(size:28,weight:.bold,design:.rounded))
                NativeDayPicker()
                NativeErrorText(message:session.error ?? resource.error)
                nutritionCard
                if !workout.isNull {
                    NavigationLink { NativeWorkoutScreen(workoutID:workout.id) } label: {
                        NativeCard {
                            HStack { Label("继续训练",systemImage:"dumbbell.fill").font(.title3.bold()); Spacer(); Image(systemName:"arrow.up.right") }
                            Text(NativeLabels.status(workout["status"].text)+" · \(workout["exercises"].values.count) 个动作").foregroundStyle(NativeTheme.muted)
                        }
                    }.buttonStyle(.plain)
                }
                HStack { Text("当天安排").font(.title3.bold()); Spacer(); NavigationLink("日历") { NativeCalendarView() } }
                ForEach(events,id:\.id) { event in
                    NavigationLink { NativeCalendarEvent(eventID:event.id) } label: {
                        NativeCard { HStack { VStack(alignment:.leading,spacing:5) { Text(event["title"].text).font(.headline); Text(NativeLabels.status(event["status"].text)+" · "+event["estimated_minutes"].text+" 分钟").font(.caption).foregroundStyle(NativeTheme.muted) }; Spacer(); Image(systemName:"chevron.right") } }
                    }.buttonStyle(.plain)
                }
                if events.isEmpty && !resource.loading { Text("这一天没有安排，可以休息或自主开练。").font(.subheadline).foregroundStyle(NativeTheme.muted) }
                NavigationLink { NativeWorkoutStart() } label: { Label("自主开练",systemImage:"play.fill").frame(maxWidth:.infinity,minHeight:48) }.buttonStyle(.borderedProminent)
                Text("记录与工具").font(.title3.bold())
                LazyVGrid(columns:[GridItem(.flexible()),GridItem(.flexible())],spacing:12) {
                    entry("食物库",icon:"carrot",color:.orange) { NativeFoodLibrary() }
                    entry("动作库",icon:"figure.strengthtraining.traditional",color:.purple) { NativeExerciseLibrary() }
                    entry("拍照记餐",icon:"camera",color:.green) { NativeNutritionPhotoView() }
                    entry("训练历史",icon:"clock.arrow.circlepath",color:.brown) { NativeWorkoutHistory() }
                    entry("身体测量",icon:"ruler",color:.blue) { NativeMeasurementForm(onSave:{}) }
                    entry("照片与报告",icon:"photo.on.rectangle",color:.indigo) { NativeBodyPhotoLibrary() }
                }
                NavigationLink("离线记录与草稿") { NativeLocalRecordsView() }.font(.caption)
            }.nativePage()
        }.background(NativeTheme.background).navigationBarHidden(true)
        .task(id:"\(NativeDates.day(session.selectedDate))|\(revision)") { await load() }
        .refreshable { await session.reload(); await load() }
        .onChange(of:scenePhase) { _,phase in if phase == .active { revision += 1 } }
        .sheet(isPresented:$showNutrition) { NavigationStack { NativeNutritionView() } }
        .sheet(isPresented:$showWater) { NavigationStack { NativeWaterView() } }
    }
    private var nutritionCard:some View {
        NativeCard {
            HStack { Text("今日补给").font(.headline); Spacer(); Text(session.summary.map { "\(Int($0.consumed.kcal.value.rounded())) 千卡" } ?? "暂无数据").font(.subheadline).monospacedDigit() }
            if let summary = session.summary {
                HStack(spacing:10) { ForEach(NutrientKind.allCases) { kind in NutrientRing(kind:kind,amount:summary.amount(kind),usesLiveData:true,goal:summary.goal(kind)) { if kind == .water { showWater = true } else { showNutrition = true } } } }
                Text(summary.target == nil ? "尚未设置营养目标，可在饮食页查看记录与建议。" : "圆环按个人目标上限显示，点击查看明细。").font(.caption2).foregroundStyle(NativeTheme.muted)
            } else { Text("连接后显示这一天的实际营养与饮水记录。").font(.subheadline).foregroundStyle(NativeTheme.muted) }
            HStack { NavigationLink("记一餐") { NativeMealEditor(onSave:{}) }; Spacer(); Button("记饮水") { showWater = true } }.font(.subheadline.bold()).frame(minHeight:36)
        }
    }
    private func entry<Destination:View>(_ name:String,icon:String,color:Color,@ViewBuilder destination:()->Destination)->some View {
        NavigationLink(destination:destination) { NativeCard { Image(systemName:icon).font(.title2).foregroundStyle(color); Text(name).font(.subheadline.bold()).foregroundStyle(NativeTheme.ink) } }.buttonStyle(.plain)
    }
    private func load() async {
        await resource.load {
            let day = NativeDates.day(session.selectedDate)
            let events = try await session.api("calendar/events",query:["start_date":day,"end_date":day])
            let current:NativeJSON
            do { current = try await session.api("workouts/active") }
            catch NativeAPIError.response(let code,let name) where code == 404 && name == "WORKOUT_NOT_FOUND" { current = .null }
            return .object(["events":events,"workout":current])
        }
    }
}
