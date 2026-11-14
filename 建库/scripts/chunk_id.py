#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
chunk_id.py —— 内容哈希稳定 id + 增量建库机制（2026-09-17 工程化重构轮立档）

为什么：旧 id 由切块器按文件序号拼出（L1-正文-…-001），语料增删/重排即漂移，
过程日志续跑会错配；且曾有 190 对同名文件 id 撞车靠 -SC 后缀手工消歧（embed_run2，
已退役，git 史可考）。本模块改为内容寻址：id = sha256(稳定字段规范序列化) 截短
——同输入同 id，内容改一字即变 id，与切块器实现解耦（任何切块器只要产出带约定
字段的 chunk dict 就能接入）。为 2026-09-17 决策的"从零重建语料库（源=权威公开
文献）"准备；旧课件切块器 chunk_l1.py 已冻结为遗留参照，不在新管线内。

两类键（字段清单均可配置，默认值见 pipeline_config.DEFAULTS）：
  - id_fields     ：身份字段（默认 layer/src/section/section_seq/content）。
                    哈希进 id；**必须含 content**（配置层强校验），保证改文必变 id。
  - locator_fields：定位字段（默认为 id_fields 去掉 content）。
                    不含内容，用于增量 diff 里识别"同一位置改了文"（变更分支）——
                    id 含 content 后纯按 id 对比只能看到"增+删"，定位键把它归并为
                    "变更"。速查行级等同位多行的语料，建议把 line_no 等行位字段
                    加进 locator_fields。

增量 diff（diff_chunks）：对比新旧 chunk 集合——
  新增 added   = 新集合中有、旧集合没有，且定位键在旧集合无对应；
  变更 changed = 新 id 不在旧集合，但定位键命中旧 chunk（同位改文）；
  删除 removed = 旧 id 不在新集合且未被配对为变更；
  tasks       = added + changed 的新块 → 待嵌入任务清单（只对这些块出嵌入任务，
                省掉全量重嵌的费用）。

零 API 零计费：本模块纯本地计算。
"""
import argparse
import hashlib
import json
import sys

import pipeline_config


def _canonical(obj):
    """规范序列化：键排序+紧凑分隔+UTF-8——dict 键序无关、确定性可复现。"""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _project(chunk, fields):
    """取字段子集；缺失字段取 None（两类键共用，保证缺字段不炸）。"""
    return {f: chunk.get(f) for f in fields}


def stable_id(chunk, fields=None, id_len=None):
    """内容哈希稳定 id：sha256(canonical(字段投影)) 十六进制截短。

    fields/id_len 缺省取 pipeline_config 默认（id_fields/id_len）。
    同输入必同 id；任一参哈希字段改一字必变 id；不参哈希字段（如 line_start、
    切块器内部序号）变动不影响 id。
    """
    if fields is None:
        fields = pipeline_config.DEFAULTS["id_fields"]
    if id_len is None:
        id_len = pipeline_config.DEFAULTS["id_len"]
    blob = _canonical(_project(chunk, fields)).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:id_len]


def locator_key(chunk, fields=None):
    """定位键：不含内容的字段投影规范串（增量 diff 的"同位"判据）。"""
    if fields is None:
        fields = pipeline_config.DEFAULTS["locator_fields"]
    return _canonical(_project(chunk, fields))


def assign_ids(chunks, fields=None, id_len=None, in_place=False):
    """给 chunk 列表重算内容哈希 id。

    返回 (new_chunks, duplicates)；duplicates = {id: [该 id 的 chunk 序号]}（内容
    全同的块会撞 id——这是真重复内容，须在切块侧处理，本模块不搞 -SC 式后缀）。
    in_place=False 时返回浅拷贝（dict(chunk)），不动入参。
    """
    out, seen = [], {}
    for i, c in enumerate(chunks):
        nc = dict(c) if not in_place else c
        cid = stable_id(c, fields, id_len)
        nc["id"] = cid
        out.append(nc)
        seen.setdefault(cid, []).append(i)
    duplicates = {k: v for k, v in seen.items() if len(v) > 1}
    return out, duplicates


def find_duplicate_ids(chunks):
    """按 chunk 现有 id 字段查重 → {id: [序号]}（嵌入入口跑前自检用）。"""
    seen = {}
    for i, c in enumerate(chunks):
        seen.setdefault(c.get("id"), []).append(i)
    return {k: v for k, v in seen.items() if len(v) > 1}


def diff_chunks(old, new, id_fields=None, locator_fields=None, id_len=None):
    """新旧 chunk 集合增量对比（按内容哈希 id；定位键归并变更）。

    old/new：chunk dict 列表（id 字段忽略，内部重算，保证口径一致）。
    返回 dict：
      added/changed/removed/tasks（见模块 docstring）、unchanged 数量、
      任务数 summary 与 collisions（新集合内部 id 撞车，同 assign_ids 语义）。
    定位键多对一歧义：旧侧同定位键多条时按首次出现配对，其余仍记 removed。
    """
    old_by_id = {stable_id(c, id_fields, id_len): c for c in old}
    new_assigned, collisions = assign_ids(new, id_fields, id_len)
    new_ids = {c["id"] for c in new_assigned}

    removed_pool = [c for c in old if stable_id(c, id_fields, id_len) not in new_ids]
    old_by_locator = {}
    for c in removed_pool:
        old_by_locator.setdefault(locator_key(c, locator_fields), c)

    added, changed = [], []
    for c in new_assigned:
        if c["id"] in old_by_id:
            continue  # unchanged
        loc = locator_key(c, locator_fields)
        if loc in old_by_locator:
            oc = old_by_locator.pop(loc)
            changed.append({"old_id": oc.get("id"), "new_id": c["id"], "old": oc, "new": c})
        else:
            added.append(c)
    removed = list(old_by_locator.values())
    unchanged = len(new_assigned) - len(added) - len(changed)
    tasks = [c for c in added] + [p["new"] for p in changed]
    return {
        "old_total": len(old), "new_total": len(new_assigned),
        "unchanged": unchanged, "added": added, "changed": changed, "removed": removed,
        "tasks": tasks, "collisions": collisions,
    }


def summary_lines(diff):
    """diff 摘要行（人读/落档两用）。"""
    return [
        "旧 %d 块 → 新 %d 块：不变 %d，新增 %d，变更 %d，删除 %d" % (
            diff["old_total"], diff["new_total"], diff["unchanged"],
            len(diff["added"]), len(diff["changed"]), len(diff["removed"])),
        "待嵌入任务 %d 块（新增 %d + 变更 %d）；新集合内部 id 撞车 %d 组" % (
            len(diff["tasks"]), len(diff["added"]), len(diff["changed"]), len(diff["collisions"])),
    ]


def write_jsonl(path, items):
    with open(path, "w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="内容哈希稳定 id 计算 + 新旧 chunk 集合增量 diff（纯本地，零 API）",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog="""示例：
  # 只重算 id（新语料切块后第一步）：
  python3 chunk_id.py --new new.jsonl --emit-assigned new_with_ids.jsonl
  # 增量对比并出嵌入任务清单：
  python3 chunk_id.py --old old.jsonl --new new.jsonl --emit-tasks tasks.jsonl
  # 特殊语料换参哈希/定位字段（如速查行级加 line_no）：
  python3 chunk_id.py --old o.jsonl --new n.jsonl --locator-fields layer,src,section,line_no
