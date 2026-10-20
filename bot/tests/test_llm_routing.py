import unittest

from core.dispatcher import MessageDispatcher


class LLMRoutingTests(unittest.TestCase):
    def test_short_water_chat_uses_fast_profile(self):
        self.assertEqual(MessageDispatcher._llm_mode("来水群"), "fast")

    def test_complex_question_uses_reasoning_profile(self):
        self.assertEqual(MessageDispatcher._llm_mode("请分析这两个方案的优缺点并给出选择建议"), "reasoning")

    def test_explicit_reasoning_command(self):
        self.assertEqual(MessageDispatcher._llm_mode("/深度 为什么会这样"), "reasoning")

    def test_repeated_nickname_suffix_is_sanitized(self):
        self.assertEqual(MessageDispatcher._sanitize_addressing("Ame 处你这话说得对"), "Ame 你这话说得对")
        self.assertEqual(MessageDispatcher._sanitize_addressing("Ame处你又来了"), "Ame你又来了")


if __name__ == "__main__":
    unittest.main()
