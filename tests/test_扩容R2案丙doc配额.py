# -*- coding: utf-8 -*-
"""语料扩容治理拨键批单测（2026-10-06 施工，扩容 R2 案丙）。

对象（用户 2026-10-06 批准案丙 doc≤2 席位配额键，治 V5 残余红灯=监管族内
挤占 C19/S1V-05；决策源=运营/扩容-R2-案丙doc配额实施-20261006.md；依据=
运营/扩容-V4-挤占治理仿真呈报-20261006.md 案丙〔doc≤2：零误伤+对抗卷 +4
确定+监管族内挤占唯一覆盖方向；fam 粒度已否决勿实施〕+建库/logs/扩容-V5-
终态复验-20261006.md〔C19=工信部令第35号 5 席压 36号令正主；S1V-05=36号令
附录8 族压附录6 正主〕）：
- rag.py domain_doc_quota 键（默认 {}=关）：clean_domain_doc_quota_params
  （坏条目单条丢弃/非 dict 整键回关/域名归一）+ doc_quota_select 域表
  参数化扩展（轻路径=现役 P0① doc 配额的 domain_quotas 参数，非新选席
  机制；①关时非域表域块不限额、域表值覆盖全局档、exempt 优先）+
  RagService 挂接（_decrowd_on 深候选池、默认关=与模块级 search 逐位一致、
  [rag-decrowd] 行 ddq= 读数）。
- 三方交互：famsel（overflow 并入配额回补池）/同源折叠（族键=(doc_id,
  locator 主干) 非 doc 级，不同粒度序贯组合）/案甲域降权（选席前乘子正交）。

零网络（stub embed_fn）、8 维夹具（真实库 1024 维，逻辑与维度无关）。
跑法：<repo>/venv/bin/python -m tests.test_扩容R2案丙doc配额
"""
import json
import math
import os
import tempfile
import unittest

import rag

DOC35 = "工信部令第35号"
DOC36 = "信息产业部令第36号"
DOC257 = "工信部联通信〔2023〕257号"


def _hit(rank, score, rec, idx=0):
    return {"rank": rank, "score": score, "rec": rec, "idx": idx}


def _rec(rid, doc_id, source_domain, locator, chunk_type="clause"):
    return {"id": rid, "doc_id": doc_id, "source_domain": source_domain,
            "locator": locator, "chunk_type": chunk_type,
            "corpus_type": "", "content": "内容 " + rid, "version": ""}


# ---------------------------------------------------------------------------
# 键清洗：clean_domain_doc_quota_params
# ---------------------------------------------------------------------------
class TestCleanDomainDocQuotaParams(unittest.TestCase):
    def test_default_off_on_missing_or_bad_container(self):
        for bad in (None, {}, [], "miit", 2, 0.5, {"domain_doc_quota": 1}):
            cfg = bad if isinstance(bad, dict) else {"domain_doc_quota": bad}
            p = rag.clean_domain_doc_quota_params(cfg)
            self.assertFalse(p["enabled"], bad)
            self.assertEqual(p["table"], {}, bad)

    def test_dial_form(self):
        # 拨板形态（部署窗 config）：{"miit": 2}
        p = rag.clean_domain_doc_quota_params({"domain_doc_quota": {"miit": 2}})
        self.assertTrue(p["enabled"])
        self.assertEqual(p["table"], {"miit": 2})

    def test_domain_key_normalized(self):
        p = rag.clean_domain_doc_quota_params(
            {"domain_doc_quota": {" MIIT ": 2}})
        self.assertEqual(p["table"], {"miit": 2})

    def test_bad_entries_dropped_not_whole_group(self):
        # 坏条目单条丢弃（席位 0/负数/非数值/空域名），好条目保留——口径贴
        # clean_domain_downweight_params：不整组回退
        p = rag.clean_domain_doc_quota_params(
            {"domain_doc_quota": {"miit": 2, "x": 0, "y": -1, "z": "abc",
                                  "w": None, "": 3, "v": [2]}})
        self.assertEqual(p["table"], {"miit": 2})

    def test_int_numeric_cast_precedent(self):
        # int 数值化沿 doc_quota_max 现役清洗口径（不单立尺）：bool→1、
        # 字符串整数→int、浮点截断
        p = rag.clean_domain_doc_quota_params(
            {"domain_doc_quota": {"a": True, "b": "2", "c": 2.0}})
        self.assertEqual(p["table"], {"a": 1, "b": 2, "c": 2})

    def test_duplicate_after_normalization_last_wins(self):
        # 归一后同名后者覆盖前者（dict 归一轮次序，确定性）
        p = rag.clean_domain_doc_quota_params(
            {"domain_doc_quota": {"MIIT": 3, "miit": 2}})
        self.assertEqual(p["table"], {"miit": 2})

    def test_default_rag_config_has_key_off(self):
        self.assertEqual(rag.DEFAULT_RAG_CONFIG.get("domain_doc_quota"), {})


