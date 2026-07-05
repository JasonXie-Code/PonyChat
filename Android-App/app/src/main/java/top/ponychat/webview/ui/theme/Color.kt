package top.ponychat.webview.ui.theme

import androidx.compose.ui.graphics.Color

// ============================================================
// Dark Theme — matches WebView dark palette (#0f1419 base)
// ============================================================

val DarkBackground    = Color(0xFF0F1419)   // --bg-color
val DarkSurface       = Color(0xFF1A1F28)   // --surface-color (glass-bg base)
val DarkSurfaceVariant= Color(0xFF252D3A)   // --surface-light
val DarkCard          = Color(0xFF1A1F28)   // same as surface
val DarkCardElevated  = Color(0xFF252D3A)   // elevated card

// Primary palette — Indigo, matches WebView #6366f1 / #4f46e5
val Primary           = Color(0xFF6366F1)   // --primary-color
val PrimaryVariant    = Color(0xFF4F46E5)   // --primary-variant
val PrimaryLight      = Color(0xFF818CF8)   // lighter indigo tint
val PrimaryContainer  = Color(0xFF1E1B4B)   // dark indigo container

// Popup menus — unified dark blue surface for contextual menus
val PopupMenuBackground = Color(0xFF0B1228)
val PopupMenuOnBackground = Color(0xFFEFF6FF)
val PopupMenuDanger = Color(0xFFFF6B6B)

// Secondary — Cyan, matches WebView #06b6d4
val Secondary         = Color(0xFF06B6D4)
val SecondaryVariant  = Color(0xFF0891B2)

// Accent colors
val AccentRose        = Color(0xFFFF4081)
val AccentAmber       = Color(0xFFFFC107)

// Text on dark backgrounds
val DarkOnBackground  = Color(0xFFF1F5F9)   // --text-primary
val DarkOnSurface     = Color(0xFFE2E8F0)
val DarkOnSurfaceVariant = Color(0xFF94A3B8) // --text-secondary
val DarkOnPrimary     = Color(0xFFFFFFFF)

// Semantic
val ErrorColor        = Color(0xFFEF4444)
val SuccessColor      = Color(0xFF22C55E)

// Message bubbles
// User: solid indigo (WebView uses gradient #6366f1→#4f46e5, solid approximation)
val UserBubble        = Color(0xFF4F46E5)   // --msg-user-bg
// Assistant: transparent — Gemini-style, no bubble background
val AssistantBubble   = Color.Transparent   // --msg-bot-bg is transparent in bot CSS

// ============================================================
// Light Theme — matches WebView light palette (#f8fafc base)
// ============================================================

val LightBackground      = Color(0xFFF8FAFC)  // --bg-color (light)
val LightSurface         = Color(0xFFFFFFFF)  // --surface-color (light)
val LightSurfaceVariant  = Color(0xFFF1F5F9)  // --surface-light (light)
val LightCard            = Color(0xFFFFFFFF)
val LightOnBackground    = Color(0xFF1E293B)   // --text-primary (light)
val LightOnSurface       = Color(0xFF334155)
val LightOnSurfaceVariant= Color(0xFF64748B)   // --text-secondary (light)
val LightUserBubble      = Color(0xFF4F46E5)   // same user bubble in light
val LightAssistantBubble = Color.Transparent   // also transparent in light (text on light bg)
