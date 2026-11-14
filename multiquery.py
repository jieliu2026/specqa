#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""multiquery.py —— multi-query 查询改写（检索前变体生成 + 多路 RRF 融合）。

定位（运营/调研-实操RAG方法论-20260918.md 第三节，计划内后备工序 D）：
- 对症"表述不匹配"：中文意译题面对英文表格/定义块的余弦失分——第一条变体
  固定为英文翻译，把题面拉进英文语料块的语义空间；HyDE 对短参数查询有
  反效果（Zilliz 实证），不采用。由 rag.py 的 mq_* 配置键驱动（默认关），
  默认关=不发起任何调用，行为与现状完全一致。

费用口径（启用时，写入代码注释与 config.example.json 键说明）：
- 每变体 = 1 次 qwen3.8-flash 调用 + 1 次 embedding（变体向量化走 rag 侧）；
  mq_n_variants 默认 2 → 每问至多 2 次 flash + 3 次 embed（原查询 1 + 变体 2）。
  启用评测时费用走生成侧台账口径（过程日志三节授权口径，5 元红线累计口径）。

延迟预算（启用时）：
- 正常态每问 +0.5-2s（flash 短生成 ~0.3-1s/条，逐变体串行；变体 embed
  ~0.3s/条）。mq_timeout_seconds 是**变体生成阶段的总预算**（默认 3s）：
  逐变体串行调用，每次调用超时取剩余预算；预算耗尽即止——已得变体照用，
  零变体退单条原查询。任何超时/生成失败都优雅退化，绝不拖垮请求（零恶化）。
- 墙钟口径（2026-09-21 迭代轮，运营/迭代轮-20260921.md）：per-op 超时不缚
  单调用总墙钟（判定实测 flash 单调用 7.18s>3s 预算仍返回），故 mq_wall_clock
  =true（rag 键，默认 false=旧行为）把预算升级为硬墙钟——单调用线程化、到点
  即弃。采用配方（供云端单点实测后决策）：mq_enabled+mq_n_variants=1（单
  变体=en，判定 26 问全部 got=1 即此态）+mq_wall_clock=true+预算降 2.5s。

端点与 key 纪律：与 rag.embed_query 同源——由调用方（rag.RagService）用
rag.resolve_embed_endpoint() 解析后传入（环境变量 BAILIAN_EMBED_BASE_URL/
BAILIAN_EMBED_API_KEY 优先，否则 ~/.bailian/config.json 的 base_url/api_key），
OpenAI 兼容 chat/completions 路径（口径同 建库/scripts/pipeline_config.py 的
cr_chat_path）。key 绝不回显、绝不落日志；日志只记条数/字符数/成败/时长。

依赖方向：本件不 import rag（rag 单向引用本件），纯标准库 + httpx。

mq 变体观测行（R6 施工，2026-10-16，log-only）：变体生成返回处打
[rag-mq-variants] 行（qsha16+变体数+逐变体全文）——R5/R6a 预对拍定谳"生产 mq
变体文本不落 journal=harness 无法复现 mq 路径"（结构性）的修复面。纯日志零行为
变化（打点异常吞噬，恒不抛出）；形态与消费端设计=work/R6-mq观测施工-20261016/
设计件-mq观测行-20261016.md。

