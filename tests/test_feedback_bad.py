# -*- coding: utf-8 -*-
"""差评回流供弹线（feedback_bad_enabled，默认 true）后端面单测（扩源形状战
v5 计划 §2 决策位⑥小施工，2026-10-17；零网络零 LLM/embedding，形态沿
tests/test_feedback.py（E1 先例）+tests/test_m5_paste_triage.py（开关面先例）。

覆盖：
  ① 键解析：默认**开**（无键=true——观察面非行为面，与 paste_triage 默认关
     相反、与 rerank_log_enabled 默认开同姿态）；显式 false=false；
  ② 路径解析：feedback_bad_path 可配；坏值/空串回默认 建库/logs/差评回流.jsonl；
  ③ _feedback_bad_append 纯落盘面：建目录自愈、一行 jsonl、OSError 返 False 不抛；
  ④ /api/feedback/bad 鉴权三态（沿 E1 点击路径先例=_conv_auth 同门）：无凭据
     401 auth_expired / 错口令 401 bad_passcode / cookie 或 X-QA-Passcode 头 200；
     开放态免门；
  ⑤ 限速复用 conv_hits 小表（429 形态对齐三会话端点；不占 /api/chat 预算）；
  ⑥ 校验：question/answer 必填字符串（缺失/非串/空白 → 400）；畸形 body 400；
  ⑦ jsonl 行字段最小化：{ts, conv_id, trace_id, question, answer, reasons}
     键集恰六枚（PII 最小化=无 IP/UA/device/note 面）+截长 2000/4000+
     reasons 白名单/去重/非列表忽略+trace 截 64+conv 头解析（坏值静默 NULL）；
  ⑧ journal：[feedback_bad] rating=down trace= conv= reasons= 在场、
     题面/答面内容绝不入日志；写失败 [feedback_bad] write_error=1 + 500
     persist_failed；
  ⑨ 开关关态零行为：404 not_found+零落盘+零打点+限速账不记（真零行为）；
  ⑩ 旁路性：关态/开态均不触 E1 /api/feedback 与 feedback 表（两线分账）。

每测试独立临时库+临时 jsonl 路径（绝不写 建库/logs/差评回流.jsonl 真档）。
TestClient 不进 with 上下文=不触发 lifespan 收尾关库（同 test_feedback）。"""
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


_BASE = {
    "model": "stub-model", "bot_name": "测试机",
    "max_history_messages": 5, "max_input_chars": 8000,
    "max_total_input_chars": 24000, "temperature": 0.7, "max_tokens": 100,
    "rate_limit_requests": 20, "rate_limit_window_seconds": 300,
}


def _cfg(**over):
    """缺省=开放态（无口令）+临时 jsonl 路径（防写真档）。"""
    cfg = dict(_BASE)
    cfg.setdefault("feedback_bad_path", over.pop(
        "_path", os.path.join(tempfile.mkdtemp(prefix="qabot-fb2-"),
                              "差评回流.jsonl")))
    cfg.update(over)
    return cfg


class T1FlagTest(unittest.TestCase):
    """① 键解析：默认开（观察面）；显式关。"""

    def test_default_on_without_key(self):
        cfg = {k: v for k, v in server.CONFIG.items()
               if k != "feedback_bad_enabled"}
        with mock.patch.object(server, "CONFIG", cfg):
            self.assertTrue(server._feedback_bad_enabled())  # 无键=默认开

    def test_explicit_off(self):
        cfg = {k: v for k, v in server.CONFIG.items()
               if k != "feedback_bad_enabled"}
        with mock.patch.object(server, "CONFIG",
                               {**cfg, "feedback_bad_enabled": False}):
            self.assertFalse(server._feedback_bad_enabled())


class T2PathTest(unittest.TestCase):
    """② 路径解析：可配+坏值回默认。"""

    def test_default_path(self):
        cfg = {k: v for k, v in server.CONFIG.items()
               if k != "feedback_bad_path"}
        with mock.patch.object(server, "CONFIG", cfg):
            self.assertEqual(
                server._feedback_bad_path(),
                os.path.join(server.BASE_DIR, "建库", "logs", "差评回流.jsonl"))

    def test_override_and_bad_values(self):
        cfg = {k: v for k, v in server.CONFIG.items()
               if k != "feedback_bad_path"}
        with mock.patch.object(server, "CONFIG",
                               {**cfg, "feedback_bad_path": "/tmp/x/y.jsonl"}):
            self.assertEqual(server._feedback_bad_path(), "/tmp/x/y.jsonl")
        for bad in ("", "   ", None, 123, True, [], {}):
            with mock.patch.object(server, "CONFIG",
                                   {**cfg, "feedback_bad_path": bad}):
                self.assertEqual(
                    server._feedback_bad_path(),
                    os.path.join(server.BASE_DIR, "建库", "logs",
                                 "差评回流.jsonl"), repr(bad))


