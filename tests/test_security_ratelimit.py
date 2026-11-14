# -*- coding: utf-8 -*-
"""C1 安全套件·限流面（2026-10-07 施工，只新建测试件不改产品码）。
C1 安全套件·CI 差集核验后应干净树绿。

覆盖：
  ① 滑窗边界：/api/chat 每 IP 20 次/300s——第 20 过、第 21 拒（429
     rate_limited + retry_after_s）；
  ② SQLite 持久化：写满后换新 _Store 实例同库文件（=进程重启语义）→仍 429
     （重启不清零）；
  ③ 登录失败锁：同 IP 5 次失败/600s 窗→第 6 次起 429 too_many_attempts，
     锁定期内对口令也 429（锁检查先于校验）；重启后锁仍在；
  ④ XFF 反向锁定：默认档（trusted_proxy_header 空=不信任何代理头）伪造
     X-Forwarded-For 不得改变限流身份——同一真 IP 带不同 XFF 连打仍合并计数；
     对照臂：显式配置 trusted_proxy_header 后该头才升格为身份源；
  ⑤ conv 三端点独立小账 conv_hits 60 次/60s——第 60 过、第 61 拒。

跑法（仓根）：
    cd <repo> && venv/bin/python -m tests.test_security_ratelimit
零网络零计费（伪 httpx 上游，惯例抄 tests/test_auth_rate.py 40-77 行）；
每测试独立临时库（server._store_inst 直注入），不碰 data/qa.db；
测试口令一律 stub 占位（纪律⑤：零密件；XFF 试验值用 RFC 5737 文档段）。"""
import contextlib
import json
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import server  # 仓根模块（tests/__init__.py 已做 sys.path 引导+QABOT_DB_PATH 隔离）

STUB_PW = "stub-passcode"          # 占位口令（纪律⑤：测试零密件）
WRONG_PW = "wrong-stub-passcode"   # 占位错口令
XFF_DOC_NET = "203.0.113."         # RFC 5737 文档段（TEST-NET-3，非真实 IP）


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
    """每测试一块全新临时库：server._store_inst 直注入 + 退出复位（不碰 data/qa.db）。

    TestClient 不进 with 上下文（不触发 lifespan 收尾关库——照
    tests/test_conversations.py 惯例，"重启"语义由手动换 _Store 同库实现）。"""

    def setUp(self):
        fd, self.db = tempfile.mkstemp(prefix="qabot-sec-rate-", suffix=".db")
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

    def _sql(self, sql, args=()):
        conn = sqlite3.connect(self.db)
        try:
            rows = conn.execute(sql, args).fetchall()
            conn.commit()
            return rows
        finally:
            conn.close()

    def _restart_store(self):
        """进程重启语义：关旧 _Store，同库文件挂新实例（持久化核验用）。"""
        st = server._store_inst
        if st is not None:
            st.close()
        server._store_inst = server._Store(self.db)

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


class T1ChatWindowBoundaryTest(_SecTestBase):
    """① 滑窗边界：第 20 过、第 21 拒。"""

    def test_boundary_20th_passes_21st_rejected(self):
        with self._ctx(_cfg()):  # 20 次/300s
            c = TestClient(server.app)
            c.post("/api/login", json={"passcode": STUB_PW})
            for i in range(20):
                r = c.post("/api/chat", json={"messages": _msgs()})
                self.assertEqual(r.status_code, 200, f"第{i + 1}问意外限流")
            r21 = c.post("/api/chat", json={"messages": _msgs()})
            self.assertEqual(r21.status_code, 429)
            self.assertEqual(r21.json()["error"], "rate_limited")
            self.assertEqual(r21.json()["retry_after_s"], 60)
        # 被拒的第 21 次不插行不续账（拒绝态不落库）
        self.assertEqual(self._sql("SELECT COUNT(*) FROM rate_hits")[0][0], 20)


class T2PersistenceTest(_SecTestBase):
    """② SQLite 持久化：重启（新 _Store 同库）不清零。"""

    def test_chat_rate_limit_survives_store_restart(self):
        with self._ctx(_cfg()):
            c = TestClient(server.app)
            c.post("/api/login", json={"passcode": STUB_PW})
            for _ in range(20):
                self.assertEqual(
                    c.post("/api/chat", json={"messages": _msgs()}).status_code,
                    200)
        self._restart_store()  # =进程重启：滑窗账在库文件里
        with self._ctx(_cfg()):
            c2 = TestClient(server.app)
            r = c2.post("/api/chat",
                        json={"messages": _msgs(), "passcode": STUB_PW})
            self.assertEqual(r.status_code, 429)
            self.assertEqual(r.json()["error"], "rate_limited")


