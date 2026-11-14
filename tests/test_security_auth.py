# -*- coding: utf-8 -*-
"""C1 安全套件·鉴权面（2026-10-07 施工，只新建测试件不改产品码）。
C1 安全套件·CI 差集核验后应干净树绿。

覆盖：
  ① 未登录访问全端点 401 面（chat/三会话端点/import/feedback/health 分级）。
     注：本应用鉴权失败统一 401 家族三态（auth_expired/login_required/
     bad_passcode），无 403 面——401 面即全部未授权面。
  ② 伪造 qabot_session cookie 拒绝（含伪造+错口令回落 body 双轨校验）；
  ③ 过期会话拒绝（last_seen 回拨 >7d → 401 auth_expired，行顺手清理）；
  ④ 双轨：body 口令（chat/import/feedback）与 X-QA-Passcode 头（conv 端点）；
     passcode_body_enabled=false 两轨同收口（当前实际行为）；
  ⑤ G1 越权真象（accepted risk）：带合法会话+手设 qabot_device=受害设备值
     → 可列/读/删受害会话——断言当前实际行为并显式标注 accepted risk
     （device 隔离=UX 分区非授权边界，唯一授权边界=passcode）；
  ⑥ 会话固定：登录前后 session id 轮换（服务端恒发新随机 token，绝不采纳
     客户端预置 id）；登出后旧 token 即失效。

跑法（仓根）：
    cd <repo> && venv/bin/python -m tests.test_security_auth
零网络零计费（伪 httpx 上游，惯例抄 tests/test_auth_rate.py 40-77 行）；
每测试独立临时库（server._store_inst 直注入），不碰 data/qa.db；
测试口令一律 stub 占位（纪律⑤：零密件）。"""
import contextlib
import json
import os
import re
import sqlite3
import tempfile
import time
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import server  # 仓根模块（tests/__init__.py 已做 sys.path 引导+QABOT_DB_PATH 隔离）

