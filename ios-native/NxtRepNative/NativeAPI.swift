import Foundation
import Security
import Combine

struct APINumber: Decodable {
    let value: Double
    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if let number = try? container.decode(Double.self) {
            value = number
        } else {
            let string = try container.decode(String.self)
            guard let number = Double(string), number.isFinite else {
                throw DecodingError.dataCorruptedError(in: container, debugDescription: "Invalid numeric value")
            }
            value = number
        }
    }
}

struct NutritionAmounts: Decodable {
    let kcal: APINumber
    let proteinG: APINumber
    let carbsG: APINumber
    let fatG: APINumber
}

struct DailySummary: Decodable {
    let date: String
    let waterMl: Int
    let consumed: NutritionAmounts
    let target: [String: APINumber]?

    func amount(_ kind: NutrientKind) -> Int {
        switch kind {
        case .carbs: Int(consumed.carbsG.value.rounded())
        case .protein: Int(consumed.proteinG.value.rounded())
        case .fat: Int(consumed.fatG.value.rounded())
        case .water: waterMl
        }
    }

    func goal(_ kind: NutrientKind) -> Int? {
        let key: String
        switch kind {
        case .carbs: key = "carbs_max_g"
        case .protein: key = "protein_max_g"
        case .fat: key = "fat_max_g"
        case .water: return nil
        }
        guard let value = target?[key]?.value else { return nil }
        return Int(value.rounded())
    }
}

struct WaterRecord: Decodable, Identifiable {
    let id: String
    let amountMl: Int
    let consumedAt: String
}

struct NativeUser: Codable {
    let id: String
    let username: String
}

struct NativeTokens: Decodable {
    let accessToken: String
    let refreshToken: String
    let user: NativeUser
}

struct SavedNativeSession: Codable {
    let server: String
    let refreshToken: String
    let user: NativeUser
}

enum NativeAPIError: LocalizedError {
    case message(String)
    case response(Int, String)

    var errorDescription: String? {
        switch self {
        case .message(let message): return message
        case .response(let status, let code):
            switch code {
            case "INVALID_CREDENTIALS": return "账号或密码不正确。请使用 NxtRep 账号。"
            case "ACCOUNT_LOCKED": return "账号暂时锁定，请稍后再试。"
            case "ACCOUNT_DISABLED": return "这个账号已停用。"
            case "INVALID_CURRENT_PASSWORD": return "当前密码不正确。"
            case "INVALID_REFRESH_TOKEN", "INVALID_ACCESS_TOKEN": return "登录已失效，请重新登录。"
            case "IDEMPOTENCY_IN_PROGRESS": return "这条记录正在保存，请稍后核对。"
            case "IDEMPOTENCY_KEY_REUSED": return "这条记录的提交标识冲突，请先核对饮水记录。"
            default:
                if status == 409 { return "内容已更新或存在冲突，请刷新核对最新状态后再操作。" }
                if status == 422 || status == 400 { return "填写内容未通过校验，请检查必填项、数值范围和日期。" }
                if status == 404 { return "这项内容已不存在，请返回刷新列表。" }
                if status == 429 { return "请求较多，请稍后再试。" }
                if status >= 500 { return "服务器暂时无法完成处理，请稍后重试。" }
                return "请求未能完成（\(code)），请稍后重试。"
            }
        }
    }
}

enum SessionKeychain {
    private static var query: [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: "com.zengsiqi.nxtrep.native.session",
         kSecAttrAccount as String: "active-session"]
    }

    static func load() -> SavedNativeSession? {
        var lookup = query
        lookup[kSecReturnData as String] = true
        lookup[kSecMatchLimit as String] = kSecMatchLimitOne
        var item: CFTypeRef?
        guard SecItemCopyMatching(lookup as CFDictionary, &item) == errSecSuccess,
              let data = item as? Data else { return nil }
        return try? JSONDecoder().decode(SavedNativeSession.self, from: data)
    }

    static func save(_ session: SavedNativeSession) throws {
        let data = try JSONEncoder().encode(session)
        let update = [kSecValueData as String: data]
        var status = SecItemUpdate(query as CFDictionary, update as CFDictionary)
        if status == errSecItemNotFound {
            var addition = query
            addition[kSecValueData as String] = data
            addition[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
            status = SecItemAdd(addition as CFDictionary, nil)
        }
        guard status == errSecSuccess else {
            throw NativeAPIError.message("无法安全保存登录状态，请解锁手机后重试。")
        }
    }

    static func clear() { SecItemDelete(query as CFDictionary) }
}

