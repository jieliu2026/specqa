# -*- coding: utf-8 -*-
"""rag.py BM25 并路混合检索离线单测：分词/索引打分/两模式融合/开关两态/
共存语义（hybrid 优先）/索引随库加载缓存。零网络零 API，夹具全内联。

跑法（tests/ 惯例）：仓根起 venv/bin/python -m tests.test_bm25。
沿革：原根级临时位 test_bm25.py（独立成件避免与并行代理冲突），
2026-10-07 A2 小修5 归位 tests/（git mv；件内容零改动除本注）。
"""
import json
import os
import tempfile
import unittest

import rag


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------
def _rec(doc_id, locator, content):
    """BM25Index.build 只读 META_FIELDS 文本，夹具无需 vec。"""
    return {"id": f"{doc_id}|{locator}", "content": content, "doc_id": doc_id,
            "version": "V1", "locator": locator}


CORPUS = [
    _rec("TS 36.213", "5.1.3", "SRS 功率控制 余弦填充文本，用于拉长文档长度并摊薄词频。"),
    _rec("TS 36.331", "A.1", "p0-NominalPUSCH 参数卡：INTEGER (0..15)，缺省 0。"),
    _rec("TS 36.214", "5.1.1", "RSRP 定义：资源粒子功率线性平均，参考信号接收功率。"),
]

# 服务级夹具：8 维向量。对 query=[1,0,...] 余弦依次 c1=1.0 / c2≈0.9939 / c3=0.0
# （c3 与 query 正交=余弦圈外，但含精确术语 p0-NominalPUSCH——BM25 通道正主）。
SERVICE_RECS = [
    {"id": "c1", "content": "宏切换参数概述与常见配置说明", "doc_id": "DOC-1",
     "version": "V1", "locator": "§1", "embedding": [1, 0, 0, 0, 0, 0, 0, 0]},
    {"id": "c2", "content": "TS 36.214 RSRP definition table", "doc_id": "DOC-2",
     "version": "V2", "locator": "5.1.1", "embedding": [0.9, 0.1, 0, 0, 0, 0, 0, 0]},
    {"id": "c3", "content": "p0-NominalPUSCH 参数卡 default value 0", "doc_id": "DOC-3",
     "version": "V3", "locator": "A.1", "embedding": [0, 1, 0, 0, 0, 0, 0, 0]},
]
QUERY_VEC = [1, 0, 0, 0, 0, 0, 0, 0]


def _hit(rank, score, idx, content="x"):
    """手搓单路 hit（search/BM25Index.search 形态，含 idx）。"""
    return {"rank": rank, "score": score, "idx": idx, "rec": _rec(f"D{idx}", "L", content)}


class _Silent:
    def __init__(self):
        self.lines = []

    def __call__(self, line):
        self.lines.append(line)


# ---------------------------------------------------------------------------
# 分词
# ---------------------------------------------------------------------------
class TokenizeTest(unittest.TestCase):
    def test_cjk_bigram_sliding(self):
        self.assertEqual(rag.bm25_tokenize("接续时延"), ["接续", "续时", "时延"])

    def test_ascii_lowercase_and_hyphen_kept(self):
        # 2026-10-09 键微调批（过程日志 51a）：复合词保留整词外加发切分子词
        # （两侧对称零删除；复合词组先出、子词组后随）——治复合词形分裂
        # 投票（C03 反失机制）。
        self.assertEqual(rag.bm25_tokenize("maxHARQ-Tx p0-NominalPUSCH"),
                         ["maxharq-tx", "p0-nominalpusch",
                          "maxharq", "tx", "p0", "nominalpusch"])

    def test_digits_split_on_punct(self):
        self.assertEqual(rag.bm25_tokenize("TS 36.214"), ["ts", "36", "214"])

    def test_duplicates_preserved(self):
        self.assertEqual(rag.bm25_tokenize("RSRP RSRP"), ["rsrp", "rsrp"])

    def test_empty_and_punct_only_and_single_cjk(self):
        self.assertEqual(rag.bm25_tokenize(""), [])
        self.assertEqual(rag.bm25_tokenize(None), [])
        self.assertEqual(rag.bm25_tokenize("，。！？"), [])
        self.assertEqual(rag.bm25_tokenize("率"), [])  # 单字不成词

    def test_mixed_cjk_ascii(self):
        self.assertEqual(rag.bm25_tokenize("掉话率red line红线"),
                         ["掉话", "话率", "红线", "red", "line"])


