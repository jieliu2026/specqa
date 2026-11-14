#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""miss_attribution.py —— rag=miss / low_score 低分拦截 / 低分可疑命中 归因观测工具（零 API、纯标准库）。

定位：运营回路"指标→扩库"的证据采集器。对 qa-bot 服务日志做离线归因：
把 rag=miss / rag=low_score / rag=coverage_miss 与低分/可疑 hit 逐条配对成
问答轮次，按启发式预填归因（低分闸门拦截 / 负控覆盖闸拦截 / 语料未覆盖 /
检索失败 / 排序失利），输出 markdown 底稿供人工复核。
只读日志文本，零 API、零计费、零网络、零 git、零密值。

用法：
    python3 miss_attribution.py <日志路径> [-o 输出md] [--jsonl [路径]] [阈值参数]
    例：python3 miss_attribution.py <repo>/server.log \
            -o <repo>/运营/归因底稿-20260918.md
    不给 -o 时打印到 stdout。给 -o 时自动伴生机读采集 sidecar（同名
    .md→.low_score.jsonl，--jsonl 路径 可改落点）：每行一条 JSON
    {source_file,ts,line_no,rag,top1,score,score_type,thr,q_prefix,note}，
    只收 rag=low_score 轮（top1=触发闸门的余弦原始分，score_type=
    gate_cosine_max，与 运营/阈值标定样本-20260922.jsonl 的 score/score_type
    键名口径对齐，人工复核后可直接逐行并入）；供 建库/logs/阈值ROC标定-
    20260922.md §六.3 按月聚合线上 low_score top1 分布（样本≥30 并入重算）。
    **hit 态 top1=通道排序分（hybrid RRF ~0.03 量级），两态 top1 语义不同，
    hit 行一律不入采集**。底稿 md 内亦附同一份 jsonl 代码块（§五）。

输入日志形态（本机 server.log 与云端 journalctl 导出文本均可，时间戳前缀可选）：
    [chat] ip=1.2.3.4 auth=body in_chars=19 rag=hit|miss|low_score|off ttfb=1.2s
        dur=14.9s usage={...} cancelled=0 q="查询摘要" top1=0.5678 cc=off ab=off
                                                          # 轮次锚点（四态）
    [chat] 行按 k=v 逐字段解析、字段顺序与增删无关：批1 形态（无 auth=）、
    批2 形态（ip= 与 in_chars= 之间插 auth=，尾附 ttfb=/cancelled=/cc=/ab=）
    均兼容——2026-09-22 教训：定位式正则会被服务端加字段静默打断整行。
    [rag-embed] chars=19 tokens=11 ok=1 dim=1024 dur=6.61s                # ok=0 时带 err=Xxx
    [rag] retrieve ok chars=748 blocks=5      / [rag] retrieve miss err=Xxx
    [rag] low_score cos=0.3123 thr=0.40（…）  # 低分闸门拦截行（检索到但分数不够）
    [rag] coverage_miss words=A/B cos=0.5123 thr=0.40（…）
                                              # 负控覆盖闸拦截行（S1 治理丙，
                                              # 2026-10-01 教识：题面含库外域
                                              # 词而证据集全缺；行可带
                                              # [trace:8hex] 前缀，search 容忍）
    [rerank_gate] ts=2026-10-15 12:00:01 q=<12hex> trace=<8hex> decision=refuse
        max=0.6123 thr=0.75                  # rerank 拒答闸 journal 行（0.75 档，
                                              # 2026-10-12 决策；2026-10-15 补丁纳入
                                              # 归因配对：decision=refuse|pass|skip，
                                              # skip 带 err= 无 thr；另有 skip=cap
                                              # warn 行（无 decision=）不配对）
    [rag-store] loaded=14055 bad_lines=0 dim=1024 [missing=1]
    INFO: 1.2.3.4:39170 - "POST /api/chat HTTP/1.1" 200 OK               # 会话线索（ip:port）
    可选扩展字段（出现即自动采用，向前兼容）：
      q="查询文本" / top1=0.5678 / score=0.56 / scores=[0.56,0.5] / sources=N 或 sources=[..]

轮次配对：按行序，[chat] 行结算其前未消费的 [rag-embed]/[rag] retrieve 事件
（单用户低并发场景准确；高并发日志可能串轮，属已知局限，人工复核兜底）。

归因规则（写死启发式，预填仅供参考，明细逐条留"人工复核"空栏）：
  1) 低分闸门拦截（rag=low_score，2026-09-21 批1 新增日志态）：检索链路正常、
     检索到了，但证据集最高余弦原始分低于服务端 score_threshold 阈值（现值
     0.40）→ 服务端不注入证据退裸答。属"语料未覆盖"近类但单列计数，
     不并入 miss（miss=链路异常退裸答，两者严格区分）。
  1b) 负控覆盖闸拦截（rag=coverage_miss，S1 治理丙 2026-09-28 新增日志态、
      2026-10-01 教识归因）：题面含库外域安全词形（负控词表）而证据集全部
      块文本不含该词——检索面零支撑的硬拒，不注入证据退裸答。按设计应拒的
      库外域题；域内题误伤须人工复核（S1 误伤面观测）。单列计数，不并入
      miss、亦不入 low_score 阈值标定采集（闸是词面闸非分数闸）。
  1c) rerank 拒答闸拦截（rag=rerank_refused，2026-10-12 0.75 档决策态、
      2026-10-15 补丁纳入归因）：hit 路径检索完成后 rerank 池 max<分面阈值
      （vac=0.75 / prac=0.4923）→ 转 rerank_refused（不注入证据退裸答，与
      low_score 家族同构）。判定分在配对 [rerank_gate] 行（max=/thr=）；
      [chat] 行 top1 仍=原 hit 通道排序分（RRF 量级），与闸门余弦不可比。
      单列计数，不并入 miss、不计入 miss 率；误拦面（域内题被拒）须人工复核。
  2) 检索失败：rag=miss 的各种形态（embed ok=0 / retrieve err / 无 embed 行
     （库空、查询构造为空）/ embed 成功但无 retrieve ok 行（证据超限））；
     以及 hit 但检索输入异常（embed chars≤阈值，或 in_chars 很大而 embed chars
     极小=多轮上下文丢失）。
  3) 排序失利：rag=hit 但证据弱——blocks<阈值 / evidence chars<阈值 /
     top1<阈值（仅 retrieve/embed 行分数字段；hit 态 [chat] 行 top1=通道排序分
     （hybrid RRF ~0.03 量级），与余弦刻度阈值不可比，不作此判——两态 top1
     语义不同勿混，闸门余弦口径只认 low_score 态）/ sources 空。
  4) 语料未覆盖：查询文本可得且无任何在域信号（3GPP 规范号 / 电信词表 /
     字母数字混合技术标识），命中弱时优先判库外题。q= 摘要已随上云第 2 批
     打点落 [chat] 行（清洗+截断 80 字符），缺文本的旧日志不误判、
     退规则 3 并注明待人工。

