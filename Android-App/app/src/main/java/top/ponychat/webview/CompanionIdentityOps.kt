package top.ponychat.webview

import android.app.NotificationManager
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.provider.Settings
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.core.content.getSystemService
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject

internal data class CompanionCharacterOption(
    val id: String,
    val name: String,
    val avatar: String,
    val personality: String,
    val intro: String,
    val mbti: String,
)

internal data class CompanionPersonalityStyle(
    val id: String,
    val label: String,
    val description: String,
)

internal val companionPersonalityStyles = listOf(
    CompanionPersonalityStyle("canonical", "角色原设", "完全遵循角色原本的性格与表达方式"),
    CompanionPersonalityStyle("gentle", "更温柔", "语气更柔和，更关注你的感受"),
    CompanionPersonalityStyle("lively", "更活泼", "表达更轻快，但不改变角色身份"),
    CompanionPersonalityStyle("calm", "更沉稳", "表达更克制、有条理"),
    CompanionPersonalityStyle("playful", "更俏皮", "适当增加玩笑和亲昵感"),
)

internal fun CompanionService.currentPersonalityStyleLabel(): String =
    companionPersonalityStyles.firstOrNull { it.id == personalityStyle }?.label ?: "角色原设"

internal fun CompanionService.showCompanionCharacterMenu(anchor: View) {
    anchor.isEnabled = false
    serviceScope.launch {
        val result = runCatching { fetchCompanionCharacters() }
        withContext(Dispatchers.Main) {
            anchor.isEnabled = true
            result.onSuccess { characters ->
                if (characters.isEmpty()) {
                    appendMessageToDialog(false, "暂时没有可切换的角色")
                } else {
                    showIdentityChoicePanel(
                        title = "选择接管设备的角色",
                        entries = characters.map { character ->
                            val selected = character.id == characterId
                            Triple(
                                if (selected) "✓ ${character.name}" else character.name,
                                character.personality.ifBlank { character.intro }.ifBlank { "使用该角色的独立记忆与关系" },
                                { switchCompanionIdentity(character) },
                            )
                        },
                    )
                }
            }.onFailure {
                appendMessageToDialog(false, "角色列表加载失败，请稍后再试")
            }
        }
    }
}

internal fun CompanionService.showCompanionPersonalityMenu() {
    showIdentityChoicePanel(
        title = "调整当前角色的表达个性",
        entries = companionPersonalityStyles.map { style ->
            val selected = style.id == personalityStyle
            Triple(
                if (selected) "✓ ${style.label}" else style.label,
                style.description,
                {
                    personalityStyle = style.id
                    dismissCompanionIdentityChooser()
                    closeChatDialog()
                    openChatDialog()
                },
            )
        },
    )
}

private suspend fun CompanionService.fetchCompanionCharacters(): List<CompanionCharacterOption> =
    withContext(Dispatchers.IO) {
        val url = "${apiBase.trimEnd('/')}/api/companion/characters"
            .toHttpUrlOrNull()
            ?.newBuilder()
            ?.addQueryParameter("username", username)
            ?.build()
            ?: error("Invalid API base")
        val request = Request.Builder()
            .url(url)
            .addHeader("X-Chat-Auth", authToken)
            .get()
            .build()
        httpClient.newCall(request).execute().use { response ->
            if (!response.isSuccessful) error("HTTP ${response.code}")
            val payload = JSONObject(response.body?.string().orEmpty())
            if (payload.optString("status") != "ok") error(payload.optString("message"))
            val array = payload.optJSONArray("characters") ?: return@use emptyList()
            buildList {
                for (index in 0 until array.length()) {
                    val item = array.optJSONObject(index) ?: continue
                    val id = item.optString("id").trim()
                    if (id.isEmpty()) continue
                    add(
                        CompanionCharacterOption(
                            id = id,
                            name = item.optString("name").ifBlank { "未命名角色" },
                            avatar = item.optString("avatar"),
                            personality = item.optString("personality"),
                            intro = item.optString("intro"),
                            mbti = item.optString("mbti"),
                        ),
                    )
                }
            }
        }
    }

