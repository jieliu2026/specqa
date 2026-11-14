# -*- coding: utf-8 -*-
"""C1 安全套件·Cookie 属性面（2026-10-07 施工，只新建测试件不改产品码）。
C1 安全套件·CI 差集核验后应干净树绿。

覆盖：
  ① qabot_session 属性锁：HttpOnly + SameSite=Lax + Path=/ + Max-Age=7d
     （604800）；登出清 cookie（Max-Age=0）；
  ② qabot_device 属性锁：HttpOnly + SameSite=Lax + Path=/ + Max-Age=365d
     （31536000）；GET / 种植、已在位不重种、conv 端点与 chat SSE 同种；
  ③ https_enabled 两态联动（构造两态断言）：false（默认档）时两 cookie 均无
     Secure，true 时均有 Secure（HTTP 直连态带 Secure 反而丢 cookie 的口径）。

跑法（仓根）：
    cd <repo> && venv/bin/python -m tests.test_security_cookies
零网络零计费（伪 httpx 上游，惯例抄 tests/test_auth_rate.py 40-77 行）；
每测试独立临时库（server._store_inst 直注入），不碰 data/qa.db；
测试口令一律 stub 占位（纪律⑤：零密件）。

注：Secure 态只断言响应头原始值（httpx cookie jar 对 http 通道下的 Secure
cookie 有存储策略，不当经 jar 断言——照 test_auth_rate 同款口径）。"""
import contextlib
import json
import os
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import server  # 仓根模块（tests/__init__.py 已做 sys.path 引导+QABOT_DB_PATH 隔离）

STUB_PW = "stub-passcode"   # 占位口令（纪律⑤：测试零密件）

SESSION_COOKIE = "qabot_session"
DEVICE_COOKIE = "qabot_device"
SESSION_MAX_AGE = 7 * 86400      # 7d=604800
DEVICE_MAX_AGE = 365 * 86400     # 365d=31536000


# ---------- 伪上游：即时流（3 delta+usage+DONE，零 sleep 控制用时时长） ----------
class _FastStream:
    status_code = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def aiter_lines(self):
        for tok in ("你", "好", "！"):
            yield "data: " + json.dumps(
                {"choices": [{"delta": {"content": tok}}]}, ensure_ascii=False)
        yield "data: " + json.dumps(
            {"usage": {"total_tokens": 9}, "choices": []})
        yield "data: [DONE]"

    async def aread(self):
        return b""


class _FastClient:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def stream(self, *a, **k):
        return _FastStream()


# ---------- 配置底座（请求时读 server.CONFIG，逐测试 patch） ----------
_BASE = {
    "model": "stub-model", "bot_name": "测试机",
    "max_history_messages": 5, "max_input_chars": 8000,
    "max_total_input_chars": 24000, "temperature": 0.7, "max_tokens": 100,
    "rate_limit_requests": 20, "rate_limit_window_seconds": 300,
}


def _cfg(**over):
    cfg = dict(_BASE, passcode=STUB_PW)
    cfg.update(over)
    return cfg


def _msgs(text="问句"):
    return [{"role": "user", "content": text}]


class _SecTestBase(unittest.TestCase):
    """每测试一块全新临时库：server._store_inst 直注入 + 退出复位（不碰 data/qa.db）。"""

    def setUp(self):
        fd, self.db = tempfile.mkstemp(prefix="qabot-sec-cookie-", suffix=".db")
        os.close(fd)
        server._store_inst = server._Store(self.db)

    def tearDown(self):
        st = server._store_inst
        server._store_inst = None
        if st is not None:
            try:
                st.close()
            except Exception:
                pass
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(self.db + suffix)
            except FileNotFoundError:
                pass

    @contextlib.contextmanager
    def _ctx(self, cfg, upstream=None):
        with contextlib.ExitStack() as stack:
            for p in (mock.patch.object(server, "CONFIG", cfg),
                      mock.patch.object(server, "API_KEY", "stub-key"),
                      mock.patch.object(server.httpx, "AsyncClient",
                                        upstream or _FastClient),
                      mock.patch.object(server, "rag_service", None)):
                stack.enter_context(p)
            yield