阈值参数（默认值按 2026-09-18 基线标定，可按迭代调整）：
    --low-score 0.30          top1 分数低于此 → 命中分过低（仅当日志含分数时生效）
    --min-embed-chars 10      embed chars ≤ 此 → 检索输入退化（查询向量化只剩几个字）
    --min-evidence-chars 300  retrieve evidence chars < 此 → 证据过短
    --min-blocks 3            retrieve blocks < 此 → 证据块过少（默认 topk=5）

周报/迭代轮使用说明：
  - 每周五运营周报前：云端导出近 7 天日志（导出动作归运维流程，本脚本只吃文本）
      journalctl -u qa-bot --since "7 days ago" --no-pager > /tmp/qa-bot-week.log
    然后本机/云端任一位跑：
      python3 建库/scripts/miss_attribution.py /tmp/qa-bot-week.log \
          -o 运营/归因底稿-YYYYMMDD.md
    周报"miss 模式点名"节引用本期底稿；与上期底稿手工对比填周环比；
    同类归因连续两周出现（周报 v2 迭代提案闸）→ 起草二期语料提案待决策。
  - 每日 9:30 迭代评估轮：信号源之一为昨日云端日志
      journalctl -u qa-bot --since yesterday --no-pager > /tmp/qa-bot-day.log
    同法跑一次，底稿作迭代假设证据（只提案不实施；上线/花钱>0.01元/动云端三道闸归用户）。
  - 复核口径：预填只是启发式；明细每条的"人工复核"栏由人填结论，
    语料未覆盖类确认后才进"指标→扩库"回路的语料提案。
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime as _dt
import json
import re
import sys
from typing import Dict, List, Optional

# ----------------------------- 默认阈值 -----------------------------
DEFAULT_LOW_SCORE = 0.30        # top1 余弦分低于此 → 命中分过低（日志含分数时生效）
DEFAULT_MIN_EMBED_CHARS = 10    # embed chars ≤ 此 → 检索输入退化
DEFAULT_MIN_EVIDENCE_CHARS = 300  # evidence chars < 此 → 证据过短
DEFAULT_MIN_BLOCKS = 3          # blocks < 此 → 证据块过少
QUERY_SUMMARY_LEN = 60          # 查询摘要脱长上限
# 注：embed dur 只进"检索侧证据"展示、不作触发条件——端点慢是常态（基线 6.5s），
# 绝对阈值会大面积误报；真正的失败信号是 ok=0/err。

CAT_LOW_SCORE = "低分闸门拦截"
CAT_COVERAGE_GATE = "负控覆盖闸拦截"   # S1 治理丙 coverage_miss 态（2026-10-01 教识）
CAT_RERANK_GATE = "rerank 拒答闸拦截"  # rerank_refused 态（0.75 档，2026-10-15 补丁）
CAT_COVERAGE = "语料未覆盖"
CAT_RETRIEVAL = "检索失败"
CAT_RANKING = "排序失利"

# ----------------------------- 行级解析 -----------------------------
# 时间戳前缀（journalctl short-iso / 默认 syslog / 常见 "YYYY-MM-DD HH:MM:SS,ms"），可缺省
_TS_RES = (
    re.compile(r"^\s*(?P<ts>\d{4}-\d{2}-\d{2}[T ][\d:]{8}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)\s+"),
    re.compile(r"^\s*(?P<ts>[A-Z][a-z]{2}\s+\d{1,2}\s+[\d:]{8}(?:\.\d+)?)\s+"),
)
# 各打点行（用 search 而非 match：容忍 journalctl "host app[pid]:" 类前缀）
# [chat] 行只锚 "[chat]" 标签，字段（ip/auth/in_chars/rag/ttfb/dur/usage/
# cancelled/q/top1/cc/ab…）一律走 KV_RE 逐字段解析——批2 在 ip= 与 in_chars=
# 之间插了 auth=，定位式正则曾整行静默漏配（2026-09-22 low_score 教识销账
# 教训：服务端加字段不得打断归因解析；rag= 未知新值也不再丢行，单列"其他态"）。
CHAT_RE = re.compile(r"\[chat\](?P<rest>\s.*)?$")
KNOWN_RAG_STATES = ("hit", "miss", "low_score", "coverage_miss", "rerank_refused", "off")
# rerank 拒答闸 journal 行（2026-10-12 0.75 档决策；2026-10-15 补丁纳入配对）：
# "[rerank_gate] ts=… q=<12hex> trace=<8hex> decision=refuse|pass|skip [err=…]
# [max=0.6123] thr=0.75"——行首锚 [rerank_gate] 标签，字段走 KV 逐字段解析后
# 定向校验 decision∈{refuse,pass,skip} 才配对（skip=cap warn 行无 decision=
# 键、天然不配对；ts= 值含空格不影响其余字段定向取值）。
RERANK_GATE_RE = re.compile(r"\[rerank_gate\]\s+(?P<rest>.*)$")
EMBED_RE = re.compile(r"\[rag-embed\]\s*(?P<rest>.*)$")
RETRIEVE_RE = re.compile(r"\[rag\]\s+retrieve\s+(?P<outcome>ok|miss)\b\s*(?P<rest>.*)$")
LOW_SCORE_RE = re.compile(r"\[rag\]\s+low_score\s+(?P<rest>.*)$")
# 负控覆盖闸拦截行（S1 治理丙，2026-10-01 教识）：[rag] coverage_miss words=A/B
# cos=… thr=…（中文注记）——words 无引号、'/' 分隔，cos 可为 na（gate_cosine 缺值）
COVERAGE_MISS_RE = re.compile(r"\[rag\]\s+coverage_miss\s+(?P<rest>.*)$")
STORE_RE = re.compile(r"\[rag-store\]\s*(?P<rest>.*)$")
ACCESS_RE = re.compile(r"(?P<addr>\S+) - \"POST /api/chat HTTP/1\.1\" (?P<status>\d+)")
STARTUP_RAG_RE = re.compile(r"\[startup\]\s+rag=(?P<state>on|off)\b\s*(?P<rest>.*)$")
KV_RE = re.compile(r"(\w+)=(\"[^\"]*\"|\[[^\]]*\]|\S+)")


