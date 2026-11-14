# -*- coding: utf-8 -*-
"""批次D 多会话+跨设备历史同步·后端面单测（2026-10-03，零网络零 LLM/embedding，
伪 httpx 上游同 test_auth_rate 形态；每测试独立临时库，不碰 data/qa.db）。

覆盖（编号对施工单第 5 条）：
  ① device cookie 种植：GET / Set-Cookie 在（HttpOnly/SameSite=Lax/Max-Age 365d/
     https_enabled 联动 Secure），二次携带有则不重种；/api/chat 的 SSE 响应与
     三会话端点同样种植；
  ② 未过级三端点 401（auth_expired/bad_passcode 对齐 /api/chat 形态；口令可走
     X-QA-Passcode 头）；
  ③ 过级建会话链：chat 缺省头自动建新会话（响应头 X-QA-Conv-Id、标题=首条
     user 前 24 字符、user+assistant 双落库）→ 显式带 id 续写 → 非法头换新；
     _conversation_writeback 纯函数面直测（缺省/非法/他 device 三态）；
  ④ 列表排序（updated_at desc）与 50 帽 + last_role；
  ⑤ 归属隔离：device B 拿不到 A 的会话（messages/delete 404、列表互不可见）；
  ⑥ 删除后列表与消息均 404，库内行清干净；
  ⑦ sources_json 往返（hit 轮 sources 落库 → 恢复端点解析还原；坏档给 null）；
  ⑧ conversations_enabled=false：三端点全 404、chat 双写跳过、device cookie 仍种；
  ⑨ 惰性清理不误删新会话（90 天线+messages 5 万行数帽，登录路径触发）；
  ⑩ 三端点独立限速 conv_hits（超限 429，不占 chat 的 rate_hits 账）。

TestClient 不进 with 上下文=不触发 lifespan 收尾关库（隔离 _Store 全程在位，
多设备双客户端场景无需逐段重注入；对照 test_auth_rate T4 需重启时才重注入的
反向用法）。"""
import asyncio
import contextlib
import json
import os
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


SOURCES = [{"doc_id": "TS 36.331", "version": "V17", "locator": "§5.2.2",
            "score": 0.9, "quote": "T310 缺省值 1000 ms"}]
EVIDENCE = "以下为检索到的语料片段……\n\n[出处1] T310 缺省值 1000 ms"


class _HitSvc:
    """retrieve 恒 hit 的桩（⑦ sources 往返用）。"""
    stats = {}

    def retrieve(self, query, route_res=None, history=None):
        return (EVIDENCE, SOURCES)


# ---------- 配置底座（请求时读 server.CONFIG，逐测试 patch） ----------
_BASE = {
    "model": "stub-model", "bot_name": "测试机",
    "max_history_messages": 5, "max_input_chars": 8000,
    "max_total_input_chars": 24000, "temperature": 0.7, "max_tokens": 100,
    "rate_limit_requests": 20, "rate_limit_window_seconds": 300,
}


def _cfg(**over):
    """缺省=开放态（无口令）；passcode="pw" 即口令态。"""
    cfg = dict(_BASE)
    cfg.update(over)
    return cfg


def _msgs(text="问句"):
    return [{"role": "user", "content": text}]


def _chat_events(resp):
    """SSE 响应 → 事件列表（流必须 200 才有意义）。"""
    return [json.loads(ln[5:].strip()) for ln in resp.text.splitlines()
            if ln.startswith("data:")]


class _ConvTestBase(unittest.TestCase):
    """每测试一块全新临时库：server._store_inst 直注入 + 退出复位。"""

    def setUp(self):
        fd, self.db = tempfile.mkstemp(prefix="qabot-conv-", suffix=".db")
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
    def _ctx(self, cfg=None, svc=None):
        """统一 patch 面：CONFIG/API_KEY/伪上游/rag 桩（ExitStack 一次进出）。"""
        with contextlib.ExitStack() as stack:
            for p in (mock.patch.object(server, "CONFIG", cfg if cfg is not None else _cfg()),
                      mock.patch.object(server, "API_KEY", "stub-key"),
                      mock.patch.object(server.httpx, "AsyncClient", _FastClient),
                      mock.patch.object(server, "rag_service", svc)):
                stack.enter_context(p)
            yield

    def _client(self):
        """不进 with：不触发 lifespan（避免收尾把隔离 _Store 关掉置 None）。"""
        return TestClient(server.app)

    def _chat(self, c, text="问句", headers=None):
        r = c.post("/api/chat", json={"messages": _msgs(text)}, headers=headers or {})
        self.assertEqual(r.status_code, 200, r.text)
        return r