@MainActor
final class NativeSession: ObservableObject {
    @Published private(set) var user: NativeUser?
    @Published private(set) var summary: DailySummary?
    @Published private(set) var water: [WaterRecord] = []
    @Published private(set) var busy = false
    @Published private(set) var savingWater = false
    @Published var error: String?
    @Published var selectedDate = Date()
    @Published private(set) var settings: NativeJSON = .null
    @Published private(set) var accountLoaded = false
    @Published private(set) var profileInitialized = false
    @Published var waterMessage: String?
    @Published private(set) var restoring = true
    @Published var serverText = UserDefaults.standard.string(forKey: "native-api-server") ?? "http://172.20.10.10:8000/api/v1"

    private var baseURL: URL?
    private var accessToken: String?
    private var refreshToken: String?
    private var refreshTask: Task<NativeTokens, Error>?
    private var passwordTask: Task<NativeTokens, Error>?
    private var generation = UUID()
    private var latestRead = UUID()
    // An uncertain write keeps its exact payload and key, so a manual retry cannot duplicate it.
    private var pendingWater: (body: Data, key: String)?
    private var pendingWaterAcknowledged = false
    private let transport: URLSession
    private let saveSession: (SavedNativeSession) throws -> Void
    private let loadSession: () -> SavedNativeSession?
    private let clearSessionStore: () -> Void
    let local: NativeLocalStore?

    init(transport: URLSession? = nil,
         saveSession: @escaping (SavedNativeSession) throws -> Void = SessionKeychain.save,
         loadSession: @escaping () -> SavedNativeSession? = SessionKeychain.load,
         clearSessionStore: @escaping () -> Void = SessionKeychain.clear,
         local: NativeLocalStore? = nil) {
        self.local = local
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 15
        config.timeoutIntervalForResource = 300
        config.urlCache = nil
        self.transport = transport ?? URLSession(configuration: config)
        self.saveSession = saveSession
        self.loadSession = loadSession
        self.clearSessionStore = clearSessionStore
    }

    var signedIn: Bool { user != nil }
    var hasPendingWater: Bool { pendingWater != nil }
    var imperial: Bool { settings["unit_system"].text == "imperial" }
    var weightUnit: String { imperial ? "lb" : "kg" }
    var lengthUnit: String { imperial ? "in" : "cm" }
    func displayWeight(_ kg:Double) -> Double { imperial ? kg*2.2046226218 : kg }
    func displayLength(_ cm:Double) -> Double { imperial ? cm/2.54 : cm }
    func toKG(_ value:Double) -> Double { ((imperial ? value/2.2046226218 : value)*1000).rounded()/1000 }
    func toCM(_ value:Double) -> Double { ((imperial ? value*2.54 : value)*100).rounded()/100 }
    func weightText(_ kg:Double) -> String { displayWeight(kg).formatted(.number.precision(.fractionLength(0...2)))+" "+weightUnit }
    func lengthText(_ cm:Double) -> String { displayLength(cm).formatted(.number.precision(.fractionLength(0...2)))+" "+lengthUnit }
    func loadSettings() async throws { settings = try await api("settings") }
    func applySettings(_ value:NativeJSON) { settings = value }
    func loadAccountAndSettings() async throws {
        let account = try await api("me")
        try await loadSettings()
        profileInitialized = account["profile_initialized"].flag
        accountLoaded = true
    }
    func setupPassword(username:String,setupToken:String,password:String) async throws {
        baseURL = try Self.validatedURL(serverText)
        let body = try JSONSerialization.data(withJSONObject:["username":username,"setup_token":setupToken,"new_password":password])
        let pair: NativeTokens = try await send("auth/password/setup",method:"POST",body:body)
        try accept(pair)
        UserDefaults.standard.set(serverText,forKey:"native-api-server")
        try await loadAccountAndSettings(); await reload()
    }
    func changePassword(current:String,new:String) async throws {
        guard passwordTask == nil else { throw NativeAPIError.message("密码修改正在处理，请稍候。") }
        _ = try await refresh()
        let task = Task { () throws -> NativeTokens in
            let body = try JSONSerialization.data(withJSONObject:["current_password":current,"new_password":new,"device_name":"NxtRep iPhone"])
            let pair: NativeTokens = try await send("auth/password/change",method:"POST",body:body,token:accessToken)
            try accept(pair)
            return pair
        }
        passwordTask = task
        defer { passwordTask = nil }
        do { _ = try await task.value }
        catch {
            if error is URLError { clearSession(); throw NativeAPIError.message("密码修改结果尚未确认，请使用新密码重新登录核对，避免重复修改。") }
            throw error
        }
    }

