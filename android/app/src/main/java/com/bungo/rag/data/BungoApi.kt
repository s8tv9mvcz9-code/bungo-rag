package com.bungo.rag.data

import io.ktor.client.HttpClient
import io.ktor.client.engine.android.Android
import io.ktor.client.plugins.HttpTimeout
import io.ktor.client.request.headers
import io.ktor.client.request.preparePost
import io.ktor.client.request.setBody
import io.ktor.client.statement.bodyAsChannel
import io.ktor.http.ContentType
import io.ktor.http.contentType
import io.ktor.serialization.kotlinx.json.json
import io.ktor.client.plugins.contentnegotiation.ContentNegotiation
import io.ktor.utils.io.readUTF8Line
import kotlinx.serialization.json.Json

/**
 * bungo-rag バックエンドへのクライアント。
 * /chat の NDJSON ストリームを 1 行ずつ [StreamEvent] にデコードして
 * コールバックへ渡す。
 */
class BungoApi(private val baseUrl: String) {

    private val json = Json {
        ignoreUnknownKeys = true   // @search.score など未知キーを無視
        classDiscriminator = "type"
    }

    private val client = HttpClient(Android) {
        install(ContentNegotiation) {
            json(json)
        }
        install(HttpTimeout) {
            // 生成は長くかかりうるのでリクエスト全体のタイムアウトは設けない
            requestTimeoutMillis = null
            connectTimeoutMillis = 30_000
            // Container Apps の scale-to-zero コールドスタート（最大1〜2分）を
            // 見込み、初回バイト到達までの待ちを 200 秒まで許容する
            socketTimeoutMillis = 200_000
        }
    }

    /**
     * RAG 応答をストリーミング取得する。各イベントを [onEvent] で受け取る。
     * 例外はそのまま送出されるため、呼び出し側で捕捉すること。
     */
    suspend fun streamChat(
        request: ChatRequest,
        onEvent: (StreamEvent) -> Unit,
    ) {
        client.preparePost("$baseUrl/chat") {
            contentType(ContentType.Application.Json)
            headers { append("Accept", "application/x-ndjson") }
            setBody(request)
        }.execute { response ->
            val channel = response.bodyAsChannel()
            while (true) {
                val line = channel.readUTF8Line() ?: break
                if (line.isBlank()) continue
                onEvent(json.decodeFromString(StreamEvent.serializer(), line))
            }
        }
    }

    fun close() = client.close()
}