class T1DeviceCookieTest(_ConvTestBase):
    """① device cookie 种植：GET / 首要种植点；携带有则不重种；SSE/三端点同种。"""

    def test_get_index_plants_and_no_replant(self):
        with self._ctx():
            c = self._client()
            r = c.get("/")
            self.assertEqual(r.status_code, 200)
            sc = r.headers.get("set-cookie", "")
            low = sc.lower()
            with self.subTest("qabot_device 在"):
                self.assertIn("qabot_device=", sc)
            with self.subTest("HttpOnly/SameSite=Lax/Path=/"):
                self.assertIn("httponly", low)
                self.assertIn("samesite=lax", low)
                self.assertIn("path=/", low)
            with self.subTest("Max-Age=365d(31536000)"):
                self.assertIn("max-age=31536000", low)
            with self.subTest("HTTP 直连态(默认)不设 Secure"):
                self.assertNotIn("secure", low)
            with self.subTest("token 形态:urlsafe"):
                self.assertRegex(sc, r"qabot_device=[A-Za-z0-9_\-]{20,}")
            # 二次携带有则不重种（jar 自动带 cookie）
            r2 = c.get("/")
            self.assertEqual(r2.status_code, 200)
            self.assertNotIn("qabot_device", r2.headers.get("set-cookie", ""))

    def test_https_enabled_switches_secure_flag(self):
        with self._ctx(_cfg(https_enabled=True)):
            c = self._client()
            r = c.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("secure", r.headers.get("set-cookie", "").lower())

    def test_chat_sse_response_plants_device_cookie(self):
        with self._ctx(_cfg(passcode="pw")):
            c = self._client()
            c.post("/api/login", json={"passcode": "pw"})  # login 非种植点
            r = self._chat(c)  # SSE 的 StreamingResponse 上补种
        self.assertIn("qabot_device=", r.headers.get("set-cookie", ""))

    def test_conversations_endpoint_plants_device_cookie(self):
        with self._ctx():  # 开放态免鉴权，专看种植
            c = self._client()
            r = c.get("/api/conversations")
            self.assertEqual(r.status_code, 200)
            self.assertIn("qabot_device=", r.headers.get("set-cookie", ""))
            # 种下后同一客户端再取：cookie 在位，不重种
            r2 = c.get("/api/conversations")
            self.assertNotIn("qabot_device", r2.headers.get("set-cookie", ""))


class T2AuthGateTest(_ConvTestBase):
    """② 未过级三端点 401（形态对齐 /api/chat）；口令可走 X-QA-Passcode 头。"""

    def test_three_endpoints_401_without_credentials(self):
        with self._ctx(_cfg(passcode="pw")):
            c = self._client()
            for method, path in (("get", "/api/conversations"),
                                 ("get", "/api/conversations/1/messages"),
                                 ("delete", "/api/conversations/1")):
                r = getattr(c, method)(path)
                with self.subTest(path=path):
                    self.assertEqual(r.status_code, 401)
                    self.assertEqual(r.json(), {"error": "auth_expired"})

    def test_wrong_passcode_401_and_header_ok(self):
        with self._ctx(_cfg(passcode="pw")):
            c = self._client()
            r = c.get("/api/conversations",
                      headers={"X-QA-Passcode": "bad"})
            self.assertEqual(r.status_code, 401)
            self.assertEqual(r.json(), {"error": "bad_passcode"})
            # 对口令（头）→ 200（GET 无 body 的口令通道）
            r2 = c.get("/api/conversations", headers={"X-QA-Passcode": "pw"})
            self.assertEqual(r2.status_code, 200)
            self.assertEqual(r2.json(), {"ok": True, "conversations": []})

    def test_session_cookie_passes(self):
        with self._ctx(_cfg(passcode="pw")):
            c = self._client()
            c.post("/api/login", json={"passcode": "pw"})
            r = c.get("/api/conversations")
            self.assertEqual(r.status_code, 200)
            self.assertTrue(r.json()["ok"])