# ---------------------------------------------------------------------------
# 纯函数：doc_quota_select 域表参数化扩展
# ---------------------------------------------------------------------------
def _c19_pool():
    """C19 实证形夹具：35号令×5 霸席 + 36号令正主 doc + 257号 + 3gpp。"""
    hits = []
    for i in range(5):
        hits.append(_hit(i + 1, 0.90 - 0.01 * i,
                         _rec("c35_%d" % i, DOC35, "miit", "附录1 3.%d" % i)))
    hits.append(_hit(6, 0.84, _rec("m36_a", DOC36, "miit", "附录4 4.2.2")))
    hits.append(_hit(7, 0.83, _rec("m36_b", DOC36, "miit", "附录4 4.2.3")))
    hits.append(_hit(8, 0.82, _rec("c257_a", DOC257, "miit", "主要目标 （二）")))
    hits.append(_hit(9, 0.81, _rec("g214_a", "TS 38.214", "3gpp", "5.2.2.1")))
    return hits


class TestDocQuotaSelectDomainTable(unittest.TestCase):
    """域表语义：域内 doc ≤N 让位+异 doc 补位（C19 对治形）；①关时非域表
    域块不限额；域表值覆盖全局档；exempt 优先；两遍制回补语义继承。"""

    def test_c19_crowd_capped_and_truth_doc_backfilled(self):
        # V5 §二 C19 面：35号令 5 席 → miit:2 配额后恰 2 席，36号令正主 doc
        # 与 257号 补位（异 doc 优先插队=回补语义的第一遍）
        out = rag.doc_quota_select(_c19_pool(), 5, None, (),
                                   domain_quotas={"miit": 2})
        self.assertEqual([h["rec"]["id"] for h in out],
                         ["c35_0", "c35_1", "m36_a", "m36_b", "c257_a"])
        self.assertEqual([h["rank"] for h in out], [1, 2, 3, 4, 5])

    def test_non_tabled_domain_unlimited_when_global_off(self):
        # ① 全局配额关+域表开：非域表域（3gpp）doc 不限额（轻路径核心语义
        # ——拨值只咬 miit，不外溢）
        hits = [_hit(i + 1, 0.9 - 0.01 * i,
                     _rec("g_%d" % i, "TS 38.133", "3gpp", "Annex A 表 %d" % i))
                for i in range(5)]
        out = rag.doc_quota_select(hits, 5, None, (),
                                   domain_quotas={"miit": 2})
        self.assertEqual([h["rec"]["id"] for h in out],
                         ["g_0", "g_1", "g_2", "g_3", "g_4"])

    def test_domain_value_overrides_global_quota(self):
        # ① 开（max=3）+域表 {"miit": 2}：miit doc 以域值 2 为准（更特异者
        # 胜），3gpp doc 受全局 3 席；池深足额（异 doc 补位面）→首遍即满、
        # 零回补=配额读数干净
        hits = ([_hit(i + 1, 0.9 - 0.01 * i,
                      _rec("c35_%d" % i, DOC35, "miit", "附录1 3.%d" % i))
                 for i in range(4)]
                + [_hit(5 + i, 0.85 - 0.01 * i,
                        _rec("a_%d" % i, "TS 38.133", "3gpp",
                             "Annex A 表 %d" % i)) for i in range(4)]
                + [_hit(9, 0.80, _rec("g214_a", "TS 38.214", "3gpp", "5.1")),
                   _hit(10, 0.79, _rec("g213_a", "TS 36.213", "3gpp", "5.2"))])
        out = rag.doc_quota_select(hits, 7, 3, (), domain_quotas={"miit": 2})
        docs = [h["rec"]["doc_id"] for h in out]
        self.assertEqual(docs.count(DOC35), 2)      # 域表值 2 覆盖全局 3
        self.assertEqual(docs.count("TS 38.133"), 3)
        self.assertEqual(docs, [DOC35, DOC35, "TS 38.133", "TS 38.133",
                                "TS 38.133", "TS 38.214", "TS 36.213"])

    def test_empty_table_equals_legacy_call(self):
        # domain_quotas 缺省/{}/None 三态=与旧调用形态逐字节一致（默认关纪律）
        pool = _c19_pool()
        legacy = rag.doc_quota_select(pool, 5, 2)
        for dq in (None, {}):
            out = rag.doc_quota_select(pool, 5, 2, (), domain_quotas=dq)
            self.assertEqual([(h["rec"]["id"], h["score"], h["rank"])
                              for h in out],
                             [(h["rec"]["id"], h["score"], h["rank"])
                              for h in legacy], dq)

    def test_quota_none_no_ddq_means_no_limit(self):
        # 防御位：quota=None+域表空=全不限额（服务层 enabled↔table 非空互锁
        # 下不可达，纯函数边界如实登记）——返回=topk 前缀成员不变
        out = rag.doc_quota_select(_c19_pool(), 5, None)
        self.assertEqual([h["rec"]["id"] for h in out],
                         ["c35_0", "c35_1", "c35_2", "c35_3", "c35_4"])

    def test_exempt_takes_priority_over_domain_table(self):
        # exempt（doc 子串豁免）优先于域表与全局档：35号令豁免=不限量
        out = rag.doc_quota_select(_c19_pool(), 5, None, ("35号",),
                                   domain_quotas={"miit": 2})
        self.assertEqual([h["rec"]["id"] for h in out],
                         ["c35_0", "c35_1", "c35_2", "c35_3", "c35_4"])

    def test_missing_source_domain_never_hits_table(self):
        # 缺 source_domain（""）恒不命中域表（保守向）→ 回落全局档：①开=受限、
        # ①关=不限
        hits = [_hit(1, 0.9, {"id": "x1", "doc_id": DOC35, "locator": "附录1"}),
                _hit(2, 0.8, {"id": "x2", "doc_id": DOC35, "locator": "附录2"}),
                _hit(3, 0.7, {"id": "x3", "doc_id": DOC35, "locator": "附录3"}),
                _hit(4, 0.6, _rec("m36_a", DOC36, "miit", "附录4 4.2.2")),
                _hit(5, 0.5, _rec("m36_b", DOC36, "miit", "附录4 4.2.3")),
                _hit(6, 0.4, _rec("g1", "TS 38.214", "3gpp", "5.1"))]
        out = rag.doc_quota_select(hits, 5, 1, (), domain_quotas={"miit": 2})
        # ①全局=1：x1 进、x2/x3 让位（域表不认缺字段行，回落全局档）；
        # m36 行命中域表=2 席；g1 不限额 → 首遍 4 席+回补 x2 满 5（两遍制）
        self.assertEqual([h["rec"]["id"] for h in out],
                         ["x1", "m36_a", "m36_b", "g1", "x2"])
        out2 = rag.doc_quota_select(hits, 5, None, (),
                                    domain_quotas={"miit": 2})
        # ①关：x 行不限额 → 前缀直取
        self.assertEqual([h["rec"]["id"] for h in out2],
                         ["x1", "x2", "x3", "m36_a", "m36_b"])

    def test_backfill_when_pool_cannot_fill(self):
        # 单 doc 主导池选不满 topk：让位块按原通道序回补至满——证据面绝不
        # 因配额缩水（S1 实测教训的回补语义，域表模式原样继承）
        hits = [_hit(i + 1, 0.9 - 0.01 * i,
                     _rec("c35_%d" % i, DOC35, "miit", "附录1 3.%d" % i))
                for i in range(6)]
        out = rag.doc_quota_select(hits, 5, None, (),
                                   domain_quotas={"miit": 2})
        self.assertEqual([h["rec"]["id"] for h in out],
                         ["c35_0", "c35_1", "c35_2", "c35_3", "c35_4"])
        self.assertEqual(len(out), 5)

    def test_empty_doc_id_not_counted(self):
        hits = [_hit(i + 1, 0.9 - 0.01 * i,
                     _rec("anon_%d" % i, "", "miit", "附录1 3.%d" % i))
                for i in range(3)]
        out = rag.doc_quota_select(hits, 3, None, (),
                                   domain_quotas={"miit": 1})
        self.assertEqual(len(out), 3)      # 匿名块无从归户=不计数不受限

    def test_input_not_mutated_and_rank_renumbered(self):
        pool = _c19_pool()
        snapshot = [(h["rank"], h["score"], dict(h["rec"])) for h in pool]
        out = rag.doc_quota_select(pool, 5, None, (),
                                   domain_quotas={"miit": 2})
        self.assertEqual([(h["rank"], h["score"], h["rec"]) for h in pool],
                         snapshot)
        self.assertEqual([h["rank"] for h in out], [1, 2, 3, 4, 5])

    def test_empty_hits(self):
        self.assertEqual(
            rag.doc_quota_select([], 5, None, (), {"miit": 2}), [])


