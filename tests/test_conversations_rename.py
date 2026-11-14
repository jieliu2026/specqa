# -*- coding: utf-8 -*-
"""二期批次C C1 会话重命名 + C2 最近活跃排序机制面防退化·后端面单测
（2026-10-03，零网络零 LLM/embedding，每测试独立临时库，不碰 data/qa.db；
判据预登记=运营/前端二期-批次C-20261003/判据预登记.md（§一 C1 服务端契约+
§〇 C2 核实结论：排序机制已达标，唯一缺口=append 内联 touch 无断言，故收敛为
机制面防退化测试——直改库只用于设基线，断言看真机制效果，不重蹈 T4 断言前
重写排序键的覆辙））。

覆盖（C 判据 §一 后端测试判据 1-7）：
  ① 主路径：重命名成功 {"ok":true}（不回显 title）→ 列表端点反映新标题 →
     messages 端点所在会话照常 → **updated_at 不变**（时间断言容差处理=直改库
     设基线时间后断言 rename 前后 updated_at 相等；last_msg_id 同不动）→
     journal [conv] rename 行（标题内容绝不入日志）；
  ② title 校验：空串/纯空白 → 400 bad_request 且库内标题保持原值；非 string
     （缺键/数字/数组/对象）→ 400；恰 100 全存；超 100 服务端截断到 100 入库；
     strip 后入库（首尾空白剥除）；
  ③ 归属与 id 面：非本 device 的 conv id → 404 not_found 且原标题无损；
     非整数 id/超 2^63-1 巨整数/不存在 id → 404；
  ④ 开关与鉴权面：conversations_enabled=false → 404（未过级也 404）；未过级
     → 401 三态（auth_expired/bad_passcode/login_required）对齐三端点；
     口令 cookie/头双轨过级 200；
  ⑤ 限速面：与既有会话端点同账（conv_hits 合计超限 → 429）；
  ⑥ C2 机制面防退化·append 内联 touch：两会话 A 老 B 新 → 直改库把 B 的
     updated_at 设旧于 A（基线）→ 对 B 会话经 _Store.append_message 真落一条
     → 断言 B 的 updated_at>基线、last_msg_id 推进、get_conversations 首位
     翻转到 B（测的是 append 内联 touch 机制，不是直改库造态）；
  ⑦ C2 机制面防退化·regen 删轮 touch：delete_last_round 删末轮后顺手 touch
     （updated_at 推进、last_msg_id 回落现存末条）。

TestClient 不进 with 上下文=不触发 lifespan 收尾关库（同 test_conversations）。
用法：
    <repo>/venv/bin/python -m tests.test_conversations_rename
"""
import contextlib
import io
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import server  # 仓根模块（tests/__init__.py 已做 sys.path 引导+QABOT_DB_PATH 隔离）


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


# C2 机制面基线：过去的严格分开时刻（远小于 time.time()，确定性排序）
T_OLD_A = 1_600_000_000.0   # 会话 A 基线（较新）
T_OLD_B = 1_500_000_000.0   # 会话 B 基线（较旧）


class _RenameTestBase(unittest.TestCase):
    """每测试一块全新临时库：server._store_inst 直注入 + 退出复位。"""

    def setUp(self):
        fd, self.db = tempfile.mkstemp(prefix="qabot-ren-", suffix=".db")
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
    def _ctx(self, cfg=None):
        """统一 patch 面：CONFIG/API_KEY/伪上游/rag 桩（ExitStack 一次进出）。"""
        with contextlib.ExitStack() as stack:
            for p in (mock.patch.object(server, "CONFIG", cfg if cfg is not None else _cfg()),
                      mock.patch.object(server, "API_KEY", "stub-key"),
                      mock.patch.object(server.httpx, "AsyncClient", _FastClient),
                      mock.patch.object(server, "rag_service", None)):
                stack.enter_context(p)
            yield

    def _client(self):
        """不进 with：不触发 lifespan（避免收尾把隔离 _Store 关掉置 None）。"""
        return TestClient(server.app)

    def _mk_conv(self, device="devA", title="旧标题", rounds=1):
        """直造一会话（store 既有方法）→ (conv_id, 末消息 id)。"""
        store = server._store_inst
        cid = store.create_conversation(device, title)
        last = None
        for _ in range(rounds):
            store.append_message(cid, "user", "问", None)
            last = store.append_message(cid, "assistant", "答", None)
        return cid, last

    def _patch_title(self, c, cid, title):
        return c.patch(f"/api/conversations/{cid}", json={"title": title})


# ---------- 伪上游：即时流（本件端点面用不到 LLM，仅保 _ctx patch 形态齐整） ----------
class _FastStream:
    status_code = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def aiter_lines(self):
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


