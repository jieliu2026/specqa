# -*- coding: utf-8 -*-
"""citation_clause_check —— 生成侧款号一致性检查（排序优化四期 P2 #1a，2026-10-03 立件）。

治理对象=S1 负控 5 FAIL（S1V-06/07/08/10 款族陷阱 + S1V-14 串号）的危害面——错款
数值串答（引文核验抓不住：引的确实是库里原文、只是款不对）。本件=纯程序检测面：
答案正文声明的款号/表号 vs 引用块 locator 的款号对齐校验，不判数值对错（数值对错
归判卷），不依赖模型打 [出处N] 标记（标记面≈自愿行为，见设计稿 §1.2 相邻发现）。

设计=运营/款号一致性检查-设计稿-20261003.md（冻结规格 §三）；
判据=建库/work/排序优化四期-20261003/判据-预登记-款号一致性-20261003.md（先定后测）。

冻结要点（与预登记 §一同源，改动须两档同步）：
  四正则族：附录N N.N.N( 款N)? / 第N条( 款N)?（中文↔阿拉伯归一）/ Table N.N.N-N
  （含库内字母段变体）/ 裸 N.N.N（≥2 点三段号，五护栏：前邻字母数字点、V+空格
  版本形、后邻单位符、首段4位日期形、与前族 span 重叠均不取）。
  两族分治：监管款号族（附录/条/裸号）只对监管族源校验；3GPP 表号族只对含表号源
  校验；互不跨配；声明所属族无同族源 → 该族放行；答案无声明 → 放行。
  容差=双向（用户 2026-10-03 决策①）：aligned=精确同款 ∨ 声明=源之父条 ∨
  声明=源条块之子款（依据=监管件条块正文物理含款文）；oob=同胞款不一致（同条
  不同款且源为子款块）/跨条/跨附录（表族=错表）。

恒不抛出；任何内部异常 → {"ok": True, ..., "err": <异常类名>}（放行，检测面静默
纪律同 citation_gate/rag）。纯标准库、纯函数，不挂生产（试点判据全过才谈上产）。
"""
import re

__all__ = ["check_claims"]

# ---------------------------------------------------------------------------
# 数字归一：中文数字（条/款双向，监管件面 ≤百）
# ---------------------------------------------------------------------------
_CN_DIGIT = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
             "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_NUM_CN = "0-9一二三四五六七八九十百零两"


def _cn2num(s):
    """中文数字/阿拉伯数字 → int；解析失败 → None（调用方跳过该声明）。"""
    s = str(s or "").strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    total, num = 0, 0
    for ch in s:
        if ch in _CN_DIGIT:
            num = _CN_DIGIT[ch]
        elif ch == "十":
            total += (num or 1) * 10
            num = 0
        elif ch == "百":
            total += (num or 1) * 100
            num = 0
        else:
            return None
    return total + num if total or num else None


# ---------------------------------------------------------------------------
# 声明提取（四正则族；边界条件：不取更长数字 token 的内嵌前缀/后缀片段）
# ---------------------------------------------------------------------------
_CLAUSE_NUM = r"\d{1,3}\.\d{1,3}\.\d{1,3}"

# 族1 附录族：附录N N.N.N( 款N)?
_RE_APP = re.compile(
    r"附录\s*(\d{1,2})[\s、，,]*(%s)(?:\s*款\s*([%s]{1,4}))?(?![0-9A-Za-z.])"
    % (_CLAUSE_NUM, _NUM_CN))

# 族2 条族：第N条( 款N)?（中文↔阿拉伯归一）
_RE_ART = re.compile(
    r"第\s*([%s]{1,6})\s*条(?:\s*款\s*([%s]{1,4}))?" % (_NUM_CN, _NUM_CN))

# 族3 表族：Table N(.N)+-N（库内实际形态：Table 4.1-1 / Table 5.2.1-1 /
# Table 5.3.2A.2-1 字母段变体）
_RE_TBL = re.compile(r"[Tt]able\s+([0-9]+(?:\.[0-9A-Za-z]+)+-\d{1,3})")

# 族4 裸号族：N.N.N（≥2 点=三段号），数字/字母/点邻接边界；款后缀同族1
_RE_BARE = re.compile(
    r"(?<![0-9A-Za-z.])(%s)(?:\s*款\s*([%s]{1,4}))?(?![0-9A-Za-z.])"
    % (_CLAUSE_NUM, _NUM_CN))

