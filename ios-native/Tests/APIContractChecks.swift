// Runs the real client transport/session code on the macOS build host without a phone or secrets.
import Foundation

enum NutrientKind { case carbs, protein, fat, water }

private final class StubServer: @unchecked Sendable {
    let lock = NSLock()
    var refreshCount = 0
    var rejectOldAccess = false
    var loseFirstWaterResponse = false
    var waterWrites: [(String, Data)] = []

    func handle(_ request: URLRequest) throws -> (Int, Data) {
        lock.lock()
        defer { lock.unlock() }
        let path = request.url!.path
        if path.hasSuffix("/foods/search") {
            let query = URLComponents(url:request.url!,resolvingAgainstBaseURL:false)!.queryItems!
            precondition(query.first {$0.name == "keyword"}?.value == "鸡胸肉 & 米饭")
            let page = query.first {$0.name == "page"}!.value!
            return (200,Data("{\"list\":[{\"id\":\"food-\(page)\",\"food_version_id\":\"version-\(page)\",\"basis_amount_g\":\"100\"}],\"has_more\":\(page == "1" ? "true" : "false")}".utf8))
        }
        if path.hasSuffix("/auth/login") || path.hasSuffix("/auth/refresh") {
            let refreshing = path.hasSuffix("/auth/refresh")
            if refreshing { refreshCount += 1 }
            let access = refreshing ? "new-access" : "old-access"
            return (200, Data("""
                {"access_token":"\(access)","refresh_token":"abcdefghijklmnopqrstuvwxyz0123456789","user":{"id":"test-user","username":"test"}}
                """.utf8))
        }
        if rejectOldAccess && request.value(forHTTPHeaderField: "Authorization") == "Bearer old-access" {
            return (401, Data("{\"error\":{\"code\":\"INVALID_ACCESS_TOKEN\"}}".utf8))
        }
        if path.hasSuffix("/nutrition/water") && request.httpMethod == "POST" {
            let body: Data
            if let data = request.httpBody {
                body = data
            } else if let stream = request.httpBodyStream {
                stream.open()
                defer { stream.close() }
                var collected = Data()
                var buffer = [UInt8](repeating: 0, count: 4096)
                while stream.hasBytesAvailable {
                    let count = stream.read(&buffer, maxLength: buffer.count)
                    if count <= 0 { break }
                    collected.append(buffer, count: count)
                }
                body = collected
            } else { throw URLError(.badServerResponse) }
            waterWrites.append((request.value(forHTTPHeaderField: "Idempotency-Key") ?? "", body))
            if loseFirstWaterResponse && waterWrites.count == 1 { throw URLError(.networkConnectionLost) }
            return (201, Data("{\"id\":\"water-1\",\"amount_ml\":250,\"consumed_at\":\"2026-11-09T01:00:00Z\"}".utf8))
        }
        if path.hasSuffix("/nutrition/water") { return (200, Data("[]".utf8)) }
        return (200, Data("""
            {"date":"2026-11-09","water_ml":250,"consumed":{"kcal":"12.5","carbs_g":"3.25","protein_g":0,"fat_g":"0"},"target":{"carbs_max_g":"240"}}
            """.utf8))
    }
}

private final class StubProtocol: URLProtocol, @unchecked Sendable {
    static var server = StubServer()
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        do {
            let (status, data) = try Self.server.handle(request)
            let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: ["Content-Type": "application/json"])!
            if request.url!.path.hasSuffix("/auth/refresh") {
                Thread.sleep(forTimeInterval: 0.1)
            }
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        } catch { client?.urlProtocol(self, didFailWithError: error) }
    }
    override func stopLoading() {}
}

@main
private enum APIContractChecks {
    @MainActor
    static func main() async throws {
        for address in ["http://172.20.10.10:8000/api/v1", "http://10.1.2.3:8000/api/v1", "https://example.com/api/v1"] {
            _ = try NativeSession.validatedURL(address)
        }
        for address in ["http://example.com/api/v1", "http://user:password@10.1.2.3/api/v1", "http://10.1.2.3/not-an-api", "http://10.1.2.3/api/v1?token=secret"] {
            do {
                _ = try NativeSession.validatedURL(address)
                fatalError("Unsafe address accepted")
            } catch NativeAPIError.message { /* Expected. */ }
        }
        print("PASS: server addresses reject public HTTP and embedded credentials")

        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [StubProtocol.self]
        let transport = URLSession(configuration: config)
        defer { transport.invalidateAndCancel() }
        var saved: SavedNativeSession?
        let session = NativeSession(transport: transport, saveSession: { saved = $0 }, loadSession: { nil }, clearSessionStore: { saved = nil })
        session.serverText = "http://127.0.0.1:8000/api/v1"
        await session.login(username: "test", password: "synthetic")
        precondition(session.signedIn && session.error == nil)
        precondition(session.summary?.consumed.kcal.value == 12.5)
        precondition(session.summary?.amount(.carbs) == 3)
        precondition(session.summary?.goal(.carbs) == 240)
        precondition(session.summary?.goal(.fat) == nil)
        precondition(saved?.refreshToken == "abcdefghijklmnopqrstuvwxyz0123456789")
        print("PASS: login, decimal strings, numeric values and range targets decode")
        let foods = try await session.allPages("foods/search",query:["keyword":"鸡胸肉 & 米饭"])
        precondition(foods.count == 2 && foods[1]["food_version_id"].text == "version-2")
        precondition(foods[0]["basis_amount_g"].double == 100)
        print("PASS: complete pagination, Chinese query encoding and original API field names")

        StubProtocol.server.rejectOldAccess = true
        async let first: Void = session.reload()
        async let second: Void = session.reload()
        _ = await (first, second)
        precondition(session.error == nil)
        precondition(StubProtocol.server.refreshCount == 1)
        print("PASS: concurrent expired requests share one refresh")

        StubProtocol.server.loseFirstWaterResponse = true
        await session.addWater(amount: 250)
        precondition(session.hasPendingWater)
        await session.addWater(amount: 250)
        precondition(!session.hasPendingWater)
        let writes = StubProtocol.server.waterWrites
        precondition(writes.count == 2 && !writes[0].0.isEmpty)
        precondition(writes[0].0 == writes[1].0 && writes[0].1 == writes[1].1)
        print("PASS: uncertain water response retries with identical key and timestamp")
    }
}
