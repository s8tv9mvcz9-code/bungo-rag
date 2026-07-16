package com.bungo.rag

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.bungo.rag.data.BungoApi
import com.bungo.rag.data.ChatMessage
import com.bungo.rag.data.ChatRequest
import com.bungo.rag.data.Source
import com.bungo.rag.data.StreamEvent
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

data class ChatUiState(
    val messages: List<ChatMessage> = emptyList(),
    val streaming: String? = null,          // 生成中の暫定アシスタント応答
    val sources: List<Source> = emptyList(),
    val isLoading: Boolean = false,
    val error: String? = null,
)

class ChatViewModel : ViewModel() {

    private val api = BungoApi(BuildConfig.BASE_URL, BuildConfig.API_KEY)

    private val _ui = MutableStateFlow(ChatUiState())
    val ui: StateFlow<ChatUiState> = _ui.asStateFlow()

    fun send(text: String, topK: Int = 5) {
        val message = text.trim()
        if (message.isEmpty() || _ui.value.isLoading) return

        val history = _ui.value.messages
        _ui.update {
            it.copy(
                messages = it.messages + ChatMessage("user", message),
                streaming = "",
                sources = emptyList(),
                isLoading = true,
                error = null,
            )
        }

        viewModelScope.launch {
            val builder = StringBuilder()
            try {
                withContext(Dispatchers.IO) {
                    api.streamChat(
                        ChatRequest(message = message, history = history, topK = topK)
                    ) { event ->
                        when (event) {
                            is StreamEvent.Token -> {
                                builder.append(event.content)
                                _ui.update { it.copy(streaming = builder.toString()) }
                            }
                            is StreamEvent.Sources ->
                                _ui.update { it.copy(sources = event.sources) }
                            is StreamEvent.Error ->
                                _ui.update { it.copy(error = event.message) }
                            StreamEvent.Done -> Unit
                        }
                    }
                }
                commitAssistant(builder.toString())
            } catch (e: Exception) {
                _ui.update {
                    it.copy(
                        isLoading = false,
                        streaming = null,
                        error = "通信エラー: ${e.message ?: e.javaClass.simpleName}",
                    )
                }
            }
        }
    }

    private fun commitAssistant(full: String) {
        _ui.update {
            val finalText = full.ifBlank { it.error?.let { e -> "⚠️ $e" } ?: "" }
            it.copy(
                messages = if (finalText.isBlank()) it.messages
                else it.messages + ChatMessage("assistant", finalText),
                streaming = null,
                isLoading = false,
            )
        }
    }

    fun reset() {
        _ui.value = ChatUiState()
    }

    override fun onCleared() {
        api.close()
        super.onCleared()
    }
}
