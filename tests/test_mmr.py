# -*- coding: utf-8 -*-
"""MMR 向量去冗余（mmr_enabled/mmr_lambda，检索链尾键，波3 工程件
2026-10-23 施工）离线单测。

对象=rag.py：clean_mmr_params 键清洗（缺键/非法值回 false/0.7，仅严格布尔
true 开）、_mmr_rel/_mmr_pair_sim（相关性=原始余弦提取面/块间余弦归一与
防御态）、mmr_reorder 纯函数（order-only 同集合置换：λ 加权贪心选席/首取
相关性最高 tie 原位次/rank 重编+独立 mmr_rank 键/cosine/score 逐字节不动/
输入零修改/确定性）、挂接面（retrieve 链尾=乙重排+同源折叠+B-evict 全部
治理键生效后的终 topk 截断面之后、闸门段之前——只动终 top-k 内部次序，
成员集合恒等；折叠殿后者不可复活）。

覆盖面（任务书四要件）：
① 关态逐字节一致——配置三形（缺键/false/非法值）与 bm25s 持久化新路径
  （bm25_persist False/True）共存下 evidence/sources 逐字节相同，零
  [rag-mmr] 行；
② 开态近重复候选让位——c1/c2 高相似双块（块间余弦 0.834 vs 其余 ~0.5），
  λ=0.7 下 c2 从第 2 席让位至第 5 席（c3/c4/c5 晋位），成员集合恒等、
  per-id cosine/score 载体值逐字节不变；
③ λ 边界退化态——1.0=纯相关性稳定序（纯余弦态恒等置换 moved=0）、
  0.0=纯多样性贪心（首取仍首位，此后取与已选集最不相似者）；
④ 空/单候选——mmr_reorder([])/单条原样返回（不拷贝不附键）；单块库
  retrieve 正常。

零网络（stub embed_fn）、8 维夹具（真实库 1024 维，逻辑与维度无关）；
夹具向量数值与期望序已离线验算登记（施工报告 §三）。
跑法（tests/ 惯例）：仓根起 venv/bin/python -m pytest tests/test_mmr.py。
"""
import json
import math
import os
import tempfile
import unittest

import rag

QUERY = [1, 0, 0, 0, 0, 0, 0, 0]

# 7 块 8 维夹具：对 QUERY 余弦严格降序（rank=余弦序）；c1/c2 同平面（承载
# 分量同在 dim1）=高相似双块（块间余弦 0.833992），c3-c7 各占独立正交维
# （与 c1 块间余弦=两者查询余弦之积 0.33-0.52）。查询余弦：
# c1=0.95 / c2=0.62 / c3=0.55 / c4=0.53 / c5=0.51 / c6=0.40 / c7=0.35。
# λ=0.7 期望终序（验算在案）：[c1, c3, c4, c5, c2, c6, c7]（c2 让位至 5，
# moved=4）；λ=1.0 恒等；λ=0.0 纯多样性 [c1, c7, c6, c5, c4, c3, c2]。
FIXTURE = [
    # (id, doc_id, locator, embedding)
    ("c1", "D1", "表A (p1)", [0.95, 0.31224990, 0, 0, 0, 0, 0, 0]),
    ("c2", "D1", "表A (p2)", [0.62, 0.78460181, 0, 0, 0, 0, 0, 0]),
    ("c3", "D3", "条C", [0.55, 0, 0.83516465, 0, 0, 0, 0, 0]),
    ("c4", "D4", "表D", [0.53, 0, 0, 0.84799764, 0, 0, 0, 0]),
    ("c5", "D5", "条E", [0.51, 0, 0, 0, 0.86017440, 0, 0, 0]),
    ("c6", "D6", "表F", [0.40, 0, 0, 0, 0, 0.91651514, 0, 0]),
    ("c7", "D7", "条G", [0.35, 0, 0, 0, 0, 0, 0.93674970, 0]),
]
EXPECTED_OFF = ["c1", "c2", "c3", "c4", "c5"]          # 关态=现行余弦序
EXPECTED_ON_07 = ["c1", "c3", "c4", "c5", "c2"]        # λ=0.7 让位后
EXPECTED_ON_00 = ["c1", "c5", "c4", "c3", "c2"]        # λ=0.0（top5 内纯多样性）
# 正交无近重复布局（moved=0 用例）：全独立维，λ=0.7 恒等
ORTHO = [
    ("o1", "E1", "条1", [0.95, 0.31224990, 0, 0, 0, 0, 0, 0]),
    ("o2", "E2", "条2", [0.90, 0, 0.43588989, 0, 0, 0, 0, 0]),
    ("o3", "E3", "条3", [0.85, 0, 0, 0.52678269, 0, 0, 0, 0]),
    ("o4", "E4", "条4", [0.80, 0, 0, 0, 0.6, 0, 0, 0]),
    ("o5", "E5", "条5", [0.75, 0, 0, 0, 0, 0.66143783, 0, 0]),
]

