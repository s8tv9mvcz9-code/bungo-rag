package com.bungo.rag.ui.theme

import androidx.compose.material3.Typography
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.sp

// 本文は明朝（Serif）で古典的な趣を出す
val Typography = Typography(
    bodyLarge = TextStyle(
        fontFamily = FontFamily.Serif,
        fontSize = 16.sp,
        lineHeight = 26.sp,
    ),
    bodyMedium = TextStyle(
        fontFamily = FontFamily.Serif,
        fontSize = 14.sp,
        lineHeight = 22.sp,
    ),
    titleLarge = TextStyle(
        fontFamily = FontFamily.Serif,
        fontSize = 20.sp,
        lineHeight = 28.sp,
    ),
    labelLarge = TextStyle(
        fontFamily = FontFamily.SansSerif,
        fontSize = 14.sp,
    ),
)
