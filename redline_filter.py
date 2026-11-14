#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""redline_filter——红线题答案方向性表述确定性过滤器·在线模块（F线Q 生产化，2026-10-14）。

血统与依据（单一语义源纪律）：
- 规则=P 线 p2_filter.py v1 **逐字复用**（建库/work/F线P-20261014/p2_filter.py；
  预注册=同目录 施工日志-P-20261014.md §〇-P2-1；模式表本身=O 线 O5 机检
  预注册六模式逐字复用——建库/work/F线O-20261014/施工日志 §〇-O1-2）。
- 决策=运营/F线/冻结点3-判定二窗后快照-20261014.md §四 终审决策登记③：
  "YDT-013 确定性过滤器随部署窗上线（生产化形态=log-only 检测先行、剥离启用
  待观察数据决策——沿 pii_mask 先例，质量与安全第一）"。
- 实证链：措辞路线三轮证伪（F 线复测+O4 重答+P2 温0 逐字节复现）后工程路线
  取胜——P2b 机检 pass（过滤后零方向性+零数值推测，1 轮收敛，幂等 ✓；对照
  全绿：阳性 L 窗 5 命中/O4 档案 2→0/阴性 0）。

定位与姿态（三条铁律，与 pii_mask/career_detect 同风格）：
1. **log-only 检测先行**：只对答案完成面做确定性检测，命中>0 打一行
   [redline_filter] 观测行（只有 trace/计数/模式名，**零原文**），**不改答案、
   不影响检索/答题/SSE 事件面**。转 enforce（句级拦截替换）归观察数据决策，
   禁自动生效。
2. **零原文**：日志与返回值只有计数/模式名/布尔——任何原文片段不出本模块
   （detect() 的 context 字段仅供调试调用方在**本地**消费，server 挂载面不打印）。
3. **fail-open**：模块缺席=off 不挂载（server 侧 try/except 退关闭）；本模块
   任何输入异常=零命中零日志，绝不抛出、绝不拖垮 /api/chat 主链路。

开关（server 挂载消费）：config 顶层键 redline_filter_mode 二态——
  - "off"       零动作零日志（一键关）；
  - "log_only"  **默认值**（缺键/坏值一律回此，沿 pii_mask 缺省即观察态设计）。
    命中>0 打 [redline_filter] 行，答案原样。
  v1/v2 均不收 "enforce"（resolve_mode 见到该值亦回 log_only）——句级拦截
  属观察后决策位，届时另行版本化登记（版本化纪律：改任何模式/参数须回 P2
  对照组重跑登记；v2 版本号已被词表扩容登记占用，enforce 拨键另属一条决策线）。

过拦偏严声明（P2 预注册原文沿用）：bare_cmp 等模式对**合法**比较句（如引用
规范原文的"高于/更严格"）同样命中——安全向设计取舍，如实声明。log_only 观察
数据的意义恰在量化该噪声面（周消费：命中轮占比〔分母=[chat] 完成轮〕+分模式
计数），为"是否转 enforce/是否收窄模式表"提供决策依据。