# 题面用词避开乙层词表（CLAUSE_RERANK_WORDS_*）与丙层词表
# （COVER_GATE_VOCAB），保 乙层 negs=0/父条缺席=identity 重排、覆盖闸不触发
PROBE_QUERY = "近重复让位探针"


def write_fixture(path, rows=FIXTURE):
    """写合法记录到 jsonl（向量按原样落盘，load_store 装载期归一）。"""
    with open(path, "w", encoding="utf-8") as f:
        for cid, doc, loc, emb in rows:
            f.write(json.dumps(
                {"id": cid, "content": f"{PROBE_QUERY}内容{cid}（{doc} {loc}）",
                 "doc_id": doc, "version": "V1", "locator": loc,
                 "embedding": emb}, ensure_ascii=False) + "\n")


def _hit(rank, cid, score, vec):
    """通道形态 hit（rank/score/rec），rec 带既有归一向量（rec["vec"]）。"""
    return {"rank": rank, "score": score,
            "rec": {"id": cid, "doc_id": "D", "version": "V", "locator": cid,
                    "content": f"内容{cid}", "vec": vec}}


def _fixture_hits():
    """夹具 7 块 → 通道形态 hits（纯余弦态：score=查询余弦，无 cosine 键）。"""
    q = dict((r[0], r[3]) for r in FIXTURE)
    return [_hit(i, r[0], float(r[3][0]), q[r[0]])
            for i, r in enumerate(FIXTURE, 1)]


class _Silent:
    """日志收集器（断言 [rag-mmr] 观测行用）。"""

    def __init__(self):
        self.lines = []

    def __call__(self, line):
        self.lines.append(line)

    def mmr(self):
        return [ln for ln in self.lines if ln.startswith("[rag-mmr]")]


# ---------------------------------------------------------------------------
# 键清洗与配置装载
# ---------------------------------------------------------------------------
class CleanMmrParamsTest(unittest.TestCase):
    """缺键/非法值回关+默认 λ；仅严格布尔 true 开；λ ∈[0,1] 含边界。"""

    def test_default_off(self):
        """直通键：不入 DEFAULT_RAG_CONFIG（键面守卫钉死键增量，口径贴
        tests/test_bm25_persist.py 的 bm25_persist 同款先例），缺省即关。"""
        self.assertNotIn("mmr_enabled", rag.DEFAULT_RAG_CONFIG)
        self.assertNotIn("mmr_lambda", rag.DEFAULT_RAG_CONFIG)

    def test_missing_key_off(self):
        self.assertEqual(rag.clean_mmr_params({}),
                         {"enabled": False, "lam": 0.7})
        self.assertEqual(rag.clean_mmr_params(None),
                         {"enabled": False, "lam": 0.7})

    def test_illegal_enabled_off(self):
        for bad in ("true", "yes", 1, 0, [True], {"enabled": True}, "是"):
            p = rag.clean_mmr_params({"mmr_enabled": bad})
            self.assertIs(p["enabled"], False, bad)

    def test_strict_true_on(self):
        self.assertIs(rag.clean_mmr_params({"mmr_enabled": True})["enabled"],
                      True)

    def test_lambda_bounds_and_bad_values(self):
        for good in (0.0, 1.0, 0.7, 0.5):
            self.assertEqual(
                rag.clean_mmr_params({"mmr_lambda": good})["lam"], good)
        for bad in (None, "x", float("nan"), float("inf"), 1.5, -0.1, [0.7]):
            self.assertEqual(
                rag.clean_mmr_params({"mmr_lambda": bad})["lam"], 0.7, bad)

    def test_initialize_normalizes_and_init_default(self):
        with tempfile.TemporaryDirectory() as td:
            store = os.path.join(td, "embeddings.jsonl")
            write_fixture(store)
            svc = rag.RagService(embed_fn=lambda q: list(QUERY))
            self.assertIs(svc._mmr["enabled"], False)      # __init__ 默认关
            self.assertEqual(svc._mmr["lam"], 0.7)
            svc.initialize({"store_path": store,
                            "mmr_enabled": "true", "mmr_lambda": 9})
            self.assertIs(svc._mmr["enabled"], False)      # 非法值回 false
            self.assertEqual(svc._mmr["lam"], 0.7)
            self.assertIs(svc._cfg["mmr_enabled"], False)
            self.assertEqual(svc._cfg["mmr_lambda"], 0.7)
            svc.initialize({"store_path": store, "mmr_enabled": True,
                            "mmr_lambda": 0.0})
            self.assertIs(svc._mmr["enabled"], True)
            self.assertEqual(svc._mmr["lam"], 0.0)         # 边界 0.0 合法
            self.assertIs(svc._cfg["mmr_enabled"], True)
            self.assertEqual(svc._cfg["mmr_lambda"], 0.0)


