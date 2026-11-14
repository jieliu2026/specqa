# -*- coding: utf-8 -*-
"""二期批次B 旧记录导入·后端面单测（2026-10-03，零网络零 LLM/embedding——import
端点契约零 LLM 纯落库，主路径用哨兵桩断言全程无上游调用；伪 httpx 上游同
test_conversations 形态（仅续写衔接组用）；每测试独立临时库，不碰 data/qa.db；
判据预登记=运营/前端二期-批次B-20261003/判据预登记.md（§三 import 端点契约表+
§六 后端测试判据七组））。

覆盖（B 判据 §六 七组）：
  ① 主路径：合法 body（含 assistant 条 sources；user 条 sources 合法形态照收
     但不落库=恒 None）→ 200 {ok,id} → 列表含该 id、title='本地历史（导入）'、
     updated_at 最新 → messages 逐条 role/content/sources 对拍（顺序保持、
     pending:false、无杂质字段）→ 零 LLM（哨兵桩实例化计数=0）→ journal
     [import] 行隐私纪律（消息内容绝不入日志）；
  ② 畸形 400 全清单逐例（§三校验清单 14 形态：非 JSON/非对象/messages 缺失/
     非 list/空 list/条目非对象/role 越白名单/content 非 string/空串/单条超
     16000/条数 201/sources 非 list/含非 dict 项/单条 sources 21 项）+边界
     放行（恰 200 条/恰 16000 字符/恰 20 sources → 200）；
  ③ 未过级 401：无凭据 auth_expired（形态对齐 /api/chat）/错口令
     bad_passcode；body 口令与 X-QA-Passcode 头双轨各一例过级 200；
  ④ 归属隔离：设备 A 导入 → 设备 B 列表不见、GET messages 404；
  ⑤ 限速同账：conv_hits 真限值 60 打满（与三端点共享账本，全经 GET
     /api/conversations 灌入）→ 第 61 次 import 429 rate_limited；
  ⑥ 开关关：conversations_enabled=false → 404 not_found（未过级也 404——
     回退键先于鉴权）；
  ⑦ 续写衔接：导入后以 X-QA-Conv-Id:导入id 调 /api/chat（伪上游）→ 新消息
     append 在导入消息之后（get_messages 顺序断言）。

TestClient 不进 with 上下文=不触发 lifespan 收尾关库（同 test_conversations）。
用法：
    <repo>/venv/bin/python -m tests.test_conversations_import
"""
import contextlib
import io
import json
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import server  # 仓根模块（tests/__init__.py 已做 sys.path 引导+QABOT_DB_PATH 隔离）


# ---------- 伪上游：即时流（3 delta+usage+DONE，仅 ⑦ 续写衔接组用） ----------
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


class _LlmSentinelClient:
    """零 LLM 哨兵桩：实例化即计数（import 主路径全程必须 0 次）；被调用即
    让测试炸掉（__init__ 计数已够断言，stream 兜底防御形态）。"""

    calls = 0

    def __init__(self, *a, **k):
        _LlmSentinelClient.calls += 1

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def stream(self, *a, **k):
        raise AssertionError("import 端点不得调用上游 LLM")


SOURCES = [{"doc_id": "TS 36.331", "version": "V17", "locator": "§5.2.2",
            "score": 0.9, "quote": "T310 缺省值 1000 ms"}]


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


def _imp_body(msgs):
    return {"messages": msgs}


def _pair(q="旧问题", a="旧答案"):
    """最小合法导入载荷：一问一答。"""
    return [{"role": "user", "content": q},
            {"role": "assistant", "content": a}]


def _chat_events(resp):
    return [json.loads(ln[5:].strip()) for ln in resp.text.splitlines()
            if ln.startswith("data:")]


class _ImportTestBase(unittest.TestCase):
    """每测试一块全新临时库：server._store_inst 直注入 + 退出复位。"""

    def setUp(self):
        fd, self.db = tempfile.mkstemp(prefix="qabot-imp-", suffix=".db")
        os.close(fd)
        server._store_inst = server._Store(self.db)
        _LlmSentinelClient.calls = 0

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
        """测试侧直连库做断言（WAL 多连接读写安全）。"""
        conn = sqlite3.connect(self.db)
        try:
            rows = conn.execute(sql, args).fetchall()
            conn.commit()
            return rows
        finally:
            conn.close()

    @contextlib.contextmanager
    def _ctx(self, cfg=None, client=None):
        """统一 patch 面：CONFIG/API_KEY/伪上游/rag 桩（ExitStack 一次进出）。"""
        with contextlib.ExitStack() as stack:
            for p in (mock.patch.object(server, "CONFIG", cfg if cfg is not None else _cfg()),
                      mock.patch.object(server, "API_KEY", "stub-key"),
                      mock.patch.object(server.httpx, "AsyncClient",
                                        client if client is not None else _FastClient),
                      mock.patch.object(server, "rag_service", None)):
                stack.enter_context(p)
            yield

    def _client(self):
        """不进 with：不触发 lifespan（避免收尾把隔离 _Store 关掉置 None）。"""
        return TestClient(server.app)

    def _import(self, c, msgs, headers=None):
        """POST import（msgs 直接收消息数组，鉴权口令等经 headers/自备 body 场景除外）。"""
        return c.post("/api/conversations/import", json=_imp_body(msgs),
                      headers=headers or {})


