# -*- coding: utf-8 -*-
"""server.py 深度提升批A 服务级离线单测（mock judge 零网络零真实 key）：
默认关=零新事件、A1 开=citation_check 事件先于 done、judge 失败=静默无事件
答案完整日志 cc=err、A2 insufficient=evidence_insufficient 先于 sources+保守
模板入 system、A2 超时/非高危面=照常回答。伪上游沿用批1测试形态（3 delta+
usage+DONE），另捕获上送 payload 断言 system 消息。"""
import asyncio
import contextlib
import io
import json
import time
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import citation_check
import citation_gate
import server  # 仓根模块（tests/__init__.py 已做 sys.path 引导）
from tests import clean_store_tests  # chat 型限流免疫（2026-10-02 迭代轮泛化）

SOURCES = [{"doc_id": "TS 36.331", "version": "V17", "locator": "§5.2.2",
            "score": 0.9, "quote": "T310 缺省值 1000 ms"}]
EVIDENCE = "以下为检索到的语料片段……\n\n[出处1] T310 缺省值 1000 ms"

CAPTURED = []  # 每次请求上送上游的 payload（system 消息断言用）


class _OkStream:
    status_code = 200

    def __init__(self, payload=None):
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def aiter_lines(self):
        for tok in ("你", "好", "！"):
            yield "data: " + json.dumps(
                {"choices": [{"delta": {"content": tok}}]}, ensure_ascii=False)
            await asyncio.sleep(0.01)
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

    def stream(self, method, url, json=None, headers=None, **k):
        CAPTURED.append(json)
        return _OkStream(json)


class _HitSvc:
    """retrieve 恒 hit 的桩（lifespan 启动日志要读 stats）。"""
    stats = {}

    def retrieve(self, query, route_res=None, history=None):
        return (EVIDENCE, SOURCES)


class _MissSvc:
    stats = {}

    def retrieve(self, query, route_res=None, history=None):
        return None


# 2026-10-12 同现修复臂：窗内含丙/ydt 行标块的混合窗（36号令+YD/T 4747——
# 过程日志 642 产线掉话率题的窗形态复刻），供抑制臂/关态同纹臂注入。
YDT_SOURCES = [
    {"doc_id": "信息产业部令第36号", "version": "", "locator": "附录2",
     "score": 0.75, "quote": "网络运行指标要求"},
    {"doc_id": "YD/T 4747-2024", "version": "", "locator": "9.3",
     "score": 0.71, "quote": "MRO 切换错误小区检测"},
]
YDT_EVIDENCE = "以下为检索到的语料片段……\n\n[出处1] 网络运行指标要求\n\n[出处2] MRO 切换错误小区检测"


class _YdtHitSvc:
    """retrieve 恒 hit、窗含 ydt 行标块（丙在席场景，2026-10-12 修复臂桩）。"""
    stats = {}

    def retrieve(self, query, route_res=None, history=None):
        return (YDT_EVIDENCE, YDT_SOURCES)


def _cfg(rag_extra=None, top=None):
    cfg = {
        "model": "stub-model", "passcode": "pw-test", "bot_name": "测试机",
        "max_history_messages": 40, "max_input_chars": 8000,
        "max_total_input_chars": 24000, "temperature": 0.7, "max_tokens": 100,
        "rate_limit_requests": 20, "rate_limit_window_seconds": 300,
    }
    if rag_extra is not None:
        cfg["rag"] = dict(rag_extra)
    if top:
        cfg.update(top)   # 顶层键（如 insight_gap_note_enabled——设计稿 v3-甲）
    return cfg


_DEFAULT_SVC = object()  # 哨兵：区分"缺省=hit 桩"与"显式 None=rag 关闭"


