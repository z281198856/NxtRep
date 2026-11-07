import SwiftUI

@main
struct NxtRepNativeApp: App {
    var body: some Scene {
        WindowGroup {
            PreviewShell()
                .preferredColorScheme(.light)
        }
    }
}

private enum PreviewSheet: Identifiable {
    case nutrient(NutrientKind)
    case feature(DemoFeature)

    var id: String {
        switch self {
        case .nutrient(let kind): "nutrient:" + kind.id
        case .feature(let feature): "feature:" + feature.id
        }
    }
}

private struct PreviewShell: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var selectedTab: AppTab = .today
    @State private var activeSheet: PreviewSheet?
    @State private var workout: WorkoutMode?
    @State private var waterRecords = [350, 450, 400]

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                header
                ScrollView {
                    Group {
                        if selectedTab == .today {
                            TodayView(
                                waterML: waterRecords.reduce(0, +),
                                onStart: { workout = .planned },
                                onNutrient: { activeSheet = .nutrient($0) },
                                onEntry: openEntry,
                                onMeals: { select(.meals) },
                                onProgress: { select(.progress) }
                            )
                        } else {
                            FeatureTabView(
                                tab: selectedTab,
                                onEntry: openEntry,
                                onStartWorkout: { workout = .planned }
                            )
                        }
                    }
                    .padding(.horizontal, 20)
                    .padding(.top, 5)
                    .padding(.bottom, 12)
                }
                .id(selectedTab)
                .scrollIndicators(.hidden)
                .transition(.opacity)
            }
            .background(NativeTheme.background.ignoresSafeArea())
            .safeAreaInset(edge: .bottom, spacing: 0) {
                TabDock(selection: selectedTab, onSelect: select)
                    .padding(.horizontal, 10)
                    .padding(.vertical, 5)
                    .background(NativeTheme.background)
            }
            .toolbar(.hidden, for: .navigationBar)
            .navigationDestination(item: $workout) { mode in
                WorkoutView(mode: mode, onDismiss: { workout = nil })
            }
        }
        .tint(NativeTheme.accent)
        .sheet(item: $activeSheet) { sheet in
            switch sheet {
            case .nutrient(let kind):
                NutrientDetailSheet(waterRecords: $waterRecords, kind: kind)
            case .feature(let feature):
                FeatureDetailView(feature: feature)
            }
        }
    }

    private var header: some View {
        HStack(spacing: 8) {
            Image("BrandMark")
                .resizable()
                .scaledToFit()
                .frame(width: 25, height: 25)
                .clipShape(RoundedRectangle(cornerRadius: 7))
                .accessibilityHidden(true)
            Text("NxtRep").font(.system(.headline, design: .rounded, weight: .bold))
            Spacer()
            Text("演示数据").font(.caption2).foregroundStyle(NativeTheme.muted)
            Button {
                select(.account)
            } label: {
                Image(systemName: "person")
                    .font(.system(size: 15, weight: .medium))
                    .foregroundStyle(NativeTheme.accent)
                    .frame(width: 34, height: 34)
                    .background(NativeTheme.softAccent, in: RoundedRectangle(cornerRadius: 11))
                    .frame(width: 44, height: 44)
                    .contentShape(Rectangle())
            }
            .accessibilityLabel("打开我的")
            .buttonStyle(PreviewPressStyle())
        }
        .foregroundStyle(NativeTheme.ink)
        .padding(.horizontal, 20)
    }

    private func select(_ tab: AppTab) {
        guard selectedTab != tab else { return }
        withAnimation(reduceMotion ? nil : .smooth(duration: 0.28)) {
            selectedTab = tab
        }
    }

    private func openEntry(_ feature: DemoFeature) {
        switch feature.action {
        case .detail: activeSheet = .feature(feature)
        case .freeWorkout: workout = .free
        case .water: activeSheet = .nutrient(.water)
        case .coach: select(.coach)
        }
    }
}

private struct TabDock: View {
    @Namespace private var indicator
    let selection: AppTab
    let onSelect: (AppTab) -> Void

    var body: some View {
        HStack(spacing: 1) {
            ForEach(AppTab.allCases) { tab in
                Button {
                    onSelect(tab)
                } label: {
                    VStack(spacing: 4) {
                        Image(systemName: tab.icon)
                            .font(.system(size: 17, weight: .medium))
                            .foregroundStyle(tab.tint)
                        Text(tab.title)
                            .font(.caption2.weight(tab == selection ? .semibold : .regular))
                            .foregroundStyle(tab == selection ? tab.tint : NativeTheme.muted)
                            .lineLimit(1)
                            .minimumScaleFactor(0.75)
                    }
                    .frame(maxWidth: .infinity, minHeight: 45)
                    .contentShape(Rectangle())
                    .background {
                        if tab == selection {
                            RoundedRectangle(cornerRadius: 14)
                                .fill(tab.tint.opacity(0.12))
                                .matchedGeometryEffect(id: "selection", in: indicator)
                        }
                    }
                }
                .buttonStyle(PreviewPressStyle())
                .accessibilityLabel(tab.accessibilityTitle)
                .accessibilityAddTraits(tab == selection ? .isSelected : [])
            }
        }
        .padding(4)
        .background(NativeTheme.surface, in: RoundedRectangle(cornerRadius: 19))
        .overlay(RoundedRectangle(cornerRadius: 19).strokeBorder(NativeTheme.line))
    }
}
