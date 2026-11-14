#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""decompose.py —— 复合意图拆解节点（R 线议题四方法 2 实施层，R3b 施工 2026-10-16）。

定位（判据件=work/R3b-实施层施工-20261016/判据件-拆解节点-20261016.md，预注册）：
- 对症 B21 型复合意图耦合（预验证已过：work/R3-预验证-执行-20261016/——规则 A/B
  生效实证+B43 阴性对照守住）。三件套：
  ① 触发判定（复合意图信号词表，纯函数，预注册冻结）；
  ② flash 拆解调用（qwen3.8-flash，temperature=0，异常吞噬恒不抛出——任何失败
     回 None，调用方回退不拆解=零行为降级，multiquery.generate_variant 先例）；
  ③ 四型聚合纯函数（对比 A/主从 B/并列 C/条件 D 弱形态+跨型公理，逐格沿
     work/R线-仪器-设计-20261016/方法2聚合规则推演-20261016.md §二——与预验证
     执行件 2-聚合与对照.py 的 A_TABLE/agg_C/agg_B 同源）。

挂点与键（默认关，拨键禁自动生效）：由 multiquery.generate_variants 的
decompose=None 关键字驱动（R3b 施工只加挂点，rag.py/config 接线归 R8 拨键窗，
上产执行单草案另附）；None/无此参/enabled=false → 关态逐字节一致（六态断言
=tests/test_decompose.py）。开态行为：触发 → 拆解 → 子问（≤3，清洗去重截长）
**替代** mq 变体进检索路（routes=[原查询]+子问）；不触发/失败/单意 → 回退
变体生成路径。

费用口径（启用时）：每触发题 +1 次 flash 拆解调用（max_tokens=480，≈0.001 元
级）+≤3 次 embed（检索侧另计）。观测行 [rag-mq-decompose] 由挂点（multiquery
侧）打，本件只打 [rag-decompose] 调用成败行（零密件零题面，只报类型名/时长）。

端点与 key 纪律：与 multiquery.generate_variant 同源——endpoint=(base, key)
由调用方解析传入；key 绝不回显、绝不落日志。

