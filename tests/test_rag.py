# -*- coding: utf-8 -*-
"""rag.py 离线单测：加载/余弦检索/evidence 组装/RagService 兜底/端点解析/embed 日志。

夹具：6 块 8 维假向量（真实库为 1024 维，逻辑与维度无关）。零网络——
embed_query 用伪 httpx.Client（mock 注入），RagService 用 stub embed_fn。
"""
import json
import math
import os
import shutil
import tempfile
import unittest
from unittest import mock

import rag


# 6 块 8 维夹具：对 query=[1,0,...] 的余弦得分依次 1.0 / 0.9939 / 0.9701 /
# 0.5 / 0.5（与第 4 块同分，验 tie-break）/ 0.1104
FIXTURE_VECS = [
    [1, 0, 0, 0, 0, 0, 0, 0],
    [0.9, 0.1, 0, 0, 0, 0, 0, 0],
    [0.8, 0, 0.2, 0, 0, 0, 0, 0],
    [0.5, 0.5, 0.5, 0.5, 0, 0, 0, 0],
    [0.5, 0, 0, 0, 0, 0.5, 0.5, 0.5],
    [0.1, 0, 0, 0, 0, 0, 0, 0.9],
]
QUERY = [1, 0, 0, 0, 0, 0, 0, 0]


def write_fixture(path, with_bad_lines=True):
    """写 6 块合法记录（+可选坏行/维度不符/零向量）到 jsonl。"""
    lines = []
    for i, v in enumerate(FIXTURE_VECS, 1):
        lines.append(json.dumps(
            {"id": f"c{i}", "content": f"内容{i}" * 10, "doc_id": f"DOC-{i}",
             "version": f"V{i}", "locator": f"§{i}.1", "embedding": v},
            ensure_ascii=False))
    if with_bad_lines:
        lines.insert(3, "{坏行不是json")
        lines.append(json.dumps({"id": "dim9", "content": "x", "embedding": [1] * 9}))
        lines.append(json.dumps({"id": "zero", "content": "x", "embedding": [0] * 8}))
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


class LoadStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "embeddings.jsonl")
        write_fixture(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_load_counts_and_normalizes(self):
        recs, dim, stats = rag.load_store(self.path)
        self.assertEqual(dim, 8)
        self.assertEqual(stats["loaded"], 6)
        self.assertEqual(stats["bad_lines"], 3)  # 坏 JSON + 维度不符 + 零向量
        self.assertFalse(stats["missing"])
        self.assertEqual([r["id"] for r in recs], [f"c{i}" for i in range(1, 7)])
        for r in recs:  # 加载即归一化：单位向量（2026-09-24 装载瘦身后 vec 落存
            # float32，模长偏差 ~1e-9-1e-8 量级，容差 places=12→6；实测 5.3e-09）
            self.assertAlmostEqual(math.sqrt(rag._dot(r["vec"], r["vec"])), 1.0, places=6)

    def test_missing_file_returns_empty_store(self):
        recs, dim, stats = rag.load_store(os.path.join(self.tmp.name, "无此文件.jsonl"))
        self.assertEqual(recs, [])
        self.assertIsNone(dim)
        self.assertTrue(stats["missing"])

    def test_metadata_fields_kept(self):
        recs, _, _ = rag.load_store(self.path)
        self.assertEqual(recs[0]["doc_id"], "DOC-1")
        self.assertEqual(recs[0]["version"], "V1")
        self.assertEqual(recs[0]["locator"], "§1.1")
        self.assertTrue(recs[0]["content"].startswith("内容1"))


class SearchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.path = os.path.join(cls.tmp.name, "embeddings.jsonl")
        write_fixture(cls.path)
        cls.recs, cls.dim, _ = rag.load_store(cls.path)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_topk_ordering(self):
        hits = rag.search(QUERY, self.recs, topk=5)
        self.assertEqual([h["rec"]["id"] for h in hits], ["c1", "c2", "c3", "c4", "c5"])
        scores = [h["score"] for h in hits]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertAlmostEqual(hits[0]["score"], 1.0, places=12)

    def test_tiebreak_deterministic(self):
        # c4/c5 与 query 的余弦同分（首分量均 0.5）→ 按库内行序 c4 在前；两轮结果一致
        for _ in range(2):
            hits = rag.search(QUERY, self.recs, topk=6)
            s = {h["rec"]["id"]: h["score"] for h in hits}
            self.assertAlmostEqual(s["c4"], s["c5"], places=12)
            self.assertLess([h["rec"]["id"] for h in hits].index("c4"),
                            [h["rec"]["id"] for h in hits].index("c5"))

    def test_topk_beyond_library_size(self):
        hits = rag.search(QUERY, self.recs, topk=50)
        self.assertEqual(len(hits), 6)

    def test_empty_store_returns_none(self):
        self.assertIsNone(rag.search(QUERY, [], topk=5))

    def test_dim_mismatch_raises(self):
        with self.assertRaises(ValueError):
            rag.search([1, 0, 0], self.recs, topk=5)


class BuildEvidenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        path = os.path.join(cls.tmp.name, "embeddings.jsonl")
        write_fixture(path)
        cls.recs, _, _ = rag.load_store(path)
        cls.hits = rag.search(QUERY, cls.recs, topk=6)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_format_and_listing_consistency(self):
        evidence, sources = rag.build_evidence(self.hits, max_context_chars=10 ** 9)
        self.assertTrue(evidence.startswith(rag.EVIDENCE_HEADER))
        self.assertIn("回答时优先依据语料", evidence.splitlines()[0])
        n = len(sources)
        for i in range(1, n + 1):  # 每块带 [出处n] 前缀，编号连续
            self.assertIn(f"\n\n[出处{i}] ", evidence)
        # 末尾出处清单与块前缀一致（同一批编号，含 doc_id/version/locator）
        tail = evidence.split("出处清单：\n", 1)[1]
        self.assertEqual(len(tail.strip().splitlines()), n)
        for i, s in enumerate(sources, 1):
            line = f"[出处{i}] {s['doc_id']} {s['version']} {s['locator']}"
            self.assertIn(line, tail)
        # sources 元数据形态
        self.assertEqual(sources[0]["doc_id"], "DOC-1")
        self.assertIn("score", sources[0])

    def test_truncation_drops_tail_blocks(self):
        big = 10 ** 9
        ev_full, src_full = rag.build_evidence(self.hits, max_context_chars=big)
        self.assertEqual(len(src_full), 6)
        target = None
        for limit in range(len(ev_full), 0, -20):  # 自全量长度向下细扫，找首个触发丢尾的限值
            ev_cut, src_cut = rag.build_evidence(self.hits, max_context_chars=limit)
            if ev_cut is None:
                break
            self.assertLessEqual(len(ev_cut), limit)  # 总长硬上限始终成立
            if len(src_cut) < 6:
                target = (ev_cut, src_cut)
                break
        self.assertIsNotNone(target, "应存在能触发丢尾的限值")
        ev_cut, src_cut = target
        # 丢的是尾部（得分最低的块），保留块前缀编号仍从 1 连续
        self.assertEqual(src_cut[0]["doc_id"], "DOC-1")
        self.assertEqual(src_cut[-1]["doc_id"], f"DOC-{len(src_cut)}")
        kept_ids = {s["doc_id"] for s in src_cut}
        self.assertNotIn(f"DOC-{len(src_cut) + 1}", kept_ids)
        for i in range(1, len(src_cut) + 1):
            self.assertIn(f"\n\n[出处{i}] ", ev_cut)
            self.assertNotIn(f"[出处{len(src_cut) + 1}] ", ev_cut)

    def test_first_block_too_big_returns_none(self):
        # 首块都放不下 → (None, None) → 调用方退裸答
        self.assertEqual(rag.build_evidence(self.hits, max_context_chars=10), (None, None))


class _Silent:
    def __init__(self):
        self.lines = []

    def __call__(self, line):
        self.lines.append(line)


class RagServiceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "embeddings.jsonl")
        write_fixture(self.path)
        self.log = _Silent()

    def tearDown(self):
        self.tmp.cleanup()

    def _service(self, embed_fn, **cfg):
        cfg.setdefault("store_path", self.path)
        svc = rag.RagService(embed_fn=embed_fn, log=self.log)
        svc.initialize(cfg)
        return svc

    def test_retrieve_happy_path(self):
        svc = self._service(lambda q: list(QUERY), topk=3, max_context_chars=6000)
        result = svc.retrieve("测试问题")
        self.assertIsNotNone(result)
        evidence, sources = result
        self.assertTrue(evidence.startswith(rag.EVIDENCE_HEADER))
        self.assertEqual(len(sources), 3)  # topk=3
        self.assertEqual([s["doc_id"] for s in sources], ["DOC-1", "DOC-2", "DOC-3"])
        scores = [s["score"] for s in sources]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_retrieve_missing_store_returns_none_without_embed(self):
        calls = []

        def embed(q):
            calls.append(q)
            return list(QUERY)

        svc = rag.RagService(embed_fn=embed, log=self.log)
        svc.initialize({"store_path": os.path.join(self.tmp.name, "不存在.jsonl")})
        self.assertIsNone(svc.retrieve("q"))
        self.assertEqual(calls, [])  # 库空在 embed 之前短路，不花 embed 调用

    def test_retrieve_embed_failure_returns_none(self):
        def boom(q):
            raise RuntimeError("stub 失败")

        svc = self._service(boom)
        self.assertIsNone(svc.retrieve("q"))
        self.assertTrue(any("miss" in ln for ln in self.log.lines))

    def test_retrieve_dim_mismatch_returns_none(self):
        svc = self._service(lambda q: [1.0, 0.0])  # 2 维 vs 库 8 维
        self.assertIsNone(svc.retrieve("q"))

    def test_retrieve_empty_query_returns_none(self):
        svc = self._service(lambda q: list(QUERY))
        self.assertIsNone(svc.retrieve("   "))

    def test_lazy_reload_after_store_appears(self):
        # 库文件初始化时不存在（建库在飞）→ 服务不重启，库生成后下次 retrieve 生效
        late = os.path.join(self.tmp.name, "late.jsonl")
        svc = rag.RagService(embed_fn=lambda q: list(QUERY), log=self.log)
        svc.initialize({"store_path": late, "topk": 2, "max_context_chars": 6000})
        self.assertIsNone(svc.retrieve("q"))
        write_fixture(late)
        result = svc.retrieve("q")
        self.assertIsNotNone(result)
        self.assertEqual(len(result[1]), 2)

    def test_initialize_tolerates_underscore_keys(self):
        # config.example.json 的 rag 段带 "_说明" 键，必须被容忍
        svc = rag.RagService(embed_fn=lambda q: list(QUERY), log=self.log)
        svc.initialize({"_说明": "x", "enabled": True, "store_path": self.path, "topk": 1})
        self.assertEqual(len(svc.retrieve("q")[1]), 1)


