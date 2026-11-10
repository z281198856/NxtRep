import Foundation
import Combine
import CryptoKit
import Security

/// Per-account encrypted write-ahead journal. Acknowledgements are persisted before returning.
@MainActor
final class NativeLocalStore: ObservableObject {
    @Published private(set) var state: NativeJSON = .object([:])
    @Published private(set) var scope: String?
    @Published var usingCache = false
    @Published var storageError: String?
    @Published private(set) var syncing = false
    @Published private(set) var revision = 0
    @Published var localOnly = false
    private var encryptionKey: SymmetricKey?
    private var file: URL?
    private let directory: URL?
    private let keyData: Data?
    init(directory:URL? = nil,keyData:Data? = nil) { self.directory = directory; self.keyData = keyData }
    var pending: [NativeJSON] { state["pending"].values }
    var drafts: [String:NativeJSON] { state["drafts"].fields }

    static func canRecord(_ path:String,method:String) -> Bool {
        method == "POST" && (["nutrition/water","nutrition/entries","body/measurements"].contains(path) || path.range(of:#"^workouts/[0-9a-fA-F-]+/sets$"#,options:.regularExpression) != nil)
    }
    static func canCache(_ path:String) -> Bool {
        ["me","profile","settings","workouts/active","calendar/events","training/plans/active","training/templates","media/images/capabilities"].contains(path) || ["nutrition/","body/","progress/","foods/","workouts/"].contains(where:path.hasPrefix)
    }
    static func transient(_ error:Error) -> Bool {
        if let e = error as? URLError { return e.code != .cancelled }
        if case NativeAPIError.response(let status,let code) = error { return status >= 500 || [408,429].contains(status) || ["IDEMPOTENCY_IN_PROGRESS","IDEMPOTENCY_REQUEST_IN_PROGRESS"].contains(code) }
        return false
    }
    func bind(server:String,userID:String) throws {
        let owner = SHA256.hash(data:Data((server+"|"+userID).utf8)).map { String(format:"%02x",$0) }.joined()
        guard owner != scope else { return }
        let key:SymmetricKey
        if let keyData { key = SymmetricKey(data:keyData) } else { key = try Self.key() }
        let root:URL
        if let directory { root = directory } else { root = try FileManager.default.url(for:.applicationSupportDirectory,in:.userDomainMask,appropriateFor:nil,create:true).appendingPathComponent("NxtRepLocal",isDirectory:true) }
        try FileManager.default.createDirectory(at:root,withIntermediateDirectories:true)
        var excluded = URLResourceValues(); excluded.isExcludedFromBackup = true
        var dir = root; try dir.setResourceValues(excluded)
        let location = root.appendingPathComponent(owner+".enc")
        let next: NativeJSON
        if FileManager.default.fileExists(atPath:location.path) {
            let sealed = try AES.GCM.SealedBox(combined:Data(contentsOf:location))
            next = try JSONDecoder().decode(NativeJSON.self,from:AES.GCM.open(sealed,using:key,authenticating:Data(owner.utf8)))
            guard next["schema"].integer == 1 else { throw NativeAPIError.message("本机记录版本无法读取，原文件已保留。") }
        } else { next = .object(["schema":.int(1)]) }
        scope = owner; file = location; encryptionKey = key; state = next; usingCache = false; storageError = nil
    }
    func unbind() { scope = nil; file = nil; encryptionKey = nil; state = .object([:]); usingCache = false; localOnly = false }
    private static func key() throws -> SymmetricKey {
        let query: [String:Any] = [kSecClass as String:kSecClassGenericPassword,kSecAttrService as String:"com.zengsiqi.nxtrep.native.local",kSecAttrAccount as String:"encryption-key"]
        var lookup = query; lookup[kSecReturnData as String] = true; lookup[kSecMatchLimit as String] = kSecMatchLimitOne
        var item: CFTypeRef?
        let status = SecItemCopyMatching(lookup as CFDictionary,&item)
        if status == errSecSuccess, let bytes = item as? Data { return SymmetricKey(data:bytes) }
        guard status == errSecItemNotFound else { throw NativeAPIError.message("请解锁手机后重试读取本机记录。") }
        let key = SymmetricKey(size:.bits256), bytes = key.withUnsafeBytes { Data($0) }
        var addition = query; addition[kSecValueData as String] = bytes; addition[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        guard SecItemAdd(addition as CFDictionary,nil) == errSecSuccess else { throw NativeAPIError.message("无法安全保存本机记录的密钥。") }
        return key
    }
    private func commit(_ fields:[String:NativeJSON]) throws {
        guard let file,let key = encryptionKey,let scope else { throw NativeAPIError.message("本地账户尚未就绪，请重新打开 App。") }
        do {
            let value = NativeJSON.object(fields)
            let data = try JSONEncoder().encode(value)
            let encrypted = try AES.GCM.seal(data,using:key,authenticating:Data(scope.utf8)).combined!
            #if os(iOS)
            try encrypted.write(to:file,options:[.atomic,.completeFileProtection])
            #else
            try encrypted.write(to:file,options:.atomic)
            #endif
            state = value; storageError = nil
        } catch { storageError = "无法安全保存本机记录，请解锁手机并检查可用空间。"; throw NativeAPIError.message(storageError!) }
    }
    func draft(_ key:String) -> NativeJSON { state["drafts"][key] }
    func saveDraft(_ key:String,label:String,value:NativeJSON) throws {
        var data = state.fields, drafts = self.drafts
        guard try JSONEncoder().encode(value).count <= 8_000_000 else { throw NativeAPIError.message("草稿内容过大，请减少照片后重试。") }
        if value.isNull { drafts.removeValue(forKey:key) }
        else { drafts[key] = .object(["label":.string(label),"value":value,"at":.string(NativeDates.timestamp())]) }
        data["drafts"] = .object(drafts); try commit(data)
    }
    func cached(_ resource:String) -> NativeJSON? {
        guard !state["cache"][resource].isNull else { return nil }
        usingCache = true
        return project(resource,state["cache"][resource]["value"])
    }
    func cache(_ resource:String,value:NativeJSON) {
        var data = state.fields, entries = state["cache"].fields
        entries[resource] = .object(["value":value,"at":.string(NativeDates.timestamp())])
        while entries.count > 40 || ((try? JSONEncoder().encode(entries).count) ?? 0) > 400_000 {
            guard let oldest = entries.keys.min(by:{ entries[$0]!["at"].text < entries[$1]!["at"].text }) else { break }
            entries.removeValue(forKey:oldest)
        }
        data["cache"] = .object(entries); try? commit(data)
    }
    func enqueue(path:String,body:[String:NativeJSON],key:String,draftKey:String? = nil) throws -> NativeJSON? {
        if let receipt = state["receipts"].fields[key] {
            guard receipt["path"].text == path,receipt["body"] == .object(body) else { throw NativeAPIError.message("原记录已同步，请关闭并重新打开表单后再添加其他内容。") }
            return receipt["value"]
        }
        if let existing = pending.first(where:{$0["key"].text == key}) {
            guard existing["path"].text == path,existing["body"] == .object(body) else { throw NativeAPIError.message("这次提交已保存在本机。请先同步或丢弃原记录，再修改内容。") }
            return nil
        }
        guard pending.count < 500 else { throw NativeAPIError.message("待同步记录较多，请先同步或整理。") }
        var data = state.fields
        data["pending"] = .array(pending + [.object(["key":.string(key),"path":.string(path),"body":.object(body),"created_at":.string(NativeDates.timestamp()),"draft_key":draftKey.map(NativeJSON.string) ?? .null])])
        try commit(data); return nil
    }
    func discard(_ key:String) throws { var data = state.fields; data["pending"] = .array(pending.filter {$0["key"].text != key}); try commit(data) }
    func retry(_ key:String) throws {
        var data = state.fields
        data["pending"] = .array(pending.map { item in var v = item.fields; if item["key"].text == key { v.removeValue(forKey:"issue") }; return .object(v) })
        try commit(data)
    }
    func sync(sender:(String,[String:NativeJSON],String) async throws -> NativeJSON) async -> [String:NativeJSON] {
        guard scope != nil,!syncing,!localOnly else { return [:] }
        syncing = true; defer { syncing = false }
        let owner = scope; var results: [String:NativeJSON] = [:]; var blocked = Set<String>()
        for original in pending {
            guard owner == scope else { break }
            var item = original.fields
            let key = original["key"].text,path = original["path"].text
            if let first = NativeDates.parse(original["first_attempt_at"].text),Date().timeIntervalSince(first) >= 23*3600 { item["issue"] = .string("上次提交已超过 23 小时，请先核对服务端记录，避免重复。") }
            if !item["issue",default:.null].isNull || blocked.contains(path) { blocked.insert(path); if item != original.fields { try? replace(key,.object(item)) }; continue }
            item["first_attempt_at"] = item["first_attempt_at"] ?? .string(NativeDates.timestamp())
            do {
                try replace(key,.object(item))
                let result = try await sender(path,original["body"].fields,key)
                guard owner == scope else { break }
                var data = state.fields,receipts = state["receipts"].fields
                receipts[key] = .object(["value":result,"at":.string(NativeDates.timestamp()),"path":.string(path),"body":original["body"]])
                if receipts.count > 500,let oldest = receipts.keys.min(by:{receipts[$0]!["at"].text < receipts[$1]!["at"].text}) { receipts.removeValue(forKey:oldest) }
                data["receipts"] = .object(receipts); data["pending"] = .array(pending.filter {$0["key"].text != key})
                if !original["draft_key"].text.isEmpty { var drafts = state["drafts"].fields; drafts.removeValue(forKey:original["draft_key"].text); data["drafts"] = .object(drafts) }
                try commit(data); results[key] = result; revision += 1; usingCache = false
            } catch {
                guard owner == scope else { break }
                if Self.transient(error) || storageError != nil { break }
                if case NativeAPIError.response(let status,_) = error,status == 401 || status == 403 { break }
                item["issue"] = .string(NativeSession.readable(error)); try? replace(key,.object(item)); blocked.insert(path)
            }
        }
        return results
    }
    private func replace(_ key:String,_ value:NativeJSON) throws { var data = state.fields; data["pending"] = .array(pending.map {$0["key"].text == key ? value : $0}); try commit(data) }
    func project(_ path:String,_ value:NativeJSON) -> NativeJSON {
        var data = value.fields
        guard (path == "workouts/active" || path == "workouts/"+value.id),!value.id.isEmpty else { return value }
        data["exercises"] = .array(value["exercises"].values.map { exercise in
            var v = exercise.fields; var sets = exercise["sets"].values
            for record in pending where record["path"].text == "workouts/"+value.id+"/sets" && record["body"]["workout_exercise_id"] == exercise["id"] {
                if sets.contains(where:{$0["client_generated_id"].text == record["key"].text}) { continue }
                var set = record["body"].fields; set["id"] = .string("local-"+record["key"].text); set["pending_local"] = .bool(true); sets.append(.object(set))
            }
            v["sets"] = .array(sets); return .object(v)
        }); return .object(data)
    }
}