class T1ImportMainTest(_ImportTestBase):
    """① 主路径：200 {ok,id}+列表落位+消息对拍+零 LLM+journal 隐私。"""

    def test_main_path_zero_llm(self):
        msgs = [
            {"role": "user", "content": "旧问题一"},
            {"role": "assistant", "content": "旧答案一", "sources": SOURCES},
            # user 条带合法 sources：形态过校验但落库恒 None（端侧本就丢弃，服务端同口径）
            {"role": "user", "content": "旧问题二", "sources": SOURCES},
            {"role": "assistant", "content": "旧答案二"},  # 无 sources 键
        ]
        # 预置一个先行会话：导入毕即列表最新（updated_at 内联 touch 的可见面）
        server._store_inst.create_conversation("devA", "先行会话")
        out = io.StringIO()
        with self._ctx(client=_LlmSentinelClient):
            c = self._client()
            c.cookies.set("qabot_device", "devA")
            with contextlib.redirect_stdout(out):
                r = self._import(c, msgs)
            with self.subTest("200 且回 {ok,id}（id 为整数）"):
                self.assertEqual(r.status_code, 200, r.text)
                body = r.json()
                self.assertTrue(body["ok"])
                self.assertIsInstance(body["id"], int)
                cid = body["id"]
            with self.subTest("列表：本 device 含该 id、标题固定、最新在首位"):
                rl = c.get("/api/conversations")
                self.assertEqual(rl.status_code, 200)
                convs = rl.json()["conversations"]
                self.assertEqual(convs[0]["id"], cid)
                self.assertEqual(convs[0]["title"], "本地历史（导入）")
                self.assertEqual(convs[0]["last_role"], "assistant")
            with self.subTest("messages：逐条 role/content/sources 对拍，无杂质字段"):
                rm = c.get(f"/api/conversations/{cid}/messages")
                self.assertEqual(rm.status_code, 200)
                got = rm.json()["messages"]
                self.assertEqual([m["role"] for m in got],
                                 ["user", "assistant", "user", "assistant"])
                self.assertEqual([m["content"] for m in got],
                                 ["旧问题一", "旧答案一", "旧问题二", "旧答案二"])
                for m in got:  # 恢复面四键形态，未知键=服务端未透传杂质
                    self.assertEqual(set(m.keys()),
                                     {"role", "content", "sources", "pending"})
                    self.assertFalse(m["pending"])
                self.assertIsNone(got[0]["sources"])
                self.assertEqual(got[1]["sources"], SOURCES)
                self.assertIsNone(got[2]["sources"])  # user 条恒 None
                self.assertIsNone(got[3]["sources"])
            with self.subTest("device cookie 种植面（同三端点）"):
                fresh = self._client()
                rf = self._import(fresh, _pair())
                self.assertEqual(rf.status_code, 200)
                self.assertIn("qabot_device=", rf.headers.get("set-cookie", ""))
        with self.subTest("零 LLM：哨兵桩全程 0 次实例化"):
            self.assertEqual(_LlmSentinelClient.calls, 0)
        with self.subTest("库面：user 条 sources_json 恒 None、assistant 条存数组 JSON"):
            rows = self._sql(
                "SELECT role, sources_json FROM messages WHERE conv_id=? "
                "ORDER BY id", (cid,))
            self.assertEqual([r[0] for r in rows],
                             ["user", "assistant", "user", "assistant"])
            self.assertIsNone(rows[0][1])
            self.assertEqual(json.loads(rows[1][1]), SOURCES)
            self.assertIsNone(rows[2][1])
            self.assertIsNone(rows[3][1])
        with self.subTest("journal：[import] 行带 n=/conv=，消息内容绝不入日志"):
            lines = [ln for ln in out.getvalue().splitlines()
                     if ln.startswith("[import]")]
            self.assertEqual(len(lines), 1)
            self.assertIn("n=4", lines[0])
            self.assertIn(f"conv={cid}", lines[0])
            self.assertNotIn("旧问题一", lines[0])
            self.assertNotIn("旧答案一", lines[0])


