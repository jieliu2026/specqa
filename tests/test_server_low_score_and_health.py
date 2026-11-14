# -*- coding: utf-8 -*-
"""server.py 批1三件离线单测：低分 off_topic 事件序+[chat] rag=low_score、
TTFB 打点（有 delta=数值/无 delta=na）、/api/health 分级（无口令只回 ok）。
伪 httpx.AsyncClient 模拟上游——全程零网络零真实 key。"""
import asyncio
import contextlib
import io
import json
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import rag
import server  # 仓根模块（tests/__init__.py 已做 sys.path 引导）
from tests import clean_store_tests  # chat 型限流免疫（2026-10-02 迭代轮泛化）


# ---------- 伪上游：超时（无 delta）与正常流（3 delta+usage+DONE） ----------
class _TimeoutStream:
    async def __aenter__(self):
        import httpx
        raise httpx.TimeoutException("stub 上游超时")

    async def __aexit__(self, *a):
        return False


class _TimeoutClient:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def stream(self, *a, **k):
        return _TimeoutStream()


class _OkStream:
    status_code = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def aiter_lines(self):
        for tok in ("你", "好", "！"):
            yield "data: " + json.dumps(
                {"choices": [{"delta": {"content": tok}}]}, ensure_ascii=False)
            await asyncio.sleep(0.05)
        yield "data: " + json.dumps({"usage": {"total_tokens": 9}, "choices": []})
        yield "data: [DONE]"

    async def aread(self):
        return b""


class _OkClient:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def stream(self, *a, **k):
        return _OkStream()


class _LowSvc:
    """retrieve 恒回 LowScoreResult 的桩（lifespan 启动日志要读 stats）。"""
    stats = {}

    def __init__(self, cos=0.2016, thr=0.40):
        self._r = rag.LowScoreResult(cos, thr)

    def retrieve(self, query, route_res=None, history=None):
        return self._r


class _HitSvc:
    stats = {}

    def retrieve(self, query, route_res=None, history=None):
        return ("证据", [{"doc_id": "TS 36.331", "version": "V17",
                         "locator": "§5.2.2", "score": 0.9}])


_FAKE_CONFIG = {
    "model": "stub-model", "passcode": "pw-test", "bot_name": "测试机",
    "max_history_messages": 40, "max_input_chars": 8000,
    "max_total_input_chars": 24000, "temperature": 0.7, "max_tokens": 100,
    "rate_limit_requests": 20, "rate_limit_window_seconds": 300,
}


def _post_chat(client_cls, svc, messages=None):
    body = {"messages": messages or [{"role": "user", "content": "问句"}],
            "passcode": "pw-test"}
    out = io.StringIO()
    with mock.patch.object(server.httpx, "AsyncClient", client_cls), \
            mock.patch.object(server, "CONFIG", _FAKE_CONFIG), \
            mock.patch.object(server, "API_KEY", "stub-key"), \
            mock.patch.object(server, "rag_service", svc), \
            contextlib.redirect_stdout(out):
        with TestClient(server.app) as client:
            with client.stream("POST", "/api/chat", json=body) as resp:
                assert resp.status_code == 200
                events = [json.loads(ln[5:].strip()) for ln in resp.iter_lines()
                          if ln.startswith("data:")]
    return events, out.getvalue()


def _chat_line(logged):
    return [ln for ln in logged.splitlines() if "[chat]" in ln][0]


@clean_store_tests
class LowScoreFlowTest(unittest.TestCase):
    def test_off_topic_event_first_then_deltas_and_log(self):
        events, logged = _post_chat(_OkClient, _LowSvc())
        self.assertEqual(events[0], {"type": "off_topic"})  # 先于一切正文事件
        self.assertEqual([e.get("delta") for e in events[1:4]], ["你", "好", "！"])
        self.assertTrue(events[-1].get("done"))
        self.assertFalse(any("sources" in e for e in events))  # 不下发 sources
        line = _chat_line(logged)
        self.assertIn("rag=low_score", line)
        self.assertIn("top1=0.2016", line)   # 触发闸门的余弦原始分口径
        self.assertIn('q="问句"', line)
        self.assertNotIn("stub-key", logged)

    def test_low_score_upstream_timeout_ttfb_na(self):
        events, logged = _post_chat(_TimeoutClient, _LowSvc())
        self.assertEqual(events, [{"type": "off_topic"},
                                  {"error": "upstream_timeout"}])
        line = _chat_line(logged)
        self.assertIn("rag=low_score", line)
        self.assertIn("ttfb=na", line)  # 无 delta 收尾记 na

    def test_hit_flow_ttfb_numeric(self):
        events, logged = _post_chat(_OkClient, _HitSvc())
        self.assertEqual(events[0].get("sources")[0]["doc_id"], "TS 36.331")
        line = _chat_line(logged)
        self.assertIn("rag=hit", line)
        self.assertIn("top1=0.9000", line)
        self.assertRegex(line, r"ttfb=\d+\.\d{2}s")  # 首 delta 时刻-请求开始
        self.assertNotIn("ttfb=na", line)

    def test_ttfb_field_precedes_dur(self):
        _events, logged = _post_chat(_OkClient, _HitSvc())
        line = _chat_line(logged)
        self.assertLess(line.index("ttfb="), line.index("dur="))


class HealthTierTest(unittest.TestCase):
    """分级：GET 只回 {"ok":true}；POST 正确口令回完整字段；错口令=无口令。
    口令走 POST body（校验同 /api/chat；不经 URL=不落访问日志）。"""

    def _client(self, cfg=None):
        cfg = cfg or _FAKE_CONFIG
        return mock.patch.object(server, "CONFIG", cfg), \
            mock.patch.object(server, "API_KEY", "stub-key")

    def _get(self, cfg=None):
        pc, key = self._client(cfg)
        with pc, key:
            with TestClient(server.app) as client:
                resp = client.get("/api/health")
        return resp.json()

    def _post(self, passcode, cfg=None):
        pc, key = self._client(cfg)
        with pc, key:
            with TestClient(server.app) as client:
                resp = client.post("/api/health",
                                   json={"passcode": passcode})
        return resp.json()

    def test_get_returns_ok_only(self):
        body = self._get()
        self.assertEqual(body, {"ok": True})  # 模型名等侦察面关闭

    def test_post_wrong_or_missing_passcode_returns_ok_only(self):
        self.assertEqual(self._post("wrong"), {"ok": True})
        self.assertEqual(self._post(""), {"ok": True})

    def test_post_correct_passcode_returns_full(self):
        body = self._post("pw-test")
        self.assertEqual(body, {"ok": True, "model": "stub-model",
                                "bot_name": "测试机", "has_key": True})

    def test_no_passcode_configured_keeps_full_response(self):
        # 本地开发态（passcode 空）：维持旧全量返回（保守兼容，批1决策注记）
        cfg = dict(_FAKE_CONFIG, passcode="")
        self.assertEqual(self._get(cfg), {"ok": True, "model": "stub-model",
                                          "bot_name": "测试机", "has_key": True})


if __name__ == "__main__":
    unittest.main()
