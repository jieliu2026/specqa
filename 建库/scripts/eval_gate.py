#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eval_gate.py —— 回归门禁：单一评测入口+硬指标阻断（2026-09-28 评测体系第 2 批 D1）

定位
----
换库/改代码后须跑"四卷硬线"复验，此前靠纪律人工执行（运营/云端执行单-阶段二
换库-20260926 §三：逐卷手跑 smoke_accept＋人读四线）。本件=机制化：一个命令跑
全套，硬指标不过=exit 1 阻断（BLOCK），软指标只记录不阻断。

设计纪律（硬性）
----------------
1. 只增不改：不碰任何现有文件，全部现有工具（smoke_accept.py / s1_negctrl_eval.py）
   一律以子进程方式调用（venv python 直调），判定数据从各工具的 --json 机读产物
   解析（smoke_accept.json/v1 / s1_negctrl 自有 schema），不做任何 import 级耦合。
2. 零 API 默认：本件自身零 API（不 import 嵌入/检索模块、不读密钥、零网络）；
   默认链路（四卷+负控线）零 LLM API——唯一计费面=smoke_accept --yes 的查询嵌入
   （四卷 ≈50 题 ≈0.0005 元级，与执行单四卷复验同款既有口径；红线由 smoke_accept
   内嵌红线闸自管）。--with-answers 才引入 judge LLM API（显式选入）。
   --dry-run 全链零调用预览（子进程带 dry-run 标志=不给 --yes）。
3. 硬线配置区=文件头常量（HARD_LINES），--config <JSON> 可覆盖（分节合并，键白名单
   校验，非法即退 2——禁拼写错静默改线）。
4. 库 md5 透传：四卷各跑的 smoke_accept json lib.md5（流式算）原样透传入本件报告，
   门禁判定与库身份绑定留痕。

四卷硬线口径（档内线：运营/S1负控治理方案-20260928.md §四.4／云端执行单-阶段二
换库-20260926 §三——口径=top-5 相关率，即 smoke_accept 汇总的 top5_n）：
  A ≥88.9%（16/18）｜ B =12/12 ｜ C =12/12（C09 豁免在档 11/12：失题恰=C09 按
  豁免判过，其余失题不过线）｜ Y ≥6/8（8 题制）。

S1 负控线（--with-negctrl；子进程=s1_negctrl_eval.py 三开关全开=甲乙丙组合）：
  负控 ≥8/14 + 正控 4/4 + 域内误伤 0（域内误伤=S1 锚定题覆盖闸误触发 misfire +
  四卷面 A/B/Y 安全词形触发数；2026-10-08 卷重编口径：S1V-10 退役＋S1V-17..20
  改靶，负控面 15→14、线=用户决策 Q1 主推 ≥8/14；旧 ≥7/15=A1b 时代三层组合
  上限在档口径，沿革见 HARD_LINES 注）。
  正控 4/4=2026-10-06 口径（用户决策，S1 卷维护批）：S1V-05 退役（锚族随勘误
  手术移除、全库 0 块；证据=运营/扩容-V7前-成员级诊断与机制仿真-20261006.md
  §2.2），正控件 5→4、线 5/5→4/4（生产值=门禁线-生产.json pos_min=4）。

答案卷线（--with-answers；子进程=smoke_accept --answers 答案卷-1.0.json）：
  faithfulness_rate 硬线键**预留**（HARD_LINES["answers"]["faithfulness_rate_min"]
  默认 None）——**judge 未校准转正前只记录不阻断**（G3 校准复核表
  运营/G3judge校准复核表-20260928.md 待用户填后转正，届时经 --config 定线启用）。

软指标（只进报告不阻断）：MRR@10 / nDCG@10 / hard_neg_hit_rate / 各卷工具自身
通过线（smoke_accept 自带四线/六线）——门禁只按本件硬线清单判。

口径注记（2026-10-03 施工，依据=运营/门禁口径偏差复核-BM25段-20261003.md 建议①）
------------------------------------------------------------------------------
门禁证书 channel=cosine 系纯余弦独立仪器视图：smoke_accept 评测器对向量文件自算
余弦，不读 rag 配置、不实例化 RagService，不代表产线管线形态（产线拨键后"门禁绿"
不能推论"产线绿"）。故报告层恒带注记——stdout 判定段后一行 + 机读 json 新增
caliber_note 键（channel/score_caliber 读自各卷 smoke 证书头既有键，smoke_accept
侧不加新键防 schema 漂移）。additive only：判定逻辑与既有键零变化。

指标面板 + bootstrap CI（2026-10-07 施工，Wave D 评测收敛批 D1+D2）
------------------------------------------------------------------------------
D1 指标一页化：报告恒带"指标面板"汇总段（stdout 末节 + 机读 panel 键）——四指标
一页呈现，全部为**既有结果的纯重排**（零新增 API/零新增子进程；判定面零变化，
面板不参与 BLOCK）：
  ① faithfulness：答案卷 judge faithfulness 维 pass 率（题行向量重算 + 与卷级
     faithfulness_rate 交叉核对，不一致记警示）；
  ② 拒答准确率：对拒=abstain 题 abstention 维 pass 率（答案卷 8 题；abstain 行
     识别口径=answer_judge.dims.abstention ≠ na——工具侧 normal 题该维恒 na）；
     误拒=normal 题答案文本拒答词形启发式扫描（保守口径，零 API）；对抗卷
     （题卷/对抗卷-1.0.json，210 题/30 abstain）不在本门禁执行链（其读数载体=
     R3I 同构仪器，见门禁线-生产.json adversarial 段）→ 面板留位注明；
  ③ 检索召回/精度：召回=四卷 top-5 相关率（题卷命中块对期望锚=四卷硬线同源
     读数；线=生效硬线，生产经 --config 门禁线-生产.json 即同口径）；精度信号=
     expect_miss 意外命中/越域命中/负锚命中率（越低越好，只记录）；
  ④ 答案相关性=答案卷判官综合过题率（answer_pass/answer_judged，代理口径）；
     --with-answers 未开/judge 降级 → 标"待判卷授权"（compare 通道系检索对照
     非答案相关性，不取）。
dry-run 模式面板照出：全占位标注"dry-run 占位（不判定）"。
D2 bootstrap 置信区间：卷级读数 95% CI（百分位法，标准库 random.Random，缺省
2000 次重采样，seed=20261007 固定 → 同数据同 CI，面板可独立重生成）；n<10 记
small_n=true 并标"区间宽仅供参考"。进 panel.ci 键（faithfulness_rate/对拒率/
误拒率/拒答综合准确率/四卷 top5_rate/答案过题率）。独立重生成入口=
build_panel_from_run_dir(run_dir)：从 eval_gate-runs 留痕工具产物重解析重建。

用法
----
  python3 eval_gate.py --dry-run          # 全链零调用预览（子进程 dry-run 形态）
  python3 eval_gate.py                    # 真跑四卷（嵌入 ≈0.0005 元级；BLOCK=exit 1）
  python3 eval_gate.py --json             # 另落机读报告 建库/logs/eval_gate-<日期>.json
  python3 eval_gate.py --with-negctrl     # 加 S1 负控线（零 API 只读件）
  python3 eval_gate.py --with-answers     # 加答案卷（judge LLM API，显式选入；只记录）
  python3 eval_gate.py --config 门禁线.json   # 覆盖硬线（分节合并）
  python3 eval_gate.py --timeout 7200     # 单子进程墙钟预算（默认 3600s）
  QA_BOT_ROOT=/opt/qa-bot python3 eval_gate.py --dry-run   # 云端 ECS 跑法
                                             #（或 --root /opt/qa-bot 同效）

退出码：0=硬线全过（dry-run 不判定退 0）；1=BLOCK（硬线未过）；2=前置/工具失败
（venv/工具/题卷缺失、--config 非法、子进程 rc=2、机读 JSON 缺失或畸形）。