class T2ImportMalformedTest(_ImportTestBase):
    """② 畸形 400 全清单逐例（§三校验清单）+边界放行。"""

    def test_malformed_400_checklist(self):
        cases = [
            ("非 JSON 字节", None),  # 特判：raw content 发送
            ("JSON 数组（非对象）", [1, 2]),
            ("messages 缺失", {}),
            ("messages 非 list", {"messages": "x"}),
            ("messages 空 list", {"messages": []}),
            ("条目非对象", {"messages": ["x"]}),
            ("role 越白名单",
             {"messages": [{"role": "system", "content": "x"}]}),
            ("content 非 string",
             {"messages": [{"role": "user", "content": 123}]}),
            ("content 空串",
             {"messages": [{"role": "user", "content": ""}]}),
            ("单条超 16000 字符",
             {"messages": [{"role": "user", "content": "x" * 16001}]}),
            ("条数 201",
             {"messages": [{"role": "user", "content": "m%d" % i}
                           for i in range(201)]}),
            ("sources 非 list",
             {"messages": [{"role": "assistant", "content": "a",
                            "sources": {"doc_id": "x"}}]}),
            ("sources 含非 dict 项",
             {"messages": [{"role": "assistant", "content": "a",
                            "sources": [SOURCES[0], "y"]}]}),
            ("单条 sources 21 项",
             {"messages": [{"role": "assistant", "content": "a",
                            "sources": [{"i": i} for i in range(21)]}]}),
        ]
        with self._ctx():
            c = self._client()
            for name, body in cases:
                if body is None:  # 非 JSON 字节形态
                    r = c.post("/api/conversations/import", content=b"{not-json",
                               headers={"Content-Type": "application/json"})
                else:
                    r = c.post("/api/conversations/import", json=body)
                with self.subTest(case=name):
                    self.assertEqual(r.status_code, 400, r.text)
                    self.assertEqual(r.json(), {"error": "bad_request"})
        self.assertEqual(
            self._sql("SELECT COUNT(*) FROM conversations")[0][0], 0)
        self.assertEqual(self._sql("SELECT COUNT(*) FROM messages")[0][0], 0)

    def test_boundaries_pass(self):
        """恰 200 条/恰 16000 字符/恰 20 sources：边界值放行（帽与上限是 > 才拒）。"""
        with self._ctx():
            c = self._client()
            with self.subTest("恰 200 条"):
                r = self._import(c, [{"role": "user", "content": "m%d" % i}
                                     for i in range(200)])
                self.assertEqual(r.status_code, 200, r.text)
                self.assertEqual(
                    self._sql("SELECT COUNT(*) FROM messages")[0][0], 200)
            with self.subTest("单条恰 16000 字符"):
                r = self._import(c, [{"role": "user", "content": "x" * 16000}])
                self.assertEqual(r.status_code, 200, r.text)
            with self.subTest("单条恰 20 项 sources"):
                r = self._import(c, [
                    {"role": "assistant", "content": "a",
                     "sources": [{"i": i} for i in range(20)]}])
                self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(
            self._sql("SELECT COUNT(*) FROM conversations")[0][0], 3)


class T3ImportAuthTest(_ImportTestBase):
    """③ 未过级 401（形态对齐 /api/chat）；body 口令与 X-QA-Passcode 头双轨过级。"""

    def test_no_credentials_401(self):
        with self._ctx(_cfg(passcode="pw")):
            c = self._client()
            r = self._import(c, _pair())
            self.assertEqual(r.status_code, 401)
            self.assertEqual(r.json(), {"error": "auth_expired"})

    def test_wrong_passcode_401(self):
        with self._ctx(_cfg(passcode="pw")):
            c = self._client()
            r = c.post("/api/conversations/import",
                       json={"messages": _pair(), "passcode": "bad"})
            self.assertEqual(r.status_code, 401)
            self.assertEqual(r.json(), {"error": "bad_passcode"})

    def test_body_and_header_passcode_ok(self):
        with self._ctx(_cfg(passcode="pw")):
            c1 = self._client()  # 无 cookie jar：body 口令轨
            r1 = c1.post("/api/conversations/import",
                         json={"messages": _pair(), "passcode": "pw"})
            self.assertEqual(r1.status_code, 200, r1.text)
            self.assertTrue(r1.json()["ok"])
        with self._ctx(_cfg(passcode="pw")):
            c2 = self._client()  # 无 cookie jar：X-QA-Passcode 头轨
            r2 = self._import(c2, _pair(), headers={"X-QA-Passcode": "pw"})
            self.assertEqual(r2.status_code, 200, r2.text)
            self.assertTrue(r2.json()["ok"])
        self.assertEqual(
            self._sql("SELECT COUNT(*) FROM conversations")[0][0], 2)