# ---------------------------------------------------------------------------
# 纯函数：_mmr_pair_sim / _mmr_rel
# ---------------------------------------------------------------------------
class MmrPairSimTest(unittest.TestCase):
    """块间余弦：未归一向量得真余弦；缺 vec/维度不符/零向量 → 0.0 不抛。"""

    def test_unnormalized_true_cosine(self):
        s = rag._mmr_pair_sim({"vec": [3.0, 4.0]}, {"vec": [4.0, 3.0]})
        self.assertAlmostEqual(s, 24.0 / 25.0, places=12)

    def test_unit_vectors_dot(self):
        v = FIXTURE[0][3]
        self.assertAlmostEqual(rag._mmr_pair_sim({"vec": v}, {"vec": v}),
                               1.0, places=6)

    def test_missing_or_bad_vec_zero(self):
        self.assertEqual(rag._mmr_pair_sim({}, {"vec": [1.0, 0.0]}), 0.0)
        self.assertEqual(rag._mmr_pair_sim(None, {"vec": [1.0, 0.0]}), 0.0)
        self.assertEqual(rag._mmr_pair_sim({"vec": None}, {"vec": [1.0]}), 0.0)
        self.assertEqual(rag._mmr_pair_sim({"vec": "ab"}, {"vec": [1.0]}), 0.0)
        # 维度不符/零向量：保守向 0.0（无向量证据=不惩罚）
        self.assertEqual(rag._mmr_pair_sim({"vec": [1.0, 0.0]},
                                           {"vec": [1.0, 0.0, 0.0]}), 0.0)
        self.assertEqual(rag._mmr_pair_sim({"vec": [0.0, 0.0]},
                                           {"vec": [1.0, 0.0]}), 0.0)
        self.assertEqual(rag._mmr_pair_sim({"vec": []}, {"vec": []}), 0.0)

    def test_fixture_dup_pair_is_high_similarity(self):
        """夹具自证：c1-c2 块间余弦 0.834，远高于 c1 与正交维块（≤0.5225）。"""
        s12 = rag._mmr_pair_sim({"vec": FIXTURE[0][3]}, {"vec": FIXTURE[1][3]})
        self.assertAlmostEqual(s12, 0.833992, places=5)
        for i in (2, 3, 4, 5, 6):
            s1i = rag._mmr_pair_sim({"vec": FIXTURE[0][3]},
                                    {"vec": FIXTURE[i][3]})
            self.assertLess(s1i, 0.53)
            self.assertLess(s1i, s12)


class MmrRelTest(unittest.TestCase):
    """相关性提取面=gate_cosine 同款：cosine 键优先、缺则 score、坏值 0.0。"""

    def test_cosine_key_preferred(self):
        self.assertEqual(rag._mmr_rel({"cosine": 0.8, "score": 0.03}), 0.8)

    def test_fallback_score(self):
        self.assertEqual(rag._mmr_rel({"score": 0.42}), 0.42)

    def test_bad_values_zero(self):
        for h in ({}, {"cosine": None, "score": 0.03},
                  {"cosine": "x"}, {"score": float("nan")},
                  {"cosine": True, "score": 0.5}):
            self.assertEqual(rag._mmr_rel(h), 0.0, h)


