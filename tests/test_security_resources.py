# -*- coding: utf-8 -*-
"""C1 安全套件·资源滥用面（2026-10-07 施工，只新建测试件不改产品码）。
C1 安全套件·CI 差集核验后应干净树绿。

覆盖：
  ① 超大载荷导入拒收不 OOM：10MB 单串 content（>16000 上限）→ 400 秒回、
     零落库；条数 201（>200 帽）→ 400；
  ② 超深/畸形 JSON 拒收：5000 层嵌套（解析层 RecursionError 被兜成 400）、
     800 层可解析深嵌套（形态校验 400）、垃圾字节（非 JSON）→ 400，
     全程无 500；/api/login 同面（bad_json）；
  ③ 单 device 建会话超阈行为断言（当前实际行为+注记）：无逐 device 创建
     上限，唯一阈值=列表返回 50 帽（CONVERSATIONS_LIMIT）——55 条直建后
     列表只回最新 50、降序、创建面不受阻；
  ④ 预留"长连接事件循环健康"占位用例（skip 标注"与 B2 合并"）。

跑法（仓根）：
    cd <repo> && venv/bin/python -m tests.test_security_resources
零网络零计费（无 LLM 调用——import 端点零 LLM，本件不触 /api/chat 上游）；
每测试独立临时库（server._store_inst 直注入），不碰 data/qa.db；
默认开放态（无口令，占位零密件）聚焦载荷防御面。"""
import contextlib
import os
import sqlite3
import tempfile
import time
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import server  # 仓根模块（tests/__init__.py 已做 sys.path 引导+QABOT_DB_PATH 隔离）

STUB_PW = "stub-passcode"   # 占位口令（纪律⑤：测试零密件）

IMPORT_URL = "/api/conversations/import"


# ---------- 配置底座（请求时读 server.CONFIG，逐测试 patch） ----------
_BASE = {
    "model": "stub-model", "bot_name": "测试机",
    "max_history_messages": 5, "max_input_chars": 8000,
    "max_total_input_chars": 24000, "temperature": 0.7, "max_tokens": 100,
    "rate_limit_requests": 20, "rate_limit_window_seconds": 300,
}


def _cfg(**over):
    cfg = dict(_BASE, passcode="")  # 开放态：聚焦载荷防御面不掺鉴权变量
    cfg.update(over)
    return cfg


class _SecTestBase(unittest.TestCase):
    """每测试一块全新临时库：server._store_inst 直注入 + 退出复位（不碰 data/qa.db）。"""

    def setUp(self):
        fd, self.db = tempfile.mkstemp(prefix="qabot-sec-res-", suffix=".db")
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
    def _ctx(self, cfg):
        with contextlib.ExitStack() as stack:
            for p in (mock.patch.object(server, "CONFIG", cfg),
                      mock.patch.object(server, "API_KEY", "stub-key"),
                      mock.patch.object(server, "rag_service", None)):
                stack.enter_context(p)
            yield


class T1OversizedPayloadTest(_SecTestBase):
    """① 超大载荷拒收不 OOM：校验线先于任何落库/放大。"""

    def test_10mb_single_string_rejected_fast(self):
        big = "A" * (10 * 1024 * 1024)  # 10MB 单串 content
        c = TestClient(server.app)
        with self._ctx(_cfg()):
            t0 = time.time()
            r = c.post(IMPORT_URL,
                       json={"messages": [{"role": "user", "content": big}]})
            elapsed = time.time() - t0
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json(), {"error": "bad_request"})
        # 拒收即返回：零落库（无存储放大），耗时秒级护栏（防回归成解析放大）
        self.assertEqual(
            self._sql("SELECT COUNT(*) FROM conversations")[0][0], 0)
        self.assertLess(elapsed, 30.0, f"拒收路径过慢：{elapsed:.1f}s")

    def test_message_count_over_200_rejected(self):
        msgs = [{"role": "user", "content": "x"} for _ in range(201)]
        c = TestClient(server.app)
        with self._ctx(_cfg()):
            r = c.post(IMPORT_URL, json={"messages": msgs})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json(), {"error": "bad_request"})
        self.assertEqual(
            self._sql("SELECT COUNT(*) FROM conversations")[0][0], 0)