# ---------------------------------------------------------------------------
# BM25 索引与打分
# ---------------------------------------------------------------------------
class BM25IndexTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = rag.BM25Index.build(CORPUS)

    def test_build_stats(self):
        # 3 文档；token 逐块计（doc_id/version/locator/content 同口径入索引）
        self.assertEqual(self.index.n_docs, 3)
        self.assertGreater(self.index.avgdl, 0)
        self.assertGreater(self.index.n_terms, 0)
        self.assertEqual(self.index.n_terms, len(self.index._post_ids))
        self.assertEqual(self.index.n_postings,
                         sum(len(v) for v in self.index._post_ids.values()))
        self.assertGreater(self.index.postings_bytes, 0)

    def test_doc_id_and_locator_indexed(self):
        # doc_id 里的规范号片段参与索引（36/213/331/214 均可召回本块）
        hits = self.index.search("36.214", topk=3)
        self.assertEqual(hits[0]["rec"]["doc_id"], "TS 36.214")

    def test_rare_exact_term_ranks_first(self):
        hits = self.index.search("p0-NominalPUSCH 取值", topk=3)
        self.assertEqual(hits[0]["rec"]["doc_id"], "TS 36.331")
        # 零命中块不出现在结果里（BM25 只回有匹配项的块）
        self.assertEqual([h["rank"] for h in hits], [1])
        self.assertIn("idx", hits[0])  # 融合所需的库内行序

    def test_empty_or_tokenless_query_returns_empty(self):
        self.assertEqual(self.index.search("", topk=3), [])
        self.assertEqual(self.index.search("。？", topk=3), [])
        self.assertEqual(self.index.search("率", topk=3), [])

    def test_length_normalization_b(self):
        # docA 短、docB 长但 alpha 词频相同：b=1 短文档胜，b=0 与长度无关（同分 tie 行序）
        recs = [_rec("A", "L", "alpha"),
                _rec("B", "L", "alpha " + "填充文本 " * 100)]
        idx = rag.BM25Index.build(recs)
        s_b1 = idx.search("alpha", topk=2, b=1.0)
        self.assertEqual([h["rec"]["doc_id"] for h in s_b1], ["A", "B"])
        s_b0 = idx.search("alpha", topk=2, b=0.0)
        self.assertAlmostEqual(s_b0[0]["score"], s_b0[1]["score"], places=12)
        self.assertEqual([h["rec"]["doc_id"] for h in s_b0], ["A", "B"])

    def test_k1_b_param_bounds_no_crash(self):
        for k1, b in ((-1.0, 0.75), (1.5, 9.0), (1.5, -0.5)):
            hits = self.index.search("RSRP 定义", topk=2, k1=k1, b=b)
            self.assertTrue(hits)

    def test_query_term_repeat_counts(self):
        # 题面重复术语加权：qtf=2 的块得分 ≈ 2×qtf=1（同块同查询）
        one = self.index.search("RSRP", topk=1)[0]["score"]
        two = self.index.search("RSRP RSRP", topk=1)[0]["score"]
        self.assertAlmostEqual(two, 2.0 * one, places=9)
        self.assertEqual(self.index.search("RSRP", topk=1)[0]["idx"],
                         self.index.search("RSRP RSRP", topk=1)[0]["idx"])

    def test_topk_truncation(self):
        hits = self.index.search("RSRP SRS p0-NominalPUSCH 定义 参数", topk=2)
        self.assertEqual(len(hits), 2)