# ---------------------------------------------------------------------------
# RagService 挂接（深候选池/默认关逐位一致/log 打点/拨板形态）
# ---------------------------------------------------------------------------
# (id, doc_id, source_domain, locator, e)——e 升序=cos 降序（vec=[1,e,0..]，
# query=[1,0..]，cos=1/sqrt(1+e²)，与 R1 测试同器）
_DDQ_FIXTURE = [
    ("c35_0", DOC35, "miit", "附录1 3.1", 0.00),
    ("c35_1", DOC35, "miit", "附录1 3.2", 0.01),
    ("c35_2", DOC35, "miit", "附录1 3.3", 0.02),
    ("c35_3", DOC35, "miit", "附录1 3.4", 0.03),
    ("c35_4", DOC35, "miit", "附录1 3.5", 0.04),
    ("m36_a", DOC36, "miit", "附录4 4.2.2", 0.05),
    ("m36_b", DOC36, "miit", "附录4 4.2.3", 0.06),
    ("c257_a", DOC257, "miit", "主要目标 （二）", 0.07),
    ("g214_a", "TS 38.214", "3gpp", "5.2.2.1", 0.08),
]
_DDQ_QUERY = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]


class _Silent:
    def __init__(self):
        self.lines = []

    def __call__(self, line):
        self.lines.append(line)


