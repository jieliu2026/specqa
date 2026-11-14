# -*- coding: utf-8 -*-
"""server.py 款号一致性检查挂点单测（排序优化四期 P2 #1a 后续，2026-10-03）。

对象=server.py rag 段键 citation_clause_check_enabled（默认 false=零事件零日志，
行为与既往逐字节一致）：开态=正文收尾后跑 citation_clause_check.check_claims
→ 日志行 [citation-clause] face=decl|none oob=N + SSE 事件 citation_clause（先于
done；检测态绝不改答案）。体例=tests/test_citation_sse.py（伪上游 3 delta+usage+
DONE，零网络零真实 key）。
"""
import asyncio
import contextlib
import io
import json
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import server  # 仓根模块（tests/__init__.py 已做 sys.path 引导）
from tests import clean_store_tests  # chat 型限流免疫（2026-10-02 迭代轮泛化）

# 监管族源（款号一致性可判面）：locator=附录1 1.2.1 款1/款2 子款块
SOURCES = [
    {"doc_id": "信息产业部令第36号", "version": "2005（发文年份）",
     "locator": "附录1 1.2.1 拨号时延 款1", "score": 0.80, "quote": "平均值≤2.8秒"},
    {"doc_id": "信息产业部令第36号", "version": "2005（发文年份）",
     "locator": "附录1 1.2.1 拨号时延 款2", "score": 0.79, "quote": "最大值为5.0秒"},
]
EVIDENCE = "以下为检索到的语料片段……\n\n[出处1] 平均值≤2.8秒\n[出处2] 最大值为5.0秒"

OOB_ANSWER = ["见附录1 ", "1.2.9 款1 ", "的规定。"]        # 跨条声明 → oob=1
DECL_OK_ANSWER = ["见附录1 ", "1.2.1 款1 ", "的规定。"]    # 声明面 aligned → oob=0
PLAIN_ANSWER = ["你好", "！", "无任何款号声明。"]           # 无声明面 → face=none


def _stream_tokens(tokens):
    class _OkStream:
        status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def aiter_lines(self):
            for tok in tokens:
                yield "data: " + json.dumps(
                    {"choices": [{"delta": {"content": tok}}]}, ensure_ascii=False)
                await asyncio.sleep(0.01)
            yield "data: " + json.dumps({"usage": {"total_tokens": 9}, "choices": []})
            yield "data: [DONE]"

        async def aread(self):
            return b""

    return _OkStream


class _OkClient:
    def __init__(self, tokens):
        self._tokens = tokens

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def stream(self, method, url, json=None, headers=None, **k):
        return _stream_tokens(self._tokens)()


class _HitSvc:
    """retrieve 恒 hit 的桩（lifespan 启动日志要读 stats）。"""
    stats = {}

    def retrieve(self, query, route_res=None, history=None):
        return (EVIDENCE, SOURCES)


def _cfg(rag_extra=None):
    cfg = {
        "model": "stub-model", "passcode": "pw-test", "bot_name": "测试机",
        "max_history_messages": 40, "max_input_chars": 8000,
        "max_total_input_chars": 24000, "temperature": 0.7, "max_tokens": 100,
        "rate_limit_requests": 20, "rate_limit_window_seconds": 300,
    }
    if rag_extra is not None:
        cfg["rag"] = dict(rag_extra)
    return cfg


_DEFAULT = object()


def _post_chat(rag_extra, tokens, clause_mod=_DEFAULT):
    """一次 /api/chat 全链路（伪上游）→ (events, 日志)。clause_mod=None 可模拟模块缺席。"""
    body = {"messages": [{"role": "user", "content": "拨号时延的规定是什么"}],
            "passcode": "pw-test"}
    out = io.StringIO()
    patches = [
        mock.patch.object(server.httpx, "AsyncClient",
                          lambda *a, **k: _OkClient(tokens)),
        mock.patch.object(server, "CONFIG", _cfg(rag_extra)),
        mock.patch.object(server, "API_KEY", "stub-key"),
        mock.patch.object(server, "rag_service", _HitSvc()),
        contextlib.redirect_stdout(out),
    ]
    if clause_mod is not _DEFAULT:
        patches.append(mock.patch.object(server, "citation_clause_check", clause_mod))
    with contextlib.ExitStack() as st:
        for p in patches:
            st.enter_context(p)
        with TestClient(server.app) as client:
            with client.stream("POST", "/api/chat", json=body) as resp:
                assert resp.status_code == 200
                events = [json.loads(ln[5:].strip()) for ln in resp.iter_lines()
                          if ln.startswith("data:")]
    return events, out.getvalue()


