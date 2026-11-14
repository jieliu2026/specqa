# -*- coding: utf-8 -*-
"""话术批（扩源专项 v3.4，2026-10-16）离线单测：off_topic 事件可选 note。

对象=server.py OFF_TOPIC_NOTE_PINNED/OFF_TOPIC_NOTE_TOPICS/OFF_TOPIC_CAREER_GUARD
与归类器 _off_topic_note + chat 流 off_topic 事件下发面。覆盖：
  ① 归类器：职业向守卫（闭项决策维持域外如实）→ 永不覆盖面（外审 P2-13，
     MML/网管与认证题库文案固定、优先于主题映射）→ 主题映射（coverage_miss
     以闸触发词 words 查表=词形权威口径；low_score 以题面关键词归类）→
     无命中 None；
  ② SSE 流：coverage_miss 带词 → 事件携 note；low_score 题面归类 → 事件携
     note；无映射（旧形态）→ 事件体逐字节 {"type":"off_topic"}（兼容面）；
  ③ 前端面：两版前端的 otNote 渲染接线与页脚覆盖公告（P2-17）文件级断言
     （Vue 渲染分支断言在 frontend/tests/BotMessage.ssr.test.ts ⑫）。
零网络（stub embed 桩+伪上游 httpx，口径同 test_s1治理丙覆盖闸）。"""
import contextlib
import io
import json
import os
import unittest
from unittest import mock

import rag
import server  # 仓根模块（tests/__init__.py 已做 sys.path 引导）
from tests import clean_store_tests  # chat 型限流免疫

NOTE_MML = "该领域涉及设备商内部文档，建议参考您所在运营商的内部网管手册或设备商技术支持"
NOTE_CERT = "建议参考华为人才在线官方大纲"
NOTE_SAT = "卫星通信（NTN）内容暂未收录，可参考 3GPP NTN 系列规范（TS 38.300 等）"
NOTE_PORT = "该业务办理口径本库暂未收录，建议参考工信部携号转网专区或运营商营业厅/官方 App"
NOTE_BB = "装机流程属运营商属地业务，建议咨询当地装维/10000 号"
NOTE_AIR = "空口信令细节可参考 3GPP TS 38.331/38.323/38.413 等对应篇"


