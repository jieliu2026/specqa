#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pii_mask——输入侧 PII 止血掩码模块（F线语料专项 C 线 C2，2026-10-14）。

施工依据：运营/F线语料专项-执行计划-20261014.md §一②（PII P0 输入侧止血）。
设计报告：运营/F线/C线-止血实现与测试-20261014.md。

定位与姿态（三条铁律）：
1. **不截断全文**：只对四类敏感字段（手机号/邮箱/身份证号/详细地址）做占位
   替换，任务摘要与上下文原样保留——掩码后文本仍可正常检索/答题/落库。
2. **日志模式先行**：config 顶层键 pii_mask_mode 三态——
   - "off"       零动作零日志（一键关）；
   - "log_only"  **默认值**。只打一行 [pii_mask] 命中观测行（只含计数，零原文），
                 不实际掩码——观察一周后是否启用掩码归决策，禁自动生效；
   - "mask"      实际掩码：clean 列表中 user 消息 content 的四类字段替换为
                 <手机号>/<邮箱>/<身份证号>/<详细地址> 占位（assistant 消息不动）。
   缺键/坏值一律回默认 log_only（清洗见 resolve_mode）。
3. **掩码原文绝不入日志**：[pii_mask] 行只有 trace= 与各类计数；掩码后的
   原文（即被替换前的敏感字段值）不落任何日志/输出。

简历类触发口径（§一②"仅匹配高度结构化简历特征"）：简历结构判定=
多行短句（≥RESUME_MIN_LINES 行且短行占比 ≥RESUME_SHORT_RATIO）
+ 联系方式共现（电话/邮箱形态命中 ≥1）——只影响 resume=0/1 观测标记，
不单独触发任何额外处理（四类字段掩码对任意文本同规则；职业向问句如
"网优工程师的工作内容有哪些"无联系方式/无简历结构，不会被标 resume=1，
更不会被拒答——职业向不建拒答模板是决策基线，本模块只做字段掩码）。

fail-open 纪律：本模块任何异常=放行原文、绝不拖垮 /api/chat 主链路
（apply_to_messages 内部兜底，绝不抛出）。

零依赖：纯标准库 re；零网络零 API 零计费。

版本：v1（2026-10-14 首版）；v1.1（2026-10-15 代码评审立改批 X2）：
- P1：ADDRESS_RE 行政区首段补直辖市分支 (?:北京|上海|天津|重庆)市——四大
  直辖市详细地址（"到门牌号级"口径不变）不再整族漏检；后段全可选形态未动
  （ReDoS 复测阴性：24k 最坏构造 detect <10ms，见评审档）。
- P2：PHONE_RE 支持 +86 前缀与空格/连字符分段（11 位整段含分隔符替换），
  尾断言 (?![\\d.]) 改 (?![\\d.]?\\d)——放行 ASCII 句点收尾（"…13812345678."
  可命中）同时保住浮点防护（"…13800138000.5" 仍不命中）；IDCARD_RE 支持
  空格/连字符分段 18 位（整段含分隔符替换，不分段各自掩）。
- P5：detect/mask_text/_log_hit/apply_to_messages 四处 except 静默路径加
  限频 [pii_mask] err=<异常类型> 遥测行（进程级一次/小时，零原文）。
v1.2（2026-10-15 消零收尾批 Y2）：
- P9：EMAIL_RE local-part 量化上界 [A-Za-z0-9._%+-]{1,64}——无 @ 的
  数字/点/加号长跑二次回溯根治（修复前 6k/12k/24k/48k=26/105/420/1676ms
  二次曲线，修复后同构造 0.7/1.5/2.9/5.8ms 线性，本机 best-of-3；占有
  量词 ++ 单用实测 305ms@24k 仍二次，不采——选形依据见 EMAIL_RE 行内注）。
  命中集面：常规邮箱（local-part ≤64）零变化；>64 字符 RFC 外形态改以
  末 64 字符后缀参与匹配（命中计数不缩、掩码起算点后移）。
