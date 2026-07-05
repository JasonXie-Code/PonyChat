package top.ponychat.webview.ui.theme

import androidx.compose.material3.Typography
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

/**
 * 应用字体规范（sp）
 * 阶梯：Display(28,24,22) → Title/Headline(18,17,16,15) → Body(16,14,13,12) → Label(12,11,10)
 * 行高约为字号的 1.25～1.4 倍，保证可读性。
 */
object AppFontSizes {
    /** 页面主标题（如个人资料顶部） */
    val displayHero = 32.sp
    /** 登录/品牌 Logo 标题 */
    val displayLogo = 38.sp
    val displayLarge = 28.sp
    val displayMedium = 24.sp
    val displaySmall = 22.sp
    /** 大标题与 displayMedium 之间的阶梯 */
    val displaySub = 26.sp
    val headlineLarge = 20.sp
    val headlineMedium = 18.sp
    val headlineSmall = 17.sp
    val titleLarge = 17.sp
    val titleMedium = 16.sp
    val titleSmall = 15.sp
    val bodyLarge = 18.sp
    val bodyMedium = 16.sp
    val bodySmall = 14.sp
    val labelLarge = 16.sp
    val labelMedium = 15.sp
    val labelSmall = 13.sp
    val caption = 12.sp
    /** 极小辅助文字（如角标） */
    val captionSmall = 11.sp

    /** HTML/富文本默认正文字号（Float，用于 AndroidView 等） */
    const val defaultBody = 16f
    const val defaultBodySmall = 15f
    const val defaultCaption = 14f
}

/** 行高（与字号配套） */
private object LineHeights {
    val lh36 = 36.sp
    val lh32 = 32.sp
    val lh28 = 28.sp
    val lh24 = 24.sp
    val lh22 = 22.sp
    val lh20 = 20.sp
    val lh18 = 18.sp
    val lh16 = 16.sp
}

val Typography = Typography(
    displayLarge = TextStyle(
        fontWeight = FontWeight.Bold,
        fontSize = AppFontSizes.displayLarge,
        lineHeight = LineHeights.lh32
    ),
    displayMedium = TextStyle(
        fontWeight = FontWeight.Bold,
        fontSize = AppFontSizes.displayMedium,
        lineHeight = LineHeights.lh32
    ),
    displaySmall = TextStyle(
        fontWeight = FontWeight.SemiBold,
        fontSize = AppFontSizes.displaySmall,
        lineHeight = LineHeights.lh28
    ),
    headlineLarge = TextStyle(
        fontWeight = FontWeight.SemiBold,
        fontSize = AppFontSizes.headlineLarge,
        lineHeight = LineHeights.lh28
    ),
    headlineMedium = TextStyle(
        fontWeight = FontWeight.Medium,
        fontSize = AppFontSizes.headlineMedium,
        lineHeight = LineHeights.lh24
    ),
    headlineSmall = TextStyle(
        fontWeight = FontWeight.Medium,
        fontSize = AppFontSizes.headlineSmall,
        lineHeight = LineHeights.lh24
    ),
    titleLarge = TextStyle(
        fontWeight = FontWeight.SemiBold,
        fontSize = AppFontSizes.titleLarge,
        lineHeight = LineHeights.lh24
    ),
    titleMedium = TextStyle(
        fontWeight = FontWeight.Medium,
        fontSize = AppFontSizes.titleMedium,
        lineHeight = LineHeights.lh24
    ),
    titleSmall = TextStyle(
        fontWeight = FontWeight.Medium,
        fontSize = AppFontSizes.titleSmall,
        lineHeight = LineHeights.lh20
    ),
    bodyLarge = TextStyle(
        fontWeight = FontWeight.Normal,
        fontSize = AppFontSizes.bodyLarge,
        lineHeight = LineHeights.lh28
    ),
    bodyMedium = TextStyle(
        fontWeight = FontWeight.Normal,
        fontSize = AppFontSizes.bodyMedium,
        lineHeight = LineHeights.lh24
    ),
    bodySmall = TextStyle(
        fontWeight = FontWeight.Normal,
        fontSize = AppFontSizes.bodySmall,
        lineHeight = LineHeights.lh20
    ),
    labelLarge = TextStyle(
        fontWeight = FontWeight.Medium,
        fontSize = AppFontSizes.labelLarge,
        lineHeight = LineHeights.lh24
    ),
    labelMedium = TextStyle(
        fontWeight = FontWeight.Medium,
        fontSize = AppFontSizes.labelMedium,
        lineHeight = LineHeights.lh20
    ),
    labelSmall = TextStyle(
        fontWeight = FontWeight.Medium,
        fontSize = AppFontSizes.labelSmall,
        lineHeight = LineHeights.lh18
    )
)
