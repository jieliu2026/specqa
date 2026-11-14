# -*- coding: utf-8 -*-
"""批次E 反馈闭环+追问同流尾巴·后端面单测（2026-10-03，零网络零 LLM/embedding，
伪 httpx 上游同 test_conversations 形态；每测试独立临时库，不碰 data/qa.db）。

覆盖（施工单 E1+E2）：
  ① /api/feedback 鉴权三态：无凭据 401 auth_expired / 错口令 401 bad_passcode /
     会话 cookie 或 X-QA-Passcode 头过级 200（开放态免门）；
  ② 限速：复用 conv_hits 小表（与三会话端点同账 60 次/分；patch 上限打满 429，
     不占 /api/chat 的 rate_hits 预算）；
  ③ rating 白名单（缺失/非法值 400 bad_request）与畸形 body（非 JSON/非对象 400）；
  ④ note 截长 500 字符 + conv 头解析（合法 int 落库、巨整数/非整数静默 NULL）；
  ⑤ feedback 表落库字段（ts REAL/trace_id/rating/note/conv_id 空态）与
     journal 行（rating= trace= conv= 在、note 内容绝不入日志）；
  ⑥ trace 关联：/api/chat SSE 响应头 X-QA-Trace-Id 在（8 hex、与流首
     ": trace_id=" 注释行同值；X-QA-Conv-Id 也在——双头 additive 共存）；
  ⑦ E2 默认关=现行行为零变化（事件序逐字段一致、system 无尾巴指令段）；
  ⑧ E2 开=剥除与下发：标记跨 delta 拆半不漏发、标记后内容截留、done 后
     followups 事件（条目解析/丢弃规则）、无标记流悬尾补发；
  ⑨ 净文本三处作用：citation_gate 只看净正文（尾巴里的假摘录不进闸）、
     批次D 会话落库 content=净文本；
  ⑩ 纯函数面：_followup_holdback 前缀重叠 / _parse_followup_items 条数与长度规则。

TestClient 不进 with 上下文=不触发 lifespan 收尾关库（同 test_conversations）。"""
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


# ---------- 伪上游：可配置 delta 序列（E2 剥除面需要精细切分控制） ----------
CAPTURED = []  # 每次请求上送上游的 payload（system 消息断言用）


class _SeqStream:
    status_code = 200

    def __init__(self, deltas):
        self._deltas = list(deltas)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def aiter_lines(self):
        for tok in self._deltas:
            yield "data: " + json.dumps(
                {"choices": [{"delta": {"content": tok}}]}, ensure_ascii=False)
        yield "data: " + json.dumps(
            {"usage": {"total_tokens": 9}, "choices": []})
        yield "data: [DONE]"

    async def aread(self):
        return b""


class _SeqClient:
    """按请求次序轮换 delta 序列的多幕伪上游：类属性 SCRIPTS 为剧本队列
    （每个元素=一次请求的 delta 元组），用尽回退 ("你","好","！")。"""

    SCRIPTS = [("你", "好", "！")]

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def stream(self, method, url, json=None, headers=None, **k):
        CAPTURED.append(json)
        seq = self.SCRIPTS.pop(0) if self.SCRIPTS else ("你", "好", "！")
        return _SeqStream(seq)


SOURCES = [{"doc_id": "TS 36.331", "version": "V17", "locator": "§5.2.2",
            "score": 0.9, "quote": "T310 缺省值 1000 ms"}]
EVIDENCE = "以下为检索到的语料片段……\n\n[出处1] T310 缺省值 1000 ms"


class _HitSvc:
    """retrieve 恒 hit 的桩（⑨ gate 净文本面用）。"""
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


def _deltas(events):
    return "".join(e.get("delta", "") for e in events if "delta" in e)


