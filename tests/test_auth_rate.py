# -*- coding: utf-8 -*-
"""批2 服务端单测：会话+限流持久化+双轨鉴权+PBKDF2（2026-09-21，
配套 运营/优化提升-20260921/服务端会话设计稿-20260921.md §6 服务端 8 条）。

覆盖（编号对设计稿 §6）：
  ① 错口令 401、对口令 Set-Cookie 含 HttpOnly/SameSite（附 https_enabled
     开关联动 Secure 位）；
  ② cookie 有效免 body 口令、伪造 token 401（附 cookie 过 /api/health 分级、
     /api/logout 删行）；
  ③ 双轨期 body 口令仍可用、passcode_body_enabled=false 后 401 收口；
  ④ 限流持久化：写满 20 条→换新 _Store 实例同库文件（=进程重启语义）→仍 429；
  ⑤ 窗口滑出：直改库把 ts 推出窗口后放行；
  ⑥ 会话过期惰性清理：过期行命中即删（chat 路径）+ 登录路径顺手清全局过期行；
  ⑦ PBKDF2 哈希校验+盐错配失败（低迭代数跑测，生产 600k 由 hash_passcode.py 管）；
  ⑧ msgs_json 超限裁剪正确（条数=max_history_messages、单条=max_input_chars）；
  ⑨ 登录失败限速（2026-09-21 批2遗留补强件）：同 IP 10 分钟窗 5 次失败后锁
     /api/login（第 6 次起 429"尝试次数过多，请稍后再试"）；成功登录清计数；
     锁定期内对口令也 429（锁检查先于 PBKDF2，防研磨计时侧信道）；重启
     （新 _Store 同库）锁仍生效；与 /api/chat 频控（rate_hits）分表互不影响。

全程零网络零真实 key（伪 httpx 上游）；每测试独立临时库文件+独立 _Store
（server._store_inst 直注入，不碰 data/qa.db 与其他测试的限流账）。"""
import contextlib
import hashlib
import json
import os
import secrets
import sqlite3
import tempfile
import time
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import server  # 仓根模块（tests/__init__.py 已做 sys.path 引导+QABOT_DB_PATH 隔离）


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


def _hash_cfg(pwd, salt=None, iterations=100_000, **over):
    """口令 → PBKDF2 三键形态的 fake config（迭代数用 100_000=C8 下限，再低会被服务端守门回落）。"""
    salt = salt if salt is not None else secrets.token_bytes(16)
    cfg = dict(_BASE)
    cfg.update({
        "passcode": "",
        "passcode_hash": hashlib.pbkdf2_hmac(
            "sha256", pwd.encode("utf-8"), salt, iterations).hex(),
        "passcode_salt": salt.hex(),
        "pbkdf2_iterations": iterations,
    })
    cfg.update(over)
    return cfg


def _plain_cfg(pwd="pw", **over):
    cfg = dict(_BASE, passcode=pwd)
    cfg.update(over)
    return cfg


def _msgs(n=1):
    return [{"role": "user", "content": "问句%d" % i} for i in range(1, n + 1)]


def _chat_events(resp):
    """SSE 响应 → 事件列表（流必须 200 才有意义）。"""
    return [json.loads(ln[5:].strip()) for ln in resp.text.splitlines()
            if ln.startswith("data:")]


class _StoreIsolatedTest(unittest.TestCase):
    """每测试一块全新临时库：server._store_inst 直注入 + 退出复位。"""

    def setUp(self):
        fd, self.db = tempfile.mkstemp(prefix="qabot-auth-rate-", suffix=".db")
        os.close(fd)
        server._store_inst = server._Store(self.db)

    def tearDown(self):
        st = server._store_inst
        server._store_inst = None
        if st is not None:
            try:
                st.close()
            except Exception:
                pass  # lifespan 退出可能已关
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
    def _client_ctx(self, cfg):
        """统一 patch 面：CONFIG/API_KEY/伪上游/关 RAG（ExitStack 一次进出）。"""
        with contextlib.ExitStack() as stack:
            for p in (mock.patch.object(server, "CONFIG", cfg),
                      mock.patch.object(server, "API_KEY", "stub-key"),
                      mock.patch.object(server.httpx, "AsyncClient", _FastClient),
                      mock.patch.object(server, "rag_service", None)):
                stack.enter_context(p)
            yield


