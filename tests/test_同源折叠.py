# -*- coding: utf-8 -*-
"""同源折叠（same_source_fold，检索链尾键）离线单测（2026-10-03 施工）。

对象=rag.py：same_source_family_key 族键剥离（先剥尾 "(pN)" 再剥尾
"行组N[-–]N"，[-–] 含 ASCII - 与 U+2013 –——与 建库/work/排序优化-
20261002/消融.py fam_key 逐字同器）、same_source_fold1 单席族帽（族首留位/
超席殿后保序/同集合置换）、clean_same_source_fold_params 键清洗（缺键/
非法值回 false）、挂接面（_search_one/_retrieve_mq 窗深放粗、
_decrowd_assemble fold_window 只放粗组装截断、retrieve 链尾=乙层头 topk +
窗 6-10 原序殿后 → fold1 → 截 topk + rank 重编）。

结构断言（关态零触碰）：same_source_fold_enabled=false（默认）时——
_fold.enabled=False、_search_one 仍截 topk、_decrowd_assemble 仍截 topk、
retrieve 证据集=现行排序（同族重复块原样相邻保留，零折叠零换序）。
依据与判卷=运营/呈报-纯折叠第二钥匙-20261003.md（过程日志三节 26②同日终拍
+ADR-0009 调线记录在档；试点=建库/work/纯折叠试点-20261003/）。
零网络（stub embed_fn）、8 维夹具（真实库 1024 维，逻辑与维度无关）。
"""
import json
import math
import os
import tempfile
import unittest

import rag

QUERY = [1, 0, 0, 0, 0, 0, 0, 0]

# 12 块 8 维夹具：对 QUERY 余弦严格降序（rank=余弦序），族交织——
# D1 表A 三克隆（(p1)/(p2)/行组3-5）+ 窗外第 4 克隆 (p3)、D2 表B 两克隆
# （本体/行组2）、D3-D8 各单席。fold1(top10) 期望：taken=c01/c03/c05/c06/
# c08/c09/c10、deferred=c02/c04/c07、top5=[c01,c03,c05,c06,c08]。
FIXTURE = [
    # (id, doc_id, locator, cos)
    ("c01", "D1", "表A (p1)", 0.995),
    ("c02", "D1", "表A (p2)", 0.990),
    ("c03", "D2", "表B", 0.980),
    ("c04", "D1", "表A 行组3-5", 0.970),
    ("c05", "D3", "条C", 0.960),
    ("c06", "D4", "表D", 0.950),
    ("c07", "D2", "表B 行组2", 0.940),
    ("c08", "D5", "条E", 0.930),
    ("c09", "D6", "表F", 0.920),
    ("c10", "D7", "条G", 0.910),
    ("c11", "D1", "表A (p3)", 0.900),
    ("c12", "D8", "条H", 0.890),
]
EXPECTED_TOP5_OFF = ["c01", "c02", "c03", "c04", "c05"]   # 关态=现行排序
EXPECTED_TOP5_ON = ["c01", "c03", "c05", "c06", "c08"]    # 折叠后（c06/c08 晋位）


def write_fold_fixture(path):
    """写 12 块合法记录到 jsonl（余弦由首两维承载，幅值归一）。"""
    with open(path, "w", encoding="utf-8") as f:
        for cid, doc, loc, cos in FIXTURE:
            sin = math.sqrt(max(0.0, 1.0 - cos * cos))
            f.write(json.dumps(
                {"id": cid, "content": f"内容{cid}（{doc} {loc}）",
                 "doc_id": doc, "version": "V1", "locator": loc,
                 "embedding": [cos, sin, 0, 0, 0, 0, 0, 0]},
                ensure_ascii=False) + "\n")


def _hit(rank, doc, loc, rid=None):
    """通道形态 hit（rank/score/rec），供纯函数直测。"""
    return {"rank": rank, "score": 1.0 - rank * 0.01,
            "rec": {"id": rid or f"{doc}#{rank}", "doc_id": doc,
                    "version": "V", "locator": loc, "content": "内容"}}


