import SwiftUI

struct DemoMeal: Identifiable {
    let name: String
    let calories: Int
    let carbs: Int
    let protein: Int
    let fat: Int

    var id: String { name }
}

enum DemoNutrition {
    static let meals = [
        DemoMeal(name: "早餐", calories: 480, carbs: 56, protein: 28, fat: 16),
        DemoMeal(name: "午餐", calories: 800, carbs: 92, protein: 54, fat: 24)
    ]

    static var calories: Int { meals.reduce(0) { $0 + $1.calories } }

    static func amount(for kind: NutrientKind, waterML: Int) -> Int {
        switch kind {
        case .carbs: meals.reduce(0) { $0 + $1.carbs }
        case .protein: meals.reduce(0) { $0 + $1.protein }
        case .fat: meals.reduce(0) { $0 + $1.fat }
        case .water: waterML
        }
    }
}

enum NutrientKind: String, CaseIterable, Identifiable {
    case carbs, protein, fat, water

    var id: String { rawValue }

    var title: String {
        switch self {
        case .carbs: "碳水"
        case .protein: "蛋白质"
        case .fat: "脂肪"
        case .water: "饮水"
        }
    }

    var unit: String { self == .water ? "毫升" : "克" }
    var ringUnit: String { self == .water ? "升" : unit }

    var upperGoal: Int {
        switch self {
        case .carbs: 240
        case .protein: 120
        case .fat: 65
        case .water: 2_000
        }
    }

    var goalLabel: String {
        switch self {
        case .carbs: "200–240 克"
        case .protein: "95–120 克"
        case .fat: "50–65 克"
        case .water: "2,000 毫升"
        }
    }

    var color: Color {
        switch self {
        case .carbs: NativeTheme.color(0xDA9853)
        case .protein: NativeTheme.color(0x54A990)
        case .fat: NativeTheme.color(0xD57999)
        case .water: NativeTheme.color(0x609ADE)
        }
    }

    var labelColor: Color {
        switch self {
        case .carbs: NativeTheme.color(0x975620)
        case .protein: NativeTheme.color(0x2C715C)
        case .fat: NativeTheme.color(0xA14768)
        case .water: NativeTheme.color(0x2B669B)
        }
    }

    func ringValue(_ amount: Int) -> String {
        if self == .water {
            return (Double(amount) / 1_000).formatted(.number.precision(.fractionLength(0...2)))
        }
        return amount.formatted()
    }
}

struct TodayView: View {
    let waterML: Int
    var summary: DailySummary? = nil
    var connected: Bool = false
    let onStart: () -> Void
    let onNutrient: (NutrientKind) -> Void
    let onEntry: (DemoFeature) -> Void
    let onMeals: () -> Void
    let onProgress: () -> Void

    private let columns = Array(repeating: GridItem(.flexible(), spacing: 6), count: 3)

