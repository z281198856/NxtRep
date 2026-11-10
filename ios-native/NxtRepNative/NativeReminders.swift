import SwiftUI
import UserNotifications

enum NativeReminderKind: String,CaseIterable,Codable,Identifiable {
    case training,breakfast,lunch,dinner,water,measurement
    var id:String { rawValue }
    var title:String { ["training":"训练","breakfast":"早餐记录","lunch":"午餐记录","dinner":"晚餐记录","water":"饮水","measurement":"身体数据"][rawValue]! }
    var destination:String { switch self { case .training:"training"; case .water:"water"; case .measurement:"progress"; default:"nutrition" } }
    var message:String {
        switch self {
        case .training:"到你设置的训练时间了，打开查看安排，按状态决定是否训练。"
        case .water:"到你设置的饮水提醒时间了，按需要补充水分，也可以记录饮水。"
        case .measurement:"到你设置的身体数据记录时间了，可按相近条件测量并记录。"
        default:"到你设置的\(title)时间了，可按实际情况补记。"
        }
    }
}
struct NativeReminderRule: Codable,Identifiable {
    var kind:NativeReminderKind
    var enabled = false
    var times:[Int]
    var weekdays:[Int]
    var id:String { kind.rawValue }
}
struct NativeReminderConfig: Codable {
    var enabled = false
    var hidePreview = true
    var quietEnabled = true
    var quietStart = 1320
    var quietEnd = 480
    var rules = [
        NativeReminderRule(kind:.training,times:[1080],weekdays:[1,3,5]),
        NativeReminderRule(kind:.breakfast,times:[480],weekdays:Array(1...7)),
        NativeReminderRule(kind:.lunch,times:[720],weekdays:Array(1...7)),
        NativeReminderRule(kind:.dinner,times:[1080],weekdays:Array(1...7)),
        NativeReminderRule(kind:.water,times:[540,660,840,960,1080],weekdays:Array(1...7)),
        NativeReminderRule(kind:.measurement,times:[510],weekdays:[1])
    ]
    func isQuiet(_ time:Int)->Bool { quietEnabled && (quietStart < quietEnd ? time >= quietStart && time < quietEnd : time >= quietStart || time < quietEnd) }
    func slots() throws -> [(NativeReminderKind,Int,Int)] {
        guard (0..<1440).contains(quietStart),(0..<1440).contains(quietEnd),!quietEnabled || quietStart != quietEnd,rules.count == 6,Set(rules.map(\.kind)).count == 6 else { throw NativeAPIError.message("请核对提醒和勿扰设置。") }
        var slots: [(NativeReminderKind,Int,Int)] = []
        for rule in rules {
            guard (1...6).contains(rule.times.count),Set(rule.times).count == rule.times.count,rule.times.allSatisfy({(0..<1440).contains($0)}),!rule.weekdays.isEmpty,rule.weekdays.allSatisfy({(1...7).contains($0)}),Set(rule.weekdays).count == rule.weekdays.count else { throw NativeAPIError.message("请为每类提醒选择有效且不重复的时间和星期。") }
            if enabled && rule.enabled {
                for time in rule.times where !isQuiet(time) {
                    for day in rule.weekdays.count == 7 ? [0] : rule.weekdays.sorted() { slots.append((rule.kind,time,day)) }
                }
            }
        }
        guard slots.count <= 63 else { throw NativeAPIError.message("提醒安排超过系统限制，请减少时间或星期后保存。") }
        return slots
    }
}

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
