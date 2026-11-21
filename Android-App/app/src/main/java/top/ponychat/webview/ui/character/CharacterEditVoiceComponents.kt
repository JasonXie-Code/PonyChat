package top.ponychat.webview.ui.character

import android.net.Uri
import android.provider.OpenableColumns
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.UploadFile
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import top.ponychat.webview.data.model.Character
import top.ponychat.webview.ui.theme.ErrorColor
import top.ponychat.webview.ui.theme.Primary
import top.ponychat.webview.ui.theme.PrimaryLight
import top.ponychat.webview.ui.theme.ScaledIcon as Icon

@Composable
internal fun VoiceToneEditor(
    voiceEnabled: Boolean,
    onVoiceEnabledChange: (Boolean) -> Unit,
    sourceMode: String,
    onSourceModeChange: (String) -> Unit,
    voiceId: String,
    onVoiceIdChange: (String) -> Unit,
    instruct: String,
    onInstructChange: (String) -> Unit,
    referenceAudioUrl: String,
    referenceText: String,
    onReferenceTextChange: (String) -> Unit,
    isUploadingReference: Boolean,
    isDesigningVoice: Boolean,
    enabled: Boolean,
    onPreviewDesignVoice: () -> Unit,
    onReplaceDesignVoice: () -> Unit,
    onPickReferenceAudio: () -> Unit,
    onRemoveReferenceAudio: () -> Unit,
    onDisabledClick: () -> Unit
) {
    Column(modifier = Modifier.padding(bottom = 8.dp)) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .then(if (!enabled) Modifier.clickable { onDisabledClick() } else Modifier)
                .padding(horizontal = 16.dp, vertical = 12.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = "启用语音回复",
                    color = MaterialTheme.colorScheme.onBackground,
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.SemiBold
                )
                Text(
                    text = if (voiceEnabled) "聊天回复会生成语音消息" else "关闭后仅返回文本",
                    color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.68f),
                    style = MaterialTheme.typography.labelSmall
                )
            }
            Switch(
                checked = voiceEnabled,
                onCheckedChange = { if (enabled) onVoiceEnabledChange(it) else onDisabledClick() },
                enabled = enabled,
                colors = SwitchDefaults.colors(checkedThumbColor = Color.White, checkedTrackColor = Primary)
            )
        }
        CardDivider()
        VoiceModeSelector(
            selected = normalizeVoiceSourceMode(sourceMode),
            enabled = enabled,
            onSelected = onSourceModeChange,
            onDisabledClick = onDisabledClick
        )
        when (normalizeVoiceSourceMode(sourceMode)) {
            VOICE_SOURCE_INSTRUCT -> {
                CardDivider()
                Text(
                    text = "音色描述",
                    color = MaterialTheme.colorScheme.onBackground,
                    style = MaterialTheme.typography.titleSmall,
                    modifier = Modifier.padding(start = 16.dp, top = 12.dp)
                )
                MultilineEditItem(
                    value = instruct,
                    onValueChange = onInstructChange,
                    placeholder = "例如：清亮、轻快、靠近手机麦克风，语气自然",
                    minLines = 3,
                    maxLines = 5,
                    enabled = enabled,
                    onDisabledClick = onDisabledClick
                )
                DesignVoiceActionRow(
                    isBusy = isDesigningVoice,
                    enabled = enabled,
                    onPreview = onPreviewDesignVoice,
                    onReplace = onReplaceDesignVoice,
                    onDisabledClick = onDisabledClick
                )
            }
            VOICE_SOURCE_CLONE -> {
                CardDivider()
                ReferenceAudioPickerRow(
                    referenceAudioUrl = referenceAudioUrl,
                    isUploading = isUploadingReference,
                    enabled = enabled,
                    onPick = onPickReferenceAudio,
                    onRemove = onRemoveReferenceAudio,
                    onDisabledClick = onDisabledClick
                )
                CardDivider()
                Text(
                    text = "音频文本",
                    color = MaterialTheme.colorScheme.onBackground,
                    style = MaterialTheme.typography.titleSmall,
                    modifier = Modifier.padding(start = 16.dp, top = 12.dp)
                )
                MultilineEditItem(
                    value = referenceText,
                    onValueChange = onReferenceTextChange,
                    placeholder = "逐字填写参考音频中说出的内容",
                    minLines = 3,
                    maxLines = 6,
                    enabled = enabled,
                    onDisabledClick = onDisabledClick
                )
                CardDivider()
                Text(
                    text = "附加指令",
                    color = MaterialTheme.colorScheme.onBackground,
                    style = MaterialTheme.typography.titleSmall,
                    modifier = Modifier.padding(start = 16.dp, top = 12.dp)
                )
                MultilineEditItem(
                    value = instruct,
                    onValueChange = onInstructChange,
                    placeholder = "可选：描述语速、情绪、距离感",
                    minLines = 2,
                    maxLines = 4,
                    enabled = enabled,
                    onDisabledClick = onDisabledClick
                )
            }
            else -> {
                CardDivider()
                EditItem(
                    label = "Voice ID",
                    value = voiceId,
                    onValueChange = onVoiceIdChange,
                    placeholder = "例如 ponyvoice:muffins 或 longanyang",
                    enabled = enabled,
                    onDisabledClick = onDisabledClick
                )
            }
        }
    }
}