class _FbTestBase(unittest.TestCase):
    """每测试一块全新临时库：server._store_inst 直注入 + 退出复位。"""

    def setUp(self):
        fd, self.db = tempfile.mkstemp(prefix="qabot-fb-", suffix=".db")
        os.close(fd)
        server._store_inst = server._Store(self.db)
        _SeqClient.SCRIPTS = [("你", "好", "！")]  # 剧本复位
        CAPTURED.clear()

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
    def _ctx(self, cfg=None, svc=None):
        """统一 patch 面：CONFIG/API_KEY/伪上游/rag 桩（ExitStack 一次进出）。"""
        with contextlib.ExitStack() as stack:
            for p in (mock.patch.object(server, "CONFIG", cfg if cfg is not None else _cfg()),
                      mock.patch.object(server, "API_KEY", "stub-key"),
                      mock.patch.object(server.httpx, "AsyncClient", _SeqClient),
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

    def _login_chat(self, cfg, text="问句", svc=None, headers=None):
        """口令态登录后发一问 → SSE 响应（E2 用例标配链）。"""
        with self._ctx(cfg, svc=svc):
            c = self._client()
            c.post("/api/login", json={"passcode": "pw"})
            return self._chat(c, text, headers=headers)


class T1FeedbackAuthTest(_FbTestBase):
    """① /api/feedback 鉴权三态（401 形态对齐 /api/chat；口令可走头）。"""

    def test_no_credentials_401_auth_expired(self):
        with self._ctx(_cfg(passcode="pw")):
            c = self._client()
            r = c.post("/api/feedback", json={"rating": "up"})
            self.assertEqual(r.status_code, 401)
            self.assertEqual(r.json(), {"error": "auth_expired"})

    def test_wrong_passcode_401(self):
        with self._ctx(_cfg(passcode="pw")):
            c = self._client()
            r = c.post("/api/feedback", json={"rating": "up", "passcode": "bad"})
            self.assertEqual(r.status_code, 401)
            self.assertEqual(r.json(), {"error": "bad_passcode"})

    def test_session_cookie_and_header_pass_ok(self):
        with self._ctx(_cfg(passcode="pw")):
            c = self._client()
            c.post("/api/login", json={"passcode": "pw"})
            with self.subTest("会话 cookie 过级"):
                r = c.post("/api/feedback", json={"rating": "up"})
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r.json(), {"ok": True})
        with self._ctx(_cfg(passcode="pw")):  # 新客户端（无 cookie jar）
            c2 = self._client()
            r2 = c2.post("/api/feedback", json={"rating": "down"},
                         headers={"X-QA-Passcode": "pw"})
            self.assertEqual(r2.status_code, 200)
            self.assertEqual(r2.json(), {"ok": True})
        self.assertEqual(self._sql("SELECT COUNT(*) FROM feedback")[0][0], 2)

    def test_open_mode_no_gate(self):
        """本地开放态（未配口令）免鉴权直接过（口径同 /api/health）。"""
        with self._ctx():
            c = self._client()
            r = c.post("/api/feedback", json={"rating": "up"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"ok": True})


class T2FeedbackRateTest(_FbTestBase):
    """② 限速复用 conv_hits：打满 429，形态对齐三会话端点；不占 chat 预算。"""

    def test_rate_limit_429_and_shape(self):
        with self._ctx(), mock.patch.object(server, "CONV_RATE_LIMIT", 3):
            c = self._client()
            for i in range(3):
                r = c.post("/api/feedback", json={"rating": "up"})
                self.assertEqual(r.status_code, 200, f"第{i + 1}次不应限流")
            r4 = c.post("/api/feedback", json={"rating": "up"})
            self.assertEqual(r4.status_code, 429)
            self.assertEqual(r4.json(),
                             {"error": "rate_limited", "retry_after_s": 60})
        self.assertEqual(self._sql("SELECT COUNT(*) FROM conv_hits")[0][0], 3)
        self.assertEqual(self._sql("SELECT COUNT(*) FROM rate_hits")[0][0], 0)

    def test_shares_conv_hits_with_conversations(self):
        """与三会话端点同账：会话端点打满后 feedback 也 429（复用=共用小表）。"""
        with self._ctx(), mock.patch.object(server, "CONV_RATE_LIMIT", 3):
            c = self._client()
            for _ in range(3):
                self.assertEqual(c.get("/api/conversations").status_code, 200)
            self.assertEqual(c.post("/api/feedback", json={"rating": "up"})
                             .status_code, 429)


class T3FeedbackValidationTest(_FbTestBase):
    """③ rating 白名单 + 畸形 body 一律 400 {"error":"bad_request"}。"""

    def test_bad_rating_values(self):
        with self._ctx(_cfg(passcode="pw")):
            c = self._client()
            c.post("/api/login", json={"passcode": "pw"})
            for bad in ("good", "", None, 1, ["up"], {"x": 1}, "UP"):
                r = c.post("/api/feedback", json={"rating": bad})
                with self.subTest(rating=bad):
                    self.assertEqual(r.status_code, 400)
                    self.assertEqual(r.json(), {"error": "bad_request"})

    def test_malformed_body(self):
        with self._ctx(_cfg(passcode="pw")):
            c = self._client()
            c.post("/api/login", json={"passcode": "pw"})
            with self.subTest("非 JSON 字节"):
                r = c.post("/api/feedback", content=b"{not-json",
                           headers={"Content-Type": "application/json"})
                self.assertEqual(r.status_code, 400)
                self.assertEqual(r.json(), {"error": "bad_request"})
            with self.subTest("JSON 数组（非对象）"):
                r2 = c.post("/api/feedback", json=[1, 2])
                self.assertEqual(r2.status_code, 400)
                self.assertEqual(r2.json(), {"error": "bad_request"})
        self.assertEqual(self._sql("SELECT COUNT(*) FROM feedback")[0][0], 0)


