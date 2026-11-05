import Foundation
import ImageIO
import PhotosUI
import SwiftUI
import UIKit

struct FeatureTabView: View {
    let tab: AppTab
    let onEntry: (DemoFeature) -> Void
    let onStartWorkout: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(tab.heading)
                .font(.largeTitle.weight(.bold))
                .accessibilityAddTraits(.isHeader)
            tabSummary
            VStack(spacing: 8) {
                ForEach(DemoContent.entries(for: tab)) { feature in
                    entryButton(feature)
                }
            }
            if tab == .meals {
                mealRecords
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .foregroundStyle(NativeTheme.ink)
    }

    @ViewBuilder
    private var tabSummary: some View {
        switch tab {
        case .plan:
            PlannedWorkoutCard(onStart: onStartWorkout)
        case .progress:
            entryButton(DemoContent.trainingOverview)
        case .coach:
            VStack(alignment: .leading, spacing: 6) {
                Label("示例建议", systemImage: "sparkles")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(tab.tint)
                Text("今天是上肢训练日。先完成热身，再进入卧推工作组。按计划休息，再开始下一组。")
                    .font(.subheadline)
                    .lineSpacing(3)
            }
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(tab.tint.opacity(0.08), in: RoundedRectangle(cornerRadius: 17))
        case .account:
            Text("示例账号")
                .font(.subheadline)
                .foregroundStyle(NativeTheme.muted)
        case .today, .meals:
            EmptyView()
        }
    }

    private var mealRecords: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("今日餐次")
                .font(.headline)
                .accessibilityAddTraits(.isHeader)
            ForEach(DemoNutrition.meals) { meal in
                VStack(alignment: .leading, spacing: 5) {
                    HStack(alignment: .firstTextBaseline) {
                        Text(meal.name)
                        Spacer()
                        Text("\(meal.calories) 千卡")
                            .foregroundStyle(tab.tint)
                    }
                    .font(.subheadline.weight(.semibold))
                    Text("碳水 \(meal.carbs) 克 · 蛋白质 \(meal.protein) 克 · 脂肪 \(meal.fat) 克")
                        .font(.caption)
                        .foregroundStyle(NativeTheme.muted)
                }
                .padding(12)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(NativeTheme.surface, in: RoundedRectangle(cornerRadius: 15))
                .overlay(RoundedRectangle(cornerRadius: 15).strokeBorder(NativeTheme.line))
                .accessibilityElement(children: .combine)
            }
        }
    }

    private func entryButton(_ feature: DemoFeature) -> some View {
        Button {
            onEntry(feature)
        } label: {
            HStack(spacing: 11) {
                FeatureIcon(feature: feature, size: 36)
                VStack(alignment: .leading, spacing: 3) {
                    Text(feature.title)
                        .font(.subheadline.weight(.semibold))
                    Text(feature.subtitle)
                        .font(.caption)
                        .foregroundStyle(NativeTheme.muted)
                }
                Spacer(minLength: 3)
                Image(systemName: "chevron.right")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(NativeTheme.muted)
                    .accessibilityHidden(true)
            }
            .foregroundStyle(NativeTheme.ink)
            .multilineTextAlignment(.leading)
            .padding(10)
            .background(NativeTheme.surface, in: RoundedRectangle(cornerRadius: 15))
            .overlay(RoundedRectangle(cornerRadius: 15).strokeBorder(NativeTheme.line))
        }
        .buttonStyle(PreviewPressStyle())
        .accessibilityLabel(feature.title)
        .accessibilityHint(feature.subtitle)
    }
}

struct FeatureDetailView: View {
    @Environment(\.dismiss) private var dismiss
    let feature: DemoFeature

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    FeatureIcon(feature: feature, size: 44)
                    Text(feature.title)
                        .font(.title2.weight(.bold))
                        .accessibilityAddTraits(.isHeader)
                    Text(feature.subtitle)
                        .font(.subheadline)
                        .foregroundStyle(NativeTheme.muted)
                    if !feature.rows.isEmpty {
                        detailRows
                    }
                    if feature.showsPhotoPicker {
                        LocalPhotoPicker(tint: feature.tint)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .foregroundStyle(NativeTheme.ink)
                .padding(20)
            }
            .background(NativeTheme.background.ignoresSafeArea())
            .navigationTitle("功能预览")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("完成") { dismiss() }
                }
            }
        }
    }

    private var detailRows: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("示例详情")
                .font(.caption.weight(.semibold))
                .foregroundStyle(feature.tint)
                .accessibilityAddTraits(.isHeader)
            ForEach(feature.rows) { row in
                Divider()
                VStack(alignment: .leading, spacing: 4) {
                    Text(row.label)
                        .font(.caption)
                        .foregroundStyle(NativeTheme.muted)
                    Text(row.value)
                        .font(.subheadline.weight(.semibold))
                }
                .accessibilityElement(children: .combine)
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(NativeTheme.surface, in: RoundedRectangle(cornerRadius: 15))
        .overlay(RoundedRectangle(cornerRadius: 15).strokeBorder(NativeTheme.line))
    }
}

private struct FeatureIcon: View {
    let feature: DemoFeature
    let size: CGFloat

    var body: some View {
        Image(systemName: feature.icon)
            .font(.system(size: size * 0.43, weight: .medium))
            .foregroundStyle(feature.tint)
            .frame(width: size, height: size)
            .background(feature.tint.opacity(0.11), in: RoundedRectangle(cornerRadius: 11))
            .accessibilityHidden(true)
    }
}

private struct LocalPhotoPicker: View {
    private enum PhotoState {
        case idle, loading, loaded(UIImage), failed
    }

    let tint: Color
    @State private var selection: PhotosPickerItem?
    @State private var state: PhotoState = .idle

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            PhotosPicker(selection: $selection, matching: .images) {
                Label("从相册选择", systemImage: "photo.on.rectangle")
                    .font(.subheadline.weight(.semibold))
                    .frame(maxWidth: .infinity, minHeight: 34)
            }
            .buttonStyle(.borderedProminent)
            .tint(tint)
            Text("照片仅用于当前页面的本机预览。")
                .font(.caption)
                .foregroundStyle(NativeTheme.muted)
            switch state {
            case .idle:
                EmptyView()
            case .loading:
                ProgressView("正在读取照片")
                    .font(.caption)
            case .loaded(let image):
                Image(uiImage: image)
                    .resizable()
                    .scaledToFit()
                    .frame(maxWidth: .infinity)
                    .frame(maxHeight: 240)
                    .clipShape(RoundedRectangle(cornerRadius: 14))
                    .accessibilityLabel("所选照片的预览")
            case .failed:
                Text("这张照片无法预览，请重新选择。")
                    .font(.caption)
                    .foregroundStyle(NativeTheme.muted)
            }
        }
        .task(id: selection) {
            guard let selection else { return }
            defer {
                if !Task.isCancelled {
                    self.selection = nil
                }
            }
            state = .loading
            do {
                let data = try await selection.loadTransferable(type: Data.self)
                try Task.checkCancellation()
                guard let data, let image = thumbnail(from: data) else {
                    state = .failed
                    return
                }
                state = .loaded(image)
            } catch {
                guard !Task.isCancelled else { return }
                state = .failed
            }
        }
    }

    private func thumbnail(from data: Data) -> UIImage? {
        let options = [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceCreateThumbnailWithTransform: true,
            kCGImageSourceThumbnailMaxPixelSize: 960
        ] as [CFString: Any]
        guard let source = CGImageSourceCreateWithData(data as CFData, nil),
              let image = CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary) else {
            return nil
        }
        return UIImage(cgImage: image)
    }
}