# ---------------------------------------------------------------------------
# 融合（rrf / weighted）
# ---------------------------------------------------------------------------
class FuseHitsTest(unittest.TestCase):
    def test_rrf_formula_and_channels(self):
        cos = [_hit(1, 0.90, 0), _hit(2, 0.80, 1)]
        bm = [_hit(1, 5.0, 2), _hit(2, 4.0, 1)]
        out = rag.fuse_hits(cos, bm, topk=3, mode="rrf", rrf_k=60.0)
        by_idx = {h["idx"]: h for h in out}
        self.assertAlmostEqual(by_idx[0]["score"], 1.0 / 61, places=12)
        self.assertAlmostEqual(by_idx[1]["score"], 2.0 / 62, places=12)
        self.assertAlmostEqual(by_idx[2]["score"], 1.0 / 61, places=12)
        self.assertEqual(by_idx[0]["channels"], "cos")
        self.assertEqual(by_idx[1]["channels"], "cos+bm25")
        self.assertEqual(by_idx[2]["channels"], "bm25")
        self.assertIsNone(by_idx[2]["cosine"])
        self.assertIsNone(by_idx[0]["bm25"])
        self.assertEqual(by_idx[1]["bm25"], 4.0)
        # 同分 tie：cos 路位次小者（idx0）先于仅 bm 路（idx2）
        self.assertEqual([h["idx"] for h in out], [1, 0, 2])
        self.assertEqual([h["rank"] for h in out], [1, 2, 3])

    def test_rrf_single_channel_preserves_order(self):
        cos = [_hit(1, 0.9, 3), _hit(2, 0.8, 1), _hit(3, 0.7, 0)]
        out = rag.fuse_hits(cos, [], topk=3, mode="rrf")
        self.assertEqual([h["idx"] for h in out], [3, 1, 0])

    def test_weighted_formula(self):
        cos = [_hit(1, 0.8, 0), _hit(2, 0.4, 1)]
        bm = [_hit(1, 6.0, 2), _hit(2, 3.0, 1)]
        out = rag.fuse_hits(cos, bm, topk=3, mode="weighted", bm25_weight=0.5)
        by_idx = {h["idx"]: h for h in out}
        self.assertAlmostEqual(by_idx[0]["score"], 0.5 * 1.0, places=12)
        self.assertAlmostEqual(by_idx[1]["score"], 0.5 * 0.5 + 0.5 * 0.5, places=12)
        self.assertAlmostEqual(by_idx[2]["score"], 0.5 * 1.0, places=12)

    def test_weighted_pulls_bm25_only_doc_to_top(self):
        cos = [_hit(1, 0.9, 0), _hit(2, 0.1, 1)]
        bm = [_hit(1, 9.9, 5)]
        out = rag.fuse_hits(cos, bm, topk=3, mode="weighted", bm25_weight=0.9)
        self.assertEqual(out[0]["idx"], 5)  # 0.9*1.0 > 0.1*1.0
        self.assertEqual(out[0]["channels"], "bm25")

    def test_topk_truncation_and_rank_renumber(self):
        cos = [_hit(1, 0.9, 0), _hit(2, 0.8, 1), _hit(3, 0.7, 2)]
        out = rag.fuse_hits(cos, [], topk=2)
        self.assertEqual(len(out), 2)
        self.assertEqual([h["rank"] for h in out], [1, 2])

    def test_empty_inputs(self):
        self.assertEqual(rag.fuse_hits([], []), [])
        self.assertEqual(rag.fuse_hits(None, None, topk=3), [])

    def test_invalid_params_forgiving(self):
        cos = [_hit(1, 0.9, 0)]
        bm = [_hit(1, 3.0, 1)]
        # rrf_k 非法 → 退默认 60；两块各为所在路 rank1 → 同为 1/(60+1)，tie 由
        # cos_rank 决（idx0 先）；bm25_weight 越界 → 钳 [0,1]
        out = rag.fuse_hits(cos, bm, topk=2, rrf_k=-5.0)
        self.assertAlmostEqual(out[0]["score"], 1.0 / 61, places=12)
        self.assertEqual(out[0]["idx"], 0)
        out = rag.fuse_hits(cos, bm, topk=2, mode="weighted", bm25_weight=9.0)
        self.assertEqual(out[0]["idx"], 1)  # w=1 → 纯 bm25 序

    def test_inputs_not_mutated(self):
        cos = [_hit(1, 0.9, 0), _hit(2, 0.8, 1)]
        bm = [_hit(1, 5.0, 2)]
        snap = (json.dumps(cos, sort_keys=True), json.dumps(bm, sort_keys=True))
        rag.fuse_hits(cos, bm, topk=3)
        self.assertEqual((json.dumps(cos, sort_keys=True),
                          json.dumps(bm, sort_keys=True)), snap)