    private var dateLabel: String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "zh_CN")
        formatter.dateFormat = "M月d日 EEEE"
        return formatter.string(from: .now)
    }

    var body: some View {
        VStack(spacing: 12) {
            HStack(alignment: .firstTextBaseline) {
                Text("今日")
                    .font(.system(.largeTitle, weight: .bold))
                    .accessibilityAddTraits(.isHeader)
                Spacer()
                Text(dateLabel)
                    .font(.footnote)
                    .foregroundStyle(NativeTheme.muted)
            }
            PlannedWorkoutCard(onStart: onStart)
            nutritionCard
            quickEntries
            progressButton
        }
        .foregroundStyle(NativeTheme.ink)
    }

    private var nutritionCard: some View {
        VStack(spacing: 9) {
            HStack {
                Text("今日营养").font(.headline)
                Spacer()
                Button(action: onMeals) {
                    Label("查看记录", systemImage: "chevron.right")
                        .labelStyle(TrailingIconLabelStyle())
                        .font(.caption)
                        .foregroundStyle(NativeTheme.accent)
                        .frame(minHeight: 44)
                }
                .buttonStyle(PreviewPressStyle())
            }
            Divider()
            HStack {
                HStack(alignment: .firstTextBaseline, spacing: 4) {
                    Text((summary.map { Int($0.consumed.kcal.value.rounded()) } ?? DemoNutrition.calories).formatted())
                        .font(.title3.weight(.semibold)).monospacedDigit()
                    Text("千卡").font(.caption).foregroundStyle(NativeTheme.muted)
                }
                Spacer()
                Button {
                    onNutrient(.water)
                } label: {
                    Label("记饮水", systemImage: "drop")
                        .font(.caption.weight(.medium))
                        .foregroundStyle(NutrientKind.water.labelColor)
                        .frame(minHeight: 44)
                }
                .buttonStyle(PreviewPressStyle())
            }
            HStack(spacing: 3) {
                ForEach(NutrientKind.allCases) { kind in
                    NutrientRing(kind: kind,
                                 amount: summary?.amount(kind) ?? DemoNutrition.amount(for: kind, waterML: waterML),
                                 usesLiveData: connected, goal: summary?.goal(kind)) {
                        onNutrient(kind)
                    }
                }
            }
        }
        .padding(.horizontal, 12)
        .padding(.top, 3)
        .padding(.bottom, 12)
        .background(NativeTheme.surface, in: RoundedRectangle(cornerRadius: 21))
        .overlay(RoundedRectangle(cornerRadius: 21).strokeBorder(NativeTheme.line))
    }

    private var quickEntries: some View {
        VStack(alignment: .leading, spacing: 7) {
            Text("快速开始").font(.subheadline.weight(.semibold)).accessibilityAddTraits(.isHeader)
            LazyVGrid(columns: columns, spacing: 6) {
                ForEach(DemoContent.quickEntries) { entry in
                    Button {
                        onEntry(entry)
                    } label: {
                        VStack(spacing: 4) {
                            Image(systemName: entry.icon)
                                .font(.system(size: 14, weight: .medium))
                                .foregroundStyle(entry.tint)
                                .frame(width: 25, height: 25)
                                .background(entry.tint.opacity(0.1), in: RoundedRectangle(cornerRadius: 8))
                            Text(entry.quickTitle ?? entry.title)
                                .font(.caption2.weight(.semibold))
                                .foregroundStyle(NativeTheme.ink)
                                .lineLimit(2)
                                .multilineTextAlignment(.center)
                        }
                        .frame(maxWidth: .infinity, minHeight: 50)
                        .padding(.vertical, 3)
                        .background(NativeTheme.surface, in: RoundedRectangle(cornerRadius: 13))
                        .overlay(RoundedRectangle(cornerRadius: 13).strokeBorder(NativeTheme.line))
                    }
                    .buttonStyle(PreviewPressStyle())
                }
            }
        }
    }

    private var progressButton: some View {
        Button(action: onProgress) {
            HStack(spacing: 10) {
                Image(systemName: "chart.line.uptrend.xyaxis")
                    .font(.system(size: 16, weight: .medium))
                    .foregroundStyle(NativeTheme.accent)
                    .frame(width: 34, height: 34)
                    .background(NativeTheme.softAccent, in: RoundedRectangle(cornerRadius: 10))
                VStack(alignment: .leading, spacing: 3) {
                    Text("本周进展").font(.subheadline.weight(.semibold))
                    Text(connected ? "训练进展界面预览" : "完成 2 次训练").font(.caption).foregroundStyle(NativeTheme.muted)
                }
                Spacer()
                Image(systemName: "chevron.right").font(.caption).foregroundStyle(NativeTheme.muted)
            }
            .foregroundStyle(NativeTheme.ink)
            .padding(10)
            .background(NativeTheme.surface, in: RoundedRectangle(cornerRadius: 17))
            .overlay(RoundedRectangle(cornerRadius: 17).strokeBorder(NativeTheme.line))
        }
        .buttonStyle(PreviewPressStyle())
    }
}

struct PlannedWorkoutCard: View {
    let onStart: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("今日计划").font(.footnote).foregroundStyle(NativeTheme.color(0xBFC8DC))
                Spacer()
                Label("待开始", systemImage: "circle.fill")
                    .font(.caption2.weight(.medium))
                    .foregroundStyle(NativeTheme.color(0xDBE4FF))
                    .padding(.horizontal, 8)
                    .padding(.vertical, 5)
                    .overlay(Capsule().strokeBorder(NativeTheme.color(0x4A556D)))
            }
            Text("上肢力量").font(.title2.weight(.bold))
            Text("杠铃卧推 · 4 组").font(.subheadline).foregroundStyle(NativeTheme.color(0xBFC8DC))
            Button(action: onStart) {
                Label("开始训练", systemImage: "arrow.right")
                    .labelStyle(TrailingIconLabelStyle())
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(NativeTheme.hero)
                    .padding(.horizontal, 13)
                    .frame(minHeight: 44)
                    .background(NativeTheme.color(0xE2EAFF), in: RoundedRectangle(cornerRadius: 11))
            }
            .buttonStyle(PreviewPressStyle())
            .padding(.top, 4)
        }
        .foregroundStyle(Color.white)
        .padding(15)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(NativeTheme.hero, in: RoundedRectangle(cornerRadius: 21))
    }
}