class T4FeedbackPersistTest(_FbTestBase):
    """④⑤ 表落库：note 截长、conv 头解析、空态、journal 行无 note 内容。"""

    def test_full_round_and_truncation(self):
        note = "反" * 600
        with self._ctx(_cfg(passcode="pw")):
            c = self._client()
            c.post("/api/login", json={"passcode": "pw"})
            with contextlib.redirect_stdout(open(os.devnull, "w")):
                r = c.post("/api/feedback", json={
                    "rating": "down", "trace_id": "ab12cd34", "note": note},
                    headers={"X-QA-Conv-Id": "42"})
            self.assertEqual(r.status_code, 200)
        rows = self._sql(
            "SELECT ts, trace_id, rating, note, conv_id FROM feedback")
        self.assertEqual(len(rows), 1)
        ts, tid, rating, noted, cid = rows[0]
        self.assertIsInstance(ts, float)
        self.assertGreater(ts, 0)
        self.assertEqual(tid, "ab12cd34")
        self.assertEqual(rating, "down")
        self.assertEqual(noted, "反" * 500)  # 截长 500
        self.assertEqual(cid, 42)
        # 开放态空态：无 trace/note/conv 头 → 三 NULL
        with self._ctx():
            c2 = self._client()
            c2.post("/api/feedback", json={"rating": "up"})
        row2 = self._sql("SELECT trace_id, note, conv_id FROM feedback "
                         "WHERE rating='up'")[0]
        self.assertEqual(row2, (None, None, None))

    def test_conv_header_bad_values_null(self):
        """非整数/巨整数（超 SQLite 绑定域）/越界 conv 头静默落 NULL，不 500。"""
        with self._ctx():
            c = self._client()
            for hdr in ("abc", "99999999999999999999999", "-1", "0"):
                r = c.post("/api/feedback", json={"rating": "up"},
                           headers={"X-QA-Conv-Id": hdr})
                self.assertEqual(r.status_code, 200, hdr)
        cids = [r[0] for r in self._sql("SELECT conv_id FROM feedback")]
        self.assertEqual(cids, [None, None, None, None])

    def test_journal_line_without_note(self):
        out = io.StringIO()
        with self._ctx():
            c = self._client()
            with contextlib.redirect_stdout(out):
                c.post("/api/feedback", json={
                    "rating": "down", "trace_id": "ff00a1b2",
                    "note": "这是绝不能进日志的隐私备注"})
        lines = [ln for ln in out.getvalue().splitlines()
                 if ln.startswith("[feedback]")]
        self.assertEqual(len(lines), 1)
        with self.subTest("rating= trace= conv= 三键在"):
            self.assertIn("rating=down", lines[0])
            self.assertIn("trace=ff00a1b2", lines[0])
            self.assertIn("conv=-", lines[0])
        with self.subTest("note 内容绝不入日志"):
            self.assertNotIn("隐私备注", lines[0])


class T5TraceHeaderTest(_FbTestBase):
    """⑥ /api/chat SSE 双响应头：X-QA-Trace-Id（8 hex，与流首注释行同值）。"""

    def test_trace_id_header_on_chat_sse(self):
        r = self._login_chat(_cfg(passcode="pw"), "trace 头验证")
        tid = r.headers.get("x-qa-trace-id", "")
        self.assertRegex(tid, r"^[0-9a-f]{8}$")
        with self.subTest("与 SSE 流首 ': trace_id=' 注释行同值"):
            first = [ln for ln in r.text.splitlines()
                     if ln.startswith(": trace_id=")][0]
            self.assertEqual(first, f": trace_id={tid}")
        with self.subTest("批次D X-QA-Conv-Id 仍在（双头 additive 共存）"):
            self.assertTrue(r.headers.get("x-qa-conv-id", "").isdigit())

    def test_feedback_round_trip_with_trace(self):
        """端到端关联链：chat 拿头 → feedback 带 trace_id → 落库同值。"""
        with self._ctx(_cfg(passcode="pw")):
            c = self._client()
            c.post("/api/login", json={"passcode": "pw"})
            r = self._chat(c)
            tid = r.headers.get("x-qa-trace-id")
            cid = r.headers.get("x-qa-conv-id")
            rf = c.post("/api/feedback", json={"rating": "up", "trace_id": tid},
                        headers={"X-QA-Conv-Id": cid})
            self.assertEqual(rf.status_code, 200)
        row = self._sql("SELECT trace_id, conv_id FROM feedback")[0]
        self.assertEqual(row, (tid, int(cid)))