class T3ChatChainTest(_ConvTestBase):
    """③ 建会话链：缺省自动建新（头回传+标题 24 字符+双落库）→ 续写 → 非法头换新。"""

    LONG_Q = "这是一个超过二十四字符的长问题用来验证会话标题截断口径是否正确"

    def test_auto_create_then_continue(self):
        with self._ctx(_cfg(passcode="pw")):
            c = self._client()
            c.post("/api/login", json={"passcode": "pw"})
            r1 = self._chat(c, self.LONG_Q)
            cid = r1.headers.get("x-qa-conv-id", "")
            self.assertTrue(cid.isdigit(), f"X-QA-Conv-Id 应为整数 id：{cid!r}")
            self.assertTrue(_chat_events(r1)[-1].get("done"))
        with self.subTest("标题=首条 user 前 24 字符"):
            rows = self._sql("SELECT title FROM conversations")
            self.assertEqual(rows[0][0], self.LONG_Q[:24])
        with self.subTest("user+assistant 双落库"):
            msgs = self._sql(
                "SELECT role, content, sources_json FROM messages ORDER BY id")
            self.assertEqual([m[0] for m in msgs], ["user", "assistant"])
            self.assertEqual(msgs[0][1], self.LONG_Q)
            self.assertEqual(msgs[1][1], "你好！")  # 3 delta 拼接
            self.assertIsNone(msgs[1][2])  # rag off 轮 sources_json 空
        with self.subTest("显式带 id 续写=同一会话"):
            with self._ctx(_cfg(passcode="pw")):
                r2 = self._chat(c, "追问", headers={"X-QA-Conv-Id": cid})
                self.assertEqual(r2.headers.get("x-qa-conv-id"), cid)
            self.assertEqual(self._sql("SELECT COUNT(*) FROM conversations")[0][0], 1)
            self.assertEqual(self._sql("SELECT COUNT(*) FROM messages")[0][0], 4)
        with self.subTest("非法头（非 int）→ 自动换新会话"):
            with self._ctx(_cfg(passcode="pw")):
                r3 = self._chat(c, "另起", headers={"X-QA-Conv-Id": "abc"})
                cid3 = r3.headers.get("x-qa-conv-id")
            self.assertNotEqual(cid3, cid)
            self.assertTrue(cid3.isdigit())
            self.assertEqual(self._sql("SELECT COUNT(*) FROM conversations")[0][0], 2)

    def test_writeback_header_semantics(self):
        """_conversation_writeback 纯函数面：缺省/续写/非法/他 device 四态。"""
        store = server._store_inst
        cid = asyncio.run(server._conversation_writeback(store, "devA", None, "第一问"))
        self.assertEqual(
            [m[1] for m in store.get_messages(cid, "devA")], ["第一问"])
        # 续写：同 device 同头 → 同一会话
        cid2 = asyncio.run(server._conversation_writeback(store, "devA", str(cid), "第二问"))
        self.assertEqual(cid2, cid)
        self.assertEqual(
            [m[1] for m in store.get_messages(cid, "devA")], ["第一问", "第二问"])
        # 非法头 → 新建
        cid3 = asyncio.run(server._conversation_writeback(store, "devA", "abc", "第三问"))
        self.assertNotEqual(cid3, cid)
        # 他 device 拿 A 的会话 id → 静默换新（归属隔离，不 404 不借用）
        cid4 = asyncio.run(server._conversation_writeback(store, "devB", str(cid), "冒用"))
        self.assertNotEqual(cid4, cid)
        self.assertEqual([m[1] for m in store.get_messages(cid4, "devB")], ["冒用"])
        self.assertEqual(len(store.get_messages(cid, "devA")), 2)  # A 侧无污染


class T4ListOrderCapTest(_ConvTestBase):
    """④ 列表排序（updated_at desc）与 50 帽 + last_role。"""

    def test_order_and_cap_and_last_role(self):
        store = server._store_inst
        for i in range(55):
            store.create_conversation("devA", "标题%d" % i)
        # 最新的第 55 号会话追加两条消息 → last_role=assistant；隔一个验 user 态
        store.append_message(55, "user", "问", None)
        store.append_message(55, "assistant", "答", None)
        store.append_message(54, "user", "只问未答", None)
        # 排序确定性：直改库把 updated_at 设为严格递增（insert 序），消除同毫秒平局
        self._sql("UPDATE conversations SET updated_at = 1000000 + id")
        rows = store.get_conversations("devA")
        with self.subTest("50 帽"):
            self.assertEqual(len(rows), 50)
        with self.subTest("updated_at desc（最新在前）"):
            self.assertEqual([r["id"] for r in rows[:3]], [55, 54, 53])
            self.assertEqual(rows[-1]["id"], 6)  # 1-5 被帽截掉
        with self.subTest("标题与 last_role"):
            self.assertEqual(rows[0]["title"], "标题54")
            self.assertEqual(rows[0]["last_role"], "assistant")
            self.assertEqual(rows[1]["last_role"], "user")
            self.assertIsNone(rows[2]["last_role"])  # 空会话
        with self.subTest("device 隔离：他设备列表为空"):
            self.assertEqual(store.get_conversations("devB"), [])
        # 端点面同口径（开放态；显式带 devA 的 device cookie——新客户端 jar 为空，
        # 不带的话会新造一个 device id 只能看到空列表）
        with self._ctx():
            c = self._client()
            c.cookies.set("qabot_device", "devA")
            r = c.get("/api/conversations")
            self.assertEqual(r.status_code, 200)
            body = r.json()
            self.assertTrue(body["ok"])
            self.assertEqual([x["id"] for x in body["conversations"][:3]],
                             [55, 54, 53])
            self.assertEqual(len(body["conversations"]), 50)
            self.assertEqual(body["conversations"][0]["last_role"], "assistant")