class SameSourceFamilyKeyTest(unittest.TestCase):
    """族键剥离三态：剥 "(pN)"、剥 "行组N[-–]N"、无后缀原样。"""

    def test_strip_pn_suffix(self):
        self.assertEqual(
            rag.same_source_family_key({"doc_id": "38.133",
                                        "locator": "Annex A 表 (p12)"}),
            ("38.133", "Annex A 表"))          # 多位数页码
        self.assertEqual(
            rag.same_source_family_key({"doc_id": "D", "locator": "表A (p1)"}),
            rag.same_source_family_key({"doc_id": "D", "locator": "表A (p2)"}),
            "同 doc 跨分页并族")

    def test_strip_rowgroup_suffix(self):
        for loc in ("表B 行组2", "表B 行组3-5", "表B 行组3–5"):  # ASCII - 与 U+2013 –
            self.assertEqual(rag.same_source_family_key(
                {"doc_id": "D", "locator": loc}), ("D", "表B"), loc)

    def test_strip_both_in_order(self):
        # 先剥 "(pN)" 再剥 "行组N-M"（顺序敏感：反向剥不掉）
        self.assertEqual(
            rag.same_source_family_key({"doc_id": "36.133",
                                        "locator": "Annex A 表 行组3-5 (p2)"}),
            ("36.133", "Annex A 表"))

    def test_no_suffix_unchanged_and_not_overstripped(self):
        self.assertEqual(
            rag.same_source_family_key({"doc_id": "36号", "locator": "附录1 1.2.3 款2"}),
            ("36号", "附录1 1.2.3 款2"))        # " 款N" 是乙层语义，本键不剥
        self.assertEqual(
            rag.same_source_family_key({"doc_id": "D", "locator": "X.Y.Z 表"}),
            ("D", "X.Y.Z 表"))

    def test_missing_fields_conservative(self):
        self.assertEqual(rag.same_source_family_key({}), ("", ""))
        self.assertEqual(rag.same_source_family_key(None), ("", ""))
        self.assertEqual(rag.same_source_family_key({"doc_id": "D"}),
                         ("D", ""))              # 缺 locator=空主干单席族
        # 36.101 "X.Y.Z 表" 同表并族（doc 相同、locator 主干相同）
        self.assertEqual(
            rag.same_source_family_key({"doc_id": "36.101", "locator": "4.2.1 表"}),
            rag.same_source_family_key({"doc_id": "36.101", "locator": "4.2.1 表 行组7"}))

    def test_whitespace_and_strip(self):
        self.assertEqual(
            rag.same_source_family_key({"doc_id": "D", "locator": "  表A 行组2  "}),
            ("D", "表A"))


