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

/** 参照した青空文庫チャンク */
@Serializable
data class Source(
    val title: String = "",
    val author: String = "",
    val style: String = "",
    val text: String = "",
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
    data class Sources(val sources: List<Source>) : StreamEvent()

    @Serializable
    @SerialName("done")
    data object Done : StreamEvent()

    @Serializable
    @SerialName("error")
    data class Error(val message: String) : StreamEvent()
}
