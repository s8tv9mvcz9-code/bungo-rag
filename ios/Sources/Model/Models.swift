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
/// color/colorName は共感覚の追加キー（旧サーバでは欠落 = nil）。
struct Source: Decodable, Identifiable {
    let id = UUID()
    let title: String
    let author: String
    let style: String
    let text: String
    let color: String?          // 例 "#6C848D"
    let colorName: String?      // 例 "藍鼠"

    enum CodingKeys: String, CodingKey {
        case title, author, style, text, color
        case colorName = "color_name"
    }
}

/// 共感覚パレットの 1 色（日本の伝統色）
struct PaletteColor: Decodable {
    let hex: String
    let name: String
    let strength: Double?
}

/// 共感覚パレット（sources イベントの追加キー "palette"）。
/// 旧サーバは送らない → nil。旧クライアントは未知キーとして無視 → 双方向互換。
struct Palette: Decodable {
    let stops: [String]                 // グラデーション hex 列
    let input: PaletteColor?            // 入力文の色
    let blend: PaletteColor?            // 連想（補間）色
    let exemplar: PaletteColor?         // 手本の合成色
    let categories: [String]?           // 情調ラベル（例 ["哀愁","月影"]）
}

/// NDJSONストリームの1行をデコードした結果（API契約 §2.1: token/sources/done/error）
enum StreamEvent {
    case token(String)
    case sources([Source], Palette?)
    case done
    case error(String)
}