class T3AppendTest(unittest.TestCase):
    """③ 纯落盘面：建目录自愈/一行 jsonl/OSError 返 False 不抛。"""

    def test_append_creates_dir_and_line(self):
        d = tempfile.mkdtemp(prefix="qabot-fb2-")
        p = os.path.join(d, "sub", "差评回流.jsonl")  # sub 不存在=建目录自愈面
        rec = {"ts": "2026-10-17 00:00:00", "conv_id": None, "trace_id": None,
               "question": "题面", "answer": "答面", "reasons": []}
        with mock.patch.object(server, "CONFIG",
                               {**dict(server.CONFIG),
                                "feedback_bad_path": p}):
            self.assertTrue(server._feedback_bad_append(rec))
            self.assertTrue(server._feedback_bad_append(rec))
        lines = [l for l in open(p, encoding="utf-8") if l.strip()]
        self.assertEqual(len(lines), 2)  # 追加制（非覆写）
        self.assertEqual(json.loads(lines[0]), rec)

    def test_append_oserror_returns_false(self):
        d = tempfile.mkdtemp(prefix="qabot-fb2-")
        blocker = os.path.join(d, "blocker")  # 占位文件：其"子路径"开目录必败
        open(blocker, "w").close()
        p = os.path.join(blocker, "sub", "x.jsonl")
        with mock.patch.object(server, "CONFIG",
                               {**dict(server.CONFIG),
                                "feedback_bad_path": p}):
            self.assertFalse(server._feedback_bad_append(
                {"ts": "x", "question": "q", "answer": "a", "reasons": []}))


class _FbBadBase(unittest.TestCase):
    """每测试一块全新临时库+独立 jsonl 路径（test_feedback._FbTestBase 同款）。"""

    def setUp(self):
        fd, self.db = tempfile.mkstemp(prefix="qabot-fb2-", suffix=".db")
        os.close(fd)
        server._store_inst = server._Store(self.db)
        self.fbdir = tempfile.mkdtemp(prefix="qabot-fb2-jsonl-")
        self.fbpath = os.path.join(self.fbdir, "差评回流.jsonl")

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
    def _ctx(self, cfg=None):
        with mock.patch.object(
                server, "CONFIG",
                cfg if cfg is not None else _cfg(feedback_bad_path=self.fbpath)):
            yield

    def _client(self):
        return TestClient(server.app)  # 不进 with：不触发 lifespan

    def _post(self, c, body=None, headers=None, **over):
        payload = {"question": "切换成功率怎么优化？", "answer": "答面正文。",
                   "reasons": ["missed_point"]}
        if body is not None:
            payload = body
        payload.update(over)
        return c.post("/api/feedback/bad", json=payload, headers=headers or {})


class T4AuthTest(_FbBadBase):
    """④ 鉴权三态（沿 E1 点击路径先例=_conv_auth 同门）。"""

    def test_no_credentials_401_auth_expired(self):
        with self._ctx(_cfg(passcode="pw", feedback_bad_path=self.fbpath)):
            r = self._client().post(
                "/api/feedback/bad", json={"question": "q", "answer": "a"})
            self.assertEqual(r.status_code, 401)
            self.assertEqual(r.json(), {"error": "auth_expired"})

    def test_wrong_passcode_401(self):
        with self._ctx(_cfg(passcode="pw", feedback_bad_path=self.fbpath)):
            r = self._client().post("/api/feedback/bad", json={
                "question": "q", "answer": "a", "passcode": "bad"})
            self.assertEqual(r.status_code, 401)
            self.assertEqual(r.json(), {"error": "bad_passcode"})

    def test_session_cookie_and_header_pass_ok(self):
        with self._ctx(_cfg(passcode="pw", feedback_bad_path=self.fbpath)):
            c = self._client()
            c.post("/api/login", json={"passcode": "pw"})
            with contextlib.redirect_stdout(open(os.devnull, "w")):
                r = c.post("/api/feedback/bad",
                           json={"question": "q", "answer": "a"})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json(), {"ok": True})
        with self._ctx(_cfg(passcode="pw", feedback_bad_path=self.fbpath)):
            c2 = self._client()  # 新客户端（无 cookie jar）走头
            r2 = c2.post("/api/feedback/bad",
                         json={"question": "q", "answer": "a"},
                         headers={"X-QA-Passcode": "pw"})
            self.assertEqual(r2.status_code, 200)
        self.assertEqual(len(self._lines()), 2)

    def test_open_mode_no_gate(self):
        with self._ctx():
            r = self._post(self._client())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"ok": True})

    def _lines(self):
        if not os.path.exists(self.fbpath):
            return []
        return [l for l in open(self.fbpath, encoding="utf-8") if l.strip()]


