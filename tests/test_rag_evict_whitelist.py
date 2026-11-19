# -*- coding: utf-8 -*-
"""B-evict 定向清位 + 表降权白名单 双键正向单测（独立测件，无对拍基线依赖）。

对象=rag.py 两配置键（默认均关）：
- b_evict_enabled（默认 false）：挂检索链尾（同源折叠后、终 topk 截断与闸门段
  之前）。题面命中 B_EVICT_VOCAB（七词冻结）才激活；激活后以窗内 rank1 块
  负项集为基准（n1=rank1 缺词数）逐出负项严格超基准（n(b)>n1）的块，幸存者
  原序取前 topk（席位不足如实缩减；rank1 恒幸存；W 空=零改动原样返回）。
- table_downweight_whitelist（默认 []）：消费点=decrowd_rescore ②表因子分支
  ——locator 正则（re.search）命中白名单的块静默跳过表降权（③制式不受
  影响、cosine 闸载体不变、无新打点）。

本件=正向行为测件：不与任何改前备份对拍，全部断言自明（键清洗/纯函数
语义/检索链集成/表降权豁免四层）。零网络（stub embed_fn）、8 维夹具
（逻辑与维度无关）。

运行：/home/jieliu/qa-bot/venv/bin/python -m pytest tests/test_rag_evict_whitelist.py -q
"""
import json
import math
import os
import re
import tempfile
import unittest

import rag

QUERY = [1, 0, 0, 0, 0, 0, 0, 0]

# B_STRONG 七词冻结镜像（词表若被改动，本断言亮红灯=扩改须走变更纪律的测试面）
B_STRONG_FROZEN = ("国内长途", "无线信道", "IP电话", "呼叫建立", "消息", "成功", "抖动")

# 激活题面（W=国内长途/呼叫建立/成功，按 B_EVICT_VOCAB 序）与块内容三态
Q_EVICT = "国内长途呼叫建立的成功率是多少"
C_ALL = "国内长途 呼叫建立 成功 指标定义原文"          # 三词全含（n=0）
C_MISS1 = "国内长途 呼叫建立 指标定义原文"             # 缺"成功"（n=1）
C_MISS2 = "国内长途 指标定义原文"                      # 缺"呼叫建立/成功"（n=2）
C_MISS3 = "无关内容甲乙丙丁"                           # 三词全缺（n=3）

# 12 块 8 维夹具（余弦严格降序；e02 与 e01 同族=折叠组合支用，fold 关态无影响）
FIXTURE = [
    # (id, doc_id, locator, cos, content)
    ("e01", "TS 38.101", "4.1 条", 0.995, C_ALL),
    ("e02", "TS 38.101", "4.1 条 (p2)", 0.990, C_MISS3),
    ("e03", "TS 38.101", "4.2 条", 0.980, C_ALL),
    ("e04", "TS 38.331", "5.3 条", 0.970, C_MISS1),
    ("e05", "TS 38.101", "4.3 条", 0.960, C_ALL),
    ("e06", "TS 38.201", "6.1 条", 0.950, C_ALL),
    ("e07", "TS 38.202", "6.2 条", 0.940, C_ALL),
    ("e08", "TS 38.203", "6.3 条", 0.930, C_ALL),
    ("e09", "TS 38.204", "6.4 条", 0.920, C_ALL),
    ("e10", "TS 38.205", "6.5 条", 0.910, C_ALL),
    ("e11", "TS 38.206", "6.6 条", 0.900, C_MISS3),
    ("e12", "TS 38.207", "6.7 条", 0.890, C_MISS3),
]
# 关态=现行余弦序 top5；折叠开+evict 开=e02/e04 逐出、e06/e07 晋位
EXPECTED_TOP5_OFF = ["e01", "e02", "e03", "e04", "e05"]
EXPECTED_TOP5_EVICT_FOLD = ["e01", "e03", "e05", "e06", "e07"]


