# -*- coding: utf-8 -*-
"""P0 检索层去挤占（decrowd 四件套）离线单测（2026-09-29 施工）。

对象=rag.py：①doc_quota_select（同 doc 席位上限，改成员）②③decrowd_rescore
（38.133 表降权+制式信号压制，只乘排序分、余弦原始分恒存 cosine 键）
④retrieval_snapshot_dir 快照落盘 + clean_decrowd_params 坏值清洗 +
RagService._search_one 深候选池组装。结构断言：全部默认关=现状逐字节不变；
gate_cosine 读原始余弦（0.40 闸载体零侵蚀）；歧义保护（双侧制式信号→不压）。
零网络（stub embed_fn）、8 维夹具（真实库 1024 维，逻辑与维度无关）。
"""
import json
import os
import tempfile
import unittest

import rag


def _hit(rank, score, rid, doc_id, locator, content="内容", **extra):
    rec = {"id": rid, "doc_id": doc_id, "version": "Rel-18",
           "locator": locator, "content": content}
    h = {"rank": rank, "score": score, "rec": rec, "idx": rank - 1}
    h.update(extra)
    return h


# —— 服务级夹具库：9 块 8 维（query=[1,0,...] 余弦=1/sqrt(1+e²)，e 见注）——
# 基线 top5 = a1,a2,a3,l1,a4（TS 38.133 占 4 席——G04/G07 型表格洪流缩样）
FIXTURE = [
    # (id, doc_id, locator, e)      cos(q)
    ("a1", "TS 38.133", "Annex A.1", 0.00),    # 1.0000
    ("a2", "TS 38.133", "Annex A.2", 0.10),    # 0.9950
    ("a3", "TS 38.133", "Annex A.3", 0.15),    # 0.9889
    ("l1", "TS 36.331", "nr-RSRP-r15", 0.16),  # 0.9874（LTE 卡，G03 型撞名）
    ("a4", "TS 38.133", "9.2.7.3", 0.20),      # 0.9806（38.133 非 Annex 正文）
    ("n1", "TS 38.215", "5.1.1", 0.25),        # 0.9701（正主型）
    ("n2", "TS 38.213", "12 (p1)", 0.30),      # 0.9578
    ("n3", "TR 36.805", "6.1.1", 0.35),        # 0.9427（TR 案例卡）
    ("n4", "TS 38.331", "5.5.3.2", 0.40),      # 0.9285
]
QUERY = [1, 0, 0, 0, 0, 0, 0, 0]
NR_QUERY = "5G NR 中 SS-RSRP 的定义是什么"
LTE_QUERY = "LTE 的切换参数有哪些"
BASE_TOP5 = ["a1", "a2", "a3", "l1", "a4"]


def write_fixture(path):
    with open(path, "w", encoding="utf-8") as f:
        for rid, doc, loc, e in FIXTURE:
            vec = [1.0] + [0.0] * 7
            vec[1] = e
            f.write(json.dumps({"id": rid, "content": "%s 内容" % rid,
                                "doc_id": doc, "version": "Rel-18",
                                "locator": loc, "embedding": vec},
                               ensure_ascii=False) + "\n")


class _Silent:
    def __init__(self):
        self.lines = []

    def __call__(self, line):
        self.lines.append(line)