class T1SessionCookieTest(_SecTestBase):
    """① qabot_session 属性锁（HttpOnly/SameSite=Lax/Path=/Max-Age 7d）+登出清除。"""

    def test_session_cookie_attributes_locked_http_mode(self):
        with self._ctx(_cfg()):  # 无 https_enabled 键=默认 false 态
            c = TestClient(server.app)
            r = c.post("/api/login", json={"passcode": STUB_PW})
        self.assertEqual(r.status_code, 200)
        sc = r.headers.get("set-cookie", "")
        low = sc.lower()
        with self.subTest("cookie 名"):
            self.assertIn(f"{SESSION_COOKIE}=", sc)
        with self.subTest("HttpOnly"):
            self.assertIn("httponly", low)
        with self.subTest("SameSite=Lax"):
            self.assertIn("samesite=lax", low)
        with self.subTest("Path=/"):
            self.assertIn("path=/", low)
        with self.subTest("Max-Age=7d(604800)"):
            self.assertIn(f"max-age={SESSION_MAX_AGE}", low)
        with self.subTest("HTTP 直连态（默认）不设 Secure"):
            self.assertNotIn("secure", low)

    def test_session_cookie_secure_follows_https_flag_both_states(self):
        # 构造两态断言：https_enabled=true 有 Secure；显式 false 无 Secure
        with self._ctx(_cfg(https_enabled=True)):
            c = TestClient(server.app)
            r_on = c.post("/api/login", json={"passcode": STUB_PW})
        self.assertEqual(r_on.status_code, 200)
        self.assertIn("secure",
                      r_on.headers.get("set-cookie", "").lower())
        with self._ctx(_cfg(https_enabled=False)):
            c2 = TestClient(server.app)
            r_off = c2.post("/api/login", json={"passcode": STUB_PW})
        self.assertEqual(r_off.status_code, 200)
        self.assertNotIn("secure",
                         r_off.headers.get("set-cookie", "").lower())

    def test_logout_clears_session_cookie(self):
        with self._ctx(_cfg()):
            c = TestClient(server.app)
            c.post("/api/login", json={"passcode": STUB_PW})
            r = c.post("/api/logout")
        self.assertEqual(r.status_code, 200)
        sc = r.headers.get("set-cookie", "").lower()
        self.assertIn(SESSION_COOKIE, sc)
        self.assertIn("max-age=0", sc)  # 清 cookie（过期法）


class T2DeviceCookieTest(_SecTestBase):
    """② qabot_device 属性锁 + 种植点行为（GET /、conv 端点、chat SSE）。"""

    def test_device_cookie_attributes_locked_http_mode(self):
        with self._ctx(_cfg()):
            c = TestClient(server.app)
            r = c.get("/")  # device cookie 首要种植点
        self.assertEqual(r.status_code, 200)
        sc = r.headers.get("set-cookie", "")
        low = sc.lower()
        with self.subTest("cookie 名"):
            self.assertIn(f"{DEVICE_COOKIE}=", sc)
        with self.subTest("HttpOnly"):
            self.assertIn("httponly", low)
        with self.subTest("SameSite=Lax"):
            self.assertIn("samesite=lax", low)
        with self.subTest("Path=/"):
            self.assertIn("path=/", low)
        with self.subTest("Max-Age=365d(31536000)"):
            self.assertIn(f"max-age={DEVICE_MAX_AGE}", low)
        with self.subTest("HTTP 直连态（默认）不设 Secure"):
            self.assertNotIn("secure", low)

    def test_device_cookie_secure_follows_https_flag_both_states(self):
        # 构造两态断言：https_enabled=true 有 Secure；显式 false 无 Secure
        with self._ctx(_cfg(https_enabled=True)):
            c = TestClient(server.app)
            r_on = c.get("/")
        self.assertEqual(r_on.status_code, 200)
        self.assertIn("secure", r_on.headers.get("set-cookie", "").lower())
        with self._ctx(_cfg(https_enabled=False)):
            c2 = TestClient(server.app)
            r_off = c2.get("/")
        self.assertEqual(r_off.status_code, 200)
        self.assertNotIn("secure",
                         r_off.headers.get("set-cookie", "").lower())

    def test_device_cookie_not_replanted_when_present(self):
        # 已在位不重种：二次 GET / 响应不再带 qabot_device Set-Cookie
        with self._ctx(_cfg()):
            c = TestClient(server.app)
            r1 = c.get("/")
            self.assertIn(DEVICE_COOKIE,
                          r1.headers.get("set-cookie", "").lower())
            r2 = c.get("/")
            self.assertEqual(r2.status_code, 200)
            self.assertNotIn(DEVICE_COOKIE,
                             r2.headers.get("set-cookie", "").lower())

    def test_device_cookie_set_on_conv_endpoint_and_chat_sse(self):
        # conv 端点与 chat SSE（StreamingResponse）同样种植，属性与 GET / 一致
        # （两分支各用全新客户端=零 cookie 起步，各自验证"未带即种"）
        with self._ctx(_cfg()):
            c_conv = TestClient(server.app)
            r_conv = c_conv.request("GET", "/api/conversations",
                                    headers={"X-QA-Passcode": STUB_PW})
            self.assertEqual(r_conv.status_code, 200)
            low_conv = r_conv.headers.get("set-cookie", "").lower()
            self.assertIn(f"{DEVICE_COOKIE}=", low_conv)
            self.assertIn("httponly", low_conv)
            self.assertIn(f"max-age={DEVICE_MAX_AGE}", low_conv)
            c_chat = TestClient(server.app)
            r_chat = c_chat.post("/api/chat",
                                 json={"messages": _msgs(),
                                       "passcode": STUB_PW})
            self.assertEqual(r_chat.status_code, 200)
            low_chat = r_chat.headers.get("set-cookie", "").lower()
            self.assertIn(f"{DEVICE_COOKIE}=", low_chat)
            self.assertIn("httponly", low_chat)
            self.assertIn(f"max-age={DEVICE_MAX_AGE}", low_chat)


if __name__ == "__main__":
    unittest.main()
