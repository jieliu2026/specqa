# -*- coding: utf-8 -*-
"""citation_gate 单测（公开仓面=本体判定 + server 键面）。

口径：citation_gate 的三形引用计数（[证据N]/[出处N]/[来源N] 同规则）、
软空白 warn/硬错 hard 两分、无引用面放行、永不抛出。

源仓另有"双件同源锁定卷"（citation_gate 与 建库/scripts/引文核对器.py 同输入
同判定的对拍类），因该核对器脚本未随公开仓分发（未做脱敏审查），锁定卷不随
本件迁移——本件只保留零私有件依赖的本体测点；两件同源性在源仓测试面维护。

运行：/home/jieliu/qa-bot/venv/bin/python -m pytest tests/test_citation_gate.py -q
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import citation_gate  # noqa: E402

EV = "SS-RSRP is defined as the linear average of the power contributions of the resource elements."
EV2 = "The RRCConnectionReconfiguration message is the command to modify an RRC connection."


class CheckTextTest(unittest.TestCase):
    def test_ok(self):
        r = citation_gate.check_text(f"定义为线性平均[证据1]「{EV}」", EV, 2)
        self.assertTrue(r["ok"] and r["n_cites"] == 1 and r["n_quotes"] == 1)

    def test_out_of_range(self):
        r = citation_gate.check_text("x[证据3]", EV, 2)
        self.assertFalse(r["ok"] and r["hard"] == 1)

    def test_three_forms_in_range(self):
        # 两源不同修复（2026-10-03）：[出处N]/[来源N] 与 [证据N] 同规则计数
        r = citation_gate.check_text(
            f"定义为线性平均[出处1]「{EV}」，另见[来源2]。", EV + "\n" + EV2, 2)
        self.assertTrue(r["ok"] and r["n_cites"] == 2 and r["hard"] == 0)

    def test_chuchu_form_out_of_range(self):
        # 此前 [出处N] 走"无引用面"放行（漏检），现按同规则判越界=纠正漏检
        r = citation_gate.check_text("x[出处3]", EV, 2)
        self.assertFalse(r["ok"])
        self.assertEqual(r["hard"], 1)
        self.assertEqual(r["n_cites"], 1)
        self.assertEqual(r["violations"][0]["type"], "cite_out_of_range")

    def test_laiyuan_form_out_of_range(self):
        r = citation_gate.check_text("y[来源9]", EV, 2)
        self.assertFalse(r["ok"] and r["hard"] == 1)

    def test_three_forms_mixed(self):
        r = citation_gate.check_text("[证据1][出处2][来源2]", EV, 2)
        self.assertTrue(r["ok"] and r["n_cites"] == 3)

    def test_ws_soft(self):
        r = citation_gate.check_text(f"「{EV[:20]}  {EV[20:25]}」", EV, 1)
        self.assertTrue(r["ok"] and r["warn"] == 1 and r["hard"] == 0)

    def test_not_found_hard(self):
        r = citation_gate.check_text("「totally fabricated quote here」", EV, 1)
        self.assertFalse(r["ok"] and r["hard"] == 1)

    def test_no_citation_face(self):
        r = citation_gate.check_text("资料中未找到相应内容。", EV, 1)
        self.assertTrue(r["ok"] and r["n_cites"] == 0)

    def test_never_raises(self):
        r = citation_gate.check_text(None, None, None)
        self.assertTrue(r["ok"])


class ServerConfigTest(unittest.TestCase):
    def test_default_off(self):
        import server
        d = server._depth_config({})
        self.assertFalse(d["citation_gate_enabled"])
        d2 = server._depth_config({"rag": {"citation_gate_enabled": True}})
        self.assertTrue(d2["citation_gate_enabled"])

    def test_example_key_present(self):
        cfg = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
        self.assertIn("citation_gate_enabled", cfg["rag"])
        self.assertIs(cfg["rag"]["citation_gate_enabled"], False)


if __name__ == "__main__":
    unittest.main()
