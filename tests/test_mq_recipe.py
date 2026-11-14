# -*- coding: utf-8 -*-
"""深度提升批B4 mq 配方键离线单测（2026-09-22，运营/深度提升批B4-mq施工-20260922.md）。

覆盖三新键（mq_single_variant / mq_variant_timeout / mq_wall_timeout）：
坏值钳制（口径贴批A server._depth_config 先例）、单变体模式（配方=1 变体 en
与原查询合并、去重）、预算分键（生成预算=min(mq_variant_timeout, wall 剩余)）、
整体墙钟耗尽降级（生成阶段/变体路阶段两处 cut，弃变体走原查询不拖检索）、
[rag-mq] 降级打点字段、以及**三键缺省=零行为变化回归**（默认关逐字节一致；
mq 开旧键态与既往行为一致）。

零网络零 API：embed_fn/variant_fn 注入 + mock multiquery.httpx（形态贴根
test_multiquery.py）。夹具向量语义同该件：q0=V0 → c1>c2>c3>c4；英文变体
V_EN=V1 → c3>c2>c1>c4（单变体融合 top2 = DOC-1, DOC-3）。
"""
import json
import math
import os
import re
import tempfile
import time
import unittest
from unittest import mock

import httpx

import multiquery
import rag


# ---------------------------------------------------------------------------
# 夹具（同根 test_multiquery.py 语义，独立内联避免跨件依赖）
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

ENDPOINT = ("http://bailian.example", "sk-test-key")


def _embed_map(t):
    return {Q0: list(V0), V_EN: list(V1), V_ZH: list(V2)}.get(t, list(V0))


class _Silent:
    def __init__(self):
        self.lines = []

    def __call__(self, line):
        self.lines.append(line)


def _ok_payload(content):
    return {"choices": [{"message": {"content": content}}]}


def _make_client_cls(responses, sleep_s=0.0):
    """multiquery.httpx.Client 替身：按序回放（payload 或异常），记录请求。"""
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


# ---------------------------------------------------------------------------
# 纯函数：_norm_mq_budget 坏值钳制（口径贴批A server._depth_config 先例）
# ---------------------------------------------------------------------------
class NormMQBudgetTest(unittest.TestCase):
    def test_none_falls_back(self):
        self.assertEqual(rag._norm_mq_budget(None, 3.0), 3.0)
        self.assertIsNone(rag._norm_mq_budget(None, None))

    def test_valid_values_pass(self):
        self.assertEqual(rag._norm_mq_budget(2.5, None), 2.5)
        self.assertEqual(rag._norm_mq_budget("1.5", None), 1.5)   # 数字串容忍
        self.assertEqual(rag._norm_mq_budget(30, None), 30.0)     # 上界含 30
        self.assertEqual(rag._norm_mq_budget(0.05, None), 0.05)

    def test_bad_values_fall_back(self):
        for bad in ("abc", "", float("nan"), float("inf"), 0, -1, 31, [], {}):
            with self.subTest(bad=bad):
                self.assertEqual(rag._norm_mq_budget(bad, 3.0), 3.0)
                self.assertIsNone(rag._norm_mq_budget(bad, None))
        self.assertTrue(math.isnan(float("nan")))  # NaN 走 f != f 分支 sanity


