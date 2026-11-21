import unittest

from companion_controller.mobile_tools import ScreenElement
from companion_controller.qq_command import QqDeviceCommand
from companion_controller.web_query_workflow import BrowserWebQueryWorkflow


class FakeTools:
    def __init__(self, screens):
        self.screens = list(screens)
        self.urls = []
        self.buttons = []

    def open_url(self, device, url):
        self.urls.append((device, url))

    def list_elements(self, device):
        if len(self.screens) > 1:
            return self.screens.pop(0)
        return self.screens[0]

    def press_button(self, device, button):
        self.buttons.append((device, button))


def element(text, y):
    return ScreenElement(text=text, y=y, width=100, height=40)


class BrowserWebQueryWorkflowTest(unittest.TestCase):
    def test_weather_result_contains_summary_and_full_link(self):
        tools = FakeTools([[
            element("深圳今天的天气", 100),
            element("31°C", 200),
            element("多云", 240),
            element("降雨概率 20%", 280),
        ]])
        result = BrowserWebQueryWorkflow(
            tools,
            "emulator",
            settle_seconds=0,
            browser_timeout_seconds=0.01,
            rss_fetcher=lambda _: [],
            weather_fetcher=lambda _: [],
            web_fetcher=lambda _: [],
        ).run(
            QqDeviceCommand("weather_search", "深圳今天的天气"),
        )

        self.assertTrue(result.success)
        self.assertIn("31°C", result.message)
        self.assertIn("降雨概率 20%", result.message)
        self.assertIn("完整结果：https://www.google.com/search?", result.message)

    def test_video_query_uses_video_search_and_clips_long_result(self):
        tools = FakeTools([[
            element("小马宝莉 视频", 100),
            element("精彩片段 " + "内容" * 200, 200),
            element("第二个视频结果", 300),
        ]])
        result = BrowserWebQueryWorkflow(
            tools,
            "emulator",
            settle_seconds=0,
            browser_timeout_seconds=0.01,
            rss_fetcher=lambda _: [],
            web_fetcher=lambda _: [],
        ).run(
            QqDeviceCommand("video_search", "小马宝莉视频"),
        )

        self.assertTrue(result.success)
        self.assertIn("tbm=vid", tools.urls[0][1])
        self.assertLess(len(result.message), 900)

    def test_browser_noise_is_not_returned_as_summary(self):
        snippets = BrowserWebQueryWorkflow._extract_snippets(
            [
                element("Google", 10),
                element("Search", 20),
                element("Clear Search", 25),
                element("Double-tap to search Google.", 28),
                element("有效摘要", 30),
            ],
            "查询词",
        )
        self.assertEqual(["有效摘要"], snippets)

    def test_rss_summary_includes_original_source_link(self):
        tools = FakeTools([[element("Web View", 10)]])
        result = BrowserWebQueryWorkflow(
            tools,
            "emulator",
            settle_seconds=0,
            browser_timeout_seconds=0.01,
            rss_fetcher=lambda _: [],
            weather_fetcher=lambda _: [
                "深圳天气预报\n今天多云，最高 31°C\nhttps://weather.example/shenzhen",
            ],
            web_fetcher=lambda _: [],
        ).run(QqDeviceCommand("weather_search", "深圳今天的天气"))

        self.assertTrue(result.success)
        self.assertIn("今天多云", result.message)
        self.assertIn("https://weather.example/shenzhen", result.message)

    def test_irrelevant_search_result_is_rejected(self):
        self.assertFalse(BrowserWebQueryWorkflow._is_relevant(
            "深圳人工智能产业",
            "90 Day Fiance episodes and television discussion",
        ))
        self.assertTrue(BrowserWebQueryWorkflow._is_relevant(
            "深圳人工智能产业",
            "深圳人工智能产业发展报告",
        ))

    def test_ponychat_web_search_summary_is_preferred_to_browser_tree(self):
        tools = FakeTools([[element("Web View", 10)]])
        result = BrowserWebQueryWorkflow(
            tools,
            "emulator",
            settle_seconds=0,
            browser_timeout_seconds=0.01,
            rss_fetcher=lambda _: [],
            weather_fetcher=lambda _: [],
            web_fetcher=lambda _: ["深圳人工智能产业规模持续增长"],
        ).run(QqDeviceCommand("article_search", "深圳人工智能产业文章"))

        self.assertTrue(result.success)
        self.assertIn("产业规模持续增长", result.message)

    def test_all_fahrenheit_variants_are_converted_to_celsius(self):
        normalized = BrowserWebQueryWorkflow._normalize_celsius(
            "当前 86°F，体感 95℉，夜间为华氏 77 度",
        )

        self.assertEqual("当前 30°C，体感 35°C，夜间为25°C", normalized)


if __name__ == "__main__":
    unittest.main()