def _write_store(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for rid, doc, dom, loc, e in rows:
            vec = [1.0] + [0.0] * 7
            vec[1] = e
            f.write(json.dumps({"id": rid, "content": "内容 " + rid,
                                "doc_id": doc, "source_domain": dom,
                                "locator": loc, "chunk_type": "clause",
                                "embedding": vec},
                               ensure_ascii=False) + "\n")


def _ddq_service(rows, cfg_extra=None, topk=5):
    tmp = tempfile.mkdtemp(prefix="r2ddq-test-")
    store = os.path.join(tmp, "store.jsonl")
    _write_store(store, rows)
    svc = rag.RagService(embed_fn=lambda text: list(_DDQ_QUERY), log=_Silent(),
                         base_dir=tmp)
    cfg = {"enabled": True, "topk": topk, "store_path": store,
           "score_threshold": 0.0}
    cfg.update(cfg_extra or {})
    svc.initialize(cfg)
    return svc


class TestDomainDocQuotaServiceHook(unittest.TestCase):
    def test_default_off_byte_identical_with_plain_search(self):
        svc = _ddq_service(_DDQ_FIXTURE)
        hits = svc._search_one("q", _DDQ_QUERY)
        plain = rag.search(_DDQ_QUERY, svc._recs, 5)
        self.assertEqual([h["rec"]["id"] for h in hits],
                         [h["rec"]["id"] for h in plain])
        self.assertTrue(all(math.isclose(a["score"], b["score"], rel_tol=0,
                                         abs_tol=1e-12)
                            for a, b in zip(hits, plain)))
        # 默认关：C19 形原样（35号令×5 霸席）=V5 红灯读数同构
        self.assertEqual([h["rec"]["id"] for h in hits],
                         ["c35_0", "c35_1", "c35_2", "c35_3", "c35_4"])
        self.assertFalse(svc._decrowd_on())
        self.assertFalse([line for line in svc._log.lines if "rag-decrowd" in line])
        self.assertNotIn("cosine", hits[0])   # 旧 hit 形态（无重打分）

    def test_dial_on_c19_yields_and_backfill(self):
        # 拨板形态（部署窗 config）：{"miit": 2}——35号令恰 2 席、36号令正主
        # doc 与 257号 补位（深候选池=全 9 块在池，首遍即满配额席）
        svc = _ddq_service(_DDQ_FIXTURE, {"domain_doc_quota": {"miit": 2}})
        self.assertTrue(svc._decrowd_on())          # 触发深候选池
        hits = svc._search_one("q", _DDQ_QUERY)
        self.assertEqual([h["rec"]["id"] for h in hits],
                         ["c35_0", "c35_1", "m36_a", "m36_b", "c257_a"])
        docs = [h["rec"]["doc_id"] for h in hits]
        self.assertEqual(docs.count(DOC35), 2)
        self.assertEqual(docs.count(DOC36), 2)
        # 打点：[rag-decrowd] 行 quota=off（①关）+ ddq=miit:2
        ddq_lines = [line for line in svc._log.lines if "rag-decrowd" in line]
        self.assertEqual(len(ddq_lines), 1)
        self.assertIn("ddq=miit:2", ddq_lines[0])
        self.assertIn("quota=off", ddq_lines[0])
        # 选席不改分：cos 原始分在位，gate 读原始余弦（0.99+ 带非降权分）
        self.assertGreater(rag.gate_cosine(hits), 0.99)

    def test_initialize_recleans_bad_container(self):
        # initialize 键归一（单一尺=clean_domain_doc_quota_params）：非 dict
        # 整键回关、坏条目单丢
        svc = _ddq_service(_DDQ_FIXTURE, {"domain_doc_quota": ["miit"]})
        self.assertFalse(svc._domain_doc_quota["enabled"])
        svc2 = _ddq_service(_DDQ_FIXTURE,
                            {"domain_doc_quota": {"miit": 2, "bad": 0}})
        self.assertEqual(svc2._domain_doc_quota["table"], {"miit": 2})

    def test_off_retrieve_path_unchanged(self):
        # retrieve 全链默认关=现状（乙重排零信号 no-op、35号令×5 原样）
        svc = _ddq_service(_DDQ_FIXTURE)
        ev, src = svc.retrieve("监管配额测试")
        self.assertEqual([s.get("id") for s in src],
                         ["c35_0", "c35_1", "c35_2", "c35_3", "c35_4"])

    def test_dial_on_retrieve_evidence_swapped(self):
        # retrieve 全链拨开：证据面换员（35号令 5 席 → 2 席+正主 doc 补位）
        svc = _ddq_service(_DDQ_FIXTURE, {"domain_doc_quota": {"miit": 2}})
        ev, src = svc.retrieve("监管配额测试")
        self.assertEqual([s.get("id") for s in src],
                         ["c35_0", "c35_1", "m36_a", "m36_b", "c257_a"])

    def test_mq_deep_path_no_seat_selection(self):
        # 两态断言位一（ADR-0018 决策⑤ 2026-10-06 在册纪律修订调线，决策源=
        # 过程日志三节37③；旧锁面="mq 深度路径不选席"整句，修订表述="**路级**
        # （truncate=False）不选席：治理选席统一挂**融合级组装段**（mq_fused_
        # select 键域）"）：路级仍不选席——深度 8 返回通道原序、35号令 5 席
        # 不受限（"扭曲 RRF 融合语义"的关切仅适用于路级选席形态，本体保留）
        svc = _ddq_service(_DDQ_FIXTURE, {"domain_doc_quota": {"miit": 2}})
        hits = svc._search_one("q", _DDQ_QUERY, depth=8)
        self.assertEqual(len(hits), 8)
        docs = [h["rec"]["doc_id"] for h in hits]
        self.assertEqual(docs.count(DOC35), 5)

    def test_mq_fused_level_selection_two_states(self):
        # 两态断言位二（ADR-0018 决策⑤；实施=运营/扩容-R3C-代码批-
        # 20261006.md，详测=tests/test_扩容R3C融合级配额与弱注入.py）：
        # 融合级键关=现状逐字节不变（raw 前缀、35号令霸窗原样、零 [rag-mq-
        # quota] 行）；键开=融合级选席生效（miit doc ≤2 席、深池回补、打点在案）
        common = {"domain_doc_quota": {"miit": 2}, "mq_enabled": True,
                  "mq_fused_candidates": 9}   # 融合池=夹具全深 9（回补面）
        svc_off = _ddq_service(_DDQ_FIXTURE, dict(common))
        svc_off._variant_fn = lambda q: ["监管配额测试 en variant"]
        svc_on = _ddq_service(_DDQ_FIXTURE,
                              dict(common, mq_fused_select_enabled=True))
        svc_on._variant_fn = lambda q: ["监管配额测试 en variant"]
        off_hits = svc_off._retrieve_mq("监管配额测试")
        on_hits = svc_on._retrieve_mq("监管配额测试")
        # 键关=现状：融合窗前缀原样（embed stub 常量=两路同列表，RRF 保序）
        self.assertEqual([h["rec"]["id"] for h in off_hits],
                         ["c35_0", "c35_1", "c35_2", "c35_3", "c35_4"])
        self.assertFalse(any("rag-mq-quota" in line for line in svc_off._log.lines))
        # 键开=融合级配额生效：35号令 ≤2 席、36号令正主 doc 与 257号 深位回补
        self.assertEqual([h["rec"]["id"] for h in on_hits],
                         ["c35_0", "c35_1", "m36_a", "m36_b", "c257_a"])
        self.assertLessEqual(
            [h["rec"]["doc_id"] for h in on_hits].count(DOC35), 2)
        quota_lines = [line for line in svc_on._log.lines if "rag-mq-quota" in line]
        self.assertEqual(len(quota_lines), 1)
        self.assertIn("ddq=miit:2", quota_lines[0])
        self.assertIn("exit=fused", quota_lines[0])

    def test_global_quota_and_ddq_both_on(self):
        # ① 开（max=3）+域表 {"miit": 2} 同开：miit doc 以域值 2 为准、3gpp
        # doc 受全局 3 席；打点 quota=on:3 ddq=miit:2 并存
        rows = ([(("c35_%d" % i), DOC35, "miit", "附录1 3.%d" % i,
                  0.00 + 0.01 * i) for i in range(4)]
                + [(("a_%d" % i), "TS 38.133", "3gpp", "Annex A 表 %d" % i,
                    0.04 + 0.01 * i) for i in range(4)]
                + [("g214_a", "TS 38.214", "3gpp", "5.2.2.1", 0.08),
                   ("g213_a", "TS 36.213", "3gpp", "5.1.3.1", 0.09)])
        svc = _ddq_service(rows, {"domain_doc_quota": {"miit": 2},
                                  "doc_quota_enabled": True,
                                  "doc_quota_max": 3})
        hits = svc._search_one("q", _DDQ_QUERY)
        docs = [h["rec"]["doc_id"] for h in hits]
        self.assertEqual(docs.count(DOC35), 2)      # 域表值覆盖全局档
        self.assertEqual(docs.count("TS 38.133"), 3)
        line = [ln for ln in svc._log.lines if "rag-decrowd" in ln][0]
        self.assertIn("quota=on:3", line)
        self.assertIn("ddq=miit:2", line)


# ---------------------------------------------------------------------------
# 三方交互（famsel / 同源折叠 / 案甲域降权）
# ---------------------------------------------------------------------------
class TestFamselInteraction(unittest.TestCase):
    """famsel 在前（R1 父条让位）、overflow 并入配额回补池；域配额在后咬
    doc 席——序贯组合，证据面经两遍制不缩水。"""

    ROWS = [
        # 父条（无 款N 后缀）+两子款同族=层级族（"附录6 6.2.1 电信服务"）
        ("m_parent", DOC36, "miit", "附录6 6.2.1 电信服务", 0.00),
        ("m_child1", DOC36, "miit", "附录6 6.2.1 电信服务 款1", 0.01),
        ("c35_1", DOC35, "miit", "附录1 3.2", 0.02),
        ("c35_2", DOC35, "miit", "附录1 3.3", 0.03),
        ("c35_3", DOC35, "miit", "附录1 3.4", 0.04),
        ("m_child2", DOC36, "miit", "附录6 6.2.1 电信服务 款2", 0.05),
        ("c257_a", DOC257, "miit", "主要目标 （二）", 0.06),
        ("g214_a", "TS 38.214", "3gpp", "5.2.2.1", 0.07),
    ]

    def test_famsel_r1_drop_then_doc_quota_compose(self):
        svc = _ddq_service(self.ROWS, {"domain_doc_quota": {"miit": 2},
                                       "family_select_enabled": True})
        hits = svc._search_one("q", _DDQ_QUERY)
        # famsel R1：父条 m_parent 让位（子款在 topk 窗共存）→ overflow；
        # 配额走 selected+overflow 池：child1(36:1)、c35_1/c35_2(35:2 席)、
        # child2(36:2)、c257 → 满 5 席
        self.assertEqual([h["rec"]["id"] for h in hits],
                         ["m_child1", "c35_1", "c35_2", "m_child2", "c257_a"])
        docs = [h["rec"]["doc_id"] for h in hits]
        self.assertEqual(docs.count(DOC36), 2)
        self.assertEqual(docs.count(DOC35), 2)
        # 双打点在案：famsel 行 + decrowd 行 ddq 读数
        self.assertTrue(any("rag-famsel" in line and "r1_drop=1" in line
                            for line in svc._log.lines))
        self.assertTrue(any("rag-decrowd" in line and "ddq=miit:2" in line
                            for line in svc._log.lines))


class TestSameSourceFoldInteraction(unittest.TestCase):
    """同源折叠族键=(doc_id, locator 主干) **非 doc 级**（与 doc 配额不同
    粒度）：配额先咬 doc 席（选席窗=折叠窗 10）、折叠再咬同源单席——序贯
    组合无双重配额冲突。"""

    ROWS = [
        ("c35a", DOC35, "miit", "附录1 6.2 表", 0.00),
        ("c35b", DOC35, "miit", "附录1 6.2 表 行组1-5", 0.01),   # 同折叠族
        ("c35c", DOC35, "miit", "附录1 6.3 表", 0.02),
        ("c35d", DOC35, "miit", "附录1 6.4 表", 0.03),
        ("m36a", DOC36, "miit", "附录4 4.2.2", 0.04),
        ("m36b", DOC36, "miit", "附录4 4.2.3", 0.05),
        ("m36c", DOC36, "miit", "附录4 4.2.4", 0.06),
        ("c257a", DOC257, "miit", "主要目标 （二）", 0.07),
        ("c257b", DOC257, "miit", "主要目标 （三）", 0.08),
        ("g214", "TS 38.214", "3gpp", "5.2.2.1", 0.09),
        ("g213", "TS 36.213", "3gpp", "5.1.3.1", 0.10),
    ]

    def test_fold_key_is_not_doc_level(self):
        # 族键粒度核实：同 doc 不同 locator 主干=不同折叠族（折叠不咬）、
        # 同 doc 同主干（行组尾）=同族（折叠咬）——两者同处一个 doc 配额桶
        self.assertEqual(rag.same_source_family_key(
            {"doc_id": DOC35, "locator": "附录1 6.2 表"}),
            (DOC35, "附录1 6.2 表"))
        self.assertEqual(rag.same_source_family_key(
            {"doc_id": DOC35, "locator": "附录1 6.2 表 行组1-5"}),
            (DOC35, "附录1 6.2 表"))          # 行组尾剥离=同族
        self.assertNotEqual(rag.same_source_family_key(
            {"doc_id": DOC35, "locator": "附录1 6.3 表"}),
            (DOC35, "附录1 6.2 表"))          # 异主干=不同族（doc 配额才咬）

    def test_quota_then_fold_compose_on_retrieve(self):
        # 折叠开：_search_one 放粗到 10 窗（配额窗=fold_win）；配额先咬 doc
        # ≤2（首遍 8 席+回补 c35c/c35d 满 10）→折叠再咬同源单席（c35b 同族
        # 殿后）→终 top5
        svc = _ddq_service(self.ROWS, {"domain_doc_quota": {"miit": 2},
                                       "same_source_fold_enabled": True})
        win = svc._search_one("q", _DDQ_QUERY)
        self.assertEqual(len(win), 10)             # 折叠窗深
        docs10 = [h["rec"]["doc_id"] for h in win]
        for doc in (DOC35, DOC36, DOC257):
            self.assertLessEqual(docs10[:8].count(doc), 2,
                                 "首遍（前 8 席）doc 配额生效")
        ev, src = svc.retrieve("监管配额测试")
        # 折叠后终 top5：c35a（族首）、m36a/m36b、c257a/c257b
        self.assertEqual([s.get("id") for s in src],
                         ["c35a", "m36a", "m36b", "c257a", "c257b"])
        self.assertTrue(any("rag-fold" in line for line in svc._log.lines))
        self.assertTrue(any("rag-decrowd" in line and "ddq=miit:2" in line
                            for line in svc._log.lines))


class TestDomainDownweightInteraction(unittest.TestCase):
    """案甲域降权=选席前乘子（重打分段）、案丙域配额=选席段——正交组合：
    TH 域乘 0.5 让位+miit doc 席 ≤2 同题生效。"""

    ROWS = [
        ("th1", "telecomhall-t1", "telecomhall", "t1#p1", 0.00),
        ("th2", "telecomhall-t2", "telecomhall", "t2#p2", 0.01),
        ("c35a", DOC35, "miit", "附录1 3.1", 0.02),
        ("c35b", DOC35, "miit", "附录1 3.2", 0.03),
        ("c35c", DOC35, "miit", "附录1 3.3", 0.04),
        ("m36a", DOC36, "miit", "附录4 4.2.2", 0.05),
        ("m36b", DOC36, "miit", "附录4 4.2.3", 0.06),
        ("g214", "TS 38.214", "3gpp", "5.2.2.1", 0.07),
    ]

    def test_downweight_and_doc_quota_compose(self):
        svc = _ddq_service(self.ROWS,
                           {"domain_downweight": {"telecomhall": 0.5},
                            "domain_doc_quota": {"miit": 2}})
        hits = svc._search_one("q", _DDQ_QUERY)
        # TH×0.5 殿后（域内保序）；miit 配额：c35a/c35b(35:2)、m36a/m36b
        # (36:2)、g214 补位——35号令第三席让位
        self.assertEqual([h["rec"]["id"] for h in hits],
                         ["c35a", "c35b", "m36a", "m36b", "g214"])
        docs = [h["rec"]["doc_id"] for h in hits]
        self.assertEqual(docs.count(DOC35), 2)
        line = [ln for ln in svc._log.lines if "rag-decrowd" in ln][0]
        self.assertIn("domain_n=2", line)
        self.assertIn("ddq=miit:2", line)
        # cos 原始分零侵蚀（TH 块 cosine=原始分>0.99，非 ×0.5 分）
        th = [h for h in hits if h["rec"]["id"] == "th1"]
        self.assertEqual(th, [])    # TH 已让位出 top5
        self.assertGreater(rag.gate_cosine(hits), 0.99)


if __name__ == "__main__":
    unittest.main(verbosity=2)