class ResolveEndpointTest(unittest.TestCase):
    def test_env_vars_take_priority(self):
        base, key = rag.resolve_embed_endpoint(
            env={"BAILIAN_EMBED_BASE_URL": "https://env.example", "BAILIAN_EMBED_API_KEY": "env-key"})
        self.assertEqual((base, key), ("https://env.example", "env-key"))

    def _cfg_file(self, payload):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        cfg_path = os.path.join(d, "config.json")
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        return cfg_path

    def test_falls_back_to_config_file(self):
        cfg_path = self._cfg_file({"base_url": "https://file.example", "api_key": "file-key"})
        base, key = rag.resolve_embed_endpoint(env={}, config_path=cfg_path)
        self.assertEqual((base, key), ("https://file.example", "file-key"))

    def test_mixed_env_and_file(self):
        cfg_path = self._cfg_file({"base_url": "https://file.example", "api_key": "file-key"})
        base, key = rag.resolve_embed_endpoint(
            env={"BAILIAN_EMBED_BASE_URL": "https://env.example"}, config_path=cfg_path)
        self.assertEqual((base, key), ("https://env.example", "file-key"))

    def test_missing_file_raises_for_caller_fallback(self):
        with self.assertRaises(OSError):
            rag.resolve_embed_endpoint(env={}, config_path="/nonexistent/.bailian.json")

    def test_incomplete_file_raises(self):
        cfg_path = self._cfg_file({"base_url": "https://file.example"})  # 缺 api_key
        with self.assertRaises(RuntimeError):
            rag.resolve_embed_endpoint(env={}, config_path=cfg_path)


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeClient:
    """伪 httpx.Client：只记录请求参数并返回预置响应，零网络。"""

    resp = None
    exc = None
    captured = {}

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, json=None, headers=None):
        type(self).captured = {"url": url, "json": json, "headers": headers}
        if type(self).exc:
            raise type(self).exc
        return _FakeResp(type(self).resp)


