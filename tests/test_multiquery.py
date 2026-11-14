# -*- coding: utf-8 -*-
"""rag.py + multiquery.py multi-query 查询改写离线单测：清洗/变体生成（mock
httpx）/预算与超时退化/多路 RRF 融合/RagService 开关两态与三开关共存矩阵。
零网络零 API，夹具全内联。

跑法（tests/ 惯例）：仓根起 venv/bin/python -m tests.test_multiquery。
沿革：原根级临时位 test_multiquery.py（独立成件避免与并行代理冲突），
2026-10-07 A2 小修5 归位 tests/（git mv；件内容零改动除本注）。

夹具向量语义（8 维）：q0 中文意译题面 embed=V0=[1,0,...] → 余弦序
c1>c2>c3(0 分 tie 行序)>c4；英文变体 embed=V1=[0,1,...] → 余弦序 c3>c2>c1>c4
（c3=英文语料块，余弦圈外被英文变体拉回）；v2=V2=[0,.6,.8,...] → c4>c3>c2>c1。
"""
import json
import os
import tempfile
import time
import unittest
from unittest import mock

import httpx

import multiquery
import rag


# ---------------------------------------------------------------------------
# 夹具：4 块 8 维假向量 + 查询向量映射
# ---------------------------------------------------------------------------
def _rec(rid, doc_id, locator, content, vec):
    return {"id": rid, "content": content, "doc_id": doc_id,
            "version": "V1", "locator": locator, "embedding": vec}


SERVICE_RECS = [
    _rec("c1", "DOC-1", "§1", "宏切换参数概述与常见配置说明", [1, 0, 0, 0, 0, 0, 0, 0]),
    _rec("c2", "DOC-2", "5.1.1", "TS 36.214 RSRP definition table",
         [0.9, 0.1, 0, 0, 0, 0, 0, 0]),
    _rec("c3", "DOC-3", "A.1", "SRS power control p0-NominalPUSCH parameter card",
         [0, 1, 0, 0, 0, 0, 0, 0]),
    _rec("c4", "DOC-4", "§2", "掉话率统计口径说明", [0, 0, 1, 0, 0, 0, 0, 0]),
]
Q0 = "上行探测参考信号的功率控制参数有哪些"
V0 = [1, 0, 0, 0, 0, 0, 0, 0]            # q0 → c1,c2,c3,c4
V_EN = "SRS power control parameters"
V1 = [0, 1, 0, 0, 0, 0, 0, 0]            # 英文变体 → c3,c2,c1,c4
V_ZH = "SRS 功控相关参数说明"
V2 = [0, 0.6, 0.8, 0, 0, 0, 0, 0]        # 中文改述 → c4,c3,c2,c1


def _embed_map(t):
    return {"q0": list(V0), Q0: list(V0), "v_en": list(V1), V_EN: list(V1),
            "v_zh": list(V2), V_ZH: list(V2)}.get(t, list(V0))


class _Silent:
    def __init__(self):
        self.lines = []

    def __call__(self, line):
        self.lines.append(line)


# ---------------------------------------------------------------------------
# multiquery 纯函数：条数钳制与清洗
# ---------------------------------------------------------------------------
class ClampAndCleanTest(unittest.TestCase):
    def test_clamp_bounds(self):
        self.assertEqual(multiquery.clamp_n_variants(2), 2)
        self.assertEqual(multiquery.clamp_n_variants(9), 2)
        self.assertEqual(multiquery.clamp_n_variants(0), 0)   # 0=不产变体
        self.assertEqual(multiquery.clamp_n_variants(-3), 0)
        self.assertEqual(multiquery.clamp_n_variants("x"), multiquery.DEFAULT_MQ_N_VARIANTS)
        self.assertEqual(multiquery.clamp_n_variants(None), multiquery.DEFAULT_MQ_N_VARIANTS)

    def test_clean_variant_strips_markers_quotes_newlines(self):
        self.assertEqual(multiquery.clean_variant('1. "SRS power control"\n'),
                         "SRS power control")
        self.assertEqual(multiquery.clean_variant("- 「功控参数说明」"),
                         "功控参数说明")
        self.assertEqual(multiquery.clean_variant("2）a\nb\tc"), "a b c")

    def test_clean_variant_think_tag_and_clamp(self):
        self.assertEqual(multiquery.clean_variant("<think>推理</think>SRS 功控"),
                         "SRS 功控")
        long = "x" * (multiquery.DEFAULT_MQ_MAX_VARIANT_CHARS + 50)
        self.assertEqual(len(multiquery.clean_variant(long)),
                         multiquery.DEFAULT_MQ_MAX_VARIANT_CHARS)
        self.assertEqual(multiquery.clean_variant(None), "")
        self.assertEqual(multiquery.clean_variant("   "), "")

    def test_clean_variants_dedupe_and_cap(self):
        out = multiquery.clean_variants(Q0, ["  " + Q0 + "  ", V_EN, V_EN, V_ZH], 2)
        self.assertEqual(out, [V_EN, V_ZH])  # 与原查询同（空白不敏感）→ 丢；重复 → 丢
        self.assertEqual(multiquery.clean_variants(Q0, [V_EN, V_ZH, "第三条"], 1), [V_EN])
        self.assertEqual(multiquery.clean_variants(Q0, "不是列表", 2), [])
        self.assertEqual(multiquery.clean_variants(Q0, [], 2), [])
        self.assertEqual(multiquery.clean_variants(Q0, [V_EN], 0), [])  # n=0 全弃