# ---------------------------------------------------------------------------
# RagService 开关两态与共存语义
# ---------------------------------------------------------------------------
class RagServiceHybridTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "embeddings.jsonl")
        with open(self.path, "w", encoding="utf-8") as f:
            for r in SERVICE_RECS:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        self.log = _Silent()

    def tearDown(self):
        self.tmp.cleanup()

    def _service(self, **cfg):
        cfg.setdefault("store_path", self.path)
        cfg.setdefault("topk", 2)
        cfg.setdefault("max_context_chars", 6000)
        svc = rag.RagService(embed_fn=lambda q: list(QUERY_VEC), log=self.log)
        svc.initialize(cfg)
        return svc

    def test_default_config_hybrid_off_is_pure_cosine(self):
        svc = self._service()  # 不带任何 hybrid_* 键 → 默认关=现状
        _, sources = svc.retrieve("p0-NominalPUSCH 的取值")
        self.assertEqual([s["doc_id"] for s in sources], ["DOC-1", "DOC-2"])
        self.assertIsNone(svc._bm25)
        self.assertFalse(any("[rag-bm25]" in ln for ln in self.log.lines))
        self.assertFalse(any("[rag-hybrid]" in ln for ln in self.log.lines))

    def test_explicit_hybrid_off_same_as_default(self):
        svc = self._service(hybrid_bm25_enabled=False, bm25_weight_ok=False)
        _, sources = svc.retrieve("p0-NominalPUSCH 的取值")
        self.assertEqual([s["doc_id"] for s in sources], ["DOC-1", "DOC-2"])

    def test_hybrid_rrf_pulls_cosine_outside_block(self):
        # candidates=2 → 余弦圈只收 DOC-1/2；DOC-3 余弦 0 在圈外，但精确术语命中
        # BM25 rank1（fused 1/61 与 DOC-1 平，tie 由 cos_rank 决）→ 挤掉 DOC-2 进 topk
        svc = self._service(hybrid_bm25_enabled=True, hybrid_fusion="rrf",
                            hybrid_candidates=2)
        _, sources = svc.retrieve("p0-NominalPUSCH 的取值")
        self.assertEqual([s["doc_id"] for s in sources], ["DOC-1", "DOC-3"])

    def test_hybrid_weighted_bm25_wins(self):
        svc = self._service(hybrid_bm25_enabled=True, hybrid_fusion="weighted",
                            hybrid_bm25_weight=0.9, hybrid_candidates=10)
        _, sources = svc.retrieve("p0-NominalPUSCH 的取值")
        self.assertEqual([s["doc_id"] for s in sources], ["DOC-3", "DOC-1"])
        self.assertAlmostEqual(sources[0]["score"], 0.9, places=9)

    def test_hybrid_attribution_log_line(self):
        svc = self._service(hybrid_bm25_enabled=True, hybrid_candidates=10)
        svc.retrieve("p0-NominalPUSCH 的取值")
        line = next(ln for ln in self.log.lines if "[rag-hybrid]" in ln)
        self.assertIn("mode=rrf", line)
        self.assertIn("ch=cos", line)
        self.assertIn("cos=", line)
        self.assertIn("bm25=", line)
        self.assertIn("fused=", line)
        self.assertIn("DOC-3", line)

    def test_hybrid_bm25_tokenless_query_degrades_to_cosine_order(self):
        # 题面无 token（纯标点）→ BM25 空路 → 单路 rrf 保余弦序，不失败
        svc = self._service(hybrid_bm25_enabled=True, hybrid_candidates=10)
        result = svc.retrieve("。。。")
        self.assertIsNotNone(result)
        _, sources = result
        self.assertEqual([s["doc_id"] for s in sources], ["DOC-1", "DOC-2"])

    def test_index_built_at_load_and_cached(self):
        svc = self._service(hybrid_bm25_enabled=True)
        self.assertIsNotNone(svc._bm25)
        build_lines = [ln for ln in self.log.lines if "[rag-bm25] build" in ln]
        self.assertEqual(len(build_lines), 1)  # 随库加载构建一次
        svc.retrieve("RSRP 定义")
        svc.retrieve("p0-NominalPUSCH 取值")
        self.assertEqual([ln for ln in self.log.lines
                          if "[rag-bm25] build" in ln], build_lines)  # 复用缓存

    def test_hybrid_candidates_floor_when_below_topk(self):
        svc = self._service(hybrid_bm25_enabled=True, hybrid_candidates=1, topk=3)
        _, sources = svc.retrieve("p0-NominalPUSCH 的取值")
        self.assertEqual(len(sources), 3)

    def test_coexistence_hybrid_wins_over_lexical(self):
        both = self._service(hybrid_bm25_enabled=True, lexical_boost=True,
                             lexical_lambda=2.0, hybrid_candidates=2)
        _, sources = both.retrieve("p0-NominalPUSCH 的取值")
        # hybrid 优先：结果=纯 hybrid rrf 态（DOC-1 tie-break 在前），lexical 不生效
        self.assertEqual([s["doc_id"] for s in sources], ["DOC-1", "DOC-3"])
        # lexical 单开（hybrid 关）时大 λ（词法分满 1.0×2 > 余弦 1.0）把 DOC-3 抬到
        # 首位——两态结果不同，可证同开时 lexical 确被短路
        lex = self._service(lexical_boost=True, lexical_lambda=2.0)
        _, sources_lex = lex.retrieve("p0-NominalPUSCH 的取值")
        self.assertEqual([s["doc_id"] for s in sources_lex], ["DOC-3", "DOC-1"])
        # 同开时 initialize 打 warn 一行
        warns = [ln for ln in self.log.lines if "hybrid_bm25" in ln and "warn" in ln]
        self.assertEqual(len(warns), 1)

    def test_missing_store_with_hybrid_returns_none(self):
        svc = rag.RagService(embed_fn=lambda q: list(QUERY_VEC), log=self.log)
        svc.initialize({"store_path": os.path.join(self.tmp.name, "无.jsonl"),
                        "hybrid_bm25_enabled": True})
        self.assertIsNone(svc.retrieve("q"))
        self.assertIsNone(svc._bm25)  # 空库不建索引

    def test_default_rag_config_hybrid_keys(self):
        self.assertFalse(rag.DEFAULT_RAG_CONFIG["hybrid_bm25_enabled"])
        self.assertEqual(rag.DEFAULT_RAG_CONFIG["bm25_k1"], rag.DEFAULT_BM25_K1)
        self.assertEqual(rag.DEFAULT_RAG_CONFIG["bm25_b"], rag.DEFAULT_BM25_B)
        self.assertEqual(rag.DEFAULT_RAG_CONFIG["hybrid_fusion"], "rrf")
        self.assertEqual(rag.DEFAULT_RAG_CONFIG["hybrid_rrf_k"], 60.0)
        self.assertEqual(rag.DEFAULT_RAG_CONFIG["hybrid_bm25_weight"], 0.3)
        self.assertEqual(rag.DEFAULT_RAG_CONFIG["hybrid_candidates"], 20)


if __name__ == "__main__":
    unittest.main()