class T1LoginCookieTest(_StoreIsolatedTest):
    """§6 ①：错口令 401；对口令 Set-Cookie 属性四件+Secure 随 https_enabled。"""

    def test_wrong_passcode_401(self):
        cfg = _hash_cfg("right")
        for p in ("wrong", ""):
            with self._client_ctx(cfg):
                with TestClient(server.app) as c:
                    r = c.post("/api/login", json={"passcode": p})
            with self.subTest(passcode="空" if not p else "错"):
                self.assertEqual(r.status_code, 401)
                self.assertEqual(r.json(), {"error": "bad_passcode"})

    def test_correct_passcode_sets_cookie_attrs(self):
        cfg = _hash_cfg("right")
        with self._client_ctx(cfg):
            with TestClient(server.app) as c:
                r = c.post("/api/login", json={"passcode": "right"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"ok": True})
        sc = r.headers.get("set-cookie", "")
        low = sc.lower()
        with self.subTest("HttpOnly"):
            self.assertIn("httponly", low)
        with self.subTest("SameSite=Lax"):
            self.assertIn("samesite=lax", low)
        with self.subTest("Path=/"):
            self.assertIn("path=/", low)
        with self.subTest("Max-Age=7d(604800)"):
            self.assertIn("max-age=604800", low)
        with self.subTest("HTTP 直连态(默认)不设 Secure"):
            self.assertNotIn("secure", low)
        with self.subTest("token 形态:qabot_session=<urlsafe>"):
            self.assertRegex(sc, r"qabot_session=[A-Za-z0-9_\-]{40,}")

    def test_https_enabled_switches_secure_flag(self):
        cfg = _hash_cfg("right", https_enabled=True)
        with self._client_ctx(cfg):
            with TestClient(server.app) as c:
                r = c.post("/api/login", json={"passcode": "right"})
        self.assertEqual(r.status_code, 200)
        low = r.headers.get("set-cookie", "").lower()
        self.assertIn("secure", low)  # ④ HTTPS 半边的服务端开关契约


class T2CookieChatTest(_StoreIsolatedTest):
    """§6 ②：cookie 有效免 body 口令；伪造 token 401；cookie 过 health；logout 删行。"""

    def test_cookie_flow(self):
        cfg = _plain_cfg()
        with self._client_ctx(cfg):
            with TestClient(server.app) as c:
                r = c.post("/api/login", json={"passcode": "pw"})
                self.assertEqual(r.status_code, 200)
                # cookie 会话免 body 口令（客户端 jar 自动带 cookie）
                r2 = c.post("/api/chat", json={"messages": _msgs()})
                self.assertEqual(r2.status_code, 200, r2.text)
                self.assertTrue(_chat_events(r2)[-1].get("done"))
                # 有效 cookie 过 /api/health 分级 → 完整字段
                h = c.get("/api/health")
                self.assertEqual(h.json(), {"ok": True, "model": "stub-model",
                                            "bot_name": "测试机", "has_key": True})
        # 库内会话行在位（msgs_json 已落裁剪后上下文）
        rows = self._sql("SELECT COUNT(*) FROM sessions")
        self.assertEqual(rows[0][0], 1)

    def test_forged_token_401(self):
        cfg = _plain_cfg()
        with self._client_ctx(cfg):
            with TestClient(server.app) as c:
                # 伪造 token+无口令 → auth_expired（前端据此弹口令栏）
                r = c.post("/api/chat", json={"messages": _msgs()},
                           headers={"Cookie": "qabot_session=forged-tok"})
                self.assertEqual(r.status_code, 401)
                self.assertEqual(r.json(), {"error": "auth_expired"})
                # 伪造 token+错口令 → bad_passcode（回落 body 双轨校验）
                r2 = c.post("/api/chat",
                            json={"messages": _msgs(), "passcode": "bad"},
                            headers={"Cookie": "qabot_session=forged-tok"})
                self.assertEqual(r2.status_code, 401)
                self.assertEqual(r2.json(), {"error": "bad_passcode"})
                # 伪造 token 过不了 health 分级
                h = c.get("/api/health",
                          headers={"Cookie": "qabot_session=forged-tok"})
                self.assertEqual(h.json(), {"ok": True})

    def test_logout_deletes_session_row_and_cookie(self):
        cfg = _plain_cfg()
        with self._client_ctx(cfg):
            with TestClient(server.app) as c:
                c.post("/api/login", json={"passcode": "pw"})
                r = c.post("/api/logout")
                self.assertEqual(r.status_code, 200)
                low = r.headers.get("set-cookie", "").lower()
                self.assertIn("max-age=0", low)  # 清 cookie
        self.assertEqual(self._sql("SELECT COUNT(*) FROM sessions")[0][0], 0)