@Composable
private fun VoiceModeSelector(
    selected: String,
    enabled: Boolean,
    onSelected: (String) -> Unit,
    onDisabledClick: () -> Unit
) {
    Column(modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp)) {
        Text(
            text = "音色来源",
            color = MaterialTheme.colorScheme.onBackground,
            style = MaterialTheme.typography.titleSmall,
            fontWeight = FontWeight.SemiBold
        )
        Spacer(Modifier.height(10.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
            voiceModeOptions.forEach { option ->
                SelectablePill(
                    text = option.label,
                    selected = selected == option.value,
                    enabled = enabled,
                    modifier = Modifier.weight(1f),
                    onClick = { onSelected(option.value) },
                    onDisabledClick = onDisabledClick
                )
            }
        }
    }
}

@Composable
private fun SelectablePill(
    text: String,
    selected: Boolean,
    enabled: Boolean,
    modifier: Modifier = Modifier,
    onClick: () -> Unit,
    onDisabledClick: () -> Unit
) {
    Surface(
        modifier = modifier
            .height(38.dp)
            .clip(RoundedCornerShape(10.dp))
            .clickable { if (enabled) onClick() else onDisabledClick() },
        shape = RoundedCornerShape(10.dp),
        color = if (selected) Primary.copy(alpha = 0.18f) else MaterialTheme.colorScheme.surface.copy(alpha = 0.78f),
        border = androidx.compose.foundation.BorderStroke(
            1.dp,
            if (selected) Primary else MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.12f)
        )
    ) {
        Box(contentAlignment = Alignment.Center) {
            Text(
                text = text,
                color = if (selected) PrimaryLight else MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.labelMedium,
                fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Medium,
                textAlign = TextAlign.Center,
                maxLines = 1
            )
        }
    }
}