class T2DeepMalformedJsonTest(_SecTestBase):
    """② 超深/畸形 JSON 拒收：任何解析层失败都兜成 400，绝无 500。"""

    def test_5000_level_nesting_rejected_not_500(self):
        # 5000 层嵌套：json 解析层 RecursionError 被端点兜成 400
        raw = '{"a":' * 5000 + "1" + "}" * 5000
        c = TestClient(server.app)
        with self._ctx(_cfg()):
            r = c.post(IMPORT_URL, content=raw.encode("utf-8"),
                       headers={"content-type": "application/json"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json(), {"error": "bad_request"})

    def test_800_level_parseable_nesting_rejected_by_shape(self):
        # 800 层（解析器递归限内）可解析，但 messages 形态校验拒 → 400
        raw = '{"messages":' + '[' * 800 + ']' * 800 + "}"
        c = TestClient(server.app)
        with self._ctx(_cfg()):
            r = c.post(IMPORT_URL, content=raw.encode("utf-8"),
                       headers={"content-type": "application/json"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json(), {"error": "bad_request"})

    def test_garbage_bytes_rejected_on_import_and_login(self):
        # 垃圾字节（非 JSON）：import → 400 bad_request；login → 400 bad_json
        garbage = b"\x00\xff garbage \xfe\x80"
        c = TestClient(server.app)
        with self._ctx(_cfg()):
            r = c.post(IMPORT_URL, content=garbage,
                       headers={"content-type": "application/json"})
            self.assertEqual(r.status_code, 400)
            self.assertEqual(r.json(), {"error": "bad_request"})
        with self._ctx(_cfg(passcode=STUB_PW)):
            r2 = c.post("/api/login", content=garbage,
                        headers={"content-type": "application/json"})
            self.assertEqual(r2.status_code, 400)
            self.assertEqual(r2.json(), {"error": "bad_json"})


class T3DeviceConversationOverageTest(_SecTestBase):
    """③ 单 device 建会话超阈：当前实际行为断言（注记）。"""

    def test_single_device_conversation_overage_current_behavior(self):
        # 当前实际行为注记（2026-10-07 存档）：单 device 建会话数无逐 device
        # 创建闸（可无限建，DB 行数只受 messages 5 万惰性帽间接约束）；唯一
        # 阈值=列表返回 50 帽（CONVERSATIONS_LIMIT，updated_at desc）。本用例
        # 锁该现状：55 条直建 → 创建面全成功，列表只回最新 50、降序、无 500。
        dev = "dev-overage-stub"
        store = server._store_inst
        for i in range(55):
            store.create_conversation(dev, f"会话{i}")
        c = TestClient(server.app)
        c.cookies.set(server.DEVICE_COOKIE, dev)
        with self._ctx(_cfg()):
            r = c.get("/api/conversations")
        self.assertEqual(r.status_code, 200)
        rows = r.json()["conversations"]
        self.assertEqual(len(rows), 50)               # 列表 50 帽
        ids = [row["id"] for row in rows]
        self.assertEqual(set(ids), set(range(6, 56)))  # 最新 50 条
        self.assertEqual(ids[0], 55)                   # 降序首=最新
        with self.subTest("创建面无上限（当前实际行为，注记存档）"):
            self.assertEqual(
                self._sql("SELECT COUNT(*) FROM conversations")[0][0], 55)


class T4PlaceholderTest(_SecTestBase):
    """④ 预留占位：长连接/事件循环健康面（B2 专项合并施工后补）。"""

    @unittest.skip("与 B2 合并")
    def test_long_connection_event_loop_health_placeholder(self):
        """占位用例：SSE 长连接持流期间事件循环健康度（挂起任务/定时器/
        取消传播）待 B2 专项施工后补齐断言面。"""
        self.fail("占位用例不应被执行")


if __name__ == "__main__":
    unittest.main()
