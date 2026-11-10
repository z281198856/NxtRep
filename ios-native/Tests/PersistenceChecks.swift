import Foundation
import CryptoKit

enum PersistenceChecks {
    @MainActor static func run() async throws {
        var parser = NativeSSEParser()
        _ = try parser.push(": keepalive")
        _ = try parser.push("event: message_delta")
        _ = try parser.push("data: {\"delta\":\"你好\"}")
        let event = try parser.push("")
        precondition(event?.0 == "message_delta" && event?.1["delta"].text == "你好")
        _ = try parser.push("data: {\"event\":\"completed\",")
        _ = try parser.push("data: \"response\":{\"message\":\"完成\"}}")
        let completed = try parser.finish()
        precondition(completed?.0 == "completed")
        print("PASS: SSE comments, boundaries, multiline JSON and event names")
        var reminders = NativeReminderConfig()
        var slots = try reminders.slots(); precondition(slots.isEmpty)
        reminders.enabled = true; reminders.rules[4].enabled = true
        slots = try reminders.slots(); precondition(slots.count == 5 && slots.allSatisfy {$0.0 == .water && $0.2 == 0})
        reminders.quietStart = 9*60; reminders.quietEnd = 12*60
        slots = try reminders.slots(); precondition(slots.count == 3)
        reminders.rules[4].weekdays = [1,3,5]
        slots = try reminders.slots(); precondition(slots.count == 9)
        precondition(reminders.isQuiet(9*60) && !reminders.isQuiet(12*60))
        reminders.rules[4].times = [540,540]
        do { _ = try reminders.slots(); preconditionFailure("Duplicate times accepted") } catch {}
        print("PASS: reminder opt-in, quiet boundaries, daily/weekly expansion and duplicate rejection")
        reminders = NativeReminderConfig(); reminders.enabled = true; reminders.quietEnabled = false
        for index in reminders.rules.indices { reminders.rules[index].enabled = true; reminders.rules[index].weekdays = [1,2,3,4,5,6]; reminders.rules[index].times = [480,540,600,660,720,780] }
        do { _ = try reminders.slots(); preconditionFailure("iOS notification limit exceeded") } catch {}
        print("PASS: notification plans above the iOS scheduling limit are rejected before replacing reminders")
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("nxtrep-persistence-"+UUID().uuidString,isDirectory:true)
        defer { try? FileManager.default.removeItem(at:root) }
        let bytes = Data(repeating:0x3a,count:32)
        let store = NativeLocalStore(directory:root,keyData:bytes)
        let body: [String:NativeJSON] = ["amount_ml":.int(250),"consumed_at":.string("2026-11-10T00:00:00Z")]
        try store.bind(server:"https://example.test/api/v1",userID:"account-a")
        let owner = store.scope!
        try store.saveDraft("water",label:"饮水",value:.object(["amount":.string("250")]))
        _ = try store.enqueue(path:"nutrition/water",body:body,key:"test-key",draftKey:"water")
        let location = root.appendingPathComponent(owner+".enc")
        let ciphertext = try Data(contentsOf:location)
        precondition(ciphertext.range(of:Data("consumed_at".utf8)) == nil)
        let restored = NativeLocalStore(directory:root,keyData:bytes)
        try restored.bind(server:"https://example.test/api/v1",userID:"account-a")
        precondition(restored.pending.count == 1 && restored.pending[0]["body"] == .object(body))
        precondition(restored.draft("water")["value"]["amount"].text == "250")
        print("PASS: encrypted journal and drafts survive recreation")
        try restored.bind(server:"https://example.test/api/v1",userID:"account-b")
        precondition(restored.pending.isEmpty && restored.drafts.isEmpty)
        try restored.bind(server:"https://other.test/api/v1",userID:"account-a")
        precondition(restored.pending.isEmpty)
        try restored.bind(server:"https://example.test/api/v1",userID:"account-a")
        print("PASS: account and server isolation preserve original queues")
        var attempts: [(String,[String:NativeJSON],String)] = []
        _ = await restored.sync { path,payload,key in attempts.append((path,payload,key)); throw URLError(.networkConnectionLost) }
        precondition(restored.pending.count == 1 && !restored.pending[0]["first_attempt_at"].isNull)
        let results = await restored.sync { path,payload,key in attempts.append((path,payload,key)); return .object(["id":.string("server-water")]) }
        precondition(attempts.count == 2 && attempts[0].1 == attempts[1].1 && attempts[0].2 == attempts[1].2)
        precondition(results["test-key"]?.id == "server-water" && restored.pending.isEmpty && restored.draft("water").isNull)
        let receipt = try restored.enqueue(path:"nutrition/water",body:body,key:"test-key")
        precondition(receipt?.id == "server-water" && restored.pending.isEmpty)
        print("PASS: uncertain writes retain key and time; receipts prevent duplicate submissions")
        do { _ = try restored.enqueue(path:"nutrition/water",body:["amount_ml":.int(500)],key:"test-key"); preconditionFailure("Acknowledged key accepted a changed payload") } catch {}
        _ = try restored.enqueue(path:"body/measurements",body:["weight_kg":.number(70)],key:"blocked")
        _ = await restored.sync { _,_,_ in throw NativeAPIError.response(409,"VERSION_CONFLICT") }
        precondition(!restored.pending[0]["issue"].text.isEmpty)
        var called = false
        _ = await restored.sync { _,_,_ in called = true; return .null }
        precondition(!called)
        print("PASS: business conflicts pause automatic replay")
        precondition(!NativeLocalStore.canRecord("confirmations/123/approve",method:"POST"))
        precondition(!NativeLocalStore.canRecord("agent/conversations/123/messages",method:"POST"))
        precondition(!NativeLocalStore.canRecord("nutrition/water",method:"DELETE"))
        print("PASS: AI, confirmations and destructive requests stay outside offline queue")
        let record:NativeJSON = .object(["key":.string("old-key"),"path":.string("nutrition/water"),"body":.object(body),"first_attempt_at":.string(NativeDates.timestamp(Date().addingTimeInterval(-24*3600)))])
        let old:NativeJSON = .object(["schema":.int(1),"pending":.array([record])])
        let sealed = try AES.GCM.seal(JSONEncoder().encode(old),using:SymmetricKey(data:bytes),authenticating:Data(owner.utf8)).combined!
        try sealed.write(to:location,options:.atomic)
        restored.unbind(); try restored.bind(server:"https://example.test/api/v1",userID:"account-a")
        called = false
        _ = await restored.sync { _,_,_ in called = true; return .null }
        precondition(!called && restored.pending[0]["issue"].text.contains("23"))
        print("PASS: old uncertain writes require reconciliation after 23 hours")
        var damaged = sealed; damaged[damaged.count-1] ^= 0xff; try damaged.write(to:location)
        restored.unbind()
        do { try restored.bind(server:"https://example.test/api/v1",userID:"account-a"); preconditionFailure("Tampered journal accepted") } catch {}
        let after = try Data(contentsOf:location); precondition(after == damaged)
        print("PASS: damaged ciphertext is rejected without overwriting original data")
    }
}
