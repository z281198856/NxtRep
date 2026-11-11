// Runs the real client transport/session code on the macOS build host without a phone or secrets.
import Foundation

enum NutrientKind { case carbs, protein, fat, water }

private final class StubServer: @unchecked Sendable {
    let lock = NSLock()
    var refreshCount = 0
    var rejectOldAccess = false
    var loseFirstWaterResponse = false
    var waterWrites: [(String, Data)] = []
    let conversationID = "b413b9cf-43f7-45fc-9a76-09174e1d32a0"
    let runID = "c98415df-1c9a-4fea-9b9b-b3605607bf4a"
    var conversationsCreated = 0
    var messagesSent = 0
    var stopTest = false
    private var stopStreamReleased = false
    private(set) var stopRequests = 0

    func releaseStopStream() { lock.withLock { stopStreamReleased = true } }
    var canStartStopStream: Bool { lock.withLock { stopStreamReleased } }
    var stopAccepted: Bool { lock.withLock { stopRequests == 2 } }

    func handle(_ request: URLRequest) throws -> (Int, Data) {
        lock.lock()
        defer { lock.unlock() }
        let path = request.url!.path
        if path.hasSuffix("/me") { return (200,Data("{\"profile_initialized\":true}".utf8)) }
        if path.hasSuffix("/settings") { return (200,Data("{\"unit_system\":\"metric\",\"privacy_mode\":\"private\",\"version\":1}".utf8)) }
        if path.hasSuffix("/exercises") {
            let query = URLComponents(url:request.url!,resolvingAgainstBaseURL:false)!.queryItems ?? []
            precondition(!query.contains {$0.name == "keyword" && ($0.value ?? "").isEmpty},"Optional keyword must not be sent empty")
            return (200,Data("{\"list\":[{\"id\":\"exercise-1\"}],\"has_more\":false}".utf8))
        }
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
        let conversation = Data("{\"id\":\"\(conversationID)\",\"title\":null,\"status\":\"active\"}".utf8)
        if path.hasSuffix("/agent/runs/" + runID) {
            return (200, run(status: "running", version: 2 + stopRequests))
        }
        if path.hasSuffix("/agent/runs/" + runID + ":cancel") {
            let body = try JSONDecoder().decode(NativeJSON.self, from: Self.requestBody(request))
            precondition(body["expected_version"].integer == 2 + stopRequests)
            stopRequests += 1
            if stopRequests == 1 {
                return (409, Data("{\"error\":{\"code\":\"AGENT_RUN_CONFLICT\"}}".utf8))
            }
            return (200, run(status: "cancel_requested", version: 4))
        }
        if path.hasSuffix("/agent/conversations") && request.httpMethod == "POST" {
            conversationsCreated += 1
            return (201, conversation)
        }
        if path.hasSuffix("/agent/conversations/" + conversationID) { return (200, conversation) }
        if path.hasSuffix("/agent/conversations/" + conversationID + "/messages") {
            if request.httpMethod == "POST" {
                let body = try JSONDecoder().decode(NativeJSON.self, from: Self.requestBody(request))
                precondition(body["message"].text == "这是一条联调消息")
                precondition(UUID(uuidString: body["client_turn_id"].text) != nil)
                messagesSent += 1
                if stopTest { return (200, Data()) }
                return (200, Data((
                    "event: run_started\r\ndata: {\"run_id\":\"c98415df-1c9a-4fea-9b9b-b3605607bf4a\"}\r\n\r\n" +
                    "event: message_delta\ndata: {\"delta\":\"你好\"}\n\n" +
                    "event: completed\ndata: {\"response\":{\"message\":\"你好\",\"status\":\"completed\",\"confirmation_cards\":[]}}\n\n"
                ).utf8))
            }
            return (200, Data("""
                {"list":[{"id":"message-1","sequence":1,"role":"user","content":"这是一条联调消息","image_asset_ids":[]},{"id":"message-2","sequence":2,"role":"assistant","content":"你好","image_asset_ids":[]}],"has_more":false}
                """.utf8))
        }
        if path.hasSuffix("/confirmations") {
            return (200, Data("{\"confirmation_cards\":[],\"completed_cards\":[]}".utf8))
        }
        if path.hasSuffix("/nutrition/water") && request.httpMethod == "POST" {
            let body = try Self.requestBody(request)
            waterWrites.append((request.value(forHTTPHeaderField: "Idempotency-Key") ?? "", body))
            if loseFirstWaterResponse && waterWrites.count == 1 { throw URLError(.networkConnectionLost) }
            return (201, Data("{\"id\":\"water-1\",\"amount_ml\":250,\"consumed_at\":\"2026-11-09T01:00:00Z\"}".utf8))
        }
        if path.hasSuffix("/nutrition/water") { return (200, Data("[]".utf8)) }
        return (200, Data("""
            {"date":"2026-11-09","water_ml":250,"consumed":{"kcal":"12.5","carbs_g":"3.25","protein_g":0,"fat_g":"0"},"target":{"carbs_max_g":"240"}}
            """.utf8))
    }

