#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""route_domain.py —— 检索路由域分类器（词表 v2=2026-09-29 D9 批档；期 1 已挂接 b337415）。

定位（运营/设计稿-分层放行与路由-20260929.md §2.2/§2.3/§2.4；批档 D1-D9=过程日志
三节 9+设计稿〇节批档注）：
- 五域（概念/口径/监管数字/参数/精确表）规则分类：零 API、纯本地确定性、零随机、
  恒不抛出；先例风格=multiquery.py/citation_check.py。
- 红线否决（§2.4 硬门控）：参数/精确表/监管数字任一信号命中 → veto=1，禁入一切
  减轻档，域面收窄与 doc 直判同样让位（一律全量检索，宁多勿漏）——**veto 逻辑
  不设关闭参数**（代码级纪律；单测断言面锁死，仅随挂接侧 route_enabled 整体关断
  =回到现行无路由行为）。
- 参数域复用 citation_check 的 HIGH_STAKES_KEYWORDS/HIGH_STAKES_PATTERNS
  （import 复用禁复制——红线词面单锚，与 A2 生产口径同源）。

**词表纪律（D9）**：五域信号词表系设计稿 §2.3 表格初稿逐字嵌入——正式采用随
期 1 放行批确认；扩改须用户决策、禁自动生效（与 cover_gate_vocab 机制同款在册
条文）。库面常量（TS_DOCS/TR_DOCS/REG_DOCS 等）与现役库 2026-09-29 快照联动
（51,794 行=TS 20 件 50,229+TR 13 件 1,155+监管 3 件 221+合成卡 189），扩库/
换库须同步修订（同 D9 决策面）。

**词表 v2（2026-09-29 D9 批档，批档指针=过程日志-qa-bot-产品家-20260916.md 三节
12②；呈报面=建库/logs/期1路由挂接-20260929.md §四 五条，仅此五条禁扩）**：
- 修订①G12/ANSG12 型单位/出处疑问形（"以什么单位上报/定义出处在哪件规范"
  ——参数类活险，最高优先）：参数行增单位/上报值/出处语境形（防"单位"泛词
  误伤=只取疑问形/组合形，裸"单位"不入表）；
- 修订②G38 型"几+单位"形：数量疑问词扩数值单位组合（几 dB/几毫秒…）；
- 修订③p0-Nominal 型单数字记号形：HIGH_STAKES_PATTERNS[0] 要求 \\d{2,}，
  单数字记号漏——放宽至 \\d{1,}+参数语境词组合（双件同步已完工 2026-09-29：
  citation_check 侧 HIGH_STAKES_SYMBOL_RE/EXCLUDE/CONTEXT 三常量逐字同源
  镜像 PARAM_V2_SYMBOL_*，同源逐字锁在 tests/test_citation_check.py；事件名
  A1-A6/B1/B2 形排除=PARAM_EVENT_RE 取值语境专闸承接，防"事件概念题不误
  veto"纪律回退）；
- 修订④拒答型库外域负信号（G33/G34 型）：库外域词命中 → 抑制域定向退全量
  （veto/doc 直判不受影响；误命中只多一次全量检索=宁多勿漏零正确性风险）；
- 修订⑤实操泛指标词（C22 型）："指标"单信号触口径误定向——口径域单域置信
  下限=2（模块常量面；route_min_confidence 配置键/classify 签名零触碰，
  §四.5"min_confidence=2 对口径域"候选面的模块内实现）。
v1 初稿面（既有 tuple/正则）逐字零改动；v2 新增面独立 tuple/常量并同步锁死
卷（tests/test_route_domain.py）；五条外任何词表条目/规则逻辑禁改（veto 无
关闭键等结构性纪律零触碰）。

挂接状态（历史注记）：本段系期 1 预备施工边界登记——期 1 挂接已完成（提交
b337415，rag.py/server.py 挂点稳定面，本轮词表 v2 对其只读）。挂点=设计稿 §2.3"实现挂点"与 §4.1——
server.py chat 入口（build_retrieval_query 之后、retrieve 之前）对拼接后 query
调 classify 一次（mq 变体继承域判定不重复分类）；rag.py _search_one 以
doc_in_domain 作选席约束（P0 decrowd 深候选池→重打分→选席架构的同构扩展位）。
挂接施工另归用户放行，以 P0 收割终态代码复核挂点。

