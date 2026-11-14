#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""citation_check.py —— 深度提升批A：引文忠实度校验（A1）+ 证据充分性评审（A2）纯逻辑层。

定位（2026-09-22 深度提升批A 施工）：
- A1 引文逐句忠实度：回答收尾后把（题面、正文、带 quote 的 sources）交给 judge
  模型逐源判定 verdict∈{supports,partial,unsupported,not_relevant} + 总体
  label∈{grounded,partial,inferred}，server.py 据此在 done 前发 citation_check
  SSE 事件（前端出处条渲染徽标/总标 chip）。
- A2 生成端二次拒答：高危面题（精确数字/参数名/取值范围/表值类，本地启发式
  is_high_stakes_question）在证据组装后先跑 assess_evidence，insufficient →
  server.py 追加保守模板指令 + 发 evidence_insufficient 事件。

双件同步批（2026-09-29，8de6185 词表 v2 批遗留销项）：词表 v2 修订③
（p0-Nominal 型单数字记号形）镜像入本件——新增 HIGH_STAKES_SYMBOL_RE/
EXCLUDE/CONTEXT 三常量（值与 route_domain.py 的 PARAM_V2_SYMBOL_RE/
EXCLUDE/CONTEXT 逐字一致，双件同源逐字锁在 tests/test_citation_check.py，
单侧漂移必红）+ is_high_stakes_question 第三 OR 分支（记号形+排除集+语境词
组合逻辑镜像 route_domain._hits_param 修订③分支）。HIGH_STAKES_KEYWORDS/
HIGH_STAKES_PATTERNS 本体一字不动（route_domain.py:53 单锚 import 复用本体，
事件名排除/不误 veto 纪律保持）。

降级纪律（与 rag.py/multiquery.py 同口径）：check_citation / assess_evidence
恒不抛出——JSON 解析失败、judge 异常、墙钟超时一律返回 None，调用方静默跳过，
绝不影响答案主链路。judge 可插拔：生产实现 token_plan_judge（薄 httpx 走
Token Plan 订阅通道，端点/key 由调用方注入，key 绝不回显绝不落日志）；测试
全部用 mock callable。

费用口径（启用时）：A1 每命中问答至多 1 次 judge 调用（citation_check_sample
抽样率控制）；A2 每高危面题至多 1 次。默认全关=零调用零费用。

