# -*- coding: utf-8 -*-
"""二期批A A2 重新生成改替换·案①服务端替换·后端面单测（2026-10-03，零网络零
LLM/embedding，伪 httpx 上游同 test_conversations 形态；每测试独立临时库，
不碰 data/qa.db；判据预登记=运营/前端二期-批次A-20261003/判据预登记.md）。

覆盖：
  ① 端到端主路径：显式 conv id+X-QA-Regen:1 续写 → 末轮（user+assistant 对）
     被删、本轮写入；GET messages 旧轮不残留（恢复面旧答不重现的库侧保证）；
  ② 纯函数面 _conversation_writeback regen 参数：孤 user 断流形态（writeback
     只落 user 侧=天然孤链）删末轮再写；
  ③ _Store.delete_last_round 三形态直测：完整对/孤 user/空会话与无 user 防御
     形态 + last_msg_id 回落；
  ④ 头语义边界：缺省 conv id 时 regen 头静默忽略（自动建新）；值非 1（"2"）
     忽略照常追加；跨设备冒用 conv id+regen → 静默换新会话、A 侧零污染；
  ⑤ 错误轮（assistant content=错误 SSE JSON 原文）可替换；
  ⑥ conversations_enabled=false：带 regen 头 chat 照常流式、双写整体跳过零报错。

TestClient 不进 with 上下文=不触发 lifespan 收尾关库（同 test_conversations）。
用法：
    <repo>/venv/bin/python -m tests.test_conversations_regen
"""
import asyncio
import contextlib
import json
import os
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import server  # 仓根模块（tests/__init__.py 已做 sys.path 引导+QABOT_DB_PATH 隔离）


# ---------- 伪上游：即时流（3 delta+usage+DONE）与错误流（非 200） ----------
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


class _ErrStream:
    status_code = 503  # 非 200 → aread 出 detail 后收尾（错误 JSON 原文落库）

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def aiter_lines(self):
        return
        yield  # 空异步生成器（非 200 分支走不到）

    async def aread(self):
        return b"upstream exploded"


class _ErrClient(_FastClient):
    def stream(self, *a, **k):
        return _ErrStream()


# ---------- 配置底座（开放态免鉴权，最简链路；请求时读 server.CONFIG） ----------
_BASE = {
    "model": "stub-model", "bot_name": "测试机",
    "max_history_messages": 5, "max_input_chars": 8000,
    "max_total_input_chars": 24000, "temperature": 0.7, "max_tokens": 100,
    "rate_limit_requests": 20, "rate_limit_window_seconds": 300,
}


def _cfg(**over):
    cfg = dict(_BASE)
    cfg.update(over)
    return cfg


def _chat_events(resp):
    return [json.loads(ln[5:].strip()) for ln in resp.text.splitlines()
            if ln.startswith("data:")]


class _RegenTestBase(unittest.TestCase):
    """每测试一块全新临时库：server._store_inst 直注入 + 退出复位。"""

    def setUp(self):
        fd, self.db = tempfile.mkstemp(prefix="qabot-regen-", suffix=".db")
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
        import sqlite3
        conn = sqlite3.connect(self.db)
        try:
            rows = conn.execute(sql, args).fetchall()
            conn.commit()
            return rows
        finally:
            conn.close()

    @contextlib.contextmanager
    def _ctx(self, cfg=None):
        with contextlib.ExitStack() as stack:
            for p in (mock.patch.object(server, "CONFIG", cfg if cfg is not None else _cfg()),
                      mock.patch.object(server, "API_KEY", "stub-key"),
                      mock.patch.object(server.httpx, "AsyncClient", _FastClient),
                      mock.patch.object(server, "rag_service", None)):
                stack.enter_context(p)
            yield

    def _client(self):
        return TestClient(server.app)

    def _chat(self, c, text, headers=None):
        r = c.post("/api/chat",
                   json={"messages": [{"role": "user", "content": text}]},
                   headers=headers or {})
        self.assertEqual(r.status_code, 200, r.text)
        return r

    def _msgs_content(self, c, cid):
        r = c.get(f"/api/conversations/{cid}/messages")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["ok"])
        return r.json()["messages"]