private struct TrailingIconLabelStyle: LabelStyle {
    func makeBody(configuration: Configuration) -> some View {
        HStack(spacing: 6) {
            configuration.title
            configuration.icon
        }
    }
}

struct NutrientRing: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var fill: CGFloat = 0

    let kind: NutrientKind
    let amount: Int
    var usesLiveData: Bool = false
    var goal: Int? = nil
    let onTap: () -> Void

    private var fraction: CGFloat {
        let limit = usesLiveData ? goal : kind.upperGoal
        guard let limit, limit > 0 else { return 0 }
        return CGFloat(min(1, max(0, Double(amount) / Double(limit))))
    }

    var body: some View {
        Button(action: onTap) {
            VStack(spacing: 7) {
                ZStack {
                    Circle().stroke(kind.color.opacity(0.17), lineWidth: 4)
                    Circle()
                        .trim(from: 0, to: fill)
                        .stroke(kind.color, style: StrokeStyle(lineWidth: 4, lineCap: .round))
                        .rotationEffect(.degrees(-90))
                    VStack(spacing: 2) {
                        Text(kind.ringValue(amount))
                            .font(.system(.body, design: .rounded, weight: .semibold))
                            .monospacedDigit()
                            .lineLimit(1)
                            .minimumScaleFactor(0.55)
                            .contentTransition(reduceMotion ? .identity : .numericText(value: Double(amount)))
                        Text(kind.ringUnit)
                            .font(.caption2)
                            .foregroundStyle(NativeTheme.muted)
                    }
                    .padding(.horizontal, 7)
                }
                .aspectRatio(1, contentMode: .fit)
                .frame(maxWidth: 59)
                .padding(3)
                Text(kind.title)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(kind.labelColor)
                    .lineLimit(1)
                    .minimumScaleFactor(0.8)
            }
            .frame(maxWidth: .infinity, minHeight: 44)
            .contentShape(Rectangle())
            .foregroundStyle(NativeTheme.ink)
        }
        .buttonStyle(PreviewPressStyle())
        .accessibilityLabel(kind.title)
        .accessibilityValue(usesLiveData ? "\(amount.formatted()) \(kind.unit)" : "\(amount.formatted()) \(kind.unit)，示例目标 \(kind.goalLabel)")
        .onAppear { updateFill() }
        .onChange(of: fraction) { updateFill() }
    }

    private func updateFill() {
        withAnimation(reduceMotion ? nil : .smooth(duration: 0.65)) { fill = fraction }
    }
}

struct NutrientDetailSheet: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Binding var waterRecords: [Int]
    let kind: NutrientKind

    private var amount: Int {
        DemoNutrition.amount(for: kind, waterML: waterRecords.reduce(0, +))
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 13) {
                HStack {
                    Text("今日" + kind.title).font(.headline)
                    Spacer()
                    Button("完成") { dismiss() }.frame(minHeight: 44)
                }
                HStack(alignment: .firstTextBaseline, spacing: 5) {
                    Text(amount.formatted())
                        .font(.system(.largeTitle, design: .rounded, weight: .semibold))
                        .monospacedDigit()
                        .contentTransition(reduceMotion ? .identity : .numericText(value: Double(amount)))
                    Text(kind.unit).foregroundStyle(NativeTheme.muted)
                }
                Text("示例目标 " + kind.goalLabel)
                    .font(.subheadline)
                    .foregroundStyle(NativeTheme.muted)
                if kind == .water {
                    Button {
                        withAnimation(reduceMotion ? nil : .smooth(duration: 0.35)) {
                            waterRecords.append(250)
                        }
                    } label: {
                        Label("记 250 毫升", systemImage: "drop.fill")
                            .font(.subheadline.weight(.semibold))
                            .foregroundStyle(Color.white)
                            .frame(maxWidth: .infinity, minHeight: 46)
                            .background(kind.labelColor, in: RoundedRectangle(cornerRadius: 12))
                    }
                    .buttonStyle(PreviewPressStyle())
                    Text("\(waterRecords.count) 次示例记录")
                        .font(.caption)
                        .foregroundStyle(NativeTheme.muted)
                } else {
                    Text("两餐示例记录合计，圆环按目标上限填充")
                        .font(.caption)
                        .foregroundStyle(NativeTheme.muted)
                }
            }
            .foregroundStyle(NativeTheme.ink)
            .padding(22)
        }
        .presentationDetents([.medium, .large])
        .presentationDragIndicator(.visible)
    }
}