依赖方向：本件不 import server/rag（server 单向引用本件），纯标准库 + httpx。
"""
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout

import httpx

# 判定枚举（白名单：越界值一律按畸形丢弃，前端映射文案同枚举）
VERDICTS = ("supports", "partial", "unsupported", "not_relevant")
LABELS = ("grounded", "partial", "inferred")
ASSESS_VERDICTS = ("sufficient", "insufficient")

DEFAULT_CC_TIMEOUT_SECONDS = 3.0
_WATCHDOG_SLACK_S = 0.5      # 墙钟看门狗 = judge 自身预算 + 宽限（口径同 multiquery）
_JUDGE_MAX_TOKENS = 512      # judge 输出是短 JSON，flash/max 档都绰绰有余
QUESTION_MAX_CHARS = 1200    # 题面截长（防多轮拼接态超长浪费 judge tokens）
ANSWER_MAX_CHARS = 8000      # 正文截长（对齐 max_input_chars 量级）
EVIDENCE_MAX_CHARS = 6000    # 证据截长（对齐 rag.max_context_chars 默认）
QUOTE_MAX_CHARS = 400        # 单源引文截长（rag 侧 quote 已截 200，这里再兜一层）
REASON_MAX_CHARS = 200       # assess reason 截长（前端注意条单行渲染量级）

CC_SYSTEM_PROMPT = (
    "你是引文忠实度评审器。给定用户问题、待评审回答与编号语料出处（各附引文片段），"
    "逐源判定回答对该源的依赖程度，并给出总体结论。判定标准：\n"
    "supports=回答中涉及该源的关键论述能被该源引文直接支持；\n"
    "partial=仅部分相关论述获该源支持，或数值/条件与引文有出入；\n"
    "unsupported=回答出现该源应有但引文没有的内容，或与引文矛盾；\n"
    "not_relevant=该源与回答内容无关。\n"
    "总体 label：grounded=关键论述均有源支持；partial=部分支持、部分超出语料；"
    "inferred=基本无源支持、主要靠模型自有知识。\n"
    "只输出一个 JSON 对象，不要解释、不要代码围栏，格式：\n"
    '{"per_source": [{"index": 1, "verdict": "supports"}], "label": "grounded"}\n'
    "index 为出处编号（从 1 起）；verdict 只能取 supports/partial/unsupported/"
    "not_relevant；label 只能取 grounded/partial/inferred。")

ASSESS_SYSTEM_PROMPT = (
    "你是证据充分性评审器。给定用户问题与检索到的语料证据，判定证据是否足以支撑"
    "对问题中精确数值/参数取值/门限/表值的确定性回答。\n"
    "只输出一个 JSON 对象，不要解释、不要代码围栏，格式：\n"
    '{"verdict": "sufficient", "reason": "一句话理由"}\n'
    "verdict 只能取 sufficient（证据直接覆盖所问数值/取值）或 insufficient"
    "（未覆盖或仅间接相关）；reason 为不超过 80 字的中文一句话。")


def _default_log(line: str) -> None:
    print(line, flush=True)


# ---------------------------------------------------------------------------
# judge 消息构建（纯函数；question/answer/sources 形态容错，绝不抛出）
# ---------------------------------------------------------------------------
def _flatten(text, limit):
    """任意输入 → 截长后的字符串（换行保留，judge 需要块结构）。"""
    return str(text or "")[:limit]


def build_judge_messages(question, answer, sources_with_quotes):
    """(题面, 正文, 带 quote 的 sources) → judge messages（system+user 两条）。

    - sources_with_quotes 条目形态同 rag.build_evidence 输出（含 quote 字段，
      2026-09-22 批A 增）；非 dict 条目跳过；quote 缺失按空串（judge 自会判
      not_relevant/unsupported，不代答）；
    - 出处编号 [出处N] 与 per_source.index 同口径（1 起，按列表序）。
    """
    # 编号只对 dict 条目连续排（1 起），与 check_citation 的 index→doc_id 映射同口径
    blocks = []
    kept = [s for s in (sources_with_quotes or []) if isinstance(s, dict)]
    for i, s in enumerate(kept, 1):
        head = " ".join(str(s.get(k) or "").strip()
                        for k in ("doc_id", "version", "locator")).strip()
        quote = " ".join(str(s.get("quote") or "").split())[:QUOTE_MAX_CHARS]
        blocks.append(f"[出处{i}] {head}\n引文：{quote}")
    user = ("【用户问题】\n" + _flatten(question, QUESTION_MAX_CHARS).strip() +
            "\n\n【待评审回答】\n" + _flatten(answer, ANSWER_MAX_CHARS).strip() +
            "\n\n【编号出处与引文】\n" + "\n\n".join(blocks) +
            "\n\n请按系统要求只输出 JSON 对象。")
    return [{"role": "system", "content": CC_SYSTEM_PROMPT},
            {"role": "user", "content": user}]


def build_assess_messages(question, evidence_text):
    """(题面, 证据文本) → assess messages（system+user 两条）。"""
    user = ("【用户问题】\n" + _flatten(question, QUESTION_MAX_CHARS).strip() +
            "\n\n【检索到的语料证据】\n" + _flatten(evidence_text, EVIDENCE_MAX_CHARS).strip() +
            "\n\n请按系统要求只输出 JSON 对象。")
    return [{"role": "system", "content": ASSESS_SYSTEM_PROMPT},
            {"role": "user", "content": user}]


# ---------------------------------------------------------------------------
# judge 输出解析（宽容提取 + 白名单严校验；畸形一律 None）
# ---------------------------------------------------------------------------
_FENCE_HEAD_RE = re.compile(r"^```[a-zA-Z]*\s*")
_FENCE_TAIL_RE = re.compile(r"\s*```$")


def _extract_json_obj(raw):
    """judge 原始输出 → dict 或 None：剥代码围栏、截取首 { 到末 }，解析失败 None。"""
    if not isinstance(raw, str) or not raw.strip():
        return None
    t = raw.strip()
    if t.startswith("```"):
        t = _FENCE_TAIL_RE.sub("", _FENCE_HEAD_RE.sub("", t)).strip()
    lo, hi = t.find("{"), t.rfind("}")
    if lo < 0 or hi <= lo:
        return None
    try:
        obj = json.loads(t[lo:hi + 1])
    except (json.JSONDecodeError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None


def parse_citation_json(raw):
    """A1 judge 输出 → {"label","per_source":[{"index","verdict"}]} 或 None。

    严校验：label 必须∈LABELS、per_source 必须是列表，否则整体 None（畸形）；
    条目级宽容：非 dict/verdict 越界/index 非整数的条目逐条丢弃（不影响整体）。
    """
    obj = _extract_json_obj(raw)
    if obj is None:
        return None
    label = obj.get("label")
    if label not in LABELS:
        return None
    ps = obj.get("per_source")
    if not isinstance(ps, list):
        return None
    out = []
    for e in ps:
        if not isinstance(e, dict):
            continue
        v = e.get("verdict")
        if v not in VERDICTS:
            continue
        try:
            idx = int(e.get("index"))
        except (TypeError, ValueError):
            continue
        out.append({"index": idx, "verdict": v})
    return {"label": label, "per_source": out}


def parse_assess_json(raw):
    """A2 judge 输出 → {"verdict","reason"} 或 None（verdict 越界=畸形整体 None）。

    reason 清洗：压平空白、截 REASON_MAX_CHARS（前端注意条走 esc() 渲染，
    这里只做长度/单行纪律，不做转义——转义是展示层职责）。
    """
    obj = _extract_json_obj(raw)
    if obj is None:
        return None
    verdict = obj.get("verdict")
    if verdict not in ASSESS_VERDICTS:
        return None
    reason = " ".join(str(obj.get("reason") or "").split())[:REASON_MAX_CHARS]
    return {"verdict": verdict, "reason": reason}


# ---------------------------------------------------------------------------
# 墙钟看门狗（口径同 multiquery._call_with_deadline：judge 放单工线程，到点即弃）
# ---------------------------------------------------------------------------
def _call_with_deadline(fn, seconds, tag, say):
    """fn 单工线程执行，seconds 内未归即弃（被弃线程自了，结果丢弃）；恒不抛出。

    httpx per-op 超时不缚单调用总墙钟（multiquery 判定实测在案），故 judge
    自身拿 timeout 作请求预算，看门狗再加 _WATCHDOG_SLACK_S 宽限兜底。"""
    ex = ThreadPoolExecutor(max_workers=1)
    try:
        fut = ex.submit(fn)
        try:
            return fut.result(timeout=max(0.0, seconds))
        except FuturesTimeout:
            say(f"[rag-cc] {tag} watchdog cut budget={seconds:.2f}s")
            return None
        except Exception as e:  # judge 内部异常按失败计（只报类型名）
            say(f"[rag-cc] {tag} fail err={type(e).__name__}")
            return None
    finally:
        ex.shutdown(wait=False)


def _norm_budget(timeout, default=DEFAULT_CC_TIMEOUT_SECONDS):
    """timeout 清洗：坏值/非正数回默认（防误配零预算=必超时）。"""
    try:
        t = float(timeout)
    except (TypeError, ValueError):
        return default
    return t if t > 0 else default


# ---------------------------------------------------------------------------
# A1：引文忠实度校验（恒不抛出；失败/超时/畸形 → None=调用方静默跳过）
# ---------------------------------------------------------------------------
def check_citation(question, answer, sources, judge_callable,
                   timeout=DEFAULT_CC_TIMEOUT_SECONDS, log=None):
    """→ {"label": 总体标, "per_source": [{"doc_id","verdict"}]} 或 None。

    - judge_callable(messages, timeout) → 原始输出字符串（可抛异常，本函数兜底）；
    - sources 形态同 rag.build_evidence 输出（含 quote）；index 按 sources 列表序
      映射回 doc_id，越界条目丢弃；
    - 空 sources/空正文/judge 不可调用 → None（不打 judge，不浪费调用费）；
    - JSON 解析失败/judge 异常/墙钟超时 → None（静默降级纪律）。
    """
    say = log or _default_log
    srcs = [s for s in (sources or []) if isinstance(s, dict)]
    ans = str(answer or "").strip()
    if not srcs or not ans or not callable(judge_callable):
        return None
    budget = _norm_budget(timeout)
    messages = build_judge_messages(question, ans, srcs)
    raw = _call_with_deadline(lambda: judge_callable(messages, budget),
                              budget + _WATCHDOG_SLACK_S, "judge", say)
    if raw is None:
        return None
    parsed = parse_citation_json(raw)
    if parsed is None:
        say("[rag-cc] judge 输出畸形（JSON 解析/白名单校验失败），按 None 降级")
        return None
    per = []
    for e in parsed["per_source"]:
        i = e["index"]
        if 1 <= i <= len(srcs):
            per.append({"doc_id": str(srcs[i - 1].get("doc_id") or ""),
                        "verdict": e["verdict"]})
    return {"label": parsed["label"], "per_source": per}


# ---------------------------------------------------------------------------
# A2：证据充分性评审（同降级纪律：恒不抛出，失败 → None=调用方照常回答）
# ---------------------------------------------------------------------------
def assess_evidence(question, evidence_text, judge_callable,
                    timeout=DEFAULT_CC_TIMEOUT_SECONDS, log=None):
    """→ {"verdict": "sufficient"|"insufficient", "reason": str} 或 None。"""
    say = log or _default_log
    ev = str(evidence_text or "").strip()
    if not ev or not callable(judge_callable):
        return None
    budget = _norm_budget(timeout)
    messages = build_assess_messages(question, ev)
    raw = _call_with_deadline(lambda: judge_callable(messages, budget),
                              budget + _WATCHDOG_SLACK_S, "assess", say)
    if raw is None:
        return None
    parsed = parse_assess_json(raw)
    if parsed is None:
        say("[rag-cc] assess 输出畸形（JSON 解析/白名单校验失败），按 None 降级")
    return parsed


# ---------------------------------------------------------------------------
# 高危面题本地启发式分类（A2 前置闸门，确定性、零 API）
# ---------------------------------------------------------------------------
# 关键词面：精确取值/门限/定时器/表值类提问词（保守宽进——多命中只多一次
# judge 调用，漏命中则该题退回普通回答链路，无正确性风险）
HIGH_STAKES_KEYWORDS = (
    "取值", "默认值", "门限", "阈值", "定时器", "参数值", "配置值", "表值",
    "上限", "下限", "最大值", "最小值", "范围", "多少",
)
# 模式面：参数名式记号（T310/N310/p0-Nominal 类）、数值+单位
HIGH_STAKES_PATTERNS = (
    re.compile(r"[A-Za-z][A-Za-z0-9_-]*\d{2,}"),
    re.compile(r"\d+(?:\.\d+)?\s*(?:dBm|dB|ms|MHz|kHz|GHz|km|米|秒|分钟|小时|%|％|字节)",
               re.IGNORECASE),
)
# 词表 v2 修订③双件同步面（2026-09-29 双件同步批，8de6185 遗留销项）：
# 单数字记号形（p0/N1 型）放宽至 \d{1,}+参数语境词组合。以下三常量与
# route_domain.py 的 PARAM_V2_SYMBOL_RE/EXCLUDE/CONTEXT **逐字一致**（双件
# 同源逐字锁死卷=tests/test_citation_check.py，任一侧改动必红）；事件名形
# 排除（A1-A6/B1/B2）防"A3 和 A5 事件有什么区别"型事件概念题误触发（route
# 侧由 PARAM_EVENT_RE 取值语境专闸承接，既有纪律零回退）。
HIGH_STAKES_SYMBOL_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z][A-Za-z0-9_-]*\d(?![A-Za-z0-9])")
HIGH_STAKES_SYMBOL_EXCLUDE = frozenset(
    ("A1", "A2", "A3", "A4", "A5", "A6", "B1", "B2"))
HIGH_STAKES_SYMBOL_CONTEXT = (
    "含义", "定义", "是什么", "什么意思", "取值", "门限", "阈值", "配置",
    "参数", "默认值", "单位", "出处", "数值",
)


def is_high_stakes_question(text) -> bool:
    """题面 → 是否高危面题（精确数字/参数名/取值范围/表值类）。纯函数、绝不抛出。"""
    t = str(text or "")
    if not t.strip():
        return False
    if any(k in t for k in HIGH_STAKES_KEYWORDS):
        return True
    if any(p.search(t) for p in HIGH_STAKES_PATTERNS):
        return True
    # 词表 v2 修订③双件同步面（2026-09-29 批）：记号形+排除集+语境词组合，
    # 逻辑逐字镜像 route_domain._hits_param 修订③分支（route_domain.py:298-301）
    return (any(m.group(0).upper() not in HIGH_STAKES_SYMBOL_EXCLUDE
                for m in HIGH_STAKES_SYMBOL_RE.finditer(t))
            and any(w in t for w in HIGH_STAKES_SYMBOL_CONTEXT))


# ---------------------------------------------------------------------------
# judge 生产实现：薄 httpx 走 Token Plan 订阅通道（OpenAI 兼容 chat/completions）
# ---------------------------------------------------------------------------
def token_plan_judge(messages, *, api_key, model, upstream,
                     timeout=DEFAULT_CC_TIMEOUT_SECONDS,
                     max_tokens=_JUDGE_MAX_TOKENS, log=None,
                     temperature=0, seed=None):
    """生产 judge callable 实体：POST upstream（server.py 注入端点/key/model）。

    成功 → choices[0].message.content 字符串；任何失败抛异常（check_citation/
    assess_evidence 统一转 None）。key 绝不回显、绝不落日志；日志只记字符数/
    成败/时长（口径同 [rag-embed]/[rag-mq]）：
      [rag-cc] judge chars=123 ok=1 dur=0.42s
      [rag-cc] judge ok=0 dur=3.00s err=TimeoutException
    temperature/seed（2026-10-11 提升计划波1 B3 调用面同步改造）：缺省 0/None
    与历史行为逐字节一致（评审确定性口径）；k 重复采样场景可传 temperature>0 +
    逐样本 seed（seed 缺省不传——进请求体才可复现采样轨迹）。
    """
    say = log or _default_log
    t0 = time.time()
    body = {"model": model, "messages": messages,
            "temperature": temperature,   # 评审要确定性（缺省 0，口径同 multiquery/CR 管线）
            "max_tokens": max_tokens, "stream": False,
            # qwen3 系兼容口默认开思考模式（计费+拖慢），评审是秒级预算任务，显式关闭
            "enable_thinking": False}
    if seed is not None:
        body["seed"] = seed
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(upstream, json=body,
                               headers={"Authorization": f"Bearer {api_key}"})
            resp.raise_for_status()
            data = resp.json()
        content = data["choices"][0]["message"].get("content") or ""
        if not content.strip():
            raise ValueError("judge 回包 content 为空")
        say(f"[rag-cc] judge chars={len(content)} ok=1 dur={time.time() - t0:.2f}s")
        return content
    except Exception as e:  # 只报异常类型名，不带任何请求细节
        say(f"[rag-cc] judge ok=0 dur={time.time() - t0:.2f}s err={type(e).__name__}")
        raise
