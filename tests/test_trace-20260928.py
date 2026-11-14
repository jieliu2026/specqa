# -*- coding: utf-8 -*-
"""E1 全链路 trace 结构化日志单测（2026-09-28 第 3 批，全离线 mock 零 API 零网络）。

覆盖：
- trace_id 生成形态（时间戳+序号哈希 → 8 位 hex）与跨请求唯一性；
- /api/chat 端到端（伪 httpx 上游 + mock rag_service）：
  * SSE 流首 ": trace_id=xxx" 注释行；data 事件体零改动（首数据事件/事件序与
    现状逐字段一致——护住"前端零改动"约束，trace_id 不进 data 事件的原因见
    server.py 件头注）；
  * 三行结构化行（[trace:xxx] 前缀 + 紧凑 JSON 体）字段齐：retrieval（top-k
    摘要+rag_state+gate 判定）/ llm（模型/token 用量/耗时/收尾态）/ citations
    （答案引用→chunk 对齐）；
  * [chat] 行尾 trace= 关联键，既有字段（rag=/q=/top1=/cc=/ab=）原样保留；
  * low_score / coverage_miss / miss / off 分态的 retrieval 行 gate 判定；
  * 上游超时路径 llm 行 status=timeout、无 citations 行；
- rag.py build_evidence 挂钩点：sources 透传 chunk id（引用对齐的 join key）；
- miss_attribution 向下兼容：含 trace 行 + [chat] 尾字段 + 前缀 rag 行的日志文本
  过 建库/scripts/miss_attribution.py parse_log——轮次/态/top1 解析不破坏，
  trace 行不被误计为轮次（回归护住"不许破坏现有归因"约束）。
"""
import contextlib
import io
import json
import os
import re
import sys
import unittest
from unittest import mock

import httpx
from fastapi.testclient import TestClient

import rag
import server  # 仓根模块（tests/__init__.py 已做 sys.path 引导）
from tests import clean_store_tests  # chat 型限流免疫（2026-10-02 迭代轮泛化）

# miss_attribution（建库/scripts 非包，路径注入导入；只读日志文本零副作用）
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MAS = os.path.join(_ROOT, "建库", "scripts")
if _MAS not in sys.path:
    sys.path.insert(0, _MAS)
import miss_attribution  # noqa: E402

SOURCES = [
    {"id": "c-001", "doc_id": "TS 36.331", "version": "V17", "locator": "5.2.2",
     "score": 0.9, "quote": "T310 缺省值 1000 ms"},
    {"id": "c-002", "doc_id": "TS 36.211", "version": "V18", "locator": "4.2",
     "score": 0.7, "quote": "帧结构类型 2"},
]
EVIDENCE = "以下为检索到的语料片段……\n\n[出处1] T310 缺省值 1000 ms\n\n[出处2] 帧结构"
DELTAS = ["根据[出处1]，T310 缺省值为 1000 ms。",
          "帧结构细节另见 TS 36.211 的 4.2 节，",
          "更多背景见[出处9]。"]
USAGE = {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}

_FAKE_CONFIG = {
    "model": "stub-model", "passcode": "pw-test", "bot_name": "测试机",
    "max_history_messages": 40, "max_input_chars": 8000,
    "max_total_input_chars": 24000, "temperature": 0.7, "max_tokens": 100,
    "rate_limit_requests": 100, "rate_limit_window_seconds": 300,
}


class _OkStream:
    status_code = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def aiter_lines(self):
        for tok in DELTAS:
            yield "data: " + json.dumps(
                {"choices": [{"delta": {"content": tok}}]}, ensure_ascii=False)
        yield "data: " + json.dumps({"usage": USAGE, "choices": []})
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


class _TimeoutStream:
    async def __aenter__(self):
        raise httpx.TimeoutException("stub 上游超时")

    async def __aexit__(self, *a):
        return False


class _TimeoutClient:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def stream(self, *a, **k):
        return _TimeoutStream()


class _HitSvc:
    stats = {}

    def retrieve(self, query, route_res=None, history=None):
        return (EVIDENCE, [dict(s) for s in SOURCES])


