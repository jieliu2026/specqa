#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
embed_run.py —— 建库嵌入管线唯一入口（2026-09-17 工程化重构：embed_run.py 与
embed_run2.py 合并；接续段的 id 消歧 -SC 逻辑不迁移，git 史可考，id 问题改由
chunk_id.py 内容哈希机制从根上解决）

机制全部来自 embed_common（重试退避/对半拆/进度幂等/用量登记/红线熔断/并发），
配置全部来自 pipeline_config（模块默认 + --config JSON + --set CLI 覆盖）。
本文件只做：参数装配、预览/计费闸、切块加载与 id 查重、收尾汇总。

计费纪律（默认零调用）：不带 --yes 只做预览（计数/粗估费用/进度），绝不碰 API；
--status 同样零调用。真正调按量通道必须显式 --yes（过程日志三节 3 授权口径，
红线 red_line_cny 累计熔断在机制层）。

CR 前缀拼接（2026-09-18 加）：--set cr_prepend_context=true（或配置文件同名键）开
Contextual Retrieval 块首拼接——嵌入文本=cr_context+换行+content，切块源吃 chunks-cr/
装配产物；缺/空 cr_context 的块退原文并计数警告；默认关=嵌入文本仍为 content 原文，
行为与本开关加入前完全一致（id/进度/幂等口径均不变：CR 前后同 id 属预期换库语义）。

增量重嵌 diff 硬闸（2026-09-21 加，优化提升批 1；诊断报告 P1-7 / deepseek-v4.1-flash
P0-1）：预览（不带 --yes）与 --yes 执行前，强制对新切块 vs 现有向量库（out_vecs 全量
行）跑 chunk_id.diff_chunks 内容级对比，输出 added/changed/removed 摘要 + 重嵌任务
预估费用（按 cfg 价目）+ 相对全量重嵌可省多少；库非空且新增占比 >90% 时打显著告警
（疑似 locator_fields 配置失效/切块定位字段漂移导致全量重嵌——跑完才发现增量没生效
的事故前置拦截）。摘要同时落一行 stage="diff" 到用量台账（log_usage）。向量库空
（首次建库）只提示无基线，不做 diff 不落台账。纯本地零 API（读 out_vecs 本地文件）。

用法：
  python3 embed_run.py --chunks A.jsonl,B.jsonl [--config cfg.json] [--set k=v ...]
                       [--workers N] [--yes | --status]
  python3 embed_run.py --dump-config > my_cfg.json   # 导出配置模板
