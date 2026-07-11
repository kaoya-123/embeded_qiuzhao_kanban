import os
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from main_table_completion import (  # noqa: E402
    WHITELIST,
    build_apply_updates,
    build_completion_preview,
    default_requested_fields,
    load_profiles,
    merge_ai_profile_candidates,
    update_company_profiles_from_main,
)


def main_record(rid="m1", fields=None):
    base = {"公司名称": "联合飞机"}
    base.update(fields or {})
    return {"record_id": rid, "fields": base}


FIELD_META = {
    "嵌入式方向": {"property": {"options": [{"name": "BSP"}, {"name": "Linux驱动"}, {"name": "飞控"}]}},
    "工作地点": {"property": {"options": [{"name": "深圳"}, {"name": "上海"}, {"name": "成都"}]}},
    "公司/行业类型": {"property": {"options": [{"name": "低空经济"}, {"name": "机器人"}]}},
    "细分类型": {"property": {"options": [{"name": "无人机"}, {"name": "飞行器"}]}},
    "公司规模": {},
    "公司简介": {},
    "岗位类型": {"property": {"options": [{"name": "秋招"}, {"name": "提前批"}]}},
}


PROFILES = {
    "联合飞机": {
        "公司/行业类型": ["低空经济", "机器人"],
        "细分类型": ["无人机", "飞行器"],
        "嵌入式方向": ["BSP", "Linux驱动", "飞控"],
        "公司所在地": ["深圳", "上海", "成都"],
        "公司简介": "低空经济飞行器企业，嵌入式方向覆盖飞控、驱动和机载系统。",
        "公司规模": "1000-5000人",
        "confidence": "high",
        "updated_at": "2026-07-11",
    }
}