class T5RateTest(_FbBadBase):
    """⑤ 限速复用 conv_hits：429 形态+与三会话端点同账+不占 chat 预算。"""

    def test_rate_limit_429_and_shape(self):
        with self._ctx(), mock.patch.object(server, "CONV_RATE_LIMIT", 3):
            c = self._client()
            with contextlib.redirect_stdout(open(os.devnull, "w")):
                for i in range(3):
                    r = self._post(c)
                    self.assertEqual(r.status_code, 200, f"第{i + 1}次不应限流")
                r4 = self._post(c)
            self.assertEqual(r4.status_code, 429)
            self.assertEqual(r4.json(),
                             {"error": "rate_limited", "retry_after_s": 60})
        self.assertEqual(self._sql("SELECT COUNT(*) FROM conv_hits")[0][0], 3)
        self.assertEqual(self._sql("SELECT COUNT(*) FROM rate_hits")[0][0], 0)

    def test_shares_conv_hits_with_conversations(self):
        with self._ctx(), mock.patch.object(server, "CONV_RATE_LIMIT", 3):
            c = self._client()
            for _ in range(3):
                self.assertEqual(c.get("/api/conversations").status_code, 200)
            with contextlib.redirect_stdout(open(os.devnull, "w")):
                self.assertEqual(self._post(c).status_code, 429)


class T6ValidationTest(_FbBadBase):
    """⑥ question/answer 必填字符串；畸形 body 一律 400 bad_request。"""

    def test_bad_question_answer_values(self):
        with self._ctx():
            c = self._client()
            bads = [
                {"answer": "a"},                                  # 缺 question
                {"question": "q"},                                # 缺 answer
                {"question": "", "answer": "a"},                  # 空题面
                {"question": "   ", "answer": "a"},               # 空白题面
                {"question": "q", "answer": ""},                  # 空答面
                {"question": 123, "answer": "a"},                 # 非串题面
                {"question": "q", "answer": ["x"]},               # 非串答面
                {"question": None, "answer": None},
            ]
            for bad in bads:
                r = c.post("/api/feedback/bad", json=bad)
                with self.subTest(body=bad):
                    self.assertEqual(r.status_code, 400)
                    self.assertEqual(r.json(), {"error": "bad_request"})
        self.assertFalse(os.path.exists(self.fbpath))  # 全 400 零落盘

    def test_malformed_body(self):
        with self._ctx():
            c = self._client()
            with self.subTest("非 JSON 字节"):
                r = c.post("/api/feedback/bad", content=b"{not-json",
                           headers={"Content-Type": "application/json"})
                self.assertEqual(r.status_code, 400)
                self.assertEqual(r.json(), {"error": "bad_request"})
            with self.subTest("JSON 数组（非对象）"):
                r2 = c.post("/api/feedback/bad", json=[1, 2])
                self.assertEqual(r2.status_code, 400)
                self.assertEqual(r2.json(), {"error": "bad_request"})