class EmbedQueryLogTest(unittest.TestCase):
    """embed_query 的请求形态与用量日志（伪 client，零网络零真实 key）。"""

    def test_success_log_and_request_shape(self):
        _FakeClient.resp = {"data": [{"embedding": [0.5, 0.5]}], "usage": {"total_tokens": 9}}
        _FakeClient.exc = None
        lines = []
        with mock.patch.object(rag.httpx, "Client", _FakeClient):
            vec = rag.embed_query("测试文本", endpoint=("https://e.example", "sk-FAKE"),
                                  log=lines.append)
        self.assertEqual(vec, [0.5, 0.5])
        req = _FakeClient.captured
        self.assertEqual(req["url"], "https://e.example/compatible-mode/v1/embeddings")
        self.assertEqual(req["json"]["model"], "text-embedding-v4")
        self.assertEqual(req["json"]["input"], ["测试文本"])  # 单条批
        self.assertEqual(req["json"]["dimensions"], 1024)
        self.assertTrue(req["headers"]["Authorization"].startswith("Bearer sk-FAKE"))
        # 用量日志：时间/字符数/tokens/成败齐全，绝不含 key 与 URL
        self.assertEqual(len(lines), 1)
        line = lines[0]
        self.assertIn("[rag-embed]", line)
        self.assertIn("chars=4", line)
        self.assertIn("tokens=9", line)
        self.assertIn("ok=1", line)
        self.assertIn("dur=", line)
        self.assertNotIn("sk-FAKE", line)
        self.assertNotIn("e.example", line)

    def test_failure_log_reports_type_only(self):
        _FakeClient.resp = None
        _FakeClient.exc = TimeoutError("stub 超时")
        lines = []
        with mock.patch.object(rag.httpx, "Client", _FakeClient):
            with self.assertRaises(TimeoutError):
                rag.embed_query("abc", endpoint=("https://e.example", "sk-FAKE"), log=lines.append)
        line = lines[0]
        self.assertIn("ok=0", line)
        self.assertIn("chars=3", line)
        self.assertIn("err=TimeoutError", line)
        self.assertNotIn("sk-FAKE", line)
        self.assertNotIn("stub 超时", line)  # 异常消息（可能含敏感细节）不落日志

    def test_bad_payload_raises(self):
        _FakeClient.resp = {"data": [{"nope": 1}]}  # 无 embedding 字段
        _FakeClient.exc = None
        with mock.patch.object(rag.httpx, "Client", _FakeClient):
            with self.assertRaises(Exception):
                rag.embed_query("x", endpoint=("https://e.example", "k"), log=lambda line: None)


if __name__ == "__main__":
    unittest.main()
