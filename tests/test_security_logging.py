# -*- coding: utf-8 -*-
"""C1 安全套件·日志与脱敏面（2026-10-07 施工，只新建测试件不改产品码）。
C1 安全套件·CI 差集核验后应干净树绿。

覆盖：
  ① 登录失败留可检索日志行（[login] ok=0）——含事件类型、不含口令实值；
  ② 限流命中（登录锁 429）留可检索行（[login] ok=0 locked retry_after=）；
     注记（当前实际行为）：chat/conv 每次命中 429 无逐行 journal（响应码即
     观测面），全应用唯一的限流命中日志行=登录锁 locked 行，本件以之为代表
     并负控断言 chat 429 路径零口令泄露；
  ③ [chat] 成功行含事件面字段（auth= 等）、绝不进口令实值；
  ④ _DemoteScanNoise 白名单负控：只降级白名单精确命中的扫描噪声行，
     安全类 WARNING（含近形变体）一律原样放行不降级；过滤器挂载在位；
  ⑤ 错误响应与日志脱敏负控：上游异常 detail 只带异常类型名（不带内部
     细节），401 响应体绝不回显口令。

跑法（仓根）：
    cd <repo> && venv/bin/python -m tests.test_security_logging
零网络零计费（伪 httpx 上游，惯例抄 tests/test_auth_rate.py 40-77 行）；
每测试独立临时库（server._store_inst 直注入），不碰 data/qa.db；
测试口令一律 stub 占位（纪律⑤：零密件）。日志捕获=进程内 stdout 重定向
（journal 全走 print(flush=True)，TestClient 同进程请求，捕获面完整）。"""
import contextlib
import io
import json
import logging
import os
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import server  # 仓根模块（tests/__init__.py 已做 sys.path 引导+QABOT_DB_PATH 隔离）

STUB_PW = "stub-passcode"          # 占位口令（纪律⑤：测试零密件）
WRONG_PW = "wrong-stub-passcode"   # 占位错口令
SECRET_DETAIL = "supposedly-secret-internal-detail-stub"  # 伪内部细节探针


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


class _BoomClient:
    """⑤ 专用：上游抛带"内部细节"的异常（探针=SECRET_DETAIL）。"""

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def stream(self, *a, **k):
        raise ValueError(SECRET_DETAIL)


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
        fd, self.db = tempfile.mkstemp(prefix="qabot-sec-log-", suffix=".db")
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

    def _run_captured(self, fn):
        """在 stdout 捕获窗内执行 fn → (返回值, 捕获文本)。"""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            out = fn()
        return out, buf.getvalue()


class T1AuthJournalTest(_SecTestBase):
    """①②③ 登录失败/锁定（限流命中）/chat 行：可检索、零口令。"""

    def test_login_failure_line_searchable_without_passcode(self):
        with self._ctx(_cfg()):
            c = TestClient(server.app)
            r, out = self._run_captured(
                lambda: c.post("/api/login", json={"passcode": WRONG_PW}))
        self.assertEqual(r.status_code, 401)
        self.assertIn("[login]", out)       # 事件类型可检索
        self.assertIn("ok=0", out)          # 失败态标记
        self.assertNotIn(WRONG_PW, out)     # 口令实值绝不入日志
        self.assertNotIn(STUB_PW, out)

    def test_login_lock_line_searchable_without_passcode(self):
        # 限流命中（登录锁 429）的可检索行：ok=0 locked retry_after=
        with self._ctx(_cfg()):
            c = TestClient(server.app)

            def _burst():
                for _ in range(5):
                    c.post("/api/login", json={"passcode": WRONG_PW})
                return c.post("/api/login", json={"passcode": STUB_PW})

            r, out = self._run_captured(_burst)
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r.json()["error"], "too_many_attempts")
        self.assertIn("locked", out)              # 锁定事件可检索
        self.assertIn("retry_after=", out)        # 剩余秒数字段在
        self.assertNotIn(STUB_PW, out)            # 对口令也不入日志
        self.assertNotIn(WRONG_PW, out)

    def test_chat_journal_line_searchable_no_credentials(self):
        # [chat] 成功行含事件面字段（auth= 等）；chat 429（限流命中）当前
        # 实际行为=不落 [chat] 行（响应码即观测面，见件头注记）且零口令泄露。
        with self._ctx(_cfg(rate_limit_requests=1,
                            rate_limit_window_seconds=300)):
            c = TestClient(server.app)
            c.post("/api/login", json={"passcode": STUB_PW})

            def _two():
                r1 = c.post("/api/chat", json={"messages": _msgs()})
                r2 = c.post("/api/chat",
                            json={"messages": _msgs(), "passcode": STUB_PW})
                return r1, r2

            (r1, r2), out = self._run_captured(_two)
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 429)  # 第二问命中限流
        self.assertIn("[chat]", out)
        self.assertIn("auth=cookie", out)
        self.assertNotIn(STUB_PW, out)
        self.assertNotIn(WRONG_PW, out)
        self.assertEqual(out.count("[chat]"), 1)  # 被拒请求不打 [chat] 行