class T7RecordTest(_FbBadBase):
    """⑦ jsonl 行字段最小化+截长+reasons 清洗+头解析。"""

    def _lines(self):
        return [json.loads(l) for l in open(self.fbpath, encoding="utf-8")
                if l.strip()]

    def test_full_round_field_set_minimal(self):
        with self._ctx():
            with contextlib.redirect_stdout(open(os.devnull, "w")):
                r = self._post(
                    self._client(), trace_id="ab12cd34",
                    headers={"X-QA-Conv-Id": "42"})
            self.assertEqual(r.status_code, 200)
        rows = self._lines()
        self.assertEqual(len(rows), 1)
        rec = rows[0]
        # PII 最小化硬断言：键集恰六枚（无 ip/ua/device/note/user 面）
        self.assertEqual(sorted(rec.keys()),
                         ["answer", "conv_id", "question", "reasons",
                          "trace_id", "ts"])
        self.assertIsInstance(rec["ts"], str)
        self.assertRegex(rec["ts"], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
        self.assertEqual(rec["conv_id"], 42)
        self.assertEqual(rec["trace_id"], "ab12cd34")
        self.assertEqual(rec["question"], "切换成功率怎么优化？")
        self.assertEqual(rec["answer"], "答面正文。")
        self.assertEqual(rec["reasons"], ["missed_point"])

    def test_truncation_q2000_a4000_trace64(self):
        q = "题" * 2500
        a = "答" * 5000
        with self._ctx():
            with contextlib.redirect_stdout(open(os.devnull, "w")):
                self._post(self._client(), question=q, answer=a,
                           trace_id="t" * 100)
        rec = self._lines()[0]
        self.assertEqual(len(rec["question"]), 2000)
        self.assertEqual(len(rec["answer"]), 4000)
        self.assertEqual(len(rec["trace_id"]), 64)

    def test_reasons_cleaning(self):
        with self._ctx():
            c = self._client()
            with contextlib.redirect_stdout(open(os.devnull, "w")):
                self._post(c, reasons=["no_source", "no_source", "hack",
                                       "missed_point", 1, None])
                self._post(c, reasons="missed_point")   # 非列表=整忽略
                # 缺省（body 无 reasons 键）=空表（_post 默认载荷带值，此处裸 body）
                c.post("/api/feedback/bad", json={"question": "q",
                                                  "answer": "a"})
        rows = self._lines()
        self.assertEqual(rows[0]["reasons"],
                         ["no_source", "missed_point"])  # 白名单+去重保序
        self.assertEqual(rows[1]["reasons"], [])
        self.assertEqual(rows[2]["reasons"], [])

    def test_conv_header_bad_values_null(self):
        with self._ctx():
            c = self._client()
            with contextlib.redirect_stdout(open(os.devnull, "w")):
                for hdr in ("abc", "99999999999999999999999", "-1", "0"):
                    r = self._post(c, headers={"X-QA-Conv-Id": hdr})
                    self.assertEqual(r.status_code, 200, hdr)
        cids = [r["conv_id"] for r in self._lines()]
        self.assertEqual(cids, [None, None, None, None])

    def test_path_configurable_via_key(self):
        alt = os.path.join(self.fbdir, "别处.jsonl")
        with self._ctx(_cfg(feedback_bad_path=alt)):
            with contextlib.redirect_stdout(open(os.devnull, "w")):
                self._post(self._client())
        self.assertTrue(os.path.exists(alt))
        self.assertFalse(os.path.exists(self.fbpath))


class T8JournalTest(_FbBadBase):
    """⑧ journal 行：计数键在场、内容绝不在场；写失败面。"""

    def test_journal_line_without_content(self):
        out = io.StringIO()
        with self._ctx():
            c = self._client()
            with contextlib.redirect_stdout(out):
                c.post("/api/feedback/bad", json={
                    "question": "绝不能进日志的题面XYZ",
                    "answer": "绝不能进日志的答面UVW",
                    "reasons": ["no_source", "other"], "trace_id": "ff00a1b2"},
                    headers={"X-QA-Conv-Id": "7"})
        lines = [ln for ln in out.getvalue().splitlines()
                 if ln.startswith("[feedback_bad]")]
        self.assertEqual(len(lines), 1)
        with self.subTest("rating= trace= conv= reasons= 四键在"):
            self.assertIn("rating=down", lines[0])
            self.assertIn("trace=ff00a1b2", lines[0])
            self.assertIn("conv=7", lines[0])
            self.assertIn("reasons=no_source,other", lines[0])
        with self.subTest("题面/答面内容绝不入日志"):
            self.assertNotIn("题面XYZ", lines[0])
            self.assertNotIn("答面UVW", lines[0])

    def test_journal_empty_reasons_dash(self):
        out = io.StringIO()
        with self._ctx():
            with contextlib.redirect_stdout(out):
                self._post(self._client(), reasons=[])
        line = [ln for ln in out.getvalue().splitlines()
                if ln.startswith("[feedback_bad]")][0]
        self.assertIn("reasons=-", line)
        self.assertIn("conv=-", line)

    def test_persist_failure_500_and_journal(self):
        blocker = os.path.join(self.fbdir, "blocker")
        open(blocker, "w").close()
        bad_path = os.path.join(blocker, "sub", "x.jsonl")
        out = io.StringIO()
        with self._ctx(_cfg(feedback_bad_path=bad_path)):
            with contextlib.redirect_stdout(out):
                r = self._post(self._client())
        self.assertEqual(r.status_code, 500)
        self.assertEqual(r.json(), {"error": "persist_failed"})
        err_lines = [ln for ln in out.getvalue().splitlines()
                     if ln.startswith("[feedback_bad]")]
        self.assertEqual(len(err_lines), 1)              # 打点恰一行
        self.assertIn("write_error=1", err_lines[0])


class T9DisabledTest(_FbBadBase):
    """⑨ 开关关态零行为：404+零落盘+零打点+限速账不记。"""

    def test_disabled_404_zero_behavior(self):
        out = io.StringIO()
        with self._ctx(_cfg(feedback_bad_enabled=False,
                            feedback_bad_path=self.fbpath)):
            c = self._client()
            with contextlib.redirect_stdout(out):
                for _ in range(3):  # 连打三轮：conv_hits 也不记（真零行为）
                    r = self._post(c)
            self.assertEqual(r.status_code, 404)
            self.assertEqual(r.json(), {"error": "not_found"})
        self.assertFalse(os.path.exists(self.fbpath))       # 零落盘
        self.assertNotIn("[feedback_bad]", out.getvalue())  # 零打点
        self.assertEqual(
            self._sql("SELECT COUNT(*) FROM conv_hits")[0][0], 0)  # 零限速账

    def test_disabled_then_enabled_recovers(self):
        with self._ctx(_cfg(feedback_bad_enabled=False,
                            feedback_bad_path=self.fbpath)):
            c = self._client()
            with contextlib.redirect_stdout(open(os.devnull, "w")):
                self.assertEqual(self._post(c).status_code, 404)
        with self._ctx(_cfg(feedback_bad_path=self.fbpath)):
            with contextlib.redirect_stdout(open(os.devnull, "w")):
                self.assertEqual(self._post(c).status_code, 200)
        self.assertEqual(len(self._lines()), 1)

    def _lines(self):
        if not os.path.exists(self.fbpath):
            return []
        return [l for l in open(self.fbpath, encoding="utf-8") if l.strip()]


class T10BypassTest(_FbBadBase):
    """⑩ 旁路性：feedback/bad 不触 E1 /api/feedback 与 feedback 表（两线分账）。"""

    def test_e1_endpoint_and_table_untouched(self):
        with self._ctx():
            c = self._client()
            with contextlib.redirect_stdout(open(os.devnull, "w")):
                r1 = c.post("/api/feedback", json={"rating": "up"})
                r2 = self._post(c)          # 差评回流一笔
                r3 = c.post("/api/feedback", json={"rating": "down"})
            self.assertEqual(r1.status_code, 200)
            self.assertEqual(r2.status_code, 200)
            self.assertEqual(r3.status_code, 200)
        self.assertEqual(
            self._sql("SELECT COUNT(*) FROM feedback")[0][0], 2)  # E1 两笔
        self.assertEqual(len(self._lines()), 1)          # 差评回流一笔（jsonl）

    def test_badfb_disabled_e1_still_works(self):
        with self._ctx(_cfg(feedback_bad_enabled=False,
                            feedback_bad_path=self.fbpath)):
            c = self._client()
            with contextlib.redirect_stdout(open(os.devnull, "w")):
                self.assertEqual(self._post(c).status_code, 404)
                r = c.post("/api/feedback", json={"rating": "up"})
            self.assertEqual(r.status_code, 200)  # E1 不受开关键影响
        self.assertEqual(self._sql("SELECT COUNT(*) FROM feedback")[0][0], 1)

    def _lines(self):
        if not os.path.exists(self.fbpath):
            return []
        return [l for l in open(self.fbpath, encoding="utf-8") if l.strip()]


if __name__ == "__main__":
    unittest.main(verbosity=2)
