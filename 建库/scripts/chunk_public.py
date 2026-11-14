#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
chunk_public.py —— 公开源语料库切块器（设计稿-公开源语料库-20260917 D2/D3 落地，2026-09-17）

切块方案（D2）：
  - 监管件（建库/L3/raw/ 三件，只读）：条→款两级 + 每件一个摘要块。
      一级=条文/场景条目整块（保上下文，chunk_type=条）；
      二级=款/数字句（数字级可检，chunk_type=款，section 带句片段供 locator 级匹配）；
      摘要块=文号+主题+现行性 caveat（电信服务规范 2005 标"历史口径待核"）。
  - 3GPP 件（建库/raw/3gpp/*.md，只读）：正文按 clause 号切（块首富化
      "TS 36.331 V18.10.0 clause 4.2.2 主题词"，版本自 原始件/ PDF 文件名解析、
      兜底变更史/清单）；表格整表或按行组切块（行组带表头上下文，断裂/跨页表
      解析不动时退整表块，绝不丢表）；ASN.1 不整段入库，从 asn1/ 附件抽"参数卡"
      （参数名/类型/单位若可推/取值域或枚举/步进若可推/出处 clause），解析不出
      取值域的参数宁缺毋滥，计入统计"低把握数"。

字段（D3，rag.py 新库规范至少 id/content/doc_id/version/locator）：
  source_domain(miit/3gpp)/doc_id(规范形态"TS 36.331"带空格；监管用文号简称)/
  version(Release+V 号 或 发文年份)/pub_date/effective_status/chunk_type
  (summary/条/款/table_row_group/asn1_card/clause)/locator(clause 号/条号/表号/
  参数名)/source_url/fetch_date(源文件 mtime)/line_no(行级定位，chunk_id 遗留项
  要求)/content。另随行 retrieve.py 旧口径的 layer/corpus_type/src/chapter/
  doc_title/section/section_seq/sub_part/line_start/line_end，两套消费方都不改。

id：chunk_id.stable_id 内容哈希（id_fields 含 content 与 line_no；行级块
  locator_fields 含 line_no），幂等重切=整文件重写。

零 API 零计费：本模块纯本地；token/费用仅为估算（语种分档精算为主口径——
英文 0.25 token/字符、中文 0.63 token/字符，另留双档 0.5/0.8 粗估参照），
不触任何密钥。

2026-09-17 续跑收尾轮（关机过程日志恢复）：修 12 处——清单.md 误入语料件、
ASN.1 附件名探测（-V18 后缀）、_join_paras 逢噪声断段致碎块膨胀、小写后缀
clause（5.2.1.2a 型，147 个）、表题注按表回溯配对、L2 标签、ASN.1 两行
IE 定义与类型引用解析（Hysteresis ::= / hysteresis Hysteresis 型）、表块
行号绝对化、统计分域分 chunk_type 字符/token 精算、markdown 统计档输出。

2026-09-18 抽取质量改造轮（零 API 纯本地；动因=词法重排评测失分证据
S16/S17/B04）：①题注回溯可跨下标残行吸收续行（Table 号+完整题注入
locator/语境，题注与表体之间的残片并入题注文本）；②表格序列化保结构——
跨行散落表头按值列聚类重建逻辑列，数据行以「列名 = 值」逐行序列化（TDD
宽表同基名列折叠为紧凑形），解析不动退原 pipe 行绝不丢表；③表块新增
摘要行+中文语境关键词行（静态术语表，无任何外部调用），块首带
LTE/NR 族标签；④公式规范形词典——36.213/38.213 功控族 clause 按签名
注入规范公式+变量表+中文语境（B04 型 unicode 数学符号 PDF 抽取损耗的
语料侧补救）；⑤行内 "## " 占位与 \x01-\x1f 控制字符假代符号清理；
⑥监管件 =tbl> 边界表格规整为「指标=值」行（.doc 直转残留）。

2026-09-22 期1 扩库防护轮：DEFAULTS 增 gpp_exclude_files 默认排除清单（期1
7 件 TS 与现役 12 件同目录同文件名形态，防默认全量复跑误并；期1 件走
scripts/chunk_phase1.py 白名单驱动独立落 chunks/期1-pm-rrm.jsonl）。

2026-09-26 B3 重切轮（枚举全列保真）：chunk_asn1_cards 取值域去 >20 截短
「…共N项」——截短域过不了取值域真值差分闸（149 张共N项卡全落低桶的机理），
与 2026-09-25 C3 轮 3 张 21 值卡全列保真先例对齐；配套 fixture 增 >20 值
枚举用例锁全列输出。本改动对 ≤20 值卡零影响（输出逐字不变）。

用法：
  python3 chunk_public.py                      # 全量（监管+3GPP）
  python3 chunk_public.py --domain 3gpp        # 只切 3GPP
  python3 chunk_public.py --config my.json --stats
"""
import argparse
import datetime
import json
import os
import re
import sys

import pipeline_config
from chunk_id import assign_ids, find_duplicate_ids, write_jsonl

# ---------------------------------------------------------------------------
# 配置（模块默认 → --config JSON 覆盖；路径相对 BASE_DIR=建库/，绝对路径原样）
# 与 pipeline_config 的关系：价格/红线默认值取其 DEFAULTS（同一口径），但本模块
# 的切块参数键集独立（pipeline_config 键集校验拒绝未知键，不能塞私键进去）。
# ---------------------------------------------------------------------------
_PRICE_DEFAULT = pipeline_config.DEFAULTS["price_per_mtok"]

DEFAULTS = {
    # 输入（只读）
    "miit_raw_dir": "L3/raw",
    "gpp_raw_dir": "raw/3gpp",
    "gpp_asn1_dir": "raw/3gpp/asn1",
    "gpp_manifest": "raw/3gpp/清单.md",
    # 默认全量扫描排除清单（2026-09-22 期1 扩库防护，报告四.6 隐患闭环）：
    # 期1 7 件 TS md 与现役 12 件同落 raw/3gpp/，文件名同形（TSxx.yyy-Vnn.md），
    # _RE_GPP_FILE 按名全收——不加排除则任何默认全量复跑会把期1 件并进现役
    # chunks/3gpp.jsonl（未经决策的语料混入+vectors 漂移风险）。期1 件走
    # chunk_phase1.py（自带白名单+独立输出位 chunks/期1-pm-rrm.jsonl）；
    # 若决策并入现役，删此清单相应项即可（--config 覆盖为 [] 同效）。
    "gpp_exclude_files": [
        "TS32.423-V18.md", "TS32.425-V18.md", "TS32.432-V18.md",
        "TS28.552-V18.md", "TS28.554-V18.md", "TS36.133-V18.md",
        "TS38.133-V18.md",
    ],
    # 输出（整文件重写）
    "out_miit": "chunks/监管.jsonl",
    "out_gpp": "chunks/3gpp.jsonl",
    "out_stats": "chunks/切块统计.json",
    "out_report": "logs/切块统计-公开源一期.md",
    # 内容哈希 id（chunk_id.py 口径；须含 content）
    "id_fields": ["source_domain", "doc_id", "version", "chunk_type",
                  "locator", "line_no", "content"],
    "locator_fields": ["source_domain", "doc_id", "chunk_type", "locator", "line_no"],
    "id_len": 16,
    # 切块参数
    "clause_max_chars": 6000,     # 3GPP 单 clause 块超长分段阈值
    "clause_min_chars": 20,       # 过短 clause 不成块（标题并入统计）
    "table_group_rows": 6,        # 大表行组：每组数据行数
    "table_max_chars": 2600,      # 表整体不超此字符量则整表一块
    "skip_annex_titles": ["change history"],   # 跳过的 annex（编史噪声表）
    # 2026-09-18 抽取质量改造轮开关（均可用 --config JSON 覆盖关闭）
    "table_serialize": True,      # 表格逻辑列重建 + 列名=值 序列化（解析不动退原 pipe 行）
    "table_ctx_line": True,       # 表块摘要行 + 中文语境关键词行（静态术语表，零 API）
    # 2026-10-13 杠杆2（过程日志70③案甲决策）：表格保形双形态——序列化 KV 不动，
    # 块尾追加 markdown 管道表段（表格原文，chunker 侧从表格模型直出=保真非反推）。
    # 默认 False=现行为逐字节不变；段超 table_pipe_max_chars 弃置该块管道段（纯 KV）。
    "table_pipe_dual": False,
    "table_pipe_max_chars": 1200,
    "formula_glossary": True,     # 功控族公式规范形词典注入（签名匹配才注）
    # token/费用估算（不触 API；en=英文 4 字符/token，cjk=中文旧库实测锚）
    "token_ratio_low": 0.5,       # 双档：token/字符 低档（粗估参照）
    "token_ratio_high": 0.8,      # 双档：token/字符 高档（粗估参照）
    "token_ratio_en": 0.25,       # 语种精算档：英文 3GPP
    "token_ratio_cjk": 0.63,      # 语种精算档：中文监管（旧库实测锚）
    "price_per_mtok": _PRICE_DEFAULT,
}

# 3GPP 12 件主题词（doc_title；件号→人读标题，建库时点静态事实）
TITLE_3GPP = {
    "TS 36.300": "E-UTRA 总体描述（Stage 2）",
    "TS 36.211": "E-UTRA 物理信道与调制",
    "TS 36.213": "E-UTRA 物理层过程",
    "TS 36.214": "E-UTRA 物理层测量",
    "TS 36.321": "E-UTRA MAC 协议",
    "TS 36.331": "E-UTRA RRC 协议（含测量事件与 ASN.1 参数）",
    "TS 38.300": "NR 总体描述（Stage 2）",
    "TS 38.211": "NR 物理信道与调制",
    "TS 38.213": "NR 物理层过程（控制）",
    "TS 38.214": "NR 物理层过程（数据，CSI/波束管理）",
    "TS 38.215": "NR 测量",
    "TS 38.331": "NR RRC 协议（含测量事件与 ASN.1 参数）",
}

# 监管三件登记（终态事实：doc_id/日期/现行性口径；未登记件走保守兜底口径）
MIIT_REGISTRY = {
    "01": {"doc_id": "信息产业部令第36号",
           "doc_title": "电信服务规范（信息产业部令第 36 号）",
           "chapter": "电信服务规范",
           "version": "2005（发文年份）",
           "pub_date": "2005-03-13",
           "effective_status": "历史口径待核（2005 年规章；现行性待核，引用前须核对最新版本）",
           "theme": "电信服务质量与通信质量标准：正文二十一条＋附录 1-8 分业务标准"
                    "（固定电话/数字蜂窝移动/因特网数据传送/IP 电话/无线寻呼/租用信道等）"},
    "02": {"doc_id": "工信部联通信〔2023〕257号",
           "doc_title": "“信号升格”专项行动通知（十一部门联发）",
           "chapter": "信号升格专项行动",
           "version": "2023（发文年份）",
           "pub_date": "2023-12-27",
           "effective_status": "现行有效（专项行动；2024/2025 两档到期目标，到期后口径以后续文件为准）",
           "theme": "移动网络深度覆盖专项行动：重点场景覆盖（政务/文旅/医疗/高校/交通/地铁/"
                    "公铁水路/商超/住宅/楼宇/乡镇农村）与 2024/2025 速率目标"},
    "03": {"doc_id": "2025年通信业统计公报",
           "doc_title": "2025 年通信业统计公报（工业和信息化部，2026-01 发布）",
           "chapter": "通信业统计公报",
           "version": "2026-01（发布）",
           "pub_date": "2026-01-28",
           "effective_status": "现行（2025 年数据为初步统计数；统计不含港澳台；部分数据四舍五入）",
           "theme": "通信业年度统计：行业总体/用户发展/电信业务量/网络基础设施/区域发展"},
    # 04：2026-10-01 季度现行性巡检决策②入库（官方 PDF 直读；指标表为图片，关键值
    # 媒体多源一致登记待核——详见 04 md 元数据与 运营/现行性巡检-20261001.md）
    "04": {"doc_id": "工信部规〔2026〕188号",
           "doc_title": "信息通信行业发展“十五五”规划（工业和信息化部，2026-08-12 印发）",
           "chapter": "信息通信行业十五五规划",
           "version": "2026（发文年份）",
           "pub_date": "2026-08-12",
           "effective_status": "现行有效（“十五五”期 2026-2030 信息通信行业顶层规划；"
                              "“主要指标”表为官方 PDF 内图片，文本层不含表值）",
           "theme": "信息通信业“十五五”顶层规划：2030 全面建成覆盖完善性能领先新一代通信网"
                    "（关键指标媒体共识待核图片表：行业收入 4.1 万亿元/五年累计投资 3.8 万亿元/"
                    "智能算力 9800 EFLOPS/每万人 5G 基站 50 个/5G 用户普及率 95%/移动物联网终端 38 亿）；"
                    "九方面重点任务：双万兆演进/5G-A 县级以上连续覆盖/万兆光网试点/算存协同毫秒用算/"
                    "6G 创新适时商用/星地融合/融合应用/应急通信/绿色低碳；接续“信号升格”专项行动"},
    # 05：2026-10-01 决策②补录轮入库（H1 原案经微信转载直读获得，五节全+多源数字互证；
    # 原发页 JS 不可直读，03 件同先例转载承重）——详见 05 md 元数据
    "05": {"doc_id": "2026年上半年通信业经济运行情况",
           "doc_title": "2026 年上半年通信业经济运行情况（工业和信息化部运行监测协调局，2026-07-31 披露）",
           "chapter": "通信业经济运行情况",
           "version": "2026-07（披露）",
           "pub_date": "2026-07-31",
           "effective_status": "现行（上半年累计口径；后续月度/累计件发布后以最新为准）",
           "theme": "通信业半年度统计：电信业务收入 8873 亿元（-2.1%）/业务总量 +7.7%；"
                    "用户发展：宽带 7.01 亿户、千兆 2.58 亿户（36.8%）、移动电话 18.44 亿、"
                    "5G 用户 12.88 亿（69.9%）、移动物联网终端 29.94 亿；业务使用：移动互联网流量 "
                    "2197 亿GB（+17.7%）、6 月 DOU 23.57GB；通信能力：5G 基站 510.2 万个（39.1%）、"
                    "光缆 7612 万公里、FTTH/O 端口占 96.6%；地区发展（东中西东北渗透率与流量）"},
}

_MONTHS = {m.lower(): i + 1 for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"])}


# ---------------------------------------------------------------------------
# 2026-09-18 抽取质量改造：族标签 / 符号规整 / 中文语境 / 公式规范形
# （全部静态规则，零 API 零联网；只做确定性转写修复，不臆造内容）
# ---------------------------------------------------------------------------
_FAMILY_TAG = (("TS 36.", "LTE"), ("TS 38.", "NR"))


def _family(doc_id):
    """TS 36.x→LTE / TS 38.x→NR（中文题面常带 4G/5G 族词，块首要对得上）。"""
    for pre, tag in _FAMILY_TAG:
        if doc_id.startswith(pre):
            return tag
    return ""


# 表头/题注内 unicode 数学符号的 PDF 抽取损耗规整（δ_PUSCH,c 型下标归位）。
# 只用于题注与合并表头（短文本、模式确定），不用于 clause 正文（乱序线性化
# 无法靠正则安全复原，正文公式走 FORMULA_GLOSSARY 规范形注入）。
_SYM_RULES = [
    # "δ [dB] only DCI format PUSCH,c" → "δ_PUSCH,c [dB] only DCI format"
    (re.compile(r"([δαΔβ])\s*\[dB\]\s*(only DCI format)\s+"
                r"(PUSCH|PUCCH|SRS|PRACH),([a-z])"), r"\1_\3,\4 [dB] \2"),
    # 题注 δ 漂移（5.1.2.1-1 型）："δ 1A/1B/…/1G to values PUCCH" → "…to values δ_PUCCH"
    (re.compile(r"\b([δαΔβ])\s+((?:[0-9A-Za-z]+/)+[0-9A-Za-z]+)\s+to\s+"
                r"((?:absolute\s+and\s+)?(?:accumulated\s+)?values)\s+"
                r"(PUSCH|PUCCH|SRS|PRACH)"), r"\2 to \3 \1_\4"),
    # "δ [dB] PUSCH,c" / "δ [dB] PUCCH" → "δ_PUSCH,c [dB]" / "δ_PUCCH [dB]"
    (re.compile(r"([δαΔβ])\s*\[dB\]\s*(PUSCH|PUCCH|SRS|PRACH)(,([a-z]))?"),
     r"\1_\2\3 [dB]"),
    # 闭合 ] 散落到他行的变体："δ [dB PUSCH,c"（及尾随 " ]"）
    (re.compile(r"([δαΔβ])\s*\[dB\s*(PUSCH|PUCCH|SRS|PRACH),([a-z])\s*\]"),
     r"\1_\2,\3 [dB]"),
    (re.compile(r"([δαΔβ])\s*\[dB\s*(PUSCH|PUCCH|SRS|PRACH),([a-z])"),
     r"\1_\2,\3 [dB"),
    # 题注下标残片行拼接后："δ c PUSCH ," → "δ_PUSCH,c"
    (re.compile(r"([δαΔβ])\s+([a-z])\s+(PUSCH|PUCCH|SRS|PRACH)\s*,?\s*$"),
     r"\1_\3,\2"),
    (re.compile(r"([δαΔβ])\s+([a-z])\s+(PUSCH|PUCCH|SRS|PRACH)\s*,"), r"\1_\3,\2,"),
    # "K PUSCH" / "M SRS" 型断行残片
    (re.compile(r"\b([KM])\s+(PUSCH|PUCCH|SRS|PRACH)\b"), r"\1_\2"),
    # 题注断词 "…6-0A/3B/7-0A/7-\n0B…" 拼接后的 "7- 0B" → "7-0B"
    (re.compile(r"(\d)- (?=[0-9A-Za-z])"), r"\1-"),
]


def _norm_syms(text):
    """题注/表头符号规整（幂等：先规则后空白折叠）。"""
    for pat, rep in _SYM_RULES:
        text = pat.sub(rep, text)
    return re.sub(r"\s{2,}", " ", text).strip()


# 中文语境关键词静态术语表（表格摘要行用；多词优先，编译期排序）
_ZH_TERM_PAIRS = [
    ("power control", "功率控制"), ("transmit power", "发射功率"),
    ("tpc command", "TPC 命令（发射功率控制命令）"), ("tpc", "TPC 功控命令"),
    ("accumulated", "累积"), ("absolute", "绝对"),
    ("uplink", "上行"), ("downlink", "下行"),
    ("random access", "随机接入"), ("preamble", "前导码（前导序列）"),
    ("path loss", "路损（路径损耗）"), ("pusch", "物理上行共享信道 PUSCH"),
    ("pucch", "物理上行控制信道 PUCCH"), ("prach", "物理随机接入信道 PRACH"),
    ("srs", "探测参考信号 SRS"), ("cqi", "信道质量指示 CQI"),
    ("modulation", "调制方式"), ("code rate", "码率"), ("efficiency", "频谱效率"),
    ("sub-band", "子带"), ("offset", "偏置"), ("timing", "定时"),
    ("subframe", "子帧"), ("slot", "时隙"), ("symbol", "符号"),
    ("bandwidth", "带宽"), ("resource block", "资源块"),
    ("harq", "混合自动重传 HARQ"), ("csi", "信道状态信息 CSI"),
    ("rsrp", "参考信号接收功率 RSRP"), ("rsrq", "参考信号接收质量 RSRQ"),
    ("dci format", "DCI 格式"), ("configuration", "配置"),
    ("measurement", "测量"), ("scheduling", "调度"), ("allocation", "分配"),
    ("mapping", "映射"), ("carrier", "载波"), ("antenna", "天线端口"),
]
_ZH_TERMS = sorted(
    ((re.compile(r"\b%s\b" % re.escape(en), re.I), zh) for en, zh in _ZH_TERM_PAIRS),
    key=lambda x: -len(x[0].pattern))


def _zh_keywords(text, limit=12):
    """文本 → 命中的中文语境词条（去重、保序、封顶）。"""
    out = []
    for pat, zh in _ZH_TERMS:
        if zh in out:
            continue
        if pat.search(text):
            out.append(zh)
            if len(out) >= limit:
                break
    return out


# 公式规范形词典：PDF 抽取把公式线性化打乱（下标/括号散行、## 占位、
# \x01-\x1f 控制字符假代符号），语料侧以「签名匹配→注入规范形」补救。
# 签名 = 打乱文本中稳定保留的 token（须全部命中才注入，防错版误注）。
FORMULA_GLOSSARY = [
    {"doc": "TS 36.213", "clause": "5.1.1.1",
     "sig": ["The setting of the UE Transmit power for a Physical Uplink Shared Channel"],
     "formula": "P_PUSCH,c(i) = min{ P_CMAX,c(i), 10log10(M_PUSCH,c(i)) + "
                "P_O_PUSCH,c(j) + alpha_c(j)*PL_c + delta_TF,c(i) + f_c(i) } [dBm]",
     "vars": "P_CMAX,c(i)=configured UE transmit power（配置 UE 发射功率）；"
             "M_PUSCH,c(i)=PUSCH 传输带宽（资源块数）；P_O_PUSCH,c(j)=目标接收功率基值"
             "（高层参数）；alpha_c(j)=路损补偿因子；PL_c=下行路损估计；"
             "delta_TF,c(i)=MCS 相关功率偏移；f_c(i)=TPC 调整函数（累积/绝对，"
             "见 Table 5.1.1.1-2/-3）",
     "zh": "LTE PUSCH 上行功控 发射功率 TPC 命令 累积 调整"},
    {"doc": "TS 36.213", "clause": "5.1.2.1",
     "sig": ["the setting of the UE Transmit power"],
     "formula": "P_PUCCH,b(i) = min{ P_CMAX,c(i), P_O_PUCCH,b + delta_F,PUCCH(F) "
                "+ delta_TxD(c) + g_b(i) } [dBm]（PUCCH format 1/1a/1b/2/2a/2b/3；"
                "format 4/5 另含 10log10(M_PUCCH,c(i)) 项）",
     "vars": "g_b(i)=PUCCH TPC 累积调整命令（映射见 Table 5.1.2.1-1/-2）；"
             "delta_TxD(c) 仅 PUCCH 发射分集配置时计入",
     "zh": "LTE PUCCH 上行控制信道功控 发射功率 TPC 命令"},
    {"doc": "TS 36.213", "clause": "5.1.3.1",
     "sig": ["The setting of the UE Transmit power"],
     "formula": "P_SRS,c(i) = min{ P_CMAX,c(i), P_SRS_OFFSET,c(m) + "
                "10log10(M_SRS,c) + alpha_c*PL_c + f_c(i) } [dBm]",
     "vars": "P_SRS_OFFSET,c(m)=SRS 功率偏移（m=0/1 对应 trigger type 0/1 等场景，"
             "高层半静态配置）；M_SRS,c=SRS 带宽（资源块数）；f_c(i)=PUSCH TPC "
             "调整函数（无 PUSCH/PUCCH 配置等场景的基值变体见原文 P_O_PUSCH 形）",
     "zh": "LTE SRS 探测参考信号 上行功控 发射功率"},
    {"doc": "TS 36.213", "clause": "6.1",
     "sig": ["PPRACH = min{", "PREAMBLE_RECEIVED_TARGET_POWER"],
     "formula": "P_PRACH = min{ P_CMAX,c(i), PREAMBLE_RECEIVED_TARGET_POWER + PL_c } [dBm]",
     "vars": "P_CMAX,c(i)=configured UE transmit power（配置 UE 发射功率，子帧 i "
             "服务小区 c，见 [6]）；PL_c=downlink path loss estimate（UE 估算的"
             "服务小区 c 下行路损）；PREAMBLE_RECEIVED_TARGET_POWER 由高层按 "
             "PREAMBLE_RECEIVED_TARGET_POWER + DELTA_PREAMBLE + (PREAMBLE_TRANSMISSION_"
             "COUNTER–1)*powerRampingStep 逐次爬坡",
     "zh": "LTE PRACH 随机接入 前导发射功率 功率控制 功率爬坡"},
    {"doc": "TS 38.213", "clause": "7.1.1",
     "sig": ["the UE determines the PUSCH transmission power"],
     "formula": "P_PUSCH,b,f,c(i,j,q_d,l) = min{ P_CMAX,f,c(i), P_O_PUSCH,b,f,c(q_d) "
                "+ 10log10(2^mu * M_RB,b,f,c(i,j)) + alpha_b,f,c(q_d)*PL_b,f,c(q_d) "
                "+ delta_TF,b,f,c(i) + f_b,f,c(i,j,l) } [dBm]",
     "vars": "b/f/c=BWP/载波/服务小区；i/j=符号组/PUSCH 传输时机；q_d=路损参考"
             "索引；l=功控调整态索引；M_RB=资源块数；mu=子载波间隔参数；"
             "f_b,f,c(i,j,l)=TPC 累积/绝对调整（映射见 38.213 Table 7.1.1-1/-2）",
     "zh": "NR PUSCH 上行功控 发射功率 TPC 命令 5G"},
]


def _formula_lines(doc_id, clause_num, region_text, cfg):
    """签名匹配的规范公式行（注入 clause 块首；无匹配返回 []）。"""
    if not cfg.get("formula_glossary", True):
        return []
    out = []
    for ent in FORMULA_GLOSSARY:
        if ent["doc"] != doc_id or ent["clause"] != clause_num:
            continue
        if not all(sig in region_text for sig in ent["sig"]):
            continue
        out.append("公式（规范形）：%s" % ent["formula"])
        out.append("公式变量：%s" % ent["vars"])
        out.append("中文语境：%s" % ent["zh"])
    return out


class ChunkerConfigError(ValueError):
    """本模块配置非法。"""


def load_cfg(path=None):
    """DEFAULTS → JSON 文件覆盖 → 校验。"""
    cfg = dict(DEFAULTS)
    if path is not None:
        with open(pipeline_config.resolve_path(path), encoding="utf-8") as f:
            overlay = json.load(f)
        if not isinstance(overlay, dict):
            raise ChunkerConfigError("配置文件顶层须为对象")
        for k, v in overlay.items():
            if k not in DEFAULTS:
                raise ChunkerConfigError("未知配置键 %r（可用键：%s）" % (k, ", ".join(sorted(DEFAULTS))))
            cfg[k] = v
    if "content" not in cfg["id_fields"]:
        raise ChunkerConfigError("id_fields 须包含 content")
    if not cfg["locator_fields"]:
        raise ChunkerConfigError("locator_fields 不可为空")
    if not 8 <= cfg["id_len"] <= 64:
        raise ChunkerConfigError("id_len 须在 8..64")
    return cfg


def _rp(cfg, key):
    return pipeline_config.resolve_path(cfg[key])


# ---------------------------------------------------------------------------
# 通用
# ---------------------------------------------------------------------------
def _read_lines(path):
    """读 md → 行列表（容错替换字符；NUL 已由取数侧清洗，这里再兜底去掉；
    2026-09-18：\x01-\x1f 控制字符是 PDF 字体映射损耗的假代符号残迹
    （TS36.213 单件实测 2300+ 处），嵌入端不可读，一律剔除）。"""
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read().replace("\x00", "")
    text = text.replace("\t", " ")
    text = re.sub(r"[\x01-\x08\x0b\x0c\x0e-\x1f]", "", text)
    return text.split("\n")


def _mk_chunk(doc, seq, chunk_type, locator, section, content, line_no, line_end,
              sub_part=""):
    """组装单个 chunk dict（新口径 D3 字段 + retrieve.py 旧口径兼容字段）。"""
    seq[0] += 1
    return {
        "source_domain": doc["source_domain"],
        "doc_id": doc["doc_id"],
        "doc_title": doc["doc_title"],
        "version": doc.get("version") or "",
        "pub_date": doc.get("pub_date") or "",
        "effective_status": doc.get("effective_status") or "",
        "chunk_type": chunk_type,
        "locator": locator,
        "section": section,
        "section_seq": seq[0],
        "sub_part": sub_part,
        "line_no": line_no,
        "line_start": line_no,
        "line_end": line_end,
        "src": doc["src"],
        "layer": doc["layer"],
        "corpus_type": doc["corpus_type"],
        "chapter": doc["chapter"],
        "source_url": doc.get("source_url") or "",
        "fetch_date": doc.get("fetch_date") or "",
        "content": content,
    }


# ---------------------------------------------------------------------------
# 监管件（miit）：条→款两级 + 摘要块
# ---------------------------------------------------------------------------
_RE_L1 = re.compile(r"^[一二三四五六七八九十]{1,3}、\s*(\S.*)$")
_RE_L2 = re.compile(r"^（([一二三四五六七八九十]{1,3})）\s*(\S.*)$")
_RE_L3 = re.compile(r"^(\d{1,2})[.．]\s*(\S.*)$")                       # 场景条目 "1.政务中心。"
_RE_ART = re.compile(r"^(第[一二三四五六七八九十百零]{1,4}条)\s*(\S.*)$")
_RE_ANNEX = re.compile(r"^(附录\s*\d+)\s*[:：]?\s*(.*)$")
_RE_ENTRY = re.compile(r"^(\d{1,2}\.\d{1,2}(?:\.\d{1,2}[A-Z]?)?)\s*(\S.*)$")  # x.y / x.y.z
_RE_BULLET = re.compile(r"^[—–]{1,2}\s*(\S.*)$")
_RE_DIGIT = re.compile(r"\d")


def _short(text, n):
    text = re.sub(r"\s+", " ", (text or "")).strip()
    return text[:n] + ("…" if len(text) > n else "")


def _classify_miit(line):
    """一行 → (kind, label, level, head_text) 或 None。

    label 用于 locator；head_text 为该行去掉编号后的正文开头。
    """
    s = line.strip()
    if not s:
        return None
    m = _RE_ANNEX.match(s)
    if m:
        return ("ANNEX", "附录" + re.sub(r"\D", "", m.group(1)), 2, m.group(2))
    m = _RE_ENTRY.match(s)
    if m:
        num, rest = m.group(1), m.group(2)
        depth = num.count(".") + 1
        title = rest.split("。")[0].split("；")[0]
        return ("ENTRY", "%s %s" % (num, _short(title, 18)), depth + 1, rest)
    m = _RE_ART.match(s)
    if m:
        return ("ART", m.group(1), 2, m.group(2))
    m = _RE_L1.match(s)
    if m:
        return ("L1", _short(m.group(1), 22), 1, m.group(1))
    m = _RE_L2.match(s)
    if m:
        return ("L2", "（%s）" % m.group(1), 2, m.group(2))
    m = _RE_L3.match(s)
    if m:
        title = m.group(2).split("。")[0]
        return ("L3", "%s %s" % (m.group(1), _short(title, 16)), 3, m.group(2))
    if _RE_BULLET.match(s):
        return None  # —— 列表行归入当前组正文
    return None


def _sentences_cjk(text):
    """中文句切分（。；分隔，保留句末标点）。"""
    parts = re.split(r"(?<=[。；])", text)
    return [p.strip() for p in parts if p.strip()]


_MIIT_TBL_SEP = re.compile(r"^[:=*\-—\s]*$")


def _miit_table_text(lines):
    """=tbl> 边界内 pipe 行 → 「指标=值」规整行（.doc 直转残留的规整；
    解析不出返回 ""，由调用方按普通行处理）。"""
    rows = []
    for l in lines:
        s = l.strip()
        if not s or not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        while cells and cells[-1] == "":
            cells.pop()
        if not cells or all(_MIIT_TBL_SEP.match(c) for c in cells):
            continue    # 分隔行（| = | 型）与空行
        rows.append(cells)
    if not rows:
        return ""
    hdr, data = rows[0], rows[1:]
    if len(hdr) == 2 and all(len(r) == 2 for r in data):
        return "【指标表：%s→%s】%s" % (
            hdr[0], hdr[1], "；".join("%s=%s" % (r[0], r[1]) for r in data))
    return "【表格】" + "；".join("／".join(r) for r in rows)


def chunk_miit_doc(path, cfg):
    """监管单件切块 → (chunks, doc_stats)。"""
    lines = _read_lines(path)
    fname = os.path.basename(path)
    key = fname[:2]
    reg = MIIT_REGISTRY.get(key)
    # 元数据/正文/尾注 三段切分（首个与末个独立 "---" 行）
    sep_idx = [i for i, l in enumerate(lines) if l.strip() == "---"]
    meta_lines = lines[:sep_idx[0]] if sep_idx else lines[:20]
    body_lines = lines[sep_idx[0] + 1: sep_idx[1]] if len(sep_idx) >= 2 else \
        (lines[sep_idx[0] + 1:] if sep_idx else lines)
    meta_text = "\n".join(meta_lines)
    m = re.search(r"层级[:：]\s*(\S+)", meta_text)
    url_m = re.search(r"https?://\S+", meta_text)
    fetch_date = datetime.date.fromtimestamp(os.path.getmtime(path)).isoformat()
    if reg:
        doc = dict(reg)
    else:  # 未登记件：保守口径
        t = next((l.lstrip("# ").strip() for l in meta_lines + lines if l.startswith("#")), fname)
        doc_m = re.search(r"文号[:：]\s*([^\n（(]+)", meta_text)
        doc = {"doc_id": _short(doc_m.group(1).strip() if doc_m else t, 40),
               "doc_title": t, "chapter": _short(t, 20), "version": "",
               "pub_date": "", "effective_status": "现行性待核（未登记件，默认保守口径）",
               "theme": _short(t, 60)}
    doc.update({"source_domain": "miit", "layer": "公开源", "corpus_type": "监管",
                "src": path, "fetch_date": fetch_date,
                "source_url": (url_m.group(0) if url_m else "")})
    seq = [0]
    chunks = []

    # ---- 结构化：节点栈 + 叶组 ----
    nodes = []           # [{'kind','label','level','line','paras':[...]}]
    stack = []
    intro_paras = []
    cur_para = []

    def flush_para():
        if cur_para:
            if stack:
                stack[-1]["paras"].append("".join(cur_para).strip())
            else:
                intro_paras.append("".join(cur_para).strip())
            del cur_para[:]

    tbl_buf = None    # =tbl> .. >tbl= 边界内的表格行（.doc 直转残留表格）
    for idx, raw in enumerate(body_lines, start=(sep_idx[0] + 2 if sep_idx else 1)):
        line_no = idx
        s = raw.strip()
        if tbl_buf is not None:
            if s == ">tbl=":
                norm = _miit_table_text(tbl_buf)
                tbl_buf = None
                if norm:
                    cur_para.append(norm)
                    flush_para()
                    if stack:
                        stack[-1]["line_end"] = line_no
                continue
            tbl_buf.append(raw)
            if stack:
                stack[-1]["line_end"] = line_no
            continue
        if s == "=tbl>":
            flush_para()
            tbl_buf = []
            continue
        cls = _classify_miit(raw)
        if cls:
            flush_para()
            kind, label, level, head = cls
            # 命名层级（L1/L2/L3/ART/ANNEX/ENTRY）开新节点；ENTRY 深度由编号决定
            while stack and stack[-1]["level"] >= level:
                stack.pop()
            node = {"kind": kind, "label": label, "level": level, "line": line_no,
                    "head": head.strip(), "paras": [], "line_end": line_no}
            nodes.append(node)
            stack.append(node)
        else:
            if not s or s == ">tbl=":   # 后者为旧抽取的表格边界标记行（非正文）
                flush_para()
            else:
                cur_para.append(s)
                if stack:
                    stack[-1]["line_end"] = line_no
    flush_para()

    # 节点全文：head（编号后正文，常即整条内容）+ 后续段
    def node_text(n):
        parts = []
        if n["head"]:
            parts.append(n["head"])
        parts.extend(p for p in n["paras"] if p)
        return "\n".join(parts)

    # 用节点顺序重建父子链（nodes 按出现序，level 严格嵌套）
    parent_of = {}
    anc = []
    for n in nodes:
        while anc and anc[-1]["level"] >= n["level"]:
            anc.pop()
        parent_of[id(n)] = list(anc)
        anc.append(n)

    def locator_of(n):
        chain = parent_of[id(n)] + [n]
        labels = [c["label"] for c in chain]
        # 压缩：纯附录号保留；数字编号若被更深编号包含前缀则可省中间层
        out = []
        for i, lab in enumerate(labels):
            num_m = re.match(r"^(\d+(?:\.\d+)*)\s", lab + " ")
            if num_m and any(re.match(r"^" + re.escape(num_m.group(1)) + r"\.\d",
                                      l) for l in labels[i + 1:]):
                continue
            out.append(lab)
        return " ".join(out)

    def ctx_of(n):
        chain = parent_of[id(n)] + [n]
        return "｜".join("%s %s" % (c["label"], _short(c["head"], 24)) if c["kind"] in ("L2", "L3", "ENTRY", "ART")
                        else c["label"] for c in chain)

    stats = {"file": fname, "counts": {}, "articles": 0, "annexes": 0, "entries": 0}

    # ---- 摘要块 ----
    n_art = sum(1 for n in nodes if n["kind"] == "ART")
    n_annex = sum(1 for n in nodes if n["kind"] == "ANNEX")
    n_entry = sum(1 for n in nodes if n["kind"] == "ENTRY")
    first_line = 1
    # 注：fetch_date（mtime 推得）只入字段不入 content——防源文件被 touch 后
    # 摘要 content 变→id 漂移→无谓重嵌（幂等纪律）。
    summary_content = (
        "【监管文件摘要】%s。文号：%s。发布/成文：%s。主题：%s。"
        "结构：正文条款 %d 条、附录 %d 个、编号条目 %d 项。现行性口径：%s。"
        "来源：%s。"
        % (doc["doc_title"], doc["doc_id"], doc.get("pub_date") or "见文号",
           doc["theme"], n_art, n_annex, n_entry, doc["effective_status"],
           doc.get("source_url") or "（见源文件元数据）"))
    if intro_paras:
        summary_content += "\n文件引言：" + _short("".join(intro_paras), 300)
    chunks.append(_mk_chunk(doc, seq, "summary", "摘要", doc["chapter"],
                            summary_content, first_line,
                            min((nodes[0]["line"] - 1) if nodes else len(lines), 9999)))

    # ---- 条/款两级 ----
    for n in nodes:
        text = node_text(n)
        if not text:
            continue
        loc = locator_of(n)
        ctx = "【" + ctx_of(n) + "】"
        line_no, line_end = n["line"], max(n["line_end"], n["line"])
        chunks.append(_mk_chunk(doc, seq, "条", loc, _short(n["head"], 60),
                                ctx + "\n" + text, line_no, line_end))
        # 二级款：数字句（句序号），条块已含全文的不重复出
        sents = _sentences_cjk(re.sub(r"\n", "", text))
        digit_sents = [s for s in sents if _RE_DIGIT.search(s) and len(s) >= 10]
        if len(sents) == 1:
            continue
        seen = set()
        for k, s in enumerate([x for x in sents if _RE_DIGIT.search(x) and len(x) >= 10], 1):
            if s in seen:
                continue
            seen.add(s)
            chunks.append(_mk_chunk(doc, seq, "款", "%s 款%d" % (loc, k),
                                    _short(s, 80), ctx + "\n" + s, line_no, line_end))
    stats["counts"] = {}
    for c in chunks:
        stats["counts"][c["chunk_type"]] = stats["counts"].get(c["chunk_type"], 0) + 1
    stats["articles"], stats["annexes"], stats["entries"] = n_art, n_annex, n_entry
    return chunks, stats


# ---------------------------------------------------------------------------
# 3GPP 件：clause 切块 + 表格行组 + ASN.1 参数卡
# ---------------------------------------------------------------------------
_RE_HEAD = re.compile(r"^#{2,6}\s+(.+?)\s*$")
_RE_CLAUSE = re.compile(r"^(\d{1,2}(?:\.\d{1,3}){0,5}[A-Za-z]?)\s+(\S.*)$")
_RE_ANNEX_GPP = re.compile(r"^(Annex\s+[A-Z])\s*(?:\((?:informative|normative)\))?\s*:?\s*(.*)$", re.I)
_RE_TOC_DOTS = re.compile(r"\.{4,}")
_RE_CAPTION = re.compile(r"^(Table\s+[0-9A-Za-z.]+-\d+[A-Za-z]?)\s*:?\s*(.*)$", re.I)


def _num_key(num):
    """clause 号 → 可比较元组（5.1.14A/5.2.1.2a → (5,1,14,1) 型；后缀者排本条后）。"""
    comps = []
    parts = num.split(".")
    for i, p in enumerate(parts):
        m = re.match(r"^(\d+)([A-Za-z]?)$", p)
        if not m:
            return None
        comps.append(int(m.group(1)))
        if m.group(2):
            comps.append(1)  # 字母后缀子条排在本条之后（大小写同规）
    return tuple(comps)


def parse_gpp_headings(lines):
    """扫描 markdown 标题 → 接受的 clause/annex 节点列表。

    防公式伪标题（抽取侧把公式行还原成了 ## N xxx 形态）三重闸：
      1) 标题词形：clause 标题须以大写字母开头且 ≥3 字符（"mod"/"8,6,4"/"("类全拒）；
      2) 单调性：clause 号须严格大于前一接受号（文档序），数字段后不再收数字段；
      3) 点导线（ToC 残留 "References ..... 26"）直接跳过。
    """
    accepted = []
    last_num = None
    annex_on = False
    last_annex = None
    rejected = 0
    for i, raw in enumerate(lines):
        m = _RE_HEAD.match(raw.strip())
        if not m:
            continue
        head = m.group(1)
        if _RE_TOC_DOTS.search(head):
            rejected += 1
            continue
        am = _RE_ANNEX_GPP.match(head)
        if am:
            letter = am.group(1).split()[-1].upper()
            if annex_on and letter <= last_annex:
                rejected += 1
                continue
            accepted.append({"num": "Annex %s" % letter,
                             "title": (am.group(2) or "").strip(),
                             "line": i, "kind": "annex"})
            annex_on, last_annex = True, letter
            continue
        if annex_on:
            rejected += 1
            continue
        cm = _RE_CLAUSE.match(head)
        if not cm:
            rejected += 1
            continue
        num, title = cm.group(1), cm.group(2).strip()
        if not re.match(r"^[A-Z]", title) or len(title) < 3:
            rejected += 1
            continue
        key = _num_key(num)
        if key is None or key[0] > 60:
            rejected += 1
            continue
        if last_num is not None and key <= last_num:
            rejected += 1
            continue
        accepted.append({"num": num, "title": title, "line": i, "kind": "clause"})
        last_num = key
    for j, node in enumerate(accepted):
        node["end"] = accepted[j + 1]["line"] if j + 1 < len(accepted) else len(lines)
    return accepted, rejected


_RE_NOISE_PURE = re.compile(r"^[^A-Za-z0-9\u4e00-\u9fff]{1,8}$")


def _gpp_noise(line):
    """3GPP 正文噪声行判定（页码/孤立符号/公式残片/ASN.1 标记）。

    2026-09-18：增补一类——纯数字/比较符/占位井号构成的短行（"## 1 ≥" 型
    公式占位残迹、表值 spillover），嵌入端不可读，直接弃。
    """
    s = line.strip()
    if not s:
        return True
    if re.match(r"^\d{1,4}$", s):
        return True
    if _RE_NOISE_PURE.match(s):
        return True
    if re.match(r"^[A-Za-z]$", s):
        return True
    if re.match(r"^[-–—⋅·]+$", s):
        return True
    if len(s) <= 24 and re.match(r"^[=≤≥+\-*/^_]", s):
        return True
    if len(s) <= 24 and re.fullmatch(r"[\d\s≥≤<>=+\-−.,()#]+", s):
        return True
    if "ASN1START" in s or "ASN1STOP" in s or re.match(r"^--\s*ASN", s):
        return True
    return False