def _types(events):
    return [e.get("type") or ("sources" if "sources" in e else
                              "delta" if "delta" in e else
                              "done" if e.get("done") else "?") for e in events]


def _clause_events(events):
    return [e for e in events if e.get("type") == "citation_clause"]


def _clause_log(logged):
    return [ln for ln in logged.splitlines() if "[citation-clause]" in ln]


class ClauseConfigTest(unittest.TestCase):
    def test_default_off(self):
        for cfg in ({}, {"rag": {}}, {"rag": "not-a-dict"}):
            self.assertFalse(server._depth_config(cfg)["citation_clause_check_enabled"])
        d = server._depth_config({"rag": {"citation_clause_check_enabled": True}})
        self.assertTrue(d["citation_clause_check_enabled"])
        d2 = server._depth_config({"rag": {"citation_clause_check_enabled": 0}})
        self.assertFalse(d2["citation_clause_check_enabled"])


@clean_store_tests
class DefaultOffTest(unittest.TestCase):
    """默认关：零 citation_clause 事件、零 [citation-clause] 日志行。"""

    def test_off_zero_event_zero_log(self):
        events, logged = _post_chat({}, OOB_ANSWER)
        self.assertEqual(_clause_events(events), [])
        self.assertEqual(_clause_log(logged), [])
        self.assertEqual(_types(events), ["sources", "delta", "delta", "delta", "done"])

    def test_explicit_off_zero_event(self):
        events, logged = _post_chat({"citation_clause_check_enabled": False},
                                     OOB_ANSWER)
        self.assertEqual(_clause_events(events), [])
        self.assertEqual(_clause_log(logged), [])


@clean_store_tests
class EnabledTest(unittest.TestCase):
    """开态两分支：oob 拦报与无声明面放行（事件先于 done；答案 deltas 原样）。"""

    def test_oob_branch(self):
        events, logged = _post_chat({"citation_clause_check_enabled": True},
                                     OOB_ANSWER)
        types = _types(events)
        self.assertEqual(types, ["sources", "delta", "delta", "delta",
                                 "citation_clause", "done"])
        ev = _clause_events(events)[0]
        self.assertEqual(ev, {"type": "citation_clause", "ok": False,
                              "claims": 1, "oob": 1, "err": None})
        lines = _clause_log(logged)
        self.assertEqual(len(lines), 1)
        self.assertIn("face=decl", lines[0])
        self.assertIn("oob=1", lines[0])
        self.assertIn("claims=1", lines[0])
        # 检测态不改答案：deltas 原样、done 照常
        self.assertEqual([e.get("delta") for e in events if "delta" in e], OOB_ANSWER)
        self.assertTrue(events[-1]["done"])

    def test_declared_aligned_branch(self):
        events, logged = _post_chat({"citation_clause_check_enabled": True},
                                     DECL_OK_ANSWER)
        ev = _clause_events(events)[0]
        self.assertEqual((ev["ok"], ev["claims"], ev["oob"]), (True, 1, 0))
        self.assertIn("face=decl", _clause_log(logged)[0])
        self.assertIn("oob=0", _clause_log(logged)[0])

    def test_no_claim_face_branch(self):
        events, logged = _post_chat({"citation_clause_check_enabled": True},
                                     PLAIN_ANSWER)
        ev = _clause_events(events)[0]
        self.assertEqual((ev["ok"], ev["claims"], ev["oob"]), (True, 0, 0))
        self.assertIn("face=none", _clause_log(logged)[0])
        self.assertIn("oob=0", _clause_log(logged)[0])
        self.assertTrue(events[-1]["done"])

    def test_module_absent_degrades_off(self):
        # citation_clause_check=None（部署漏带）→ 零事件零日志照常回答
        events, logged = _post_chat({"citation_clause_check_enabled": True},
                                     OOB_ANSWER, clause_mod=None)
        self.assertEqual(_clause_events(events), [])
        self.assertEqual(_clause_log(logged), [])
        self.assertTrue(events[-1]["done"])

    def test_stub_key_never_logged(self):
        _events, logged = _post_chat({"citation_clause_check_enabled": True},
                                      OOB_ANSWER)
        self.assertNotIn("stub-key", logged)   # key 绝不落日志


if __name__ == "__main__":
    unittest.main(verbosity=2)