class T3DualTrackBodyTest(_StoreIsolatedTest):
    """§6 ③：双轨期 body 口令仍可用；passcode_body_enabled=false → 401 收口。"""

    def test_body_passcode_dual_track_and_closure(self):
        with self._client_ctx(_plain_cfg()):  # 开关缺省=双轨期
            with TestClient(server.app) as c:
                r = c.post("/api/chat",
                           json={"messages": _msgs(), "passcode": "pw"})
                self.assertEqual(r.status_code, 200)
                self.assertTrue(_chat_events(r)[-1].get("done"))
        with self._client_ctx(_plain_cfg(passcode_body_enabled=False)):
            with TestClient(server.app) as c:
                r2 = c.post("/api/chat",
                            json={"messages": _msgs(), "passcode": "pw"})
                self.assertEqual(r2.status_code, 401)
                self.assertEqual(r2.json(), {"error": "login_required"})


class T4RatePersistenceTest(_StoreIsolatedTest):
    """§6 ④：写满 20 条→新 _Store 同库文件（=重启）→仍 429。"""

    def test_rate_limit_survives_store_restart(self):
        cfg = _plain_cfg()  # 20 次/300s
        with self._client_ctx(cfg):
            with TestClient(server.app) as c:
                c.post("/api/login", json={"passcode": "pw"})
                for i in range(20):
                    r = c.post("/api/chat", json={"messages": _msgs()})
                    self.assertEqual(r.status_code, 200, f"第{i + 1}问意外限流")
                r = c.post("/api/chat", json={"messages": _msgs()})
                self.assertEqual(r.status_code, 429)
                self.assertEqual(r.json(), {"error": "rate_limited",
                                            "retry_after_s": 60})
            # "重启"：lifespan 退出已关旧 store 并置 None；换新 _Store 挂同一库文件
            server._store_inst = server._Store(self.db)
            with TestClient(server.app) as c2:
                r2 = c2.post("/api/chat",
                             json={"messages": _msgs(), "passcode": "pw"})
                self.assertEqual(r2.status_code, 429)  # 重启不清零
                self.assertEqual(r2.json()["error"], "rate_limited")


class T5RateWindowSlideTest(_StoreIsolatedTest):
    """§6 ⑤：写满 429 后，直改库把 ts 推出窗口（窗口滑出）→放行。"""

    def test_stale_hits_slide_out_of_window(self):
        cfg = _plain_cfg(rate_limit_requests=3, rate_limit_window_seconds=300)
        with self._client_ctx(cfg):
            with TestClient(server.app) as c:
                c.post("/api/login", json={"passcode": "pw"})
                for _ in range(3):
                    self.assertEqual(
                        c.post("/api/chat", json={"messages": _msgs()}).status_code, 200)
                r = c.post("/api/chat", json={"messages": _msgs()})
                self.assertEqual(r.status_code, 429)
                # 手术：全部命中行回拨到窗口外（=等价 300s 前的旧行）
                self._sql("UPDATE rate_hits SET ts = ts - 301")
                r2 = c.post("/api/chat", json={"messages": _msgs()})
                self.assertEqual(r2.status_code, 200)  # 旧 ts 滑出→放行
                # 且顺手清理已把窗口外旧行删净（语义等价旧 deque popleft）
                left = self._sql("SELECT COUNT(*) FROM rate_hits WHERE ts <= ?",
                                 (time.time() - 300,))
                self.assertEqual(left[0][0], 0)


