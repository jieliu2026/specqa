# -*- coding: utf-8 -*-
"""S1 负控治理·乙（order-only 同款族重排）离线单测（2026-09-28 选项一）。

对象=rag.py clause_family_rerank（同款族父条让位+限定词/主体词负项重排，挂
retrieve() 闸前）+ 开关键 clause_family_rerank（默认开，false=回滚旧行为）。
结构断言：order-only——top-k 成员集合与 gate_cosine 闸分逐题零变化（0.40 薄
余量零侵蚀）；让位样例（S1V-12 型：父条含双值压首）+负项重排样例（限定词/
主体词缺失降位）+无信号退化回通道序。零网络（stub embed_fn）。"""
import json
import os
import tempfile
import unittest

import rag


def _hit(rank, score, rid, locator, content, doc_id="信息产业部令第36号"):
    rec = {"id": rid, "doc_id": doc_id, "version": "（2005）",
           "locator": locator, "content": content}
    return {"rank": rank, "score": score, "rec": rec, "idx": rank - 1}


# —— S1V-12 型夹具：父条（含双值）余弦压首，正主子款 款2 次位 ——
P12 = "附录1 1.2.3 网络接通率"
Q12 = "固定电话国内长途网络接通率是多少"
HITS_P12 = [
    _hit(1, 0.80, "p", P12, "【附录1】\n固定电话网网络接通率：本地≥95%，长途≥93%。"),
    _hit(2, 0.79, "s2", P12 + " 款2", "【附录1】\n固定电话国内长途网络接通率≥93%。"),
    _hit(3, 0.78, "s1", P12 + " 款1", "【附录1】\n固定电话本地电话网络接通率≥95%。"),
    _hit(4, 0.60, "f1", "附录2 2.2.1 可接入率", "【附录2】\n可接入率：90％位置99％时间20秒内。"),
    _hit(5, 0.55, "f2", "第十三条", "【正文】\n投诉15个工作日内答复。"),
]


class OrderOnlyInvariantTest(unittest.TestCase):
    """order-only 结构断言：成员集合与闸分零变化（乙的安全面）。"""

    def _assert_invariants(self, query, hits):
        rer = rag.clause_family_rerank(query, hits)
        self.assertSetEqual({h["rec"]["id"] for h in hits},
                            {h["rec"]["id"] for h in rer})           # 成员集合不变
        self.assertEqual([h["rank"] for h in rer], list(range(1, len(rer) + 1)))
        self.assertAlmostEqual(rag.gate_cosine(hits), rag.gate_cosine(rer),
                               places=12)                            # 闸分不变
        by_id = {h["rec"]["id"]: h["score"] for h in hits}
        for h in rer:                                                # 分值不动
            self.assertEqual(h["score"], by_id[h["rec"]["id"]])
        return rer

    def test_p12_invariants(self):
        # 信号=固定/国内长途：s2 零负项居首、s1 缺"国内长途"(1)、f1/f2 双缺(2)、
        # 父条 p 绝对让位至尾
        rer = self._assert_invariants(Q12, HITS_P12)
        self.assertEqual([h["rec"]["id"] for h in rer], ["s2", "s1", "f1", "f2", "p"])

    def test_empty_hits_passthrough(self):
        self.assertEqual(rag.clause_family_rerank(Q12, []), [])

    def test_input_hits_not_mutated(self):
        snapshot = [(h["rank"], h["rec"]["id"]) for h in HITS_P12]
        rag.clause_family_rerank(Q12, HITS_P12)
        self.assertEqual([(h["rank"], h["rec"]["id"]) for h in HITS_P12], snapshot)


