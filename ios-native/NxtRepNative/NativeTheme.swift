import SwiftUI

enum NativeTheme {
    static let background = color(0xF5F7FB)
    static let surface = Color.white
    static let ink = color(0x192131)
    static let muted = color(0x626D80)
    static let line = color(0xE4E9F1)
    static let accent = color(0x4657A6)
    static let hero = color(0x20283A)
    static let softAccent = color(0xE9EDFA)

    static func color(_ hex: UInt32) -> Color {
        Color(
            red: Double((hex >> 16) & 255) / 255,
            green: Double((hex >> 8) & 255) / 255,
            blue: Double(hex & 255) / 255
        )
    }
}

struct PreviewPressStyle: ButtonStyle {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed && !reduceMotion ? 0.98 : 1)
            .opacity(configuration.isPressed ? 0.82 : 1)
            .animation(reduceMotion ? nil : .easeOut(duration: 0.14), value: configuration.isPressed)
    }
}