class T6SessionExpiryTest(_StoreIsolatedTest):
    """§6 ⑥：会话过期惰性清理（chat 命中即删 + 登录路径顺手清全局过期行）。"""

    def test_expired_session_rejected_and_row_deleted(self):
        cfg = _plain_cfg()
        with self._client_ctx(cfg):
            with TestClient(server.app) as c:
                c.post("/api/login", json={"passcode": "pw"})
                # 会话行 last_seen 回拨 8 天（>7d 有效期）
                self._sql("UPDATE sessions SET last_seen = ?", (time.time() - 8 * 86400,))
                r = c.post("/api/chat", json={"messages": _msgs()})
                self.assertEqual(r.status_code, 401)
                self.assertEqual(r.json(), {"error": "auth_expired"})
        # 过期行已被 get_session 顺手删除（不残留可复活僵尸行）
        self.assertEqual(self._sql("SELECT COUNT(*) FROM sessions")[0][0], 0)

    def test_login_purges_other_expired_rows(self):
        cfg = _plain_cfg()
        # 预埋一条 8 天前的孤儿过期会话
        self._sql(
            "INSERT INTO sessions(token, created_at, last_seen, msgs_json)"
            " VALUES('ghost', ?, ?, NULL)",
            (time.time() - 9 * 86400, time.time() - 8 * 86400))
        with self._client_ctx(cfg):
            with TestClient(server.app) as c:
                r = c.post("/api/login", json={"passcode": "pw"})
                self.assertEqual(r.status_code, 200)
        # ghost 被登录路径惰性清理（新登录行 token 非确定，只断言 ghost 消失）
        self.assertEqual(self._sql(
            "SELECT COUNT(*) FROM sessions WHERE token='ghost'")[0][0], 0)
        self.assertEqual(self._sql(
            "SELECT COUNT(*) FROM sessions")[0][0], 1)  # 只剩新登录行


class T7Pbkdf2Test(_StoreIsolatedTest):
    """§6 ⑦：PBKDF2 哈希校验通过；错口令/盐错配失败；无哈希键时明文兼容。"""

    def test_hash_login_paths(self):
        right = _hash_cfg("right")
        with self._client_ctx(right):
            with TestClient(server.app) as c:
                self.assertEqual(
                    c.post("/api/login", json={"passcode": "right"}).status_code, 200)
                self.assertEqual(
                    c.post("/api/login", json={"passcode": "wrong"}).status_code, 401)
        # 盐错配：配置里放"盐 A 派生的哈希+盐 B"（真·错配——哈希不是盐 B 算的），
        # 校验必不过，且不给明文回退开后门
        salt_a = secrets.token_bytes(16)
        salt_b = secrets.token_bytes(16)
        wrong_salt = dict(_BASE)
        wrong_salt.update({
            "passcode": "",
            "passcode_hash": hashlib.pbkdf2_hmac(
                "sha256", b"right", salt_a, 1000).hex(),
            "passcode_salt": salt_b.hex(),
            "pbkdf2_iterations": 100_000,
        })
        with self._client_ctx(wrong_salt):
            with TestClient(server.app) as c:
                r = c.post("/api/login", json={"passcode": "right"})
                self.assertEqual(r.status_code, 401)
                self.assertEqual(r.json(), {"error": "bad_passcode"})
        # 哈希键在但盐残缺：按不通过处理（不落明文兼容分支）
        broken = dict(_hash_cfg("right"))
        broken["passcode_salt"] = ""
        with self._client_ctx(broken):
            with TestClient(server.app) as c:
                self.assertEqual(
                    c.post("/api/login", json={"passcode": "right"}).status_code, 401)

    def test_plaintext_compat_login(self):
        # 兼容期：无哈希三键、只有旧明文键 → 明文校验可用（启动日志有警告）
        with self._client_ctx(_plain_cfg()):
            with TestClient(server.app) as c:
                self.assertEqual(
                    c.post("/api/login", json={"passcode": "pw"}).status_code, 200)
                self.assertEqual(
                    c.post("/api/login", json={"passcode": "nope"}).status_code, 401)