class _MissSvc:
    stats = {}

    def retrieve(self, query, route_res=None, history=None):
        return None


def _post(client_cls, svc, question="T310 定时器缺省值是多少？"):
    """一次 /api/chat 全链路（伪上游+mock 检索）→ (raw SSE 行, 事件, 捕获日志)。"""
    body = {"messages": [{"role": "user", "content": question}], "passcode": "pw-test"}
    out = io.StringIO()
    try:
        with mock.patch.object(server.httpx, "AsyncClient", client_cls), \
                mock.patch.object(server, "CONFIG", _FAKE_CONFIG), \
                mock.patch.object(server, "API_KEY", "stub-key"), \
                mock.patch.object(server, "rag_service", svc), \
                contextlib.redirect_stdout(out):
            with TestClient(server.app) as client:
                with client.stream("POST", "/api/chat", json=body) as resp:
                    assert resp.status_code == 200
                    raw = list(resp.iter_lines())
    finally:
        # 测试卫生（口径同 test_citation_sse）：清本请求灌入的 rate_hits——套件
        # 共享 QABOT_DB_PATH 临时库，不清会吃光同 IP 滑窗预算，后续测试误触 429
        store = server._store()
        with store._lock:
            store._conn.execute("DELETE FROM rate_hits")
            store._conn.commit()
    events = [json.loads(ln[5:].strip()) for ln in raw if ln.startswith("data:")]
    return raw, events, out.getvalue()


def _chat_line(logged):
    return [ln for ln in logged.splitlines() if "[chat]" in ln][0]


_TRACE_LINE_RE = re.compile(r"^\[trace:([0-9a-f]{8})\] (\{.*\})$")


def _trace_objs(logged):
    """日志 → [(trace_id, JSON 对象)]（结构化行解析口径：前缀 ] 后空格+JSON）。"""
    out = []
    for ln in logged.splitlines():
        m = _TRACE_LINE_RE.match(ln)
        if m:
            out.append((m.group(1), json.loads(m.group(2))))
    return out


def _stage(objs, stage):
    return [o for _tid, o in objs if o.get("stage") == stage]


class TraceIdTest(unittest.TestCase):
    def test_format_and_uniqueness(self):
        ids = {server._new_trace_id() for _ in range(2000)}
        self.assertGreaterEqual(len(ids), 1999)   # 8-hex 空间 2000 抽样碰撞率≈0.046%，容忍 1 次（2026-10-08 CI 首跑实锤+用户批口径）
        for tid in ids:
            self.assertRegex(tid, server._TRACE_ID_RE)


class RagSourcesIdHookTest(unittest.TestCase):
    """rag.py 挂钩点：build_evidence 的 sources 透传 chunk id（最小侵入一行）。"""

    def test_sources_carry_chunk_id(self):
        recs = [{"vec": [1.0, 0.0], "id": "c1", "content": "甲" * 20,
                 "doc_id": "DOC-1", "version": "V1", "locator": "§1.1"},
                {"vec": [0.0, 1.0], "id": "c2", "content": "乙" * 20,
                 "doc_id": "DOC-2", "version": "V2", "locator": "§2.1"}]
        hits = [{"rank": i, "score": 0.9, "rec": r, "idx": i - 1}
                for i, r in enumerate(recs, 1)]
        _ev, sources = rag.build_evidence(hits, max_context_chars=10 ** 6)
        self.assertEqual([s["id"] for s in sources], ["c1", "c2"])   # E1 join key
        self.assertEqual([s["doc_id"] for s in sources], ["DOC-1", "DOC-2"])
        self.assertIn("score", sources[0])
        self.assertIn("quote", sources[0])   # 既有字段不删