class T6TailDefaultOffTest(_FbTestBase):
    """⑦ E2 默认关=现行行为零变化：事件序逐字段一致、system 无指令段。"""

    def test_off_identical_events_and_prompt(self):
        _SeqClient.SCRIPTS = [("你", "好", "！")]
        r = self._login_chat(_cfg(passcode="pw"))
        events = _chat_events(r)
        with self.subTest("事件序=deltas+done，无 followups"):
            types = [e.get("delta") if "delta" in e else
                     "done" if e.get("done") else e.get("type", "?") for e in events]
            self.assertEqual(types, ["你", "好", "！", "done"])
        self.assertEqual(_deltas(events), "你好！")
        with self.subTest("上送 system 无尾巴指令段"):
            sysc = CAPTURED[0]["messages"][0]["content"]
            self.assertNotIn("FOLLOWUP", sysc)


class T7TailStripTest(_FbTestBase):
    """⑧ E2 开=剥除与下发：跨 delta 拆半/截留/followups 事件/悬尾补发。"""

    ON = _cfg(passcode="pw", followup_tail_enabled=True)

    def test_marker_split_across_deltas(self):
        """标记被拆成两半：前半扣住不发、后半拼上后整体截留，净文本零泄漏。"""
        _SeqClient.SCRIPTS = [(
            "答案第一段。\n<<<FOLL", "OWUP>>>\n- 追问甲", "\n- 追问乙\n收尾杂行")]
        r = self._login_chat(self.ON, "拆半标记验证")
        events = _chat_events(r)
        self.assertEqual(_deltas(events), "答案第一段。")  # 标记连前导换行剥净
        self.assertNotIn("FOLLOWUP", r.text)
        fu = [e for e in events if e.get("type") == "followups"]
        self.assertEqual(len(fu), 1)
        self.assertEqual(fu[0]["items"], ["追问甲", "追问乙"])  # 杂行不成条目
        with self.subTest("事件序：followups 在 done 之后"):
            types = ["done" if e.get("done") else e.get("type", "?")
                     for e in events]
            self.assertLess(types.index("done"), types.index("followups"))
        with self.subTest("system 末尾追加指令段"):
            self.assertTrue(CAPTURED[0]["messages"][0]["content"]
                            .endswith(server.FOLLOWUP_TAIL_NOTE))

    def test_no_marker_flushes_tail(self):
        """模型没输出标记：扣住的悬尾是正文一部分，流结束补发；无 followups。"""
        _SeqClient.SCRIPTS = [("答案开头", "，继续说完", "。")]
        r = self._login_chat(self.ON, "无标记流验证")
        events = _chat_events(r)
        self.assertEqual(_deltas(events), "答案开头，继续说完。")
        self.assertEqual([e for e in events if e.get("type") == "followups"], [])

    def test_holdback_prefix_only(self):
        """正文以标记前缀片段收尾（如 "……见 38.331\n<<<"）：扣住补发不误删。"""
        _SeqClient.SCRIPTS = [("正文。见 TS 38.331", "\n<<<")]
        r = self._login_chat(self.ON, "悬尾前缀验证")
        events = _chat_events(r)
        self.assertEqual(_deltas(events), "正文。见 TS 38.331\n<<<")
        self.assertEqual([e for e in events if e.get("type") == "followups"], [])

    def test_discard_rules_for_followups(self):
        """条数>3 / 单条>200 字符 → followups 事件整体丢弃不发。"""
        _SeqClient.SCRIPTS = [(
            "答。\n<<<FOLLOWUP>>>", "\n- 问一\n- 问二\n- 问三\n- 问四")]
        r = self._login_chat(self.ON, "四条丢弃验证")
        self.assertEqual(_deltas(_chat_events(r)), "答。")
        self.assertEqual([e for e in _chat_events(r)
                          if e.get("type") == "followups"], [])
        _SeqClient.SCRIPTS = [(
            "答。\n<<<FOLLOWUP>>>", "\n- " + "长" * 201)]
        r2 = self._login_chat(self.ON, "超长丢弃验证")
        self.assertEqual([e for e in _chat_events(r2)
                          if e.get("type") == "followups"], [])

    def test_error_path_no_followups(self):
        """上游错误收尾：无 done 也无 followups（尾巴只挂成功收尾）。"""

        class _ErrClient(_SeqClient):
            def stream(self, *a, **k):
                return _ErrStream()

        class _ErrStream:
            status_code = 503

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def aiter_lines(self):
                return
                yield

            async def aread(self):
                return b"boom"

        with self._ctx(self.ON):
            with mock.patch.object(server.httpx, "AsyncClient", _ErrClient):
                c = self._client()
                c.post("/api/login", json={"passcode": "pw"})
                r = self._chat(c)
        events = _chat_events(r)
        self.assertTrue(any("error" in e for e in events))
        self.assertEqual([e for e in events if e.get("type") == "followups"], [])