依赖方向：纯标准库 + httpx；不 import multiquery/rag（multiquery 单向引用
本件；子问单行清洗用本件 _clean_sub_line，与 multiquery.clean_variant 核心
规则镜像，改其一须同步另一处）。
"""
import json
import re
import time

import httpx

CHAT_PATH = "/compatible-mode/v1/chat/completions"  # 口径同 multiquery/CR 管线

DEFAULT_DECOMPOSE_MODEL = "qwen3.8-flash"
DEFAULT_DECOMPOSE_TIMEOUT_SECONDS = 5.0
DECOMPOSE_MAX_TOKENS = 480          # 3 子问 JSON 输出上界（判据件 §二.2）
MAX_SUBS = 3                        # 子问条数帽（规则 C 边界：>3 登记已知界）
MAX_SUB_CHARS = 300                 # 子问截长（对齐 multiquery.DEFAULT_MQ_MAX_VARIANT_CHARS）

DECOMPOSE_TYPES = ("对比", "主从", "并列", "条件", "单意")
LABELS = ("可答", "不确定", "不可答")   # 判官 v2 三态（u3clib 首词协议）
ROLES = ("main", "slave", "gen")       # main=技术主问；slave=库外从问（判定但
#                                        不入聚合，规则 B 单向传播）；gen=生成侧
#                                        指令（不入判官面，规则 D 边界条款）

# ---------------------------------------------------------------------------
# §一 触发判定（词表预注册冻结，判据件 §1.1——改词表=重走判据件评审）
# ---------------------------------------------------------------------------
QMARK_CHARS = ("？", "?")
CONJ_WORDS = ("顺便", "另外", "还有", "以及", "再说", "捎带", "接着问")
CMP_WORDS = ("哪个更", "哪个能", "哪一个", "谁更", "区别", "对比",
             "相比", "差别", "差异", "还是")
INTERROGATIVE_WORDS = ("是多少", "是什么", "有哪些", "靠什么", "有没有", "为什么",
                       "怎么", "如何", "多少", "哪个", "干嘛", "什么")
OFFLIB_TASK_WORDS = ("推荐", "建议", "帮我拟", "帮我写", "帮我列", "帮我编",
                     "帮我总结", "找个", "介绍个", "安利")
COND_FALLBACK_WORDS = ("没写的话", "没写", "没有的话", "不存在的话",
                       "缺失的话", "的话帮我")

# 技术实体 token：字母开头词形，或规范号形（38.331/38331）；保留含数字或全大写
# ≥2 字符者（t310/38331/SIB1/LTE/NR/SI）；大小写不敏感去重。
_ENTITY_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.\-]{1,}|\d[\d.]{2,}")


def _default_log(line: str) -> None:
    print(line, flush=True)


def extract_entities(query):
    """题面 → 相异技术实体列表（保持出现序；纯函数恒不抛出）。"""
    out = []
    try:
        for tok in _ENTITY_RE.findall(str(query or "")):
            if tok in out:
                continue
            if any(c.isdigit() for c in tok) or (len(tok) >= 2 and tok.upper() == tok):
                out.append(tok)
    except Exception:
        return []
    return out


def detect_composite(query):
    """题面 → 触发判定结构（纯函数恒不抛出）。

    返回 {"triggered", "signals", "n_qmarks", "n_entities", "entities",
    "n_interrogatives", "type_hint"}；四路信号（判据件 §1.1）任一即触发：
    T1 多问号 ≥2／T2 对比词∧双实体／T3 连词∧(疑问模式 ≥2∨库外任务词)／
    T4 条件回落词∧库外任务词。type_hint=拆解 prompt 侧的型提示（对比/条件/
    主从/并列），非聚合权威（聚合权威=flash 输出 type）。
    """
    q = str(query or "")
    n_qmarks = sum(q.count(c) for c in QMARK_CHARS)
    entities = extract_entities(q)
    n_int = sum(1 for w in INTERROGATIVE_WORDS if w in q)
    has_conj = any(w in q for w in CONJ_WORDS)
    has_cmp = any(w in q for w in CMP_WORDS)
    has_offlib = any(w in q for w in OFFLIB_TASK_WORDS)
    has_cond = any(w in q for w in COND_FALLBACK_WORDS)
    t1 = n_qmarks >= 2
    t2 = has_cmp and len(entities) >= 2
    t3 = has_conj and (n_int >= 2 or has_offlib)
    t4 = has_cond and has_offlib
    signals = [s for s, f in (("T1多问号", t1), ("T2对比双实体", t2),
                              ("T3连词并举", t3), ("T4条件弱形态", t4)) if f]
    if t2:
        hint = "对比"
    elif t4:
        hint = "条件"
    elif has_offlib:
        hint = "主从"
    else:
        hint = "并列"
    return {"triggered": bool(signals), "signals": signals,
            "n_qmarks": n_qmarks, "n_entities": len(entities),
            "entities": entities, "n_interrogatives": n_int,
            "type_hint": hint}


# ---------------------------------------------------------------------------
# §二 拆解调用（flash，temp=0，异常吞噬恒不抛出）
# ---------------------------------------------------------------------------
# 系统段预注册逐字冻结（判据件 §二.2；改 prompt=重走判据件评审）
DECOMPOSE_SYSTEM_PROMPT = (
    "你是复合问题拆解器。把用户的复合问题拆成自包含的原子子问题，输出单行紧凑"
    "JSON（不要解释、不要markdown围栏）：\n"
    '{"type":"对比|主从|并列|条件|单意","subs":[{"id":"S1","q":"子问题文本",'
    '"entity":true,"role":"main"}]}\n'
    "规则：\n"
    "- 每个子问题必须自含：补足原题省略的主语与制式限定（如 LTE/NR、规范号 TS "
    "36.331），可独立判定；\n"
    "- 覆盖原题全部意图、互不重叠；子问题条数不超过 3；\n"
    "- type 判定：对比=两个实体并举且比较义（vs/哪个更/区别）；主从=主技术问"
    "＋库外附加任务（推荐/建议/帮我拟稿）；并列=多个独立技术问连发；条件=后问"
    "依赖前问结果或\"没写的话帮我拟\"式回落（回落拟稿子问 role=gen 不入判定）；\n"
    "- entity=该子问是否含可检索技术实体（参数名/规范号/制式名），布尔值；\n"
    "- role ∈ main（技术主问）/slave（库外从问，如推荐类，单独判定但聚合零贡献）"
    "/gen（生成侧指令，不入判定）；\n"
    "- 对比型恰以两个 main 子问构成比较对，另有并列技术附注子问也标 main；\n"
    "- 单一意图问题不是复合问题，输出 {\"type\":\"单意\",\"subs\":[]}。\n"
    "只输出 JSON 本身。")

_THINK_RE = re.compile(r"<think>.*?</think>", re.S)
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.S)


def _clean_sub_line(text):
    """子问题文本 → 单行字符串（不合法回 ""）。与 multiquery.clean_variant
    核心规则镜像：剥 think/围栏/成对引号、折叠空白、截长。"""
    if not isinstance(text, str):
        return ""
    t = _THINK_RE.sub(" ", text).strip()
    m = _FENCE_RE.search(t)
    if m:                       # 围栏包裹（模型外溢形态）取围栏内
        t = m.group(1).strip()
    for left, right in (('"', '"'), ("'", "'"), ("「", "」"),
                        ("‘", "’"), ("“", "”")):
        if len(t) >= 2 and t.startswith(left) and t.endswith(right):
            t = t[1:-1].strip()
    t = " ".join(t.split())
    return t[:MAX_SUB_CHARS]


def _locate_json_object(text):
    """文本 → 首个平衡 {...} 子串（找不到回 None）。逐字符括号深度扫描，
    字符串字面量内的 {}/\" 不计深度。"""
    s = str(text or "")
    start = s.find("{")
    while start != -1:
        depth, i, instr = 0, start, False
        while i < len(s):
            c = s[i]
            if instr:
                if c == "\\":
                    i += 2
                    continue
                if c == '"':
                    instr = False
            elif c == '"':
                instr = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return s[start:i + 1]
            i += 1
        start = s.find("{", start + 1)
    return None


