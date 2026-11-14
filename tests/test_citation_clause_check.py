# -*- coding: utf-8 -*-
"""citation_clause_check 单测（排序优化四期 P2 #1a）。

覆盖面（设计稿 §3.7）：四族提取（附录/条中文↔阿拉伯/Table/裸号五护栏）、
aligned 三向（精确同款/父条/条块之子款）、oob 三因（同胞款/跨条/跨附录）、
表族两向、两族分治、无声明面放行、恒不抛出。
体例=tests/test_citation_gate.py。
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import citation_clause_check as ccc  # noqa: E402


def src(loc, doc="信息产业部令第36号"):
    return {"doc_id": doc, "version": "2005（发文年份）", "locator": loc}


REG = [src("附录1 1.2.1 拨号时延 款1"), src("附录1 1.2.1 拨号时延 款2")]
BLOCK = [src("附录1 1.2.1 拨号时延")]
ART = [src("第十三条"), src("第十三条 款1")]
TBL = [{"doc_id": "TS 36.211", "version": "V18.0.2", "locator": "5.2.1 Table 5.2.1-1"}]


class ExtractTest(unittest.TestCase):
    """四族提取与归一（经 claims 面间接断言）。"""

    def _claims(self, text, sources=REG):
        return ccc.check_claims(text, sources)

    def test_app_family_with_kuan(self):
        r = self._claims("依据附录1 1.2.1 款1，平均值≤2.8秒。")
        self.assertEqual(r["n_reg"], 1)
        self.assertEqual(r["claims"][0]["norm"], "附录1 1.2.1 款1")

    def test_art_family_cn_arabic(self):
        r = self._claims("第13条 款1 规定 15 个工作日内答复。", ART)
        self.assertEqual(r["claims"][0]["norm"], "第13条 款1")
        r2 = self._claims("第十三条 款1 规定。", ART)
        self.assertEqual(r2["claims"][0]["norm"], "第13条 款1")

    def test_tbl_family_letter_variant(self):
        r = self._claims("参见 Table 5.2.1-1 与 Table 5.3.2A.2-1。", TBL)
        self.assertEqual(r["n_tbl"], 2)
        self.assertEqual(r["oob"][0]["reason"], "错表")

    def test_bare_family_extracted(self):
        r = self._claims("拨号时延见 1.2.1 款1。", BLOCK)
        self.assertEqual(r["n_reg"], 1)
        self.assertEqual(r["claims"][0]["norm"], "1.2.1 款1")
        self.assertTrue(r["ok"])


class BareGuardTest(unittest.TestCase):
    """裸号族五护栏（误伤防线）。"""

    def test_version_prefix(self):
        r = ccc.check_claims("按 V18.0.2 及 V 15.2.0 版本执行。", REG)
        self.assertEqual(r["n_claims"], 0)

    def test_date_form(self):
        r = ccc.check_claims("自 2026.10.03 起施行。", REG)
        self.assertEqual(r["n_claims"], 0)

    def test_unit_suffix(self):
        r = ccc.check_claims("抖动修正值 3.2.3ms，幅度 3.2.3 毫米。", REG)
        self.assertEqual(r["n_claims"], 0)

    def test_span_overlap_with_app_family(self):
        r = ccc.check_claims("依据附录1 1.2.1 拨号时延 款1 作答。", REG)
        self.assertEqual(r["n_reg"], 1)  # 裸号不重复取
        self.assertTrue(r["ok"])

    def test_no_prefix_of_longer_number(self):
        # "1.2.10" 整取，不得截成 "1.2.1"；前邻字母数字点之内不取
        r = ccc.check_claims("条款 1.2.10 及 TS36.211.4 的说明。", [src("附录1 1.2.10")])
        self.assertEqual(r["n_claims"], 1)
        self.assertEqual(r["claims"][0]["norm"], "1.2.10")
        self.assertTrue(r["ok"])


class AlignedTest(unittest.TestCase):
    """容差三向（预登记 §〇决策①）。"""

    def test_exact_same_kuan(self):
        self.assertTrue(ccc.check_claims("见附录1 1.2.1 款1。", REG)["ok"])

    def test_claim_is_parent_of_source(self):
        # 声明=条级，源=款N 子款块 → aligned（方向二）
        self.assertTrue(ccc.check_claims("见附录1 1.2.1 的规定。", REG)["ok"])

    def test_claim_is_child_of_block(self):
        # 声明=款N，源=条块（locator 无款尾缀）→ aligned（方向三：条块正文物理含款文）
        self.assertTrue(ccc.check_claims("见附录1 1.2.1 款2。", BLOCK)["ok"])

    def test_bare_parent(self):
        self.assertTrue(ccc.check_claims("拨号时延见 1.2.1。", REG)["ok"])

    def test_art_cn_claim_vs_arabic(self):
        self.assertTrue(ccc.check_claims("第十三条 款1 有规定。", ART)["ok"])


class OobTest(unittest.TestCase):
    """oob 三因：同胞款不一致/跨条/跨附录（表族=错表）。"""

    def test_sibling_kuan(self):
        # 源只有 款1 子款块，声明 款2 → 同胞款不一致（条块不在场，方向三不适用）
        r = ccc.check_claims("移动场景见附录1 1.2.1 款2。", [src("附录1 1.2.1 拨号时延 款1")])
        self.assertFalse(r["ok"])
        self.assertEqual(r["oob"][0]["reason"], "同胞款不一致")

    def test_cross_clause(self):
        r = ccc.check_claims("接续时延见附录1 1.2.2 款1。", REG)
        self.assertFalse(r["ok"])
        self.assertEqual(r["oob"][0]["reason"], "跨条")

    def test_cross_appendix(self):
        r = ccc.check_claims("见附录2 2.2.1 可接入率。", REG)
        self.assertFalse(r["ok"])
        self.assertEqual(r["oob"][0]["reason"], "跨附录")

    def test_art_cross(self):
        r = ccc.check_claims("第十五条 款1 另有规定。", ART)
        self.assertFalse(r["ok"])
        self.assertEqual(r["oob"][0]["reason"], "跨条")

    def test_tbl_wrong_table(self):
        r = ccc.check_claims("见 Table 5.2.3-1。", TBL)
        self.assertFalse(r["ok"])
        self.assertEqual(r["oob"][0]["reason"], "错表")

    def test_sibling_trumps_cross(self):
        # 同条同胞款优先归因，不带出"跨条"
        r = ccc.check_claims("附录1 1.2.1 款9 与附录1 1.2.2。", REG)
        reasons = {o["reason"] for o in r["oob"]}
        self.assertIn("同胞款不一致", reasons)
        self.assertIn("跨条", reasons)


class FamilySplitTest(unittest.TestCase):
    """两族分治：监管款号族与 3GPP 表号族互不跨配。"""

    def test_reg_claim_no_reg_source_pass(self):
        # 监管族声明 + 只有 3GPP 表号源 → 无同族源放行
        r = ccc.check_claims("依据附录1 1.2.1 款1 作答。", TBL)
        self.assertTrue(r["ok"])
        self.assertEqual(r["n_reg"], 1)
        self.assertEqual(r["oob"], [])

    def test_tbl_claim_no_tbl_source_pass(self):
        r = ccc.check_claims("见 Table 5.2.1-1。", REG)
        self.assertTrue(r["ok"])
        self.assertEqual(r["n_tbl"], 1)

    def test_mixed_families_each_checked(self):
        r = ccc.check_claims("附录1 1.2.1 款1 与 Table 5.2.3-1。",
                             REG + TBL)
        self.assertFalse(r["ok"])  # 表族错表仍拦（监管族声明 aligned 不受影响）
        self.assertEqual(len(r["oob"]), 1)
        self.assertEqual(r["oob"][0]["family"], "tbl")

    def test_no_family_source_locator(self):
        # 无族 locator（摘要/主要目标/3GPP 纯条号）不参与对齐
        weird = [{"locator": "摘要"}, {"locator": "主要目标 （二） 款2"},
                 {"locator": "3.1 (p1)"}]
        r = ccc.check_claims("依据附录1 1.2.1 款1。", weird)
        self.assertTrue(r["ok"])


class PassThroughTest(unittest.TestCase):
    """无声明面放行 + 恒不抛出。"""

    def test_no_claim_face(self):
        r = ccc.check_claims("资料中未找到相应内容，建议核实。", REG)
        self.assertTrue(r["ok"])
        self.assertEqual(r["n_claims"], 0)

    def test_never_raises_none(self):
        self.assertTrue(ccc.check_claims(None, None)["ok"])
        self.assertTrue(ccc.check_claims(None, None)["n_claims"] == 0)

    def test_never_raises_bad_types(self):
        r1 = ccc.check_claims(12345, "not-a-list")
        r2 = ccc.check_claims("附录1 1.2.1 款1", [None, 42, {"locator": None}])
        for r in (r1, r2):
            self.assertIsInstance(r, dict)
            self.assertIn("ok", r)

    def test_never_raises_bad_locator(self):
        r = ccc.check_claims("附录1 1.2.1 款1", [{"locator": {"嵌套": 1}}])
        self.assertIsInstance(r, dict)
        self.assertIn("ok", r)


if __name__ == "__main__":
    unittest.main()
