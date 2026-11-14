# -*- coding: utf-8 -*-
"""rerank 行为级拒答拦截（0.75 档决策 2026-10-12）单测。

铁律面（对应 server.py 拦截段头注）：
- 双键默认关（rerank_refusal_enabled 缺省 false）=零拦截零 [rerank_gate] 日志，
  /api/chat 行为与既往逐字节一致；
- 开+池 max<阈值 → rerank_refused 态：首数据事件 off_topic、无 sources 事件、
  裸答照常流式；journal [rerank_gate] decision=refuse + [chat] rag=rerank_refused；
- fail-open 铁律：cap/空池/无端点/异常一律放行（decision=skip，行为=正常 hit）；
- 台账 stage=rerank_gate；月顶软顶与探针 rerank_log 两段共账。

零网络零计费：rerank API 调用/端点解析全 mock（形态同 tests/test_rerank_log.py）。
"""
import contextlib
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
import server
from tests import clean_store_tests  # noqa: F401  chat 型限速免疫
from tests.test_rag import QUERY, write_fixture
from tests.test_server_rag import _FakeAsyncClient, _auth_ok_cfg

_CANDS = [{"id": f"c{i}", "doc_id": f"DOC-{i}", "locator": "§1.1",
           "cos": 0.9, "text": f"候选内容{i}"} for i in range(1, 4)]

_GATE_LINE = re.compile(
    r"^\[rerank_gate\] ts=\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} "
    r"q=[0-9a-f]{12} trace=[0-9a-f]{8} decision=(refuse|pass|skip)")


class _FakeProbeSvc:
    """探针数据面替身（rerank_probe_candidates 可注入；其余透传真 RagService）。"""

    def __init__(self, cands=None, exc=None, delegate=None):
        self._cands = list(cands or [])
        self._exc = exc
        self._delegate = delegate

    def __getattr__(self, name):
        return getattr(self._delegate, name)

    def rerank_probe_candidates(self, query, n=50):
        if self._exc is not None:
            raise self._exc
        return list(self._cands)


class FlagTest(unittest.TestCase):
    def test_default_off_and_explicit_on(self):
        cfg = {k: v for k, v in server.CONFIG.items()
               if k != "rerank_refusal_enabled"}
        with mock.patch.object(server, "CONFIG", cfg):
            self.assertFalse(server._rerank_refusal_enabled())  # 无键=默认关
        with mock.patch.object(server, "CONFIG",
                               {**cfg, "rerank_refusal_enabled": True}):
            self.assertTrue(server._rerank_refusal_enabled())

    def test_threshold_default_and_cleaning(self):
        cfg = {k: v for k, v in server.CONFIG.items()
               if k != "rerank_refusal_threshold"}
        with mock.patch.object(server, "CONFIG", cfg):
            self.assertEqual(server._rerank_refusal_threshold(), 0.75)
        for bad in ("x", None, 0, 1, -0.5, 1.5, float("nan")):
            with mock.patch.object(server, "CONFIG",
                                   {**cfg, "rerank_refusal_threshold": bad}):
                self.assertEqual(server._rerank_refusal_threshold(), 0.75)
        with mock.patch.object(server, "CONFIG",
                               {**cfg, "rerank_refusal_threshold": 0.85}):
            self.assertEqual(server._rerank_refusal_threshold(), 0.85)


