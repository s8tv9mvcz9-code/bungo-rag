package com.bungo.rag

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import com.bungo.rag.ui.ChatScreen
import com.bungo.rag.ui.theme.BungoRagTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            BungoRagTheme {
                ChatScreen()
            }
        }
    }
}
