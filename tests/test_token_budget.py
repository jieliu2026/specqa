# -*- coding: utf-8 -*-
"""token 月度上限 + tokenizer 真实化 离线单测（2026-09-28 施工，路线计划阶段三）。

命名口径：test_*.py discover 形态（test_rag_faiss.py 先例）。错峰纪律：本件
只单跑（python -m unittest tests.test_token_budget 或根级 discover -p
"test_token*"）；全套根级 discover 由主会话在 S1-A 收口后统一复验。

覆盖（全离线零 API，embed 全 stub，合成向量 dim=8 复用 tests.test_rag 夹具）：
- 默认关逐字节等价：rag 段缺键/显式 false 两态 retrieve 输出与金路径（模块级
  rag.search+build_evidence 原函数）全等、零 [rag-budget] 日志、台账零读；
  server input_limit_unit 缺省=chars 截断与现行字符口径逐字节一致。
- 预算闸三态：正常（<预警静默）/预警（[rag-budget] warn 照常嵌入）/硬顶
  （[rag-budget] block + retrieve None=退裸答 + embed 零调用）；边界值
  （=预警/=硬顶）；台账续写缓存失效；缺台账计 0 闸开（warn 一次不刷屏）。
- 台账月度切片：带日期锚+时间回跳>2h 步进日重建（跨月归属翻月）、无锚保守
  全归当月、坏行/缺文件/坏 ts 计 0；真实台账 2026-09 切片=全文件 prompt_tokens
  求和（口径收口档在档数字）、2026-08=0。
- token 计数器三档：①真 tokenizer 档（QABOT_TOKENIZER_JSON 指定件→tokenizers
  加载 tier=qwen，mock 注入档探测一次即缓存；tiktoken 档同机制）②校准近似档
  （CJK×0.79+其余×0.42 精确值+ceil）③口径登记（[tokenizer] tier= 日志一行，
  档位可观测）；truncate_to_tokens 保前缀二分；_input_unit 容错回 chars。
- /api/chat 端到端（伪上游零网络）：chars 口径截断=content[:N] 现行语义；
  tokens 口径按计数器截断/413 计量；坏值回 chars。
- 校准回归（skipUnless 锚件在位）：查询面 38 题/985 tok 锚——校准系数误差
  −0.4% 级、默认粗档 +15.4%（带内断言，系数与施工报告一致）。
- 容缺键：rag 段非 dict/空段/坏值 → 默认 off/40/50（模块常量口径；2026-10-05
  调线，拨键批=2026-10-14 断言三件套）；预警>硬顶钳到硬顶（=不钳）。
- 2026-10-14 拨键批改造：去 20/25 钉死——预算闸三态/容缺键一律**注入值测机制**
  （阈值显式注入 config，与模块默认解耦）；模块默认只测接线（DEFAULT_RAG_CONFIG
  ↔ 常量）+调线锚（40/50 一处钉死，部署红线"拨键 assert"的测试面）；
  新增 budget==cap 不钳、config 覆盖优先级（注入值胜默认且不反污模块默认）、
  坏值族扩充（空串/0/负数/字符串/NaN）。
"""
import contextlib
import datetime
import io
import json
import math
import os
import tempfile
import unittest
from unittest import mock

import httpx
from fastapi.testclient import TestClient

import rag
import server  # tests/__init__.py 已做 sys.path 引导
from tests import clean_store_tests  # chat 型限流免疫（2026-10-02 迭代轮泛化）
from tests.test_rag import QUERY, write_fixture

try:
    import tokenizers  # noqa: F401 —— 真 tokenizer 档测试用（venv 已装）
    _HAS_TOKENIZERS = True
except Exception:
    _HAS_TOKENIZERS = False

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL_LEDGER = os.path.join(REPO, "建库", "logs", "embed用量.jsonl")
VEC_CACHE = os.path.join(REPO, "建库", "logs", "hybrid-mq评测-vec缓存.json")


def _month_ts(day):
    """当月台账行时间戳（2026-10-01 换月打穿教训：夹具日期改动态当月，
    与 _budget_month_cny 的当月切片恒同月——写死历史月份会在每月首日全红）。"""
    return "%s-%02d 10:00:00" % (datetime.date.today().strftime("%Y-%m"), day)


def _reset_tokenizer():
    """两用例间复位计数器缓存（tier 惰性探测是模块级单例态）。"""
    server._tokenizer_state["tier"] = None
    server._tokenizer_state["counter"] = None


