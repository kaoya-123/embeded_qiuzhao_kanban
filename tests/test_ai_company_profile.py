import os
import sys
import unittest
from types import SimpleNamespace

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from ai_company_profile import (  # noqa: E402
    AIProfileError,
    build_company_contexts,
    generate_profile_candidates,
)


class FakeClient:
    def __init__(self, text):
        self.text = text
        self.kwargs = None
        self.messages = self

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text=self.text)],
        )


class AICompanyProfileTest(unittest.TestCase):
    def test_build_contexts_uses_safe_fields_and_pasted_materials(self):
        recs = [{"record_id": "r1", "fields": {"公司名称": "联合飞机", "JD原文": "飞控 BSP", "账号密码": "secret"}}]
        contexts = build_company_contexts(
            recs,
            public_materials=[{"company": "联合飞机", "title": "官网", "text": "低空经济飞行器"}],
            profiles={},
            missing_only=False,
        )
        self.assertEqual(contexts[0]["company"], "联合飞机")
        self.assertIn("JD原文", contexts[0]["main_table_fields"])
        self.assertNotIn("账号密码", contexts[0]["main_table_fields"])
        self.assertEqual(contexts[0]["public_materials"][0]["title"], "官网")

    def test_generate_candidates_uses_structured_output_without_tools(self):
        text = '{"candidates":[{"company":"联合飞机","fields":{"嵌入式方向":["BSP"],"工作地点":["深圳"],"公司/行业类型":["低空经济"],"细分类型":["无人机"],"公司规模":"1000-5000人","公司简介":"低空经济飞行器企业。"},"confidence":"medium","sources":[{"type":"main_table","field":"JD原文","record_id":"r1"}],"reasoning":"JD 提到 BSP 和飞控。","warnings":[]}],"warnings":[]}'
        client = FakeClient(text)
        result = generate_profile_candidates([
            {"company": "联合飞机", "record_id": "r1", "requested_fields": ["嵌入式方向"], "main_table_fields": {"JD原文": "BSP"}, "existing_profile": {}, "public_materials": []}
        ], client=client, model="claude-opus-4-8")
        self.assertEqual(result["candidates"][0]["company"], "联合飞机")
        self.assertEqual(result["candidates"][0]["fields"]["嵌入式方向"], ["BSP"])
        self.assertNotIn("tools", client.kwargs)
        self.assertEqual(client.kwargs["model"], "claude-opus-4-8")

    def test_rejects_missing_key_without_client(self):
        old = os.environ.pop("ANTHROPIC_API_KEY", None)
        try:
            with self.assertRaises(AIProfileError):
                generate_profile_candidates([{"company": "联合飞机"}], api_key="")
        finally:
            if old is not None:
                os.environ["ANTHROPIC_API_KEY"] = old


if __name__ == "__main__":
    unittest.main()
