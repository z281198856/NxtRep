import SwiftUI

@MainActor
final class NativeResource: ObservableObject {
    @Published var value: NativeJSON = .null
    @Published var loading = false
    @Published var loadedAt: Date?
    @Published var error: String?
    private var revision = UUID()

    func load(_ operation: () async throws -> NativeJSON) async {
        let id = UUID()
        revision = id
        loading = true
        do {
            let response = try await operation()
            guard id == revision else { return }
            value = response
            loadedAt = .now
            error = nil
        } catch {
            guard id == revision else { return }
            self.error = NativeSession.readable(error)
        }
        if id == revision { loading = false }
    }
}

struct NativeCard<Content: View>: View {
    @ViewBuilder var content: () -> Content
    var body: some View {
        VStack(alignment: .leading, spacing: 12, content: content)
            .frame(maxWidth: .infinity, alignment: .leading).padding(16)
            .background(NativeTheme.surface, in: RoundedRectangle(cornerRadius: 20))
            .overlay(RoundedRectangle(cornerRadius: 20).strokeBorder(NativeTheme.line))
    }
}

struct NativeErrorText: View {
    let message: String?
    var body: some View { if let message { Text(message).font(.subheadline).foregroundStyle(.red).textSelection(.enabled) } }
}

struct NativeActionButton: View {
    let title: String
    var role: ButtonRole? = nil
    let action: (String) async throws -> Void
    @State private var busy = false
    @State private var error: String?
    @State private var requestID = UUID().uuidString

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Button(role: role) {
                guard !busy else { return }
                busy = true
                error = nil
                Task {
                    do { try await action(requestID); requestID = UUID().uuidString }
                    catch { self.error = NativeSession.readable(error) }
                    busy = false
                }
            } label: {
                HStack {
                    if busy { ProgressView() }
                    Text(busy ? "处理中…" : title)
                }
                .frame(maxWidth: .infinity, minHeight: 44)
            }
            .buttonStyle(.borderedProminent).disabled(busy)
            NativeErrorText(message: error)
        }
    }
}

struct NativeField: View {
    let title: String
    @Binding var text: String
    var keyboard: UIKeyboardType = .default
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title).font(.caption).foregroundStyle(NativeTheme.muted)
            TextField(title, text: $text).keyboardType(keyboard).textFieldStyle(.roundedBorder)
        }
    }
}

struct NativeDayPicker: View {
    @EnvironmentObject private var session: NativeSession
    var body: some View {
        DatePicker("记录日期", selection: $session.selectedDate, displayedComponents: .date)
            .environment(\.timeZone, NativeDates.china).datePickerStyle(.compact)
    }
}

enum NativeLabels {
    static let muscles = ["chest":"胸部", "upper_back":"上背", "lats":"背阔肌", "back":"背部", "shoulders":"肩部", "front_delts":"三角肌前束", "side_delts":"三角肌中束", "rear_delts":"三角肌后束", "biceps":"肱二头肌", "triceps":"肱三头肌", "forearms":"前臂", "quads":"股四头肌", "quadriceps":"股四头肌", "hamstrings":"腘绳肌", "glutes":"臀肌", "calves":"小腿", "abs":"腹肌", "core":"核心", "obliques":"腹斜肌", "lower_back":"下背", "adductors":"内收肌", "abductors":"外展肌"]
    static let equipment = ["barbell":"杠铃", "dumbbell":"哑铃", "cable":"绳索", "machine":"器械", "smith_machine":"史密斯机", "bodyweight":"自重", "kettlebell":"壶铃", "resistance_band":"弹力带", "other":"其他"]
    static let meals = ["breakfast":"早餐", "lunch":"午餐", "dinner":"晚餐", "snack":"加餐", "other":"其他"]
    static let statuses = ["active":"进行中", "paused":"已暂停", "completed":"已完成", "abandoned":"已放弃", "planned":"待训练", "pending":"待确认", "approved":"已确认", "rejected":"已拒绝", "succeeded":"已执行", "failed":"未完成", "expired":"已过期", "archived":"已归档", "draft":"草稿"]
    static func muscle(_ value: String) -> String { muscles[value] ?? value }
    static func tool(_ value: String) -> String { equipment[value] ?? value }
    static func status(_ value: String) -> String { statuses[value] ?? value }
    static func split(_ text: String) -> [String] { text.components(separatedBy: CharacterSet(charactersIn: ",，、\n")).map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty } }
}

struct NativeMealPicker: View {
    @Binding var selection: String
    var body: some View {
        Picker("餐次", selection: $selection) {
            ForEach(["breakfast", "lunch", "dinner", "snack", "other"], id: \.self) { Text(NativeLabels.meals[$0] ?? $0).tag($0) }
        }
    }
}

extension View {
    func nativePage() -> some View { self.padding(18).frame(maxWidth: .infinity, alignment: .leading).background(NativeTheme.background) }
}
