#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""career_detect——毕业季职业向探测器在线模块（F线 CD2-2，2026-10-14）。

规则来源：建库/work/F线C-20261014/探测器校准-20261014.py vC1.2（344 条金标回测
P=1.0000 / R=0.9586 / F1=0.9789，零误报；校准报告=运营/F线/C线-探测器校准
报告-20261014.md）。本文件把校准脚本的规则参数与判定逻辑**原样提取**为可在线
挂载的独立模块：词表/正则/阈值与校准脚本逐常量一致（血统一致性由
tests/test_career_detect.py 对校准脚本正向抽样断言守恒）；改任何参数=升
DETECTOR_VERSION 并回 344 条金标重跑登记（版本化纪律，校准报告 §五）。

定位与姿态（三条铁律，与 pii_mask 同风格）：
1. **log-only 纯标注**：只输出布尔判定/命中支路/信号明细，不改消息、不影响
   检索/答题/拒答行为——职业向不建拒答模板是决策基线，探测错分不影响答题。
2. **零原文零掩码**：对外返回值只有 bool/支路名/信号布尔明细，任何原文片段
   不出本模块（[chat] career= 字段零题面零密值）。
3. **fail-open**：模块缺席=off 不挂载（server 侧 try/except 退关闭）；本模块
   任何输入异常=不命中（False），绝不抛出、绝不拖垮 /api/chat 主链路。

开关（server 挂载消费）：config 顶层键 career_log 二态——
  - "on"  [chat] 行尾附 career=hit|- 标注（命中/未命中各一字段值）；
  - "off" 默认值。缺键/坏值一律 off（零动作零日志零字段）。
启用归决策（呈报位=运营/F线/CD2-观测挂载呈报-20261014.md；观察面口径=
career= 命中率作为毕业季探测器北极星周报消费面，周抽检版本化见校准报告 §五）。