def normalize_decomposition(obj, query):
    """flash 原始解析对象 → 归一化结构或 None（纯函数恒不抛出）。

    归一化规则（判据件 §二.3）：type ∈ DECOMPOSE_TYPES（单意→None）；subs
    1..MAX_SUBS；q 逐条 _clean_sub_line（空/casefold 重复/与原题同文者剔除）；
    role/entity 归一（缺省 main/False）；id 重排 S1..Sn；判官面（main+slave）
    至少 1 条，否则 None。输出 {"type", "subs", "type_hint_source": "flash"}。
    """
    try:
        if not isinstance(obj, dict):
            return None
        qtype = obj.get("type")
        if qtype not in DECOMPOSE_TYPES or qtype == "单意":
            return None
        raw_subs = obj.get("subs")
        if not isinstance(raw_subs, list) or not raw_subs:
            return None
        origin_key = " ".join(str(query or "").split()).casefold()
        seen = {origin_key}
        subs = []
        for rs in raw_subs[:MAX_SUBS]:
            if not isinstance(rs, dict):
                continue
            q = _clean_sub_line(rs.get("q") or rs.get("text") or "")
            key = q.casefold()
            if not q or key in seen:
                continue
            role = rs.get("role") if rs.get("role") in ROLES else "main"
            ent = rs.get("entity")
            entity = bool(ent) if isinstance(ent, bool) else str(ent).lower() in ("true", "1", "yes")
            subs.append({"id": "S%d" % (len(subs) + 1), "q": q,
                         "entity": entity, "role": role})
            seen.add(key)
        if not subs or not any(s["role"] in ("main", "slave") for s in subs):
            return None
        return {"type": qtype, "subs": subs}
    except Exception:
        return None


def decompose_query(query, *, model=DEFAULT_DECOMPOSE_MODEL,
                    timeout=DEFAULT_DECOMPOSE_TIMEOUT_SECONDS, endpoint=None,
                    log=None, type_hint=None):
    """复合题面 → 拆解结构 dict 或 None（任何失败回 None，绝不抛出）。

    - flash 调用参数：temperature=0 / enable_thinking=False / max_tokens=480
      （判据件 §二.1）；type_hint 非空时附在 user 段首作型提示（触发信号产物）；
    - 回包=choices[0].message.content；剥 think/围栏 → _locate_json_object →
      json.loads → normalize_decomposition；解析失败/单意/结构非法 → None；
    - 每次调用记一行成败日志（零密件零题面，只报类型名/时长/字符数）：
      [rag-decompose] ok=1 type=对比 n=2 dur=0.85s
      [rag-decompose] ok=0 err=TimeoutException dur=5.00s
    """
    say = log or _default_log
    t0 = time.time()
    try:
        if endpoint is None:
            raise RuntimeError("endpoint 未解析")
        base, key = endpoint
        user = query
        if type_hint and type_hint in ("对比", "主从", "并列", "条件"):
            user = "（型提示：%s）%s" % (type_hint, query)
        body = {"model": model,
                "messages": [
                    {"role": "system", "content": DECOMPOSE_SYSTEM_PROMPT},
                    {"role": "user", "content": user}],
                "temperature": 0,       # 同题面复跑字节级一致（口径同 CR 管线）
                "max_tokens": DECOMPOSE_MAX_TOKENS,
                "enable_thinking": False}
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(base.rstrip("/") + CHAT_PATH, json=body,
                               headers={"Authorization": f"Bearer {key}"})
            resp.raise_for_status()
            data = resp.json()
        raw = (data["choices"][0]["message"].get("content") or "")
        usage = data.get("usage") or {}
        cand = _locate_json_object(_THINK_RE.sub(" ", raw))
        obj = json.loads(cand) if cand else None
        res = normalize_decomposition(obj, query)
        if res is None:
            raise ValueError("拆解输出为空/单意/结构非法")
        say(f"[rag-decompose] ok=1 type={res['type']} n={len(res['subs'])} "
            f"dur={time.time() - t0:.2f}s")
        res["_usage"] = {"in_tok": int(usage.get("prompt_tokens") or 0),
                         "out_tok": int(usage.get("completion_tokens") or 0)}
        return res
    except Exception as e:  # 只报异常类型名，不带任何请求细节
        say(f"[rag-decompose] ok=0 err={type(e).__name__} "
            f"dur={time.time() - t0:.2f}s")
        return None


