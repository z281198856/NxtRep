import SwiftUI

struct NativeRootView: View {
    @StateObject private var session = NativeSession(local:NativeLocalStore())
    @State private var didRestore = false

    var body: some View {
        Group {
            if session.restoring {
                ProgressView("正在恢复连接…")
            } else if session.signedIn {
                if !session.accountLoaded {
                    VStack(spacing:16) {
                        if let error = session.error {
                            NativeErrorText(message:error)
                            Button("重新读取账户") { Task { do { try await session.loadAccountAndSettings() } catch { session.error = NativeSession.readable(error) } } }
                        } else { ProgressView("正在读取账户…") }
                        Button("退出登录") { Task { await session.logout() } }
                    }.padding(24)
                } else if !session.profileInitialized {
                    NativeOnboardingView()
                } else {
                    NativeAppShell()
                }
            } else {
                NativeConnectionView(session: session)
            }
        }
        .tint(NativeTheme.accent)
        .environmentObject(session)
        .onChange(of:session.signedIn) { _,signedIn in if !signedIn { NativeReminders.shared.deactivate() } }
        .task {
            guard !didRestore else { return }
            didRestore = true
            await session.restore()
        }
    }
}

struct NativeConnectionView: View {
    @ObservedObject var session: NativeSession
    @State private var username = ""
    @State private var password = ""
    @State private var showingPreview = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    Image("BrandMark")
                        .resizable().scaledToFit().frame(width: 62, height: 62)
                        .clipShape(RoundedRectangle(cornerRadius: 18))
                    VStack(alignment: .leading, spacing: 8) {
                        Text("连接你的 NxtRep").font(.largeTitle.bold())
                        Text("连接你的训练、饮食、身体数据和 AI 私人教练。")
                            .font(.subheadline).foregroundStyle(NativeTheme.muted)
                    }
                    VStack(alignment: .leading, spacing: 14) {
                        Text("服务器地址").font(.subheadline.weight(.semibold))
                        TextField("http://电脑地址:8000/api/v1", text: $session.serverText)
                            .keyboardType(.URL).textInputAutocapitalization(.never).autocorrectionDisabled()
                        Divider()
                        TextField("NxtRep 账号", text: $username)
                            .textContentType(.username).textInputAutocapitalization(.never).autocorrectionDisabled()
                        Divider()
                        SecureField("NxtRep 密码", text: $password)
                            .textContentType(.password)
                    }
                    .padding(20).background(NativeTheme.surface, in: RoundedRectangle(cornerRadius: 22))
                    if let error = session.error {
                        Text(error).font(.subheadline).foregroundStyle(.red).accessibilityLabel("登录提示：" + error)
                    }
                    Button {
                        Task {
                            await session.login(username: username, password: password)
                            if session.signedIn { password = "" }
                        }
                    } label: {
                        HStack {
                            if session.busy { ProgressView().tint(.white) }
                            Text(session.busy ? "正在连接…" : "登录并连接")
                        }
                        .font(.headline).frame(maxWidth: .infinity, minHeight: 52)
                        .foregroundStyle(.white).background(NativeTheme.accent, in: RoundedRectangle(cornerRadius: 16))
                    }
                    .disabled(session.busy || username.isEmpty || password.isEmpty)
                    Text("使用本项目的 NxtRep 账号。USB 联调时保持数据线连接；首次连接请允许访问本地网络。")
                        .font(.footnote).foregroundStyle(NativeTheme.muted)
                    Button("先体验界面预览") { showingPreview = true }
                        .font(.subheadline).frame(minHeight: 44)
                    NavigationLink("首次设置 NxtRep 密码") { NativePasswordSetupView() }
                }
                .padding(24).padding(.top, 24)
            }
            .background(NativeTheme.background)
            .disabled(session.busy)
            .fullScreenCover(isPresented: $showingPreview) {
                PreviewShell(session: session, isPreview: true)
                    .safeAreaInset(edge: .top) {
                        Button("返回登录") { showingPreview = false }
                            .frame(maxWidth: .infinity, minHeight: 44)
                            .background(NativeTheme.background)
                    }
            }
        }
    }
}

