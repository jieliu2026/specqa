# -*- coding: utf-8 -*-
"""server.py 侧 RAG 集成离线单测：配置解析默认关闭、system 消息组装、
多轮检索查询构造（build_retrieval_query）、sources SSE 序列化（ensure_ascii=False）、
/api/chat 端到端 SSE 流（伪上游零网络）。"""
import contextlib
import io
import json
import os
import py_compile
import tempfile
import unittest
from unittest import mock

import httpx
from fastapi.testclient import TestClient

import rag
import server  # 仓根模块（tests/__init__.py 已做 sys.path 引导）
from tests import clean_store_tests  # chat 型限流免疫（2026-10-02 迭代轮泛化）
from tests.test_rag import QUERY, write_fixture


class RagConfigTest(unittest.TestCase):
    def test_missing_section_means_off(self):
        self.assertIsNone(server._rag_config({}))
        self.assertIsNone(server._rag_config({"model": "m"}))

    def test_enabled_false_means_off(self):
        self.assertIsNone(server._rag_config({"rag": {"enabled": False, "topk": 5}}))
        self.assertIsNone(server._rag_config({"rag": {}}))
        self.assertIsNone(server._rag_config({"rag": "not-a-dict"}))

    def test_enabled_true_returns_section(self):
        cfg = {"rag": {"enabled": True, "topk": 5, "store_path": "x.jsonl"}}
        self.assertEqual(server._rag_config(cfg), cfg["rag"])

    def test_module_state_matches_config(self):
        # 模块态与配置一致：rag 段未启用 → 服务对象必须为 None（行为与现状完全一致）
        if server._rag_config(server.CONFIG) is None:
            self.assertIsNone(server.rag_service)
        else:
            self.assertIsNotNone(server.rag_service)


class SystemContentTest(unittest.TestCase):
    """payload 组装（纯函数）：有/无 evidence 两态的 system 消息形态。"""

    def test_without_evidence_unchanged(self):
        self.assertEqual(server._build_system_content("SP", None), "SP")
        self.assertEqual(server._build_system_content("SP", ""), "SP")

    def test_with_evidence_joined_by_blank_line(self):
        # F18 围栏（2026-10-14）：evidence 外套 <qa_corpus> 标签，段落间仍空行相接
        self.assertEqual(server._build_system_content("SP", "EV"),
                         "SP\n\n<qa_corpus>\nEV\n</qa_corpus>")
        # 每问重读机制不变：system_prompt 实时值 + 围栏证据
        self.assertEqual(server._build_system_content(server._system_prompt(), "EV"),
                         server._system_prompt()
                         + "\n\n<qa_corpus>\nEV\n</qa_corpus>")

    def test_empty_prompt_evidence_only(self):
        self.assertEqual(server._build_system_content("", "EV"),
                         "<qa_corpus>\nEV\n</qa_corpus>")

    def test_messages_payload_shape_both_states(self):
        clean = [{"role": "user", "content": "问"}]
        for evidence in (None, "EV"):
            sys_content = server._build_system_content("SP", evidence)
            messages = [{"role": "system", "content": sys_content}] + clean
            self.assertEqual(messages[0]["role"], "system")
            self.assertEqual(messages[-1]["role"], "user")
            self.assertIn("SP", messages[0]["content"])
            if evidence:
                # F18：有证据时以围栏闭标签收尾（证据整体被包住）
                self.assertTrue(messages[0]["content"].endswith("</qa_corpus>"))
            else:
                self.assertEqual(messages[0]["content"], "SP")