def _post(rag_extra, judge_fn=None, question="问句", svc=_DEFAULT_SVC, top=None):
    """一次 /api/chat 全链路（伪上游+mock judge）→ (events, 日志, 上送 payload 列表）。"""
    CAPTURED.clear()
    body = {"messages": [{"role": "user", "content": question}], "passcode": "pw-test"}
    out = io.StringIO()
    patches = [
        mock.patch.object(server.httpx, "AsyncClient", _OkClient),
        mock.patch.object(server, "CONFIG", _cfg(rag_extra, top)),
        mock.patch.object(server, "API_KEY", "stub-key"),
        mock.patch.object(server, "rag_service",
                          _HitSvc() if svc is _DEFAULT_SVC else svc),
        contextlib.redirect_stdout(out),
    ]
    if judge_fn is not None:
        patches.append(mock.patch.object(citation_check, "token_plan_judge", judge_fn))
    try:
        with contextlib.ExitStack() as st:
            for p in patches:
                st.enter_context(p)
            with TestClient(server.app) as client:
                with client.stream("POST", "/api/chat", json=body) as resp:
                    assert resp.status_code == 200
                    events = [json.loads(ln[5:].strip()) for ln in resp.iter_lines()
                              if ln.startswith("data:")]
    finally:
        # 测试卫生：清掉本件灌入的 rate_hits 行——套件共享 QABOT_DB_PATH 临时库，
        # 本件十余次 /api/chat 不清会吃光同 IP 滑窗预算，后续测试文件误触 429
        store = server._store()
        with store._lock:
            store._conn.execute("DELETE FROM rate_hits")
            store._conn.commit()
    return events, out.getvalue(), list(CAPTURED)


def _chat_line(logged):
    return [ln for ln in logged.splitlines() if "[chat]" in ln][0]


def _types(events):
    return [e.get("type") or ("sources" if "sources" in e else
                              "delta" if "delta" in e else
                              "done" if e.get("done") else "?") for e in events]


def _boom_judge(messages, **kwargs):
    raise AssertionError("judge 不应被调用")


class DepthConfigTest(unittest.TestCase):
    """_depth_config 六键解析：缺失/坏值回默认（全关、抽样 1.0、预算 3s）。"""

    def test_defaults_when_absent(self):
        for cfg in ({}, {"rag": {}}, {"rag": "not-a-dict"}, None):
            out = server._depth_config(cfg if cfg is not None else {})
            self.assertFalse(out["citation_check_enabled"])
            self.assertFalse(out["abstain_enabled"])
            self.assertEqual(out["citation_check_model"], "")
            self.assertEqual(out["citation_check_sample"], 1.0)
            self.assertEqual(out["citation_check_timeout"], 3.0)
            self.assertEqual(out["abstain_timeout"], 3.0)

    def test_bad_values_clamped(self):
        out = server._depth_config({"rag": {
            "citation_check_sample": "abc", "citation_check_timeout": 0,
            "abstain_timeout": -2, "citation_check_model": "  m1  "}})
        self.assertEqual(out["citation_check_sample"], 1.0)   # 坏值回默认
        self.assertEqual(out["citation_check_timeout"], 3.0)  # 0=必超时→回默认
        self.assertEqual(out["abstain_timeout"], 3.0)         # 负数→回默认
        self.assertEqual(out["citation_check_model"], "m1")   # 去空白
        out2 = server._depth_config({"rag": {"citation_check_sample": 3}})
        self.assertEqual(out2["citation_check_sample"], 1.0)  # 钳 [0,1]
        out3 = server._depth_config({"rag": {"citation_check_sample": -1}})
        self.assertEqual(out3["citation_check_sample"], 0.0)


@clean_store_tests
class DefaultOffTest(unittest.TestCase):
    """默认全关：事件序/日志与批A 前逐字段一致（零新事件、judge 零调用）。"""

    def test_hit_flow_unchanged_with_cc_ab_off(self):
        events, logged, payloads = _post({}, judge_fn=_boom_judge)
        self.assertEqual(_types(events), ["sources", "delta", "delta", "delta", "done"])
        self.assertEqual(events[0], {"sources": SOURCES})
        self.assertTrue(events[-1]["done"])
        line = _chat_line(logged)
        self.assertIn("cc=off", line)
        self.assertIn("ab=off", line)
        # 既有口径不动：rag=/top1=/ttfb 仍在且 cc/ab 在其后
        self.assertIn("rag=hit", line)
        self.assertLess(line.index("top1="), line.index("cc="))
        # system 消息无保守模板（A2 未触发）
        self.assertNotIn(server.ABSTAIN_SYSTEM_NOTE, payloads[0]["messages"][0]["content"])

    def test_rag_off_round_has_no_cc_ab_fields(self):
        # rag=off 轮不打 cc/ab（与现状逐字节一致，miss_attribution 前段口径安全）
        events, logged, _ = _post({}, judge_fn=_boom_judge, svc=None)
        line = _chat_line(logged)
        self.assertIn("rag=off", line)
        self.assertNotIn("cc=", line)
        self.assertNotIn("ab=", line)