def write_fixture(path, rows=None):
    """写夹具到 jsonl（余弦由首两维承载，幅值归一）。"""
    rows = rows if rows is not None else FIXTURE
    with open(path, "w", encoding="utf-8") as f:
        for cid, doc, loc, cos, content in rows:
            sin = math.sqrt(max(0.0, 1.0 - cos * cos))
            f.write(json.dumps(
                {"id": cid, "content": content, "doc_id": doc,
                 "version": "V1", "locator": loc,
                 "embedding": [cos, sin, 0, 0, 0, 0, 0, 0]},
                ensure_ascii=False) + "\n")


def _hit(rank, score, doc, loc, ctype=None, content="内容", version="V1"):
    """通道形态 hit（rank/score/rec），供纯函数直测。"""
    return {"rank": rank, "score": score,
            "rec": {"id": "%s#%d" % (doc, rank), "doc_id": doc,
                    "version": version, "locator": loc, "content": content,
                    **({"chunk_type": ctype} if ctype is not None else {})}}


class _Silent:
    """日志收集器（行为断言用 lines；默认注入后不打印）。"""

    def __init__(self):
        self.lines = []

    def __call__(self, line):
        self.lines.append(line)


# ---------------------------------------------------------------------------
# 默认键面与词表冻结
# ---------------------------------------------------------------------------
class DefaultsAndVocabTest(unittest.TestCase):
    """默认关态键面：两键默认值 + B_EVICT_VOCAB 七词冻结。"""

    def test_defaults_off_and_empty(self):
        self.assertIs(rag.DEFAULT_RAG_CONFIG["b_evict_enabled"], False)
        self.assertEqual(rag.DEFAULT_RAG_CONFIG["table_downweight_whitelist"], [])

    def test_vocab_frozen_seven_words(self):
        self.assertEqual(rag.B_EVICT_VOCAB, B_STRONG_FROZEN)
        self.assertEqual(len(rag.B_EVICT_VOCAB), 7)
        self.assertNotIn("5G", rag.B_EVICT_VOCAB, "裸词 5G 禁入一切词表")


class CleanBEvictParamsTest(unittest.TestCase):
    """键清洗：缺键/非法值回 false，仅严格布尔 true 开启。"""

    def test_missing_key_off(self):
        self.assertEqual(rag.clean_b_evict_params({}), {"enabled": False})
        self.assertEqual(rag.clean_b_evict_params(None), {"enabled": False})

    def test_illegal_values_off(self):
        for bad in ("true", "yes", 1, 0, [True], {"enabled": True}, "开"):
            self.assertIs(rag.clean_b_evict_params(
                {"b_evict_enabled": bad})["enabled"], False, bad)

    def test_strict_true_on(self):
        self.assertIs(rag.clean_b_evict_params(
            {"b_evict_enabled": True})["enabled"], True)

    def test_initialize_normalizes_and_init_default(self):
        with tempfile.TemporaryDirectory() as td:
            store = os.path.join(td, "embeddings.jsonl")
            write_fixture(store)
            svc = rag.RagService(embed_fn=lambda q: list(QUERY))
            self.assertIs(svc._bevict["enabled"], False)   # __init__ 默认关
            svc.initialize({"store_path": store, "b_evict_enabled": "true"})
            self.assertIs(svc._bevict["enabled"], False)   # 非法值回 false
            self.assertIs(svc._cfg["b_evict_enabled"], False)
            svc.initialize({"store_path": store, "b_evict_enabled": True})
            self.assertIs(svc._bevict["enabled"], True)    # 严格 true 开
            self.assertIs(svc._cfg["b_evict_enabled"], True)


