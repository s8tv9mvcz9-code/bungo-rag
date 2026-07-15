package com.bungo.rag.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable

private val DarkColors = darkColorScheme(
    primary = Cha,
    onPrimary = InkDark,
    secondary = Shu,
    background = Sumi,
    onBackground = Kinari,
    surface = SumiVariant,
    onSurface = Kinari,
    surfaceVariant = SumiVariant,
    onSurfaceVariant = Kinari,
)

private val LightColors = lightColorScheme(
    primary = Cha,
    onPrimary = WashiLight,
    secondary = Shu,
    background = WashiLight,
    onBackground = InkDark,
    surface = WashiLight,
    onSurface = InkDark,
)

@Composable
fun BungoRagTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit,
) {
    MaterialTheme(
        colorScheme = if (darkTheme) DarkColors else LightColors,
        typography = Typography,
        content = content,
    )
}