@clean_store_tests
class A1CitationCheckTest(unittest.TestCase):
    """A1：citation_check_enabled=true 的 SSE 事件序、降级与抽样。"""

    RAW_OK = json.dumps({"per_source": [{"index": 1, "verdict": "supports"}],
                         "label": "grounded"})

    def _judge(self, raw=None, fn=None):
        calls = []

        def judge(messages, **kwargs):
            calls.append((messages, kwargs))
            if fn is not None:
                return fn(messages, **kwargs)
            return raw if raw is not None else self.RAW_OK
        judge.calls = calls
        return judge

    def test_citation_event_before_done(self):
        judge = self._judge()
        events, logged, _ = _post({"citation_check_enabled": True}, judge_fn=judge)
        types = _types(events)
        self.assertIn("citation_check", types)
        cc_ev = [e for e in events if e.get("type") == "citation_check"][0]
        self.assertEqual(cc_ev, {"type": "citation_check", "overall": "grounded",
                                 "per_source": [{"doc_id": "TS 36.331",
                                                 "verdict": "supports"}]})
        # 事件序：sources → deltas → citation_check → done（citation_check 先于 done）
        self.assertLess(types.index("citation_check"), types.index("done"))
        self.assertLess(types.index("sources"), types.index("citation_check"))
        self.assertIn("cc=ok", _chat_line(logged))
        self.assertIn("ab=off", _chat_line(logged))
        # judge 收到的是带 quote 的 sources 构建的消息（生产链路 api_key/model 注入）
        msgs, kwargs = judge.calls[0]
        self.assertEqual(kwargs["api_key"], "stub-key")
        self.assertEqual(kwargs["model"], "stub-model")  # 缺省同 chat 模型
        self.assertIn("T310 缺省值 1000 ms", msgs[1]["content"])

    def test_custom_model_and_body_carried(self):
        judge = self._judge()
        _post({"citation_check_enabled": True, "citation_check_model": "judge-m"},
              judge_fn=judge)
        self.assertEqual(judge.calls[0][1]["model"], "judge-m")

    def test_judge_fail_silent_answer_intact(self):
        # judge 回畸形 JSON：无 citation_check 事件、答案完整（delta+done 照常）、cc=err
        judge = self._judge(raw="这不是JSON")
        events, logged, _ = _post({"citation_check_enabled": True}, judge_fn=judge)
        self.assertNotIn("citation_check", _types(events))
        self.assertEqual([e.get("delta") for e in events if "delta" in e], ["你", "好", "！"])
        self.assertTrue(events[-1]["done"])
        self.assertIn("cc=err", _chat_line(logged))

    def test_judge_exception_silent(self):
        def boom(messages, **kwargs):
            raise RuntimeError("端点炸了")
        events, logged, _ = _post({"citation_check_enabled": True}, judge_fn=boom)
        self.assertNotIn("citation_check", _types(events))
        self.assertTrue(events[-1]["done"])
        self.assertIn("cc=err", _chat_line(logged))

    def test_sample_zero_skips_judge(self):
        judge = self._judge(fn=_boom_judge)  # 抽样 0：judge 一次都不许打
        events, logged, _ = _post(
            {"citation_check_enabled": True, "citation_check_sample": 0.0},
            judge_fn=judge)
        self.assertEqual(judge.calls, [])
        self.assertNotIn("citation_check", _types(events))
        self.assertIn("cc=skip", _chat_line(logged))

    def test_miss_path_no_judge(self):
        # rag=miss：无 sources 可校，judge 不打（cc=off——armed 前提不成立）
        judge = self._judge(fn=_boom_judge)
        events, logged, _ = _post({"citation_check_enabled": True}, judge_fn=judge,
                                  svc=_MissSvc())
        self.assertEqual(judge.calls, [])
        self.assertNotIn("citation_check", _types(events))
        self.assertIn("rag=miss", _chat_line(logged))
        self.assertIn("cc=off", _chat_line(logged))