class CitationAlignmentTest(unittest.TestCase):
    """_citation_alignment 纯函数：marker/oob/text_hit（数字边界/归一匹配）。"""

    def test_full_alignment(self):
        ans = "".join(DELTAS)
        out = server._citation_alignment(ans, SOURCES)
        self.assertEqual(out["n_sources"], 2)
        self.assertEqual(out["oob"], [9])                       # [出处9] 超界
        self.assertTrue(out["chunks"][0]["marker"])             # [出处1]
        self.assertFalse(out["chunks"][0]["text_hit"])
        self.assertFalse(out["chunks"][1]["marker"])
        self.assertTrue(out["chunks"][1]["text_hit"])           # "TS 36.211 的 4.2"
        self.assertEqual(out["cited_n"], 2)
        self.assertEqual(out["uncited_n"], 0)

    def test_numeric_boundary_and_normalization(self):
        # locator=4.2：答案只出现 14.23（边界内不误配）；ts36.331 无空格可互配
        out = server._citation_alignment("见 14.23 节与 ts36.331 的描述",
                                         [SOURCES[1], SOURCES[0]])
        self.assertFalse(out["chunks"][0]["text_hit"])          # 4.2 ≠ 14.23
        self.assertTrue(out["chunks"][1]["text_hit"])           # TS 36.331 归一命中
        self.assertEqual(out["cited_n"], 1)

    def test_no_citation_at_all(self):
        out = server._citation_alignment("模型没引任何出处", SOURCES)
        self.assertEqual(out["cited_n"], 0)
        self.assertEqual(out["uncited_n"], 2)
        self.assertEqual(out["oob"], [])


@clean_store_tests
class HitTraceFlowTest(unittest.TestCase):
    """hit 全链路：SSE 注释行+三结构化行+[chat] 尾字段，data 事件零改动。"""

    @classmethod
    def setUpClass(cls):
        cls.raw, cls.events, cls.logged = _post(_OkClient, _HitSvc())
        cls.objs = _trace_objs(cls.logged)

    def test_sse_head_comment_carries_trace_id(self):
        # 流首行=trace_id 注释行（SSE 规范注释；前端/既有测试只认 data: 行）
        m = re.match(r"^: trace_id=([0-9a-f]{8})$", self.raw[0])
        self.assertIsNotNone(m, self.raw[0])

    def test_data_events_unchanged(self):
        # 首数据事件仍为 sources（逐字段精确），delta 序不变，done 事件键集不含
        # trace_id（前端零改动=数据事件体不增字段）
        self.assertEqual(self.events[0], {"sources": SOURCES})
        self.assertEqual([e.get("delta") for e in self.events[1:4]], DELTAS)
        done = self.events[-1]
        self.assertTrue(done["done"])
        self.assertEqual(done["usage"], USAGE)
        self.assertEqual(set(done.keys()), {"done", "usage"})

    def test_three_stages_present_and_single_line(self):
        stages = [o.get("stage") for _tid, o in self.objs]
        self.assertIn("retrieval", stages)
        self.assertIn("llm", stages)
        self.assertIn("citations", stages)
        for ln in self.logged.splitlines():
            if ln.startswith("[trace:"):
                self.assertNotIn("\n", ln)   # 单行（机器可按行解析）
                json.loads(ln.split("] ", 1)[1])   # ] 后是合法 JSON

    def test_retrieval_line_fields(self):
        line = _stage(self.objs, "retrieval")[0]
        self.assertEqual(line["rag"], "hit")
        self.assertEqual(line["q"], server._q_log_field("T310 定时器缺省值是多少？"))
        self.assertEqual(line["q_chars"], len("T310 定时器缺省值是多少？"))
        self.assertEqual(line["top1"], 0.9)
        self.assertEqual(line["gate"], {"state": "hit"})
        self.assertEqual(len(line["topk"]), 2)
        for chunk, src in zip(line["topk"], SOURCES):
            self.assertEqual(set(chunk.keys()),
                             {"id", "doc", "locator", "score", "is_answer", "gate"})
            self.assertEqual(chunk["id"], src["id"])
            self.assertEqual(chunk["doc"], src["doc_id"])
            self.assertEqual(chunk["locator"], src["locator"])
            self.assertEqual(chunk["score"], src["score"])
            self.assertIsNone(chunk["is_answer"])   # 服务面未装载 section，恒 null
            self.assertEqual(chunk["gate"], "pass")
        self.assertIsInstance(line["ts"], float)

    def test_llm_line_fields(self):
        line = _stage(self.objs, "llm")[0]
        self.assertEqual(line["model"], "stub-model")
        self.assertEqual(line["status"], "done")
        self.assertEqual(line["in_tok"], 100)
        self.assertEqual(line["out_tok"], 50)
        self.assertEqual(line["total_tok"], 150)
        self.assertIsInstance(line["dur_s"], (int, float))
        self.assertIsInstance(line["ttfb_s"], (int, float))

    def test_citations_line_fields(self):
        line = _stage(self.objs, "citations")[0]
        self.assertEqual(line["n_sources"], 2)
        self.assertEqual(line["oob"], [9])
        self.assertEqual([c["id"] for c in line["chunks"]], ["c-001", "c-002"])
        self.assertEqual([c["doc"] for c in line["chunks"]],
                         ["TS 36.331", "TS 36.211"])

    def test_trace_id_pervades_all_lines(self):
        m = re.match(r"^: trace_id=([0-9a-f]{8})$", self.raw[0])
        tid = m.group(1)
        for t, _o in self.objs:
            self.assertEqual(t, tid)                    # 三结构化行同一 id
        self.assertIn(f"trace={tid}", _chat_line(self.logged))   # [chat] 锚点关联

    def test_chat_line_keeps_legacy_fields_with_trace_tail(self):
        line = _chat_line(self.logged)
        self.assertIn("rag=hit", line)
        self.assertIn('q="', line)
        self.assertIn("top1=0.9000", line)
        self.assertIn("cc=off", line)
        self.assertIn("ab=off", line)
        # trace= 尾附在既有字段之后（KV 尾部追加安全位）；2026-10-13 一致性
        # 收敛批再尾附 dev=/ua=（设备归因键，同款安全位）
        self.assertLess(line.index("ab="), line.index("trace="))
        self.assertRegex(line, r"trace=[0-9a-f]{8} dev=[A-Za-z0-9_-]{8} ua=\S+$")


