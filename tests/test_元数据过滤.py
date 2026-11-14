# -*- coding: utf-8 -*-
"""试点 2 元数据过滤（meta_filter_v1）单测（2026-10-01 施工，试点 2）。

对象=rag.py：parse_version_key/build_meta_version_index（版本族索引）、
clean_meta_filter_params（坏值清洗）、meta_filter_rescore（同族陈旧降权，
只乘通道排序分、余弦原始分恒存 cosine 键）+ RagService 挂接（装载期建索引、
decrowd 深候选池组装、默认关=现状逐字节不变）。
结构断言：默认关=_search_one 与模块级 search 逐位一致（id/score/rank 全等）；
开=陈旧块降权让位（含成员变化样例）；闸载体零侵蚀（cosine 键=原始余弦）；
空版本/不可解析版本（监管"发文年份"形）恒不降权。
零网络（stub embed_fn）、8 维夹具（真实库 1024 维，逻辑与维度无关）。
"""
import json
import math
import os
import tempfile
import unittest

import rag


def _rec(rid, doc_id, version, locator="4.1", content="内容"):
    return {"id": rid, "doc_id": doc_id, "version": version,
            "locator": locator, "content": content}


def _hit(rank, score, rec, idx=0):
    return {"rank": rank, "score": score, "rec": rec, "idx": idx}


# —— 服务级夹具库：7 块 8 维（query=[1,0,...]，cos=1/sqrt(1+e²)）——
# X.1 为双版本族（V18.10.0 陈旧 s1 余弦最高 vs V18.11.0 新鲜 f1/f2）；
# Y.3 空版本、Y.2/Y.4/TR Z.9 单版本（监管"发文年份"形的等价形态覆盖）。
FIXTURE = [
    # (id, doc_id, version, locator, e)        cos(q)
    ("s1", "TS X.1", "Rel-18 V18.10.0", "5.1", 0.05),   # 0.99875 陈旧族员
    ("f1", "TS X.1", "Rel-18 V18.11.0", "5.1", 0.12),   # 0.99288 新鲜族员
    ("f2", "TS X.1", "Rel-18 V18.11.0", "5.2", 0.14),   # 0.99015 新鲜族员
    ("n1", "TS Y.2", "Rel-18 V18.5.0", "6.1", 0.16),    # 0.98717 单版本
    ("n2", "TS Y.3", "", "7.1", 0.19),                  # 0.98243 空版本
    ("n3", "TS Y.4", "Rel-18 V18.2.0", "8.1", 0.22),    # 0.97669 单版本
    ("n4", "TR Z.9", "2026（发文年份）", "9.1", 0.26),   # 0.96824 不可解析
]
QUERY = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
OFF_TOP5 = ["s1", "f1", "f2", "n1", "n2"]
ON_TOP5 = ["f1", "f2", "n1", "n2", "n3"]        # s1×0.85=0.84894 落至 rank6


def write_fixture(path):
    with open(path, "w", encoding="utf-8") as f:
        for rid, doc, ver, loc, e in FIXTURE:
            vec = [1.0] + [0.0] * 7
            vec[1] = e
            f.write(json.dumps({"id": rid, "content": "%s 内容" % rid,
                                "doc_id": doc, "version": ver,
                                "locator": loc, "embedding": vec},
                               ensure_ascii=False) + "\n")


class _Silent:
    def __init__(self):
        self.lines = []

    def __call__(self, line):
        self.lines.append(line)


def _service(cfg_extra=None, store_path=None):
    tmp = tempfile.mkdtemp(prefix="metafilter-test-")
    store = store_path or os.path.join(tmp, "store.jsonl")
    if store_path is None:
        write_fixture(store)
    svc = rag.RagService(embed_fn=lambda text: list(QUERY), log=_Silent(),
                         base_dir=tmp)
    cfg = {"enabled": True, "topk": 5, "store_path": store}
    cfg.update(cfg_extra or {})
    svc.initialize(cfg)
    return svc


class TestParseVersionKey(unittest.TestCase):
    def test_triple_forms(self):
        self.assertEqual(rag.parse_version_key("Rel-18 V18.10.0"), (18, 10, 0))
        self.assertEqual(rag.parse_version_key("V18.9.0"), (18, 9, 0))
        self.assertEqual(rag.parse_version_key("v2.1.0"), (2, 1, 0))
        self.assertEqual(rag.parse_version_key("V18.10.0（刷新）"), (18, 10, 0))

    def test_unparseable(self):
        for bad in ("", None, "2026（发文年份）", "2026-01（发布）", "Rel-18"):
            self.assertIsNone(rag.parse_version_key(bad), bad)

    def test_comparison_ordering(self):
        self.assertGreater(rag.parse_version_key("V18.11.0"),
                           rag.parse_version_key("Rel-18 V18.10.0"))
        self.assertGreater(rag.parse_version_key("V19.0.0"),
                           rag.parse_version_key("V18.99.99"))