@clean_store_tests
class A2AbstainTest(unittest.TestCase):
    """A2：abstain_enabled=true 的高危面题证据充分性闸门。"""

    HS_Q = "T310定时器的默认值是多少？"
    RAW_INSUFF = json.dumps({"verdict": "insufficient",
                             "reason": "语料未覆盖 T310 默认取值"}, ensure_ascii=False)
    RAW_SUFF = json.dumps({"verdict": "sufficient", "reason": "出处1 直接覆盖"})

    def _judge(self, raw=None, fn=None):
        calls = []

        def judge(messages, **kwargs):
            calls.append((messages, kwargs))
            if fn is not None:
                return fn(messages, **kwargs)
            return raw
        judge.calls = calls
        return judge

    def test_insufficient_event_and_conservative_template(self):
        judge = self._judge(raw=self.RAW_INSUFF)
        events, logged, payloads = _post({"abstain_enabled": True}, judge_fn=judge,
                                         question=self.HS_Q)
        types = _types(events)
        # evidence_insufficient 先于 sources，答案照常流式收尾
        self.assertEqual(types[0], "evidence_insufficient")
        self.assertEqual(events[0], {"type": "evidence_insufficient",
                                     "reason": "语料未覆盖 T310 默认取值"})
        self.assertLess(types.index("evidence_insufficient"), types.index("sources"))
        self.assertTrue(events[-1]["done"])
        # 保守模板指令追加进 system 消息（既有 system_prompt+证据之后）
        sysc = payloads[0]["messages"][0]["content"]
        self.assertIn(server.ABSTAIN_SYSTEM_NOTE, sysc)
        self.assertTrue(sysc.endswith(server.ABSTAIN_SYSTEM_NOTE))
        self.assertIn("ab=insuff", _chat_line(logged))
        # judge 收到 assess 消息（证据在场）
        self.assertIn(EVIDENCE[:20], judge.calls[0][0][1]["content"])

    def test_sufficient_no_event_no_template(self):
        judge = self._judge(raw=self.RAW_SUFF)
        events, logged, payloads = _post({"abstain_enabled": True}, judge_fn=judge,
                                         question=self.HS_Q)
        self.assertNotIn("evidence_insufficient", _types(events))
        self.assertNotIn(server.ABSTAIN_SYSTEM_NOTE,
                         payloads[0]["messages"][0]["content"])
        self.assertIn("ab=pass", _chat_line(logged))

    def test_non_high_stakes_skips_judge(self):
        judge = self._judge(fn=_boom_judge)
        events, logged, _ = _post({"abstain_enabled": True}, judge_fn=judge,
                                  question="什么是切换？")
        self.assertEqual(judge.calls, [])
        self.assertNotIn("evidence_insufficient", _types(events))
        self.assertIn("ab=off", _chat_line(logged))

    def test_judge_timeout_answers_normally(self):
        # judge 挂 2s、预算 0.2s：墙钟看门狗弃疗 → 照常回答，无事件，ab=pass
        def slow(messages, **kwargs):
            time.sleep(2.0)
            return self.RAW_INSUFF
        judge = self._judge(fn=slow)
        t0 = time.time()
        events, logged, payloads = _post(
            {"abstain_enabled": True, "abstain_timeout": 0.2}, judge_fn=judge,
            question=self.HS_Q)
        self.assertLess(time.time() - t0, 5.0)
        self.assertNotIn("evidence_insufficient", _types(events))
        self.assertTrue(events[-1]["done"])
        self.assertNotIn(server.ABSTAIN_SYSTEM_NOTE,
                         payloads[0]["messages"][0]["content"])
        self.assertIn("ab=pass", _chat_line(logged))
        self.assertTrue(any("[abstain]" in ln for ln in logged.splitlines()))

    def test_malformed_judge_output_answers_normally(self):
        judge = self._judge(raw="评审模型话痨了，没给JSON")
        events, logged, payloads = _post({"abstain_enabled": True}, judge_fn=judge,
                                         question=self.HS_Q)
        self.assertNotIn("evidence_insufficient", _types(events))
        self.assertNotIn(server.ABSTAIN_SYSTEM_NOTE,
                         payloads[0]["messages"][0]["content"])
        self.assertIn("ab=pass", _chat_line(logged))


@clean_store_tests
class A1A2CombinedTest(unittest.TestCase):
    """双开：A2 insufficient + A1 grounded 同轮——事件序与日志字段互不干扰。"""

    def test_both_events_in_order(self):
        def judge(messages, **kwargs):
            sysc = messages[0]["content"]
            if "证据充分性" in sysc:
                return json.dumps({"verdict": "insufficient", "reason": "覆盖不足"},
                                  ensure_ascii=False)
            return json.dumps({"per_source": [{"index": 1, "verdict": "partial"}],
                               "label": "partial"})
        events, logged, payloads = _post(
            {"abstain_enabled": True, "citation_check_enabled": True},
            judge_fn=judge, question="T310定时器的默认值是多少？")
        types = _types(events)
        self.assertEqual(types, ["evidence_insufficient", "sources",
                                 "delta", "delta", "delta", "citation_check", "done"])
        cc_ev = [e for e in events if e.get("type") == "citation_check"][0]
        self.assertEqual(cc_ev["overall"], "partial")
        line = _chat_line(logged)
        self.assertIn("cc=ok", line)
        self.assertIn("ab=insuff", line)
        self.assertIn(server.ABSTAIN_SYSTEM_NOTE, payloads[0]["messages"][0]["content"])
        self.assertNotIn("stub-key", logged)  # key 绝不落日志


