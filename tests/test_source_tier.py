# -*- coding: utf-8 -*-
"""G 徽标（备发包-20261012·件1）随包测试件——施工窗拷入 tests/ 后生效。

覆盖：source_tier 映射（六族+前缀规则+撞名域 id 分域+缺级 None）、
_annotate_source_tier 纯增键/幂等/容错、开关默认关（config 无键=False）。
零网络零计费：纯函数面单测（先例=tests/test_server_rag.py 的 RagConfigTest）。
"""
import unittest
from unittest import mock

import server  # 仓根模块（tests/__init__.py 已做 sys.path 引导）


class SourceTierMapTest(unittest.TestCase):
    def test_known_docs_and_prefix_rules(self):
        self.assertEqual(server._source_tier_of("TS 38.331", ""), "L1")     # 3GPP TS
        self.assertEqual(server._source_tier_of("TR 28.861", ""), "L2")     # 3GPP TR
        self.assertEqual(server._source_tier_of("YD/T 5264-2021", ""), "L1")  # 行标
        self.assertEqual(server._source_tier_of("国务院令第291号", ""), "L1")   # 工信部件
        self.assertEqual(server._source_tier_of("2025年通信业统计公报", ""), "L2")  # 统计体
        self.assertEqual(server._source_tier_of(
            "2026年前8个月通信业经济运行情况", ""), "L2")
        self.assertEqual(server._source_tier_of(
            "通信系统运行管理专业教学标准（高等职业教育专科）", ""), "L1")  # govstd 域 2026-10-19 扩入
        # 前缀规则位：F3 SON 四件（换库后自动覆盖，无需补表）
        self.assertEqual(server._source_tier_of("TS 32.521", ""), "L1")
        self.assertEqual(server._source_tier_of("TS 28.313", ""), "L1")
        self.assertEqual(server._source_tier_of("TR 32.836", ""), "L2")

    def test_unknown_doc_returns_none(self):
        self.assertIsNone(server._source_tier_of("DOC-X", ""))   # 缺级不猜级
        self.assertIsNone(server._source_tier_of("", ""))

    def test_synthetic_ids_split_domain_despite_doc_collision(self):
        """synthetic 域 doc_id 与 3gpp TS 撞名（如 TS 36.331 双域在役）——块级
        id 冻结名单分域：synthetic 主体=L2、导读卡=L3、3gpp 真身=L1。"""
        syn = sorted(server.SOURCE_TIER_SYNTHETIC_IDS)[0]
        dao = sorted(server.SOURCE_TIER_DAODU_IDS)[0]
        self.assertEqual(server._source_tier_of("TS 36.331", syn), "L2")
        self.assertEqual(server._source_tier_of("TS 36.331", dao), "L3")
        self.assertEqual(server._source_tier_of("TS 36.331", ""), "L1")

    def test_frozen_sets_shape(self):
        self.assertEqual(len(server.SOURCE_TIER_SYNTHETIC_IDS), 304)   # 2026-10-12 Wave4：F2 五卡入表
        self.assertEqual(len(server.SOURCE_TIER_DAODU_IDS), 88)
        self.assertTrue(server.SOURCE_TIER_DAODU_IDS <= server.SOURCE_TIER_SYNTHETIC_IDS)
        # govstd 组（2026-10-19 职责域供给批扩入）：单键 doc 集，与 stat/miit 两
        # doc 集互不相交（doc_exact 合并序无关性的机制前提）
        self.assertEqual(len(server.SOURCE_TIER_GOVSTD_DOCS), 1)
        self.assertFalse(server.SOURCE_TIER_GOVSTD_DOCS
                         & (server.SOURCE_TIER_MIIT_STAT_DOCS
                            | server.SOURCE_TIER_MIIT_DOCS))


class AnnotateTest(unittest.TestCase):
    def test_adds_only_known_and_keeps_existing(self):
        srcs = [{"doc_id": "TS 38.331", "id": "a"},
                {"doc_id": "DOC-X", "id": "b"},                        # 缺级不加键
                {"doc_id": "TS 36.331", "id": "x", "source_tier": "keep"}]
        server._annotate_source_tier(srcs)
        server._annotate_source_tier(srcs)                              # 幂等
        self.assertEqual(srcs[0]["source_tier"], "L1")
        self.assertNotIn("source_tier", srcs[1])
        self.assertEqual(srcs[2]["source_tier"], "keep")                # 不覆写

    def test_tolerates_bad_input(self):
        server._annotate_source_tier(None)                              # None 容错
        server._annotate_source_tier(["x", 7, None])                    # 非 dict 跳过


class FlagTest(unittest.TestCase):
    def test_default_off_and_explicit_on(self):
        cfg = {k: v for k, v in server.CONFIG.items()
               if k != "source_tier_enabled"}
        with mock.patch.object(server, "CONFIG", cfg):
            self.assertFalse(server._source_tier_enabled())     # 无键=默认关
        with mock.patch.object(server, "CONFIG", dict(server.CONFIG,
                                                     source_tier_enabled=True)):
            self.assertTrue(server._source_tier_enabled())


if __name__ == "__main__":
    unittest.main()