STUB_PW = "stub-passcode"          # 占位口令（纪律⑤：测试零密件）
WRONG_PW = "wrong-stub-passcode"   # 占位错口令


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
    tests/test_conversations.py 惯例，隔离 _Store 全程在位）。"""

    def setUp(self):
        fd, self.db = tempfile.mkstemp(prefix="qabot-sec-auth-", suffix=".db")
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
        """测试侧直连库做"外科手术"与断言（WAL 多连接读写安全）。"""
        conn = sqlite3.connect(self.db)
        try:
            rows = conn.execute(sql, args).fetchall()
            conn.commit()
            return rows
        finally:
            conn.close()

    @contextlib.contextmanager
    def _ctx(self, cfg, upstream=None):
        """统一 patch 面：CONFIG/API_KEY/伪上游/关 RAG（ExitStack 一次进出）。"""
        with contextlib.ExitStack() as stack:
            for p in (mock.patch.object(server, "CONFIG", cfg),
                      mock.patch.object(server, "API_KEY", "stub-key"),
                      mock.patch.object(server.httpx, "AsyncClient",
                                        upstream or _FastClient),
                      mock.patch.object(server, "rag_service", None)):
                stack.enter_context(p)
            yield


class T1UnauthSurfaceTest(_SecTestBase):
    """① 未登录访问全端点 401 面（401 家族=本应用全部未授权面，无 403 面）。"""

    def test_unauthenticated_requests_rejected_401(self):
        c = TestClient(server.app)
        with self._ctx(_cfg()):
            cases = [
                ("post", "/api/chat", {"messages": _msgs()}),
                ("get", "/api/conversations", None),
                ("get", "/api/conversations/1/messages", None),
                ("delete", "/api/conversations/1", None),
                ("patch", "/api/conversations/1", {"title": "t"}),
                ("post", "/api/conversations/import",
                 {"messages": [{"role": "user", "content": "c"}]}),
                ("post", "/api/feedback", {"rating": "up"}),
            ]
            for method, url, body in cases:
                r = c.request(method.upper(), url, json=body)
                with self.subTest(f"{method.upper()} {url}"):
                    self.assertEqual(r.status_code, 401)
                    self.assertEqual(r.json()["error"], "auth_expired")

    def test_health_unauthenticated_leaks_nothing(self):
        # 分级健康面：未过级 GET 只回 {"ok":true}，不泄露 model/bot_name/has_key
        c = TestClient(server.app)
        with self._ctx(_cfg()):
            r = c.get("/api/health")
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json(), {"ok": True})


class T2ForgedCookieTest(_SecTestBase):
    """② 伪造 qabot_session cookie 拒绝（token 随机不可猜，不存在的行=无效）。"""

    def test_forged_session_cookie_rejected(self):
        c = TestClient(server.app)
        hdr = {"Cookie": "qabot_session=forged-token-abc"}
        with self._ctx(_cfg()):
            with self.subTest("chat：伪造 token 无口令 → auth_expired"):
                r = c.post("/api/chat", json={"messages": _msgs()}, headers=hdr)
                self.assertEqual(r.status_code, 401)
                self.assertEqual(r.json(), {"error": "auth_expired"})
            with self.subTest("chat：伪造 token+错口令 → bad_passcode（回落双轨）"):
                r2 = c.post("/api/chat",
                            json={"messages": _msgs(), "passcode": WRONG_PW},
                            headers=hdr)
                self.assertEqual(r2.status_code, 401)
                self.assertEqual(r2.json(), {"error": "bad_passcode"})
            with self.subTest("conv 列表：伪造 token → 401"):
                r3 = c.get("/api/conversations", headers=hdr)
                self.assertEqual(r3.status_code, 401)
                self.assertEqual(r3.json()["error"], "auth_expired")
            with self.subTest("conv 消息：伪造 token → 401"):
                r4 = c.get("/api/conversations/1/messages", headers=hdr)
                self.assertEqual(r4.status_code, 401)


class T3ExpiredSessionTest(_SecTestBase):
    """③ 过期会话拒绝（>7d 惰性过期：命中即删，不残留可复活僵尸行）。"""

    def test_expired_session_rejected_and_purged(self):
        with self._ctx(_cfg()):
            c = TestClient(server.app)
            c.post("/api/login", json={"passcode": STUB_PW})
            # 手术：last_seen 回拨 8 天（>7d 有效期）
            self._sql("UPDATE sessions SET last_seen = ?",
                      (time.time() - 8 * 86400,))
            r = c.post("/api/chat", json={"messages": _msgs()})
            self.assertEqual(r.status_code, 401)
            self.assertEqual(r.json(), {"error": "auth_expired"})
            r2 = c.get("/api/conversations")
            self.assertEqual(r2.status_code, 401)
            self.assertEqual(r2.json()["error"], "auth_expired")
        # 过期行被 get_session 顺手删除
        self.assertEqual(self._sql("SELECT COUNT(*) FROM sessions")[0][0], 0)


class T4DualTrackTest(_SecTestBase):
    """④ 双轨鉴权：cookie 会话外，body 口令（chat 家族）与 X-QA-Passcode 头（conv 家族）。"""

    def test_body_passcode_track_on_chat(self):
        c = TestClient(server.app)
        with self._ctx(_cfg()):
            r = c.post("/api/chat",
                       json={"messages": _msgs(), "passcode": STUB_PW})
            self.assertEqual(r.status_code, 200)
            r2 = c.post("/api/chat",
                        json={"messages": _msgs(), "passcode": WRONG_PW})
            self.assertEqual(r2.status_code, 401)
            self.assertEqual(r2.json(), {"error": "bad_passcode"})

    def test_header_passcode_track_on_conv_endpoints(self):
        c = TestClient(server.app)
        with self._ctx(_cfg()):
            ok = {"X-QA-Passcode": STUB_PW}
            r = c.get("/api/conversations", headers=ok)
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json(), {"ok": True, "conversations": []})
            r2 = c.get("/api/conversations/1/messages", headers=ok)
            self.assertEqual(r2.status_code, 404)  # 过鉴权后才落 id 域校验
            r3 = c.delete("/api/conversations/1", headers=ok)
            self.assertEqual(r3.status_code, 404)
            bad = {"X-QA-Passcode": WRONG_PW}
            r4 = c.get("/api/conversations", headers=bad)
            self.assertEqual(r4.status_code, 401)
            self.assertEqual(r4.json(), {"error": "bad_passcode"})

    def test_body_passcode_track_on_import_and_feedback(self):
        c = TestClient(server.app)
        with self._ctx(_cfg()):
            r = c.post("/api/conversations/import",
                       json={"messages": [{"role": "user", "content": "存档"}],
                             "passcode": STUB_PW})
            self.assertEqual(r.status_code, 200)
            self.assertTrue(r.json()["ok"])
            r2 = c.post("/api/feedback",
                        json={"rating": "down", "passcode": STUB_PW})
            self.assertEqual(r2.status_code, 200)
            self.assertEqual(r2.json(), {"ok": True})

    def test_passcode_body_enabled_false_closes_both_tracks(self):
        # 当前实际行为：收口开关管 body/头两轨（_conv_auth 同读该键）
        c = TestClient(server.app)
        with self._ctx(_cfg(passcode_body_enabled=False)):
            r = c.post("/api/chat",
                       json={"messages": _msgs(), "passcode": STUB_PW})
            self.assertEqual(r.status_code, 401)
            self.assertEqual(r.json(), {"error": "login_required"})
            r2 = c.get("/api/conversations",
                       headers={"X-QA-Passcode": STUB_PW})
            self.assertEqual(r2.status_code, 401)
            self.assertEqual(r2.json(), {"error": "login_required"})


class T5G1DeviceBoundaryTest(_SecTestBase):
    """⑤ G1 越权真象：device cookie 不与会话绑定=UX 分区非授权边界（详见用例注）。"""

    def _victim_conv(self, victim):
        """受害者侧：种 device、登录、导入一条会话（零 LLM）→ (conv_id, device)。"""
        victim.get("/")
        r_login = victim.post("/api/login", json={"passcode": STUB_PW})
        self.assertEqual(r_login.status_code, 200)
        r_imp = victim.post(
            "/api/conversations/import",
            json={"messages": [{"role": "user", "content": "受害者的私有问题"}]})
        self.assertEqual(r_imp.status_code, 200)
        return r_imp.json()["id"], victim.cookies.get("qabot_device")

    def test_g1_forged_device_cookie_cross_device_access__accepted_risk(self):
        # ACCEPTED RISK（G1·2026-10-07 登记）：qabot_device 隔离=UX 分区非授权
        # 边界，唯一授权边界=passcode；持合法会话者手设 qabot_device=受害设备
        # 值即可列/读/删受害会话——本用例断言并锁定当前实际行为（现状存档，
        # 非合规背书）；若未来将 device 升格为授权边界，本用例应翻红提醒重审。
        with self._ctx(_cfg()):
            victim = TestClient(server.app)
            conv_id, victim_dev = self._victim_conv(victim)
            # 攻击者：持合法会话（=知道口令，单一授权边界）+手设受害 device 值
            attacker = TestClient(server.app)
            r_login = attacker.post("/api/login", json={"passcode": STUB_PW})
            self.assertEqual(r_login.status_code, 200)
            attacker.cookies.set("qabot_device", victim_dev)
            with self.subTest("越权列：受害会话可见"):
                lst = attacker.get("/api/conversations")
                self.assertEqual(lst.status_code, 200)
                ids = [row["id"] for row in lst.json()["conversations"]]
                self.assertIn(conv_id, ids)
            with self.subTest("越权读：受害消息全文可读"):
                msgs = attacker.get(f"/api/conversations/{conv_id}/messages")
                self.assertEqual(msgs.status_code, 200)
                self.assertEqual(msgs.json()["messages"][0]["content"],
                                 "受害者的私有问题")
            with self.subTest("越权删：受害会话可删"):
                dele = attacker.delete(f"/api/conversations/{conv_id}")
                self.assertEqual(dele.status_code, 200)
                self.assertEqual(dele.json(), {"ok": True})

    def test_g1_control_own_device_stays_isolated(self):
        # 对照臂：不持受害 device 值的登录用户看不到受害会话——隔离只认
        # device cookie 值本身（知道 passcode 但不知受害 device 值则隔离在）。
        with self._ctx(_cfg()):
            victim = TestClient(server.app)
            conv_id, _ = self._victim_conv(victim)
            other = TestClient(server.app)
            other.post("/api/login", json={"passcode": STUB_PW})
            lst = other.get("/api/conversations")
            ids = [row["id"] for row in lst.json()["conversations"]]
            self.assertNotIn(conv_id, ids)
            r404 = other.get(f"/api/conversations/{conv_id}/messages")
            self.assertEqual(r404.status_code, 404)
            self.assertEqual(r404.json(), {"error": "not_found"})


class T6SessionRotationTest(_SecTestBase):
    """⑥ 会话固定：登录前后 session id 轮换；登出即失效。"""

    def test_session_id_rotates_on_login_no_fixation(self):
        def _tok(resp):
            m = re.search(r"qabot_session=([^;]+)",
                          resp.headers.get("set-cookie", ""))
            self.assertIsNotNone(m, "登录响应缺 qabot_session Set-Cookie")
            return m.group(1)

        with self._ctx(_cfg()):
            c = TestClient(server.app)
            # 攻击者预置固定 id（会话固定攻击的经典前摇）
            c.cookies.set("qabot_session", "attacker-fixed-session-id")
            r1 = c.post("/api/login", json={"passcode": STUB_PW})
            self.assertEqual(r1.status_code, 200)
            tok1 = _tok(r1)
            self.assertNotEqual(tok1, "attacker-fixed-session-id")
            self.assertRegex(tok1, r"^[A-Za-z0-9_\-]{40,}$")  # 服务端随机 urlsafe
            r2 = c.post("/api/login", json={"passcode": STUB_PW})  # 重复登录
            tok2 = _tok(r2)
            self.assertNotEqual(tok1, tok2)  # 每次登录都轮换新 token
        rows = self._sql("SELECT token FROM sessions")
        self.assertEqual(len(rows), 2)  # 两行均为服务端新发
        self.assertNotIn(("attacker-fixed-session-id",), rows)
        for (t,) in rows:
            self.assertRegex(t, r"^[A-Za-z0-9_\-]{40,}$")

    def test_logout_invalidates_session_token(self):
        with self._ctx(_cfg()):
            c = TestClient(server.app)
            r_login = c.post("/api/login", json={"passcode": STUB_PW})
            m = re.search(r"qabot_session=([^;]+)",
                          r_login.headers.get("set-cookie", ""))
            self.assertIsNotNone(m)
            tok = m.group(1)
            r = c.post("/api/logout")
            self.assertEqual(r.status_code, 200)
            # 旧 token 手动回放 → 401（行已删）
            r2 = c.post("/api/chat", json={"messages": _msgs()},
                        headers={"Cookie": f"qabot_session={tok}"})
            self.assertEqual(r2.status_code, 401)
            self.assertEqual(r2.json(), {"error": "auth_expired"})


if __name__ == "__main__":
    unittest.main()