    private func run(status: String, version: Int) -> Data {
        Data("{\"id\":\"\(runID)\",\"conversation_id\":\"\(conversationID)\",\"status\":\"\(status)\",\"version\":\(version)}".utf8)
    }

    private static func requestBody(_ request: URLRequest) throws -> Data {
        if let data = request.httpBody { return data }
        guard let stream = request.httpBodyStream else { throw URLError(.badServerResponse) }
        stream.open()
        defer { stream.close() }
        var collected = Data()
        var buffer = [UInt8](repeating: 0, count: 4096)
        while stream.hasBytesAvailable {
            let count = stream.read(&buffer, maxLength: buffer.count)
            if count <= 0 { break }
            collected.append(buffer, count: count)
        }
        return collected
    }
}

private final class StubProtocol: URLProtocol, @unchecked Sendable {
    static var server = StubServer()
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        do {
            let (status, data) = try Self.server.handle(request)
            let contentType = request.value(forHTTPHeaderField: "Accept") == "text/event-stream"
                ? "text/event-stream; charset=utf-8" : "application/json"
            let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: ["Content-Type": contentType])!
            if request.url!.path.hasSuffix("/auth/refresh") {
                Thread.sleep(forTimeInterval: 0.1)
            }
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            if Self.server.stopTest && contentType.hasPrefix("text/event-stream") {
                deliverStopStream(started: false, remaining: 400)
                return
            }
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        } catch { client?.urlProtocol(self, didFailWithError: error) }
    }
    private func deliverStopStream(started: Bool, remaining: Int) {
        if remaining == 0 {
            client?.urlProtocol(self, didFailWithError: URLError(.timedOut))
            return
        }
        var hasStarted = started
        if !hasStarted && Self.server.canStartStopStream {
            let event = "event: run_started\ndata: {\"run_id\":\"\(Self.server.runID)\"}\n\n"
            client?.urlProtocol(self, didLoad: Data(event.utf8))
            hasStarted = true
        }
        if hasStarted && Self.server.stopAccepted {
            client?.urlProtocol(self, didLoad: Data("event: cancelled\ndata: {\"event\":\"cancelled\"}\n\n".utf8))
            client?.urlProtocolDidFinishLoading(self)
            return
        }
        let next = hasStarted
        DispatchQueue.global().asyncAfter(deadline: .now() + .milliseconds(10)) { [weak self] in
            self?.deliverStopStream(started: next, remaining: remaining - 1)
        }
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
        let exercises = try await session.allPages("exercises",query:NativeQueries.exercises(keyword:" \n "))
        precondition(exercises.count == 1)
        precondition(NativeQueries.exercises(keyword:" 卧推 ",equipment:"barbell")["keyword"] == "卧推")
        print("PASS: optional exercise search omits blank keywords and trims entered text")

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
        try await checkCoach(transport: transport)
        try checkChangePreview()
        try await PersistenceChecks.run()
    }

    @MainActor
    private static func checkCoach(transport: URLSession) async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let local = NativeLocalStore(directory: root, keyData: Data(repeating: 0x38, count: 32))
        let session = NativeSession(transport: transport, saveSession: { _ in }, loadSession: { nil }, clearSessionStore: {}, local: local)
        session.serverText = "http://127.0.0.1:8000/api/v1"
        await session.login(username: "test", password: "synthetic")
        let agent = NativeAgent()
        await agent.attach(session)
        try agent.startNewConversation()
        precondition(agent.canCompose && StubProtocol.server.conversationsCreated == 0)
        agent.input = "  这是一条联调消息  "
        agent.saveInput()
        local.localOnly = true
        await agent.send()
        precondition(agent.error != nil && agent.canSend && !agent.needsVerification)
        precondition(StubProtocol.server.conversationsCreated == 0)
        local.localOnly = false

        await agent.send()
        precondition(agent.error == nil, agent.error ?? "")
        precondition(!agent.needsVerification && agent.canCompose)
        precondition(StubProtocol.server.conversationsCreated == 1 && StubProtocol.server.messagesSent == 1)
        precondition(agent.messages.count == 2 && agent.messages.last?["content"].text == "你好")
        precondition(local.draft("ai-input-new").isNull)
        agent.input = "继续训练计划"
        try agent.startNewConversation()
        precondition(agent.conversation.id.isEmpty && agent.messages.isEmpty && agent.input.isEmpty)
        precondition(StubProtocol.server.conversationsCreated == 1)
        let reopened = NativeAgent()
        await reopened.attach(session)
        precondition(reopened.conversation.id.isEmpty && reopened.canCompose)
        try await reopened.open(StubProtocol.server.conversationID)
        precondition(reopened.input == "继续训练计划" && reopened.messages.count == 2)
        print("PASS: coach opens a writable new chat, creates on send, receives SSE, and keeps per-chat drafts")

        StubProtocol.server.stopTest = true
        reopened.input = "这是一条联调消息"
        let sending = Task { await reopened.send() }
        for _ in 0..<100 where !reopened.needsVerification {
            try await Task.sleep(for: .milliseconds(10))
        }
        precondition(reopened.receivingReply && reopened.needsVerification && reopened.pending["run_id"].isNull)
        reopened.requestStop()
        reopened.requestStop()
        precondition(reopened.stopping)
        StubProtocol.server.releaseStopStream()
        await sending.value
        precondition(reopened.error == nil, reopened.error ?? "")
        precondition(reopened.notice == "已停止回复。" && reopened.canCompose && !reopened.stopping)
        precondition(reopened.input == "这是一条联调消息" && StubProtocol.server.stopRequests == 2)
        print("PASS: early stop waits for run ID, retries a version conflict, and restores the cancelled draft")
    }

    private static func checkChangePreview() throws {
        let body = try JSONDecoder().decode(NativeJSON.self, from: Data("""
            {"operation_type":"body_measurement_create","impact":"{\\"internal\\":true}","after":{"measurement":{"weight_kg":"71.5","waist_cm":"79","measured_at":"2026-11-11T02:00:00Z","source":"manual","conditions":null,"notes":"[1,2]","expected_version":12}}}
            """.utf8))
        let preview = NativeChangePreview(card: body, imperial: false)
        let rows = preview.sections.flatMap(\.rows)
        precondition(preview.title == "保存身体记录" && preview.impact == nil)
        precondition(rows.map(\.label) == ["体重", "腰围", "测量时间"])
        precondition(rows[0].value.hasSuffix(" kg") && rows[1].value == "79 cm")
        precondition(rows[2].value == "2026-11-11 10:00")

        let meal = try JSONDecoder().decode(NativeJSON.self, from: Data("""
            {"operation_type":"nutrition_entry_create","status":"pending","after":{"entry":{"meal_type":"lunch"},"preview":{"items":[{"name":"米饭","amount_g":"150"},{"amount_g":"80"},{"name":"鸡胸肉","amount_g":"100"}],"totals":{"kcal":"330","protein_g":"28"}}}}
            """.utf8))
        let mealPreview = NativeChangePreview(card: meal, imperial: false)
        precondition(mealPreview.portions.map(\.id) == [0, 2])
        precondition(mealPreview.sections.flatMap(\.rows).contains { $0.label == "热量" && $0.value == "330 千卡" })
        print("PASS: change previews show named measurements and meal values, omit JSON, and retain item indices")
    }
}