class SameSourceFold1Test(unittest.TestCase):
    """fold1 单席族帽：单席/殿后保序/回填晋位/空列表/不足5/集合置换。"""

    def test_empty_list(self):
        self.assertEqual(rag.same_source_fold1([]), ([], []))

    def test_single_seat_deferred_to_tail(self):
        seq = [_hit(1, "D", "表A (p1)"), _hit(2, "D", "表A (p2)"),
               _hit(3, "E", "条B")]
        folded, deferred = rag.same_source_fold1(seq)
        self.assertEqual([h["rec"]["id"] for h in folded], ["D#1", "E#3", "D#2"])
        self.assertEqual([h["rec"]["id"] for h in deferred], ["D#2"])

    def test_deferred_keep_relative_order(self):
        seq = [_hit(1, "D", "表A (p1)"), _hit(2, "D", "表A (p2)"),
               _hit(3, "E", "条B"), _hit(4, "D", "表A 行组3-5"),
               _hit(5, "F", "条C")]
        folded, deferred = rag.same_source_fold1(seq)
        self.assertEqual([h["rec"]["id"] for h in folded],
                         ["D#1", "E#3", "F#5", "D#2", "D#4"])
        self.assertEqual([h["rec"]["id"] for h in deferred], ["D#2", "D#4"])

    def test_promote_into_top5(self):
        """回填：窗内位 6 晋位补 top5 缺席（族首覆盖只增不减的题面形态）。"""
        seq = [_hit(i, *FIXTURE[i - 1][1:3], rid=FIXTURE[i - 1][0])
               for i in range(1, 11)]            # c01..c10（=夹具余弦序）
        folded, deferred = rag.same_source_fold1(seq)
        ids = [h["rec"]["id"] for h in folded]
        self.assertEqual(ids[:5], EXPECTED_TOP5_ON)
        self.assertEqual(ids[5:], ["c09", "c10", "c02", "c04", "c07"])
        self.assertEqual([h["rec"]["id"] for h in deferred],
                         ["c02", "c04", "c07"])

    def test_set_permutation_invariant(self):
        seq = [_hit(i, *FIXTURE[i - 1][1:3], rid=FIXTURE[i - 1][0])
               for i in range(1, 13)]            # 全 12 块（含窗外 c11/c12）
        folded, deferred = rag.same_source_fold1(seq)
        self.assertEqual(sorted(h["rec"]["id"] for h in folded),
                         sorted(h["rec"]["id"] for h in seq), "同集合置换")
        self.assertEqual(len(folded), 12)
        # 全列表折叠时窗外克隆 c11 也殿后（窗纪律由调用方截窗，纯函数不吃窗）
        self.assertEqual([h["rec"]["id"] for h in deferred],
                         ["c02", "c04", "c07", "c11"])

    def test_short_list_under_topk(self):
        """不足 topk：折叠仍是同集合置换，绝不多不少。"""
        seq = [_hit(1, "D", "表A (p1)"), _hit(2, "D", "表A (p2)"),
               _hit(3, "E", "条B"), _hit(4, "F", "条C")]
        folded, deferred = rag.same_source_fold1(seq)
        self.assertEqual([h["rec"]["id"] for h in folded[:5]],
                         ["D#1", "E#3", "F#4", "D#2"])
        self.assertEqual(len(deferred), 1)

    def test_missing_rec_family_semantics(self):
        """缺 rec 行族键归 ("", "")=同族（=试点 fam_key 同器语义，第二席殿后；
        生产 hit 恒有 rec，本位为纯函数边界登记）。"""
        seq = [{"rank": 1, "score": 0.9}, {"rank": 2, "score": 0.8},
               _hit(3, "D", "表A")]
        folded, deferred = rag.same_source_fold1(seq)
        self.assertEqual([id(h) for h in folded],
                         [id(h) for h in [seq[0], seq[2], seq[1]]])
        self.assertEqual(deferred, [seq[1]])

    def test_input_not_modified(self):
        seq = [_hit(1, "D", "表A (p1)"), _hit(2, "D", "表A (p2)"),
               _hit(3, "E", "条B")]
        snapshot = [dict(h) for h in seq]
        rag.same_source_fold1(seq)
        self.assertEqual(seq, snapshot, "输入列表与元素零改动")


class CleanSameSourceFoldParamsTest(unittest.TestCase):
    """config 清洗：缺键/非法值回 false，仅严格布尔 true 开启。"""

    def test_default_off(self):
        self.assertIs(rag.DEFAULT_RAG_CONFIG["same_source_fold_enabled"], False)

    def test_missing_key_off(self):
        self.assertEqual(rag.clean_same_source_fold_params({}),
                         {"enabled": False})
        self.assertEqual(rag.clean_same_source_fold_params(None),
                         {"enabled": False})

    def test_illegal_values_off(self):
        for bad in ("true", "yes", 1, 0, [True], {"enabled": True}, "是"):
            p = rag.clean_same_source_fold_params(
                {"same_source_fold_enabled": bad})
            self.assertIs(p["enabled"], False, bad)

    def test_strict_true_on(self):
        self.assertIs(rag.clean_same_source_fold_params(
            {"same_source_fold_enabled": True})["enabled"], True)

    def test_initialize_normalizes_and_init_default(self):
        with tempfile.TemporaryDirectory() as td:
            store = os.path.join(td, "embeddings.jsonl")
            write_fold_fixture(store)
            svc = rag.RagService(embed_fn=lambda q: list(QUERY))
            self.assertIs(svc._fold["enabled"], False)   # __init__ 默认关
            svc.initialize({"store_path": store,
                            "same_source_fold_enabled": "true"})
            self.assertIs(svc._fold["enabled"], False)   # 非法值回 false
            self.assertIs(svc._cfg["same_source_fold_enabled"], False)
            svc.initialize({"store_path": store,
                            "same_source_fold_enabled": True})
            self.assertIs(svc._fold["enabled"], True)    # 严格 true 开
            self.assertIs(svc._cfg["same_source_fold_enabled"], True)