# ---------------------------------------------------------------------------
# 变体生成：mock httpx（零网络），按序回放响应/异常
# ---------------------------------------------------------------------------
def _ok_payload(content):
    return {"choices": [{"message": {"content": content}}]}


def _make_client_cls(responses, sleep_s=0.0):
    """造 multiquery.httpx.Client 替身类：按序回放（payload 或异常），记录请求。"""
    calls = []

    class _C:
        def __init__(self, *a, **kw):
            self._timeout = kw.get("timeout")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, json=None, headers=None):
            calls.append({"url": url, "json": json, "headers": headers,
                          "timeout": self._timeout})
            if sleep_s:
                time.sleep(sleep_s)
            r = responses[len(calls) - 1] if len(calls) <= len(responses) \
                else RuntimeError("意外的多余调用")
            if isinstance(r, Exception):
                raise r
            return _FakeResp(r)

    class _FakeResp:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            pass

        def json(self):
            return self._payload

    return _C, calls


ENDPOINT = ("http://bailian.example", "sk-test-key")


class GenerateVariantTest(unittest.TestCase):
    def setUp(self):
        self.log = _Silent()

    def test_success_parses_and_cleans(self):
        cls, calls = _make_client_cls([_ok_payload('1. "SRS power control"\n')])
        with mock.patch.object(multiquery.httpx, "Client", cls):
            v = multiquery.generate_variant(Q0, 0, model="qwen3.8-flash",
                                            timeout=2.0, endpoint=ENDPOINT,
                                            log=self.log)
        self.assertEqual(v, "SRS power control")
        req = calls[0]
        self.assertTrue(req["url"].endswith(multiquery.CHAT_PATH))
        self.assertEqual(req["headers"]["Authorization"], "Bearer sk-test-key")
        self.assertEqual(req["json"]["model"], "qwen3.8-flash")
        self.assertEqual(req["json"]["messages"][1]["content"], Q0)  # 题面入 user 消息
        self.assertEqual(req["json"]["temperature"], 0)
        self.assertTrue(any("ok=1" in ln and "kind=en" in ln for ln in self.log.lines))

    def test_http_error_returns_none(self):
        cls, _ = _make_client_cls([httpx.HTTPStatusError("503", request=None, response=None)])
        with mock.patch.object(multiquery.httpx, "Client", cls):
            v = multiquery.generate_variant(Q0, 0, endpoint=ENDPOINT, log=self.log)
        self.assertIsNone(v)
        self.assertTrue(any("ok=0" in ln and "err=HTTPStatusError" in ln
                            for ln in self.log.lines))

    def test_empty_or_malformed_payload_returns_none(self):
        for payload in ({}, {"choices": []}, _ok_payload("  ")):
            cls, _ = _make_client_cls([payload])
            with mock.patch.object(multiquery.httpx, "Client", cls):
                self.assertIsNone(multiquery.generate_variant(
                    Q0, 1, endpoint=ENDPOINT, log=self.log))

    def test_endpoint_none_fails_gracefully(self):
        self.assertIsNone(multiquery.generate_variant(Q0, 0, endpoint=None, log=self.log))
        self.assertTrue(any("err=RuntimeError" in ln for ln in self.log.lines))