class TestBuildMetaVersionIndex(unittest.TestCase):
    def test_multi_version_family_latest(self):
        recs = [
            _rec("a", "TS X.1", "Rel-18 V18.10.0"),
            _rec("b", "TS X.1", "Rel-18 V18.11.0"),
            _rec("c", "TS X.1", "Rel-18 V18.10.0"),
        ]
        idx = rag.build_meta_version_index(recs)
        self.assertEqual(set(idx), {"TS X.1"})
        self.assertEqual(idx["TS X.1"][0], (18, 11, 0))
        self.assertEqual(idx["TS X.1"][1], "Rel-18 V18.11.0")

    def test_single_version_and_empty_not_family(self):
        recs = [
            _rec("a", "TS Y.2", "Rel-18 V18.5.0"),      # 单版本
            _rec("b", "TS Y.3", ""),                     # 空版本
            _rec("c", "TS Y.4", "2026（发文年份）"),      # 不可解析
            _rec("d", "TS Y.5", ""),                     # 空 + 单解析版 = 仍单版本族
            _rec("e", "TS Y.5", "Rel-18 V18.2.0"),
            _rec("f", "TS Y.6", "V18.10.0"),             # 同三元组不同写法=同版本
            _rec("g", "TS Y.6", "Rel-18 V18.10.0"),
        ]
        self.assertEqual(rag.build_meta_version_index(recs), {})

    def test_empty_recs(self):
        self.assertEqual(rag.build_meta_version_index([]), {})
        self.assertEqual(rag.build_meta_version_index(None), {})


class TestCleanMetaFilterParams(unittest.TestCase):
    def test_defaults_on_missing(self):
        p = rag.clean_meta_filter_params({})
        self.assertFalse(p["enabled"])
        self.assertEqual(p["stale_factor"], rag.DEFAULT_META_STALE_FACTOR)

    def test_bad_factor_falls_back(self):
        for bad in (0, -1, 1.5, "x", None, float("nan")):
            p = rag.clean_meta_filter_params({"meta_stale_factor": bad})
            self.assertEqual(p["stale_factor"], rag.DEFAULT_META_STALE_FACTOR, bad)
        p = rag.clean_meta_filter_params({"meta_stale_factor": 1.0})
        self.assertEqual(p["stale_factor"], 1.0)      # 1.0=合法（等价关）

    def test_enabled_coercion(self):
        self.assertTrue(rag.clean_meta_filter_params({"meta_filter_v1": 1})["enabled"])
        self.assertFalse(rag.clean_meta_filter_params({"meta_filter_v1": 0})["enabled"])
        self.assertEqual(rag.clean_meta_filter_params(None),
                         {"enabled": False,
                          "stale_factor": rag.DEFAULT_META_STALE_FACTOR})


class TestMetaFilterRescore(unittest.TestCase):
    def _pool(self):
        idx = rag.build_meta_version_index(
            [_rec(r[0], r[1], r[2]) for r in FIXTURE])
        hits = []
        def cos(e):
            return 1.0 / math.sqrt(1.0 + e * e)
        for rank, (rid, doc, ver, loc, e) in enumerate(FIXTURE, 1):
            hits.append(_hit(rank, cos(e), _rec(rid, doc, ver, loc), rank - 1))
        return hits, idx

    def test_disabled_returns_same_object(self):
        hits, idx = self._pool()
        out, info = rag.meta_filter_rescore(
            hits, {"enabled": False, "stale_factor": 0.85}, idx)
        self.assertIs(out, hits)                      # 零拷贝直通
        self.assertEqual(info, {"stale_n": 0, "families": 0})

    def test_empty_index_returns_same_object(self):
        hits, _ = self._pool()
        out, info = rag.meta_filter_rescore(
            hits, {"enabled": True, "stale_factor": 0.85}, {})
        self.assertIs(out, hits)

    def test_no_stale_in_pool_returns_same_object(self):
        # 池全为新鲜/无关块（去掉 s1）：bit 级直通
        hits, idx = self._pool()
        fresh = hits[1:]
        out, info = rag.meta_filter_rescore(
            fresh, {"enabled": True, "stale_factor": 0.85}, idx)
        self.assertIs(out, fresh)
        self.assertEqual(info["stale_n"], 0)

    def test_stale_downweighted_and_reordered(self):
        hits, idx = self._pool()
        snapshot = [dict(h) for h in hits]
        out, info = rag.meta_filter_rescore(
            hits, {"enabled": True, "stale_factor": 0.85}, idx)
        self.assertEqual(info, {"stale_n": 1, "families": 1})
        self.assertEqual([h["rec"]["id"] for h in out],
                         ["f1", "f2", "n1", "n2", "n3", "n4", "s1"])
        self.assertEqual([h["rank"] for h in out], [1, 2, 3, 4, 5, 6, 7])
        stale = out[6]
        self.assertEqual(stale["rec"]["id"], "s1")
        self.assertAlmostEqual(stale["score"], snapshot[0]["score"] * 0.85,
                               places=12)
        self.assertEqual(stale["meta_factor"], 0.85)
        self.assertAlmostEqual(stale["cosine"], snapshot[0]["score"],
                               places=12)            # 闸载体=原始余弦
        for h in out[:5]:                            # 非陈旧块不改分
            orig = next(x for x in snapshot if x["rec"]["id"] == h["rec"]["id"])
            self.assertEqual(h["score"], orig["score"])
            self.assertNotIn("meta_factor", h)
            self.assertEqual(h["cosine"], orig["score"])   # cosine 补挂
        self.assertEqual(hits, snapshot)             # 输入不被修改

    def test_factor_one_observes_without_rescoring(self):
        hits, idx = self._pool()
        out, info = rag.meta_filter_rescore(
            hits, {"enabled": True, "stale_factor": 1.0}, idx)
        self.assertEqual(info["stale_n"], 1)
        self.assertEqual([h["rec"]["id"] for h in out],
                         [h["rec"]["id"] for h in hits])   # 序不变
        stale = next(h for h in out if h["rec"]["id"] == "s1")
        self.assertEqual(stale["score"], hits[0]["score"])
        self.assertEqual(stale["meta_factor"], 1.0)

    def test_gate_cosine_unchanged_for_full_pool(self):
        # 成员不截断时（重打分态），集内最大余弦=原始值（降权只动通道排序分）
        hits, idx = self._pool()
        before = rag.gate_cosine(hits)
        out, _ = rag.meta_filter_rescore(
            hits, {"enabled": True, "stale_factor": 0.85}, idx)
        self.assertEqual(rag.gate_cosine(out), before)