class CleanDecrowdParamsTest(unittest.TestCase):
    """配置清洗：默认全关；坏值回默认档（口径贴 _norm_budget_cny 先例）。"""

    def test_defaults_all_off(self):
        p = rag.clean_decrowd_params(rag.DEFAULT_RAG_CONFIG)
        self.assertFalse(p["quota_on"] or p["table_on"] or p["spec_on"])
        self.assertIsNone(p["snapshot_dir"])
        self.assertEqual(p["quota_max"], 2)
        self.assertEqual(p["candidates"], 20)
        self.assertEqual(p["table_docs"], ("38.133",))
        self.assertEqual(p["table_scope"], "annex")
        self.assertIs(p["spec_rules"], rag.SPEC_SUPPRESS_BUILTIN_RULES)

    def test_bad_values_fall_back(self):
        p = rag.clean_decrowd_params({
            "doc_quota_enabled": True, "doc_quota_max": "x",
            "table_downweight_enabled": True, "table_downweight_factor": 1.5,
            "spec_suppress_enabled": True, "spec_suppress_factor": -1,
            "table_downweight_scope": "bogus", "decrowd_candidates": 0,
        })
        self.assertEqual(p["quota_max"], rag.DEFAULT_DOC_QUOTA_MAX)
        self.assertEqual(p["table_factor"], rag.DEFAULT_TABLE_DOWNWEIGHT_FACTOR)
        self.assertEqual(p["spec_factor"], rag.DEFAULT_SPEC_SUPPRESS_FACTOR)
        self.assertEqual(p["table_scope"], "annex")
        self.assertEqual(p["candidates"], rag.DEFAULT_DECROWD_CANDIDATES)

    def test_factor_one_is_legal_noop(self):
        p = rag.clean_decrowd_params({"table_downweight_factor": 1.0})
        self.assertEqual(p["table_factor"], 1.0)

    def test_custom_rules_cleaned(self):
        rules = [
            {"name": "ok", "signal_patterns": ["nr"], "suppress_doc_contains": ["TS 36."],
             "factor": 0.7},
            {"name": "坏正则", "signal_patterns": ["("], "suppress_doc_contains": ["x"]},
            {"signal_patterns": [], "suppress_doc_contains": ["x"]},   # 空信号→丢
            "不是dict",
        ]
        p = rag.clean_decrowd_params({"spec_suppress_rules": rules})
        self.assertEqual(len(p["spec_rules"]), 1)
        self.assertEqual(p["spec_rules"][0]["name"], "ok")
        self.assertEqual(p["spec_rules"][0]["factor"], 0.7)

    def test_explicit_empty_rules_means_no_rules(self):
        p = rag.clean_decrowd_params({"spec_suppress_rules": []})
        self.assertEqual(p["spec_rules"], ())

    def test_exempt_and_docs_lists(self):
        p = rag.clean_decrowd_params({
            "doc_quota_exempt_docs": ["信息产业部令", " ", 36],
            "table_downweight_docs": ["38.133", "36.133"],
        })
        self.assertEqual(p["quota_exempt"], ("信息产业部令", "36"))
        self.assertEqual(p["table_docs"], ("38.133", "36.133"))


class SpecSuppressRulesTest(unittest.TestCase):
    """③ 制式信号识别：命中/歧义保护/边界防误报（3.5GHz、5GHz、版本号）。"""

    def setUp(self):
        self.rules = rag.SPEC_SUPPRESS_BUILTIN_RULES

    def _fired(self, q):
        return rag.spec_suppress_fired_rules(q, self.rules)

    def test_nr_signals(self):
        for q in ("5G NR 中 SS-RSRP 的定义", "NR 的 BWP 切换规则",
                  "TS 38.213 clause 12 说了什么", "请问5G的随机接入流程"):
            got = self._fired(q)
            self.assertEqual(len(got), 1, q)
            self.assertEqual(got[0]["name"], "nr_query_suppress_lte_docs", q)

    def test_lte_signals(self):
        for q in ("LTE 的切换参数有哪些", "E-UTRA 测量事件 A3",
                  "4G 网络重选优先级", "TS 36.331 的 t310 取值"):
            got = self._fired(q)
            self.assertEqual(len(got), 1, q)
            self.assertEqual(got[0]["name"], "lte_query_suppress_nr_docs", q)

    def test_ambiguity_guard_both_signals_no_suppress(self):
        for q in ("4G和5G互操作的重选优先级", "TS 36.331 与 TS 38.331 事件对比",
                  "LTE 与 NR 双模终端"):
            self.assertEqual(self._fired(q), [], q)

    def test_no_signal_queries(self):
        for q in ("掉话率监管红线是多少", "宽带装机时限", "V18.10.0 版本说明"):
            self.assertEqual(self._fired(q), [], q)

    def test_frequency_band_false_positive_guards(self):
        # "3.5GHz"/"5GHz" 频段词绝不触发 5G 制式信号（前置 [.0-9] 负断言+hz 负前瞻）
        for q in ("3.5GHz 频段的 SSB 个数", "5GHz 信道带宽", "n78 频段 3.5GHz"):
            names = [r["name"] for r in self._fired(q)]
            self.assertNotIn("nr_query_suppress_lte_docs", names, q)


