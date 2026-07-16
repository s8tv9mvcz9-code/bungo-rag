package com.bungo.rag.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.DeleteOutline
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.bungo.rag.ChatUiState
import com.bungo.rag.ChatViewModel
import com.bungo.rag.data.ChatMessage
import com.bungo.rag.data.Palette
import com.bungo.rag.data.Source

private val EXAMPLES = listOf(
    "「今日はいい天気ですね」を旧字旧仮名に変換して",
    "「秋の夕暮れ」というテーマで文語体の文章を書いて",
    "「桜が散った。風が吹いた。」を格調高い文体に",
    "旧字旧仮名とはどういうものか教えて",
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen(vm: ChatViewModel = viewModel()) {
    val state by vm.ui.collectAsStateWithLifecycle()
    val listState = rememberLazyListState()

    // 新しい内容が来たら末尾へスクロール
    LaunchedEffect(state.messages.size, state.streaming, state.sources.size) {
        val total = listState.layoutInfo.totalItemsCount
        if (total > 0) listState.animateScrollToItem(total - 1)
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("📖 文語作文支援") },
                actions = {
                    IconButton(onClick = vm::reset) {
                        Icon(Icons.Filled.DeleteOutline, contentDescription = "会話をリセット")
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.surface,
                    titleContentColor = MaterialTheme.colorScheme.onSurface,
                    actionIconContentColor = MaterialTheme.colorScheme.onSurface,
                ),
            )
        },
        bottomBar = { InputBar(enabled = !state.isLoading, onSend = { vm.send(it) }) },
    ) { padding ->
        Box(
            Modifier
                .padding(padding)
                .fillMaxSize()
                .background(MaterialTheme.colorScheme.background)
        ) {
            if (state.messages.isEmpty() && state.streaming == null) {
                WelcomeView(onExample = { vm.send(it) })
            } else {
                MessageList(state, listState)
            }
        }
    }
}

@Composable
private fun WelcomeView(onExample: (String) -> Unit) {
    Column(
        Modifier
            .fillMaxSize()
            .padding(24.dp),
        verticalArrangement = Arrangement.Center,
    ) {
        Text(
            "青空文庫をコーパスとした\n戦前日本語スタイル支援",
            style = MaterialTheme.typography.titleLarge,
            color = MaterialTheme.colorScheme.onBackground,
        )
        Text(
            "現代語を旧字旧仮名・文語体へ。下の例から試せます。",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onBackground,
            modifier = Modifier.padding(top = 8.dp, bottom = 24.dp),
        )
        EXAMPLES.forEach { ex ->
            OutlinedButton(
                onClick = { onExample(ex) },
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(vertical = 4.dp),
            ) { Text(ex) }
        }
    }
}

