import unittest

from core.reply import split_reply


class ReplySplitTests(unittest.TestCase):
    def test_short_reply_stays_one_message(self):
        self.assertEqual(split_reply("呵呵。"), ["呵呵"])

    def test_sentences_split_and_punctuation_is_kept(self):
        self.assertEqual(
            split_reply("来了。先等我一下！马上开。"),
            ["来了", "先等我一下！", "马上开"],
        )

    def test_newlines_split_and_excess_is_folded(self):
        self.assertEqual(
            split_reply("第一句\n第二句\n第三句\n第四句"),
            ["第一句", "第二句", "第三句 第四句"],
        )

    def test_long_comma_sentence_can_split(self):
        self.assertEqual(
            split_reply("到了就赶紧进屋，别又边走边刷屏，进门以后再慢慢聊。"),
            ["到了就赶紧进屋", "别又边走边刷屏", "进门以后再慢慢聊"],
        )

    def test_medium_two_comma_sentence_can_split(self):
        self.assertEqual(
            split_reply("行，学会分发了，下一步该怎么把话说完了。"),
            ["行", "学会分发了", "下一步该怎么把话说完了"],
        )

    def test_single_comma_water_chat_sentence_can_split(self):
        self.assertEqual(
            split_reply("到了就赶紧进屋，别又边走边刷屏。"),
            ["到了就赶紧进屋", "别又边走边刷屏"],
        )


if __name__ == "__main__":
    unittest.main()