class T3LoginFailLockTest(_SecTestBase):
    """③ 登录失败锁：5 次/600s，第 6 次起 429；对口令也拦；重启仍在。"""

    def test_sixth_attempt_locked_after_five_failures(self):
        with self._ctx(_cfg()):
            c = TestClient(server.app)
            for i in range(5):
                r = c.post("/api/login", json={"passcode": WRONG_PW})
                self.assertEqual(r.status_code, 401, f"第{i + 1}次失败应 401")
            r6 = c.post("/api/login", json={"passcode": WRONG_PW})
            self.assertEqual(r6.status_code, 429)
            self.assertEqual(r6.json()["error"], "too_many_attempts")
            self.assertTrue(0 < r6.json()["retry_after_s"] <= 600,
                            r6.json()["retry_after_s"])  # 10 分钟窗内
            r7 = c.post("/api/login", json={"passcode": STUB_PW})
            self.assertEqual(r7.status_code, 429)  # 锁检查先于口令校验
            self.assertEqual(r7.json()["error"], "too_many_attempts")

    def test_login_lock_survives_store_restart(self):
        with self._ctx(_cfg()):
            c = TestClient(server.app)
            for _ in range(5):
                c.post("/api/login", json={"passcode": WRONG_PW})
        self._restart_store()
        with self._ctx(_cfg()):
            c2 = TestClient(server.app)
            r = c2.post("/api/login", json={"passcode": STUB_PW})
            self.assertEqual(r.status_code, 429)  # 重启不清零（对口令也拦）
            self.assertEqual(r.json()["error"], "too_many_attempts")


class T4XffIdentityTest(_SecTestBase):
    """④ XFF 反向锁定：默认档伪造 X-Forwarded-For 不得改变限流身份。"""

    def test_spoofed_xff_cannot_reset_rate_identity_default(self):
        # 默认档：trusted_proxy_header 缺失=不信任何代理头。攻击者每请求换
        # 伪造 XFF（若被采信=每请求独立身份、永不触顶）——实际仍合并计数。
        with self._ctx(_cfg()):  # 无 trusted_proxy_header 键
            c = TestClient(server.app)
            c.post("/api/login", json={"passcode": STUB_PW})
            for i in range(20):
                r = c.post("/api/chat", json={"messages": _msgs()},
                           headers={"X-Forwarded-For":
                                    f"{XFF_DOC_NET}{i % 256}"})
                self.assertEqual(r.status_code, 200, f"第{i + 1}问意外限流")
            r21 = c.post("/api/chat", json={"messages": _msgs()},
                         headers={"X-Forwarded-For": f"{XFF_DOC_NET}99"})
            self.assertEqual(r21.status_code, 429)  # 合并计数：伪造无效
        # 限流身份恒=真实 socket 对端（TestClient 固定 "testclient"）
        self.assertEqual(self._sql("SELECT DISTINCT ip FROM rate_hits"),
                         [("testclient",)])

    def test_proxy_header_honored_only_when_configured(self):
        # 对照臂：显式配置 trusted_proxy_header 后，该头才升格为身份源
        # （默认关闭的安全姿态由上一用例锁定；此例证明开关确实存在且可控）。
        with self._ctx(_cfg(trusted_proxy_header="X-Forwarded-For")):
            c = TestClient(server.app)
            c.post("/api/login", json={"passcode": STUB_PW})
            for _ in range(20):
                r = c.post("/api/chat", json={"messages": _msgs()},
                           headers={"X-Forwarded-For": f"{XFF_DOC_NET}10"})
                self.assertEqual(r.status_code, 200)
            r21 = c.post("/api/chat", json={"messages": _msgs()},
                         headers={"X-Forwarded-For": f"{XFF_DOC_NET}10"})
            self.assertEqual(r21.status_code, 429)  # 同头值=同身份，触顶
            r_other = c.post("/api/chat", json={"messages": _msgs()},
                             headers={"X-Forwarded-For": f"{XFF_DOC_NET}11"})
            self.assertEqual(r_other.status_code, 200)  # 换头值=独立桶


class T5ConvRateTest(_SecTestBase):
    """⑤ conv 端点独立小账：60 次/60s——第 60 过、第 61 拒（不占 chat 预算）。"""

    def test_conv_endpoints_60_per_minute_boundary(self):
        with self._ctx(_cfg(passcode="")):  # 开放态聚焦限流面
            c = TestClient(server.app)
            for i in range(60):
                r = c.get("/api/conversations")
                self.assertEqual(r.status_code, 200, f"第{i + 1}次意外限流")
            r61 = c.get("/api/conversations")
            self.assertEqual(r61.status_code, 429)
            self.assertEqual(r61.json()["error"], "rate_limited")
            self.assertEqual(r61.json()["retry_after_s"], 60)
        with self.subTest("conv_hits 落 60 行（被拒不插行）"):
            self.assertEqual(
                self._sql("SELECT COUNT(*) FROM conv_hits")[0][0], 60)
        with self.subTest("不占 /api/chat 的 rate_hits 账"):
            self.assertEqual(
                self._sql("SELECT COUNT(*) FROM rate_hits")[0][0], 0)


if __name__ == "__main__":
    unittest.main()
