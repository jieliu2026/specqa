# -*- coding: utf-8 -*-
"""rag.py BM25 索引持久化（波3 工程件 2026-10-23）离线单测：默认关态行为
不变/开态落盘与二次装载命中/索引逐位等价/校验失败回退/损坏与恶意件回退/
写盘失败韧性/装载加速。零网络零 API，夹具全内联。

跑法（tests/ 惯例）：仓根起 venv/bin/python -m tests.test_bm25_persist。
"""
import builtins
import json
import os
import pickle
import re
import tempfile
import time
import unittest

import rag


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------
def _svc_rec(rid, content, doc_id, locator, embedding):
    return {"id": rid, "content": content, "doc_id": doc_id,
            "version": "V1", "locator": locator, "embedding": embedding}


# 8 维向量：对 query=[1,0,...] 余弦 c1=1.0 / c2≈0.9939 / c3=0.0（c3 含精确
# 术语 p0-NominalPUSCH，BM25 通道正主——口径同 tests/test_bm25.py 服务级夹具）
SERVICE_RECS = [
    _svc_rec("c1", "宏切换参数概述与常见配置说明", "DOC-1", "§1", [1, 0, 0, 0, 0, 0, 0, 0]),
    _svc_rec("c2", "TS 36.214 RSRP definition table", "DOC-2", "5.1.1", [0.9, 0.1, 0, 0, 0, 0, 0, 0]),
    _svc_rec("c3", "p0-NominalPUSCH 参数卡 default value 0", "DOC-3", "A.1", [0, 1, 0, 0, 0, 0, 0, 0]),
    _svc_rec("c4", "RSRP 测量报告配置 measConfig 说明", "DOC-4", "5.1.2", [0.8, 0.2, 0, 0, 0, 0, 0, 0]),
    _svc_rec("c5", "切换迟滞 hys 与时间触发器 TTT 说明", "DOC-5", "5.2.1", [0.7, 0.3, 0, 0, 0, 0, 0, 0]),
]
QUERY_VEC = [1, 0, 0, 0, 0, 0, 0, 0]
# 追加块（换库回退测试用）：含独占探针词，回退重建后应可被检索到
APPEND_REC = _svc_rec("c6", "zzzUniqueProbeTerm 专项条款说明", "DOC-6", "9.9",
                      [0.6, 0.4, 0, 0, 0, 0, 0, 0])

# 直接建索引用的纯文本 recs（BM25Index.build 只读 META 文本，无需向量）
def _txt_rec(i):
    return {"id": f"t{i}", "content": f"第 {i} 号切换参数卡 alphaConfig-{i % 97} "
                                      f"取值说明与配置约束条文填充",
            "doc_id": f"DOC-{i % 200}", "version": "V1", "locator": f"5.{i % 90}.{i % 7}"}


class _Silent:
    def __init__(self):
        self.lines = []

    def __call__(self, line):
        self.lines.append(line)

    def bm25(self):
        return [ln for ln in self.lines if ln.startswith("[rag-bm25]")]