class DecrowdRescoreTest(unittest.TestCase):
    """②③ 重打分：乘系数/cosine 原始分补挂/重排确定性/输入零改动/关=零拷贝。"""

    def setUp(self):
        self.hits = [
            _hit(1, 0.90, "t1", "TS 38.133", "Annex A.1"),
            _hit(2, 0.88, "t2", "TS 38.133", "Annex A.2"),
            _hit(3, 0.86, "c1", "TS 38.133", "9.2.7.3"),          # 非 Annex
            _hit(4, 0.80, "l1", "TS 36.331", "nr-RSRP-r15"),
            _hit(5, 0.70, "n1", "TS 38.215", "5.1.1"),
        ]

    def _params(self, **over):
        p = rag.clean_decrowd_params(rag.DEFAULT_RAG_CONFIG)
        p.update(over)
        return p

    def test_both_off_returns_same_object(self):
        out, info = rag.decrowd_rescore("q", self.hits, self._params())
        self.assertIs(out, self.hits)
        self.assertEqual(info, {"table_n": 0, "spec_rule": None, "spec_n": 0})

    def test_table_downweight_annex_scope(self):
        out, info = rag.decrowd_rescore(
            "q", self.hits, self._params(table_on=True, table_factor=0.85))
        self.assertEqual(info["table_n"], 2)
        by_id = {h["rec"]["id"]: h for h in out}
        self.assertAlmostEqual(by_id["t1"]["score"], 0.90 * 0.85)
        self.assertAlmostEqual(by_id["t2"]["score"], 0.88 * 0.85)
        self.assertEqual(by_id["c1"]["score"], 0.86)   # 非 Annex 不降
        # cosine 原始分补挂（纯余弦态无 cosine 键 → score 原值入 cosine）
        self.assertEqual(by_id["t1"]["cosine"], 0.90)
        self.assertEqual(by_id["c1"]["cosine"], 0.86)
        # 重排：0.86(c1) > 0.80(l1) > 0.765(t1) > 0.748(t2) > 0.70(n1)
        self.assertEqual([h["rec"]["id"] for h in out],
                         ["c1", "l1", "t1", "t2", "n1"])
        self.assertEqual([h["rank"] for h in out], [1, 2, 3, 4, 5])
        self.assertAlmostEqual(by_id["t1"]["decrowd_factor"], 0.85)

    def test_table_scope_all_includes_non_annex(self):
        out, info = rag.decrowd_rescore(
            "q", self.hits,
            self._params(table_on=True, table_scope="all"))
        self.assertEqual(info["table_n"], 3)

    def test_gate_cosine_reads_raw_unchanged(self):
        # 0.40 闸载体=余弦原始分：降权后 gate_cosine 零侵蚀（乙同款薄余量纪律）
        before = rag.gate_cosine(self.hits)
        out, _ = rag.decrowd_rescore(
            "q", self.hits, self._params(table_on=True, table_factor=0.5))
        self.assertAlmostEqual(rag.gate_cosine(out), before, places=12)

    def test_spec_suppress_nr_query(self):
        out, info = rag.decrowd_rescore(
            NR_QUERY, self.hits, self._params(spec_on=True, spec_factor=0.85))
        self.assertEqual(info["spec_rule"], "nr_query_suppress_lte_docs")
        self.assertEqual(info["spec_n"], 1)
        by_id = {h["rec"]["id"]: h for h in out}
        self.assertAlmostEqual(by_id["l1"]["score"], 0.80 * 0.85)
        self.assertEqual(by_id["t1"]["score"], 0.90)   # NR 侧块不压

    def test_spec_ambiguity_no_suppress(self):
        out, info = rag.decrowd_rescore(
            "4G和5G互操作", self.hits, self._params(spec_on=True))
        self.assertIsNone(info["spec_rule"])
        self.assertEqual(info["spec_n"], 0)

    def test_double_hit_multiplies(self):
        # LTE 题面 + TS 38.133 Annex 块 → 表降权×制式压制连乘
        out, info = rag.decrowd_rescore(
            LTE_QUERY, self.hits,
            self._params(table_on=True, table_factor=0.85,
                         spec_on=True, spec_factor=0.85))
        by_id = {h["rec"]["id"]: h for h in out}
        self.assertAlmostEqual(by_id["t1"]["score"], 0.90 * 0.85 * 0.85)
        self.assertAlmostEqual(by_id["t1"]["decrowd_factor"], 0.7225, places=5)
        self.assertAlmostEqual(by_id["c1"]["score"], 0.86 * 0.85)  # 仅压制非表降权
        self.assertAlmostEqual(by_id["n1"]["score"], 0.70 * 0.85)
        self.assertEqual(by_id["l1"]["score"], 0.80)   # LTE 块在 LTE 题面不压
        self.assertEqual(info["table_n"], 2)           # t1/t2（Annex）
        self.assertEqual(info["spec_n"], 4)            # t1/t2/c1/n1（TS 38. 系）

    def test_existing_cosine_key_preserved(self):
        # lexical/hybrid 态已附 cosine（原始余弦）与合成分 score：只乘 score
        hits = [_hit(1, 0.95, "t1", "TS 38.133", "Annex A.1", cosine=0.90),
                _hit(2, 0.60, "n1", "TS 38.215", "5.1.1", cosine=0.58)]
        out, _ = rag.decrowd_rescore(
            "q", hits, self._params(table_on=True, table_factor=0.85))
        by_id = {h["rec"]["id"]: h for h in out}
        self.assertEqual(by_id["t1"]["cosine"], 0.90)          # 原始分不被覆盖
        self.assertAlmostEqual(by_id["t1"]["score"], 0.95 * 0.85)

    def test_input_not_mutated(self):
        snap = [(h["rank"], h["score"], "cosine" in h) for h in self.hits]
        rag.decrowd_rescore("q", self.hits, self._params(table_on=True))
        self.assertEqual([(h["rank"], h["score"], "cosine" in h)
                          for h in self.hits], snap)

    def test_empty_hits(self):
        out, info = rag.decrowd_rescore("q", [], self._params(table_on=True))
        self.assertEqual(out, [])
        self.assertEqual(info["table_n"], 0)