@clean_store_tests
class StatesTraceTest(unittest.TestCase):
    """low_score / coverage_miss / miss / off 分态的 retrieval 行 gate 判定。"""

    def test_low_score_gate_detail(self):
        svc = type("_LowSvc", (), {"stats": {},
                                   "retrieve": staticmethod(lambda q, route_res=None, history=None: rag.LowScoreResult(0.3123, 0.40))})()
        _raw, events, logged = _post(_OkClient, svc)
        line = _stage(_trace_objs(logged), "retrieval")[0]
        self.assertEqual(line["rag"], "low_score")
        self.assertEqual(line["top1"], 0.3123)
        self.assertEqual(line["gate"], {"state": "low_score", "thr": 0.40,
                                        "observed": 0.3123})
        self.assertEqual(line["topk"], [])            # 闸态不产出 sources
        self.assertEqual(events[0], {"type": "off_topic"})   # 事件序零改动
        self.assertIn("rag=low_score", _chat_line(logged))
        self.assertIn("top1=0.3123", _chat_line(logged))

    def test_coverage_miss_gate_detail(self):
        svc = type("_CovSvc", (), {"stats": {}, "retrieve": staticmethod(
            lambda q, route_res=None, history=None: rag.CoverageMissResult(["卫星"], 0.5123, 0.40))})()
        _raw, events, logged = _post(_OkClient, svc)
        line = _stage(_trace_objs(logged), "retrieval")[0]
        self.assertEqual(line["rag"], "coverage_miss")
        self.assertEqual(line["gate"]["words"], ["卫星"])
        self.assertEqual(line["gate"]["observed"], 0.5123)
        self.assertEqual(line["topk"], [])
        # 话术批（2026-10-16）：闸触发词"卫星"命中主题映射 → off_topic 事件带 note
        self.assertEqual(events[0], {"type": "off_topic",
                                     "note": "卫星通信（NTN）内容暂未收录，可参考 3GPP NTN 系列规范（TS 38.300 等）"})

    def test_miss_state(self):
        _raw, events, logged = _post(_OkClient, _MissSvc())
        line = _stage(_trace_objs(logged), "retrieval")[0]
        self.assertEqual(line["rag"], "miss")
        self.assertEqual(line["gate"], {"state": "miss"})
        self.assertEqual(line["topk"], [])
        self.assertEqual(events[0].get("delta"), DELTAS[0])   # 无 sources 直入正文
        chat = _chat_line(logged)
        self.assertIn("rag=miss", chat)
        self.assertNotIn("top1=", chat)

    def test_off_state_still_traced(self):
        _raw, events, logged = _post(_OkClient, None)
        line = _stage(_trace_objs(logged), "retrieval")[0]
        self.assertEqual(line["rag"], "off")
        self.assertEqual(line["gate"], {"state": "off"})
        self.assertEqual(line["topk"], [])
        self.assertEqual(_stage(_trace_objs(logged), "llm")[0]["status"], "done")
        chat = _chat_line(logged)
        self.assertIn("rag=off", chat)
        self.assertRegex(chat, r"trace=[0-9a-f]{8} dev=[A-Za-z0-9_-]{8} ua=\S+$")   # off 轮也带关联键（2026-10-13 尾再附 dev=/ua=）
        self.assertNotIn("q=", chat)
        self.assertNotIn("cc=", chat)

    def test_distinct_ids_across_requests(self):
        _r1, _e1, log1 = _post(_OkClient, _HitSvc())
        _r2, _e2, log2 = _post(_OkClient, _HitSvc())
        tid1 = _trace_objs(log1)[0][0]
        tid2 = _trace_objs(log2)[0][0]
        self.assertNotEqual(tid1, tid2)