# ---------------------------------------------------------------------------
# initialize 归一：三新键生效值（含旧键回退链）
# ---------------------------------------------------------------------------
class InitializeNormalizationTest(unittest.TestCase):
    def setUp(self):
        self.log = _Silent()

    def _cfg_after_init(self, **extra):
        cfg = {"store_path": os.path.join(tempfile.gettempdir(),
                                          "b4-不存在的库.jsonl")}
        cfg.update(extra)
        svc = rag.RagService(log=self.log)
        svc.initialize(cfg)
        return svc._cfg

    def test_default_rag_config_new_keys(self):
        self.assertFalse(rag.DEFAULT_RAG_CONFIG["mq_single_variant"])
        self.assertIsNone(rag.DEFAULT_RAG_CONFIG["mq_variant_timeout"])
        self.assertIsNone(rag.DEFAULT_RAG_CONFIG["mq_wall_timeout"])
        # 既有键不动（回归锚点）
        self.assertFalse(rag.DEFAULT_RAG_CONFIG["mq_enabled"])
        self.assertFalse(rag.DEFAULT_RAG_CONFIG["mq_wall_clock"])

    def test_no_new_keys_falls_back_to_legacy(self):
        cfg = self._cfg_after_init(mq_enabled=True)
        self.assertEqual(cfg["mq_variant_timeout"], 3.0)   # 回退 mq_timeout_seconds 默认
        self.assertIsNone(cfg["mq_wall_timeout"])          # 无整体预算=旧行为
        self.assertFalse(cfg["mq_single_variant"])

    def test_legacy_timeout_key_still_honored(self):
        cfg = self._cfg_after_init(mq_enabled=True, mq_timeout_seconds=0.05)
        self.assertEqual(cfg["mq_variant_timeout"], 0.05)

    def test_variant_timeout_overrides_legacy(self):
        cfg = self._cfg_after_init(mq_enabled=True, mq_timeout_seconds=3,
                                   mq_variant_timeout=2.5)
        self.assertEqual(cfg["mq_variant_timeout"], 2.5)

    def test_bad_variant_timeout_falls_back_chain(self):
        cfg = self._cfg_after_init(mq_enabled=True, mq_variant_timeout="abc")
        self.assertEqual(cfg["mq_variant_timeout"], 3.0)   # 回退旧键默认
        cfg2 = self._cfg_after_init(mq_enabled=True, mq_variant_timeout=99,
                                    mq_timeout_seconds=1.5)
        self.assertEqual(cfg2["mq_variant_timeout"], 1.5)  # 越界回退旧键生效值
        cfg3 = self._cfg_after_init(mq_enabled=True, mq_variant_timeout="x",
                                    mq_timeout_seconds="y")
        self.assertEqual(cfg3["mq_variant_timeout"], 3.0)  # 双坏回 multiquery 默认

    def test_wall_timeout_norm(self):
        self.assertEqual(self._cfg_after_init(mq_wall_timeout=2.5)["mq_wall_timeout"], 2.5)
        for bad in (0, -1, 31, "x", float("nan")):
            with self.subTest(bad=bad):
                self.assertIsNone(self._cfg_after_init(mq_wall_timeout=bad)
                                  ["mq_wall_timeout"])

    def test_single_variant_bool_coerced(self):
        self.assertTrue(self._cfg_after_init(mq_single_variant="yes")
                        ["mq_single_variant"])
        self.assertFalse(self._cfg_after_init(mq_single_variant=0)
                         ["mq_single_variant"])


# ---------------------------------------------------------------------------
# RagService 端到端夹具基类
# ---------------------------------------------------------------------------
class _MQServiceBase(unittest.TestCase):
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

    def _lines_with(self, *needles):
        return [ln for ln in self.log.lines
                if all(n in ln for n in needles)]


