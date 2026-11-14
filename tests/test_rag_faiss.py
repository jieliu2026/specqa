# -*- coding: utf-8 -*-
"""rag.py faiss IndexFlatIP 加速件离线单测（2026-09-26 施工，阶段二⑤前置件）。

命名口径：取 test_*.py 可 discover 形态（仓根 `python -m unittest discover
-s . -p "test_*.py"` 默认 pattern），连字符日期先例只用于日志/备份件——
带连字符的文件名不被 discover 认得，故不取。

覆盖（全离线零 API，embed 全 stub，合成向量 dim=16）：
- 默认关逐字节等价：开关缺省与显式 false 两态，retrieve 输出与"改前"金路径
  （模块级 rag.search+build_evidence 原函数）全等（含 score 逐位、零新日志）；
- faiss 开等价性：真实 faiss 路径 vs 纯余弦路径，top-k idx/rank 逐位一致、
  分数 |Δ|≤1e-6（对拍口径：排序逐位+分数容差内，见
  建库/logs/faiss对拍-20260926.md）；
- tie-break：比特级同分块（重复向量）相对位次=库内行序，两路一致；
- 降级路径：faiss import 失败（mock）→ [rag-faiss] degrade reason=build +
  退纯余弦输出全等；检索期异常（假索引）→ reason=search + 退纯余弦全等；
- 容缺键 initialize 兼容 + 空库不建索引 + 维度/零向量 ValueError 语义不变；
- 通道复用：hybrid_bm25 / lexical_boost 开时余弦底座走同一 faiss 索引，
  融合/重排结果与 faiss 关时一致（hit 形态不变）。
"""
import json
import os
import random
import tempfile
import unittest
from unittest import mock

import rag

try:
    import faiss  # noqa: F401 —— 仅探测；真实路径由 rag.build_faiss_index 延迟导入
    _HAS_FAISS = True
except Exception:  # pragma: no cover —— 未装 faiss 的环境：等价/降级检索类跳过
    _HAS_FAISS = False

DIM = 16
N_ROWS = 48
SEED = 20260926
TOL = 1e-6        # hits 分数容差（对拍 max|Δ|=1.7e-07，合成 16 维远小于此）
TOL_SRC = 2e-6    # sources.score 已 round(…,6)，容差放宽到进位差


class FaissFixture:
    """共用夹具：48 行合成向量库 + 12 条固定查询（seed 固定，可复跑）。"""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.store = os.path.join(self.tmp.name, "embeddings.jsonl")
        rng = random.Random(SEED)
        self.rows = [[rng.uniform(-1, 1) for _ in range(DIM)]
                     for _ in range(N_ROWS)]
        self._write_store(self.rows)
        self.queries = {f"q{i}": [rng.uniform(-1, 1) for _ in range(DIM)]
                        for i in range(12)}
        self.base_cfg = {"store_path": self.store, "score_threshold": 0,
                         "topk": 5}

    def tearDown(self):
        self.tmp.cleanup()

    def _write_store(self, rows):
        with open(self.store, "w", encoding="utf-8") as f:
            for i, vec in enumerate(rows):
                f.write(json.dumps(
                    {"id": f"c{i}", "content": f"chunk {i} param{i} TS{i} value{i}",
                     "doc_id": f"DOC-{i}", "version": "V1", "locator": f"A.{i}",
                     "embedding": vec}, ensure_ascii=False) + "\n")

    def _svc(self, extra=None):
        """建 RagService（embed stub=查询表；收集日志）→ (svc, logs)。"""
        logs = []
        qmap = self.queries
        cfg = dict(self.base_cfg)
        cfg.update(extra or {})
        svc = rag.RagService(embed_fn=lambda t: qmap[t], log=logs.append)
        svc.initialize(cfg)
        return svc, logs

    def _golden(self, text, topk=5):
        """改前金路径：模块级原函数 search+build_evidence（未被本次施工改动）。"""
        recs, dim, _ = rag.load_store(self.store, use_sidecar=False)
        hits = rag.search(self.queries[text], recs, topk)
        return rag.build_evidence(hits, rag.DEFAULT_MAX_CONTEXT_CHARS)

    @staticmethod
    def _idx_ranks(hits):
        return [h["idx"] for h in hits], [h["rank"] for h in hits]

    def _assert_hits_equivalent(self, hits_f, hits_p):
        """faiss 路 vs 纯余弦路：idx/rank 逐位一致，分数容差内（对拍口径）。"""
        self.assertEqual(self._idx_ranks(hits_f), self._idx_ranks(hits_p))
        self.assertEqual([h["rec"]["id"] for h in hits_f],
                         [h["rec"]["id"] for h in hits_p])
        for hf, hp in zip(hits_f, hits_p):
            self.assertAlmostEqual(hf["score"], hp["score"], delta=TOL)

    def _assert_sources_equivalent(self, src_f, src_p):
        self.assertEqual(len(src_f), len(src_p))
        for xf, xp in zip(src_f, src_p):
            for k in ("doc_id", "version", "locator", "quote"):
                self.assertEqual(xf[k], xp[k], k)
            self.assertAlmostEqual(xf["score"], xp["score"], delta=TOL_SRC)


