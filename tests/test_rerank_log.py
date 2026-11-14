# -*- coding: utf-8 -*-
"""rerank log-only 影子探针（部署窗件2·2026-10-12）单测。

铁律面（对应 server.py 探针段头注三条）：
- 开关关（rerank_log_enabled=false）=零探针零日志零台账；
- 开=探针 mock 下主链路行为零变化（SSE 事件序与关态逐字段一致）+
  journal 行格式（[rerank_probe] 查询哈希/三阈值过线计数/最高分/token/gold=na）
  +台账行 stage=rerank_log；
- 超时/失败只记跳过不重试；月顶软顶跳过+warn 一次；rag=miss 不 fire；
- 评测面零扰动快检：离线 harness 直连 rag.RagService.retrieve（探针挂点
  外置在 server /api/chat——rag 模块零探针面），retrieve 输出确定性不变。

零网络零计费：rerank API 调用与查询补嵌全部 mock（embed_fn 注入先例=
tests/test_server_rag.py ChatEndpointRagFlowTest）。key/题面绝不入断言面。
"""
import contextlib
import hashlib
import io
import json
import os
import re
import tempfile
import time
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import rag
import server  # 仓根模块（tests/__init__.py 已做 sys.path 引导）
from tests import clean_store_tests  # chat 型限流免疫
from tests.test_rag import QUERY, write_fixture
from tests.test_server_rag import _FakeAsyncClient, _auth_ok_cfg

_CANDS = [{"id": f"c{i}", "doc_id": f"DOC-{i}", "locator": "§1.1",
           "cos": 0.9, "text": f"候选内容{i}"} for i in range(1, 4)]

_PROBE_LINE_RE = re.compile(
    r"^\[rerank_probe\] ts=\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} "
    r"q=[0-9a-f]{12} st=(hit|low_score|coverage_miss) trace=[0-9a-f]{8} "
    r"n=\d+ max=0\.\d{4} c075=\d+ c085=\d+ c095=\d+ "
    r"tok=\d+ cny=\d+\.\d{6} gold=na$")


class _FakeProbeSvc:
    """探针数据面替身：rerank_probe_candidates 可注入返回/异常；其余属性
    透传（chat 流的 retrieve/stats 照走真件或另一替身）。"""

    def __init__(self, cands=None, exc=None, delegate=None):
        self._cands = list(cands or [])
        self._exc = exc
        self._delegate = delegate
        self.probe_calls = []

    def __getattr__(self, name):
        return getattr(self._delegate, name)

    def rerank_probe_candidates(self, query, n=50):
        self.probe_calls.append((query, n))
        if self._exc is not None:
            raise self._exc
        return list(self._cands)


class FlagTest(unittest.TestCase):
    def test_default_on_and_explicit_off(self):
        cfg = {k: v for k, v in server.CONFIG.items()
               if k != "rerank_log_enabled"}
        with mock.patch.object(server, "CONFIG", cfg):
            self.assertTrue(server._rerank_log_enabled())      # 无键=默认开
        with mock.patch.object(server, "CONFIG", dict(
                server.CONFIG, rerank_log_enabled=False)):
            self.assertFalse(server._rerank_log_enabled())     # 显式关

    def test_cap_default_and_bad_values(self):
        cfg = {k: v for k, v in server.CONFIG.items()
               if k != "rerank_log_monthly_cap_cny"}
        with mock.patch.object(server, "CONFIG", cfg):
            self.assertEqual(server._rerank_log_cap_cny(), 5.0)
        for bad in ("x", None, -1, 0, float("nan"), []):
            with mock.patch.object(server, "CONFIG", dict(
                    server.CONFIG, rerank_log_monthly_cap_cny=bad)):
                self.assertEqual(server._rerank_log_cap_cny(), 5.0)  # 坏值回默认
        with mock.patch.object(server, "CONFIG", dict(
                server.CONFIG, rerank_log_monthly_cap_cny=8)):
            self.assertEqual(server._rerank_log_cap_cny(), 8.0)