class T1RegenE2ETest(_RegenTestBase):
    """① 端到端主路径：regen 续写删末轮写本轮，旧轮不残留、同会话续写。"""

    def test_regen_replaces_last_round(self):
        with self._ctx():
            c = self._client()
            r1 = self._chat(c, "第一问")
            cid = r1.headers.get("x-qa-conv-id")
            self.assertTrue(cid and cid.isdigit())
            self._chat(c, "第二问", headers={"X-QA-Conv-Id": cid})
            # regen 前 2 轮 4 行；若服务端仍追加语义，regen 后会变 3 轮 6 行
            self.assertEqual(
                len(self._msgs_content(c, cid)), 4)
            # 重新生成：同一问带 regen 头重发
            r3 = self._chat(c, "第二问",
                            headers={"X-QA-Conv-Id": cid, "X-QA-Regen": "1"})
            with self.subTest("仍续写同一会话（响应头同 id）"):
                self.assertEqual(r3.headers.get("x-qa-conv-id"), cid)
            with self.subTest("替换后取消息=2 轮 4 行，旧轮不残留"):
                got = self._msgs_content(c, cid)
                self.assertEqual(len(got), 4)
                self.assertEqual(
                    [m["content"] for m in got],
                    ["第一问", "你好！", "第二问", "你好！"])
                self.assertEqual(
                    [m["role"] for m in got],
                    ["user", "assistant", "user", "assistant"])
            with self.subTest("库面同一事实（防端点序列化面失真）"):
                self.assertEqual(
                    self._sql("SELECT COUNT(*) FROM messages")[0][0], 4)
                self.assertEqual(
                    self._sql("SELECT COUNT(*) FROM conversations")[0][0], 1)


class T2WritebackRegenTest(_RegenTestBase):
    """② 纯函数面：_conversation_writeback regen 参数（孤 user 链=断流形态）。"""

    def test_writeback_regen_semantics(self):
        store = server._store_inst
        cid = asyncio.run(server._conversation_writeback(store, "devA", None, "第一问"))
        asyncio.run(server._conversation_writeback(store, "devA", str(cid), "第二问"))
        self.assertEqual(
            [m[1] for m in store.get_messages(cid, "devA")],
            ["第一问", "第二问"])  # 孤 user 链：writeback 只落 user 侧
        # regen：删末轮（孤 user u2）再写本轮 → [第一问, 第二问'] 同文本
        cid2 = asyncio.run(server._conversation_writeback(
            store, "devA", str(cid), "第二问", regen=True))
        self.assertEqual(cid2, cid)
        self.assertEqual(
            [m[1] for m in store.get_messages(cid, "devA")], ["第一问", "第二问"])
        # 非 regen 续写照常追加（回归锚：默认参数行为与既往一致）
        asyncio.run(server._conversation_writeback(store, "devA", str(cid), "第三问"))
        self.assertEqual(
            [m[1] for m in store.get_messages(cid, "devA")],
            ["第一问", "第二问", "第三问"])


class T3DeleteLastRoundTest(_RegenTestBase):
    """③ _Store.delete_last_round 直测：完整对/孤 user/防御形态+last_msg_id 回落。"""

    def test_shapes(self):
        store = server._store_inst
        cid = store.create_conversation("devA", "标题")
        with self.subTest("空会话 → 0 不动"):
            self.assertEqual(store.delete_last_round(cid), 0)
        store.append_message(cid, "user", "问一")
        a1 = store.append_message(cid, "assistant", "答一")
        store.append_message(cid, "user", "问二")
        with self.subTest("孤 user 末轮（断流形态）→ 删 1"):
            self.assertEqual(store.delete_last_round(cid), 1)
            self.assertEqual(
                [m[0] for m in store.get_messages(cid, "devA")], ["user", "assistant"])
        store.append_message(cid, "user", "问二")
        store.append_message(cid, "assistant", "答二")
        with self.subTest("完整对末轮 → 删 2"):
            self.assertEqual(store.delete_last_round(cid), 2)
            self.assertEqual(
                [m[1] for m in store.get_messages(cid, "devA")], ["问一", "答一"])
        with self.subTest("last_msg_id 回落到现存末条"):
            row = self._sql(
                "SELECT last_msg_id FROM conversations WHERE id=?", (cid,))[0]
            self.assertEqual(row[0], a1)

    def test_no_user_defensive(self):
        """无 user 消息的防御形态（理论不可达）：返回 0 不动。"""
        store = server._store_inst
        cid = store.create_conversation("devA", "标题")
        store.append_message(cid, "assistant", "孤儿答")
        self.assertEqual(store.delete_last_round(cid), 0)
        self.assertEqual(
            len(store.get_messages(cid, "devA")), 1)