class GenerateVariantsTest(unittest.TestCase):
    def setUp(self):
        self.log = _Silent()

    def test_two_kinds_happy_path(self):
        cls, calls = _make_client_cls([_ok_payload(V_EN), _ok_payload(V_ZH)])
        with mock.patch.object(multiquery.httpx, "Client", cls):
            got = multiquery.generate_variants(Q0, n_variants=2, endpoint=ENDPOINT,
                                               log=self.log)
        self.assertEqual(got, [V_EN, V_ZH])
        self.assertEqual(len(calls), 2)
        # 第 0/1 次调用分别用英文/中文规格的 system prompt
        self.assertIn("英文", calls[0]["json"]["messages"][0]["content"])
        self.assertIn("中文", calls[1]["json"]["messages"][0]["content"])

    def test_partial_failure_keeps_earlier_variant(self):
        cls, _ = _make_client_cls([_ok_payload(V_EN), httpx.ConnectError("x")])
        with mock.patch.object(multiquery.httpx, "Client", cls):
            got = multiquery.generate_variants(Q0, n_variants=2, endpoint=ENDPOINT,
                                               log=self.log)
        self.assertEqual(got, [V_EN])  # 部分成功好过全弃
        self.assertTrue(any("err=ConnectError" in ln for ln in self.log.lines))

    def test_budget_spent_stops_after_first_call(self):
        # 预算 0.05s，替身睡 0.2s 后超时：第 0 条失败且耗时超预算 → 不再发第 1 条
        cls, calls = _make_client_cls([httpx.TimeoutException("t")], sleep_s=0.2)
        with mock.patch.object(multiquery.httpx, "Client", cls):
            got = multiquery.generate_variants(Q0, n_variants=2, timeout=0.05,
                                               endpoint=ENDPOINT, log=self.log)
        self.assertEqual(got, [])
        self.assertEqual(len(calls), 1)
        self.assertTrue(any("gen stop" in ln and "budget_spent" in ln
                            for ln in self.log.lines))

    def test_zero_budget_or_n_zero_no_calls(self):
        cls, calls = _make_client_cls([])
        with mock.patch.object(multiquery.httpx, "Client", cls):
            self.assertEqual(multiquery.generate_variants(
                Q0, n_variants=2, timeout=0, endpoint=ENDPOINT), [])
            self.assertEqual(multiquery.generate_variants(
                Q0, n_variants=0, endpoint=ENDPOINT), [])
            self.assertEqual(multiquery.generate_variants(
                "", n_variants=2, endpoint=ENDPOINT), [])
        self.assertEqual(calls, [])


# ---------------------------------------------------------------------------
# 多路 RRF 融合（fuse_hits 的 N 路推广）
# ---------------------------------------------------------------------------
def _hit(rank, idx, score=0.5):
    return {"rank": rank, "score": score, "idx": idx,
            "rec": {"id": f"c{idx + 1}", "doc_id": f"DOC-{idx + 1}", "locator": "L"}}