class MonthSpendTest(unittest.TestCase):
    """月顶判别的台账切片（ts 当月锚/坏 ts 保守计入/他月与异 stage 排除）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = os.path.join(self.tmp.name, "生成用量.jsonl")
        month = time.strftime("%Y-%m")

        def row(ts, stage, est):
            return json.dumps({"ts": ts, "stage": stage, "model": "m",
                               "n": 1, "input_tokens": 1, "retries": 0,
                               "est_cny": est}, ensure_ascii=False)

        with open(self.ledger, "w", encoding="utf-8") as f:
            f.write(row(f"{month}-01 08:00:00", "rerank_log", 1.5) + "\n")
            f.write(row(f"{month}-02 09:00:00", "rerank_log", 2.0) + "\n")
            f.write(row("2020-01-01 00:00:00", "rerank_log", 99.0) + "\n")  # 他月排除
            f.write(row(f"{month}-03 10:00:00", "CR", 50.0) + "\n")          # 异 stage 排除
            f.write(json.dumps({"stage": "rerank_log", "est_cny": 0.5},
                               ensure_ascii=False) + "\n")                  # 坏 ts 保守计入
            f.write("{不是json" + "\n")                                     # 坏行忽略

    def tearDown(self):
        self.tmp.cleanup()

    def test_slices_only_current_month_rerank_log(self):
        self.assertAlmostEqual(server._rerank_month_spend(self.ledger), 4.0)

    def test_missing_file_is_zero(self):
        self.assertEqual(
            server._rerank_month_spend(os.path.join(self.tmp.name, "无此档.jsonl")), 0.0)

    def test_unreadable_returns_none(self):
        d = os.path.join(self.tmp.name, "adir")
        os.makedirs(d, exist_ok=True)
        self.assertIsNone(server._rerank_month_spend(d))   # IsADirectoryError→OSError


@clean_store_tests
class ProbeWorkerTest(unittest.TestCase):
    """探线程主体单测（直调 worker；台账路径/RERANK API 全 mock）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = os.path.join(self.tmp.name, "生成用量.jsonl")
        server._rerank_log_cap_warned = False
        self._api_patch = None

    def tearDown(self):
        if self._api_patch:
            self._api_patch.stop()
        server._rerank_log_cap_warned = False
        self.tmp.cleanup()

    def _mock_api(self, ret=([0.91, 0.80, 0.60], 1234), exc=None):
        calls = []

        def fake(query, docs, timeout=server.RERANK_LOG_TIMEOUT_S):
            calls.append({"query": query, "docs": list(docs), "timeout": timeout})
            if exc is not None:
                raise exc
            return ret

        self._api_patch = mock.patch.object(server, "_rerank_api_call", fake)
        self._api_patch.start()
        return calls

    def _run(self, svc, state="hit"):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), \
                mock.patch.object(server, "RERANK_LOG_LEDGER", self.ledger):
            server._rerank_log_probe_worker(svc, "查询题面X", state, "abcd1234")
        return out.getvalue()

    def _ledger_lines(self):
        if not os.path.exists(self.ledger):
            return []
        with open(self.ledger, encoding="utf-8") as f:
            return [json.loads(x) for x in f if x.strip()]

    def test_success_journal_line_and_ledger(self):
        api = self._mock_api()
        svc = _FakeProbeSvc(_CANDS)
        logged = self._run(svc)
        m = [ln for ln in logged.splitlines() if ln.startswith("[rerank_probe]")]
        self.assertEqual(len(m), 1)
        self.assertRegex(m[0], _PROBE_LINE_RE)
        # 0.91/0.80/0.60 → max=0.9100，≥0.75 两个、≥0.85 一个、≥0.95 零
        self.assertIn("n=3 max=0.9100 c075=2 c085=1 c095=0", m[0])
        self.assertIn("tok=1234 cny=0.000617 gold=na", m[0])
        self.assertIn("st=hit", m[0])
        # 查询哈希=sha256 前 12 hex（隐私纪律：题面原文绝不入 journal）
        self.assertIn(hashlib.sha256("查询题面X".encode()).hexdigest()[:12], m[0])
        self.assertNotIn("查询题面X", logged)
        # API 单发一次：docs=候选文本（E 判死池同构=纯内容不带 doc_id 前缀）
        self.assertEqual(len(api), 1)
        self.assertEqual(api[0]["query"], "查询题面X")
        self.assertEqual(api[0]["docs"], [c["text"] for c in _CANDS])
        self.assertEqual(api[0]["timeout"], 3.0)
        # 台账一行 stage=rerank_log（生成用量台账同款字段）
        rows = self._ledger_lines()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["stage"], "rerank_log")
        self.assertEqual(rows[0]["model"], "qwen3.7-text-rerank")
        self.assertEqual(rows[0]["n"], 3)
        self.assertEqual(rows[0]["input_tokens"], 1234)
        self.assertEqual(rows[0]["retries"], 0)
        self.assertAlmostEqual(rows[0]["est_cny"], 0.000617)
        self.assertTrue(rows[0]["ts"])

    def test_timeout_or_failure_skips_without_retry(self):
        api = self._mock_api(exc=TimeoutError("t"))
        logged = self._run(_FakeProbeSvc(_CANDS))
        self.assertEqual(len(api), 1)                       # 零重试
        self.assertIn("err=TimeoutError skip=1", logged)
        self.assertEqual(self._ledger_lines(), [])          # 失败不入台账

    def test_cap_soft_skip_warns_once(self):
        month = time.strftime("%Y-%m")
        with open(self.ledger, "w", encoding="utf-8") as f:
            f.write(json.dumps({"ts": f"{month}-01 00:00:00", "stage": "rerank_log",
                                "est_cny": 2.5}, ensure_ascii=False) + "\n")
            f.write(json.dumps({"ts": f"{month}-02 00:00:00", "stage": "rerank_log",
                                "est_cny": 2.5}, ensure_ascii=False) + "\n")
        api = self._mock_api()
        logged1 = self._run(_FakeProbeSvc(_CANDS))
        self.assertIn("skip=cap cum=5.0000 cap=5.00 warn=1", logged1)
        self.assertEqual(len(api), 0)                       # 超顶=探针不发
        self.assertEqual(len(self._ledger_lines()), 2)      # 台账不加行
        logged2 = self._run(_FakeProbeSvc(_CANDS))          # 第二次=静默跳过
        self.assertNotIn("[rerank_probe]", logged2)

    def test_empty_pool_and_candidate_failure(self):
        api = self._mock_api()
        self.assertIn("skip=empty_pool", self._run(_FakeProbeSvc([])))
        self.assertIn("err=RuntimeError skip=1",
                      self._run(_FakeProbeSvc(_CANDS, exc=RuntimeError("e"))))
        self.assertEqual(len(api), 0)

    def test_no_endpoint_skips(self):
        api = self._mock_api()
        with mock.patch.object(server, "_rerank_log_resolve_endpoint",
                               lambda: None):
            logged = self._run(_FakeProbeSvc(_CANDS))
        self.assertIn("skip=no_endpoint", logged)
        self.assertEqual(len(api), 0)