规格源=work/代码评审-20261015/分级发现表.md（P1/P2/P5=主体表；P9/T04=
施工后补录节）与 深读-redline-piimask.md；正则改动同步扩
tests/test_pii_mask.py 用例（v1.2 批=邮箱对抗时限用例+身份证残段反例）。
参数迭代请改本文件头常量并在 运营/F线/C线-止血实现与测试-20261014.md
登记（版本化，禁无档改参；本批可写边界不含该档，外部档登记归协调侧）。
"""
import contextlib
import re
import time

# ---------- 开关三态 ----------
MODE_OFF = "off"
MODE_LOG_ONLY = "log_only"
MODE_MASK = "mask"
MODES = (MODE_OFF, MODE_LOG_ONLY, MODE_MASK)
DEFAULT_MODE = MODE_LOG_ONLY   # 日志模式先行（观察一周）；启用 mask 归决策
CONFIG_KEY = "pii_mask_mode"   # config.json 顶层键（文档位=本 docstring+设计报告）

# ---------- 四类敏感字段正则（v1.1 口径；变更登记见模块头注） ----------
# 手机号：大陆 11 位手机号（1[3-9] 段），支持 +86 前缀与段间单个空格/连字符
# （138 1234 5678 / 138-1234-5678 / +8613812345678 / +86-138-1234-5678）——
# 整段含分隔符替换。边界防误配（时间戳/进度/向量数字串，校准依据见设计报告
# 测试面）：左断言前非数字非点（保浮点 0.138… 防护）；尾断言 (?![\d.]?\d)
# 排更长数字串与 ".数字" 续接（13800138000.5 不配），但放行句点收尾
# （"call 13812345678." 可配——v1.1/P2）。
PHONE_RE = re.compile(
    r"(?<![\d.])(?:\+?86[\s-]?)?1[3-9]\d(?:[\s-]?\d{4}){2}(?![\d.]?\d)")
# 邮箱：常规 user@domain.tld 形态。v1.2/P9：local-part 量化上界 {1,64}
# （RFC 5321 上界 64 octets）——无 @ 的数字/点/加号长跑下，单起点尝试的
# 回溯深度由 O(n) 钳为 O(64)，二次回溯消除（修复前 6k/12k/24k/48k=
# 26/105/420/1676ms 标准二次曲线，修复后=0.7/1.5/2.9/5.8ms 线性，本机
# best-of-3；占有量词 ++ 单用实测 305ms@24k 仍二次——只消单点回溯消不掉
# 外层逐起点扫描，故不采）。上界副作用：>64 字符 local-part（RFC 外
# 形态）改以末 64 字符后缀参与匹配——命中计数不缩、掩码起算点后移；
# 常规邮箱（≤64）命中集零变化（既有 38 用例基线全绿复验）。
EMAIL_RE = re.compile(
    r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
# 身份证号：18 位（末位 X/x），内嵌年月段校验（19xx/20xx 年+合法月日），
# 边界排除更长数字串——纯随机 18 位数字无年月结构不匹配（假阳性防护）。
# v1.1/P2：区划/年/月/日后各允许单个空格或连字符分段（110105 1949 1231
# 002X、110105-1949-1231-002X 等）——整段含分隔符替换，不分段各自掩。
IDCARD_RE = re.compile(
    r"(?<![0-9Xx])\d{6}[\s-]?(?:19|20)\d{2}[\s-]?"
    r"(?:0[1-9]|1[0-2])[\s-]?(?:0[1-9]|[12]\d|3[01])[\s-]?"
    r"\d{3}[\dXx](?![0-9Xx])")
# 详细地址：行政区序列（省/市…区/县…乡镇街道可缺）+ 道路 + 门牌号
# （+可选楼栋/单元/室）——"详细"口径=必须到门牌号级；只出现"北京市"等
# 行政区名不匹配（不误伤"电信服务规范"-类规范文本）。
# v1.1/P1：行政区首段补直辖市分支——(省|自治区)+(市|盟|州) 或
# (北京|上海|天津|重庆)市 二选一（四大直辖市下辖区即接原可选区/县段，
# 后段全可选形态未动，ReDoS 复测阴性）。
ADDRESS_RE = re.compile(
    r"(?:[\u4e00-\u9fa5]{2,10}(?:省|自治区)"
    r"[\u4e00-\u9fa5]{2,12}(?:市|盟|州)"
    r"|(?:北京|上海|天津|重庆)市)"
    r"(?:[\u4e00-\u9fa5]{2,12}(?:区|县|旗))?"
    r"(?:[\u4e00-\u9fa5]{2,14}(?:区|县|镇|乡|街道|社区))?"
    r"[\u4e00-\u9fa5A-Za-z0-9]{2,20}(?:路|街|巷|大道|大街|道)"
    r"[\u4e00-\u9fa5A-Za-z0-9]{0,12}号"
    r"(?:[\u4e00-\u9fa5A-Za-z0-9]{0,12}(?:栋|幢|座|单元|室))*"
    r"(?:[\u4e00-\u9fa5A-Za-z0-9]{0,8}室)?")

# 占位符（无空白无引号——可安全进 [chat] q= 摘要与 KV 日志）
PLACEHOLDER = {"phone": "<手机号>", "email": "<邮箱>",
               "idcard": "<身份证号>", "address": "<详细地址>"}

# ---------- 简历结构判定常量（v1） ----------
RESUME_MIN_LINES = 4        # 非空行数下限（多行）
RESUME_LINE_SHORT_CHARS = 40  # "短句"判定：去空白后字符数上限
RESUME_SHORT_RATIO = 0.6    # 短行占比下限
RESUME_CONTACT_MIN = 1      # 联系方式（电话/邮箱形态）命中数下限
# 联系方式共现探测（宽口径：掩码标记形态也算——生产简历粘贴已被
# 云端认录管线掩成 <11位已掩码> 等形态，观察面须能识别这类已掩码简历）
_CONTACT_HINT_RE = re.compile(
    r"(?:电话|手机|联系方式|邮箱|e-?mail|<\d+位已掩码>|<姓名>|姓名)", re.I)

# ---------- fail-open 异常遥测（v1.1/P5） ----------
# except 静默路径的限频打点：[pii_mask] err=<异常类型>——只打类型名，
# 零原文零堆栈（掩码原文绝不入日志铁律同样约束遥测行）；进程级一次/小时
# （系统性异常=整窗放行时日志面至少留一行痕迹，与"零命中"可区分）。
_ERR_LAST = [0.0]


def _log_err(e, log=print):
    """fail-open 异常遥测行（限频一次/小时）；本函数自身任何异常静默——
    遥测绝不反噬 fail-open 主链路。"""
    now = time.monotonic()
    if now - _ERR_LAST[0] < 3600.0:
        return
    _ERR_LAST[0] = now
    with contextlib.suppress(Exception):
        log(f"[pii_mask] err={type(e).__name__}", flush=True)


def _nonspace_len(s: str) -> int:
    return len("".join(s.split()))


def detect(text: str) -> dict:
    """text → 检测结果（纯函数，绝不抛出）。

    返回 {"phone": n, "email": n, "idcard": n, "address": n, "total": n,
          "resume_like": bool}——只含计数与布尔，不含任何原文片段。"""
    try:
        t = str(text or "")
        counts = {
            "phone": len(PHONE_RE.findall(t)),
            "email": len(EMAIL_RE.findall(t)),
            "idcard": len(IDCARD_RE.findall(t)),
            "address": len(ADDRESS_RE.findall(t)),
        }
        counts["total"] = sum(counts.values())
        counts["resume_like"] = _resume_like(t, counts)
        return counts
    except Exception as e:
        _log_err(e)
        return {"phone": 0, "email": 0, "idcard": 0, "address": 0,
                "total": 0, "resume_like": False}


def _resume_like(t: str, counts: dict) -> bool:
    """高度结构化简历特征：多行短句 + 联系方式共现（v1 口径，见模块头注）。

    联系方式共现=联系方式关键词/掩码标记命中 或 本文本内电话/邮箱正则命中
    ≥RESUME_CONTACT_MIN。单行职业问句（"网优工程师的工作内容有哪些"）无
    多行结构，恒 False——简历类标记不误挂职业向知识问。"""
    lines = [ln for ln in t.splitlines() if ln.strip()]
    if len(lines) < RESUME_MIN_LINES:
        return False
    short = sum(1 for ln in lines if _nonspace_len(ln) <= RESUME_LINE_SHORT_CHARS)
    if short / len(lines) < RESUME_SHORT_RATIO:
        return False
    contact = counts.get("phone", 0) + counts.get("email", 0)
    if contact + len(_CONTACT_HINT_RE.findall(t)) >= RESUME_CONTACT_MIN:
        return True
    return False


def mask_text(text: str) -> tuple:
    """text → (掩码后文本, 计数 dict)。只替换四类字段，其余原样（不截断）。

    替换序=身份证→手机号→邮箱→地址（身份证在前防 18 位串被手机号子段截配）。
    纯函数；任何异常回 (原文本, 零计数)（fail-open）。"""
    try:
        t = str(text or "")
        counts = {}
        for key, pattern in (("idcard", IDCARD_RE), ("phone", PHONE_RE),
                             ("email", EMAIL_RE), ("address", ADDRESS_RE)):
            t, counts[key] = pattern.subn(PLACEHOLDER[key], t)
        counts["total"] = sum(counts.values())
        return t, counts
    except Exception as e:
        _log_err(e)
        return text, {"phone": 0, "email": 0, "idcard": 0, "address": 0,
                      "total": 0}


def resolve_mode(config: dict) -> str:
    """config dict（server.CONFIG 形态）→ 模式三态清洗。

    缺键/非字符串/未知值 → DEFAULT_MODE（log_only）。枚举见 MODES。"""
    try:
        v = str((config or {}).get(CONFIG_KEY) or "").strip().lower()
    except Exception:
        return DEFAULT_MODE
    return v if v in MODES else DEFAULT_MODE


def _log_hit(mode: str, counts: dict, trace_id: str, log=print) -> None:
    """[pii_mask] 命中观测行（零原文零掩码后原文——只有计数与标记）。

    格式：[pii_mask] mode=log_only|mask trace=xxxxxxxx phone=N email=N
    idcard=N addr=N resume=0|1 len=N。total=0 不打行（零噪音）；
    off 态不打行。len=原始输入字符数（观测面，不含内容）。"""
    try:
        if counts.get("total"):
            log(f"[pii_mask] mode={mode} trace={trace_id or '-'} "
                f"phone={counts.get('phone', 0)} email={counts.get('email', 0)} "
                f"idcard={counts.get('idcard', 0)} addr={counts.get('address', 0)} "
                f"resume={1 if counts.get('resume_like') else 0} "
                f"len={counts.get('len', 0)}", flush=True)
    except Exception as e:
        _log_err(e, log)


def apply_to_messages(clean: list, mode: str, trace_id: str = "", log=print) -> list:
    """/api/chat 清洗段产物 clean（[{role, content}, ...]）→ 处理后消息列表。

    - off：原样返回（同对象引用，零拷贝零日志）；
    - log_only：对全部 user 消息做 detect 聚合（跨消息合并计数与 resume 标记），
      total>0 时打一行 [pii_mask]（零原文），消息原样返回（同对象引用）；
    - mask：逐条 user 消息 mask_text（assistant 消息不动——assistant 内容是
      本机生成物，无用户 PII 注入面），打一行 [pii_mask] mode=mask；
      返回**新列表**（新 dict，不就地改 clean——调用侧 clean 旧引用不漂移）。
    任何异常：返回原 clean（fail-open，绝不抛出）。"""
    try:
        if mode not in MODES:
            mode = DEFAULT_MODE
        if mode == MODE_OFF:
            return clean
        user_texts = [m.get("content") for m in (clean or [])
                      if isinstance(m, dict) and m.get("role") == "user"
                      and isinstance(m.get("content"), str)]
        if not user_texts:
            return clean
        joined = "\n".join(user_texts)
        total_len = len(joined)
        if mode == MODE_LOG_ONLY:
            counts = detect(joined)
            counts["len"] = total_len
            _log_hit(mode, counts, trace_id, log)
            return clean
        # mode == MODE_MASK
        agg = {"phone": 0, "email": 0, "idcard": 0, "address": 0}
        resume_any = False
        out = []
        for m in clean:
            if not (isinstance(m, dict) and m.get("role") == "user"
                    and isinstance(m.get("content"), str)):
                out.append(m)
                continue
            masked, c = mask_text(m["content"])
            det = detect(m["content"])
            resume_any = resume_any or det.get("resume_like", False)
            for k in agg:
                agg[k] += c.get(k, 0)
            out.append({"role": m["role"], "content": masked})
        agg["total"] = sum(agg.values())
        agg["resume_like"] = resume_any
        agg["len"] = total_len
        _log_hit(mode, agg, trace_id, log)
        return out
    except Exception as e:
        _log_err(e, log)
        return clean
