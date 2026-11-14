#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""装载预检.py —— 装库内存预估闸（排序优化四期 P1 #5，2026-10-03 施工）

口径依据：运营/排序优化四期提升计划-交接-20261003.md #5 + 过程日志一节19 窗后事故
（swap 4G 勘正在档）——装载全库的评测永不上 2C2G 云端。本闸装在一切"整库装载"
入口（建库/scripts/retrieve.py 的 load_library、deploy_check.py 核对项⑦）之前：
预估峰值 > MemAvailable 即 loud 拒载，防再一次把机器拖进 swap。

纯标准库；绝不装载库文件（stat + 读 sidecar meta json + 读首行即出预估）：
    peek_store(path)          —— 探库形：bin 镜像口径优先，行式首行推形回落
    peek_mirror(path)         —— bin 镜像对探形（rag sidecar 同契约校验；坏返 None）
    peak_bytes_from(s,r,d)    —— 峰值预估公式（两分支取大 + 余量）
    estimate_peak_bytes(path) —— peek_store → peak_bytes_from
    mem_available_bytes()     —— /proc/meminfo MemAvailable（不可读返 None）
    ensure_load_feasible(p,t) —— 闸门本体

2026-10-26 估算面现代化（过程日志 176 债清账/235③ 即办）：现产行式件
embeddings.jsonl 已是锚占位空件（库以 f32.bin+meta.json 镜像对为装载面，
82,232 现产形态），行式首行估算推不出库形（rows_est=0）——peek_store 升
bin 镜像口径优先（meta count/dim=faiss ntotal 持久面 + f32.bin 长度自证 +
源过期校验，契约与 rag._try_load_sidecar 同源），行式首行估算保留为二级
回落（镜像缺席/过期/坏时语义与 2026-10-03 版一致）。

公式：max(int(size*2.5), rows*dim*4*2) + HEADROOM_BYTES（两分支与余量不变）
    - size*2.5 分支：JSON 文本驻留 + dict/tuple 解析膨胀的粗放上界
      （整库装载过程 Python 对象膨胀实测约 2-2.5 倍于读入体积）；
      size 口径随 peek src：镜像形态=bin+meta 两件字节和（装载实际读入量），
      行式回落=jsonl 字节（原语义）；
    - rows*dim*4*2 分支：归一化 float 向量原生驻留（rows*dim*4B）×2
      （装载瞬间原始容器与归一化向量并存）。
