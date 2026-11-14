#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""qa-bot 云端部署后验收一键脚本（本机执行；2026-09-18 立档，配套 运营/上云差异-第2批-20260918.md §七）

用法
----
    python3 <repo>/deploy_check.py [--smoke] [--hybrid-off]
            [--expect-loaded N] [--dry-run[=场景]]

档位
----
必跑（零 API 调用、零密值输出——证据行一律先脱敏再打印/落盘）：
    ① 服务活：systemctl is-active qa-bot == active
    ② 装载行：startup rag=on loaded=<n> bad_lines=0 dim=1024；另取云端
       sidecar meta count 对照"装载=库行数"（2026-10-15 换库窗②收口修：
       行式 embeddings.jsonl 未随换库更新=行式同步债已知界，行数对照改以
       sidecar count 为准，行式 wc -l 降为 sidecar 缺席时的回退档）。
       loaded 数字打印供与换库登底值人工对照（默认登底=本机镜像 meta count
       优先〔2026-10-26 估算面现代化：count 补 f32.bin 长度自证
       （count×dim×4==bin 字节），不符视坏值走行式二级；缺失回落本机行式
       行数，再回落常数 82,232=锚面卡批1换库窗 2026-10-26 终态口径〕，
       --expect-loaded N 覆盖；N=0 = 不按登底强校验、只打印数字）
    ③ [rag-bm25] build 行存在且 docs=loaded（默认档=hybrid 已启用时）；
       BM25 未启用跑 --hybrid-off，改核"最近一次启动后无 bm25/hybrid 行"
    ④ [chat] 行打点规则抽验（三规则五态）：hit 行带 q= 与 top1=（top1 缺分=na）；
       low_score 行同样带 q= 与 top1=（top1=触发闸门的余弦原始分，2026-09-21 批1
       低分拦截态）；coverage_miss 行同 low_score 规则（S1 治理丙负控覆盖闸态，
       2026-10-01 教识并入——此前整行从抽验消失）；miss 行只带 q= 无 top1=；
       off 行两字段皆无。[chat] 行尾 rt= 键（期1 路由开态，2026-10-01 起容忍且
       计数核读不误报）。能区分两种 FAIL 判读："云端仍是旧版 server.py（hit 行
       无 q=/top1=）" vs "新版已部署但形态异常"
    ⑤ /health == 200 且 ok:true（云端回环 curl，经 SSH，不出公网）
    ⑦ 装载内存预估闸：云端 MemAvailable vs 库峰值预估对照（2026-10-26
       估算面现代化：行式→bin 镜像口径，过程日志 176 债/235③——一条只读 SSH
       往返取 awk /proc/meminfo + 云端镜像形态 MC/MD/MB/MM〔count/dim/
       bin/meta 字节，校验契约与 rag._try_load_sidecar 同源〕；镜像缺席/
       过期/坏=LS 行式件字节回退=二级）——est>avail 即 FAIL（过程日志一节19
       窗后事故防线；公式与 建库/scripts/装载预检.py 单点同源〔peek_store
       同为镜像口径优先〕，编号⑥预留）
    ⑧ rerank 探针 armed（2026-10-12 合围工程基建一期 2-C 新项甲）：启动行
       [startup] rerank_log=<on|off> cap=<N>cny 在场且与部署意图一致。行缺=
       云端仍旧版（未部署新版）≠ rerank_log=off（新版有意关探针，部署动作）
       ——两种 FAIL 判读语义分开（沿 ④ 新旧版判读哲学）；证据通道=②既有
       journal 首段（grep 模式 ^\\[startup\\] 已覆盖该行，零新增 SSH 往返）
    ⑨ SOURCE_TIER 数据件在位（2-C 新项乙）：云端 /opt/qa-bot/data/source-tier.json
       存在且可解析（只读 SSH：远端 python os.path.exists+json.load，零改动
       零密值回显）。分级（并行泳道施工期容忍口径）：件缺=INFO 不红（泳道
       未合入/部署包未含——服务走 server.py 内置回退快照不受影响，泳道合入
       随包上云后自然转绿）；件在但解析失败=WARN（部署不完整——回退快照
       兜底服务可用，须人工重传）；取数通道失败=FAIL（同①⑦ 哲学）
    ⑩ rerank 行为键状态呈现（2-C 新项丙）：config 顶层键 rerank_refusal_enabled
       现值呈现（只读 SSH 远端 python 单键打印，零密值），不判红——键开=呈现
       开态+核 [rerank_gate] 行可判读；键关（默认 false）=关态呈现，零 gate 行
       属预期。[chat] rag=rerank_refused 态已入 ④ 既有五态规则（零新判定）
    ⑪ SLA 状态机读数（2026-10-14 产品维度升级收口 §三/§10）：SSH 只读云端
       /opt/qa-bot/建库/logs/obs-latency-自动-*.json 最新档（一条往返：ls -1
       排序取最新+次新、cat 最新），按 §10 冻结 schema 呈现截至期号（文件名
       日期）/真实样本/成功率/p50/p95/p99/状态机态/consecutive_miss/
       formal_since。**程序呈现、不阻断（绝不 FAIL）**：FORMAL 达标=INFO；
       INSUFFICIENT/最新档距今>14 天（缺期≥2）/json 损坏/字段缺/期数倒退=
       WARN+SLA_UNKNOWN；OBSERVING=WARN 观察期读数；FORMAL 连续未达/p95>8s/
       成功率<95%=WARN"连续未达 N 期，开窗时由用户裁定"；无档（脚本刚上云
       首窗未跑）=INFO"SLA 观测未起（首窗周五 08:30）"
    ⑫ 嵌入预算拨键呈现（§三/§五）：SSH 只读核云端 config.json rag 段预算三键
       （embed_monthly_budget_enabled/budget_cny/cap_cny；远端 python3 -c 只
       提取打印三键值，**绝不 cat 整个 config.json——密件纪律**，dry-run
       fixture 同理只含三键）。期望=true/40.0/50.0（本专项拨键口径：40=预警
       线/50=熔断线）；基态 INFO，值不符/budget≥cap/坏值/缺键=WARN——同 ⑪
       程序呈现级不阻断

可选 --smoke（默认不开）：
    产生 2 次问答调用（走云端服务自身的订阅 key；2 次查询嵌入走云端按量
    embed key，计入按量通道 5 元红线累计口径）且需要 passcode——自本机
    config.json 读入内存变量不回显，经 SSH stdin 送云端回环 curl
    （--data-binary @-），不落任何一侧命令行。两题=掉话率红线 / a3-Offset
    形态题，核 sources 事件与出处首位锚与答案数值。首位锚=**合格锚集**判定，
    锚集自条款级数据档 BASE_DIR/期望锚集-条款级.json 装载（2026-09-27 S1
    重校准升档：锚集外置+装载校验，档内含每锚回源三要件引文与冻结日期；
    S1=36号文 附录2 2.2.4｜附录4 4.2.2，S2=TS 36.331 a3-Offset 参数卡族；
    档缺失/非法=FAIL 不静默回退）；题后回捞 [chat]/[rag-embed]/[rag-hybrid]
    行佐证④；口吻项（清单⑦）属人工判读，报告给答案摘录供人眼复核。

可选 --hybrid-off：hybrid 未启用时的降级核对集（③跳过，改核无 bm25 行）。

--dry-run[=场景]：自测模式，不连云端（场景 ok|ok-off|oldver|offline，默认
    ok），用内置样例日志走同一套判定逻辑；报告落 /tmp，不入仓目录。

退出码：0=无 FAIL；1=存在 FAIL（或运行性错误）。
报告：<repo>/运营/部署核验-YYYYMMDD-HHMM.md（同分钟重跑自动加序号）。

纪律：不执行任何 git 命令；对云端全部命令只读（is-active/journalctl/wc/curl
回环 GET 与 POST 问答本身），不改云端任何状态；SSH 登录目标运行时自
运维私密-20260916.md 只读解析、全程不回显；输出与报告里 IP/口令/key 一律
脱敏形态（<IP>/<IPv6>/<用户@主机>/<KEY>）。
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime

# ---------- 常量（路径全绝对） ----------
BASE_DIR = "<repo>"
SECRET_FILE = os.path.join(BASE_DIR, "运维私密-20260916.md")
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
REPORT_DIR = os.path.join(BASE_DIR, "运营")
UNIT = "qa-bot"
CLOUD_DIR = "/opt/qa-bot"
STORE_REL = "建库/vectors/embeddings.jsonl"
OLD_LIB_LINES = 14055            # 公开源一期旧库口径（loaded=14055 = 仍旧版库）
# 2026-10-01 缺口修 A：登底默认值动态化——本机现行库行数（缺失回落旧常数）；
# 实测教训：刷新轮云端 52,626 被旧常数 14,266 误判 FAIL。
# 2026-10-15 换库窗②收口修：登底源升级=本机 sidecar meta count 优先（换库后
# 行式件未随 sidecar 更新=行式同步债已知界〔换库窗②-执行回执-20261015 已知界
# ③〕，行式行数已不代表库态）；行式行数降为回退档；末位回落常数同步换 62,512
# （F 线语料专项换库终态口径，前回落常数 14,266 系 CR 重嵌 2026-09-18 交件口径）。
# 2026-10-26 估算面现代化（过程日志 176 债清账/235③）：meta count 补 f32.bin
# 长度自证（count×dim×4==bin 字节，即 faiss ntotal 持久面自洽校验），不符
# 视坏值走行式二级回落——防 meta 半写/漂移态下误拿错 count 当登底。
STORE_META_REL = "建库/vectors/embeddings.jsonl.f32.meta.json"
STORE_BIN_REL = "建库/vectors/embeddings.jsonl.f32.bin"
def _local_meta_count():
    """本机 bin 镜像 count（现行库块数权威口径；读不到/坏值/自证不符返回 None）。"""
    try:
        with open(os.path.join(BASE_DIR, STORE_META_REL), encoding="utf-8") as f:
            meta = json.load(f)
        n, d = meta.get("count"), meta.get("dim")
        if (not isinstance(n, int) or isinstance(n, bool) or n < 0
                or not isinstance(d, int) or isinstance(d, bool) or d <= 0):
            return None
        if os.path.getsize(os.path.join(BASE_DIR, STORE_BIN_REL)) != n * d * 4:
            return None    # f32.bin 长度自证不符（镜像半写/漂移）=坏值走行式回落
        return int(n)
    except (OSError, ValueError):
        return None
def _local_store_lines():
    try:
        with open(os.path.join(BASE_DIR, STORE_REL), "rb") as f:
            return sum(1 for _ in f)
    except OSError:
        return None
DEFAULT_EXPECT_LOADED = (_local_meta_count() or _local_store_lines()
                         or 83031)    # staging799扩库窗 2026-10-26 终态口径（回落档；前值 82,232=锚面卡批1换库窗 口径）
HEALTH_URL = "http://127.0.0.1:8000/api/health"
CHAT_URL = "http://127.0.0.1:8000/api/chat"
SMOKE_Q1 = "电信服务规范规定的掉话率监管红线是多少"      # 预期首位=36号文 附录2 2.2.4｜附录4 4.2.2（合格锚集，见 _s1_anchor_ok），答案 ≤5%
SMOKE_Q2 = "切换参数 a3-Offset 的取值范围和步进是多少"    # 预期首位=TS 36.331 a3-Offset 参数卡族（a3-Offset｜a3-Offset-r16，见 _s2_anchor_ok），答案 -30..30 步进 0.5 dB（实际值=字段值×0.5）

# 条款级期望锚集数据档（2026-09-27 S1 重校准：锚集自硬码枚举升为外置数据档；
# 档内含每锚回源三要件引文（数值/主体/款义）+证据块 id+冻结日期，装载校验
# 见 _load_anchor_spec；改集/扩集须用户决策，禁自动生效——refresh_procedure 在档）
ANCHOR_SPEC_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "期望锚集-条款级.json")  # __file__ 相对解析（本机=BASE_DIR 同位；CI 可移植，2026-10-08 smoke 二跑红灯修）

# 装载内存预估闸依赖（排序优化四期 P1 #5，2026-10-03）：峰值预估公式复用
# 建库/scripts/装载预检.py（单点维护、与 retrieve.load_library 入口闸同源）；
# 安全件 import 失败=loud 崩、不静默降级。
_SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "建库", "scripts")  # __file__ 相对解析（本机=BASE_DIR 同位逐字节等价；CI 检出路径可移植，2026-10-08 smoke 首跑红灯修）
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)
import 装载预检  # noqa: E402


class AnchorSpecError(Exception):
    """锚集数据档缺失/非法（--smoke S1/S2 首位锚判定无据可依——loud 失败，
    禁静默回退硬码枚举：静默回退=锚集程序化刷新的整个意义归零）。"""