class BuildRetrievalQueryTest(unittest.TestCase):
    """build_retrieval_query 纯函数：长问原样 / 短追问拼前文 / 上限与截断 / 容错。"""

    LONG = "我在分析一个LTE网络的掉话问题，切换参数配置与无线链路失败计数需要逐项核查"  # 去空白 38 字

    def test_long_question_returned_as_is(self):
        # base 去空白 ≥30：原样返回，即使前面有再多轮历史（行为与现状完全一致）
        self.assertEqual(server.build_retrieval_query(
            [{"role": "user", "content": self.LONG}]), self.LONG)
        msgs = [{"role": "user", "content": "上一轮问题"},
                {"role": "assistant", "content": "上一轮回答"},
                {"role": "user", "content": self.LONG}]
        self.assertEqual(server.build_retrieval_query(msgs), self.LONG)

    def test_short_followup_joins_previous_user(self):
        msgs = [{"role": "user", "content": "请帮我分析LTE掉话问题的切换参数配置清单与排查步骤"},
                {"role": "assistant", "content": "好的，逐项分析如下……"},
                {"role": "user", "content": "继续分析"}]
        self.assertEqual(server.build_retrieval_query(msgs),
                         "请帮我分析LTE掉话问题的切换参数配置清单与排查步骤\n继续分析")

    def test_no_earlier_user_returns_base(self):
        # 前面只有 assistant（或什么都没有）可拼 → base 原样
        self.assertEqual(server.build_retrieval_query(
            [{"role": "user", "content": "继续"}]), "继续")
        self.assertEqual(server.build_retrieval_query(
            [{"role": "assistant", "content": "回答"},
             {"role": "user", "content": "继续"}]), "继续")

    def test_joins_at_most_two_earlier_messages(self):
        # 三条更早 user 都很短：只拼最近两条，最早一条不参与
        msgs = [{"role": "user", "content": "第一句短"},
                {"role": "user", "content": "第二句短"},
                {"role": "assistant", "content": "答"},
                {"role": "user", "content": "第三句短"},
                {"role": "user", "content": "继续"}]
        self.assertEqual(server.build_retrieval_query(msgs), "第二句短\n第三句短\n继续")

    def test_truncates_to_max_chars_keeping_tail(self):
        # 拼接态总长超上限：截到 max_chars，且 base（当前追问）完整保留在尾部
        prev = "甲" * 700
        msgs = [{"role": "user", "content": prev},
                {"role": "assistant", "content": "答"},
                {"role": "user", "content": "继续"}]
        query = server.build_retrieval_query(msgs)
        self.assertEqual(len(query), 600)
        self.assertTrue(query.endswith("继续"))

    def test_ignores_assistant_messages(self):
        # assistant 内容再长也不进入查询
        long_ans = "回答内容" * 50
        msgs = [{"role": "user", "content": "上一轮的问题"},
                {"role": "assistant", "content": long_ans},
                {"role": "user", "content": "继续"}]
        query = server.build_retrieval_query(msgs)
        self.assertEqual(query, "上一轮的问题\n继续")
        self.assertNotIn("回答内容", query)

    def test_fullwidth_space_and_newline_tolerance(self):
        # 全角空格/换行不算信息量：判长用去空白长度，拼接时只剥首尾空白
        msgs = [{"role": "user", "content": "背景问题"},
                {"role": "user", "content": "　继续\u3000\n\n"}]
        self.assertEqual(server.build_retrieval_query(msgs), "背景问题\n继续")
        padded = "继　续\n" * 20  # 去空白 40 字 ≥30 → 长问题，原样返回（空白形态不变）
        self.assertEqual(server.build_retrieval_query(
            [{"role": "user", "content": padded}]), padded)
        tiny = "　继续\n" * 10  # 去空白 20 字 <30 → 仍触发拼接（内部空白保留）
        msgs2 = [{"role": "user", "content": "背景问题"},
                 {"role": "user", "content": tiny}]
        self.assertEqual(server.build_retrieval_query(msgs2), "背景问题\n" + tiny.strip())

    def test_no_user_messages_returns_empty(self):
        self.assertEqual(server.build_retrieval_query([]), "")
        self.assertEqual(server.build_retrieval_query(
            [{"role": "assistant", "content": "仅回答"}]), "")


class SseSourcesTest(unittest.TestCase):
    def test_sources_event_keeps_chinese_unescaped(self):
        sources = [{"doc_id": "L3-电信服务规范", "version": "2021版", "locator": "§12",
                    "score": 0.87654321}]
        line = server._sse({"sources": sources})
        self.assertTrue(line.startswith("data: "))
        self.assertTrue(line.endswith("\n\n"))
        self.assertIn("电信服务规范", line)          # ensure_ascii=False：中文原样
        self.assertIn("§12", line)
        self.assertNotIn("\\u", line)                 # 无 \uXXXX 转义
        payload = json.loads(line[6:].strip())       # 前端 JSON.parse 可原样还原
        self.assertEqual(payload["sources"][0]["doc_id"], "L3-电信服务规范")

    def test_sources_event_multiple_items(self):
        line = server._sse({"sources": [
            {"doc_id": "TS 38.331", "version": "V17", "locator": "§5.2.2", "score": 0.9},
            {"doc_id": "YD/T 5089", "version": "2018", "locator": "表3", "score": 0.7}]})
        payload = json.loads(line[6:].strip())
        self.assertEqual(len(payload["sources"]), 2)