class RagFixture:
    """共用夹具：test_rag 6 块合成库 + embed stub（记录调用）。"""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.store = os.path.join(self.tmp.name, "embeddings.jsonl")
        write_fixture(self.store)
        self.embed_calls = []

    def tearDown(self):
        self.tmp.cleanup()

    def _svc(self, extra=None, ledger=None):
        logs = []
        calls = self.embed_calls
        cfg = {"store_path": self.store, "score_threshold": 0}
        cfg.update(extra or {})
        if ledger is not None:
            cfg["embed_ledger_path"] = ledger
        svc = rag.RagService(embed_fn=lambda t: (calls.append(t) or list(QUERY)),
                             log=logs.append)
        svc.initialize(cfg)
        return svc, logs

    def _golden(self, text):
        """金路径：模块级原函数（未被本次施工改动）。"""
        recs, dim, _ = rag.load_store(self.store, use_sidecar=False)
        hits = rag.search(QUERY, recs, 5)
        return rag.build_evidence(hits, rag.DEFAULT_MAX_CONTEXT_CHARS)


def _write_ledger(path, rows):
    """rows: [(ts, prompt_tokens), ...] → jsonl 台账。"""
    with open(path, "w", encoding="utf-8") as f:
        for ts, tok in rows:
            f.write(json.dumps({"ts": ts, "batch": 0, "n": 10,
                                "prompt_tokens": tok, "retries": 0},
                               ensure_ascii=False) + "\n")


# -- 默认关：与改前逐字节等价 ------------------------------------------------
class BudgetDefaultOffTest(RagFixture, unittest.TestCase):

    def test_missing_keys_equals_golden(self):
        svc, logs = self._svc(ledger=os.path.join(self.tmp.name, "无此台账.jsonl"))
        self.assertIs(svc._cfg["embed_monthly_budget_enabled"], False)
        self.assertEqual(svc.retrieve("查询"), self._golden("查询"))  # 全等含 score
        self.assertTrue(self.embed_calls)                     # embed 照常调用
        self.assertFalse(any("[rag-budget]" in line for line in logs))  # 零新日志
        self.assertFalse(os.path.exists(svc._cfg["embed_ledger_path"]))  # 关=台账零读零建

    def test_explicit_false_equals_golden(self):
        svc, logs = self._svc({"embed_monthly_budget_enabled": False},
                              ledger=os.path.join(self.tmp.name, "无此.jsonl"))
        self.assertEqual(svc.retrieve("查询"), self._golden("查询"))
        self.assertFalse(any("[rag-budget]" in line for line in logs))

    def test_defaults_in_module_config(self):
        """接线测试（机制）：DEFAULT_RAG_CONFIG 三键挂模块常量，非复制字面量。"""
        self.assertIs(rag.DEFAULT_RAG_CONFIG["embed_monthly_budget_enabled"], False)
        self.assertIs(rag.DEFAULT_RAG_CONFIG["embed_monthly_budget_cny"],
                      rag.DEFAULT_EMBED_MONTHLY_BUDGET_CNY)
        self.assertIs(rag.DEFAULT_RAG_CONFIG["embed_monthly_cap_cny"],
                      rag.DEFAULT_EMBED_MONTHLY_CAP_CNY)

    def test_constants_match_2026_10_05_adjustment(self):
        """调线锚（钉死处）：40=预警线/50=熔断线（过程日志三节 36①，2026-10-05
        用户批"预算我可以上调到 50 元"；前口径 25/20 系 2026-09-26 调线）。
        部署红线"拨键 assert"的测试面——本断言红=常量回退，收口窗即知。"""
        self.assertEqual(rag.DEFAULT_EMBED_MONTHLY_BUDGET_CNY, 40.0)
        self.assertEqual(rag.DEFAULT_EMBED_MONTHLY_CAP_CNY, 50.0)