def strip_timestamp(line: str) -> str:
    """剥离行首时间戳前缀 → 时间戳字符串（无则空串）。"""
    line = line.rstrip("\n")
    for rex in _TS_RES:
        m = rex.match(line)
        if m:
            return m.group("ts")
    return ""


def parse_kv(body: str) -> Dict[str, str]:
    """`k=v` 串 → dict（值不含空格；引号/方括号值原样保留）。"""
    return {k: v for k, v in KV_RE.findall(body)}


def _unquote(v: str) -> str:
    if len(v) >= 2 and v[0] == "\"" and v[-1] == "\"":
        return v[1:-1]
    return v


def _to_int(v: Optional[str]) -> Optional[int]:
    try:
        return int(str(v))
    except (TypeError, ValueError):
        return None


def _first_float(v: Optional[str]) -> Optional[float]:
    if v is None:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", v)
    return float(m.group(0)) if m else None


@dataclasses.dataclass
class Turn:
    """一个问答轮次 = 一条 [chat] 行 + 其前配对的检索侧事件。"""
    idx: int                      # 轮次序号（1 起）
    line_no: int                  # [chat] 行号（1 起，无时间戳日志的定位锚）
    ts: str = ""                  # [chat] 行时间戳（无则空）
    ip: str = ""
    in_chars: Optional[int] = None
    rag: str = ""
    dur: Optional[float] = None
    embeds: List[Dict[str, str]] = dataclasses.field(default_factory=list)
    retrieve: Optional[Dict[str, str]] = None   # 含 outcome=ok|miss|low_score
    gate: Optional[Dict[str, str]] = None       # 配对 [rerank_gate] 行（decision=*
                                                # 才收；2026-10-15 补丁，rerank_refused
                                                # 轮的判定分 max=/thr= 来源）
    access: str = ""              # uvicorn 访问行（ip:port status），会话线索
    query: str = ""               # 可选：日志若含 q="..." 查询文本
    top1: Optional[float] = None  # 可选：top1/score/scores 首值
    top1_src: str = ""            # top1 取值来源：retrieve/embed/chat（语义分型用：
    # hit 态 [chat] 行 top1=通道排序分（hybrid RRF ~0.03 量级），low_score 态
    # [chat] 行 top1=闸门余弦原始分——两态语义不同，余弦阈值只可比后者/retrieve 分）
    sources_count: Optional[int] = None  # 可选：sources=N 或 sources=[..] 计数

    # -- 派生证据（展示用） ---------------------------------------------
    def last_ok_embed(self) -> Optional[Dict[str, str]]:
        for e in reversed(self.embeds):
            if e.get("ok") == "1":
                return e
        return None

    def embed_desc(self) -> str:
        if not self.embeds:
            return "无 embed 行"
        parts = []
        for e in self.embeds:
            parts.append("chars={chars} ok={ok}{tok}{dim}{dur}{err}".format(
                chars=e.get("chars", "?"), ok=e.get("ok", "?"),
                tok=f" tokens={e['tokens']}" if e.get("tokens") else "",
                dim=f" dim={e['dim']}" if e.get("dim") else "",
                dur=f" dur={e['dur']}" if e.get("dur") else "",
                err=f" err={e['err']}" if e.get("err") else ""))
        return "；".join(parts)

    def retrieve_desc(self) -> str:
        if self.retrieve is None:
            return "无 retrieve 行"
        r = self.retrieve
        if r.get("outcome") == "ok":
            return f"ok chars={r.get('chars', '?')} blocks={r.get('blocks', '?')}"
        if r.get("outcome") == "low_score":
            return f"low_score cos={r.get('cos', '?')} thr={r.get('thr', '?')}"
        if r.get("outcome") == "coverage_miss":
            words = "/".join(r.get("words") or []) or "?"
            return f"coverage_miss words={words} cos={r.get('cos', '?')} thr={r.get('thr', '?')}"
        return f"miss err={r.get('err', '?')}"


@dataclasses.dataclass
class Meta:
    """日志整体元信息。"""
    n_lines: int = 0
    n_chat: int = 0
    has_ts: bool = False
    startup_rag: str = ""         # 最近一次 [startup] rag=on|off（附 rest）
    last_store: str = ""          # 最近一次 [rag-store] 行（库状态线索）