struct NativeAccountView: View {
    @ObservedObject var session: NativeSession
    @State private var loggingOut = false

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("我的连接").font(.largeTitle.bold())
            Label(session.user?.username ?? "", systemImage: "person.crop.circle")
                .font(.title3.weight(.semibold))
            Text(session.serverText).font(.footnote).textSelection(.enabled)
            Text("首页营养和饮水已连接真实数据。计划、进展和 AI 教练等页面仍可体验界面预览。")
                .font(.subheadline).foregroundStyle(NativeTheme.muted)
            Button("刷新首页") { Task { await session.reload() } }
                .frame(minHeight: 44)
            Button(loggingOut ? "正在退出…" : "退出登录", role: .destructive) {
                loggingOut = true
                Task { await session.logout(); loggingOut = false }
            }
            .frame(minHeight: 44).disabled(loggingOut || session.savingWater)
        }
        .frame(maxWidth: .infinity, alignment: .leading).padding(.vertical, 16)
    }
}

struct ConnectedNutrientSheet: View {
    @Environment(\.dismiss) private var dismiss
    @ObservedObject var session: NativeSession
    let kind: NutrientKind

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                HStack {
                    Text("今日" + kind.title).font(.headline)
                    Spacer()
                    Button("完成") { dismiss() }.frame(minHeight: 44)
                }
                Text("\(session.summary?.amount(kind) ?? 0) \(kind.unit)")
                    .font(.system(.largeTitle, design: .rounded, weight: .semibold))
                if let goal = session.summary?.goal(kind), goal > 0 {
                    Text("目标上限 \(goal) \(kind.unit)").foregroundStyle(NativeTheme.muted)
                } else {
                    Text("尚未设置个人目标").foregroundStyle(NativeTheme.muted)
                }
                if kind == .water {
                    Button {
                        Task { await session.addWater(amount: 250) }
                    } label: {
                        HStack {
                            if session.savingWater { ProgressView().tint(.white) }
                            Label(session.hasPendingWater ? "重试并核对本次记录" : "记 250 毫升", systemImage: "drop.fill")
                        }
                        .font(.subheadline.weight(.semibold)).foregroundStyle(.white)
                        .frame(maxWidth: .infinity, minHeight: 50)
                        .background(kind.labelColor, in: RoundedRectangle(cornerRadius: 14))
                    }
                    .disabled(session.savingWater)
                    if let message = session.waterMessage {
                        Text(message).font(.subheadline).foregroundStyle(NativeTheme.muted)
                    }
                    Text("已保存 \(session.water.count) 次记录").font(.subheadline.weight(.semibold))
                    ForEach(session.water) { record in
                        HStack {
                            Label("\(record.amountMl) 毫升", systemImage: "drop")
                            Spacer()
                            Text(timeLabel(record.consumedAt)).foregroundStyle(NativeTheme.muted)
                        }
                        .font(.subheadline).padding(.vertical, 6)
                    }
                } else {
                    Text("按服务器上的今日饮食记录汇总。未记录的进食不计入统计。")
                        .font(.subheadline).foregroundStyle(NativeTheme.muted)
                }
            }
            .padding(22)
        }
        .presentationDetents([.medium, .large]).presentationDragIndicator(.visible)
        .interactiveDismissDisabled(session.savingWater)
    }

    private func timeLabel(_ text: String) -> String {
        let parser = ISO8601DateFormatter()
        parser.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let fractional = parser.date(from: text)
        parser.formatOptions = [.withInternetDateTime]
        guard let date = fractional ?? parser.date(from: text) else { return "已保存" }
        return date.formatted(date: .omitted, time: .shortened)
    }
}