# ---------------------------------------------------------------------------
# 单变体模式（mq_single_variant，配方=1 变体 en 与原查询合并）
# ---------------------------------------------------------------------------
class SingleVariantModeTest(_MQServiceBase):
    def test_single_overrides_n_variants_two(self):
        svc = self._service(mq_enabled=True, mq_n_variants=2,
                            mq_single_variant=True,
                            _variant_fn=lambda q: [V_EN, V_ZH])
        # 配方形态：只留第 0 条（en）与原查询两路融合（手算同根件 mq×1 变体例）
        self.assertEqual(self._docs(svc.retrieve(Q0)), ["DOC-1", "DOC-3"])
        self.assertEqual(self.embeds, [Q0, V_EN])          # 变体只 embed 一条
        line = self._lines_with("[rag-mq] variants", "asked=1", "got=1", "single=1")
        self.assertEqual(len(line), 1)

    def test_single_overrides_n_variants_zero(self):
        svc = self._service(mq_enabled=True, mq_n_variants=0,
                            mq_single_variant=True,
                            _variant_fn=lambda q: [V_EN])
        self.assertEqual(self._docs(svc.retrieve(Q0)), ["DOC-1", "DOC-3"])
        self.assertEqual(self.embeds, [Q0, V_EN])          # single 覆盖 0 → 1 条

    def test_single_off_default_keeps_two_variants(self):
        svc = self._service(mq_enabled=True, mq_n_variants=2,
                            _variant_fn=lambda q: [V_EN, V_ZH])
        self._docs(svc.retrieve(Q0))
        self.assertEqual(self.embeds, [Q0, V_EN, V_ZH])
        self.assertEqual(len(self._lines_with("[rag-mq] variants",
                                              "asked=2", "single=0")), 1)

    def test_single_real_path_only_one_flash_call_en_spec(self):
        # 真实生成路径（mock httpx）：single 开 → 只发 1 次 flash，用英文规格
        cls, calls = _make_client_cls([_ok_payload(V_EN), _ok_payload(V_ZH)])
        svc = self._service(mq_enabled=True, mq_n_variants=2,
                            mq_single_variant=True)
        with mock.patch.object(rag, "resolve_embed_endpoint", return_value=ENDPOINT), \
                mock.patch.object(multiquery.httpx, "Client", cls):
            self.assertEqual(self._docs(svc.retrieve(Q0)), ["DOC-1", "DOC-3"])
        self.assertEqual(len(calls), 1)                    # zh 变体未发=省一次调用
        self.assertIn("英文", calls[0]["json"]["messages"][0]["content"])

    def test_single_dedupe_against_original_query(self):
        # 与原查询合并去重：变体清洗后与原查询同（空白不敏感）→ 零变体降级
        svc = self._service(mq_enabled=True, mq_single_variant=True,
                            _variant_fn=lambda q: ["  " + Q0 + "  "])
        self.assertEqual(self._docs(svc.retrieve(Q0)), ["DOC-1", "DOC-2"])
        self.assertEqual(self.embeds, [Q0])
        self.assertEqual(len(self._lines_with("[rag-mq] variants",
                                              "got=0", "single=1")), 1)
        self.assertEqual(len(self._lines_with("degrade reason=no_variants")), 1)

    def test_single_gen_failure_silent_degrade(self):
        def boom(q):
            raise RuntimeError("生成侧炸了")

        svc = self._service(mq_enabled=True, mq_single_variant=True,
                            _variant_fn=boom)
        self.assertEqual(self._docs(svc.retrieve(Q0)), ["DOC-1", "DOC-2"])
        self.assertEqual(self.embeds, [Q0])
        self.assertEqual(len(self._lines_with("gen fail err=RuntimeError")), 1)
        self.assertEqual(len(self._lines_with("degrade reason=no_variants")), 1)