def _clean_gpp_line(line):
    """正文行清洗：伪标题标记还原 + 行内 ## 占位剔除（返回清洗后行）。"""
    s = re.sub(r"^#{2,6}\s+", "", line.strip())
    if "##" in s:
        s = s.replace("## ", "").replace("##", "")
    return s


def _split_table_blocks(region_lines):
    """区域行 → (text_lines, tables)；tables=[{'start','end','lines':[...]}]。

    连续 | 行成表（允许中间夹 1 个空行）；<2 行不成表。
    """
    text_lines = []
    tables = []
    i = 0
    n = len(region_lines)
    while i < n:
        if region_lines[i].lstrip().startswith("|"):
            j = i
            block = [i]
            while j + 1 < n:
                if region_lines[j + 1].lstrip().startswith("|"):
                    j += 1
                    block.append(j)
                elif (not region_lines[j + 1].strip()
                      and j + 2 < n
                      and region_lines[j + 2].lstrip().startswith("|")):
                    j += 2
                    block.append(j - 1)
                    block.append(j)
                else:
                    break
            if len(block) >= 2:
                tables.append({"start": block[0], "end": block[-1],
                               "lines": [region_lines[k] for k in block]})
                i = block[-1] + 1
                continue
        if region_lines[i].strip():
            text_lines.append(region_lines[i])
        i += 1
    return text_lines, tables


