package top.ponychat.webview.util

import org.json.JSONObject
import top.ponychat.webview.data.model.ChatMessage
import top.ponychat.webview.ui.chat.effectiveVoiceState

/**
 * 游戏 / 锁分模式系统通知正文：优先「角色回复」scene.response，再按已有字段逐级补全。
 */
object GalgameNotificationPreview {

    private val htmlTagRe = Regex("<[^>]+>")
    private val galSceneSpeechRe =
        Regex("""<div\s+class="[^"]*gal-scene-speech[^"]*"[^>]*>([\s\S]*?)</div>""", RegexOption.IGNORE_CASE)

    /** 从任意嵌套对象规范化出 scene Map（Gson Map / JSONObject 等）。 */
    @Suppress("UNCHECKED_CAST")
    fun normalizeSceneMap(raw: Any?): Map<String, Any?> {
        if (raw == null) return emptyMap()
        if (raw is Map<*, *>) {
            return raw.entries.associate { it.key.toString() to it.value }
        }
        return emptyMap()
    }

    fun jsonObjectToSceneMap(j: JSONObject?): Map<String, Any?> {
        if (j == null || j.length() == 0) return emptyMap()
        val m = mutableMapOf<String, Any?>()
        val it = j.keys()
        while (it.hasNext()) {
            val k = it.next()
            val v = j.opt(k)
            m[k] = if (v === JSONObject.NULL) null else v
        }
        return m
    }

    /**
     * @param scene 本轮 scene 字典（含 response、body_state、thoughts 等）
     * @param msgContent 助手消息富文本或纯文本
     * @param displayHtml 用于从 gal-scene-speech 抽对白
     * @param scoreDeltaReason 分数变化理由（在 data 层）
     */
    fun buildPlainPreview(
        scene: Map<String, Any?>,
        msgContent: String,
        displayHtml: String,
        scoreDeltaReason: String?,
    ): String {
        scene.stringField("response")?.let { if (it.isNotBlank()) return it }

        stripToPlain(msgContent).takeIf { it.isNotBlank() }?.let { return it }

        extractGalSceneSpeechPlain(displayHtml).takeIf { it.isNotBlank() }?.let { return it }

        scene.stringField("body_state")?.let { if (it.isNotBlank()) return it }
        scene.stringField("thoughts")?.let { if (it.isNotBlank()) return it }

        scene.stringField("third_party_dialogue")?.let { t ->
            if (t.isNotBlank() && !t.equals("null", true) && !t.equals("none", true)) return t
        }

        scoreDeltaReason?.trim()?.takeIf { it.isNotBlank() }?.let { return it }

        val time = scene.stringField("time").orEmpty()
        val loc = scene.stringField("location").orEmpty()
        listOf(time, loc).filter { it.isNotBlank() }.joinToString(" · ").takeIf { it.isNotBlank() }?.let { return it }

        scene.stringField("env")?.let { if (it.isNotBlank()) return it }

        return ""
    }

    /**
     * outbox / WS `chat_complete`：优先结构化 scene（若后端附带），否则沿用服务端 preview。
     */
    fun resolveForChatComplete(
        mode: String,
        serverPreview: String,
        scene: Map<String, Any?>,
        scoreDeltaReason: String?,
    ): String {
        val m = mode.lowercase()
        if (m != "galgame" && m != "galgame_lock") return serverPreview
        val built = buildPlainPreview(scene, "", "", scoreDeltaReason)
        return built.ifBlank { serverPreview.trim() }
    }

    fun resolveForChatCompleteJson(
        mode: String,
        serverPreview: String,
        sceneJson: JSONObject?,
        scoreDeltaReason: String?,
    ): String = resolveForChatComplete(mode, serverPreview, jsonObjectToSceneMap(sceneJson), scoreDeltaReason)

    private fun Map<String, Any?>.stringField(key: String): String? {
        val v = this[key] ?: return null
        val s = v.toString().trim()
        return s.ifBlank { null }
    }

    private fun extractGalSceneSpeechPlain(html: String): String {
        if (html.isBlank()) return ""
        val m = galSceneSpeechRe.find(html) ?: return ""
        return stripToPlain(m.groupValues.getOrNull(1).orEmpty())
    }

    private fun stripToPlain(s: String): String {
        if (s.isBlank()) return ""
        return s.replace(htmlTagRe, " ")
            .replace(Regex("\\[([^\\]]+)]\\([^)]+\\)"), "$1")
            .replace(Regex("(`{1,3}|\\*\\*|__|\\*|_|~~)"), "")
            .replace(Regex("\\s+"), " ")
            .trim()
    }

