import SwiftUI
import UserNotifications

@MainActor
final class NativeReminders: NSObject,ObservableObject,UNUserNotificationCenterDelegate {
    static let shared = NativeReminders()
    @Published private(set) var permission = "尚未读取"
    @Published var route:String?
    @Published var error:String?
    private var owner:String?
    private var pendingTap:(String,String)?
    private let center = UNUserNotificationCenter.current()
    private override init() { super.init(); center.delegate = self }
    func activate(_ store:NativeLocalStore) async {
        owner = store.scope
        if let tap = pendingTap,tap.0 == owner { route = tap.1; pendingTap = nil }
        do {
            let saved = store.draft("reminder-settings")["value"]
            let config = saved.isNull ? NativeReminderConfig() : try JSONDecoder().decode(NativeReminderConfig.self,from:JSONEncoder().encode(saved))
            try await schedule(config)
        } catch { self.error = NativeSession.readable(error) }
    }
    func deactivate() {
        owner = nil; route = nil
        center.removeAllPendingNotificationRequests(); center.removeAllDeliveredNotifications()
    }
    func status() async {
        let settings = await center.notificationSettings()
        switch settings.authorizationStatus { case .authorized,.provisional,.ephemeral:permission = "已允许"; case .denied:permission = "未允许，请在系统设置开启"; default:permission = "尚未申请" }
    }
    func authorize() async throws {
        guard try await center.requestAuthorization(options:[.alert,.sound,.badge]) else { await status(); throw NativeAPIError.message("系统通知未获允许，请到设置 → 通知 → NxtRep 开启。") }
        await status()
    }
    func schedule(_ config:NativeReminderConfig) async throws {
        let slots = try config.slots(),scope = owner
        await status()
        guard scope == owner,scope != nil else { return }
        center.removeAllPendingNotificationRequests()
        if !config.enabled { return }
        let settings = await center.notificationSettings()
        guard scope == owner,[UNAuthorizationStatus.authorized,.provisional,.ephemeral].contains(settings.authorizationStatus) else { return }
        for (kind,minute,day) in slots {
            guard scope == owner else { return }
            let content = UNMutableNotificationContent()
            content.title = config.hidePreview ? "NxtRep" : "NxtRep · "+kind.title
            content.body = config.hidePreview ? "你设置的提醒到了，打开 NxtRep 查看。" : kind.message
            content.sound = .default; content.userInfo = ["owner":scope!,"destination":kind.destination]
            var date = DateComponents(); date.calendar = Calendar(identifier:.gregorian); date.timeZone = .current; date.hour = minute/60; date.minute = minute%60
            if day != 0 { date.weekday = day%7+1 }
            let identifier = "nxtrep."+kind.rawValue+".\(minute).\(day)"
            try await center.add(UNNotificationRequest(identifier:identifier,content:content,trigger:UNCalendarNotificationTrigger(dateMatching:date,repeats:true)))
            if scope != owner { center.removePendingNotificationRequests(withIdentifiers:[identifier]); return }
        }
    }
    func test(hidePreview:Bool) async throws {
        try await authorize()
        guard let owner else { throw NativeAPIError.message("请先登录。") }
        let content = UNMutableNotificationContent(); content.title = "NxtRep"; content.body = hidePreview ? "你设置的提醒到了，打开 NxtRep 查看。" : "这是一条测试提醒，点击进入饮水记录。"; content.sound = .default
        content.userInfo = ["owner":owner,"destination":"water"]
        try await center.add(UNNotificationRequest(identifier:"nxtrep.test",content:content,trigger:UNTimeIntervalNotificationTrigger(timeInterval:10,repeats:false)))
    }
    nonisolated func userNotificationCenter(_ center:UNUserNotificationCenter,didReceive response:UNNotificationResponse,withCompletionHandler completionHandler:@escaping ()->Void) {
        let info = response.notification.request.content.userInfo,scope = info["owner"] as? String,destination = info["destination"] as? String
        Task { @MainActor in if let scope,let destination { if scope == self.owner { self.route = destination } else if self.owner == nil { self.pendingTap = (scope,destination) } } }
        completionHandler()
    }
    nonisolated func userNotificationCenter(_ center:UNUserNotificationCenter,willPresent notification:UNNotification,withCompletionHandler completionHandler:@escaping (UNNotificationPresentationOptions)->Void) {
        let scope = notification.request.content.userInfo["owner"] as? String
        Task { @MainActor in completionHandler(scope == self.owner && scope != nil ? [.banner,.sound] : []) }
    }
}