# 裸号护栏：后邻单位符（ASCII 单位词 + CJK 单位头字）
_UNIT_ASCII_RE = re.compile(r"\s*(?:ms|dBm|dB|MHz|GHz|Hz|Gbps|Mbps|kbit|Mbit|GB|MB|kB|s|%|％)")
_UNIT_CJK_HEAD = set("个毫微秒米赫兹度％%℃万千亿倍")

# 源侧解析（locator → 族化款号；同 s1_negctrl_eval.fam/_sub_of 先例的款尾缀口径）
_SRC_APP_RE = re.compile(r"^附录\s*(\d{1,2})\s+(%s)(?![0-9A-Za-z.])" % _CLAUSE_NUM)
_SRC_ART_RE = re.compile(r"^第\s*([%s]{1,6})\s*条(?:\s+款\s*([%s]{1,4}))?\s*$"
                         % (_NUM_CN, _NUM_CN))
_SRC_TAIL_KUAN_RE = re.compile(r"款\s*([%s]{1,4})\s*$" % _NUM_CN)


def _extract_claims(text):
    """answer_text → claims 列表 [{family,app,clause,art,kuan,tbl,raw,start,end}]。

    family ∈ {app, art, tbl, bare}；先族1-3（记录 span），裸号族再过五护栏净取。
    """
    claims, spans = [], []
    for m in _RE_APP.finditer(text):
        kuan = _cn2num(m.group(3)) if m.group(3) else None
        claims.append({"family": "app", "app": int(m.group(1)),
                       "clause": m.group(2), "kuan": kuan,
                       "raw": m.group(0), "start": m.start(), "end": m.end()})
        spans.append((m.start(), m.end()))
    for m in _RE_ART.finditer(text):
        art = _cn2num(m.group(1))
        if art is None:
            continue
        kuan = _cn2num(m.group(2)) if m.group(2) else None
        claims.append({"family": "art", "art": art, "kuan": kuan,
                       "raw": m.group(0), "start": m.start(), "end": m.end()})
        spans.append((m.start(), m.end()))
    for m in _RE_TBL.finditer(text):
        claims.append({"family": "tbl", "tbl": m.group(1),
                       "raw": m.group(0), "start": m.start(), "end": m.end()})
        spans.append((m.start(), m.end()))
    for m in _RE_BARE.finditer(text):
        s, e = m.start(), m.end()
        # 护栏5：与前族 span 重叠不取
        if any(s < se and e > ss for ss, se in spans):
            continue
        clause = m.group(1)
        # 护栏4：日期形（任一段 ≥4 位按日期/编号面弃；监管/3GPP 条号各段 ≤2 位常态）
        if any(len(seg) >= 4 for seg in clause.split(".")):
            continue
        # 护栏2：V+空格版本形（"V 15.2.0"）
        if re.search(r"[Vv]\s*$", text[:s]):
            continue
        # 护栏3：后邻单位符（"3.2.3ms"/"3.2.3 毫米" 形数值非条款）
        rest = text[e:e + 8]
        if _UNIT_ASCII_RE.match(rest) or (rest.lstrip()[:1] in _UNIT_CJK_HEAD):
            continue
        kuan = _cn2num(m.group(2)) if m.group(2) else None
        claims.append({"family": "bare", "app": None, "clause": clause,
                       "kuan": kuan, "raw": m.group(0),
                       "start": s, "end": e})
    return claims


def _parse_sources(sources):
    """sources（rag.build_evidence 产物 list[dict]，缺键容错）→ (reg_srcs, tbl_srcs)。

    reg_srcs=[("app",app,clause,kuan)|("art",art,kuan)]；tbl_srcs=[表号串]。
    locator 解析不出四族形态（摘要/主要目标/3GPP 纯条号"3.1 (p1)"）→ 无族不入。
    """
    reg, tbl = [], []
    for s in sources or []:
        if not isinstance(s, dict):
            continue
        loc = str(s.get("locator") or "").strip()
        if not loc:
            continue
        m = _SRC_APP_RE.match(loc)
        if m:
            km = _SRC_TAIL_KUAN_RE.search(loc)
            reg.append(("app", int(m.group(1)), m.group(2),
                        _cn2num(km.group(1)) if km else None))
            continue
        m = _SRC_ART_RE.match(loc)
        if m:
            art = _cn2num(m.group(1))
            if art is not None:
                reg.append(("art", art, None,
                            _cn2num(m.group(2)) if m.group(2) else None))
                continue
        m = _RE_TBL.search(loc)
        if m:
            tbl.append(m.group(1))
    return reg, tbl


