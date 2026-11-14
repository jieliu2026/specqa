# -*- coding: utf-8 -*-
"""rag.py 分数阈值闸门（off_topic 双做，2026-09-21 批1）离线单测。

覆盖：top1 余弦口径（纯余弦/lexical/hybrid 三通道形态）、LowScoreResult 载荷、
关闸回退（0/null）、坏配置清洗（非数回默认）、hybrid BM25-only top1 顺位取次优
余弦（不误拦）、top1_cosine 助手函数、默认配置键。零网络（stub embed_fn）。"""
import json
import os
import tempfile
import unittest

import rag
from tests.test_rag import QUERY, write_fixture

# 对 tests/test_rag.py 夹具（6 块 8 维）构造正交查询：第 5 维单位向量与全部
# 6 块的余弦均为 0.0（各块第 5 维分量全 0）→ top1 余弦 0.0（远低于 0.40），
# 口径对齐实测域外样例（Q5 家常菜 top1=0.2016，检索有结果但全弱相关）。
ORTHO_VEC = [0, 0, 0, 0, 1, 0, 0, 0]


class _Silent:
    def __init__(self):
        self.lines = []

    def __call__(self, line):
        self.lines.append(line)


class GateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "embeddings.jsonl")
        write_fixture(self.path)
        self.log = _Silent()

    def tearDown(self):
        self.tmp.cleanup()

    def _service(self, embed=None, **cfg):
        embed = embed or (lambda q: list(QUERY))
        cfg.setdefault("store_path", self.path)
        cfg.setdefault("topk", 3)
        cfg.setdefault("max_context_chars", 6000)
        svc = rag.RagService(embed_fn=embed, log=self.log)
        svc.initialize(cfg)
        return svc

    def test_pure_cosine_below_threshold_returns_low_score(self):
        svc = self._service(embed=lambda q: list(ORTHO_VEC))
        r = svc.retrieve("推荐一道家常菜")
        self.assertIsInstance(r, rag.LowScoreResult)
        self.assertAlmostEqual(r.cosine, 0.0, places=3)  # 余弦原始分，非融合分
        self.assertEqual(r.threshold, 0.40)
        self.assertTrue(any(ln.startswith("[rag] low_score") for ln in self.log.lines))

    def test_pure_cosine_above_threshold_returns_evidence(self):
        svc = self._service()  # top1 余弦 1.0
        ev, srcs = svc.retrieve("a3-Offset 参数取值范围")
        self.assertTrue(ev.startswith(rag.EVIDENCE_HEADER))
        self.assertEqual(len(srcs), 3)
        self.assertFalse(any("low_score" in ln for ln in self.log.lines))

    def test_threshold_zero_disables_gate(self):
        svc = self._service(embed=lambda q: list(ORTHO_VEC), score_threshold=0)
        ev, srcs = svc.retrieve("q")
        self.assertTrue(ev.startswith(rag.EVIDENCE_HEADER))  # 旧行为：照常注入

    def test_threshold_none_disables_gate(self):
        svc = self._service(embed=lambda q: list(ORTHO_VEC), score_threshold=None)
        ev, _srcs = svc.retrieve("q")
        self.assertTrue(ev.startswith(rag.EVIDENCE_HEADER))

    def test_bad_threshold_value_falls_back_to_default(self):
        svc = self._service(embed=lambda q: list(ORTHO_VEC), score_threshold="abc")
        self.assertIsInstance(svc.retrieve("q"), rag.LowScoreResult)  # 回默认 0.40 生效

    def test_threshold_boundary_equal_passes(self):
        # 恰等于阈值不拦（语义=低于才拦）：QUERY 对 c1 余弦恰 1.0，阈值也设 1.0
        svc = self._service(embed=lambda q: list(QUERY), score_threshold=1.0)
        ev, _srcs = svc.retrieve("q")
        self.assertTrue(ev.startswith(rag.EVIDENCE_HEADER))

    def test_lexical_channel_gates_on_cosine_key(self):
        # lexical 态 score=合成分（余弦+λ×词法）≠余弦：闸门必须读 cosine 键。
        # ORTHO_VEC 下合成分=0+λ×词法分（λ 再大也不该抬过闸），cosine 键=0 → 拦。
        svc = self._service(embed=lambda q: list(ORTHO_VEC),
                            lexical_boost=True, lexical_lambda=0.5)
        r = svc.retrieve("内容1 的定义是什么")
        self.assertIsInstance(r, rag.LowScoreResult)

    def test_hybrid_channel_gates_on_cosine_key(self):
        # hybrid 态 score=RRF 融合分（≈0.03 量级）：若闸门误读 score 会全拦（含域内）；
        # 读 cosine 键则余弦高的照常通过——两方向都验。
        svc = self._service(embed=lambda q: list(QUERY), hybrid_bm25_enabled=True)
        ev, _srcs = svc.retrieve("内容1")
        self.assertTrue(ev.startswith(rag.EVIDENCE_HEADER))  # 余弦 1.0 过闸
        svc_low = self._service(embed=lambda q: list(ORTHO_VEC),
                                hybrid_bm25_enabled=True)
        r = svc_low.retrieve("内容1")
        self.assertIsInstance(r, rag.LowScoreResult)
        self.assertAlmostEqual(r.cosine, 0.0, places=3)  # 携带余弦而非融合分

    def test_default_config_has_score_threshold(self):
        self.assertEqual(rag.DEFAULT_RAG_CONFIG["score_threshold"],
                         rag.DEFAULT_SCORE_THRESHOLD)
        self.assertEqual(rag.DEFAULT_SCORE_THRESHOLD, 0.40)