零依赖：纯标准库 re；零网络零 API 零计费（本地规则计算）。
版本：vC1.2（2026-10-14，与校准脚本终版同步提取）。
"""
import re

# ---------- 开关二态 ----------
MODE_ON = "on"
MODE_OFF = "off"
MODES = (MODE_ON, MODE_OFF)
DEFAULT_MODE = MODE_OFF      # 默认关（log-only 挂载启用归决策，禁自动生效）
CONFIG_KEY = "career_log"    # config.json 顶层键（文档位=本 docstring+呈报档）

# ================= 探测器参数（版本化；与校准脚本 vC1.2 逐常量一致） =================
DETECTOR_VERSION = "career-detector vC1.2（2026-10-14；vC1.1 基础上补职责复合词两枚，终版）"

# ---- 信号词组（组合命中：至少走一条"信号组∧无对应排除"的支路才算命中） ----
# S1 面试（强信号，无排除面——面试话术与优化意图天然不共现）
SIG_INTERVIEW = ("面试", "话术", "该怎么回答", "怎么回答", "该怎么说",
                 "会问到", "多问一些", "自我介绍")
# S2 简历（强信号；含改写流追问短语与粘贴特征词，对齐第10卷规则 P1）
SIG_RESUME = ("简历", "意向岗位", "教育经历", "个人资料", "相关技能",
              "自我评价", "写进简历", "帮我填", "模板中的", "修改通顺",
              "再写细", "换一点", "再来一点", "再补充", "帮我补充", "写一段",
              "降本增效", "助力网络", "精准识别", "主导全网", "显著提升",
              "公司名称", "工作经历", "有限公司", "至今", "扩写", "精选",
              "求职")
# 简历版式特征（姓 名 分写/期程行 20XX.XX-）
RESUME_FORM_RE = re.compile(r"姓\s*名|20\d{2}[./]\d{1,2}\s*[-—~]\s*(至今|20\d{2})")
# S3 联系方式共现（弱信号，仅与版式/多行特征组合成支路）
SIG_CONTACT = ("电话", "邮箱", "手机", "联系方式", "e-mail", "E-mail",
               "<11位已掩码>", "<姓名>")
# S4 职责问面（中信号；受优化意图+技术活动词双排除约束）
SIG_DUTY = ("工作内容", "主要工作", "日常工作", "岗位职责", "职责",
            "做些什么", "做什么的", "做什么", "哪些工作", "会做些什么",
            "工作职责", "负责什么", "主要内容", "具体工作", "工作细节",
            "工作sop", "SOP", "sop", "工作有哪些", "工作主要", "详细工作")
# S5 JD/条文解读（中信号；受技术术语排除——含术语则落技术域，对齐提案 §1.2）
SIG_JD = ("这是什么意思", "具体是做什么的", "具体是做些什么工作",
          "做些什么工作", "具体做什么的")
# S6 岗位名词残片（弱信号；仅短残片形态受，对齐补丁 P3：LTE/NR后台分析工程师）
TITLE_RE = re.compile(
    r"(?:LTE|NR|5[Gg]|4[Gg]|GSM|WCDMA)?[\s]*"
    r"(?:无线|网优|后台|数据|路测|测试|接入网|核心网|传输|优化)?"
    r"[\u4e00-\u9fa5]{0,4}工程师")
TITLE_MAX_LEN = 30   # 残片形态长度上限（超长=正常问句不按残片判）
TITLE_TAIL_MAX = 4   # 纯残片判：剥去职称匹配段后剩余（去空白标点）字符上限

# ---- 排除词表 ----
# E1 优化/处置意图（对齐 METHOD_QUERY_SIGNALS 优化面 + 解决/配置/修改/开关族）
EXC_OPTIMIZE = ("怎么优化", "如何优化", "怎么提升", "如何提升", "怎么降低",
                "怎么处理", "如何处理", "怎么排查", "排查思路", "优化思路",
                "优化方法", "处理方法", "操作方法", "具体操作", "怎么整治",
                "整治方案", "怎么解决", "如何解决", "怎样配置", "怎样修改",
                "怎么开", "怎么办", "该怎么做", "怎么做", "怎样做")
# E2 技术活动词（职责支路排除面=外场活动，对齐提案 §1.2 岗位职责闸；非域词）
EXC_ACTIVITY = ("路测", "DT", "CQT", "拉网", "簇", "单站验证", "单验",
                "MR", "灌包", "CHR", "ping", "Ping", "拨测")
# E3 技术术语（JD 支路排除面，对齐提案 §1.2 JD 闸）
EXC_TECH_TERM = ("SSB", "波束", "RSRP", "PCI", "PRB", "SINR", "RRC",
                 "a3-Offset", "counter", "Counter", "TDD", "MML")


def _hit(text, words):
    return any(w in text for w in words)


def _is_bare_title(t: str) -> bool:
    """纯岗位名词残片判定（vC1.1 收紧）：长度 ≤TITLE_MAX_LEN 且剥去职称
    匹配段后剩余（去空白与标点）≤TITLE_TAIL_MAX 字符——只收"LTE/NR后台
    分析工程师"式裸残片，"网优工程师，处理弱覆盖有哪些手段"（职称+技术
    问句）不入此支路（vC1.0 全部 12 例 FP 均系此形态误收）。"""
    if len(t.strip()) > TITLE_MAX_LEN:
        return False
    m = TITLE_RE.search(t)
    if not m:
        return False
    rest = (t[:m.start()] + t[m.end():])
    rest = re.sub(r"[\s，。,；;、（）()：:？?！!]", "", rest)
    return len(rest) <= TITLE_TAIL_MAX


def detect_career(q: str):
    """问面 → (是否职业向, 命中支路, 信号/排除明细)。

    支路优先序（首中即停，对齐第10卷提案 §1.2 职业向四闸+残片补丁）：
    S1 面试 → S2 简历 → S5 JD(∧无技术术语) → S4 职责(∧无优化意图∧无技术活动)
    → 联系方式∧版式/多行（简历粘贴兜底） → S6 岗位名词残片(∧短∧无排除)。

    明细 dict 键=interview/resume/contact/duty/jd/title/multi_line/
    exc_opt/exc_act/exc_term（全布尔，零原文）。纯函数。"""
    t = str(q or "")
    s_interview = _hit(t, SIG_INTERVIEW)
    s_resume = _hit(t, SIG_RESUME) or bool(RESUME_FORM_RE.search(t))
    s_contact = _hit(t, SIG_CONTACT)
    s_duty = _hit(t, SIG_DUTY)
    s_jd = _hit(t, SIG_JD)
    s_title = _is_bare_title(t)
    multi_line = len([ln for ln in t.splitlines() if ln.strip()]) >= 3
    e_opt = _hit(t, EXC_OPTIMIZE)
    e_act = _hit(t, EXC_ACTIVITY)
    e_term = _hit(t, EXC_TECH_TERM)
    detail = {"interview": s_interview, "resume": s_resume, "contact": s_contact,
              "duty": s_duty, "jd": s_jd, "title": s_title,
              "multi_line": multi_line, "exc_opt": e_opt, "exc_act": e_act,
              "exc_term": e_term}
    if s_interview:
        return True, "面试", detail
    if s_resume:
        return True, "简历", detail
    if s_jd and not e_term and not e_opt:
        return True, "JD解读", detail
    if s_duty and not e_opt and not e_act:
        return True, "岗位职责", detail
    if s_contact and (multi_line or s_resume):
        return True, "简历粘贴兜底", detail   # 联系方式∧多行版式（无简历词的粘贴）
    if s_title and not e_opt and not e_act:
        return True, "岗位名词残片", detail
    return False, "-", detail


def is_career_question(text: str) -> bool:
    """text → 是否职业向问（fail-open：任何异常= False，绝不抛出）。

    server [chat] career= 标注的唯一消费入口（命中=hit / 未命中=-）。"""
    try:
        return bool(detect_career(text)[0])
    except Exception:
        return False


def career_branch(text: str) -> str:
    """text → 命中支路名（未命中="-"；异常="-"）。观测明细面（零原文）。"""
    try:
        return detect_career(text)[1]
    except Exception:
        return "-"


def resolve_mode(config: dict) -> str:
    """config dict（server.CONFIG 形态）→ 开关二态清洗。

    缺键/非字符串/未知值 → DEFAULT_MODE（off）。枚举=on|off。"""
    try:
        v = str((config or {}).get(CONFIG_KEY) or "").strip().lower()
    except Exception:
        return DEFAULT_MODE
    return v if v in MODES else DEFAULT_MODE