# ---------------------------------------------------------------------------
# 纯函数：mmr_reorder
# ---------------------------------------------------------------------------
class MmrReorderPureTest(unittest.TestCase):
    """选席迭代/边界退化/载体纪律/确定性/输入零修改。"""

    def test_empty_and_single_unchanged(self):
        self.assertEqual(rag.mmr_reorder([]), ([], {"n": 0, "moved": 0,
                                                    "perm": []}))
        seq = _fixture_hits()[:1]
        out, info = rag.mmr_reorder(seq)
        self.assertIs(out, seq)                    # 原样返回（同对象，未拷贝）
        self.assertEqual(info, {"n": 1, "moved": 0, "perm": [0]})

    def test_dup_yields_seat_at_default_lambda(self):
        """近重复让位：c2 从第 2 席让位至第 5 席（c3/c4/c5 晋位）。"""
        out, info = rag.mmr_reorder(_fixture_hits(), 0.7)
        self.assertEqual([h["rec"]["id"] for h in out],
                         ["c1", "c3", "c4", "c5", "c2", "c6", "c7"])
        self.assertEqual(info["n"], 7)
        self.assertEqual(info["moved"], 4)         # 第 2-5 席全部换位
        self.assertEqual(info["perm"], [0, 2, 3, 4, 1, 5, 6])

    def test_lambda_1_identity_on_cosine_sorted(self):
        """λ=1 退化=纯相关性稳定序；纯余弦态列表已按 score 降序 ⇒ 恒等置换。"""
        out, info = rag.mmr_reorder(_fixture_hits(), 1.0)
        self.assertEqual([h["rec"]["id"] for h in out],
                         ["c1", "c2", "c3", "c4", "c5", "c6", "c7"])
        self.assertEqual(info["moved"], 0)
        self.assertEqual(info["perm"], list(range(7)))

    def test_lambda_0_pure_diversity(self):
        """λ=0 退化=纯多样性贪心：首取仍相关性首位，此后取与已选集最不相似。"""
        out, info = rag.mmr_reorder(_fixture_hits(), 0.0)
        self.assertEqual([h["rec"]["id"] for h in out],
                         ["c1", "c7", "c6", "c5", "c4", "c3", "c2"])
        self.assertEqual(info["moved"], 6)

    def test_rank_renumbered_and_mmr_rank_attached(self):
        """rank 按 MMR 终序重编 1..n（[出处N] 编号位）；另附独立 mmr_rank
        选席序键（与重编 rank 数值恒同=纯观测面）。"""
        out, _ = rag.mmr_reorder(_fixture_hits(), 0.7)
        self.assertEqual([h["rank"] for h in out], list(range(1, 8)))
        self.assertEqual([h["mmr_rank"] for h in out], list(range(1, 8)))

    def test_set_permutation_and_carriers_byte_identical(self):
        """同集合置换 + 闸分载体纪律：cosine/score 逐元素逐字节不变。"""
        seq = _fixture_hits()
        before = json.dumps([(h["rec"]["id"], h["score"], h.get("cosine"))
                             for h in seq], sort_keys=False)
        out, _ = rag.mmr_reorder(seq, 0.7)
        after = json.dumps([(h["rec"]["id"], h["score"], h.get("cosine"))
                            for h in out], sort_keys=False)
        self.assertEqual(sorted(json.loads(after), key=lambda t: t[0]),
                         sorted(json.loads(before), key=lambda t: t[0]),
                         "per-id (score, cosine) 载体逐字节不变")
        self.assertEqual(sorted(h["rec"]["id"] for h in out),
                         sorted(h["rec"]["id"] for h in seq), "同集合置换")

    def test_gate_cosine_unchanged(self):
        """闸门读数不变：gate_cosine 取集内最大原始余弦，重排后恒等。"""
        seq = _fixture_hits()
        out, _ = rag.mmr_reorder(seq, 0.7)
        self.assertEqual(rag.gate_cosine(out), rag.gate_cosine(seq))

    def test_input_not_modified(self):
        seq = _fixture_hits()
        snapshot = [dict(h) for h in seq]
        rag.mmr_reorder(seq, 0.7)
        self.assertEqual(seq, snapshot, "输入列表与元素零修改")

    def test_deterministic_and_bad_lam_fallback(self):
        seq = _fixture_hits()
        out1, _ = rag.mmr_reorder(seq, 0.7)
        out2, _ = rag.mmr_reorder(seq, 0.7)
        self.assertEqual([h["rec"]["id"] for h in out1],
                         [h["rec"]["id"] for h in out2])
        # 直调坏 λ（清洗面已钳，防御位回默认 0.7）与 NaN 钳界
        out_bad, _ = rag.mmr_reorder(seq, "x")
        self.assertEqual([h["rec"]["id"] for h in out_bad],
                         [h["rec"]["id"] for h in out1])
        out_nan, _ = rag.mmr_reorder(seq, float("nan"))
        self.assertEqual([h["rec"]["id"] for h in out_nan],
                         [h["rec"]["id"] for h in out1])

    def test_orthogonal_no_move(self):
        """正交无近重复布局：λ=0.7 恒等（moved=0，纯函数仍附键重编）。"""
        hits = [_hit(i, r[0], float(r[3][0]), r[3])
                for i, r in enumerate(ORTHO, 1)]
        out, info = rag.mmr_reorder(hits, 0.7)
        self.assertEqual([h["rec"]["id"] for h in out],
                         ["o1", "o2", "o3", "o4", "o5"])
        self.assertEqual(info["moved"], 0)

    def test_fused_scale_state_uses_cosine_relevance(self):
        """hybrid/mq 态（cosine 键在场、fused score ~1e-2 量级）：相关性取
        原始余弦（gate_cosine 同款面）——λ 语义在融合态同有效，近重复仍让位
        且首取=最高原始余弦块（非 fused 最高者）。"""
        q = dict((r[0], r[3]) for r in FIXTURE)
        hits = []
        for i, r in enumerate(FIXTURE[:5], 1):
            hits.append({"rank": i,
                         "score": 0.02 - i * 0.001,   # fused 序与余弦序相反
                         "cosine": float(r[3][0]),
                         "rec": {"id": r[0], "doc_id": "D", "version": "V",
                                 "locator": r[2], "content": "内容",
                                 "vec": q[r[0]]}})
        out, info = rag.mmr_reorder(hits, 0.7)
        self.assertEqual([h["rec"]["id"] for h in out],
                         ["c1", "c3", "c4", "c5", "c2"])
        self.assertGreater(info["moved"], 0)
        self.assertEqual(out[0]["rec"]["id"], "c1")  # 首取=最高原始余弦

    def test_missing_vec_still_order_only(self):
        """缺 vec 块（防御态：相似度恒 0=不惩罚）仍参与选席，集合恒等不抛。"""
        hits = _fixture_hits()
        for h in hits:
            h["rec"] = {k: v for k, v in h["rec"].items() if k != "vec"}
        out, info = rag.mmr_reorder(hits, 0.7)
        self.assertEqual(sorted(h["rec"]["id"] for h in out),
                         sorted(h["rec"]["id"] for h in hits))