    /**
     * 角色列表第二行专用：在 [stripToPlain] 之后仍可能残留未成对的 `**`、代码块等，此处做最后一轮剥离。
     */
    fun stripMarkdownForListPreview(raw: String): String {
        if (raw.isBlank()) return ""
        var t = raw.replace(htmlTagRe, " ")
        t = Regex("```[\\s\\S]*?```").replace(t, " ")
        t = Regex("`+([^`\\n]+?)`+").replace(t, "$1")
        t = Regex("\\[(.+?)]\\([^)]+\\)").replace(t, "$1")
        var guard = 0
        var prev: String
        do {
            prev = t
            t = Regex("\\*\\*(.+?)\\*\\*", RegexOption.DOT_MATCHES_ALL).replace(t, "$1")
            t = Regex("__(.+?)__", RegexOption.DOT_MATCHES_ALL).replace(t, "$1")
            guard++
        } while (t != prev && guard < 32)
        t = Regex("~~(.*?)~~", RegexOption.DOT_MATCHES_ALL).replace(t, "$1")
        t = Regex("^#{1,6}\\s*", RegexOption.MULTILINE).replace(t, "")
        t = t.replace("**", "").replace("__", "")
        t = t.replace("*", "").replace("_", "").replace("~", "").replace("`", "")
        return Regex("\\s+").replace(t, " ").trim()
    }

    /**
     * 角色列表第二行：该模式下最后一条可见助手消息的摘要（单行由 UI `maxLines=1` 截断）。
     * 普通模式用正文去 HTML/Markdown；游戏/锁分与通知策略一致（response → content → gal-scene-speech…）。
     */
    fun listRowSnippetFromLastAssistant(messages: List<ChatMessage>, mode: String): String {
        val last = messages
            .filter { m -> m.role.equals("assistant", ignoreCase = true) && m.isHidden != true }
            .maxWithOrNull { a, b ->
                val aSeq = a.sequenceNumber ?: Int.MIN_VALUE
                val bSeq = b.sequenceNumber ?: Int.MIN_VALUE
                val aTs = a.timestamp ?: 0L
                val bTs = b.timestamp ?: 0L
                when {
                    aSeq != bSeq -> aSeq.compareTo(bSeq)
                    aTs != bTs -> aTs.compareTo(bTs)
                    else -> (a.messageId ?: "").compareTo(b.messageId ?: "")
                }
            } ?: return ""
        val mNorm = mode.trim().lowercase().let { mo ->
            when (mo) {
                "galgame", "galgame_lock" -> mo
                else -> "normal"
            }
        }
        val out = if (mNorm != "galgame" && mNorm != "galgame_lock") {
            val voice = effectiveVoiceState(last)
            val voiceText = voice
                ?.readableText(last.content)
                ?.takeIf { it.isNotBlank() }
                ?: voice
                    ?.textFragments
                    ?.filter { it.isNotBlank() }
                    ?.joinToString(" ")
                    ?.takeIf { it.isNotBlank() }
            stripToPlain(voiceText ?: last.content).trim()
        } else {
            val baseScene = mutableMapOf<String, Any?>()
            mergeSceneFromGalgameRaw(baseScene, last.rawContent)
            val scoreReason = baseScene["score_delta_reason"]?.toString()?.trim()?.ifBlank { null }
            val built = buildPlainPreview(
                baseScene,
                last.content,
                last.displayContent.orEmpty(),
                scoreReason,
            ).trim()
            if (built.isNotBlank()) built
            else stripToPlain(last.displayContent ?: "").trim().ifBlank { stripToPlain(last.content).trim() }
        }
        return stripMarkdownForListPreview(out)
    }

    private fun mergeSceneFromGalgameRaw(scene: MutableMap<String, Any?>, raw: String?) {
        if (raw.isNullOrBlank()) return
        try {
            val j0 = JSONObject(raw)
            val j = j0.optJSONObject("data") ?: j0
            j.optJSONObject("scene")?.let { jo ->
                val sub = jsonObjectToSceneMap(jo)
                for ((k, v) in sub) {
                    val existing = scene[k]?.toString()?.trim().orEmpty()
                    val nv = v?.toString()?.trim().orEmpty()
                    if (existing.isBlank() && nv.isNotBlank()) scene[k] = v
                }
            }
            val resp = j.optString("response", "").trim()
            if (resp.isNotBlank()) {
                val cur = scene["response"]?.toString()?.trim().orEmpty()
                if (cur.isBlank()) scene["response"] = resp
            }
            val sdr = j.optString("score_delta_reason", "").trim()
            if (sdr.isNotBlank()) {
                val cur = scene["score_delta_reason"]?.toString()?.trim().orEmpty()
                if (cur.isBlank()) scene["score_delta_reason"] = sdr
            }
        } catch (_: Exception) {
        }
    }
}