class T5DeviceIsolationTest(_ConvTestBase):
    """⑤ 归属隔离：device B 拿不到 A 的会话（404/列表互不可见），A 侧无损。"""

    def test_cross_device_404(self):
        with self._ctx(_cfg(passcode="pw")):
            ca = self._client()
            ca.get("/")  # 种 device cookie A
            ca.post("/api/login", json={"passcode": "pw"})
            r = self._chat(ca, "A 的第一问")
            cid = r.headers.get("x-qa-conv-id")
            # 设备 B：全新客户端（jar 里是新 device cookie+新登录会话）
            cb = self._client()
            cb.get("/")
            cb.post("/api/login", json={"passcode": "pw"})
            with self.subTest("B 列表看不到 A 的会话"):
                rb = cb.get("/api/conversations")
                self.assertEqual(rb.status_code, 200)
                self.assertEqual(rb.json()["conversations"], [])
            with self.subTest("B 取 A 的消息 404"):
                self.assertEqual(
                    cb.get(f"/api/conversations/{cid}/messages").status_code, 404)
            with self.subTest("B 删 A 的会话 404 且不动 A 的数据"):
                self.assertEqual(
                    cb.delete(f"/api/conversations/{cid}").status_code, 404)
            ra = ca.get(f"/api/conversations/{cid}/messages")
            self.assertEqual(ra.status_code, 200)  # A 侧照常可读
            self.assertEqual([m["role"] for m in ra.json()["messages"]],
                             ["user", "assistant"])
        self.assertEqual(self._sql("SELECT COUNT(*) FROM conversations")[0][0], 1)

    def test_error_shape_not_found(self):
        with self._ctx(_cfg(passcode="pw")):
            c = self._client()
            c.post("/api/login", json={"passcode": "pw"})
            r = c.get("/api/conversations/999/messages")
            self.assertEqual(r.status_code, 404)
            self.assertEqual(r.json(), {"error": "not_found"})
            self.assertEqual(c.get("/api/conversations/abc/messages").status_code, 404)
            with self.subTest("巨整数 id（超 SQLite 64 位绑定域）404 不 500"):
                self.assertEqual(
                    c.get("/api/conversations/99999999999999999999999/messages")
                    .status_code, 404)
                self.assertEqual(
                    c.delete("/api/conversations/99999999999999999999999")
                    .status_code, 404)


class T6DeleteTest(_ConvTestBase):
    """⑥ 删除后列表与消息均 404，库内行清干净。"""

    def test_delete_flow(self):
        with self._ctx(_cfg(passcode="pw")):
            c = self._client()
            c.post("/api/login", json={"passcode": "pw"})
            cid = self._chat(c, "待删会话").headers.get("x-qa-conv-id")
            rd = c.delete(f"/api/conversations/{cid}")
            self.assertEqual(rd.status_code, 200)
            self.assertEqual(rd.json(), {"ok": True})
            with self.subTest("消息端点 404"):
                self.assertEqual(
                    c.get(f"/api/conversations/{cid}/messages").status_code, 404)
            with self.subTest("列表已空"):
                self.assertEqual(
                    c.get("/api/conversations").json()["conversations"], [])
            with self.subTest("重复删 404"):
                self.assertEqual(
                    c.delete(f"/api/conversations/{cid}").status_code, 404)
        self.assertEqual(self._sql("SELECT COUNT(*) FROM conversations")[0][0], 0)
        self.assertEqual(self._sql("SELECT COUNT(*) FROM messages")[0][0], 0)