# ---------------------------------------------------------------------------
# 服务级：关态逐字节一致（含 bm25s 持久化新路径共存）
# ---------------------------------------------------------------------------
class MmrOffEquivalenceTest(unittest.TestCase):
    """关态零触碰：配置三形（缺键/false/非法值）evidence/sources 逐字节
    相同=现行排序，零 [rag-mmr] 行。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = os.path.join(self.tmp.name, "embeddings.jsonl")
        write_fixture(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def _svc(self, extra=None):
        log = _Silent()
        cfg = {"store_path": self.store}
        cfg.update(extra or {})
        svc = rag.RagService(embed_fn=lambda q: list(QUERY), log=log)
        svc.initialize(cfg)
        return svc, log

    def test_off_returns_plain_top5(self):
        svc, log = self._svc()
        out = svc.retrieve(PROBE_QUERY)
        self.assertIsNotNone(out)
        evidence, sources = out
        self.assertEqual([s["id"] for s in sources], EXPECTED_OFF)
        self.assertIn("[出处5]", evidence)
        self.assertEqual(log.mmr(), [], "关态零 [rag-mmr] 行")

    def test_off_config_variants_byte_identical(self):
        outs = []
        for extra in (None, {"mmr_enabled": False},
                      {"mmr_enabled": "true", "mmr_lambda": 0.1}):
            svc, log = self._svc(extra)
            out = svc.retrieve(PROBE_QUERY)
            self.assertIsNotNone(out)
            outs.append(out)
            self.assertEqual(log.mmr(), [])
        self.assertEqual(outs[0], outs[1])
        self.assertEqual(outs[0], outs[2])


class MmrOffBm25PersistCoexistTest(unittest.TestCase):
    """关态与 bm25s 持久化新路径共存：hybrid_bm25 开（RRF 融合态）+
    bm25_persist False/True（新路径存/取）组合下 evidence/sources 逐字节
    相同、零 [rag-mmr] 行——MMR 关态对今日并入的持久化路径零干扰。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = os.path.join(self.tmp.name, "embeddings.jsonl")
        write_fixture(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def _svc(self, extra=None):
        log = _Silent()
        cfg = {"store_path": self.store, "hybrid_bm25_enabled": True}
        cfg.update(extra or {})
        svc = rag.RagService(embed_fn=lambda q: list(QUERY), log=log)
        svc.initialize(cfg)
        return svc, log

    def test_off_identical_across_persist_paths(self):
        base, log0 = self._svc()                       # 无 persist 键=旧路径
        out0 = base.retrieve(PROBE_QUERY)
        self.assertIsNotNone(out0)
        self.assertEqual(log0.mmr(), [])
        svc1, log1 = self._svc({"bm25_persist": True})  # 新路径（首跑=落盘）
        out1 = svc1.retrieve(PROBE_QUERY)
        svc2, log2 = self._svc({"bm25_persist": True})  # 新路径（二跑=取缓存）
        out2 = svc2.retrieve(PROBE_QUERY)
        self.assertEqual(out0, out1, "persist 关/开逐字节一致")
        self.assertEqual(out0, out2, "persist 落盘/取缓存逐字节一致")
        self.assertEqual(log1.mmr(), [])
        self.assertEqual(log2.mmr(), [])

    def test_on_membership_and_carriers_unchanged(self):
        """开态在 hybrid 融合态下：成员集合恒等 + per-id sources score 载体
        逐字节不变（build_evidence score=round(hit.score,6)）。"""
        off, _ = self._svc()
        out_off = off.retrieve(PROBE_QUERY)
        on, log = self._svc({"mmr_enabled": True})
        out_on = on.retrieve(PROBE_QUERY)
        self.assertIsNotNone(out_off)
        self.assertIsNotNone(out_on)
        s_off = {s["id"]: s["score"] for s in out_off[1]}
        s_on = {s["id"]: s["score"] for s in out_on[1]}
        self.assertEqual(sorted(s_off), sorted(s_on), "成员集合恒等")
        self.assertEqual(s_off, s_on, "per-id score 载体逐字节不变")


# ---------------------------------------------------------------------------
# 服务级：开态效果
# ---------------------------------------------------------------------------
class MmrOnServiceTest(unittest.TestCase):
    """开态：近重复让位 + 观测行 + 载体不变 + λ 边界服务级。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = os.path.join(self.tmp.name, "embeddings.jsonl")
        write_fixture(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def _svc(self, extra=None):
        log = _Silent()
        cfg = {"store_path": self.store}
        cfg.update(extra or {})
        svc = rag.RagService(embed_fn=lambda q: list(QUERY), log=log)
        svc.initialize(cfg)
        return svc, log

    def test_dup_yields_seat_in_sources(self):
        svc, log = self._svc({"mmr_enabled": True})
        out = svc.retrieve(PROBE_QUERY)
        self.assertIsNotNone(out)
        evidence, sources = out
        self.assertEqual([s["id"] for s in sources], EXPECTED_ON_07)
        # 闸门通过（未落 low_score/coverage_miss）且出处编号 1..5 连续在位
        self.assertIn("[出处5]", evidence)
        self.assertIn("（MMR 去冗余", "".join(log.mmr()))
        self.assertTrue(any("moved=4" in ln for ln in log.mmr()),
                        log.mmr())

    def test_membership_and_gate_carriers_identical_to_off(self):
        off, log_off = self._svc()
        on, log_on = self._svc({"mmr_enabled": True})
        out_off = off.retrieve(PROBE_QUERY)
        out_on = on.retrieve(PROBE_QUERY)
        s_off = {s["id"]: s["score"] for s in out_off[1]}
        s_on = {s["id"]: s["score"] for s in out_on[1]}
        self.assertEqual(sorted(s_off), sorted(s_on), "成员集合恒等")
        self.assertEqual(s_off, s_on, "per-id score 逐字节不变（闸分载体）")
        self.assertEqual(log_off.mmr(), [])

    def test_lambda_1_service_identity(self):
        svc, log = self._svc({"mmr_enabled": True, "mmr_lambda": 1.0})
        out = svc.retrieve(PROBE_QUERY)
        self.assertEqual([s["id"] for s in out[1]], EXPECTED_OFF)
        self.assertEqual(log.mmr(), [], "恒等置换 moved=0 零打点")

    def test_lambda_0_service_pure_diversity(self):
        svc, _ = self._svc({"mmr_enabled": True, "mmr_lambda": 0.0})
        out = svc.retrieve(PROBE_QUERY)
        self.assertEqual([s["id"] for s in out[1]], EXPECTED_ON_00)

    def test_no_move_layout_zero_log(self):
        """正交布局（无近重复）：λ=0.7 恒等=moved=0 零打点，sources 原序。"""
        store = os.path.join(self.tmp.name, "ortho.jsonl")
        write_fixture(store, ORTHO)
        log = _Silent()
        svc = rag.RagService(embed_fn=lambda q: list(QUERY), log=log)
        svc.initialize({"store_path": store, "mmr_enabled": True})
        out = svc.retrieve(PROBE_QUERY)
        self.assertEqual([s["id"] for s in out[1]],
                         ["o1", "o2", "o3", "o4", "o5"])
        self.assertEqual(log.mmr(), [])


# ---------------------------------------------------------------------------
# 服务级：与同源折叠共存（不可复活纪律）+ 单块库
# ---------------------------------------------------------------------------
class MmrFoldCoexistTest(unittest.TestCase):
    """折叠+MMR 同开：折叠殿后者（c2 同族表A）不可借 MMR 复活——成员集合
    =折叠单开态恒等，MMR 只在折叠幸存者内部动次序。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = os.path.join(self.tmp.name, "embeddings.jsonl")
        write_fixture(self.store)     # c1/c2 同 doc D1 同族 locator 表A

    def tearDown(self):
        self.tmp.cleanup()

    def _svc(self, extra=None):
        log = _Silent()
        cfg = {"store_path": self.store, "same_source_fold_enabled": True}
        cfg.update(extra or {})
        svc = rag.RagService(embed_fn=lambda q: list(QUERY), log=log)
        svc.initialize(cfg)
        return svc, log

    def test_folded_member_never_resurrected(self):
        fold_only, log_f = self._svc()
        out_f = fold_only.retrieve(PROBE_QUERY)
        self.assertIsNotNone(out_f)
        ids_f = [s["id"] for s in out_f[1]]
        self.assertNotIn("c2", ids_f)                 # 折叠殿后出 top5
        both, log_b = self._svc({"mmr_enabled": True})
        out_b = both.retrieve(PROBE_QUERY)
        ids_b = [s["id"] for s in out_b[1]]
        self.assertNotIn("c2", ids_b, "MMR 不可复活折叠殿后者")
        self.assertEqual(sorted(ids_b), sorted(ids_f), "成员集合=折叠态恒等")
        # 本布局（幸存者全正交维）MMR 恒等：次序亦与折叠单开一致
        self.assertEqual(ids_b, ids_f)
        scores_f = {s["id"]: s["score"] for s in out_f[1]}
        scores_b = {s["id"]: s["score"] for s in out_b[1]}
        self.assertEqual(scores_f, scores_b, "per-id score 逐字节不变")


class MmrSingleBlockStoreTest(unittest.TestCase):
    """空/单候选：单块库开态 retrieve 正常（len≤1 早退，零 MMR 面）。"""

    def test_single_block_store(self):
        with tempfile.TemporaryDirectory() as td:
            store = os.path.join(td, "embeddings.jsonl")
            write_fixture(store, FIXTURE[:1])
            log = _Silent()
            svc = rag.RagService(embed_fn=lambda q: list(QUERY), log=log)
            svc.initialize({"store_path": store, "mmr_enabled": True})
            out = svc.retrieve(PROBE_QUERY)
            self.assertIsNotNone(out)
            self.assertEqual([s["id"] for s in out[1]], ["c1"])
            self.assertEqual(log.mmr(), [])

    def test_empty_store_miss(self):
        with tempfile.TemporaryDirectory() as td:
            store = os.path.join(td, "embeddings.jsonl")
            log = _Silent()
            svc = rag.RagService(embed_fn=lambda q: list(QUERY), log=log)
            svc.initialize({"store_path": store, "mmr_enabled": True})
            self.assertIsNone(svc.retrieve(PROBE_QUERY))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