class DocQuotaSelectTest(unittest.TestCase):
    """① doc 配额选席：超限让位+深处补位（改成员）/豁免/匿名块/短缺。"""

    def setUp(self):
        self.hits = [
            _hit(1, 0.99, "a1", "TS 38.133", "Annex A.1"),
            _hit(2, 0.98, "a2", "TS 38.133", "Annex A.2"),
            _hit(3, 0.97, "a3", "TS 38.133", "Annex A.3"),
            _hit(4, 0.96, "l1", "TS 36.331", "nr-RSRP-r15"),
            _hit(5, 0.95, "a4", "TS 38.133", "9.2.7.3"),
            _hit(6, 0.94, "n1", "TS 38.215", "5.1.1"),
            _hit(7, 0.93, "n2", "TS 38.213", "12 (p1)"),
        ]

    def test_quota_two_promotes_deep_blocks(self):
        out = rag.doc_quota_select(self.hits, topk=5, quota=2)
        self.assertEqual([h["rec"]["id"] for h in out],
                         ["a1", "a2", "l1", "n1", "n2"])   # a3/a4 让位、深处补位
        self.assertEqual([h["rank"] for h in out], [1, 2, 3, 4, 5])

    def test_quota_one_backfills_overflow(self):
        out = rag.doc_quota_select(self.hits, topk=5, quota=1)
        # 第一遍配额席=a1/l1/n1/n2（4 doc 各 1 席）；第二遍按原序回补让位块
        self.assertEqual([h["rec"]["id"] for h in out],
                         ["a1", "l1", "n1", "n2", "a2"])
        self.assertEqual([h["rank"] for h in out], [1, 2, 3, 4, 5])

    def test_single_doc_pool_backfill_keeps_prefix(self):
        # S1V-01 型：候选池单 doc 主导（监管域题面）——回补语义下证据面不
        # 缩水，最终 topk=基线前缀（配额零副作用的边界形态）
        hits = [_hit(i, 1.0 - i * 0.01, "r%d" % i, "信息产业部令第36号",
                     "附录1 1.2.%d" % i) for i in range(1, 8)]
        out = rag.doc_quota_select(hits, topk=5, quota=2)
        self.assertEqual([h["rec"]["id"] for h in out],
                         ["r1", "r2", "r3", "r4", "r5"])
        out2 = rag.doc_quota_select(hits, topk=5, quota=2,
                                    exempt_docs=("信息产业部令",))
        self.assertEqual([h["rec"]["id"] for h in out2],
                         ["r1", "r2", "r3", "r4", "r5"])   # 豁免=同形态

    def test_exempt_doc_unlimited(self):
        out = rag.doc_quota_select(self.hits, topk=5, quota=1,
                                   exempt_docs=("38.133",))
        self.assertEqual([h["rec"]["id"] for h in out],
                         ["a1", "a2", "a3", "l1", "a4"])

    def test_empty_doc_id_not_counted(self):
        hits = [_hit(1, 0.9, "x1", "", "L1"), _hit(2, 0.8, "x2", "", "L2"),
                _hit(3, 0.7, "y1", "DOC-Y", "L1")]
        out = rag.doc_quota_select(hits, topk=3, quota=1)
        self.assertEqual([h["rec"]["id"] for h in out], ["x1", "x2", "y1"])

    def test_input_not_mutated(self):
        snap = [(h["rank"], h["rec"]["id"]) for h in self.hits]
        rag.doc_quota_select(self.hits, topk=3, quota=1)
        self.assertEqual([(h["rank"], h["rec"]["id"]) for h in self.hits], snap)

    def test_empty_hits(self):
        self.assertEqual(rag.doc_quota_select([], 5, 2), [])