# ---------------------------------------------------------------------------
# 预算分键：生成预算=min(mq_variant_timeout, mq_wall_timeout 剩余)
# ---------------------------------------------------------------------------
class BudgetSplitTest(_MQServiceBase):
    def _captured_gen_budget(self, **cfg):
        """mock generate_variants 捕获 timeout 形参（=rag 侧算好的生成预算）。"""
        captured = {}

        def fake_gv(query, **kw):
            captured.update(kw)
            return [V_EN]

        cfg.setdefault("mq_enabled", True)
        cfg.setdefault("mq_n_variants", 1)
        svc = self._service(**cfg)
        with mock.patch.object(rag, "resolve_embed_endpoint", return_value=ENDPOINT), \
                mock.patch.object(multiquery, "generate_variants", fake_gv):
            svc.retrieve(Q0)
        return captured

    def test_no_new_keys_budget_is_legacy_timeout(self):
        cap = self._captured_gen_budget()
        self.assertAlmostEqual(cap["timeout"], 3.0)        # 旧键默认档

    def test_legacy_key_only_budget(self):
        cap = self._captured_gen_budget(mq_timeout_seconds=0.05)
        self.assertAlmostEqual(cap["timeout"], 0.05)       # 旧键继续生效（兼容）

    def test_variant_timeout_key_drives_budget(self):
        cap = self._captured_gen_budget(mq_variant_timeout=2.5,
                                        mq_timeout_seconds=3)
        self.assertAlmostEqual(cap["timeout"], 2.5)        # 新键优先于旧键

    def test_wall_caps_variant_budget(self):
        cap = self._captured_gen_budget(mq_wall_timeout=2.5)  # variant 默认 3.0
        self.assertAlmostEqual(cap["timeout"], 2.5)        # 整体墙钟压生成预算

    def test_variant_budget_smaller_than_wall_wins(self):
        cap = self._captured_gen_budget(mq_variant_timeout=1.0,
                                        mq_wall_timeout=2.5)
        self.assertAlmostEqual(cap["timeout"], 1.0)        # 取小

    def test_recipe_defaults_wall_clock_plumbed(self):
        # 采用配方建议档接线：wall_clock 透传 + 预算 2.5
        cap = self._captured_gen_budget(mq_single_variant=True,
                                        mq_wall_clock=True,
                                        mq_wall_timeout=2.5)
        self.assertTrue(cap["wall_clock"])
        self.assertAlmostEqual(cap["timeout"], 2.5)
        self.assertEqual(cap["n_variants"], 1)

    def test_variant_timeout_end_to_end_degrade(self):
        # 端到端：新键 0.05s 预算 + 替身睡 0.2s 超时 → 弃变体退单条原查询
        svc = self._service(mq_enabled=True, mq_n_variants=1,
                            mq_variant_timeout=0.05, mq_timeout_seconds=3)
        cls, calls = _make_client_cls([httpx.TimeoutException("t")], sleep_s=0.2)
        with mock.patch.object(rag, "resolve_embed_endpoint", return_value=ENDPOINT), \
                mock.patch.object(multiquery.httpx, "Client", cls):
            self.assertEqual(self._docs(svc.retrieve(Q0)), ["DOC-1", "DOC-2"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.embeds, [Q0])                # 未多花 embed
        self.assertEqual(len(self._lines_with("err=TimeoutException")), 1)
        self.assertEqual(len(self._lines_with("degrade reason=no_variants")), 1)


# ---------------------------------------------------------------------------
# mq_wall_timeout 整体墙钟：耗尽=弃变体走原查询，不拖不砍基础检索
# ---------------------------------------------------------------------------
class WallTimeoutTest(_MQServiceBase):
    def test_wall_exhausted_in_gen_phase_real_path(self):
        # 墙钟 0.15s + 慢端点 0.6s + wall_clock 看门狗 → 生成阶段被切，
        # 退单条原查询；总耗时贴预算而非端点延迟（硬墙钟口径）
        svc = self._service(mq_enabled=True, mq_n_variants=1,
                            mq_wall_clock=True, mq_wall_timeout=0.15)
        cls, calls = _make_client_cls([_ok_payload(V_EN)], sleep_s=0.6)
        t0 = time.time()
        with mock.patch.object(rag, "resolve_embed_endpoint", return_value=ENDPOINT), \
                mock.patch.object(multiquery.httpx, "Client", cls):
            self.assertEqual(self._docs(svc.retrieve(Q0)), ["DOC-1", "DOC-2"])
        self.assertLess(time.time() - t0, 0.5)             # 不等慢调用
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.embeds, [Q0])
        self.assertEqual(len(self._lines_with("watchdog", "cut wall_clock")), 1)
        self.assertEqual(len(self._lines_with("degrade reason=wall_budget",
                                              "phase=gen")), 1)

    def test_wall_exhausted_before_variant_routes(self):
        # 生成成功但耗光整体预算 → 变体路全弃（cut=2），原查询路照常检索
        def slow_variants(q):
            time.sleep(0.3)
            return [V_EN, V_ZH]

        svc = self._service(mq_enabled=True, mq_n_variants=2,
                            mq_wall_timeout=0.1, _variant_fn=slow_variants)
        t0 = time.time()
        self.assertEqual(self._docs(svc.retrieve(Q0)), ["DOC-1", "DOC-2"])
        self.assertLess(time.time() - t0, 2.0)             # 无挂起
        self.assertEqual(self.embeds, [Q0])                # 变体未向量化
        line = self._lines_with("degrade reason=wall_budget",
                                "phase=routes", "cut=2")
        self.assertEqual(len(line), 1)

    def test_wall_enough_normal_fusion_no_degrade(self):
        svc = self._service(mq_enabled=True, mq_n_variants=1,
                            mq_wall_timeout=5.0, _variant_fn=lambda q: [V_EN])
        self.assertEqual(self._docs(svc.retrieve(Q0)), ["DOC-1", "DOC-3"])
        self.assertEqual(self.embeds, [Q0, V_EN])
        self.assertEqual(self._lines_with("degrade"), [])  # 预算充足零降级打点

    def test_wall_none_default_slow_variants_not_cut(self):
        # 缺省（无整体预算=旧行为）：慢变体生成不切，照常融合
        def slow_variants(q):
            time.sleep(0.25)
            return [V_EN]

        svc = self._service(mq_enabled=True, mq_n_variants=1,
                            _variant_fn=slow_variants)
        self.assertEqual(self._docs(svc.retrieve(Q0)), ["DOC-1", "DOC-3"])
        self.assertEqual(self.embeds, [Q0, V_EN])
        self.assertEqual(self._lines_with("degrade"), [])

    def test_wall_does_not_cut_original_route(self):
        # 墙钟耗尽只弃变体路，原查询基础检索绝不截断（零恶化）：
        # 预算 0.1 已被生成耗光，原查询路仍完整走 _search_one 出结果
        def slow_variants(q):
            time.sleep(0.2)
            return [V_EN]

        svc = self._service(mq_enabled=True, mq_n_variants=1,
                            mq_wall_timeout=0.1, _variant_fn=slow_variants)
        result = svc.retrieve(Q0)
        self.assertEqual(self._docs(result), ["DOC-1", "DOC-2"])
        self.assertEqual(self.embeds, [Q0])
        self.assertTrue(result[0])                         # 证据文本照常产出


