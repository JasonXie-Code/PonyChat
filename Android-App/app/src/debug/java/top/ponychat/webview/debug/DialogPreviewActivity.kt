package top.ponychat.webview.debug

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.Image
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import top.ponychat.webview.ui.common.PonyAlertDialog
import top.ponychat.webview.ui.common.PonyButton
import top.ponychat.webview.ui.common.PonyConfirmDialog
import top.ponychat.webview.ui.common.PonyDialogActionStyle
import top.ponychat.webview.ui.common.PonyDialogOption
import top.ponychat.webview.ui.common.PonyOptionDialog
import top.ponychat.webview.ui.theme.PonyChatTheme
import top.ponychat.webview.ui.theme.Primary

class DialogPreviewActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val dialogIndex = intent.getIntExtra("dialog_index", 0)
        setContent {
            PonyChatTheme(darkTheme = true) {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background
                ) {
                    Box(Modifier.fillMaxSize()) {
                        DialogPreview(dialogIndex)
                    }
                }
            }
        }
    }
}

@Composable
private fun DialogPreview(index: Int) {
    when (index) {
        0 -> PonyAlertDialog(
            title = "关于 PonyChat 角色",
            onDismiss = {},
            content = {
                Text(
                    "PonyChat 中所有角色均由人工智能驱动。\n\n" +
                        "角色的全部回复均为 AI 生成内容，不代表真实的感情承诺或真人关系。\n\n" +
                        "请理性使用，保持健康的现实生活。",
                    style = MaterialTheme.typography.bodyMedium
                )
            },
            confirmButton = {
                PonyButton(
                    text = "我已了解，进入应用",
                    onClick = {}
                )
            }
        )
        1 -> PonyConfirmDialog(
            title = "确认退出",
            message = "角色信息不全，退出将不保存，确认退出吗？",
            confirmText = "退出",
            actionStyle = PonyDialogActionStyle.Danger,
            onConfirm = {},
            onDismiss = {}
        )
        2 -> PonyConfirmDialog(
            title = "清空缓存",
            message = "将清除本地对话与角色大厅缓存，登录状态保留。建议完成后重启应用。",
            confirmText = "清空",
            onConfirm = {},
            onDismiss = {}
        )
        3 -> PonyConfirmDialog(
            title = "重置角色内容",
            message = "将清除与「Twilight Sparkle」的所有对话记录、对话记忆和陪玩记录。\n\n游戏/锁分内容不受影响。\n\n此操作不可撤销。",
            confirmText = "确认重置 (3)",
            actionStyle = PonyDialogActionStyle.Danger,
            confirmEnabled = false,
            onConfirm = {},
            onDismiss = {}
        )
        4 -> PonyOptionDialog(
            title = "导出 3 条消息",
            onDismiss = {},
            options = listOf(
                PonyDialogOption(
                    title = "导出为图片",
                    subtitle = "保存到相册，可直接分享",
                    icon = Icons.Filled.Image,
                    iconTint = Primary,
                    onClick = {}
                ),
                PonyDialogOption(
                    title = "复制为纯文本",
                    subtitle = "昵称 时间 / 消息内容，复制到剪贴板",
                    icon = Icons.Filled.ContentCopy,
                    iconTint = MaterialTheme.colorScheme.onSurfaceVariant,
                    onClick = {}
                )
            )
        )
        5 -> PonyAlertDialog(
            title = "扫描结果",
            onDismiss = {},
            content = {
                val scroll = rememberScrollState()
                Text(
                    "ponychat://character/import?id=demo-character-uuid&source=hall\n\n" +
                        "这类可滚动结果弹窗保留自定义内容区域，只统一标题、背景和按钮样式。",
                    color = MaterialTheme.colorScheme.onSurface,
                    style = MaterialTheme.typography.bodyMedium,
                    modifier = Modifier
                        .verticalScroll(scroll)
                        .heightIn(max = 360.dp)
                )
            },
            dismissButton = {
                TextButton(onClick = {}) {
                    Text("复制", color = MaterialTheme.colorScheme.primary, fontWeight = FontWeight.Medium)
                }
            },
            confirmButton = {
                TextButton(onClick = {}) {
                    Text("确定", color = Primary, fontWeight = FontWeight.Medium)
                }
            }
        )
        else -> PonyAlertDialog(
            title = "弹窗预览",
            message = "未知预览编号：$index",
            onDismiss = {}
        )
    }
}