# -- 默认关：与改前逐字节等价 ------------------------------------------------
class DefaultOffEquivalenceTest(FaissFixture, unittest.TestCase):

    def test_missing_key_equals_prechange(self):
        svc, logs = self._svc()  # rag 段无 faiss_enabled 键（容缺键口径）
        self.assertIs(svc._cfg["faiss_enabled"], False)
        self.assertIsNone(svc._faiss)
        self.assertFalse(any("[rag-faiss]" in line for line in logs))  # 零新日志
        for text in self.queries:
            got = svc.retrieve(text)
            self.assertEqual(got, self._golden(text))  # 全等：evidence 串+sources 含 score

    def test_explicit_false_equals_prechange(self):
        svc, logs = self._svc({"faiss_enabled": False})
        self.assertIsNone(svc._faiss)
        self.assertFalse(any("[rag-faiss]" in line for line in logs))
        for text in self.queries:
            self.assertEqual(svc.retrieve(text), self._golden(text))

    def test_config_defaults_and_tolerance(self):
        self.assertIs(rag.DEFAULT_RAG_CONFIG["faiss_enabled"], False)
        svc = rag.RagService(log=lambda s: None)
        svc.initialize(None)  # 非 dict rag 段（容错口径同现有键）
        self.assertIs(svc._cfg["faiss_enabled"], False)
        svc, _ = self._svc({"faiss_enabled": True})
        self.assertIs(svc._cfg["faiss_enabled"], True)

    def test_empty_store_no_index(self):
        svc, logs = self._svc({"faiss_enabled": True,
                               "store_path": os.path.join(self.tmp.name, "无此库.jsonl")})
        self.assertIsNone(svc._faiss)  # 空库不建索引（retriev 后同）
        self.assertFalse(svc.loaded)
        self.assertIsNone(svc.retrieve("q0"))


# -- faiss 开：与纯余弦路径等价（需 faiss 已装）------------------------------
@unittest.skipUnless(_HAS_FAISS, "faiss-cpu 未装（本测需真实 faiss 路径）")
class FaissOnEquivalenceTest(FaissFixture, unittest.TestCase):

    def test_build_and_hits_equivalence(self):
        svc, logs = self._svc({"faiss_enabled": True})
        self.assertIsNotNone(svc._faiss)
        self.assertEqual(svc._faiss.ntotal, N_ROWS)
        self.assertTrue(any(line.startswith("[rag-faiss] build") for line in logs))
        for text, vec in self.queries.items():
            self._assert_hits_equivalent(
                svc._search_one(text, vec),
                rag.search(vec, svc._recs, self.base_cfg["topk"]))
            # mq 用的统一候选深度路径（depth>topk）同口径
            self._assert_hits_equivalent(
                svc._search_one(text, vec, depth=12),
                rag.search(vec, svc._recs, 12))

    def test_retrieve_equivalence(self):
        svc_f, _ = self._svc({"faiss_enabled": True})
        svc_p, _ = self._svc({"faiss_enabled": False})
        for text in self.queries:
            out_f, out_p = svc_f.retrieve(text), svc_p.retrieve(text)
            self.assertIsNotNone(out_f)
            self.assertEqual(out_f[0], out_p[0])  # evidence 文本全等（不含分数）
            self._assert_sources_equivalent(out_f[1], out_p[1])

    def test_tie_break_row_order(self):
        # 行 4-14 比特级同向量（连续同分块）：自查询产生跨 top-k 边界的同分块，
        # 两路的同分块相对位次都必须=库内行序（生产确定性 tie-break）
        dup = list(self.rows[4])
        rows = list(self.rows)
        for i in range(5, 15):
            rows[i] = list(dup)
        self._write_store(rows)
        self.queries["tie"] = list(self.rows[4])
        svc_f, _ = self._svc({"faiss_enabled": True, "topk": 8})
        svc_p, _ = self._svc({"faiss_enabled": False, "topk": 8})
        self._assert_hits_equivalent(svc_f._search_one("tie", self.queries["tie"]),
                                     svc_p._search_one("tie", self.queries["tie"]))

    def test_validation_semantics_unchanged(self):
        svc, _ = self._svc({"faiss_enabled": True})
        with self.assertRaises(ValueError):  # 维度不符（文案口径同 search）
            svc._search_cos([0.1] * (DIM - 1), 5)
        with self.assertRaises(ValueError):  # 零向量
            svc._search_cos([0.0] * DIM, 5)


