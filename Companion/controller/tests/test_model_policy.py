import unittest

from companion_controller.model_policy import DEEPSEEK_FLASH, DEEPSEEK_VISION, choose_model


class ModelPolicyTest(unittest.TestCase):
    def test_simple_tasks_use_deepseek(self):
        self.assertEqual(DEEPSEEK_FLASH, choose_model().model)

    def test_images_use_deepseek_vision(self):
        self.assertEqual(DEEPSEEK_VISION, choose_model(has_image=True).model)

    def test_hard_tasks_use_deepseek_vision(self):
        self.assertEqual(DEEPSEEK_VISION, choose_model(high_difficulty=True).model)


if __name__ == "__main__":
    unittest.main()