# ---------------------------------------------------------------------------
# 缺省=零行为变化回归（默认关逐字节一致；mq 开旧键态与既往一致）
# ---------------------------------------------------------------------------
class DefaultOffRegressionTest(_MQServiceBase):
    def test_default_off_zero_mq_lines_and_calls(self):
        calls = []

        def variant_fn(q):
            calls.append(q)
            return [V_EN]

        svc = self._service(_variant_fn=variant_fn)        # 不带任何 mq_* 键
        self.assertEqual(self._docs(svc.retrieve(Q0)), ["DOC-1", "DOC-2"])
        self.assertEqual(self.embeds, [Q0])
        self.assertEqual(calls, [])
        self.assertEqual(self._lines_with("[rag-mq]"), [])
        self.assertEqual(self._lines_with("degrade"), [])

    def test_explicit_defaults_byte_identical_to_absent_keys(self):
        # 新三键显式置缺省值 vs 完全不带键：证据文本/来源/日志逐字节一致
        # 2026-10-15 调线（细诊-20261015 档一 A 族，过程日志 83③）：两臂同用
        # 现产模块两跑，2026-10-14 E1 埋点（F线B 笔 822820c）起两跑各带一条
        # [rag-search] 计时行（epoch 毫秒必异）——start/end/dur 时标三元组
        # 归一为占位符后比对（归一非过滤：行存在性与 outcome 位仍受比对，
        # 任何其他行差照红）。
        svc_a = self._service()
        res_a = svc_a.retrieve(Q0)
        lines_a = list(self.log.lines)
        self.log.lines.clear()
        self.embeds.clear()
        svc_b = self._service(mq_single_variant=False, mq_variant_timeout=None,
                              mq_wall_timeout=None)
        res_b = svc_b.retrieve(Q0)
        self.assertEqual(res_a[0], res_b[0])               # 证据文本逐字节
        self.assertEqual([s["doc_id"] for s in res_a[1]],
                         [s["doc_id"] for s in res_b[1]])

        def _norm(lines):
            return [re.sub(r"start_ms=[0-9.]+ end_ms=[0-9.]+ dur_ms=[0-9.]+",
                           "start_ms=X end_ms=X dur_ms=X", ln)
                    for ln in lines]

        self.assertEqual(_norm(lines_a), _norm(self.log.lines))  # 日志逐行一致

    def test_mq_on_legacy_keys_behavior_unchanged(self):
        # mq 开+旧键态（无新键）：与批B4 前行为一致——2 变体三路融合、
        # 生成预算=旧键值、无墙钟降级打点
        svc = self._service(mq_enabled=True, mq_n_variants=2,
                            mq_timeout_seconds=3,
                            _variant_fn=lambda q: [V_EN, V_ZH])
        self.assertEqual(self._docs(svc.retrieve(Q0)), ["DOC-3", "DOC-2"])
        self.assertEqual(self.embeds, [Q0, V_EN, V_ZH])
        self.assertEqual(len(self._lines_with("[rag-mq] variants",
                                              "asked=2", "single=0")), 1)
        self.assertEqual(self._lines_with("degrade"), [])
        self.assertEqual(self._lines_with("watchdog"), [])

    def test_wall_clock_key_semantics_untouched(self):
        # mq_wall_clock 旧键语义不变：默认 False 不透传看门狗（快调用照常）
        captured = {}

        def fake_gv(query, **kw):
            captured.update(kw)
            return [V_EN]

        svc = self._service(mq_enabled=True, mq_n_variants=1,
                            mq_wall_timeout=2.5)
        with mock.patch.object(rag, "resolve_embed_endpoint", return_value=ENDPOINT), \
                mock.patch.object(multiquery, "generate_variants", fake_gv):
            svc.retrieve(Q0)
        self.assertFalse(captured["wall_clock"])           # 新键不隐式开看门狗


if __name__ == "__main__":
    unittest.main()