class RagServiceDecrowdTest(unittest.TestCase):
    """服务级：默认关=基线逐位不变；各开关经 _search_one 深候选池组装生效。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "embeddings.jsonl")
        write_fixture(self.path)
        self.log = _Silent()

    def tearDown(self):
        self.tmp.cleanup()

    def _service(self, **cfg):
        cfg.setdefault("store_path", self.path)
        cfg.setdefault("topk", 5)
        svc = rag.RagService(embed_fn=lambda q: list(QUERY), log=self.log)
        svc.initialize(cfg)
        return svc

    def _ids(self, svc, q="测试"):
        return [h["rec"]["id"] for h in svc._search_one(q, list(QUERY))]

    def test_default_off_baseline_unchanged(self):
        svc = self._service()
        self.assertEqual(self._ids(svc), BASE_TOP5)
        # 显式全关与新键缺省同构；且 _decrowd_on=False 走原路径
        svc2 = self._service(doc_quota_enabled=False,
                             table_downweight_enabled=False,
                             spec_suppress_enabled=False,
                             retrieval_snapshot_dir=None)
        self.assertEqual(self._ids(svc2), BASE_TOP5)
        self.assertFalse(svc2._decrowd_on())

    def test_baseline_scores_are_raw_cosine(self):
        svc = self._service()
        hits = svc._search_one("测试", list(QUERY))
        self.assertAlmostEqual(hits[0]["score"], 1.0, places=6)
        self.assertNotIn("cosine", hits[0])   # 默认关：hit 形态与旧版一致

    def test_doc_quota_promotes_from_deep_pool(self):
        svc = self._service(doc_quota_enabled=True, doc_quota_max=2)
        ids = self._ids(svc)
        # 基线 top5 里 TS 38.133 占 4 席（a1/a2/a3/a4）→ 配额后仅 2 席+补位
        self.assertEqual(ids, ["a1", "a2", "l1", "n1", "n2"])
        self.assertTrue(any("[rag-decrowd]" in ln for ln in self.log.lines))

    def test_table_downweight_keeps_non_annex(self):
        svc = self._service(table_downweight_enabled=True,
                            table_downweight_factor=0.85)
        ids = self._ids(svc)
        # Annex 三块 ×0.85 后跌出：l1(0.9874)>a4(0.9806 非Annex)>n1>n2>n3
        self.assertEqual(ids, ["l1", "a4", "n1", "n2", "n3"])
        self.assertNotIn("a1", ids)          # 降权块让位出证据面
        hits = svc._search_one("测试", list(QUERY))
        by_id = {h["rec"]["id"]: h for h in hits}
        self.assertAlmostEqual(by_id["l1"]["cosine"], by_id["l1"]["score"],
                               places=9)   # 未降权块 cosine=score（原始分补挂）

    def test_spec_suppress_on_nr_query(self):
        svc = self._service(spec_suppress_enabled=True, spec_suppress_factor=0.85)
        ids = [h["rec"]["id"] for h in svc._search_one(NR_QUERY, list(QUERY))]
        # l1（TS 36.331）0.9874→0.8393 让位 a4/n1；n3（TR 36.805）同压
        self.assertEqual(ids, ["a1", "a2", "a3", "a4", "n1"])

    def test_spec_suppress_lte_query_presses_nr_docs(self):
        svc = self._service(spec_suppress_enabled=True)
        ids = [h["rec"]["id"] for h in svc._search_one(LTE_QUERY, list(QUERY))]
        # 全部 TS 38.x 块 ×0.85：l1(0.9874) 独存 + n3(TR 36.805 0.9427)
        self.assertEqual(ids[0], "l1")
        self.assertEqual(ids[1], "n3")

    def test_combo_quota_table_spec(self):
        svc = self._service(doc_quota_enabled=True, doc_quota_max=2,
                            table_downweight_enabled=True,
                            spec_suppress_enabled=True)
        hits = svc._search_one(NR_QUERY, list(QUERY))
        ids = [h["rec"]["id"] for h in hits]
        self.assertEqual(len(ids), 5)
        docs = [h["rec"]["doc_id"] for h in hits]
        self.assertLessEqual(docs.count("TS 38.133"), 2)
        self.assertNotIn("TS 36.331", docs)     # NR 题面 LTE 卡被压出
        self.assertIn("n1", ids)                 # 正主型块补进

    def test_gate_cosine_untouched_by_downweight(self):
        import math
        base = self._service()
        dw = self._service(table_downweight_enabled=True,
                           table_downweight_factor=0.5)
        hb = base._search_one("测试", list(QUERY))
        hd = dw._search_one("测试", list(QUERY))
        # 闸=集内最大余弦原始分：降权臂 a1(cos=1.0) 让位后集内最大原始分=
        # l1 的 cosine 键（0.16 扰动 → 1/sqrt(1+0.16²)）——绝不读乘后分
        self.assertAlmostEqual(rag.gate_cosine(hd),
                               1.0 / math.sqrt(1 + 0.16 ** 2), places=6)
        self.assertAlmostEqual(rag.gate_cosine(hb), 1.0, places=6)

    def test_hybrid_branch_with_decrowd(self):
        svc = self._service(hybrid_bm25_enabled=True, doc_quota_enabled=True,
                            table_downweight_enabled=True)
        hits = svc._search_one("SS-RSRP 定义", list(QUERY))
        self.assertLessEqual(len(hits), 5)
        docs = [h["rec"]["doc_id"] for h in hits]
        self.assertLessEqual(docs.count("TS 38.133"), 2)
        self.assertTrue(any("[rag-hybrid]" in ln for ln in self.log.lines))

    def test_lexical_branch_with_decrowd(self):
        svc = self._service(lexical_boost=True, doc_quota_enabled=True)
        hits = svc._search_one("测试", list(QUERY))
        self.assertLessEqual(len(hits), 5)
        docs = [h["rec"]["doc_id"] for h in hits]
        self.assertLessEqual(docs.count("TS 38.133"), 2)

    def test_mq_depth_path_rescores_without_quota(self):
        # mq 深度路径（depth 给定）：只重打分、截回请求深度，不做配额选席
        svc = self._service(table_downweight_enabled=True,
                            doc_quota_enabled=True)
        hits = svc._search_one("测试", list(QUERY), depth=8)
        self.assertEqual(len(hits), 8)
        docs = [h["rec"]["doc_id"] for h in hits]
        # 降权重排后序=l1,a4,n1,n2,n3,n4,a1,a2（38.133 三席在列）——若配额
        # 生效应 ≤2 席：选席未发生（route 级纪律），仅重打分
        self.assertEqual(docs.count("TS 38.133"), 3)
        self.assertTrue(any(h.get("decrowd_factor") for h in hits))  # 重打分在


class SnapshotTest(unittest.TestCase):
    """④ 检索快照：默认关零写；开启逐态落行；写失败 warn 一次不拖垮检索。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "embeddings.jsonl")
        write_fixture(self.path)
        self.log = _Silent()
        self.snapdir = os.path.join(self.tmp.name, "snap")

    def tearDown(self):
        self.tmp.cleanup()

    def _service(self, **cfg):
        cfg.setdefault("store_path", self.path)
        cfg.setdefault("topk", 5)
        svc = rag.RagService(embed_fn=lambda q: list(QUERY), log=self.log)
        svc.initialize(cfg)
        return svc

    def _read_lines(self):
        p = os.path.join(self.snapdir, "retrieval-snapshot.jsonl")
        if not os.path.exists(p):
            return []
        with open(p, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def test_default_off_no_file(self):
        svc = self._service()
        svc.retrieve("测试问题")
        self.assertEqual(self._read_lines(), [])
        self.assertFalse(os.path.exists(self.snapdir))

    def test_hit_state_snapshot(self):
        svc = self._service(retrieval_snapshot_dir=self.snapdir)
        result = svc.retrieve("测试问题")
        self.assertIsNotNone(result)
        lines = self._read_lines()
        self.assertEqual(len(lines), 1)
        row = lines[0]
        self.assertEqual(row["query"], "测试问题")
        self.assertEqual(row["state"], "hit")
        self.assertEqual(len(row["vec"]), 8)          # 查询向量全量留档
        self.assertEqual(row["vec"][0], 1.0)
        self.assertEqual([h["id"] for h in row["hits"]], BASE_TOP5)
        self.assertEqual(row["hits"][0]["rank"], 1)
        self.assertAlmostEqual(row["hits"][0]["cosine"], 1.0, places=6)
        self.assertEqual(row["blocks"], 5)

    def test_low_score_state_snapshot(self):
        svc = self._service(retrieval_snapshot_dir=self.snapdir,
                            score_threshold=0.999999)
        # 全低分查询（与库内所有块近正交）→ low_score 态也落快照
        svc._embed_fn = lambda q: [0, 0, 0, 0, 0, 0, 0.2, 1]
        result = svc.retrieve("域外问题")
        self.assertIsInstance(result, rag.LowScoreResult)
        row = self._read_lines()[0]
        self.assertEqual(row["state"], "low_score")
        self.assertIn("gate_cosine", row)
        self.assertEqual(len(row["hits"]), 5)

    def test_coverage_miss_state_snapshot(self):
        svc = self._service(retrieval_snapshot_dir=self.snapdir)
        # 宽带装机型（2026-10-24 移词后现役词表词）：丙词表词+证据集全缺
        result = svc.retrieve("宽带装机的时限要求")
        self.assertIsInstance(result, rag.CoverageMissResult)
        row = self._read_lines()[0]
        self.assertEqual(row["state"], "coverage_miss")
        self.assertIn("宽带装机", row["words"])

    def test_miss_error_state_snapshot(self):
        svc = self._service(retrieval_snapshot_dir=self.snapdir)
        svc._embed_fn = lambda q: (_ for _ in ()).throw(RuntimeError("x"))
        self.assertIsNone(svc.retrieve("测试"))
        row = self._read_lines()[0]
        self.assertEqual(row["state"], "miss_error")
        self.assertEqual(row["err"], "RuntimeError")
        self.assertIsNone(row["vec"])

    def test_write_failure_warns_once_and_retrieve_survives(self):
        blocker = os.path.join(self.tmp.name, "占位文件")
        with open(blocker, "w") as f:
            f.write("x")
        svc = self._service(retrieval_snapshot_dir=blocker)  # 目录位被文件占住
        r1 = svc.retrieve("测试一")
        r2 = svc.retrieve("测试二")
        self.assertIsNotNone(r1)          # 快照写失败绝不拖垮检索
        self.assertIsNotNone(r2)
        warns = [ln for ln in self.log.lines if "[rag-snapshot]" in ln]
        self.assertEqual(len(warns), 1)   # 只 warn 一次防刷屏

    def test_snapshot_dir_relative_anchored_to_base_dir(self):
        svc = rag.RagService(embed_fn=lambda q: list(QUERY), log=self.log,
                             base_dir=self.tmp.name)
        svc.initialize({"store_path": self.path, "topk": 5,
                        "retrieval_snapshot_dir": "snap2"})
        svc.retrieve("测试")
        self.assertTrue(os.path.exists(
            os.path.join(self.tmp.name, "snap2", "retrieval-snapshot.jsonl")))

    def test_decrowd_factor_recorded_in_snapshot(self):
        # topk=9 收全库：降权块虽让位仍在快照证据面留 decrowd_factor 痕迹
        svc = self._service(retrieval_snapshot_dir=self.snapdir,
                            table_downweight_enabled=True, topk=9)
        svc.retrieve("测试问题")
        row = self._read_lines()[0]
        marked = [h for h in row["hits"] if h.get("decrowd_factor")]
        self.assertEqual(len(marked), 3)   # Annex 三块（归因直读）
        self.assertEqual({h["id"] for h in marked}, {"a1", "a2", "a3"})


if __name__ == "__main__":
    unittest.main(verbosity=2)


class ScopedTablesScopeTest(unittest.TestCase):
    """scope=tables（2026-10-02 scoped 变体）：仅表行组块降权，同 doc 条款/卡
    正主面不动；缺 chunk_type 的块保守不降（未知≠表格）。判效依据=
    建库/logs/检索排序治理-判效-20261002.md §四。"""

    @staticmethod
    def _h(rank, score, rid, doc, loc, chunk_type):
        return {"rank": rank, "score": score,
                "rec": {"id": rid, "doc_id": doc, "version": "Rel-18",
                        "locator": loc, "content": "内容",
                        "chunk_type": chunk_type}}

    def _params(self, **over):
        cfg = {"table_downweight_enabled": True,
               "table_downweight_docs": ["38.300"],
               "table_downweight_scope": "tables",
               "table_downweight_factor": 0.85}
        cfg.update(over)
        return rag.clean_decrowd_params(cfg)

    def test_clean_accepts_tables_scope(self):
        self.assertEqual(self._params()["table_scope"], "tables")

    def test_tables_only_table_row_group_demoted(self):
        hits = [
            self._h(1, 0.90, "t1", "TS 38.300", "9.2.2.4.1 表", "table_row_group"),
            self._h(2, 0.85, "c1", "TS 38.300", "9.2.6", "clause"),
            self._h(3, 0.80, "k1", "TS 38.300", "9.2.6", "case_card"),
        ]
        out, info = rag.decrowd_rescore("q", hits, self._params())
        self.assertEqual(info["table_n"], 1)          # 仅表行组块
        by_id = {h["rec"]["id"]: h for h in out}
        self.assertAlmostEqual(by_id["t1"]["score"], 0.90 * 0.85)
        self.assertAlmostEqual(by_id["c1"]["score"], 0.85)   # 条款不降
        self.assertAlmostEqual(by_id["k1"]["score"], 0.80)   # 卡面不降
        self.assertEqual([h["rec"]["id"] for h in out], ["c1", "k1", "t1"])

    def test_missing_chunk_type_conservative_no_demote(self):
        hits = [self._h(1, 0.90, "u1", "TS 38.300", "9.2.2.4.1 表", "")]
        out, info = rag.decrowd_rescore("q", hits, self._params())
        self.assertEqual(info["table_n"], 0)
        self.assertAlmostEqual(out[0]["score"], 0.90)

    def test_other_docs_untouched(self):
        hits = [self._h(1, 0.90, "x1", "TS 36.213", "7.2.1 表", "table_row_group")]
        out, info = rag.decrowd_rescore("q", hits, self._params())
        self.assertEqual(info["table_n"], 0)

    def test_annex_all_parity_unchanged(self):
        # 改造后 annex/all 两档行为与旧谓词逐位一致（防回归）
        hits = [
            self._h(1, 0.90, "t1", "TS 38.300", "Annex A.1 表", "table_row_group"),
            self._h(2, 0.85, "c1", "TS 38.300", "9.2.6", "clause"),
        ]
        out_a, info_a = rag.decrowd_rescore(
            "q", [dict(h) for h in hits], self._params(table_downweight_scope="annex"))
        self.assertEqual(info_a["table_n"], 1)
        out_all, info_all = rag.decrowd_rescore(
            "q", [dict(h) for h in hits], self._params(table_downweight_scope="all"))
        self.assertEqual(info_all["table_n"], 2)