    func api(_ path: String, method: String = "GET", query: [String: String] = [:], body: [String: NativeJSON]? = nil, key: String? = nil, draftKey:String? = nil) async throws -> NativeJSON {
        var components = URLComponents()
        components.path = path.hasPrefix("/") ? path : "/" + path
        if !query.isEmpty { components.queryItems = query.sorted { $0.key < $1.key }.map { URLQueryItem(name: $0.key, value: $0.value) } }
        let resource = String((components.string ?? path).drop(while: { $0 == "/" }))
        let data = try body.map { try JSONEncoder().encode($0) }
        let requestKey = key ?? (method == "POST" ? UUID().uuidString : nil)
        if let local, NativeLocalStore.canRecord(path,method:method),let body,let requestKey {
            if let receipt = try local.enqueue(path:path,body:body,key:requestKey,draftKey:draftKey) { return receipt }
            let results = await syncLocal()
            if let result = results[requestKey] { return result }
            throw NativeAPIError.message("已保存在本机，待联网同步；可在“离线记录与草稿”查看。请勿另建同一条记录。")
        }
        if local?.localOnly == true,method != "GET" { throw NativeAPIError.message("当前选择了仅保存在本机。这个操作需要联网，请先在离线记录页关闭该选项。") }
        let owner = generation
        do {
            if local?.localOnly == true,method == "GET" { throw URLError(.notConnectedToInternet) }
            let result: NativeJSON = try await authorized(resource, method: method, body: data, key:requestKey)
            guard owner == generation else { throw CancellationError() }
            if method == "GET",NativeLocalStore.canCache(path) { local?.cache(resource,value:result) }
            return local?.project(path,result) ?? result
        } catch {
            if method == "GET",owner == generation,NativeLocalStore.transient(error),let cached = local?.cached(resource) { return cached }
            throw error
        }
    }

    @discardableResult func syncLocal() async -> [String:NativeJSON] {
        guard let local,signedIn else { return [:] }
        return await local.sync { path,body,key in
            try await self.authorized(path,method:"POST",body:JSONEncoder().encode(body),key:key)
        }
    }

