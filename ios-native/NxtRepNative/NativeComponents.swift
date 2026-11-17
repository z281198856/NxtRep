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

struct NativeActionIcon: View {
    let symbol: String
    let tint: Color
    var size: CGFloat = 36

    var body: some View {
        Image(systemName: symbol)
            .font(.system(size: size * 0.43, weight: .semibold))
            .foregroundStyle(tint)
            .frame(width: size, height: size)
            .background(tint.opacity(0.10), in: RoundedRectangle(cornerRadius: size * 0.35))
            .accessibilityHidden(true)
    }
}

struct NativeIconTile: View {
    let title: String
    let icon: String
    let tint: Color

    var body: some View {
        VStack(spacing: 6) {
            NativeActionIcon(symbol: icon, tint: tint)
            Text(title)
                .font(.caption.weight(.semibold))
                .foregroundStyle(NativeTheme.ink)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, minHeight: 70)
        .padding(.horizontal, 3)
        .padding(.vertical, 3)
        .background(NativeTheme.surface, in: RoundedRectangle(cornerRadius: 18))
        .overlay(RoundedRectangle(cornerRadius: 18).strokeBorder(NativeTheme.line))
        .contentShape(RoundedRectangle(cornerRadius: 18))
        .accessibilityElement(children: .combine)
    }
}

enum NativeQuantity {
    static func number(_ text: String) -> Double? {
        let normalized = text.trimmingCharacters(in: .whitespacesAndNewlines).replacingOccurrences(of: ",", with: ".")
        guard let value = Double(normalized), value.isFinite else { return nil }
        return value
    }

    static func format(_ value: Double, decimals: Int) -> String {
        value.formatted(.number.grouping(.never).precision(.fractionLength(0...decimals)))
    }
}

struct NativeQuantityChoices: View {
    let values: [Int]
    let unit: String
    @Binding var value: String
    let tint: Color

    var body: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 63), spacing: 7)], spacing: 7) {
            ForEach(values, id: \.self) { option in
                let selected = NativeQuantity.number(value) == Double(option)
                Button { value = String(option) } label: {
                    Text("\(option) \(unit)")
                        .font(.caption.weight(.semibold)).monospacedDigit()
                        .multilineTextAlignment(.center)
                        .foregroundStyle(selected ? .white : tint)
                        .frame(maxWidth: .infinity, minHeight: 44)
                        .background(selected ? tint : tint.opacity(0.10), in: RoundedRectangle(cornerRadius: 12))
                }
                .buttonStyle(PreviewPressStyle())
                .accessibilityAddTraits(selected ? .isSelected : [])
            }
        }
    }
}

struct NativeDailyNutritionCard: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.dynamicTypeSize) private var typeSize
    let summary: DailySummary?
    var title = "当日营养"
    var showTargets = false
    var onNutrient: ((NutrientKind) -> Void)? = nil

    var body: some View {
        NativeCard {
            if let summary {
                let calories = summary.consumed.kcal.value.rounded()
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(title).font(.subheadline.weight(.semibold)).foregroundStyle(NativeTheme.muted)
                        HStack(alignment: .firstTextBaseline, spacing: 5) {
                            Text(calories.formatted(.number.precision(.fractionLength(0))))
                                .font(.system(.largeTitle, design: .rounded, weight: .bold))
                                .monospacedDigit()
                                .foregroundStyle(NativeTheme.ink)
                                .contentTransition(reduceMotion ? .identity : .numericText(value: calories))
                            Text("千卡").font(.footnote.weight(.semibold)).foregroundStyle(NativeTheme.muted)
                        }
                        .accessibilityElement(children: .combine)
                    }
                    Spacer(minLength: 8)
                    NativeActionIcon(symbol: "flame.fill", tint: NutrientKind.carbs.labelColor, size: 44)
                }
                LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 10), count: typeSize.isAccessibilitySize ? 2 : 4), spacing: 12) {
                    ForEach(NutrientKind.allCases) { kind in
                        NutrientRing(
                            kind: kind,
                            amount: summary.amount(kind),
                            usesLiveData: true,
                            goal: summary.goal(kind),
                            onTap: onNutrient.map { action in { action(kind) } }
                        )
                    }
                }
                .animation(reduceMotion ? nil : .easeInOut(duration: 0.25), value: calories)
                if showTargets, let target = summary.target {
                    targetRanges(target)
                }
            } else {
                Label(title, systemImage: "chart.donut").font(.headline).foregroundStyle(NativeTheme.ink)
                Text("暂无当日数据").font(.subheadline).foregroundStyle(NativeTheme.muted)
            }
        }
    }

    private func targetRanges(_ target: [String: APINumber]) -> some View {
        DisclosureGroup("每日目标") {
            ForEach(["kcal", "carbs", "protein", "fat"], id: \.self) { metric in
                let unit = metric == "kcal" ? " 千卡" : " 克"
                let suffix = metric == "kcal" ? "" : "_g"
                if let low = target[metric + "_min" + suffix]?.value,
                   let high = target[metric + "_max" + suffix]?.value {
                    let lower = low.formatted(.number.precision(.fractionLength(0...1)))
                    let upper = high.formatted(.number.precision(.fractionLength(0...1)))
                    LabeledContent(["kcal": "热量", "carbs": "碳水", "protein": "蛋白质", "fat": "脂肪"][metric] ?? metric,
                                   value: lower + "–" + upper + unit)
                        .font(.footnote)
                        .padding(.top, 5)
                }
            }
        }
        .font(.footnote.weight(.medium))
        .foregroundStyle(NativeTheme.muted)
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
    static let muscles = ["chest":"胸部", "upper_back":"上背", "lats":"背阔肌", "back":"背部", "shoulders":"肩部", "front_delts":"三角肌前束", "side_delts":"三角肌中束", "rear_delts":"三角肌后束", "biceps":"肱二头肌", "triceps":"肱三头肌", "forearms":"前臂", "quads":"股四头肌", "quadriceps":"股四头肌", "hamstrings":"腘绳肌", "glutes":"臀肌", "gluteus":"臀肌", "trapezius":"斜方肌", "hip_flexors":"髋屈肌", "calves":"小腿", "abs":"腹肌", "core":"核心", "obliques":"腹斜肌", "lower_back":"下背", "adductors":"内收肌", "abductors":"外展肌"]
    static let equipment = ["barbell":"杠铃", "dumbbell":"哑铃", "cable":"绳索", "machine":"器械", "smith_machine":"史密斯机", "bodyweight":"自重", "kettlebell":"壶铃", "resistance_band":"弹力带", "band":"弹力带", "other":"其他"]
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