class T8MsgsTrimTest(_StoreIsolatedTest):
    """§6 ⑧：msgs_json 条数裁到 max_history_messages、单条裁到 max_input_chars。"""

    def test_msgs_json_trimmed(self):
        cfg = _plain_cfg(max_history_messages=5, max_input_chars=40)
        long_txt = "长" * 60  # 超单条上限，应裁到 40
        msgs = []
        for i in range(1, 10):
            content = long_txt if i == 7 else "消息%d" % i
            msgs.append({"role": "user" if i % 2 else "assistant", "content": content})
        self.assertEqual(msgs[-1]["role"], "user")  # 末条 user（服务端校验前置）
        with self._client_ctx(cfg):
            with TestClient(server.app) as c:
                c.post("/api/login", json={"passcode": "pw"})
                r = c.post("/api/chat", json={"messages": msgs})
                self.assertEqual(r.status_code, 200)
        (blob,) = self._sql("SELECT msgs_json FROM sessions")[0]
        stored = json.loads(blob)
        with self.subTest("条数=max_history_messages(5)"):
            self.assertEqual(len(stored), 5)
        with self.subTest("保尾 5 条且末条 user"):
            self.assertEqual([m["content"] for m in stored],
                             ["消息5", "消息6", long_txt[:40], "消息8", "消息9"])
            self.assertEqual(stored[-1]["role"], "user")
        with self.subTest("单条=max_input_chars(40)"):
            self.assertEqual(len(stored[2]["content"]), 40)