class T8TailNetTextTest(_FbTestBase):
    """⑨ 净文本三处作用：gate 只看净正文、批次D 落库 content=净文本。"""

    def test_gate_and_db_use_clean_text(self):
        """尾巴里塞假摘录「未命中证据」——若尾巴进闸必 hard 违规；断言 ok=True
        证明 gate 只见净正文；同轮落库 content 同为净文本。"""
        _SeqClient.SCRIPTS = [(
            "根据[证据1]，T310 缺省值 1000 ms。",
            "\n<<<FOLLOWUP>>>「尾巴里的假摘录不在证据里」\n- 追问一\n- 追问二")]
        cfg = _cfg(passcode="pw", followup_tail_enabled=True)
        cfg["rag"] = {"citation_gate_enabled": True}
        r = self._login_chat(cfg, "净文本闸面验证", svc=_HitSvc())
        events = _chat_events(r)
        gate = [e for e in events if e.get("type") == "citation_gate"][0]
        with self.subTest("gate 只看净正文（假摘录不进闸、[证据1] 计 cites）"):
            self.assertTrue(gate["ok"])
            self.assertEqual(gate["cites"], 1)
            self.assertEqual(gate["quotes"], 0)
        with self.subTest("落库 content=净文本（无标记无尾巴）"):
            rows = self._sql(
                "SELECT content FROM messages WHERE role='assistant'")
            self.assertEqual(rows[0][0], "根据[证据1]，T310 缺省值 1000 ms。")
        with self.subTest("followups 照常解析下发"):
            fu = [e for e in events if e.get("type") == "followups"]
            self.assertEqual(fu[0]["items"], ["追问一", "追问二"])


class T9FollowupPureTest(unittest.TestCase):
    """⑩ 纯函数面：_followup_holdback / _parse_followup_items（零 IO）。"""

    def test_holdback_overlap(self):
        M = server.FOLLOWUP_MARKER
        cases = {
            "": 0,
            "正文": 0,
            "\n": 1,                      # 标记首字符
            "\n<<<": 4,
            "\n<<<FOLLOWU": len("\n<<<FOLLOWU"),
            M: 0,                         # 全标记在场时 find 已命中，不走 holdback
                                           # （唯一 "\n" 在串首=除全长外无前缀形后缀）
            M[1:]: 0,                     # 无前导换行=不构成标记前缀
            "尾巴\n": 1,                  # 尾部换行=潜在标记首字符，扣住
            "x\n\n<": 2,                  # 尾部 "\n<" 是标记前缀（重叠取最长后缀）
        }
        for buf, want in cases.items():
            with self.subTest(buf=repr(buf)):
                self.assertEqual(server._followup_holdback(buf), want)

    def test_parse_items_rules(self):
        P = server._parse_followup_items
        with self.subTest("2-3 条照收，剥 '- ' 前缀与空白"):
            self.assertEqual(P("\n- 问一\n- 问二"), ["问一", "问二"])
            self.assertEqual(P("-问一\n  - 问二  \n- 问三"), ["问一", "问二", "问三"])
        with self.subTest("非 '-' 行/空行忽略"):
            self.assertEqual(P("\n建议如下：\n- 问一\n\n- 问二"), ["问一", "问二"])
        with self.subTest("条数 0 或 >3 → None"):
            self.assertIsNone(P("没有任何建议行"))
            self.assertIsNone(P("".join("\n- 问%d" % i for i in range(4))))
        with self.subTest("单条空或 >200 字符 → None"):
            self.assertIsNone(P("\n-  \n- 问一"))
            self.assertIsNone(P("\n- " + "长" * 200 + "超"))
            self.assertEqual(P("\n- " + "长" * 200), ["长" * 200])  # 恰 200 收
        with self.subTest("非字符串入参（None/数字）安全"):
            self.assertIsNone(P(None))
            self.assertIsNone(P(123))


if __name__ == "__main__":
    unittest.main()