class MainTableCompletionTest(unittest.TestCase):
    def test_default_fields_are_profile_only(self):
        defaults = set(default_requested_fields())
        self.assertEqual(defaults, {"嵌入式方向", "工作地点", "公司/行业类型", "细分类型", "公司规模", "公司简介"})
        self.assertNotIn("投递链接", WHITELIST)
        self.assertNotIn("投递截止时间", WHITELIST)
        self.assertNotIn("秋招岗位", WHITELIST)
        self.assertNotIn("JD原文", WHITELIST)
        self.assertNotIn("岗位类型", WHITELIST)

    def test_preview_fills_profile_fields_and_multiple_locations(self):
        result = build_completion_preview(
            [main_record()],
            [],
            FIELD_META,
            default_requested_fields(),
            profiles=PROFILES,
        )
        self.assertEqual(result["summary"]["records_with_changes"], 1)
        by_field = {x["field"]: x for x in result["changes"][0]["fields"]}
        self.assertEqual(by_field["工作地点"]["proposed_value"], ["深圳", "上海", "成都"])
        self.assertEqual(by_field["嵌入式方向"]["proposed_value"], ["BSP", "Linux驱动", "飞控"])
        self.assertIn("公司画像", by_field["工作地点"]["reason"])
        self.assertEqual(by_field["工作地点"]["source"]["kind"], "company_profile")

    def test_compatible_with_legacy_work_location_key(self):
        profiles = {"联合飞机": {"工作地点": ["深圳", "上海"]}}
        result = build_completion_preview(
            [main_record()],
            [],
            FIELD_META,
            ["工作地点"],
            profiles=profiles,
        )
        self.assertEqual(result["changes"][0]["fields"][0]["proposed_value"], ["深圳", "上海"])

    def test_does_not_overwrite_existing_main_value(self):
        result = build_completion_preview(
            [main_record(fields={"工作地点": ["北京"]})],
            [],
            FIELD_META,
            ["工作地点"],
            profiles=PROFILES,
        )
        self.assertEqual(result["summary"]["field_changes"], 0)
        self.assertEqual(result["skips"][0]["reason_code"], "main_value_present")

    def test_rejects_unwhitelisted_job_type(self):
        result = build_completion_preview(
            [main_record()],
            [],
            FIELD_META,
            ["岗位类型"],
            profiles={"联合飞机": {"岗位类型": "秋招"}},
        )
        self.assertEqual(result["summary"]["field_changes"], 0)
        self.assertEqual(result["skips"][0]["reason_code"], "field_not_whitelisted")

    def test_multiselect_option_validation_rejects_unknown_location(self):
        profiles = {"联合飞机": {"公司所在地": ["不存在城市"]}}
        result = build_completion_preview(
            [main_record()],
            [],
            FIELD_META,
            ["工作地点"],
            profiles=profiles,
        )
        self.assertEqual(result["summary"]["field_changes"], 0)
        self.assertEqual(result["skips"][0]["reason_code"], "invalid_value")

    def test_apply_rechecks_empty(self):
        result = build_completion_preview([main_record()], [], FIELD_META, ["工作地点"], profiles=PROFILES)
        updates, skipped = build_apply_updates(result, [main_record(fields={"工作地点": ["刚刚手填"]})], FIELD_META)
        self.assertEqual(updates, [])
        self.assertEqual(skipped[0]["reason_code"], "main_value_changed")

    def test_update_company_profiles_from_main_writes_local_profile_json(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "profiles.json")
            result = update_company_profiles_from_main([
                main_record(fields={
                    "公司/行业类型": ["低空经济"],
                    "细分类型": ["无人机"],
                    "嵌入式方向": ["BSP"],
                    "工作地点": ["深圳", "上海"],
                    "公司规模": "1000-5000人",
                    "公司简介": "低空经济飞行器企业。",
                })
            ], path=path)
            self.assertTrue(result["success"])
            self.assertEqual(result["companies_scanned"], 1)
            profiles = load_profiles(path)
            self.assertIn("联合飞机", profiles)
            self.assertEqual(profiles["联合飞机"]["公司所在地"], ["深圳", "上海"])
            self.assertEqual(profiles["联合飞机"]["confidence"], "high")

    def test_update_company_profiles_uses_seed_for_known_company(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "profiles.json")
            result = update_company_profiles_from_main([
                {"record_id": "m2", "fields": {"公司名称": "大疆"}}
            ], path=path)
            self.assertTrue(result["success"])
            profiles = load_profiles(path)
            self.assertIn("大疆", profiles)
            self.assertTrue(profiles["大疆"].get("公司所在地"))
            self.assertTrue(profiles["大疆"].get("嵌入式方向"))
    def test_merge_ai_profile_candidates_writes_local_profile_json(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "profiles.json")
            result = merge_ai_profile_candidates([
                {
                    "company": "联合飞机",
                    "fields": {
                        "嵌入式方向": ["BSP", "飞控"],
                        "工作地点": ["深圳"],
                        "公司/行业类型": ["低空经济"],
                        "细分类型": ["无人机"],
                        "公司规模": "1000-5000人",
                        "公司简介": "低空经济飞行器企业。",
                    },
                    "confidence": "medium",
                    "sources": [{"type": "main_table", "field": "JD原文", "record_id": "m1"}],
                    "reasoning": "JD 提到飞控与 BSP。",
                }
            ], path=path, model="claude-opus-4-8")
            self.assertTrue(result["success"])
            self.assertEqual(result["profiles_created"], 1)
            profiles = load_profiles(path)
            self.assertEqual(profiles["联合飞机"]["嵌入式方向"], ["BSP", "飞控"])
            self.assertEqual(profiles["联合飞机"]["公司所在地"], ["深圳"])
            self.assertEqual(profiles["联合飞机"]["source"], "ai_claude")
            self.assertEqual(profiles["联合飞机"]["ai"]["model"], "claude-opus-4-8")
            self.assertEqual(profiles["联合飞机"]["sources"][0]["field"], "JD原文")

    def test_merge_ai_profile_candidates_does_not_overwrite_text_fields(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "profiles.json")
            merge_ai_profile_candidates([
                {"company": "联合飞机", "fields": {"公司规模": "1000人", "公司简介": "旧简介", "嵌入式方向": ["BSP"]}}
            ], path=path)
            merge_ai_profile_candidates([
                {"company": "联合飞机", "fields": {"公司规模": "9999人", "公司简介": "新简介", "嵌入式方向": ["飞控"]}}
            ], path=path)
            profiles = load_profiles(path)
            self.assertEqual(profiles["联合飞机"]["公司规模"], "1000人")
            self.assertEqual(profiles["联合飞机"]["公司简介"], "旧简介")
            self.assertEqual(profiles["联合飞机"]["嵌入式方向"], ["BSP", "飞控"])


if __name__ == "__main__":
    unittest.main()