def _check_reg_claim(claim, reg_srcs):
    """监管族声明联合对齐 → None（aligned）/ oob 原因串。"""
    is_art = claim["family"] == "art"
    same_head = same_kuan_conflict = any_head = False
    for src in reg_srcs:
        if src[0] == "art":
            if not is_art or src[1] != claim["art"]:
                continue  # 头不同（条号不等或跨族）不参与本源对齐
            same_head = True
            ck, sk = claim["kuan"], src[3]
            if ck is None or sk is None or ck == sk:
                return None  # 精确同款 ∨ 声明=父条 ∨ 声明=条块之子款
            same_kuan_conflict = True
        else:
            _kind, sapp, sclause, skuan = src
            capp = claim.get("app")
            if capp is None and claim.get("clause"):
                capp = int(claim["clause"].split(".")[0])  # 裸号：附录号由首段推定
            if is_art or sapp != capp:
                continue
            any_head = True
            if sclause != claim["clause"]:
                continue
            same_head = True
            ck, sk = claim["kuan"], skuan
            if ck is None or sk is None or ck == sk:
                return None
            same_kuan_conflict = True
    if same_kuan_conflict:
        return "同胞款不一致"
    if same_head:
        return "跨条"
    if is_art:
        return "跨条"
    if any_head:
        return "跨条"
    return "跨附录"


def _snippet(text, start, end, width=24):
    lo, hi = max(0, start - width), min(len(text), end + width)
    return "…" + text[lo:hi].replace("\n", " ") + "…"


def check_claims(answer_text, sources):
    """款号一致性检查主入口（纯函数恒不抛出）。

    answer_text=答案正文；sources=rag.build_evidence 的 sources 列表
    （[{locator,...}]，缺键容错）。返回：
      {"ok": bool,            # oob 空=True 放行
       "n_claims", "n_reg", "n_tbl",
       "claims": [{family,raw,norm}],
       "oob": [{"claim","family","reason","snippet"}],
       "err": None}
    """
    res = {"ok": True, "n_claims": 0, "n_reg": 0, "n_tbl": 0,
           "claims": [], "oob": [], "err": None}
    try:
        text = str(answer_text or "")
        reg_srcs, tbl_srcs = _parse_sources(sources)
        claims = _extract_claims(text)
        res["n_claims"] = len(claims)
        seen_oob = set()
        for c in claims:
            if c["family"] == "tbl":
                res["n_tbl"] += 1
                if not tbl_srcs:
                    continue  # 两族分治：无同族源 → 放行
                norm = "Table %s" % c["tbl"]
                res["claims"].append({"family": "tbl", "raw": c["raw"], "norm": norm})
                if norm not in {"Table %s" % t for t in tbl_srcs}:
                    key = ("tbl", norm)
                    if key not in seen_oob:
                        seen_oob.add(key)
                        res["oob"].append({"claim": c["raw"], "family": "tbl",
                                           "reason": "错表",
                                           "snippet": _snippet(text, c["start"], c["end"])})
                continue
            res["n_reg"] += 1
            if not reg_srcs:
                continue  # 两族分治：无同族源 → 放行
            reason = _check_reg_claim(c, reg_srcs)
            if c["family"] == "art":
                norm = "第%d条%s" % (c["art"], " 款%d" % c["kuan"] if c["kuan"] else "")
            elif c["family"] == "bare":
                norm = c["clause"] + (" 款%d" % c["kuan"] if c["kuan"] else "")
            else:
                norm = "附录%d %s%s" % (c["app"], c["clause"],
                                        " 款%d" % c["kuan"] if c["kuan"] else "")
            res["claims"].append({"family": c["family"], "raw": c["raw"], "norm": norm})
            if reason:
                key = (c["family"], norm, reason)
                if key not in seen_oob:
                    seen_oob.add(key)
                    res["oob"].append({"claim": c["raw"], "family": c["family"],
                                       "reason": reason,
                                       "snippet": _snippet(text, c["start"], c["end"])})
        res["ok"] = not res["oob"]
        return res
    except Exception as e:  # 检测面静默（恒不抛出，异常放行）
        res.update({"ok": True, "n_claims": 0, "n_reg": 0, "n_tbl": 0,
                    "claims": [], "oob": [], "err": type(e).__name__})
        return res