# ---------------------------------------------------------------------------
# 锚集数据档装载+校验（条款级；_load_anchor_spec + _validate_anchor_spec）
# ---------------------------------------------------------------------------
def _validate_anchor_spec(spec, src):
    """锚集数据档结构校验（非法抛 AnchorSpecError，错误信息带定位）。"""
    def _need(cond, msg):
        if not cond:
            raise AnchorSpecError("锚集数据档非法（%s）：%s" % (src, msg))

    _need(isinstance(spec, dict), "顶层须为对象")
    _need(spec.get("schema_version") == 1, "schema_version 须为 1")
    _need(isinstance(spec.get("frozen_date"), str) and spec["frozen_date"].strip(),
          "frozen_date（冻结日期）须为非空字符串")
    _need(isinstance(spec.get("refresh_procedure"), str) and spec["refresh_procedure"].strip(),
          "refresh_procedure（再验程序指针）须为非空字符串")
    smokes = spec.get("smokes")
    _need(isinstance(smokes, dict) and {"S1", "S2"} <= set(smokes), "smokes 须含 S1/S2 两键")
    for sid in ("S1", "S2"):
        s = smokes[sid]
        _need(isinstance(s, dict), "%s 须为对象" % sid)
        _need(isinstance(s.get("question"), str) and s["question"].strip(),
              "%s question 须为非空字符串" % sid)
        docs = s.get("doc_id_any")
        _need(isinstance(docs, list) and docs
              and all(isinstance(t, str) and t.strip() for t in docs),
              "%s doc_id_any 须为非空字符串数组" % sid)
        for key in ("answer_pattern", "answer_pattern2"):
            pat = s.get(key)
            if key == "answer_pattern":
                _need(isinstance(pat, str) and pat.strip(), "%s answer_pattern 须为非空正则串" % sid)
            elif pat is None:
                continue
            _need(isinstance(pat, str) and pat.strip(), "%s %s 须为非空正则串或缺省" % (sid, key))
            try:
                re.compile(pat)
            except re.error as e:
                raise AnchorSpecError("锚集数据档非法（%s）：%s %s 正则不可编译：%s（%s）"
                                      % (src, sid, key, pat, e))
        anchors = s.get("anchors")
        _need(isinstance(anchors, list) and anchors, "%s anchors 须为非空数组" % sid)
        for i, a in enumerate(anchors, 1):
            where = "%s 锚#%d" % (sid, i)
            _need(isinstance(a, dict), "%s 须为对象" % where)
            _need(isinstance(a.get("anchor_id"), str) and a["anchor_id"].strip(),
                  "%s anchor_id 须为非空字符串" % where)
            rx = a.get("locator_regex")
            _need(isinstance(rx, str) and rx.strip(), "%s locator_regex 须为非空正则串" % where)
            try:
                re.compile(rx)
            except re.error as e:
                raise AnchorSpecError("锚集数据档非法（%s）：%s locator_regex 不可编译：%s（%s）"
                                      % (src, where, rx, e))
            contains = a.get("locator_contains")
            _need(isinstance(contains, list) and all(isinstance(t, str) for t in contains),
                  "%s locator_contains 须为字符串数组" % where)
            ev = a.get("evidence_blocks")
            _need(isinstance(ev, list) and ev
                  and all(isinstance(e, dict) and isinstance(e.get("chunk_id"), str)
                          and e["chunk_id"].strip() for e in ev),
                  "%s evidence_blocks 须为非空数组且逐块含 chunk_id" % where)
            req = a.get("requirements")
            _need(isinstance(req, dict)
                  and all(isinstance(req.get(k), str) and req.get(k, "").strip()
                          for k in ("数值", "主体", "款义")),
                  "%s requirements 须含非空三要件引文（数值/主体/款义）" % where)
    return spec


_ANCHOR_SPEC_CACHE = {}


def _load_anchor_spec(path=None):
    """锚集数据档装载（默认 ANCHOR_SPEC_FILE；path 供测试注入）→ 校验后的 spec。

    缺失/JSON 坏/结构非法一律抛 AnchorSpecError（调用方 loud 处置，不静默）。
    默认路径结果缓存（单次进程一次读盘）；path 注入路径不进缓存（测试隔离）。"""
    if path is None and "spec" in _ANCHOR_SPEC_CACHE:
        return _ANCHOR_SPEC_CACHE["spec"]
    p = path or ANCHOR_SPEC_FILE
    try:
        with open(p, encoding="utf-8") as f:
            spec = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise AnchorSpecError("锚集数据档读取失败：%s（%s）" % (type(e).__name__, os.path.basename(p)))
    _validate_anchor_spec(spec, os.path.basename(p))
    if path is None:
        _ANCHOR_SPEC_CACHE["spec"] = spec
    return spec


def _smoke_anchor_ok(smoke_id, loc, spec=None):
    """合格锚集通用判定：smoke_id（S1/S2）任一锚命中即过。

    锚命中 = locator_contains 全部子串在 + locator_regex 命中（锚间 OR、
    锚内 AND）——款号边界（`(?![.\\d])`）由档内正则自带，子款串号不认。"""
    spec = spec or _load_anchor_spec()
    loc = str(loc or "")
    return any(all(s in loc for s in a["locator_contains"])
               and re.search(a["locator_regex"], loc)
               for a in spec["smokes"][smoke_id]["anchors"])


def _s1_anchor_ok(loc):
    """S1 首位锚合格集（条款级数据档驱动）：附录2 2.2.4（原锚）或 附录4 4.2.2
    （语料演化型新锚）——锚集与三要件引文见 期望锚集-条款级.json（冻结
    2026-09-27；回源全扫=建库/work/S1S2锚集回源全扫-20260927.py，幂等重跑）。

    两锚均已回源验证同证「通话中断率（掉话率）≤5％」（运营/合并轮-20260925.md
    §五裁定+运营/迭代轮-20260926.md 回源复核；2026-09-27 三要件全扫复证=2 锚，
    附录4 主体=国内IP电话业务已在档内 subject_note 如实登记）。两者 RRF 融合
    分差为 1e-5~1e-4 量级（tie-break 抖动带）：库态（44,792→44,881 多轮换血）
    与 mq 开关态都会造成首位互换（09-25 云端 mq 开=附录4 居首；09-26 本机
    mq 关=附录2 居首；2026-09-27 双库×双态离线矩阵复证，实测在档）——首位
    断言按集合判定，防 1e-5 级抖动误报（S1 曾因此 6/7 误 FAIL）。款号带边界
    （`(?![.\\d])`，档内正则自带）：2.2.44/4.2.2.9 一类子款串号不认。"""
    return _smoke_anchor_ok("S1", loc)


def _s2_anchor_ok(loc):
    """S2 首位锚合格集（2026-09-27 S1 重校准同法扩展，W3 处置）：TS 36.331
    a3-Offset 参数卡族——a3-Offset（原锚）或 a3-Offset-r16（同 IE 同款
    clause 5.5.4.2 的 Rel-16 扩展卡，取值域 INTEGER -30..30 同证，证据块
    id 在档）。两卡同族 tie 翻转按集合吸收（S1 同机理预防，未爆发先设防）。"""
    return _smoke_anchor_ok("S2", loc)

# 对云端执行的命令（全部只读；报告头会原样列出，$CLOUD 为脱敏占位）
CMD_IS_ACTIVE = "systemctl is-active %s" % UNIT
# ② 库行数对照取数（2026-10-15 换库窗②收口修）：sidecar meta count 为准
# （行式 embeddings.jsonl 未随换库更新=行式同步债已知界，wc -l 只作 sidecar
# 缺席时回退）。输出形如 STORE_COUNT=62512（回退形 STORE_COUNT=wc:62461）。
# 本命令不做外层 % 格式化（python -c 体内 %s 为远端占位原样传，同
# CMD_SOURCETIER/CMD_RERANKCFG 口径），路径经字符串拼接注入。
CMD_STORECOUNT = (
    "python3 -c 'import json,os\n"
    "_m=\"" + CLOUD_DIR + "/" + STORE_REL + ".f32.meta.json\"\n"
    "_l=\"" + CLOUD_DIR + "/" + STORE_REL + "\"\n"
    "print(\"STORE_COUNT=%s\"%(json.load(open(_m))[\"count\"] if os.path.exists(_m) else \"wc:\"+str(sum(1 for _ in open(_l)))))'"
)
# ⑦ 一条只读往返取云端 MemAvailable（/proc/meminfo，单位 kB）与库镜像形态
# （2026-10-26 估算面现代化：行式 stat size → bin 镜像口径 MC/MD/MB/MM
# =count/dim/f32.bin/meta.json 字节，校验契约与 rag._try_load_sidecar 同源
# 〔version/源 size+mtime 过期校验/bin 长度=count×dim×4〕；镜像缺席/过期/坏
# =LS 行式件字节数回退=二级；__SZ__ 分隔符分段）。本命令不做外层 % 格式化
# （python3 -c 体内 %d 为远端占位原样传，同 CMD_STORECOUNT 口径），路径经
# 字符串拼接注入。
CMD_MEMPRE = (
    "awk '/^MemAvailable/ {print $2}' /proc/meminfo; echo __SZ__; "
    "python3 -c 'import json,os\n"
    "_b=\"" + CLOUD_DIR + "/" + STORE_REL + ".f32.bin\"\n"
    "_m=\"" + CLOUD_DIR + "/" + STORE_REL + ".f32.meta.json\"\n"
    "_l=\"" + CLOUD_DIR + "/" + STORE_REL + "\"\n"
    "try:\n"
    " _d=json.load(open(_m));_c,_i=_d[\"count\"],_d[\"dim\"];_s=os.stat(_l)\n"
    " assert os.path.getsize(_b)==_c*_i*4 and _d.get(\"src_size\")==_s.st_size and _d.get(\"src_mtime_ns\")==_s.st_mtime_ns\n"
    " print(\"MC=%d\"%_c);print(\"MD=%d\"%_i);print(\"MB=%d\"%os.path.getsize(_b));print(\"MM=%d\"%os.path.getsize(_m))\n"
    "except Exception:\n"
    " print(\"LS=%d\"%os.path.getsize(_l))'"
)
CMD_HEALTH = "curl -s --max-time 10 -w '\\n%%{http_code}' %s" % HEALTH_URL
CMD_JOURNAL = (
    "journalctl -u %(u)s --no-pager -o cat | grep -E "
    "'^\\[startup\\]|^\\[rag-store\\]|^\\[rag-bm25\\]|^\\[rag-hybrid\\]|^\\[rag\\] warn' | tail -n 40; "
    "echo __CHAT__; "
    "journalctl -u %(u)s _SYSTEMD_INVOCATION_ID=$(systemctl show -p InvocationID --value %(u)s) "
    "--no-pager -o cat | grep -E '^\\[chat\\]|^\\[rag-embed\\]' | tail -n 20; "
    "echo __RERANK__; "
    "journalctl -u %(u)s --no-pager -o cat | grep -E '^\\[rerank_probe\\]|^\\[rerank_gate\\]' | tail -n 20"
) % {"u": UNIT}
# 说明：比验收单"最近 50 行"更稳的取法——journalctl 全量 grep 后 tail
# （服务重启已久、50 行窗口已滚没 startup 行时仍能核到最近一次启动态；输出有界）。
# 第二段按 InvocationID 只取当前服务进程的行——restart 后旧进程的 [chat] 行不再污染打点三规则抽验
# （2026-09-19 上云验收实测踩坑：全历史 tail 混入旧版无打点行，误报"打点形态异常"）。
# 第三段 __RERANK__（2026-10-12 合围工程基建一期 2-C）：[rerank_probe]/[rerank_gate]
# 行独立取数段（全历史 tail 20，同首段口径）——不并入首段 grep 是防 probe 行随流量
# 增长挤占首段 tail -n 40 窗口（滚没 [startup] 行=②⑧ 伪红）；split_journal 与
# parse_* 既有解析零改动（第三段行落入 run 段尾部，parse_chat_line 只认 rag= 子串
# 不误吞，⑩ 自行按前缀过滤取用）。
CMD_SOURCETIER = (
    "cd /opt/qa-bot && python3 -c "
    "'import json,os\n"
    "_p=\"data/source-tier.json\"\n"
    "print(\"ST_EXISTS=%d\"%os.path.exists(_p))\n"
    "_d=json.load(open(_p)) if os.path.exists(_p) else {}\n"
    "print(\"ST_RULES=%d\"%len(_d.get(\"rules\") or {}))'"
)
# 只读核验云端数据件：存在性 + json.load 可解析 + rules 键计数呈现（结构深校验
# 归 E1/E3 泳道单测职责，本项只锚"在位且可解析"）；输出仅 ST_* 标记行，零密值。
# 注：本命令不做 % 格式化（无 %%s/%%d 转义需求），单 % 字面量原样传远端。
CMD_RERANKCFG = (
    "cd /opt/qa-bot && python3 -c "
    "'import json\n"
    "_c=json.load(open(\"config.json\"))\n"
    "print(\"rerank_log_enabled=%s\"%_c.get(\"rerank_log_enabled\",\"<absent=true>\"))\n"
    "print(\"rerank_refusal_enabled=%s\"%_c.get(\"rerank_refusal_enabled\",\"<absent=false>\"))'"
)
# 只读呈现 config 顶层 rerank 两键现值（⑧ 交叉对照+⑩ 本体）：单键打印，
# config 其他键（passcode 等）绝不回显。
# ⑪ SLA 观测机读档取数（2026-10-14 产品维度升级收口 §三/§10）：ls -1 按名排序
# 取最新+次新（文件名 obs-latency-自动-YYYYMMDD，字典序即时间序），cat 最新一档；
# __OBSLAT__ 分隔 listing 与 json 两段。json 字段=度量面（§10 冻结 schema），
# 无 IP/口令/key，零密值；末尾 true 兜 rc=0（无档时 [ -n "$f" ] 短路亦不报错）。
CMD_OBS_SLA = (
    "ls -1 /opt/qa-bot/建库/logs/obs-latency-自动-*.json 2>/dev/null | sort | tail -n 2; "
    "echo __OBSLAT__; "
    "f=$(ls -1 /opt/qa-bot/建库/logs/obs-latency-自动-*.json 2>/dev/null | sort | tail -n 1); "
    '[ -n "$f" ] && cat "$f"; true'
)
# ⑫ 嵌入预算三键取数（§三/§五/§10）：远端 python3 只提取并打印 config rag 段
# 预算三键——**绝不 cat 整个 config.json（含密件）**，输出仅三行 key=value
# （数值面非密值）。注：本命令不做 % 格式化（无外层 % 消费），python -c 体内
# 的 %s/%_r.get 原样传远端（同 CMD_RERANKCFG 口径）；体内只用双引号（外壳
# 单引号串不含单引号）。
CMD_EMBEDBUDGET = (
    "cd /opt/qa-bot && python3 -c "
    "'import json\n"
    "_r=(json.load(open(\"config.json\")).get(\"rag\") or {})\n"
    "print(\"embed_monthly_budget_enabled=%s\"%_r.get(\"embed_monthly_budget_enabled\",\"<absent>\"))\n"
    "print(\"embed_monthly_budget_cny=%s\"%_r.get(\"embed_monthly_budget_cny\",\"<absent>\"))\n"
    "print(\"embed_monthly_cap_cny=%s\"%_r.get(\"embed_monthly_cap_cny\",\"<absent>\"))'"
)
# ⑫ 期望值（2026-10-14 产品维度升级收口 §五 拨键口径：enabled=true/
# budget=40.0=预警线/cap=50.0=熔断线；语义与台账总治理线〔过程日志 36① 累计 50
# 元〕分账——两管线闸=机械执行面，合计可超单闸=已知界，周报合计监督行兜底；
# 后续调线改此一处即可，禁自动生效）。
EMBED_BUDGET_EXPECT = {
    "embed_monthly_budget_enabled": True,
    "embed_monthly_budget_cny": 40.0,
    "embed_monthly_cap_cny": 50.0,
}
CMD_SMOKE_CURL = "curl -sN --max-time 120 -H 'Content-Type: application/json' --data-binary @- %s" % CHAT_URL