def _auth_ok_cfg():
    """认证面测试 CONFIG：基于现网 server.CONFIG，剔哈希三键+放明文测试口令。
    2026-10-07 起生产 config.json 只余 passcode_hash/passcode_salt/pbkdf2_iterations
    三键（无明文 passcode），直读明文键得空串→body 无口令→401 auth_expired。
    保留哈希键会走 PBKDF2 比对分支照样 401，故必剔三键；测试口令为编造值，
    绝不涉真实口令（先例=tests/test_server_clause_hook.py 的 _cfg）。
    其余键原样保留=只动认证面，行为面零扰动。"""
    cfg = dict(server.CONFIG)
    for k in ("passcode_hash", "passcode_salt", "pbkdf2_iterations"):
        cfg.pop(k, None)
    cfg["passcode"] = "pw-test"
    return cfg


class _FakeAsyncStream:
    async def __aenter__(self):
        raise httpx.TimeoutException("stub 上游超时")  # 伪上游：一律超时，零网络

    async def __aexit__(self, *args):
        return False


class _FakeAsyncClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def stream(self, *args, **kwargs):
        return _FakeAsyncStream()


@clean_store_tests
class ChatEndpointRagFlowTest(unittest.TestCase):
    """/api/chat 端到端：rag hit/miss/off 三态的 SSE 事件序与 [chat] 日志标记。
    伪 httpx.AsyncClient 模拟上游超时——全程零网络零真实 key。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = os.path.join(self.tmp.name, "embeddings.jsonl")
        write_fixture(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def _post_chat(self, messages=None):
        body = {"messages": messages or [{"role": "user", "content": "问句"}],
                "passcode": "pw-test"}  # _auth_ok_cfg 明文测试口令，不涉真实口令
        out = io.StringIO()
        # 探针面测试卫生（2026-10-15 小修，样板=tests/test_rerank_log.py
        # FireAndZeroChangeTest._cap_fire）：hit 臂真实 fire 的 rerank-log-probe
        # 守护线程若不收编，其滞留 [rerank_probe] 打印会落在任意后续 stdout
        # 窗口（跨件渗漏源），且 _rerank_api_call 会对真实端点实调+写真实台账。
        # → join 收编 + 端点/打分/台账三面全桩（零网络零台账污染）。
        ledger = os.path.join(self.tmp.name, "探针账.jsonl")
        _orig_fire = server._rerank_log_fire  # 先捕原函数（patch 前引用，防自递归）

        def _cap_fire(*a, **k):
            t = _orig_fire(*a, **k)
            if t is not None:
                t.join(timeout=5)              # 测试收编（生产绝不 join）
            return t

        with mock.patch.object(server.httpx, "AsyncClient", _FakeAsyncClient), \
                mock.patch.object(server, "CONFIG", _auth_ok_cfg()), \
                mock.patch.object(server, "_rerank_log_fire", _cap_fire), \
                mock.patch.object(server, "RERANK_LOG_LEDGER", ledger), \
                mock.patch.object(server, "_rerank_log_resolve_endpoint",
                                  lambda: ("http://t/", "k")), \
                mock.patch.object(server, "_rerank_api_call",
                                  lambda q, d, timeout=3.0: ([0.9], 100)), \
                contextlib.redirect_stdout(out):
            with TestClient(server.app) as client:
                with client.stream("POST", "/api/chat", json=body) as resp:
                    self.assertEqual(resp.status_code, 200)
                    events = [json.loads(ln[5:].strip()) for ln in resp.iter_lines()
                              if ln.startswith("data:")]
        return events, out.getvalue()

    def test_rag_hit_emits_sources_first(self):
        svc = rag.RagService(embed_fn=lambda q: list(QUERY), log=lambda line: None)
        svc.initialize({"store_path": self.store, "topk": 2, "max_context_chars": 6000})
        expected_sources = svc.retrieve("问句")[1]
        with mock.patch.object(server, "API_KEY", "stub-key"), \
                mock.patch.object(server, "rag_service", svc):
            events, logged = self._post_chat()
        # 出处先于流式正文；伪上游超时→error 事件收流（现状语义：done 只在正常收尾发）
        self.assertEqual(events[0], {"sources": expected_sources})
        self.assertEqual(events[1], {"error": "upstream_timeout"})
        self.assertEqual(len(events), 2)
        self.assertIn("rag=hit", logged)
        self.assertNotIn("stub-key", logged)  # 日志绝不带 key

    def test_rag_miss_falls_back_to_bare_answer(self):
        svc = rag.RagService(embed_fn=lambda q: (_ for _ in ()).throw(RuntimeError("x")),
                             log=lambda line: None)
        svc.initialize({"store_path": self.store})
        with mock.patch.object(server, "API_KEY", "stub-key"), \
                mock.patch.object(server, "rag_service", svc):
            events, logged = self._post_chat()
        self.assertEqual(events, [{"error": "upstream_timeout"}])  # 无 sources 事件，照旧裸答
        self.assertIn("rag=miss", logged)
        self.assertNotIn("stub-key", logged)

    def test_rag_off_unchanged_behavior(self):
        with mock.patch.object(server, "API_KEY", "stub-key"), \
                mock.patch.object(server, "rag_service", None):
            events, logged = self._post_chat()
        self.assertEqual(events, [{"error": "upstream_timeout"}])  # 与现状完全一致
        self.assertIn("rag=off", logged)

    def test_short_followup_uses_prior_user_context_as_query(self):
        # 多轮短追问：retrieve 收到的 query 必须是"上一条 user + \n + 追问"，
        # assistant 内容不得混入（修 [rag-embed] chars=8-10 检索退化的实测短板）
        captured = {}
        sources = [{"doc_id": "DOC-X", "version": "V", "locator": "§1", "score": 0.9}]

        class _CaptureSvc:
            stats = {}  # lifespan 启动日志要读 rag_service.stats

            def retrieve(self, query, route_res=None, history=None):
                captured["q"] = query
                return ("证据", sources)

        long_q = "我在分析一个LTE网络的掉话问题，切换参数配置如下需要逐项核查排查"
        msgs = [{"role": "user", "content": long_q},
                {"role": "assistant", "content": "好的，以下是逐项分析……"},
                {"role": "user", "content": "继续分析"}]
        with mock.patch.object(server, "API_KEY", "stub-key"), \
                mock.patch.object(server, "rag_service", _CaptureSvc()):
            events, logged = self._post_chat(msgs)
        self.assertEqual(captured["q"], long_q + "\n" + "继续分析")
        self.assertEqual(events[0], {"sources": sources})  # 检索照常前置下发
        self.assertIn("rag=hit", logged)


class QLogFieldTest(unittest.TestCase):
    """_q_log_field：q= 字段清洗/脱长（与 miss_attribution.py 的 k="..." 正则对齐）。"""

    def test_cleans_control_chars_quotes_and_truncates(self):
        # 换行/制表/控制字符折空格并折叠；内嵌双引号降级单引号；超长截 80
        dirty = '他说"你好"\t继续\n\n\u0000查TS 38.331的T310' + "长" * 100
        out = server._q_log_field(dirty)
        self.assertNotIn('"', out)
        self.assertNotIn("\n", out)
        self.assertNotIn("\t", out)
        self.assertNotIn("\u0000", out)
        self.assertEqual(len(out), 80)
        self.assertTrue(out.startswith("他说'你好' 继续 查TS 38.331的T310"))
        # 单行无空白坍缩歧义：清洗后 split/join 折叠连续空白
        self.assertEqual(server._q_log_field("a   b\t\tc"), "a b c")

    def test_empty_and_plain_passthrough(self):
        self.assertEqual(server._q_log_field(""), "")
        self.assertEqual(server._q_log_field(None), "")
        q = "T310定时器在5G NR中如何配置与排查"
        self.assertEqual(server._q_log_field(q), q)


class ChatLogAttributionFieldsTest(unittest.TestCase):
    """[chat] 行打点：q=/top1= 字段落日志（miss 归因自动化证据源）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()   # 探针台账桩位（2026-10-15 小修）
        self.addCleanup(self.tmp.cleanup)

    def _post_chat(self, messages=None):
        body = {"messages": messages or [{"role": "user", "content": "问句"}],
                "passcode": "pw-test"}  # _auth_ok_cfg 明文测试口令，不涉真实口令
        out = io.StringIO()
        # 探针面测试卫生（同 ChatEndpointRagFlowTest._post_chat，样板=test_rerank_log
        # 的 _cap_fire）：hit 臂探线程 join 收编+端点/打分/台账三面全桩。
        ledger = os.path.join(self.tmp.name, "探针账.jsonl")
        _orig_fire = server._rerank_log_fire  # 先捕原函数（patch 前引用，防自递归）

        def _cap_fire(*a, **k):
            t = _orig_fire(*a, **k)
            if t is not None:
                t.join(timeout=5)              # 测试收编（生产绝不 join）
            return t

        with mock.patch.object(server.httpx, "AsyncClient", _FakeAsyncClient), \
                mock.patch.object(server, "CONFIG", _auth_ok_cfg()), \
                mock.patch.object(server, "_rerank_log_fire", _cap_fire), \
                mock.patch.object(server, "RERANK_LOG_LEDGER", ledger), \
                mock.patch.object(server, "_rerank_log_resolve_endpoint",
                                  lambda: ("http://t/", "k")), \
                mock.patch.object(server, "_rerank_api_call",
                                  lambda q, d, timeout=3.0: ([0.9], 100)), \
                contextlib.redirect_stdout(out):
            with TestClient(server.app) as client:
                with client.stream("POST", "/api/chat", json=body) as resp:
                    self.assertEqual(resp.status_code, 200)
                    events = [json.loads(ln[5:].strip()) for ln in resp.iter_lines()
                              if ln.startswith("data:")]
        return events, out.getvalue()

    def test_hit_logs_q_and_top1_miss_logs_q_only(self):
        # hit：sources 各条自带 score → top1=最高分（%.4f）；q= 为清洗后查询
        sources = [{"doc_id": "TS 38.331", "version": "V17", "locator": "§5.2.2", "score": 0.5},
                   {"doc_id": "TS 36.331", "version": "V17", "locator": "A.1", "score": 0.9}]

        class _Svc:
            stats = {}

            def retrieve(self, query, route_res=None, history=None):
                return ("证据", sources)

        q = "T310定时器在5G NR中如何配置与排查，给出规范出处"
        with mock.patch.object(server, "API_KEY", "stub-key"), \
                mock.patch.object(server, "rag_service", _Svc()):
            _events, logged = self._post_chat([{"role": "user", "content": q}])
        chat_line = [ln for ln in logged.splitlines() if "[chat]" in ln][0]
        self.assertIn(f'q="{server._q_log_field(q)}"', chat_line)
        self.assertIn("top1=0.9000", chat_line)
        self.assertIn("rag=hit", chat_line)

        # miss：q= 照记（归因脚本按缺失分数处理，不误判），top1 不出现
        class _MissSvc:
            stats = {}

            def retrieve(self, query, route_res=None, history=None):
                return None

        with mock.patch.object(server, "API_KEY", "stub-key"), \
                mock.patch.object(server, "rag_service", _MissSvc()):
            _events, logged = self._post_chat([{"role": "user", "content": q}])
        chat_line = [ln for ln in logged.splitlines() if "[chat]" in ln][0]
        self.assertIn(f'q="{server._q_log_field(q)}"', chat_line)
        self.assertIn("rag=miss", chat_line)
        self.assertNotIn("top1=", chat_line)

    def test_off_keeps_chat_line_unchanged(self):
        # rag=off：不追加任何字段，[chat] 行与打点前逐字段一致（现状零扰动）
        with mock.patch.object(server, "API_KEY", "stub-key"), \
                mock.patch.object(server, "rag_service", None):
            _events, logged = self._post_chat([{"role": "user", "content": "问句"}])
        chat_line = [ln for ln in logged.splitlines() if "[chat]" in ln][0]
        self.assertNotIn("q=", chat_line)
        self.assertNotIn("top1=", chat_line)


class CompileTest(unittest.TestCase):
    """语法门：server.py 与 rag.py 均须过 py_compile。"""

    def _repo_file(self, name):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), name)
        self.assertTrue(os.path.exists(path), f"缺文件 {name}")
        return path

    def test_py_compile_server_and_rag(self):
        for name in ("server.py", "rag.py"):
            with tempfile.NamedTemporaryFile(suffix=".pyc", delete=False) as tf:
                cfile = tf.name
            try:
                py_compile.compile(self._repo_file(name), cfile=cfile, doraise=True)
            finally:
                os.unlink(cfile)


if __name__ == "__main__":
    unittest.main()
