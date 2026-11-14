# -*- coding: utf-8 -*-
"""C1 安全套件·注入与载荷面（2026-10-07 施工，只新建测试件不改产品码）。
C1 安全套件·CI 差集核验后应干净树绿。

覆盖：
  ① conv_id 非法形态拒绝：字母/小数/负数/0/SQL 关键字形态/十六进制形等
     → 三端点（messages/DELETE/PATCH）一律 404 not_found，绝无 500；
  ② conv_id 64 位边界：2^63-1（域内，不存在→404）/2^63 与 2^63+1（域外→404）
     ——超 SQLite 绑定域不炸 OverflowError 500；
  ③ title/JSON 含引号与 SQL 关键字往返无损：rename 与 import 双面
     （API 面读回 + 库面直核，逐字符等值；无注入副作用=无 rogue 表/无扩行）；
  ④ SSE 载荷转义：data 帧恒单行 JSON（换行/引号必被 json.dumps 转义），
     逐帧可解析、delta 拼回原文逐字符无损——衔接既有 mxss 件口径不重复
     （mxss 件锁前端渲染对抗，本件锁服务端传输帧形态）；
  ⑤ 三负控：响应无 Access-Control-Allow-Origin 头（无 CORS 面）；
     SQL 参数化往返（③ 已含，此处汇总断言库结构完整）；
     server.UPSTREAM 不受请求参数影响（读常量断言+构造恶意请求后常量不变）。

跑法（仓根）：
    cd <repo> && venv/bin/python -m tests.test_security_injection
零网络零计费（伪 httpx 上游，惯例抄 tests/test_auth_rate.py 40-77 行）；
每测试独立临时库（server._store_inst 直注入），不碰 data/qa.db；
测试口令一律 stub 占位（纪律⑤：零密件）。默认开放态（无口令）聚焦载荷面。"""
import contextlib
import json
import os
import sqlite3
import tempfile
import unittest
import urllib.parse
from unittest import mock

from fastapi.testclient import TestClient

import server  # 仓根模块（tests/__init__.py 已做 sys.path 引导+QABOT_DB_PATH 隔离）

STUB_PW = "stub-passcode"   # 占位口令（纪律⑤：测试零密件）

# ① conv_id 非法形态清单（字母/小数/负数/0/SQL 关键字/十六进制/科学计数/百分号形）
BAD_CONV_IDS = [
    "abc", "1.5", "-1", "0", str(2 ** 63), str(2 ** 63 + 1),
    "1;DROP TABLE conversations;--", "1 OR 1=1", "' OR '1'='1",
    "0x10", "1e3", "%31", "%27",
]

# ③ SQL 注入形态载荷（含双引号/单引号/SQL 关键字/中文引号上下文）
TITLE_PAYLOAD = 'x"; DROP TABLE conversations;-- y\' OR \'1\'=\'1 你好"引号'
CONTENT_PAYLOAD = ('含双引号"单引号\'反斜杠\\换行\n'
                   "; DROP TABLE messages;-- UNION SELECT token FROM sessions-- "
                   "中文与<b>标签</b> [出处1]")

# ④ SSE 转义对抗载荷（引号/反斜杠/换行/标签/SQL 关键字/制表符/中文）
SSE_PAYLOAD = ('引号"单引号\'反斜杠\\换行\n第二行</script><img src=x onerror=alert(1)> '
               "'; DROP TABLE messages;--\t[出处1] 中文尾部")


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


class _PayloadStream:
    """④ 专用：把 SSE_PAYLOAD 拆两段 delta 下发（模拟流式拆块）。"""
    status_code = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def aiter_lines(self):
        mid = len(SSE_PAYLOAD) // 2
        for part in (SSE_PAYLOAD[:mid], SSE_PAYLOAD[mid:]):
            yield "data: " + json.dumps(
                {"choices": [{"delta": {"content": part}}]}, ensure_ascii=False)
        yield "data: " + json.dumps({"usage": {"total_tokens": 9}, "choices": []})
        yield "data: [DONE]"

    async def aread(self):
        return b""


class _PayloadClient:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def stream(self, *a, **k):
        return _PayloadStream()