class T1RenameMainTest(_RenameTestBase):
    """① 主路径：重命名成功、列表反映新标题、updated_at/last_msg_id 不动。"""

    BASELINE = 1_600_000_000.0  # 过去基线（远小于 time.time()，零时钟竞态）

    def test_rename_ok_and_ordering_keys_untouched(self):
        cid, last_mid = self._mk_conv(title="旧标题")
        self._sql("UPDATE conversations SET updated_at=? WHERE id=?",
                  (self.BASELINE, cid))
        out = io.StringIO()
        with self._ctx():
            c = self._client()
            c.cookies.set("qabot_device", "devA")
            with contextlib.redirect_stdout(out):
                r = self._patch_title(c, cid, "新标题")
            with self.subTest("200 且只回 {ok}（不回显 title，对齐 DELETE 形态）"):
                self.assertEqual(r.status_code, 200, r.text)
                self.assertEqual(r.json(), {"ok": True})
            with self.subTest("列表端点反映新标题"):
                rl = c.get("/api/conversations")
                self.assertEqual(rl.status_code, 200)
                conv = rl.json()["conversations"][0]
                self.assertEqual(conv["id"], cid)
                self.assertEqual(conv["title"], "新标题")
            with self.subTest("messages 端点所在会话照常"):
                rm = c.get(f"/api/conversations/{cid}/messages")
                self.assertEqual(rm.status_code, 200)
                self.assertTrue(rm.json()["ok"])
        with self.subTest("直读库：updated_at=基线原值（rename 不 touch 排序键）"):
            row = self._sql(
                "SELECT title, updated_at, last_msg_id FROM conversations "
                "WHERE id=?", (cid,))[0]
            self.assertEqual(row[0], "新标题")
            self.assertEqual(row[1], self.BASELINE)
            self.assertEqual(row[2], last_mid)
        with self.subTest("journal：[conv] rename 行在、标题内容绝不入日志"):
            lines = [ln for ln in out.getvalue().splitlines()
                     if ln.startswith("[conv] rename")]
            self.assertEqual(len(lines), 1)
            self.assertIn("ok=1", lines[0])
            self.assertNotIn("新标题", lines[0])


class T2RenameTitleValidationTest(_RenameTestBase):
    """② title 校验：空/非 string 400（库内保持原值）；截断与边界。"""

    def test_empty_and_blank_400_keep_original(self):
        cid, _ = self._mk_conv(title="旧标题")
        with self._ctx():
            c = self._client()
            c.cookies.set("qabot_device", "devA")
            for bad in ("", "   "):
                with self.subTest(title=repr(bad)):
                    r = self._patch_title(c, cid, bad)
                    self.assertEqual(r.status_code, 400)
                    self.assertEqual(r.json(), {"error": "bad_request"})
        self.assertEqual(
            self._sql("SELECT title FROM conversations WHERE id=?",
                      (cid,))[0][0], "旧标题")

    def test_non_string_400(self):
        cid, _ = self._mk_conv(title="旧标题")
        with self._ctx():
            c = self._client()
            c.cookies.set("qabot_device", "devA")
            with self.subTest("缺键"):
                r = c.patch(f"/api/conversations/{cid}", json={})
                self.assertEqual(r.status_code, 400)
                self.assertEqual(r.json(), {"error": "bad_request"})
            for bad in (123, ["x"], {"a": 1}, True):
                with self.subTest(title=bad):
                    r = self._patch_title(c, cid, bad)
                    self.assertEqual(r.status_code, 400)
                    self.assertEqual(r.json(), {"error": "bad_request"})
        self.assertEqual(
            self._sql("SELECT title FROM conversations WHERE id=?",
                      (cid,))[0][0], "旧标题")

    def test_length_boundary_and_strip(self):
        cid, _ = self._mk_conv(title="旧标题")
        with self._ctx():
            c = self._client()
            c.cookies.set("qabot_device", "devA")
            with self.subTest("恰 100 字符全存"):
                t100 = "百" * 100
                r = self._patch_title(c, cid, t100)
                self.assertEqual(r.status_code, 200)
                self.assertEqual(
                    self._sql("SELECT title FROM conversations WHERE id=?",
                              (cid,))[0][0], t100)
            with self.subTest("超 100 → 服务端截断到 100 入库（不 400）"):
                r = self._patch_title(c, cid, "千" * 105)
                self.assertEqual(r.status_code, 200)
                self.assertEqual(
                    self._sql("SELECT title FROM conversations WHERE id=?",
                              (cid,))[0][0], "千" * 100)
            with self.subTest("strip 后入库（首尾空白剥除）"):
                r = self._patch_title(c, cid, "  新标题  ")
                self.assertEqual(r.status_code, 200)
                self.assertEqual(
                    self._sql("SELECT title FROM conversations WHERE id=?",
                              (cid,))[0][0], "新标题")
        with self.subTest("畸形 body（非 JSON/非对象）400"):
            with self._ctx():
                c2 = self._client()
                c2.cookies.set("qabot_device", "devA")
                r1 = c2.patch(f"/api/conversations/{cid}",
                              content=b"{not-json",
                              headers={"Content-Type": "application/json"})
                self.assertEqual(r1.status_code, 400)
                self.assertEqual(r1.json(), {"error": "bad_request"})
                r2 = c2.patch(f"/api/conversations/{cid}", json=[1, 2])
                self.assertEqual(r2.status_code, 400)
                self.assertEqual(r2.json(), {"error": "bad_request"})


