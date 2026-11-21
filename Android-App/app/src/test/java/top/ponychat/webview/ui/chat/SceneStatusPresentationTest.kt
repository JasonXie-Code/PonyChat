package top.ponychat.webview.ui.chat

import org.junit.Assert.assertEquals
import org.junit.Test

class SceneStatusPresentationTest {
    @Test
    fun modeLabelsOnlyUseTheRecordedAgentSelection() {
        assertEquals("即时对话", sceneInteractionLabel("instant_messaging"))
        assertEquals("虚拟扮演", sceneInteractionLabel("virtual_roleplay"))
        assertEquals("尚无识别记录", sceneInteractionLabel(null))
        assertEquals("尚无识别记录", sceneInteractionLabel("unexpected"))
    }

    @Test
    fun olderScenePronounsRenderWithParticipantNamesWithoutChangingEvidence() {
        val source = "紫悦站在桌旁，面向你，手边是你的茶杯。"
        assertEquals("紫悦站在桌旁，面向Jason，手边是Jason的茶杯。",
            objectiveSceneValue(source, "Jason", "紫悦"))
        assertEquals("紫悦坐在Jason旁边。", objectiveSceneValue("我坐在你旁边。", "Jason", "紫悦"))
        assertEquals("未记录", objectiveSceneValue(null, "Jason", "紫悦"))
    }
}