"""
import argparse
import json
import os
import sys
import time

import embed_common
import pipeline_config
from chunk_id import find_duplicate_ids, diff_chunks

# 增量失效告警阈值：库非空且 added/new_total 严格大于此值 → 显著警告（疑似
# locator 配置失效导致全量重嵌）；口径=诊断报告 P1-7（"added 占比 >90%"）
DIFF_ADDED_WARN_RATIO = 0.9


def _has_cr_prefix(c):
    """块是否带可用的 cr_context（非空非空白字符串；缺字段/None/其他类型均 False）。"""
    ctx = c.get("cr_context")
    return isinstance(ctx, str) and ctx.strip() != ""


def build_embed_text_fn(prepend):
    """构造 chunk→嵌入文本 函数（传 embed_common.run_pipeline 的 text_fn）。

    prepend=False → None（run_pipeline 走默认 c["content"]，与开关加入前逐字节一致）；
    True → cr_context + "\\n" + content（块首拼接口径，Anthropic Contextual Retrieval），
    缺/空 cr_context 的块退原文（退化计数由调用方在预览/启动时警告）。只改送 API 的
    文本；落盘向量行仍存原 chunk 全字段，id 仍为块 id。
    """
    if not prepend:
        return None

    def text_fn(c):
        if _has_cr_prefix(c):
            return c["cr_context"] + "\n" + (c.get("content") or "")
        return c.get("content") or ""

    return text_fn


def cr_prepend_stats(chunks):
    """(拼前缀块数, 退化块数, 退化块样例 id≤3)——cr_prepend_context=true 时的
    预览/警告口径（退化=缺 cr_context 字段、空串/空白或非字符串）。"""
    fb_ids = [c.get("id") for c in chunks if not _has_cr_prefix(c)]
    return len(chunks) - len(fb_ids), len(fb_ids), fb_ids[:3]


def estimate_embed_chars(chunks, prepend=False):
    """预览粗估字符数（CJK 字符≈token 的量级口径不变，仅预览用）：
    默认=Σlen(content)；prepend=True 时有效前缀块加计 len(cr_context)+1（换行）。"""
    n = 0
    for c in chunks:
        base = len(c.get("content") or "")
        if prepend and _has_cr_prefix(c):
            n += base + 1 + len(c["cr_context"])
        else:
            n += base
    return n


def run_diff_gate(chunks, cfg, out_path, usage_path, prepend=False):
    """增量重嵌 diff 硬闸（预览与 --yes 执行前必过；纯本地零 API）。

    新切块 vs 现有向量库（out_path 全量行）做 chunk_id.diff_chunks 内容级对比
    （id/locator 字段口径取 cfg，两侧同一套重算，存储 id 不参与）。返回
    (diff, gate_lines)：diff=None 表示库空无基线（首建语义）；gate_lines 为
    待打印行（摘要+费用+失效告警）。diff 非 None 时同步落一行 stage="diff"
    摘要到 usage_path 台账（幂等：每跑一次闸记一行，供事后对账增量是否生效）。
    """
    if not os.path.exists(out_path):
        return None, ["[diff闸] 向量库基线为空（%s 未建）——首次建库语义，无增量 diff" % out_path]
    old = embed_common.load_jsonl(out_path)
    if not old:
        return None, ["[diff闸] 向量库基线为空（%s 0 行）——首次建库语义，无增量 diff" % out_path]

    diff = diff_chunks(old, chunks, cfg["id_fields"], cfg["locator_fields"], cfg["id_len"])
    n_added, n_changed, n_removed = len(diff["added"]), len(diff["changed"]), len(diff["removed"])
    n_tasks = len(diff["tasks"])
    est_tasks_tokens = estimate_embed_chars(diff["tasks"], prepend)
    est_tasks_cny = embed_common.estimate_cost_cny(est_tasks_tokens, cfg["price_per_mtok"])
    full_tokens = estimate_embed_chars(chunks, prepend)
    full_cny = embed_common.estimate_cost_cny(full_tokens, cfg["price_per_mtok"])
    added_ratio = (n_added / diff["new_total"]) if diff["new_total"] else 0.0

    lines = [
        "[diff闸] 增量对比（旧库 %d 行 → 新切块 %d 块）：不变 %d，新增 %d，变更 %d，删除 %d"
        "（id_fields=%s；locator_fields=%s）" % (
            diff["old_total"], diff["new_total"], diff["unchanged"],
            n_added, n_changed, n_removed,
            ",".join(cfg["id_fields"]), ",".join(cfg["locator_fields"])),
        "[diff闸] 重嵌任务=新增+变更 %d 块，粗估 %d tokens ≈ %.4f 元（价目 %.2f 元/百万 token）；"
        "全量重嵌基线 %d tokens ≈ %.4f 元，增量口径可省约 %.4f 元" % (
            n_tasks, est_tasks_tokens, est_tasks_cny, cfg["price_per_mtok"],
            full_tokens, full_cny, full_cny - est_tasks_cny),
    ]
    if diff["collisions"]:
        lines.append("[警告][diff闸] 新集合内部 id 撞车 %d 组（id_fields 区分度不足或内容真重复，"
                     "参 chunk_id.py 处置口径：扩字段或切块侧去重）" % len(diff["collisions"]))
    if diff["old_total"] and added_ratio > DIFF_ADDED_WARN_RATIO:
        lines.append(
            "[警告][diff闸] 增量失效疑似：新增占比 %.1f%%（added %d / 新切块 %d）> 90%% 且向量库非空"
            "（%d 行）——疑似 locator 配置失效/切块定位字段漂移导致全量重嵌，"
            "请核对 id_fields/locator_fields 或切块定位字段后再 --yes" % (
                100.0 * added_ratio, n_added, diff["new_total"], diff["old_total"]))

    os.makedirs(os.path.dirname(os.path.abspath(usage_path)), exist_ok=True)
    entry = {"ts": time.strftime("%H:%M:%S"), "stage": "diff",
             "old_total": diff["old_total"], "new_total": diff["new_total"],
             "unchanged": diff["unchanged"], "added": n_added, "changed": n_changed,
             "removed": n_removed, "tasks": n_tasks,
             "est_tasks_tokens": est_tasks_tokens, "est_tasks_cny": est_tasks_cny,
             "full_tokens": full_tokens, "full_cny": full_cny,
             "price_per_mtok": cfg["price_per_mtok"],
             "added_ratio": round(added_ratio, 4)}
    with open(usage_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return diff, lines


def build_argparser():
    ap = argparse.ArgumentParser(
        description="建库嵌入管线入口（默认预览零 API；--yes 才真正按量调用）",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--chunks", action="append",
                    help="切块源 jsonl 路径（可重复或逗号分隔；缺省用配置 src_files）")
    ap.add_argument("--config", help="JSON 配置文件（pipeline_config 模板可 --dump-config 导出）")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                    help="CLI 覆盖配置项（可重复；如 --set price_per_mtok=0.25 --set batch=5）")
    ap.add_argument("--workers", type=int, help="并发路数（等价 --set workers=N）")
    ap.add_argument("--status", action="store_true", help="只报进度（零 API 调用）")
    ap.add_argument("--yes", action="store_true",
                    help="显式确认按量计费并真正执行（不带则只预览）")
    ap.add_argument("--dump-config", action="store_true", help="打印 JSON 配置模板后退出")
    return ap


def main(argv=None):
    ap = build_argparser()
    args = ap.parse_args(argv)
    if args.dump_config:
        print(pipeline_config.dump_template())
        return 0

    overrides = pipeline_config.parse_set_args(args.set)
    if args.workers is not None:
        overrides["workers"] = str(args.workers)
    cfg = pipeline_config.load_config(args.config, overrides)

    src_files = []
    if args.chunks:
        for item in args.chunks:
            src_files.extend(p for p in item.split(",") if p.strip())
    src_files = [pipeline_config.resolve_path(p) for p in (src_files or cfg["src_files"])]

    out_path = pipeline_config.resolve_path(cfg["out_vecs"])
    usage_path = pipeline_config.resolve_path(cfg["log_usage"])
    progress_path = pipeline_config.resolve_path(cfg["log_progress"])
    err_path = pipeline_config.resolve_path(cfg["log_err"])

    done, p = embed_common.load_progress(progress_path)
    acc_cny = embed_common.estimate_cost_cny(p["total_prompt_tokens"], cfg["price_per_mtok"])

    if not src_files:
        if args.status:
            print("[进度] 进度档 %s：done=%d 请求=%d 批=%d 重试=%d tokens=%d（估 %.4f 元）" % (
                progress_path, len(done), p["requests"], p["batches"], p["retries"],
                p["total_prompt_tokens"], acc_cny))
            return 0
        ap.error("未给 --chunks 且配置 src_files 为空——新语料切块后经 --chunks 指定（或写入配置）")

    chunks = embed_common.load_chunks(src_files)
    dups = find_duplicate_ids(chunks)
    if dups:
        print("[中止] 切块源 id 撞车 %d 组（样例 %s）——先经 chunk_id.py 重算内容哈希 id 或切块侧去重" % (
            len(dups), list(dups)[:3]))
        return 2

    # 增量 diff 硬闸：预览与 --yes 执行前必过（库空=首建语义只提示；纯本地零 API）
    prepend = cfg["cr_prepend_context"]
    _, gate_lines = run_diff_gate(chunks, cfg, out_path, usage_path, prepend)
    for line in gate_lines:
        print(line)

    todo = [c for c in chunks if c["id"] not in done]
    n_batches = (len(todo) + cfg["batch"] - 1) // cfg["batch"]
    n_prefix = n_fallback = 0
    if prepend:
        n_prefix, n_fallback, fb_ids = cr_prepend_stats(todo)
    # 粗估（CJK 字符≈token 的量级口径，仅预览用；真实用量以逐批登记为准）；
    # cr_prepend_context=true 时口径含块首 cr_context 前缀+换行
    est_new_tokens = estimate_embed_chars(todo, prepend)
    est_new_cny = embed_common.estimate_cost_cny(est_new_tokens, cfg["price_per_mtok"])

    print("[预览] 全量 %d；已完成 %d；待做 %d → %d 批（batch=%d，workers=%d，model=%s/%d 维）" % (
        len(chunks), len(done), len(todo), n_batches, cfg["batch"], cfg["workers"],
        cfg["model"], cfg["dims"]))
    if prepend:
        extra_chars = est_new_tokens - estimate_embed_chars(todo, False)
        print("[预览] CR 前缀拼接=开（cr_prepend_context=true）：嵌入文本=cr_context+换行+content；"
              "待做 %d 块中拼前缀 %d 块、退化原文 %d 块；粗估口径含前缀 +%d 字符" % (
                  len(todo), n_prefix, n_fallback, extra_chars))
        if n_fallback:
            print("[警告] 待做 %d 块缺或空 cr_context（样例 id %s）——退化原文嵌入（无 CR 增益），"
                  "请核对切块源是否为 chunks-cr/ 装配产物" % (n_fallback, fb_ids))
        if len(chunks) - len(todo) > 0:
            print("[警告] 进度档已有 %d 个同 id 块按幂等跳过——CR 前后同 id 但嵌入文本不同，"
                  "如系换库重嵌请换 out_vecs/log_progress 路径（或清进度档）后再跑" % (len(chunks) - len(todo)))
    print("[预览] 本次粗估 %d tokens ≈ %.4f 元；进度档已累计 %.4f 元（红线 %.2f 元）" % (
        est_new_tokens, est_new_cny, acc_cny, cfg["red_line_cny"]))
    print("[预览] 输出 %s；进度 %s；用量 %s" % (out_path, progress_path, usage_path))
    if args.status or not todo:
        return 0
    if not args.yes:
        print("[预览] 未执行（零 API 调用）。确认按量计费后加 --yes 真正运行")
        return 0

    api = embed_common.load_api_settings(cfg["key_path"], cfg["embeddings_path"])
    print("[启动] --yes 已确认，%d 批并发 %d（单请求延迟实测 ~270s，预计 %.0f 分钟）" % (
        n_batches, cfg["workers"], n_batches * 4.6 / cfg["workers"]))
    if prepend:
        print("[启动] CR 前缀拼接=开：拼前缀 %d 块、退化原文 %d 块（退化计数警告见预览）" % (
            n_prefix, n_fallback))
    # CR prepend 旗标台账（2026-10-12 常驻监控备发包·工具面）：--yes 执行前先落一行
    # run_meta 到用量台账，记该次嵌入 cr_prepend_context 与否——过程日志 61 波0 自查
    # "历史库 CR 前后混嵌 902 块"（10-08 云窗轮 prepend=关裸嵌）的后续审计位。
    # 只新增行：不触既有台账行/向量行/进度幂等口径；预览与 --status 路径零落账
    # （输出逐字节不变）；先于 run_pipeline 落=中途断电审计行仍在。
    os.makedirs(os.path.dirname(os.path.abspath(usage_path)), exist_ok=True)
    with open(usage_path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": time.strftime("%H:%M:%S"), "stage": "run_meta",
                            "cr_prepend": bool(prepend), "chunks": len(todo),
                            "model": cfg["model"]}, ensure_ascii=False) + "\n")
    summary = embed_common.run_pipeline(
        todo, cfg, api, out_path, usage_path, progress_path, done, p,
        text_fn=build_embed_text_fn(prepend))

    print("[收尾] 本次落盘 %d chunk；失败 %d 批；累计 tokens=%d 估 %.4f 元（价格 %.2f 元/百万 token）" % (
        summary["ok_chunks"], summary["fail_batches"], p["total_prompt_tokens"],
        summary["est_cost_cny"], cfg["price_per_mtok"]))
    if summary["red_line_hit"]:
        print("[收尾] 红线已触发：在飞批已如实计费，剩余批未启动；如需继续须用户重新确认口径")
    if summary["fails"]:
        embed_common.save_fails(err_path, summary["fails"])
        print("[收尾] 失败 %d 批落档 %s（重跑本入口自动续做）" % (len(summary["fails"]), err_path))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
