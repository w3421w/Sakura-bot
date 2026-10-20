import json
import os
import unittest

import llm.deepseek_client as deepseek_module
from llm.deepseek_client import DeepSeekClient


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()


class DeepSeekClientTests(unittest.TestCase):
    def test_openai_compatible_payload_and_key(self):
        old = os.environ.get("DEEPSEEK_API_KEY")
        os.environ["DEEPSEEK_API_KEY"] = "unit-test-key"
        seen = {}

        def fake_urlopen(request, timeout):
            seen["url"] = request.full_url
            seen["body"] = json.loads(request.data.decode())
            seen["auth"] = request.headers["Authorization"]
            return _Response()

        original = deepseek_module.urllib.request.urlopen
        deepseek_module.urllib.request.urlopen = fake_urlopen
        try:
            client = DeepSeekClient({"base_url": "https://api.deepseek.com", "model": "deepseek-flash"})
            self.assertEqual(client._chat_sync([{"role": "user", "content": "hi"}]), "ok")
        finally:
            deepseek_module.urllib.request.urlopen = original
            if old is None:
                os.environ.pop("DEEPSEEK_API_KEY", None)
            else:
                os.environ["DEEPSEEK_API_KEY"] = old
        self.assertTrue(seen["url"].endswith("/chat/completions"))
        self.assertEqual(seen["body"]["thinking"], {"type": "disabled"})
        self.assertEqual(seen["auth"], "Bearer unit-test-key")

    def test_reasoning_payload_uses_thinking_profile(self):
        old = os.environ.get("DEEPSEEK_API_KEY")
        os.environ["DEEPSEEK_API_KEY"] = "unit-test-key"
        seen = {}

        def fake_urlopen(request, timeout):
            seen["body"] = json.loads(request.data.decode())
            return _Response()

        original = deepseek_module.urllib.request.urlopen
        deepseek_module.urllib.request.urlopen = fake_urlopen
        try:
            client = DeepSeekClient({
                "base_url": "https://api.deepseek.com",
                "model": "deepseek-flash",
                "reasoning": {
                    "model": "deepseek-flash",
                    "thinking": "enabled",
                    "reasoning_effort": "high",
                    "max_tokens": 1200,
                },
            })
            self.assertEqual(
                client._chat_sync([{"role": "user", "content": "分析这个方案"}], mode="reasoning"),
                "ok",
            )
        finally:
            deepseek_module.urllib.request.urlopen = original
            if old is None:
                os.environ.pop("DEEPSEEK_API_KEY", None)
            else:
                os.environ["DEEPSEEK_API_KEY"] = old
        self.assertEqual(seen["body"]["model"], "deepseek-flash")
        self.assertEqual(seen["body"]["thinking"], {"type": "enabled"})
        self.assertEqual(seen["body"]["reasoning_effort"], "high")
        self.assertEqual(seen["body"]["max_tokens"], 1200)
        self.assertNotIn("temperature", seen["body"])


if __name__ == "__main__":
    unittest.main()