@clean_store_tests
class FireAndZeroChangeTest(unittest.TestCase):
    """/api/chat 挂点面：fire-and-forget 触发条件 + 探针开/关 SSE 逐字段一致
    （铁律①的主链路行为零变化断言）+ rag=miss 不 fire。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = os.path.join(self.tmp.name, "embeddings.jsonl")
        write_fixture(self.store)
        server._rerank_log_cap_warned = False

    def tearDown(self):
        server._rerank_log_cap_warned = False
        self.tmp.cleanup()

    def _svc(self, threshold=None):
        cfg = {"store_path": self.store, "topk": 2, "max_context_chars": 6000}
        if threshold is not None:
            cfg["score_threshold"] = threshold
        svc = rag.RagService(embed_fn=lambda q: list(QUERY), log=lambda line: None)
        svc.initialize(cfg)
        return svc

    def _chat(self, svc, cfg):
        body = {"messages": [{"role": "user", "content": "问句"}],
                "passcode": "pw-test"}
        out = io.StringIO()
        fired = []
        _orig_fire = server._rerank_log_fire   # 先捕原函数（patch 前引用，防自递归）

        def _cap_fire(*a, **k):
            t = _orig_fire(*a, **k)
            fired.append({"args": a, "thread": t})
            if t is not None:
                t.join(timeout=5)      # 测试确定性收编（生产路径绝不 join）
            return t

        with mock.patch.object(server.httpx, "AsyncClient", _FakeAsyncClient), \
                mock.patch.object(server, "CONFIG", cfg), \
                mock.patch.object(server, "API_KEY", "stub-key"), \
                mock.patch.object(server, "rag_service", svc), \
                mock.patch.object(server, "_rerank_log_fire", _cap_fire), \
                mock.patch.object(server, "_rerank_log_resolve_endpoint",
                                  lambda: ("http://rerank.test/", "stub-key")), \
                contextlib.redirect_stdout(out):
            with TestClient(server.app) as client:
                with client.stream("POST", "/api/chat", json=body) as resp:
                    self.assertEqual(resp.status_code, 200)
                    events = [json.loads(ln[5:].strip()) for ln in resp.iter_lines()
                              if ln.startswith("data:")]
        return events, out.getvalue(), fired

    def test_off_zero_probe_and_on_sse_identical(self):
        off_cfg = dict(_auth_ok_cfg(), rerank_log_enabled=False)
        on_cfg = dict(_auth_ok_cfg(), rerank_log_enabled=True)
        ledger = os.path.join(self.tmp.name, "生成用量.jsonl")

        # 关态：零探针零日志（真 RagService+探针数据面记录器）——挂点照调
        # _rerank_log_fire（闸在函数内），但必须零线程启动=thread None
        svc_off = _FakeProbeSvc(delegate=self._svc())
        api_calls = []
        with mock.patch.object(server, "RERANK_LOG_LEDGER", ledger), \
                mock.patch.object(server, "_rerank_api_call",
                                  lambda q, d, timeout=3.0: (
                                      api_calls.append(1), ([0.9], 100))[1]):
            ev_off, log_off, fired_off = self._chat(svc_off, off_cfg)
        self.assertEqual(len(fired_off), 1)
        self.assertIsNone(fired_off[0]["thread"])          # 开关关=不启动探线程
        self.assertEqual(svc_off.probe_calls, [])        # 零探针
        self.assertNotIn("[rerank_probe]", log_off)      # 零日志
        self.assertEqual(api_calls, [])                  # 零 API
        self.assertFalse(os.path.exists(ledger))         # 零台账

        # 开态：探针真跑（守护线程收编 join），SSE 与关态逐字段一致
        svc_on = _FakeProbeSvc(_CANDS, delegate=self._svc())
        with mock.patch.object(server, "RERANK_LOG_LEDGER", ledger), \
                mock.patch.object(server, "_rerank_api_call",
                                  lambda q, d, timeout=3.0: (
                                      api_calls.append(1), ([0.9], 100))[1]):
            ev_on, log_on, fired_on = self._chat(svc_on, on_cfg)
        self.assertEqual(len(fired_on), 1)
        self.assertIsNotNone(fired_on[0]["thread"])       # 开关开=探线程启动
        self.assertEqual(fired_on[0]["args"][0], svc_on)
        self.assertEqual(fired_on[0]["args"][1], "问句")
        self.assertEqual(fired_on[0]["args"][2], "hit")   # rag_state 透传
        self.assertEqual([c[0] for c in svc_on.probe_calls], ["问句"])
        self.assertIn("[rerank_probe]", log_on)
        self.assertNotIn("stub-key", log_on)              # key 绝不落日志
        self.assertNotIn("http://rerank.test", log_on)    # 端点 URL 不入 journal
        self.assertEqual(len(api_calls), 1)
        with open(ledger, encoding="utf-8") as f:         # 台账恰一行
            rows = [json.loads(x) for x in f if x.strip()]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["stage"], "rerank_log")
        # 铁律①断言：事件序逐字段一致（sources/off_topic/delta/error 全同）
        self.assertEqual(json.dumps(ev_on, ensure_ascii=False),
                         json.dumps(ev_off, ensure_ascii=False))

    def test_low_score_state_fires_and_miss_does_not(self):
        on_cfg = dict(_auth_ok_cfg(), rerank_log_enabled=True)
        ledger = os.path.join(self.tmp.name, "生成用量.jsonl")
        with mock.patch.object(server, "RERANK_LOG_LEDGER", ledger), \
                mock.patch.object(server, "_rerank_api_call",
                                  lambda q, d, timeout=3.0: ([0.9], 100)):
            # low_score（拒答信号主采数面）：fire，st=low_score
            #（fixture QUERY↔c1 余弦=1.0，阈值 1.01>1.0 → LowScoreResult）
            svc_ls = _FakeProbeSvc(_CANDS, delegate=self._svc(threshold=1.01))
            _, log_ls, fired_ls = self._chat(svc_ls, on_cfg)
            self.assertEqual(len(fired_ls), 1)
            self.assertEqual(fired_ls[0]["args"][2], "low_score")
            self.assertRegex(
                next(ln for ln in log_ls.splitlines()
                     if ln.startswith("[rerank_probe]")), _PROBE_LINE_RE)
        # miss（补嵌失败=检索失败面）：闸在 fire 内拦 rag_state=miss=不启动线程
        svc_miss = _FakeProbeSvc(delegate=rag.RagService(
            embed_fn=lambda q: (_ for _ in ()).throw(RuntimeError("x")),
            log=lambda line: None))
        svc_miss._delegate.initialize({"store_path": self.store})
        _, log_miss, fired_miss = self._chat(svc_miss, on_cfg)
        self.assertEqual(len(fired_miss), 1)
        self.assertIsNone(fired_miss[0]["thread"])
        self.assertEqual(svc_miss.probe_calls, [])
        self.assertNotIn("[rerank_probe]", log_miss)


@clean_store_tests
class EvalHarnessZeroPerturbTest(unittest.TestCase):
    """评测面零扰动论证+快检：探针挂点外置在 server /api/chat——离线评测
    harness 直连 rag.RagService.retrieve()/模块函数（建库/scripts/retrieve.py
    同面），不经挂点=零探针；rag 侧 rerank_probe_candidates 为新增只读方法，
    retrieve() 主链路签名与行为零改动。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = os.path.join(self.tmp.name, "embeddings.jsonl")
        write_fixture(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def test_direct_retrieve_stable_and_probe_free(self):
        svc = rag.RagService(embed_fn=lambda q: list(QUERY), log=lambda line: None)
        svc.initialize({"store_path": self.store, "topk": 2,
                        "max_context_chars": 6000})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            r1 = svc.retrieve("问句")
            r2 = svc.retrieve("问句")          # 确定性：同查询同结果
        self.assertEqual(r1, r2)
        self.assertIsInstance(r1, tuple)                # hit 形态=(evidence, sources)
        self.assertTrue(r1[0])                          # 证据非空
        self.assertNotIn("[rerank_probe]", out.getvalue())   # 直连面零探针日志
        # 候选池旁路可用但不被主链路消费（只读方法独立存在）
        cands = svc.rerank_probe_candidates("问句", 3)
        self.assertTrue(all(set(c) == {"id", "doc_id", "locator", "cos", "text"}
                            for c in cands))
        self.assertEqual(svc.retrieve("问句"), r1)          # 旁路调用后主链路不变

    def test_hook_isolation_source_guard(self):
        """源面快检：_rerank_log_fire 只在 server /api/chat 一处挂点（rag 模块
        零引用）；rag.py 的 rerank_probe_candidates 只有方法定义一处（retrieve
        主链路不消费）。"""
        with open(server.__file__, encoding="utf-8") as f:
            src_server = f.read()
        self.assertEqual(src_server.count("_rerank_log_fire("), 2)  # def+唯一挂点
        with open(rag.__file__, encoding="utf-8") as f:
            src_rag = f.read()
        self.assertEqual(src_rag.count("rerank_probe_candidates"), 1)  # 仅 def


if __name__ == "__main__":
    unittest.main()