class ClassifierTest(unittest.TestCase):
    """_off_topic_note：守卫序与映射命中。"""

    def test_career_guard_wins_over_everything(self):
        # 职业向闭项决策：简历/面试/求职类维持域外如实（零 note）——含与
        # 永不覆盖面词共现的复合题（守卫先行）
        for q in ("工程后台简历可以写什么", "面试会问哪些网优题",
                  "网管岗位简历怎么写", "跳槽求职 HCIE 题库哪里有"):
            self.assertIsNone(server._off_topic_note(q), q)

    def test_pinned_mml(self):
        for q in ("怎么用 MML 查基站状态", "mml 命令在哪里查", "网管怎么配置小区"):
            self.assertEqual(server._off_topic_note(q), NOTE_MML, q)

    def test_pinned_cert(self):
        for q in ("HCIE 题库哪里有", "认证考试真题", "数通真题下载"):
            self.assertEqual(server._off_topic_note(q), NOTE_CERT, q)

    def test_pinned_beats_topics(self):
        # 永不覆盖面优先：MML 与卫星共现 → MML 文案（不被主题映射改写）
        self.assertEqual(server._off_topic_note("用 MML 配置卫星链路"), NOTE_MML)

    def test_coverage_words_lookup(self):
        # coverage_miss 路径：闸触发词 words 查表（词形权威口径）
        self.assertEqual(server._off_topic_note("携号转网流程", ["携号转网"]), NOTE_PORT)
        self.assertEqual(server._off_topic_note("宽带装机要多久", ["宽带装机"]), NOTE_BB)
        self.assertEqual(server._off_topic_note("卫星通信题面", ["卫星"]), NOTE_SAT)
        self.assertEqual(server._off_topic_note("空口时延", ["空口"]), NOTE_AIR)

    def test_low_score_query_classification(self):
        # low_score 路径（words=None）：题面关键词归类
        self.assertEqual(server._off_topic_note("携号转网手续怎么办"), NOTE_PORT)
        self.assertEqual(server._off_topic_note("怎么开通卫星通信业务"), NOTE_SAT)

    def test_custom_vocab_word_off_table_yields_none(self):
        # 词表可配（cover_gate_vocab）：表外词零 note（扩表须决策禁自动生效）
        self.assertIsNone(server._off_topic_note("北斗短报文覆盖", ["北斗短报文"]))

    def test_no_match_returns_none(self):
        for q in ("问句", "附近有什么好吃的餐厅推荐", "今天是星期几", ""):
            self.assertIsNone(server._off_topic_note(q), repr(q))

    def test_none_and_empty_words(self):
        self.assertIsNone(server._off_topic_note("问句", None))
        self.assertIsNone(server._off_topic_note("问句", []))

    def test_table_texts_are_pinned(self):
        # P2-13 永不覆盖面：文案固定（改文案=改契约，本断言即哨兵）
        pinned = dict((k, n) for keys, n in server.OFF_TOPIC_NOTE_PINNED for k in keys)
        self.assertEqual(pinned["MML"], NOTE_MML)
        self.assertEqual(pinned["网管"], NOTE_MML)
        self.assertEqual(pinned["题库"], NOTE_CERT)
        # 四域词全在主题映射表（词表现状=卫星/空口/携号转网/宽带装机）
        topics = [k for keys, _n in server.OFF_TOPIC_NOTE_TOPICS for k in keys]
        for w in ("卫星", "空口", "携号转网", "宽带装机"):
            self.assertIn(w, topics)


# ---------- SSE 流面：伪上游（口径同 test_s1治理丙覆盖闸） ----------
class _OkStream:
    status_code = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def aiter_lines(self):
        yield "data: " + json.dumps(
            {"choices": [{"delta": {"content": "通用"}}]}, ensure_ascii=False)
        yield "data: " + json.dumps({"usage": {"total_tokens": 9}, "choices": []})
        yield "data: [DONE]"

    async def aread(self):
        return b""


class _OkClient:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def stream(self, *a, **k):
        return _OkStream()


class _CovSvc:
    """retrieve 恒回 CoverageMissResult（词=携号转网）。"""

    stats = {}

    def retrieve(self, query, route_res=None, history=None):
        return rag.CoverageMissResult(["携号转网"], 0.5565, 0.40)


class _LowSvc:
    """retrieve 恒回 LowScoreResult。"""

    stats = {}

    def retrieve(self, query, route_res=None, history=None):
        return rag.LowScoreResult(0.3184, 0.40)


_FAKE_CONFIG = {
    "model": "stub-model", "passcode": "pw-test", "bot_name": "测试机",
    "max_history_messages": 40, "max_input_chars": 8000,
    "max_total_input_chars": 24000, "temperature": 0.7, "max_tokens": 100,
    "rate_limit_requests": 20, "rate_limit_window_seconds": 300,
}


def _post_chat(svc, question):
    from fastapi.testclient import TestClient
    body = {"messages": [{"role": "user", "content": question}],
            "passcode": "pw-test"}
    out = io.StringIO()
    with mock.patch.object(server.httpx, "AsyncClient", _OkClient), \
            mock.patch.object(server, "CONFIG", _FAKE_CONFIG), \
            mock.patch.object(server, "API_KEY", "stub-key"), \
            mock.patch.object(server, "rag_service", svc), \
            contextlib.redirect_stdout(out):
        with TestClient(server.app) as client:
            with client.stream("POST", "/api/chat", json=body) as resp:
                assert resp.status_code == 200
                events = [json.loads(ln[5:].strip()) for ln in resp.iter_lines()
                          if ln.startswith("data:")]
    return events, out.getvalue()


