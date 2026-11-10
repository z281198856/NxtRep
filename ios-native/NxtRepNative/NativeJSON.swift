import Foundation

/// Preserves API field names and Decimal strings across all business modules.
enum NativeJSON: Codable, Equatable, Sendable {
    case object([String: NativeJSON]), array([NativeJSON]), string(String), int(Int), number(Double), bool(Bool), null

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let v = try? c.decode(Bool.self) { self = .bool(v) }
        else if let v = try? c.decode(Int.self) { self = .int(v) }
        else if let v = try? c.decode(Double.self) { self = .number(v) }
        else if let v = try? c.decode(String.self) { self = .string(v) }
        else if let v = try? c.decode([String: NativeJSON].self) { self = .object(v) }
        else { self = .array(try c.decode([NativeJSON].self)) }
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .object(let v): try c.encode(v)
        case .array(let v): try c.encode(v)
        case .string(let v): try c.encode(v)
        case .int(let v): try c.encode(v)
        case .number(let v): try c.encode(v)
        case .bool(let v): try c.encode(v)
        case .null: try c.encodeNil()
        }
    }

    subscript(_ key: String) -> NativeJSON { fields[key] ?? .null }
    var fields: [String: NativeJSON] { if case .object(let v) = self { return v }; return [:] }
    var values: [NativeJSON] { if case .array(let v) = self { return v }; return [] }
    var text: String {
        switch self {
        case .string(let v): return v
        case .int(let v): return String(v)
        case .number(let v): return v.formatted(.number.precision(.fractionLength(0...2)))
        default: return ""
        }
    }
    var double: Double { switch self { case .number(let v): return v; case .int(let v): return Double(v); default: return Double(text) ?? 0 } }
    var integer: Int { Int(double) }
    var flag: Bool { if case .bool(let v) = self { return v }; return false }
    var isNull: Bool { self == .null }
    var strings: [String] { values.map(\.text) }
    var id: String { if !self["id"].text.isEmpty { return self["id"].text }; return self["confirmation_id"].text.isEmpty ? self["key"].text : self["confirmation_id"].text }
    var version: Int { self["version"].integer }
    var records: [NativeJSON] { if case .array = self { return values }; return self["list"].values }
    static func strings(_ values: [String]) -> NativeJSON { .array(values.map(NativeJSON.string)) }
}

enum NativeDates {
    static let china = TimeZone(secondsFromGMT: 8 * 3600)!
    static func day(_ date: Date = .now) -> String {
        let f = DateFormatter()
        f.calendar = Calendar(identifier: .gregorian)
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = china
        f.dateFormat = "yyyy-MM-dd"
        return f.string(from: date)
    }
    static func timestamp(_ date: Date = .now) -> String { ISO8601DateFormatter().string(from: date) }
    static func parse(_ text: String) -> Date? {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let d = f.date(from: text) { return d }
        f.formatOptions = [.withInternetDateTime]
        if let d = f.date(from: text) { return d }
        let day = DateFormatter()
        day.timeZone = china
        day.dateFormat = "yyyy-MM-dd"
        return day.date(from: text)
    }
    static func display(_ text: String) -> String { parse(text)?.formatted(date: .abbreviated, time: .shortened) ?? text }
}

struct NativeSSEParser {
    private var name = "message"
    private var data: [String] = []
    mutating func push(_ line:String) throws -> (String,NativeJSON)? {
        if line.isEmpty { return try finish() }
        if line.hasPrefix(":") { return nil }
        let pair = line.split(separator:":",maxSplits:1,omittingEmptySubsequences:false)
        var value = pair.count > 1 ? String(pair[1]) : ""
        if value.hasPrefix(" ") { value.removeFirst() }
        if pair[0] == "event" { name = value }
        if pair[0] == "data" { data.append(value) }
        guard data.reduce(0,{$0+$1.utf8.count}) <= 8_000_000 else { throw URLError(.dataLengthExceedsMaximum) }
        return nil
    }
    mutating func finish() throws -> (String,NativeJSON)? {
        defer { name = "message"; data = [] }
        guard !data.isEmpty else { return nil }
        let value = try JSONDecoder().decode(NativeJSON.self,from:Data(data.joined(separator:"\n").utf8))
        return (value["event"].text.isEmpty ? name : value["event"].text,value)
    }
}