# ---------- 配置底座（请求时读 server.CONFIG，逐测试 patch） ----------
_BASE = {
    "model": "stub-model", "bot_name": "测试机",
    "max_history_messages": 5, "max_input_chars": 8000,
    "max_total_input_chars": 24000, "temperature": 0.7, "max_tokens": 100,
    "rate_limit_requests": 20, "rate_limit_window_seconds": 300,
}


def _cfg(**over):
    cfg = dict(_BASE, passcode="")  # 默认开放态：聚焦载荷面不掺鉴权变量
    cfg.update(over)
    return cfg


def _msgs(text="问句"):
    return [{"role": "user", "content": text}]


class _SecTestBase(unittest.TestCase):
    """每测试一块全新临时库：server._store_inst 直注入 + 退出复位（不碰 data/qa.db）。"""

    def setUp(self):
        fd, self.db = tempfile.mkstemp(prefix="qabot-sec-inj-", suffix=".db")
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

    def _mk_conv(self, c, content="内容"):
        r = c.post("/api/conversations/import",
                   json={"messages": [{"role": "user", "content": content}]})
        self.assertEqual(r.status_code, 200)
        return r.json()["id"]


class T1ConvIdValidationTest(_SecTestBase):
    """① conv_id 非法形态拒绝：强转 int + 白名单域校验，404 绝无 500。"""

    def test_invalid_conv_id_forms_rejected_404_never_500(self):
        c = TestClient(server.app)
        with self._ctx(_cfg()):
            for bad in BAD_CONV_IDS:
                q = urllib.parse.quote(bad, safe="")
                with self.subTest(conv_id=bad):
                    r = c.get(f"/api/conversations/{q}/messages")
                    self.assertEqual(r.status_code, 404)
                    self.assertEqual(r.json(), {"error": "not_found"})
                    r2 = c.delete(f"/api/conversations/{q}")
                    self.assertEqual(r2.status_code, 404)
                    r3 = c.patch(f"/api/conversations/{q}",
                                 json={"title": "t"})
                    self.assertEqual(r3.status_code, 404)

    def test_conv_id_64bit_boundary_no_500(self):
        c = TestClient(server.app)
        with self._ctx(_cfg()):
            cases = {
                "9223372036854775807": 404,   # 2^63-1：域内合法形，不存在→404
                "9223372036854775808": 404,   # 2^63：域外→404（防 OverflowError）
                "-9223372036854775808": 404,  # 负域外→404
            }
            for v, expect in cases.items():
                with self.subTest(conv_id=v):
                    r = c.get(f"/api/conversations/{v}/messages")
                    self.assertEqual(r.status_code, expect)
                    self.assertNotEqual(r.status_code, 500)