@Composable
private fun MessageList(state: ChatUiState, listState: androidx.compose.foundation.lazy.LazyListState) {
    LazyColumn(
        state = listState,
        modifier = Modifier.fillMaxSize(),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(12.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        items(state.messages) { msg -> MessageBubble(msg) }

        // 生成中の暫定バブル
        if (state.streaming != null) {
            item {
                MessageBubble(
                    ChatMessage("assistant", state.streaming.ifBlank { "…" }),
                    streaming = true,
                )
            }
        }

        // 共感覚パレット（直近の応答の情調 → 伝統色）
        val palette = state.palette
        if (palette != null && !state.isLoading) {
            item { PaletteBar(palette) }
        }

        // 参照元（直近の応答に対して）
        if (state.sources.isNotEmpty() && !state.isLoading) {
            item { SourcesCard(state.sources) }
        }
    }
}

/** "#RRGGBB" → Compose Color（不正値は null）。
 * parseColor は未知色名で IllegalArgumentException、空文字/短文字列で
 * StringIndexOutOfBoundsException を投げるため RuntimeException で受ける。 */
private fun parseHexColor(hex: String?): Color? = try {
    if (hex.isNullOrBlank()) null
    else Color(android.graphics.Color.parseColor(hex))
} catch (_: RuntimeException) {
    null
}

/** 共感覚の色帯: 入力色 → 連想色 → 手本色 のグラデーションと伝統色名 */
@Composable
private fun PaletteBar(palette: Palette) {
    val colors = palette.stops.mapNotNull { parseHexColor(it) }
    if (colors.size < 2) return
    Column(Modifier.fillMaxWidth()) {
        Box(
            Modifier
                .fillMaxWidth()
                .height(8.dp)
                .background(
                    brush = Brush.horizontalGradient(colors),
                    shape = RoundedCornerShape(4.dp),
                )
        )
        val label = buildString {
            append("情調 「${palette.blend?.name ?: ""}」")
            if (palette.categories.isNotEmpty()) {
                append("　—　${palette.categories.joinToString("・")}の氣配")
            }
        }
        Text(
            label,
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onBackground.copy(alpha = 0.7f),
            modifier = Modifier.padding(top = 4.dp),
        )
    }
}

@Composable
private fun MessageBubble(msg: ChatMessage, streaming: Boolean = false) {
    val isUser = msg.role == "user"
    val bubbleColor =
        if (isUser) MaterialTheme.colorScheme.primary
        else MaterialTheme.colorScheme.surface
    val textColor =
        if (isUser) MaterialTheme.colorScheme.onPrimary
        else MaterialTheme.colorScheme.onSurface

    Row(
        Modifier.fillMaxWidth(),
        horizontalArrangement = if (isUser) Arrangement.End else Arrangement.Start,
    ) {
        Card(
            shape = RoundedCornerShape(14.dp),
            colors = androidx.compose.material3.CardDefaults.cardColors(containerColor = bubbleColor),
            modifier = Modifier.fillMaxWidth(0.88f),
        ) {
            Text(
                text = msg.content + if (streaming) " ▌" else "",
                color = textColor,
                style = MaterialTheme.typography.bodyLarge,
                modifier = Modifier.padding(14.dp),
            )
        }
    }
}

@Composable
private fun SourcesCard(sources: List<Source>) {
    var expanded by remember { mutableStateOf(false) }
    Card(
        colors = androidx.compose.material3.CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant,
        ),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(12.dp)) {
            Text(
                "📚 参照した青空文庫テキスト（${sources.size} 件）",
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                fontWeight = FontWeight.Bold,
                modifier = Modifier.clickableNoRipple { expanded = !expanded },
            )
            if (expanded) {
                sources.forEachIndexed { i, s ->
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier.padding(top = 8.dp),
                    ) {
                        // 共感覚: 手本の色点（旧サーバでは color=null → 表示なし）
                        parseHexColor(s.color)?.let { dot ->
                            Box(
                                Modifier
                                    .padding(end = 6.dp)
                                    .size(10.dp)
                                    .background(dot, CircleShape)
                            )
                        }
                        Text(
                            "[${i + 1}] ${s.title} / ${s.author}（${s.style}）" +
                                (s.colorName?.let { "〔$it〕" } ?: ""),
                            style = MaterialTheme.typography.bodyMedium,
                            fontWeight = FontWeight.Bold,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    Text(
                        s.text.take(160) + if (s.text.length > 160) "…" else "",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 4,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            } else {
                Text(
                    "タップして展開",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun InputBar(enabled: Boolean, onSend: (String) -> Unit) {
    var text by remember { mutableStateOf("") }
    Row(
        Modifier
            .background(MaterialTheme.colorScheme.surface)
            .fillMaxWidth()
            .padding(8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        OutlinedTextField(
            value = text,
            onValueChange = { text = it },
            modifier = Modifier.weight(1f),
            placeholder = { Text("依頼を入力（例：月夜の情景を文語体で）") },
            maxLines = 4,
        )
        IconButton(
            onClick = {
                if (text.isNotBlank()) {
                    onSend(text)
                    text = ""
                }
            },
            enabled = enabled,
        ) {
            if (enabled) {
                Icon(
                    Icons.AutoMirrored.Filled.Send,
                    contentDescription = "送信",
                    tint = MaterialTheme.colorScheme.primary,
                )
            } else {
                CircularProgressIndicator(
                    modifier = Modifier.size(24.dp),
                    strokeWidth = 2.dp,
                )
            }
        }
    }
}

/** リップル無しのタップ修飾子（ヘッダ展開用の簡易実装） */
@Composable
private fun Modifier.clickableNoRipple(onClick: () -> Unit): Modifier {
    val interaction = remember { MutableInteractionSource() }
    return this.clickable(
        interactionSource = interaction,
        indication = null,
        onClick = onClick,
    )
}