class ParentYieldTest(unittest.TestCase):
    """子规则①：同款族父条让位至证据集尾部（父条=数值歧义源）。"""

    def test_parent_yields_to_tail_child_promoted(self):
        rer = rag.clause_family_rerank(Q12, HITS_P12)
        # 父条 p 绝对让位至尾；款2（0 负项）居首；款1 缺"国内长途"降位
        self.assertEqual(rer[-1]["rec"]["id"], "p")
        self.assertEqual(rer[0]["rec"]["id"], "s2")

    def test_parent_yields_even_without_query_signals(self):
        # 题面无词表信号 → 负项无相对差异退化回余弦序，但父让位仍生效
        rer = rag.clause_family_rerank("网络指标是多少", HITS_P12)
        self.assertEqual([h["rec"]["id"] for h in rer], ["s2", "s1", "f1", "f2", "p"])

    def test_no_family_no_reorder(self):
        # 无父子并存且无信号 → 逐位不动（纯退化=旧行为）
        rer = rag.clause_family_rerank("网络指标是多少", HITS_P12[3:])
        self.assertEqual([h["rec"]["id"] for h in rer], ["f1", "f2"])


class NegativeTermTest(unittest.TestCase):
    """子规则②：限定词/主体词负项重排（题面信号缺失者降位，同负项回余弦序）。"""

    def test_qualifier_missing_demotes(self):
        # 款1 缺"国内长途"（负项 1）→ 排在有信号的款2 之后；父条仍绝对让位
        rer = rag.clause_family_rerank(Q12, HITS_P12)
        order = [h["rec"]["id"] for h in rer]
        self.assertLess(order.index("s2"), order.index("s1"))

    def test_subject_word_normalization_matches(self):
        # 归一=去空白+小写："IP 电话"（文本）与"IP电话"（题面）可互配：
        # a 含双信号零负项；b/c 双缺（负项 2），同负项回余弦序（b 分高在前）
        hits = [
            _hit(1, 0.9, "a", "附录3 3.2.1 IP包丢失率 款2",
                 "【附录3】\n移动 IP 电话网络包丢失率≤5%。"),
            _hit(2, 0.89, "b", "附录3 3.2.1 IP包丢失率 款1",
                 "【附录3】\n固定 IP 包丢失率≤2%。"),
            _hit(3, 0.5, "c", "附录4 4.2.5 语音质量", "【附录4】\nMOS 值≥3.5。"),
        ]
        rer = rag.clause_family_rerank("移动IP电话网络包丢失率上限", hits)
        self.assertEqual([h["rec"]["id"] for h in rer], ["a", "b", "c"])

    def test_words_mode_core_vs_full(self):
        # "抖动"属指标词（仅 full 档）：core 下无该信号退化余弦序（父让位除外）
        hits = [
            _hit(1, 0.9, "x", "附录3 3.2.3 IP网络时延抖动 款2",
                 "【附录3】\n移动网络时延抖动≤20ms。"),
            _hit(2, 0.7, "y", "附录3 3.2.2 IP网络时延 款2",
                 "【附录3】\n移动网络时延抖动≤80ms。"),  # 同含"抖动"（负项同）
            _hit(3, 0.6, "z", "附录1 1.2.2 接续时延 款2",
                 "【附录1】\n接续时延平均值≤2.2秒。"),   # 缺"抖动"（full 下负项）
        ]
        full = rag.clause_family_rerank("IP网络时延抖动上限", hits, "full")
        core = rag.clause_family_rerank("IP网络时延抖动上限", hits, "core")
        self.assertEqual([h["rec"]["id"] for h in full], ["x", "y", "z"])
        self.assertEqual([h["rec"]["id"] for h in core], ["x", "y", "z"])  # 同序退化

    def test_full_mode_metric_word_demotes_missing_block(self):
        hits = [
            _hit(1, 0.9, "j", "附录1 1.2.1 拨号时延 款2",
                 "【附录1】\n国内长途拨号时延上限4.5秒。"),
            _hit(2, 0.88, "k", "附录1 1.2.2 接续时延 款2",
                 "【附录1】\n接续时延（回铃音）平均值2.7秒。"),  # 缺"拨号"
        ]
        rer = rag.clause_family_rerank("固话国内长途拨号时延上限", hits)
        self.assertEqual([h["rec"]["id"] for h in rer], ["j", "k"])  # k 负项降位