    func streamConversation(_ id:String,body:[String:NativeJSON],onEvent:(String,NativeJSON) async throws -> Void) async throws {
        guard local?.localOnly != true else { throw NativeAPIError.message("AI 处理需要联网，请先关闭仅保存在本机。") }
        if accessToken == nil { _ = try await refresh() }
        let owner = generation
        for attempt in 0...1 {
            guard let baseURL,let url = URL(string:baseURL.absoluteString.trimmingCharacters(in:CharacterSet(charactersIn:"/"))+"/agent/conversations/"+id+"/messages?granularity=chunk") else { throw NativeAPIError.message("请先连接服务器。") }
            let sentToken = accessToken
            var request = URLRequest(url:url); request.httpMethod = "POST"; request.httpBody = try JSONEncoder().encode(body)
            request.timeoutInterval = 90; request.setValue("application/json",forHTTPHeaderField:"Content-Type"); request.setValue("text/event-stream",forHTTPHeaderField:"Accept")
            request.setValue("Bearer "+(sentToken ?? ""),forHTTPHeaderField:"Authorization")
            let (bytes,response) = try await transport.bytes(for:request)
            guard let http = response as? HTTPURLResponse else { throw URLError(.badServerResponse) }
            if http.statusCode == 401,attempt == 0 { if accessToken == sentToken { _ = try await refresh() }; continue }
            guard (200..<300).contains(http.statusCode),http.value(forHTTPHeaderField:"Content-Type")?.contains("text/event-stream") == true else { throw NativeAPIError.response(http.statusCode,"AI_STREAM_UNAVAILABLE") }
            var parser = NativeSSEParser()
            for try await line in bytes.lines {
                try Task.checkCancellation()
                guard owner == generation else { throw CancellationError() }
                if let event = try parser.push(line) { try await onEvent(event.0,event.1) }
            }
            if let event = try parser.finish() { try await onEvent(event.0,event.1) }
            return
        }
    }

    func allPages(_ path: String, query: [String: String] = [:], limit: Int = 100) async throws -> [NativeJSON] {
        var result: [NativeJSON] = []
        var page = 1
        while true {
            var params = query
            params["page"] = String(page)
            params["page_size"] = String(limit)
            let response = try await api(path, query: params)
            let items = response.records
            result += items
            if !response["has_more"].flag { return result }
            guard !items.isEmpty, page < 1000 else { throw NativeAPIError.message("列表分页异常，请重新加载。") }
            page += 1
        }
    }

    func approve(_ confirmationID: String) async throws -> NativeJSON {
        let detail = try await api("confirmations/" + confirmationID)
        let result = try await api("confirmations/" + confirmationID + "/approve", method: "POST", body: ["expected_version": .int(detail.version)])
        guard result["status"].text == "succeeded" else { throw NativeAPIError.message("本次确认未能执行，请核对确认单状态。") }
        await reload()
        return result
    }

    static func validatedURL(_ text: String) throws -> URL {
        guard let url = URL(string: text.trimmingCharacters(in: .whitespacesAndNewlines)),
              let host = url.host?.lowercased(), url.user == nil, url.password == nil,
              url.query == nil, url.fragment == nil,
              url.path.trimmingCharacters(in: CharacterSet(charactersIn: "/")) == "api/v1" else {
            throw NativeAPIError.message("请输入完整的服务器地址，例如 http://172.20.10.10:8000/api/v1。")
        }
        let parts = host.split(separator: ".").compactMap { Int($0) }
        let privateIP = parts.count == 4 && parts.allSatisfy { (0...255).contains($0) } &&
            (parts[0] == 10 || (parts[0] == 172 && (16...31).contains(parts[1])) ||
             (parts[0] == 192 && parts[1] == 168) || parts[0] == 127)
        guard url.scheme == "https" || (url.scheme == "http" && (privateIP || host == "localhost" || host.hasSuffix(".local"))) else {
            throw NativeAPIError.message("HTTP 联调仅支持本地网络地址；公网服务器请使用 HTTPS。")
        }
        return url
    }

    func restore() async {
        defer { restoring = false }
        guard let saved = loadSession() else { return }
        do {
            baseURL = try Self.validatedURL(saved.server)
            serverText = saved.server
            refreshToken = saved.refreshToken
            try local?.bind(server:saved.server,userID:saved.user.id)
            user = saved.user
            _ = try await refresh()
            await reload()
            try await loadAccountAndSettings()
        } catch {
            self.error = Self.readable(error)
            // Keep the saved refresh credential on transport failure, allowing a later retry.
            if case NativeAPIError.response(let status, _) = error, status == 401 {
                clearSession()
            }
            if signedIn,NativeLocalStore.transient(error) {
                do { try await loadAccountAndSettings(); await reload() } catch { self.error = Self.readable(error) }
            }
        }
    }

