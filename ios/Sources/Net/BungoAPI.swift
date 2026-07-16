import Foundation

/// NDJSON 1行の生デコード用（"type" フィールドで分岐する）。
/// BungoAPI 内部の実装詳細のためこのファイルにのみ閉じる。
private struct RawEvent: Decodable {
    let type: String
    let content: String?
    let sources: [Source]?
    let message: String?
}

/// bungo-rag バックエンドへのクライアント。
/// /chat の NDJSON ストリームを1行ずつ StreamEvent にデコードして
/// コールバックへ渡す（API契約 §2.1）。
final class BungoAPI {
    private let base: URL
    private let apiKey: String?
    private let session: URLSession

    init(baseURL: URL, apiKey: String? = nil) {
        self.base = baseURL
        self.apiKey = apiKey
        let c = URLSessionConfiguration.default
        c.timeoutIntervalForRequest = 200   // scale-to-zero コールドスタート(最大1〜2分)対応
        c.timeoutIntervalForResource = 600
        self.session = URLSession(configuration: c)
    }

    /// RAG応答をストリーミング取得する。各イベントを onEvent で受け取る。
    /// 例外はそのまま送出されるため、呼び出し側で捕捉すること。
    func streamChat(_ req: ChatRequest, onEvent: @escaping (StreamEvent) -> Void) async throws {
        var r = URLRequest(url: base.appendingPathComponent("chat"))
        r.httpMethod = "POST"
        r.setValue("application/json", forHTTPHeaderField: "Content-Type")
        r.setValue("application/x-ndjson", forHTTPHeaderField: "Accept")
        // 関係者キーが設定されていれば送る（nil なら公開枠のまま）
        if let apiKey { r.setValue(apiKey, forHTTPHeaderField: "X-API-Key") }
        r.httpBody = try JSONEncoder().encode(req)

        let (bytes, resp) = try await session.bytes(for: r)
        guard let h = resp as? HTTPURLResponse, 200..<300 ~= h.statusCode else {
            throw URLError(.badServerResponse)
        }

        for try await line in bytes.lines {
            guard let data = line.data(using: .utf8),
                  let raw = try? JSONDecoder().decode(RawEvent.self, from: data) else { continue }
            switch raw.type {
            case "token":
                if let c = raw.content { onEvent(.token(c)) }
            case "sources":
                onEvent(.sources(raw.sources ?? []))
            case "done":
                onEvent(.done)
            case "error":
                onEvent(.error(raw.message ?? "unknown"))
            default:
                break
            }
        }
    }
}