class T4ImportIsolationTest(_ImportTestBase):
    """④ 归属隔离：设备 A 导入 → 设备 B 列表不见、GET messages 404。"""

    def test_device_isolation(self):
        with self._ctx():
            ca = self._client()
            ca.get("/")  # 种 device cookie A
            ra = self._import(ca, _pair("A 的旧问", "A 的旧答"))
            self.assertEqual(ra.status_code, 200)
            cid = ra.json()["id"]
            cb = self._client()
            cb.get("/")  # 种 device cookie B（全新 jar=另一台设备）
            with self.subTest("B 列表不见 A 的导入会话"):
                rb = cb.get("/api/conversations")
                self.assertEqual(rb.status_code, 200)
                self.assertEqual(rb.json()["conversations"], [])
            with self.subTest("B 取 A 的导入消息 404"):
                self.assertEqual(
                    cb.get(f"/api/conversations/{cid}/messages").status_code,
                    404)
            with self.subTest("A 侧照常可读可列"):
                self.assertEqual(
                    ca.get(f"/api/conversations/{cid}/messages").status_code,
                    200)
                self.assertEqual(
                    [x["id"] for x in
                     ca.get("/api/conversations").json()["conversations"]],
                    [cid])
        self.assertEqual(
            self._sql("SELECT COUNT(*) FROM conversations")[0][0], 1)


class T5ImportRateTest(_ImportTestBase):
    """⑤ 限速同账：conv_hits 真限值 60 打满（与三端点共享账本）→ import 429。"""

    def test_shared_conv_hits_429(self):
        with self._ctx():
            c = self._client()
            for i in range(server.CONV_RATE_LIMIT):  # 60：全经列表端点灌入
                r = c.get("/api/conversations")
                self.assertEqual(r.status_code, 200, f"第{i + 1}次不应限流")
            r61 = self._import(c, _pair())
            self.assertEqual(r61.status_code, 429)
            self.assertEqual(r61.json(),
                             {"error": "rate_limited", "retry_after_s": 60})
        self.assertEqual(
            self._sql("SELECT COUNT(*) FROM conv_hits")[0][0],
            server.CONV_RATE_LIMIT)
        self.assertEqual(
            self._sql("SELECT COUNT(*) FROM rate_hits")[0][0], 0)  # 不占 chat 账
        self.assertEqual(
            self._sql("SELECT COUNT(*) FROM conversations")[0][0], 0)


class T6ImportSwitchTest(_ImportTestBase):
    """⑥ 开关关：conversations_enabled=false → 404 not_found（先于鉴权）。"""

    def test_disabled_404(self):
        with self._ctx(_cfg(conversations_enabled=False)):
            c = self._client()
            r = self._import(c, _pair())  # 未过级（开放态无凭据）也 404
            self.assertEqual(r.status_code, 404)
            self.assertEqual(r.json(), {"error": "not_found"})
        self.assertEqual(
            self._sql("SELECT COUNT(*) FROM conversations")[0][0], 0)
        self.assertEqual(self._sql("SELECT COUNT(*) FROM messages")[0][0], 0)


class T7ImportContinueTest(_ImportTestBase):
    """⑦ 续写衔接：导入会话以 X-QA-Conv-Id 续写，新消息 append 在导入消息之后。"""

    def test_continue_after_import(self):
        with self._ctx():
            c = self._client()
            c.get("/")
            ri = self._import(c, _pair("导入的旧问", "导入的旧答"))
            self.assertEqual(ri.status_code, 200)
            cid = ri.json()["id"]
            r = c.post("/api/chat",
                       json={"messages": [{"role": "user", "content": "续问"}]},
                       headers={"X-QA-Conv-Id": str(cid)})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertTrue(_chat_events(r)[-1].get("done"))
            with self.subTest("仍续写同一会话（响应头同 id）"):
                self.assertEqual(r.headers.get("x-qa-conv-id"), str(cid))
            with self.subTest("新消息 append 在导入消息之后（顺序断言）"):
                got = c.get(f"/api/conversations/{cid}/messages").json()["messages"]
                self.assertEqual(
                    [m["content"] for m in got],
                    ["导入的旧问", "导入的旧答", "续问", "你好！"])
                self.assertEqual(
                    [m["role"] for m in got],
                    ["user", "assistant", "user", "assistant"])
        self.assertEqual(
            self._sql("SELECT COUNT(*) FROM conversations")[0][0], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