struct NativeMinutePicker: View {
    let title:String
    @Binding var minute:Int
    var body: some View {
        DatePicker(title,selection:Binding(get:{ Calendar.current.startOfDay(for:Date()).addingTimeInterval(Double(minute*60)) },set:{ let c = Calendar.current.dateComponents([.hour,.minute],from:$0); minute = (c.hour ?? 0)*60+(c.minute ?? 0) }),displayedComponents:.hourAndMinute)
    }
}

struct NativeReminderSettingsView: View {
    @EnvironmentObject private var session:NativeSession
    @ObservedObject private var reminders = NativeReminders.shared
    @State private var config = NativeReminderConfig()
    @State private var message:String?
    var body: some View {
        Form {
            Section("系统通知") {
                Text(reminders.permission)
                NativeActionButton(title:"申请通知权限") { _ in try await reminders.authorize() }
                Link("打开系统通知设置",destination:URL(string:UIApplication.openNotificationSettingsURLString)!)
            }
            Section {
                Toggle("开启本机系统提醒",isOn:$config.enabled)
                Toggle("隐藏通知内容",isOn:$config.hidePreview)
                Text("提醒保存在这台 iPhone，按本机时间执行。退出账号会撤销本机提醒，重新登录会恢复该账号的设置。").font(.footnote).foregroundStyle(NativeTheme.muted)
            }
            ForEach($config.rules) { $rule in
                Section(rule.kind.title) {
                    Toggle("开启"+rule.kind.title+"提醒",isOn:$rule.enabled)
                    if rule.enabled {
                        ForEach(rule.times.indices,id:\.self) { index in
                            HStack {
                                NativeMinutePicker(title:"提醒时间",minute:$rule.times[index])
                                if rule.times.count > 1 { Button(role:.destructive) { rule.times.remove(at:index) } label:{ Image(systemName:"minus.circle") }.buttonStyle(.borderless) }
                            }
                        }
                        if rule.times.count < 6 { Button("添加时间") { let next = (rule.times.last ?? 480)+60; rule.times.append(next%1440) } }
                        HStack { ForEach(1...7,id:\.self) { day in
                            Button(["一","二","三","四","五","六","日"][day-1]) { if rule.weekdays.contains(day) { if rule.weekdays.count > 1 { rule.weekdays.removeAll {$0 == day} } } else { rule.weekdays.append(day) } }
                                .buttonStyle(.bordered).tint(rule.weekdays.contains(day) ? NativeTheme.accent : .gray).frame(maxWidth:.infinity).accessibilityLabel("星期"+["一","二","三","四","五","六","日"][day-1])
                        } }
                    }
                }
            }
            Section("勿扰") {
                Toggle("开启勿扰时段",isOn:$config.quietEnabled)
                NativeMinutePicker(title:"开始",minute:$config.quietStart)
                NativeMinutePicker(title:"结束",minute:$config.quietEnd)
                Text("落在勿扰时段的提醒会跳过。").font(.caption).foregroundStyle(NativeTheme.muted)
            }
            Section {
                NativeActionButton(title:"保存提醒设置") { _ in
                    _ = try config.slots()
                    if config.enabled { try await reminders.authorize() }
                    let value = try JSONDecoder().decode(NativeJSON.self,from:JSONEncoder().encode(config))
                    try session.local?.saveDraft("reminder-settings",label:"本机提醒设置",value:value)
                    if let local = session.local { await reminders.activate(local) }
                    message = "设置已保存，勿扰时间内的安排会跳过。"
                }
                NativeActionButton(title:"10 秒后发送测试提醒") { _ in try await reminders.test(hidePreview:config.hidePreview); message = "测试提醒已安排，可暂时回到主屏幕等待。" }
                if let message { Text(message).font(.footnote) }
                NativeErrorText(message:reminders.error)
            }
        }.navigationTitle("本机系统提醒").task {
            do { let v = session.local?.draft("reminder-settings")["value"] ?? .null; if !v.isNull { config = try JSONDecoder().decode(NativeReminderConfig.self,from:JSONEncoder().encode(v)) }; await reminders.status() }
            catch { message = NativeSession.readable(error) }
        }
    }
}