def _table_rows(raw_lines):
    """原始 pipe 行 → 单元格行列表（去首尾空单元）。"""
    rows = []
    for l in raw_lines:
        cells = [c.strip() for c in l.strip().strip("|").split("|")]
        while cells and cells[-1] == "":
            cells.pop()
        rows.append(cells)
    return rows


def _sep_row(cells):
    return bool(cells) and all(re.match(r"^:?-{2,}:?$", c) for c in cells if c != "") and \
        any(c for c in cells)


def _short_label(label, n=26):
    """列名截短（行序列化用；词边界优先）。"""
    if len(label) <= n:
        return label
    cut = label.rfind(" ", 0, n)
    return (label[:cut] if cut > n // 2 else label[:n]).rstrip()


def _logical_rows(body):
    """数据行区 → 逻辑行 [{'cells':[...], 'k': 数据区行号}]（非空单元 ≤1 的
    跨行断裂伪影并入前一逻辑行——PDF 逐行吐字的 spillover）。"""
    logical = []
    for k, r in enumerate(body):
        nonempty = [c for c in r if c]
        if logical and len(nonempty) <= 1 and any(logical[-1]["cells"]):
            logical[-1]["cells"].extend(nonempty)
        else:
            logical.append({"cells": list(r), "k": k})
    return logical


def _table_model(rows):
    """pipe 单元行 → 逻辑列模型（2026-09-18 表格保结构核心，解析不动返回 None）。

    步骤：定位分隔行 → 表头区/数据区 →（两列键值表识别：36.214 定义表型，
    题注首行即数据）→ 数据区逻辑行合并 → 后半逻辑行非空单元数众数=逻辑列数
    L → 数据行高填充物理列=值列 → 表头文本（含数据区首行前的表头续行）按
    最近值列聚类合并为 L 个列标签。值行序列化见 _row_line。
    """
    sep_idx = next((k for k, r in enumerate(rows) if _sep_row(r)), None)
    if sep_idx is not None and sep_idx <= 3:
        header_rows, body = rows[:sep_idx], rows[sep_idx + 1:]
        body0 = sep_idx + 1
    else:
        header_rows, body = rows[:1], rows[1:]
        body0 = 1
    kv = False
    if sep_idx is not None and 1 <= sep_idx <= 3:
        # 两列键值表：分隔行前的"表头"行第 2 列是长正文（非列标签）→ 并入数据
        pre_texts = [c for r in rows[:sep_idx] for c in r[1:2] if c]
        post_texts = [c for r in rows[sep_idx + 1:] for c in r[1:2] if c]
        if pre_texts and post_texts and max(len(t) for t in pre_texts) > 60:
            body = rows[:sep_idx] + rows[sep_idx + 1:]
            header_rows, body0, kv = [], 0, True
    if not body:
        return None
    logical = _logical_rows(body)
    counts = [sum(1 for c in lr["cells"] if c) for lr in logical]
    half = counts[len(counts) // 2:] or counts
    mode = {}
    for c in half:
        mode[c] = mode.get(c, 0) + 1
    L = max(mode, key=lambda k: (mode[k], k)) if mode else 0
    if L < 2:
        return None
    data_pos = [i for i, c in enumerate(counts) if c == L]
    if not data_pos:
        return None
    fill = {}
    for i in data_pos:
        for p, cell in enumerate(logical[i]["cells"]):
            if cell:
                fill[p] = fill.get(p, 0) + 1
    vcols = sorted(p for p, n in fill.items() if n >= max(1, int(len(data_pos) * 0.6)))
    if len(vcols) != L:
        return None

    def _bucket(p):
        return min(vcols, key=lambda v: (abs(v - p), v))

    if kv:
        cols = [{"pos": vcols[0], "label": "条目名"}, {"pos": vcols[1], "label": "条目内容"}]
    else:
        vcol_set = set(vcols)

        def _on_vcol(cells):
            """逻辑行有非空单元恰落值列物理位 → 部分数据行；整体错位
            （±1 列漂移）→ 表头续行。"""
            return any(c and p in vcol_set for p, c in enumerate(cells))

        hdr_texts = {p: [] for p in vcols}
        for r in header_rows:
            for p, cell in enumerate(r):
                if cell:
                    hdr_texts[_bucket(p)].append(cell)
        for i in range(data_pos[0]):
            if _on_vcol(logical[i]["cells"]):
                continue       # CQI 0 行型部分数据行（物理位在值列上）
            for p, cell in enumerate(logical[i]["cells"]):
                if cell:
                    hdr_texts[_bucket(p)].append(cell)
        cols = []
        for p in vcols:
            label = _norm_syms(" ".join(hdr_texts[p]))
            toks = label.split(" ")
            if any(re.search(r"[A-Za-z]", t) for t in toks):
                toks = [t for t in toks if not re.fullmatch(r"\d{1,3}", t)]
            label = _norm_syms(" ".join(toks))
            cols.append({"pos": p, "label": label})
        # 数值列名继承最近文字列名（TDD 子帧列：表头文字只写在首物理列位）
        last_alpha = ""
        for c in cols:
            if re.search(r"[A-Za-z]", c["label"]):
                last_alpha = c["label"]
            elif re.fullmatch(r"\d{1,3}", c["label"]) and last_alpha:
                c["label"] = "%s %s" % (last_alpha, c["label"])
        for c in cols:
            if not c["label"]:
                c["label"] = "列%d" % (c["pos"] + 1)
    on_vcol = (lambda cells: True) if kv else (lambda cells: any(
        c and p in set(vcols) for p, c in enumerate(cells)))
    data = []
    for i, lr in enumerate(logical):
        vals = [c for c in lr["cells"] if c]
        if counts[i] == L:
            data.append({"vals": vals, "k": lr["k"], "cells": lr["cells"],
                         "partial": False})
        elif len(vals) >= 2:
            if not kv and i < data_pos[0] and not on_vcol(lr["cells"]):
                continue      # 已并入列标签的表头续行（不重复出）
            # 部分数据行（缺列/合并格断行）：按物理位对列序列化（≈ 标记）
            data.append({"vals": vals, "k": lr["k"], "cells": lr["cells"],
                         "partial": True})
        # len<=1 的断行已被 _logical_rows 折叠
    if not data:
        return None
    return {"L": L, "cols": cols, "data": data, "body0": body0, "kv": kv}


def _row_line(model, entry):
    """一条数据 → 序列化行。满行：「列名 = 值 | …」（TDD 型同基名宽列折叠
    为「基名: i0=v0, i1=v1, …」）；部分行（缺列/合并格断行，≈ 标记）：按
    物理位对列配对，落不到值列的散值缀尾；键值表：「键 = 内容」。"""
    if model.get("kv"):
        return "%s = %s" % (entry["vals"][0],
                            entry["vals"][1] if len(entry["vals"]) > 1 else "")
    if entry.get("partial"):
        by_pos = {c["pos"]: c for c in model["cols"]}
        parts, stray = [], []
        for p, v in enumerate(entry["cells"]):
            if not v:
                continue
            c = by_pos.get(p)
            if c is not None:
                parts.append("%s = %s" % (_short_label(c["label"]), v))
            else:
                stray.append(v)
        line = "≈ " + " | ".join(parts) if parts else "≈ " + " | ".join(stray)
        if parts and stray:
            line += " | " + " | ".join(stray)
        return line
    cols = model["cols"]
    vals = entry["vals"]
    bases = [re.sub(r"\s*\d{1,3}$", "", c["label"]) for c in cols]
    bc = {}
    for b in bases:
        bc[b] = bc.get(b, 0) + 1
    if len(cols) >= 6 and max(bc.values()) >= len(cols) * 0.8:
        base = max(bc, key=lambda b: bc[b])
        parts, run = [], []

        def _flush():
            if run:
                parts.append("%s: %s" % (_short_label(base), ", ".join(
                    "%s=%s" % (suffix, v) for suffix, v in run)))
                del run[:]

        for i, v in enumerate(vals[:len(cols)]):
            if bases[i] == base:
                m = re.search(r"(\d{1,3})$", cols[i]["label"])
                run.append(((m.group(1) if m else str(len(run))), v))
            else:
                _flush()
                parts.append("%s = %s" % (_short_label(cols[i]["label"]), v))
        _flush()
        return " | ".join(parts)
    return " | ".join("%s = %s" % (_short_label(c["label"]), v)
                      for c, v in zip(cols, vals))


def _pipe_cell(v):
    """管道格消毒：竖线/换行会破表——替换为 / 与空格，其余原样（保真不猜值）。"""
    return str(v).replace("|", "/").replace("\r", " ").replace("\n", " ").strip()


def _pipe_lines(model, entries, cfg):
    """table_pipe_dual 开时：块尾追加的 markdown 管道表段（表格原文）。

    仅满行进格（部分行只留在 KV 段——物理位错配不猜，≈ 形态 KV 已承载）；
    键值表出「条目名|条目内容」两列表。段总长（含表头/分隔行）超
    table_pipe_max_chars（默认 1200）→ 整段弃置（该块保持纯 KV=旧行为，
    防 evidence 6000 上限下表密集查询 top5 叠加丢尾）。返回 [] 或
    ["", "表格原文：", header, sep, *数据行]——行形态固定，供配对门闸
    （前缀逐字节相等 + 后缀管道段）确定性剥离核验。
    """
    rows_in = [e for e in entries if not e.get("partial")]
    if not rows_in:
        return []
    if model.get("kv"):
        header = "| 条目名 | 条目内容 |"
        sep = "|" + "|".join([" --- "] * 2) + "|"
        body = ["| %s | %s |" % (
            _pipe_cell(e["vals"][0]),
            _pipe_cell(e["vals"][1] if len(e["vals"]) > 1 else "")) for e in rows_in]
    else:
        labels = [_pipe_cell(c["label"]) or "列%d" % (i + 1)
                  for i, c in enumerate(model["cols"])]
        header = "| %s |" % " | ".join(labels)
        sep = "|" + "|".join([" --- "] * len(labels)) + "|"
        body = ["| %s |" % " | ".join(_pipe_cell(v) for v in e["vals"][:len(labels)])
                for e in rows_in]
    lines = ["", "表格原文：", header, sep] + body
    if sum(len(l) for l in lines) > int(cfg.get("table_pipe_max_chars", 1200)):
        return []
    return lines


def _table_ctx_lines(doc, clause, title, cap, model, cfg):
    """表块摘要行 + 中文语境行（2026-09-18 语境对齐；静态术语表零 API）。"""
    if not cfg.get("table_ctx_line", True):
        return []
    fam = _family(doc["doc_id"])
    cap_txt = _norm_syms(cap[1]) if cap and cap[1] else ""
    if model.get("kv"):
        cols_desc = "两列键值表（第1列=条目名，第2列=条目内容）"
    else:
        cols_desc = "；".join("%d) %s" % (i + 1, _short(c["label"], 48))
                              for i, c in enumerate(model["cols"]))
    zh_src = " ".join([cap_txt, " ".join(c["label"] for c in model["cols"]), title])
    zh = _zh_keywords(zh_src)
    lines = ["表格摘要：本表 %d 列 × %d 数据行；列 = %s。表题：%s" % (
        model["L"], len(model["data"]), cols_desc,
        cap_txt or "（无题注，见表头/语境行）")]
    lines.append("表格语境：%s%s %s clause %s%s%s" % (
        (fam + " ") if fam else "", doc["doc_id"], doc["version"], clause,
        (" " + _short(title, 60)) if title else "",
        ("｜中文关键词：" + "、".join(zh)) if zh else ""))
    return lines


def _raw_ctx_lines(doc, clause, title, cap, cfg):
    """退原 pipe 行表块的最小语境行（无列模型，只有题注/题名/中文关键词；
    内容行保真原样，语义序列化未覆盖的复杂表型）。"""
    if not cfg.get("table_ctx_line", True):
        return []
    fam = _family(doc["doc_id"])
    cap_txt = _norm_syms(cap[1]) if cap and cap[1] else ""
    zh = _zh_keywords(" ".join([cap_txt, title]))
    return ["表格语境：%s%s %s clause %s%s%s（原行保真：合并格/嵌套表型未语义化）" % (
        (fam + " ") if fam else "", doc["doc_id"], doc["version"], clause,
        (" " + _short(title, 60)) if title else "",
        ("｜中文关键词：" + "、".join(zh)) if zh else "")]


def chunk_gpp_tables(doc, seq, clause, tbl_caption, table, chunks, stats,
                     line_base=1, title="", cfg=None):
    """单表切块（2026-09-18 改造）。

    优先走逻辑列模型：块首富化行 + 摘要行 + 中文语境行 + 「列名 = 值」逐行
    序列化（表头跨行散落已按值列聚类重建；TDD 宽列折叠紧凑形；未对列残行
    保原文贴块尾）；模型解析不动或改造开关关闭时退原 pipe 行（绝不丢表）。
    小表整块；大表按数据行分组。

    line_base：table['start'/'end'] 为 clause 区域内相对行号，+line_base 转为
    md 文件 1-based 绝对行号（行级 locator 用）。title：所属 clause 标题（无
    题注表的语境兜底）。cfg：切块配置（table_serialize/table_ctx_line 开关）。
    """
    cfg = cfg or {}
    raw = table["lines"]
    rows = _table_rows(raw)
    width_modal = {}
    for r in rows:
        width_modal[len(r)] = width_modal.get(len(r), 0) + 1
    modal = max(width_modal, key=width_modal.get) if width_modal else 0
    ragged = sum(1 for r in rows if len(r) != modal) > len(rows) * 0.35
    cap_txt = _norm_syms(tbl_caption[1]) if tbl_caption and tbl_caption[1] else ""
    loc = "%s %s" % (clause, tbl_caption[0]) if tbl_caption else "%s 表" % clause
    sec_fb = _short(title, 40) or "整表"
    section_txt = _short(cap_txt or sec_fb, 60)
    fam = _family(doc["doc_id"])
    hdr = "[%s%s %s clause %s 表格 %s%s]" % (
        doc["doc_id"], (" (%s)" % fam) if fam else "", doc["version"], clause,
        tbl_caption[0] if tbl_caption else "",
        (" " + _short(cap_txt, 80)) if cap_txt else "")
    total_chars = sum(len(l) for l in raw)
    ln_start, ln_end = line_base + table["start"], line_base + table["end"]
    grp = doc.get("_grp_rows", 6)

    def _emit(content, locator, section, sub_part=""):
        chunks.append(_mk_chunk(doc, seq, "table_row_group", locator, section,
                                content, ln_start, ln_end, sub_part=sub_part))

    # ---- 逻辑列模型路径 ----
    model = _table_model(rows) if cfg.get("table_serialize", True) else None
    if model is not None:
        ctx_lines = _table_ctx_lines(doc, clause, title, tbl_caption, model, cfg)
        data = model["data"]
        pipe_on = bool(cfg.get("table_pipe_dual", False))

        def _row_block(lo, hi):
            # 杠杆2 双形态：KV 序列化行不动，块尾按开关追加管道表段（表格
            # 原文）；段不参与下方 whole/est 边界判定=块边界与关态逐块一致
            lines = list(ctx_lines) + [_row_line(model, e) for e in data[lo:hi]]
            if pipe_on:
                lines += _pipe_lines(model, data[lo:hi], cfg)
            return lines

        whole = len(data) <= grp + 2
        if not whole:
            est = sum(len(_row_line(model, e)) for e in data) + 400
            whole = est <= doc.get("_tbl_chars", 2600)
        if whole:
            content = "\n".join([hdr] + _row_block(0, len(data)))
            _emit(content, loc, section_txt)
            stats["tables_whole"] += 1
            if ragged:
                stats["tables_whole_ragged"] += 1
            else:
                stats["tables_whole_small"] += 1
        else:
            for gi in range(0, len(data), grp):
                hi = min(gi + grp, len(data))
                content = "\n".join([hdr] + _row_block(gi, hi))
                _emit(content, "%s 行组%d-%d" % (loc, gi + 1, hi),
                      _short("行组 " + "; ".join(
                          str(e["vals"][0]) for e in data[gi:hi] if e["vals"]), 60),
                      sub_part="行组%d" % (gi // grp + 1))
                stats["table_groups"] += 1
        stats["tables_total"] += 1
        stats["tables_serialized"] = stats.get("tables_serialized", 0) + 1
        return

    # ---- 退原 pipe 行（模型解析不动/开关关闭；绝不丢表） ----
    if ragged or len(rows) <= grp + 2 or total_chars <= doc.get("_tbl_chars", 2600):
        content = "\n".join([hdr] + _raw_ctx_lines(doc, clause, title,
                                                    tbl_caption, cfg)) + \
            "\n" + "\n".join(raw)
        _emit(content, loc, section_txt)
        stats["tables_whole"] += 1
        if ragged:
            stats["tables_whole_ragged"] += 1   # 不规则退整表（质量信号）
        else:
            stats["tables_whole_small"] += 1    # 小表整块（设计内行为）
        stats["tables_total"] += 1
        stats["tables_raw_keep"] = stats.get("tables_raw_keep", 0) + 1
        return
    # 分离表头与数据行
    sep_idx = next((k for k, r in enumerate(rows) if _sep_row(r)), None)
    if sep_idx is not None and sep_idx <= 3:
        header_rows, data_rows = rows[:sep_idx], rows[sep_idx + 1:]
        header_raw = raw[:sep_idx]
    else:
        header_rows, data_rows = rows[:1], rows[1:]
        header_raw = raw[:1]
    if not data_rows:
        content = "\n".join([hdr] + _raw_ctx_lines(doc, clause, title,
                                                   tbl_caption, cfg)) + \
            "\n" + "\n".join(raw)
        _emit(content, loc, "整表（无数据行）")
        stats["tables_whole"] += 1
        stats["tables_total"] += 1
        return
    # 逻辑行合并（跨行断裂伪影：非空单元 ≤1 的行并入前一逻辑行）
    logical = []  # [{'cells':[...], 'raw':[...]}]
    for k, r in enumerate(data_rows):
        raw_idx = (sep_idx + 1 if sep_idx is not None else 1) + k
        nonempty = [c for c in r if c]
        if logical and len(nonempty) <= 1 and logical[-1]["cells"]:
            logical[-1]["cells"].extend(nonempty)
            logical[-1]["raw"].append(raw[raw_idx] if raw_idx < len(raw) else "")
        else:
            logical.append({"cells": list(r), "raw": [raw[raw_idx] if raw_idx < len(raw) else ""]})
    for gi in range(0, len(logical), grp):
        part = logical[gi:gi + grp]
        content = "\n".join([hdr] + _raw_ctx_lines(doc, clause, title,
                                                    tbl_caption, cfg)) + \
            "\n" + "\n".join(header_raw) + "\n" + \
            "\n".join(l for p in part for l in p["raw"] if l.strip())
        chunks.append(_mk_chunk(
            doc, seq, "table_row_group",
            "%s 行组%d-%d" % (loc, gi + 1, gi + len(part)),
            _short("行组 " + "; ".join(p["cells"][0] for p in part if p["cells"]), 60),
            content, ln_start, ln_end,
            sub_part="行组%d" % (gi // grp + 1)))
        stats["table_groups"] += 1
    stats["tables_total"] += 1
    stats["tables_raw_keep"] = stats.get("tables_raw_keep", 0) + 1


def _join_paras(text_lines, max_chars):
    """行→段块：噪声行（页码/孤立符号/公式残片）剔除不拼接，段界只认空行；
    超长段在 max_chars 内取最后一个空格软切（无空格才硬切）。

    注：抽取 md 无空行分隔段落，故一个 clause 区域通常聚成连续段块序列，
    按块首富化+max_chars 分段——段块粒度即 clause 级设计的超长分段口径。
    2026-09-18：存留行先过 _clean_gpp_line（伪标题 ## 标记还原/行内 ## 占位
    剔除）再拼接。
    """
    parts, cur = [], []
    for l in text_lines:
        if _gpp_noise(l):
            continue          # 噪声行直接丢（不 flush——公式区逐行 flush 会碎成单词块）
        cur.append(_clean_gpp_line(l))
        if sum(len(x) for x in cur) >= max_chars:
            parts.append(" ".join(cur))
            cur = []
    if cur:
        parts.append(" ".join(cur))
    # 长段软切（max_chars 是上限不是目标：只在超限处切）
    out = []
    for p in parts:
        while len(p) > max_chars:
            cut = p.rfind(" ", int(max_chars * 0.6), max_chars)
            if cut <= 0:
                cut = max_chars
            out.append(p[:cut].rstrip())
            p = p[cut:].lstrip()
        if p:
            out.append(p)
    return out


def _gpp_docinfo(md_path, cfg):
    """文件名/原始件 PDF/变更史/清单 → doc 元数据（版本优先级：PDF 名>变更史>清单>文件名）。"""
    base = os.path.splitext(os.path.basename(md_path))[0]   # TS36.331-V18
    m = re.match(r"^(TS\d{2})\.(\d{3})-V(\d{2})$", base)
    if not m:
        return None
    doc_id = "TS %s.%s" % (m.group(1)[2:], m.group(2))   # "TS 36.331"（带空格形态）
    major = m.group(3)
    exact = None
    # ① 原始件 PDF 文件名 TS36.331-V18.10.0.pdf
    pdf_dir = os.path.join(_rp(cfg, "gpp_raw_dir"), "原始件")
    if os.path.isdir(pdf_dir):
        for fn in os.listdir(pdf_dir):
            pm = re.match(r"^%s-V(\d{2}\.\d{1,2}\.\d{1,2})\.pdf$" % re.escape(base), fn)
            if pm:
                exact = pm.group(1)
                break
    text = "\n".join(_read_lines(md_path))
    # ② 变更史（文件尾 Publication 表；版本单调递增取最大且主版本须与文件名一致）
    pub_date = ""
    if not exact:
        vers = [(tuple(int(x) for x in v.split(".")), v)
                for v in re.findall(r"V(\d{2}\.\d{1,2}\.\d{1,2})", text)
                if v.startswith(major + ".")]
        if vers:
            exact = max(vers)[1]
    if exact:
        mm = re.search(r"V%s[^\n|]*\|?\s*(January|February|March|April|May|June|July|"
                       r"August|September|October|November|December)\s+(\d{4})" % re.escape(exact), text)
        if mm:
            pub_date = "%04d-%02d" % (int(mm.group(2)), _MONTHS[mm.group(1).lower()])
    # ③ 清单.md（source_url 与兜底版本）
    source_url = ""
    man = _rp(cfg, "gpp_manifest")
    if os.path.exists(man):
        man_text = "\n".join(_read_lines(man))
        row = re.search(r"\|\s*%s\s*\|\s*(V[\d.]+)\s*Rel-\d+\s*\|\s*(\S+)\s*\|" % re.escape(doc_id), man_text)
        if row:
            source_url = "https://www.etsi.org/deliver/" + row.group(2)
            if not exact:
                exact = row.group(1)
    version = "Rel-%s V%s" % (major, exact or major)
    return {
        "source_domain": "3gpp", "doc_id": doc_id,
        "doc_title": TITLE_3GPP.get(doc_id, doc_id),
        "chapter": doc_id, "version": version, "pub_date": pub_date,
        "effective_status": "现行（Rel-%s published；现行性按建库时点登记，巡检口径见设计稿 D3）" % major,
        "src": md_path, "layer": "公开源", "corpus_type": "3gpp",
        "source_url": source_url,
        "fetch_date": datetime.date.fromtimestamp(os.path.getmtime(md_path)).isoformat(),
        "_grp_rows": cfg["table_group_rows"], "_tbl_chars": cfg["table_max_chars"],
        "_tbl_serialize": cfg.get("table_serialize", True),
        "_tbl_ctx": cfg.get("table_ctx_line", True),
    }


def build_clause_index(md_path):
    """主文 clause 区域索引（ASN.1 参数卡回查出处 clause 用）→ [(num, text, text_lower)]。

    存小写副本：参数名大小写不敏感匹配（t300/T300），避免逐参数 tolower 全文。
    """
    lines = _read_lines(md_path)
    heads, _ = parse_gpp_headings(lines)
    out = []
    for h in heads:
        body = "\n".join(lines[h["line"] + 1: h["end"]])
        if body:
            out.append((h["num"], body, body.lower()))
    return out


def _find_clause(index, name):
    """参数/IE 名在主文首次出现所在 clause 号（大小写不敏感；None=未命中）。"""
    nl = name.lower()
    for num, text, low in index:
        if nl in low:
            return num
    return None


def chunk_gpp_doc(md_path, cfg, doc=None):
    """3GPP 单件正文切块 → (chunks, doc_stats)。doc 可外部传入（避免重复解析）。"""
    if doc is None:
        doc = _gpp_docinfo(md_path, cfg)
    if doc is None:
        return [], {"file": os.path.basename(md_path), "skipped": "文件名不匹配 TSxx.yyy-Vnn"}
    lines = _read_lines(md_path)
    heads, rejected_heads = parse_gpp_headings(lines)
    seq = [0]
    chunks = []
    stats = {"file": os.path.basename(md_path), "counts": {},
             "tables_total": 0, "tables_whole": 0, "table_groups": 0,
             "tables_whole_small": 0, "tables_whole_ragged": 0,
             "tables_serialized": 0, "tables_raw_keep": 0,
             "formulas_injected": 0,
             "rejected_heads": rejected_heads, "skipped_annex": "",
             "noise_chars_dropped": 0, "doc_id": doc["doc_id"],
             "version": doc["version"], "pub_date": doc["pub_date"]}
    skip_titles = [t.lower() for t in cfg["skip_annex_titles"]]
    # ---- 摘要块（Scope 首段入摘要，题面带件号/版本词可命中）----
    scope_body = ""
    for h in heads:
        if h["num"] == "1":
            scope_body = " ".join(_join_paras(
                [l for l in lines[h["line"] + 1: h["end"]]], 10 ** 9)[:2])[:400]
            break
    fam = _family(doc["doc_id"])
    chunks.append(_mk_chunk(
        doc, seq, "summary", "摘要", "Scope",
        "【3GPP 规范摘要】%s%s（%s）。%s。Scope：%s。现行性：%s。来源：%s" % (
            doc["doc_id"], ("（%s）" % fam) if fam else "", doc["doc_title"],
            doc["version"], _short(scope_body, 360),
            doc["effective_status"], doc.get("source_url") or "见清单"),
        1, (heads[0]["line"] + 1) if heads else 1))
    # ---- clause 区域 ----
    for h in heads:
        region = lines[h["line"] + 1: h["end"]]
        # 2026-09-21 语料修复轮（预研§② 方案 A）：fallback 标题提为全迭代可用。
        # annex 标题行 "## Annex X (informative):" 抓后 group(2) 空，region 首非空
        # 行即标题；clause 类标题经 parse_gpp_headings 闸恒非空，or 短路零开销。
        # section 两处换用本变量；hdr 与表格 title 仍用 h["title"]（保 content 字节不变）。
        title = h["title"] or next((l.strip() for l in region if l.strip()), "")
        if h["kind"] == "annex":
            if any(t in title.lower() for t in skip_titles):
                stats["skipped_annex"] = title
                stats["noise_chars_dropped"] += sum(len(l) for l in region)
                continue
        text_lines, tables = _split_table_blocks(region)
        # 表格题注捕获（2026-09-18：跨下标残行回溯吸收）。题注与表体之间的
        # 短残片行（≤60 字符、非管道）并入题注文本，并从正文区抹除——旧行为
        # 在此处断言"最近非空行即无题注"，致 S16 型表题注整段丢失（8 张表共
        # 用无语境 locator"5.1.1.1 表"）。
        caps = []
        for t in tables:
            cap = None
            k = t["start"] - 1
            steps = 0
            while k >= 0 and steps < 12:
                s = region[k].strip()
                if not s:
                    k -= 1
                    steps += 1
                    continue
                if s.startswith("|"):
                    break                      # 上一张表的行——本表无题注
                cm = _RE_CAPTION.match(s)
                if cm:
                    frag = []
                    for m in range(k + 1, t["start"]):
                        c2 = region[m].strip()
                        if c2 and len(c2) <= 60 and not c2.startswith("|"):
                            frag.append((m, c2))
                    cap = (cm.group(1), _norm_syms(" ".join(
                        [cm.group(2).strip()] + [x for _, x in frag])))
                    for m, _ in frag:
                        region[m] = ""         # 已吸收的残片不再入正文
                    break
                if len(s) > 60:
                    break                      # 长正文行=表引句，不再上溯
                k -= 1                         # 短残片行（下标/断词）——跨过去
                steps += 1
            caps.append(cap)
        text_lines, tables = _split_table_blocks(region)   # 抹除后重切
        parts = _join_paras(text_lines, cfg["clause_max_chars"])
        body_chars = sum(len(p) for p in parts)
        flines = _formula_lines(doc["doc_id"], h["num"],
                                "\n".join(text_lines), cfg)   # 公式规范形注入
        if flines:
            stats["formulas_injected"] += 1
        hdr = "[%s%s %s clause %s %s]" % (
            doc["doc_id"], (" (%s)" % fam) if fam else "", doc["version"],
            h["num"], _short(h["title"], 80))
        if body_chars >= cfg["clause_min_chars"]:
            if len(parts) == 1:
                chunks.append(_mk_chunk(doc, seq, "clause", h["num"],
                                        _short(title, 80),
                                        "\n".join([hdr] + flines + [parts[0]]),
                                        h["line"] + 1, h["end"]))
            else:
                for pi, p in enumerate(parts, 1):
                    pre = flines if (flines and pi == 1) else []
                    chunks.append(_mk_chunk(
                        doc, seq, "clause", "%s (p%d)" % (h["num"], pi),
                        _short(title, 80),
                        "\n".join(["%s [part %d/%d]" % (hdr, pi, len(parts))] + pre + [p]),
                        h["line"] + 1, h["end"], sub_part="p%d" % pi))
        # 表格：题注已在上面按表配对
        line_base = h["line"] + 2   # region[0] 的 1-based 绝对行号
        for t, cap in zip(tables, caps):
            chunk_gpp_tables(doc, seq, h["num"], cap, t, chunks, stats,
                             line_base=line_base, title=h["title"], cfg=cfg)
    stats["counts"] = {}
    for c in chunks:
        stats["counts"][c["chunk_type"]] = stats["counts"].get(c["chunk_type"], 0) + 1
    return chunks, stats


# ---------------------------------------------------------------------------
# ASN.1 参数卡（asn1/ 附件；宁缺毋滥，低把握计数）
# ---------------------------------------------------------------------------
_RE_ASN_IE_DEF = re.compile(
    r"^([A-Za-z][A-Za-z0-9-]*)\s*::=\s*(INTEGER|ENUMERATED|BOOLEAN)\b\s*(.*)$")
_RE_ASN_IE_DEF2 = re.compile(r"^([A-Za-z][A-Za-z0-9-]*)\s*::=\s*$")   # 两行形态头
_RE_ASN_FIELD_DEF = re.compile(
    r"^([a-z][A-Za-z0-9-]*)\s+(INTEGER|ENUMERATED|BOOLEAN)\b\s*(.*)$")
_RE_ASN_TYPE_REF = re.compile(
    r"^([a-z][A-Za-z0-9-]*)\s+([A-Za-z][A-Za-z0-9-]*)\s*[,;]?\s*(?:OPTIONAL|DEFAULT\s+\S+)?\s*$")
_RE_ASN_NAME_ONLY = re.compile(r"^[a-z][A-Za-z0-9-]*$")
_RE_ASN_TYPE_LINE = re.compile(r"^(INTEGER|ENUMERATED|BOOLEAN)\b\s*(.*)$")
_RE_ASN_NAME_LINE2 = re.compile(r"^([A-Za-z][A-Za-z0-9-]*)\s*[,;]?\s*(?:OPTIONAL)?\s*$")
_RE_RANGE = re.compile(r"\(\s*(-?\d+)\s*\.\.\s*(-?\d+)\s*\)")
_RE_STEP_UNIT = re.compile(
    r"actual value is field value\s*\*\s*([\d.]+)\s*(dB|ms|seconds?|meters?)", re.I)
_RE_UNIT_ENUM = re.compile(
    r"[Vv]alue\s+(ms|sf|n)(\d+)\s+corresponds\s+(?:with|to)\s+\d+\s*(ms|subframes?)")
_RE_DESC_HEADER = re.compile(r"^([A-Za-z][A-Za-z0-9-]*)\s+field descriptions\s*$")


def _collect_asn1_typedefs(lines):
    """全文件扫 `X ::= INTEGER(..)/ENUMERATED{..}`（含两行形态）→ {名: 定义 dict}。

    供字段级类型引用解析（如 `hysteresis  Hysteresis,` → INTEGER 0..30）。
    """
    tds = {}
    n = len(lines)
    for i, raw in enumerate(lines):
        line = raw.rstrip()
        if not line.strip() or line.strip().startswith("--"):
            continue
        m = _RE_ASN_IE_DEF.match(line)
        if m:
            name, typ, rest = m.group(1), m.group(2), m.group(3).strip()
        else:
            m2 = _RE_ASN_IE_DEF2.match(line)
            if not m2 or i + 1 >= n:
                continue
            tm = _RE_ASN_TYPE_LINE.match(lines[i + 1].strip())
            if not tm:
                continue
            name, typ, rest = m2.group(1), tm.group(1), tm.group(2).strip()
        if name in tds:
            continue
        rng = None
        if typ == "INTEGER":
            rm = _RE_RANGE.search(rest)
            if rm:
                rng = (int(rm.group(1)), int(rm.group(2)))
        enums = None
        if typ == "ENUMERATED":
            enums = _enum_values(lines, i, rest)
        if rng is None and enums is None:
            continue    # 无取值域的 typedef 不入（宁缺毋滥）
        tds[name] = {"type": typ, "range": rng, "enums": enums}
    return tds


def _enum_values(block_lines, start_idx, after_text):
    """收集 ENUMERATED {...} 枚举值（跨行花括号配平，向后看 60 行）。

    after_text 为类型词之后的同行残段；花括号与值跨行分布时向后拼 60 行再配平。
    两行形态（名字行/字段行 + 独立类型行）下 after_text 即类型行残段，join 须跳过
    类型行本身：否则类型行字面量重新拼入，与 after_text 的 "{" 黏连成首个逗号段，
    被含花括号过滤器整段丢弃 → 首值系统性丢失（2026-09-25 fa3496cb 根因，237 张
    高+中命中卡同源；类型行上带值时同段重拼还会双计）。跳过判据=下一行以类型词
    开头且其残段与 after_text 全同（单行形态的续值行不可能逐字凑巧同段）。
    """
    join_from = start_idx + 1
    if start_idx + 1 < len(block_lines):
        tm = _RE_ASN_TYPE_LINE.match(block_lines[start_idx + 1].strip())
        if tm and tm.group(2).strip() == after_text:
            join_from = start_idx + 2   # 两行形态：类型行已由 after_text 代表，跳过
    text = after_text + "\n" + "\n".join(block_lines[join_from:join_from + 59])
    m = re.search(r"\{", text)
    if not m:
        return None
    seg = text[m.end():]
    end = seg.find("}")
    if end < 0:
        return None
    vals = []
    for v in seg[:end].split(","):
        v = v.strip()
        if not v or v == "..." or v.startswith("--") or "{" in v or "}" in v:
            continue
        vals.append(v)
    return vals or None


def _parse_asn1_params(block_lines, typedefs=None):
    """一个 ASN.1 块 → 参数定义列表 [{name, kind(ie|field), type, type_ref,
    range|None, enums|None, line}]。typedefs 给出时解析类型引用（Hysteresis 型）。"""
    typedefs = typedefs or {}
    out = []

    def _mk(name, kind, typ, rest, line, type_ref=""):
        rng, enums = None, None
        if typ == "INTEGER":
            rm = _RE_RANGE.search(rest)
            if rm:
                rng = (int(rm.group(1)), int(rm.group(2)))
        elif typ == "ENUMERATED":
            enums = _enum_values(block_lines, line, rest)
        if rng is None and enums is None and type_ref:
            td = typedefs.get(type_ref)
            if td:
                typ, rng, enums = td["type"], td["range"], td["enums"]
        return {"name": name, "kind": kind, "type": typ, "type_ref": type_ref,
                "range": rng, "enums": enums, "line": line}

    n = len(block_lines)
    for i, raw in enumerate(block_lines):
        line = raw.rstrip()
        if not line.strip() or line.strip().startswith("--"):
            continue
        m = _RE_ASN_IE_DEF.match(line)
        if m:
            out.append(_mk(m.group(1), "ie", m.group(2), m.group(3).strip(), i))
            continue
        m = _RE_ASN_IE_DEF2.match(line)   # 两行 IE 定义（Hysteresis ::= / INTEGER (0..30)）
        if m and i + 1 < n:
            tm = _RE_ASN_TYPE_LINE.match(block_lines[i + 1].strip())
            if tm:
                out.append(_mk(m.group(1), "ie", tm.group(1), tm.group(2).strip(), i))
                continue
        m = _RE_ASN_FIELD_DEF.match(line)
        if m:
            out.append(_mk(m.group(1), "field", m.group(2), m.group(3).strip(), i))
            continue
        # 类型引用字段：`hysteresis  Hysteresis,`（单行）
        m = _RE_ASN_TYPE_REF.match(line)
        if m and m.group(2) in typedefs:
            out.append(_mk(m.group(1), "field", "", "", i, type_ref=m.group(2)))
            continue
        # 两行形态：字段名单独一行 + 下一有效行以类型词/类型名开头
        if _RE_ASN_NAME_ONLY.match(line.strip()) and i + 1 < n:
            nxt = block_lines[i + 1].strip()
            tm = _RE_ASN_TYPE_LINE.match(nxt)
            if tm and "::=" not in line:
                out.append(_mk(line.strip(), "field", tm.group(1),
                               tm.group(2).strip(), i))
                continue
            nm = _RE_ASN_NAME_LINE2.match(nxt)
            if nm and nm.group(1) in typedefs and "::=" not in line:
                out.append(_mk(line.strip(), "field", "", "", i,
                               type_ref=nm.group(1)))
    return out


def _parse_asn1_descriptions(lines):
    """'XXX field descriptions' 段 → {name: 描述}（斜杠/逗号多名共享；t3xy 类通配名展开）。"""
    descs = {}
    i = 0
    n = len(lines)
    while i < n:
        m = _RE_DESC_HEADER.match(lines[i].strip())
        if m:
            i += 1
            while i < n:
                s = lines[i].strip()
                if (not s or s in ("–", "-") or s.startswith("-- ASN1")
                        or _RE_DESC_HEADER.match(s)):
                    break
                # 名字行：无句末标点、仅字母数字/-/斜杠/逗号/空格
                if (s and not s.endswith((".", ",", ";"))
                        and re.match(r"^[A-Za-z][A-Za-z0-9 ./,\-]{2,90}$", s)):
                    names = [x.strip() for x in re.split(r"[/,]", s) if x.strip()]
                    dparts = []
                    j = i + 1
                    while j < n and lines[j].strip() and not _RE_DESC_HEADER.match(lines[j].strip()):
                        t = lines[j].strip()
                        if t in ("–", "-") or t.startswith("-- ASN1"):
                            break
                        dparts.append(t)
                        j += 1
                    desc = " ".join(dparts)
                    for nm in names:
                        if "x" in nm:
                            pat = re.compile("^" + re.escape(nm).replace(r"\x", ".") + "$", re.I)
                            descs.setdefault("__pat__" + nm, (pat, desc))
                        else:
                            descs[nm] = desc
                    i = j
                    continue
                i += 1
        else:
            i += 1
    return descs


def _lookup_desc(descs, name):
    if name in descs:
        return descs[name]
    for key, val in descs.items():
        if key.startswith("__pat__"):
            pat, desc = val
            if pat.match(name):
                return desc
    return ""


def _unit_step(desc, enums):
    """从字段描述/枚举前缀推单位与步进（推不出返回 None/None）。"""
    unit = step = None
    m = _RE_STEP_UNIT.search(desc)
    if m:
        step, unit = m.group(1), m.group(2)
    m = _RE_UNIT_ENUM.search(desc)
    if not unit and m:
        unit = m.group(3)
    if not unit and enums:
        pre = {re.match(r"^[a-z]+", e).group(0) if re.match(r"^[a-z]+", e) else "" for e in enums}
        if pre == {"ms"}:
            unit = "ms"
        elif pre == {"sf"}:
            unit = "subframe（子帧）"
        elif pre == {"n"}:
            unit = "次数（计数）"
    return unit, step


# 参数卡人口过滤：占位/CHOICE 分支等通用名（非真实可问参数，入卡只稀释语料）
_RE_ASN_JUNK_NAME = re.compile(r"^(dummy\d*|setup|release|true|false|spare\d*)$")


def chunk_asn1_cards(asn1_path, doc, clause_index, cfg):
    """ASN.1 附件 → 参数卡 chunks（宁缺毋滥）。

    人口三闸：①占位/CHOICE 通用名黑名单；②BOOLEAN 或无取值域不入；
    ③同名同值域去重（跨 IE 重复定义只留首张——rrc-TransactionIdentifier
    一类在数十个 IE 里重复定义，参数级检索一张即够）。
    """
    lines = _read_lines(asn1_path)
    descs = _parse_asn1_descriptions(lines)
    typedefs = _collect_asn1_typedefs(lines)
    seq = [0]
    chunks = []
    stats = {"file": os.path.basename(asn1_path), "cards": 0,
             "skipped_no_domain": 0, "skipped_junk": 0, "low_confidence": 0,
             "dupes": 0, "typedefs": len(typedefs)}
    seen = set()
    ie_intro = {}
    # 逐段扫描：-- ASN1START .. -- ASN1STOP 为代码块；块间文字给 IE 名与简介
    i = 0
    n = len(lines)
    cur_ie = ""
    while i < n:
        s = lines[i].strip()
        if s.startswith("-- ASN1START"):
            j = i + 1
            while j < n and not lines[j].strip().startswith("-- ASN1STOP"):
                j += 1
            block = lines[i + 1:j]
            params = _parse_asn1_params(block, typedefs)
            for p in params:
                if _RE_ASN_JUNK_NAME.match(p["name"]):
                    stats["skipped_junk"] += 1
                    continue
                if p["type"] == "BOOLEAN" or (p["range"] is None and p["enums"] is None):
                    stats["skipped_no_domain"] += 1   # 无取值域，不入卡
                    continue
                ie = p["name"] if p["kind"] == "ie" else cur_ie
                key = (p["name"], str(p["range"]), tuple(p["enums"] or ()))
                if key in seen:
                    stats["dupes"] += 1
                    continue
                seen.add(key)
                desc = _lookup_desc(descs, p["name"]) or (
                    ie_intro.get(cur_ie, "") if p["kind"] == "field" else ie_intro.get(p["name"], ""))
                unit, step = _unit_step(desc, p["enums"])
                # 低把握：取值域解析出来了但既无描述也无出处（可信度打折，仍入卡但计数）
                src_clause = _find_clause(clause_index, ie or p["name"]) or ""
                if not desc and not src_clause:
                    stats["low_confidence"] += 1
                # 2026-09-26 B3 重切轮：枚举取值域全列保真（去 >20 截短「…共N项」）——
                # 截短形态过不了 ASN.1 取值域真值差分闸（oracle 对截短域恒非 OK，
                # 149 张共N项卡全落低桶的机理；C3 轮 3 张 21 值卡已以全列保真先例）。
                dom = ("INTEGER %d..%d" % p["range"]) if p["range"] else \
                    ("ENUMERATED {%s}" % ", ".join(p["enums"]))
                step_txt = ("，实际值=字段值×%s %s（步进 %s）" % (step, unit, step)
                            if step else "")
                loc = p["name"]
                content = ("[%s%s %s ASN.1 参数卡 | %s]\n参数：%s%s\n类型：%s%s\n取值域：%s%s%s\n出处：clause %s\n说明：%s"
                           % (doc["doc_id"], (" (%s)" % _family(doc["doc_id"])) if _family(doc["doc_id"]) else "",
                              doc["version"], loc, loc,
                              ("（所属 IE：%s）" % ie) if p["kind"] == "field" and ie else "",
                              p["type"],
                              ("（类型引用 %s）" % p["type_ref"]) if p["type_ref"] else "",
                              dom,
                              ("；单位 %s" % unit) if unit else "", step_txt,
                              src_clause or "（主文未检得，见 ASN.1 附件）", _short(desc, 240) or "—"))
                chunks.append(_mk_chunk(
                    doc, seq, "asn1_card", loc,
                    _short("%s · %s %s" % (ie or p["name"], p["type"],
                                           ("%d..%d" % p["range"]) if p["range"] else "enum"), 60),
                    content, i + p["line"] + 2, j + 1))
                stats["cards"] += 1
            i = j + 1
            continue
        # 块间文字：IE 名行（独立词形态）＋简介（名行到 "information element" 标记间）
        if re.match(r"^[A-Za-z][A-Za-z0-9-]*$", s):
            intro = []
            k = i + 1
            while k < n:
                t = lines[k].strip()
                if (not t or t == "–" or "information element" in t.lower()
                        or t.startswith("-- ASN1") or t.startswith("-- TAG-")):
                    break
                intro.append(t)
                k += 1
            cur_ie = s
            ie_intro[s] = " ".join(intro)
        i += 1
    return chunks, stats


# ---------------------------------------------------------------------------
# 统计与 CLI
# ---------------------------------------------------------------------------
def _chunk_lang(ch):
    """单 chunk 语种画像 → (总字符, CJK 字符)。"""
    text = ch.get("content") or ""
    cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    return len(text), cjk


def _char_profile(chunks):
    chars = cjk = 0
    for c in chunks:
        a, b = _chunk_lang(c)
        chars += a
        cjk += b
    return chars, cjk


def build_stats(runs, cfg):
    """runs: {domain: [(chunks, stats), ...]} → 汇总 dict。

    token 精算口径（主口径）：分语种分档 en/cjk 每 chunk 语种画像加权；
    双档 0.5/0.8 字符粗估仅作参照。by_type 含 chunk 数/字符量/token 量。
    """
    out = {"generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
           "domains": {}, "token_est": {}, "quality": {}}
    price = cfg["price_per_mtok"]
    lo, hi = cfg["token_ratio_low"], cfg["token_ratio_high"]
    en_r, cjk_r = cfg["token_ratio_en"], cfg["token_ratio_cjk"]
    tot_lo = tot_hi = tot_cal = 0.0
    for dom, results in runs.items():
        d = {"chunks": 0, "chars": 0, "by_type": {}, "by_doc": {}}
        dom_cjk = 0
        for chunks, st in results:
            chars, cjk = _char_profile(chunks)
            st["chars"] = chars
            st["cjk_chars"] = cjk
            d["chunks"] += len(chunks)
            d["chars"] += chars
            dom_cjk += cjk
            for c in chunks:
                t = d["by_type"].setdefault(
                    c["chunk_type"], {"chunks": 0, "chars": 0, "cjk_chars": 0,
                                      "tokens": 0.0})
                a, b = _chunk_lang(c)
                t["chunks"] += 1
                t["chars"] += a
                t["cjk_chars"] += b
                t["tokens"] += b * cjk_r + (a - b) * en_r
            key = st.get("file") or (chunks[0]["doc_id"] if chunks else "?")
            d["by_doc"][key] = {"chunks": len(chunks), "chars": chars,
                                "counts": st.get("counts", {}),
                **{k: v for k, v in st.items()
                   if k in ("tables_total", "tables_whole", "table_groups",
                            "tables_whole_small", "tables_whole_ragged",
                            "tables_serialized", "tables_raw_keep",
                            "formulas_injected",
                            "rejected_heads", "skipped_annex", "cards",
                            "skipped_no_domain", "skipped_junk",
                            "low_confidence", "dupes", "typedefs",
                            "articles", "annexes", "entries",
                            "doc_id", "version", "pub_date") and v}}
        d["cjk_chars"] = dom_cjk
        t_lo, t_hi = d["chars"] * lo, d["chars"] * hi
        t_cal = dom_cjk * cjk_r + max(0, d["chars"] - dom_cjk) * en_r
        d["tokens_low"], d["tokens_high"], d["tokens_calibrated"] = t_lo, t_hi, t_cal
        d["cost_low"], d["cost_high"], d["cost_calibrated"] = (
            t_lo / 1e6 * price, t_hi / 1e6 * price, t_cal / 1e6 * price)
        tot_lo += t_lo
        tot_hi += t_hi
        tot_cal += t_cal
        out["domains"][dom] = d
    out["token_est"] = {
        "ratios": {"low": lo, "high": hi, "en": en_r, "cjk": cjk_r},
        "price_per_mtok": price,
        "total": {"tokens_low": tot_lo, "tokens_high": tot_hi, "tokens_calibrated": tot_cal,
                  "cost_low": tot_lo / 1e6 * price, "cost_high": tot_hi / 1e6 * price,
                  "cost_calibrated": tot_cal / 1e6 * price},
    }
    # 质量备注（哪些件表格/ASN.1 质量弱）
    notes = []
    for dom, results in runs.items():
        for chunks, st in results:
            f = st.get("file", "?")
            if st.get("tables_whole", 0) > 0 and dom == "3gpp":
                notes.append("%s：整表块 %d/%d 张（小表整块 %d 设计内；不规则退整表 %d）" % (
                    f, st["tables_whole"], st["tables_total"],
                    st.get("tables_whole_small", 0), st.get("tables_whole_ragged", 0)))
            if st.get("tables_raw_keep", 0):
                notes.append("%s：逻辑列模型解析不动退原 pipe 行 %d/%d 张（保表不丢，语义序列化未覆盖）" % (
                    f, st["tables_raw_keep"], st["tables_total"]))
            if st.get("low_confidence", 0):
                notes.append("%s：ASN.1 低把握参数卡 %d 张（无描述且主文未检得出处）" % (
                    f, st["low_confidence"]))
            if st.get("rejected_heads", 0) > 50:
                notes.append("%s：拒伪标题 %d 个（公式/点导线噪声，已并入正文）" % (
                    f, st["rejected_heads"]))
    out["quality"]["notes"] = notes
    return out


def build_report_md(stats):
    """统计 dict → markdown 统计档（建库/logs/切块统计-公开源一期.md 用）。"""
    te = stats["token_est"]
    L = ["# 切块统计-公开源一期（chunk_public.py 生成）", "",
         "- 生成时间：%s（幂等重切以两 jsonl 为准，本档为快照）" % stats["generated_at"],
         "- token 精算口径：分语种分档（英文 %.2f token/字符、中文 %.2f token/字符，"
         "中文系数=旧库 179.8 万 token 实测锚）；单价 %.2f 元/百万 token；"
         "双档 %.1f/%.1f 字符粗估仅作参照。" % (
             te["ratios"]["en"], te["ratios"]["cjk"], te["price_per_mtok"],
             te["ratios"]["low"], te["ratios"]["high"]), ""]
    for dom, d in stats["domains"].items():
        L.append("## 域 %s：chunk=%d，字符=%d（CJK %d）" % (dom, d["chunks"], d["chars"], d["cjk_chars"]))
        L.append("")
        L.append("| chunk_type | chunk 数 | 字符量 | token 量（精算） | 费用（元） |")
        L.append("|---|---:|---:|---:|---:|")
        for t in sorted(d["by_type"]):
            v = d["by_type"][t]
            L.append("| %s | %d | %d | %.0f | %.3f |" % (
                t, v["chunks"], v["chars"], v["tokens"],
                v["tokens"] / 1e6 * te["price_per_mtok"]))
        L.append("| **小计** | **%d** | **%d** | **%.0f** | **%.3f** |" % (
            d["chunks"], d["chars"], d["tokens_calibrated"], d["cost_calibrated"]))
        L.append("")
        L.append("### 逐件")
        L.append("")
        L.append("| 件 | chunk 数 | 字符 | 分型/备注 |")
        L.append("|---|---:|---:|---|")
        for f, dd in sorted(d["by_doc"].items()):
            extra = []
            if dd.get("doc_id"):
                extra.append("%s %s" % (dd["doc_id"], dd.get("version") or ""))
            extra.extend("%s=%s" % kv for kv in sorted(dd.get("counts", {}).items()))
            for k in ("tables_total", "tables_whole", "tables_whole_small",
                      "tables_whole_ragged", "table_groups", "tables_serialized",
                      "tables_raw_keep", "formulas_injected", "cards",
                      "skipped_no_domain", "skipped_junk", "low_confidence", "dupes",
                      "typedefs", "rejected_heads", "skipped_annex"):
                if dd.get(k) not in (None, "", 0):
                    extra.append("%s=%s" % (k, dd[k]))
            L.append("| %s | %d | %d | %s |" % (f, dd["chunks"], dd["chars"],
                                                _short("; ".join(extra), 150)))
        L.append("")
    tt = te["total"]
    L.append("## 费用精算与决策口径对照")
    L.append("")
    L.append("| 口径 | token | 费用（元） |")
    L.append("|---|---:|---:|")
    L.append("| 语种精算（主口径） | %.0f | %.3f |" % (tt["tokens_calibrated"], tt["cost_calibrated"]))
    L.append("| 双档粗估低档 %.1f/字符 | %.0f | %.3f |" % (
        te["ratios"]["low"], tt["tokens_low"], tt["cost_low"]))
    L.append("| 双档粗估高档 %.1f/字符 | %.0f | %.3f |" % (
        te["ratios"]["high"], tt["tokens_high"], tt["cost_high"]))
    L.append("")
    L.append("- 决策口径对照：过程日志一.8 上修预估 **1.2-1.4 元**（英文 4 字符/token 口径）；"
             "本精算 %.3f 元，%s决策带。归因：决策基数=正文 10.59M 原文字符（未含"
             " ASN.1 参数卡与块首富化开销）；本切块含参数卡约 0.37 元、块首富化与表头"
             "上下文重复约 0.2 元、监管域 0.007 元。" % (
                 tt["cost_calibrated"],
                 "在" if 1.2 <= tt["cost_calibrated"] <= 1.4 else "偏离"))
    L.append("- 红线口径：text-embedding-v4 按量累计红线 5 元（已用约 0.90 元），"
             "本批嵌入后累计预计约 %.2f 元，预警线 4 元内。" % (
                 0.90 + tt["cost_calibrated"]))
    L.append("")
    if stats["quality"]["notes"]:
        L.append("## 质量备注")
        L.append("")
        for note in stats["quality"]["notes"]:
            L.append("- %s" % note)
        L.append("")
    return "\n".join(L)


def print_stats(stats):
    print("=" * 72)
    print("切块统计（%s）" % stats["generated_at"])
    te = stats["token_est"]
    for dom, d in stats["domains"].items():
        print("[%s] chunks=%d chars=%d（CJK %d）" % (dom, d["chunks"], d["chars"], d["cjk_chars"]))
        for t, v in sorted(d["by_type"].items()):
            print("    %-16s %5d chunk %9d chars %9.0f tok" % (
                t, v["chunks"], v["chars"], v["tokens"]))
        for f, dd in sorted(d["by_doc"].items()):
            extra = " ".join("%s=%s" % kv for kv in sorted(dd.items())
                             if kv[0] not in ("chunks", "chars", "counts") and kv[1] not in ("", 0))
            print("    · %-24s chunks=%-4d chars=%-8d %s" % (f[:24], dd["chunks"], dd["chars"], extra))
    print("[token 双档 %.1f/%.1f 每字符] 低档 %.0f tok ≈ %.3f 元；高档 %.0f tok ≈ %.3f 元（单价 %s 元/Mtok）"
          % (te["ratios"]["low"], te["ratios"]["high"],
             te["total"]["tokens_low"], te["total"]["cost_low"],
             te["total"]["tokens_high"], te["total"]["cost_high"], te["price_per_mtok"]))
    print("[语种精算档 en %.2f/cjk %.2f] %.0f tok ≈ %.3f 元（对照决策口径 1.2-1.4 元）"
          % (te["ratios"]["en"], te["ratios"]["cjk"], te["total"]["tokens_calibrated"],
             te["total"]["cost_calibrated"]))
    for note in stats["quality"]["notes"]:
        print("[质量] " + note)
    print("=" * 72)


_RE_GPP_FILE = re.compile(r"^TS\d{2}\.\d{3}-V\d{2}\.md$")


def run_domain(domain, cfg, say=print):
    """切一个域 → [(chunks, stats), ...]；ASN.1 卡并入对应 3GPP 件。"""
    runs = []
    if domain == "miit":
        raw_dir = _rp(cfg, "miit_raw_dir")
        for fn in sorted(os.listdir(raw_dir)):
            if fn.endswith(".md"):
                chunks, st = chunk_miit_doc(os.path.join(raw_dir, fn), cfg)
                runs.append((chunks, st))
                say("[miit] %-44s chunks=%d（条 %s）" % (
                    fn, len(chunks),
                    {k: v for k, v in st["counts"].items()}))
    else:
        raw_dir = _rp(cfg, "gpp_raw_dir")
        asn1_dir = _rp(cfg, "gpp_asn1_dir")
        excluded = set(cfg.get("gpp_exclude_files") or [])
        for fn in sorted(os.listdir(raw_dir)):
            if not fn.endswith(".md") or not _RE_GPP_FILE.match(fn):
                continue          # 清单.md（台账）与子目录不入语料
            if fn in excluded:
                continue          # 默认排除清单（期1 件走 chunk_phase1.py）
            path = os.path.join(raw_dir, fn)
            doc = _gpp_docinfo(path, cfg)
            chunks, st = chunk_gpp_doc(path, cfg, doc=doc)
            say("[3gpp] %-24s chunks=%-4d 表=%d（序列化 %d/退原行 %d；行组 %d/整表 %d）公式注入=%d 拒伪标题=%d%s" % (
                fn, len(chunks), st["tables_total"], st.get("tables_serialized", 0),
                st.get("tables_raw_keep", 0), st["table_groups"], st["tables_whole"],
                st.get("formulas_injected", 0), st["rejected_heads"],
                ("；跳过 " + st["skipped_annex"]) if st["skipped_annex"] else ""))
            # ASN.1 参数卡（RRC 双件；附件名不带 -V18 后缀：TS36.331-ASN1.md）
            base = os.path.splitext(fn)[0]
            asn1_path = next(
                (p for p in (
                    os.path.join(asn1_dir, base + "-ASN1.md"),
                    os.path.join(asn1_dir, re.sub(r"-V\d+$", "", base) + "-ASN1.md"))
                 if os.path.exists(p)), None)
            if doc and asn1_path:
                index = build_clause_index(path)
                cards, ast = chunk_asn1_cards(asn1_path, doc, index, cfg)
                chunks.extend(cards)
                st["counts"]["asn1_card"] = st["counts"].get("asn1_card", 0) + ast["cards"]
                st.update({k: v for k, v in ast.items() if k != "counts"})
                say("        └ ASN.1 参数卡 %d（typedef %d；弃无取值域 %d/占位名 %d，低把握 %d，同名同值域 %d）" % (
                    ast["cards"], ast["typedefs"], ast["skipped_no_domain"],
                    ast["skipped_junk"], ast["low_confidence"], ast["dupes"]))
            runs.append((chunks, st))
    return runs


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="公开源语料库切块器（D2/D3；纯本地零 API 零计费；幂等重切=整文件重写）",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog="""示例：
  python3 chunk_public.py                      # 全量：监管+3GPP → 建库/chunks/
  python3 chunk_public.py --domain 3gpp        # 只切 3GPP（D 交齐后重跑）
  python3 chunk_public.py --stats              # 切完打印统计（token 双档 0.5/0.8+语种校准档）
  python3 chunk_public.py --config my.json     # 输出路径/切块参数可覆盖（模板见 DEFAULTS）""")
    ap.add_argument("--domain", choices=["all", "miit", "3gpp"], default="all",
                    help="切块域（默认 all）")
    ap.add_argument("--config", help="JSON 配置文件（覆盖 DEFAULTS；路径相对 建库/）")
    ap.add_argument("--stats", action="store_true", help="打印切块统计详表")
    args = ap.parse_args(argv)

    try:
        cfg = load_cfg(args.config)
    except (ChunkerConfigError, OSError, ValueError) as e:
        print("错误：配置加载失败：%s" % e, file=sys.stderr)
        return 2

    domains = ["miit", "3gpp"] if args.domain == "all" else [args.domain]
    runs = {}
    for dom in domains:
        results = run_domain(dom, cfg)
        chunks_all = [c for cl, _ in results for c in cl]
        if not chunks_all:
            print("[warn] %s 域未产出任何 chunk（检查 raw 目录 %s）" % (
                dom, _rp(cfg, "miit_raw_dir" if dom == "miit" else "gpp_raw_dir")), file=sys.stderr)
        assigned, dups = assign_ids(chunks_all, cfg["id_fields"], cfg["id_len"])
        dups = dups or find_duplicate_ids(assigned)
        if dups:
            print("错误：id 撞车 %d 组（样例 %s），中止写盘" % (
                len(dups), list(dups)[:3]), file=sys.stderr)
            return 2
        out = _rp(cfg, "out_miit" if dom == "miit" else "out_gpp")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        write_jsonl(out, assigned)
        runs[dom] = results
        print("[写出] %s：%d chunk（id_len=%d，fields=%s）" % (
            out, len(assigned), cfg["id_len"], ",".join(cfg["id_fields"])))

    stats = build_stats(runs, cfg)
    out_stats = _rp(cfg, "out_stats")
    os.makedirs(os.path.dirname(out_stats), exist_ok=True)
    with open(out_stats, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=1)
    print("[写出] 统计 → %s" % out_stats)
    out_report = _rp(cfg, "out_report")
    if out_report:
        os.makedirs(os.path.dirname(out_report), exist_ok=True)
        with open(out_report, "w", encoding="utf-8") as f:
            f.write(build_report_md(stats))
        print("[写出] 统计档 → %s" % out_report)
    te = stats["token_est"]["total"]
    print("[合计] chunk=%d chars=%d；语种精算 %.0f tok（≈%.3f 元，对照决策口径 1.2-1.4 元）；双档粗估 %.0f-%.0f tok（≈%.3f-%.3f 元）"
          % (sum(d["chunks"] for d in stats["domains"].values()),
             sum(d["chars"] for d in stats["domains"].values()),
             te["tokens_calibrated"], te["cost_calibrated"],
             te["tokens_low"], te["tokens_high"], te["cost_low"], te["cost_high"]))
    if args.stats:
        print_stats(stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
