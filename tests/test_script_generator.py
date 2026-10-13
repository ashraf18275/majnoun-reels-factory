import json
import unittest

from factory.script_generator import ScriptGenerationError, generate_script


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.payload


class TestScriptGenerator(unittest.TestCase):
    def test_requests_local_ollama_with_sources_and_returns_text(self):
        def opener(request, timeout):
            self.assertEqual(request.full_url, "http://127.0.0.1:11434/api/generate")
            self.assertEqual(timeout, 240)
            payload = json.loads(request.data)
            self.assertEqual(payload["model"], "qwen2.5:1.5b")
            self.assertFalse(payload["stream"])
            self.assertIn("مصدر موثوق", payload["prompt"])
            return FakeResponse({"response": "مسودة للتقييم."})

        result = generate_script("فكرة علمية", "مصدر موثوق", opener=opener)
        self.assertEqual(result, "مسودة للتقييم.")

    def test_source_notes_are_required(self):
        with self.assertRaisesRegex(ScriptGenerationError, "المصادر"):
            generate_script("فكرة علمية", " ")

    def test_empty_model_response_is_rejected(self):
        with self.assertRaisesRegex(ScriptGenerationError, "فارغ"):
            generate_script("فكرة علمية", "رابط مصدر", opener=lambda *_a, **_k: FakeResponse({"response": " "}))


if __name__ == "__main__":
    unittest.main()