零依赖：纯标准库 re；零网络零 API 零计费（本地规则计算）。
版本：v1（2026-10-14，P 线 p2_filter.py 生产化提取；模式参数与 P2 逐常量一致）。
2026-10-15 评审立改批 X2（R4/R5，零模式零参数改动——不触发版本化重跑）：
observe_answer 观测行补 flush=True（对齐 pii_mask/server 惯例）；
count_by_pattern/observe_answer except 静默路径加限频 [redline_filter]
err=<异常类型> 遥测行（进程级一次/小时，零原文；fail-open 语义不变）。
v2（2026-10-15，R1 词表扩容+繁简归一化层；规格源=work/代码评审-20261015/
R1词面覆盖矩阵.md §四草案，用户决策立项施工）：
① CMP 组内 +10 词（更加严格/更加宽松/更加严/优于/严于/强于/宽于/逊于/胜过/
  不及）；② dir_assert 尾组 +严/松 单字（"比/较…还严/更松了"族翻正；内联组
  提升为常量 DA_TAIL，结构余部逐字不变）；③ DIR 组内 +不及/逊于/超过/超出；
  ④ spec_num 前缀组 +大约/约为/或将/有望/预估/料将/恐将/差不多（裸"约"不收
  ——合约期限 FP 探针实证排除；内联组提升为常量 SPEC_LEAD）；⑤ 新增繁简
  归一化层 _normalize（检测前繁→简静态映射 23 字，覆盖六词组全字符集的繁体
  变体差集，一次性关闭繁体字符面；R2 词内插字符剥除预留同一入口）。
  草案标称"核心 23 词"=CMP10+尾词2+DIR4+spec8 的组位合计（24 组位/22 去重
  词形，不及/逊于跨 CMP/DIR 双位复用；标称口径差待矩阵档更正，按草案分组表
  逐词落码）。备选 6 词（领先/超过→CMP、不如/没有→dir_assert 前缀、严格得
  多/宽松得多）FP 面高不入（矩阵 §四登记，归后续决策）。
  矩阵回归（81 题，tests/test_redline_filter.py 夹具）：对抗零命中 v1 57/69
  → v2 10/69（残余=领先×3/超过无数字×2/X得多×2/没有…严×1/中文数字×2，
  登记为 known-miss；中文数字=边界声明内，v1 设计即只认 \\d 阿拉伯数字）。
  ⑥ 性能层（v2 施工内新增，两件套）：ReDoS 抽测发现 24k 触发风暴（如
  "通常更"×8000）下 adv_cmp 族 O(N×间隙宽×词枝数) 有界回扫达 ~28ms，超
  10ms 红线——(a) 同隙零宽前瞻护栏 _gap_guard（词组首字在间隙内出现的必要
  条件，首字类从词组程序化派生零漂移；只裁失败路径回扫）；(b) bare 成词
  预过滤 _has_cmp_word（adv 命中必含 CMP 成词⇒全文无成词即整位跳过 adv
  两模式扫描）。两者零宽/零语义变（等价性证据=矩阵回归+既有单测全绿），
  风暴实测：纯诱饵 28→~3ms、非首字风暴 ~2ms、混合全要素 ~7ms、真实命中
  密集 ~3ms。已知残余（登记待决策）：极限形态"24k 诱饵海+全文仅一处成词"
  仍 ~27ms（1.1μs/字，有界线性无灾难回溯；本模块输入=自有 RAG 答案文本，
  该形态不可达）——根治路径=离正则扫描改写或窗口跳跃双字护栏（原型已验
  等价、成本权衡在档），归后续决策，不因复杂度隐性引入安全模块。
  备选 6 词与 enforce 拨线口径见上；enforce 拨键仍属另一决策线（不因 v2
  自动生效；fail-open/off 语义零动）。P2 对照组重跑登记=待办位（本轮仅
  本地施工+矩阵回归自验；上云部署归批次②）。