class T9LoginFailRateTest(_StoreIsolatedTest):
    """⑨ 批2 遗留补强（2026-09-21）：/api/login 每 IP 失败限速。

    口径：同 IP 10 分钟滑窗 5 次失败→锁登录；第 6 次起 429（带"尝试次数
    过多，请稍后再试"提示）；被拒尝试不续锁；成功登录清计数；计数落
    login_fails 表（与 chat 频控的 rate_hits 分表，语义同滑窗：重启不清零）。"""

    def test_sixth_attempt_429_after_five_failures(self):
        """5 次错口令全 401→第 6 次 429（error/message/retry_after_s 三件齐）。"""
        with self._client_ctx(_plain_cfg()):
            with TestClient(server.app) as c:
                for i in range(5):
                    r = c.post("/api/login", json={"passcode": "bad"})
                    self.assertEqual(r.status_code, 401, f"第{i + 1}次失败应 401")
                    self.assertEqual(r.json(), {"error": "bad_passcode"})
                r6 = c.post("/api/login", json={"passcode": "bad"})
        self.assertEqual(r6.status_code, 429)
        body = r6.json()
        with self.subTest("error 码"):
            self.assertEqual(body["error"], "too_many_attempts")
        with self.subTest("提示文案"):
            self.assertEqual(body["message"], "尝试次数过多，请稍后再试")
        with self.subTest("retry_after_s 落在 10 分钟窗内"):
            self.assertTrue(0 < body["retry_after_s"] <= 600, body["retry_after_s"])
        with self.subTest("计数恰 5 行落库（被拒的第 6 次不插行不续锁）"):
            self.assertEqual(self._sql("SELECT COUNT(*) FROM login_fails")[0][0], 5)

    def test_success_clears_counter(self):
        """成功登录清计数：错→对→计数归零；再错从 0 起数（再 5 错仍全 401，第 6 错才 429）。

        注：这里先错 4 次而非 5 次——满 5 即锁且锁检查先于口令校验（③ 的防研磨
        语义），"对口令"必须在未锁态才能成功清计数；若成功未清计数，后面第 1 次
        错（第 5 次失败）后第 2 次错就会 429，判别力与字面 5+1 等价。"""
        with self._client_ctx(_plain_cfg()):
            with TestClient(server.app) as c:
                for _ in range(4):
                    self.assertEqual(
                        c.post("/api/login", json={"passcode": "bad"}).status_code, 401)
                self.assertEqual(
                    c.post("/api/login", json={"passcode": "pw"}).status_code, 200)
                self.assertEqual(
                    self._sql("SELECT COUNT(*) FROM login_fails")[0][0], 0)
                # 若计数未清，这里的第 1 次错（累计第 5 次失败）就会让第 2 次错 429
                for i in range(5):
                    self.assertEqual(
                        c.post("/api/login", json={"passcode": "bad"}).status_code,
                        401, f"清零后第{i + 1}次错应重新 401 起数")
                self.assertEqual(
                    c.post("/api/login", json={"passcode": "bad"}).status_code, 429)

    def test_locked_correct_passcode_also_429(self):
        """锁定期内对口令也 429 且不建会话行（锁检查先于 PBKDF2，防研磨计时侧信道）。"""
        with self._client_ctx(_hash_cfg("right")):
            with TestClient(server.app) as c:
                for _ in range(5):
                    self.assertEqual(
                        c.post("/api/login", json={"passcode": "bad"}).status_code, 401)
                r = c.post("/api/login", json={"passcode": "right"})
                self.assertEqual(r.status_code, 429)
                self.assertEqual(r.json()["error"], "too_many_attempts")
        self.assertEqual(
            self._sql("SELECT COUNT(*) FROM sessions")[0][0], 0)  # 没换出会话

    def test_lock_survives_store_restart(self):
        """写满 5 失败→新 _Store 同库文件（=进程重启）→对口令仍 429。"""
        with self._client_ctx(_plain_cfg()):
            with TestClient(server.app) as c:
                for _ in range(5):
                    self.assertEqual(
                        c.post("/api/login", json={"passcode": "bad"}).status_code, 401)
            # "重启"：lifespan 退出已关旧 store 并置 None；换新 _Store 挂同一库文件
            server._store_inst = server._Store(self.db)
            with TestClient(server.app) as c2:
                r = c2.post("/api/login", json={"passcode": "pw"})
                self.assertEqual(r.status_code, 429)  # 重启不清零（对口令也拦）
                self.assertEqual(r.json()["error"], "too_many_attempts")

    def test_login_rate_isolated_from_chat_rate(self):
        """登录锁与 chat 频控分表各管各账：登录锁上 chat 照常；chat 写满登录不受牵连。"""
        with self._client_ctx(_plain_cfg()):  # chat 20 次/300s
            with TestClient(server.app) as c:
                # 正向：登录锁上（5 错）后 /api/chat 照常（body 双轨口令）
                for _ in range(5):
                    self.assertEqual(
                        c.post("/api/login", json={"passcode": "bad"}).status_code, 401)
                r = c.post("/api/chat", json={"messages": _msgs(), "passcode": "pw"})
                self.assertEqual(r.status_code, 200, r.text)
                self.assertTrue(_chat_events(r)[-1].get("done"))
                # 手术清登录锁：隔开两段账，防登录锁干扰后半段断言
                self._sql("DELETE FROM login_fails")
                # 反向：chat 频控写满 20 问→第 21 问 429；登录不受牵连（对口令 200）
                for i in range(19):
                    self.assertEqual(
                        c.post("/api/chat",
                               json={"messages": _msgs(), "passcode": "pw"}).status_code,
                        200, f"第{i + 2}问意外限流")
                self.assertEqual(
                    c.post("/api/chat",
                           json={"messages": _msgs(), "passcode": "pw"}).status_code,
                    429)
                self.assertEqual(
                    c.post("/api/login", json={"passcode": "pw"}).status_code, 200)
        with self.subTest("chat 频控 20 行落 rate_hits"):
            self.assertEqual(self._sql("SELECT COUNT(*) FROM rate_hits")[0][0], 20)
        with self.subTest("登录计数已被成功登录清零（login_fails 独立账）"):
            self.assertEqual(self._sql("SELECT COUNT(*) FROM login_fails")[0][0], 0)


if __name__ == "__main__":
    unittest.main()