@clean_store_tests
class InsightGapTest(unittest.TestCase):
    """意图缺口批甲（设计稿 v3-甲，2026-10-09 批）：insight_gap SSE 确定性
    标注事件——键关=零新事件、键开+方法论题+hit=先于 sources、abstain 互锁/
    非方法论题/miss 态零触发、journal 计数打点禁记题面、文案过 citation_gate。
    2026-10-12 同现修复臂（过程日志 60⑤/642）：丙/ydt 证据在席（窗内 doc_id
    "YD/T" 前缀）→ 抑制事件+[insight-gap-supp] 观测行（obs GAP_RE 不可匹配
    形态）；键关+丙在席窗逐字节不变；判定纯函数各形态。"""

    MQ_Q = "5g小区掉话率升高了怎么优化"            # 方法论问法（词表命中、非高危面）
    NON_MQ_Q = "电信服务规范规定的掉话率监管红线是多少"   # 限值问（判据③非方法论题）
    HS_MQ_Q = "掉话率的取值范围怎么处理"            # 高危面+方法论（互锁臂专用）

    def test_key_off_zero_event_even_with_method_query(self):
        # 键关（默认）：方法论题面也零新事件（事件流与既往逐字节一致）
        events, logged, _ = _post({}, judge_fn=_boom_judge, question=self.MQ_Q)
        self.assertEqual(_types(events), ["sources", "delta", "delta", "delta", "done"])
        self.assertNotIn("[insight-gap]", logged)

    def test_fired_event_before_sources(self):
        events, logged, payloads = _post(
            {}, top={"insight_gap_note_enabled": True},
            judge_fn=_boom_judge, question=self.MQ_Q)
        types = _types(events)
        # insight_gap 先于 sources，答案照常流式收尾
        self.assertEqual(types, ["insight_gap", "sources",
                                 "delta", "delta", "delta", "done"])
        self.assertEqual(events[0], {"type": "insight_gap",
                                     "note": server.INSIGHT_GAP_NOTE})
        # journal 计数打点：恰一行、fired=1、domain=-（route 关）、禁记题面
        gap_lines = [ln for ln in logged.splitlines() if "[insight-gap]" in ln]
        self.assertEqual(gap_lines, ["[insight-gap] fired=1 domain=-"])
        # prompt 栈零改动：system 消息不含标注文案（SSE 形不进 prompt——评审 P1）
        self.assertNotIn(server.INSIGHT_GAP_NOTE,
                         payloads[0]["messages"][0]["content"])

    def test_abstain_insuff_interlock_zero_fire(self):
        # abstain 互锁（评审 P3）：高危面+方法论题面+insuff → evidence_insufficient
        # 在场而 insight_gap 零触发（两事件互斥不同现）
        def judge(messages, **kwargs):
            return json.dumps({"verdict": "insufficient", "reason": "覆盖不足"},
                              ensure_ascii=False)
        events, logged, _ = _post(
            {"abstain_enabled": True}, top={"insight_gap_note_enabled": True},
            judge_fn=judge, question=self.HS_MQ_Q)
        types = _types(events)
        self.assertIn("evidence_insufficient", types)
        self.assertNotIn("insight_gap", types)
        self.assertNotIn("[insight-gap]", logged)

    def test_non_method_query_zero_fire(self):
        # 非方法论题（限值问形，判据③）零触发
        events, logged, _ = _post(
            {}, top={"insight_gap_note_enabled": True},
            judge_fn=_boom_judge, question=self.NON_MQ_Q)
        self.assertNotIn("insight_gap", _types(events))
        self.assertNotIn("[insight-gap]", logged)

    def test_miss_state_zero_fire(self):
        # rag=miss（hit 条件不成立）零触发
        events, logged, _ = _post(
            {}, top={"insight_gap_note_enabled": True},
            judge_fn=_boom_judge, question=self.MQ_Q, svc=_MissSvc())
        self.assertNotIn("insight_gap", _types(events))
        self.assertNotIn("[insight-gap]", logged)

    # ---- 2026-10-12 同现修复臂（过程日志 60⑤/642：丙/ydt 证据在席时抑制标注） ----

    def test_ydt_window_suppresses_event_and_prints_supp_line(self):
        # 键开+方法论题+hit+窗含 ydt 行标块（混合窗：36号令+YD/T 4747——过程日志
        # 642 掉话率题窗形态）→ 零 insight_gap 事件、零 [insight-gap] 行、恰一行
        # [insight-gap-supp] cause=ydt domain=-（route 关）；sources/正文照常
        events, logged, _ = _post(
            {}, top={"insight_gap_note_enabled": True},
            judge_fn=_boom_judge, question=self.MQ_Q, svc=_YdtHitSvc())
        self.assertEqual(_types(events), ["sources", "delta", "delta", "delta", "done"])
        self.assertNotIn("insight_gap", _types(events))
        self.assertNotIn("[insight-gap]", logged)   # fired 行零出现（注：非 supp 行子串）
        supp_lines = [ln for ln in logged.splitlines() if "[insight-gap-supp]" in ln]
        self.assertEqual(supp_lines, ["[insight-gap-supp] cause=ydt domain=-"])

    def test_key_off_ydt_window_byte_identical_stream(self):
        # 键关+丙在席窗：事件流与既有完全一致（无 insight_gap/无新事件）、
        # journal 零 [insight-gap] 与零 [insight-gap-supp]（关态铁门 E1）
        events, logged, _ = _post(
            {}, judge_fn=_boom_judge, question=self.MQ_Q, svc=_YdtHitSvc())
        self.assertEqual(_types(events), ["sources", "delta", "delta", "delta", "done"])
        self.assertNotIn("[insight-gap]", logged)
        self.assertNotIn("[insight-gap-supp]", logged)

    def test_ydt_evidence_in_window_pure_function(self):
        # 判定纯函数：ydt doc_id（含前导空白）True；TS/miit/小写形态 False；
        # None/空表/非 dict 条目 False、绝不抛出（判据 E5）
        self.assertTrue(server._ydt_evidence_in_window(
            [{"doc_id": "YD/T 5264-2021"}]))
        self.assertTrue(server._ydt_evidence_in_window(
            [{"doc_id": "TS 36.331"}, {"doc_id": " YD/T 4747-2024 "}, "junk"]))
        self.assertFalse(server._ydt_evidence_in_window(
            [{"doc_id": "TS 36.331"}, {"doc_id": "信息产业部令第36号"}]))
        self.assertFalse(server._ydt_evidence_in_window(
            [{"doc_id": "yd/t 4747-2024"}]))          # 前缀大小写敏感（冻结前缀同口径）
        self.assertFalse(server._ydt_evidence_in_window([]))
        self.assertFalse(server._ydt_evidence_in_window(None))
        self.assertFalse(server._ydt_evidence_in_window([{"doc_id": None}]))
        self.assertFalse(server._ydt_evidence_in_window([None, 42, "YD/T 裸串"]))
        self.assertFalse(server._ydt_evidence_in_window("YD/T 4747"))

    def test_note_text_passes_citation_gate_zero_hard(self):
        # 文案过 citation_gate.check_text 零 hard（评审 P20：文案禁「」）
        self.assertNotIn("「", server.INSIGHT_GAP_NOTE)
        m = citation_gate.check_text(server.INSIGHT_GAP_NOTE, EVIDENCE, 1)
        self.assertEqual(m["hard"], 0)
        self.assertTrue(m["ok"])

    def test_method_query_hit_pure_function(self):
        # 词表命中纯函数：当前轮题面（clean 末条）判、历史文本不触发、形态异常恒 False
        self.assertTrue(server._method_query_hit(
            [{"role": "user", "content": "接入率低怎么提升"}]))
        # 历史轮含信号词、当前轮不含 → 不触发（裸题面语义，非检索拼接查询）
        self.assertFalse(server._method_query_hit([
            {"role": "user", "content": "掉话率怎么优化"},
            {"role": "assistant", "content": "……"},
            {"role": "user", "content": "那它的定义是什么"}]))
        self.assertFalse(server._method_query_hit(
            [{"role": "user", "content": "T310 默认值是多少"}]))
        self.assertFalse(server._method_query_hit([]))
        self.assertFalse(server._method_query_hit(None))
        self.assertFalse(server._method_query_hit([{"role": "user"}]))


if __name__ == "__main__":
    unittest.main()