备注：子进程 python=ROOT 解析的 venv python（QA_BOT_PYTHON > ROOT/venv/bin/
python > sys.executable；本机缺省 <repo>/venv/bin/python，云端缺省
当前解释器）；ROOT 优先级=QA_BOT_ROOT > --root > 自动探测（含 venv/建库 的最近
祖先）。嵌入通道网络形态按执行环境自理（本机历史先例=run_ipv4 包装，见执行单；
门禁不改该面）。
"""
import argparse
import json
import os
import random
import subprocess
import sys
import time

# ---------------------------------------------------------------------------
# 路径与工具（只读引用，绝不写这些位置以外的现有文件）
# ---------------------------------------------------------------------------
# ROOT 参数化（2026-09-28 云端部署遗留债清偿）：原硬编码 <repo> 在
# 云端 ECS（/opt/qa-bot）必退 2。三通道解析，优先级（任务决策）：
#   ① 环境变量 QA_BOT_ROOT；② CLI --root；③ 自动探测=脚本位置逐级向上找含
#   venv/建库 的最近祖先（本机得 <repo>，云端 /opt/qa-bot 同构可探）。
# venv python 同步参数化：① QA_BOT_PYTHON；② ROOT/venv/bin/python（存在才用，
# 云端无本机 venv 位）；③ sys.executable。缺省通道本机结果=原硬编码值（零变化纪律）。
ROOT_ENV = "QA_BOT_ROOT"
PYTHON_ENV = "QA_BOT_PYTHON"
_ROOT_MARKERS = ("venv", "建库")          # 根目录标志（祖先含其一即认根）
_ROOT_FALLBACK = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))    # 探测失败回退=原硬编码值（参数化前口径）


def _detect_root(start_dir=None):
    """自动探测：start_dir（缺省=本文件目录）向上找含 venv/建库 的祖先 → root。

    探到 / 仍无标志则回退 _ROOT_FALLBACK（=原硬编码值，探测失败不劣于改前）。
    """
    d = os.path.abspath(start_dir or os.path.dirname(__file__))
    while True:
        if any(os.path.isdir(os.path.join(d, m)) for m in _ROOT_MARKERS):
            return d
        nxt = os.path.dirname(d)
        if nxt == d:
            return _ROOT_FALLBACK
        d = nxt


def resolve_root(cli_root=None, env=None, start_dir=None):
    """ROOT 解析 → (root, 来源)。优先级：QA_BOT_ROOT > --root > 自动探测。"""
    env = os.environ if env is None else env
    v = (env.get(ROOT_ENV) or "").strip()
    if v:
        return os.path.abspath(v), ROOT_ENV
    if cli_root:
        return os.path.abspath(cli_root), "--root"
    return _detect_root(start_dir), "auto"


def resolve_venv_python(root, env=None):
    """venv python 解析：QA_BOT_PYTHON > ROOT/venv/bin/python（存在才用）>
    sys.executable（云端无本机 venv 位，落空即用当前解释器）。"""
    env = os.environ if env is None else env
    v = (env.get(PYTHON_ENV) or "").strip()
    if v:
        return os.path.abspath(v)
    cand = os.path.join(root, "venv", "bin", "python")
    return cand if os.path.exists(cand) else sys.executable


def _apply_root(root, env=None):
    """按 root 重算本件路径常量（import 期与 main() --root/QA_BOT_ROOT 通道共用）。"""
    global ROOT, SCRIPTS_DIR, LOGS_DIR, RUNS_DIR, VENV_PYTHON
    ROOT = root
    SCRIPTS_DIR = os.path.join(root, "建库", "scripts")
    LOGS_DIR = os.path.join(root, "建库", "logs")
    RUNS_DIR = os.path.join(LOGS_DIR, "eval_gate-runs")   # 每跑一门的工具机读产物留痕
    VENV_PYTHON = resolve_venv_python(root, env)


ROOT, ROOT_SOURCE = resolve_root()      # import 期缺省解析（本机=原硬编码值）
_apply_root(ROOT)
SMOKE_TOOL = "smoke_accept.py"                        # 四卷/答案卷评测工具
S1_TOOL = "s1_negctrl_eval.py"                        # S1 负控线工具（零 API 只读）

# 四卷定义（A=smoke_accept 内置卷免文件；B/C/Y=外部题卷；ANS=答案卷选入）。
# 值=相对 建库/scripts 的路径（存在性核查用）；子进程实给绝对路径——smoke_accept
# 的 --questions-file 经 pipeline_config.resolve_path 锚 BASE_DIR（=建库/）而非
# cwd，相对形会错拼 建库/题卷/…（2026-09-28 dry-run 实测踩坑），绝对路径无歧义。
PAPER_FILES = {
    "B": "题卷/独立B.json",
    "C": "题卷/独立C实操.json",
    "Y": "题卷/独立Y意译.json",
    "ANS": "题卷/答案卷-1.1.json",
}
FOUR_VOLUME_KEYS = ("A", "B", "C", "Y")
ANSWER_KEY = "ANS"

# S1 负控线三开关（档内口径=甲乙丙全开组合；s1_negctrl_eval.py CLI）
S1_SWITCHES = ("--with-judge-exempt", "--with-rerank", "--with-cover-gate")

# ---------------------------------------------------------------------------
# 硬线配置区（文件头常量；--config 可分节覆盖）
# ---------------------------------------------------------------------------
# volumes 各键：min_top5=top-5 相关率过题数下限（四卷硬线口径=top5_n）；n=档内
# 题数（仅作一致性警示，不参与判定）；exempt_ids=豁免在档失题清单（失题集合 ⊆
# 该清单且 top5_n ≥ min_top5-len(exempt_ids) 时按"豁免过"判——C09 口径：云端执行
# 单-阶段二换库 §三"失题恰=C09 按豁免判过，其余失题不过线"）。
HARD_LINES = {
    "volumes": {
        "A": {"min_top5": 16, "n": 18, "exempt_ids": []},
        "B": {"min_top5": 12, "n": 12, "exempt_ids": []},
        "C": {"min_top5": 12, "n": 12, "exempt_ids": ["C09"]},
        "Y": {"min_top5": 6, "n": 8, "exempt_ids": []},
    },
    # S1 负控线（--with-negctrl 才判）：负控 ≥8/14（2026-10-08 用户决策 Q1=主推线：
    # 幸存×60% 公式，14×60%=8.4 取整；卷重编=S1V-10 退役+S1V-17..20 改靶，负控面
    # 15→14 含改靶正控 4 题；材料=建库/work/S1负控重审-20261008/重审报告.md §五）+正控
    # 4/4+域内误伤 0（misfire_max 管 S1 锚定题误触发与四卷 A/B/Y 安全词形触发之和）。
    # 口径沿革：正控 5/5→4/4（2026-10-06 用户决策，S1 卷维护批）：S1V-05 退役（供给面证伪，
    # 证据=运营/扩容-V7前-成员级诊断与机制仿真-20261006.md §2.2）；负控 ≥7/15→≥8/14
    # （2026-10-08，Q2=批一并执行）——与 门禁线-生产.json negctrl（neg_min=8/n=14）
    # 同批同步，缺省值须与生产 config 一致。
    "negctrl": {"neg_min": 8, "pos_min": 4, "misfire_max": 0},
    # 答案卷线：faithfulness_rate_min=None=只记录不阻断——judge 未校准转正前不
    # 阻断（G3 复核表在档待用户；转正后经 --config 定数值线启用）
    "answers": {"faithfulness_rate_min": None},
}

# 软指标键（只进报告不阻断；来源=smoke_accept papers[].metrics）
SOFT_KEYS = ("mrr_at_10", "ndcg_at_10", "hard_neg_hit_rate")

# 机读 schema 标记
GATE_SCHEMA = "eval_gate.json/v1"
SMOKE_SCHEMA = "smoke_accept.json/v1"

# 门禁口径注记（2026-10-03 复核件建议①施工）：门禁读数=纯余弦独立仪器视图
# （smoke_accept 对向量文件自算余弦，不读 rag 配置/不实例化 RagService），不代表
# 产线管线形态；channel/score_caliber 引用各卷 smoke 证书头既有键（不加新键）。
CALIBER_NOTE_DOC = "运营/门禁口径偏差复核-BM25段-20261003.md"


def build_caliber_note(channels=None):
    """口径注记行文本（报告层恒带；纯函数，单测面）。

    channels=真跑各卷 smoke 证书头 channel 观察集：缺省/纯 cosine=标准表述；
    含非 cosine 通道时如实并列并改述（防未来双视图通道——复核件建议②面——
    落地后注记失真）。
    """
    seen = sorted({str(c) for c in (channels or []) if c}) or ["cosine"]
    if seen == ["cosine"]:
        view = "channel=cosine 系纯余弦独立仪器视图"
    else:
        view = ("channel=%s 系独立仪器视图（含非余弦通道，非纯余弦读数）"
                % "+".join(seen))
    return "口径注记：%s，不读 rag 配置、不代表产线管线形态；卷线 view=pipeline 绑定卷按管线视图（--pipeline-view 证书面）判（依据=%s）" % (
        view, CALIBER_NOTE_DOC)

# 指标面板常量（D1+D2，2026-10-07 Wave D 评测收敛批）
PANEL_SCHEMA = "eval_gate.panel/v1"       # 面板机读 schema 标记
PANEL_BOOTSTRAP_N = 2000                  # D2 重采样次数（任务线 ≥2000）
PANEL_BOOTSTRAP_LEVEL = 0.95              # CI 置信水平
PANEL_BOOTSTRAP_SEED = 20261007           # 固定种子 → 同数据同 CI（可独立重生成）
PANEL_SMALL_N = 10                        # n<该值 → small_n 标注"区间宽仅供参考"
PANEL_DOC = "运营/测试体系-20261007/草案/D1D2-施工报告-20261007.md"
# 误拒词形启发式标记（保守口径：正常题答案文本命中即计"误拒"候选；零 API 纯扫描）
REFUSAL_MARKERS = ("拒答", "无法作答", "无法回答", "无法支撑", "超出本知识库",
                   "超出本库", "不在现行库", "不在本库")

# 单子进程墙钟预算默认值（秒）：四卷各跑含 660MB 级库装载+嵌入，留足余量
DEFAULT_TIMEOUT_S = 3600


class GateConfigError(ValueError):
    """--config / 硬线配置非法（前置失败，退出码 2）。"""


class GateDataError(ValueError):
    """子进程机读 JSON 缺失/畸形/形状不符（前置失败，退出码 2）。"""


# ---------------------------------------------------------------------------
# 硬线覆盖（--config）
# ---------------------------------------------------------------------------
_VOL_LINE_KEYS = ("min_top5", "n", "exempt_ids", "view")
# negctrl 的 "n"=负控面题数基数（2026-10-08 卷重编批随 门禁线-生产.json 引入：
# 14=幸存 10＋改靶 4；仅作登记不参与判定——语义同 volumes 各卷的 n 键，防
# neg_min=8 脱离基数被误读为旧 /15 口径）
_NEG_LINE_KEYS = ("neg_min", "pos_min", "misfire_max", "n")
_ANS_LINE_KEYS = ("faithfulness_rate_min",)


def _validate_int(v, where, minimum=0):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or int(v) != v:
        raise GateConfigError("%s 须为整数，得 %r" % (where, v))
    iv = int(v)
    if iv < minimum:
        raise GateConfigError("%s 须 ≥%d，得 %d" % (where, minimum, iv))
    return iv


def _merge_volume_line(base, override, where):
    out = dict(base)
    for k, v in override.items():
        if k not in _VOL_LINE_KEYS:
            raise GateConfigError("%s 未知键 %r（合法：%s）" % (
                where, k, "、".join(_VOL_LINE_KEYS)))
        if k == "exempt_ids":
            if not isinstance(v, list) or not all(isinstance(x, str) and x.strip()
                                                  for x in v):
                raise GateConfigError("%s exempt_ids 须为字符串数组" % where)
            out[k] = [str(x) for x in v]
        elif k == "view":   # 双视图绑定（2026-10-08 C 线收口批）：缺省 cosine=现状
            if v not in ("cosine", "pipeline"):
                raise GateConfigError('%s view 须为 "cosine"|"pipeline"，得 %r'
                                      % (where, v))
            out[k] = v
        elif k == "n":
            out[k] = _validate_int(v, "%s n" % where)
        else:  # min_top5
            out[k] = _validate_int(v, "%s min_top5" % where)
    return out


def merge_lines(config_path=None):
    """文件头常量 + --config 覆盖 → 生效硬线（深拷贝；非法即 GateConfigError）。"""
    lines = {"volumes": {k: dict(v) for k, v in HARD_LINES["volumes"].items()},
             "negctrl": dict(HARD_LINES["negctrl"]),
             "answers": dict(HARD_LINES["answers"])}
    source = "builtin（文件头常量）"
    if not config_path:
        return lines, source
    try:
        with open(config_path, encoding="utf-8") as f:
            override = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise GateConfigError("--config 读取/解析失败（%s）：%s" % (config_path, e))
    if not isinstance(override, dict):
        raise GateConfigError("--config 顶层须为对象（volumes/negctrl/answers 分节）")
    vols = override.get("volumes") or {}
    if not isinstance(vols, dict):
        raise GateConfigError("--config volumes 须为对象")
    for key, ov in vols.items():
        if key not in lines["volumes"]:
            raise GateConfigError("--config volumes 未知卷 %r（合法：%s）" % (
                key, "、".join(lines["volumes"])))
        if not isinstance(ov, dict):
            raise GateConfigError("--config volumes.%s 须为对象" % key)
        lines["volumes"][key] = _merge_volume_line(
            lines["volumes"][key], ov, "--config volumes.%s" % key)
    for sec, allowed in (("negctrl", _NEG_LINE_KEYS), ("answers", _ANS_LINE_KEYS)):
        ov = override.get(sec) or {}
        if not isinstance(ov, dict):
            raise GateConfigError("--config %s 须为对象" % sec)
        for k, v in ov.items():
            if k not in allowed:
                raise GateConfigError("--config %s 未知键 %r（合法：%s）" % (
                    sec, k, "、".join(allowed)))
            if sec == "answers" and v is None:
                lines[sec][k] = None       # 显式 null=回到只记录（豁免启用后的回退位）
                continue
            if k == "faithfulness_rate_min":
                if isinstance(v, bool) or not isinstance(v, (int, float)) \
                        or not 0.0 <= float(v) <= 1.0:
                    raise GateConfigError(
                        "--config answers.faithfulness_rate_min 须为 [0,1] 数值或 null")
                lines[sec][k] = float(v)
            else:
                lines[sec][k] = _validate_int(v, "--config %s.%s" % (sec, k))
    return lines, "config:%s" % os.path.abspath(config_path)


# ---------------------------------------------------------------------------
# 子进程命令构造与执行
# ---------------------------------------------------------------------------
def build_smoke_cmd(vol_key, json_path, real, with_answers=False,
                    pipeline_on=False):
    """smoke_accept 子进程命令（cwd=建库/scripts，题卷相对路径同执行单口径）。

    real=True 给 --yes（真跑：嵌入计费、判定、写 --json）；real=False=dry-run 形态
    （smoke_accept 自身 dry-run=零网络零计费不写 json）。with_answers 仅答案卷用：
    --answers 通道在 smoke_accept 侧亦受 --yes 计费闸约束（dry-run 形态零调用）。
    pipeline_on（2026-10-08 C 线收口批）：生效线含卷绑 pipeline 视图时给
    --pipeline-view（smoke 侧双视图证书；cosine 面零变化、管线面零新增 API）。
    """
    cmd = [VENV_PYTHON, SMOKE_TOOL]
    if vol_key != "A":
        cmd += ["--questions-file", os.path.join(SCRIPTS_DIR,
                                                 PAPER_FILES[vol_key])]
    if with_answers:
        cmd += ["--answers"]
    if pipeline_on:
        cmd += ["--pipeline-view"]
    if real:
        cmd += ["--yes"]
    cmd += ["--json", json_path]
    return cmd


def build_s1_cmd(json_path):
    """s1_negctrl 子进程命令（三开关全开=甲乙丙组合；零 API 只读件，无 dry-run 位）。"""
    return [VENV_PYTHON, S1_TOOL] + list(S1_SWITCHES) + ["--json", json_path]


def run_tool(cmd, timeout_s, say=print):
    """执行子进程（stdout/stderr 直通控制台=沿工具既有回显），→ (rc, 耗时秒)。

    rc=None 表示超时（按前置失败处理）。超时/负 rc（信号崩溃）不在此抛错，由调用
    方统一按工具失败（退出码 2）收口。
    """
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, cwd=SCRIPTS_DIR, timeout=max(1, int(timeout_s)))
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        rc = None
    dur = time.time() - t0
    say("[gate] rc=%s 耗时 %.1fs：%s" % (rc if rc is not None else "超时", dur,
                                        " ".join(cmd)))
    return rc, dur


# ---------------------------------------------------------------------------
# 子进程机读产物解析
# ---------------------------------------------------------------------------
def parse_smoke_result(path, expect_paper=None):
    """smoke_accept --json 产物 → 归一 dict（判定用）。

    结构依赖（smoke_accept.json/v1）：papers 恰 1 卷（四卷各跑=单卷）、metrics.top5_n
    /n、questions[].qid/judge_type/hit_rank、lib.md5、usage、channel/score_caliber
    （证书头既有键→口径注记引用面，缺失不拒收）。schema 不符记警示不拒收
    （向后兼容面：新增键不断门禁）。
    """
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise GateDataError("smoke 机读 JSON 读取失败（%s）：%s" % (path, e))
    if not isinstance(data, dict) or not isinstance(data.get("papers"), list) \
            or len(data["papers"]) != 1:
        raise GateDataError("smoke 机读 JSON 形状不符（papers 须恰 1 卷）：%s" % path)
    p = data["papers"][0]
    m = p.get("metrics") or {}
    for k in ("n", "top5_n"):
        if not isinstance(m.get(k), int):
            raise GateDataError("smoke 机读 JSON metrics.%s 缺失/非整数（%s）" % (k, path))
    if expect_paper is not None and p.get("paper_id") != expect_paper:
        raise GateDataError("卷 id 不符：期望 %r 得 %r（%s）" % (
            expect_paper, p.get("paper_id"), path))
    return {
        "schema": data.get("schema"),
        "paper_id": p.get("paper_id"),
        "title": p.get("title", ""),
        "n": m["n"], "top5_n": m["top5_n"],
        "top5_rate": m.get("top5_rate"),
        "all_pass": p.get("all_pass"),
        "pass_lines": p.get("pass_lines"),
        "soft": {k: m.get(k) for k in SOFT_KEYS},
        "metrics_extra": {k: v for k, v in m.items()
                          if k in ("n_rel", "monitor_hits", "monitor_n", "param_hits",
                                   "param_n", "cross_total", "miss_rate", "domain_rate",
                                   "unexpected_hits", "answer_judged", "answer_null",
                                   "answer_pass", "faithfulness_rate")},
        # 双视图（2026-10-08 C 线收口批）：管线面指标缺省 None=证书未开
        # --pipeline-view（卷线绑 pipeline 视图时 judge_volume 显式报错）
        "pipeline": {"top5_n": m.get("top5_n_pipeline"),
                     "n_rel": m.get("n_rel_pipeline"),
                     "top5_rate": m.get("top5_rate_pipeline")},
        "lib": data.get("lib") or {},
        "channel": data.get("channel"),
        "score_caliber": data.get("score_caliber"),
        "usage": data.get("usage") or {},
        "questions": data.get("questions") or [],
    }


# ---------------------------------------------------------------------------
# 硬线判定（纯函数，单测面）
# ---------------------------------------------------------------------------
def row_top5_ok(row):
    """题行 top5_ok 推导：hit_rank 非 None 且 ≤5（judge_question 口径=首个锚匹配
    命中位次 ≤5 ⟺ 预期文档进 top-5；expect_miss 行不参与四卷线）。"""
    hr = row.get("hit_rank")
    return hr is not None and hr <= 5


def judge_volume(vol_key, parsed, line):
    """单卷四线判定 → dict（verdict ∈ pass/fail/exempt；fail=BLOCK 面）。

    - 基线：top5_n ≥ min_top5 → pass；
    - 豁免（档内 C09 口径）：失题集合 ⊆ exempt_ids 且 top5_n ≥ min_top5-len(exempt_ids)
      → exempt（豁免过，不阻断；非 C09 失题/多失题不过线）；
    - miss_ids 自题行重算（relevance 行 hit_rank>5 或 None），与卷级 top5_n 互补
      校验不一致记警示（不改变判定，防 schema 漂移静默误判）；
    - view 绑定（2026-10-08 C 线收口批）：line.view=="pipeline" 时按证书管线面
      读数判（分母=n_rel_pipeline、miss_ids 自题行 pipeline.hit_rank 重算，
      窗=终证据 top5）；缺省/“cosine”=现状零变化。证书无管线读数而线绑
      pipeline=显式报错（不伪绿）。
    """
    view = line.get("view") or "cosine"
    if view == "pipeline":
        pipe = parsed.get("pipeline") or {}
        if not isinstance(pipe.get("top5_n"), int) \
                or not isinstance(pipe.get("n_rel"), int):
            raise GateDataError(
                "%s 卷线绑 pipeline 视图但证书无管线读数（smoke 须 --pipeline-view）"
                % vol_key)
        n, top5_n = pipe["n_rel"], pipe["top5_n"]
        miss_ids = [str(r.get("qid")) for r in parsed["questions"]
                    if (r.get("judge_type") or "relevance") == "relevance"
                    and not ((r.get("pipeline") or {}).get("top5_ok") is True)]
        view_tag = "（管线视图）"
    else:
        n, top5_n = parsed["n"], parsed["top5_n"]
        miss_ids = [str(r.get("qid")) for r in parsed["questions"]
                    if (r.get("judge_type") or "relevance") == "relevance"
                    and not row_top5_ok(r)]
        view_tag = ""
    exempt_ids = list(line.get("exempt_ids") or [])
    warnings = []
    if len(miss_ids) != max(0, n - top5_n):
        warnings.append("%s 卷：题行失题数 %d 与卷级 top5_n=%d/n=%d 互补不一致"
                        "（schema 漂移警示，判定以卷级为准）" % (
                            vol_key, len(miss_ids), top5_n, n))
    if view == "cosine" and line.get("n") is not None and n != line["n"]:
        warnings.append("%s 卷：题数 %d 与档内线题数 %d 不符（卷改版须同步调线）"
                        % (vol_key, n, line["n"]))
    ok = top5_n >= line["min_top5"]
    exempt_ok = (not ok) and set(miss_ids) <= set(exempt_ids) \
        and top5_n >= line["min_top5"] - len(exempt_ids)
    if ok:
        verdict, detail = "pass", "top5 %d/%d ≥ 线 %d%s" % (
            top5_n, n, line["min_top5"], view_tag)
    elif exempt_ok:
        verdict = "exempt"
        detail = "top5 %d/%d < 线 %d，失题=%s ⊆ 豁免清单 %s（豁免在档→判过）%s" % (
            top5_n, n, line["min_top5"], "、".join(miss_ids) or "（无）",
            "、".join(exempt_ids), view_tag)
    else:
        verdict = "fail"
        detail = "top5 %d/%d < 线 %d；失题=%s（豁免面=%s）%s" % (
            top5_n, n, line["min_top5"], "、".join(miss_ids) or "（无）",
            "、".join(exempt_ids) or "无", view_tag)
    return {"verdict": verdict, "detail": detail, "n": n, "top5_n": top5_n,
            "top5_rate": parsed.get("top5_rate"), "miss_ids": miss_ids,
            "view": view, "warnings": warnings}


def parse_s1_result(path):
    """s1_negctrl_eval --json 产物 → 归一 dict。

    结构依赖：combos[]（jia/yi/bing/pos/neg/misfire——门禁消费甲乙丙全开组合）、
    four_paper{A,B,Y: cover_gate_triggers, C: 挂起}、meta.store_stats/run_seconds。
    """
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise GateDataError("S1 机读 JSON 读取失败（%s）：%s" % (path, e))
    combos = data.get("combos")
    if not isinstance(combos, list) or not combos:
        raise GateDataError("S1 机读 JSON 无 combos（%s）" % path)
    sel = next((c for c in combos
                if c.get("jia") and c.get("yi") and c.get("bing")), None)
    if sel is None:
        raise GateDataError("S1 机读 JSON 缺甲乙丙全开组合（%s）" % path)
    four = data.get("four_paper") or {}
    return {"combo": sel, "four_paper": four,
            "meta": data.get("meta") or {},
            "baseline_crosscheck": data.get("baseline_crosscheck")}


def judge_negctrl(parsed, line):
    """S1 负控线判定 → dict（verdict ∈ pass/fail；fail=BLOCK 面）。

    域内误伤口径=两面板之和：① S1 卷锚定题覆盖闸误触发（combo.misfire——正控题/
    非型4 负控题被丙层误拦即域内误伤，方案 §四.3 机器面）；② 四卷面 A/B/Y 安全
    词形触发数（four_paper[k].cover_gate_triggers；C 卷向量无缓存恒挂起、样例/K
    面零 API 不复算——挂起面沿 s1 件档内口径）。任一面破 misfire_max 即 BLOCK。
    """
    sel = parsed["combo"]
    neg, pos = int(sel.get("neg", 0)), int(sel.get("pos", 0))
    s1_misfire = len(sel.get("misfire") or [])
    four = parsed.get("four_paper") or {}
    aby_triggers = sum(len((four.get(k) or {}).get("cover_gate_triggers") or [])
                       for k in ("A", "B", "Y"))
    misfire_total = s1_misfire + aby_triggers
    checks = {"neg": neg >= line["neg_min"],
              "pos": pos >= line["pos_min"],
              "misfire": misfire_total <= line["misfire_max"]}
    verdict = "pass" if all(checks.values()) else "fail"
    # 正控基数=4（2026-10-06 起，S1V-05 退役口径）；负控面基数=14（2026-10-08 起，
    # 卷重编口径：S1V-10 退役＋S1V-17..20 改靶，负控面 15→14 含改靶正控 4 题；
    # 历史 /15 读数见 .bak-20261008-卷维护前 备份）
    detail = ("负控 %d/14（线≥%d）｜正控 %d/4（线=%d）｜域内误伤 %d（S1 锚定 %d"
              "+四卷触发 %d，线≤%d）" % (neg, line["neg_min"], pos, line["pos_min"],
                                        misfire_total, s1_misfire, aby_triggers,
                                        line["misfire_max"]))
    return {"verdict": verdict, "detail": detail, "neg": neg, "pos": pos,
            "s1_misfire": s1_misfire, "aby_cover_triggers": aby_triggers,
            "misfire_total": misfire_total, "checks": checks,
            "fail_ids": sel.get("fail_ids") or []}


def judge_answers(parsed, line):
    """答案卷判定 → dict（verdict ∈ pass/fail/record；fail=BLOCK 面）。

    faithfulness_rate_min=None（默认）=只记录不阻断——**judge 未校准转正前不
    阻断**（G3 校准复核表在档待用户，转正后经 --config 定 [0,1] 数值线启用；
    rate 为 None=judge 全降级，同样只记录并警示）。
    """
    rate = parsed.get("metrics_extra", {}).get("faithfulness_rate")
    threshold = line.get("faithfulness_rate_min")
    warnings = []
    if rate is None:
        warnings.append("答案卷 faithfulness_rate=None（judge 全降级或零评审对象），"
                        "只记录")
    if threshold is None:
        verdict = "record"
        detail = "faithfulness_rate=%s（线未设定=只记录——judge 未校准转正前不阻断）" % (
            "Null" if rate is None else "%.4f" % rate)
    else:
        ok = rate is not None and rate >= threshold
        verdict = "pass" if ok else "fail"
        detail = "faithfulness_rate=%s，线≥%.4f → %s" % (
            "Null" if rate is None else "%.4f" % rate, threshold,
            "过" if ok else "未过（含 judge 全降级）")
    return {"verdict": verdict, "detail": detail, "faithfulness_rate": rate,
            "threshold": threshold, "warnings": warnings}


# ---------------------------------------------------------------------------
# 指标面板 + bootstrap CI（D1+D2，2026-10-07 Wave D；纯重排零 API，判定面零变化）
# ---------------------------------------------------------------------------
def bootstrap_ci_mean(values, n_resample=PANEL_BOOTSTRAP_N,
                      level=PANEL_BOOTSTRAP_LEVEL, seed=PANEL_BOOTSTRAP_SEED):
    """D2：均值读数的百分位法 bootstrap CI（标准库 random）→ (lo, hi, n) 或 None。

    values=0/1 或数值向量（空 → None）；n_resample 缺省 2000（任务线 ≥2000）；
    seed 固定缺省 → 同一向量恒得同一 CI（面板可独立重生成）。百分位取序：升序
    均值数组的 [α/2, 1-α/2] 位（int 截断，越界钳 n_resample-1）。
    """
    vals = [float(v) for v in (values or [])]
    n = len(vals)
    if n == 0:
        return None
    rng = random.Random(seed)
    alpha = 1.0 - level
    means = sorted(sum(vals[rng.randrange(n)] for _ in range(n)) / n
                   for _ in range(n_resample))
    lo = means[min(int(alpha / 2 * n_resample), n_resample - 1)]
    hi = means[min(int((1 - alpha / 2) * n_resample), n_resample - 1)]
    return lo, hi, n


def _ci_entry(values, unavailable_reason=None):
    """D2：CI 机读条目 → dict（available False 只带 reason；n<10 记 small_n）。"""
    if unavailable_reason:
        return {"available": False, "reason": unavailable_reason}
    res = bootstrap_ci_mean(values)
    if res is None:
        return {"available": False, "reason": "零样本"}
    lo, hi, n = res
    return {"available": True, "lo": round(lo, 4), "hi": round(hi, 4), "n": n,
            "small_n": n < PANEL_SMALL_N}


def _ci_str(entry):
    """CI 控制台文本（面板行内用；不可用如实报原因）。"""
    if not entry or not entry.get("available"):
        return "CI 不出（%s）" % ((entry or {}).get("reason") or "缺位")
    s = "%.0f%%CI [%.4f,%.4f]" % (PANEL_BOOTSTRAP_LEVEL * 100,
                                  entry["lo"], entry["hi"])
    if entry.get("small_n"):
        s += "（n=%d<%d：区间宽仅供参考）" % (entry["n"], PANEL_SMALL_N)
    return s


def _mean(values):
    vals = list(values or [])
    return (sum(vals) / len(vals)) if vals else None


def _looks_refused(text):
    """误拒词形启发式：答案文本命中拒答标记词形即 True（保守口径，零 API）。"""
    return any(m in (text or "") for m in REFUSAL_MARKERS)


def volume_top5_vector(parsed):
    """四卷题行 → 0/1 top5 向量（row_top5_ok 同口径；expect_miss 行不入——四卷线面）。"""
    return [1 if row_top5_ok(r) else 0 for r in (parsed.get("questions") or [])
            if (r.get("judge_type") or "relevance") == "relevance"]


def answers_judge_vectors(parsed):
    """答案卷题行 → 判官维度向量组（零 API 纯重排）。

    判官非 null 行（answer_judge.dims 含 faithfulness 键）才入分母——与工具侧
    answer_paper_metrics 的 ok 集合同口径（降级行不入）；abstain 行识别=
    dims.abstention ∈ {pass,fail}（工具侧 normal 题该维恒 na，卷面 expected_type
    不入题行输出故以判官维为识别面）。
    """
    faith, apass, abst, normal_refused = [], [], [], []
    for r in (parsed.get("questions") or []):
        aj = r.get("answer_judge") or {}
        dims = aj.get("dims") or {}
        if "faithfulness" not in dims:
            continue                          # 判官降级/null 行：不入任何分母
        faith.append(1 if dims["faithfulness"] == "pass" else 0)
        apass.append(1 if aj.get("pass") else 0)
        if dims.get("abstention") in ("pass", "fail"):
            abst.append(1 if dims["abstention"] == "pass" else 0)
        else:                                 # normal 行 → 误拒词形扫描
            normal_refused.append(1 if _looks_refused(aj.get("answer")) else 0)
    return {"faith": faith, "answer_pass": apass, "abstain_pass": abst,
            "normal_refused": normal_refused}


def _panel_value_note(value, n, source, extra=""):
    return {"available": value is not None, "value": value, "n": n,
            "source": source, "note": extra}


def build_panel(vol_parsed=None, ans_parsed=None, lines=None, mode="real"):
    """D1 面板装配 → dict（纯重排：零 API 零子进程；不参与门禁判定）。

    vol_parsed={A/B/C/Y: parse_smoke_result 产物或 None}；ans_parsed=答案卷产物或
    None（--with-answers 未开/dry-run 均 None）；mode ∈ real/dry-run（dry-run 全
    占位标注不判定）。CI 一律进 panel["ci"]（D2 键位），元信息在 ci_meta。
    """
    dry = (mode == "dry-run")
    lines = lines or HARD_LINES
    metrics = {"faithfulness": {}, "refusal": {}, "retrieval": {}, "relevance": {}}
    ci = {}

    def _unavail(kind):
        return {"available": False,
                "note": "dry-run 占位（不判定）" if dry else kind}

    # ---- ① faithfulness + ② 拒答准确率 + ④ 答案相关性（答案卷三面）----
    vecs = answers_judge_vectors(ans_parsed) if (ans_parsed and not dry) else None
    mx = (ans_parsed or {}).get("metrics_extra") or {}
    if vecs is None:
        f_note = r_note = rel_note = _unavail(
            "待判卷授权（--with-answers 未开）" if not dry else "")
        metrics["faithfulness"] = f_note
        metrics["relevance"] = dict(f_note)
        metrics["refusal"] = {"correct": dict(f_note), "wrong": dict(f_note),
                              "accuracy": dict(f_note),
                              "adversarial": dict(f_note)}
        for k in ("faithfulness_rate", "refusal_correct_rate",
                  "refusal_wrong_rate", "refusal_accuracy", "answer_pass_rate"):
            ci[k] = {"available": False,
                     "reason": "dry-run 占位" if dry else "答案卷通道未开"}
    else:
        # ① faithfulness：题行向量优先；缺位回退卷级读数（CI 不出）；交叉核对
        f_vec = vecs["faith"]
        f_val, f_n = _mean(f_vec), len(f_vec)
        note = "题行判官 faithfulness 维 pass 率"
        if not f_vec:
            rate = mx.get("faithfulness_rate")
            if rate is not None:
                f_val, f_n = rate, mx.get("answer_judged")
                note = "卷级读数直取（题行判官维度缺位，CI 不出）"
            else:
                f_val, note = None, "judge 全降级/零评审对象"
        else:
            rate = mx.get("faithfulness_rate")
            if rate is not None and abs(f_val - rate) > 1e-9:
                note += "；警示：题行均值与卷级 faithfulness_rate 不一致（schema 漂移）"
        metrics["faithfulness"] = _panel_value_note(
            None if f_val is None else round(f_val, 4), f_n, "答案卷 judge", note)
        ci["faithfulness_rate"] = _ci_entry(
            f_vec, None if f_vec else "题行向量缺位（卷级读数无重采样面）")

        # ② 拒答准确率（对拒/误拒/综合；对抗卷面留位）
        abst = vecs["abstain_pass"]
        wrong = vecs["normal_refused"]
        c_val = _mean(abst)
        w_val = _mean(wrong)
        acc_vec = abst + [1 - x for x in wrong]
        a_val = _mean(acc_vec)
        metrics["refusal"] = {
            "correct": _panel_value_note(
                None if c_val is None else round(c_val, 4), len(abst),
                "答案卷 abstain 题 abstention 维（对拒）",
                "" if abst else "无 abstain 题行（判官维度缺位或卷改版）"),
            "wrong": {"available": w_val is not None,
                      "count": sum(wrong), "n": len(wrong),
                      "value": None if w_val is None else round(w_val, 4),
                      "source": "答案卷 normal 题误拒（词形启发式，保守口径）",
                      "note": "" if wrong is not None and len(wrong) else "无 normal 判官行"},
            "accuracy": _panel_value_note(
                None if a_val is None else round(a_val, 4), len(acc_vec),
                "答案卷（对拒+normal 未误拒）/判官行",
                "" if acc_vec else "零判官行"),
            "adversarial": {"available": False,
                            "note": "对抗卷面未接入：对抗卷（题卷/对抗卷-1.0.json，"
                                    "210 题/30 abstain）不在本门禁执行链——读数载体="
                                    "R3I 同构仪器（mq同构评测-20261006.py），线见 "
                                    "门禁线-生产.json adversarial 段；面板留位待接"}}
        ci["refusal_correct_rate"] = _ci_entry(
            abst, None if abst else "无 abstain 题行")
        ci["refusal_wrong_rate"] = _ci_entry(
            wrong, None if wrong else "无 normal 判官行")
        ci["refusal_accuracy"] = _ci_entry(
            acc_vec, None if acc_vec else "零判官行")

        # ④ 答案相关性：判官综合过题率（代理口径）
        p_vec = vecs["answer_pass"]
        p_val, p_n = _mean(p_vec), len(p_vec)
        note = "判官综合过题率（代理口径，非专测相关性维；compare 通道系检索对照不取）"
        if not p_vec:
            aj_n, ap = mx.get("answer_judged"), mx.get("answer_pass")
            if isinstance(aj_n, int) and aj_n > 0 and isinstance(ap, int):
                p_val, p_n = ap / aj_n, aj_n
                note = "卷级读数直取（题行判官维度缺位，CI 不出）"
            else:
                p_val = None
                note = "judge 全降级/零评审对象"
        metrics["relevance"] = _panel_value_note(
            None if p_val is None else round(p_val, 4), p_n, "答案卷 judge", note)
        ci["answer_pass_rate"] = _ci_entry(
            p_vec, None if p_vec else "题行向量缺位（卷级读数无重采样面）")

    # ---- ③ 检索召回/精度（四卷面）----
    recall = {}
    prec_per = {}
    for k in FOUR_VOLUME_KEYS:
        parsed = (vol_parsed or {}).get(k)
        if not parsed or dry:
            recall[k] = _unavail("卷机读产物缺位" if not dry else "")
            prec_per[k] = dict(recall[k])
            ci["top5_rate_%s" % k] = {"available": False,
                                      "reason": "dry-run 占位" if dry else "卷机读产物缺位"}
            continue
        n, top5_n = parsed["n"], parsed["top5_n"]
        line = lines["volumes"].get(k) or {}
        recall[k] = {"available": True, "pass_n": top5_n, "n": n,
                     "value": round(top5_n / n, 4) if n else None,
                     "line_min_top5": line.get("min_top5"),
                     "exempt_ids": list(line.get("exempt_ids") or [])}
        vec = volume_top5_vector(parsed)
        ci["top5_rate_%s" % k] = _ci_entry(
            vec, None if vec else "题行向量缺位（卷级读数无重采样面）")
        m = parsed.get("metrics_extra") or {}
        prec_per[k] = {"unexpected_hits": m.get("unexpected_hits"),
                       "cross_total": m.get("cross_total"),
                       "hard_neg_hit_rate": (parsed.get("soft") or {}).get(
                           "hard_neg_hit_rate")}

    def _sum_or_none(key):
        vals = [v[key] for v in prec_per.values()
                if isinstance(v, dict) and isinstance(v.get(key), (int, float))]
        return sum(vals) if vals else None

    metrics["retrieval"] = {
        "recall": recall,
        "precision": {"per_volume": prec_per,
                      "sum_unexpected_hits": _sum_or_none("unexpected_hits"),
                      "sum_cross_total": _sum_or_none("cross_total"),
                      "note": "越低越好；负锚命中率 None=该卷未测（只记录不阻断）"}}
    return {"schema": PANEL_SCHEMA, "mode": mode,
            "note": "D1 指标面板：既有结果纯重排（零新增 API/零子进程），不参与门禁"
                    "判定；CI=D2 百分位法 bootstrap（依据=%s）" % PANEL_DOC,
            "metrics": metrics, "ci": ci,
            "ci_meta": {"method": "percentile bootstrap（标准库 random.Random）",
                        "n_resample": PANEL_BOOTSTRAP_N,
                        "level": PANEL_BOOTSTRAP_LEVEL,
                        "seed": PANEL_BOOTSTRAP_SEED,
                        "small_n_threshold": PANEL_SMALL_N,
                        "small_n_note": "区间宽仅供参考"}}


def build_panel_from_run_dir(run_dir, config_path=None):
    """面板独立重生成：从 run_dir 留痕工具机读产物重解析 → panel（零子进程零 API）。

    与 execute() 真跑面板同源同种子（PANEL_BOOTSTRAP_SEED 固定）→ 同数据同 CI；
    产物缺位的卷如实标缺位（不补跑）。
    """
    lines, _src = merge_lines(config_path)
    parsed = {}
    for key in list(FOUR_VOLUME_KEYS) + [ANSWER_KEY]:
        p = os.path.join(run_dir, "smoke-%s.json" % key)
        parsed[key] = (parse_smoke_result(p, expect_paper=EXPECT_PAPER_IDS[key])
                       if os.path.exists(p) else None)
    return build_panel(parsed, parsed.get(ANSWER_KEY), lines, mode="real")


def print_panel(panel, say=print):
    """面板一页化控制台输出（stdout 末节；dry-run 占位如实标注）。"""
    m = (panel or {}).get("metrics") or {}
    say("\n---- 指标面板（D1 一页化｜只重排既有结果零新增 API｜只呈现不阻断）----")
    dry = (panel or {}).get("mode") == "dry-run"
    ci = (panel or {}).get("ci") or {}

    f = m.get("faithfulness") or {}
    if f.get("available"):
        say("faithfulness      %.4f（n=%s）  %s  ［%s］%s" % (
            f["value"], f.get("n"), _ci_str(ci.get("faithfulness_rate")),
            f.get("source", ""), f.get("note", "")))
    else:
        say("faithfulness      -（%s）" % (f.get("note") or "缺位"))

    r = m.get("refusal") or {}
    for part, label, cik in (("correct", "对拒", "refusal_correct_rate"),
                             ("wrong", "误拒", "refusal_wrong_rate"),
                             ("accuracy", "综合", "refusal_accuracy")):
        e = r.get(part) or {}
        if e.get("available"):
            cnt = e.get("count")
            if cnt is None:
                cnt = int(round(e["value"] * e["n"]))
            say("拒答准确率·%s    %s/%s=%.4f  %s  ［%s］%s" % (
                label, cnt, e["n"], e["value"], _ci_str(ci.get(cik)),
                e.get("source", ""), e.get("note", "")))
        else:
            say("拒答准确率·%s    -（%s）" % (label, e.get("note") or "缺位"))
    adv = r.get("adversarial") or {}
    say("拒答准确率·对抗卷面  %s" % (adv.get("note") or "缺位"))

    t = m.get("retrieval") or {}
    rec = t.get("recall") or {}
    if any((rec.get(k) or {}).get("available") for k in FOUR_VOLUME_KEYS):
        say("检索召回/精度      召回（top-5 相关率=题卷命中块对期望锚）：%s" % "｜".join(
            "%s %s/%s=%s" % (k, rec[k]["pass_n"], rec[k]["n"], rec[k]["value"])
            for k in FOUR_VOLUME_KEYS if (rec.get(k) or {}).get("available")))
        say("                  每卷 CI：%s" % "｜".join(
            "%s %s" % (k, _ci_str(ci.get("top5_rate_%s" % k)))
            for k in FOUR_VOLUME_KEYS if (rec.get(k) or {}).get("available")))
        pr = t.get("precision") or {}
        say("                  精度信号（越低越好）：expect_miss 意外命中 Σ%s｜越域命中 Σ%s"
            "｜负锚命中率 %s" % (
                pr.get("sum_unexpected_hits") if pr.get("sum_unexpected_hits") is not None else "未测",
                pr.get("sum_cross_total") if pr.get("sum_cross_total") is not None else "未测",
                "未测（有值时见机读 panel.metrics.retrieval.precision）"))
    else:
        say("检索召回/精度      -（%s）" % (
            "dry-run 占位（不判定）" if dry else "卷机读产物缺位"))

    rel = m.get("relevance") or {}
    if rel.get("available"):
        say("答案相关性        %.4f（n=%s）  %s  ［%s］%s" % (
            rel["value"], rel.get("n"), _ci_str(ci.get("answer_pass_rate")),
            rel.get("source", ""), rel.get("note", "")))
    else:
        say("答案相关性        -（%s）" % (rel.get("note") or "缺位"))

    if dry:
        say("（dry-run 模式：面板占位值不判定——真跑后既有产物自动出数）")
    meta = (panel or {}).get("ci_meta") or {}
    say("（面板 CI=%s，n_resample=%s，seed=%s；依据=%s）" % (
        meta.get("method"), meta.get("n_resample"), meta.get("seed"), PANEL_DOC))


# ---------------------------------------------------------------------------
# 编排：全链执行 → 判定 → 报告
# ---------------------------------------------------------------------------
# 各卷期望 paper_id（身份绑定：题卷文件被换/改 id 即拒收，防跑错卷静默判分）
EXPECT_PAPER_IDS = {"A": "验收卷A(内置)", "B": "独立B", "C": "独立C实操",
                    "Y": "独立Y意译", "ANS": "ANSWER-1.1"}


def default_report_path():
    """机读报告缺省落点：建库/logs/eval_gate-<YYYYMMDD>.json（当日重跑覆盖式，
    ran_at 在档——沿 smoke_accept --json 覆盖式先例）。"""
    return os.path.join(LOGS_DIR, "eval_gate-%s.json" % time.strftime("%Y%m%d"))


def precheck_missing(vol_keys, with_negctrl):
    """前置存在性核查 → 缺失清单（空=过）。"""
    missing = []
    if not os.path.exists(VENV_PYTHON):
        missing.append(VENV_PYTHON)
    if not os.path.exists(os.path.join(SCRIPTS_DIR, SMOKE_TOOL)):
        missing.append(os.path.join(SCRIPTS_DIR, SMOKE_TOOL))
    if with_negctrl and not os.path.exists(os.path.join(SCRIPTS_DIR, S1_TOOL)):
        missing.append(os.path.join(SCRIPTS_DIR, S1_TOOL))
    for k in vol_keys:
        if k in PAPER_FILES and not os.path.exists(
                os.path.join(SCRIPTS_DIR, PAPER_FILES[k])):
            missing.append(os.path.join(SCRIPTS_DIR, PAPER_FILES[k]))
    return missing


def _tool_rc_bad(rc):
    """子进程 rc 是否属工具失败（gate 退 2 面）：rc=2（工具前置失败）/超时(None)/
    信号崩溃(<0)/超范围。rc=1=工具自身线未过（如 A 卷内置四线），门禁按自身硬线
    独立判，只记录不沿袭。"""
    return rc is None or rc < 0 or rc not in (0, 1, 2) or rc == 2


def execute(args, run_dir=None, say=print):
    """全链编排 → (退出码, 报告 dict)。

    dry-run：smoke_accept 子进程走其 dry-run 形态（无 --yes，零调用零计费）；S1 件
    无 dry-run 位不执行只列计划命令；不判定恒退 0。真跑：smoke_accept 带 --yes
    （嵌入计费=执行单四卷复验同款口径）、S1 三开关全开、逐卷判硬线，任一 fail=BLOCK。
    """
    t0 = time.time()
    lines, lines_source = merge_lines(args.config)
    dry = bool(args.dry_run)
    vol_keys = list(FOUR_VOLUME_KEYS) + ([ANSWER_KEY] if args.with_answers else [])
    stamp = time.strftime("%Y%m%d-%H%M%S")
    if run_dir is None:
        run_dir = os.path.join(RUNS_DIR, stamp)
    if not dry:
        os.makedirs(run_dir, exist_ok=True)   # 工具机读产物留痕（BLOCK 取证面）
    say("==== 回归门禁 eval_gate（模式=%s｜ROOT=%s｜负控线=%s｜答案卷=%s｜线来源=%s）====" % (
        "dry-run 预览（零调用）" if dry else "真跑（四卷嵌入 ≈0.0005 元级）",
        ROOT, "开" if args.with_negctrl else "关", "开" if args.with_answers else "关",
        lines_source))

    report = {
        "schema": GATE_SCHEMA,
        "ran_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": "dry-run" if dry else "real",
        "switches": {"negctrl": bool(args.with_negctrl),
                     "answers": bool(args.with_answers)},
        "lines": {"volumes": lines["volumes"], "negctrl": lines["negctrl"],
                  "answers": lines["answers"], "source": lines_source},
        "caliber_note": build_caliber_note(),   # 口径注记（真跑后按观察集重算）
        "gate": {"blocked": False, "exit_code": 0, "failed": [], "error": None},
        "volumes": [], "negctrl": None, "answers": None,
        "warnings": [], "run_dir": run_dir if not dry else None,
        "duration_s": 0.0,
    }
    if dry:
        report["planned_run_dir"] = run_dir

    missing = precheck_missing(vol_keys, args.with_negctrl)
    if missing:
        raise GateDataError("前置缺失（退 2 不空跑）：%s" % "、".join(missing))

    error = None
    observed_channels = []          # 各卷 smoke 证书头 channel 观察集（注记引用面）
    parsed_by_key = {}              # 各卷机读产物归一结果（D1 面板取数面）
    try:
        # ---- 四卷（+答案卷）：smoke_accept 子进程逐卷 ----
        _any_pipeline = any((lines["volumes"].get(k) or {}).get("view") == "pipeline"
                            for k in vol_keys if k != ANSWER_KEY)
        for key in vol_keys:
            json_path = os.path.join(run_dir, "smoke-%s.json" % key)
            cmd = build_smoke_cmd(key, json_path, real=not dry,
                                  with_answers=(key == ANSWER_KEY),
                                  pipeline_on=_any_pipeline)
            entry = {"key": key, "paper_id": EXPECT_PAPER_IDS[key], "tool": SMOKE_TOOL,
                     "cmd": cmd, "executed": True, "dry_run": dry,
                     "line": dict(lines["volumes"][key] if key != ANSWER_KEY
                                  else {"faithfulness_rate_min":
                                        lines["answers"]["faithfulness_rate_min"]})}
            rc, dur = run_tool(cmd, args.timeout, say=say)
            entry.update(rc=rc, duration_s=round(dur, 1))
            if _tool_rc_bad(rc):
                raise GateDataError("%s 卷工具失败（rc=%s，门禁退 2——判定数据缺位）"
                                    % (key, rc))
            if dry:
                entry["verdict"] = "preview"
                entry["detail"] = "dry-run 预览（子进程 dry-run 形态零调用，不判定）"
                if key == ANSWER_KEY:
                    report["answers"] = entry
                else:
                    report["volumes"].append(entry)
                continue
            parsed = parse_smoke_result(json_path,
                                        expect_paper=EXPECT_PAPER_IDS[key])
            parsed_by_key[key] = parsed
            if parsed.get("channel"):
                observed_channels.append(parsed["channel"])
            entry.update(paper_id=parsed["paper_id"], n=parsed["n"],
                         top5_n=parsed["top5_n"], top5_rate=parsed["top5_rate"],
                         tool_all_pass=parsed["all_pass"], lib=parsed["lib"],
                         channel=parsed["channel"],
                         score_caliber=parsed["score_caliber"],
                         soft=parsed["soft"], metrics_extra=parsed["metrics_extra"],
                         usage=parsed["usage"], tool_json=json_path)
            if key == ANSWER_KEY:
                j = judge_answers(parsed, lines["answers"])
                report["answers"] = dict(entry, **j)
            else:
                j = judge_volume(key, parsed, lines["volumes"][key])
                report["warnings"].extend(j.pop("warnings"))
                report["volumes"].append(dict(entry, **j))
            say("[judge] %s：%s → %s" % (key, j["detail"], j["verdict"]))

        # ---- S1 负控线（--with-negctrl）----
        if args.with_negctrl:
            json_path = os.path.join(run_dir, "s1-negctrl.json")
            cmd = build_s1_cmd(json_path)
            entry = {"tool": S1_TOOL, "cmd": cmd,
                     "line": dict(lines["negctrl"])}
            if dry:
                entry.update(executed=False, verdict="preview", rc=None,
                             duration_s=None)
                entry["detail"] = ("dry-run：S1 件无 dry-run 位（零 API 只读件），"
                                   "真跑模式才执行")
                say("[dry-run] S1 负控计划命令（不执行）：%s" % " ".join(cmd))
            else:
                rc, dur = run_tool(cmd, args.timeout, say=say)
                entry.update(executed=True, rc=rc, duration_s=round(dur, 1))
                if _tool_rc_bad(rc):
                    raise GateDataError("S1 负控工具失败（rc=%s，门禁退 2）" % rc)
                parsed = parse_s1_result(json_path)
                entry["meta"] = {"store_stats": parsed["meta"].get("store_stats"),
                                 "run_seconds": parsed["meta"].get("run_seconds"),
                                 "baseline_crosscheck": parsed["baseline_crosscheck"]}
                entry["four_paper_status"] = {
                    k: (parsed["four_paper"].get(k) or {}).get("status")
                    for k in ("A", "B", "C", "Y")}
                j = judge_negctrl(parsed, lines["negctrl"])
                entry.update(j)
                entry["tool_json"] = json_path
                say("[judge] S1负控：%s → %s" % (j["detail"], j["verdict"]))
            report["negctrl"] = entry
    except GateDataError as e:
        error = str(e)
        say("[gate-错误] %s" % error)

    # ---- 汇总判定（BLOCK 面=各硬线 fail；record/preview/exempt/pass 不阻断）----
    failed = []
    for v in report["volumes"]:
        if v.get("verdict") == "fail":
            failed.append({"scope": "%s卷" % v["key"], "detail": v["detail"]})
    if report["negctrl"] and report["negctrl"].get("verdict") == "fail":
        failed.append({"scope": "S1负控线", "detail": report["negctrl"]["detail"]})
    if report["answers"] and report["answers"].get("verdict") == "fail":
        failed.append({"scope": "答案卷", "detail": report["answers"]["detail"]})
    report["gate"]["failed"] = failed
    report["gate"]["blocked"] = bool(failed) and not dry and error is None
    report["duration_s"] = round(time.time() - t0, 1)
    if error is not None:
        report["gate"]["error"] = error
        report["gate"]["exit_code"] = 2
    elif dry:
        report["gate"]["exit_code"] = 0
    else:
        report["gate"]["exit_code"] = 1 if failed else 0

    # 口径注记重算（2026-10-03 复核件建议①）：真跑有证书头 channel 观察集按实重算
    # （dry-run 无机读产物=缺省表述）；只改注记文本，判定逻辑零变化。
    if observed_channels:
        report["caliber_note"] = build_caliber_note(observed_channels)
    # ---- 指标面板（D1+D2，2026-10-07 Wave D）：既有结果纯重排，零新增 API ----
    # 真跑=各卷已解析产物重排成四指标一页；dry-run=无产物全占位（不判定）。
    report["panel"] = build_panel(
        vol_parsed={k: parsed_by_key.get(k) for k in FOUR_VOLUME_KEYS},
        ans_parsed=parsed_by_key.get(ANSWER_KEY), lines=lines,
        mode="dry-run" if dry else "real")
    print_report(report, say=say)
    if args.json is not None:
        path = default_report_path() if args.json == "auto" else args.json
        write_report(report, path, say=say)
    return report["gate"]["exit_code"], report


# ---------------------------------------------------------------------------
# 控制台报告与机读落盘
# ---------------------------------------------------------------------------
def _fmt(v, spec="%s"):
    return "-" if v is None else spec % v


def _md5_short(lib):
    md5 = (lib or {}).get("md5")
    return (md5[:8] + "…") if md5 else "-"


def print_report(report, say=print):
    """控制台表格：四卷硬线表+软指标表+负控/答案节+门禁判定横幅。"""
    say("\n---- 四卷硬线（BLOCK 线；口径=top-5 相关率=%s）----"
        % report["lines"]["source"])
    say("%-4s %-14s %-5s %-9s %-22s %-5s %-4s %-10s" % (
        "卷", "卷id", "题数", "top5", "硬线", "判定", "工具线", "库md5"))
    for v in report["volumes"]:
        if v.get("verdict") == "preview":
            say("%-4s %-14s %-5s %-9s %-22s %-5s" % (
                v["key"], v["paper_id"], "-", "-", "（dry-run 预览不判定）", "预览"))
            continue
        line = v["line"]
        line_disp = "≥%d" % line["min_top5"] if line["min_top5"] == (line.get("n") or 0) \
            else "≥%d/%s" % (line["min_top5"], line.get("n") or "?")
        if line.get("exempt_ids"):
            line_disp += "（豁免 %s）" % "、".join(line["exempt_ids"])
        say("%-4s %-14s %-5d %-9s %-22s %-5s %-4s %-10s" % (
            v["key"], v["paper_id"], v["n"], "%d/%d" % (v["top5_n"], v["n"]),
            line_disp, v["verdict"],
            "-" if v.get("tool_all_pass") is None else (
                "过" if v["tool_all_pass"] else "未过"),
            _md5_short(v.get("lib"))))
    soft_rows = [v for v in report["volumes"] if v.get("soft")]
    if soft_rows:
        say("（软指标只记录不阻断：MRR@10／nDCG@10／hard_neg_hit_rate／嵌入费）")
        say("%-4s %-8s %-8s %-8s %-10s" % ("卷", "MRR@10", "nDCG@10", "hard_neg", "嵌入费"))
        for v in soft_rows:
            s = v["soft"]
            cost = (v.get("usage") or {}).get("est_cost_cny")
            say("%-4s %-8s %-8s %-8s %-10s" % (
                v["key"], _fmt(s.get("mrr_at_10"), "%.4f"),
                _fmt(s.get("ndcg_at_10"), "%.4f"),
                _fmt(s.get("hard_neg_hit_rate"), "%.3f"),
                _fmt(cost, "%.6f")))
    neg = report.get("negctrl")
    if neg is not None:
        say("\n---- S1 负控线（--with-negctrl%s）----" % (
            "" if neg.get("verdict") != "preview" else "；dry-run 只列计划不执行"))
        say("%s → %s" % (neg["detail"], neg.get("verdict", "preview")))
    ans = report.get("answers")
    if ans is not None:
        say("\n---- 答案卷（--with-answers；faithfulness 硬线键预留，默认只记录——"
            "judge 未校准转正前不阻断）----")
        say("ANS %-14s %s → %s" % (ans.get("paper_id"), ans["detail"],
                                   ans.get("verdict")))
    g = report["gate"]
    say("\n==== 门禁判定：%s%s====" % (
        ("BLOCK（%d 线未过——exit 1 阻断）" % len(g["failed"])
         if g["blocked"] else "通过（硬线全过）")
        if report["mode"] != "dry-run"
        else "dry-run 预览（零调用，不判定）",
        "；工具/前置错误（exit 2）" if g["error"] else ""))
    for f in g["failed"]:
        say("  ✗ %s：%s" % (f["scope"], f["detail"]))
    for w in report["warnings"]:
        say("  ⚠ %s" % w)
    # 口径注记行（判定段后恒打一行——复核件建议①，防"门禁绿=产线绿"误读）
    say(report.get("caliber_note") or build_caliber_note())
    # 指标面板（D1+D2，2026-10-07）：stdout 末节一页化（零新增 API；不参与判定）
    print_panel(report.get("panel"), say=say)


def write_report(report, path, say=print):
    """机读报告落盘（父目录缺失则建；覆盖式，ran_at 在档）。"""
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    say("[json] 已写 → %s" % path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser():
    ap = argparse.ArgumentParser(
        prog="eval_gate.py",
        description="回归门禁：单一评测入口+硬指标阻断（四卷硬线 exit 1 阻断；"
                    "软指标只记录；报告恒含指标面板+bootstrap CI——D1+D2，"
                    "2026-10-07 Wave D，零新增 API 纯重排；详见模块 docstring）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例：
  python3 eval_gate.py --dry-run        # 全链零调用预览（子进程 dry-run 形态）
  python3 eval_gate.py --json           # 真跑四卷+落机读报告 logs/eval_gate-<日期>.json
  python3 eval_gate.py --with-negctrl --with-answers
  python3 eval_gate.py --config 门禁线.json
退出码：0=硬线全过（dry-run 恒 0）；1=BLOCK（硬线未过）；2=前置/工具失败。""")
    ap.add_argument("--with-negctrl", action="store_true",
                    help="加 S1 负控线（s1_negctrl_eval 三开关全开；验收=负控≥8/14"
                         "+正控 4/4（2026-10-06 口径）+域内误伤 0；零 API 只读件）")
    ap.add_argument("--with-answers", action="store_true",
                    help="加答案卷（smoke_accept --answers PAPER_FILES['ANS'] 所指卷；judge LLM "
                         "API 显式选入；faithfulness_rate 硬线键预留默认只记录——"
                         "judge 未校准转正前不阻断）")
    ap.add_argument("--dry-run", action="store_true",
                    help="全链零调用预览：子进程带 dry-run 标志（smoke_accept 不给 "
                         "--yes；S1 件无 dry-run 位不执行只列计划命令）；不判定退 0"
                         "（工具/前置失败仍退 2）")
    ap.add_argument("--json", nargs="?", const="auto", default=None, metavar="[路径]",
                    help="机读报告落盘（schema %s；缺省路径=建库/logs/eval_gate-"
                         "<日期>.json；dry-run 只记计划不判定）" % GATE_SCHEMA)
    ap.add_argument("--config", metavar="JSON路径",
                    help="硬线覆盖文件（分节合并 volumes/negctrl/answers；键白名单"
                         "校验，非法退 2）")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_S, metavar="秒",
                    help="单子进程墙钟预算（默认 %d 秒；超时按前置失败退 2）"
                         % DEFAULT_TIMEOUT_S)
    ap.add_argument("--root", metavar="目录",
                    help="仓库根目录覆盖（缺省=自动探测：脚本位置向上找含 "
                         "venv/建库 的祖先；环境变量 QA_BOT_ROOT 优先于本参数）")
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    root, root_src = resolve_root(cli_root=args.root)
    _apply_root(root)
    if args.root and root_src == ROOT_ENV:
        print("[root] QA_BOT_ROOT=%s 已生效，--root %s 被忽略（优先级：环境变量"
              ">CLI>自动探测）" % (root, args.root), file=sys.stderr)
    try:
        rc, _report = execute(args)
    except (GateConfigError, GateDataError, OSError) as e:
        print("[gate-错误] %s：%s" % (type(e).__name__, e), file=sys.stderr)
        return 2
    return rc


if __name__ == "__main__":
    sys.exit(main())