# ---------------------------------------------------------------------------
# b_evict_clear 纯函数语义
# ---------------------------------------------------------------------------
class BEvictClearPureTest(unittest.TestCase):
    """W 空/严格超基准/基准容忍/rank1 恒幸存/窗界/归一/输入零改动。"""

    def test_w_empty_zero_change_identity(self):
        seq = [_hit(1, 0.9, "D", "1.1"), _hit(2, 0.8, "D", "1.2")]
        out, info = rag.b_evict_clear(seq, "无关题面不含判别词")
        self.assertIs(out, seq, "W 空=原样返回（同一对象=零拷贝零改动）")
        self.assertEqual(info, {"activated": False, "words": (), "base": None,
                                "evicted": 0})

    def test_empty_hits_passthrough(self):
        out, info = rag.b_evict_clear([], Q_EVICT)
        self.assertEqual(out, [])
        self.assertFalse(info["activated"])

    def test_strict_above_base_evicted_equal_survives(self):
        """n(b)>n1 才逐出；n(b)==n1 基准容忍幸存。"""
        seq = [_hit(1, 0.9, "D", "1.1", content=C_MISS1),   # rank1 n1=1
               _hit(2, 0.8, "D", "1.2", content=C_ALL),     # n=0 ≤1 幸存
               _hit(3, 0.7, "D", "1.3", content=C_MISS1),   # n=1 ==n1 幸存
               _hit(4, 0.6, "D", "1.4", content=C_MISS2),   # n=2 >1 逐出
               _hit(5, 0.5, "D", "1.5", content=C_MISS3)]   # n=3 >1 逐出
        out, info = rag.b_evict_clear(seq, Q_EVICT, topk=5, window=10)
        self.assertTrue(info["activated"])
        self.assertEqual(info["base"], 1)
        self.assertEqual(info["evicted"], 2)
        self.assertEqual([h["rec"]["id"] for h in out], ["D#1", "D#2", "D#3"])

    def test_rank1_always_survives_solo_seat(self):
        """全员超基准（除 rank1）→ 席位坍缩至 1，rank1 独席恒幸存。"""
        seq = ([_hit(1, 0.9, "D", "1.1", content=C_ALL)] +
               [_hit(i, 0.9 - i * 0.01, "D%d" % i, "%d.1" % i, content=C_MISS3)
                for i in range(2, 11)])
        out, info = rag.b_evict_clear(seq, Q_EVICT, topk=5, window=10)
        self.assertEqual(info["evicted"], 9)
        self.assertEqual([h["rec"]["id"] for h in out], ["D#1"])

    def test_window_bounds_only_first_n(self):
        """窗=前 max(topk,window) 位：窗外块不参与（不逐出也不入幸存序列）。"""
        seq = ([_hit(1, 0.99, "A", "1.1", content=C_ALL)] +
               [_hit(i, 0.9 - i * 0.01, "B%d" % i, "%d.1" % i, content=C_ALL)
                for i in range(2, 13)])
        seq.append(_hit(13, 0.5, "Z", "13.1", content=C_MISS3))  # 第 13 位窗外
        out, info = rag.b_evict_clear(seq, Q_EVICT, topk=5, window=10)
        self.assertEqual(len(out), 5)
        self.assertNotIn("Z#13", [h["rec"]["id"] for h in out])

    def test_promotion_from_deep_positions(self):
        """幸存者原序取前 topk：6 位及以后的幸存块晋位补席。"""
        seq = ([_hit(1, 0.99, "A", "1.1", content=C_ALL),      # n1=0
                _hit(2, 0.95, "B", "2.1", content=C_MISS3),    # 逐出
                _hit(3, 0.94, "B", "3.1", content=C_MISS1)] +  # 逐出
               [_hit(i, 0.9 - i * 0.02, "C", "%d.1" % i, content=C_ALL)
                for i in range(4, 11)])                        # 全幸存
        out, info = rag.b_evict_clear(seq, Q_EVICT, topk=5, window=10)
        self.assertEqual(info["evicted"], 2)
        self.assertEqual([h["rec"]["id"] for h in out],
                         ["A#1", "C#4", "C#5", "C#6", "C#7"])

    def test_ws_norm_ip_phone_variants(self):
        """归一=_ws_norm_text：题面"IP 电话"（带空格）命中块文"IP电话"。"""
        seq = [_hit(1, 0.9, "D", "1.1", content="IP电话 呼叫建立 成功 抖动"),
               _hit(2, 0.8, "D", "1.2", content="无线信道 指标")]
        out, info = rag.b_evict_clear(seq, "IP 电话的呼叫建立成功与抖动",
                                      topk=5, window=10)
        self.assertEqual(tuple(info["words"]),
                         ("IP电话", "呼叫建立", "成功", "抖动"))
        self.assertEqual([h["rec"]["id"] for h in out], ["D#1"])

    def test_missing_rec_treated_as_all_missing(self):
        """缺 rec 行按空文本=全缺词（不抛出；负项=|W|）。"""
        seq = [{"rank": 1, "score": 0.9,
                "rec": {"id": "D#1", "content": C_ALL, "doc_id": "D",
                        "locator": "1.1"}},
               {"rank": 2, "score": 0.8}]
        out, info = rag.b_evict_clear(seq, Q_EVICT, topk=5, window=10)
        self.assertEqual([h["rec"].get("id") if h.get("rec") else h["rank"]
                          for h in out], ["D#1"])
        self.assertEqual(info["evicted"], 1)

    def test_input_not_modified(self):
        seq = [_hit(1, 0.9, "D", "1.1", content=C_ALL),
               _hit(2, 0.8, "D", "1.2", content=C_MISS3)]
        snapshot = [dict(h) for h in seq]
        rag.b_evict_clear(seq, Q_EVICT, topk=5, window=10)
        self.assertEqual(seq, snapshot, "输入列表与元素零改动（rank 不重编）")