class T7SourcesRoundtripTest(_ConvTestBase):
    """⑦ sources_json 往返：hit 轮落库 → 恢复端点还原；坏档给 null。"""

    def test_sources_roundtrip_and_corrupt_null(self):
        with self._ctx(_cfg(passcode="pw"), svc=_HitSvc()):
            c = self._client()
            c.post("/api/login", json={"passcode": "pw"})
            cid = self._chat(c, "T310 的缺省值是多少？").headers.get("x-qa-conv-id")
            stored = self._sql(
                "SELECT sources_json FROM messages WHERE role='assistant'")
            self.assertEqual(json.loads(stored[0][0]), SOURCES)  # 落库原文=数组 JSON
            # 同一客户端（同一 jar=同一 device cookie）：重登录后历史仍在——
            # device cookie 与登录会话解耦的口径
            c.post("/api/logout")
            c.post("/api/login", json={"passcode": "pw"})
            r = c.get(f"/api/conversations/{cid}/messages")
            self.assertEqual(r.status_code, 200)
            msgs = r.json()["messages"]
            with self.subTest("恢复形态：role/content/sources/pending"):
                self.assertEqual([m["role"] for m in msgs], ["user", "assistant"])
                self.assertEqual(msgs[1]["content"], "你好！")
                self.assertEqual(msgs[1]["sources"], SOURCES)
                self.assertFalse(msgs[1]["pending"])
                self.assertIsNone(msgs[0]["sources"])
            with self.subTest("坏档 sources_json → null"):
                self._sql("UPDATE messages SET sources_json='{not-json' "
                          "WHERE role='assistant'")
                r3 = c.get(f"/api/conversations/{cid}/messages")
                self.assertIsNone(r3.json()["messages"][1]["sources"])

    def test_error_event_stored_verbatim(self):
        """错误收尾：assistant 侧落错误 SSE 事件 JSON 原文（不做特判）。"""

        class _ErrStream:
            status_code = 503  # 非 200 → aread 出 detail 后直接收尾，不读流

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def aiter_lines(self):
                return
                yield  # 仅为成为空异步生成器（非 200 分支走不到）

            async def aread(self):
                return b"upstream exploded"

        class _ErrClient(_FastClient):
            def stream(self, *a, **k):
                return _ErrStream()

        with self._ctx(_cfg(passcode="pw")):
            with mock.patch.object(server.httpx, "AsyncClient", _ErrClient):
                c = self._client()
                c.post("/api/login", json={"passcode": "pw"})
                r = self._chat(c, "会触发上游错误的问题")
                self.assertTrue(any("error" in e for e in _chat_events(r)))
        rows = self._sql("SELECT role, content FROM messages ORDER BY id")
        self.assertEqual(rows[-1][0], "assistant")
        err = json.loads(rows[-1][1])
        self.assertEqual(err["error"], "upstream_error")
        self.assertEqual(err["status"], 503)
        self.assertEqual(err["detail"], "upstream exploded")


class T8DisabledSwitchTest(_ConvTestBase):
    """⑧ conversations_enabled=false：三端点全 404、chat 双写跳过、cookie 仍种。"""

    def test_disabled_surface(self):
        cfg = _cfg(passcode="pw", conversations_enabled=False)
        with self._ctx(cfg):
            c = self._client()
            with self.subTest("三端点 404（未过级也 404——回退键先于鉴权，不泄漏端点存在性）"):
                self.assertEqual(c.get("/api/conversations").status_code, 404)
                self.assertEqual(
                    c.get("/api/conversations/1/messages").status_code, 404)
                self.assertEqual(
                    c.delete("/api/conversations/1").status_code, 404)
                self.assertEqual(
                    c.get("/api/conversations").json(), {"error": "not_found"})
            with self.subTest("GET / 仍 200 且种 device cookie"):
                r = c.get("/")
                self.assertEqual(r.status_code, 200)
                self.assertIn("qabot_device=", r.headers.get("set-cookie", ""))
            with self.subTest("chat 照常、双写跳过、响应不带会话头"):
                c.post("/api/login", json={"passcode": "pw"})
                r = self._chat(c, "关开关后的一问")
                self.assertTrue(_chat_events(r)[-1].get("done"))
                self.assertNotIn("x-qa-conv-id", r.headers)
                # device cookie 已在 jar（前面 GET / 种下），chat 不重种；
                # "cookie 仍种"口径由 GET / 断言覆盖
                self.assertNotIn("qabot_device", r.headers.get("set-cookie", ""))
                self.assertIsNotNone(c.cookies.get("qabot_device"))
        self.assertEqual(self._sql("SELECT COUNT(*) FROM conversations")[0][0], 0)
        self.assertEqual(self._sql("SELECT COUNT(*) FROM messages")[0][0], 0)


