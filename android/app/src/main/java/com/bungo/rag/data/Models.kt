package com.bungo.rag.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/** チャット 1 発言（API リクエスト履歴用 / UI 表示用を兼ねる） */
@Serializable
data class ChatMessage(
    val role: String,      // "user" | "assistant"
    val content: String,
)

/** POST /chat のリクエストボディ */
@Serializable
data class ChatRequest(
    val message: String,
    val history: List<ChatMessage>,
    @SerialName("top_k") val topK: Int = 5,
)

/** 参照した青空文庫チャンク（color/colorName は共感覚の追加キー。旧サーバでは欠落=null） */
@Serializable
data class Source(
    val title: String = "",
    val author: String = "",
    val style: String = "",
    val text: String = "",
    val color: String? = null,                       // 例 "#6C848D"
    @SerialName("color_name") val colorName: String? = null,  // 例 "藍鼠"
)

/** 共感覚パレットの 1 色（日本の伝統色） */
@Serializable
data class PaletteColor(
    val hex: String = "",
    val name: String = "",
    val strength: Double? = null,
)

/**
 * 共感覚パレット（sources イベントの追加キー "palette"）。
 * 旧サーバは送らない → null。旧クライアントは ignoreUnknownKeys で無視 → 双方向互換。
 */
@Serializable
data class Palette(
    val stops: List<String> = emptyList(),           // グラデーション hex 列
    val input: PaletteColor? = null,                 // 入力文の色
    val blend: PaletteColor? = null,                 // 連想（補間）色
    val exemplar: PaletteColor? = null,              // 手本の合成色
    val categories: List<String> = emptyList(),      // 情調ラベル（例 ["哀愁","月影"]）
)

/**
 * NDJSON ストリームの 1 行。"type" フィールドで種別を判別する
 * （Json の classDiscriminator = "type" 設定と対応）。
 */
@Serializable
sealed class StreamEvent {
    @Serializable
    @SerialName("token")
    data class Token(val content: String) : StreamEvent()

    @Serializable
    @SerialName("sources")
    data class Sources(
        val sources: List<Source> = emptyList(),
        val palette: Palette? = null,
    ) : StreamEvent()

    @Serializable
    @SerialName("done")
    data object Done : StreamEvent()

    @Serializable
    @SerialName("error")
    data class Error(val message: String) : StreamEvent()
}