# -- 预算闸三态 --------------------------------------------------------------
class BudgetGateThreeStatesTest(RagFixture, unittest.TestCase):
    """台账 token → 元：cny = tok×0.5/1e6（注入阈值 20/25：4000 万 tok=20 元、
    5000 万 tok=25 元）。2026-10-14 拨键批改造：阈值**显式注入**（机制测试与
    模块默认解耦——默认 40/50 只在 BudgetDefaultOffTest 调线锚一处钉死）。"""

    BUDGET, CAP = 20, 25   # 注入阈值（任意合法值皆可；取旧默认沿用台账量设计）

    def _ledger(self, tok):
        p = os.path.join(self.tmp.name, "embed用量.jsonl")
        _write_ledger(p, [(_month_ts(1), tok)])
        return p

    def _gate(self, tok):
        return self._svc({"embed_monthly_budget_enabled": True,
                          "embed_monthly_budget_cny": self.BUDGET,
                          "embed_monthly_cap_cny": self.CAP},
                         ledger=self._ledger(tok))

    def test_normal_silent(self):
        svc, logs = self._gate(20_000_000)  # 10.0 元 < 20（注入预警线）
        self.assertEqual(svc.retrieve("查询"), self._golden("查询"))
        self.assertFalse(any("[rag-budget]" in line for line in logs))  # 正常态零日志

    def test_warn_marks_and_embeds(self):
        svc, logs = self._gate(44_000_000)  # 22 元 ∈ [20,25)
        self.assertEqual(svc.retrieve("查询"), self._golden("查询"))  # 照常嵌入
        self.assertEqual(len(self.embed_calls), 1)
        warns = [line for line in logs if line.startswith("[rag-budget] warn")]
        self.assertEqual(len(warns), 1)
        self.assertIn("monthly=22.00cny", warns[0])

    def test_block_refuses_embed_bare_answer(self):
        svc, logs = self._gate(60_000_000)  # 30 元 ≥ 25（注入硬顶）
        self.assertIsNone(svc.retrieve("查询"))            # 退纯裸答（rag=miss）
        self.assertEqual(self.embed_calls, [])              # 嵌入零调用
        blocks = [line for line in logs if line.startswith("[rag-budget] block")]
        self.assertEqual(len(blocks), 1)
        self.assertIn("monthly=30.00cny", blocks[0])
        self.assertTrue(any("err=EmbedBudgetExceeded" in line for line in logs))

    def test_boundaries(self):
        svc, logs = self._gate(40_000_000)  # =20 注入预警线
        self.assertIsNotNone(svc.retrieve("查询"))
        self.assertTrue(any(line.startswith("[rag-budget] warn") for line in logs))
        svc2, logs2 = self._gate(50_000_000)  # =25 注入硬顶
        self.assertIsNone(svc2.retrieve("查询"))
        self.assertTrue(any(line.startswith("[rag-budget] block") for line in logs2))

    def test_budget_gate_direct_raise_and_message(self):
        # 熔断行为路径直测：_budget_gate 在台账当月累计 ≥ cap 时抛
        # EmbedBudgetExceeded（retrieve 兜底路径已在 test_block_* 端到端覆盖）
        svc, _ = self._gate(60_000_000)
        with self.assertRaises(rag.EmbedBudgetExceeded) as cm:
            svc._budget_gate()
        self.assertIn("cap 25.00", str(cm.exception))

    def test_ledger_growth_invalidates_cache(self):
        p = self._ledger(20_000_000)
        svc, logs = self._svc({"embed_monthly_budget_enabled": True,
                               "embed_monthly_budget_cny": self.BUDGET,
                               "embed_monthly_cap_cny": self.CAP}, ledger=p)
        self.assertEqual(svc._budget_month_cny(), 10.0)
        # 续写（追加行=生产形态）：size 变化即时失效（tmpfs mtime 粒度 ~4ms，
        # 同刻重写靠 size 兜底——台账生产面只追加，登记见施工报告）
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": _month_ts(2), "batch": 0, "n": 10,
                                "prompt_tokens": 40_000_000, "retries": 0}) + "\n")
        self.assertEqual(svc._budget_month_cny(), 30.0)
        # 同尺寸改写：以显式 utime 推 mtime（模拟跨刻）→ mtime 维度失效
        _write_ledger(p, [(_month_ts(1), 60_000_000)])
        os.utime(p, ns=(0, os.stat(p).st_atime_ns + 10_000_000))
        self.assertEqual(svc._budget_month_cny(), 30.0)  # 60M tok=30 元（同值新读）

    def test_missing_ledger_counts_zero_and_warns_once(self):
        svc, logs = self._svc({"embed_monthly_budget_enabled": True,
                               "embed_monthly_budget_cny": self.BUDGET,
                               "embed_monthly_cap_cny": self.CAP},
                              ledger=os.path.join(self.tmp.name, "缺.jsonl"))
        self.assertEqual(svc._budget_month_cny(), 0.0)      # 计 0=闸开
        self.assertEqual(svc._budget_month_cny(), 0.0)
        warns = [line for line in logs if "ledger_missing" in line]
        self.assertEqual(len(warns), 1)                     # 只 warn 一次不刷屏
        self.assertIsNotNone(svc.retrieve("查询"))           # 检索照常


