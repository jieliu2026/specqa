# -*- coding: utf-8 -*-
"""探针重复 embed 消除·rag 侧单测（2026-10-12 合围 Wave 2-A 第一期）。

对应 建库/work/合围-工程基建一期-20261012/判据-预登记.md 的 E10/E11/E11b
（rag 面原语层；server.py 调用点直传接线由后续小棒做，不在本件面）：
- E10 探针读数零变化：query_vec 直传与 None 自查补嵌两路，同库同题输出
  逐字段一致（[{id,doc_id,locator,cos,text}]），打分逻辑零变化；
- E11 embed 实调每问 -1：query_vec 直传时 embed_query/embed_fn 均不再被调
  （monkeypatch 计数），[rag-embed] journal 行相应少一行（登记在案的唯一
  有意差异）；None 路径=现行为（每调恰一次补嵌）；
- E11b 共享 httpx client：懒初始化（并发首调只构造一次）、超时按调用参数
  生效（异参调用自动回退 per-call 新建）、传输失败回退旧行为 fail-open、
  服务端响应态（HTTP 状态错/坏响应体）不重试（按量面防双发）、journal
  行格式不变、鉴权头按调用逐次构造（key 绝不烘入共享 client）。

零网络零计费：httpx.Client 全伪桩（mock 注入），RagService 用 stub embed_fn
（先例=tests/test_rag.py / tests/test_rerank_log.py）。key/题面绝不入断言面。
"""
import json
import os
import tempfile
import threading
import unittest
from unittest import mock

import rag
from tests.test_rag import QUERY, write_fixture


def _reset_shared_client():
    """模块级共享 embed 连接态复位（测试隔离：伪桩绝不跨文件/跨类泄漏；
    先例=tests/test_rerank_log.py 对 server._rerank_log_cap_warned 的复位）。"""
    rag._embed_client_state = None


# ---------------------------------------------------------------------------
# 伪桩：httpx.Client / Response 形态（零网络）
# ---------------------------------------------------------------------------
class _StubResp:
    """伪 httpx.Response：raise_for_status 无操作；json 返回预置体或抛预置异常。"""

    def __init__(self, payload, json_exc=None):
        self._payload = payload
        self._json_exc = json_exc

    def raise_for_status(self):
        pass

    def json(self):
        if self._json_exc is not None:
            raise self._json_exc
        return self._payload


class _RecordingClient:
    """伪 httpx.Client：记录构造 kwargs 与 post 计数，返回预置响应。

    - instances：类级构造清单（懒初始化/重建/回退的断言面）；
    - fail_posts：前 N 次 post 抛 exc（传输失败→回退旧行为断言面）；
    - json_exc：响应体解析失败（服务端响应态不重试断言面）；
    - post 计数锁保护（并发冒烟下计数确定性）。
    """

    instances = []
    resp = None
    exc = None
    fail_posts = 0
    json_exc = None
    _count_lock = threading.Lock()

    def __init__(self, *args, **kwargs):
        self.timeout_kwarg = kwargs.get("timeout")
        self.posts = 0
        self.closed = False
        type(self).instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    @property
    def is_closed(self):
        return self.closed

    def post(self, url, json=None, headers=None):
        with _RecordingClient._count_lock:
            self.posts += 1
            fail = type(self).fail_posts > 0
            if fail:
                type(self).fail_posts -= 1
        if fail:
            raise type(self).exc
        return _StubResp(type(self).resp, type(self).json_exc)

    def close(self):
        self.closed = True