class WallClockTest(unittest.TestCase):
    """mq_wall_clock 墙钟看门狗（2026-09-21 迭代轮，运营/迭代轮-20260921.md）。

    判定实证（运营/hybrid-mq判定-20260919.md §三）：httpx per-op 超时下 flash
    单调用 7.18s>3s 预算仍成功返回——看门狗把预算升级为硬墙钟。"""

    def setUp(self):
        self.log = _Silent()

    def test_wall_clock_cut_slow_call(self):
        cls, _ = _make_client_cls([_ok_payload("en variant slow")], sleep_s=0.6)
        t0 = time.time()
        with mock.patch.object(multiquery.httpx, "Client", cls):
            got = multiquery.generate_variants(
                Q0, n_variants=1, timeout=0.15, endpoint=ENDPOINT,
                log=self.log, wall_clock=True)
        self.assertEqual(got, [])                        # 到点即弃→零变体
        self.assertLess(time.time() - t0, 0.5)           # 不等慢调用（墙钟硬界）
        self.assertTrue(any("watchdog" in ln and "cut wall_clock" in ln
                            for ln in self.log.lines))

    def test_wall_clock_fast_call_passes(self):
        cls, _ = _make_client_cls([_ok_payload("en variant fast")])
        with mock.patch.object(multiquery.httpx, "Client", cls):
            got = multiquery.generate_variants(
                Q0, n_variants=1, timeout=2.0, endpoint=ENDPOINT,
                log=self.log, wall_clock=True)
        self.assertEqual(got, ["en variant fast"])       # 预算内照常取回
        self.assertFalse(any("watchdog" in ln for ln in self.log.lines))

    def test_wall_clock_off_legacy_waits_out(self):
        # 默认（false=旧行为）：慢调用不被切——per-op 超时不缚墙钟，预算只在
        # 两次调用之间检查，单调用跑完即得变体（判定 26 问全部 got=1 的形态）
        cls, _ = _make_client_cls([_ok_payload("en variant slow")], sleep_s=0.6)
        t0 = time.time()
        with mock.patch.object(multiquery.httpx, "Client", cls):
            got = multiquery.generate_variants(
                Q0, n_variants=1, timeout=0.15, endpoint=ENDPOINT,
                log=self.log, wall_clock=False)
        self.assertEqual(got, ["en variant slow"])
        self.assertGreaterEqual(time.time() - t0, 0.6)
        self.assertFalse(any("watchdog" in ln for ln in self.log.lines))

    def test_wall_clock_cut_then_no_second_call(self):
        # 首变体被切后剩余预算≤0 → 不发第二变体（gen stop）
        cls, calls = _make_client_cls([_ok_payload("v1")], sleep_s=0.6)
        with mock.patch.object(multiquery.httpx, "Client", cls):
            got = multiquery.generate_variants(
                Q0, n_variants=2, timeout=0.15, endpoint=ENDPOINT,
                log=self.log, wall_clock=True)
        self.assertEqual(got, [])
        self.assertTrue(any("gen stop" in ln for ln in self.log.lines))
        self.assertEqual(len(calls), 1)                  # zh 变体未发


class RRFFuseHitListsTest(unittest.TestCase):
    def test_formula_and_attribution(self):
        l0 = [_hit(1, 0), _hit(2, 1)]          # A=idx0 r1, B=idx1 r2
        l1 = [_hit(1, 2), _hit(2, 1)]          # C=idx2 r1, B=idx1 r2
        out = multiquery.rrf_fuse_hit_lists([l0, l1], topk=3)
        by_idx = {h["idx"]: h for h in out}
        self.assertAlmostEqual(by_idx[1]["score"], 2.0 / 62, places=12)  # 两路 r2
        self.assertAlmostEqual(by_idx[0]["score"], 1.0 / 61, places=12)
        self.assertAlmostEqual(by_idx[2]["score"], 1.0 / 61, places=12)
        self.assertEqual(by_idx[1]["queries"], "q0+q1")
        self.assertEqual(by_idx[0]["queries"], "q0")
        self.assertEqual(by_idx[2]["queries"], "q1")
        self.assertEqual(by_idx[0]["q_ranks"], (1, None))
        self.assertEqual(by_idx[1]["q_ranks"], (2, 2))
        # B 两路叠加最高；A/C 同分 tie → 查询序优先（q0 的 A 先于仅 q1 的 C）
        self.assertEqual([h["idx"] for h in out], [1, 0, 2])
        self.assertEqual([h["rank"] for h in out], [1, 2, 3])

    def test_duplicate_idx_in_one_list_keeps_best_rank(self):
        lst = [_hit(3, 0), _hit(1, 0)]  # 同 idx 重复（防御面）→ 只计最优 rank
        out = multiquery.rrf_fuse_hit_lists([lst], topk=1)
        self.assertAlmostEqual(out[0]["score"], 1.0 / 61, places=12)

    def test_single_list_preserves_order(self):
        lst = [_hit(1, 3), _hit(2, 1), _hit(3, 0)]
        out = multiquery.rrf_fuse_hit_lists([lst], topk=3)
        self.assertEqual([h["idx"] for h in out], [3, 1, 0])
        self.assertTrue(all(h["queries"] == "q0" for h in out))

    def test_empty_and_none_inputs(self):
        self.assertEqual(multiquery.rrf_fuse_hit_lists([], topk=3), [])
        self.assertEqual(multiquery.rrf_fuse_hit_lists([[], None, []]), [])

    def test_topk_truncation(self):
        lst = [_hit(i, i) for i in range(5)]
        out = multiquery.rrf_fuse_hit_lists([lst], topk=2)
        self.assertEqual([h["idx"] for h in out], [0, 1])

    def test_invalid_rrf_k_falls_back_to_60(self):
        l0, l1 = [_hit(1, 0)], [_hit(1, 1)]
        out = multiquery.rrf_fuse_hit_lists([l0, l1], topk=2, rrf_k=float("nan"))
        self.assertAlmostEqual(out[0]["score"], 1.0 / 61, places=12)

    def test_inputs_not_mutated(self):
        l0, l1 = [_hit(1, 0), _hit(2, 1)], [_hit(1, 2)]
        snap = (json.dumps(l0, sort_keys=True), json.dumps(l1, sort_keys=True))
        multiquery.rrf_fuse_hit_lists([l0, l1], topk=3)
        self.assertEqual((json.dumps(l0, sort_keys=True),
                          json.dumps(l1, sort_keys=True)), snap)