def parse_log(lines: List[str]):
    """日志行列表 → (turns, meta)。配对：[chat] 行结算其前未消费的 embed/retrieve。"""
    meta = Meta(n_lines=len(lines))
    turns: List[Turn] = []
    pending_embeds: List[Dict[str, str]] = []
    pending_retrieve: Optional[Dict[str, str]] = None
    pending_gate: Optional[Dict[str, str]] = None   # [rerank_gate] 行（2026-10-15 补丁）
    pending_access = ""
    last_store_rest = ""
    for no, raw in enumerate(lines, 1):
        if not raw.strip():
            continue
        ts = strip_timestamp(raw)
        if ts:
            meta.has_ts = True
        m = STARTUP_RAG_RE.search(raw)
        if m:
            meta.startup_rag = f"rag={m.group('state')} {m.group('rest')}".strip()
            continue
        m = STORE_RE.search(raw)
        if m:
            last_store_rest = m.group("rest").strip()
            meta.last_store = last_store_rest
            continue
        m = EMBED_RE.search(raw)
        if m:
            kv = parse_kv(m.group("rest"))
            pending_embeds.append(kv)
            continue
        m = RETRIEVE_RE.search(raw)
        if m:
            kv = parse_kv(m.group("rest"))
            kv["outcome"] = m.group("outcome")
            pending_retrieve = kv
            continue
        m = LOW_SCORE_RE.search(raw)
        if m:
            # [rag] low_score cos=… thr=…（…中文注记）：定向取 cos/thr 数值
            # （整行 parse_kv 会把中文注记吞进 thr 值），配对口径同 retrieve 行
            kv = {"outcome": "low_score"}
            for k in ("cos", "thr"):
                mm = re.search(r"\b%s=([\d.]+)" % k, m.group("rest"))
                if mm:
                    kv[k] = mm.group(1)
            pending_retrieve = kv
            continue
        m = COVERAGE_MISS_RE.search(raw)
        if m:
            # [rag] coverage_miss words=A/B cos=… thr=…（…中文注记）：定向取
            # words/cos/thr（words='/' 分隔、cos 可为 na），配对口径同 low_score 行
            kv = {"outcome": "coverage_miss"}
            mm = re.search(r"\bwords=([^\s（(]+)", m.group("rest"))
            if mm:
                kv["words"] = [w for w in mm.group(1).split("/") if w]
            for k in ("cos", "thr"):
                mm = re.search(r"\b%s=([\d.]+|na)\b" % k, m.group("rest"))
                if mm:
                    kv[k] = mm.group(1)
            pending_retrieve = kv
            continue
        m = RERANK_GATE_RE.search(raw)
        if m:
            kv = parse_kv(m.group("rest"))
            if kv.get("decision") in ("refuse", "pass", "skip"):
                pending_gate = kv
            # decision 取值异常的行不配对（防服务端未来改形态串轮）
            continue
        m = ACCESS_RE.search(raw)
        if m:
            pending_access = f"POST /api/chat {m.group('addr')} -> {m.group('status')}"
            continue
        m = CHAT_RE.search(raw)
        if m:
            chat_kv = parse_kv(m.group("rest") or "")
            if not chat_kv.get("rag"):
                continue  # 带 [chat] 标签却无 rag= 字段：非轮次锚点行，跳过
            t = Turn(idx=len(turns) + 1, line_no=no, ts=ts, ip=chat_kv.get("ip", ""),
                     in_chars=_to_int(chat_kv.get("in_chars")), rag=chat_kv["rag"],
                     dur=_first_float(chat_kv.get("dur")),
                     embeds=pending_embeds, retrieve=pending_retrieve,
                     gate=pending_gate, access=pending_access)
            # 可选扩展字段（向前兼容）：q / top1 / score / scores / sources
            _kv_srcs = ([("retrieve", t.retrieve or {})]
                        + [("embed", e) for e in t.embeds] + [("chat", chat_kv)])
            for src_name, kv in _kv_srcs:
                q = _unquote(kv.get("q") or kv.get("query") or "")
                if q:
                    t.query = q
                if t.top1 is None:
                    for k in ("top1", "top1_score", "score"):
                        v = _first_float(kv.get(k))
                        if v is not None:
                            t.top1, t.top1_src = v, src_name
                            break
                if t.top1 is None and kv.get("scores"):
                    v = _first_float(kv.get("scores"))
                    if v is not None:
                        t.top1, t.top1_src = v, src_name
                if t.sources_count is None and kv.get("sources") is not None:
                    sv = kv["sources"]
                    t.sources_count = (len(_bracket_items(sv)) if sv.startswith("[")
                                       else _to_int(sv))
            turns.append(t)
            meta.n_chat += 1
            pending_embeds = []
            pending_retrieve = None
            pending_gate = None
            pending_access = ""
            continue
    # 尾部未结算的 pending（无 [chat] 行收口）不算轮次，属残缺事件，忽略
    return turns, meta


def _bracket_items(v: str) -> List[str]:
    inner = v.strip()[1:-1] if v.strip().startswith("[") else v
    return [x for x in inner.split(",") if x.strip()]


# ----------------------------- 在域判定（语料未覆盖启发式） -----------------------------
# 语料域=3GPP 36/38 系（RRC/RRM/PHY 计数）+工信部监管件；仅当日志含查询文本时使用。
_SPEC_NUM_RE = re.compile(r"\b(?:2[578]|3[68])\.\d{3}\b")           # 36.214 / 38.215 / 25.xxx …
_TS_NUM_RE = re.compile(r"\b(?:TS|TR)\s?\d{2,3}\b", re.IGNORECASE)
_TECH_TOKEN_RE = re.compile(  # t310/5G/n78/maxHARQ-Tx（字母数字混合或连字符标识）
    r"\b(?:[A-Za-z]+\d[A-Za-z0-9-]*|\d+[A-Za-z][A-Za-z0-9-]*|[A-Za-z]{2,}-[A-Za-z0-9]+)\b")
_IN_DOMAIN_CJK = (
    "切换", "测量", "邻区", "小区", "载波", "波束", "调度", "重选", "随机接入", "接入网",
    "核心网", "基站", "信道", "功率", "电平", "频段", "频率", "带宽", "时隙", "帧结构",
    "移动性", "注册", "寻呼", "鉴权", "漫游", "计费", "携号", "号码携带", "号码携转",
    "网间结算", "结算", "互联互通", "进网", "电信设备", "干扰", "掉话", "语音", "短信",
    "定位", "计数器", "覆盖", "上行", "下行", "组网", "号段", "增值电信", "许可", "驻留",
    "idle", "attached", "去附着", "附着", "寻呼", "重定向", "聚合", "分流",
)
_IN_DOMAIN_ASCII = frozenset((
    "RSRP", "RSRQ", "SINR", "HARQ", "PRACH", "PUCCH", "PUSCH", "PDSCH", "PDCCH",
    "RRC", "NAS", "AMF", "SMF", "UPF", "GNB", "ENB", "LTE", "NR", "NSA", "TDD",
    "FDD", "QCI", "5QI", "IMEI", "IMSI", "SUPI", "PEI", "URLLC", "EMBB", "MTC",
    "VOLTE", "VONR", "RACH", "BWP", "MIMO", "OFDM", "QAM", "AMBR", "GBR", "SRB",
    "DRB", "RLF", "ANR", "CSI", "SSB", "PLMN", "AUSF", "UDM", "PCF", "NRF",
    "MEC", "AKA", "NSSAI", "EN-DC", "V2X", "SL", "NTN", "RED CAP", "REDCAP",
))


def in_domain_hits(query: str) -> List[str]:
    """查询文本 → 命中的在域信号列表（空=疑似库外题）。"""
    hits: List[str] = []
    hits += _SPEC_NUM_RE.findall(query)
    hits += [m.group(0).upper() for m in _TS_NUM_RE.finditer(query)]
    up = query.upper()
    for kw in _IN_DOMAIN_ASCII:
        if re.search(r"\b%s\b" % re.escape(kw), up):
            hits.append(kw)
    for kw in _IN_DOMAIN_CJK:
        if kw in query:
            hits.append(kw)
    # 字母数字混合技术标识（t310/a3-Offset/5G/n78）算弱在域信号，取前 3 个示意
    tech = [t for t in _TECH_TOKEN_RE.findall(query)
            if not t.isdigit() and len(t) >= 2][:3]
    hits.extend(t for t in tech if t not in hits)
    return hits


