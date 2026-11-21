package top.ponychat.companion.reply

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class QqDeviceCommandDetectorTest {
    @Test
    fun `recognizes supported image search command`() {
        assertTrue(QqDeviceCommandDetector.isSupported("帮我从网上找一下小马宝莉紫悦的图片"))
    }

    @Test
    fun `recognizes weather article and video web queries`() {
        assertTrue(QqDeviceCommandDetector.isSupported("帮我从网上看看深圳今天的天气"))
        assertTrue(QqDeviceCommandDetector.isSupported("搜索关于深圳人工智能产业的文章"))
        assertTrue(QqDeviceCommandDetector.isSupported("帮我找一下小马宝莉的视频"))
        assertTrue(QqDeviceCommandDetector.isSupported("深圳明天天气怎么样？"))
    }

    @Test
    fun `does not divert ordinary private chat`() {
        assertFalse(QqDeviceCommandDetector.isSupported("你最喜欢哪一匹小马？"))
    }

    @Test
    fun `recognizes general device operations for autonomous controller`() {
        assertTrue(QqDeviceCommandDetector.isSupported("打开相机拍一张照片"))
        assertTrue(QqDeviceCommandDetector.isSupported("把屏幕亮度调低一点"))
        assertTrue(QqDeviceCommandDetector.isSupported("用QQ给谢永鹏发消息说晚上好"))
        assertTrue(QqDeviceCommandDetector.isSupported("在浏览器打开 yuelimei.cn"))
    }
}
