import SwiftUI

struct NativeCoachNoticesView: View {
    @EnvironmentObject private var session:NativeSession
    @StateObject private var resource = NativeResource()
    @State private var revision = 0
    var body: some View {
        ScrollView { VStack(alignment:.leading,spacing:14) {
            NavigationLink("主动教练设置") { NativeCoachSettingsView() }
            NativeErrorText(message:resource.error)
            if resource.loading { ProgressView("正在读取建议…") }
            ForEach(resource.value.records,id:\.id) { notice in
                NativeCard {
                    Text(notice["title"].text).font(.headline)
                    Text(notice["body"].text)
                    destination(notice["data"]["route"].text)
                    HStack {
                        NativeActionButton(title:"已读") { _ in _ = try await session.api("notifications/"+notice.id+"/read",method:"POST"); revision += 1 }
                        Menu("稍后提醒") {
                            Button("1 小时后") { snooze(notice,seconds:3600) }
                            Button("明天") { snooze(notice,seconds:86400) }
                        }.frame(minHeight:44)
                    }
                    HStack {
                        NativeActionButton(title:"有帮助") { _ in _ = try await session.api("agent/proactive/notices/"+notice.id+"/feedback",method:"PUT",body:["rating":.string("helpful")]); revision += 1 }
                        NativeActionButton(title:"暂不需要") { _ in _ = try await session.api("agent/proactive/notices/"+notice.id+"/feedback",method:"PUT",body:["rating":.string("not_relevant")]); revision += 1 }
                        NativeActionButton(title:"不准确") { _ in _ = try await session.api("agent/proactive/notices/"+notice.id+"/feedback",method:"PUT",body:["rating":.string("inaccurate")]); revision += 1 }
                    }
                }
            }
            if !resource.loading && resource.value.records.isEmpty { ContentUnavailableView("暂无主动建议",systemImage:"sparkles",description:Text("可在设置中开启主动教练，并选择建议范围。")) }
        }.nativePage() }.navigationTitle("主动建议")
        .task(id:revision) { await load() }.refreshable { await load() }
    }
    private func load() async {
        await resource.load {
            let settings = try await session.api("notification-settings")
            guard settings["enabled"].flag,settings["categories"]["proactive_coach"].flag else { return .array([]) }
            _ = try await session.api("agent/proactive/review",method:"POST")
            let notices = try await session.allPages("notifications",query:["unread_only":"true","category":"proactive_coach"],limit:20)
            return .array(notices.filter { settings["frequency"].text != "important_only" || $0["data"]["kind"].text != "nutrition_log_gap" })
        }
    }
    private func snooze(_ notice:NativeJSON,seconds:Double) {
        Task { do { _ = try await session.api("agent/proactive/notices/"+notice.id+"/snooze",method:"POST",body:["until":.string(NativeDates.timestamp(Date().addingTimeInterval(seconds)))]); revision += 1 } catch { resource.error = NativeSession.readable(error) } }
    }
    @ViewBuilder private func destination(_ route:String) -> some View {
        switch route {
        case "training","plan": NavigationLink("查看训练安排") { NativePlanHub() }
        case "nutrition": NavigationLink("查看饮食记录") { NativeNutritionView() }
        case "progress": NavigationLink("查看身体进展") { NativeProgressView() }
        default: NavigationLink("与教练讨论") { NativeCoachView() }
        }
    }
}

struct NativeCoachSettingsView: View {
    @EnvironmentObject private var session:NativeSession
    @State private var current:NativeJSON = .null
    @State private var enabled = false
    @State private var frequency = "important_only"
    @State private var quietEnabled = true
    @State private var start = 22*60
    @State private var end = 8*60
    @State private var error:String?
    @State private var pauseUntil:String?
    var body: some View {
        Form {
            NativeErrorText(message:error)
            Toggle("主动教练",isOn:$enabled)
            Text("根据已有训练和记录生成建议；涉及实际记录或计划的改动仍需你确认。").font(.footnote).foregroundStyle(NativeTheme.muted)
            Picker("建议范围",selection:$frequency) { Text("重要事项").tag("important_only"); Text("每日建议").tag("daily") }
            Toggle("勿扰时段",isOn:$quietEnabled)
            NativeMinutePicker(title:"勿扰开始",minute:$start)
            NativeMinutePicker(title:"勿扰结束",minute:$end)
            Text("主动教练按上海时间处理勿扰时段。").font(.caption)
            if let pauseUntil { Text("暂停至 "+NativeDates.display(pauseUntil)).font(.caption) }
            Button("暂停一天") { pauseUntil = NativeDates.timestamp(Date().addingTimeInterval(86400)) }
            Button("恢复提醒") { pauseUntil = nil }
            NativeActionButton(title:"保存主动教练设置") { _ in
                guard !current.isNull,!quietEnabled || start != end else { throw NativeAPIError.message("请设置不同的勿扰开始与结束时间。") }
                var categories = current["categories"].fields; categories["proactive_coach"] = .bool(enabled)
                var quiet = current["quiet_hours"].fields
                quiet["enabled"] = .bool(quietEnabled); quiet["start"] = .string(Self.time(start)); quiet["end"] = .string(Self.time(end))
                quiet["timezone"] = .string("Asia/Shanghai"); quiet["pause_until"] = pauseUntil.map(NativeJSON.string) ?? .null
                current = try await session.api("notification-settings",method:"PATCH",body:["enabled":.bool(enabled || current["enabled"].flag),"categories":.object(categories),"frequency":.string(frequency),"quiet_hours":.object(quiet),"expected_version":.int(current.version)])
            }.disabled(current.isNull)
            NavigationLink("本机系统提醒") { NativeReminderSettingsView() }
        }.navigationTitle("主动教练设置").task {
            do {
                current = try await session.api("notification-settings"); enabled = current["enabled"].flag && current["categories"]["proactive_coach"].flag; frequency = current["frequency"].text
                let quiet = current["quiet_hours"]
                pauseUntil = quiet["pause_until"].isNull ? nil : quiet["pause_until"].text
                if !quiet.isNull { quietEnabled = quiet["enabled"].flag; start = Self.minute(quiet["start"].text,default:1320); end = Self.minute(quiet["end"].text,default:480) }
            } catch { self.error = NativeSession.readable(error) }
        }
    }
    private static func time(_ value:Int)->String { String(format:"%02d:%02d",value/60,value%60) }
    private static func minute(_ text:String,default fallback:Int)->Int { let parts = text.split(separator:":").compactMap {Int($0)}; return parts.count == 2 ? parts[0]*60+parts[1] : fallback }
}
