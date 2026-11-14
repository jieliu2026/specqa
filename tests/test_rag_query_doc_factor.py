# -*- coding: utf-8 -*-
"""rag.py H 线查询-族定向加权（query_doc_factor，2026-10-14 F线H 排序治理批）
离线单测。

命名口径同 test_rag_faiss.py：test_*.py 可 discover 形态
（`python -m unittest discover -s . -p "test_*.py"`）。

覆盖（全离线零 API，embed 全 stub，合成向量 dim=16）：
- 清洗面：默认缺键/[]=关；非 list 整键回关；坏条目（空信号词/缺目标面/
  factor 越界 (0,2]/非数字）单条丢弃不整组回退；name 缺省 ruleN；
- 纯函数：题面零命中信号=bit 级直通（对象同一性）；命中重排（-score, 原位次）
  + rank 重编；cosine 闸载体补挂与恒存；qdf_factor 归因键；多规则连乘；
  目标面三选择器（doc_contains 子串/corpus_types 精确/source_domains 归一）
  并集语义；词形归一（去空白+小写）互配；输入 hits 不被修改；
- 服务面：默认配置 _decrowd_on=False（零调用面）+ initialize 容缺键；
  键开时 _decrowd_on=True；deep 路径端到端（合成库）命中块让位+补位；
  [rag-qdf] 观测行（不含题面）。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import rag  # noqa: E402

DIM = 16


def _mk_hits():
    """合成深池 hits：3 块（doc A/B、corpus_type 卡/文、域 x/y）。"""
    recs = [
        {"id": "a1", "doc_id": "YD/T 5264-2021", "corpus_type": "行标",
         "source_domain": "ydt", "locator": "4.13.1", "version": "", "content": ""},
        {"id": "b1", "doc_id": "TS 36.331", "corpus_type": "case_card",
         "source_domain": "3gpp", "locator": "5.3.5.6", "version": "", "content": ""},
        {"id": "c1", "doc_id": "YD/T 4288-2023", "corpus_type": "行标",
         "source_domain": "ydt", "locator": "5", "version": "", "content": ""},
    ]
    return [{"rank": i + 1, "score": s, "rec": r}
            for i, (s, r) in enumerate(zip((0.8, 0.75, 0.7), recs))]


RULES_ON = {"query_doc_factor": [
    {"name": "r_sp", "query_words": ["审批"], "doc_contains": ["YD/T 5264-2021"],
     "factor": 0.7},
    {"name": "r_card", "query_words": ["核心网", "UPF"], "corpus_types": ["case_card"],
     "factor": 0.5},
]}


class TestClean(unittest.TestCase):
    def test_default_off(self):
        for cfg in ({}, {"query_doc_factor": []}, None):
            p = rag.clean_query_doc_factor_params(cfg or {})
            self.assertFalse(p["enabled"])
            self.assertEqual(p["rules"], ())

    def test_non_list_whole_key_off(self):
        p = rag.clean_query_doc_factor_params({"query_doc_factor": {"a": 1}})
        self.assertFalse(p["enabled"])

    def test_bad_entries_dropped_singly(self):
        p = rag.clean_query_doc_factor_params({"query_doc_factor": [
            RULES_ON["query_doc_factor"][0],
            {"query_words": [], "doc_contains": ["X"], "factor": 0.5},   # 空信号词
            {"query_words": ["w"], "factor": 0.5},                        # 缺目标面
            {"query_words": ["w"], "doc_contains": ["X"], "factor": 0},   # factor 越界
            {"query_words": ["w"], "doc_contains": ["X"], "factor": 2.5},  # factor 越界
            {"query_words": ["w"], "doc_contains": ["X"], "factor": "x"},  # 非数字
            {"query_words": ["w"], "doc_contains": ["X"]},                 # 缺 factor
            "not-a-dict",
        ]})
        self.assertTrue(p["enabled"])
        self.assertEqual(len(p["rules"]), 1)
        self.assertEqual(p["rules"][0]["name"], "r_sp")

    def test_name_default_and_factor_bounds(self):
        p = rag.clean_query_doc_factor_params({"query_doc_factor": [
            {"query_words": ["w"], "doc_contains": ["X"], "factor": 2.0},
            {"query_words": ["w2"], "source_domains": ["YDT"], "factor": 1.0},
        ]})
        self.assertEqual([r["name"] for r in p["rules"]], ["rule0", "rule1"])
        self.assertEqual([r["factor"] for r in p["rules"]], [2.0, 1.0])


class TestRescore(unittest.TestCase):
    def _params(self):
        return rag.clean_query_doc_factor_params(RULES_ON)

    def test_no_signal_passthrough_identity(self):
        hits = _mk_hits()
        out, info = rag.query_doc_factor_rescore(hits, "基站日常维护内容", self._params())
        self.assertIs(out, hits)                      # bit 级直通（零拷贝零重排）
        self.assertEqual(info["fired"], 0)

    def test_signal_rerank_and_factors(self):
        hits = _mk_hits()
        out, info = rag.query_doc_factor_rescore(hits, "5g基站建设审批流程", self._params())
        self.assertEqual(info["fired"], 1)
        # a1: 0.8×0.7=0.56 殿后；b1 0.75 首位、c1 0.7 第二（卡规则未激活）
        self.assertEqual([h["rec"]["id"] for h in out], ["b1", "c1", "a1"])
        self.assertEqual(round(out[2]["score"], 6), 0.56)
        self.assertEqual(out[2]["qdf_factor"], 0.7)
        self.assertAlmostEqual(out[2]["cosine"], 0.8)   # 闸载体=原始余弦
        self.assertEqual([h["rank"] for h in out], [1, 2, 3])

    def test_multi_rule_multiply(self):
        hits = _mk_hits()
        # 题面同含 审批+核心网 → r_sp 激活（a1）+ r_card 激活（b1）；b1 0.75×0.5=0.375
        out, info = rag.query_doc_factor_rescore(
            hits, "核心网审批流程怎么走", self._params())
        self.assertEqual(info["fired"], 2)
        self.assertEqual([h["rec"]["id"] for h in out], ["c1", "a1", "b1"])
        self.assertEqual(round(out[2]["score"], 6), 0.375)
        self.assertEqual(out[2]["qdf_factor"], 0.5)

    def test_word_normalization(self):
        hits = _mk_hits()
        # "UPF 用户面"（带空格）与 UPF 归一互配；UPF 全角/大小写变体同配
        out, info = rag.query_doc_factor_rescore(
            hits, "5G核心网 upf 节点故障", self._params())
        self.assertEqual(info["fired"], 1)
        self.assertEqual(out[-1]["rec"]["id"], "b1")

    def test_domain_selector_normalized(self):
        params = rag.clean_query_doc_factor_params({"query_doc_factor": [
            {"query_words": ["传输"], "source_domains": ["YDT"], "factor": 0.6}]})
        hits = _mk_hits()
        out, _ = rag.query_doc_factor_rescore(hits, "传输时延要求", params)
        # a1/c1（ydt 域）均降权：0.8×0.6=0.48/0.7×0.6=0.42 → b1 首位
        self.assertEqual([h["rec"]["id"] for h in out], ["b1", "a1", "c1"])

    def test_input_not_mutated(self):
        hits = _mk_hits()
        before = [(h["rank"], h["score"]) for h in hits]
        rag.query_doc_factor_rescore(hits, "审批流程", self._params())
        self.assertEqual([(h["rank"], h["score"]) for h in hits], before)

    def test_pool_zero_target_hits_passthrough(self):
        params = rag.clean_query_doc_factor_params({"query_doc_factor": [
            {"query_words": ["审批"], "doc_contains": ["不存在的件"], "factor": 0.5}]})
        hits = _mk_hits()
        out, info = rag.query_doc_factor_rescore(hits, "审批流程", params)
        self.assertIs(out, hits)                       # 信号在但池内零命中块=直通
        self.assertEqual(info["fired"], 1)
        self.assertEqual(info["hit_n"], 0)

    def test_empty_hits(self):
        out, info = rag.query_doc_factor_rescore([], "审批", self._params())
        self.assertEqual(out, [])
        self.assertEqual(info["fired"], 0)


class TestServiceWiring(unittest.TestCase):
    def _svc(self, cfg=None, extra=None):
        store = os.path.join(os.path.dirname(rag.__file__),
                             "tests", "_不存在库.jsonl")
        cfg = dict(cfg or {})
        cfg.update({"enabled": False, "store_path": store, "score_threshold": 0})
        cfg.update(extra or {})
        svc = rag.RagService(embed_fn=lambda t: [0.1] * DIM)
        logs = []
        svc._log = logs.append
        svc.initialize(cfg)
        return svc, logs

    def test_default_off_decrowd_on_false(self):
        svc, _ = self._svc()
        self.assertEqual(svc._cfg["query_doc_factor"], [])
        self.assertFalse(svc._qdf["enabled"])
        self.assertFalse(svc._decrowd_on())            # 零调用面

    def test_enabled_decrowd_on_true_and_log(self):
        svc, logs = self._svc(cfg=RULES_ON)
        self.assertTrue(svc._qdf["enabled"])
        self.assertTrue(svc._decrowd_on())
        hits = _mk_hits()
        out = svc._decrowd_assemble("5g基站建设审批流程", hits, topk=3)
        self.assertEqual([h["rec"]["id"] for h in out], ["b1", "c1", "a1"])
        self.assertTrue(any(line.startswith("[rag-qdf]") and "审批" not in line
                            for line in logs))

    def test_enabled_no_signal_no_log_no_change(self):
        svc, logs = self._svc(cfg=RULES_ON)
        hits = _mk_hits()
        out = svc._decrowd_assemble("基站日常维护", hits, topk=3)
        self.assertEqual([h["rec"]["id"] for h in out],
                         ["a1", "b1", "c1"])           # 零命中=纯截断原序
        self.assertFalse([line for line in logs if line.startswith("[rag-qdf]")])


if __name__ == "__main__":
    unittest.main()