class T2ScanNoiseFilterTest(_SecTestBase):
    """④ _DemoteScanNoise 白名单负控：安全类 WARNING 不被降级。"""

    @staticmethod
    def _record(msg, level=logging.WARNING):
        return logging.LogRecord(
            "uvicorn.error", level, __file__, 1, msg, None, None)

    def test_filter_attached_and_demotes_only_whitelisted_noise(self):
        logger = logging.getLogger("uvicorn.error")
        filters = [f for f in logger.filters
                   if isinstance(f, server._DemoteScanNoise)]
        self.assertEqual(len(filters), 1)  # 过滤器挂载在位（单例）
        f = filters[0]
        # 正控：白名单噪声 WARNING→INFO（扫描噪声降级在效）
        rec = self._record("Invalid HTTP request received.")
        self.assertTrue(f.filter(rec))
        self.assertEqual(rec.levelno, logging.INFO)
        # 负控：其他 WARNING（安全事件行/近形变体）原样放行不降级
        for msg in ("[login] ip=example-host ok=0",
                    "SecurityEvent: authentication failure",
                    "鉴权失败安全事件", "Invalid HTTP request received.X",
                    ""):
            rec2 = self._record(msg)
            self.assertTrue(f.filter(rec2))
            self.assertEqual(rec2.levelno, logging.WARNING, repr(msg))

    def test_filter_exact_match_only(self):
        # 白名单是精确全文匹配：前缀同形/大小写变体/带尾随内容一律不降级
        f = server._DemoteScanNoise()
        for msg in ("Invalid HTTP request received. ",
                    "invalid http request received.",
                    "Invalid HTTP request received!\nextra"):
            rec = self._record(msg)
            f.filter(rec)
            self.assertEqual(rec.levelno, logging.WARNING, repr(msg))


class T3ErrorSanitizeTest(_SecTestBase):
    """⑤ 错误响应与日志脱敏负控。"""

    def test_upstream_error_detail_type_name_only(self):
        # 伪上游抛带"内部细节"的异常 → SSE 错误事件只带异常类型名
        c = TestClient(server.app)
        with self._ctx(_cfg(), upstream=_BoomClient):
            r_login = c.post("/api/login", json={"passcode": STUB_PW})
            self.assertEqual(r_login.status_code, 200)
            r, out = self._run_captured(
                lambda: c.post("/api/chat", json={"messages": _msgs()}))
        self.assertEqual(r.status_code, 200)  # SSE 流内错误事件
        self.assertIn("upstream_error", r.text)
        self.assertIn("ValueError", r.text)          # 只带异常类型名
        self.assertNotIn(SECRET_DETAIL, r.text)      # 内部细节不入响应
        self.assertNotIn(SECRET_DETAIL, out)         # 也不入日志
        self.assertNotIn("stub-key", r.text.lower())  # key 不入响应
        self.assertNotIn("stub-key", out.lower())     # key 不入日志

    def test_401_body_never_echoes_passcode(self):
        c = TestClient(server.app)
        with self._ctx(_cfg()):
            r = c.post("/api/chat",
                       json={"messages": _msgs(), "passcode": WRONG_PW})
            r2 = c.request("GET", "/api/conversations",
                           headers={"X-QA-Passcode": WRONG_PW})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r2.status_code, 401)
        for resp in (r, r2):
            self.assertNotIn(WRONG_PW, resp.text)  # 响应体不回显口令
            self.assertNotIn(STUB_PW, resp.text)


if __name__ == "__main__":
    unittest.main()
