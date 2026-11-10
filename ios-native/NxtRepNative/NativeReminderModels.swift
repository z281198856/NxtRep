import Foundation

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