# ---------------------------------------------------------------------------
# §三 四型聚合（纯函数，逐格沿设计件 §二——A_TABLE/agg_C/agg_B 与预验证执行件
#     2-聚合与对照.py 同源；本件新增=通用化分轴递归，公理 5 深度帽 2 层）
# ---------------------------------------------------------------------------
# §2.2 对比类分表（两子问；行=S1 态，列=S2 态）→ (聚合三态, 二次检索标记侧)
A_TABLE = {
    ("可答", "可答"): ("可答", None),
    ("可答", "不确定"): ("不确定", None),
    ("可答", "不可答"): ("不确定", "S2"),
    ("不确定", "可答"): ("不确定", None),
    ("不确定", "不确定"): ("不确定", None),
    ("不确定", "不可答"): ("不确定", None),
    ("不可答", "可答"): ("不确定", "S1"),
    ("不可答", "不确定"): ("不确定", None),
    ("不可答", "不可答"): ("不可答", None),   # 通用边界 1：两子问皆不可答→不可答
}


def agg_A(l1, l2, ent1, ent2, id1, id2):
    """规则 A（对比类分表）。KeyError=分表死角 → 上层断言炸（无逻辑死角判读）。"""
    lab, side = A_TABLE[(l1, l2)]
    flags = set()
    if side == "S1" and ent1:
        flags.add(id1)
    if side == "S2" and ent2:
        flags.add(id2)
    return lab, flags


def agg_C(units):
    """规则 C（并列类）。units=[(unit_id, label, entity_signal, carried_flags)]。
    全可答→可答；全不可答→不可答；混合/全不确定→不确定；
    标记=承袭标记 ∪ {不可答且含实体信号子问}（附带动作位，公理 4）。"""
    labels = [u[1] for u in units]
    if all(x == "可答" for x in labels):
        lab = "可答"
    elif all(x == "不可答" for x in labels):
        lab = "不可答"
    else:
        lab = "不确定"
    flags = set()
    for uid, ulab, uent, carried in units:
        flags |= set(carried)
        if ulab == "不可答" and uent:
            flags.add(uid)
    return lab, flags


def agg_B(main_lab, main_flags):
    """规则 B（主从类）：聚合=f(主轴态)单向传播，从问态零贡献；B 步自身无
    二次检索（从问库外不入库内检索）；主轴标记作为附带动作位承袭（公理 4）。"""
    return main_lab, set(main_flags)


def judge_face_subs(decomp):
    """拆解结构 → 判官面子问列表（main+slave；gen 剔除——规则 D 边界条款）。"""
    return [s for s in decomp["subs"] if s["role"] in ("main", "slave")]


