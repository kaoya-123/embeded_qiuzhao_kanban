import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import sync_apply_url_deadline  # noqa: E402


class SyncSelectionTest(unittest.TestCase):
    def test_build_updates_collapses_duplicate_pool_records(self):
        main_recs = [
            {"record_id": "main-union-air", "fields": {"公司名称": "联合飞机"}},
        ]
        pool_recs = [
            {
                "record_id": "good",
                "fields": {
                    "疑似公司": "联合飞机",
                    "岗位名称": "嵌入式系统工程师/电控嵌入式工程师/飞控算法工程师",
                    "发现类型": "嵌入式岗位开放",
                    "岗位开放状态": "已开放",
                    "可信度": "高",
                    "投递链接": {"link": "https://www.uatair.com/about/school.html", "text": "官网"},
                    "投递截至时间": "2026年7月24日截止",
                    "JD原文": "联合飞机2027届校园招聘，嵌入式系统工程师。",
                    "首次发现时间": 100,
                },
            },
            {
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
            },
        ]

        updates, skip_not_open, skip_no_match, merge_notes, display_names = sync_apply_url_deadline.build_updates(pool_recs, main_recs)

        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]["record_id"], "main-union-air")
        self.assertEqual(updates[0]["fields"]["投递截止时间"], "2026年7月24日截止")
        self.assertEqual(updates[0]["fields"]["秋招岗位"], "嵌入式系统工程师/电控嵌入式工程师/飞控算法工程师")
        self.assertEqual(len(merge_notes), 1)
        self.assertEqual(skip_not_open, [])
        self.assertEqual(skip_no_match, [])


if __name__ == "__main__":
    unittest.main()
