import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from dedupe_utils import (  # noqa: E402
    choose_best_pool_record,
    discovery_cluster_key,
    is_description_like_job,
    merge_pool_fields,
    normalize_company,
)


class DedupeUtilsTest(unittest.TestCase):
    def test_description_like_job(self):
        self.assertTrue(is_description_like_job("4.负责飞控系统各类传感器驱动和外设接口软件开发"))
        self.assertFalse(is_description_like_job("嵌入式系统工程师"))

    def test_company_alias(self):
        self.assertEqual(normalize_company(" 乐鑫科技 "), "乐鑫")

    def test_union_air_duplicate_cluster_and_best_record(self):
        good = {
            "record_id": "good",
            "fields": {
                "疑似公司": "联合飞机",
                "岗位名称": "嵌入式系统工程师/电控嵌入式工程师/飞控算法工程师",
                "发现类型": "嵌入式岗位开放",
                "岗位开放状态": "已开放",
                "可信度": "高",
                "投递链接": {"link": "https://www.uatair.com/about/school.html", "text": "官网"},
                "投递截至时间": "2026年7月24日截止",
                "JD原文": "联合飞机2027届校园招聘，嵌入式系统工程师，负责飞控相关开发。",
                "首次发现时间": 100,
            },
        }
        bad = {
            "record_id": "bad",
            "fields": {
                "疑似公司": "联合飞机",
                "岗位名称": "4.负责飞控系统各类传感器驱动和外设接口软件开发",
                "发现类型": "嵌入式岗位开放",
                "岗位开放状态": "已开放",
                "可信度": "高",
                "投递链接": {"link": "https://www.uatair.com/about/school.html", "text": "官网"},
                "投递截至时间": "",
                "JD原文": "4.负责飞控系统各类传感器驱动和外设接口软件开发。",
                "首次发现时间": 200,
            },
        }

        self.assertEqual(discovery_cluster_key(good["fields"]), discovery_cluster_key(bad["fields"]))
        self.assertEqual(choose_best_pool_record([bad, good])["record_id"], "good")
        merged = merge_pool_fields([bad, good])
        self.assertEqual(merged["岗位名称"], "嵌入式系统工程师/电控嵌入式工程师/飞控算法工程师")
        self.assertEqual(merged["投递截至时间"], "2026年7月24日截止")


if __name__ == "__main__":
    unittest.main()
