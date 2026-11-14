# -*- coding: utf-8 -*-
"""rag.py 词法重排（lexical boost）离线单测：信号提取/词法打分/重排排序/
开关两态/λ=0 退化等价。零网络零 API，全部夹具数据。"""
import json
import os
import tempfile
import unittest

import rag


def _signals_by_key(query):
    return {key: (kind, w) for kind, key, w in rag.lexical_signals(query)}


class LexicalSignalsTest(unittest.TestCase):
    def test_spec_number_signal(self):
        sigs = _signals_by_key("TS 36.214 里 RSRP 怎么定义")
        self.assertIn("36.214", sigs)
        self.assertEqual(sigs["36.214"], ("spec", 2.0))

    def test_identifier_vs_acronym_weights(self):
        sigs = _signals_by_key("t310 a3-Offset RSRP 5G dB maxHARQ-Tx")
        self.assertEqual(sigs["t310"], ("ascii", 1.5))          # 含数字标识符
        self.assertEqual(sigs["a3-Offset"], ("ascii", 1.5))     # 连字符+含数字
        self.assertEqual(sigs["RSRP"], ("ascii", 1.0))          # 全大写缩写
        self.assertEqual(sigs["5G"], ("ascii", 1.5))            # 含数字
        self.assertEqual(sigs["dB"], ("ascii", 0.3))            # 短混合大小写→普通词
        self.assertEqual(sigs["maxHARQ-Tx"], ("ascii", 1.5))    # 驼峰标识

    def test_spec_number_fragments_not_tokens(self):
        # 规范号区间打码：36.214 只产生 spec 信号，不产生 36/214 数字片段
        sigs = _signals_by_key("36.214 规定")
        self.assertNotIn("36", sigs)
        self.assertNotIn("214", sigs)

    def test_pure_digit_filtering(self):
        sigs = _signals_by_key("2024 220 15 483.8")
        self.assertEqual(sigs.get("2024"), ("ascii", 1.2))  # ≥4 位
        self.assertEqual(sigs.get("220"), ("ascii", 0.4))   # 3 位
        self.assertNotIn("15", sigs)                        # ≤2 位丢弃
        self.assertEqual(sigs.get("483"), ("ascii", 0.4))   # 非规范号小数断词，按位宽计

    def test_cjk_bigrams_after_filler_strip(self):
        sigs = _signals_by_key("掉话率监管红线是多少")
        for bg in ("掉话", "话率", "监管", "红线"):
            self.assertEqual(sigs.get(bg), ("cjk", 0.15))
        for noise in ("是多", "多少", "的是", "定义"):
            self.assertNotIn(noise, sigs)

    def test_cjk_filler_words_stripped(self):
        sigs = _signals_by_key("RSRP 的定义是什么")
        self.assertNotIn("定义", sigs)  # 功能词不产生信号（RSRP 仍独立计）

    def test_dedup(self):
        sigs = rag.lexical_signals("RSRP 与 RSRP、RSRP")
        keys = [k for _, k, _ in sigs if k == "RSRP"]
        self.assertEqual(len(keys), 1)

    def test_no_signal_on_pure_filler_query(self):
        self.assertEqual(rag.lexical_signals("的定义是什么"), [])


class LexicalScoreTest(unittest.TestCase):
    def test_case_sensitive_full_credit(self):
        sigs = rag.lexical_signals("T310")
        self.assertEqual(rag.lexical_score("T310", "T310 timer", sigs), 1.0)

    def test_case_insensitive_partial_credit(self):
        sigs = rag.lexical_signals("T310")
        self.assertAlmostEqual(rag.lexical_score("T310", "t310 ENUMERATED", sigs), 0.3)

    def test_spec_number_boundary(self):
        sigs = rag.lexical_signals("36.214 规定")
        self.assertEqual(rag.lexical_score("36.214 规定", "TS 36.214 clause 5", sigs), 1.0)
        self.assertEqual(rag.lexical_score("36.214 规定", "see 36.2141 note", sigs), 0.0)

    def test_score_range_and_zero(self):
        for text in ("", "完全无关文本", "RSRP RSRP"):
            s = rag.lexical_score("RSRP 的定义是什么", text)
            self.assertGreaterEqual(s, 0.0)
            self.assertLessEqual(s, 1.0)
        self.assertEqual(rag.lexical_score("的定义是什么", "任意文本"), 0.0)

    def test_mixed_kinds_weighted_average(self):
        # 信号：36.214(2.0)+RSRP(1.0)=3.0；文本只含 RSRP → 1.0/3.0
        sigs = rag.lexical_signals("36.214 RSRP")
        self.assertAlmostEqual(rag.lexical_score("36.214 RSRP", "RSRP definition", sigs),
                               1.0 / 3.0)


class RerankHitsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hits = [
            {"rank": 1, "score": 0.90, "rec": {"id": "decoy", "doc_id": "TS 36.331",
             "version": "", "locator": "clause A", "content": "something else"}},
            {"rank": 2, "score": 0.89, "rec": {"id": "target", "doc_id": "TS 36.214",
             "version": "", "locator": "5.1.1", "content": "RSRP definition"}},
            {"rank": 3, "score": 0.80, "rec": {"id": "other", "doc_id": "TS 38.215",
             "version": "", "locator": "5.1.2", "content": "CSI-RSRP definition"}},
        ]

    def test_lambda_zero_degenerates_to_cosine(self):
        out = rag.rerank_hits("36.214 RSRP", self.hits, lam=0.0)
        self.assertEqual([h["rec"]["id"] for h in out], ["decoy", "target", "other"])
        for h in out:
            self.assertEqual(h["score"], h["cosine"])  # 精确相等（IEEE +0.0×x）
            self.assertGreaterEqual(h["lexical"], 0.0)
        self.assertEqual([h["rank"] for h in out], [1, 2, 3])

    def test_boost_pulls_matching_block_up(self):
        out = rag.rerank_hits("36.214 RSRP 的定义是什么", self.hits, lam=0.1)
        self.assertEqual(out[0]["rec"]["id"], "target")
        self.assertEqual([h["rank"] for h in out], [1, 2, 3])
        self.assertGreater(out[0]["score"], out[1]["score"])

    def test_tie_break_by_cosine_rank(self):
        # 两块词法分同 0、余弦同分 → 余弦位次（rank）小者在前，且结果确定
        hits = [
            {"rank": 1, "score": 0.5, "rec": {"doc_id": "", "version": "",
             "locator": "", "content": "x"}},
            {"rank": 2, "score": 0.5, "rec": {"doc_id": "", "version": "",
             "locator": "", "content": "y"}},
        ]
        for _ in range(2):
            out = rag.rerank_hits("RSRP", hits, lam=0.5)
            self.assertEqual([h["rec"]["content"] for h in out], ["x", "y"])

    def test_negative_lambda_treated_as_zero(self):
        out = rag.rerank_hits("RSRP", self.hits, lam=-1.0)
        self.assertEqual([h["rec"]["id"] for h in out], ["decoy", "target", "other"])

    def test_empty_hits(self):
        self.assertEqual(rag.rerank_hits("RSRP", [], lam=0.1), [])

    def test_input_hits_not_mutated(self):
        snapshot = json.dumps(self.hits, sort_keys=True)
        rag.rerank_hits("RSRP 定义", self.hits, lam=0.2)
        self.assertEqual(json.dumps(self.hits, sort_keys=True), snapshot)

    def test_custom_text_of_for_flat_hits(self):
        flat = [{"rank": 1, "score": 0.9, "id": "x", "text": "TS 36.214 RSRP"},
                {"rank": 2, "score": 0.95, "id": "y", "text": "nothing"}]
        out = rag.rerank_hits("36.214 RSRP", flat, lam=0.1,
                              text_of=lambda h: h["text"])
        self.assertEqual(out[0]["id"], "x")
        self.assertEqual([h["rank"] for h in out], [1, 2])


class RagServiceLexicalSwitchTest(unittest.TestCase):
    """开关两态：默认/显式关=纯余弦现状；开=词法重排参与服务检索路径。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "embeddings.jsonl")
        recs = [
            {"id": "c1", "content": "macro handover parameters", "doc_id": "DOC-1",
             "version": "V1", "locator": "§1", "embedding": [1, 0, 0, 0, 0, 0, 0, 0]},
            {"id": "c2", "content": "TS 36.214 RSRP definition table",
             "doc_id": "DOC-2", "version": "V2", "locator": "5.1.1",
             "embedding": [0.9, 0.1, 0, 0, 0, 0, 0, 0]},
        ]
        with open(self.path, "w", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        self.query_vec = [1, 0, 0, 0, 0, 0, 0, 0]

    def tearDown(self):
        self.tmp.cleanup()

    def _service(self, **cfg):
        cfg.setdefault("store_path", self.path)
        cfg.setdefault("topk", 2)
        cfg.setdefault("max_context_chars", 6000)
        svc = rag.RagService(embed_fn=lambda q: list(self.query_vec), log=lambda line: None)
        svc.initialize(cfg)
        return svc

    def test_default_config_boost_off_matches_cosine_order(self):
        svc = self._service()  # 不带任何 lexical_* 键 → 默认关
        _, sources = svc.retrieve("36.214 RSRP 的定义是什么")
        self.assertEqual([s["doc_id"] for s in sources], ["DOC-1", "DOC-2"])

    def test_explicit_boost_off_same_as_default(self):
        svc = self._service(lexical_boost=False, lexical_lambda=0.9)  # λ 再大也不生效
        _, sources = svc.retrieve("36.214 RSRP 的定义是什么")
        self.assertEqual([s["doc_id"] for s in sources], ["DOC-1", "DOC-2"])

    def test_boost_on_pulls_lexically_matching_block(self):
        svc = self._service(lexical_boost=True, lexical_lambda=0.1)
        evidence, sources = svc.retrieve("36.214 RSRP 的定义是什么")
        self.assertEqual([s["doc_id"] for s in sources], ["DOC-2", "DOC-1"])
        self.assertGreater(sources[0]["score"], sources[1]["score"])
        self.assertIn("[出处1] DOC-2", evidence)  # 重排后编号与块序一致

    def test_boost_on_with_lambda_zero_equals_cosine(self):
        svc = self._service(lexical_boost=True, lexical_lambda=0)
        _, sources = svc.retrieve("36.214 RSRP 的定义是什么")
        self.assertEqual([s["doc_id"] for s in sources], ["DOC-1", "DOC-2"])

    def test_candidates_floor_respected(self):
        # lexical_candidates < topk 时取大者（余弦候选面不小于输出面）
        svc = self._service(lexical_boost=True, lexical_lambda=0.1,
                            lexical_candidates=1, topk=2)
        _, sources = svc.retrieve("36.214 RSRP 的定义是什么")
        self.assertEqual(len(sources), 2)
        self.assertEqual(sources[0]["doc_id"], "DOC-2")

    def test_default_rag_config_has_lexical_off(self):
        self.assertFalse(rag.DEFAULT_RAG_CONFIG["lexical_boost"])
        self.assertEqual(rag.DEFAULT_RAG_CONFIG["lexical_lambda"],
                         rag.DEFAULT_LEXICAL_LAMBDA)
        self.assertEqual(rag.DEFAULT_RAG_CONFIG["lexical_candidates"], 20)


if __name__ == "__main__":
    unittest.main()