    func login(username: String, password: String) async {
        guard !busy else { return }
        busy = true
        error = nil
        defer { busy = false }
        do {
            baseURL = try Self.validatedURL(serverText)
            let body = try JSONSerialization.data(withJSONObject: [
                "username": username.trimmingCharacters(in: .whitespacesAndNewlines),
                "password": password, "device_name": "NxtRep iPhone"
            ])
            let tokens: NativeTokens = try await send("auth/login", method: "POST", body: body)
            try accept(tokens)
            UserDefaults.standard.set(serverText, forKey: "native-api-server")
        } catch { self.error = Self.readable(error) }
        if signedIn { await reload(); do { try await loadAccountAndSettings() } catch { self.error = Self.readable(error) } }
    }

    func reload() async {
        guard signedIn else { return }
        let current = generation
        let readID = UUID()
        latestRead = readID
        do {
            let day = NativeDates.day(selectedDate)
            let summaryValue = try await api("nutrition/daily-summary",query:["date":day])
            let waterValue = try await api("nutrition/water",query:["date":day])
            let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
            let nextSummary = try decoder.decode(DailySummary.self,from:JSONEncoder().encode(summaryValue))
            let nextWater = try decoder.decode([WaterRecord].self,from:JSONEncoder().encode(waterValue))
            guard current == generation, readID == latestRead else { return }
            summary = nextSummary
            water = nextWater
            error = nil
        } catch {
            guard current == generation, readID == latestRead else { return }
            self.error = Self.readable(error)
        }
    }

    func addWater(amount: Int) async {
        guard !savingWater, signedIn else { return }
        savingWater = true
        waterMessage = nil
        defer { savingWater = false }
        let current = generation
        do {
            if pendingWater == nil {
                pendingWater = (try JSONSerialization.data(withJSONObject: [
                    "amount_ml": amount,
                    "consumed_at": ISO8601DateFormatter().string(from: .now)
                ]), UUID().uuidString)
                pendingWaterAcknowledged = false
            }
            guard let pending = pendingWater else { return }
            if !pendingWaterAcknowledged {
                let _: WaterRecord = try await authorized("nutrition/water", method: "POST", body: pending.body, key: pending.key)
                guard current == generation else { return }
                pendingWaterAcknowledged = true
            }
            await reload()
            guard current == generation else { return }
            if error == nil {
                pendingWater = nil
                pendingWaterAcknowledged = false
                waterMessage = "饮水记录已保存，首页已更新。"
            } else {
                waterMessage = "记录已保存，暂时无法刷新。请重试核对记录。"
            }
        } catch {
            guard current == generation else { return }
            if case NativeAPIError.response(let status, _) = error, (400..<500).contains(status), status != 408, status != 409, status != 429 {
                pendingWater = nil
            }
            waterMessage = Self.readable(error) + " 请先核对记录；重试会沿用本次提交标识。"
        }
    }

    func logout() async {
        guard !savingWater, passwordTask == nil else { return }
        if let token = refreshToken,
           let body = try? JSONSerialization.data(withJSONObject: ["refresh_token": token]) {
            let _: EmptyResponse? = try? await send("auth/logout", method: "POST", body: body)
        }
        clearSession()
    }

    private func clearSession() {
        generation = UUID()
        refreshTask?.cancel()
        refreshTask = nil
        accessToken = nil
        refreshToken = nil
        user = nil
        summary = nil
        water = []
        settings = .null
        accountLoaded = false
        profileInitialized = false
        pendingWater = nil
        waterMessage = nil
        clearSessionStore()
        local?.unbind()
    }

    private func accept(_ tokens: NativeTokens) throws {
        try saveSession(SavedNativeSession(server: serverText, refreshToken: tokens.refreshToken, user: tokens.user))
        try local?.bind(server:serverText,userID:tokens.user.id)
        accessToken = tokens.accessToken
        refreshToken = tokens.refreshToken
        user = tokens.user
    }