class T3RenameOwnershipIdTest(_RenameTestBase):
    """③ 归属与 id 面：非本 device 404 且原标题无损；id 面三态 404。"""

    def test_cross_device_404_keep_original(self):
        cid, _ = self._mk_conv(device="devA", title="A 的标题")
        with self._ctx():
            cb = self._client()
            cb.cookies.set("qabot_device", "devB")
            r = self._patch_title(cb, cid, "B 想改的名")
            self.assertEqual(r.status_code, 404)
            self.assertEqual(r.json(), {"error": "not_found"})
        self.assertEqual(
            self._sql("SELECT title FROM conversations WHERE id=?",
                      (cid,))[0][0], "A 的标题")

    def test_bad_and_missing_ids_404(self):
        cid, _ = self._mk_conv(device="devA", title="旧标题")
        with self._ctx():
            c = self._client()
            c.cookies.set("qabot_device", "devA")
            for path in ("/api/conversations/abc",            # 非整数
                         "/api/conversations/99999999999999999999999",  # 超 64 位绑定域
                         "/api/conversations/999"):           # 不存在
                with self.subTest(path=path):
                    r = c.patch(path, json={"title": "x"})
                    self.assertEqual(r.status_code, 404)
                    self.assertEqual(r.json(), {"error": "not_found"})
        self.assertEqual(
            self._sql("SELECT title FROM conversations WHERE id=?",
                      (cid,))[0][0], "旧标题")


class T4RenameGateTest(_RenameTestBase):
    """④ 开关与鉴权面：关=404 先于鉴权；401 三态对齐三端点；口令双轨过级。"""

    def test_disabled_404(self):
        cid, _ = self._mk_conv(title="旧标题")
        with self._ctx(_cfg(conversations_enabled=False)):
            c = self._client()
            c.cookies.set("qabot_device", "devA")
            r = self._patch_title(c, cid, "改名")  # 开放态无凭据也 404（回退键先于鉴权）
            self.assertEqual(r.status_code, 404)
            self.assertEqual(r.json(), {"error": "not_found"})
        self.assertEqual(
            self._sql("SELECT title FROM conversations WHERE id=?",
                      (cid,))[0][0], "旧标题")

    def test_unauthorized_three_states(self):
        cid, _ = self._mk_conv(title="旧标题")
        with self._ctx(_cfg(passcode="pw")):
            c = self._client()
            c.cookies.set("qabot_device", "devA")
            with self.subTest("无凭据 → auth_expired"):
                r = self._patch_title(c, cid, "x")
                self.assertEqual(r.status_code, 401)
                self.assertEqual(r.json(), {"error": "auth_expired"})
            with self.subTest("错口令 → bad_passcode"):
                r = c.patch(f"/api/conversations/{cid}",
                            json={"title": "x", "passcode": "bad"})
                self.assertEqual(r.status_code, 401)
                self.assertEqual(r.json(), {"error": "bad_passcode"})
            with self.subTest("body 口令轨过级 → 200"):
                r = c.patch(f"/api/conversations/{cid}",
                            json={"title": "口令改名", "passcode": "pw"})
                self.assertEqual(r.status_code, 200, r.text)
                self.assertEqual(r.json(), {"ok": True})
        with self._ctx(_cfg(passcode="pw", passcode_body_enabled=False)):
            c2 = self._client()  # 新客户端（无 cookie jar）
            with self.subTest("body 口令收口态 → login_required（头轨同收）"):
                r = c2.patch(f"/api/conversations/{cid}",
                             json={"title": "x", "passcode": "pw"})
                self.assertEqual(r.status_code, 401)
                self.assertEqual(r.json(), {"error": "login_required"})
        with self._ctx(_cfg(passcode="pw")):
            c3 = self._client()  # 新客户端（无 cookie jar）：X-QA-Passcode 头轨
            c3.cookies.set("qabot_device", "devA")
            with self.subTest("X-QA-Passcode 头轨过级 → 200"):
                r = c3.patch(f"/api/conversations/{cid}", json={"title": "头轨改名"},
                             headers={"X-QA-Passcode": "pw"})
                self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(
            self._sql("SELECT title FROM conversations WHERE id=?",
                      (cid,))[0][0], "头轨改名")