class T4RegenHeaderEdgeTest(_RegenTestBase):
    """④ 头语义边界：缺省 conv id/值非 1/跨设备冒用/开关关。"""

    def test_regen_ignored_without_conv_id(self):
        with self._ctx():
            c = self._client()
            r1 = self._chat(c, "第一问")
            cid1 = r1.headers.get("x-qa-conv-id")
            # 缺省 conv id + regen 头 → 自动建新会话，regen 静默忽略不报错
            r2 = self._chat(c, "第二问", headers={"X-QA-Regen": "1"})
            cid2 = r2.headers.get("x-qa-conv-id")
            self.assertTrue(cid2 and cid2.isdigit())
            self.assertNotEqual(cid2, cid1)
            with self.subTest("第一会话原样（regen 无对象可删）"):
                self.assertEqual(len(self._msgs_content(c, cid1)), 2)
            with self.subTest("第二会话独立成链"):
                self.assertEqual(len(self._msgs_content(c, cid2)), 2)
            self.assertEqual(
                self._sql("SELECT COUNT(*) FROM conversations")[0][0], 2)

    def test_regen_value_not_one_ignored(self):
        with self._ctx():
            c = self._client()
            r1 = self._chat(c, "第一问")
            cid = r1.headers.get("x-qa-conv-id")
            r2 = self._chat(c, "第二问", headers={"X-QA-Conv-Id": cid,
                                                  "X-QA-Regen": "2"})
            self.assertEqual(r2.headers.get("x-qa-conv-id"), cid)
            with self.subTest("值非 1 → 照常追加不删轮（4 行）"):
                self.assertEqual(len(self._msgs_content(c, cid)), 4)

    def test_cross_device_regen_silent_new(self):
        with self._ctx():
            a = self._client()
            r1 = self._chat(a, "A 的问题")
            cid_a = r1.headers.get("x-qa-conv-id")
            b = self._client()  # 第二个 client=第二台设备（各自种 device cookie）
            r2 = self._chat(b, "B 冒用",
                            headers={"X-QA-Conv-Id": cid_a, "X-QA-Regen": "1"})
            cid_b = r2.headers.get("x-qa-conv-id")
            with self.subTest("冒用 → 静默换新会话"):
                self.assertNotEqual(cid_b, cid_a)
                self.assertTrue(cid_b and cid_b.isdigit())
            with self.subTest("A 侧零污染（消息原样、删轮不误伤）"):
                self.assertEqual(len(self._msgs_content(a, cid_a)), 2)

    def test_disabled_switch_regen_harmless(self):
        with self._ctx(_cfg(conversations_enabled=False)):
            c = self._client()
            r = self._chat(c, "关开关的一问",
                           headers={"X-QA-Conv-Id": "1", "X-QA-Regen": "1"})
            with self.subTest("照常流式收尾、无会话头"):
                self.assertTrue(_chat_events(r)[-1].get("done"))
                self.assertNotIn("x-qa-conv-id", r.headers)
        self.assertEqual(
            self._sql("SELECT COUNT(*) FROM conversations")[0][0], 0)
        self.assertEqual(self._sql("SELECT COUNT(*) FROM messages")[0][0], 0)


class T5ErrorRoundTest(_RegenTestBase):
    """⑤ 错误轮（assistant=错误 SSE JSON 原文）可替换：regen 后错误轮不残留。"""

    def test_error_round_replaced(self):
        with self._ctx():
            c = self._client()
            r1 = self._chat(c, "第一问")
            cid = r1.headers.get("x-qa-conv-id")
            with mock.patch.object(server.httpx, "AsyncClient", _ErrClient):
                r2 = self._chat(c, "会出错的问题",
                                headers={"X-QA-Conv-Id": cid})
                self.assertTrue(
                    any("error" in e for e in _chat_events(r2)))
            with self.subTest("错误轮落库为 JSON 原文（前置事实）"):
                rows = self._sql("SELECT role, content FROM messages ORDER BY id")
                self.assertEqual(rows[-1][0], "assistant")
                self.assertEqual(json.loads(rows[-1][1])["error"],
                                 "upstream_error")
            # regen：错误轮被删、新轮正常落
            r3 = self._chat(c, "会出错的问题",
                            headers={"X-QA-Conv-Id": cid, "X-QA-Regen": "1"})
            self.assertEqual(r3.headers.get("x-qa-conv-id"), cid)
            got = self._msgs_content(c, cid)
            with self.subTest("错误轮不残留，两轮干净"):
                self.assertEqual(len(got), 4)
                for m in got:
                    self.assertNotIn("upstream_error", m["content"])
                self.assertEqual(got[2]["content"], "会出错的问题")
                self.assertEqual(got[3]["content"], "你好！")


if __name__ == "__main__":
    unittest.main(verbosity=2)