@Composable
private fun DesignVoiceActionRow(
    isBusy: Boolean,
    enabled: Boolean,
    onPreview: () -> Unit,
    onReplace: () -> Unit,
    onDisabledClick: () -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(start = 16.dp, end = 16.dp, top = 6.dp, bottom = 12.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        OutlinedButton(
            onClick = { if (enabled) onPreview() else onDisabledClick() },
            enabled = enabled && !isBusy,
            shape = RoundedCornerShape(10.dp),
            modifier = Modifier.weight(1f),
            border = androidx.compose.foundation.BorderStroke(1.dp, Primary.copy(alpha = 0.85f)),
            colors = ButtonDefaults.outlinedButtonColors(contentColor = PrimaryLight)
        ) {
            if (isBusy) {
                CircularProgressIndicator(color = PrimaryLight, modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
            } else {
                Icon(Icons.Filled.PlayArrow, contentDescription = null, tint = PrimaryLight, modifier = Modifier.size(17.dp))
                Spacer(Modifier.width(5.dp))
                Text("试听", style = MaterialTheme.typography.labelMedium)
            }
        }
        Button(
            onClick = { if (enabled) onReplace() else onDisabledClick() },
            enabled = enabled && !isBusy,
            shape = RoundedCornerShape(10.dp),
            modifier = Modifier.weight(1f),
            colors = ButtonDefaults.buttonColors(containerColor = Primary)
        ) {
            if (isBusy) {
                CircularProgressIndicator(color = Color.White, modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
            } else {
                Icon(Icons.Filled.Refresh, contentDescription = null, tint = Color.White, modifier = Modifier.size(16.dp))
                Spacer(Modifier.width(5.dp))
                Text("更换", color = Color.White, style = MaterialTheme.typography.labelMedium)
            }
        }
    }
}

@Composable
private fun ReferenceAudioPickerRow(
    referenceAudioUrl: String,
    isUploading: Boolean,
    enabled: Boolean,
    onPick: () -> Unit,
    onRemove: () -> Unit,
    onDisabledClick: () -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .then(if (!enabled) Modifier.clickable { onDisabledClick() } else Modifier)
            .padding(horizontal = 16.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = "参考音频",
                color = MaterialTheme.colorScheme.onBackground,
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.SemiBold
            )
            Text(
                text = referenceAudioUrl.takeIf { it.isNotBlank() }?.substringAfterLast("/") ?: "未上传",
                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.68f),
                style = MaterialTheme.typography.labelSmall,
                maxLines = 1
            )
        }
        if (referenceAudioUrl.isNotBlank() && enabled) {
            IconButton(onClick = onRemove, modifier = Modifier.size(38.dp)) {
                Icon(Icons.Filled.Close, contentDescription = "移除", tint = ErrorColor, modifier = Modifier.size(18.dp))
            }
        }
        Button(
            onClick = { if (enabled) onPick() else onDisabledClick() },
            enabled = enabled && !isUploading,
            shape = RoundedCornerShape(10.dp),
            contentPadding = PaddingValues(horizontal = 12.dp, vertical = 0.dp),
            colors = ButtonDefaults.buttonColors(containerColor = Primary)
        ) {
            if (isUploading) {
                CircularProgressIndicator(color = Color.White, modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
            } else {
                Icon(Icons.Filled.UploadFile, contentDescription = null, tint = Color.White, modifier = Modifier.size(16.dp))
                Spacer(Modifier.width(4.dp))
                Text("上传", color = Color.White, style = MaterialTheme.typography.labelMedium)
            }
        }
    }
}


internal const val VOICE_SOURCE_ID = "voice_id"
internal const val VOICE_SOURCE_INSTRUCT = "instruct"
internal const val VOICE_SOURCE_CLONE = "clone"
internal const val VOICE_POLICY_BACKEND = "director"

private data class VoiceOption(val value: String, val label: String)

private val voiceModeOptions = listOf(
    VoiceOption(VOICE_SOURCE_ID, "Voice ID"),
    VoiceOption(VOICE_SOURCE_INSTRUCT, "描述"),
    VoiceOption(VOICE_SOURCE_CLONE, "参考音频")
)

internal data class VoiceEditSettings(
    val enabled: Boolean,
    val voiceId: String,
    val voiceInstruct: String,
    val voiceDecisionPolicy: String,
    val voiceSourceMode: String,
    val voiceBaseVoiceId: String,
    val voiceReferenceAudioUrl: String,
    val voiceReferenceText: String,
    val voiceProfileId: String,
    val voiceCloneStatus: String
)

internal fun normalizeVoiceSourceMode(mode: String?): String {
    return when (mode?.trim()?.lowercase()) {
        VOICE_SOURCE_INSTRUCT, "instruction", "prompt" -> VOICE_SOURCE_INSTRUCT
        VOICE_SOURCE_CLONE, "reference", "reference_audio" -> VOICE_SOURCE_CLONE
        else -> VOICE_SOURCE_ID
    }
}

private fun isExternalVoiceId(value: String?): Boolean {
    val clean = value?.trim().orEmpty()
    return clean.isNotBlank() && !clean.startsWith("ponyvoice:", ignoreCase = true)
}