class RetrieveIntegrationTest(unittest.TestCase):
    """retrieve() 全链：默认开（选项一决策）生效、开关可关（回滚=旧行为）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "embeddings.jsonl")
        recs = [  # 查询向量=[1,0,..]：父条余弦 1.0 压首，款2 0.98，干扰块低分
            {"id": "p", "content": "【附录1】\n固定电话网网络接通率：本地≥95%，长途≥93%。",
             "doc_id": "信息产业部令第36号", "version": "（2005）",
             "locator": "附录1 1.2.3 网络接通率", "embedding": [1, 0, 0, 0, 0, 0, 0, 0]},
            {"id": "s2", "content": "【附录1】\n固定电话国内长途网络接通率≥93%。",
             "doc_id": "信息产业部令第36号", "version": "（2005）",
             "locator": "附录1 1.2.3 网络接通率 款2",
             "embedding": [0.98, 0, 0.2, 0, 0, 0, 0, 0]},
            {"id": "s1", "content": "【附录1】\n固定电话本地电话网络接通率≥95%。",
             "doc_id": "信息产业部令第36号", "version": "（2005）",
             "locator": "附录1 1.2.3 网络接通率 款1",
             "embedding": [0.95, 0, 0.3, 0, 0, 0, 0, 0]},
            {"id": "f1", "content": "【附录2】\n可接入率：90％位置99％时间20秒内。",
             "doc_id": "信息产业部令第36号", "version": "（2005）",
             "locator": "附录2 2.2.1 可接入率", "embedding": [0.6, 0.8, 0, 0, 0, 0, 0, 0]},
        ]
        with open(self.path, "w", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        self.lines = []

    def tearDown(self):
        self.tmp.cleanup()

    def _service(self, **cfg):
        cfg.setdefault("store_path", self.path)
        cfg.setdefault("topk", 4)
        cfg.setdefault("max_context_chars", 6000)
        svc = rag.RagService(embed_fn=lambda q: [1, 0, 0, 0, 0, 0, 0, 0],
                             log=self.lines.append)
        svc.initialize(cfg)
        return svc

    def test_default_on_reranks_before_gate(self):
        svc = self._service()
        ev, srcs = svc.retrieve(Q12)
        self.assertTrue(ev.startswith(rag.EVIDENCE_HEADER))
        # 证据序=重排后序：款2 居首、父条让位至尾（rank 编号按新序）
        self.assertEqual([s["locator"] for s in srcs],
                         ["附录1 1.2.3 网络接通率 款2", "附录1 1.2.3 网络接通率 款1",
                          "附录2 2.2.1 可接入率", "附录1 1.2.3 网络接通率"])
        self.assertTrue(any(ln.startswith("[rag] family_rerank") for ln in self.lines))
        # 闸分口径：过闸（余弦 1.0 ≥ 0.40）——order-only 不影响 gate
        self.assertFalse(any("low_score" in ln for ln in self.lines))

    def test_switch_off_restores_legacy_order(self):
        svc = self._service(clause_family_rerank=False)
        ev, srcs = svc.retrieve(Q12)
        self.assertEqual([s["locator"] for s in srcs][0], "附录1 1.2.3 网络接通率")
        self.assertFalse(any("family_rerank" in ln for ln in self.lines))

    def test_bad_words_mode_falls_back_to_full(self):
        svc = self._service(clause_family_rerank_words="bogus")
        self.assertEqual(svc._cfg["clause_family_rerank_words"], "full")
        ev, srcs = svc.retrieve(Q12)
        self.assertEqual(srcs[0]["locator"], "附录1 1.2.3 网络接通率 款2")


class ConfigDefaultsTest(unittest.TestCase):
    def test_defaults_on_per_option1(self):
        self.assertTrue(rag.DEFAULT_RAG_CONFIG["clause_family_rerank"])
        self.assertEqual(rag.DEFAULT_RAG_CONFIG["clause_family_rerank_words"], "full")

    def test_vocab_shapes(self):
        self.assertIn(("限定词", "国内长途"), rag.CLAUSE_RERANK_WORDS_CORE)
        self.assertIn(("指标词", "抖动"), rag.CLAUSE_RERANK_WORDS_METRIC)
        self.assertNotIn("5G", rag.COVER_GATE_VOCAB)  # 丙词表纪律顺带锁定


if __name__ == "__main__":
    unittest.main()