class T5RenameRateTest(_RenameTestBase):
    """⑤ 限速同账：conv_hits 与既有会话端点合计超限 → 429（复用 feedback 桩法）。"""

    def test_shared_conv_hits_429(self):
        cid, _ = self._mk_conv(title="旧标题")
        with self._ctx(), mock.patch.object(server, "CONV_RATE_LIMIT", 3):
            c = self._client()
            c.cookies.set("qabot_device", "devA")
            for _ in range(3):  # 会话端点打满（限 3）——共享账本
                self.assertEqual(c.get("/api/conversations").status_code, 200)
            r = self._patch_title(c, cid, "改名")
            self.assertEqual(r.status_code, 429)
            self.assertEqual(r.json(),
                             {"error": "rate_limited", "retry_after_s": 60})
        self.assertEqual(self._sql("SELECT COUNT(*) FROM conv_hits")[0][0], 3)
        self.assertEqual(
            self._sql("SELECT title FROM conversations WHERE id=?",
                      (cid,))[0][0], "旧标题")


class T6TouchMechanismTest(_RenameTestBase):
    """⑥⑦ C2 机制面防退化：append 内联 touch 推进排序键、删轮顺手 touch。

    写法纪律（C 判据 §〇）：直改库只用于设基线，断言看真机制效果——
    若有人把 append_message 内联的 UPDATE conversations SET updated_at 拆掉，
    下列断言即红（T4ListOrderCapTest 的排序断言全在直改库重写 updated_at
    之后做，测不出该退化——本类补的就是这个缺口）。"""

    def test_append_inline_touch_flips_order(self):
        store = server._store_inst
        cid_a = store.create_conversation("devA", "会话A（老）")
        store.append_message(cid_a, "user", "A 的问", None)
        cid_b = store.create_conversation("devA", "会话B（新）")
        store.append_message(cid_b, "user", "B 的问", None)
        # 直改库设基线：B 的 updated_at 旧于 A（A 在顶、B 沉底——只设基线，断言不动它）
        self._sql("UPDATE conversations SET updated_at=? WHERE id=?",
                  (T_OLD_A, cid_a))
        self._sql("UPDATE conversations SET updated_at=? WHERE id=?",
                  (T_OLD_B, cid_b))
        with self.subTest("基线形态：A 在顶（前置事实）"):
            self.assertEqual([r["id"] for r in store.get_conversations("devA")],
                             [cid_a, cid_b])
        # 真机制：对 B 会话经 _Store.append_message 落一条（不直改库）
        new_mid = store.append_message(cid_b, "assistant", "B 的新答", None)
        row = self._sql(
            "SELECT updated_at, last_msg_id FROM conversations WHERE id=?",
            (cid_b,))[0]
        with self.subTest("append 推进 updated_at（>基线）"):
            self.assertGreater(row[0], T_OLD_B)
        with self.subTest("last_msg_id 推进到新消息"):
            self.assertEqual(row[1], new_mid)
        with self.subTest("get_conversations 首位翻转到 B（老会话 A 让顶）"):
            self.assertEqual([r["id"] for r in store.get_conversations("devA")],
                             [cid_b, cid_a])
        with self.subTest("A 的排序键原值未动"):
            self.assertEqual(
                self._sql("SELECT updated_at FROM conversations WHERE id=?",
                          (cid_a,))[0][0], T_OLD_A)

    def test_delete_last_round_touches(self):
        """regen 删轮后顺手 touch：updated_at 推进、last_msg_id 回落现存末条。"""
        store = server._store_inst
        cid, _ = self._mk_conv(title="删轮会话", rounds=2)  # 两轮四条
        a1 = self._sql(
            "SELECT id FROM messages WHERE conv_id=? ORDER BY id LIMIT 1 "
            "OFFSET 1", (cid,))[0][0]  # round1 assistant（删轮后现存的末条）
        self._sql("UPDATE conversations SET updated_at=? WHERE id=?",
                  (T_OLD_B, cid))
        with self.subTest("删末轮（round2 的 user+assistant）"):
            self.assertEqual(store.delete_last_round(cid), 2)
        row = self._sql(
            "SELECT updated_at, last_msg_id FROM conversations WHERE id=?",
            (cid,))[0]
        with self.subTest("删轮也 touch：updated_at > 基线"):
            self.assertGreater(row[0], T_OLD_B)
        with self.subTest("last_msg_id 回落现存末条（round1 assistant）"):
            self.assertEqual(row[1], a1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