"""
import contextlib
import re
import time

# ---------- 开关二态（v1） ----------
MODE_OFF = "off"
MODE_LOG_ONLY = "log_only"
MODES = (MODE_OFF, MODE_LOG_ONLY)
DEFAULT_MODE = MODE_LOG_ONLY   # 缺省即观察态（沿 pii_mask 先例；转 enforce 归决策）
CONFIG_KEY = "redline_filter_mode"   # config.json 顶层键（文档位=本 docstring）

FILTER_VERSION = ("redline-filter v2（2026-10-15；词表 v1→v2=R1 核心扩词（CMP+10/"
                  "尾词+2/DIR+4/spec+8）+繁简归一化层；规格源=R1词面覆盖矩阵.md；"
                  "enforce 拨键另属决策线）")

# ---------- 六模式词组（v2，2026-10-15；规格源=R1词面覆盖矩阵.md §四） ----------
# v1 基线=O5 机检模式表预注册原文（逐字复用 P 线 p2_filter.py）；v2 在各词组
# (?:...) 组内增补核心词+繁简归一化层（见 _normalize）。
# 构造纪律（矩阵 §五.4）：增补词必须收进组内——组外串接会脱离结构裸匹配
# （tests/test_redline_filter.py 构造位断言锁定）。
ADV = r"(?:通常|往往|一般而言|一般来说|大概率|多半|大多|普遍|常见|典型)"
ADV_PLAIN = r"(?:通常|往往|一般|大概率|多半|大多|普遍|常见|典型)"
CMP = (r"(?:更严格|更宽松|更严|更松|更高|更低|更大|更小|更紧|更先进|更苛刻"
       r"|更加严格|更加宽松|更加严|优于|严于|强于|宽于|逊于|胜过|不及)")   # v2：+10
DIR = (r"(?:远低于|远高于|明显低于|明显高于|显著低于|显著高于|低于|高于"
       r"|不及|逊于|超过|超出)")   # v2：+4
DA_TAIL = r"(?:严格|宽松|高|低|大|小|紧|严|松)"   # v2：+严/松（v1 内联组提升为常量）
SPEC_LEAD = (r"(?:可能|或许|也许|大概|预计|估计"
             r"|大约|约为|或将|有望|预估|料将|恐将|差不多)")   # v2：+8（裸"约"不收）


def _first_chars(group_src):
    """词组各枝首字去重排序 → 字符类源（v2 性能护栏派生量；枝均纯词面，
    构造纪律断言锁定，首字经 re.escape 无字符类注入面）。"""
    return "[" + "".join(sorted({re.escape(a[0])
                                 for a in group_src[3:-1].split("|")})) + "]"


def _gap_guard(gap_src, group_src):
    """同隙零宽前瞻护栏（v2 性能层之一，语义等价）：词组首字在间隙内出现=
    原模式可匹配的必要条件——原可匹配则护栏必过（零宽不占跨度、不改计数），
    只裁失败路径回扫；与 _has_cmp_word 预过滤合力压风暴耗时（见头注⑥，
    等价性证据=矩阵回归+既有单测全绿）。"""
    return r"(?=" + gap_src + _first_chars(group_src) + r")"


_GAP_ADV = r"[^。；;\n]{0,20}"
_GAP_DA = r"[^。；;\n]{0,16}"

PATTERNS = [
    ("adv_cmp", re.compile(ADV + _gap_guard(_GAP_ADV, CMP) + _GAP_ADV + CMP)),
    ("adv_cmp_plain", re.compile(ADV_PLAIN + _gap_guard(_GAP_ADV, CMP)
                                 + _GAP_ADV + CMP)),
    ("bare_cmp", re.compile(CMP)),
    ("dir_assert", re.compile(r"(?:较|比)" + _gap_guard(_GAP_DA, DA_TAIL)
                              + _GAP_DA + DA_TAIL)),
    ("dir_num", re.compile(r"(?:远|明显|显著)?" + DIR + r"[^\d。；;\n]{0,6}\d+(?:\.\d+)?%?")),
    ("spec_num", re.compile(SPEC_LEAD + r"[^。；;\n]{0,10}"
                            r"\d+(?:\.\d+)?%?")),
]

_PAT_BY_NAME = dict(PATTERNS)   # 供 bare 成词预过滤按名取模（私有索引）

PATTERN_NAMES = tuple(name for name, _ in PATTERNS)

SENT_SPLIT = re.compile(r"(?<=[。；;！？\n])")
FALLBACK_SENT = "（库内无现行依据，此处不作方向性表述；现行数值请以主管部门现行文件为准。）"

# ---------- 繁简归一化层（v2，2026-10-15；矩阵 §四：一次性关闭繁体字符面） ----------
# 覆盖口径=六词组全字符集的繁体变体差集（23 字静态映射，非全量 T2S——本模块
# 只需模式词面可达）；检测前统一映射。R2（词内插字符剥除，剥 ZWSP 等）预留
# 同一入口——届时在 translate 前串接。
_T2S_MAP = {
    "嚴": "严", "寬": "宽", "鬆": "松", "緊": "紧", "進": "进", "優": "优",
    "於": "于", "強": "强", "遜": "逊", "勝": "胜", "過": "过", "遠": "远",
    "顯": "显", "計": "计", "預": "预", "約": "约", "為": "为", "將": "将",
    "許": "许", "說": "说", "來": "来", "見": "见", "較": "较",
}
_T2S_TABLE = str.maketrans(_T2S_MAP)


def _normalize(text):
    """检测前繁→简归一化（v2 行为层；str.translate 纯内存映射）。

    输入须为 str（count_by_pattern 已 str 兜底；detect 沿 v1 惯例由调用方保证）。
    简体文本零扰动（映射键均为繁体独占码位）。"""
    return text.translate(_T2S_TABLE)

# ---------- fail-open 异常遥测（2026-10-15 评审立改批 R5） ----------
# except 静默路径的限频打点：[redline_filter] err=<异常类型>——只打类型名，
# 零原文零堆栈；进程级一次/小时（系统性异常=观察数据整窗归零时，日志面与
# "零命中/off"至少留一行区分痕迹）。fail-open 语义不变。
_ERR_LAST = [0.0]


def _log_err(e, log=print):
    """fail-open 异常遥测行（限频一次/小时）；本函数自身任何异常静默——
    遥测绝不反噬 fail-open 主链路。"""
    now = time.monotonic()
    if now - _ERR_LAST[0] < 3600.0:
        return
    _ERR_LAST[0] = now
    with contextlib.suppress(Exception):
        log(f"[redline_filter] err={type(e).__name__}", flush=True)


def _has_cmp_word(t):
    """bare 成词预过滤（v2 性能层）：adv_cmp/adv_cmp_plain 的任何命中必然
    内含一次 CMP 成词（匹配跨度含 CMP 子串）⇒ 全文无 CMP 成词时两模式必零，
    可整位跳过其扫描（语义零变——等价性证据=矩阵回归+既有单测+构造位断言）。

    背景：无预过滤时 24k 纯诱饵风暴（如"通常更"×8000）下 adv 族有界回扫
    达 ~28ms；预过滤后整位跳过（实测 ~3ms）。"""
    return _PAT_BY_NAME["bare_cmp"].search(t) is not None


def detect(text):
    """六模式全形态命中清单（pattern/match/context；检测前过繁简归一化层）。

    adv_* 两模式在全文无 CMP 成词时跳过扫描（_has_cmp_word 预过滤，命中
    集合零变）。context 仅供本地调试消费——server 挂载面零打印（零原文铁律）。"""
    hits = []
    t = _normalize(text)
    adv_skip = not _has_cmp_word(t)
    for name, pat in PATTERNS:
        if adv_skip and name in ("adv_cmp", "adv_cmp_plain"):
            continue
        for m in pat.finditer(t):
            s = max(0, m.start() - 18)
            e = min(len(t), m.end() + 18)
            hits.append({"pattern": name, "match": m.group(0)[:40],
                         "context": t[s:e].replace("\n", " ")})
    return hits


def count_by_pattern(text):
    """text → {模式名: 命中数}+total（零原文；log_only 观测行的数据源）。

    fail-open：任何异常=全零 dict。adv_* 两模式过 _has_cmp_word 预过滤。"""
    zero = {name: 0 for name in PATTERN_NAMES}
    try:
        t = _normalize(str(text or ""))
        out = dict(zero)
        adv_skip = not _has_cmp_word(t)
        for name, pat in PATTERNS:
            if adv_skip and name in ("adv_cmp", "adv_cmp_plain"):
                continue
            out[name] = len(pat.findall(t))
        out["total"] = sum(out[n] for n in PATTERN_NAMES)
        return out
    except Exception as e:
        _log_err(e)
        out = dict(zero)
        out["total"] = 0
        return out


def observe_answer(mode, text, trace_id="", log=print):
    """server 挂载唯一入口（v1）：off=零动作；log_only=命中>0 打一行观测行。

    行格式：[redline_filter] mode=log_only trace=xxxxxxxx hits=N
            pat=adv_cmp:2,dir_num:1（只列命中>0 的模式；零原文）。
    绝不改文本、绝不抛出（fail-open 铁律）。返回计数 dict（观测面零副作用）。"""
    try:
        if mode != MODE_LOG_ONLY:
            return None
        counts = count_by_pattern(text)
        if not counts.get("total"):
            return counts
        pat_s = ",".join("%s:%d" % (n, counts[n]) for n in PATTERN_NAMES
                         if counts.get(n))
        log("[redline_filter] mode=%s trace=%s hits=%d pat=%s"
            % (MODE_LOG_ONLY, trace_id or "-", counts["total"], pat_s),
            flush=True)
        return counts
    except Exception as e:
        _log_err(e, log)
        return None


def _split_sentences(text):
    parts = [p for p in SENT_SPLIT.split(text) if p]
    return parts


def _is_clean(text):
    return not detect(text)


def filter_answer(text, max_rounds=2):
    """句级拦截过滤 → (filtered_text, rounds_log, converged)。

    **v1 挂载面不调用**（enforce 归观察后决策；保留=P2 语义源不删，届时直接
    复用免重测漂移）。命中句整句替换为兜底句（保留原句尾分隔符——句法结构
    零破坏）；converged=False=迭代 max_rounds 轮后仍命中（登记待人工改写）。
    幂等=兜底句零命中结构性保证 filter(filter(x))==filter(x)（P2b 实证）。"""
    rounds_log = []
    cur = text
    for rnd in range(1, max_rounds + 1):
        n_hit = 0
        out = []
        for s in _split_sentences(cur):
            if detect(s):
                tail = s[-1] if s and s[-1] in "。；;！？\n" else ""
                out.append(FALLBACK_SENT + tail)
                n_hit += 1
            else:
                out.append(s)
        cur = "".join(out)
        rounds_log.append({"round": rnd, "sentences_hit": n_hit})
        if _is_clean(cur):
            return cur, rounds_log, True
    return cur, rounds_log, _is_clean(cur)


def resolve_mode(config: dict) -> str:
    """config dict（server.CONFIG 形态）→ 开关二态清洗。

    缺键/非字符串/未知值（含 enforce——不收）→ DEFAULT_MODE（log_only）。"""
    try:
        v = str((config or {}).get(CONFIG_KEY) or "").strip().lower()
    except Exception:
        return DEFAULT_MODE
    return v if v in MODES else DEFAULT_MODE