class GateCheckTest(unittest.TestCase):
    """_rerank_gate_check 单元面（无 HTTP）：判定/fail-open/台账/共账。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = os.path.join(self.tmp.name, "生成用量.jsonl")
        server._rerank_gate_cap_warned = False

    def tearDown(self):
        server._rerank_gate_cap_warned = False
        self.tmp.cleanup()

    def _check(self, svc, scores=(0.5,), cfg=None, cap=None):
        ledger = os.path.join(self.tmp.name, f"账-{id(svc)}-{scores[0]}-{cap}.jsonl")
        with mock.patch.object(server, "CONFIG", cfg or {}), \
                mock.patch.object(server, "RERANK_LOG_LEDGER", ledger), \
                mock.patch.object(server, "_rerank_log_resolve_endpoint",
                                  lambda: ("http://t/", "k")), \
                mock.patch.object(server, "_rerank_api_call",
                                  lambda q, d, timeout=3.0: (list(scores), 100)):
            if cap is not None:
                # 桩 ts 须落当月（月顶切片=ts[:7] 当月锚，server.
                # _rerank_month_spend）：固定日期随时间滚出当月即陈旧
                # （2026-11-01 三红根因=2026-10-12 桩被切片排除）。
                with open(ledger, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"ts": f"{time.strftime('%Y-%m')}-01 00:00:00",
                                        "stage": "rerank_log",
                                        "est_cny": cap}) + "\n")
            return server._rerank_gate_check(svc, "问句"), ledger

    def test_refuse_and_pass(self):
        svc = _FakeProbeSvc(_CANDS)
        (refused, mx, err), ledger = self._check(svc, scores=(0.3, 0.6))
        self.assertTrue(refused)
        self.assertEqual(mx, 0.6)
        self.assertIsNone(err)
        with open(ledger, encoding="utf-8") as f:
            rows = [json.loads(x) for x in f if x.strip()]
        self.assertEqual([r["stage"] for r in rows], ["rerank_gate"])
        (refused, mx, err), _ = self._check(svc, scores=(0.8, 0.91))
        self.assertFalse(refused)
        self.assertEqual(mx, 0.91)
        self.assertIsNone(err)

    def test_fail_open_faces(self):
        svc = _FakeProbeSvc(_CANDS)
        (r, mx, err), _ = self._check(svc, cap=9.0)                # 月顶超=退化不拦
        self.assertFalse(r)
        self.assertEqual(err, "cap")
        (r, mx, err), _ = self._check(_FakeProbeSvc(exc=RuntimeError("x")))
        self.assertFalse(r)
        self.assertEqual(err, "RuntimeError")  # 异常类名
        (r, mx, err), _ = self._check(_FakeProbeSvc([]))
        self.assertFalse(r)
        self.assertEqual(err, "empty_pool")

    def test_month_spend_counts_both_stages(self):
        # 桩 ts 落当月（月顶切片当月锚；固定 2026-10-12 桩在 11 月跑=0.0
        # 假红——2026-11-01 陈旧根因），双 stage 共账断言语义不变。
        month = time.strftime("%Y-%m")
        with open(self.ledger, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": f"{month}-01 00:00:00", "stage": "rerank_log",
                                "est_cny": 2.0}) + "\n")
            f.write(json.dumps({"ts": f"{month}-02 00:00:00", "stage": "rerank_gate",
                                "est_cny": 1.5}) + "\n")
            f.write(json.dumps({"ts": f"{month}-03 00:00:00", "stage": "other",
                                "est_cny": 99.0}) + "\n")
        with mock.patch.object(server, "RERANK_LOG_LEDGER", self.ledger):
            self.assertAlmostEqual(server._rerank_month_spend(), 3.5)


@clean_store_tests
class ChatFlowTest(unittest.TestCase):
    """SSE 级：拒答分支事件流 + fail-open 行为 + 默认关零增量。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = os.path.join(self.tmp.name, "embeddings.jsonl")
        write_fixture(self.store)
        server._rerank_gate_cap_warned = False
        server._rerank_log_cap_warned = False

    def tearDown(self):
        server._rerank_gate_cap_warned = False
        server._rerank_log_cap_warned = False
        self.tmp.cleanup()

    def _svc(self):
        svc = rag.RagService(embed_fn=lambda q: list(QUERY), log=lambda line: None)
        svc.initialize({"store_path": self.store, "topk": 2,
                        "max_context_chars": 6000})
        return svc

    def _chat(self, svc, cfg=None, scores=(0.9,)):
        cfg = cfg or dict(_auth_ok_cfg())
        body = {"messages": [{"role": "user", "content": "问句"}],
                "passcode": "pw-test"}
        out = io.StringIO()
        ledger = os.path.join(self.tmp.name, "生成用量.jsonl")
        with mock.patch.object(server.httpx, "AsyncClient", _FakeAsyncClient), \
                mock.patch.object(server, "CONFIG", cfg), \
                mock.patch.object(server, "API_KEY", "stub-key"), \
                mock.patch.object(server, "rag_service", svc), \
                mock.patch.object(server, "_rerank_log_fire", lambda *a, **k: None), \
                mock.patch.object(server, "RERANK_LOG_LEDGER", ledger), \
                mock.patch.object(server, "_rerank_log_resolve_endpoint",
                                  lambda: ("http://t/", "k")), \
                mock.patch.object(server, "_rerank_api_call",
                                  lambda q, d, timeout=3.0: (list(scores), 100)), \
                contextlib.redirect_stdout(out):
            with TestClient(server.app) as client:
                with client.stream("POST", "/api/chat", json=body) as resp:
                    self.assertEqual(resp.status_code, 200)
                    events = [json.loads(ln[5:].strip()) for ln in resp.iter_lines()
                              if ln.startswith("data:")]
        return events, out.getvalue(), ledger

    def test_default_off_identical_hit_flow(self):
        # 无键=默认关：正常 hit 流（sources 事件在场）+零 [rerank_gate] 行
        ev, log, ledger = self._chat(_FakeProbeSvc(_CANDS, delegate=self._svc()))
        self.assertTrue(any("sources" in e for e in ev))
        self.assertNotIn("[rerank_gate]", log)
        self.assertNotIn("rerank_refused", log)
        self.assertFalse(os.path.exists(ledger))

    def test_refused_flow_off_topic_no_sources(self):
        cfg = dict(_auth_ok_cfg(), rerank_refusal_enabled=True,
                   rerank_refusal_threshold=0.75)
        ev, log, ledger = self._chat(
            _FakeProbeSvc(_CANDS, delegate=self._svc()), cfg=cfg, scores=(0.3, 0.5))
        self.assertEqual(ev[0], {"type": "off_topic"})       # 首数据事件=拒答提示
        self.assertFalse(any("sources" in e for e in ev))    # 零出处事件
        self.assertTrue(any("error" in e for e in ev[1:]))  # 伪上游恒超时：流过闸进裸答面即证
        m = [ln for ln in log.splitlines() if ln.startswith("[rerank_gate]")]
        self.assertEqual(len(m), 1)
        self.assertRegex(m[0], _GATE_LINE)
        self.assertIn("decision=refuse", m[0])
        self.assertIn("max=0.5000", m[0])
        chat = [ln for ln in log.splitlines() if "[chat]" in ln]
        ref = [ln for ln in chat if "rag=rerank_refused" in ln]
        self.assertTrue(ref)
        # top1= 保留原 hit 通道排序分（deploy_check 核验同口径：q= 与 top1= 双全，
        # rerank 判定分在 [rerank_gate] 行——server/deploy_check 跨件契约锁）
        self.assertRegex(ref[0], r'\bq="[^"]*"')
        self.assertRegex(ref[0], r"\btop1=(?:na|\d+(?:\.\d+)?)\b")
        with open(ledger, encoding="utf-8") as f:
            rows = [json.loads(x) for x in f if x.strip()]
        self.assertEqual([r["stage"] for r in rows], ["rerank_gate"])

    def test_pass_and_failopen_keep_hit_flow(self):
        cfg = dict(_auth_ok_cfg(), rerank_refusal_enabled=True,
                   rerank_refusal_threshold=0.75)
        ev, log, _ = self._chat(
            _FakeProbeSvc(_CANDS, delegate=self._svc()), cfg=cfg, scores=(0.9,))
        self.assertTrue(any("sources" in e for e in ev))
        self.assertFalse(any(e.get("type") == "off_topic" for e in ev))
        self.assertIn("decision=pass", log)
        # 异常=fail-open：正常 hit 流照答（decision=skip err=…）
        ev2, log2, _ = self._chat(
            _FakeProbeSvc(_CANDS, exc=RuntimeError("boom"),
                          delegate=self._svc()), cfg=cfg)
        self.assertTrue(any("sources" in e for e in ev2))
        self.assertIn("decision=skip err=RuntimeError", log2)


if __name__ == "__main__":
    unittest.main()