# ---------------------------------------------------------------------------
# RagService：开关两态、退化路径与三开关共存矩阵
# ---------------------------------------------------------------------------
class RagServiceMQTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "embeddings.jsonl")
        with open(self.path, "w", encoding="utf-8") as f:
            for r in SERVICE_RECS:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        self.log = _Silent()
        self.embeds = []

    def tearDown(self):
        self.tmp.cleanup()

    def _embed(self, t):
        self.embeds.append(t)
        return _embed_map(t)

    def _service(self, **cfg):
        cfg.setdefault("store_path", self.path)
        cfg.setdefault("topk", 2)
        cfg.setdefault("max_context_chars", 6000)
        variant_fn = cfg.pop("_variant_fn", None)
        svc = rag.RagService(embed_fn=self._embed, log=self.log,
                             variant_fn=variant_fn)
        svc.initialize(cfg)
        return svc

    def _docs(self, result):
        self.assertIsNotNone(result)
        return [s["doc_id"] for s in result[1]]

    # -- 默认关：零调用 ------------------------------------------------------
    def test_default_off_zero_extra_calls(self):
        calls = []

        def variant_fn(q):
            calls.append(q)
            return [V_EN]

        svc = self._service(_variant_fn=variant_fn)  # 不带 mq_* 键 → 默认关
        self.assertEqual(self._docs(svc.retrieve(Q0)), ["DOC-1", "DOC-2"])
        self.assertEqual(self.embeds, [Q0])          # 只 embed 原查询
        self.assertEqual(calls, [])                  # 变体生成零调用
        self.assertFalse(any("[rag-mq]" in ln for ln in self.log.lines))

    def test_default_config_mq_keys(self):
        self.assertFalse(rag.DEFAULT_RAG_CONFIG["mq_enabled"])
        self.assertEqual(rag.DEFAULT_RAG_CONFIG["mq_n_variants"],
                         multiquery.DEFAULT_MQ_N_VARIANTS)
        self.assertEqual(rag.DEFAULT_RAG_CONFIG["mq_model"],
                         multiquery.DEFAULT_MQ_MODEL)
        self.assertEqual(rag.DEFAULT_RAG_CONFIG["mq_timeout_seconds"],
                         multiquery.DEFAULT_MQ_TIMEOUT_SECONDS)
        self.assertFalse(rag.DEFAULT_RAG_CONFIG["mq_wall_clock"])  # 默认=旧行为

    def test_mq_wall_clock_plumbed_to_generate_variants(self):
        # rag 键 → generate_variants(wall_clock=) 接线：默认 False，显式 True 透传
        captured = {}

        def fake_gv(query, **kw):
            captured.update(kw)
            return [V_EN]

        svc = self._service(mq_enabled=True, mq_n_variants=1)
        with mock.patch.object(rag, "resolve_embed_endpoint", return_value=ENDPOINT), \
                mock.patch.object(multiquery, "generate_variants", fake_gv):
            svc.retrieve(Q0)
        self.assertFalse(captured.get("wall_clock"))      # 缺省键=旧行为
        captured.clear()
        svc2 = self._service(mq_enabled=True, mq_n_variants=1, mq_wall_clock=True)
        with mock.patch.object(rag, "resolve_embed_endpoint", return_value=ENDPOINT), \
                mock.patch.object(multiquery, "generate_variants", fake_gv):
            svc2.retrieve(Q0)
        self.assertTrue(captured.get("wall_clock"))       # 显式开=透传

    # -- mq 开：变体融合 -----------------------------------------------------
    def test_mq_on_english_variant_pulls_english_block(self):
        svc = self._service(mq_enabled=True, mq_n_variants=1,
                            _variant_fn=lambda q: [V_EN])
        # 英文变体把余弦圈外的英文块 DOC-3 拉进 top-2（单查询态是 DOC-1/DOC-2）
        self.assertEqual(self._docs(svc.retrieve(Q0)), ["DOC-1", "DOC-3"])
        self.assertEqual(self.embeds, [Q0, V_EN])    # 原查询+1 变体各 1 次 embed
        line = next(ln for ln in self.log.lines if ln.startswith("[rag-mq] queries"))
        self.assertIn("queries=2", line)
        self.assertIn("q=q0+q1", line)               # DOC-1 两路都中

    def test_mq_on_two_variants_three_way_fusion(self):
        svc = self._service(mq_enabled=True, mq_n_variants=2,
                            _variant_fn=lambda q: [V_EN, V_ZH])
        # 手算（k=60）：DOC-3=1/63+1/61+1/62 > DOC-2=2/62+1/63 > DOC-4 > DOC-1
        self.assertEqual(self._docs(svc.retrieve(Q0)), ["DOC-3", "DOC-2"])
        self.assertIn("[rag-mq] queries=3", " ".join(self.log.lines))

    def test_mq_n_variants_clamped_to_two(self):
        svc = self._service(mq_enabled=True, mq_n_variants=9,
                            _variant_fn=lambda q: [V_EN, V_ZH, "第三条变体"])
        self._docs(svc.retrieve(Q0))
        self.assertEqual(self.embeds, [Q0, V_EN, V_ZH])  # 上限 2 条变体
        self.assertEqual(len(self.embeds), 3)

    # -- 变体生成失败：优雅退单条原查询（零恶化） ------------------------------
    def test_mq_variant_fn_raises_falls_back_to_single(self):
        def boom(q):
            raise RuntimeError("生成侧炸了")

        svc = self._service(mq_enabled=True, _variant_fn=boom)
        self.assertEqual(self._docs(svc.retrieve(Q0)), ["DOC-1", "DOC-2"])
        self.assertEqual(self.embeds, [Q0])
        self.assertTrue(any("gen fail err=RuntimeError" in ln for ln in self.log.lines))

    def test_mq_variant_fn_bad_output_falls_back(self):
        for bad in ([], "不是列表", ["  ", "  " + Q0 + "  "]):  # 空/非列表/全与原查询重复
            with self.subTest(bad=bad):
                self.log.lines.clear()
                self.embeds.clear()
                svc = self._service(mq_enabled=True, _variant_fn=lambda q: bad)
                self.assertEqual(self._docs(svc.retrieve(Q0)), ["DOC-1", "DOC-2"])
                self.assertEqual(self.embeds, [Q0])

    def test_mq_endpoint_unresolved_falls_back(self):
        svc = self._service(mq_enabled=True, mq_n_variants=1)  # 无 variant_fn=真实路径
        with mock.patch.object(rag, "resolve_embed_endpoint",
                               side_effect=RuntimeError("key 缺失")):
            self.assertEqual(self._docs(svc.retrieve(Q0)), ["DOC-1", "DOC-2"])
        self.assertEqual(self.embeds, [Q0])
        self.assertTrue(any("gen fail" in ln for ln in self.log.lines))

    def test_mq_timeout_degrades_end_to_end(self):
        # 真实生成路径端到端超时：替身睡 0.2s 超预算 0.05s → 变体弃 → 单条原查询
        svc = self._service(mq_enabled=True, mq_n_variants=1, mq_timeout_seconds=0.05)
        cls, calls = _make_client_cls([httpx.TimeoutException("t")], sleep_s=0.2)
        with mock.patch.object(rag, "resolve_embed_endpoint", return_value=ENDPOINT), \
                mock.patch.object(multiquery.httpx, "Client", cls):
            self.assertEqual(self._docs(svc.retrieve(Q0)), ["DOC-1", "DOC-2"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.embeds, [Q0])          # 变体未向量化=未多花 embed
        self.assertTrue(any("err=TimeoutException" in ln for ln in self.log.lines))

    def test_mq_variant_embed_fail_skips_that_route_only(self):
        def embed_fail_en(t):
            self.embeds.append(t)
            if t == V_EN:
                raise RuntimeError("变体 embed 失败")
            return _embed_map(t)

        svc = rag.RagService(embed_fn=embed_fail_en, log=self.log,
                             variant_fn=lambda q: [V_EN])
        svc.initialize({"store_path": self.path, "topk": 2,
                        "max_context_chars": 6000, "mq_enabled": True})
        self.assertEqual(self._docs(svc.retrieve(Q0)), ["DOC-1", "DOC-2"])  # 退单条
        self.assertEqual(self.embeds, [Q0, V_EN])
        self.assertTrue(any("variant1" in ln and "跳过该变体" in ln
                            for ln in self.log.lines))

    # -- 三开关共存矩阵 ------------------------------------------------------
    def test_matrix_default_all_off_is_current_behavior(self):
        svc = self._service()
        self.assertEqual(self._docs(svc.retrieve(Q0)), ["DOC-1", "DOC-2"])
        self.assertEqual(self.embeds, [Q0])
        self.assertFalse(any("[rag-mq]" in ln or "[rag-hybrid]" in ln
                             for ln in self.log.lines))

    def test_matrix_mq_off_hybrid_on_unchanged(self):
        svc = self._service(hybrid_bm25_enabled=True, hybrid_candidates=20,
                            _variant_fn=lambda q: [V_EN])
        # 现行 hybrid 行为（test_bm25.py 同构路径）：DOC-1 双路 r1 居首
        self.assertEqual(self._docs(svc.retrieve(Q0)), ["DOC-1", "DOC-2"])
        self.assertEqual(self.embeds, [Q0])          # mq 关 → 不生成变体
        self.assertEqual(len([ln for ln in self.log.lines
                              if ln.startswith("[rag-hybrid]")]), 1)

    def test_matrix_mq_on_hybrid_on(self):
        svc = self._service(mq_enabled=True, mq_n_variants=1,
                            hybrid_bm25_enabled=True, hybrid_candidates=20,
                            _variant_fn=lambda q: [V_EN])
        # 每查询各自 cos+BM25 融合（topk=2 截）：q0 路=[DOC-1,DOC-2]，
        # 英文变体路=[DOC-3,DOC-2]（DOC-3 BM25 r1+cos r1）→ 多路 RRF：
        # DOC-2=2/62 居首，DOC-1/DOC-3 同 1/61，查询序 DOC-1 先 → [DOC-2, DOC-1]
        self.assertEqual(self._docs(svc.retrieve(Q0)), ["DOC-2", "DOC-1"])
        self.assertEqual(self.embeds, [Q0, V_EN])
        hybrid_lines = [ln for ln in self.log.lines if ln.startswith("[rag-hybrid]")]
        self.assertEqual(len(hybrid_lines), 2)       # 每查询一行（归因保留）
        self.assertTrue(any(ln.startswith("[rag-mq] queries=2")
                            for ln in self.log.lines))

    def test_matrix_mq_on_lexical_on(self):
        svc = self._service(mq_enabled=True, mq_n_variants=1,
                            lexical_boost=True, lexical_lambda=0.0,
                            _variant_fn=lambda q: [V_EN])
        # λ=0：重排退化余弦序 → 每查询路=余弦 top2 → 融合结果同 mq×hybrid 手算
        with mock.patch.object(rag, "rerank_hits", wraps=rag.rerank_hits) as sp:
            self.assertEqual(self._docs(svc.retrieve(Q0)), ["DOC-2", "DOC-1"])
            self.assertEqual(sp.call_count, 2)       # 每查询各走一次词法重排

    def test_matrix_all_three_on_hybrid_wins(self):
        svc = self._service(mq_enabled=True, mq_n_variants=1,
                            hybrid_bm25_enabled=True, lexical_boost=True,
                            hybrid_candidates=20, _variant_fn=lambda q: [V_EN])
        with mock.patch.object(rag, "rerank_hits", wraps=rag.rerank_hits) as sp:
            self.assertEqual(self._docs(svc.retrieve(Q0)), ["DOC-2", "DOC-1"])
            self.assertEqual(sp.call_count, 0)       # lexical 仍被 hybrid 短路
        self.assertTrue(any("warn" in ln and "hybrid_bm25" in ln
                            for ln in self.log.lines))

    def test_mq_enabled_but_multiquery_module_missing(self):
        # multiquery 模块缺席（部署漏带）：mq 退关，其余检索不受影响
        with mock.patch.object(rag, "multiquery", None):
            svc = self._service(mq_enabled=True, _variant_fn=lambda q: [V_EN])
            self.assertEqual(self._docs(svc.retrieve(Q0)), ["DOC-1", "DOC-2"])
            self.assertEqual(self.embeds, [Q0])
        self.assertTrue(any("mq_enabled 退关" in ln for ln in self.log.lines))


if __name__ == "__main__":
    unittest.main()