class T2SqlRoundtripTest(_SecTestBase):
    """③ title/JSON 含引号与 SQL 关键字往返无损（含 ⑤ 之参数化负控）。"""

    def test_rename_title_sql_shaped_roundtrip_intact(self):
        c = TestClient(server.app)
        with self._ctx(_cfg()):
            cid = self._mk_conv(c)
            r = c.patch(f"/api/conversations/{cid}",
                        json={"title": TITLE_PAYLOAD})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json(), {"ok": True})
            lst = c.get("/api/conversations").json()["conversations"]  # API 面读回
            got = [row["title"] for row in lst if row["id"] == cid]
            self.assertEqual(got, [TITLE_PAYLOAD])  # 逐字符无损
        # 库面直核：参数化无注入副作用（行仍在/无 rogue 表/结构完整）
        (t,) = self._sql(
            "SELECT title FROM conversations WHERE id=?", (cid,))[0]
        self.assertEqual(t, TITLE_PAYLOAD)
        tables = {row[0] for row in self._sql(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        for must in ("conversations", "messages", "sessions", "rate_hits"):
            self.assertIn(must, tables)  # DROP 形载荷未得逞
        self.assertFalse(any("pwn" in t2.lower() for t2 in tables))
        self.assertEqual(
            self._sql("SELECT COUNT(*) FROM conversations")[0][0], 1)

    def test_import_content_sql_shaped_roundtrip_intact(self):
        c = TestClient(server.app)
        with self._ctx(_cfg()):
            r = c.post("/api/conversations/import",
                       json={"messages": [{"role": "user",
                                           "content": CONTENT_PAYLOAD}]})
            self.assertEqual(r.status_code, 200)
            cid = r.json()["id"]
            m = c.get(f"/api/conversations/{cid}/messages")
            self.assertEqual(m.status_code, 200)
            self.assertEqual(m.json()["messages"][0]["content"],
                             CONTENT_PAYLOAD)  # 逐字符无损（含换行/引号）
        # 库面：未被注入扩行（UNION SELECT 形载荷不得改变行数）
        self.assertEqual(self._sql("SELECT COUNT(*) FROM messages")[0][0], 1)
        self.assertEqual(
            self._sql("SELECT COUNT(*) FROM sessions")[0][0], 0)


class T3SseEscapingTest(_SecTestBase):
    """④ SSE 载荷转义：服务端 data 帧恒单行 JSON、往返逐字符无损。

    衔接既有 tests/test_frontend_mxss.py 口径不重复：mxss 件锁前端渲染对抗
    （esc/DOM 零执行面），本件锁服务端传输帧形态（_sse 的 json.dumps 转义）。"""

    def test_sse_payload_json_escaped_roundtrip(self):
        c = TestClient(server.app)
        with self._ctx(_cfg(), upstream=_PayloadClient):
            r = c.post("/api/chat",
                       json={"messages": [{"role": "user",
                                           "content": "sse 转义问句"}]})
            self.assertEqual(r.status_code, 200)
            self.assertTrue(r.headers["content-type"].startswith(
                "text/event-stream"))
            deltas, done = [], False
            for ln in r.text.splitlines():
                if not ln.startswith("data:"):
                    continue  # 注释行（": trace_id=..."）不进事件面
                ev = json.loads(ln[5:].strip())  # 每帧单行可解析=换行必被转义
                if "delta" in ev:
                    deltas.append(ev["delta"])
                done = done or bool(ev.get("done"))
            self.assertTrue(done, "流未自然收尾")
            self.assertEqual("".join(deltas), SSE_PAYLOAD)  # 拼回原文无损


class T4NegativeControlsTest(_SecTestBase):
    """⑤ 三负控：无 ACAO 头 / SQL 参数化往返（T2 已证，此处锁 UPSTREAM 免疫）。"""

    def test_no_access_control_allow_origin_header(self):
        # 无 CORS/ACAO 面：任何端点（含带 Origin 头的跨域形请求）不得出现
        # Access-Control-Allow-Origin / Access-Control-Allow-Credentials
        c = TestClient(server.app)
        with self._ctx(_cfg(passcode=STUB_PW)):
            r1 = c.post("/api/login", json={"passcode": STUB_PW})
            r2 = c.get("/api/conversations",
                       headers={"X-QA-Passcode": STUB_PW})
            r3 = c.post("/api/chat", json={"messages": _msgs(),
                                           "passcode": STUB_PW},
                        headers={"Origin": "https://evil.example"})
            r4 = c.get("/api/health",
                       headers={"Origin": "https://evil.example"})
        for r in (r1, r2, r3, r4):
            with self.subTest(url=str(r.url)):
                self.assertIsNone(r.headers.get("access-control-allow-origin"))
                self.assertIsNone(
                    r.headers.get("access-control-allow-credentials"))

    def test_upstream_constant_immune_to_request_params(self):
        # server.UPSTREAM 是模块常量：读常量断言（恒 https 形态）+构造恶意
        # 请求（body 夹带伪 upstream/恶意头）后常量不变。
        before = server.UPSTREAM
        self.assertTrue(before.startswith("https://"))
        c = TestClient(server.app)
        with self._ctx(_cfg(passcode=STUB_PW)):
            c.post("/api/chat",
                   json={"messages": [{"role": "user",
                                       "content": "http://evil.example/exploit "
                                                  + before}],
                         "passcode": STUB_PW},
                   headers={"X-QA-Conv-Id": "1; DROP",
                            "X-Forwarded-Host": "evil.example"})
            c.post("/api/login",
                   json={"passcode": STUB_PW,
                         "upstream": "http://evil.example/"})
            c.post("/api/feedback",
                   json={"rating": "up", "upstream": "http://evil.example/"})
        self.assertEqual(server.UPSTREAM, before)  # 恶意请求后逐字节不变


if __name__ == "__main__":
    unittest.main()