""")
    ap.add_argument("--new", required=True, help="新 chunk 集 jsonl（必填）")
    ap.add_argument("--old", help="旧 chunk 集 jsonl（给了才做增量 diff，否则只算 id）")
    ap.add_argument("--id-fields", help="参哈希字段清单（逗号分隔；默认取 pipeline_config）")
    ap.add_argument("--locator-fields", help="定位键字段清单（逗号分隔；默认取 pipeline_config）")
    ap.add_argument("--id-len", type=int, help="id 截短长度（默认取 pipeline_config）")
    ap.add_argument("--config", help="JSON 配置文件（默认值之外再覆盖 id_fields 等）")
    ap.add_argument("--emit-assigned", metavar="PATH", help="写出带新 id 的新集合 jsonl")
    ap.add_argument("--emit-tasks", metavar="PATH", help="写出待嵌入任务清单 jsonl（added+changed）")
    ap.add_argument("--summary", metavar="PATH", help="diff 摘要落档 JSON")
    ap.add_argument("--json", action="store_true", help="diff 结果全文机读输出（含各分支明细）")
    args = ap.parse_args(argv)

    cfg = pipeline_config.load_config(args.config)
    id_fields = args.id_fields.split(",") if args.id_fields else cfg["id_fields"]
    locator_fields = args.locator_fields.split(",") if args.locator_fields else cfg["locator_fields"]
    id_len = args.id_len or cfg["id_len"]
    if not 8 <= id_len <= 64:
        ap.error("--id-len 须在 8..64（sha256 十六进制 64 位内截短）")

    from embed_common import load_jsonl  # 局部 import：CLI 才需要，库调用零依赖
    new_chunks = load_jsonl(args.new)

    assigned, dups = assign_ids(new_chunks, id_fields, id_len)
    if dups:
        print("[警告] 新集合内部 id 撞车 %d 组（字段清单区分度不足或内容真重复）：" % len(dups))
        for cid, idxs in list(dups.items())[:5]:
            print("  id=%s ×%d（行号 %s…）" % (cid, len(idxs), ",".join(map(str, idxs[:5]))))
        print("  处置：扩 id_fields（如加 line_no/doc），或切块侧去重；本工具不做后缀式消歧")
    if args.emit_assigned:
        write_jsonl(args.emit_assigned, assigned)
        print("[写出] 带新 id 新集合 %d 行 → %s" % (len(assigned), args.emit_assigned))

    if not args.old:
        print("[id] %d 块全部重算 id（id_len=%d，fields=%s）" % (len(assigned), id_len, ",".join(id_fields)))
        return 0

    old_chunks = load_jsonl(args.old)
    diff = diff_chunks(old_chunks, new_chunks, id_fields, locator_fields, id_len)
    for line in summary_lines(diff):
        print("[diff] %s" % line)
    if args.emit_tasks:
        write_jsonl(args.emit_tasks, diff["tasks"])
        print("[写出] 待嵌入任务 %d 块 → %s" % (len(diff["tasks"]), args.emit_tasks))
    slim = {k: diff[k] for k in ("old_total", "new_total", "unchanged")}
    slim["added"] = [c["id"] for c in diff["added"]]
    slim["changed"] = [{"old_id": p["old_id"], "new_id": p["new_id"]} for p in diff["changed"]]
    slim["removed"] = [c.get("id") for c in diff["removed"]]
    slim["tasks"] = len(diff["tasks"])
    if args.json:
        print(json.dumps(diff, ensure_ascii=False, indent=1))
    if args.summary:
        with open(args.summary, "w", encoding="utf-8") as f:
            json.dump(slim, f, ensure_ascii=False, indent=1)
        print("[写出] diff 摘要 → %s" % args.summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