class T9LazyPurgeTest(_ConvTestBase):
    """⑨ 惰性清理：登录路径删 90 天未动会话，不误删新会话；messages 行数帽。"""

    def test_stale_purged_fresh_survives(self):
        store = server._store_inst
        old_cid = store.create_conversation("devA", "旧会话")
        store.append_message(old_cid, "user", "旧问", None)
        store.append_message(old_cid, "assistant", "旧答", None)
        fresh_cid = store.create_conversation("devA", "新会话")
        store.append_message(fresh_cid, "user", "新问", None)
        # 旧会话回拨 91 天（>90 天线）
        self._sql("UPDATE conversations SET updated_at = ? WHERE id = ?",
                  (time.time() - 91 * 86400, old_cid))
        store.create_session(None)  # 登录路径触发惰性清理
        with self.subTest("旧会话+其消息被清"):
            self.assertEqual(
                self._sql("SELECT COUNT(*) FROM conversations WHERE id=?",
                          (old_cid,))[0][0], 0)
            self.assertEqual(
                self._sql("SELECT COUNT(*) FROM messages WHERE conv_id=?",
                          (old_cid,))[0][0], 0)
        with self.subTest("新会话不受牵连（含消息）"):
            self.assertIsNotNone(store.get_messages(fresh_cid, "devA"))
            self.assertEqual(
                len(store.get_messages(fresh_cid, "devA")), 1)

    def test_messages_rows_cap(self):
        store = server._store_inst
        cid = store.create_conversation("devA", "大会话")
        conn = sqlite3.connect(self.db)
        try:
            conn.executemany(
                "INSERT INTO messages(conv_id, role, content, sources_json, "
                "created_at) VALUES(?, 'user', ?, NULL, ?)",
                ((cid, "灌%d" % i, time.time()) for i in range(server.MESSAGES_ROWS_CAP + 1)))
            conn.commit()
        finally:
            conn.close()
        self.assertEqual(
            self._sql("SELECT COUNT(*) FROM messages")[0][0],
            server.MESSAGES_ROWS_CAP + 1)
        store.create_session(None)  # 登录路径触发行数帽清理
        left = self._sql(
            "SELECT COUNT(*), MIN(id), MAX(id) FROM messages")[0]
        with self.subTest("行数回到帽（5 万）"):
            self.assertEqual(left[0], server.MESSAGES_ROWS_CAP)
        with self.subTest("删的是最旧行（保尾）"):
            self.assertEqual(left[2] - left[1] + 1, server.MESSAGES_ROWS_CAP)


class T10ConvRateTest(_ConvTestBase):
    """⑩ 三端点独立限速：conv_hits 滑窗超限 429，不吃 chat 的 rate_hits 账。"""

    def test_rate_limit_429(self):
        with self._ctx(), mock.patch.object(server, "CONV_RATE_LIMIT", 3):
            c = self._client()
            for i in range(3):
                self.assertEqual(c.get("/api/conversations").status_code, 200,
                                 f"第{i + 1}次不应限流")
            r4 = c.get("/api/conversations")
            self.assertEqual(r4.status_code, 429)
            self.assertEqual(r4.json(),
                             {"error": "rate_limited", "retry_after_s": 60})
        self.assertEqual(self._sql("SELECT COUNT(*) FROM conv_hits")[0][0], 3)

    def test_conv_rate_isolated_from_chat_rate(self):
        with self._ctx(_cfg(passcode="pw")):
            c = self._client()
            c.post("/api/login", json={"passcode": "pw"})
            # 会话端点打满 3 次（限 3）→ 429；但 chat 照常（rate_hits 独立账）
            with mock.patch.object(server, "CONV_RATE_LIMIT", 3):
                for _ in range(3):
                    self.assertEqual(c.get("/api/conversations").status_code, 200)
                self.assertEqual(c.get("/api/conversations").status_code, 429)
            r = self._chat(c, "限速隔离验证")
            self.assertEqual(r.status_code, 200)
        self.assertEqual(self._sql("SELECT COUNT(*) FROM rate_hits")[0][0], 1)
        self.assertEqual(self._sql("SELECT COUNT(*) FROM conv_hits")[0][0], 3)


if __name__ == "__main__":
    unittest.main()
