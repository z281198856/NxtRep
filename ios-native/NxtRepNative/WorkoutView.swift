import Foundation
import SwiftUI

enum WorkoutMode: String, Hashable, Identifiable {
    case planned
    case free

    var id: String { rawValue }

    var title: String {
        switch self {
        case .planned: "上肢力量"
        case .free: "自主训练"
        }
    }
}

struct WorkoutView: View {
    let mode: WorkoutMode
    let onDismiss: () -> Void

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.scenePhase) private var scenePhase
    @State private var completedSets = 0
    @State private var rest: RestPeriod? = nil
    @State private var feedback: String? = nil
    @State private var feedbackSequence = 0

    private let totalSets = 4
    private let restSeconds: TimeInterval = 45
    private let extraRestSeconds: TimeInterval = 15

    private struct RestPeriod {
        var deadline: Date
        var duration: TimeInterval

        func remaining(at date: Date) -> TimeInterval {
            max(0, min(duration, deadline.timeIntervalSince(date)))
        }
    }

    private var isComplete: Bool { completedSets == totalSets }
    private var nextSet: Int { completedSets + 1 }

    private var status: String {
        if isComplete { return "已完成" }
        if rest != nil { return "休息中" }
        return "训练中"
    }

    private var actionTitle: String {
        if isComplete { return "再练一次" }
        if rest != nil { return "跳过休息，开始下一组" }
        return "完成第 \(nextSet) 组"
    }

    private var motion: Animation? {
        reduceMotion ? nil : .snappy(duration: 0.28, extraBounce: 0)
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                header
                exerciseCard
            }
            .padding(.horizontal, 22)
            .padding(.top, 10)
            .padding(.bottom, 24)
            .frame(maxWidth: 560)
            .frame(maxWidth: .infinity)
        }
        .scrollBounceBehavior(.basedOnSize)
        .background(NativeTheme.background.ignoresSafeArea())
        .safeAreaInset(edge: .bottom, spacing: 0) { workoutActions }
        .toolbar(.hidden, for: .navigationBar)
        .sensoryFeedback(.success, trigger: feedbackSequence)
        .onChange(of: scenePhase) { _, phase in
            if phase == .active, let rest, rest.deadline <= .now {
                finishRest("休息结束，准备下一组")
            }
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Button(action: onDismiss) {
                    Label("返回", systemImage: "chevron.left")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(NativeTheme.accent)
                        .frame(minWidth: 44, minHeight: 44, alignment: .leading)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                Spacer()
                Text("演示数据")
                    .font(.caption)
                    .foregroundStyle(NativeTheme.muted)
            }
            HStack(alignment: .top, spacing: 12) {
                VStack(alignment: .leading, spacing: 5) {
                    Text("今日训练")
                        .font(.subheadline)
                        .foregroundStyle(NativeTheme.muted)
                    Text(mode.title)
                        .font(.largeTitle.bold())
                        .foregroundStyle(NativeTheme.ink)
                        .accessibilityAddTraits(.isHeader)
                }
                Spacer(minLength: 0)
                Text(status)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(NativeTheme.accent)
                    .padding(.horizontal, 11)
                    .padding(.vertical, 6)
                    .background(NativeTheme.softAccent, in: Capsule())
            }
        }
    }

    private var exerciseCard: some View {
        VStack(alignment: .leading, spacing: 16) {
            ViewThatFits(in: .horizontal) {
                HStack(alignment: .firstTextBaseline, spacing: 10) {
                    exerciseTitle.fixedSize(horizontal: true, vertical: false)
                    Spacer(minLength: 0)
                    setCount.fixedSize(horizontal: true, vertical: false)
                }
                VStack(alignment: .leading, spacing: 5) {
                    exerciseTitle
                    setCount
                }
            }
            HStack(spacing: 5) {
                ForEach(0..<totalSets, id: \.self) { index in
                    Capsule()
                        .fill(index < completedSets ? NativeTheme.accent : NativeTheme.line)
                        .frame(height: 4)
                }
            }
            .accessibilityHidden(true)

            Divider().overlay(NativeTheme.line)

            if isComplete {
                Label("全部计划组数已完成", systemImage: "checkmark.circle.fill")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(NativeTheme.accent)
            } else {
                VStack(alignment: .leading, spacing: 12) {
                    Text(rest == nil ? "第 \(nextSet) 组" : "下一组 · 第 \(nextSet) 组")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(NativeTheme.ink)
                        .contentTransition(reduceMotion ? .identity : .numericText())
                    HStack(alignment: .top, spacing: 16) {
                        metric(label: "重量", number: "55", unit: "kg")
                        Rectangle()
                            .fill(NativeTheme.line)
                            .frame(width: 1, height: 46)
                            .accessibilityHidden(true)
                        metric(label: "次数", number: "8", unit: "次")
                    }
                }
            }
        }
        .padding(18)
        .background(NativeTheme.surface, in: RoundedRectangle(cornerRadius: 20))
        .overlay {
            RoundedRectangle(cornerRadius: 20)
                .strokeBorder(NativeTheme.line, lineWidth: 1)
                .allowsHitTesting(false)
        }
    }

    private var exerciseTitle: some View {
        Text("杠铃卧推")
            .font(.title3.weight(.semibold))
            .foregroundStyle(NativeTheme.ink)
            .accessibilityAddTraits(.isHeader)
    }

    private var setCount: some View {
        Text("已完成 \(completedSets) / \(totalSets) 组")
            .font(.footnote.monospacedDigit())
            .foregroundStyle(NativeTheme.muted)
            .contentTransition(reduceMotion ? .identity : .numericText())
    }

    private func metric(label: String, number: String, unit: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(label)
                .font(.caption)
                .foregroundStyle(NativeTheme.muted)
            HStack(alignment: .firstTextBaseline, spacing: 4) {
                Text(number)
                    .font(.title.weight(.semibold).monospacedDigit())
                    .foregroundStyle(NativeTheme.ink)
                Text(unit)
                    .font(.caption)
                    .foregroundStyle(NativeTheme.muted)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
    }

    private var workoutActions: some View {
        VStack(alignment: .leading, spacing: 10) {
            if let feedback {
                Text(feedback)
                    .font(.footnote)
                    .foregroundStyle(NativeTheme.accent)
            }
            if let rest {
                restPanel(rest)
                    .transition(reduceMotion ? .identity : .move(edge: .bottom).combined(with: .opacity))
            }
            Button(action: performAction) {
                Text(actionTitle)
                    .font(.headline)
                    .foregroundStyle(.white)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 12)
                    .frame(maxWidth: .infinity, minHeight: 52)
                    .background(NativeTheme.hero, in: RoundedRectangle(cornerRadius: 13))
            }
            .buttonStyle(PreviewPressStyle())
        }
        .padding(.horizontal, 22)
        .padding(.vertical, 12)
        .frame(maxWidth: 560)
        .frame(maxWidth: .infinity)
        .background(NativeTheme.background)
    }

    private func restPanel(_ period: RestPeriod) -> some View {
        TimelineView(.periodic(from: .now, by: 0.2)) { context in
            let remaining = period.remaining(at: context.date)
            let seconds = Int(ceil(remaining))
            VStack(alignment: .leading, spacing: 8) {
                HStack(alignment: .center, spacing: 8) {
                    VStack(alignment: .leading, spacing: 3) {
                        Text("组间休息")
                            .font(.caption)
                            .foregroundStyle(NativeTheme.muted)
                        Text(String(format: "%02d:%02d", seconds / 60, seconds % 60))
                            .font(.title.weight(.semibold).monospacedDigit())
                            .foregroundStyle(NativeTheme.ink)
                            .contentTransition(reduceMotion ? .identity : .numericText(countsDown: true))
                            .animation(motion, value: seconds)
                            .accessibilityLabel("剩余 \(seconds) 秒")
                    }
                    Spacer(minLength: 0)
                    Button(action: extendRest) {
                        Text("+15 秒")
                            .font(.subheadline.weight(.semibold))
                            .foregroundStyle(NativeTheme.accent)
                            .padding(.horizontal, 12)
                            .frame(minHeight: 44)
                            .background(NativeTheme.surface, in: RoundedRectangle(cornerRadius: 10))
                    }
                    .buttonStyle(PreviewPressStyle())
                    .accessibilityLabel("延长休息 15 秒")
                }
                ProgressView(value: remaining, total: period.duration)
                    .progressViewStyle(.linear)
                    .tint(NativeTheme.accent)
                    .animation(reduceMotion ? nil : .linear(duration: 0.2), value: remaining)
                    .accessibilityHidden(true)
            }
            .padding(14)
            .background(NativeTheme.softAccent, in: RoundedRectangle(cornerRadius: 15))
            .onChange(of: seconds, initial: true) { _, value in
                if value == 0, rest?.deadline == period.deadline {
                    finishRest("休息结束，准备下一组")
                }
            }
        }
    }

    private func performAction() {
        if isComplete {
            withAnimation(motion) {
                completedSets = 0
                feedback = nil
            }
        } else if rest != nil {
            finishRest(nil)
        } else {
            withAnimation(motion) {
                completedSets += 1
                feedbackSequence += 1
                if isComplete {
                    feedback = "第 \(completedSets) 组已记录，训练完成"
                } else {
                    feedback = "第 \(completedSets) 组已记录"
                    rest = RestPeriod(deadline: .now.addingTimeInterval(restSeconds), duration: restSeconds)
                }
            }
        }
    }

    private func finishRest(_ message: String?) {
        withAnimation(motion) {
            rest = nil
            feedback = message
        }
    }

    private func extendRest() {
        guard var period = rest else { return }
        guard period.deadline > .now else {
            finishRest("休息结束，准备下一组")
            return
        }
        period.deadline = period.deadline.addingTimeInterval(extraRestSeconds)
        period.duration += extraRestSeconds
        withAnimation(motion) { rest = period }
    }
}
