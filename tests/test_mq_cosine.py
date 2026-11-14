# -*- coding: utf-8 -*-
"""multiquery.py rrf_fuse_hit_lists 补 cosine 键（2026-09-21 批1 件2）离线单测。

mq 融合输出此前无 cosine 键=阈值闸门启用 mq 的唯一缺口；本件验证补键口径：
纯余弦列表读 score、lexical/hybrid 列表读 cosine 键、跨列表取最大、全无值
None、输入不被修改，以及 mq 端到端闸门路径（RagService mq_enabled+低余弦 →
LowScoreResult）。零网络（stub embed_fn/variant_fn）。"""
import json
import os
import tempfile
import unittest

import multiquery
import rag


def _rec(idx):
    return {"id": f"c{idx}", "doc_id": f"DOC-{idx}", "version": "V1",
            "locator": f"§{idx}", "content": f"内容{idx}"}


class FuseCosineKeyTest(unittest.TestCase):
    def test_pure_cosine_lists_score_is_cosine(self):
        l0 = [{"rank": 1, "score": 0.82, "rec": _rec(0), "idx": 0},
              {"rank": 2, "score": 0.70, "rec": _rec(1), "idx": 1}]
        l1 = [{"rank": 1, "score": 0.91, "rec": _rec(1), "idx": 1}]
        out = multiquery.rrf_fuse_hit_lists([l0, l1], topk=2)
        by_idx = {h["idx"]: h for h in out}
        self.assertAlmostEqual(by_idx[0]["cosine"], 0.82)
        self.assertAlmostEqual(by_idx[1]["cosine"], 0.91)  # 跨列表取最大

    def test_hybrid_list_cosine_key_preferred_over_fused_score(self):
        # hybrid 列表 score=融合分（0.03 量级）、cosine=余弦原始分：cosine 键优先
        l0 = [{"rank": 1, "score": 0.0328, "cosine": 0.85, "bm25": 3.2,
               "channels": "cos+bm25", "rec": _rec(0), "idx": 0}]
        out = multiquery.rrf_fuse_hit_lists([l0], topk=1)
        self.assertAlmostEqual(out[0]["cosine"], 0.85)

    def test_none_cosine_in_one_list_filled_by_other(self):
        # BM25-only 块在某路 cosine=None：另一路有余弦则取该值
        l0 = [{"rank": 1, "score": 5.0, "cosine": None, "rec": _rec(0), "idx": 0}]
        l1 = [{"rank": 2, "score": 0.42, "rec": _rec(0), "idx": 0}]
        out = multiquery.rrf_fuse_hit_lists([l0, l1], topk=1)
        self.assertAlmostEqual(out[0]["cosine"], 0.42)

    def test_all_none_returns_none(self):
        l0 = [{"rank": 1, "score": 5.0, "cosine": None, "rec": _rec(0), "idx": 0}]
        out = multiquery.rrf_fuse_hit_lists([l0], topk=1)
        self.assertIsNone(out[0]["cosine"])

    def test_gate_cosine_consumes_fused_output(self):
        # 与 rag.gate_cosine 对接：融合输出直接喂闸门口径函数
        l0 = [{"rank": 1, "score": 0.82, "rec": _rec(0), "idx": 0}]
        l1 = [{"rank": 1, "score": 0.91, "rec": _rec(1), "idx": 1}]
        out = multiquery.rrf_fuse_hit_lists([l0, l1], topk=2)
        self.assertAlmostEqual(rag.gate_cosine(out), 0.91)

    def test_inputs_not_mutated(self):
        l0 = [{"rank": 1, "score": 0.82, "rec": _rec(0), "idx": 0}]
        l1 = [{"rank": 1, "score": 0.91, "cosine": 0.91, "rec": _rec(1), "idx": 1}]
        snap = (json.dumps(l0, sort_keys=True), json.dumps(l1, sort_keys=True))
        multiquery.rrf_fuse_hit_lists([l0, l1], topk=2)
        self.assertEqual((json.dumps(l0, sort_keys=True),
                          json.dumps(l1, sort_keys=True)), snap)


class _Silent:
    def __init__(self):
        self.lines = []

    def __call__(self, line):
        self.lines.append(line)


class MqGateEndToEndTest(unittest.TestCase):
    """mq 开启端到端：融合输出带 cosine 键 → 低余弦走 LowScoreResult（闸门前置补齐）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "embeddings.jsonl")
        recs = [  # q=[1,0,..] 余弦 c1=1.0/c2≈0.9939/c3=0；正交查询全 0
            {"id": "c1", "content": "macro handover parameters", "doc_id": "DOC-1",
             "version": "V1", "locator": "§1", "embedding": [1, 0, 0, 0, 0, 0, 0, 0]},
            {"id": "c2", "content": "TS 36.214 RSRP definition table",
             "doc_id": "DOC-2", "version": "V2", "locator": "5.1.1",
             "embedding": [0.9, 0.1, 0, 0, 0, 0, 0, 0]},
            {"id": "c3", "content": "p0-NominalPUSCH 参数卡 INTEGER 0..15",
             "doc_id": "DOC-3", "version": "V3", "locator": "A.1",
             "embedding": [0, 1, 0, 0, 0, 0, 0, 0]},
        ]
        with open(self.path, "w", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        self.log = _Silent()

    def tearDown(self):
        self.tmp.cleanup()

    def _service(self, embed, **cfg):
        cfg.setdefault("store_path", self.path)
        cfg.setdefault("topk", 2)
        cfg.setdefault("max_context_chars", 6000)
        svc = rag.RagService(embed_fn=embed, log=self.log,
                             variant_fn=lambda q: ["variant of query"])
        svc.initialize(cfg)
        return svc

    def test_mq_low_cosine_gated(self):
        svc = self._service(lambda q: [0, 0, 0, 0, 1, 0, 0, 0],
                            mq_enabled=True, mq_n_variants=1)
        self.assertIsInstance(svc.retrieve("任意问题"), rag.LowScoreResult)

    def test_mq_high_cosine_passes(self):
        svc = self._service(lambda q: [1, 0, 0, 0, 0, 0, 0, 0],
                            mq_enabled=True, mq_n_variants=1)
        ev, srcs = svc.retrieve("宏切换参数")
        self.assertTrue(ev.startswith(rag.EVIDENCE_HEADER))


if __name__ == "__main__":
    unittest.main()