private fun CompanionService.switchCompanionIdentity(next: CompanionCharacterOption) {
    if (next.id == characterId) {
        dismissCompanionIdentityChooser()
        return
    }
    val oldCharacterId = characterId
    val durationSeconds = ((System.currentTimeMillis() - companionStartTime) / 1000).toInt().coerceAtLeast(0)
    dismissCompanionIdentityChooser()
    generatingJob?.cancel()
    generatingJob = null
    currentStreamingCall?.cancel()
    currentStreamingCall = null
    stopAgentLoop(reason = null)
    ttsBridge?.stop()
    appendMessageToDialog(false, "正在保存${characterName}的本次经历…")

    serviceScope.launch {
        val persisted = endIdentitySession(oldCharacterId, durationSeconds)
        withContext(Dispatchers.Main) {
            if (!persisted) {
                appendMessageToDialog(false, "旧角色记忆尚未保存成功，已取消切换，请稍后重试")
                return@withContext
            }
            closeChatDialog()
            characterId = next.id
            characterName = next.name
            avatarUrl = next.avatar
            characterPersonality = next.personality
            personalityStyle = "canonical"
            conversationHistory.clear()
            proactiveAttempted = false
            proactiveConsecutiveCount = 0
            lastActivityTimeMs = System.currentTimeMillis()
            companionStartTime = System.currentTimeMillis()
            getSystemService<NotificationManager>()?.notify(CompanionService.NOTIFY_ID, buildNotification())
            openChatDialog()
            mainHandler.postDelayed({ sendProactiveAiMessage("greeting") }, 500L)
        }
    }
}

private suspend fun CompanionService.endIdentitySession(character: String, durationSeconds: Int): Boolean =
    withContext(Dispatchers.IO) {
        try {
            val json = JSONObject().apply {
                put("character_id", character)
                put("username", username)
                put("duration_seconds", durationSeconds)
            }.toString()
            val request = Request.Builder()
                .url("${apiBase.trimEnd('/')}/api/companion/end")
                .addHeader("X-Chat-Auth", authToken)
                .post(json.toRequestBody("application/json".toMediaTypeOrNull()))
                .build()
            httpClient.newCall(request).execute().use { response ->
                if (!response.isSuccessful) return@use false
                val payload = JSONObject(response.body?.string().orEmpty())
                isCompanionMemoryFlushConfirmed(
                    status = payload.optString("status"),
                    memoryPersisted = payload.optBoolean("memory_persisted", true),
                )
            }
        } catch (_: Exception) {
            false
        }
    }

internal fun isCompanionMemoryFlushConfirmed(status: String, memoryPersisted: Boolean): Boolean =
    status == "ok" && memoryPersisted

private fun CompanionService.showIdentityChoicePanel(
    title: String,
    entries: List<Triple<String, String, () -> Unit>>,
) {
    if (!Settings.canDrawOverlays(this)) return
    dismissCompanionIdentityChooser()
    val content = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(dpToPx(16), dpToPx(14), dpToPx(16), dpToPx(14))
        background = GradientDrawable().apply {
            setColor(Color.rgb(22, 22, 42))
            cornerRadius = dpToPx(18).toFloat()
            setStroke(dpToPx(1), Color.parseColor("#446C63E4"))
        }
    }
    val header = LinearLayout(this).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
    }
    header.addView(TextView(this).apply {
        text = title
        textSize = 16f
        setTextColor(Color.WHITE)
        layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
    })
    header.addView(TextView(this).apply {
        text = "✕"
        textSize = 17f
        setTextColor(Color.parseColor("#AAFFFFFF"))
        setPadding(dpToPx(12), dpToPx(4), dpToPx(4), dpToPx(4))
        setOnClickListener { dismissCompanionIdentityChooser() }
    })
    content.addView(header)

    val list = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
    entries.forEach { (label, description, onClick) ->
        list.addView(LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dpToPx(12), dpToPx(10), dpToPx(12), dpToPx(10))
            background = GradientDrawable().apply {
                setColor(Color.parseColor("#18FFFFFF"))
                cornerRadius = dpToPx(12).toFloat()
            }
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT,
            ).apply { setMargins(0, dpToPx(8), 0, 0) }
            addView(TextView(this@showIdentityChoicePanel).apply {
                text = label
                textSize = 14f
                setTextColor(Color.WHITE)
            })
            addView(TextView(this@showIdentityChoicePanel).apply {
                text = description
                textSize = 11f
                setTextColor(Color.parseColor("#99FFFFFF"))
                maxLines = 2
            })
            setOnClickListener { onClick() }
        })
    }
    content.addView(ScrollView(this).apply {
        addView(list)
        layoutParams = LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT,
            0,
            1f,
        )
    })

    val params = WindowManager.LayoutParams(
        (screenWidth * 0.88f).toInt(),
        (screenHeight * 0.62f).toInt(),
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
        } else {
            @Suppress("DEPRECATION") WindowManager.LayoutParams.TYPE_PHONE
        },
        WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
        PixelFormat.TRANSLUCENT,
    ).apply {
        gravity = Gravity.TOP or Gravity.CENTER_HORIZONTAL
        y = dpToPx(48)
    }
    identityChooserView = content
    windowManager.addView(content, params)
}

internal fun CompanionService.dismissCompanionIdentityChooser() {
    val view = identityChooserView ?: return
    identityChooserView = null
    try {
        windowManager.removeViewImmediate(view)
    } catch (_: Exception) {
        try { windowManager.removeView(view) } catch (_: Exception) {}
    }
}