# ---------------------------------------------------------------------------
# 直接层：落盘/装载/等价/校验
# ---------------------------------------------------------------------------
class Bm25PersistCoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        # 锚点 store（save/try_load 只读其 size/mtime，内容不参与）
        self.store = os.path.join(self.tmp.name, "embeddings.jsonl")
        with open(self.store, "w", encoding="utf-8") as f:
            f.write(json.dumps(SERVICE_RECS[0], ensure_ascii=False) + "\n")
        # BM25Index.build 只读 META 文本——去 embedding 即纯文本 recs
        self.recs = [{k: v for k, v in r.items() if k != "embedding"}
                     for r in SERVICE_RECS]
        self.cache = rag.bm25_cache_path(self.store)
        self.assertFalse(os.path.exists(self.cache))

    def tearDown(self):
        self.tmp.cleanup()

    def test_default_config_key_off(self):
        """直通键：不入 DEFAULT_RAG_CONFIG（键面守卫钉死键增量），缺省即关。"""
        self.assertNotIn("bm25_persist", rag.DEFAULT_RAG_CONFIG)

    def test_missing_cache_returns_none(self):
        self.assertIsNone(rag.try_load_bm25_index(self.store, self.recs, 8))

    def test_roundtrip_identical_to_built(self):
        built = rag.BM25Index.build(self.recs)
        rag.save_bm25_index(built, self.store, 8)
        self.assertTrue(os.path.exists(self.cache))
        loaded = rag.try_load_bm25_index(self.store, self.recs, 8)
        self.assertIsNotNone(loaded)
        # 派生统计逐项一致（现算即校验）
        for k in ("n_docs", "n_terms", "n_postings", "postings_bytes"):
            self.assertEqual(getattr(loaded, k), getattr(built, k),
                             f"stat mismatch: {k}")
        self.assertAlmostEqual(loaded.avgdl, built.avgdl, places=12)
        # 内部结构逐位一致（dict/array 均按值比较）
        self.assertEqual(loaded._post_ids, built._post_ids)
        self.assertEqual(loaded._post_tfs, built._post_tfs)
        self.assertEqual(list(loaded._doc_len), list(built._doc_len))
        # recs 挂当前装载面（不落盘、引用重挂）
        self.assertIs(loaded.recs, self.recs)
        # 检索结果逐位一致（rank/score/idx）
        for q in ("RSRP 定义", "p0-NominalPUSCH 取值", "切换 hys TTT",
                  "measConfig", "alphaConfig-1", ""):
            ha = built.search(q, topk=5)
            hb = loaded.search(q, topk=5)
            self.assertEqual([(h["rank"], h["score"], h["idx"]) for h in ha],
                             [(h["rank"], h["score"], h["idx"]) for h in hb], q)

    def test_store_size_or_mtime_change_rejects(self):
        built = rag.BM25Index.build(self.recs)
        rag.save_bm25_index(built, self.store, 8)
        # 同内容重写（size 不变）+ 显式拨 mtime → 锚点不符即弃
        with open(self.store, "w", encoding="utf-8") as f:
            f.write(json.dumps(SERVICE_RECS[0], ensure_ascii=False) + "\n")
        st = os.stat(self.store)
        os.utime(self.store, ns=(st.st_atime_ns + 10 ** 9,
                                 st.st_mtime_ns + 10 ** 9))
        self.assertIsNone(rag.try_load_bm25_index(self.store, self.recs, 8))
        # 追加一行（size 变）→ 同样弃
        rag.save_bm25_index(built, self.store, 8)
        with open(self.store, "a", encoding="utf-8") as f:
            f.write("{}\n")
        self.assertIsNone(rag.try_load_bm25_index(self.store, self.recs, 8))

    def test_dim_or_n_docs_mismatch_rejects(self):
        built = rag.BM25Index.build(self.recs)
        rag.save_bm25_index(built, self.store, 8)
        self.assertIsNone(rag.try_load_bm25_index(self.store, self.recs, 16))
        self.assertIsNone(rag.try_load_bm25_index(self.store, self.recs[:4], 8))

    def test_corrupt_file_rejects(self):
        built = rag.BM25Index.build(self.recs)
        rag.save_bm25_index(built, self.store, 8)
        raw = open(self.cache, "rb").read()
        with open(self.cache, "wb") as f:  # 垃圾字节
            f.write(b"\x00not a pickle at all")
        self.assertIsNone(rag.try_load_bm25_index(self.store, self.recs, 8))
        with open(self.cache, "wb") as f:  # 截断的有效 pickle
            f.write(raw[: len(raw) // 2])
        self.assertIsNone(rag.try_load_bm25_index(self.store, self.recs, 8))

    def test_malicious_pickle_rejected_not_executed(self):
        class _Evil:
            def __reduce__(self):
                return (builtins.eval, ("1+1",))  # 若放行即被执行

        with open(self.cache, "wb") as f:
            pickle.dump(_Evil(), f)
        self.assertIsNone(rag.try_load_bm25_index(self.store, self.recs, 8))

    def test_load_faster_than_build_loose(self):
        """亚秒级断言=宽松阈值防抖（20,000 块样本，本地实测量级见施工报告）。"""
        recs = [_txt_rec(i) for i in range(20000)]
        t0 = time.time()
        built = rag.BM25Index.build(recs)
        t_build = time.time() - t0
        rag.save_bm25_index(built, self.store, 8)
        t0 = time.time()
        loaded = rag.try_load_bm25_index(self.store, recs, 8)
        t_load = time.time() - t0
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.n_docs, 20000)
        self.assertLess(t_load, 5.0)      # 宽松亚秒级阈（CI 抖动余量）
        self.assertLess(t_load, t_build)  # 加速件本义：装载须快于全量重建
        print(f"\n[bm25-persist] 20000 块: build={t_build:.3f}s "
              f"load={t_load:.3f}s speedup={t_build / max(t_load, 1e-9):.1f}x")


# ---------------------------------------------------------------------------
# 服务层：RagService 装载路径两态
# ---------------------------------------------------------------------------
class Bm25PersistServiceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "embeddings.jsonl")
        self._write_store(SERVICE_RECS)
        self.log = _Silent()

    def tearDown(self):
        self.tmp.cleanup()

    def _write_store(self, recs):
        with open(self.path, "w", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    def _service(self, **cfg):
        cfg.setdefault("store_path", self.path)
        cfg.setdefault("topk", 2)
        cfg.setdefault("max_context_chars", 6000)
        cfg.setdefault("hybrid_bm25_enabled", True)
        svc = rag.RagService(embed_fn=lambda q: list(QUERY_VEC), log=self.log)
        svc.initialize(cfg)
        return svc

    def test_persist_off_default_unchanged(self):
        """关态默认=现状逐字节：不落盘、日志格式与旧版一致、二次装载仍重建。"""
        self.assertNotIn("bm25_persist", rag.DEFAULT_RAG_CONFIG)
        svc = self._service()  # 不带 bm25_persist 键 → 默认关
        lines = self.log.bm25()
        self.assertEqual(len(lines), 1)
        # 旧版 build 行格式（无 persist 后缀、无 load 形）
        self.assertRegex(lines[0], r"^\[rag-bm25\] build docs=5 terms=\d+ "
                                   r"postings=\d+ avgdl=[\d.]+ arr_mb=[\d.]+ "
                                   r"dur=[\d.]+s$")
        self.assertFalse(os.path.exists(rag.bm25_cache_path(self.path)))
        # 显式 false 同态；再起一个服务仍是 build（无缓存可载）
        svc2 = self._service(bm25_persist=False)
        self.assertEqual(len(self.log.bm25()), 2)
        self.assertTrue(self.log.bm25()[1].startswith("[rag-bm25] build "))
        self.assertFalse(os.path.exists(rag.bm25_cache_path(self.path)))
        self.assertIsNotNone(svc2._bm25)

    def test_persist_on_save_then_cache_hit_on_second_load(self):
        svc1 = self._service(bm25_persist=True)
        cache = rag.bm25_cache_path(self.path)
        self.assertTrue(os.path.exists(cache))
        l1 = self.log.bm25()[0]
        self.assertRegex(l1, r"^\[rag-bm25\] build .+ persist=save "
                             r"save_dur=[\d.]+s$")
        # 第二次装载（新服务实例=模拟重启）：缓存命中，不再全量重建
        svc2 = self._service(bm25_persist=True)
        l2 = [ln for ln in self.log.bm25() if ln.startswith("[rag-bm25] load ")]
        self.assertEqual(len(l2), 1)
        self.assertIn("（cache 命中）", l2[0])
        self.assertEqual(svc2._bm25.n_docs, svc1._bm25.n_docs)
        self.assertEqual(svc2._bm25.n_terms, svc1._bm25.n_terms)
        self.assertIsNot(svc2._bm25, svc1._bm25)
        self.assertIs(svc2._bm25.recs, svc2._recs)  # recs 挂当前装载面
        # 端到端检索冒烟：两态同结果（hybrid 融合路径吃的是装载索引）
        _, s1 = svc1.retrieve("p0-NominalPUSCH 的取值")
        _, s2 = svc2.retrieve("p0-NominalPUSCH 的取值")
        self.assertEqual([x["doc_id"] for x in s1], [x["doc_id"] for x in s2])

    def test_store_changed_rebuilds_and_resaves(self):
        svc1 = self._service(bm25_persist=True)
        self.assertEqual(svc1._bm25.n_docs, 5)
        # 换库（追加一块）：锚点不符 → 回退全量重建，检索面吃新库
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(APPEND_REC, ensure_ascii=False) + "\n")
        n_before = len(self.log.bm25())
        svc2 = self._service(bm25_persist=True)
        self.assertEqual(len(self.log.bm25()), n_before + 1)
        l2 = self.log.bm25()[-1]
        self.assertTrue(l2.startswith("[rag-bm25] build "), l2)  # 非缓存命中
        self.assertIn("persist=save", l2)  # 重建后重新落盘
        self.assertEqual(svc2._bm25.n_docs, 6)
        hit = svc2._bm25.search("zzzUniqueProbeTerm 条款", topk=2)
        self.assertTrue(hit and hit[0]["rec"]["doc_id"] == "DOC-6")
        # 第三次装载：新缓存命中（含第 6 块）
        svc3 = self._service(bm25_persist=True)
        self.assertTrue(self.log.bm25()[-1].startswith("[rag-bm25] load "))
        self.assertEqual(svc3._bm25.n_docs, 6)

    def test_corrupt_cache_rebuilds(self):
        self._service(bm25_persist=True)
        with open(rag.bm25_cache_path(self.path), "wb") as f:
            f.write(b"\x80\x05 garbage broken")
        svc2 = self._service(bm25_persist=True)
        self.assertTrue(self.log.bm25()[-1].startswith("[rag-bm25] build "))
        self.assertIsNotNone(svc2._bm25)
        self.assertEqual(svc2._bm25.n_docs, 5)
        self.assertIn("persist=save", self.log.bm25()[-1])  # 坏件被重建覆盖

    def test_save_failure_warns_service_still_ok(self):
        # 预占缓存件路径为目录 → 落盘必败（os.replace 目录目标非法）
        os.mkdir(rag.bm25_cache_path(self.path))
        svc = self._service(bm25_persist=True)
        l = self.log.bm25()[-1]
        self.assertIn("persist=save_fail", l)
        self.assertIsNotNone(svc._bm25)  # 现役索引已在内存，检索不受影响
        self.assertEqual(svc._bm25.n_docs, 5)
        _, sources = svc.retrieve("RSRP 定义")
        self.assertTrue(sources)


if __name__ == "__main__":
    unittest.main()
