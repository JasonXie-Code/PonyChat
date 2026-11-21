import unittest

from companion_controller.qq_command import parse_qq_device_command


class QqDeviceCommandTest(unittest.TestCase):
    def test_parses_natural_image_search_command(self):
        command = parse_qq_device_command("帮我从网上找一下小马宝莉紫悦的图片")

        self.assertIsNotNone(command)
        self.assertEqual("image_search", command.kind)
        self.assertEqual("小马宝莉紫悦", command.query)

    def test_plain_chat_is_not_a_device_command(self):
        self.assertIsNone(parse_qq_device_command("你最喜欢哪一匹小马？"))

    def test_routes_general_device_operations_to_autonomous_agent(self):
        cases = (
            "打开相机拍一张照片",
            "把屏幕亮度调低一点",
            "用QQ给谢永鹏发消息说晚上好",
            "在浏览器打开 yuelimei.cn",
        )
        for text in cases:
            with self.subTest(text=text):
                command = parse_qq_device_command(text)
                self.assertIsNotNone(command)
                self.assertEqual("general_device", command.kind)

    def test_parses_weather_article_video_and_general_queries(self):
        cases = (
            ("帮我从网上看看深圳今天的天气", "weather_search", "深圳今天的天气"),
            ("搜索关于深圳人工智能产业的文章", "article_search", "关于深圳人工智能产业的文章"),
            ("帮我找一下小马宝莉的视频", "video_search", "小马宝莉的视频"),
            ("帮我联网查询 PonyChat", "web_search", "PonyChat"),
            ("深圳明天天气怎么样？", "weather_search", "深圳明天天气怎么样"),
        )
        for text, kind, query in cases:
            with self.subTest(text=text):
                command = parse_qq_device_command(text)
                self.assertIsNotNone(command)
                self.assertEqual(kind, command.kind)
                self.assertEqual(query, command.query)

    def test_existing_image_share_command_is_reused(self):
        command = parse_qq_device_command(
            "Companion在浏览器里面搜索小马宝莉的小马“紫悦”的图片，并发给QQ的谢永鹏"
        )

        self.assertIsNotNone(command)
        self.assertEqual("image_share_to_qq", command.kind)
        self.assertEqual("谢永鹏", command.image_share_task.recipient)


if __name__ == "__main__":
    unittest.main()