# -- 台账月度切片 ------------------------------------------------------------
class LedgerMonthSlicingTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def _p(self, name="embed用量.jsonl"):
        return os.path.join(self.tmp.name, name)

    def test_parse_ledger_ts_forms(self):
        self.assertEqual(rag.parse_ledger_ts("10:30:59"), (None, 10 * 3600 + 30 * 60 + 59))
        d, s = rag.parse_ledger_ts("2026-09-21 16:31:43")
        self.assertEqual((d.year, d.month, d.day), (2026, 9, 21))
        self.assertEqual(s, 16 * 3600 + 31 * 60 + 43)
        d2, s2 = rag.parse_ledger_ts("2026-09-21")
        self.assertEqual((d2.year, d2.month, d2.day), (2026, 9, 21))
        self.assertIsNone(s2)
        self.assertEqual(rag.parse_ledger_ts("garbage"), (None, None))
        self.assertEqual(rag.parse_ledger_ts(""), (None, None))
        self.assertEqual(rag.parse_ledger_ts(None), (None, None))
        self.assertEqual(rag.parse_ledger_ts("25:99:00"), (None, None))

    def test_dated_rows_split_by_month(self):
        p = self._p()
        _write_ledger(p, [("2026-08-31 23:00:00", 100),
                          ("2026-09-01 08:00:00", 200),
                          ("2026-09-30 23:59:59", 300)])
        self.assertEqual(rag.ledger_month_tokens(p, "2026-08"), 100)
        self.assertEqual(rag.ledger_month_tokens(p, "2026-09"), 500)

    def test_anchor_and_backward_jump_crosses_month(self):
        # 锚 09-30 23:00 → 无日期行 23:30（同日）；00:30 回跳 23h>2h → 翻 10-01
        p = self._p()
        _write_ledger(p, [("2026-09-30 23:00:00", 1000),
                          ("23:30:00", 100),
                          ("00:30:00", 200),
                          ("00:40:00", 400)])
        self.assertEqual(rag.ledger_month_tokens(p, "2026-09"), 1100)
        self.assertEqual(rag.ledger_month_tokens(p, "2026-10"), 600)

    def test_forward_gap_within_day_not_flipped(self):
        # 已知口径（在册）：前跳<24h-gap 的跨日续跑不翻日——正午锚后 23:50 仍记当月日
        p = self._p()
        _write_ledger(p, [("2026-09-30 12:00:00", 100),
                          ("23:50:00", 200)])
        self.assertEqual(rag.ledger_month_tokens(p, "2026-09"), 300)
        self.assertEqual(rag.ledger_month_tokens(p, "2026-10"), 0)

    def test_no_anchor_all_to_queried_month(self):
        p = self._p()
        _write_ledger(p, [("01:00:00", 100), ("02:00:00", 200)])
        # 无锚=保守全归所查当月（宁可多计：换月后旧台账随锚缺席会持续计入，
        # 现行台账有锚行、新行按回跳步进，见施工报告口径节）
        self.assertEqual(rag.ledger_month_tokens(p, "2026-09"), 300)

    def test_bad_rows_and_missing_file(self):
        p = self._p()
        with open(p, "w", encoding="utf-8") as f:
            f.write("{坏行\n\n" + json.dumps({"ts": "10:00:00", "prompt_tokens": 50}) + "\n"
                    + json.dumps({"ts": "10:01:00"}) + "\n")   # 缺 prompt_tokens 计 0
        self.assertEqual(rag.ledger_month_tokens(p, "2026-09"), 50)
        self.assertEqual(rag.ledger_month_tokens(os.path.join(self.tmp.name, "无.jsonl"),
                                                 "2026-09"), 0)

    @unittest.skipUnless(os.path.exists(REAL_LEDGER), "主台账不在位（非仓根环境）")
    def test_real_ledger_month_attribution_total(self):
        """真实台账月归属完备不变量（2026-10-02 迭代轮修）。

        原"09 月切片=全量和"系写作期事实（当时台账全行落 09 月）——10 月
        行入场（FK 重标定/EA-28 等）后失效。真不变量=锚步进归属无遗漏：
        候选月（锚月±边界月）切片之和==全文件 prompt_tokens 之和；
        无关月（如 2099-09）恒 0。台账逐月只增，本断言永随演化成立。"""
        full, anchor_months, n = 0, set(), 0
        with open(REAL_LEDGER, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except json.JSONDecodeError:
                    continue
                pt = o.get("prompt_tokens")
                if isinstance(pt, (int, float)) and not isinstance(pt, bool):
                    full += pt
                day, _ = rag.parse_ledger_ts(o.get("ts"))
                if day is not None:
                    anchor_months.add(datetime.date(day.year, day.month, 1))
                n += 1
        self.assertGreater(n, 5000)  # 防夹具误置（真实台账 6 千行级）
        self.assertTrue(anchor_months)
        cand = set(anchor_months)
        cand.add(min(anchor_months) - datetime.timedelta(days=1))   # 首锚回溯界
        cand.add(max(anchor_months) + datetime.timedelta(days=31))  # 末锚前进界
        slices = sum(rag.ledger_month_tokens(REAL_LEDGER, d.strftime("%Y-%m"))
                     for d in cand)
        self.assertEqual(slices, int(full),
                         msg="候选月 %s 切片和≠全量和（归属有漏）"
                             % sorted(d.strftime("%Y-%m") for d in cand))
        self.assertEqual(rag.ledger_month_tokens(REAL_LEDGER, "2099-09"), 0)


# -- token 计数器三档 --------------------------------------------------------
class TokenizerTiersTest(unittest.TestCase):

    def setUp(self):
        _reset_tokenizer()

    def tearDown(self):
        _reset_tokenizer()

    def test_approx_tier_values(self):
        with mock.patch.object(server, "_probe_real_tokenizer",
                               return_value=(None, None)):
            self.assertEqual(server.count_tokens("中" * 100), 79)   # ceil(100×0.79)
            self.assertEqual(server.count_tokens("a" * 100), 42)   # ceil(100×0.42)
            self.assertEqual(server.count_tokens(""), 0)
            # 混合：2 CJK×0.79 + 3 其他×0.42 = 2.84 → ceil 3
            self.assertEqual(server.count_tokens("中文abc"), 3)
            # 换行/标点计入"其他"口径（与回测锚同口径）
            self.assertEqual(server.count_tokens("中\na b"), 3)
        self.assertEqual(server._tokenizer_state["tier"], "approx")

    def test_approx_float_for_calibration(self):
        f = server._hybrid_token_count("中文abc")
        self.assertAlmostEqual(f, 2 * 0.79 + 3 * 0.42, places=12)

    def test_real_tier_mock_used_and_cached(self):
        probe = mock.Mock(return_value=("qwen", lambda t: max(1, len(t) // 2)))
        with mock.patch.object(server, "_probe_real_tokenizer", probe):
            self.assertEqual(server.count_tokens("abcdefgh"), 4)
            self.assertEqual(server.count_tokens("abc"), 1)
        self.assertEqual(probe.call_count, 1)   # 惰性探测一次即缓存
        self.assertEqual(server._tokenizer_state["tier"], "qwen")

    def test_tiktoken_tier_mock(self):
        with mock.patch.object(server, "_probe_real_tokenizer",
                               return_value=("tiktoken", lambda t: len(t))):
            self.assertEqual(server.count_tokens("abcd"), 4)
        self.assertEqual(server._tokenizer_state["tier"], "tiktoken")

    def test_tier_log_line_registered(self):
        out = io.StringIO()
        with mock.patch.object(server, "_probe_real_tokenizer",
                               return_value=(None, None)), \
                contextlib.redirect_stdout(out):
            server.count_tokens("x")
        self.assertIn("[tokenizer] tier=approx", out.getvalue())  # 档③口径登记可观测

    @unittest.skipUnless(_HAS_TOKENIZERS, "tokenizers 包不在位")
    def test_qwen_file_tier_end_to_end(self):
        # 最小 BPE tokenizer.json（词表 a/b/c）：真件加载全链路（探档→加载→计数），
        # 词表外字符（中文）按该 fixture 语义记 0——只验档位接线，不验词表覆盖
        from tokenizers import Tokenizer, models
        tok = Tokenizer(models.BPE(vocab={"a": 0, "b": 1, "c": 2}, merges=[]))
        tok_file = os.path.join(tempfile.mkdtemp(prefix="qabot-tok-"), "tokenizer.json")
        tok.save(tok_file)
        with mock.patch.dict(os.environ, {"QABOT_TOKENIZER_JSON": tok_file}):
            self.assertEqual(server.count_tokens("abcabc"), 6)
            self.assertEqual(server._tokenizer_state["tier"], "qwen")
            self.assertEqual(server.count_tokens("中文"), 0)  # 词表外不入 ids
        # 未指定 env 且 HF 缓存无 Qwen 实体件的本机态：探不到真件落 approx
        _reset_tokenizer()
        env = {k: v for k, v in os.environ.items() if k != "QABOT_TOKENIZER_JSON"}
        with mock.patch.dict(os.environ, env, clear=True):
            tier, counter = server._probe_real_tokenizer()
        self.assertIn(tier, (None, "qwen", "tiktoken"))  # 探测不抛错即合格
        if tier is None:
            server.count_tokens("abc")  # 落 approx 档可用
            self.assertEqual(server._tokenizer_state["tier"], "approx")

    def test_truncate_to_tokens(self):
        def cnt(t):
            return math.ceil(server._hybrid_token_count(t))
        self.assertEqual(server.truncate_to_tokens("中" * 100, 10, count=cnt), "中" * 12)
        self.assertEqual(server.truncate_to_tokens("a" * 100, 10, count=cnt), "a" * 23)
        self.assertEqual(server.truncate_to_tokens("abc", 10, count=cnt), "abc")  # 限内原样
        self.assertEqual(server.truncate_to_tokens("abc", 0, count=cnt), "")

    def test_input_unit_tolerance(self):
        self.assertEqual(server._input_unit({}), "chars")
        self.assertEqual(server._input_unit({"input_limit_unit": None}), "chars")
        self.assertEqual(server._input_unit({"input_limit_unit": "chars"}), "chars")
        self.assertEqual(server._input_unit({"input_limit_unit": "CHARS"}), "chars")
        self.assertEqual(server._input_unit({"input_limit_unit": "tokens"}), "tokens")
        self.assertEqual(server._input_unit({"input_limit_unit": "TOKENS"}), "tokens")
        self.assertEqual(server._input_unit({"input_limit_unit": "tok"}), "chars")   # 坏值回默认
        self.assertEqual(server._input_unit({"input_limit_unit": 1}), "chars")
        self.assertEqual(server._input_unit("not-a-dict"), "chars")


# -- /api/chat 端到端：chars 现行语义逐字节 + tokens 口径（伪上游零网络） -----
class _CaptureTimeoutStream:
    async def __aenter__(self):
        raise httpx.TimeoutException("stub 上游超时")

    async def __aexit__(self, *args):
        return False


class _CaptureAsyncClient:
    payloads = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def stream(self, method, url, json=None, headers=None, **kwargs):
        _CaptureAsyncClient.payloads.append(json)
        return _CaptureTimeoutStream()


def _chat_config(**extra):
    cfg = {"bot_name": "t", "model": "m", "port": 8000, "temperature": 0.7,
           "max_tokens": 128, "max_history_messages": 5, "max_input_chars": 50,
           "max_total_input_chars": 120, "rate_limit_requests": 99,
           "rate_limit_window_seconds": 60, "passcode": "", "passcode_hash": ""}
    cfg.update(extra)
    return cfg


@clean_store_tests
class ChatInputLimitTest(unittest.TestCase):

    def setUp(self):
        _reset_tokenizer()
        _CaptureAsyncClient.payloads = []
        self.cfg = _chat_config()

    def tearDown(self):
        _reset_tokenizer()

    def _post(self, cfg, messages):
        async def _ok(ip):
            return True
        body = {"messages": messages}
        with mock.patch.object(server, "CONFIG", cfg), \
                mock.patch.object(server, "API_KEY", "stub-key"), \
                mock.patch.object(server, "rag_service", None), \
                mock.patch.object(server, "_rate_ok", _ok), \
                mock.patch.object(server.httpx, "AsyncClient", _CaptureAsyncClient):
            with TestClient(server.app) as client:
                resp = client.post("/api/chat", json=body)
        return resp

    def test_chars_mode_byte_identical_clipping(self):
        # 缺省（无 input_limit_unit 键）=现行字符口径：content[:50]、total=len 计
        long = "甲" * 80
        resp = self._post(self.cfg, [{"role": "user", "content": long}])
        self.assertEqual(resp.status_code, 200)
        sent = _CaptureAsyncClient.payloads[-1]["messages"][-1]["content"]
        self.assertEqual(sent, long[: 50])               # 现行切片语义逐字节
        self.assertEqual(len(sent), 50)
        # 两条共 100 字 ≤120 放行（末条必须 user，现行校验语义）；三条 150>120 → 413
        ok_msgs = [{"role": "assistant", "content": "a" * 50},
                   {"role": "user", "content": "q" * 50}]
        over_msgs = [{"role": "user", "content": "u" * 50},
                     {"role": "assistant", "content": "a" * 50},
                     {"role": "user", "content": "q" * 50}]
        self.assertEqual(self._post(self.cfg, ok_msgs).status_code, 200)
        self.assertEqual(self._post(self.cfg, over_msgs).status_code, 413)

    def test_chars_mode_explicit_and_bad_value(self):
        for unit in ("chars", "bogus"):
            cfg = _chat_config(input_limit_unit=unit)
            resp = self._post(cfg, [{"role": "user", "content": "乙" * 80}])
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(len(_CaptureAsyncClient.payloads[-1]["messages"][-1]
                                 ["content"]), 50)

    def test_tokens_mode_clipping_and_413(self):
        cfg = _chat_config(input_limit_unit="tokens", max_input_chars=10,
                           max_total_input_chars=25)
        with mock.patch.object(server, "_probe_real_tokenizer",
                               return_value=(None, None)):
            # 纯中文 100 字 → 79 tok >10 → 截到 12 字（ceil(0.79×12)=10）
            resp = self._post(cfg, [{"role": "user", "content": "中" * 100}])
            self.assertEqual(resp.status_code, 200)
            sent = _CaptureAsyncClient.payloads[-1]["messages"][-1]["content"]
            self.assertEqual(len(sent), 12)
            self.assertLessEqual(server.count_tokens(sent), 10)
            # 纯 ASCII 100 字 → 42 tok >10 → 截到 23 字（ceil(0.42×23)=10）
            resp = self._post(cfg, [{"role": "user", "content": "a" * 100}])
            sent = _CaptureAsyncClient.payloads[-1]["messages"][-1]["content"]
            self.assertEqual(len(sent), 23)
            # 总量口径：3 条各 10 tok=30 >25 → 413
            msgs = [{"role": "user", "content": "中" * 12},
                    {"role": "assistant", "content": "中" * 12},
                    {"role": "user", "content": "中" * 12}]
            self.assertEqual(self._post(cfg, msgs).status_code, 413)


# -- 校准回归：查询面锚（38 题/985 tok，语料面 730MB 大档只入施工报告） --------
@unittest.skipUnless(os.path.exists(VEC_CACHE), "vec 缓存锚件不在位")
class CalibrationAnchorTest(unittest.TestCase):

    def test_query_face_calibration_error(self):
        d = json.load(open(VEC_CACHE, encoding="utf-8"))
        queries, true_tok = d["queries"], d["total_tokens"]
        self.assertEqual(len(queries), 38)
        cjk = sum(1 for q in queries for ch in q if "\u4e00" <= ch <= "\u9fff")
        other = sum(len(q) for q in queries) - cjk
        calibrated = cjk * server.TOKENIZER_CJK_COEF + other * server.TOKENIZER_OTHER_COEF
        default = cjk * 1.0 + other * 0.25
        err_c = (calibrated - true_tok) / true_tok
        err_d = (default - true_tok) / true_tok
        self.assertLess(abs(err_c), 0.02)   # 校准系数：−0.4% 级（带内）
        self.assertLess(err_d, 0.20)        # 默认粗档：+15.4%（带内）
        self.assertGreater(err_d, 0.10)
        # 系数常量与施工报告登记一致（防漂移）
        self.assertEqual((server.TOKENIZER_CJK_COEF, server.TOKENIZER_OTHER_COEF),
                         (0.79, 0.42))


# -- 容缺键与归一 ------------------------------------------------------------
class ConfigToleranceTest(unittest.TestCase):
    """store_path 一律指不存在件：本类只测配置归一，不触真实库装载（17s/次）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.no_store = os.path.join(self.tmp.name, "无此库.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def test_non_dict_and_empty_section(self):
        for cfg in (None, {}, "not-a-dict"):
            # base_dir 指临时目录：非 dict 段回默认 store_path 时不触真实库装载
            svc = rag.RagService(log=lambda s: None, base_dir=self.tmp.name)
            svc.initialize(cfg)
            self.assertIs(svc._cfg["embed_monthly_budget_enabled"], False)
            # 回退目标=模块常量（机制；字面值钉死归 BudgetDefaultOffTest 调线锚）
            self.assertIs(svc._cfg["embed_monthly_budget_cny"],
                          rag.DEFAULT_EMBED_MONTHLY_BUDGET_CNY)
            self.assertIs(svc._cfg["embed_monthly_cap_cny"],
                          rag.DEFAULT_EMBED_MONTHLY_CAP_CNY)

    def test_bad_values_fall_back_to_defaults(self):
        """坏值族（2026-10-14 扩充）：字符串/负数/0/空串/None/NaN 全回默认。
        （bool 不在坏值族：float(True)=1.0 系现行清洗器合法值口径。）"""
        for bad in ("abc", -5, 0, "", None, float("nan")):
            svc = rag.RagService(log=lambda s: None)
            svc.initialize({"store_path": self.no_store,
                            "embed_monthly_budget_enabled": True,
                            "embed_monthly_budget_cny": bad,
                            "embed_monthly_cap_cny": bad})
            self.assertIs(svc._cfg["embed_monthly_budget_cny"],
                          rag.DEFAULT_EMBED_MONTHLY_BUDGET_CNY, msg=repr(bad))
            self.assertIs(svc._cfg["embed_monthly_cap_cny"],
                          rag.DEFAULT_EMBED_MONTHLY_CAP_CNY, msg=repr(bad))

    def test_budget_above_cap_clamped(self):
        svc = rag.RagService(log=lambda s: None)
        svc.initialize({"store_path": self.no_store,
                        "embed_monthly_budget_enabled": True,
                        "embed_monthly_budget_cny": 30,
                        "embed_monthly_cap_cny": 25})
        self.assertEqual(svc._cfg["embed_monthly_budget_cny"], 25.0)  # 钳到硬顶
        self.assertEqual(svc._cfg["embed_monthly_cap_cny"], 25.0)     # 硬顶不动

    def test_budget_equal_cap_not_clamped(self):
        # 钳制语义=严格大于才钳（budget==cap 合法放行：warn 与 block 同线时
        # 先判 block——cny>=cap 拒绝、恒到不了 warn，语义保持"block 先于 warn"）
        svc = rag.RagService(log=lambda s: None)
        svc.initialize({"store_path": self.no_store,
                        "embed_monthly_budget_enabled": True,
                        "embed_monthly_budget_cny": 25,
                        "embed_monthly_cap_cny": 25})
        self.assertEqual(svc._cfg["embed_monthly_budget_cny"], 25.0)

    def test_config_override_takes_priority_over_defaults(self):
        """config 覆盖优先级：注入值胜默认；且不反污模块级 DEFAULT_RAG_CONFIG。"""
        svc = rag.RagService(log=lambda s: None)
        svc.initialize({"store_path": self.no_store,
                        "embed_monthly_budget_enabled": True,
                        "embed_monthly_budget_cny": 33,
                        "embed_monthly_cap_cny": 44})
        self.assertEqual(svc._cfg["embed_monthly_budget_cny"], 33.0)
        self.assertEqual(svc._cfg["embed_monthly_cap_cny"], 44.0)
        self.assertIs(svc._cfg["embed_monthly_budget_enabled"], True)
        # 模块默认零反污（initialize 用 dict 拷贝，不原地改）
        self.assertEqual(rag.DEFAULT_RAG_CONFIG["embed_monthly_budget_cny"],
                         rag.DEFAULT_EMBED_MONTHLY_BUDGET_CNY)
        self.assertEqual(rag.DEFAULT_RAG_CONFIG["embed_monthly_cap_cny"],
                         rag.DEFAULT_EMBED_MONTHLY_CAP_CNY)

    def test_ledger_path_resolution(self):
        svc = rag.RagService(log=lambda s: None)
        svc.initialize({"store_path": self.no_store,
                        "embed_ledger_path": os.path.join("建库", "logs", "x.jsonl")})
        self.assertEqual(svc._cfg["embed_ledger_path"],
                         os.path.join(rag.BASE_DIR, "建库", "logs", "x.jsonl"))
        abs_p = os.path.join(self.tmp.name, "ledger.jsonl")
        svc2 = rag.RagService(log=lambda s: None)
        svc2.initialize({"store_path": self.no_store, "embed_ledger_path": abs_p})
        self.assertEqual(svc2._cfg["embed_ledger_path"], abs_p)
        svc3 = rag.RagService(log=lambda s: None)
        svc3.initialize({"store_path": self.no_store})
        self.assertEqual(svc3._cfg["embed_ledger_path"],
                         os.path.join(rag.BASE_DIR, rag.DEFAULT_EMBED_LEDGER_PATH))


if __name__ == "__main__":
    unittest.main()