internal fun inferVoiceSourceMode(character: Character?): String {
    val explicit = character?.voiceSourceMode?.trim().orEmpty()
    if (explicit.isNotBlank()) return normalizeVoiceSourceMode(explicit)
    if (!character?.voiceReferenceAudioUrl.isNullOrBlank()) return VOICE_SOURCE_CLONE
    if (!character?.voiceInstruct.isNullOrBlank()) return VOICE_SOURCE_INSTRUCT
    return VOICE_SOURCE_ID
}

internal fun voiceEditSettingsFromCharacter(character: Character): VoiceEditSettings {
    val mode = inferVoiceSourceMode(character)
    val rawVoiceId = character.voiceId.orEmpty().trim()
    val rawProfileId = character.voiceProfileId.orEmpty().trim()
    return when (mode) {
        VOICE_SOURCE_INSTRUCT -> {
            val profileId = rawProfileId.ifBlank {
                rawVoiceId.takeIf { it.startsWith("ponyvoice:", ignoreCase = true) }.orEmpty()
            }
            VoiceEditSettings(
                enabled = character.voiceEnabled ?: rawVoiceId.isNotBlank(),
                voiceId = profileId.ifBlank { rawVoiceId },
                voiceInstruct = character.voiceInstruct.orEmpty().trim(),
                voiceDecisionPolicy = VOICE_POLICY_BACKEND,
                voiceSourceMode = VOICE_SOURCE_INSTRUCT,
                voiceBaseVoiceId = "",
                voiceReferenceAudioUrl = "",
                voiceReferenceText = "",
                voiceProfileId = profileId,
                voiceCloneStatus = character.voiceCloneStatus.orEmpty().trim()
            )
        }
        VOICE_SOURCE_CLONE -> {
            val profileId = rawProfileId.ifBlank {
                rawVoiceId.takeIf { it.startsWith("ponyvoice:", ignoreCase = true) }.orEmpty()
            }
            VoiceEditSettings(
                enabled = character.voiceEnabled ?: rawVoiceId.isNotBlank(),
                voiceId = profileId.ifBlank { rawVoiceId },
                voiceInstruct = character.voiceInstruct.orEmpty().trim(),
                voiceDecisionPolicy = VOICE_POLICY_BACKEND,
                voiceSourceMode = VOICE_SOURCE_CLONE,
                voiceBaseVoiceId = "",
                voiceReferenceAudioUrl = character.voiceReferenceAudioUrl.orEmpty().trim(),
                voiceReferenceText = character.voiceReferenceText.orEmpty().trim(),
                voiceProfileId = profileId,
                voiceCloneStatus = character.voiceCloneStatus.orEmpty().trim()
            )
        }
        else -> VoiceEditSettings(
            enabled = character.voiceEnabled ?: rawVoiceId.isNotBlank(),
            voiceId = rawVoiceId,
            voiceInstruct = "",
            voiceDecisionPolicy = VOICE_POLICY_BACKEND,
            voiceSourceMode = VOICE_SOURCE_ID,
            voiceBaseVoiceId = "",
            voiceReferenceAudioUrl = "",
            voiceReferenceText = "",
            voiceProfileId = "",
            voiceCloneStatus = ""
        )
    }
}

internal fun displayNameForUri(contentResolver: android.content.ContentResolver, uri: Uri): String {
    runCatching {
        contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { cursor ->
            if (cursor.moveToFirst()) {
                val index = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                if (index >= 0) {
                    val name = cursor.getString(index)
                    if (!name.isNullOrBlank()) return name
                }
            }
        }
    }
    val fallback = uri.lastPathSegment?.substringAfterLast('/')?.takeIf { it.isNotBlank() }
    return fallback ?: "voice_reference"
}

internal fun inferAudioMimeType(uri: Uri): String {
    return when (uri.toString().substringAfterLast('.', "").lowercase()) {
        "wav" -> "audio/wav"
        "webm" -> "audio/webm"
        "m4a", "mp4" -> "audio/mp4"
        "aac" -> "audio/aac"
        "ogg", "oga" -> "audio/ogg"
        "flac" -> "audio/flac"
        else -> "audio/mpeg"
    }
}