class HybridLowCosineTop1Test(unittest.TestCase):
    """hybrid weighted 态 top1 为低余弦 BM25 块（词法通道抬首）：闸门取集内
    最大余弦不误拦（0.40 档取向=宁可放行，见阈值分析 §四；亦为 test_bm25
    加权融合/词法重排在册行为的守护口径）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "embeddings.jsonl")
        recs = [  # 口径同 test_bm25.SERVICE_RECS：q=[1,0,..] 余弦 c1=1.0/c2≈0.9939/c3=0
            {"id": "c1", "content": "macro handover parameters", "doc_id": "DOC-1",
             "version": "V1", "locator": "§1", "embedding": [1, 0, 0, 0, 0, 0, 0, 0]},
            {"id": "c2", "content": "TS 36.214 RSRP definition table",
             "doc_id": "DOC-2", "version": "V2", "locator": "5.1.1",
             "embedding": [0.9, 0.1, 0, 0, 0, 0, 0, 0]},
            {"id": "c3", "content": "p0-NominalPUSCH 参数卡：INTEGER (0..15)",
             "doc_id": "DOC-3", "version": "V3", "locator": "A.1",
             "embedding": [0, 1, 0, 0, 0, 0, 0, 0]},
        ]
        with open(self.path, "w", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_low_cosine_top1_not_blocked_when_set_has_good_cosine(self):
        # weighted w=0.9 → BM25 满分的 DOC-3 融合分 0.9 居首（余弦 0.0），但集内
        # DOC-1 余弦 1.0 ≥0.40 → 不拦（返回证据而非 LowScoreResult）
        svc = rag.RagService(embed_fn=lambda q: [1, 0, 0, 0, 0, 0, 0, 0],
                             log=lambda line: None)
        svc.initialize({"store_path": self.path, "topk": 2,
                        "max_context_chars": 6000,
                        "hybrid_bm25_enabled": True, "hybrid_fusion": "weighted",
                        "hybrid_bm25_weight": 0.9, "hybrid_candidates": 10})
        result = svc.retrieve("p0-NominalPUSCH 的取值")
        ev, srcs = result
        self.assertEqual([s["doc_id"] for s in srcs], ["DOC-3", "DOC-1"])

    def test_whole_set_low_cosine_still_gated_in_hybrid(self):
        # 反向：整集余弦全低（正交查询）→ 融合重排也救不回，照拦
        svc = rag.RagService(embed_fn=lambda q: [0, 0, 0, 0, 1, 0, 0, 0],
                             log=lambda line: None)
        svc.initialize({"store_path": self.path, "topk": 2,
                        "max_context_chars": 6000,
                        "hybrid_bm25_enabled": True, "hybrid_fusion": "weighted",
                        "hybrid_bm25_weight": 0.9, "hybrid_candidates": 10})
        self.assertIsInstance(svc.retrieve("p0-NominalPUSCH 的取值"),
                              rag.LowScoreResult)


class GateCosineHelperTest(unittest.TestCase):
    """gate_cosine：三种 hit 形态的取值；取集内最大（混合/重排态防误拦）。"""

    def test_pure_cosine_shape_reads_score(self):
        hits = [{"rank": 1, "score": 0.82, "rec": {}, "idx": 0}]
        self.assertEqual(rag.gate_cosine(hits), 0.82)

    def test_lexical_hybrid_shape_reads_cosine_key(self):
        hits = [{"rank": 1, "score": 0.91, "cosine": 0.82, "lexical": 0.9, "rec": {},
                 "idx": 0}]
        self.assertEqual(rag.gate_cosine(hits), 0.82)  # score=合成分不读

    def test_max_over_hits_not_first_hit(self):
        # weighted 融合把余弦 0 的 BM25 块抬到首位：闸门取集内最大余弦（1.0）
        # 而非字面 top1（0.0）——精确术语块被词法/融合通道抬首是设计目的，不拦
        hits = [{"rank": 1, "score": 0.9, "cosine": 0.0, "rec": {}, "idx": 7},
                {"rank": 2, "score": 0.1, "cosine": 1.0, "rec": {}, "idx": 3}]
        self.assertEqual(rag.gate_cosine(hits), 1.0)

    def test_none_cosine_skipped(self):
        hits = [{"rank": 1, "score": 0.9, "cosine": None, "rec": {}, "idx": 7},
                {"rank": 2, "score": 0.5, "cosine": 0.66, "rec": {}, "idx": 3}]
        self.assertEqual(rag.gate_cosine(hits), 0.66)

    def test_all_none_returns_none(self):
        hits = [{"rank": 1, "score": 0.03, "cosine": None, "rec": {}, "idx": 0}]
        self.assertIsNone(rag.gate_cosine(hits))

    def test_empty_hits(self):
        self.assertIsNone(rag.gate_cosine([]))

    def test_bool_ignored(self):
        hits = [{"rank": 1, "score": True, "rec": {}, "idx": 0}]
        self.assertIsNone(rag.gate_cosine(hits))  # bool 是 int 子类，须排除


class NormThresholdTest(unittest.TestCase):
    def test_none_disables(self):
        self.assertEqual(rag._norm_score_threshold(None), 0.0)

    def test_zero_and_negative_disable(self):
        self.assertEqual(rag._norm_score_threshold(0), 0.0)
        self.assertEqual(rag._norm_score_threshold(-0.5), 0.0)

    def test_nan_disables(self):
        self.assertEqual(rag._norm_score_threshold(float("nan")), 0.0)

    def test_bad_value_falls_back_to_default(self):
        self.assertEqual(rag._norm_score_threshold("abc"), rag.DEFAULT_SCORE_THRESHOLD)
        self.assertEqual(rag._norm_score_threshold({}), rag.DEFAULT_SCORE_THRESHOLD)

    def test_valid_value_kept(self):
        self.assertEqual(rag._norm_score_threshold("0.45"), 0.45)
        self.assertEqual(rag._norm_score_threshold(0.5), 0.5)


class LowScoreResultReprTest(unittest.TestCase):
    def test_repr_carries_scores_only(self):
        r = rag.LowScoreResult(0.2016, 0.40)
        self.assertIn("0.2016", repr(r))
        self.assertIn("0.4", repr(r))


if __name__ == "__main__":
    unittest.main()
