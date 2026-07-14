import Foundation

/// チャット1発言（API契約 §2.1 と一致）
struct ChatMessage: Codable {
    let role: String
    let content: String
}

/// POST /chat のリクエストボディ（API契約 §2.1）
struct ChatRequest: Encodable {
    let message: String
    let history: [ChatMessage]
    let topK: Int

    enum CodingKeys: String, CodingKey {
        case message
        case history
        case topK = "top_k"
    }
}

/// 参照した青空文庫チャンク。未知キー（book_id 等）は Codable が自動で無視する。
struct Source: Decodable, Identifiable {
    let id = UUID()
    let title: String
    let author: String
    let style: String
    let text: String

    enum CodingKeys: String, CodingKey {
        case title, author, style, text
    }
}

/// NDJSONストリームの1行をデコードした結果（API契約 §2.1: token/sources/done/error）
enum StreamEvent {
    case token(String)
    case sources([Source])
    case done
    case error(String)
}
