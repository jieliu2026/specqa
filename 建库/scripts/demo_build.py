#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""demo 向量库构建脚本（20261114）——demo/corpus.jsonl → demo/vectors/embeddings.jsonl。

用你自己的百炼/DashScope key 把演示语料嵌入为 rag.py 可装载的向量库
（行式与生产库同构：chunk 元数据 + "embedding" 1024 维）。复用 embed_common
的请求形状与重试/对半拆逻辑，与主管线同形。

费用闸：--dry-run 只估不算（字符/1.7 估 token，0.5 元/百万 token 保守档）；
--yes 才真调 API；用量落 demo/usage.jsonl。--apply-config 顺带把 config.json
的 rag.enabled 置 true、store_path 指向 demo 库（原子替换）。

用法：python3 建库/scripts/demo_build.py --dry-run
      python3 建库/scripts/demo_build.py --yes [--apply-config]
"""
import argparse
import datetime
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "建库" / "scripts"))
import embed_common  # noqa: E402

CORPUS = ROOT / "demo" / "corpus.jsonl"
STORE = ROOT / "demo" / "vectors" / "embeddings.jsonl"
USAGE = ROOT / "demo" / "usage.jsonl"
CONFIG = ROOT / "config.json"
MODEL, DIMS, BATCH = "text-embedding-v4", 1024, 10
PRICE_PER_MTOK = 0.5
CPT = 1.7  # 中文字符/token 估算


def est(texts):
    toks = sum(int(len(t) / CPT) for t in texts)
    return toks, round(toks / 1e6 * PRICE_PER_MTOK, 6)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", action="store_true", help="真跑（API 计费）")
    ap.add_argument("--apply-config", action="store_true",
                    help="构建毕后把 config.json 指向 demo 库并开 rag")
    args = ap.parse_args()
    chunks = [json.loads(x) for x in CORPUS.read_text(encoding="utf-8").splitlines() if x.strip()]
    texts = [c["content"] for c in chunks]
    toks, cny = est(texts)
    print(f"[预检] {len(chunks)} 块 / 估 {toks} tok / 估费 {cny} 元（{PRICE_PER_MTOK} 元/Mtok 保守档）")
    if args.dry_run or not args.yes:
        print("[dry-run] 未调 API。真跑：--yes")
        return 0
    api = embed_common.load_api_settings(str(Path.home() / ".bailian" / "config.json"))
    cfg = {"model": MODEL, "dims": DIMS, "max_retry": 3,
           "request_timeout": 120, "retry_max_sleep": 60}
    rows, done, reqs, real_toks = [], 0, 0, 0
    for i in range(0, len(texts), BATCH):
        batch = texts[i:i + BATCH]
        vecs, usage, _retried, err = embed_common.embed_batch(batch, cfg, api)
        if err is not None:
            print(f"[中止] 第 {reqs + 1} 批失败：{err}")
            return 2
        reqs += 1
        real_toks += int(usage.get("prompt_tokens", 0))
        for j, v in enumerate(vecs):
            row = dict(chunks[i + j])
            row["embedding"] = v
            rows.append(json.dumps(row, ensure_ascii=False))
        done += len(batch)
        print(f"[嵌入] {done}/{len(texts)}")
    STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_suffix(".tmp")
    tmp.write_text("\n".join(rows) + "\n", encoding="utf-8")
    os.replace(tmp, STORE)
    with USAGE.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "batch": "demo_corpus", "n": len(chunks), "requests": reqs,
                            "real_tokens": real_toks,
                            "real_cny": round(real_toks / 1e6 * PRICE_PER_MTOK, 6)},
                           ensure_ascii=False) + "\n")
    print(f"[毕] {len(rows)} 行 → {STORE}（实耗 {real_toks} tok ≈ {real_toks / 1e6 * PRICE_PER_MTOK:.6f} 元，用量记 {USAGE.name}）")
    if args.apply_config:
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
        rag = cfg.setdefault("rag", {})
        rag["enabled"] = True
        rag["store_path"] = "demo/vectors/embeddings.jsonl"
        rag["score_threshold"] = 0.58   # demo 库标定（2026-11-18 独立标定卷 60 题：
        # in 下界 0.722／out 上界 0.522，断带中点偏域内；生产默认 0.40 系生产库标定不变）
        t = CONFIG.with_suffix(".tmp")
        t.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(t, CONFIG)
        print("[配置] config.json：rag.enabled=true，store_path → demo 库")
    return 0


if __name__ == "__main__":
    sys.exit(main())