# ---------------------------------------------------------------------------
# evict 开态挂接（retrieve 链尾：折叠后、截 topk 前、闸门段前）
# ---------------------------------------------------------------------------
class EvictOnIntegrationTest(unittest.TestCase):
    """开态四支：激活/不激活/逐出（含晋位与席位坍缩）/rank1 幸存。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = os.path.join(self.tmp.name, "embeddings.jsonl")
        write_fixture(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def _svc(self, extra=None):
        cfg = {"store_path": self.store, "b_evict_enabled": True,
               "clause_family_rerank": False}      # 隔离乙层（evict 不依赖乙）
        cfg.update(extra or {})
        svc = rag.RagService(embed_fn=lambda q: list(QUERY), log=_Silent())
        svc.initialize(cfg)
        return svc

    def _evict_lines(self, svc):
        return [line for line in svc._log.lines if line.startswith("[rag-evict]")]

    def test_off_state_baseline_top5(self):
        """关态锚：现行余弦序 top5（本类夹具的行为基准）。"""
        svc = self._svc({"b_evict_enabled": False})
        _, sources = svc.retrieve(Q_EVICT)
        self.assertEqual([s["id"] for s in sources], EXPECTED_TOP5_OFF)
        self.assertEqual(self._evict_lines(svc), [])

    def test_activated_evicts_and_promotes_with_fold(self):
        """部署窗形态（折叠+evict 同开）：折叠序上逐出 e02/e04、e06/e07 晋位。"""
        svc = self._svc({"same_source_fold_enabled": True})
        evidence, sources = svc.retrieve(Q_EVICT)
        self.assertEqual([s["id"] for s in sources], EXPECTED_TOP5_EVICT_FOLD)
        self.assertNotIn("e02", [s["id"] for s in sources], "同族殿后+负项超基准双杀")
        self.assertNotIn("e04", [s["id"] for s in sources])
        for i, s in enumerate(sources, 1):
            self.assertIn("[出处%d]" % i, evidence)   # rank 重编 1..5
        # 打点：[rag-evict] q=<题面命中词> base=<n1> evicted=<n>（rag-fold 风格）
        self.assertTrue(any(re.match(
            r"\[rag-evict\] q=国内长途/呼叫建立/成功 base=0 evicted=2（", line)
            for line in self._evict_lines(svc)), svc._log.lines)
        self.assertTrue(any(line.startswith("[rag-fold]") for line in svc._log.lines))

    def test_activated_fold_off_shrinks_seats(self):
        """evict 单开（折叠关）：现行 topk 深度上逐出，席位如实缩减（无晋位面）。"""
        svc = self._svc()
        evidence, sources = svc.retrieve(Q_EVICT)
        self.assertEqual([s["id"] for s in sources], ["e01", "e03", "e05"])
        self.assertTrue(any(re.match(
            r"\[rag-evict\] q=国内长途/呼叫建立/成功 base=0 evicted=2（", line)
            for line in self._evict_lines(svc)))

    def test_not_activated_identical_and_no_log(self):
        """不激活支：题面零命中 → 结果与关态同构 + 无 [rag-evict] 行。"""
        q = "接入网参数配置是什么"
        svc_on = self._svc()
        svc_off = self._svc({"b_evict_enabled": False})
        _, src_on = svc_on.retrieve(q)
        _, src_off = svc_off.retrieve(q)
        self.assertEqual([s["id"] for s in src_on], [s["id"] for s in src_off])
        self.assertEqual(src_on, src_off)
        self.assertEqual(self._evict_lines(svc_on), [])

    def test_activated_zero_evicted_log_line_present(self):
        """激活≠逐出：全员不超基准 → 零逐出零换员，激活行仍打（evicted=0）。"""
        rows = [("f%02d" % i, "TS 38.%03d" % (i + 30), "%d.1 条" % i,
                 0.99 - i * 0.01, C_ALL) for i in range(1, 13)]
        write_fixture(os.path.join(self.tmp.name, "f2.jsonl"), rows)
        cfg = {"store_path": os.path.join(self.tmp.name, "f2.jsonl"),
               "b_evict_enabled": True, "clause_family_rerank": False}
        svc = rag.RagService(embed_fn=lambda q: list(QUERY), log=_Silent())
        svc.initialize(cfg)
        _, sources = svc.retrieve(Q_EVICT)
        self.assertEqual([s["id"] for s in sources],
                         [r[0] for r in rows[:5]], "零逐出=现行序原样")
        self.assertTrue(any(re.match(
            r"\[rag-evict\] q=国内长途/呼叫建立/成功 base=0 evicted=0（", line)
            for line in self._evict_lines(svc)))

    def test_rank1_solo_seat_survives(self):
        """rank1 恒幸存：全员超基准 → 幸存 1 席=rank1 独席（无空集路径）。"""
        rows = ([("g01", "TS 38.101", "4.1 条", 0.995, C_ALL)] +
                [("g%02d" % i, "TS 38.%03d" % (i + 40), "%d.1 条" % i,
                  0.99 - i * 0.01, C_MISS3) for i in range(2, 13)])
        write_fixture(os.path.join(self.tmp.name, "f3.jsonl"), rows)
        cfg = {"store_path": os.path.join(self.tmp.name, "f3.jsonl"),
               "b_evict_enabled": True, "clause_family_rerank": False,
               "same_source_fold_enabled": True}
        svc = rag.RagService(embed_fn=lambda q: list(QUERY), log=_Silent())
        svc.initialize(cfg)
        _, sources = svc.retrieve(Q_EVICT)
        self.assertEqual([s["id"] for s in sources], ["g01"])
        self.assertTrue(any(re.match(
            r"\[rag-evict\] q=国内长途/呼叫建立/成功 base=0 evicted=9（", line)
            for line in self._evict_lines(svc)))

    def test_base_tolerance_n1_equal_survives(self):
        """基准容忍：n1=1 时同负项数块（n=1）幸存、仅严格超基准（n≥2）逐出。"""
        rows = [
            ("h01", "TS 38.101", "4.1 条", 0.995, C_MISS1),   # rank1 n1=1
            ("h02", "TS 38.101", "4.2 条", 0.990, C_ALL),     # n=0 幸存
            ("h03", "TS 38.102", "4.3 条", 0.985, C_MISS1),   # n=1==n1 幸存
            ("h04", "TS 38.103", "4.4 条", 0.980, C_MISS2),   # n=2 逐出
            ("h05", "TS 38.104", "4.5 条", 0.975, C_ALL),     # n=0 幸存
        ] + [("h%02d" % i, "TS 38.%03d" % (i + 10), "%d.1 条" % i,
              0.97 - i * 0.01, C_MISS3) for i in range(6, 13)]
        write_fixture(os.path.join(self.tmp.name, "f4.jsonl"), rows)
        cfg = {"store_path": os.path.join(self.tmp.name, "f4.jsonl"),
               "b_evict_enabled": True, "clause_family_rerank": False,
               "same_source_fold_enabled": True}
        svc = rag.RagService(embed_fn=lambda q: list(QUERY), log=_Silent())
        svc.initialize(cfg)
        _, sources = svc.retrieve(Q_EVICT)
        self.assertEqual([s["id"] for s in sources],
                         ["h01", "h02", "h03", "h05"])
        self.assertTrue(any(re.match(
            r"\[rag-evict\] q=国内长途/呼叫建立/成功 base=1 evicted=\d+（", line)
            for line in self._evict_lines(svc)))

    def test_gate_cosine_not_lowered_below_rank1(self):
        """闸纪律：rank1 恒幸存 ⇒ 证据集最大余弦 ≥ cos(rank1)（0.40 闸零新增触发）。"""
        svc = self._svc({"same_source_fold_enabled": True})
        hits10 = svc._search_one(Q_EVICT, QUERY)
        folded, _ = rag.same_source_fold1(hits10)
        out, info = rag.b_evict_clear(folded, Q_EVICT, topk=5, window=10)
        self.assertGreaterEqual(rag.gate_cosine(out),
                                rag.gate_cosine(folded[:1]))


# ---------------------------------------------------------------------------
# 表降权白名单（decrowd_rescore ②表因子分支）
# ---------------------------------------------------------------------------
class WhitelistDecrowdTest(unittest.TestCase):
    """三支：命中豁免/不命中照降/默认空；锚定语义+坏正则+③不受影响。"""

    def _params(self, **over):
        cfg = {"table_downweight_enabled": True, "table_downweight_scope": "all"}
        cfg.update({k: v for k, v in over.items() if k != "hits"})
        return rag.clean_decrowd_params(cfg)

    def test_whitelist_hit_exempt(self):
        """命中豁免：locator 命中白名单正则 → 不乘表因子（score/无 factor 键）。"""
        hits = [_hit(1, 0.90, "TS 38.133", "5.6 Table 5.6-1 行组2-3"),
                _hit(2, 0.88, "TS 38.133", "Annex A.2")]
        p = self._params(table_downweight_whitelist=["5\\.6 Table 5\\.6-1"])
        out, info = rag.decrowd_rescore("q", hits, p)
        self.assertEqual(info["table_n"], 1)          # 只降了 Annex 块
        self.assertEqual(out[0]["score"], 0.90)       # 豁免块原分
        self.assertNotIn("decrowd_factor", out[0])
        self.assertAlmostEqual(out[1]["score"], 0.88 * 0.85)
        self.assertEqual(out[1]["decrowd_factor"], 0.85)
        self.assertEqual(out[0]["cosine"], 0.90)      # 闸载体照挂

    def test_whitelist_miss_still_downweighted(self):
        """不命中照降：白名单在位但 locator 不匹配 → 全部目标块照乘表因子。"""
        hits = [_hit(1, 0.90, "TS 38.133", "5.6 Table 5.6F-1"),  # 相邻表号不中
                _hit(2, 0.88, "TS 38.133", "Annex A.2")]
        p = self._params(table_downweight_whitelist=["5\\.6 Table 5\\.6-1"])
        out, info = rag.decrowd_rescore("q", hits, p)
        self.assertEqual(info["table_n"], 2)
        self.assertAlmostEqual(out[0]["score"], 0.90 * 0.85)
        self.assertAlmostEqual(out[1]["score"], 0.88 * 0.85)

    def test_default_empty_all_downweighted(self):
        """默认空：白名单 []（默认值）→ 目标块全降。"""
        hits = [_hit(1, 0.90, "TS 38.133", "5.6 Table 5.6-1"),
                _hit(2, 0.88, "TS 38.133", "Annex A.2")]
        for wl in ([], None, "not-a-list"):
            p = self._params(table_downweight_whitelist=wl)
            out, info = rag.decrowd_rescore("q", hits, p)
            self.assertEqual(info["table_n"], 2, wl)
            self.assertAlmostEqual(out[0]["score"], 0.90 * 0.85)
            self.assertAlmostEqual(out[1]["score"], 0.88 * 0.85)

    def test_anchor_caret_semantics(self):
        """锚定值语义：^7\\.2.3  只豁免 locator 起始块（re.search+^ 锚）。"""
        hits = [_hit(1, 0.90, "TS 36.101", "7.2.3 表"),
                _hit(2, 0.88, "TS 36.101", "x7.2.3 表"),
                _hit(3, 0.86, "TS 36.101", "5.6 Table 5.6-1")]
        p = rag.clean_decrowd_params({
            "table_downweight_enabled": True,
            "table_downweight_docs": ["36.101"],
            "table_downweight_scope": "all",
            "table_downweight_whitelist": ["5\\.6 Table 5\\.6-1", "^7\\.2\\.3 "]})
        out, info = rag.decrowd_rescore("q", hits, p)
        self.assertEqual(info["table_n"], 1)          # 只有 x7.2.3 被降
        # 降权后重排：0.90（豁免）> 0.86（豁免）> 0.88×0.85（x7.2.3）
        self.assertEqual(out[0]["score"], 0.90)       # ^7.2.3 豁免
        self.assertEqual(out[0]["rec"]["locator"], "7.2.3 表")
        self.assertEqual(out[1]["score"], 0.86)       # 5.6 Table 豁免
        self.assertEqual(out[1]["rec"]["locator"], "5.6 Table 5.6-1")
        self.assertAlmostEqual(
            next(h["score"] for h in out
                 if h["rec"]["locator"] == "x7.2.3 表"), 0.88 * 0.85)

    def test_spec_suppress_unaffected_for_whitelisted(self):
        """③制式不受影响：白名单块跳过 ②表因子但 ③压制照乘（连乘只豁免 ②）。"""
        hits = [_hit(1, 0.90, "TS 36.101", "7.2.3 表"),
                _hit(2, 0.88, "TS 36.101", "9.1 表")]
        p = rag.clean_decrowd_params({
            "table_downweight_enabled": True, "spec_suppress_enabled": True,
            "table_downweight_docs": ["36.101"], "table_downweight_scope": "all",
            "table_downweight_whitelist": ["^7\\.2\\.3 "]})
        out, info = rag.decrowd_rescore("nr 的参数是多少", hits, p)
        self.assertEqual(info["table_n"], 1)
        self.assertEqual(info["spec_n"], 2)           # 两块都被 ③ 压
        self.assertAlmostEqual(out[0]["score"], 0.90 * 0.85)  # 只乘 spec
        self.assertAlmostEqual(out[1]["score"], 0.88 * 0.85 * 0.85)  # ②③连乘
        self.assertEqual(out[0]["decrowd_factor"], 0.85)
        self.assertEqual(out[1]["decrowd_factor"], round(0.85 * 0.85, 6))

    def test_bad_regex_dropped_good_kept(self):
        """坏正则单条丢弃不整组回退。"""
        p = rag.clean_decrowd_params({
            "table_downweight_whitelist": ["bad[", "(", "  ", "5\\.6 Table"]})
        self.assertEqual(len(p["table_whitelist"]), 1)
        with tempfile.TemporaryDirectory() as td:
            store = os.path.join(td, "e.jsonl")
            write_fixture(store)
            svc = rag.RagService(embed_fn=lambda q: list(QUERY), log=_Silent())
            svc.initialize({"store_path": store,
                            "table_downweight_whitelist": ["bad[", "^7\\.2\\.3 "]})
            self.assertEqual(len(svc._decrowd["table_whitelist"]), 1)


if __name__ == "__main__":
    unittest.main()
