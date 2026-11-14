# -*- coding: utf-8 -*-
"""E1 检索计时埋点单测（F线B，2026-10-14）：rag.py retrieve() 的 [rag-search] 行。

埋点契约（rag.py retrieve() finally 收口，施工=运营/F线/B线-施工日志-20261014.md）：
  [rag-search] start_ms=<epoch ms> end_ms=<epoch ms> dur_ms=<单调钟差 ms> outcome=<词表>
- outcome 词表与 _dump_snapshot 快照位对齐：
  hit / miss / low_score / coverage_miss / miss_empty_store / miss_empty_query /
  miss_evidence_overflow / miss_error
- 全部返回路径（含异常兜底）恰打一行；dur_ms 非负。
夹具：合成 4 块 8 维假向量（零网络，embed_fn=stub；禁真实用户内容）。
"""
import json
import math
import os
import re
import tempfile
import unittest

import rag

SEARCH_RE = re.compile(r"\[rag-search\] start_ms=(\S+) end_ms=(\S+) "
                       r"dur_ms=(\S+) outcome=(\S+)")
OUTCOMES = ("hit", "miss", "low_score", "coverage_miss", "miss_empty_store",
            "miss_empty_query", "miss_evidence_overflow", "miss_error")

# 4 块 8 维合成夹具：对 query=[1,0,...] 余弦 1.0 / 0.9939 / 0.9701 / 0.5
FIXTURE_VECS = [
    [1, 0, 0, 0, 0, 0, 0, 0],
    [0.9, 0.1, 0, 0, 0, 0, 0, 0],
    [0.8, 0, 0.2, 0, 0, 0, 0, 0],
    [0.5, 0.5, 0.5, 0.5, 0, 0, 0, 0],
]
QUERY = [1, 0, 0, 0, 0, 0, 0, 0]


def write_fixture(path):
    lines = [json.dumps(
        {"id": f"c{i}", "content": f"合成内容{i}" * 8, "doc_id": f"DOC-{i}",
         "version": f"V{i}", "locator": f"§{i}.1", "embedding": v},
        ensure_ascii=False) for i, v in enumerate(FIXTURE_VECS, 1)]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


class _Silent:
    def __init__(self):
        self.lines = []

    def __call__(self, line):
        self.lines.append(line)

    def search_lines(self):
        return [ln for ln in self.lines if "[rag-search]" in ln]


class E1SearchTimingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "embeddings.jsonl")
        write_fixture(self.path)
        self.log = _Silent()

    def tearDown(self):
        self.tmp.cleanup()

    def _service(self, embed_fn, **cfg):
        cfg.setdefault("store_path", self.path)
        cfg.setdefault("topk", 3)
        cfg.setdefault("max_context_chars", 6000)
        svc = rag.RagService(embed_fn=embed_fn, log=self.log)
        svc.initialize(cfg)
        return svc

    @staticmethod
    def _parse(ln):
        m = SEARCH_RE.search(ln)
        assert m, "行不匹配契约正则：%r" % ln
        return (float(m.group(1)), float(m.group(2)), float(m.group(3)),
                m.group(4))

    def test_hit_path_single_wellformed_line(self):
        svc = self._service(lambda q: list(QUERY))
        result = svc.retrieve("合成问题")
        # 既有返回契约不动（回归守卫）：hit → (evidence, sources)
        self.assertIsNotNone(result)
        evidence, sources = result
        self.assertEqual(len(sources), 3)
        scores = [s["score"] for s in sources]
        self.assertEqual(scores, sorted(scores, reverse=True))
        lines = self.log.search_lines()
        self.assertEqual(len(lines), 1, "hit 路径应恰打一行 [rag-search]")
        start_ms, end_ms, dur_ms, outcome = self._parse(lines[0])
        self.assertEqual(outcome, "hit")
        self.assertTrue(outcome in OUTCOMES)
        self.assertTrue(math.isfinite(dur_ms) and dur_ms >= 0.0,
                        "dur_ms 须为非负有限数（单调钟差）")
        self.assertTrue(math.isfinite(start_ms) and math.isfinite(end_ms))
        self.assertGreaterEqual(end_ms, start_ms,
                                "epoch 毫秒时标 start→end 不得倒序")

    def test_empty_store_outcome(self):
        svc = rag.RagService(embed_fn=lambda q: list(QUERY), log=self.log)
        svc.initialize({"store_path": os.path.join(self.tmp.name, "不存在.jsonl")})
        self.assertIsNone(svc.retrieve("q"))
        lines = self.log.search_lines()
        self.assertEqual(len(lines), 1)
        _, _, dur_ms, outcome = self._parse(lines[0])
        self.assertEqual(outcome, "miss_empty_store")
        self.assertTrue(dur_ms >= 0.0)

    def test_empty_query_outcome(self):
        svc = self._service(lambda q: list(QUERY))
        self.assertIsNone(svc.retrieve("   "))
        lines = self.log.search_lines()
        self.assertEqual(len(lines), 1)
        _, _, _, outcome = self._parse(lines[0])
        self.assertEqual(outcome, "miss_empty_query")

    def test_embed_failure_outcome_and_contract(self):
        def boom(q):
            raise RuntimeError("stub 嵌入失败")

        svc = self._service(boom)
        self.assertIsNone(svc.retrieve("q"))  # 异常兜底契约：退 None 不外抛
        lines = self.log.search_lines()
        self.assertEqual(len(lines), 1, "异常路径也应恰打一行（finally 收口）")
        _, _, dur_ms, outcome = self._parse(lines[0])
        self.assertEqual(outcome, "miss_error")
        self.assertTrue(dur_ms >= 0.0)

    def test_low_score_outcome(self):
        # 阈值闸门：合成库 top1 余弦=1.0，阈值抬到 1.0 之上即触发 low_score
        svc = self._service(lambda q: list(QUERY), score_threshold=1.5)
        result = svc.retrieve("合成问题")
        self.assertIsInstance(result, rag.LowScoreResult)
        lines = self.log.search_lines()
        self.assertEqual(len(lines), 1)
        _, _, _, outcome = self._parse(lines[0])
        self.assertEqual(outcome, "low_score")

    def test_repeated_retrieves_each_logged(self):
        svc = self._service(lambda q: list(QUERY))
        for _ in range(3):
            self.assertIsNotNone(svc.retrieve("合成问题"))
        self.assertEqual(len(self.log.search_lines()), 3, "逐次调用逐行打点")

    def test_timing_does_not_alter_prior_log_surface(self):
        # 既有打点面守卫：hit 路径仍打 [rag] retrieve ok 行（既有消费不受伤）
        svc = self._service(lambda q: list(QUERY))
        self.assertIsNotNone(svc.retrieve("合成问题"))
        self.assertTrue(any(ln.startswith("[rag] retrieve ok ") for ln
                            in self.log.lines))


if __name__ == "__main__":
    unittest.main()