# ---------- 脱敏 ----------
# IPv4 与点分条款号豁免（2026-09-23 修：答案文本里点分条款号如"规范第 5.5.4.7 节"
# 曾被误判 IPv4 打成 <IP>——实证 运营/部署核验-20260923-1012.md S2"规范第 <IP>"）。
# 安全优先、宁可多遮不可漏遮，豁免仅两路：
#   ① 5 段以上点分链（如 5.5.4.7.1）——天然非 IPv4，整链豁免（旧行为还会把
#      前 4 段遮掉留"<IP>.1"残尾）；
#   ② 明确条款语境词紧邻前置（第/节/条款/章节/附录/规范/规程/§/clause/section/
#      TS/TR，中间容空白或冒号）——有文字语境信号才豁免。
#   歧义形态（无前缀裸点分四段）一律仍遮——宁可对无语境条款号误遮，不漏真 IP。
# 已知取舍：真 IP 若恰好紧跟条款前置词（如"第 8.8.8.8"）会被豁免；日志/答案
# 语境里该组合几乎不出现，裸形态真 IP（ip= 打点、ssh 回显等）不受影响。
# 边界说明：前后界沿用旧 \b 语义（(?<!\w)/(?!\w)）另加点链守卫（(?<!\d\.)/
# (?!\.\d)）——链守卫只挡"数字.数字"续接（链中段起匹配/链尾续段），普通点号
# 贴邻（如句点后"end.203.0.113.9"）照遮不误，与旧行为一致；数字紧贴中文
# （如"见5.5.4.7"）新旧皆不匹配（中文属 \w），非本次引入。
_RE_CHAIN5 = re.compile(r"(?<!\w)(?<!\d\.)\d{1,3}(?:\.\d{1,3}){4,}(?!\w|\.\d)")
_RE_CLAUSE = re.compile(
    r"(?:第|节|条款|章节|附录|规范|规程|§"
    r"|(?<![A-Za-z])[Cc]lauses?|(?<![A-Za-z])[Ss]ections?|(?<![A-Za-z])TS|(?<![A-Za-z])TR)"
    r"\s*[:：]?\s*"
    r"\d{1,3}(?:\.\d{1,3}){3}(?!\w|\.\d)")
_RE_IP4 = re.compile(r"(?<!\w)(?<!\d\.)\d{1,3}(?:\.\d{1,3}){3}(?!\w|\.\d)")
_RE_IPV6A = re.compile(r"\b(?:[0-9A-Fa-f]{1,4}:){3,}[0-9A-Fa-f]{0,4}\b")
_RE_IPV6B = re.compile(r"\b[0-9A-Fa-f]{1,4}(?::[0-9A-Fa-f]{0,4}){0,3}::[0-9A-Fa-f:]*\b")
_RE_AT = re.compile(r"\b[A-Za-z0-9_.-]+@[A-Za-z0-9_.:-]+\b")
_RE_KEY = re.compile(r"\bsk-[A-Za-z0-9_-]{6,}\b")
_RE_BEARER = re.compile(r"Bearer\s+\S+")
_RE_PASSCODE = re.compile(r"(passcode|api_key|token)([\"'=:\s]+)\S+", re.I)


def sanitize(text):
    """证据/输出统一脱敏：IPv4/IPv6/用户@主机/key/Bearer/passcode 值。
    回环地址（127.0.0.1/::1/localhost）非密值，豁免（否则命令回显不可读）。
    点分条款号豁免（2026-09-23）：条款语境紧邻前置（第/§/clause/TS/TR/规范…）
    的点分四段、及 5 段以上点分链原样保留；其余点分四段一律遮 <IP>——
    安全优先，宁可多遮不可漏遮（取舍详见 _RE_CHAIN5/_RE_CLAUSE 注释）。"""
    if not text:
        return text
    s = str(text)
    s = s.replace("127.0.0.1", "\x00LO\x00").replace("localhost", "\x00LH\x00")
    s = re.sub(r"(?<![\w:])::1(?![\w:])", "\x00L1\x00", s)  # 仅豁免独立 ::1（防 IPv6 尾段误豁免）
    # 条款号豁免：先用占位符持有（同回环地址豁免手法），全部脱敏后再还原——
    # 还原晚于各脱敏 sub，被豁免片段不会二次入判；占位符若被 Bearer/passcode
    # 类 \S+ 吞掉则持有值随之脱敏（只会多遮不会漏遮）。
    held = []

    def _hold(m):
        held.append(m.group(0))
        return "\x00H%d\x00" % (len(held) - 1)

    s = _RE_CHAIN5.sub(_hold, s)   # 5 段以上点分链：天然非 IPv4
    s = _RE_CLAUSE.sub(_hold, s)   # 条款语境紧邻前置的点分四段
    s = _RE_IPV6B.sub("<IPv6>", s)   # 先匹配含 :: 的压缩形态（防无::形态截尾留残）
    s = _RE_IPV6A.sub("<IPv6>", s)
    s = _RE_IP4.sub("<IP>", s)
    s = _RE_AT.sub("<用户@主机>", s)
    s = _RE_KEY.sub("<KEY>", s)
    s = _RE_BEARER.sub("Bearer <TOKEN>", s)
    s = _RE_PASSCODE.sub(r"\1\2<已脱敏>", s)
    for i, v in enumerate(held):
        s = s.replace("\x00H%d\x00" % i, v)
    s = s.replace("\x00LO\x00", "127.0.0.1").replace("\x00LH\x00", "localhost").replace("\x00L1\x00", "::1")
    return s


# ---------- 报告收集 ----------
class Report:
    def __init__(self):
        self.lines = []
        self.results = []  # (编号, 标题, 状态, 证据[], 提示[])

    def say(self, text=""):
        line = sanitize(text)
        print(line)
        self.lines.append(line)

    def add(self, num, title, status, evidence=(), hints=()):
        self.results.append((num, title, status, [sanitize(e) for e in evidence],
                             [sanitize(h) for h in hints]))
        self.say("## %s %s — %s" % (num, title, status))
        for e in evidence:
            self.say("证据: " + sanitize(e))
        for h in hints:
            self.say("提示: " + sanitize(h))
        self.say()

    def has_fail(self):
        return any(r[2] == "FAIL" for r in self.results)

    def dump_markdown(self, header=None):
        """落盘报告组装（2026-10-15 小修：header 缺省化——此前 main 里 header 已
        经 rep.say 入 lines，dump 再拼一遍致落盘报告头双写，见 部署核验-
        20261015-0002 头两段重复实例；现 header 仅在显式传入时拼装）。"""
        out = [sanitize(line) for line in (header or [])]
        if out:
            out.append("")
        out.extend(self.lines)
        out.append("—— 由 deploy_check.py 生成；本报告零密值（IP/口令/key 均脱敏形态）。")
        return "\n".join(out) + "\n"