"""
import json
import os

RED_LINE = "装载全库的评测永不上 2C2G 云端（过程日志一节19 立规）"
HEADROOM_BYTES = 100 * 1024 * 1024      # 100MB 常态余量（解释器/页缓存抖动带）
_PEEK_FIRST_LINE_CAP = 1 << 20          # 首行读取上限 1MB（超出=截断，估偏保守）
# bin 镜像 sidecar 两件后缀（与 rag.sidecar_paths/SIDECAR_SUFFIX 同值——本件
# 纯标准库不 import rag，改后缀须两处同步；2026-10-26 估算面现代化引入）
_SIDECAR_BIN_SUFFIX = ".f32.bin"
_SIDECAR_META_SUFFIX = ".f32.meta.json"


class MemoryPreflightError(RuntimeError):
    """装载内存预估闸拦截（est>avail 且未设 QA_BOT_MEM_FORCE=1 豁免）。"""


def peek_mirror(store_path):
    """bin 镜像对探形（绝不装载）→ {"count","dim","bin_bytes","meta_bytes"} / None。

    校验契约与 rag._try_load_sidecar 同源（=装载真会走镜像的充分条件面）：
    meta version==2、count/dim 合法、源 size/mtime 与 meta 记录一致（在飞
    续写/换库=过期）、f32.bin 长度==count×dim×4；任何不符 → None，调用方
    回退行式估算——估算面与 rag 装载面同判（镜像过期时 rag 也退 jsonl 行装，
    估算若仍按镜像=漏拦）。rows 长度深校验（len(rows)==count）须整解析
    meta（百 MB 级 json），估算面省略——宁大勿漏由公式保守分支兜底。
    """
    try:
        with open(store_path + _SIDECAR_META_SUFFIX, encoding="utf-8") as f:
            meta = json.load(f)
        if not isinstance(meta, dict) or meta.get("version") != 2:
            return None
        count, dim = meta.get("count"), meta.get("dim")
        if (not isinstance(count, int) or isinstance(count, bool) or count < 0
                or not isinstance(dim, int) or isinstance(dim, bool) or dim <= 0):
            return None
        st = os.stat(store_path)
        if (meta.get("src_size") != st.st_size
                or meta.get("src_mtime_ns") != st.st_mtime_ns):
            return None
        bin_bytes = os.path.getsize(store_path + _SIDECAR_BIN_SUFFIX)
        if bin_bytes != count * dim * 4:
            return None
        return {"count": count, "dim": dim, "bin_bytes": bin_bytes,
                "meta_bytes": os.path.getsize(store_path + _SIDECAR_META_SUFFIX)}
    except (OSError, ValueError):
        return None


def peek_store(path):
    """stat 推库形（绝不装载）；bin 镜像口径优先、行式首行推形二级回落。

    → 一级（镜像，2026-10-26）：peek_mirror 命中 →
      {"size"=bin+meta 字节和（装载实际读入两件量）、"first_line_bytes"=0、
       "rows_est"=count（faiss ntotal 持久同源面）、"dim"、"src"="mirror"}；
    → 二级（行式回落）：镜像缺席/过期/坏 → stat+读首行推
      {"size", "first_line_bytes"(含行尾 \\n), "rows_est"(=size//首行字节),
       "dim"(首行 embedding 维度；坏行/无 embedding=None), "src"="lines"}。
    首行超上限被截断时 first_line_bytes 偏小 → rows_est 偏大 → 预估偏保守（安全向）。
    """
    mir = peek_mirror(path)
    if mir is not None:
        return {"size": mir["bin_bytes"] + mir["meta_bytes"], "first_line_bytes": 0,
                "rows_est": mir["count"], "dim": mir["dim"], "src": "mirror"}
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        chunk = f.readline(_PEEK_FIRST_LINE_CAP)
    dim = None
    try:
        obj = json.loads(chunk)
        if isinstance(obj, dict) and isinstance(obj.get("embedding"), list) \
                and obj["embedding"]:
            dim = len(obj["embedding"])
    except (json.JSONDecodeError, ValueError):
        pass
    flb = len(chunk)
    return {"size": size, "first_line_bytes": flb,
            "rows_est": (size // flb) if flb else 0, "dim": dim, "src": "lines"}


def peak_bytes_from(size, rows, dim):
    """峰值预估（两分支取大 + 100MB 余量）。

    真实库自证（2026-10-02 库态实测）：embeddings.jsonl=1,322,357,108B、
    首行 26,211B → rows_est=50,450、dim=1024，公式结果≈3252MB，≥ 实测装载
    峰值带 800MB-1.2G（窗后事故勘正在档）——闸取保守上界，宁误拦不漏拦。
    2026-10-26 镜像口径：现产 82,232 形态 size=bin+meta≈459MB、rows=count
    → est≈1194MB，仍盖住镜像装载实测峰值带（估算面现代化，过程日志 176 清账）。
    """
    tuple_branch = int(rows) * int(dim) * 4 * 2 if dim else 0
    return max(int(size * 2.5), tuple_branch) + HEADROOM_BYTES


def estimate_peak_bytes(path):
    """库路径 → 峰值预估 bytes（peek_store 推形 + peak_bytes_from 计算）。"""
    info = peek_store(path)
    return peak_bytes_from(info["size"], info["rows_est"], info["dim"])


def mem_available_bytes():
    """/proc/meminfo MemAvailable → bytes；不可读/无该键 → None（调用方放行）。"""
    try:
        with open("/proc/meminfo", encoding="ascii", errors="replace") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024   # meminfo 数值单位 kB
    except (OSError, ValueError, IndexError):
        return None
    return None


def _mb(n):
    """bytes → 整数 MB（1024 进制口径；真实库 est=3252MB 即此口径）。"""
    return int(n) // (1024 * 1024)


def ensure_load_feasible(path, tag):
    """装载闸门：est>avail 且未 FORCE → raise MemoryPreflightError；其余放行。

    - MemAvailable 不可读（非 Linux/权限）→ 打印跳过、放行（无据不拦）；
    - est>avail 且 env QA_BOT_MEM_FORCE=1 → 打 [装载预检] FORCE 行后放行
      （豁免须显式设 env，留审计迹）；
    - est>avail → raise（信息含 est/avail MB 数字、tag、红线句）；
    - 否则打 [装载预检] ok=1 行（内存充足=调用方行为零变化，仅多一行日志）。
    """
    est = estimate_peak_bytes(path)
    avail = mem_available_bytes()
    if avail is None:
        print("[装载预检] MemAvailable 不可读，跳过判定")
        return
    if avail < est:
        if os.environ.get("QA_BOT_MEM_FORCE") == "1":
            print("[装载预检] FORCE tag=%s est=%dMB avail=%dMB（QA_BOT_MEM_FORCE=1 显式豁免）"
                  % (tag, _mb(est), _mb(avail)))
            return
        raise MemoryPreflightError(
            "装载内存预估闸拦截：tag=%s 预估峰值 est=%dMB > 可用 MemAvailable "
            "avail=%dMB（库 %s）——%s（窗后事故 swap 4G 勘正在档；确属有意冒进可 "
            "QA_BOT_MEM_FORCE=1 豁免）"
            % (tag, _mb(est), _mb(avail), os.path.basename(str(path)), RED_LINE))
    print("[装载预检] tag=%s est=%dMB avail=%dMB ok=1" % (tag, _mb(est), _mb(avail)))
