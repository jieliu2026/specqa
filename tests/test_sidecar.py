# -*- coding: utf-8 -*-
"""rag.py sidecar 装载加速缓存离线单测（2026-09-24 装载瘦身选装件）。

覆盖：构建→装载等价（vec 逐位相等、检索同分同序）、过期退回（源 mtime/size
变化）、坏件退回（bin 截断/meta 坏 JSON/rows 行数不符）、默认无 sidecar=与
旧行为一致、use_sidecar=False 显式绕开、显式缓存路径、缺库 missing 语义、
幂等重建。零网络零 API，夹具全内联（4 维假向量）。
"""
import json
import os
import tempfile
import unittest

import rag


VECS = [
    [1, 0, 0, 0],
    [0.6, 0.8, 0, 0],
    [0, 0.6, 0.8, 0],
    [0, 0, 0.6, 0.8],
]
QUERY = [1, 0, 0, 0]


def write_fixture(path):
    """4 块合法 4 维记录 + 1 坏行（loaded=4 bad=1 total=5）。"""
    lines = []
    for i, v in enumerate(VECS, 1):
        lines.append(json.dumps(
            {"id": f"c{i}", "content": f"内容{i}", "doc_id": f"DOC-{i}",
             "version": f"V{i}", "locator": f"§{i}", "embedding": v},
            ensure_ascii=False))
    lines.append("{坏行不是json")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


class SidecarTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = os.path.join(self.tmp.name, "embeddings.jsonl")
        write_fixture(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def _plain(self):
        return rag.load_store(self.store, use_sidecar=False)

    def _build(self, **kw):
        recs, dim, stats = self._plain()
        return rag.build_sidecar(recs, dim, self.store, stats=stats, **kw)

    # -- 等价性 ---------------------------------------------------------------
    def test_no_sidecar_is_plain_jsonl_path(self):
        _, _, stats = rag.load_store(self.store)  # 未构建过 sidecar
        self.assertEqual((stats["loaded"], stats["bad_lines"],
                          stats["total_lines"], stats["dim"]), (4, 1, 5, 4))
        self.assertNotIn("sidecar", stats)  # 无缓存件=与旧行为完全一致

    def test_build_then_load_equivalent(self):
        recs_a, dim_a, stats_a = self._plain()
        bp, mp = self._build()
        self.assertTrue(os.path.exists(bp) and os.path.exists(mp))
        recs_b, dim_b, stats_b = rag.load_store(self.store)
        self.assertTrue(stats_b["sidecar"])  # 走了 sidecar 快装
        self.assertEqual(dim_b, dim_a)
        self.assertEqual((stats_b["loaded"], stats_b["bad_lines"],
                          stats_b["total_lines"]), (4, 1, 5))  # 统计还原
        self.assertEqual([r["id"] for r in recs_b], [r["id"] for r in recs_a])
        for ra, rb in zip(recs_a, recs_b):
            for k in ("id", "content", "doc_id", "version", "locator"):
                self.assertEqual(rb[k], ra[k])
            self.assertTrue(rb["vec"] == ra["vec"])  # float32 逐位相等
        # 检索同分同序（sidecar 存的即 jsonl 路径算出的 float32 值）
        hits_a = rag.search(QUERY, recs_a, topk=4)
        hits_b = rag.search(QUERY, recs_b, topk=4)
        self.assertEqual([h["idx"] for h in hits_b], [h["idx"] for h in hits_a])
        self.assertEqual([h["score"] for h in hits_b], [h["score"] for h in hits_a])

    def test_idempotent_rebuild(self):
        self._build()
        self._build()  # 幂等覆盖
        _, _, stats = rag.load_store(self.store)
        self.assertTrue(stats["sidecar"])
        self.assertEqual(stats["loaded"], 4)

    # -- 过期/坏件一律退 jsonl ------------------------------------------------
    def test_stale_mtime_falls_back(self):
        self._build()
        st = os.stat(self.store)
        os.utime(self.store, ns=(st.st_mtime_ns + 1_000_000_000,) * 2)
        _, _, stats = rag.load_store(self.store)
        self.assertNotIn("sidecar", stats)  # 源已变（在飞续写）→ 过期弃缓存
        self.assertEqual(stats["loaded"], 4)

    def test_stale_size_falls_back(self):
        self._build()
        with open(self.store, "a", encoding="utf-8") as f:  # 追加 1 合法行
            f.write(json.dumps({"id": "c5", "content": "新块", "doc_id": "DOC-5",
                                "version": "V5", "locator": "§5",
                                "embedding": [0, 0, 0, 1]}) + "\n")
        recs, _, stats = rag.load_store(self.store)
        self.assertNotIn("sidecar", stats)
        self.assertEqual((stats["loaded"], stats["total_lines"]), (5, 6))
        self.assertEqual(recs[-1]["id"], "c5")

    def test_truncated_bin_falls_back(self):
        bp, _ = self._build()
        with open(bp, "r+b") as f:  # 截掉一半
            f.truncate(os.path.getsize(bp) // 2)
        _, _, stats = rag.load_store(self.store)
        self.assertNotIn("sidecar", stats)
        self.assertEqual(stats["loaded"], 4)

    def test_corrupt_meta_falls_back(self):
        _, mp = self._build()
        with open(mp, "w", encoding="utf-8") as f:
            f.write("{坏json")
        _, _, stats = rag.load_store(self.store)
        self.assertNotIn("sidecar", stats)
        self.assertEqual(stats["loaded"], 4)

    def test_rowcount_mismatch_falls_back(self):
        _, mp = self._build()
        with open(mp, encoding="utf-8") as f:  # rows 少一行（count 不变）
            meta = json.load(f)
        meta["rows"].pop()
        with open(mp, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)
        _, _, stats = rag.load_store(self.store)
        self.assertNotIn("sidecar", stats)
        self.assertEqual(stats["loaded"], 4)

    # -- 显式路径与绕开 --------------------------------------------------------
    def test_explicit_sidecar_paths(self):
        alt_bin = os.path.join(self.tmp.name, "alt.bin")
        alt_meta = os.path.join(self.tmp.name, "alt.meta.json")
        self._build(bin_path=alt_bin, meta_path=alt_meta)
        self.assertFalse(os.path.exists(self.store + rag.SIDECAR_SUFFIX + ".bin"))
        _, _, stats = rag.load_store(self.store, sidecar_bin=alt_bin,
                                     sidecar_meta=alt_meta)
        self.assertTrue(stats["sidecar"])
        # 默认路径无件 → 不显式指定时不生效
        _, _, stats2 = rag.load_store(self.store)
        self.assertNotIn("sidecar", stats2)

    def test_use_sidecar_false_bypasses_existing_cache(self):
        self._build()
        _, _, stats = rag.load_store(self.store, use_sidecar=False)
        self.assertNotIn("sidecar", stats)
        self.assertEqual(stats["loaded"], 4)

    def test_missing_store_still_missing(self):
        self._build()
        recs, dim, stats = rag.load_store(
            os.path.join(self.tmp.name, "无此库.jsonl"))
        self.assertEqual(recs, [])
        self.assertIsNone(dim)
        self.assertTrue(stats["missing"])


if __name__ == "__main__":
    unittest.main()