# ----------------------------- 归因 -----------------------------
@dataclasses.dataclass
class Options:
    low_score: float = DEFAULT_LOW_SCORE
    min_embed_chars: int = DEFAULT_MIN_EMBED_CHARS
    min_evidence_chars: int = DEFAULT_MIN_EVIDENCE_CHARS
    min_blocks: int = DEFAULT_MIN_BLOCKS


@dataclasses.dataclass
class Finding:
    turn: Turn
    category: str        # 归因分类之一（低分闸门拦截/语料未覆盖/检索失败/排序失利）
    reasons: List[str]   # 触发理由（证据侧）
    note: str            # 预填口径说明（含待人工提示）


def classify_turn(t: Turn, opts: Options) -> Optional[Finding]:
    """单轮 → 归因预填（None=未触发：干净 hit / rag=off / 未知态）。"""
    if t.rag == "off":
        return None
    if t.rag not in KNOWN_RAG_STATES:
        # 未知新态（服务端未来加态）：不猜归因、不丢行——报表"其他未知 rag 态"
        # 单列计数提示人工核（2026-09-22 教识口径：任何 [chat] 态都不得被静默跳过）
        return None
    hard: List[str] = []   # 检索失败信号
    weak: List[str] = []   # 命中质量弱信号

    for e in t.embeds:
        if e.get("ok") == "0":
            hard.append(f"embed ok=0 err={e.get('err', '?')} dur={e.get('dur', '?')}")
    ok_embed = t.last_ok_embed()
    if ok_embed is not None:
        c = _to_int(ok_embed.get("chars"))
        if c is not None and c <= opts.min_embed_chars:
            hard.append(f"embed chars={c}≤{opts.min_embed_chars}（检索输入退化为几个字）")
        elif (c is not None and (t.in_chars or 0) >= 200
              and c <= max(opts.min_embed_chars * 2, (t.in_chars or 0) // 50)):
            hard.append(f"embed chars={c} 远小于 in_chars={t.in_chars}（多轮上下文丢失嫌疑）")

    r = t.retrieve
    if t.rag == "miss":
        if hard:
            return Finding(t, CAT_RETRIEVAL, hard, "embed/输入侧异常，确定性较高")
        if r is not None and r.get("outcome") == "miss":
            return Finding(t, CAT_RETRIEVAL,
                           [f"retrieve miss err={r.get('err', '?')}"] + hard, "检索链路异常")
        if not t.embeds:
            return Finding(t, CAT_RETRIEVAL, ["miss 且无 embed 行"], 
                           "库空/缺失或查询构造为空导致退裸答（对照 [rag-store] 行核实），待人工")
        return Finding(t, CAT_RETRIEVAL, ["embed ok=1 但无 retrieve ok 行"],
                       "证据组装超限或库重载为空，待人工")

    # ---- rag=low_score（低分闸门拦截：单列归因，不并入 miss） ----
    if t.rag == "low_score":
        # 检索链路正常、检索到了，但证据集最高余弦原始分低于服务端
        # score_threshold → 不注入证据退裸答。属"语料未覆盖"近类但单列计数。
        if r is not None and r.get("outcome") == "low_score" and r.get("cos"):
            reasons = [f"low_score cos={r['cos']} thr={r.get('thr', '?')}"
                       "（证据集最高余弦分低于闸门阈值，不注入证据）"]
        elif t.top1 is not None:
            reasons = [f"top1={t.top1:.4f}（闸门触发分=余弦原始分口径，"
                       "低于服务端 score_threshold）"]
        else:
            reasons = ["rag=low_score（无 [rag] low_score 行且 [chat] 行无 top1，"
                       "按轮次锚点口径）"]
        return Finding(t, CAT_LOW_SCORE, reasons,
                       "检索到但分数不够被闸门拦截退裸答；'语料未覆盖'近类但单列计数"
                       "（不并入 miss），复核确认库外题后进指标→扩库提案")

    # ---- rag=coverage_miss（负控覆盖闸拦截：单列归因，不并入 miss） ----
    if t.rag == "coverage_miss":
        # S1 治理丙（2026-09-28 批1 新增日志态，2026-10-01 教识归因）：题面含
        # 库外域安全词形而证据集全部块文本不含该词——检索面零支撑的硬拒，
        # 行为与 low_score 同构（不注入证据退裸答），与 miss（链路异常）严格区分。
        if r is not None and r.get("outcome") == "coverage_miss" and r.get("words"):
            words = "/".join(r["words"])
            reasons = [f"coverage_miss words={words} cos={r.get('cos', '?')} "
                       f"thr={r.get('thr', '?')}（题面库外域词在场、证据集全缺，"
                       "不注入证据）"]
        elif t.top1 is not None:
            reasons = [f"top1={t.top1:.4f}（闸前证据集最大余弦观测值口径）"]
        else:
            reasons = ["rag=coverage_miss（无 [rag] coverage_miss 行且 [chat] 行"
                       "无 top1，按轮次锚点口径）"]
        return Finding(t, CAT_COVERAGE_GATE, reasons,
                       "负控覆盖闸拦截（S1 治理丙）：按设计应拒的库外域题；若系"
                       "域内题误伤须人工复核（S1 误伤面+L2 触发锚①观测口径），"
                       "不计入 miss 率、不入 low_score 阈值标定采集")

    # ---- rag=rerank_refused（rerank 拒答闸拦截：单列归因，不并入 miss） ----
    if t.rag == "rerank_refused":
        # 0.75 档行为级拒答（2026-10-12 决策；2026-10-15 补丁纳入归因）：hit 路径
        # 检索完成后 rerank 池 max<分面阈值 → 转 rerank_refused（不注入证据、不下发
        # sources、裸答流式，与 low_score 家族同构）。判定分在配对 [rerank_gate] 行
        # （max=/thr=）；[chat] 行 top1=原 hit 通道排序分（RRF 量级）不判闸。
        g = t.gate
        if g is not None and g.get("decision") == "refuse":
            reasons = [f"[rerank_gate] decision=refuse max={g.get('max', '?')} "
                       f"thr={g.get('thr', '?')}（rerank 池 max<分面阈值，不注入证据）"]
        elif g is not None:
            reasons = [f"[rerank_gate] decision={g.get('decision')} "
                       f"err={g.get('err', '无')}（配对行非 refuse——串轮或服务端"
                       "状态机变化，待人工）"]
        else:
            reasons = ["rag=rerank_refused（日志未见配对 [rerank_gate] 行，"
                       "按轮次锚点口径，待人工）"]
        return Finding(t, CAT_RERANK_GATE, reasons,
                       "rerank 拒答闸拦截（0.75 档）：检索链路正常、通道排序 hit，"
                       "但 rerank 池 max<分面阈值（vac=0.75/prac=0.4923）转拒答退裸答；"
                       "与 miss（链路异常）严格区分、不计入 miss 率；误拦面（域内题"
                       "被拒）须人工复核")

    # ---- rag=hit ----
    if r is None:
        if hard:
            return Finding(t, CAT_RETRIEVAL, hard, "hit 轮却无 retrieve 行+输入侧异常，配对/日志可疑，待人工")
        return None
    if r.get("outcome") == "miss":
        hard.append(f"配对异常：hit 轮带 retrieve miss err={r.get('err', '?')}")
    else:
        b = _to_int(r.get("blocks"))
        if b is not None and b < opts.min_blocks:
            weak.append(f"blocks={b}<{opts.min_blocks}（证据块过少）")
        c = _to_int(r.get("chars"))
        if c is not None and c < opts.min_evidence_chars:
            weak.append(f"evidence chars={c}<{opts.min_evidence_chars}（证据过短）")
    # hit 态 top1 语义分型（两态勿混）：[chat] 行 hit top1=通道排序分（hybrid RRF
    # ~0.03 量级），与余弦刻度阈值不可比——不作弱信号（否则云端每个 hybrid hit
    # 都被误判"命中分过低"）；闸门余弦口径只认 low_score 态与 retrieve 行分数字段。
    if t.top1 is not None and t.top1 < opts.low_score and t.top1_src != "chat":
        weak.append(f"top1={t.top1:.4f}<{opts.low_score}（命中分过低，{t.top1_src} 行分数）")
    if t.sources_count == 0:
        weak.append("sources 空")
    if hard:
        return Finding(t, CAT_RETRIEVAL, hard + weak, "hit 但检索输入异常")
    if not weak:
        return None
    if t.query:
        dom = in_domain_hits(t.query)
        if not dom:
            return Finding(t, CAT_COVERAGE, weak,
                           "查询无在域信号（3GPP/电信词表零命中），疑似库外题；确认后进指标→扩库提案")
        return Finding(t, CAT_RANKING, [f"在域信号：{', '.join(dom[:5])}"] + weak,
                       "在域查询但命中质量弱（目标块可能在库但排不进 top-k）")
    return Finding(t, CAT_RANKING, weak, "日志未记查询文本，无法判域；按证据弱预填，待人工")


# ------------------- low_score 机读采集（阈值 ROC 标定真数据源） -------------------
def low_score_records(turns: List[Turn], src: str) -> List[Dict]:
    """low_score 轮 → 机读记录列表（供 jsonl 落盘/嵌入底稿 §五）。

    口径（建库/logs/阈值ROC标定-20260922.md §六.3 触发事件②的真数据源）：
    - 只取 rag=low_score 轮：top1=触发闸门的证据集内最大余弦原始分
      （score_type=gate_cosine_max，与 运营/阈值标定样本-20260922.jsonl 的
      score/score_type 键名对齐，人工复核后可直接逐行并入重算阈值表）。
    - hit 态 top1=通道排序分（hybrid RRF ~0.03 量级），两态 top1 语义不同，
      hit 行一律不入采集（防污染闸门标定样本）。
    - top1 缺失（top1=na / 旧日志无打点）→ top1/score/score_type=null，
      行仍保留（拦截事件计数本身也是分布证据）。
    - q_prefix=日志 q= 清洗摘要前 QUERY_SUMMARY_LEN 字符（无 q= 则空串）。
    """
    recs: List[Dict] = []
    for t in turns:
        if t.rag != "low_score":
            continue
        gate = t.retrieve if (t.retrieve or {}).get("outcome") == "low_score" else {}
        recs.append({
            "source_file": src,
            "ts": t.ts,
            "line_no": t.line_no,
            "rag": t.rag,
            "top1": t.top1,
            "score": t.top1,          # 镜像 top1，对齐阈值标定样本 jsonl 键名
            "score_type": "gate_cosine_max" if t.top1 is not None else None,
            "thr": _first_float(gate.get("thr")),  # 闸门阈值（[rag] low_score 行配对时有值）
            "q_prefix": (" ".join(t.query.split())[:QUERY_SUMMARY_LEN]
                         if t.query else ""),
            "note": "线上 low_score 采集（闸门余弦原始分口径）；归因底稿人工复核后再并入阈值标定样本",
        })
    return recs


def render_jsonl(records: List[Dict]) -> str:
    """记录列表 → jsonl 文本（每行一个 JSON 对象，ensure_ascii=False 便于人工浏览）。"""
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)


# ----------------------------- 渲染 -----------------------------
def _query_summary(t: Turn) -> str:
    if t.query:
        q = " ".join(t.query.split())
        return q[:QUERY_SUMMARY_LEN] + ("…" if len(q) > QUERY_SUMMARY_LEN else "")
    return f"（日志未记查询文本；in_chars={t.in_chars if t.in_chars is not None else '?'}）"


def _time_label(t: Turn) -> str:
    return t.ts if t.ts else f"行L{t.line_no}"


def render_markdown(turns: List[Turn], findings: List[Finding], meta: Meta,
                    opts: Options, src: str, gen_time: str,
                    jsonl_records: Optional[List[Dict]] = None) -> str:
    n_hit = sum(1 for t in turns if t.rag == "hit")
    n_miss = sum(1 for t in turns if t.rag == "miss")
    n_low = sum(1 for t in turns if t.rag == "low_score")
    n_cov = sum(1 for t in turns if t.rag == "coverage_miss")
    n_rr = sum(1 for t in turns if t.rag == "rerank_refused")
    n_off = sum(1 for t in turns if t.rag == "off")
    n_other = sum(1 for t in turns if t.rag not in KNOWN_RAG_STATES)
    miss_rate = (100.0 * n_miss / (n_hit + n_miss)) if (n_hit + n_miss) else 0.0
    cat_counts = {c: sum(1 for f in findings if f.category == c)
                  for c in (CAT_LOW_SCORE, CAT_COVERAGE_GATE, CAT_RERANK_GATE,
                            CAT_COVERAGE, CAT_RETRIEVAL, CAT_RANKING)}
    L: List[str] = []
    L.append("# rag miss/low_score/低分命中 归因底稿（miss_attribution.py 自动生成）")
    L.append("")
    L.append(f"- 生成时间：{gen_time}")
    L.append(f"- 日志来源：{src}（{meta.n_lines} 行；时间戳：{'有' if meta.has_ts else '无'}；问答轮次：{meta.n_chat}）")
    if meta.startup_rag:
        L.append(f"- 服务状态线索：[startup] {meta.startup_rag}")
    if meta.last_store:
        L.append(f"- 库状态线索：[rag-store] {meta.last_store}")
    L.append(f"- 判定阈值：low_score={opts.low_score} / min_embed_chars={opts.min_embed_chars}"
             f" / min_evidence_chars={opts.min_evidence_chars} / min_blocks={opts.min_blocks}"
             f"（q=/top1= 已打点：hit 态 top1=通道排序分、low_score 态 top1=闸门余弦原始分，"
             f"两态语义不同勿混；分数字段缺失时相关规则自动不生效）")
    L.append("")
    L.append("## 一、汇总统计")
    L.append("")
    L.append("| 指标 | 值 |")
    L.append("|---|---|")
    L.append(f"| 问答轮次（[chat] 行） | {meta.n_chat} |")
    L.append(f"| rag=hit / miss / low_score / off | {n_hit} / {n_miss} / {n_low} / {n_off} |")
    if n_other:
        L.append(f"| 其他未知 rag 态（服务端新打点？人工核，不入四态归因） | {n_other} |")
    L.append(f"| miss 率 miss/(hit+miss) | {miss_rate:.1f}%（{n_miss}/{n_hit + n_miss}） |")
    L.append(f"| 低分闸门拦截（rag=low_score，单列不计入 miss 率） | {n_low} |")
    L.append(f"| 负控覆盖闸拦截（rag=coverage_miss，单列不计入 miss 率） | {n_cov} |")
    L.append(f"| rerank 拒答闸拦截（rag=rerank_refused，单列不计入 miss 率） | {n_rr} |")
    L.append(f"| 低分/可疑 hit（触发条目） | {sum(1 for f in findings if f.turn.rag == 'hit')} |")
    L.append(f"| 归因预填·{CAT_LOW_SCORE} | {cat_counts[CAT_LOW_SCORE]} |")
    L.append(f"| 归因预填·{CAT_COVERAGE_GATE} | {cat_counts[CAT_COVERAGE_GATE]} |")
    L.append(f"| 归因预填·{CAT_RERANK_GATE} | {cat_counts[CAT_RERANK_GATE]} |")
    L.append(f"| 归因预填·{CAT_COVERAGE} | {cat_counts[CAT_COVERAGE]} |")
    L.append(f"| 归因预填·{CAT_RETRIEVAL} | {cat_counts[CAT_RETRIEVAL]} |")
    L.append(f"| 归因预填·{CAT_RANKING} | {cat_counts[CAT_RANKING]} |")
    L.append("")
    L.append("周环比：与上期底稿对比留待周报手工填写（上期：＿＿ → 本期：＿＿）。")
    L.append("")
    L.append("## 二、全量轮次一览（基线证据，含未触发条目）")
    L.append("")
    L.append("| # | 时间/行号 | rag | in_chars | embed（chars ok dur） | retrieve（chars/blocks 或 err） | top1 |")
    L.append("|---|---|---|---|---|---|---|")
    for t in turns:
        ok_e = t.last_ok_embed()
        emb = (f"{_to_int(ok_e.get('chars'))} ok={ok_e.get('ok')} {ok_e.get('dur', '?')}"
               if ok_e else ("ok=0" if any(e.get("ok") == "0" for e in t.embeds) else "无"))
        L.append(f"| {t.idx} | {_time_label(t)} | {t.rag} | "
                 f"{t.in_chars if t.in_chars is not None else '?'} | {emb} | "
                 f"{t.retrieve_desc()} | {('%.4f' % t.top1) if t.top1 is not None else '-'} |")
    L.append("")
    L.append("## 三、待复核明细（预填=启发式；逐条人工复核，复核确认后才可进指标→扩库提案）")
    L.append("")
    if not findings:
        L.append("（本期无 rag=miss、无低分/可疑 hit —— 基线干净，如实呈现；空也是基线。）")
        L.append("")
    for f in findings:
        t = f.turn
        L.append(f"### #{t.idx} {_time_label(t)} rag={t.rag} —— 预填：{f.category}")
        L.append("")
        L.append(f"- 时间/定位：{t.ts if t.ts else '日志无时间戳，见 [chat] 行 L%d' % t.line_no}"
                 f"{'；会话线索：' + t.access if t.access else ''}")
        L.append(f"- 查询摘要：{_query_summary(t)}")
        L.append(f"- 检索侧证据：embed：{t.embed_desc()}；retrieve：{t.retrieve_desc()}"
                 f"{'；top1=%.4f' % t.top1 if t.top1 is not None else ''}")
        for reason in f.reasons:
            L.append(f"- 触发理由：{reason}")
        L.append(f"- 预填口径：{f.note}")
        L.append("- 人工复核（留空待填）：结论：＿＿；若判语料未覆盖，是否起草扩库提案：＿＿")
        L.append("")
    L.append("## 四、口径备注")
    L.append("")
    L.append("- rag=low_score=低分闸门拦截（2026-09-21 批1 新增日志态）：检索链路正常、"
             "证据集最高余弦分低于服务端 score_threshold，不注入证据退裸答；归因单列"
             "'低分闸门拦截'（语料未覆盖近类），与 miss（链路异常退裸答）严格区分、"
             "不计入 miss 率。")
    L.append("- rag=coverage_miss=负控覆盖闸拦截（S1 治理丙 2026-09-28 新增日志态、"
             "2026-10-01 教识）：题面含库外域安全词形而证据集全缺该词，不注入证据"
             "退裸答；归因单列'负控覆盖闸拦截'，不计入 miss 率、不入 low_score 阈值"
             "标定采集——域内题误伤（非预期拒答）须人工复核。")
    L.append("- rag=rerank_refused=rerank 拒答闸拦截（2026-10-12 0.75 档决策态、"
             "2026-10-15 补丁纳入）：hit 检索完成后 rerank 池 max<分面阈值转拒答"
             "退裸答；判定分在配对 [rerank_gate] 行（max=/thr=），[chat] top1 仍="
             "通道排序分；归因单列，不计入 miss 率——误拦面（域内题被拒）须人工复核。")
    L.append("- 归因分类=启发式预填（规则见脚本 docstring），不构成专项证据链输入；"
             "语料未覆盖类依赖 q= 查询摘要判域（q= 已打点；旧日志缺文本时退排序失利并注待人工）。")
    L.append("- 周报用法：云端 `journalctl -u qa-bot --since \"7 days ago\" --no-pager` 导出后跑本脚本，"
             "与上期底稿对比；同类归因连续两周 → 触发指标→扩库回路提案（人工决策）。")
    L.append("- 高并发日志轮次配对可能串轮（已知局限），复核时以 [chat] 行号/时间戳回对原日志。")
    if jsonl_records is not None:
        L.append("")
        L.append("## 五、low_score 机读采集（jsonl，阈值 ROC 标定 §六.3 对接口径）")
        L.append("")
        L.append("- 只收 rag=low_score 轮：top1=score=触发闸门的余弦原始分"
                 "（score_type=gate_cosine_max），与 运营/阈值标定样本-20260922.jsonl "
                 "键名对齐，本节各行人工复核后可直接逐行并入重算阈值表。")
        L.append("- hit 态 top1=通道排序分（hybrid RRF ~0.03 量级），两态语义不同，"
                 "hit 行一律不入本采集；top1=null 行=日志缺分数（top1=na/旧打点），"
                 "拦截事件计数仍保留。")
        if jsonl_records:
            L.append("")
            L.append("```jsonl")
            for rec in jsonl_records:
                L.append(json.dumps(rec, ensure_ascii=False))
            L.append("```")
        else:
            L.append("")
            L.append("（本期无 rag=low_score 行——空采集也是基线。）")
    return "\n".join(L) + "\n"


# ----------------------------- CLI -----------------------------
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="rag=miss/low_score 低分拦截/低分命中 归因观测（零 API、纯标准库、只读日志）")
    ap.add_argument("log_path", help="日志文件路径（server.log 或 journalctl 导出文本）")
    ap.add_argument("-o", "--output", default=None, help="输出 markdown 路径（缺省打印 stdout）")
    ap.add_argument("--low-score", type=float, default=DEFAULT_LOW_SCORE,
                    help=f"top1 分数阈值，低于判命中分过低（默认 {DEFAULT_LOW_SCORE}）")
    ap.add_argument("--min-embed-chars", type=int, default=DEFAULT_MIN_EMBED_CHARS,
                    help=f"embed chars 阈值，低于判检索输入退化（默认 {DEFAULT_MIN_EMBED_CHARS}）")
    ap.add_argument("--min-evidence-chars", type=int, default=DEFAULT_MIN_EVIDENCE_CHARS,
                    help=f"evidence chars 阈值，低于判证据过短（默认 {DEFAULT_MIN_EVIDENCE_CHARS}）")
    ap.add_argument("--min-blocks", type=int, default=DEFAULT_MIN_BLOCKS,
                    help=f"blocks 阈值，小于判证据块过少（默认 {DEFAULT_MIN_BLOCKS}）")
    ap.add_argument("--jsonl", nargs="?", const="auto", default=None, metavar="PATH",
                    help="low_score 机读采集 jsonl 落点：给路径=写该路径；只给旗标=随 -o "
                         "自动伴生（.md→.low_score.jsonl）；不给旗标但有 -o 时同样自动伴生"
                         "（周报表形态默认带机读 sidecar）；纯 stdout 模式不落文件")
    args = ap.parse_args(argv)

    try:
        with open(args.log_path, encoding="utf-8", errors="replace") as fp:
            lines = fp.readlines()
    except OSError as e:
        print(f"[miss_attribution] 读日志失败：{e}", file=sys.stderr)
        return 2

    turns, meta = parse_log(lines)
    opts = Options(low_score=args.low_score, min_embed_chars=args.min_embed_chars,
                   min_evidence_chars=args.min_evidence_chars, min_blocks=args.min_blocks)
    findings = [f for f in (classify_turn(t, opts) for t in turns) if f is not None]
    records = low_score_records(turns, args.log_path)
    gen_time = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    md = render_markdown(turns, findings, meta, opts, args.log_path, gen_time,
                         jsonl_records=records)

    # low_score 机读采集 sidecar：显式 --jsonl PATH 优先；否则有 -o 即自动伴生
    jsonl_path = None
    if args.jsonl and args.jsonl != "auto":
        jsonl_path = args.jsonl
    elif args.output:
        stem = args.output[:-3] if args.output.endswith(".md") else args.output
        jsonl_path = stem + ".low_score.jsonl"
    elif args.jsonl == "auto":
        print("[miss_attribution] --jsonl 不带路径时需配合 -o（纯 stdout 模式请给显式路径）",
              file=sys.stderr)
    if jsonl_path:
        with open(jsonl_path, "w", encoding="utf-8") as fp:
            fp.write(render_jsonl(records))

    if args.output:
        with open(args.output, "w", encoding="utf-8") as fp:
            fp.write(md)
        n = {c: sum(1 for f in findings if f.category == c) for c in
             (CAT_LOW_SCORE, CAT_COVERAGE, CAT_RETRIEVAL, CAT_RANKING)}
        n_rr_cat = sum(1 for f in findings if f.category == CAT_RERANK_GATE)
        print(f"[miss_attribution] 轮次={meta.n_chat} hit/miss/low_score/off="
              f"{sum(1 for t in turns if t.rag == 'hit')}/{sum(1 for t in turns if t.rag == 'miss')}"
              f"/{sum(1 for t in turns if t.rag == 'low_score')}"
              f"/{sum(1 for t in turns if t.rag == 'off')} 触发={len(findings)} "
              f"（{CAT_LOW_SCORE}={n[CAT_LOW_SCORE]} {CAT_COVERAGE}={n[CAT_COVERAGE]} "
              f"{CAT_RETRIEVAL}={n[CAT_RETRIEVAL]} {CAT_RANKING}={n[CAT_RANKING]}）→ {args.output}"
              + (f"；{CAT_RERANK_GATE}={n_rr_cat}" if n_rr_cat else "")
              + (f"；low_score 机读采集 {len(records)} 行 → {jsonl_path}" if jsonl_path else ""))
    else:
        sys.stdout.write(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