class FoldOffEquivalenceTest(unittest.TestCase):
    """关态零触碰：enabled=false 时现路径原样（_search_one 截 topk、证据集
    =现行排序，同族重复块原样相邻保留，零折叠零换序）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = os.path.join(self.tmp.name, "embeddings.jsonl")
        write_fold_fixture(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def _svc(self, extra=None):
        cfg = {"store_path": self.store}
        cfg.update(extra or {})
        svc = rag.RagService(embed_fn=lambda q: list(QUERY))
        svc.initialize(cfg)
        return svc

    def test_off_returns_plain_top5_with_duplicates(self):
        svc = self._svc()
        out = svc.retrieve("表A 是什么")
        self.assertIsNotNone(out)
        evidence, sources = out
        self.assertEqual([s["id"] for s in sources], EXPECTED_TOP5_OFF)
        self.assertIn("[出处5]", evidence)      # build_evidence 编号 1..5

    def test_off_search_one_truncates_topk(self):
        svc = self._svc()
        hits = svc._search_one("表A", QUERY)
        self.assertEqual(len(hits), 5)
        self.assertEqual([h["rec"]["id"] for h in hits], EXPECTED_TOP5_OFF)

    def test_off_decrowd_assemble_truncates_topk(self):
        """hybrid+decrowd 开（走 _decrowd_assemble truncate 分支）仍截 topk。"""
        svc = self._svc({"hybrid_bm25_enabled": True,
                         "table_downweight_enabled": True})
        hits = svc._search_one("表A", QUERY)
        self.assertEqual(len(hits), 5)

    def test_off_fold_window_none_is_identity(self):
        """fold_window=None（关态传参）与不传同值：组装截断=topk。"""
        svc = self._svc({"hybrid_bm25_enabled": True,
                         "table_downweight_enabled": True})
        cos = svc._search_cos(QUERY, 20)
        a = svc._decrowd_assemble("表A", list(cos), 5, truncate=True)
        b = svc._decrowd_assemble("表A", list(cos), 5, truncate=True,
                                  fold_window=None)
        self.assertEqual([h["rec"]["id"] for h in a],
                         [h["rec"]["id"] for h in b])
        self.assertEqual(len(a), 5)


class FoldOnIntegrationTest(unittest.TestCase):
    """开态挂接：窗深放粗（前 10）、乙层只吃头 topk、fold1 截 top5、rank 重编。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = os.path.join(self.tmp.name, "embeddings.jsonl")
        write_fold_fixture(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def _svc(self, extra=None):
        cfg = {"store_path": self.store, "same_source_fold_enabled": True}
        cfg.update(extra or {})
        svc = rag.RagService(embed_fn=lambda q: list(QUERY))
        svc.initialize(cfg)
        return svc

    def test_search_one_returns_window_depth(self):
        svc = self._svc()
        hits = svc._search_one("表A", QUERY)     # 纯余弦路：fold_win=10
        self.assertEqual(len(hits), 10)
        self.assertEqual([h["rec"]["id"] for h in hits],
                         [f[0] for f in FIXTURE[:10]])

    def test_search_one_window_under_depth(self):
        """不足 10 取全部（夹具剪到 7 块 → 窗=7）。"""
        keep = FIXTURE[:7]
        path = os.path.join(self.tmp.name, "small.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            for cid, doc, loc, cos in keep:
                sin = math.sqrt(max(0.0, 1.0 - cos * cos))
                f.write(json.dumps({"id": cid, "content": f"内容{cid}",
                                    "doc_id": doc, "version": "V1",
                                    "locator": loc,
                                    "embedding": [cos, sin, 0, 0, 0, 0, 0, 0]},
                                   ensure_ascii=False) + "\n")
        svc = rag.RagService(embed_fn=lambda q: list(QUERY))
        svc.initialize({"store_path": path,
                        "same_source_fold_enabled": True})
        hits = svc._search_one("表A", QUERY)
        self.assertEqual(len(hits), 7)

    def test_decrowd_deep_path_window(self):
        """hybrid+decrowd 深池路：_decrowd_assemble fold_window 放粗到 10
        （窗序=RRF 融合+重打分序，不作余弦序断言——通道序语义归通道测试）。"""
        svc = self._svc({"hybrid_bm25_enabled": True,
                         "table_downweight_enabled": True})
        hits = svc._search_one("表A", QUERY)
        self.assertEqual(len(hits), 10)
        ids = [h["rec"]["id"] for h in hits]
        self.assertEqual(len(set(ids)), 10)      # 窗内无重复
        self.assertTrue(set(ids) <= {f[0] for f in FIXTURE})
        self.assertEqual([h["rank"] for h in hits], list(range(1, 11)))

    def test_retrieve_folds_top5_and_renumbers_ranks(self):
        svc = self._svc()
        out = svc.retrieve("表A 是什么")
        self.assertIsNotNone(out)
        evidence, sources = out
        self.assertEqual([s["id"] for s in sources], EXPECTED_TOP5_ON)
        for i, s in enumerate(sources, 1):
            self.assertIn(f"[出处{i}]", evidence)   # rank 重编 1..5

    def test_retrieve_set_permutation_within_window(self):
        svc = self._svc()
        out = svc.retrieve("表A 是什么")
        _, sources = out
        window_ids = [f[0] for f in FIXTURE[:10]]
        self.assertTrue(set(s["id"] for s in sources) <= set(window_ids),
                        "终 top5 成员⊆窗内前 10（同集合面=窗内置换取前 5）")
        fams = [rag.same_source_family_key(
            {"doc_id": f[1], "locator": f[2]})
            for f in FIXTURE if f[0] in {s["id"] for s in sources}]
        self.assertEqual(len(fams), len(set(fams)), "终 top5 单席族帽")

    def test_clause_rerank_applies_to_head_only(self):
        """乙层头 topk + 窗 6-10 原序殿后：夹具无款后缀/无词表信号 → 乙=恒等，
        折叠结果=纯 fold1(余弦 top10)——与 test_retrieve_folds_top5 同锚。"""
        svc = self._svc()                          # clause_family_rerank 默认开
        self.assertTrue(svc._cfg.get("clause_family_rerank"))
        hits = svc._search_one("表A", QUERY)
        rer = rag.clause_family_rerank("表A", hits[:5], "full")
        self.assertEqual([h["rec"]["id"] for h in rer], EXPECTED_TOP5_OFF)
        folded, deferred = rag.same_source_fold1(
            rer + hits[5:10])                      # =retrieve 链尾构造
        self.assertEqual([h["rec"]["id"] for h in folded[:5]],
                         EXPECTED_TOP5_ON)

    @unittest.skipIf(rag.multiquery is None, "multiquery 模块缺席")
    def test_mq_path_window_depth(self):
        """mq 路终截断同放粗到折叠窗（rrf_fuse topk=窗深）。"""
        calls = {"n": 0}

        def variant_fn(q):
            calls["n"] += 1
            return ["变体一句话"]

        by_text = {"原查询": list(QUERY), "变体一句话": [0, 1, 0, 0, 0, 0, 0, 0]}
        svc = rag.RagService(embed_fn=lambda t: by_text[t],
                             variant_fn=variant_fn)
        svc.initialize({"store_path": self.store, "mq_enabled": True,
                        "same_source_fold_enabled": True})
        hits = svc._retrieve_mq("原查询")
        self.assertEqual(len(hits), 10)            # 折叠窗深（关态=5）
        svc_off = rag.RagService(embed_fn=lambda t: by_text[t],
                                 variant_fn=variant_fn)
        svc_off.initialize({"store_path": self.store, "mq_enabled": True})
        self.assertEqual(len(svc_off._retrieve_mq("原查询")), 5)


if __name__ == "__main__":
    unittest.main()
