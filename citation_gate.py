# -*- coding: utf-8 -*-
"""citation_gate —— A1 前置程序闸（引用契约的确定性核对，检测面，2026-10-01 立件）。

大模型维度提升·二期 Phase 2。依据=运营/调研-大模型最佳实践-20260930.md §二【抄①】：
引用做成可验证契约（逐字引文+块 ID 程序核对），"能用确定性 grader 就不用 LLM"。
Phase 1 实证（建库/logs/温度与纪律段对照-20260930.md Phase 1 终判）：纯提示词下
模型摘录 ≈44% 不逐字——本闸的作用=把这层失真变成程序可见的检测面。

口径（与 建库/scripts/引文核对器.py 同源——双件逐字锁死卷=tests/test_citation_gate.py
的锁定用例，任一侧改动必红）：
  ① 引用标记三形 [出处N]/[来源N]/[证据N] 编号须在 1..n_sources 内（越界=硬违规）。
     三形扩展=两源不同修复（2026-10-03，排序优化四期 #1a 相邻发现③）：build_evidence
     给模型的标签是 [出处N]（E1 trace _citation_alignment 亦认 [出处N]/[来源N]），
     原正则只认 [证据N] 属漏检。自带防误报判据：只影响"带标记答案"的检测面——
     此前 [出处N]/[来源N] 标记走"无引用面"放行，现按同规则判越界，纠正漏检
     非新增拒绝；无标记答案的放行语义不变；
  ② 「…」摘录须逐字命中证据文本（生产 evidence 为组装文本，6000 字截断面如实登记）；
     空白规整后命中=软违规；不命中=硬违规；
  ③ 无引用标记且无「」=无引用面（ok=True, n_cites=0，放行与否归上层策略）。

恒不抛出；任何内部异常 → {"ok": True, "err": "异常态"}（检测面静默纪律同 rag）。
"""
import re

_CITE_RE = re.compile(r"\[(出处|来源|证据)(\d+)\]")
_QUOTE_RE = re.compile(r"「([^「」]{2,400}?)」")


def _norm(s) -> str:
    return "".join(str(s).split())


def check_text(answer_text, evidence_text, n_sources=None):
    """检测面主入口：answer_text + 组装后证据文本（+可选 sources 数）。→ 指标 dict。"""
    try:
        ans = str(answer_text or "")
        ev = str(evidence_text or "")
        violations = []
        cites = [(int(m.group(2)), m.start(), m.group(0))
                 for m in _CITE_RE.finditer(ans)]
        n = int(n_sources) if n_sources else 0
        for num, _pos, raw in cites:
            if n and (num < 1 or num > n):
                violations.append({"type": "cite_out_of_range",
                                   "detail": "%s 越界（共 %d 块）" % (raw, n)})
        quotes = [(m.group(1), m.start()) for m in _QUOTE_RE.finditer(ans)]
        ev_norm = _norm(ev)
        for q, _pos in quotes:
            if q in ev:
                continue
            if _norm(q) in ev_norm:
                violations.append({"type": "quote_ws",
                                   "detail": "摘录空白规整后命中（软）：「%s…」" % q[:30]})
            else:
                violations.append({"type": "quote_not_found",
                                   "detail": "摘录未逐字命中证据：「%s…」" % q[:30]})
        hard = sum(1 for v in violations if v["type"] != "quote_ws")
        warn = len(violations) - hard
        return {"ok": hard == 0, "n_cites": len(cites), "n_quotes": len(quotes),
                "hard": hard, "warn": warn, "violations": violations}
    except Exception as e:  # 检测面静默（不拖垮请求路径）
        return {"ok": True, "n_cites": 0, "n_quotes": 0, "hard": 0, "warn": 0,
                "violations": [], "err": type(e).__name__}


def check_blocks(answer_text, blocks):
    """实验面入口（与 建库/scripts/引文核对器.check 同源锁死）：blocks=[{content},...]。"""
    contents = [str(b.get("content") or "") for b in (blocks or [])]
    joined = "\n\n".join(contents)
    res = check_text(answer_text, joined, len(contents))
    # 块模式下逐字命中允许命中"任一块"（与核对器一致）——joined 文本天然覆盖
    return res