def aggregate(decomp, labels):
    """拆解结构 + 子问标签 → (聚合三态, 二次检索标记集, 步骤列表)。

    - labels={sub_id: 三态}——判官面子问（main+slave）的判定；gen 子问不入场；
      slave 标签仅入步骤登记（零贡献，规则 B 公理 3）；
    - 分轴递归（公理 5，深度帽 2 层）：
      型=对比 且 main 子问恰 2 → agg_A(比较对) → 其余 main 按 agg_C 并入（轴
      单元 entity=False——A 分表为轴内标记唯一权威，预验证同款）；
      型=条件 → 判官面=main 子问（存在性面）：恰 1 → 聚合=其标签（D-弱形态）；
      >1 → 按 C 保守聚合+登记（检索级级联=预留规则位不实现，判据件 §三.4）；
      型=主从/并列（及对比 >2 main）→ main 子问 agg_C 聚主轴；
      存在 slave → 主轴聚合后 agg_B 单向传播（从问零贡献）；
    - 恒不抛出：输入标签越域/缺子问 → 按保守"不确定"聚合并记步骤异常（影子
      验证侧另有硬校验兜底；生产路径异常吞噬纪律同挂点）。
    """
    steps = []
    try:
        subs = decomp["subs"]
        byid = {s["id"]: s for s in subs}
        mains = [s for s in subs if s["role"] == "main"]
        slaves = [s for s in subs if s["role"] == "slave"]
        qtype = decomp["type"]

        def lab_of(s):
            v = labels.get(s["id"])
            return v if v in LABELS else None

        # 判官面缺失（标签越域/缺）→ 保守不确定（步骤登记）
        face = [s for s in mains + slaves]
        missing = [s["id"] for s in face if lab_of(s) is None]
        if missing:
            steps.append({"rule": "输入防御", "note":
                          "标签缺失/越域 %s → 保守不确定" % missing})
            return "不确定", set(), steps

        # 主轴聚合（深度第 1 层）
        if qtype == "条件":
            if len(mains) == 1:
                axis_lab, axis_flags = lab_of(mains[0]), set()
                steps.append({"rule": "D-weak(指令级条件不触发级联)",
                              "in": {mains[0]["id"]: lab_of(mains[0])},
                              "out": axis_lab, "flags": []})
            else:
                units = [(s["id"], lab_of(s), s["entity"], set())
                         for s in mains]
                axis_lab, axis_flags = agg_C(units)
                steps.append({"rule": "D(检索级级联=预留位，保守C聚合)",
                              "in": {s["id"]: lab_of(s) for s in mains},
                              "out": axis_lab, "flags": sorted(axis_flags)})
        elif qtype == "对比" and len(mains) == 2:
            s1, s2 = mains
            axis_lab, a_flags = agg_A(lab_of(s1), lab_of(s2),
                                      s1["entity"], s2["entity"],
                                      s1["id"], s2["id"])
            steps.append({"rule": "A(2.2分表)",
                          "in": {s1["id"]: lab_of(s1), s2["id"]: lab_of(s2)},
                          "out": axis_lab, "flags": sorted(a_flags)})
            rest = [s for s in mains[2:]]
            if rest:
                units = [(s["id"], lab_of(s), s["entity"], set())
                         for s in rest]
                units.append(("%s主轴(A聚合)" % qtype, axis_lab, False, a_flags))
                axis_lab, axis_flags = agg_C(units)
                steps.append({"rule": "C(并列并入)",
                              "in": dict({s["id"]: lab_of(s) for s in rest},
                                         **{"主轴(A聚合)": steps[-1]["out"]}),
                              "out": axis_lab, "flags": sorted(axis_flags)})
            else:
                axis_lab, axis_flags = axis_lab, a_flags
        else:
            # 并列／主从主轴／对比 >2 main（无比较对信号，保守走 C，判据件 §三.1）
            units = [(s["id"], lab_of(s), s["entity"], set()) for s in mains]
            axis_lab, axis_flags = agg_C(units)
            steps.append({"rule": ("C(主轴)" if qtype != "对比"
                                   else "C(对比>2main保守聚合)"),
                          "in": {s["id"]: lab_of(s) for s in mains},
                          "out": axis_lab, "flags": sorted(axis_flags)})

        # 附加轴（深度第 2 层）：slave 从问 → 规则 B 单向传播（零贡献）
        if slaves:
            lab, flags = agg_B(axis_lab, axis_flags)
            steps.append({"rule": "B(主从单向传播)",
                          "in": dict({"主轴聚合": axis_lab},
                                     **{s["id"]: lab_of(s) + "（零贡献）"
                                        for s in slaves}),
                          "out": lab, "flags": sorted(flags)})
            return lab, flags, steps
        return axis_lab, axis_flags, steps
    except Exception as e:  # 生产防御：聚合面异常吞噬回保守不确定（不抛出）
        steps.append({"rule": "异常防御", "note": type(e).__name__})
        return "不确定", set(), steps