# -- 降级路径：纯余弦兜底（faiss 未装也须过 build 降级测）--------------------
class FaissDegradeTest(FaissFixture, unittest.TestCase):

    def test_degrade_build_import_fail(self):
        with mock.patch.object(  # 模拟 faiss 未装：构建期 ImportError
                rag, "build_faiss_index",
                side_effect=ImportError("No module named 'faiss'")):
            svc, logs = self._svc({"faiss_enabled": True})
        self.assertIsNone(svc._faiss)  # 服务不中断
        self.assertTrue(any("[rag-faiss] degrade reason=build" in line for line in logs))
        for text in self.queries:  # 行为=旧路径：输出与金路径全等
            self.assertEqual(svc.retrieve(text), self._golden(text))

    @unittest.skipUnless(_HAS_FAISS, "faiss-cpu 未装（本测需先建真实索引）")
    def test_degrade_search_fail(self):
        class _Boom:
            def search(self, q, k):
                raise RuntimeError("boom")

        svc, logs = self._svc({"faiss_enabled": True})
        self.assertIsNotNone(svc._faiss)
        svc._faiss = _Boom()  # 检索期异常注入
        for text, vec in self.queries.items():
            self.assertEqual(svc._search_one(text, vec),      # 退纯余弦=同库同查询
                             rag.search(vec, svc._recs, self.base_cfg["topk"]))
        self.assertTrue(any("[rag-faiss] degrade reason=search" in line for line in logs))


# -- 通道复用：hybrid/lexical 的余弦底座走同一 faiss 索引 --------------------
@unittest.skipUnless(_HAS_FAISS, "faiss-cpu 未装（本测需真实 faiss 路径）")
class FaissChannelReuseTest(FaissFixture, unittest.TestCase):

    def test_hybrid_channel_equivalence(self):
        extra = {"hybrid_bm25_enabled": True, "hybrid_candidates": 12,
                 "hybrid_fusion": "rrf"}
        svc_f, _ = self._svc(dict(extra, faiss_enabled=True))
        svc_p, _ = self._svc(dict(extra, faiss_enabled=False))
        self.assertIsNotNone(svc_f._faiss)
        for text, vec in self.queries.items():
            h_f, h_p = svc_f._search_one(text, vec), svc_p._search_one(text, vec)
            self.assertEqual(self._idx_ranks(h_f), self._idx_ranks(h_p))
            self.assertEqual([h["channels"] for h in h_f],
                             [h["channels"] for h in h_p])
            for a, b in zip(h_f, h_p):  # RRF 只吃 rank：融合分应精确一致
                self.assertAlmostEqual(a["score"], b["score"], delta=1e-12)
                self.assertAlmostEqual(a["cosine"], b["cosine"], delta=TOL)

    def test_lexical_channel_equivalence(self):
        extra = {"lexical_boost": True, "lexical_lambda": 0.3,
                 "lexical_candidates": 12}
        svc_f, _ = self._svc(dict(extra, faiss_enabled=True))
        svc_p, _ = self._svc(dict(extra, faiss_enabled=False))
        self.assertIsNotNone(svc_f._faiss)
        for text, vec in self.queries.items():
            h_f, h_p = svc_f._search_one(text, vec), svc_p._search_one(text, vec)
            self.assertEqual(self._idx_ranks(h_f), self._idx_ranks(h_p))
            for a, b in zip(h_f, h_p):  # 合成分=余弦+λ×词法：余弦差≤容差
                self.assertAlmostEqual(a["score"], b["score"], delta=2 * TOL)


if __name__ == "__main__":
    unittest.main()