@clean_store_tests
class OffTopicNoteFlowTest(unittest.TestCase):
    def test_coverage_miss_event_carries_note(self):
        # coverage_miss：闸触发词查表 → off_topic 事件携 note（先于正文）
        events, logged = _post_chat(_CovSvc(), "携号转网流程")
        self.assertEqual(events[0], {"type": "off_topic", "note": NOTE_PORT})
        self.assertTrue(events[-1].get("done"))
        self.assertFalse(any("sources" in e for e in events))
        self.assertIn("rag=coverage_miss", logged)

    def test_low_score_query_hit_event_carries_note(self):
        # low_score：题面含网管 → 永不覆盖面 MML 文案
        events, logged = _post_chat(_LowSvc(), "网管上怎么创建基站对象")
        self.assertEqual(events[0], {"type": "off_topic", "note": NOTE_MML})
        self.assertIn("rag=low_score", logged)

    def test_low_score_no_map_event_byte_identical_legacy(self):
        # 兼容面：无映射命中 → 事件体逐字节 {"type":"off_topic"}（旧前端/
        # 既有精确断言零波及；职业向守卫同此形态）
        events, _logged = _post_chat(_LowSvc(), "附近有什么好吃的餐厅推荐")
        self.assertEqual(events[0], {"type": "off_topic"})
        career_events, _ = _post_chat(_LowSvc(), "工程后台简历可以写什么")
        self.assertEqual(career_events[0], {"type": "off_topic"})

    def test_note_payload_not_logged(self):
        # 密件纪律顺带锚：[chat] 行不带 note 文本（日志面零新增原文泄漏面）。
        # 断言收窄到 [chat] 行——全量日志子串会撞既有启动行 insight_gap_note=
        # 的键名（2026-10-16 首跑红灯修正，取行写法同本件 test_coverage_miss）
        _events, logged = _post_chat(_CovSvc(), "携号转网流程")
        chat_line = [ln for ln in logged.splitlines() if "[chat]" in ln][0]
        self.assertNotIn("note", chat_line)
        self.assertNotIn(NOTE_PORT, logged)
        self.assertNotIn("stub-key", logged)


class FrontendSurfaceTest(unittest.TestCase):
    """两版前端接线面（文件级）：otNote 渲染（esc/截长/复现）与页脚覆盖公告。"""

    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _read(self, *parts):
        with open(os.path.join(self.ROOT, *parts), encoding="utf-8") as f:
            return f.read()

    def test_legacy_index_wiring(self):
        html = self._read("static", "index.html")
        # 事件面：note 截长 200 + esc 转义 + otNote 随消息存（render 复现）
        self.assertIn("ev.note.slice(0, 200)", html)
        self.assertIn("msgs[last].otNote = on", html)
        self.assertIn("esc(on)", html)
        self.assertIn("esc(m.otNote)", html)
        self.assertIn("offtopic note", html)
        # 页脚覆盖公告（P2-17 期望管理）
        self.assertIn(
            "已收录：3GPP 标准/中国行标/设备商与运营商公开白皮书/学术教材/行业论坛精选（持续扩展）",
            html)

    def test_vue_frontend_wiring(self):
        use_chat = self._read("frontend", "src", "composables", "useChat.ts")
        self.assertIn("ev.note.slice(0, 200)", use_chat)
        self.assertIn("last.otNote = on", use_chat)
        store = self._read("frontend", "src", "store.ts")
        self.assertIn("o.otNote = msg.otNote", store)  # 持久化白名单
        bot = self._read("frontend", "src", "components", "BotMessage.vue")
        self.assertIn('class="offtopic note"', bot)     # 插值转义渲染面
        app = self._read("frontend", "src", "App.vue")
        self.assertIn("disclaimer coverage", app)


if __name__ == "__main__":
    unittest.main()
