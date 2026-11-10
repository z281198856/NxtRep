import SwiftUI

struct NativeLocalRecordsView: View {
    @EnvironmentObject private var session:NativeSession
    var body: some View {
        if let local = session.local { NativeLocalRecordsContents(store:local) }
        else { ContentUnavailableView("本机记录尚未就绪",systemImage:"externaldrive") }
    }
}
private struct NativeLocalRecordsContents: View {
    @EnvironmentObject private var session:NativeSession
    @ObservedObject var store:NativeLocalStore
    @State private var discarding:NativeJSON = .null
    @State private var deletingDraft:String?
    @State private var error:String?
    private var drafts:[String] { store.drafts.keys.sorted().filter { !["ai-current","ai-pending","reminder-settings"].contains($0) } }
    var body: some View {
        List {
            Section("同步") {
                Toggle("暂时只保存在本机",isOn:$store.localOnly)
                Text("仅新增的饮食、饮水、测量和训练组进入队列。发生时间和提交标识会保留；AI、确认单和修改删除需要联网。").font(.footnote).foregroundStyle(NativeTheme.muted)
                NativeActionButton(title:store.syncing ? "正在同步" : "同步待提交记录") { _ in _ = await session.syncLocal(); await session.reload() }.disabled(store.syncing)
                NativeErrorText(message:store.storageError ?? error)
                if store.usingCache { Text("当前部分内容来自本机缓存，请联网后刷新核对。").font(.caption) }
            }
            Section("待同步记录（\(store.pending.count)）") {
                ForEach(store.pending,id:\.id) { item in
                    VStack(alignment:.leading,spacing:8) {
                        Text(Self.label(item)).font(.headline)
                        Text(NativeDates.display(item["body"]["consumed_at"].text.isEmpty ? item["created_at"].text : item["body"]["consumed_at"].text)).font(.caption)
                        if !item["issue"].text.isEmpty { NativeErrorText(message:item["issue"].text) }
                        HStack {
                            NativeActionButton(title:"重试同步") { _ in try store.retry(item["key"].text); _ = await session.syncLocal() }.disabled(store.syncing)
                            Button("丢弃",role:.destructive) { discarding = item }.disabled(store.syncing)
                        }
                    }
                }
                if store.pending.isEmpty { Text("没有待同步记录").foregroundStyle(NativeTheme.muted) }
            }
            Section("本机草稿") {
                ForEach(drafts,id:\.self) { key in
                    VStack(alignment:.leading) {
                        Text(store.drafts[key]!["label"].text)
                        Text("回到原页面可以继续填写。").font(.caption).foregroundStyle(NativeTheme.muted)
                        Button("删除草稿",role:.destructive) { deletingDraft = key }
                    }
                }
            }
        }.navigationTitle("离线记录与草稿")
        .confirmationDialog("丢弃本机待同步记录？",isPresented:Binding(get:{!discarding.isNull},set:{if !$0 { discarding = .null }}),titleVisibility:.visible) {
            Button("丢弃",role:.destructive) { do { try store.discard(discarding["key"].text); discarding = .null } catch { self.error = NativeSession.readable(error) } }
        } message: { Text("若之前的请求结果不确定，请先核对服务器记录。丢弃只移除本机队列。") }
        .confirmationDialog("删除这份本机草稿？",isPresented:Binding(get:{deletingDraft != nil},set:{if !$0 { deletingDraft = nil }}),titleVisibility:.visible) { Button("删除",role:.destructive) { do { if let key = deletingDraft { try store.saveDraft(key,label:"",value:.null) }; deletingDraft = nil } catch { self.error = NativeSession.readable(error) } } }
    }
    private static func label(_ item:NativeJSON)->String {
        switch item["path"].text { case "nutrition/water":"饮水 \(item["body"]["amount_ml"].text) 毫升"; case "nutrition/entries":"饮食记录"; case "body/measurements":"身体测量"; default:"第 \(item["body"]["set_index"].text) 组 · \(item["body"]["weight_kg"].text) kg × \(item["body"]["reps"].text)" }
    }
}

private struct NativeDraftModifier: ViewModifier {
    @EnvironmentObject private var session:NativeSession
    let key:String
    let label:String
    let value:NativeJSON
    let restore:(NativeJSON)->Void
    @State private var initialized = false
    @State private var scope:String?
    @State private var error:String?
    func body(content:Content)->some View {
        content.safeAreaInset(edge:.top) { if let error { NativeErrorText(message:error).padding(8).background(NativeTheme.background) } }
            .task {
                guard !initialized else { return }
                scope = session.local?.scope
                let saved = session.local?.draft(key)["value"] ?? .null
                if !saved.isNull { restore(saved) }
                initialized = true
            }
            .onChange(of:value) { _,next in
                guard initialized,scope == session.local?.scope else { return }
                do { try session.local?.saveDraft(key,label:label,value:next); error = nil }
                catch { self.error = NativeSession.readable(error) }
            }
    }
}
extension View {
    func nativeDraft(_ key:String,label:String,value:NativeJSON,restore:@escaping (NativeJSON)->Void)->some View {
        modifier(NativeDraftModifier(key:key,label:label,value:value,restore:restore))
    }
}