class TestRagServiceMetaFilter(unittest.TestCase):
    def test_default_off_bit_identical_to_search(self):
        svc = _service()                       # 不含 meta 键=默认关
        self.assertFalse(svc._metaf["enabled"])
        self.assertIsNone(svc._meta_index)
        self.assertFalse(svc._decrowd_on())
        hits = svc._search_one("查询", QUERY)
        base = rag.search(QUERY, svc._recs, 5)
        self.assertIsNotNone(base)
        self.assertEqual([(h["rank"], h["score"], h["rec"]["id"]) for h in hits],
                         [(h["rank"], h["score"], h["rec"]["id"]) for h in base])
        self.assertEqual([h["rec"]["id"] for h in hits], OFF_TOP5)

    def test_on_builds_index_and_reorders(self):
        svc = _service({"meta_filter_v1": True, "meta_stale_factor": 0.85})
        self.assertTrue(svc._metaf["enabled"])
        self.assertTrue(svc._decrowd_on())
        self.assertIn("TS X.1", svc._meta_index)
        self.assertEqual(svc._meta_index["TS X.1"][0], (18, 11, 0))
        hits = svc._search_one("查询", QUERY)
        self.assertEqual([h["rec"]["id"] for h in hits], ON_TOP5)
        # 陈旧块出集（成员变化）；新鲜块 cosine=原始余弦（闸载体零侵蚀）
        ids = [h["rec"]["id"] for h in hits]
        self.assertNotIn("s1", ids)
        for h in hits:
            self.assertNotIn("meta_factor", h)   # 非陈旧块无标记
        pool_cos = {h["rec"]["id"]: h["cosine"] for h in hits}
        self.assertAlmostEqual(pool_cos["f1"], 1.0 / math.sqrt(1 + 0.12 ** 2),
                               places=6)   # float32 落存精度（~1e-8）
        log = "\n".join(svc._log.lines)
        self.assertIn("[rag-decrowd]", log)
        self.assertIn("meta_n=1", log)

    def test_on_retrieve_evidence_ok(self):
        svc = _service({"meta_filter_v1": True})
        out = svc.retrieve("查询")
        self.assertIsNotNone(out)
        evidence, sources = out
        self.assertTrue(evidence)
        self.assertEqual([s["doc_id"] for s in sources],
                         ["TS X.1", "TS X.1", "TS Y.2", "TS Y.3", "TS Y.4"])

    def test_switch_toggle_rebuilds_index(self):
        svc = _service({"meta_filter_v1": True})
        self.assertIsNotNone(svc._meta_index)
        svc.initialize({"enabled": True, "topk": 5,
                        "store_path": svc._cfg["store_path"]})
        self.assertIsNone(svc._meta_index)       # 关态重载=索引不建
        self.assertEqual([h["rec"]["id"] for h in svc._search_one("查询", QUERY)],
                         OFF_TOP5)

    def test_bad_factor_falls_back_to_default(self):
        svc = _service({"meta_filter_v1": True, "meta_stale_factor": 3})
        self.assertEqual(svc._metaf["stale_factor"], rag.DEFAULT_META_STALE_FACTOR)


if __name__ == "__main__":
    unittest.main()
