package top.ponychat.webview.ui.chat

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.DirectionsRun
import androidx.compose.material.icons.automirrored.filled.EventNote
import androidx.compose.material.icons.filled.AutoAwesome
import androidx.compose.material.icons.filled.AutoStories
import androidx.compose.material.icons.filled.DateRange
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.People
import androidx.compose.material.icons.filled.Psychology
import androidx.compose.material.icons.filled.Today
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector

internal data class MemoryTypeConfig(
    val key: String,
    val label: String,
    val icon: ImageVector,
    val color: Color
)

internal val FRAGMENT_TYPES = listOf(
    MemoryTypeConfig("preference", "偏好", Icons.Filled.Favorite, Color(0xFFFF6B9D)),
    MemoryTypeConfig("episode", "经历", Icons.Filled.AutoStories, Color(0xFF4ECDC4)),
    MemoryTypeConfig("relationship", "关系", Icons.Filled.People, Color(0xFFFFBE0B)),
    MemoryTypeConfig("activity", "活动", Icons.AutoMirrored.Filled.DirectionsRun, Color(0xFF8338EC))
)

internal fun fragmentTypeConfig(key: String): MemoryTypeConfig =
    FRAGMENT_TYPES.find { it.key == key } ?: FRAGMENT_TYPES[1]

internal data class LayerTabConfig(
    val layer: Int,
    val label: String,
    val icon: ImageVector,
    val color: Color,
    val desc: String
)

internal val LAYER_TABS = listOf(
    LayerTabConfig(0, "碎片", Icons.Filled.Psychology, Color(0xFF9C6FD6), "原始记忆碎片"),
    LayerTabConfig(1, "日摘", Icons.Filled.Today, Color(0xFF4ECDC4), "每日记忆摘要"),
    LayerTabConfig(2, "周摘", Icons.Filled.DateRange, Color(0xFF4A90E2), "每周记忆摘要"),
    LayerTabConfig(3, "月摘", Icons.AutoMirrored.Filled.EventNote, Color(0xFFFF9F43), "每月记忆摘要"),
    LayerTabConfig(4, "年意识", Icons.Filled.AutoAwesome, Color(0xFFFFD700), "年度意识演化")
)