@clean_store_tests
class TimeoutTraceTest(unittest.TestCase):
    """上游超时：llm 行 status=timeout、无 citations 行、事件零改动。"""

    @classmethod
    def setUpClass(cls):
        cls.raw, cls.events, cls.logged = _post(_TimeoutClient, _HitSvc())

    def test_llm_status_timeout_no_citations(self):
        objs = _trace_objs(self.logged)
        llm = _stage(objs, "llm")[0]
        self.assertEqual(llm["status"], "timeout")
        self.assertIsNone(llm["in_tok"])
        self.assertIsNone(llm["ttfb_s"])
        self.assertEqual(_stage(objs, "citations"), [])   # 无正文不对齐
        self.assertIn("ttfb=na", _chat_line(self.logged))

    def test_events_unchanged_on_timeout(self):
        self.assertEqual(self.events[0], {"sources": SOURCES})
        self.assertEqual(self.events[1], {"error": "upstream_timeout"})


class RagLinePrefixRouterTest(unittest.TestCase):
    """_rag_trace_log：请求上下文内加前缀、无上下文原样（ContextVar 路由）。"""

    def test_prefix_only_within_context(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            server._rag_trace_log("[rag] retrieve ok chars=1 blocks=1")
        self.assertEqual(out.getvalue().strip(), "[rag] retrieve ok chars=1 blocks=1")
        tok = server._trace_id_var.set("deadbeef")
        try:
            out2 = io.StringIO()
            with contextlib.redirect_stdout(out2):
                server._rag_trace_log("[rag] retrieve ok chars=1 blocks=1")
            self.assertEqual(out2.getvalue().strip(),
                             "[trace:deadbeef] [rag] retrieve ok chars=1 blocks=1")
        finally:
            server._trace_id_var.reset(tok)

    def test_prefix_visible_inside_to_thread(self):
        # asyncio.to_thread 复制 contextvars → retrieve 工作线程内打点可加前缀
        import asyncio

        async def run():
            tok = server._trace_id_var.set("cafe0001")
            try:
                return await asyncio.to_thread(server._rag_trace_log, "[rag-embed] ok=1")
            finally:
                server._trace_id_var.reset(tok)

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            asyncio.run(run())
        self.assertEqual(out.getvalue().strip(), "[trace:cafe0001] [rag-embed] ok=1")


@clean_store_tests
class MissAttributionCompatTest(unittest.TestCase):
    """向下兼容回归：trace 行/前缀 rag 行/[chat] 尾 trace= 不破坏 miss_attribution。"""

    def test_parse_log_with_trace_lines(self):
        _raw, _ev, hit_logged = _post(_OkClient, _HitSvc())
        low_svc = type("_LowSvc", (), {"stats": {}, "retrieve": staticmethod(
            lambda q, route_res=None, history=None: rag.LowScoreResult(0.3123, 0.40))})()
        _raw2, _ev2, low_logged = _post(_OkClient, low_svc)
        # 合成日志=服务日志实态切片：hit 轮的真实 trace 行+[chat] 行，再手工补
        # 前缀 rag 行/闸门行/low_score 轮 [chat]/访问行（含全部新增日志形态）
        log_lines = [
            "[startup] rag=on loaded=14055 bad_lines=0 dim=1024",
            "[rag-store] loaded=14055 bad_lines=0 dim=1024",
            "[trace:aaaaaaaa] [rag-embed] chars=19 tokens=11 ok=1 dim=1024 dur=0.01s",
            "[trace:aaaaaaaa] [rag] retrieve ok chars=748 blocks=5",
        ] + [ln for ln in hit_logged.splitlines()
             if ln.startswith("[trace:") or "[chat]" in ln] + [
            "[rag-embed] chars=10 tokens=6 ok=1 dim=1024 dur=0.01s",
            "[trace:bbbbbbbb] [rag] low_score cos=0.3123 thr=0.40（证据集余弦低于阈值，不注入证据）",
        ] + [ln for ln in low_logged.splitlines()
             if ln.startswith("[trace:") or "[chat]" in ln] + [
            'INFO: 127.0.0.1:39170 - "POST /api/chat HTTP/1.1" 200 OK',
        ]
        turns, meta = miss_attribution.parse_log(log_lines)
        self.assertEqual(meta.n_chat, 2)                       # trace 行不计为轮次
        self.assertEqual([t.rag for t in turns], ["hit", "low_score"])
        t0, t1 = turns
        # hit 轮：前缀 [rag-embed]/[rag] retrieve 行照常配对（search 式正则容忍前缀）
        self.assertEqual(t0.embeds[0].get("ok"), "1")
        self.assertEqual(t0.retrieve.get("outcome"), "ok")
        self.assertEqual(t0.retrieve.get("blocks"), "5")
        self.assertEqual(t0.top1, 0.9)                         # [chat] q=/top1= 照读
        self.assertEqual(t0.query, "T310 定时器缺省值是多少？")
        # low_score 轮：闸门行 cos/thr 定向解析不破坏
        self.assertEqual(t1.retrieve.get("outcome"), "low_score")
        self.assertEqual(t1.retrieve.get("cos"), "0.3123")
        self.assertEqual(t1.retrieve.get("thr"), "0.40")
        self.assertEqual(t1.top1, 0.3123)
        # 机读采集（阈值 ROC 标定真数据源）照常产出
        recs = miss_attribution.low_score_records(turns, "synthetic.log")
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["top1"], 0.3123)
        self.assertEqual(recs[0]["score_type"], "gate_cosine_max")
        self.assertEqual(recs[0]["thr"], 0.4)
        # 归因分类照常（hit 干净轮不触发；low_score 单列低分闸门拦截）
        opts = miss_attribution.Options()
        findings = [f for f in (miss_attribution.classify_turn(t, opts)
                                for t in turns) if f is not None]
        self.assertEqual([f.category for f in findings],
                         [miss_attribution.CAT_LOW_SCORE])

    def test_trace_lines_alone_are_not_turns(self):
        objs_only = [
            '[trace:deadbeef] {"stage":"retrieval","rag":"hit","q":"T310","top1":0.9,'
            '"gate":{"state":"hit"},"topk":[]}',
            '[trace:deadbeef] {"stage":"llm","model":"m","status":"done","in_tok":1,'
            '"out_tok":2,"total_tok":3}',
            '[trace:deadbeef] {"stage":"citations","n_sources":0,"chunks":[],'
            '"cited_n":0,"uncited_n":0,"oob":[]}',
        ]
        turns, meta = miss_attribution.parse_log(objs_only)
        self.assertEqual(turns, [])
        self.assertEqual(meta.n_chat, 0)


if __name__ == "__main__":
    unittest.main()