# ---------------------------------------------------------------------------
# ①/③ 探针向量复用面 + 缺省路径不变（E10/E11）
# ---------------------------------------------------------------------------
class ProbeVecReuseTest(unittest.TestCase):
    """query_vec 直传复用与 None 缺省路径的等价/计数断言。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = os.path.join(self.tmp.name, "embeddings.jsonl")
        write_fixture(self.store)
        _reset_shared_client()          # 防御性复位（本类走 stub，不触共享面）
        self.addCleanup(_reset_shared_client)

    def _svc(self, embed_fn):
        svc = rag.RagService(embed_fn=embed_fn, log=lambda line: None)
        svc.initialize({"store_path": self.store, "topk": 2,
                        "max_context_chars": 6000})
        return svc

    def test_query_vec_reuse_output_identical_and_skips_embed(self):
        """E10+E11 核心：直传零补嵌 + 两路输出逐字段一致。"""
        calls = []

        def embed_fn(q):
            calls.append(q)
            return list(QUERY)

        svc = self._svc(embed_fn)
        out_none = svc.rerank_probe_candidates("问句", 3)      # None=现行为
        self.assertEqual(len(calls), 1)                        # 每调恰一次补嵌
        out_vec = svc.rerank_probe_candidates("问句", 3, query_vec=list(QUERY))
        self.assertEqual(len(calls), 1)                        # 直传=零新增 embed
        self.assertEqual(out_vec, out_none)                    # 逐字段一致（==）
        self.assertEqual(json.dumps(out_vec, ensure_ascii=False),
                         json.dumps(out_none, ensure_ascii=False))  # 严格序列化同
        # 结构与打分锚位（纯余弦 top3：c1=1.0/c2≈0.9939/c3≈0.9701）
        self.assertEqual([c["id"] for c in out_none], ["c1", "c2", "c3"])
        self.assertEqual(out_none[0]["cos"], 1.0)
        self.assertTrue(all(set(c) == {"id", "doc_id", "locator", "cos", "text"}
                            for c in out_none))
        # 显式 query_vec=None 关键字=缺省现行为（每调一次补嵌）
        svc.rerank_probe_candidates("问句", 3, query_vec=None)
        self.assertEqual(len(calls), 2)

    def test_embed_query_module_fn_not_called_with_vec(self):
        """不注 embed_fn 的真路径形态：_embed 落到模块级 embed_query——直传时
        该函数零调用（monkeypatch 计数），None 路径照常一次。"""
        svc = rag.RagService(log=lambda line: None)
        svc.initialize({"store_path": self.store, "topk": 2,
                        "max_context_chars": 6000})
        counts = {"n": 0}
        lines = []

        def fake_embed_query(text, **kw):
            counts["n"] += 1
            lines.append(f"[rag-embed] chars={len(text)} ok=1 dim=8")
            return list(QUERY)

        with mock.patch.object(rag, "embed_query", fake_embed_query):
            out_none = svc.rerank_probe_candidates("问句", 3)
            self.assertEqual(counts["n"], 1)
            out_vec = svc.rerank_probe_candidates("问句", 3,
                                                  query_vec=list(QUERY))
            self.assertEqual(counts["n"], 1)          # embed_query 不再被调
        self.assertEqual(out_vec, out_none)
        # journal 面形状：直传=不补嵌 → [rag-embed] 行不增（E11 唯一有意差异）
        self.assertEqual(len([line for line in lines
                              if line.startswith("[rag-embed]")]), 1)

    def test_simulated_wired_flow_one_embed_total(self):
        """E11 计数原语面：主链 retrieve + 探针直传 → 全程一次 embed 实调
        （未接线旧形态=主链 1 + 探针补嵌 1 = 2）。"""
        calls = []

        def embed_fn(q):
            calls.append(q)
            return list(QUERY)

        svc = self._svc(embed_fn)
        r = svc.retrieve("问句")                       # 主链（未接线=照旧 1 次）
        self.assertIsInstance(r, tuple)
        self.assertEqual(len(calls), 1)
        cands = svc.rerank_probe_candidates("问句", 3, query_vec=list(QUERY))
        self.assertEqual(len(calls), 1)               # 接线后总量仍 1
        self.assertTrue(cands)
        svc.rerank_probe_candidates("问句", 3)        # 旧调用形态=再补嵌一次
        self.assertEqual(len(calls), 2)

    def test_short_circuit_zero_embed(self):
        """空查询/空库短路：两路都 [] 且零 embed（现行为不变）。"""
        calls = []

        def embed_fn(q):
            calls.append(q)
            return list(QUERY)

        svc = self._svc(embed_fn)
        self.assertEqual(svc.rerank_probe_candidates("", 3), [])
        self.assertEqual(svc.rerank_probe_candidates("", 3,
                                                    query_vec=list(QUERY)), [])
        self.assertEqual(svc.rerank_probe_candidates("   ", 3), [])
        empty = rag.RagService(embed_fn=embed_fn, log=lambda line: None)
        empty.initialize({"store_path": os.path.join(self.tmp.name, "无此库.jsonl")})
        self.assertEqual(empty.rerank_probe_candidates("问句", 3), [])
        self.assertEqual(empty.rerank_probe_candidates("问句", 3,
                                                       query_vec=list(QUERY)), [])
        self.assertEqual(calls, [])

    def test_positional_call_form_unchanged(self):
        """server.py 既有调用点（query, n）位置参形态零改动可用（旧调用形态
        兼容底线=回退自查补嵌）。"""
        calls = []

        def embed_fn(q):
            calls.append(q)
            return list(QUERY)

        svc = self._svc(embed_fn)
        out = svc.rerank_probe_candidates("问句", 3)
        self.assertEqual(len(calls), 1)
        self.assertEqual([c["id"] for c in out], ["c1", "c2", "c3"])

    def test_bad_vec_raises_in_contract(self):
        """坏向量（维度不符）由 _search_cos 原样抛出——不静默错池（契约不变，
        探针调用方兜底记跳过）。"""
        svc = self._svc(lambda q: list(QUERY))
        with self.assertRaises(ValueError):
            svc.rerank_probe_candidates("问句", 3, query_vec=[0.5] * 3)


# ---------------------------------------------------------------------------
# ② 共享 httpx client 面（E11b）
# ---------------------------------------------------------------------------
class SharedEmbedClientTest(unittest.TestCase):
    """模块级共享 embed 连接：懒初始化/超时语义/失败回退/并发冒烟/journal 格式。"""

    def setUp(self):
        _reset_shared_client()
        _RecordingClient.instances = []
        _RecordingClient.resp = {"data": [{"embedding": [0.5, 0.5]}],
                                 "usage": {"total_tokens": 9}}
        _RecordingClient.exc = None
        _RecordingClient.fail_posts = 0
        _RecordingClient.json_exc = None
        patcher = mock.patch.object(rag.httpx, "Client", _RecordingClient)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(_reset_shared_client)

    def _embed(self, text="测试文本", **kw):
        lines = []
        vec = rag.embed_query(text, endpoint=("https://e.example", "sk-FAKE"),
                              log=lines.append, **kw)
        return vec, lines

    def test_lazy_init_one_client_reused(self):
        v1, l1 = self._embed()
        v2, l2 = self._embed()
        self.assertEqual(v1, [0.5, 0.5])
        self.assertEqual(v2, [0.5, 0.5])
        self.assertEqual(len(_RecordingClient.instances), 1)   # 两次调用一次构造
        self.assertEqual(_RecordingClient.instances[0].posts, 2)
        for lines in (l1, l2):                                 # journal 格式不变
            self.assertEqual(len(lines), 1)
            self.assertIn("[rag-embed]", lines[0])
            self.assertIn("chars=4", lines[0])
            self.assertIn("tokens=9", lines[0])
            self.assertIn("ok=1", lines[0])
            self.assertIn("dim=2", lines[0])
            self.assertIn("dur=", lines[0])
            self.assertNotIn("sk-FAKE", lines[0])              # key 绝不入日志
            self.assertNotIn("e.example", lines[0])            # URL 不入日志

    def test_timeout_effective_per_call(self):
        """超时按调用参数生效：共享 client 烘入首次超时；异参调用自动回退
        per-call 新建（旧行为），同参调用回到共享连接。"""
        self._embed()                                   # 共享 client 烘入默认 3.0
        v, _ = self._embed(timeout=7.7)                 # 异参 → per-call 新建
        self.assertEqual(v, [0.5, 0.5])
        self.assertEqual(len(_RecordingClient.instances), 2)
        self.assertEqual(_RecordingClient.instances[0].timeout_kwarg, 3.0)
        self.assertEqual(_RecordingClient.instances[1].timeout_kwarg, 7.7)
        self._embed()                                   # 同参 → 复用共享连接
        self.assertEqual(len(_RecordingClient.instances), 2)
        self.assertEqual(_RecordingClient.instances[0].posts, 2)

    def test_transport_fail_falls_back_per_call_once(self):
        """传输失败 → 回退旧行为（per-call 新建重发一次）成功：journal 仍恰
        一行 ok=1；共享态弃置（尽力关闭）→ 下次调用自愈重建。"""
        _RecordingClient.exc = TimeoutError("t")
        _RecordingClient.fail_posts = 1                 # 首发（共享）失败
        v, lines = self._embed()
        self.assertEqual(v, [0.5, 0.5])
        self.assertEqual(len(lines), 1)                 # 不双行（不双记）
        self.assertIn("ok=1", lines[0])
        self.assertEqual(len(_RecordingClient.instances), 2)   # 共享+per-call
        self.assertTrue(_RecordingClient.instances[0].closed)  # 弃置即关闭
        v2, _ = self._embed()                           # 自愈：重建共享连接
        self.assertEqual(v2, [0.5, 0.5])
        self.assertEqual(len(_RecordingClient.instances), 3)

    def test_transport_fail_both_attempts_single_journal_line(self):
        """双发均失败（网络断形态）：异常原样上抛，journal 恰一行 ok=0 只报
        异常类名（旧行为形状；key/URL 绝不入行）。"""
        _RecordingClient.exc = TimeoutError("t")
        _RecordingClient.fail_posts = 99
        lines = []
        with self.assertRaises(TimeoutError):
            rag.embed_query("abc", endpoint=("https://e.example", "sk-FAKE"),
                            log=lines.append)
        self.assertEqual(len(lines), 1)
        self.assertIn("ok=0", lines[0])
        self.assertIn("err=TimeoutError", lines[0])
        self.assertNotIn("sk-FAKE", lines[0])

    def test_response_error_no_retry_no_drop(self):
        """服务端响应态（坏响应体）不重试：请求恰发一次、不新建 per-call、
        共享连接不弃置、journal 一行 ok=0（按量面防双发）。"""
        _RecordingClient.json_exc = ValueError("bad body")
        lines = []
        with self.assertRaises(ValueError):
            rag.embed_query("x", endpoint=("https://e.example", "sk-FAKE"),
                            log=lines.append)
        self.assertEqual(len(lines), 1)
        self.assertIn("ok=0", lines[0])
        self.assertIn("err=ValueError", lines[0])
        self.assertEqual(len(_RecordingClient.instances), 1)   # 无 per-call 回退
        self.assertEqual(_RecordingClient.instances[0].posts, 1)  # 恰一次请求
        self.assertFalse(_RecordingClient.instances[0].closed)    # 共享态保留
        _RecordingClient.json_exc = None                          # 坏体标志复位
        v, _ = self._embed()                                     # 下次照常复用
        self.assertEqual(v, [0.5, 0.5])
        self.assertEqual(len(_RecordingClient.instances), 1)

    def test_closed_client_rebuilds_under_lock(self):
        self._embed()
        _RecordingClient.instances[0].closed = True     # 模拟共享连接已关
        v, _ = self._embed()
        self.assertEqual(v, [0.5, 0.5])
        self.assertEqual(len(_RecordingClient.instances), 2)   # 锁内重建

    def test_construction_fail_degrades_to_old_path(self):
        """构造失败 → fail-open 回退 per-call（旧行为同形失败上抛，journal
        一行 ok=0 err=<类名>，不额外炸出机制异常）。"""

        class _Boom:
            def __init__(self, *a, **k):
                raise RuntimeError("ctor")

        with mock.patch.object(rag.httpx, "Client", _Boom):
            lines = []
            with self.assertRaises(RuntimeError):
                rag.embed_query("x", endpoint=("https://e.example", "sk-FAKE"),
                                log=lines.append)
        self.assertEqual(len(lines), 1)
        self.assertIn("ok=0", lines[0])
        self.assertIn("err=RuntimeError", lines[0])

    def test_concurrent_lazy_init_and_requests(self):
        """并发冒烟（E11b）：8 线程 × 5 调屏障同发——懒初始化恰构造一个
        client（双检锁）、40 次请求全成、零异常（请求级并发交 httpx.Client，
        计数经锁保确定性）。"""
        n_threads, per_thread = 8, 5
        barrier = threading.Barrier(n_threads)
        errors = []
        results = []

        def worker(i):
            try:
                barrier.wait(timeout=10)
                for _ in range(per_thread):
                    v, _ = self._embed(text=f"并发文本{i}")
                    results.append(v)
            except Exception as e:   # noqa: BLE001 —— 断言面=errors 清单
                errors.append(e)

        ts = [threading.Thread(target=worker, args=(i,))
              for i in range(n_threads)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(timeout=30)
        self.assertEqual(errors, [])
        self.assertEqual(len(results), n_threads * per_thread)
        self.assertTrue(all(v == [0.5, 0.5] for v in results))
        self.assertEqual(len(_RecordingClient.instances), 1)   # 恰一次构造
        self.assertEqual(_RecordingClient.instances[0].posts,
                         n_threads * per_thread)

    def test_headers_built_per_call(self):
        """鉴权头按调用逐次构造（key 绝不烘入共享 client）：异 key 两调用
        各自带各的 Authorization。"""
        captured = []
        orig_post = _RecordingClient.post

        def spy_post(self, url, json=None, headers=None):
            captured.append(headers)
            return orig_post(self, url, json=json, headers=headers)

        with mock.patch.object(_RecordingClient, "post", spy_post):
            rag.embed_query("a", endpoint=("https://e.example", "sk-FAKE-1"),
                            log=lambda line: None)
            rag.embed_query("b", endpoint=("https://e.example", "sk-FAKE-2"),
                            log=lambda line: None)
        self.assertEqual(len(captured), 2)
        self.assertEqual(captured[0]["Authorization"], "Bearer sk-FAKE-1")
        self.assertEqual(captured[1]["Authorization"], "Bearer sk-FAKE-2")


if __name__ == "__main__":
    unittest.main()