    private func refresh() async throws -> NativeTokens {
        if let task = refreshTask { return try await task.value }
        guard let token = refreshToken else { throw NativeAPIError.message("请先登录 NxtRep。") }
        let current = generation
        let task = Task { () throws -> NativeTokens in
            let body = try JSONSerialization.data(withJSONObject: ["refresh_token": token])
            let tokens: NativeTokens = try await send("auth/refresh", method: "POST", body: body)
            guard current == generation else { throw CancellationError() }
            try accept(tokens)
            return tokens
        }
        refreshTask = task
        defer { if current == generation { refreshTask = nil } }
        do { return try await task.value }
        catch {
            if current == generation,
               case NativeAPIError.response(let status, _) = error,
               status == 401 || status == 403 {
                self.error = Self.readable(error)
                clearSession()
            }
            throw error
        }
    }

    private func authorized<T: Decodable>(_ path: String, method: String = "GET", body: Data? = nil, key: String? = nil) async throws -> T {
        if let passwordTask { _ = try await passwordTask.value }
        if accessToken == nil { _ = try await refresh() }
        let sentToken = accessToken
        do { return try await send(path, method: method, body: body, token: sentToken, key: key) }
        catch NativeAPIError.response(let status, _) where status == 401 {
            do {
                // A slower request may return 401 after another request already rotated the token.
                if accessToken == sentToken { _ = try await refresh() }
            }
            catch {
                if case NativeAPIError.response(let refreshStatus, _) = error, refreshStatus == 401 { clearSession() }
                throw error
            }
            return try await send(path, method: method, body: body, token: accessToken, key: key)
        }
    }

    private func send<T: Decodable>(_ path: String, method: String = "GET", body: Data? = nil, token: String? = nil, key: String? = nil) async throws -> T {
        guard let baseURL, let url = URL(string: baseURL.absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/")) + "/" + path) else {
            throw NativeAPIError.message("请先设置服务器地址。")
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.httpBody = body
        request.timeoutInterval = method == "GET" ? 30 : 180
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if body != nil { request.setValue("application/json", forHTTPHeaderField: "Content-Type") }
        if let token { request.setValue("Bearer " + token, forHTTPHeaderField: "Authorization") }
        if let key { request.setValue(key, forHTTPHeaderField: "Idempotency-Key") }
        let (data, response) = try await transport.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw NativeAPIError.message("服务器响应无法识别。") }
        guard (200..<300).contains(http.statusCode) else {
            let envelope = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
            let info = envelope?["error"] as? [String: Any]
            throw NativeAPIError.response(http.statusCode, info?["code"] as? String ?? "HTTP_\(http.statusCode)")
        }
        if http.statusCode == 204, let empty = EmptyResponse() as? T { return empty }
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        do { return try decoder.decode(T.self, from: http.statusCode == 204 ? Data("null".utf8) : data) }
        catch { throw NativeAPIError.message("接口数据格式与 App 不一致，请更新 App 后重试。") }
    }

    static func today() -> String {
        let formatter = DateFormatter()
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(secondsFromGMT: 8 * 3600)
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter.string(from: .now)
    }

    static func readable(_ error: Error) -> String {
        if let api = error as? NativeAPIError { return api.localizedDescription }
        if let url = error as? URLError {
            if url.code == .cancelled { return "请求已取消。" }
            if url.code == .notConnectedToInternet { return "系统没有提供可用网络（-1009）。请检查 NxtRep 的无线数据和本地网络权限。" }
            if url.code == .appTransportSecurityRequiresSecureConnection { return "系统限制了这个 HTTP 连接（-1022），请核对本地地址或使用 HTTPS。" }
            return "暂时无法连接服务器（\(url.code.rawValue)）。请检查网络连接和服务器状态。"
        }
        return "操作未完成，请稍后重试。"
    }
}

private struct EmptyResponse: Decodable {}