依赖方向：本件 import citation_check（复用红线词面常量）；不 import rag/server
（挂接侧单向引用本件）；纯标准库（httpx 系 citation_check 自身依赖，本件不用）。
"""
import re

from citation_check import HIGH_STAKES_KEYWORDS, HIGH_STAKES_PATTERNS

# ---------------------------------------------------------------------------
# 域枚举与红线面
# ---------------------------------------------------------------------------
# 五域（tuple 序=稳定遍历/呈现序；D5 priority 档序判"监管数字＞精确表＞参数＞
# 口径＞概念"为二级键**未启用**——本模块冲突一律 fallback，序只作枚举稳定面）
DOMAINS = ("概念", "口径", "监管数字", "参数", "精确表")
# §2.4 veto 触发面=此三域信号词表之并（含 HIGH_STAKES 复用面）
REDLINE_DOMAINS = ("监管数字", "参数", "精确表")

ROUTE_QUERY_MAX_CHARS = 4000        # 题面截长（多轮拼接态防超长；口径量级同 citation_check）
DEFAULT_MIN_CONFIDENCE = 1          # route_min_confidence 语义默认 1（§2.3 规则 2）
DEFAULT_CONFLICT_POLICY = "fallback"
CONFLICT_POLICIES = ("fallback",)   # D5 批档：priority 档离线回放数据出来后才可启用；
                                    # 坏值/其他值（含 "priority"）一律回 fallback

# ---------------------------------------------------------------------------
# 信号词表初稿（设计稿 §2.3 表格逐字嵌入；扩改须决策禁自动生效=D9 纪律）
# ---------------------------------------------------------------------------
CONCEPT_SIGNALS = (
    "是什么", "什么是", "定义", "概念", "含义", "什么意思", "区别", "作用",
    "原理", "工作机制", "如何理解", "概述", "简介", "场景", "案例",
    "排查思路", "优化思路", "怎么处理", "流程是什么", "为什么",
)

KOUJING_SIGNALS = (
    "KPI", "指标", "计数器", "counter", "公式", "计算", "统计口径", "定义式",
    "性能测量", "PM", "话务量", "接通率", "掉话率", "掉线率", "切换成功率",
    "MOS", "CQI 口径", "测量定义", "上报口径",
)

JIANGAN_SIGNALS = (
    "工信部", "信产部", "信息产业部", "36号令", "257号", "统计公报",
    "电信服务规范", "监管", "部令", "文号", "申诉", "服务质量标准",
    "红线值", "合规", "备案", "行政处罚",
)
# 监管数字模式面（设计稿表项「"不得超过/标准是"+百分比指标形态」的模式化）
JIANGAN_PCT_RE = re.compile(
    r"(?:不得超过|标准是)[^。；;\n]{0,30}?(?:\d+(?:\.\d+)?\s*[%％]|百分之)")
JIANGAN_PCT_NAME = "不得超过/标准是+百分比"

# 参数域=HIGH_STAKES_* 复用面（顶部 import，匹配口径与 is_high_stakes_question
# 逐字同：关键词=子串 in，模式=search）+ 设计稿 §2.3 参数行新增面：
PARAM_EXTRA_SIGNALS = ("ASN.1", "IE", "字段")
# 数量疑问词扩充（初稿新增面：答案面为精确数字/枚举值的疑问形态；扩充依据=
# §3.3 风险 1 的 G07 型校准案例，正式入表随期 1 放行批=D9）
PARAM_COUNT_SIGNALS = ("最多可配", "几个", "几档", "几级", "几类")
PARAM_COMPOSE_RE = re.compile(r"由哪些[^。？?\n]{0,30}组成")   # 「由哪些…组成」G07 句式
PARAM_COMPOSE_NAME = "由哪些…组成"
# 消息名（RRCReconfiguration 型）：RRC 前缀驼峰 或 ≥2 段 PascalCase（宽进面——
# 误命中只多一次 veto=保守全量，零正确性风险，§2.4 宁多勿漏同款语义）
PARAM_MSG_NAME_RE = re.compile(
    r"(?<![A-Za-z])(?:RRC[A-Z][A-Za-z]+|[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+)(?![A-Za-z])")
PARAM_MSG_NAME = "消息名(RRCReconfiguration型)"
# 事件名+取值语境（A3/A4/A5/B1/B2——设计稿逐字面，A1/A2/A6 等扩充归 D9）：
# 事件名单独出现不触发，须同题面伴随取值语境词（防"区别/流程"类事件概念题误 veto）
PARAM_EVENT_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:A3|A4|A5|B1|B2)(?![A-Za-z0-9])", re.IGNORECASE)
PARAM_EVENT_CONTEXT = (
    "取值", "门限", "阈值", "偏移", "迟滞", "范围", "多少", "参数", "配置",
    "上报", "进入条件", "离开条件", "触发条件", "最大", "最小", "上限",
    "下限", "枚举",
)
PARAM_EVENT_NAME = "事件名+取值语境(A3/A4/A5/B1/B2)"
# HIGH_STAKES_PATTERNS 命中位命名（按 citation_check 常量区注释序：0=参数名式
# 记号 T310/N310/p0-Nominal 型，1=数值+单位；越界位按序号兜底命名）
PARAM_PATTERN_NAMES = ("参数名式记号", "数值+单位")

# ---------------------------------------------------------------------------
# 词表 v2（2026-09-29 D9 批档=过程日志三节 12②；呈报面=期1路由挂接-20260929.md
# §四 五条，仅此五条禁扩）——v1 面零改动，v2 新增面独立 tuple/常量
# ---------------------------------------------------------------------------
# 修订①（G12/ANSG12 型单位/出处疑问形——参数类活险，最高优先）：
# "RSRP 与 RSRQ 分别以什么单位上报？其定义出处 LTE 与 NR 各在哪件规范"
# 原不触参数信号 → 落概念面。防"单位"泛词误伤：只取疑问形/组合形模式，
# 裸"单位"不入表；"上报值"取报告 §四.1 语境词面。
PARAM_V2_UNIT_SOURCE_KEYWORDS = ("上报值",)
PARAM_V2_UNIT_SOURCE_RES = (
    ("v2:单位疑问形", re.compile(
        r"(?:什么|哪种|哪个|何种|啥)\s*单位"
        r"|单位\s*(?:是|为)\s*(?:什么|啥|多少|哪种|哪个|何)"
        r"|单位\s*上报|上报\s*单位")),
    ("v2:出处疑问形", re.compile(r"出处|哪件规范|哪份规范|哪个规范")),
)
# 修订②（G38 型"几+单位"形）：数量疑问词扩充数值单位组合形（v1 的
# PARAM_COUNT_SIGNALS 零改动；单位集=HIGH_STAKES 数值+单位模式同族）。
PARAM_V2_COUNT_SIGNALS = (
    "几 dB", "几 dBm", "几 ms", "几毫秒", "几秒", "几 MHz", "几 kHz",
    "几 GHz", "几 km", "几公里", "几米", "几分钟", "几小时", "几 %",
    "几个百分点", "几字节",
)
# 修订③（p0-Nominal 型单数字记号形）：记号形放宽至 \d{1,}+参数语境词组合
# （双件同步已完工 2026-09-29——citation_check 侧 HIGH_STAKES_SYMBOL_RE/
# EXCLUDE/CONTEXT 三常量逐字同源镜像 PARAM_V2_SYMBOL_*，同源逐字锁在
# tests/test_citation_check.py；route 本体三常量值零改动）。
# 事件名形排除（A1-A6/B1/B2）：PARAM_EVENT_RE 取值语境专闸承接，防
# "A3 和 A5 事件有什么区别"型事件概念题误 veto（既有纪律零回退）。
PARAM_V2_SYMBOL_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z][A-Za-z0-9_-]*\d(?![A-Za-z0-9])")
PARAM_V2_SYMBOL_EXCLUDE = frozenset(
    ("A1", "A2", "A3", "A4", "A5", "A6", "B1", "B2"))
PARAM_V2_SYMBOL_CONTEXT = (
    "含义", "定义", "是什么", "什么意思", "取值", "门限", "阈值", "配置",
    "参数", "默认值", "单位", "出处", "数值",
)
PARAM_V2_SYMBOL_NAME = "v2:单数字记号+参数语境(p0/N1型)"
# 修订④（拒答型库外域负信号，G33/G34 型）：库外域词命中 → 抑制域定向
# （routed_domain 让位退全量）；veto/doc 直判通道不受影响。误命中代价=
# 少一次域收窄=零正确性风险（宁多勿漏语义同款）。
OOD_SIGNALS = (
    "微波炉", "电磁炉", "菜谱", "食谱", "做饭", "烹饪", "外卖", "点餐",
    "淘宝", "京东", "拼多多", "抖音", "快手", "微信", "支付宝",
    "股票", "炒股", "基金", "理财", "彩票", "高考", "中考", "考研",
    "志愿填报", "分数线", "星座", "运势", "旅游", "攻略", "挂号",
    "医保", "社保", "房贷", "车贷", "育儿", "减肥", "健身",
    "游戏", "电竞", "电影", "电视剧", "综艺", "足球", "篮球", "天气",
)
# 修订⑤（实操泛指标词，C22 型）："指标"单信号触口径误定向——口径域单域
# 置信下限=2（模块常量面实现 §四.5 候选；配置键/签名零触碰）。
KOUJING_MIN_CONFIDENCE = 2

TABLE_SIGNALS = (
    "表", "Table", "对照表", "查表", "附录", "Annex", "矩阵",
    "频段表", "配置表", "映射表", "栅格",
)
# 表密集 doc 号命中（设计稿 §2.3 精确表行；38.133/36.101/36.133/32.425）
TABLE_DENSE_DOCS = ("38.133", "36.101", "36.133", "32.425")
TABLE_PRB_RE = re.compile(r"(?<![A-Za-z0-9])PRB(?![A-Za-z0-9])", re.IGNORECASE)
TABLE_PRB_NAME = "PRB/带宽组合+表语境"

# ---------------------------------------------------------------------------
# 现役库 doc 面（2026-09-29 快照，建库/vectors/embeddings.jsonl 实测对平；
# 库态联动，扩库/换库修订须决策=D9）
# ---------------------------------------------------------------------------
TS_DOCS = (
    "TS 28.552", "TS 28.554", "TS 32.423", "TS 32.425", "TS 32.432",
    "TS 36.101", "TS 36.133", "TS 36.211", "TS 36.213", "TS 36.214",
    "TS 36.300", "TS 36.321", "TS 36.331", "TS 38.133", "TS 38.211",
    "TS 38.213", "TS 38.214", "TS 38.215", "TS 38.300", "TS 38.331",
)
TR_DOCS = (
    "TR 28.861", "TR 36.805", "TR 36.824", "TR 36.839", "TR 36.842",
    "TR 36.875", "TR 36.876", "TR 36.878", "TR 36.880", "TR 36.894",
    "TR 36.902", "TR 38.828", "TR 38.830",
)
REG_DOCS = ("信息产业部令第36号", "工信部联通信〔2023〕257号", "2025年通信业统计公报")
KNOWN_DOCS = frozenset(TS_DOCS + TR_DOCS + REG_DOCS)
# 裸规范号 → doc_id（TS/TR 号段实测无冲突：TS=28.5xx/32.4xx/36.1-3xx/38.1-3xx，
# TR=28.861/36.8-9xx/38.82-830；冲突面若随扩库出现，修订须决策=D9）
_NUM_TO_DOC = {d.split(" ", 1)[1]: d for d in TS_DOCS + TR_DOCS}
# PM/KPI TS 5 件（D1 批档：口径域面含此子集——KPI 定义权威源）
KPI_TS_DOCS = frozenset(("TS 28.552", "TS 28.554", "TS 32.423",
                         "TS 32.425", "TS 32.432"))
# 监管文号别名 → doc_id（doc 号直判通道；§2.2 例举 36号令/信产部令第36号 面。
# 《电信服务规范》系 36号令所附规范、库内无独立 doc_id，别名归并同 doc——口径
# 同 smoke_accept 内置卷 expect_doc 双 token 判据）
REG_DOC_ALIASES = (
    ("信息产业部令第36号",
     ("信息产业部令第36号", "信产部令第36号", "36号令", "电信服务规范")),
    ("工信部联通信〔2023〕257号",
     ("工信部联通信〔2023〕257号", "工信部联通信", "257号", "信号升格")),
    ("2025年通信业统计公报",
     ("2025年通信业统计公报", "通信业统计公报", "统计公报")),
)

# ---------------------------------------------------------------------------
# doc 号/条款号直判通道正则（§2.2 补充通道；先例=P0 spec_suppress 的 doc 号
# 规则面：规范号须带三位小数、版本号 V18.10.0 不触发——边界纪律同款）
# ---------------------------------------------------------------------------
# 前缀形：TS 38.331 / TS38.331 / tr 36.805（大小写不敏感，输出归一库形态）
_DOC_PREFIX_RE = re.compile(
    r"(?<![A-Za-z0-9])(TS|TR)[\s\u00a0]*(\d{2}\.\d{3})(?!\d)", re.IGNORECASE)
# 裸号形：36.331（前不接数字/点/字母——防 V18.103 型版本号与 TS36.331 双计）
_DOC_BARE_RE = re.compile(r"(?<![\d.A-Za-z])(\d{2}\.\d{3})(?!\d)")
# 条款定位形："5.3.5.1"式=≥3 段点分数字（5.5.4/2.2.9/5.1.3.1 俱中；36.331 两段
# 不中）；前置排除 V/v（V18.10.0 版本号）与数字/点（日期 2025.12.3 内段不中）
_CLAUSE_RE = re.compile(r"(?<![\d.Vv])(\d{1,2}(?:\.\d{1,3}){2,})(?!\d)")
# 表密集 doc 号（词表面独立计数，与直判通道解析无关）
_TABLE_DENSE_RES = {n: re.compile(r"(?<![\d.])" + re.escape(n) + r"(?!\d)")
                    for n in TABLE_DENSE_DOCS}


# ---------------------------------------------------------------------------
# 词表条目 → 匹配正则（确定性构建；ASCII  alphanumeric 首尾加词边界环视防
# PM/IE/Table 子串误命中，CJK 首尾不加；条目内部空格放宽 \s*——"CQI 口径"与
# "CQI口径"两形俱中；IGNORECASE 统一。HIGH_STAKES_KEYWORDS 不走此面——复用
# 面保持 citation_check 原生子串口径逐字同源）
# ---------------------------------------------------------------------------
def _entry_regex(entry):
    parts = [p for p in entry.split(" ") if p]
    pat = r"\s*".join(re.escape(p) for p in parts)
    if entry[0].isascii() and entry[0].isalnum():
        pat = r"(?<![A-Za-z0-9])" + pat
    if entry[-1].isascii() and entry[-1].isalnum():
        pat = pat + r"(?![A-Za-z0-9])"
    return re.compile(pat, re.IGNORECASE)


def _kw_matchers(entries):
    return tuple((e, _entry_regex(e)) for e in entries)


_CONCEPT_M = _kw_matchers(CONCEPT_SIGNALS)
_KOUJING_M = _kw_matchers(KOUJING_SIGNALS)
_JIANGAN_M = _kw_matchers(JIANGAN_SIGNALS)
# 词表 v2：参数关键词面并入 修订①语境词+修订②"几+单位"形（v1 tuple 零改动）
_PARAM_M = _kw_matchers(PARAM_EXTRA_SIGNALS + PARAM_COUNT_SIGNALS
                        + PARAM_V2_UNIT_SOURCE_KEYWORDS + PARAM_V2_COUNT_SIGNALS)
_TABLE_M = _kw_matchers(TABLE_SIGNALS)
_OOD_M = _kw_matchers(OOD_SIGNALS)        # 词表 v2 修订④库外域负信号面


# ---------------------------------------------------------------------------
# 分域信号命中（t=规范题面；返回命中信号名 tuple，词表序稳定=等权计数的确定性面）
# ---------------------------------------------------------------------------
def _hits_kw(t, matchers):
    return tuple(name for name, rx in matchers if rx.search(t))


def _hits_jiangan(t):
    hits = list(_hits_kw(t, _JIANGAN_M))
    if JIANGAN_PCT_RE.search(t):
        hits.append(JIANGAN_PCT_NAME)
    return tuple(hits)


def _hits_param(t):
    # 复用面：关键词子串口径与 citation_check.is_high_stakes_question 逐字同
    hits = [k for k in HIGH_STAKES_KEYWORDS if k in t]
    for i, p in enumerate(HIGH_STAKES_PATTERNS):
        if p.search(t):
            name = (PARAM_PATTERN_NAMES[i]
                    if i < len(PARAM_PATTERN_NAMES) else str(i))
            hits.append("模式:" + name)
    hits.extend(_hits_kw(t, _PARAM_M))          # ASN.1/IE/字段+数量疑问词扩充面
    if PARAM_COMPOSE_RE.search(t):
        hits.append(PARAM_COMPOSE_NAME)
    if PARAM_MSG_NAME_RE.search(t):
        hits.append(PARAM_MSG_NAME)
    if (PARAM_EVENT_RE.search(t)
            and any(w in t for w in PARAM_EVENT_CONTEXT)):
        hits.append(PARAM_EVENT_NAME)
    # ---- 词表 v2（2026-09-29 D9 批档）修订①③ ----
    for name, rx in PARAM_V2_UNIT_SOURCE_RES:            # 修订①单位/出处疑问形
        if rx.search(t):
            hits.append(name)
    if any(m.group(0).upper() not in PARAM_V2_SYMBOL_EXCLUDE   # 修订③单数字记号
           for m in PARAM_V2_SYMBOL_RE.finditer(t)) \
            and any(w in t for w in PARAM_V2_SYMBOL_CONTEXT):
        hits.append(PARAM_V2_SYMBOL_NAME)
    return tuple(hits)


def ood_query_hits(t):
    """规范题面 → 库外域负信号命中 tuple（词表 v2 修订④；抑制域定向用，
    不入五域 hits 观测面——DOMAINS 枚举稳定面零触碰）。"""
    return _hits_kw(t, _OOD_M)


def _hits_table(t):
    hits = list(_hits_kw(t, _TABLE_M))
    # PRB/带宽组合+表语境：表语境=本域词表已命中任一（表/Table/附录/矩阵/栅格面）
    if hits and (TABLE_PRB_RE.search(t) or "带宽组合" in t):
        hits.append(TABLE_PRB_NAME)
    for n, rx in _TABLE_DENSE_RES.items():
        if rx.search(t):
            hits.append("表密集doc号:" + n)
    return tuple(hits)


def domain_hits(t):
    """规范题面 → {域: 命中信号名 tuple}（五域全量，观测/标定面直读）。"""
    return {"概念": _hits_kw(t, _CONCEPT_M),
            "口径": _hits_kw(t, _KOUJING_M),
            "监管数字": _hits_jiangan(t),
            "参数": _hits_param(t),
            "精确表": _hits_table(t)}


# ---------------------------------------------------------------------------
# 题面规范化与 doc 号/条款号解析
# ---------------------------------------------------------------------------
def norm_query(query):
    """任意输入 → 规范题面串（str 容错+空白折叠+截长），恒不抛出。

    非 str 走 str(text or "")（口径同 citation_check._flatten：None/0/[]/{} 等
    falsy → ""；123/dict 等 → str 形态），确定性零随机。"""
    t = str(query or "")
    if len(t) > ROUTE_QUERY_MAX_CHARS:
        t = t[:ROUTE_QUERY_MAX_CHARS]
    return " ".join(t.split())


def resolve_docs(t):
    """规范题面 → (已解析 doc_id 有序去重 list, 库外规范号引用 list)。

    显式规范号三面：TS/TR 前缀形、裸号形（按现役库号表解析出 TS/TR 前缀——
    doc 面判定用 doc_id 前缀纪律，§2.2 实现口径）、监管文号别名。库外号
    （如 24.008/TS 99.999）入 unresolved——无法定向单 doc，保守退全量。"""
    docs, unresolved, seen_nums = [], [], set()

    def _add(lst, v):
        if v not in lst:
            lst.append(v)

    for m in _DOC_PREFIX_RE.finditer(t):
        p, n = m.group(1).upper(), m.group(2)
        seen_nums.add(n)
        cand = "%s %s" % (p, n)
        if cand in KNOWN_DOCS:
            _add(docs, cand)
        elif n in _NUM_TO_DOC:
            # 前缀笔误容错：号表兜底（TS/TR 区分唯靠 doc_id 前缀，库内号唯一）
            _add(docs, _NUM_TO_DOC[n])
        else:
            _add(unresolved, cand)
    for m in _DOC_BARE_RE.finditer(t):
        n = m.group(1)
        if n in seen_nums:      # 前缀形已计（防同一引用双计成"多 doc 并现"）
            continue
        seen_nums.add(n)
        if n in _NUM_TO_DOC:
            _add(docs, _NUM_TO_DOC[n])
        else:
            _add(unresolved, n)
    for doc_id, aliases in REG_DOC_ALIASES:
        if any(a in t for a in aliases):
            _add(docs, doc_id)
    return docs, unresolved


def clause_hits(t):
    """规范题面 → 条款定位形去重 tuple（"5.3.5.1"式；V 版本号/日期段排除）。"""
    return tuple(dict.fromkeys(_CLAUSE_RE.findall(t)))


# ---------------------------------------------------------------------------
# 分类主函数（纯函数、确定性、恒不抛出、零 API）
# ---------------------------------------------------------------------------
def classify(query, *, min_confidence=DEFAULT_MIN_CONFIDENCE,
             conflict_policy=DEFAULT_CONFLICT_POLICY, doc_direct_enabled=True):
    """题面 → 路由判定 dict。判定规则五条按序（设计稿 §2.3）：

    ① 红线否决最高优先（§2.4 硬门控）：参数/精确表/监管数字任一信号命中 →
       veto=1，禁入一切减轻档，域面收窄与 doc 直判一律让位 → fallback=1
       （全量检索，出处条/A2/闸门全现行）。**veto 不设关闭参数**；
    ② 唯一域命中 → 定向该域，confidence=命中信号词数（初稿等权；
       min_confidence 默认 1，不足 → 不定向退 fallback；坏值回默认）；
       词表 v2（2026-09-29 D9 批档）附加闸两道：修订⑤口径域单域置信下限
       KOUJING_MIN_CONFIDENCE=2（"指标"单信号泛词误定向面）；修订④库外域
       负信号命中 → 抑制域定向退全量（veto/doc 直判不受影响）；
    ③ 多域共命中 → conflict=1 → 退全量（conflict_policy="fallback"=D5 批档；
       priority 档未启用——非法值/其他值一律按 fallback）；
    ④ 零命中 → 退全量（=现行行为，零恶化）；
    ⑤ doc 号/条款号直判通道（§2.2 补充通道，绕过域分类）：单一显式规范号
       （含监管别名/裸号按库表解析）→ doc_direct=该 doc_id；多 doc 号并现或
       唯一引用系库外号 → fallback。条款定位形与单 doc 号并现 → 该 doc 直判
       （条款面经 clause_locators 暴露，供期 1 挂接做 locator 级收窄）；裸条款
       号（无 doc 号）无从解析 doc 面 → 不直判、走域规则（解释性登记：设计稿
       "直判该 doc"以 doc 可解析为前提）。doc_direct_enabled=False（config 键
       route_doc_direct=false 语义）→ 整通道关断，doc 引用只观测不参与判定。

    返回键（稳定面；挂接侧**生效路由读 route 键**——doc_direct 键系观测面，
    veto=1 时仍报告命中 doc 但 route="fallback"，禁止据 doc_direct 收窄）：
      domain          唯一命中域；多域/零命中=None（veto/min_conf 下仍观测报告）
      confidence      唯一域命中信号数（等权计数）；多域/零命中=0
      domains         全部命中域 list（DOMAINS 稳定序）
      veto            0/1 红线否决（硬门控，无关闭面）
      conflict        0/1 多域共命中
      fallback        0/1 生效判定=退全量检索
      route           "doc_direct"|"domain"|"fallback" 生效路由面
      doc_direct      直判命中 doc_id（库形态归一）或 None
      docs            全部已解析 doc 引用 list（多号并现归因面）
      docs_unresolved 库外规范号引用 list
      clause_hint     0/1 条款定位形命中
      clause_locators 条款号 list（去重稳定序）
      hits            {域: [信号名]}（标定/归因观测面）
      ood             0/1 库外域负信号命中（词表 v2 修订④观测面）
      ood_hits        库外域信号名 list（同 v2 修订④）
    """
    t = norm_query(query)
    hits = domain_hits(t)
    ood_hit = ood_query_hits(t)          # 词表 v2 修订④（D9 批档）
    domains_hit = tuple(d for d in DOMAINS if hits[d])
    veto = 1 if any(hits[d] for d in REDLINE_DOMAINS) else 0

    try:
        mc = int(min_confidence)
    except (TypeError, ValueError):
        mc = DEFAULT_MIN_CONFIDENCE
    mc = max(1, mc)
    policy = (conflict_policy if conflict_policy in CONFLICT_POLICIES
              else DEFAULT_CONFLICT_POLICY)

    docs, unresolved = resolve_docs(t)
    clauses = clause_hits(t)
    dd_on = bool(doc_direct_enabled)
    refs_total = len(docs) + len(unresolved)
    if dd_on:
        doc_direct = docs[0] if (refs_total == 1 and docs) else None
        # 多 doc 号并现 → 退全量；唯一引用系库外号 → 无从定向同样退全量
        doc_face_fallback = refs_total >= 2 or (refs_total == 1 and not docs)
    else:
        doc_direct, doc_face_fallback = None, False

    conflict = 1 if len(domains_hit) > 1 else 0
    if len(domains_hit) == 1:
        domain = domains_hit[0]
        confidence = len(hits[domain])
    else:
        domain, confidence = None, 0
    # 词表 v2（2026-09-29 D9 批档）：修订⑤口径域单域置信下限=2（mc 仍为
    # 全局下限，route_min_confidence 配置键/签名面零触碰）；修订④库外域
    # 负信号命中 → 抑制域定向（veto/doc 直判通道不受影响）
    dom_floor = KOUJING_MIN_CONFIDENCE if domain == "口径" else 1
    routed_domain = (domain is not None and confidence >= max(mc, dom_floor)
                     and policy == DEFAULT_CONFLICT_POLICY and conflict == 0
                     and not ood_hit)

    if veto:                        # ① 最高优先：一切收窄让位
        fallback, route = 1, "fallback"
    elif doc_face_fallback:         # ⑤ 多号并现/库外号
        fallback, route = 1, "fallback"
    elif doc_direct is not None:    # ⑤ 单 doc 直判（绕过域分类）
        fallback, route = 0, "doc_direct"
    elif routed_domain:             # ② 唯一域定向（含 min_confidence 门）
        fallback, route = 0, "domain"
    else:                           # ③④ 冲突/零命中/置信不足 → 退全量
        fallback, route = 1, "fallback"

    return {"domain": domain, "confidence": confidence,
            "domains": list(domains_hit), "veto": veto, "conflict": conflict,
            "fallback": fallback, "route": route, "doc_direct": doc_direct,
            "docs": list(docs), "docs_unresolved": list(unresolved),
            "clause_hint": 1 if clauses else 0,
            "clause_locators": list(clauses),
            "hits": {d: list(hits[d]) for d in DOMAINS},
            "ood": 1 if ood_hit else 0, "ood_hits": list(ood_hit)}


def format_log_line(res):
    """classify 结果 → [rag-route] 打点行（§2.3 格式，不含题面文本——纪律同
    [rag-hybrid]；挂接侧可直接落日志/trace）。"""
    return "[rag-route] domain=%s conf=%d veto=%d fallback=%d" % (
        (res or {}).get("domain") or "-", int((res or {}).get("confidence") or 0),
        int((res or {}).get("veto") or 0), int((res or {}).get("fallback") or 0))


# ---------------------------------------------------------------------------
# 域面选席约束（§2.2 域映射表的库行判定单锚；供期 1 rag._search_one 挂接，
# 本模块自身不挂接。检索后兜底=候选不足回退全量+fallback 标记，系 rag 侧
# 第二层回退逻辑，不在本件——本件纯判定面）
# ---------------------------------------------------------------------------
def doc_in_domain(rec, domain):
    """库行元数据 rec（dict，缺字段容错）→ 是否属该路由域面。恒不抛出。

    判定纪律（§2.2 实现口径+附节不一致 2/3）：
    - doc_id 前缀为准、元数据字段为辅：TR/TS 同 corpus_type=3gpp，区分唯靠
      doc_id 前缀 "TR "；TS 38.133×1,460+TS 38.214×16=1,476 行缺
      source_domain/layer/corpus_type 三字段——一律 doc_id 兜底，防整块漏出域面；
    - 合成卡 189（corpus_type/chunk_type=case_card、source_domain=synthetic；
      doc_id 同锚 doc 多带 "TS " 前缀）归概念面，不得并入参数面；
    - 口径域按 D1 批档含 PM/KPI TS 5 件；设计稿"TR 速查面（summary 13 块为
      骨架）"按 TR 全行实现（速查面载体=TR 行，骨架≠收窄面）——若期 1 标定
      要收窄到 summary-only 属域面修订，须决策（D9）；
    - 精确表=TS 域面内 chunk_type∈{table_row_group,asn1_card} 细分
      （route_table_facet 二级键面，默认关=不细分防召回损失）；
    - 未知域/非 dict → False。
    """
    if not isinstance(rec, dict) or domain not in DOMAINS:
        return False
    doc_id = str(rec.get("doc_id") or "")
    corpus_type = str(rec.get("corpus_type") or "")
    chunk_type = str(rec.get("chunk_type") or "")
    source_domain = str(rec.get("source_domain") or "")
    is_card = (corpus_type == "case_card" or chunk_type == "case_card"
               or source_domain == "synthetic")
    if domain == "概念":
        return is_card or doc_id.startswith("TR ")
    if domain == "口径":
        return is_card or doc_id.startswith("TR ") or doc_id in KPI_TS_DOCS
    if domain == "监管数字":
        # doc_id 三件精确为准；corpus_type/source_domain 为辅助兜底（缺字段行
        # 两辅助键均空串，不会误入）
        return (doc_id in REG_DOCS or corpus_type == "监管"
                or source_domain == "miit")
    if domain == "参数":
        return doc_id.startswith("TS ") and not is_card
    return (doc_id.startswith("TS ") and not is_card      # 精确表
            and chunk_type in ("table_row_group", "asn1_card"))