R3b 拆解节点挂点（2026-10-16，默认关）：generate_variants 新增 decompose=None
关键字——复合意图触发（词表预注册）→flash 拆解→子问（≤3）替代变体进检索路；
默认 None/enabled=false/模块缺席=关态逐字节一致。判据件=work/R3b-实施层施工
-20261016/判据件-拆解节点-20261016.md；拆解与四型聚合实现在 decompose.py。
"""
import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout

import httpx

try:  # R3b 拆解节点（2026-10-16，默认关）：模块缺席时挂点静默退关（rag 引用
    import decompose as _decompose   # multiquery 同款容缺席形态；只读单向引用）
except Exception:                    # pragma: no cover - 部分部署防御面
    _decompose = None

CHAT_PATH = "/compatible-mode/v1/chat/completions"  # 拼在 base_url 后（口径同 CR 管线）

DEFAULT_MQ_N_VARIANTS = 2
DEFAULT_MQ_MODEL = "qwen3.8-flash"
DEFAULT_MQ_TIMEOUT_SECONDS = 3.0
DEFAULT_MQ_MAX_VARIANT_CHARS = 300   # 变体截长（对齐 server 侧检索查询上限量级）
MQ_MAX_N_VARIANTS = 2                # 变体条数上限（任务决策：1-2 条）

# 变体规格（顺序即生成顺序）：第 0 条=英文翻译（治"中文意译对英文语料块"失分，
# 1 条变体时只留这条）；第 1 条=中文同义改述（保术语换句式）。
VARIANT_SPECS = (
    ("en",
     "你是检索查询改写器。把用户查询改写为一行英文检索查询：技术术语、参数名、"
     "3GPP 规范号与条款号（如 TS 36.214、p0-NominalPUSCH、5.1.1）原样保留不译，"
     "其余译成自然的电信工程英文表述，不增删事实信息。只输出改写后的查询本身："
     "不要解释、不要引号、不要列表符号、不要换行。"),
    ("zh",
     "你是检索查询改写器。用不同的中文措辞把用户查询改写为一行检索查询：技术"
     "术语、参数名、3GPP 规范号与条款号原样保留，只换句式与用词，不增删事实"
     "信息。只输出改写后的查询本身：不要解释、不要引号、不要列表符号、不要换行。"),
)

_MQ_MAX_TOKENS = 320  # 单变体生成输出上限（查询行短，flash 档费用可忽略）


def _default_log(line: str) -> None:
    print(line, flush=True)


def clamp_n_variants(n):
    """变体条数钳制 → [0, MQ_MAX_N_VARIANTS]（0=不产变体，等价退单条原查询）。

    仅 int/float 入钳（NaN/inf 等异常浮点回默认）；bool 与其余类型（含数字
    字符串）一律回默认——2026-10-13 修：原实现 int(n) 会把 "0"/True 等解析
    入钳，与 test_D1 声明契约「非数值→默认值」相抵（hypothesis 随机抽中
    即挂的抖动源，过程日志条目69⑨）；调用面（config JSON int）行为不变。"""
    if isinstance(n, bool) or not isinstance(n, (int, float)):
        return DEFAULT_MQ_N_VARIANTS
    try:
        return max(0, min(MQ_MAX_N_VARIANTS, int(n)))
    except (ValueError, OverflowError):
        return DEFAULT_MQ_N_VARIANTS


# ---------------------------------------------------------------------------
# 生成结果清洗（确定性纯函数；真实路径与测试注入路径共用同一套）
# ---------------------------------------------------------------------------
_LIST_MARKER_RE = re.compile(r"^(?:[-*·•>]+|\d+[.、)．）]|[a-zA-Z][).])\s*")
_THINK_RE = re.compile(r"<think>.*?</think>", re.S)


def clean_variant(text):
    """LLM 单条输出 → 一行查询字符串（不合法返回 ""）。

    - 容忍 <think>...</think> 包裹（思考型模型外溢时剥掉）；
    - 剥列表符号/编号前缀、成对引号包裹；内部换行折叠空格（查询必须单行）；
    - 截长 DEFAULT_MQ_MAX_VARIANT_CHARS（防超长输出污染 embed 费用）。
    """
    if not isinstance(text, str):
        return ""
    t = _THINK_RE.sub(" ", text).strip()
    t = _LIST_MARKER_RE.sub("", t.strip()).strip()
    for left, right in (('"', '"'), ("'", "'"), ("「", "」"), ("‘", "’"), ("“", "”")):
        if len(t) >= 2 and t.startswith(left) and t.endswith(right):
            t = t[1:-1].strip()
    t = " ".join(t.split())
    return t[:DEFAULT_MQ_MAX_VARIANT_CHARS]


def clean_variants(query, variants, n_variants=DEFAULT_MQ_N_VARIANTS):
    """原始变体列表 → 去重/截数后的合法变体列表（上限 clamp 后的 n_variants 条）。

    - 逐条 clean_variant，空串丢弃；
    - 与原查询相同（大小写/空白不敏感）或与已保留变体重复的丢弃（重复路对
      RRF 只是同序加权，无信息增益还白花 embed 费用）；
    - 非列表输入 → []。
    """
    if not isinstance(variants, list):
        return []
    n = clamp_n_variants(n_variants)
    out, seen = [], {(" ".join(str(query or "").split())).casefold()}
    for raw in variants:
        if len(out) >= n:
            break
        v = clean_variant(raw)
        k = v.casefold()
        if v and k not in seen:
            seen.add(k)
            out.append(v)
    return out


# ---------------------------------------------------------------------------
# mq 变体观测行（log-only，R6 施工 2026-10-16）：变体全文落 journal——R5/R6a
# 定谳"mq 变体文本不可复原= harness 无法复现生产 mq 路径"已知界的修复面
# ---------------------------------------------------------------------------
VARIANTS_OBS_PREFIX = "[rag-mq-variants]"

_VARIANTS_OBS_RE = re.compile(
    r"\[rag-mq-variants\] qsha16=([0-9a-f]{16}) n=(\d+) v=(\[.*\])")


def fmt_variants_obs_line(query, variants):
    """变体生成结果 → 观测行（纯函数，恒单行，恒不抛出）。

    形态（一行承载 query sha16＋变体数＋逐变体全文，机器可解析）：
      [rag-mq-variants] qsha16=3fa2b91c3fa2b91c n=1 v=["SRS power control ..."]
    - qsha16=sha256(query utf-8)[:16]（口径同 R 线 harness rlib.qsha16：journal
      [chat] 行 q= 截 80 字符，harness 复放以本字段校验查询原文同一性）；
    - v=清洗后变体**全文**的紧凑 JSON（ensure_ascii=False 中文原样；复现需要
      全文——变体要过 embed＋词面路，sha16 不可复现嵌入输入）；行长上界=
      2 变体×300 字符＋转义 ≈1.3k，与 [rag-mq] queries 归因行同级；
    - 消费端=harness 复放（parse_variants_obs_line 解析后经 RagService
      variant_fn 注入复现 mq 路径）；生产经 rag log=self._log 自动带
      [trace:xxx] 前缀，与既有 [rag-mq] 族同通道落 journal。
    """
    vs = [str(v) for v in (variants or [])]
    qsha = hashlib.sha256(str(query or "").encode("utf-8")).hexdigest()[:16]
    return (f"{VARIANTS_OBS_PREFIX} qsha16={qsha} n={len(vs)} "
            f"v={json.dumps(vs, ensure_ascii=False, separators=(',', ':'))}")


def parse_variants_obs_line(line):
    """观测行（可为整条 journal 行，前缀允许前置 syslog/[trace:] 等前文）
    → {"qsha16","n","variants"} 或 None（非本行/形态不符/JSON 坏/n 与 v 长度
    不一致）。纯函数恒不抛出——harness 复放解析面（journal 行直接喂）。"""
    try:
        m = _VARIANTS_OBS_RE.search(str(line or ""))
        if not m:
            return None
        vs = json.loads(m.group(3))
        n = int(m.group(2))
        if (not isinstance(vs, list) or not all(isinstance(v, str) for v in vs)
                or len(vs) != n):
            return None
        return {"qsha16": m.group(1), "n": n, "variants": vs}
    except Exception:
        return None


# ---------------------------------------------------------------------------
# R3b 拆解节点挂点（2026-10-16，默认关）：触发判定→flash 拆解→子问清洗。
# 判据件=work/R3b-实施层施工-20261016/判据件-拆解节点-20261016.md（预注册）；
# 键默认关=decompose 入参 None/无此参/enabled=false/模块缺席 → 关态逐字节
# 一致（六态断言=tests/test_decompose.py）；开态=子问（≤3）替代 mq 变体进
# 检索路（routes=[原查询]+子问），不触发/失败/单意 → 回退变体生成路径。
# ---------------------------------------------------------------------------
DECOMPOSE_OBS_PREFIX = "[rag-mq-decompose]"

_DECOMPOSE_OBS_RE = re.compile(
    r"\[rag-mq-decompose\] qsha16=([0-9a-f]{16}) trig=(\d) type=(\S+) n=(\d+) "
    r"s=(\[.*\])")

DEFAULT_MQ_DECOMPOSE_TIMEOUT = 5.0     # 判据件 §二.1（与 mq 剩余预算取小）


def fmt_decompose_obs_line(query, trig, qtype, subs):
    """拆解触发观测行（纯函数，恒单行，恒不抛出）。形态（机器可解析）：
      [rag-mq-decompose] qsha16=3fa2b91c3fa2b91c trig=1 type=对比 n=2 s=["…"]
    trig=触发信号（1=触发进拆解）；type=拆解型；s=子问全文紧凑 JSON（复现面
    ——子问要过 embed+检索路，sha16 不可复现嵌入输入，同 variants 观测行口径）。
    """
    try:
        vs = [str(v) for v in (subs or [])]
        qsha = hashlib.sha256(str(query or "").encode("utf-8")).hexdigest()[:16]
        return (f"{DECOMPOSE_OBS_PREFIX} qsha16={qsha} "
                f"trig={1 if trig else 0} type={str(qtype or '?')} n={len(vs)} "
                f"s={json.dumps(vs, ensure_ascii=False, separators=(',', ':'))}")
    except Exception:
        return f"{DECOMPOSE_OBS_PREFIX} obs-fmt-fail"


def parse_decompose_obs_line(line):
    """拆解观测行 → {"qsha16","trig","type","n","subs"} 或 None（形态不符/
    JSON 坏/n 不一致）。纯函数恒不抛出（harness 复放解析面）。"""
    try:
        m = _DECOMPOSE_OBS_RE.search(str(line or ""))
        if not m:
            return None
        subs = json.loads(m.group(5))
        n = int(m.group(4))
        if (not isinstance(subs, list) or not all(isinstance(s, str) for s in subs)
                or len(subs) != n):
            return None
        return {"qsha16": m.group(1), "trig": int(m.group(2)),
                "type": m.group(3), "n": n, "subs": subs}
    except Exception:
        return None


def _clamp_decompose_timeout(val, remaining):
    """拆解超时 → (cfg 值, mq 剩余预算) 取小（非法值回默认；≤0 回 None=放弃）。"""
    try:
        t = float(val)
    except (TypeError, ValueError):
        t = DEFAULT_MQ_DECOMPOSE_TIMEOUT
    if t != t or t in (float("inf"),):
        t = DEFAULT_MQ_DECOMPOSE_TIMEOUT
    try:
        r = float(remaining)
    except (TypeError, ValueError):
        r = t
    out = min(t, r) if r > 0 else t
    return out if out > 0 else None


def _decompose_routes(query, dcfg, *, endpoint, log, wall_clock=False,
                      remaining=None):
    """触发判定→flash 拆解→子问清洗 → 子问列表（[] = 不触发/失败/单意，调用
    方回退变体生成路径）。恒不抛出（异常吞噬先例=generate_variant）。

    - dcfg={"enabled":true, "model":…, "timeout":…}（键面归 R8 拨键窗接线，
      本函数只认 dict 形态；model/timeout 缺省回 decompose 模块默认）；
    - 子问逐条 clean_variant（单行/截 300/剥包裹），casefold 与原题同文或
      重复者剔除，帽 decompose.MAX_SUBS=3；
    - 成功打 [rag-mq-decompose] 观测行（子问全文）；不触发不打行（零调用面）。
    """
    say = log or _default_log
    if _decompose is None:
        return []
    det = _decompose.detect_composite(query)
    if not det.get("triggered"):
        return []
    budget = _clamp_decompose_timeout(dcfg.get("timeout"), remaining)
    if budget is None:
        say("[rag-decompose] stop budget=0（回退变体路径）")
        return []
    call = lambda: _decompose.decompose_query(
        query, model=str(dcfg.get("model") or _decompose.DEFAULT_DECOMPOSE_MODEL),
        timeout=budget, endpoint=endpoint, log=say,
        type_hint=det.get("type_hint"))
    if wall_clock:
        res = _call_with_deadline(call, budget, "dc", say)
    else:
        res = call()
    if not res:
        return []
    origin_key = (" ".join(str(query or "").split())).casefold()
    seen = {origin_key}
    out = []
    for s in (res.get("subs") or []):
        if len(out) >= _decompose.MAX_SUBS:
            break
        v = clean_variant(s.get("q"))
        k = v.casefold()
        if v and k not in seen:
            seen.add(k)
            out.append(v)
    if not out:
        return []
    try:  # log-only 观测行：失败只弃行（异常吞噬，citation_check 同口径）
        say(fmt_decompose_obs_line(query, True, res.get("type"), out))
    except Exception:
        pass
    return out


# ---------------------------------------------------------------------------
# mq condense 多轮独立化改写（2026-10-24 施工，默认关；设计稿=运营/设计稿-
# mq-condense-20261023.md 案甲；试点=建库/work/mq盘点-20261024/；电池判据=
# 建库/work/mq施工-20261024/判据预登记-20261024.md §一施工面冻结）。
#
# 输入变换路：末轮追问＋最近 K 轮 user/assistant 历史 → 一条自含独立检索查询
# （c0），由 rag._retrieve_mq 挂在 q0 之后、既有变体之前（**不挤
# MQ_MAX_N_VARIANTS 帽**——帽管同义多样性变体，condense 是输入变换路独立恰
# 1 条）。跳过条件只许"无前史输入"一类确定性形态（防滑坡条款=设计稿 §四.3，
# 禁任何长度/词面/置信度类预测性门控）；键关/无前史=零调用零行为（L0/L1 面）。
# 观测行 [rag-mq-condense] 改写全文落 journal（R5 定谳"变体文本不落 journal=
# harness 无法复现"教训零豁免）。费用口径（启用时）：每多轮问 +1 次 flash
# （mq_condense_model，flash 档禁旗舰）+1 次 embed（走 rag 侧既有口径）；
# 生成侧走 LLM 台账、embed 走 embed 台账（两线分账）。
# ---------------------------------------------------------------------------
CONDENSE_OBS_PREFIX = "[rag-mq-condense]"

_CONDENSE_OBS_OK_RE = re.compile(
    r"\[rag-mq-condense\] qsha16=([0-9a-f]{16}) ok=1 dur=([0-9.]+)s r=(\[.*\])")
_CONDENSE_OBS_ERR_RE = re.compile(
    r"\[rag-mq-condense\] qsha16=([0-9a-f]{16}) ok=0 dur=([0-9.]+)s err=(\S+)")

DEFAULT_MQ_CONDENSE_TIMEOUT = 3.0         # condense 单段秒预算（与 mq 剩余墙钟取小）
DEFAULT_MQ_CONDENSE_HISTORY_TURNS = 4     # 前史消息条数帽（user+assistant 均计）
DEFAULT_MQ_CONDENSE_HISTORY_CHARS = 1200  # 前史字符帽（超帽保尾截头）

CONDENSE_SYSTEM_PROMPT = (
    "你是多轮对话检索查询独立化改写器。给定最近几轮对话历史（用户与助手）与"
    "末轮追问，把末轮追问改写为一条自含的独立检索查询：仅当末轮追问存在指代"
    "（它/这个/那个/上述等）、省略主语或省略限定时，才从历史补足所指的实体与"
    "限定词；补足后技术术语、参数名、3GPP 规范号与条款号（如 TS 36.214、"
    "p0-NominalPUSCH、5.1.1）原样保留，不得改写或翻译。若末轮追问自身已含明确"
    "主体与实体（包括单个术语或名词短语，如参数名、工具名），必须原样复述末轮，"
    "严禁把历史里的话题、实体或上一问的主题词并入查询——那会把检索引向末轮没有"
    "问的内容。输出必须保留末轮问句全部实体与术语，禁止替换为历史先行语。"
    "不得增删事实信息。只输出一行查询本身，不要任何解释、标号或引号。")


def condense_views(history, turns_cap=DEFAULT_MQ_CONDENSE_HISTORY_TURNS,
                   chars_cap=DEFAULT_MQ_CONDENSE_HISTORY_CHARS):
    """history（[{"role","content"},…]）→ (末轮 user 原文, 前史消息列表)。

    纯函数（确定性——"无前史跳过"判据的唯一载体）：
    - 末轮=最后一条 role=user 的非空消息；前史=其之前的全部合法消息
      （user+assistant 均入：assistant 答文确立的指代对象是拼接路覆盖不到的
      增量信息面，设计稿 §3.4）；
    - 前史先取最近 turns_cap 条（条数帽），再施 chars_cap 字符帽（保尾截头
      ——越近越相关，与 build_retrieval_query 保尾截断同向）；
    - 无 user 消息或前史为空 → (final 或 None, [])——调用方据此零调用跳过；
    - 帽值非数字/≤0 → 回默认（误配回已知安全档先例）。
    """
    try:
        tc = int(turns_cap)
    except (TypeError, ValueError):
        tc = DEFAULT_MQ_CONDENSE_HISTORY_TURNS
    if tc <= 0:
        tc = DEFAULT_MQ_CONDENSE_HISTORY_TURNS
    try:
        cc = int(chars_cap)
    except (TypeError, ValueError):
        cc = DEFAULT_MQ_CONDENSE_HISTORY_CHARS
    if cc <= 0:
        cc = DEFAULT_MQ_CONDENSE_HISTORY_CHARS
    msgs = [m for m in (history if isinstance(history, list) else [])
            if isinstance(m, dict) and m.get("role") in ("user", "assistant")
            and isinstance(m.get("content"), str) and m.get("content").strip()]
    final, cut = None, len(msgs)
    for i in range(len(msgs) - 1, -1, -1):
        if msgs[i]["role"] == "user":
            final = msgs[i]["content"].strip()
            cut = i
            break
    if final is None:
        return None, []
    prior = msgs[max(0, cut - tc):cut]     # 条数帽：最近 tc 条前史
    total = sum(len(m["content"]) for m in prior)
    while prior and total > cc:            # 字符帽：保尾截头（弃最旧）
        total -= len(prior[0]["content"])
        prior = prior[1:]
    return final, prior


def condense_input(final, prior):
    """（末轮, 前史消息列表）→ flash 用户输入串（判据预登记 §1.2 冻结形态）。"""
    lines = []
    for m in prior:
        tag = "用户" if m.get("role") == "user" else "助手"
        lines.append(f"{tag}：{m['content']}")
    hist = "\n".join(lines)
    if hist:
        return (f"对话历史（从早到晚）：\n{hist}\n末轮追问：{final}\n"
                f"独立检索查询：")
    return f"末轮追问：{final}\n独立检索查询："


def fmt_condense_obs_line(query, ok, dur, c0=None, err=None):
    """condense 观测行（纯函数，恒单行，恒不抛出）。形态（判据预登记 §1.5）：
      [rag-mq-condense] qsha16=3fa2b91c3fa2b91c ok=1 dur=0.42s r=["独立化改写全文"]
      [rag-mq-condense] qsha16=3fa2b91c3fa2b91c ok=0 dur=1.20s err=TimeoutException
    r=清洗后 c0 **全文**紧凑 JSON（c0 要过 embed＋检索路，sha16 不可复现嵌入
    输入——R5 定谳教训零豁免）；qsha16 锚 q0（与 [rag-mq-variants] 同口径，
    harness 复放以本字段校验请求同一性）。"""
    try:
        qsha = hashlib.sha256(str(query or "").encode("utf-8")).hexdigest()[:16]
        if ok:
            r = json.dumps([str(c0 or "")], ensure_ascii=False,
                           separators=(",", ":"))
            return (f"{CONDENSE_OBS_PREFIX} qsha16={qsha} ok=1 "
                    f"dur={float(dur):.2f}s r={r}")
        return (f"{CONDENSE_OBS_PREFIX} qsha16={qsha} ok=0 "
                f"dur={float(dur):.2f}s err={str(err or '?')}")
    except Exception:
        return f"{CONDENSE_OBS_PREFIX} obs-fmt-fail"


def parse_condense_obs_line(line):
    """condense 观测行（可为整条 journal 行，前缀允许前置 syslog/[trace:] 等
    前文）→ {"qsha16","ok","dur","r"} 或 {"qsha16","ok","dur","err"} 或 None
    （非本行/形态不符/JSON 坏/全长不符）。纯函数恒不抛出（harness 复放面）。"""
    try:
        s = str(line or "")
        m = _CONDENSE_OBS_OK_RE.search(s)
        if m:
            r = json.loads(m.group(3))
            if (not isinstance(r, list) or len(r) != 1
                    or not all(isinstance(x, str) for x in r)):
                return None
            return {"qsha16": m.group(1), "ok": 1,
                    "dur": float(m.group(2)), "r": r}
        m = _CONDENSE_OBS_ERR_RE.search(s)
        if m:
            return {"qsha16": m.group(1), "ok": 0,
                    "dur": float(m.group(2)), "err": m.group(3)}
        return None
    except Exception:
        return None


def condense_query(query, history, *, model=DEFAULT_MQ_MODEL,
                   timeout=DEFAULT_MQ_CONDENSE_TIMEOUT, endpoint=None,
                   log=None, wall_clock=False,
                   turns_cap=DEFAULT_MQ_CONDENSE_HISTORY_TURNS,
                   chars_cap=DEFAULT_MQ_CONDENSE_HISTORY_CHARS):
    """（q0, history）→ 独立化查询 c0 字符串或 None（任何失败弃路，恒不抛出）。

    - 无前史（确定性跳过）→ None：**零调用零打行**（L1 判读原料），跳过发生
      在端点解析之前（零 API 直证）；
    - flash 参数同变体生成先例：temperature=0（同题面复跑字节级一致）、
      enable_thinking=False、max_tokens=_MQ_MAX_TOKENS、httpx 超时=timeout；
      wall_clock=True 时单工线程硬墙钟（_call_with_deadline 先例，慢端点下
      延迟上界=预算而非端点延迟）；
    - 产物 clean_variant 清洗（剥 think/列表符号/引号、单行折叠、截 300）；
      空/清洗后空=失败（弃路零恶化，绝不抛出绝不拖垮请求）；
    - 成功/失败各打一行 [rag-mq-condense] 观测行（c0 全文/异常类型名）；
    - endpoint=(base_url, api_key) 由调用方解析传入（rag.resolve_embed_endpoint
      同源）；key 绝不回显绝不落日志。c0 与末轮追问同文时**保留**（试点胜出
      形：自含末轮的复述路=去稀释增益所在）；与 q0 的去重归 rag 侧 routes 组装。
    """
    say = log or _default_log
    final, prior = condense_views(history, turns_cap, chars_cap)
    if not final or not prior:
        return None                       # 无前史=确定性跳过：零调用零打行
    try:
        budget = float(timeout)
    except (TypeError, ValueError):
        budget = DEFAULT_MQ_CONDENSE_TIMEOUT
    if budget != budget or budget <= 0 or budget in (float("inf"),):
        return None
    user_text = condense_input(final, prior)
    t0 = time.time()

    def _call():
        base, key = endpoint
        body = {"model": model,
                "messages": [
                    {"role": "system", "content": CONDENSE_SYSTEM_PROMPT},
                    {"role": "user", "content": user_text}],
                "temperature": 0,       # 同题面复跑字节级一致（口径同变体生成）
                "max_tokens": _MQ_MAX_TOKENS,
                # qwen3 系兼容口默认开思考（计费+拖慢）；秒级预算任务显式关闭
                "enable_thinking": False}
        with httpx.Client(timeout=budget) as client:
            resp = client.post(base.rstrip("/") + CHAT_PATH, json=body,
                               headers={"Authorization": f"Bearer {key}"})
            resp.raise_for_status()
            return resp.json()

    try:
        if endpoint is None:
            raise RuntimeError("endpoint 未解析")
        if wall_clock:
            data = _call_with_deadline(_call, budget, "condense", say)
        else:
            data = _call()
        if not isinstance(data, dict):
            raise ValueError("回包形态不符")
        raw = data["choices"][0]["message"].get("content") or ""
        c0 = clean_variant(raw)
        if not c0:
            raise ValueError("生成结果为空或清洗后为空")
        try:  # log-only 观测行：失败只弃行（异常吞噬，citation_check 同口径）
            say(fmt_condense_obs_line(query, True, time.time() - t0, c0))
        except Exception:
            pass
        return c0
    except Exception as e:  # 只报异常类型名，不带任何请求细节
        try:
            say(fmt_condense_obs_line(query, False, time.time() - t0,
                                      err=type(e).__name__))
        except Exception:
            pass
        return None


# ---------------------------------------------------------------------------
# 变体生成：每变体 1 次 flash 调用（qwen3.8-flash，temperature 0）
# ---------------------------------------------------------------------------
def generate_variant(query, kind=0, *, model=DEFAULT_MQ_MODEL,
                     timeout=DEFAULT_MQ_TIMEOUT_SECONDS, endpoint=None, log=None):
    """单条变体生成 → 变体字符串或 None（任何失败返回 None，绝不抛出）。

    - kind 取 VARIANT_SPECS 下标（0=英文翻译，1=中文改述）；
    - endpoint=(base_url, api_key)，由调用方解析（rag.resolve_embed_endpoint）；
    - 回包解析口径同 建库/scripts/cr_contextualize.py：choices[0].message.content；
      空回包/形态不符=本条失败（退 None），不带重试（预算内由 generate_variants
      统一编排，单条失败不拖垮其余变体）；
    - 每次调用记一行用量日志（口径同 [rag-embed]，无 key 无 URL 无查询内容）：
      [rag-mq] gen i=0 kind=en chars=63 ok=1 dur=0.42s
      [rag-mq] gen i=0 kind=en ok=0 dur=3.00s err=TimeoutException
    """
    say = log or _default_log
    kind_key = VARIANT_SPECS[kind][0] if 0 <= kind < len(VARIANT_SPECS) else "?"
    t0 = time.time()
    try:
        if endpoint is None:
            raise RuntimeError("endpoint 未解析")
        base, key = endpoint
        body = {"model": model,
                "messages": [{"role": "system", "content": VARIANT_SPECS[kind][1]},
                             {"role": "user", "content": query}],
                "temperature": 0,       # 温度 0：同题面复跑字节级一致（口径同 CR 管线）
                "max_tokens": _MQ_MAX_TOKENS,
                # qwen3 系兼容口默认开思考模式（计费+拖慢），变体生成是秒级预算任务，显式关闭
                "enable_thinking": False}
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(base.rstrip("/") + CHAT_PATH, json=body,
                               headers={"Authorization": f"Bearer {key}"})
            resp.raise_for_status()
            data = resp.json()
        raw = data["choices"][0]["message"].get("content") or ""
        v = clean_variant(raw)
        if not v:
            raise ValueError("生成结果为空或清洗后为空")
        say(f"[rag-mq] gen i={kind} kind={kind_key} chars={len(v)} ok=1 "
            f"dur={time.time() - t0:.2f}s")
        return v
    except Exception as e:  # 只报异常类型名，不带任何请求细节
        say(f"[rag-mq] gen i={kind} kind={kind_key} ok=0 "
            f"dur={time.time() - t0:.2f}s err={type(e).__name__}")
        return None


def _call_with_deadline(fn, seconds, kind, say):
    """墙钟看门狗：fn 放单工线程执行，seconds 内未归即弃（线程自了，结果丢弃）。

    动机：httpx per-op 超时（connect/read/write/pool 各自计时）不保证单调用
    总墙钟——判定实测 flash 单调用均 7.18s、超 3s 预算仍成功返回（运营/
    hybrid-mq判定-20260919.md §三）。被弃调用仍会在自己的 per-op 超时内自了
    并补记一行 gen 日志（dur 即超支证据）。fn 异常按 None 计（恒不抛出）。"""
    ex = ThreadPoolExecutor(max_workers=1)
    try:
        fut = ex.submit(fn)
        try:
            return fut.result(timeout=max(0.0, seconds))
        except FuturesTimeout:
            say(f"[rag-mq] gen watchdog i={kind} cut wall_clock budget={seconds:.2f}s")
            return None
        except Exception:
            return None
    finally:
        ex.shutdown(wait=False)          # 不等被弃线程：预算即硬墙钟


def generate_variants(query, *, n_variants=DEFAULT_MQ_N_VARIANTS,
                      model=DEFAULT_MQ_MODEL, timeout=DEFAULT_MQ_TIMEOUT_SECONDS,
                      endpoint=None, log=None, wall_clock=False, decompose=None):
    """查询 → 变体列表（含预算编排与清洗）。任何失败 → []（退单条原查询）。

    - 预算：timeout 参数是**整个变体生成阶段**的秒数预算（mq_timeout_seconds）；
      逐变体串行调用，每次 httpx 超时取剩余预算；剩余 ≤0 即止（打 gen stop 行）。
      已得变体照用——部分成功好过全弃；
    - wall_clock=False（缺省=旧行为）：预算只在两次调用**之间**检查——httpx
      per-op 超时（connect/read 各自计时）不缚单调用总墙钟，判定实测 flash 单调
      用均 7.18s 超 3s 预算仍成功返回（运营/hybrid-mq判定-20260919.md §三）；
      wall_clock=True（2026-09-21 迭代轮，rag 键 mq_wall_clock 默认 false）：
      单调用放单工线程执行，剩余预算内未归即弃（被弃线程自了自记日志，其
      结果丢弃）——预算即硬墙钟，慢端点下 mq 延迟上界=预算而非端点延迟；
    - 单条失败（超时/HTTP/空回包）只丢该条，继续尝试下一条（预算允许时）；
    - 返回前统一 clean_variants（去重/截数），恒不抛出；
    - 返回前打 [rag-mq-variants] 观测行（R6 施工 2026-10-16，log-only）：qsha16
      ＋变体数＋清洗后变体全文（含全失败 n=0 形态）——生产 mq 变体自此可被
      harness 复放复现；早退（n≤0/空题面/预算≤0，未发起生成调用）不打行。
      观测失败只弃行绝不影响返回（异常吞噬，citation_check 恒不抛出同口径）。
    - decompose（R3b 拆解节点挂点，2026-10-16，**默认 None=关态零行为**）：
      dict 且 enabled=true 时先走触发判定（decompose.detect_composite，零
      调用）→触发则 flash 拆解（decompose.decompose_query，温度 0）→子问
      （≤3，clean_variant 清洗+与原题去重）**替代变体**返回（routes=[原查询]
      +子问进 _retrieve_mq RRF 融合，挂点位置=变体生成之前）；不触发/拆解
      失败/单意/模块缺席 → 回退本函数既有变体路径（零行为降级，判据件 §二.4）。
      拆解预算与 mq 剩余预算取小；成功时另打 [rag-mq-decompose] 观测行（型+
      子问全文，复现归因面）。键面接线（mq_decompose_* 配置族）归 R8 拨键窗
      （上产执行单草案），本件只认入参形态。
    """
    say = log or _default_log
    n = clamp_n_variants(n_variants)
    if n <= 0 or not (query or "").strip():
        return []
    try:
        budget = float(timeout)
    except (TypeError, ValueError):
        budget = DEFAULT_MQ_TIMEOUT_SECONDS
    if budget <= 0:
        return []
    deadline = time.monotonic() + budget
    # R3b 拆解挂点（默认关=零执行零漂移）：触发+成功 → 子问替代变体直接走
    # 既有观测行+返回面（harness 复放机制复用=子问即变体）；任何失败回退
    # 下方既有变体生成路径（关态行为逐字节一致）。
    if isinstance(decompose, dict) and decompose.get("enabled") \
            and _decompose is not None:
        try:
            subs = _decompose_routes(
                query, decompose, endpoint=endpoint, log=say,
                wall_clock=bool(decompose.get("wall_clock")),
                remaining=deadline - time.monotonic())
            if subs:
                try:
                    say(fmt_variants_obs_line(query, subs))
                except Exception:
                    pass
                return subs
        except Exception as e:  # 挂点异常吞噬：回退变体路径（恒不抛出）
            say(f"[rag-mq-decompose] hook fail err={type(e).__name__}"
                "（回退变体路径）")
    raw_out = []
    for kind in range(min(n, len(VARIANT_SPECS))):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            say(f"[rag-mq] gen stop i={kind} budget_spent got={len(raw_out)}")
            break
        if wall_clock:
            v = _call_with_deadline(
                lambda k=kind, r=remaining: generate_variant(
                    query, k, model=model, timeout=r, endpoint=endpoint, log=say),
                remaining, kind, say)
        else:
            v = generate_variant(query, kind, model=model, timeout=remaining,
                                 endpoint=endpoint, log=say)
        if v:
            raw_out.append(v)
    out = clean_variants(query, raw_out, n)
    try:  # log-only 观测行：变体全文落 journal（复现面）；观测失败只弃行
        say(fmt_variants_obs_line(query, out))
    except Exception:
        pass
    return out


# ---------------------------------------------------------------------------
# 多路 RRF 融合（fuse_hits 的 N 路推广；输入为 rag.search / fuse_hits 输出形态）
# ---------------------------------------------------------------------------
def rrf_fuse_hit_lists(hit_lists, topk=5, rrf_k=60.0):
    """N 条查询各自的 hits 列表 → RRF 融合 → 截 topk。

    - fused(d) = Σ_{d 入选的列表} 1/(rrf_k + 该列表内 rank)（rank 从 1 起；
      同一列表内同 idx 重复只计最优 rank）；rrf_k 非法值退 60.0（口径同
      rag.fuse_hits）；
    - 排序键 (-fused, 各列表最优 rank 元组（缺省 +inf）, idx)：同分确定性，
      列表序=查询序（原查询 q0 在前，天然保原查询的序优先）；
    - 输出 hit={"rank","score","rec","idx"} 另附归因键：queries="q0+q2"（该块
      出自哪些查询）、q_ranks=各列表最优 rank 元组（未入为 None）、cosine=跨
      列表最大余弦原始分（2026-09-21 补，主阈值闸门同口径：纯余弦列表读
      score、lexical/hybrid 列表读 cosine 键，取最大为该块最好语义证据；
      全路无值=None）——评测归因与 rag.gate_cosine 直接读；输入 hits 不被
      修改（输出为新 dict）；
    - 空列表/None 成员容忍；全部为空 → []。
    """
    lists = [lst for lst in (hit_lists or []) if lst]
    if not lists:
        return []
    k = float(rrf_k)
    if not (k > 0) or k != k or k in (float("inf"),):
        k = 60.0
    best = {}  # idx -> [各列表最优 rank 或 None, ...]（按列表序）
    recs = {}  # idx -> rec（各列表同 idx 同 rec——同一库内行，取首个即可）
    coss = {}  # idx -> 跨列表最大余弦原始分（阈值闸门口径；本件不 import rag，
    #           余弦提取规则与 rag.gate_cosine 逐字对齐，见上方 docstring）
    for li, lst in enumerate(lists):
        for h in lst:
            i = h["idx"]
            slot = best.setdefault(i, [None] * len(lists))
            if slot[li] is None or h["rank"] < slot[li]:
                slot[li] = h["rank"]
            recs.setdefault(i, h["rec"])
            c = h["cosine"] if "cosine" in h else h.get("score")
            if isinstance(c, (int, float)) and not isinstance(c, bool):
                cur = coss.get(i)
                if cur is None or c > cur:
                    coss[i] = float(c)
    out = []
    for i, ranks in best.items():
        fused = 0.0
        for r in ranks:
            if r is not None:
                fused += 1.0 / (k + r)
        qs = "+".join(f"q{li}" for li, r in enumerate(ranks) if r is not None)
        out.append({"score": fused, "rec": recs[i], "idx": i, "cosine": coss.get(i),
                    "queries": qs, "q_ranks": tuple(ranks)})
    out.sort(key=lambda h: (-h["score"],
                            tuple((1 << 30) if r is None else r for r in h["q_ranks"]),
                            h["idx"]))
    keep = out[: max(1, int(topk))]
    for rank, h in enumerate(keep, 1):
        h["rank"] = rank
    return keep
