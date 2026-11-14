# -*- coding: utf-8 -*-
"""一致性收敛批（2026-10-13）三件离线单测：

1. generation_seed 条件键：int 才随生成 payload 上行；缺省/bool/str/float
   不传=旧行为逐字节不变（server.py /api/chat payload 组装）。
2. embed_retry_times：缺省 0=注入桩异常一次即抛（零行为变化）；开 1 时仅
   httpx 传输类异常（超时/网络）重试一次，非传输类（HTTP 响应错语义）不重试。
3. [chat] 尾部 dev=/ua=：设备 cookie 短哈希 8 位 + UA 去空白截 60（KV 断词
   防护），既有尾键（trace=）原样在位。

全程零网络零真实 key（伪 httpx.AsyncClient / 注入 embed 桩）。"""
import asyncio
import contextlib
import io
import json
import unittest
from unittest import mock

import httpx
from fastapi.testclient import TestClient

import rag
import server  # 仓根模块（tests/__init__.py 已做 sys.path 引导）
from tests import clean_store_tests  # chat 型限流免疫


# ---------- 伪上游：正常流（3 delta+usage+DONE），捕获生成 payload ----------
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
            await asyncio.sleep(0)
        yield "data: " + json.dumps({"usage": {"total_tokens": 9}, "choices": []})
        yield "data: [DONE]"


class _CapClient:
    """伪上游 client：捕获 stream() 调用的 json= 实参（=生成 payload）。"""
    last_payload = None

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def stream(self, *a, **k):
        _CapClient.last_payload = k.get("json")
        return _OkStream()


class _MissSvc:
    """retrieve 恒 None 的桩（rag=miss 裸答路径，启动日志要读 stats）。"""
    stats = {}

    def retrieve(self, query):
        return None


_FAKE_CONFIG = {
    "model": "stub-model", "passcode": "pw-test", "bot_name": "测试机",
    "max_history_messages": 40, "max_input_chars": 8000,
    "max_total_input_chars": 24000, "temperature": 0.7, "max_tokens": 100,
    "rate_limit_requests": 20, "rate_limit_window_seconds": 300,
}


def _post_chat(cfg=None, headers=None):
    body = {"messages": [{"role": "user", "content": "问句"}], "passcode": "pw-test"}
    out = io.StringIO()
    _CapClient.last_payload = None
    with mock.patch.object(server.httpx, "AsyncClient", _CapClient), \
            mock.patch.object(server, "CONFIG", cfg or dict(_FAKE_CONFIG)), \
            mock.patch.object(server, "API_KEY", "stub-key"), \
            mock.patch.object(server, "rag_service", _MissSvc()), \
            contextlib.redirect_stdout(out):
        with TestClient(server.app) as client:
            with client.stream("POST", "/api/chat", json=body,
                               headers=headers or {}) as resp:
                assert resp.status_code == 200
                list(resp.iter_lines())
    return _CapClient.last_payload, out.getvalue()


@clean_store_tests
class GenerationSeedTest(unittest.TestCase):
    def test_seed_absent_by_default(self):
        payload, _ = _post_chat()
        self.assertNotIn("seed", payload)

    def test_seed_sent_when_int(self):
        cfg = dict(_FAKE_CONFIG)
        cfg["generation_seed"] = 42
        payload, _ = _post_chat(cfg)
        self.assertEqual(payload.get("seed"), 42)

    def test_seed_skipped_on_bad_values(self):
        for bad in (True, "42", 3.5, None):
            cfg = dict(_FAKE_CONFIG)
            cfg["generation_seed"] = bad
            payload, _ = _post_chat(cfg)
            self.assertNotIn("seed", payload, f"bad={bad!r} 不应上行")


@clean_store_tests
class ChatDeviceFieldTest(unittest.TestCase):
    def test_dev_ua_tail_fields_with_custom_ua(self):
        _, logged = _post_chat(headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) TestUA/1.0"})
        line = [ln for ln in logged.splitlines() if "[chat]" in ln][0]
        # dev=设备 cookie 短哈希前 8 位（urlsafe 字符集；TestClient 无 cookie=新造 token）
        self.assertRegex(line, r" dev=[A-Za-z0-9_-]{8} ")
        # ua=去空白（空格→下划线）截 60，防 KV 断词
        self.assertIn("ua=Mozilla/5.0_(X11;_Linux_x86_64)_TestUA/1.0", line)
        self.assertIn("trace=", line)  # 既有尾键原样在位

    def test_dev_ua_tail_fields_default_ua(self):
        _, logged = _post_chat()
        line = [ln for ln in logged.splitlines() if "[chat]" in ln][0]
        self.assertRegex(line, r" dev=[A-Za-z0-9_-]{8} ")
        self.assertIn("ua=testclient", line)  # TestClient 默认 UA


class EmbedRetryTest(unittest.TestCase):
    """RagService._embed 重试语义（注入桩直测，零网络）。"""

    @staticmethod
    def _svc(embed_fn, retry=None, logs=None):
        cfg = {"store_path": "/nonexistent-store-一致性收敛批.jsonl"}
        if retry is not None:
            cfg["embed_retry_times"] = retry
        svc = rag.RagService(embed_fn=embed_fn, log=(logs.append if logs
                                                     is not None else None) or (lambda s: None))
        svc.initialize(cfg)
        return svc

    def test_default_no_key_single_attempt(self):
        calls = []

        def flaky(q):
            calls.append(1)
            raise httpx.ConnectTimeout("stub 传输失败")

        svc = self._svc(flaky)  # 不传键=默认 0
        with self.assertRaises(httpx.ConnectTimeout):
            svc._embed("q")
        self.assertEqual(len(calls), 1)  # 旧行为：一次即抛

    def test_retry_once_on_transport_error_then_raise(self):
        calls = []

        def flaky(q):
            calls.append(1)
            raise httpx.ConnectTimeout("stub 传输失败")

        logs = []
        svc = self._svc(flaky, retry=1, logs=logs)
        with self.assertRaises(httpx.ConnectTimeout):
            svc._embed("q")
        self.assertEqual(len(calls), 2)  # 重试一次后仍失败才抛
        self.assertTrue(any("[rag-embed]" in ln and "retry=1/1" in ln
                            for ln in logs))

    def test_retry_then_success(self):
        state = {"n": 0}

        def flaky(q):
            state["n"] += 1
            if state["n"] == 1:
                raise httpx.ReadTimeout("stub 读超时")
            return [0.1, 0.2]

        svc = self._svc(flaky, retry=1)
        self.assertEqual(svc._embed("q"), [0.1, 0.2])

    def test_no_retry_on_non_transport_error(self):
        calls = []

        def boom(q):
            calls.append(1)
            raise ValueError("stub HTTP 响应错语义（防双发纪律不重试）")

        svc = self._svc(boom, retry=1)
        with self.assertRaises(ValueError):
            svc._embed("q")
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