# ---------- SSH 目标解析（只读，不回显） ----------
def resolve_ssh_target():
    """从 运维私密-20260916.md 解析 SSH 登录目标行（形如 `ssh -i <身份密钥> user@host`）。
    只读解析；返回 (身份密钥绝对路径, 登录目标) 或 (None, 错误说明)。绝不打印目标实值。"""
    try:
        with open(SECRET_FILE, encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        return None, "读运维私密档失败: %s（%s）" % (type(e).__name__, os.path.basename(SECRET_FILE))
    for line in text.splitlines():
        if "ssh" in line and " -i " in line:
            m = re.search(r"ssh\s+-i\s+(\S+)\s+([A-Za-z0-9._@:\[\]-]+)", line)  # 目标限合法主机字符集，防吞行尾中文说明
            if m:
                ident = os.path.expanduser(m.group(1).strip("`\"'"))
                target = m.group(2).strip("`\"'")
                if "@" in target and "/" not in target:
                    return (ident, target), None
    return None, "运维私密档中未找到 ssh -i <密钥> user@host 形态的登录行"


class Cloud:
    """云端命令执行层：真跑=ssh 只读命令；--dry-run=内置样例（不连云端）。"""

    def __init__(self, ssh_args=None, scenario=None, offline=False):
        self.ssh_args = ssh_args
        self.scenario = scenario
        self.offline = offline

    def run(self, cmd, timeout=60, stdin_data=None):
        """→ (rc, stdout, stderr)；异常统一折成 rc=999 + err 文本。"""
        if self.ssh_args is None:  # dry-run
            return self._fixture(cmd, stdin_data)
        try:
            p = subprocess.run(
                self.ssh_args + [cmd], input=stdin_data, text=True,
                encoding="utf-8", errors="replace",
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
            return p.returncode, p.stdout, p.stderr
        except subprocess.TimeoutExpired:
            return 999, "", "SSH 命令超时（>%ss）" % timeout
        except OSError as e:
            return 999, "", "SSH 执行失败: %s" % type(e).__name__

    # ---- 内置样例（仅 --dry-run 用；IP 用文档段示例值，输出仍会脱敏） ----
    def _fixture(self, cmd, stdin_data):
        if self.offline:
            return 255, "", "ssh: connect to host root@203.0.113.9 port 22: Connection timed out"
        fx = FIXTURES[self.scenario]
        if "systemctl is-active" in cmd:
            return fx["systemctl"]
        if "/api/health" in cmd:
            return fx["health"]
        if "STORE_COUNT" in cmd:     # ② 库行数对照取数（CMD_STORECOUNT，2026-10-15）
            return fx["storecount"]
        if "MemAvailable" in cmd:      # ⑦ 装载内存预估闸取数（CMD_MEMPRE）
            return fx["mempre"]
        if "ST_EXISTS" in cmd:         # ⑨ SOURCE_TIER 数据件取数（CMD_SOURCETIER）
            return fx["sourcetier"]
        if "rerank_refusal_enabled" in cmd:   # ⑩ 行为键取数（CMD_RERANKCFG）
            return fx["rerankcfg"]
        if "obs-latency-自动" in cmd:          # ⑪ SLA 机读档取数（CMD_OBS_SLA）
            return fx["obslat"]
        if "embed_monthly_budget_enabled" in cmd:  # ⑫ 预算三键取数（CMD_EMBEDBUDGET）
            return fx["embedbudget"]
        if "journalctl" in cmd:
            return fx["journal"]
        if "/api/chat" in cmd:
            key = "smoke_q1" if "掉话率" in (stdin_data or "") else "smoke_q2"
            return fx[key]
        return 0, "", ""


# 样例 loaded/docs/storecount 数字=本机现行库口径对齐值（2026-10-26 估算面
# 现代化随锚面卡批1换库窗终态同步：82232〔前值 62,512=换库窗② 2026-10-15
# 口径，更前 66357 系 2026-10-07 A2 对齐值〕）；后续再换库漂移时同步此值即可。
# oldver 场景 14055=旧库口径，其 FAIL 语义（仍旧版判读）原样保留。storecount
# 样例=sidecar count 口径（非 wc 回退形）。mempre 样例=⑦ 镜像口径形（MC/MD/
# MB/MM，数字=82232 现产真形）；oldver=LS 行式回落形（二级自测）。
_J_OK_STARTUP = """[rag-store] loaded=82232 bad_lines=0 dim=1024
[rag-bm25] build docs=82232 terms=48213 postings=310422 avgdl=87.3 arr_mb=15.4 dur=1.02s
[startup] model=qwen3.7-max passcode=on
[startup] rag=on loaded=82232 bad_lines=0 dim=1024
[startup] rerank_log=on cap=5cny
[rag-hybrid] mode=rrf cos_n=20 bm25_n=20 hits=5 ; #1 信息产业部令第36号|附录2 2.2.4 通话中断率（掉话率）|ch=cos+bm25|cos=0.8494|bm25=11.23|fused=0.03122"""

# 样例=批2 现行打点形态（ip= 与 in_chars= 之间带 auth=，尾附 ttfb=/cancelled=/cc=/ab=）；
# 末行故意保留批1 旧形态（无 auth=）——混合形态自测 parse_chat_line 字段序无关
# （2026-09-22 low_score 教识销账：三规则判定只锚 rag=/q=/top1= 子串，加字段不得打断）。
# 2026-10-01 观测面升级：补 coverage_miss 态行（带 q=/top1=，与 hit/low_score 同
# 规则）与 hit 行尾 rt= 键（期1 路由开态形态）——dry-run 自测新教识。
_J_OK_CHAT = """[rag-embed] chars=19 tokens=12 ok=1 dim=1024 dur=0.21s
[chat] ip=203.0.113.9 auth=body in_chars=19 rag=hit ttfb=1.1s dur=4.8s usage={'prompt_tokens': 810, 'completion_tokens': 42} cancelled=0 q="电信服务规范规定的掉话率监管红线是多少" top1=0.8494 cc=off ab=off rt=concept:d
[rag-embed] chars=18 tokens=11 ok=1 dim=1024 dur=0.19s
[chat] ip=203.0.113.9 auth=cookie in_chars=18 rag=low_score ttfb=1.3s dur=3.9s usage={'prompt_tokens': 300, 'completion_tokens': 20} cancelled=0 q="附近有什么好吃的餐厅" top1=0.3123 cc=off ab=off
[rag-embed] chars=31 tokens=18 ok=1 dim=1024 dur=0.14s
[chat] ip=203.0.113.9 auth=cookie in_chars=31 rag=coverage_miss ttfb=1.3s dur=2.1s usage={'total_tokens': 900} cancelled=0 q="卫星 NTN 的馈电链路怎么走" top1=0.5123 cc=off ab=off rt=concept:f
[chat] ip=203.0.113.9 in_chars=18 rag=hit dur=4.2s usage={'prompt_tokens': 790, 'completion_tokens': 38} q="切换参数 a3-Offset 的取值范围和步进是多少" top1=0.8123"""

_J_OKOFF_STARTUP = """[rag-store] loaded=82232 bad_lines=0 dim=1024
[startup] model=qwen3.7-max passcode=on
[startup] rag=on loaded=82232 bad_lines=0 dim=1024
[startup] rerank_log=on cap=5cny"""

_J_OLDVER_STARTUP = """[rag-store] loaded=14055 bad_lines=0 dim=1024
[startup] model=qwen3.7-max passcode=on
[startup] rag=on loaded=14055 bad_lines=0 dim=1024"""

# __RERANK__ 第三段样例（2026-10-12 2-C）：探针 armed 态的 probe fire 行 +
# gate pass 行（rerank_refusal 键关态下 gate 行=历史残留语义，⑩ 只呈现不判红；
# oldver 场景 journal 无此段=有意，"未部署新版"判读语义原样保留）
_J_OK_RERANK = """[rerank_probe] ts=2026-10-12 09:00:00 q=ab12cd34ef56 st=hit trace=84bc4e58 n=50 max=0.8494 c075=2 c085=1 c095=0 tok=1234 cny=0.001234 gold=na
[rerank_gate] ts=2026-10-12 09:00:01 q=ab12cd34ef56 trace=84bc4e58 decision=pass max=0.8494 thr=0.75"""

_J_OLDVER_CHAT = """[chat] ip=203.0.113.9 in_chars=19 rag=hit dur=7.1s usage={'prompt_tokens': 810, 'completion_tokens': 42}"""

_SSE_Q1 = (
    'data: {"sources": [{"doc_id": "信息产业部令第36号", "version": "2005", '
    '"locator": "附录2 2.2.4 通话中断率（掉话率） 款1", "score": 0.8494}, '
    '{"doc_id": "信息产业部令第36号", "version": "2005", "locator": "附录2 2.2 数字蜂窝移动通信业务的通信质量标准", "score": 0.8122}]}\n\n'
    'data: {"delta": "根据《电信服务规范》（原信息产业部令第36号）附录2 2.2.4，数字蜂窝'
    '移动通信业务的通话中断率（掉话率）应不超过5%。"}\n\n'
    'data: {"done": true, "usage": {"prompt_tokens": 810, "completion_tokens": 42, "total_tokens": 852}}\n\n'
)
_SSE_Q2 = (
    'data: {"sources": [{"doc_id": "TS 36.331", "version": "", "locator": "a3-Offset", "score": 0.8261}, '
    '{"doc_id": "TS 36.331", "version": "", "locator": "a3-Offset-r16", "score": 0.8013}]}\n\n'
    'data: {"delta": "a3-Offset 的取值范围为 -30 到 30，步进为 2；该参数属 TS 36.331 '
    'reportConfigEUTRA 报告配置（参数卡口径）。"}\n\n'
    'data: {"done": true, "usage": {"prompt_tokens": 790, "completion_tokens": 38, "total_tokens": 828}}\n\n'
)

# ⑪⑫ fixture（2026-10-14 收口 §三）：ok/ok-off/oldver 三场景的部署窗预期
# 基线=obs 脚本刚上云首窗未跑（无档 → 观测未起 INFO）；⑫ ok/ok-off=拨键达成
# 三键行（True/40.0/50.0），oldver=旧版 config 无预算键（三 absent）。⑫ fixture
# 与真命令同纪律：只含三键行，绝不带 config 其他键（密件纪律）。
_FX_OBSLAT_NOTSTARTED = (0, "__OBSLAT__\n", "")
_FX_EMBEDBUDGET_OK = (0, "embed_monthly_budget_enabled=True\n"
                        "embed_monthly_budget_cny=40.0\n"
                        "embed_monthly_cap_cny=50.0\n", "")
_FX_EMBEDBUDGET_ABSENT = (0, "embed_monthly_budget_enabled=<absent>\n"
                             "embed_monthly_budget_cny=<absent>\n"
                             "embed_monthly_cap_cny=<absent>\n", "")

FIXTURES = {
    "ok": {  # 新版全量：hybrid 开 + 新库 + 打点在
        "systemctl": (0, "active\n", ""),
        "health": (0, '{"ok":true,"model":"qwen3.7-max","bot_name":"AI 助手","has_key":true}\n200\n', ""),
        "storecount": (0, "STORE_COUNT=82232\n", ""),
        "journal": (0, _J_OK_STARTUP + "\n__CHAT__\n" + _J_OK_CHAT
                    + "\n__RERANK__\n" + _J_OK_RERANK, ""),
        "smoke_q1": (0, _SSE_Q1, ""),
        "smoke_q2": (0, _SSE_Q2, ""),
        "mempre": (0, "16200000\n__SZ__\nMC=82232\nMD=1024\nMB=336822272\nMM=122211835\n", ""),
        "sourcetier": (0, "ST_EXISTS=1\nST_RULES=4\n", ""),
        "rerankcfg": (0, "rerank_log_enabled=<absent=true>\nrerank_refusal_enabled=<absent=false>\n", ""),
        "obslat": _FX_OBSLAT_NOTSTARTED,
        "embedbudget": _FX_EMBEDBUDGET_OK,
    },
    "ok-off": {  # 新版、hybrid 未启用
        "systemctl": (0, "active\n", ""),
        "health": (0, '{"ok":true,"model":"qwen3.7-max","bot_name":"AI 助手","has_key":true}\n200\n', ""),
        "storecount": (0, "STORE_COUNT=82232\n", ""),
        "journal": (0, _J_OKOFF_STARTUP + "\n__CHAT__\n" + _J_OK_CHAT
                    + "\n__RERANK__\n" + _J_OK_RERANK, ""),
        "smoke_q1": (0, _SSE_Q1, ""),
        "smoke_q2": (0, _SSE_Q2, ""),
        "mempre": (0, "16200000\n__SZ__\nMC=82232\nMD=1024\nMB=336822272\nMM=122211835\n", ""),
        "sourcetier": (0, "ST_EXISTS=1\nST_RULES=4\n", ""),
        "rerankcfg": (0, "rerank_log_enabled=<absent=true>\nrerank_refusal_enabled=<absent=false>\n", ""),
        "obslat": _FX_OBSLAT_NOTSTARTED,
        "embedbudget": _FX_EMBEDBUDGET_OK,
    },
    "oldver": {  # 云端仍旧版：旧 server.py（无 q=/top1=）+ 旧库 14055（无 rerank
        # 面行/数据件/config 键——⑧⑨"未部署新版"判读、⑩ 键缺省关态，均有意；
        # ⑪ 无 obs 机读档=观测未起、⑫ 旧 config 无预算键=缺键 WARN，均有意）
        "systemctl": (0, "active\n", ""),
        "health": (0, '{"ok":true,"model":"qwen3.7-max","bot_name":"AI 助手","has_key":true}\n200\n', ""),
        "storecount": (0, "STORE_COUNT=14055\n", ""),
        "journal": (0, _J_OLDVER_STARTUP + "\n__CHAT__\n" + _J_OLDVER_CHAT, ""),
        "smoke_q1": (0, _SSE_Q1, ""),
        "smoke_q2": (0, _SSE_Q2, ""),
        "mempre": (0, "16200000\n__SZ__\nLS=1322357108\n", ""),
        "sourcetier": (0, "ST_EXISTS=0\n", ""),
        "rerankcfg": (0, "rerank_log_enabled=<absent=true>\nrerank_refusal_enabled=<absent=false>\n", ""),
        "obslat": _FX_OBSLAT_NOTSTARTED,
        "embedbudget": _FX_EMBEDBUDGET_ABSENT,
    },
}


# ---------- journal 解析 ----------
def split_journal(out):
    """一条 SSH 往返的合成输出 → (启动类行[], 运行行[chat/rag-embed])"""
    parts = out.split("__CHAT__")
    boot = [line for line in parts[0].splitlines() if line.strip()]
    run = [line for line in (parts[1] if len(parts) > 1 else "").splitlines() if line.strip()]
    return boot, run


def current_boot(boot_lines):
    """启动类行 → (最近一次 [startup] rag= 行在段内的下标, 当前启动段行列表)。
    当前启动段 = 上一次 [startup] rag= 行之后到结尾（含本次 rag-store/bm25/启动行与其后的运行行）。
    返回的下标相对"段"而非全列表（调用方一律拿段使用）。"""
    idxs = [i for i, line in enumerate(boot_lines) if "[startup] rag=" in line]
    if not idxs:
        return None, []
    last = idxs[-1]
    start = idxs[-2] + 1 if len(idxs) >= 2 else 0
    return last - start, boot_lines[start:]


def parse_startup_line(line):
    m = re.search(r"\[startup\] rag=(on|off)", line)
    if not m:
        return None
    d = {"rag": m.group(1)}
    for k, pat in (("loaded", r"loaded=(\d+)"), ("bad_lines", r"bad_lines=(\d+)"),
                   ("dim", r"dim=(\d+)"), ("missing", r"missing=1")):
        mm = re.search(pat, line)
        d[k] = mm.group(1) if mm else None
    return d


def parse_chat_line(line):
    # 2026-10-01 观测面升级：rag= 态并入 coverage_miss（S1 治理丙，服务端实况
    # [chat] rag=coverage_miss 带 q= 与 top1=——与 hit/low_score 同规则分支）；
    # rt= 期1 路由键（route 开态尾附，如 rt=concept:f）解析供核读，缺省 None
    m = re.search(r"\brag=(hit|miss|low_score|coverage_miss|rerank_refused|off)\b", line)
    if not m:
        return None
    rt = re.search(r"\brt=([\w:-]+)\b", line)
    return {
        "rag": m.group(1),
        "q": bool(re.search(r'\bq="[^"]*"', line)),
        "top1": bool(re.search(r"\btop1=(?:na|\d+(?:\.\d+)?)\b", line)),
        "rt": rt.group(1) if rt else None,
        "line": line,
    }


def parse_sse(text):
    """SSE 文本 → {sources, answer, errors, done}"""
    # 2026-10-01 缺口修 B1：非 SSE 的 {"error":...} 纯 JSON 错误体（bad_passcode/
    # auth_expired 等）原被当空流放行（ok=True 空答案零日志，难归因）——现显式计错。
    head = text.lstrip()
    if head.startswith('{"error"'):
        try:
            why = "API 错误体: %s" % json.loads(head.splitlines()[0]).get("error")
        except (json.JSONDecodeError, ValueError, IndexError):
            why = "API 错误体（不可解析）"
        return {"sources": None, "answer": "", "errors": [why], "done": False}
    sources, answer, errors, done = None, "", [], False
    for line in text.splitlines():
        if not line.startswith("data:"):
            continue
        try:
            obj = json.loads(line[5:].strip())
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(obj, dict):
            if obj.get("sources") is not None and sources is None:
                sources = obj["sources"]
            if isinstance(obj.get("delta"), str):
                answer += obj["delta"]
            if "error" in obj:
                errors.append(json.dumps(obj, ensure_ascii=False))
            if obj.get("done"):
                done = True
    return {"sources": sources, "answer": answer, "errors": errors, "done": done}


# ---------- 核对项 ----------
def check_active(rep, cloud):
    rc, out, err = cloud.run(CMD_IS_ACTIVE, timeout=30)
    state = out.strip()
    if rc == 0 and state == "active":
        rep.add("①", "服务活 systemctl is-active qa-bot", "PASS", ["active"])
    else:
        rep.add("①", "服务活 systemctl is-active qa-bot", "FAIL",
                ["is-active 输出=%r rc=%s" % (state or sanitize(err.strip()[:120]), rc)],
                ["判读=服务未运行/单元异常：查 cloud/qa-bot.service 与 systemctl status %s（云端）" % UNIT])
    return rc == 0 and state == "active"


def check_loaded(rep, cloud, expect):
    """② startup 装载行 + 云端库行数对照（sidecar count 口径）+ 登底判读。"""
    rc, out, err = cloud.run(CMD_JOURNAL, timeout=60)
    if rc not in (0,):
        rep.add("②", "startup 装载行", "FAIL",
                ["journalctl 取数失败 rc=%s %s" % (rc, err.strip()[:120])],
                ["判读=取数通道问题而非服务问题：核 SSH 连通与本机 ssh 客户端"])
        return None
    boot, run = split_journal(out)
    last_idx, seg = current_boot(boot)
    if last_idx is None:
        rep.add("②", "startup 装载行", "FAIL", ["journal 无 [startup] rag= 行"],
                ["判读=服务可能从未启动或单元名不符：核 systemd 单元名 %s 与 journalctl -u %s（云端）" % (UNIT, UNIT)])
        return None
    st = parse_startup_line(seg[last_idx])
    store_line = next((line for line in reversed(seg[:last_idx]) if line.startswith("[rag-store]")), None)
    ev = [seg[last_idx]]
    if store_line:
        ev.append(store_line)
    # 云端库行数对照（2026-10-15 换库窗②收口修：sidecar meta count 为准——
    # 行式 embeddings.jsonl 未随换库更新=行式同步债已知界，wc -l 只作 sidecar
    # 缺席回退形；读 94MB meta 约秒级，timeout 放 60）
    sc_rc, sc_out, sc_err = cloud.run(CMD_STORECOUNT, timeout=60)
    store_n, store_src = None, ""
    m_sc = re.search(r"STORE_COUNT=(wc:)?(\d+)", sc_out)
    if sc_rc == 0 and m_sc:
        store_n = int(m_sc.group(2))
        store_src = "行式件 wc（sidecar 缺席回退）" if m_sc.group(1) else "sidecar meta count"
        ev.append("云端库 %s = %d" % (store_src, store_n))
    else:
        ev.append("云端库行数取数失败: %s" % (sc_err.strip()[:80] or sc_out.strip()[:80]))
    if st["rag"] != "on":
        rep.add("②", "startup 装载行", "FAIL", ev,
                ["判读=rag=off：config rag 段未生效（enabled 非 true/段缺失）或处软回滚态——"
                 "若非有意回滚，查 部署-云端升级runbook 步 5 / 上云差异 §八"])
        return {"startup": st, "store": None, "store_count": store_n, "boot_seg": seg, "chat_lines": run}
    hints, ok = [], True
    loaded = int(st["loaded"] or 0)
    if st["missing"]:
        ok = False
        hints.append("missing=1：store_path 不对或库文件未到位（runbook 步 8 判读）")
    if st["bad_lines"] not in (None, "0"):
        ok = False
        hints.append("bad_lines=%s ≠ 0：库存在坏行，查换库文件完整性" % st["bad_lines"])
    if st["dim"] not in (None, "1024"):
        ok = False
        hints.append("dim=%s ≠ 1024：库维度异常" % st["dim"])
    if store_n is not None and store_n != loaded:
        ok = False
        hints.append("装载 loaded=%d 与库行数 %d 不一致（行数口径=%s）：装载不完整/换库后未 restart"
                     "（上云差异 §五步 4）；若系行式件 wc 回退口径不一致，另见行式同步债已知界"
                     "（过程日志 78，下次全量重建收敛）" % (loaded, store_n, store_src))
    # 登底对照（数字打印供人工对照；expect=0 只打印不强校验）
    if expect > 0 and loaded != expect:
        ok = False
        if loaded == OLD_LIB_LINES:
            hints.append("判读=云端仍是旧版向量库（loaded=14055 公开源一期口径）：换库未执行或已硬回滚库"
                         "（上云差异 §五/§八）——属'未升级/回滚态'而非新版异常")
        else:
            hints.append("判读=loaded=%d 与登底 %d 不符：查换库执行单步 8 登底值（若最新交件块数已变，"
                         "--expect-loaded N 按新登底重跑）" % (loaded, expect))
    elif loaded == OLD_LIB_LINES:
        hints.append("注意：loaded=14055=旧库口径（若本次验收目标为新库，即未换库/已回滚）")
    rep.add("②", "startup 装载行（rag=on loaded=<n>，登底对照：旧库=%d 期望=%s）" % (OLD_LIB_LINES, expect or "不强校验"),
            "PASS" if ok else "FAIL", ev, hints)
    return {"startup": st, "store": store_line, "store_count": store_n, "boot_seg": seg, "chat_lines": run}


def check_bm25(rep, jdata, hybrid_off):
    """③ [rag-bm25] build 行（默认档）；--hybrid-off 改核'当前启动后无 bm25/hybrid 行'。"""
    seg = jdata["boot_seg"] if jdata else []
    last_idx = next((i for i, line in enumerate(seg) if "[startup] rag=" in line), None)
    startup_block = seg[:last_idx] if last_idx is not None else seg
    runtime = seg[last_idx + 1:] if last_idx is not None else []
    warn = [line for line in seg if line.startswith("[rag] warn")]
    if hybrid_off:
        bad = [line for line in startup_block + runtime if line.startswith("[rag-bm25]") or line.startswith("[rag-hybrid]")]
        if bad:
            rep.add("③", "hybrid 关态核对（应无 [rag-bm25]/[rag-hybrid] 行）", "FAIL", bad[-2:],
                    ["判读=--hybrid-off 与云端实际不符：云端 config 仍开 hybrid_bm25_enabled 或改键后未 restart；"
                     "若云端确已启用 BM25，去掉 --hybrid-off 重跑"])
        else:
            rep.add("③", "hybrid 关态核对（应无 [rag-bm25]/[rag-hybrid] 行）", "PASS",
                    ["最近一次启动后无 bm25/hybrid 行（与 hybrid 未启用一致）"] + warn)
        return
    build = [line for line in startup_block if line.startswith("[rag-bm25] build docs=")]
    fail = [line for line in startup_block if line.startswith("[rag-bm25] build fail")]
    hybrid_rt = [line for line in runtime if line.startswith("[rag-hybrid]")]
    if fail:
        rep.add("③", "[rag-bm25] build 行（hybrid 启用档）", "FAIL", fail[-1:],
                ["判读=新版已部署但索引构建异常：检索已退单路余弦不断服务，排障后重启重建"
                 "（上云差异 §二注意段）"])
        return
    if not build:
        rep.add("③", "[rag-bm25] build 行（hybrid 启用档）", "FAIL",
                ["最近一次启动段无 [rag-bm25] build 行"],
                ["两种可能：a) 云端尚未启用 BM25（默认关，双卷复验未决策）→ 属'未启用'而非异常，"
                 "用 --hybrid-off 跑降级核对集；b) 已启用但未生效 → 查 config 段 hybrid_bm25_enabled "
                 "与 restart（上云差异 §二启用流程）"])
        return
    line = build[-1]
    m = re.search(r"docs=(\d+)", line)
    loaded = int(jdata["startup"]["loaded"] or 0) if jdata and jdata.get("startup") else None
    ev = [line] + (hybrid_rt[-1:] or [])
    hints = list(warn)
    if warn:
        hints.append("hybrid 与 lexical_boost 同开=纪律二选一（上云差异 §二注意段）")
    ok = True
    if m and loaded is not None and int(m.group(1)) != loaded:
        ok = False
        hints.append("build docs=%s 与 startup loaded=%d 不一致：索引非当前库所建（restart 未跟上换库？）" % (m.group(1), loaded))
    extra = "（[rag-hybrid] 运行行已出现）" if hybrid_rt else "（[rag-hybrid] 运行行暂无=尚无检索流量，--smoke 或发一问后复核）"
    rep.add("③", "[rag-bm25] build 行（hybrid 启用档）" + extra, "PASS" if ok else "FAIL", ev, hints)


def check_health(rep, cloud):
    rc, out, err = cloud.run(CMD_HEALTH, timeout=30)
    lines = [line for line in out.splitlines() if line.strip()]
    code = lines[-1].strip() if lines else ""
    body = "\n".join(lines[:-1]) if len(lines) > 1 else ""
    ok_body = False
    try:
        ok_body = bool(json.loads(body).get("ok"))
    except (json.JSONDecodeError, ValueError):
        pass
    if rc == 0 and code == "200" and ok_body:
        rep.add("⑤", "/health 200（云端回环）", "PASS", ["HTTP 200 %s" % body])
    else:
        rep.add("⑤", "/health 200（云端回环）", "FAIL",
                ["http_code=%r rc=%s body=%s %s" % (code, rc, body[:120], sanitize(err.strip()[:80]))],
                ["判读=服务在而 health 不通：核 systemd 端口/venv/进程日志（journalctl -u %s 云端）" % UNIT])


def check_mempreflight(rep, cloud):
    """⑦ 装载内存预估闸（排序优化四期 P1 #5）：云端 MemAvailable vs 峰值预估。

    2026-10-26 估算面现代化（过程日志 176 债清账/235③）：行式→bin 镜像口径。
    一条只读 SSH 往返（CMD_MEMPRE）取云端 MemAvailable（kB）与库镜像形态
    （MC/MD/MB/MM=count/dim/f32.bin/meta.json 字节；镜像缺席/过期/坏=LS
    行式件字节回退）：
    - 一级（镜像口径）：rows=MC、dim=MD、size=MB+MM（装载实际读入两件量）
      → peak_bytes_from 判 PASS/FAIL；
    - 二级（行式回落）：LS=size + 本机同源库 peek（装载预检.peek_store 同为
      镜像优先；行式回落形取首行字节/dim）→ rows=size//首行字节 → 同公式。
    公式与 建库/scripts/装载预检.py 单点同源；est>avail=FAIL 证据带 est/avail
    MB 与红线句。SSH 通道走既有 resolve_ssh_target 解析的 cloud，本函数不
    回显任何 ssh 行。"""
    rc, out, err = cloud.run(CMD_MEMPRE, timeout=30)
    if rc != 0:
        rep.add("⑦", "装载内存预估闸（云端 MemAvailable vs 峰值预估）", "FAIL",
                ["取数失败 rc=%s %s" % (rc, err.strip()[:120])],
                ["判读=取数通道问题而非内存问题：核 SSH 连通（与①同通道）"])
        return
    parts = out.split("__SZ__")
    if len(parts) != 2 or not parts[0].strip().isdigit():
        rep.add("⑦", "装载内存预估闸（云端 MemAvailable vs 峰值预估）", "FAIL",
                ["输出形态异常: %r" % out.strip()[:120]],
                ["判读=云端 awk/meminfo 输出不符预期（/proc/meminfo 缺 MemAvailable 键）"])
        return
    avail_kb = int(parts[0].strip())
    avail = avail_kb * 1024          # /proc/meminfo 数值单位 kB → bytes
    def mb(b):  # 与 装载预检._mb 同口径，1024 进制
        return b // (1024 * 1024)
    stats = parts[1]
    m_mc = re.search(r"^MC=(\d+)$", stats, re.M)
    m_md = re.search(r"^MD=(\d+)$", stats, re.M)
    m_mb = re.search(r"^MB=(\d+)$", stats, re.M)
    m_mm = re.search(r"^MM=(\d+)$", stats, re.M)
    m_ls = re.search(r"^LS=(\d+)$", stats, re.M)
    if m_mc and m_md and m_mb and m_mm:
        rows, dim = int(m_mc.group(1)), int(m_md.group(1))
        store_size = int(m_mb.group(1)) + int(m_mm.group(1))
        est = 装载预检.peak_bytes_from(store_size, rows, dim)
        ev = ["云端 MemAvailable=%dkB → avail=%dMB" % (avail_kb, mb(avail)),
              "云端库镜像口径 count=%d dim=%d bin+meta=%dB → est=%dMB"
              "（max((bin+meta)×2.5, rows×dim×8)+100MB）"
              % (rows, dim, store_size, mb(est))]
    elif m_ls:
        store_size = int(m_ls.group(1))
        try:
            pk = 装载预检.peek_store(os.path.join(BASE_DIR, STORE_REL))
        except OSError:
            rep.add("⑦", "装载内存预估闸（云端 MemAvailable vs 峰值预估）", "SKIP",
                    ["云端无镜像（行式回落）且本机同源库缺/不可读：%s" % os.path.join(BASE_DIR, STORE_REL)],
                    ["判读=无法推首行/dim（本机与云端库不同步？），同步后重跑"])
            return
        # 云端镜像缺席=装载走行式 jsonl；本机 peek 若也非行式形（镜像优先命中
        # 时 first_line_bytes=0）则 rows 推不出 → 0，est 由 size×2.5 文本膨胀
        # 分支主导（真行库该分支本就占优，保守向不漏拦）。
        rows = store_size // pk["first_line_bytes"] if pk["first_line_bytes"] else 0
        est = 装载预检.peak_bytes_from(store_size, rows, pk["dim"])
        ev = ["云端 MemAvailable=%dkB → avail=%dMB" % (avail_kb, mb(avail)),
              "云端库行式回落 size=%d B → est=%dMB（rows≈%d、dim=%s、max(size×2.5, rows×dim×8)+100MB）"
              % (store_size, mb(est), rows, pk["dim"])]
    else:
        rep.add("⑦", "装载内存预估闸（云端 MemAvailable vs 峰值预估）", "FAIL",
                ["输出形态异常: %r" % out.strip()[:120]],
                ["判读=云端镜像/行式取数均不符预期（库路径不对或 python3 -c 输出形态变化）"])
        return
    if avail >= est:
        rep.add("⑦", "装载内存预估闸（云端 MemAvailable vs 峰值预估）", "PASS", ev)
    else:
        ev.append("红线：%s" % 装载预检.RED_LINE)
        rep.add("⑦", "装载内存预估闸（云端 MemAvailable vs 峰值预估）", "FAIL", ev,
                ["判读=云端可用内存不足以装下预估峰值（est>avail，过程日志一节19 窗后事故"
                 "防线）：勿在该机跑装库评测；确属有意冒进，云端侧 QA_BOT_MEM_FORCE=1 "
                 "可豁免 retrieve.load_library 入口闸（本核对项仍如实记 FAIL）"])


def check_rerank_armed(rep, jdata):
    """⑧ rerank 探针 armed（2026-10-12 合围工程基建一期 2-C 新项甲）：启动行
    [startup] rerank_log=<on|off> cap=<N>cny（server lifespan :913-914 打点）。

    判读分型沿 ④ 新旧版哲学：行缺=云端仍旧版（未部署新版，非新版异常）；
    rerank_log=off=新版已部署但有意关探针（rerank_log_enabled=false 属部署
    动作——若与部署意图不符须人工核 config 与 restart）。证据通道=②既有
    journal 首段（grep 模式 ^\\[startup\\] 已覆盖），零新增 SSH 往返。"""
    seg = (jdata or {}).get("boot_seg") or []
    line = next((line for line in reversed(seg)
                 if line.startswith("[startup] rerank_log=")), None)
    if line is None:
        rep.add("⑧", "rerank 探针 armed（[startup] rerank_log 行）", "FAIL",
                ["最近一次启动段无 [startup] rerank_log= 行"],
                ["判读=云端仍是旧版 server.py（合围一期探针开关面未上云）：属'未部署新版'"
                 "而非新版异常——部署新版后重跑本项"])
        return
    m = re.search(r"rerank_log=(on|off)(?:\s+cap=([\d.]+)cny)?", line)
    if m and m.group(1) == "on":
        rep.add("⑧", "rerank 探针 armed（[startup] rerank_log 行）", "PASS",
                [line, "cap=%scny（探针月费软顶，供与 rerank_log 台账红线对照）"
                 % (m.group(2) or "?")])
    elif m:
        rep.add("⑧", "rerank 探针 armed（[startup] rerank_log 行）", "FAIL", [line],
                ["判读=新版已部署但探针有意关闭（config rerank_log_enabled=false 属"
                 "部署动作）：若与部署意图不符，查云端 config.json 与 restart——与"
                 "'未部署新版'（行缺）语义分开"])
    else:
        rep.add("⑧", "rerank 探针 armed（[startup] rerank_log 行）", "FAIL", [line],
                ["判读=行形态异常（rerank_log= 在场但 on/off/cap 不可解析）：核新版"
                 " server.py 打点形态与两侧版本对齐"])


def check_source_tier_file(rep, cloud):
    """⑨ SOURCE_TIER 数据件在位（2-C 新项乙）：云端 data/source-tier.json 存在
    且可解析（CMD_SOURCETIER 只读往返，零改动零密值回显）。

    分级（并行泳道施工期容忍口径，2026-10-12 任务书）：件缺=INFO 不红（泳道未
    合入/部署包未含——服务走 server.py 内置回退快照不受影响，属'部署不完整'
    而非'服务异常'，泳道合入随包上云后本项自然转绿）；件在但解析失败（json.load
    抛异常）=WARN（回退快照兜底服务可用，但须人工重传数据件）；取数通道失败
    =FAIL（同①⑦ 哲学：通道问题而非服务问题）。"""
    rc, out, err = cloud.run(CMD_SOURCETIER, timeout=30)
    lines = [line for line in out.splitlines() if line.startswith("ST_")]
    exists = any(line.startswith("ST_EXISTS=1") for line in lines)
    if not exists:
        if rc == 0 and any(line.startswith("ST_EXISTS=0") for line in lines):
            rep.add("⑨", "SOURCE_TIER 数据件在位（data/source-tier.json）", "INFO",
                    ["云端 /opt/qa-bot/data/source-tier.json 不在位"],
                    ["判读=部署包未含数据件（并行泳道施工中/未随包上云）：服务走 server.py"
                     " 内置回退快照，分级判定不受影响——属'部署不完整'而非'服务异常'；"
                     "泳道合入并随包上云后本项自然转绿"])
        else:
            rep.add("⑨", "SOURCE_TIER 数据件在位（data/source-tier.json）", "FAIL",
                    ["取数失败 rc=%s %s" % (rc, err.strip()[:120])],
                    ["判读=取数通道问题而非数据件问题：核 SSH 连通与远端 python3（与①同通道）"])
        return
    rules = next((line for line in lines if line.startswith("ST_RULES=")), None)
    if rules:
        rep.add("⑨", "SOURCE_TIER 数据件在位（data/source-tier.json）", "PASS",
                ["云端在位且可解析：%s；%s" % (lines[0], rules)],
                ["分级面以本项转绿为随包上云完成标志（E6）；结构深校验归泳道单测"])
    else:
        rep.add("⑨", "SOURCE_TIER 数据件在位（data/source-tier.json）", "WARN",
                ["件在位但解析失败（远端 json.load 抛异常）：%s %s"
                 % (lines[0], err.strip()[:120])],
                ["判读=部署不完整（件坏/传输截断）：服务走内置回退快照可用、分级判定"
                 "不受影响——须人工重传数据件后重跑；非'服务异常'红"])


def check_rerank_refusal_key(rep, cloud, jdata):
    """⑩ rerank 行为键状态呈现（2-C 新项丙）：config 顶层键
    rerank_refusal_enabled 现值呈现（CMD_RERANKCFG 单键打印，零密值），不判红。

    键开=呈现开态+核 [rerank_gate] 行可判读（journal __RERANK__ 段，全历史
    tail）；键关（默认 false/absent）=关态呈现，零 gate 行属预期（gate 行在场
    =历史残留，只呈现）。[chat] rag=rerank_refused 态已入 ④ 既有五态规则
    （parse_chat_line 教识在案），本项零新判定。"""
    rc, out, err = cloud.run(CMD_RERANKCFG, timeout=30)
    if rc != 0 or "rerank_refusal_enabled=" not in out:
        rep.add("⑩", "rerank 行为键状态（config rerank_refusal_enabled 现值）", "INFO",
                ["config 键取数失败 rc=%s %s" % (rc, err.strip()[:120])],
                ["判读=取数通道问题（与①同通道）；本项纯呈现不判红"])
        return
    cfg_lines = [line for line in out.splitlines()
                 if line.startswith(("rerank_log_enabled=", "rerank_refusal_enabled="))]
    refusal = next((line.split("=", 1)[1] for line in cfg_lines
                    if line.startswith("rerank_refusal_enabled=")), "?")
    # [rerank_gate] 行自 journal run 段尾（__RERANK__ 第三段）按前缀过滤
    run_lines = (jdata or {}).get("chat_lines") or []
    gate_lines = [line for line in run_lines if line.startswith("[rerank_gate]")]
    ev = cfg_lines + gate_lines[-2:]
    if refusal == "True":
        hints = ["键开态（rerank_refusal_enabled=true，0.75 档行为级拒答）："
                 "[rerank_gate] 行 %d 条（pass/refuse/skip 分布可判读）"
                 % len(gate_lines)]
        if not gate_lines:
            hints.append("键开但 journal 无 [rerank_gate] 行——尚无 hit 流量或改键后"
                         "未 restart（呈现项不判红，人工核 config 与 restart）")
        rep.add("⑩", "rerank 行为键状态（config rerank_refusal_enabled 现值）", "INFO",
                ev, hints)
    else:
        rep.add("⑩", "rerank 行为键状态（config rerank_refusal_enabled 现值）", "INFO",
                ev,
                ["键关态（%s=默认 false/显式 false）：行为与既往一致，零 [rerank_gate] 行"
                 "属预期%s——本项纯呈现不判红"
                 % (refusal, "（journal 在场 %d 条为历史残留，全历史 tail 口径）"
                    % len(gate_lines) if gate_lines else "")])


# ⑪⑫ 判读所需 obs 机读档核心字段（§10 冻结 schema 的判读子集：缺任一即
# SLA_UNKNOWN；ops/unknown/bot/success_count/fail_count/cancelled/formal_since/
# metric_version/identity_rules_version=呈现面字段，在场即显、缺省不判坏）
_OBS_SLA_CORE = ("period", "sample_total", "real", "success_rate",
                 "p50_ms", "p95_ms", "p99_ms", "sla_state", "consecutive_miss")
_OBS_SLA_NUM = ("sample_total", "real", "success_rate", "p50_ms",
                "p95_ms", "p99_ms", "consecutive_miss")
_OBS_SLA_STATES = ("INSUFFICIENT", "OBSERVING", "FORMAL")


def _obs_num(v):
    """数值字段判定（bool 不算数——json true/false 是 bool，.isdigit 场景不混入）。"""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def check_sla_status(rep, cloud, now=None):
    """⑪ SLA 状态机读数（2026-10-14 产品维度升级收口 §三/§10 接口冻结）：
    SSH 只读云端 /opt/qa-bot/建库/logs/obs-latency-自动-*.json 最新档
    （CMD_OBS_SLA 一条往返：ls -1 排序取最新+次新 + cat 最新），按 §10 冻结
    schema 判读呈现：截至期号（文件名日期）/真实样本/成功率/p50/p95/p99/
    状态机态/consecutive_miss/formal_since。

    **程序呈现、不阻断**（§六分级：WARN/INFO 不入 has_fail，本函数无任何
    FAIL 分支——SLA 开窗与否由用户裁定）。定级：
      - 解析成功且 FORMAL 且达标（p95≤8000ms 且 success_rate≥0.95 且零连续
        未达）→ INFO；
      - INSUFFICIENT（真实样本<30）/ 最新档距今>14 天（周报节奏缺期≥2）/
        json 损坏/核心字段缺/坏值/sla_state 非法/期数倒退 → WARN 且 evidence
        标 SLA_UNKNOWN（读数不可判，§三：不得 PASS）；
      - OBSERVING（样本 30–99）→ WARN 观察期读数（§二：观察=WARN 级读数）；
      - FORMAL 且 consecutive_miss≥1 或 p95>8000ms 或 success_rate<0.95 →
        WARN 且标"连续未达 N 期，开窗时由用户裁定"；
      - 云端尚无任何 obs-latency json（脚本刚上云首窗未跑）→ INFO"SLA 观测
        未起（首窗周五 08:30）"；
      - 取数通道失败 → WARN+SLA_UNKNOWN（呈现级不阻断，与 ⑨ 通道 FAIL
        哲学分开）。now 可注入（测试确定性），缺省=datetime.now()。"""
    num, title = "⑪", "SLA 状态机读数（obs-latency-自动-*.json 最新档）"
    rc, out, err = cloud.run(CMD_OBS_SLA, timeout=30)
    if rc != 0 or "__OBSLAT__" not in out:
        rep.add(num, title, "WARN",
                ["SLA_UNKNOWN（取数失败/输出形态异常 rc=%s %s）"
                 % (rc, err.strip()[:120])],
                ["判读=取数通道问题而非观测面问题（与①同通道）；本项程序呈现级"
                 "不阻断（§六），窗口核验时人工复核"])
        return
    parts = out.split("__OBSLAT__")
    files = [line.strip() for line in parts[0].splitlines() if line.strip()]
    body = parts[1].strip() if len(parts) > 1 else ""
    if not files:
        rep.add(num, title, "INFO",
                ["云端 /opt/qa-bot/建库/logs/ 下无 obs-latency-自动-*.json"],
                ["判读=SLA 观测未起（首窗周五 08:30）：obs 脚本刚上云、首窗未跑，"
                 "属部署窗预期基线（程序呈现级，下窗后自然有读数）"])
        return
    latest = files[-1]
    second = files[-2] if len(files) > 1 else None
    ev_files = ["最新档: %s%s" % (latest, ("（次新 %s）" % second) if second else "")]
    # 截至期号自文件名日期（YYYYMMDD；不可解析=只呈现不判红，缺期判读随之跳过）
    m = re.search(r"(\d{8})", latest)
    file_date = None
    if m:
        try:
            file_date = datetime.strptime(m.group(1), "%Y%m%d")
        except ValueError:
            file_date = None
    period_disp = ("%s-%s-%s" % (m.group(1)[:4], m.group(1)[4:6], m.group(1)[6:8])
                   if m else "不可解析（文件名日期）")
    # json 解析（损坏含顶层非对象）
    try:
        data = json.loads(body)
        if not isinstance(data, dict):
            raise ValueError("顶层非对象")
    except (json.JSONDecodeError, ValueError):
        rep.add(num, title, "WARN",
                ["SLA_UNKNOWN（最新档 json 损坏/不可解析）"] + ev_files,
                ["判读=机读档坏/传输截断：人工核云端 %s 与 obs timer 失败可见性"
                 "（运营/自动化任务登记.md）；本项不阻断" % latest])
        return
    # 核心字段与类型校验（缺/坏/状态枚举非法 → SLA_UNKNOWN）
    missing = [k for k in _OBS_SLA_CORE if k not in data]
    badnum = [k for k in _OBS_SLA_NUM if k in data and not _obs_num(data[k])]
    state = data.get("sla_state")
    why = []
    if missing:
        why.append("字段缺=%s" % ",".join(missing))
    if badnum:
        why.append("坏值=%s" % ",".join(badnum))
    if state not in _OBS_SLA_STATES:
        why.append("sla_state 非法=%r" % (state,))
    if why:
        rep.add(num, title, "WARN",
                ["SLA_UNKNOWN（%s）" % "；".join(why)] + ev_files,
                ["判读=机读档不合 §10 冻结 schema（obs 施工面 bug 或版本错位）："
                 "人工核最新档内容与 obs_weekly 版本；本项不阻断"])
        return
    # 读数 evidence（判级前统一构造——各分支均带完整读数呈现）
    ev = list(ev_files)
    ev.append("截至期号=%s（文件名日期）%s" % (
        period_disp, "；json period=%s" % data["period"]
        if str(data["period"]) != period_disp else ""))
    ev.append("真实样本 real=%s/总样本 sample_total=%s；成功率 success_rate=%s"
              % (data["real"], data["sample_total"], data["success_rate"]))
    ev.append("延迟 p50=%sms p95=%sms p99=%sms"
              % (data["p50_ms"], data["p95_ms"], data["p99_ms"]))
    ev.append("状态机态 sla_state=%s；consecutive_miss=%s；formal_since=%s"
              % (state, data["consecutive_miss"],
                 data.get("formal_since") or "未记录"))
    ver = [k for k in ("metric_version", "identity_rules_version") if k in data]
    if ver:
        ev.append("口径版本：%s" % "；".join("%s=%s" % (k, data[k]) for k in ver))
    # 判级一：缺期（最新档距今>14 天=周报节奏缺期≥2）——读数不代表当前，优先
    now = now or datetime.now()
    if file_date is not None:
        age = (now - file_date).days
        if age > 14:
            rep.add(num, title, "WARN",
                    ev + ["SLA_UNKNOWN（最新档距今 %d 天>14：周报节奏缺期≥2，"
                          "读数不代表当前）" % age],
                    ["判读=缺期（obs timer 停摆/失败静默）：核 timer 状态与失败"
                     "可见性登记（§一4 周报 freshness+SLA_UNKNOWN 呈现）；本项"
                     "程序呈现级不阻断"])
            return
    # 判级二：INSUFFICIENT（样本不足，读数不可判）
    if state == "INSUFFICIENT":
        rep.add(num, title, "WARN",
                ev + ["SLA_UNKNOWN（INSUFFICIENT：真实样本<30，SLA 读数不可判）"],
                ["判读=样本不足（真实成功样本<30）：流量积累后自然转观察/正式态；"
                 "本项不阻断"])
        return
    # 判级三：期数倒退（最新档 json period 早于次新档文件名日期——读数序不可信）
    if second:
        m2 = re.search(r"(\d{8})", second)
        if m2 and data["period"]:
            try:
                pdate = datetime.strptime(str(data["period"]).replace("-", ""),
                                          "%Y%m%d")
                sdate = datetime.strptime(m2.group(1), "%Y%m%d")
                if pdate < sdate:
                    rep.add(num, title, "WARN",
                            ev + ["SLA_UNKNOWN（期数倒退：最新档 period=%s 早于"
                                  "次新档日期 %s，读数序不可信）"
                                  % (data["period"], m2.group(1))],
                            ["判读=机读档序异常（obs 写档竞态/人工回填错序）：人工"
                             "核 logs 目录；本项不阻断"])
                    return
            except ValueError:
                pass    # period 非 YYYYMMDD/YYYY-MM-DD 形态（如周边号）——不误判
    # 判级四：OBSERVING（观察期，WARN 级读数——有读数故不标 SLA_UNKNOWN）
    if state == "OBSERVING":
        rep.add(num, title, "WARN", ev,
                ["判读=观察期读数（真实样本 30–99，§二 WARN 级读数）：连续两期"
                 "达标即转正式；程序呈现级不阻断"])
        return
    # 判级五：FORMAL——达标 INFO / 未达 WARN（开窗由用户裁定）
    cm = int(data["consecutive_miss"])
    misses = []
    if cm >= 1:
        misses.append("consecutive_miss=%d" % cm)
    if data["p95_ms"] > 8000:
        misses.append("p95=%sms>8000ms" % data["p95_ms"])
    if data["success_rate"] < 0.95:
        misses.append("success_rate=%s<0.95" % data["success_rate"])
    if misses:
        mark = ("连续未达 %d 期，开窗时由用户裁定" % cm if cm >= 1
                else "本期未达（连续未达计数=0），开窗时由用户裁定")
        rep.add(num, title, "WARN",
                ev + ["%s（未达项：%s）" % (mark, "；".join(misses))],
                ["判读=正式态未达 SLA 承诺线（§0 基线2：ttfb p95≤8s+成功率≥95%）："
                 "本项程序呈现级不阻断，是否开窗处置由用户裁定"])
        return
    rep.add(num, title, "INFO", ev,
            ["判读=正式态达标（p95≤8s 且成功率≥95% 且零连续未达）：SLA 承诺线"
             "读数在案（§0 基线2）；程序呈现级"])


def check_embed_budget(rep, cloud):
    """⑫ 嵌入预算拨键呈现（2026-10-14 产品维度升级收口 §三/§五/§10）：SSH
    只读核云端 /opt/qa-bot/config.json 的 rag 段预算三键
    （embed_monthly_budget_enabled/budget_cny/cap_cny）。**安全红线：远端
    python3 -c 只提取并打印三键值，绝不 cat 整个 config.json（含密件）**；
    dry-run fixture 同理只含三键。

    期望值=EMBED_BUDGET_EXPECT（本专项拨键口径 §五：enabled=true/
    budget=40.0=预警线/cap=50.0=熔断线）。**程序呈现、不阻断（无 FAIL 分支）**：
    基态 INFO（呈现三键现值+配置来源路径）；值不符/budget≥cap（预警线触到
    熔断线，语义失效）/坏值/缺键/取数失败 → WARN——调线以过程日志决策登记为准，
    程序只呈现不裁。"""
    num, title = "⑫", "嵌入预算拨键呈现（config rag 段预算三键）"
    src = ("配置来源: /opt/qa-bot/config.json rag 段（远端 python3 三键提取，"
           "不整档读取——密件纪律）")
    rc, out, err = cloud.run(CMD_EMBEDBUDGET, timeout=30)
    if rc != 0 or "embed_monthly_budget_enabled=" not in out:
        rep.add(num, title, "WARN",
                [src, "三键取数失败 rc=%s %s" % (rc, err.strip()[:120])],
                ["判读=取数通道问题而非预算面问题（与①同通道）；窗口核验时人工"
                 "复核；本项程序呈现级不阻断"])
        return
    kv = {}
    for line in out.splitlines():
        for key in EMBED_BUDGET_EXPECT:
            if line.startswith(key + "="):
                kv[key] = line.split("=", 1)[1].strip()
    ev = [src] + ["%s=%s" % (k, kv.get(k, "<absent>"))
                  for k in EMBED_BUDGET_EXPECT]
    missing = [k for k in EMBED_BUDGET_EXPECT
               if k not in kv or kv[k] == "<absent>"]
    if missing:
        rep.add(num, title, "WARN", ev + ["缺键: %s" % ",".join(missing)],
                ["判读=云端 config rag 段缺预算键（拨键未上云/旧版 config）：按"
                 " §五 拨键口径补键后 restart；本项呈现级不阻断"])
        return
    enabled = kv["embed_monthly_budget_enabled"]
    bad = []
    if enabled not in ("True", "False"):
        bad.append("enabled 坏值=%r" % enabled)
    budget = cap = None
    for key, name in (("embed_monthly_budget_cny", "budget"),
                      ("embed_monthly_cap_cny", "cap")):
        try:
            v = float(kv[key])
        except ValueError:
            bad.append("%s 坏值=%r" % (name, kv[key]))
            continue
        if v < 0:
            bad.append("%s 负值=%s" % (name, v))
        elif name == "budget":
            budget = v
        else:
            cap = v
    if bad:
        rep.add(num, title, "WARN", ev + bad,
                ["判读=键值形态异常（非布尔/非数值/负值，手改痕迹）：核云端"
                 " config rag 段；本项呈现级不阻断"])
        return
    if budget is not None and cap is not None and budget >= cap:
        rep.add(num, title, "WARN",
                ev + ["budget(%s)≥cap(%s)：预警线触到熔断线，拨键语义失效"
                      % (budget, cap)],
                ["判读=预算键语义矛盾（§五：budget=预警线须<cap=熔断线）：核"
                 "拨键口径后改键；本项呈现级不阻断"])
        return
    got = {"embed_monthly_budget_enabled": enabled == "True",
           "embed_monthly_budget_cny": budget,
           "embed_monthly_cap_cny": cap}
    if got != EMBED_BUDGET_EXPECT:
        diff = ["%s=%s（期望 %s）" % (k, got[k], EMBED_BUDGET_EXPECT[k])
                for k in EMBED_BUDGET_EXPECT if got[k] != EMBED_BUDGET_EXPECT[k]]
        rep.add(num, title, "WARN", ev + diff,
                ["判读=与本专项拨键口径（§五：enabled=true/budget=40 预警线/"
                 "cap=50 熔断线）不符：若属有意调线以过程日志决策登记为准，否则核"
                 "云端 config 与 restart；本项呈现级不阻断"])
        return
    rep.add(num, title, "INFO", ev,
            ["判读=拨键口径达成（§五：budget=40=预警线/cap=50=熔断线；台账总"
             "治理线=过程日志 36① 累计 50 元口径，两线分账——两管线闸=机械执行面，"
             "合计可超单闸=已知界，周报合计监督行兜底）"])


def check_chat_form(rep, chat_lines, smoke_ran):
    """④ [chat] 打点形态规则抽验（三规则五态：hit/low_score/coverage_miss/miss/off）
    + 新旧版判读 + 期1 路由 rt= 键核读。
    三规则=hit/low_score/coverage_miss 行带 q=+top1=（low_score/coverage_miss
    的 top1=闸门余弦原始分口径，与 hit 的通道排序分口径不同）/ miss 行只带
    q= 无 top1= / off 行两字段皆无；五态行一律入判不跳过。解析只锚 rag=/q=/
    top1=/rt= 子串，字段顺序与新增字段（auth=/ttfb=/cancelled=/cc=/ab=/rt=/
    trace=）无关——批1/批2 形态混合样本均须判读一致（rt= 键容忍不误报，
    开态下计数入核读）。"""
    parsed = [p for p in (parse_chat_line(line) for line in chat_lines) if p]
    if not parsed:
        rep.add("④", "[chat] 打点形态规则抽验", "FAIL",
                ["最近 journal 无 [chat] 行"],
                ["无法抽验（需先有问答流量）：重跑本脚本加 --smoke（2 次问答调用），"
                 "或人工发一问后复核（验收清单第 4 项口径）"])
        return
    ev = [p["line"] for p in parsed[-3:]]
    hints, ok = [], True
    viol = []
    for p in parsed:
        # low_score/coverage_miss/rerank_refused 行与 hit 同规则：带 q= 与 top1=
        # （low_score/coverage_miss 的 top1=闸门余弦原始分；rerank_refused 的
        # top1=保留原 hit 通道排序分——闸判定分在 [rerank_gate] 行，2026-10-12）
        if p["rag"] in ("hit", "low_score", "coverage_miss", "rerank_refused") and not (p["q"] and p["top1"]):
            viol.append(p)
        elif p["rag"] == "miss" and (not p["q"] or p["top1"]):
            viol.append(p)
        elif p["rag"] == "off" and (p["q"] or p["top1"]):
            viol.append(p)
    hits = [p for p in parsed if p["rag"] == "hit"]
    misses = [p for p in parsed if p["rag"] == "miss"]
    lows = [p for p in parsed if p["rag"] == "low_score"]
    covs = [p for p in parsed if p["rag"] == "coverage_miss"]
    offs = [p for p in parsed if p["rag"] == "off"]
    rts = [p["rt"] for p in parsed if p["rt"]]
    if viol:
        ok = False
        if any(p["rag"] == "hit" and not p["q"] and not p["top1"] for p in viol) and hits and \
                not any(p["q"] for p in hits):
            hints.append("判读=云端仍是旧版 server.py：hit 行全无 q=/top1=（第 2 批打点未生效）——"
                         "属'未部署新版'而非新版异常，按 上云差异 §六 次序 scp server.py + restart 后重跑；无需回滚")
        else:
            hints.append("判读=新版已部署但打点形态异常（三规则违例）：核 server.py 两侧 md5 对齐、"
                         "config rag 段与 restart（上云差异 §三/§六）")
        ev.extend(p["line"] for p in viol[-2:])
    rule_note = ("hit=%d miss=%d low_score=%d cov_miss=%d off=%d；规则=hit/low_score/"
                 "coverage_miss 行带 q=+top1= / miss 行只带 q= / off 行两字段皆无"
                 % (len(hits), len(misses), len(lows), len(covs), len(offs)))
    if rts:
        # 期1 路由开态核读（2026-10-01 教识）：rt= 键在场即路由生效证，只报形不判 FAIL
        rt_dist = "；".join(f"{v}×{rts.count(v)}" for v in sorted(set(rts)))
        hints.append("route 开态：[chat] 行带 rt= 共 %d 轮（%s）——期1 路由生效证"
                     "（域简写:态，v=红线否决/d=域定向/doc=doc直判/f=全量回退），"
                     "配 [rag-route] 行复核" % (len(rts), rt_dist))
    if offs and not hits and not misses:
        hints.append("注意：样本仅 rag=off 行——off 行新旧版逐字节一致，无法判版；rag.enabled=true 后复跑")
    if smoke_ran:
        hints.append("样本含本次 --smoke 两问的落日志行")
    rep.add("④", "[chat] 打点形态规则抽验（%s）" % rule_note, "PASS" if ok else "FAIL", ev[-6:], hints)


def read_passcode():
    """冒烟口令三级取数（2026-10-03 口令面改造，本函数仅 --smoke 路径调用）：
    ① 环境变量 QABOT_SMOKE_PASSCODE（**显式覆盖，生产口令首选不落盘**——本机
       config 存的是开发态口令，与云端 PBKDF2 生产口令不同步的伪红即靠此级解）
    ② 本机 config.json 明文键（历史路径，仅开发态与生产同口令时可用）
    ③ 交互手输（getpass 不回显）
    口令只进内存变量，任何路径都不回显、不落盘。→ (passcode, err)"""
    pc = str(os.environ.get("QABOT_SMOKE_PASSCODE") or "").strip()
    if not pc:
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                cfg = json.load(f)
            pc = str(cfg.get("passcode") or "").strip()
        except (OSError, json.JSONDecodeError):
            pc = ""
    if not pc:
        import getpass
        try:
            pc = getpass.getpass("环境变量缺、本机 config 亦无口令——请输入云端生产口令（不回显，仅 --smoke 冒烟用；推荐改用 QABOT_SMOKE_PASSCODE）：").strip()
        except (EOFError, KeyboardInterrupt):
            return None, "交互取口令被取消（建议改用 QABOT_SMOKE_PASSCODE 环境变量）"
    if not pc:
        return None, "三级取数全空（QABOT_SMOKE_PASSCODE/config.json/交互输入）"
    return pc, None


def smoke_one(cloud, passcode, question):
    payload = json.dumps({"passcode": passcode,
                          "messages": [{"role": "user", "content": question}]},
                         ensure_ascii=False)
    rc, out, err = cloud.run(CMD_SMOKE_CURL, timeout=150, stdin_data=payload)
    if rc != 0:
        return {"ok": False, "why": "云端回环 curl 失败 rc=%s %s" % (rc, sanitize(err.strip()[:100]))}
    r = parse_sse(out)
    if r["errors"]:
        return {"ok": False, "why": "SSE error 事件: %s" % "; ".join(r["errors"])[:160]}
    return {"ok": True, **r, "raw_head": out[:120]}


def _smoke_rag_layer(rep, cloud):
    """2026-10-01 缺口修 B2：无口令 RAG 直测冒烟（云端 rag 模块+.env 键，
    query 嵌入→检索→出处首位锚判定；零口令零 LLM 零额外费用）。
    触发=本机无 passcode 或 DEPLOY_SMOKE_RAG=1（cookie/PBKDF2 鉴权栈下
    口令直发双轨不可用时的正规回退，生成层不判=答案判据不适用）。"""
    try:
        spec = _load_anchor_spec()
    except AnchorSpecError as e:
        rep.add("S", "RAG 直测冒烟两题", "FAIL", [str(e)], [])
        return
    code = ("import sys,os\nsys.path.insert(0,'/opt/qa-bot')\n"
            "for _l in open('/opt/qa-bot/.env'):\n"
            "    _l=_l.strip()\n"
            "    if _l and not _l.startswith('#') and '=' in _l:\n"
            "        _k,_v=_l.split('=',1);os.environ[_k.strip()]=_v.strip().strip(chr(34)).strip(chr(39))\n"
            "import rag\n"
            "_r,_d,_s=rag.load_store('/opt/qa-bot/'+" + repr(STORE_REL) + ")\n"
            "print('RAGSMOKE|store|' + str(_s['loaded']) + '|' + ('sidecar' if _s.get('sidecar') else 'jsonl'))\n"
            "for _sid,_q in (('S1'," + repr(SMOKE_Q1) + "),('S2'," + repr(SMOKE_Q2) + ")):\n"
            "    _h=rag.search(rag.embed_query(_q),_r,topk=3)\n"
            "    _t=_h[0]['rec']\n"
            "    print('RAGSMOKE|' + _sid + '|' + str(_t.get('doc_id')) + '|' + str(_t.get('version')) + '|' + str(_t.get('locator')) + '|' + str(_h[0].get('score')))\n"
            )
    import shlex
    rc, out, err = cloud.run(
        "cd /opt/qa-bot && venv/bin/python -c " + shlex.quote(code), timeout=300)
    if rc != 0:
        rep.add("S", "RAG 直测冒烟两题", "FAIL",
                ["云端 RAG 直测失败 rc=%s" % rc, sanitize(err.strip()[:120])],
                ["判读=检索链路（.env 键/库装载/embed 调用）问题，非语料问题"])
        return
    got = {}
    for line in out.splitlines():
        parts = line.strip().split("|")
        if len(parts) >= 6 and parts[0] == "RAGSMOKE" and parts[1] in ("S1", "S2"):
            got[parts[1]] = {"doc_id": parts[2], "version": parts[3],
                             "locator": parts[4], "score": parts[5]}
        elif len(parts) >= 4 and parts[0] == "RAGSMOKE" and parts[1] == "store":
            rep.add("I", "RAG 直测装载行 loaded=%s sidecar=%s" % (parts[2], parts[3]),
                    "INFO", [line.strip()], [])
    for sid, q in (("S1", SMOKE_Q1), ("S2", SMOKE_Q2)):
        s = spec["smokes"][sid]
        g = got.get(sid)
        if not g:
            rep.add(sid, "RAG 直测（%s…）" % q[:12], "FAIL",
                    ["无输出行（判读=云端脚本异常）"], [])
            continue
        ok = (any(t in g["doc_id"] for t in s["doc_id_any"])
              and _smoke_anchor_ok(sid, g["locator"], spec))
        rep.add(sid, "RAG 直测检索锚（%s…；生成层未判=无 LLM 直测口径）" % q[:12],
                "PASS" if ok else "FAIL",
                ["top1: doc_id=%s | version=%s | locator=%s | score=%s"
                 % (g["doc_id"], g["version"], g["locator"][:30], g["score"])],
                [] if ok else ["出处首位锚漂移（期望 %s）" % "|".join(s["doc_id_any"])])


def check_smoke(rep, cloud):
    """--smoke：两题问答冒烟（2 次问答调用走云端自身 key；passcode 不回显）。

    S1/S2 首位锚=合格锚集判定，锚集/判据自条款级数据档 期望锚集-条款级.json
    装载（_load_anchor_spec 装载校验；缺失/非法=两题 FAIL+提示，禁静默回退）。"""
    pc, err = read_passcode()
    if not pc or os.environ.get("DEPLOY_SMOKE_RAG") == "1":
        # 2026-10-01 缺口修 B2：口令直发不可用（本机无口令/PBKDF2 栈）或强制
        # RAG 模式时走检索层直测回退，不再直接 FAIL
        _smoke_rag_layer(rep, cloud)
        return
    if not pc:
        rep.add("S", "问答冒烟两题（掉话率红线 / a3-Offset）", "FAIL", [err],
                ["需要 passcode：本机 config.json 的 passcode 字段读入失败或为空"])
        return
    try:
        spec = _load_anchor_spec()
    except AnchorSpecError as e:
        for sid, q in (("S1", SMOKE_Q1), ("S2", SMOKE_Q2)):
            rep.add(sid, "冒烟题（%s…）" % q[:12], "FAIL", [str(e)],
                    ["判读=锚集数据档缺失/非法（%s）：锚集外置件被删/改坏——"
                     "按档内 refresh_procedure 重扫回填或核待提交清单；禁静默回退硬码"
                     % os.path.basename(ANCHOR_SPEC_FILE)])
        return

    def _mk_judge(sid):
        s = spec["smokes"][sid]
        pats = [s["answer_pattern"]] + ([s["answer_pattern2"]] if s.get("answer_pattern2") else [])
        desc = "首位锚合格集=%s（条款级数据档 %s，冻结 %s）；答案判据=%s" % (
            "｜".join(a["anchor_id"] for a in s["anchors"]),
            os.path.basename(ANCHOR_SPEC_FILE), spec["frozen_date"],
            s.get("answer_note", "") or "／".join(pats))

        def judge(r):
            anchor_ok = (isinstance(r.get("sources"), list) and len(r["sources"]) > 0
                         and any(t in str(r["sources"][0].get("doc_id", ""))
                                 for t in s["doc_id_any"])
                         and _smoke_anchor_ok(sid, r["sources"][0].get("locator", ""), spec))
            num_ok = bool(r.get("answer")) and all(
                re.search(p, r["answer"]) for p in pats)
            return anchor_ok, num_ok, desc
        return judge

    specs = [("S1", SMOKE_Q1, _mk_judge("S1")), ("S2", SMOKE_Q2, _mk_judge("S2"))]
    for num, q, judge in specs:
        r = smoke_one(cloud, pc, q)
        if not r.get("ok"):
            rep.add(num, "冒烟题（%s…）" % q[:12], "FAIL", [r.get("why", "未知错误")],
                    ["判读=问答链路异常而非验收项失败：核服务日志与上游 key（journalctl -u %s 云端）" % UNIT])
            continue
        anchor_ok, num_ok, desc = judge(r)
        s0 = r["sources"][0] if isinstance(r.get("sources"), list) and r["sources"] else {}
        ev = [
            "sources 首位: doc_id=%s | version=%s | locator=%s | score=%s" % (
                s0.get("doc_id"), s0.get("version"), s0.get("locator"), s0.get("score")),
            "答案摘录（口吻=人工判读项，观察出处融入行文、无'（依据：…）'括号腔/独立'出处：'行）: %s" % r["answer"][:160],
        ]
        hints = []
        ok = anchor_ok and num_ok
        if not anchor_ok:
            hints.append("出处首位锚漂移（期望 %s）：核对 sources 顺序与检索质量（runbook 步 10 题 1/2 口径）" % desc)
        if not num_ok:
            hints.append("答案数值未命中期望（期望 %s）：人工复核答案摘录" % desc)
        rep.add(num, "冒烟题（%s…）" % q[:12], "PASS" if ok else "FAIL", ev, hints)


def check_post_smoke_journal(rep, cloud, jdata, hybrid_off):
    """smoke 后回捞：④ 的 [chat] 行样本 + [rag-embed] 延迟佐证（清单第 5 项，不强判）。"""
    rc, out, err = cloud.run(CMD_JOURNAL, timeout=60)
    if rc == 0:
        boot, run = split_journal(out)
        embeds = [line for line in run if line.startswith("[rag-embed]")]
        if embeds:
            rep.add("I", "[rag-embed] 检索延迟佐证（清单第 5 项，人工判读≈0.1-0.3s）", "INFO", embeds[-2:])
        if not hybrid_off:
            hyb = [line for line in run if line.startswith("[rag-hybrid]")]
            if hyb:
                rep.add("I", "[rag-hybrid] 运行行佐证（清单第 8 项）", "INFO", hyb[-1:])
        return run
    return (jdata or {}).get("chat_lines", [])


# ---------- 主流程 ----------
def main():
    ap = argparse.ArgumentParser(
        prog="deploy_check.py",
        description="qa-bot 云端部署后验收一键脚本（必跑零 API；--smoke 产生 2 次问答调用走云端自身 key；"
                    "报告落 运营/部署核验-*.md；详见文件头注释）",
        epilog="示例：python3 <repo>/deploy_check.py          # 必跑 6 项\n"
               "      python3 <repo>/deploy_check.py --smoke --hybrid-off\n"
               "      python3 <repo>/deploy_check.py --dry-run=oldver   # 自测",
    )
    ap.add_argument("--smoke", action="store_true",
                    help="加跑两题问答冒烟（2 次问答调用，走云端服务自身 key；查询嵌入走云端按量 embed key；"
                         "需本机 config.json 的 passcode，读入不回显）")
    ap.add_argument("--hybrid-off", action="store_true",
                    help="hybrid 未启用时的降级核对集：跳过 [rag-bm25] build 项，改核'启动后无 bm25/hybrid 行'")
    ap.add_argument("--expect-loaded", type=int, default=DEFAULT_EXPECT_LOADED,
                    metavar="N",
                    help="startup loaded 登底期望值（默认 %(default)s=本机 bin 镜像 meta count 优先"
                         "〔f32.bin 长度自证，2026-10-26 估算面现代化口径；现产终态 82,232=锚面卡批1"
                         "换库窗口径〕；0=只打印不强校验；最新交件块数已变则按新值传）")
    ap.add_argument("--dry-run", nargs="?", const="ok", default=None,
                    choices=["ok", "ok-off", "oldver", "offline"], metavar="场景",
                    help="自测模式，不连云端：ok=新版全量 / ok-off=新版 hybrid 关 / "
                         "oldver=云端仍旧版 / offline=SSH 不可达；报告落 /tmp")
    args = ap.parse_args()

    ts = datetime.now().strftime("%Y%m%d-%H%M")
    rep = Report()
    modes = ["必跑 6 项"]
    if args.hybrid_off:
        modes.append("--hybrid-off（③改降级核对）")
    if args.smoke:
        modes.append("--smoke（2 次问答调用，走云端自身 key，需 passcode）")

    # SSH 解析（只读，不回显）
    ssh_args, cloud, ssh_note = None, None, ""
    if args.dry_run is None:
        resolved, perr = resolve_ssh_target()
        if resolved:
            ident, target = resolved
            if not shutil.which("ssh"):
                ssh_note = "本机无 ssh 客户端"
                cloud = Cloud(offline=True)
            else:
                ssh_args = ["ssh", "-i", ident, "-o", "BatchMode=yes",
                            "-o", "ConnectTimeout=10", "-o", "StrictHostKeyChecking=accept-new", target]
                cloud = Cloud(ssh_args=ssh_args)
                ssh_note = "已解析（身份密钥 %s；登录目标不回显）" % ident
        else:
            ssh_note = perr
            cloud = Cloud(offline=True)
    else:
        cloud = Cloud(scenario=args.dry_run, offline=(args.dry_run == "offline"))
        ssh_note = "dry-run 场景=%s（不连云端）" % args.dry_run

    header = [
        "# 部署核验报告（deploy_check.py）",
        "",
        "- 时间: %s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "- 模式: %s" % " + ".join(modes),
        "- SSH 目标: %s" % ssh_note,
        "- 登底期望: loaded=%s（旧库口径=%d）" % (args.expect_loaded or "不强校验", OLD_LIB_LINES),
        "",
        "对云端执行的命令（全部只读；$CLOUD=运维私密档所载 SSH 登录目标，不回显）：",
        "  $CLOUD '%s'" % CMD_IS_ACTIVE,
        "  $CLOUD '%s'" % CMD_JOURNAL,
        "  $CLOUD '%s'" % CMD_STORECOUNT,
        "  $CLOUD '%s'" % CMD_HEALTH,
        "  $CLOUD '%s'" % CMD_MEMPRE,
        "  $CLOUD '%s'" % CMD_OBS_SLA,
        "  $CLOUD '%s'" % CMD_EMBEDBUDGET,
    ]
    if args.smoke:
        header.append("  $CLOUD '%s'   # payload 经 stdin 送入，passcode 不落命令行" % CMD_SMOKE_CURL)
    for h in header:
        rep.say(h)
    rep.say()

    if args.dry_run is None and cloud.ssh_args is None:
        rep.say("SSH 不可用（%s）——以下云端核对全部 FAIL（降级路径：本脚本不崩溃、逐项给出判读）。" % ssh_note)

    # ①②③⑤⑦ 必跑（⑦=装载内存预估闸，插在⑤后；编号⑥预留）
    check_active(rep, cloud)
    jdata = check_loaded(rep, cloud, args.expect_loaded)
    if jdata:
        check_bm25(rep, jdata, args.hybrid_off)
    else:
        rep.add("③", "[rag-bm25] build 行", "SKIP", [], ["②取数失败，无 startup 段可判"])
    check_health(rep, cloud)
    check_mempreflight(rep, cloud)
    # 合围工程基建一期 2-C 三新项（2026-10-12）：⑧ 探针 armed（复用②journal 首段
    # 零新增往返）/⑨ SOURCE_TIER 数据件在位（独立只读往返）/⑩ 行为键状态呈现
    # （独立只读往返+journal __RERANK__ 段）；既有 8 项判定逻辑一行不动
    if jdata:
        check_rerank_armed(rep, jdata)
    else:
        rep.add("⑧", "rerank 探针 armed（[startup] rerank_log 行）", "SKIP", [],
                ["②取数失败，无启动段可判"])
    check_source_tier_file(rep, cloud)
    check_rerank_refusal_key(rep, cloud, jdata)
    # 产品维度升级收口 §三（2026-10-14）：⑪ SLA 状态机读数 + ⑫ 嵌入预算拨键
    # 呈现——两新项=程序呈现级（WARN/INFO 不入 has_fail，**绝不产生 FAIL**；
    # SLA 开窗/预算调线由用户裁定），既有 ①-⑩ 判定逻辑一行不动
    check_sla_status(rep, cloud)
    check_embed_budget(rep, cloud)

    # --smoke（2 次问答调用）→ 回捞 → ④
    if args.smoke:
        check_smoke(rep, cloud)
        chat_lines = check_post_smoke_journal(rep, cloud, jdata, args.hybrid_off)
        if jdata or chat_lines:
            check_chat_form(rep, chat_lines, smoke_ran=True)
        else:
            rep.add("④", "[chat] 打点形态规则抽验", "SKIP", [], ["journal 取数失败，无样本可判"])
    elif jdata:
        check_chat_form(rep, jdata.get("chat_lines", []), smoke_ran=False)
    else:
        rep.add("④", "[chat] 打点形态规则抽验", "SKIP", [], ["②取数失败，无样本可判（--smoke 或发一问后复核）"])

    # 汇总（WARN=⑨ 数据件解析失败级，2026-10-12 2-C 引入；2026-10-14 收口再扩
    # ⑪⑫ 呈现级 WARN——均不入 has_fail；>0 才呈现，无 WARN 场景汇总行与既往
    # 逐字节一致）
    n_pass = sum(1 for r in rep.results if r[2] == "PASS")
    n_fail = sum(1 for r in rep.results if r[2] == "FAIL")
    n_skip = sum(1 for r in rep.results if r[2] == "SKIP")
    n_warn = sum(1 for r in rep.results if r[2] == "WARN")
    code = 1 if rep.has_fail() else 0
    summary = "## 汇总：PASS=%d FAIL=%d SKIP=%d" % (n_pass, n_fail, n_skip)
    if n_warn:
        summary += " WARN=%d" % n_warn
    rep.say(summary + " → 退出码 %d" % code)
    fails = [r for r in rep.results if r[2] == "FAIL"]
    if fails:
        rep.say()
        rep.say("FAIL 项速览：" + "；".join("%s %s" % (r[0], r[1].split("（")[0]) for r in fails))
        rep.say("判读口径：'仍是旧版'（未部署/未换库/未启用）≠'新版异常'（部署了但形态不对）——"
                "各 FAIL 项证据下方提示已给对应判读，处置路径见 运营/上云差异-第2批-20260918.md §六/§八。")

    # 落盘
    if args.dry_run is not None:
        path = "/tmp/deploy_check-dryrun-%s.md" % ts
    else:
        base = os.path.join(REPORT_DIR, "部署核验-%s" % ts)
        path = base + ".md"
        n = 2
        while os.path.exists(path):
            path = "%s-%d.md" % (base, n)
            n += 1
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(rep.dump_markdown())
        print("报告已落盘: %s" % path)
    except OSError as e:
        print("报告落盘失败: %s %s" % (type(e).__name__, path))
    return code


if __name__ == "__main__":
    sys.exit(main())
