package top.ponychat.companion.reply

/** Fast local gate for commands currently supported by the host Controller. */
object QqDeviceCommandDetector {
    private val searchWords = listOf("找", "搜", "搜索", "查", "查询", "查找", "看看", "看一下", "了解")
    private val imageWords = listOf("图片", "照片", "图")
    private val networkWords = listOf("网上", "网络上", "互联网上", "联网", "浏览器", "网页", "网站")
    private val liveWords = listOf(
        "天气", "气温", "降雨", "空气质量", "新闻", "资讯", "热搜", "股价", "汇率",
        "航班", "列车", "路况", "比分", "票房",
    )
    private val contentWords = listOf("文章", "资料", "新闻", "资讯", "网页", "网站", "视频", "影片")
    private val questionWords = listOf("怎么样", "多少", "如何", "会不会", "有没有", "多少度", "预报", "吗", "？", "?")
    private val deviceActions = listOf(
        "打开", "关闭", "启动", "退出", "返回", "发送", "发消息", "回复", "分享", "播放", "暂停",
        "设置", "切换", "调高", "调低", "调整", "安装", "下载", "创建", "删除", "拍照",
        "录像", "截图", "导航", "拨打", "设个提醒", "设闹钟", "滑动", "点击",
    )
    private val deviceScopes = listOf(
        "QQ", "qq", "微信", "浏览器", "网页", "网站", "应用", "软件", "相机", "相册", "视频",
        "音乐", "屏幕", "音量", "亮度", "WiFi", "wifi", "蓝牙", "设置", "联系人", "消息",
        "图片", "文件", "地图", "闹钟", "提醒",
    )

    fun isSupported(text: String): Boolean {
        val normalized = text.trim()
        if (normalized.isBlank()) return false
        val requestsSearch = searchWords.any(normalized::contains)
        val hasOnlineScope = (networkWords + liveWords + contentWords + imageWords)
            .any(normalized::contains)
        val asksLiveQuestion = liveWords.any(normalized::contains) && questionWords.any(normalized::contains)
        val generalDeviceTask = deviceActions.any(normalized::contains) &&
            deviceScopes.any(normalized::contains)
        return (requestsSearch && hasOnlineScope) || asksLiveQuestion || generalDeviceTask
    }
}
