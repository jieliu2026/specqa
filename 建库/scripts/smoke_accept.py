#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
smoke_accept.py —— 公开源语料库一期验收冒烟 harness（2026-09-17，设计稿 D5 落地）

职责
----
按《设计稿-公开源语料库-20260917.md》D5 节的 18 条验收题（三类×6），对
建库/vectors/embeddings.jsonl 做批量真 embedding 检索验收：

  1. 18 条 query 批量向量化（embed_common 通道：退避/维度校验/脱敏；
     pipeline_config 配置：模型/维度/批量/单价/红线）；
  2. 逐条调 retrieve 的 load_library/search（top-10，复用既有余弦检索器，不改它）；
  3. 判定：expect_doc 命中位次 + locator 模式匹配，监管/条款（top-5）与
     参数/表值（top-10 且行级出处）分线；
  4. 报告：逐条表（id/命中 doc+locator/score/位次/判过否）+ 四指标 vs 通过线
     + 总费用，追加落 建库/logs/验收冒烟-公开源一期.md（带时间戳，不覆盖历史）。

题卷同源纪律（硬约束）
----------------------
本模块 QUESTIONS 与人读主档 建库/logs/验收题卷-公开源一期.md 一一对应
（S01-S18 逐字段同源）。**改题必须两处同步改**：先改本文件，再同步题卷 md，
单处改动视为未生效。3GPP 版本号统一留占位，待 raw/3gpp/清单.md 就绪后回填。

计费纪律
--------
- 默认 dry-run：零网络零计费，只打印将做什么（不读密钥文件、不嵌入、不判分）。
- 真跑须显式 --yes：18 条 query 单批约 0.003 元（D5 口径），走 embed_common
  通道与 pipeline_config 配置；每批后核红线（red_line_cny 熔断）。
- 用量登记：token 数与费用落报告档尾部（本 harness 不写 embed用量.jsonl，
  避免混入建库台账；对账以 建库/logs/验收冒烟-公开源一期.md 为准）。

退出码
------
0 = 跑完且四通过线全过；1 = 跑完但有通过线未过；2 = 前置失败（库未建/配置错）。
dry-run 与 --self-test 恒零网络（库缺失时 dry-run 仅警示仍退 0，真跑才退 2）。
外部题卷模式（--questions-file）同口径：2 含题卷文件/schema 非法；设通过线的卷
有线未过 → 1；未设线的卷（B/C/Y 现档均未设）不计入 0/1 判定；expect_miss 型
"意外命中"只标注不改变退出码（除非卷设了 expect_miss_rate_min 线）；题级
expect_domain（2026-09-19 C 卷实操层翻型件）域 miss 同样只标注，除非卷设
domain_rate_min 线。外部答案盲判模式（--answers-external）零检索零嵌入：前置失败
（须联卷/与 --answers/--compare 互斥/答案文件非法/**题卷含"键占位"占位键**——轮 1
销项④结构检查整通道拒收）退 2，判卷质量不是 harness
失败——跑完恒 0（判卷未过/null 降级只入报告与机读件）。

用法
----
  python3 smoke_accept.py                     # dry-run：打印计划（零网络零计费）
  python3 smoke_accept.py --yes               # 真跑（计费闸放行，约 0.003 元）
  python3 smoke_accept.py --self-test         # 离线自检（假向量夹具，零网络）
  python3 smoke_accept.py --yes --topk 10 --report-path /tmp/r.md
  python3 smoke_accept.py --yes --vectors <路径>
                                              # 指定待评库（默认 pipeline_config 的
                                              #   out_vecs=建库/vectors/embeddings.jsonl）
  python3 smoke_accept.py --yes --compare <旧库路径>
                                              # 新旧库 A/B 对比（2026-09-18 重嵌前置件）：
                                              #   同题卷对 --vectors 待评库与旧库各检索一遍，
                                              #   查询向量化只做一次、两库复用（嵌入费与单库
                                              #   跑一致）；逐题对照表（新/旧 rank、新/旧 top1
                                              #   分、判定变化）+ 新相关率 vs 旧 72.2% 基线；
                                              #   同受 --yes 计费闸约束，退出码按新库四线定
  python3 smoke_accept.py --questions-file scripts/题卷/独立B.json
                                              # 外部题卷模式（2026-09-18 harness 统一化）：
                                              #   加载 JSON 题卷（B/C/Y 卷见 scripts/题卷/）替代
                                              #   内置验收卷 A 跑同套判定——relevance 型四指标
                                              #   （相关率/监管/参数行级/跨域）+ expect_miss 型
                                              #   "miss 即达标"率 + 题级 expect_domain 附加判定
                                              #   （指定域块进 criterion 深度即"域中"，
                                              #   2026-09-19 C 卷实操层翻型件，草稿卷
                                              #   题卷/独立C实操-v2草稿.json）；与 --vectors/
                                              #   --compare 正交
                                              #   组合；可重复给多卷（或单文件含 papers 数组），
                                              #   按卷分别汇总+总表；不给本参数默认行为不变。
                                              #   schema 与判定口径见 logs/评测harness统一-
                                              #   20260918.md；题卷模式报告默认落
                                              #   logs/题卷评测.md（追加式）
  python3 smoke_accept.py --yes --json logs/验收-机读.json
                                              # 机读结果 JSON（2026-09-23 深度提升批A3①，
                                              #   schema smoke_accept.json/v1）：卷级 checks 六键+
                                              #   all_pass+pass_lines+库 md5（流式算，库 ~660MB
                                              #   禁整读）+行数；题级 top1_cosine 与 gate_score
                                              #   分列+score_type+top5_ids/scores。md 报表与
                                              #   stdout 口径零变化（仅追加"[json] 已写"一行）；
                                              #   dry-run 不写；rc=2 前置失败不写
  run_sub.sh smoke_accept.py --yes --faithfulness [--limit N]
                                              # faithfulness 代理指标（2026-09-23 批A3③，默认关
                                              #   =零 API 零 import 面）：top-5 证据对题面金标锚
                                              #   的支持度（无答案态，评证据不评生成）；judge 复用
                                              #   批A citation_check 形态，走订阅通道（run_sub.sh
                                              #   注入环境+自带 run_ipv4）；失败/超时/畸形逐题
                                              #   降级 null 不阻塞不改退出码；--faithfulness-timeout
                                              #   默认 15s（本机 flash 实测 ~7.8s，主会话核定）；
                                              #   用量打印+登记 建库/logs/生成用量.jsonl
                                              #   stage=smoke_faithfulness
  run_sub.sh smoke_accept.py --yes --answers [--limit N]
                                              # 生成端答案评测通道（2026-09-28 评测体系第 1 批
                                              #   G1，默认关=零 API 零 import 面）：对带
                                              #   answer_points（或 expected_type=abstain）的题，
                                              #   judge（qwen3.8-flash，enable_thinking=false、
                                              #   temperature=0（G3 终轮起确定性口径），
                                              #   复用 faithfulness 调用骨架/退避/降级纪律）基于
                                              #   top-5 证据生成答案并按固定 rubric 出五维判定
                                              #   （faithfulness/citation/completeness/version/
                                              #   abstention，每维 pass/fail/na；citation 维
                                              #   v2 起可 partial），每题 pass/fail+理由，卷级
                                              #   汇总 faithfulness_rate；失败/超时/畸形先同
                                              #   输入重试 1 次（2026-09-28 轮 1 销项②）再逐题
                                              #   null 降级不改退出码；零 key/无网络环境
                                              #   整通道跳过并在输出注明；用量登记 建库/logs/
                                              #   生成用量.jsonl stage=answer_judge（九键行格式
                                              #   ts/stage/model/batch/n/input_tokens/output_
                                              #   tokens/retries/est_cny）；dry-run 零调用
  run_sub.sh smoke_accept.py --yes --answers --questions-file 题卷/答案卷-1.0.json \
                              --answers-jsonl 建库/logs/answer_judge-轮次名.jsonl
                                              # 材料持久化（2026-09-28 G3 元复核升级
                                              #   前置，仅 --answers 时生效）：逐题落
                                              #   judge 输入 ctx（题面/要点/禁答/引用
                                              #   要求/top-5 证据文本）与输出五维明细
                                              #   （answer/dims/pass/reason），追加式
                                              #   逐题 flush；缺省=logs/answer_judge-
                                              #   <日期>.jsonl；幂等缓存（paper/qid+
                                              #   messages 全文 sha16 同纹免调用复用，
                                              #   null 降级行只留痕不进缓存）；零 judge
                                              #   调用零写
                                              # rubric v2（2026-09-28 G3 校准轮）：citation
                                              #   维增 partial 档（引用指定文档的同族
                                              #   架构文档且实质支撑——G18 型，不单独
                                              #   阻断整题）；reason 核对引用须对照本题
                                              #   citation_req.docs 正主点名（G02 型）
                                              # rubric v3（2026-09-28 G3 终轮）：fail 档
                                              #   加排他条件"清单外且与正主非同族架构
                                              #   关系"（G18/G13 型消歧：同族+实质支撑
                                              #   一律走 partial，不得按清单外 fail）；
                                              #   judge 请求体恒带 temperature=0
                                              #   （G09/G15 型采样波动消除面；通道拒绝
                                              #   该参数时粘性降级不传+日志行留痕）
  run_sub.sh smoke_accept.py --yes \
              --questions-file 运营/J1b盲判-202610/题卷-J1b.json \
              --answers-external 运营/J1b盲判-202610/外部答案-轮1.jsonl \
              --answers-jsonl 建库/logs/answer_external-轮1.jsonl
                                              # 外部答案盲判通道（2026-09-28 J1b 开考
                                              #   工程件，默认关=零 API 零 import 面）：评
                                              #   **已有外部答案**（RAG 臂/裸考臂产出的
                                              #   答案文本，两臂 A/B 匿名或 bare/rag 实名）
                                              #   ——judge 只评审不生成（生成/评审分离，
                                              #   评固定文本天然可复现）。输入 JSONL 每行
                                              #   {qid, arm, answer_text}（arm 归一
                                              #   A/B/bare/rag；answer_text 空=未答按错计
                                              #   零调用，J1b 协议 §1.2-4）；judge 只见
                                              #   题面+answer_points/must_not/citation_req
                                              #   /expected_type+答案文本——盲判口径不见
                                              #   检索证据/金标锚/臂身份（协议 §1.2-1），
                                              #   五维判定同 rubric v3；输出题级 {qid,
                                              #   arm, 五维, pass}+两臂汇总（逐臂 pass 率
                                              #   +恰两臂卷逐题配对+Δpp——J1b Δpp 数据源）
                                              #   +--json 机读（mode=answers_external）；
                                              #   零检索零嵌入（不读库不嵌 query）；幂等
                                              #   缓存/台账纪律同 --answers（qid#arm 入
                                              #   缓存键、stage=answer_judge_external
                                              #   分账）；须联 --questions-file，与
                                              #   --answers/--compare 互斥
                                              # 2026-09-28 J1b 轮 1 销项（轮 2 前置，键回填
                                              #   修复-20260928.md §六.3）：①答案文本截长
                                              #   2000→4000（cfg 键
                                              #   answer_external_text_max_chars 可覆盖）；
                                              #   ②judge 单题失败同输入重试 1 次再 null 降级
                                              #   （null 行留痕不改）；③rubric v3-ext2 同族
                                              #   partial 条款加固（须实引该族文档且实质支撑，
                                              #   仅提及族名不算）；④answer_points 位置加
                                              #   "以卷内实际键文为准"注记+题卷含"键占位"
                                              #   占位键整通道拒收退 2（结构检查）
  python3 smoke_accept.py --yes --json logs/验收-机读.json --snapshot
                                              # 全量版本快照（2026-09-28 第 3 批 D2，默认关=
                                              #   输出逐字节零变化）：--json 顶层追加 "snapshot"
                                              #   运行环境键全集——库 md5/有效行数/坏行/维度、
                                              #   chunks 各源 jsonl 行数、synth prompt 模板
                                              #   文件级 sha16（hex[:16] 形态同 synth_cards，
                                              #   取整文件字节流不与生卡台账值互推）、模型/
                                              #   维度/topk/单价、三条红线值
                                              #   （embed/cr/synth）、harness 自身 sha16、python
                                              #   版本；--compare 模式追加 compare_snapshot+
                                              #   snapshot_diff 两键，md 报表追加"快照对比"段
                                              #   （仅差异键；--snapshot 不给 --json 时摘要仍进
                                              #   md 报表，机读键随 --json 才落盘）
  python3 smoke_accept.py --yes --json logs/验收-机读.json --slices
                                              # 统计切片报告（2026-09-28 第 3 批 E3，默认关=
                                              #   输出逐字节零变化）：四维切片——按 domain
                                              #   （题级 domain，空缺时回退 expect_domain 如
                                              #   合成卡）、按 criterion（top5/top10_locator）、
                                              #   按 category、按难度（note 首词 Basic/
                                              #   Difficult 解析，均无=未标注）；各组给 n/
                                              #   top5_rate/judge_pass_rate 均值（judge_pass
                                              #   对 expect_miss 题=miss 即达标口径）；--json
                                              #   papers[].slices 四键 + md 报表"切片"段
                                              #   （仅有切片差异——该维 ≥2 组——的维度显示）

判卷侧"父-子同文豁免"规则（甲，2026-09-28 S1 负控治理选项一）：try_judge_exempt
（+family_trap_ranks/clause_parent_of 辅助）——型3 子款负控题的形式 FAIL（同款族
父条压入 top-3 构成串号）在"子款正文⊆父条正文"块级同文实证且 top-5 无错误数值块
时不计串号 FAIL；四要件语义对齐 s1_negctrl_eval.try_judge_exempt（离线验证在档：
甲单走销 S1V-15 形式 FAIL），触发留块级同文证据防口径自证；不改既有 relevance/
expect_miss 判定面（对四卷零影响）。
"""
import argparse
import contextlib
import hashlib
import io
import json
import math
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request

import embed_common
import pipeline_config
import retrieve

# 报告默认落点（相对 BASE_DIR）；追加式带时间戳，不覆盖历史
DEFAULT_REPORT_REL = "logs/验收冒烟-公开源一期.md"
# 外部题卷模式（--questions-file）报告默认落点；追加式（与验收卷报告分档，不混写）
PAPER_REPORT_REL = "logs/题卷评测.md"
# 人读题卷主档（同源维护，见 docstring 纪律）
PAPER_PATH_REL = "logs/验收题卷-公开源一期.md"
# 3GPP 版本（2026-09-17 自 raw/3gpp/清单.md 回填，12 件全 Rel-18 published；与 chunks jsonl 的 version 字段同形态）
# 2026-09-27 增 TS 36.101（阶段三 P1 取数 V18.13.0；S16 换锚回带宽-PRB 原题面用）
_3GPP_VERSIONS = {
    "TS 36.101": "Rel-18 V18.13.0",
    "TS 36.211": "Rel-18 V18.0.2", "TS 36.213": "Rel-18 V18.3.0",
    "TS 36.214": "Rel-18 V18.1.0", "TS 36.300": "Rel-18 V18.8.0",
    "TS 36.321": "Rel-18 V18.5.0", "TS 36.331": "Rel-18 V18.10.0",
    "TS 38.211": "Rel-18 V18.9.0", "TS 38.213": "Rel-18 V18.8.0",
    "TS 38.214": "Rel-18 V18.10.0", "TS 38.215": "Rel-18 V18.5.0",
    "TS 38.300": "Rel-18 V18.10.0", "TS 38.331": "Rel-18 V18.10.0",
}

# D5 通过线（卷首汇总同源；改动须同步题卷 md 卷首）
PASS_LINES = {
    "top5_rate_min": 0.80,     # 18 条中预期文档进 top-5 的比例下限
    "monitor_hits_min": 5,     # 监管 6 条（S01-S06）top-5 命中条数下限
    "param_hits_min": 4,       # 参数/表值 6 条（S13-S18）top-10+行级出处条数下限
    "cross_domain_max": 0,     # 跨域污染（top-5 命中落在预期域之外）上限
}

# 旧库 A/B 对照基线（--compare 汇总锚点）：2026-09-17 验收首跑实测，验收卷 top-5
# 相关率 13/18=72.2%（独立卷 B 83.3% 为另一卷，不在本卷内，登记备查）。
OLD_BASELINE_TOP5_RATE = 13 / 18

# ---------------------------------------------------------------------------
# 机读 JSON（--json；2026-09-23 深度提升批A3①）schema 常量
# ---------------------------------------------------------------------------
JSON_SCHEMA_TAG = "smoke_accept.json/v1"
# 内置验收卷 A 在 --json 里归一为单 paper（checks 六键中 expect_miss_rate/
# domain_rate 恒 None——内置卷无此类题亦未设此两线）
BUILTIN_PAPER_ID = "验收卷A(内置)"
# score 口径分列（批A3①核心防坑位）：top1_cosine=检索 rank-1 原始分；gate_score=
# 生产闸门读数口径（证据集内最大余弦）。纯余弦通道两者同值，分列防未来闸门口径
# 演化时混列（口径大坑①）；对拍底账=运营/阈值标定样本-20260922.jsonl（ROC §六.4）。
SCORE_CALIBER = {
    "top1_cosine": "纯余弦 rank-1 原始分",
    "gate_score": "闸门读数口径=证据集内最大余弦；纯余弦通道与 top1_cosine 同值，分列防口径大坑①混列",
}
# 纯余弦 harness score_type 恒此值（枚举对齐 运营/阈值标定样本-20260922.jsonl 实测
# 形态：cosine_top1×83／gate_cosine_max×3——后者仅生产闸门读数出现，本 harness 不产）
SCORE_TYPE_COSINE = "cosine_top1"

# ---------------------------------------------------------------------------
# faithfulness 代理指标（--faithfulness；2026-09-23 深度提升批A3③）常量
# ---------------------------------------------------------------------------
# 语义="top-5 证据对题面金标锚的支持度"（无答案态，评证据不评生成）。与批A 线上
# citation_check（"答案 vs 出处"在线校验）的关系：同一 judge 形态家族、不同评审
# 对象——本件是离线代理指标，线上件是在线答案校验，互不替代。
FAITH_JUDGE_MODEL = "qwen3.8-flash"   # --faithfulness-model 可覆写（授权档同 cr_model）
# judge 单题墙钟预算默认值（秒）：本机 flash 经 run_ipv4 实测 ~7.8s（过程日志档探针），
# citation_check 默认 3s 会系统性超时全 null；主会话 2026-09-23 核定默认 15s
# （云端同域预期秒级，留 ≥2x 余量）。--faithfulness-timeout 可配。
FAITH_TIMEOUT_DEFAULT = 15.0
# verdict→score 数值映射（写死：supports 全分／partial 半分／unsupported 与
# not_relevant 均 0 分——证据与题锚无关不支持力）
FAITH_SCORES = {"supports": 1.0, "partial": 0.5, "unsupported": 0.0, "not_relevant": 0.0}
FAITH_STAGE = "smoke_faithfulness"    # 生成用量.jsonl 台账行 stage 字面（20 元单列台账）
FAITH_EVIDENCE_MAX_CHARS = 400        # 单证据块 content 截长（对齐 citation_check.QUOTE_MAX_CHARS）

# ---------------------------------------------------------------------------
# 答案评测通道（--answers；2026-09-28 评测体系第 1 批 G1——生成端答案通道）常量
# ---------------------------------------------------------------------------
# 语义="基于 top-5 证据生成答案并按固定 rubric 五维评审"（评生成不只评证据；与
# faithfulness 的关系：faith 评"证据对锚的支持度"（无答案态），本通道评"生成答案
# 本身"，是 G1 判卷器答案通道的离线 harness 面）。
ANSWER_JUDGE_MODEL = "qwen3.8-flash"   # --answers-model 可覆写（授权档同 cr_model）
# 单题墙钟预算默认值（秒）：口径同 FAITH_TIMEOUT_DEFAULT（本机 flash 实测 ~7.8s，
# 留 ≥2x 余量；--answers-timeout 可配）
ANSWER_TIMEOUT_DEFAULT = 15.0
ANSWER_STAGE = "answer_judge"          # 生成用量.jsonl 台账行 stage 字面
# rubric 版本标识（2026-09-28 G3 校准轮立，随 rubric 措辞变更须 bump）：v3=终轮排他
# 措辞（fail 档加"清单外**且与正主非同族架构关系**"排他条件——G18/G13 型"同族+实质
# 支撑"情形不得按清单外 fail，须走 partial 档，消除 partial/fail 边界 flash 执行不稳）
# + 配套 judge temperature=0 确定性口径（G09/G15 型采样波动消除面）；v2=citation 维
# partial 口径（同族架构文档实引不阻断整题，G18 型）+ reason 对照 citation_req 正主
# 点名（G02 型）；v1=首跑隐式（2026-09-28 07:17 答案卷首跑第 2 轮）。幂等缓存按
# messages 全文 sha16 失效（rubric 在 system 提示内，措辞一变即全量重判），本键
# 仅供 jsonl 行人工对档
ANSWER_RUBRIC_VERSION = "answer_rubric/v3-20260928"
# 五维判定键（固定 rubric；每维取值白名单见 ANSWER_DIM_VALUES）
ANSWER_DIMS = ("faithfulness", "citation", "completeness", "version", "abstention")
ANSWER_DIM_VALUES = ("pass", "partial", "fail", "na")   # na=该维不适用（如 normal 题 abstention 维）
# partial 仅 citation 维合法（G3 校准轮 v2 口径：同族架构文档实引）；其余维仍三值，
# 越权 partial=输出畸形整题 null 降级（口径同既有白名单纪律）
_ANSWER_DIM_VALUES_STRICT = ("pass", "fail", "na")
ANSWER_MAX_TOKENS = 768                # judge 回包上限（答案+五维+理由，宽于 faith 512）
ANSWER_ANSWER_MAX_CHARS = 400          # 评审回显 answer 截长（防报告爆炸）
# 材料持久化（--answers-jsonl，2026-09-28 G3 元复核升级前置）默认档名模板：
# %s=YYYYMMDD（追加式；幂等缓存键=paper/qid+messages sha16，命中免调用复用）
ANSWER_JSONL_REL = "logs/answer_judge-%s.jsonl"
# ---------------------------------------------------------------------------
# 第10卷实操回流扩展判据（2026-10-11 设计稿 §三/§四；2026-10-12 实施件①②）
# ---------------------------------------------------------------------------
# 三字段（must_cover/must_cite_type/hard_gate）判据段独立版本键——**不 bump 主
# rubric 版本**（ANSWER_RUBRIC_VERSION 不动，存量卷对档零扰动）；措辞变更须 bump
# 本键（扩展段入 messages 即入 msg_sha16 幂等缓存键）。
ANSWER_RUBRIC_EXT_VERSION = "answer_rubric_ext/v1-20261011"
# rubric v3.1（2026-10-12 B4 外部锚修订案实施，案源=建库/work/三臂校准-20261011/
# 报告-外部模型锚-20261012.md §六，采纳施工令=2026-10-12 用户令）：独立版本键——
# **不改动 ANSWER_SYSTEM_PROMPT（v3 文本冻结）**，沿 answer_rubric_ext 同款
# 条件注入模式追加修订段（段首带本键；激活即入 messages 即入 msg_sha16 幂等缓存
# 键——老键行 sha 不再命中=按 v3.1 重判，老行原样留存零扰动）。仅两路激活：
# 卷级标记（题卷卷对象 "answer_rubric":"v3.1"，loader 注入 q["answer_rubric"]）或
# 显式参数（--answers-rubric v3.1 → 模块态 ANSWER_RUBRIC_V31["on"]）。修订面两处：
#   ① faithfulness 判定标准不动，reason 面增"编造/超证"二分归因——超证（内容与
#     规范/金标锚一致但证据块未覆盖）仍计 fail，但 reason 必标"超证-检索缺口"
#     不写"编造"（锚 3 例超证误书编造=G03/G06/G19 型，归因检索面供建库分诊）；
#   ② completeness 判文写死"只按必答要点核覆盖，引用形态/出处/版本问题一律归
#     citation/version 维"（G44 引用渗漏型）+ abstain 题 completeness 分支单列
#     （正确拒答即 pass，缺口说明为备注不作门槛——G36 型）。
# citation partial 塌缩建议（双判官/k≥3）不随本键实施（沿 B4 原案另轮）。
ANSWER_RUBRIC_V31_VERSION = "answer_rubric/v3.1-20261012"
# v3.1 激活态（模块级；main 显式参数路置位；卷级标记路不经此态——两路汇于
# _answer_rubric_v31_on(q)。缺省 False=全部走 v3 老键，行为逐字节不变）
ANSWER_RUBRIC_V31 = {"on": False}
# must_cite_type 等级折算唯一依据（设计稿 §3b：judge 不自由裁量定级，表外来源=
# 不满足任何等级——防编造；与生产 G 徽标映射 server.py 冻结常量同源，生成器=
# 建库/work/来源等级映射生成-20261012.py，一致性单测在 test_smoke_accept_vol10ext.py）
SOURCE_LEVEL_MAP_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "题卷", "来源等级映射-1.0.json")
# 等级权威序（L1 最权威）：达标判定=rank(level) ≤ rank(min_level)
_SOURCE_LEVEL_ORDER = {"L1": 1, "L2": 2, "L3": 3}

# ---------------------------------------------------------------------------
# 题库：18 条（与 建库/logs/验收题卷-公开源一期.md 一一对应；改题两处同步改）
#
# 字段：id/query/expect_doc（可接受 doc token 列表，任一命中即算）/
#       expect_locator_pattern（正则，IGNORECASE，锚到 clause/条号/参数卡粒度）/
#       criterion（top5=预期文档进 top-5；top10_locator=进 top-10 且 locator 锚中）/
#       retest+note（旧失手复测标记）+ 辅助字段 category/domain/version。
# ---------------------------------------------------------------------------
_V = _3GPP_VERSIONS  # 题库引用短名
_V_MIIT01 = "信息产业部令第36号（2005）"
_V_MIIT02 = "工信部联通信〔2023〕257号（2023）"
_V_GONGBAO = "工信部《2025年通信业统计公报》（2026-01 发布）"

QUESTIONS = [
    # --- 一、监管数字类 S01-S06（判据 top-5；doc token 按文号/标题双匹配）---
    {"id": "S01", "category": "监管数字", "domain": "监管",
     "query": "《电信服务规范》规定的掉话率监管红线是多少",
     "expect_doc": ["信息产业部令第36号", "电信服务规范"], "version": _V_MIIT01,
     "expect_locator_pattern": r"2\.2\.4(?![.\d])|4\.2\.2(?![.\d])|掉话率", "criterion": "top5",
     "retest": True, "note": "旧失手复测（冒烟 Q14：目标行 rank>60 未命中）。"
     "2026-09-27 S1 重校准：locator 辅助锚正则补 4.2.2 与 deploy_check 合格集同步"
     "（款号边界 `(?![.\\d])` 防 2.2.44/4.2.2.9 串号；附录2 2.2.4｜附录4 4.2.2 两锚"
     "回源三要件同证 ≤5%，锚集数据档=仓根 期望锚集-条款级.json）；pass 判据仍=doc 级"
     "top5（W2 深层翻 locator 级归决策项2，本轮最小改动）"},
    {"id": "S02", "category": "监管数字", "domain": "监管",
     "query": "《电信服务规范》要求数字蜂窝移动通信业务可接入率满足什么口径（位置/时间/接入时长）",
     "expect_doc": ["信息产业部令第36号", "电信服务规范"], "version": _V_MIIT01,
     "expect_locator_pattern": r"2\.2\.1|可接入率", "criterion": "top5",
     "retest": True, "note": "旧失手复测（冒烟 Q15：目标行 rank>60 未命中）"},
    {"id": "S03", "category": "监管数字", "domain": "监管",
     "query": "“信号升格”专项行动到2025年底移动网络下行/上行均值接入速率目标各是多少",
     "expect_doc": ["工信部联通信〔2023〕257号", "信号升格"], "version": _V_MIIT02,
     "expect_locator_pattern": r"220\s*mbps|45\s*mbps|主要目标", "criterion": "top5",
     "retest": True, "note": "旧失手复测（冒烟 Q16：目标行 rank10 边缘）"},
    {"id": "S04", "category": "监管数字", "domain": "监管",
     "query": "电信业务经营者对用户投诉应在多少个工作日内答复",
     "expect_doc": ["信息产业部令第36号", "电信服务规范"], "version": _V_MIIT01,
     "expect_locator_pattern": r"第十三条|15\s*个?工作日", "criterion": "top5",
     "retest": False, "note": ""},
    {"id": "S05", "category": "监管数字", "domain": "监管",
     "query": "截至2025年底全国5G基站总数达到多少万个",
     "expect_doc": ["2025年通信业统计公报", "统计公报"], "version": _V_GONGBAO,
     "expect_locator_pattern": r"483\.8", "criterion": "top5",
     "retest": False, "note": ""},
    {"id": "S06", "category": "监管数字", "domain": "监管",
     "query": "截至2025年底全国移动电话用户总数是多少",
     "expect_doc": ["2025年通信业统计公报", "统计公报"], "version": _V_GONGBAO,
     "expect_locator_pattern": r"18\.27", "criterion": "top5",
     "retest": False, "note": ""},
    # --- 二、标准条款类 S07-S12（判据 top-5；版本占位待回填）---
    {"id": "S07", "category": "标准条款", "domain": "3gpp",
     "query": "LTE 中 A3 事件的进入条件是什么",
     "expect_doc": ["TS 36.331"], "version": _V["TS 36.331"],
     "expect_locator_pattern": r"5\.5\.4|a3", "criterion": "top5",
     "retest": False, "note": ""},
    {"id": "S08", "category": "标准条款", "domain": "3gpp",
     "query": "RSRP 和 RSRQ 的定义分别是什么",
     "expect_doc": ["TS 36.214"], "version": _V["TS 36.214"],
     "expect_locator_pattern": r"5\.1\.[12]|rsrp|rsrq", "criterion": "top5",
     "retest": False, "note": ""},
    {"id": "S09", "category": "标准条款", "domain": "3gpp",
     "query": "5G NR 中 SS-RSRP 的定义是什么",
     "expect_doc": ["TS 38.215"], "version": _V["TS 38.215"],
     "expect_locator_pattern": r"5\.1\.1|ss-?rsrp", "criterion": "top5",
     "retest": False, "note": ""},
    {"id": "S10", "category": "标准条款", "domain": "3gpp",
     "query": "RRC 定时器 T310 的用途是什么，何时启动与停止",
     "expect_doc": ["TS 36.331"], "version": _V["TS 36.331"],
     "expect_locator_pattern": r"t310", "criterion": "top5",
     "retest": False, "note": ""},
    {"id": "S11", "category": "标准条款", "domain": "3gpp",
     "query": "HARQ 重传的最大次数或口径是怎么规定的",
     "expect_doc": ["TS 36.213", "TS 38.213", "TS 38.214"], "version": _V["TS 36.213"],
     "expect_locator_pattern": r"harq", "criterion": "top5",
     "retest": False, "note": "三件任一命中即算（38.213 系 NR HARQ 控制过程正主，2026-09-17 验收首跑复盘补入）"},
    {"id": "S12", "category": "标准条款", "domain": "3gpp",
     "query": "CSI-RSRP 与 SS-RSRP 的定义差异是什么",
     "expect_doc": ["TS 38.215"], "version": _V["TS 38.215"],
     "expect_locator_pattern": r"csi-?rsrp|5\.1\.[12]", "criterion": "top5",
     "retest": False, "note": ""},
    # --- 三、表格值/参数卡类 S13-S18（判据 top-10 且 locator 回行级/参数卡）---
    {"id": "S13", "category": "表格值/参数卡", "domain": "3gpp",
     "query": "切换参数 a3-Offset 的取值范围和步进是多少",
     "expect_doc": ["TS 36.331"], "version": _V["TS 36.331"],
     "expect_locator_pattern": r"a3-?offset|reportconfigeutra", "criterion": "top10_locator",
     "retest": False, "note": "旧库行级可达深度 49（冒烟 R3 登记）"},
    {"id": "S14", "category": "表格值/参数卡", "domain": "3gpp",
     "query": "测量事件 Hysteresis（迟滞）参数的取值域是多少",
     "expect_doc": ["TS 36.331"], "version": _V["TS 36.331"],
     "expect_locator_pattern": r"hysteresis", "criterion": "top10_locator",
     "retest": False, "note": "旧库行级可达深度 >60（冒烟 R3 登记）"},
    {"id": "S15", "category": "表格值/参数卡", "domain": "3gpp",
     "query": "T300 定时器的枚举取值在 4G（LTE）和 5G（NR）中分别有哪些",
     "expect_doc": ["TS 36.331", "TS 38.331"], "version": _V["TS 36.331"],
     "expect_locator_pattern": r"t300", "criterion": "top10_locator",
     "retest": False, "note": "两件任一命中即算；旧库行级可达深度 >60（冒烟 R3 登记）"},
    {"id": "S16", "category": "表格值/参数卡", "domain": "3gpp",
     "query": "LTE 各系统带宽对应的 PRB 数是多少（如 10MHz）",
     "expect_doc": ["TS 36.101"], "version": _V["TS 36.101"],
     "expect_locator_pattern": r"5\.6-1|NRB", "criterion": "top10_locator",
     "retest": False, "note": "2026-09-27 换锚回带宽-PRB 原题面（阶段三 P2 案B 修源：36.101 V18.13.0 表 5.6-1 真值块已切 chunks/36101.jsonl，锚新块 f321e0d73470882a）；36.101 嵌入归放量轮，入向量库前本题预期不达（放量后复验销账）。历史：2026-09-17 曾换锚功控 TPC 映射表（原表在 36.213 V18.3.0 已移除）。挂账档'S15'系旧过程日志称谓，实际题号=S16（e1ef512 执行时已勘）"},
    {"id": "S17", "category": "表格值/参数卡", "domain": "3gpp",
     "query": "NR 的 CQI 表有几张、条目与调制方式如何",
     "expect_doc": ["TS 38.214"], "version": _V["TS 38.214"],
     "expect_locator_pattern": r"cqi|5\.2\.2", "criterion": "top10_locator",
     "retest": False, "note": ""},
    {"id": "S18", "category": "表格值/参数卡", "domain": "3gpp",
     "query": "SSB 周期的可配置枚举值有哪些",
     "expect_doc": ["TS 38.331"], "version": _V["TS 38.331"],
     "expect_locator_pattern": r"ssb|periodicity", "criterion": "top10_locator",
     "retest": False, "note": ""},
]

# locator 正则缓存（IGNORECASE：宽容匹配 clause 号/参数名/主题词）
_PAT_CACHE = {}


def locator_pattern(qid):
    """按题 id 取编译后的 locator 正则（首次访问时编译并缓存）。"""
    if qid not in _PAT_CACHE:
        q = next(x for x in QUESTIONS if x["id"] == qid)
        _PAT_CACHE[qid] = re.compile(q["expect_locator_pattern"], re.IGNORECASE)
    return _PAT_CACHE[qid]


# ---------------------------------------------------------------------------
# doc/域 匹配（宽容归一：新旧 schema 字段都认——doc_id/src/id 任一字段子串命中）
# ---------------------------------------------------------------------------
_STRIP_CHARS = re.compile(r"[\s.\-_/\\〔〕\[\]()（）、,，]+")


def _norm(s):
    """匹配用归一：去空白/点横杠斜杠/各类括号顿号，小写。"""
    return _STRIP_CHARS.sub("", str(s or "")).lower()


def doc_match(meta, expect_tokens):
    """命中判定：expect token（归一后）任一 ⊆ meta 的 doc_id/src/id（归一拼接）。"""
    hay = _norm(" ".join(str(meta.get(k) or "") for k in ("doc_id", "src", "id")))
    return any(_norm(t) and _norm(t) in hay for t in expect_tokens)


_REG_SIG = re.compile(r"部令|公报|工信部|信号升格|电信服务规范")
# TR 系件文本签名（2026-09-28 增：TR 36.805 等 TR 前缀件归一化后形如 tr36805，
# 原签名 ts36/ts38/3gpp 均不中 → 域空 → 3gpp 题误记跨域；依据 清洁包-20260928.md §件一）。
_TR_SIG = re.compile(r"tr\d+")
# YD/T 行标件文本签名（2026-10-09 丙六族教识：doc_id "YD/T 5264-2021" 归一化后
# 形如 ydt52642021，三签名均不中 → 域空 → 凡进 top5 必记跨域污染（评审 P7：
# 系判据面非观察面）。source_domain=="ydt" 分支为主，签名系兜底——P5 已保
# staging 逐块 source_domain=ydt（chunk_staging_ydt 硬断言）。
_YDT_SIG = re.compile(r"ydt\d")


def hit_domains(meta):
    """推断命中 chunk 的域集合：source_domain 字段（D3 schema）优先，文本签名兜底。

    返回 set（可空=未知域）；跨域污染判据=题面预期域不在该集合中（source_domain
    粒度的机器判，知识域内细判留人眼复核——口径同题卷卷首）。
    """
    doms = set()
    sd = str(meta.get("source_domain") or "").strip().lower()
    if sd == "3gpp":
        doms.add("3gpp")
    elif sd in ("miit", "监管"):
        doms.add("监管")
    elif sd == "ydt":
        doms.add("行标")
    text = " ".join(str(meta.get(k) or "") for k in ("doc_id", "src"))
    nt = _norm(text)
    if "ts36" in nt or "ts38" in nt or "3gpp" in nt or _TR_SIG.search(nt):
        doms.add("3gpp")
    if _REG_SIG.search(text):
        doms.add("监管")
    if _YDT_SIG.search(nt):
        doms.add("行标")
    return doms


def locator_text(meta):
    """locator 匹配文本：locator 字段为主，section 兜底（新 schema locator 必备）。"""
    return " ".join(str(meta.get(k) or "") for k in ("locator", "section") if meta.get(k))


# ---------------------------------------------------------------------------
# 外部题卷（--questions-file；2026-09-18 评测 harness 统一化）
# ---------------------------------------------------------------------------
# 题卷 JSON schema v1（详档：建库/logs/评测harness统一-20260918.md；expect_domain
# 增补见 建库/logs/C卷翻型准备-20260919.md）：
#   文件 = 单卷对象 ｜ {"papers":[卷,...]} ｜ [卷,...]
#   卷   = {"schema_version":1, "paper_id":str, "title"?, "source_md"?,
#           "paper_note"?, "pass_lines"（null=不设线，或六键见 _PASS_LINE_KEYS）,
#           "answer_rubric"?:"v3"|"v3.1"（卷级判卷 rubric 档位，2026-10-12 v3.1
#           修订案：缺省/"v3"=v3 老键零扰动；"v3.1"=全卷按 answer_rubric/v3.1-
#           20261012 修订段判，详见 ANSWER_RUBRIC_V31_VERSION 注；
#           **2026-10-12 用户决策采纳后前瞻默认=新评测件（新卷/未来答案卷）建卷
#           即标 "answer_rubric":"v3.1"**——机制缺省仍 "v3"（存量卷零扰动铁律），
#           既有卷已全部显式钉 "v3" 冻结（答案卷-1.0/1.1、对抗、独立 B/C/Y、
#           外部锚点、红线草案、阈值补测、难负例 18 件；第10卷草案=前瞻首件
#           标 "v3.1"），守卫单测=卷档必带档位标记）,
#           "questions":[题,...]（非空）}
#   题   = {"id":str（卷内唯一）, "query":str, "category"?, "judge_type"?,
#           "anchors":[锚,...], "expect_miss_layer"?, "expect_domain"?,
#           "retest"?, "note"?,
#           —— schema v2（2026-09-28 答案评测通道四字段 + R3 难负例 hard_negatives，
#           全可选，老卷缺省行为完全不变）："answer_points"?:[str,...]（必答要点，--answers 评审门控
#           字段之一）、"must_not"?:[str,...]（禁答点）、"citation_req"?:
#           {"docs"?:[规范号,...], "note"?:str}（引用要求）、"expected_type"?:
#           "normal"（默认）|"abstain"（无答案应拒答型——空证据下正确拒答即达标）、
#           "hard_negatives"?:[{"spec":非空str, "reason"?:str},...]（R3 难负例卷
#           前瞻字段，2026-09-28：负锚=不应压过正主的相似文档，如 NR 问法配 LTE
#           同名件；judge 对 top-5 逐块与各 spec 做 doc_match 归一匹配，命中记
#           hard_neg_hits/hard_neg_count——**只测不判**：不进单题 pass 亦不设
#           通过线，卷级仅汇总 hard_neg_hit_rate 出 precision 信号，门禁定线留后续）}
#           —— 第10卷实操回流三字段（2026-10-11 设计稿 §三
#           建库/work/第10卷schema设计-20261011.md，全可选，老卷缺省行为**逐字节
#           不变**——三字段判据仅对带字段的题条件注入 judge 提示，不带字段的老题
#           messages 与幂等缓存零扰动；loader 校验见 _validate_must_cover 三件）：
#           "must_cover"?:[str,...]（必答操作方向，≥1 项：completeness 维加严——
#           逐项必中，缺任一项即 fail，不按比例扣；与 must_not 的语义互斥由人工
#           保证，loader 不查）、"must_cite_type"?:{"min_level":"L1"|"L2"|"L3",
#           "note"?} 或简写 "L3"（citation 维改判口径：实引来源经 来源等级映射-1.0
#           .json 折算 ≥min_level 即 pass，不要求条款号——与 citation_req 互斥，
#           loader 拒收并存）、"hard_gate"?:{"executable_steps":bool,
#           "specific_params":bool, "note"?}（两门至少其一 true；整题前置硬门，
#           先于五维判定——与 expected_type=abstain 互斥，loader 拒收并存）。
#           另：入卷题可带 "reflux" 溯源键（{"draft_id","source_file","line_no",
#           "attribution","occurrences"}，设计稿 §二）——loader 白名单式重建忽略
#           该键（不拒收不进判卷面），溯源以卷面原文件为准。
#           —— 亦认 A 卷扁平简写：题级 expect_doc/version/expect_locator_pattern/
#           criterion/domain = 单 primary 锚（与 QUESTIONS/QUESTIONS_B 同形态）
#   锚   = {"expect_doc":[token,...]（非空，归一子串任一命中）, "version"?,
#           "expect_locator_pattern":正则（IGNORECASE）, "criterion":"top5"|
#           "top10_locator", "role"?:"primary"(默认)|"secondary", "domain"?:
#           "3gpp"|"监管"}
# 判定口径：
#   relevance   —— 任一 primary 锚满足其 criterion 即过（top5=预期 doc 进 top-5；
#                 top10_locator=进 top-10 且 locator 锚中；与内置卷 S11/S15
#                 "多 doc 任一命中即算"同语义）；secondary 锚只回显不计过；
#   expect_miss —— 全部锚在 top-k 均 miss 才算达标（"miss 即达标"，实操卷诚实
#                 披露判定的机器面）；任一锚命中=意外命中（未达标，报告标注，
#                 留人眼复核——可能语料已入池或锚点漂移）；
#   expect_miss_layer —— 登记性标注（C 卷实操层"当前库无，预期 miss 属有效
#                 预期"照搬），答案层属性、检索 harness 不做机器判定，只落报告；
#   expect_domain —— 题级附加机器判定（2026-09-19 C 卷实操层翻型件，取代
#                 expect_miss_layer 的登记位）：在 criterion 深度（"top5"（默认）/
#                 "top10"）内出现**任一**指定域块即判"域中"。域匹配=match_any
#                 （field,value）对 any-of 归一精确相等，缺省=合成卡域标识四件套
#                 layer="合成卡"/corpus_type="case_card"/source_domain="synthetic"/
#                 chunk_type="case_card"（匹配键依 chunks/3gpp.jsonl 首行与合成卡
#                 设计稿 D1/synth_cards.build_card_record 的现行字段形态核定，四值
#                 与既有两库"公开源"/"3gpp"/"监管"零重叠）；简写=true 或 "合成卡"。
#                 **防自证纪律（硬性）：判定粒度=域级，match 字段白名单=layer/
#                 corpus_type/source_domain/chunk_type/doc_id，绝不锚具体卡 id/
#                 卡内容/locator——防把判定调参到恰好生成的卡**；与 expect_miss_layer
#                 互斥（"应命中域"与"预期 miss"语义矛盾，loader 拒收）；judge_type
#                 不变（仍 relevance 判 spec 锚），域判定独立回显+按卷汇总
#                 （domain_hits/domain_rate，通过线键 domain_rate_min），不计入
#                 单题 pass；题配了 expect_domain 时，命中该域的 top-5 块不计跨域。
PAPER_SCHEMA_VERSION = 1
_JUDGE_TYPES = ("relevance", "expect_miss")
_ANCHOR_ROLES = ("primary", "secondary")
_CRITERIA = ("top5", "top10_locator")
_PASS_LINE_KEYS = ("top5_rate_min", "monitor_hits_min", "param_hits_min",
                   "cross_domain_max", "expect_miss_rate_min", "domain_rate_min")


class QuestionFileError(ValueError):
    """外部题卷文件/schema 非法（--questions-file 前置失败，退出码 2）。"""


# 正则缓存（键=正则串本身，跨卷安全；_PAT_CACHE 仍按题 id 缓存，eval_rerank 在用）
_RE_CACHE = {}


def _compiled(pattern):
    """按正则串取编译缓存（IGNORECASE，宽容匹配 clause 号/参数名/主题词）。"""
    if pattern not in _RE_CACHE:
        _RE_CACHE[pattern] = re.compile(pattern, re.IGNORECASE)
    return _RE_CACHE[pattern]


# ---------------------------------------------------------------------------
# expect_domain 域判定（2026-09-19 C 卷实操层翻型件；域级粒度，防自证——见 schema 注释）
# ---------------------------------------------------------------------------
# match 字段白名单：只认域级/件级标识。id/content/locator/section 等卡级锚一律
# 拒收（防把判定调参到恰好生成的卡）；doc_id 可配（件级域）但不入缺省——合成卡
# 的 doc_id 沿用源 3GPP 件号，不是域标识。
_DOMAIN_MATCH_FIELDS = ("layer", "corpus_type", "source_domain", "chunk_type", "doc_id")
# 合成卡域标识缺省四件套（any-of）：依现行 chunk 字段形态核定——synth_cards.
# build_card_record 写 layer="合成卡"/corpus_type="case_card"/source_domain=
# "synthetic"/chunk_type="case_card"；既有两库 layer="公开源"、corpus_type=
# "3gpp"/"监管"、source_domain="3gpp"/"miit"，四值零重叠，任一字段单独在即判域中。
_SYNTH_DOMAIN_MATCH_ANY = (("layer", "合成卡"), ("corpus_type", "case_card"),
                           ("source_domain", "synthetic"), ("chunk_type", "case_card"))
_DOMAIN_CRITERIA = ("top5", "top10")


def _norm_domain_spec(spec):
    """expect_domain 原始配置 → 规范化 dict（None=未配置；宽进版，judge 端用）。

    认三种形态：true／"合成卡"（简写=合成卡域缺省四件套+top5）／dict
    {domain?, match_any?:[{field,value}], criterion?}。loader 端已规范化的 dict
    原样过；未经 loader 的题 dict 也容错。非法细节（字段名白名单等）由
    _validate_expect_domain 严校验（退 2），此处只兜形状。
    """
    if not spec:
        return None
    if spec is True or spec == "合成卡":
        return {"domain": "合成卡", "match_any": _SYNTH_DOMAIN_MATCH_ANY,
                "criterion": "top5"}
    if isinstance(spec, str):
        return {"domain": spec, "match_any": _SYNTH_DOMAIN_MATCH_ANY,
                "criterion": "top5"}
    if not isinstance(spec, dict):
        return None
    pairs = spec.get("match_any")
    if not pairs:
        pairs = _SYNTH_DOMAIN_MATCH_ANY
    norm_pairs = []
    for p in pairs:
        if isinstance(p, dict):                      # 原始 JSON 形态 {field,value}
            f, v = p.get("field"), p.get("value")
        elif isinstance(p, (tuple, list)) and len(p) == 2:  # 已规范化 (field,value)
            f, v = p
        else:
            f = v = None
        if isinstance(f, str) and f.strip() and isinstance(v, str) and v.strip():
            norm_pairs.append((f.strip(), v.strip()))
    if not norm_pairs:
        return None
    return {"domain": str(spec.get("domain") or "合成卡"),
            "match_any": tuple(norm_pairs),
            "criterion": spec.get("criterion") if spec.get("criterion") in _DOMAIN_CRITERIA
            else "top5"}


def _validate_expect_domain(raw, where):
    """expect_domain 严校验（loader 路径）→ 规范化 dict（None=未配置）。

    白名单外的 match 字段（如 id/content/locator）直接拒收——防自证纪律：判定
    粒度=域级，绝不锚具体卡（见 schema 注释）。
    """
    if raw is None or raw is False:
        return None
    if raw is True:
        return _norm_domain_spec(True)
    if isinstance(raw, str):
        if not raw.strip():
            raise QuestionFileError("%s expect_domain 简写串须非空" % where)
        return _norm_domain_spec(raw)
    if not isinstance(raw, dict):
        raise QuestionFileError("%s expect_domain 须为 true／字符串／对象" % where)
    ma = raw.get("match_any")
    if ma is not None and (not isinstance(ma, list) or not ma):
        raise QuestionFileError("%s expect_domain match_any 须为非空 [{field,value}] 数组" % where)
    spec = _norm_domain_spec(raw)
    if spec is None:
        raise QuestionFileError("%s expect_domain 对象须含非空 match_any（或整体缺省）" % where)
    crit = raw.get("criterion")
    if crit is not None and crit not in _DOMAIN_CRITERIA:
        raise QuestionFileError("%s expect_domain criterion 须为 %s 之一，得 %r" % (
            where, "／".join(_DOMAIN_CRITERIA), crit))
    for p in ma or []:
        if not isinstance(p, dict):
            raise QuestionFileError("%s expect_domain match_any 项须为 {field,value} 对象" % where)
        f = p.get("field")
        if not isinstance(f, str) or not f.strip():
            raise QuestionFileError("%s expect_domain match_any.field 须为非空字符串" % where)
        if f.strip() not in _DOMAIN_MATCH_FIELDS:
            raise QuestionFileError(
                "%s expect_domain match 字段 %r 不在域级白名单（%s）——防自证纪律："
                "判定粒度=域级，绝不锚具体卡 id/内容/locator" % (
                    where, f, "、".join(_DOMAIN_MATCH_FIELDS)))
        v = p.get("value")
        if not isinstance(v, str) or not v.strip():
            raise QuestionFileError("%s expect_domain match_any.value 须为非空字符串" % where)
    return spec


def _meta_in_domain(meta, dspec):
    """chunk meta 是否落入指定域：match_any（field,value）对 any-of 归一精确相等。"""
    if not dspec:
        return False
    for f, v in dspec["match_any"]:
        nv = _norm(v)
        if nv and _norm(meta.get(f)) == nv:
            return True
    return False


def _validate_pass_lines(pl, where):
    """卷级通过线校验：null 或 {六键子集: 数值}；卷内无对应类题时该线不罚。"""
    if pl is None:
        return None
    if not isinstance(pl, dict) or not pl:
        raise QuestionFileError("%s pass_lines 须为 null 或非空对象" % where)
    out = {}
    for k, v in pl.items():
        if k not in _PASS_LINE_KEYS:
            raise QuestionFileError("%s pass_lines 未知键 %r（合法：%s）" % (
                where, k, "、".join(_PASS_LINE_KEYS)))
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise QuestionFileError("%s pass_lines[%s] 须为数值" % (where, k))
        out[k] = v
    return out


def _validate_anchor(a, qid, idx, q_domain, require_domain):
    """单锚校验+规范化（q_domain=题级 domain 兜底）。"""
    where = "%s 锚#%d" % (qid, idx + 1)
    if not isinstance(a, dict):
        raise QuestionFileError("%s 须为对象" % where)
    docs = a.get("expect_doc")
    if not isinstance(docs, list) or not docs or not all(
            isinstance(t, str) and t.strip() for t in docs):
        raise QuestionFileError("%s expect_doc 须为非空字符串数组" % where)
    pat = a.get("expect_locator_pattern")
    if not isinstance(pat, str) or not pat:
        raise QuestionFileError("%s expect_locator_pattern 须为非空正则串" % where)
    try:
        _compiled(pat)
    except re.error as e:
        raise QuestionFileError("%s locator 正则不可编译：%s（%s）" % (where, pat, e))
    crit = a.get("criterion")
    if crit not in _CRITERIA:
        raise QuestionFileError("%s criterion 须为 %s 之一，得 %r" % (
            where, "／".join(_CRITERIA), crit))
    role = a.get("role", "primary")
    if role not in _ANCHOR_ROLES:
        raise QuestionFileError("%s role 须为 %s 之一，得 %r" % (
            where, "／".join(_ANCHOR_ROLES), role))
    dom = a.get("domain", q_domain)
    if dom is not None and dom not in ("监管", "3gpp"):
        raise QuestionFileError("%s domain 须为 监管／3gpp 或缺省，得 %r" % (where, dom))
    if require_domain and role == "primary" and dom is None:
        raise QuestionFileError("%s relevance 题的 primary 锚须给 domain（跨域判定用）"
                                % where)
    return {"expect_doc": [str(t) for t in docs], "version": str(a.get("version") or ""),
            "expect_locator_pattern": pat, "criterion": crit, "role": role,
            "domain": dom}


_ANSWER_TYPES = ("normal", "abstain")


def _validate_str_list(raw, where, field):
    """schema v2 字符串数组字段校验（answer_points/must_not 共用；None→[]；
    空数组=显式空，等价缺省收下——abstain 题显式声明"无必答要点"用）。"""
    if raw is None:
        return []
    if not isinstance(raw, list) or not all(
            isinstance(t, str) and t.strip() for t in raw):
        raise QuestionFileError("%s %s 须为字符串数组或缺省（元素须非空字符串）"
                                % (where, field))
    return [str(t) for t in raw]


def _validate_citation_req(raw, where):
    """schema v2 citation_req 校验（None→None；{"docs"?, "note"?} 至少含其一）。"""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise QuestionFileError("%s citation_req 须为 {docs?,note?} 对象或缺省" % where)
    docs = raw.get("docs")
    if docs is not None and (not isinstance(docs, list) or not docs or not all(
            isinstance(t, str) and t.strip() for t in docs)):
        raise QuestionFileError("%s citation_req.docs 须为非空字符串数组" % where)
    note = raw.get("note")
    if note is not None and (not isinstance(note, str) or not note.strip()):
        raise QuestionFileError("%s citation_req.note 须为非空字符串或缺省" % where)
    if docs is None and note is None:
        raise QuestionFileError("%s citation_req 须至少含 docs/note 之一" % where)
    return {"docs": [str(t) for t in (docs or [])], "note": str(note or "")}


def _validate_hard_negatives(raw, where):
    """schema v2 hard_negatives 校验（R3 难负例卷前瞻字段，2026-09-28；None→[]）。

    元素须 {"spec":非空str, "reason"?:str}（reason 缺省补 ""）；缺省/显式空数组
    均等价 []——老卷零变化。判定纪律=与 MRR/nDCG 相同的"只测不判"：负锚命中不进
    单题 pass，仅出卷级 precision 信号（hard_neg_hit_rate），门禁定线留后续。
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise QuestionFileError("%s hard_negatives 须为数组或缺省" % where)
    out = []
    for item in raw:
        if not isinstance(item, dict):
            raise QuestionFileError("%s hard_negatives 项须为 {spec,reason?} 对象" % where)
        spec = item.get("spec")
        if not isinstance(spec, str) or not spec.strip():
            raise QuestionFileError("%s hard_negatives.spec 须为非空字符串" % where)
        reason = item.get("reason")
        if reason is not None and (not isinstance(reason, str) or not reason.strip()):
            raise QuestionFileError("%s hard_negatives.reason 须为非空字符串或缺省" % where)
        out.append({"spec": spec, "reason": str(reason or "")})
    return out


_SOURCE_LEVELS = ("L1", "L2", "L3")


def _validate_must_cite_type(raw, where):
    """第10卷 must_cite_type 校验（设计稿 §3b；None→None）。

    形态：{"min_level":"L1"|"L2"|"L3", "note"?} 或简写字符串 "L3"（等价
    min_level=L3）。与 citation_req 的互斥由 _validate_question 判（一题只许
    一种引用口径，防判据打架）。"""
    if raw is None:
        return None
    if isinstance(raw, str):
        if raw.strip() not in _SOURCE_LEVELS:
            raise QuestionFileError(
                "%s must_cite_type 简写须为 L1/L2/L3 之一，得 %r" % (where, raw))
        return {"min_level": raw.strip(), "note": ""}
    if not isinstance(raw, dict):
        raise QuestionFileError(
            "%s must_cite_type 须为 {min_level,note?} 对象或 L1/L2/L3 简写串" % where)
    unknown = [k for k in raw if k not in ("min_level", "note")]
    if unknown:
        raise QuestionFileError("%s must_cite_type 未知键 %r（合法：min_level、note）"
                                % (where, unknown[0]))
    ml = raw.get("min_level")
    if ml not in _SOURCE_LEVELS:
        raise QuestionFileError(
            "%s must_cite_type.min_level 须为 L1/L2/L3 之一，得 %r" % (where, ml))
    note = raw.get("note")
    if note is not None and (not isinstance(note, str) or not note.strip()):
        raise QuestionFileError("%s must_cite_type.note 须为非空字符串或缺省" % where)
    return {"min_level": ml, "note": str(note or "")}


def _validate_hard_gate(raw, where):
    """第10卷 hard_gate 校验（设计稿 §3c；None→None）。

    形态：{"executable_steps"?:bool, "specific_params"?:bool, "note"?}——两门
    至少其一为 true（全 false/缺省=空门无意义，拒收）。与 expected_type=abstain
    的互斥由 _validate_question 判（拒答题无可执行步骤语义）。"""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise QuestionFileError(
            "%s hard_gate 须为 {executable_steps?,specific_params?,note?} 对象或缺省"
            % where)
    unknown = [k for k in raw if k not in ("executable_steps", "specific_params", "note")]
    if unknown:
        raise QuestionFileError(
            "%s hard_gate 未知键 %r（合法：executable_steps、specific_params、note）"
            % (where, unknown[0]))
    gates = {}
    for k in ("executable_steps", "specific_params"):
        v = raw.get(k, False)
        if not isinstance(v, bool):
            raise QuestionFileError(
                "%s hard_gate.%s 须为布尔或缺省（缺省=false），得 %r" % (where, k, v))
        gates[k] = v
    if not (gates["executable_steps"] or gates["specific_params"]):
        raise QuestionFileError(
            "%s hard_gate 两门（executable_steps/specific_params）至少其一须为 true"
            "——全 false=空门无意义，请缺省该键" % where)
    note = raw.get("note")
    if note is not None and (not isinstance(note, str) or not note.strip()):
        raise QuestionFileError("%s hard_gate.note 须为非空字符串或缺省" % where)
    return {"executable_steps": gates["executable_steps"],
            "specific_params": gates["specific_params"], "note": str(note or "")}


def _validate_question(q, idx, where):
    """单题校验+规范化：anchors 形态（多锚）或 A 卷扁平简写（单锚）都认。"""
    qid = q.get("id") if isinstance(q, dict) else None
    if not isinstance(qid, str) or not qid.strip():
        raise QuestionFileError("%s 题#%d id 须为非空字符串" % (where, idx + 1))
    qw = "%s %s" % (where, qid)
    query = q.get("query")
    if not isinstance(query, str) or not query.strip():
        raise QuestionFileError("%s query（题面）须为非空字符串" % qw)
    jtype = q.get("judge_type", "relevance")
    if jtype not in _JUDGE_TYPES:
        raise QuestionFileError("%s judge_type 须为 %s 之一，得 %r" % (
            qw, "／".join(_JUDGE_TYPES), jtype))
    flat_keys = ("expect_doc", "expect_locator_pattern", "criterion")
    has_flat = any(k in q for k in flat_keys)
    raw_anchors = q.get("anchors")
    if has_flat and raw_anchors is not None:
        raise QuestionFileError("%s 同时给题级扁平锚字段与 anchors 数组（二选一）" % qw)
    q_domain = q.get("domain")
    if q_domain is not None and q_domain not in ("监管", "3gpp"):
        raise QuestionFileError("%s 题级 domain 须为 监管／3gpp 或缺省，得 %r" % (qw, q_domain))
    if has_flat:
        anchors = [_validate_anchor(q, qid, 0, q_domain, jtype == "relevance")]
    else:
        # v2（2026-09-28 G2）：答案型题（answer_points 非空或 abstain）以答案字段
        # 代替检索锚，允许无锚；纯 v1 题仍强制非空锚。
        is_answer_q = bool(q.get("answer_points")) or q.get("expected_type") == "abstain"
        if not isinstance(raw_anchors, list) or not raw_anchors:
            if not is_answer_q:
                raise QuestionFileError("%s anchors 须为非空数组（或用题级扁平单锚简写）" % qw)
            anchors = []
        else:
            anchors = [_validate_anchor(a, qid, i, q_domain, jtype == "relevance")
                       for i, a in enumerate(raw_anchors)]
            if jtype == "relevance" and not any(a["role"] == "primary" for a in anchors):
                raise QuestionFileError("%s relevance 题至少须一个 primary 锚" % qw)
    layer = q.get("expect_miss_layer")
    if layer is not None and not isinstance(layer, str):
        raise QuestionFileError("%s expect_miss_layer 须为字符串或缺省" % qw)
    dom_spec = _validate_expect_domain(q.get("expect_domain"), qw)
    if dom_spec and layer:
        raise QuestionFileError(
            "%s expect_domain 与 expect_miss_layer 互斥（应命中域 vs 预期 miss，"
            "语义矛盾二选一）" % qw)
    # schema v2 四字段（2026-09-28 答案评测通道；全可选——老卷缺省值固定，行为不变）
    answer_points = _validate_str_list(q.get("answer_points"), qw, "answer_points")
    must_not = _validate_str_list(q.get("must_not"), qw, "must_not")
    citation_req = _validate_citation_req(q.get("citation_req"), qw)
    expected_type = q.get("expected_type", "normal")
    if expected_type not in _ANSWER_TYPES:
        raise QuestionFileError("%s expected_type 须为 %s 之一或缺省，得 %r" % (
            qw, "／".join(_ANSWER_TYPES), expected_type))
    # R3 难负例前瞻字段（2026-09-28）：负锚只测不判（judge 出 hard_neg_hits
    # precision 信号，不进单题 pass；卷级 hard_neg_hit_rate，不设通过线）
    hard_negs = _validate_hard_negatives(q.get("hard_negatives"), qw)
    # 第10卷实操回流三字段（2026-10-11 设计稿 §三；全可选——老卷缺省值固定，
    # 行为逐字节不变；must_cover 显式空数组=空门无意义拒收，缺省则等价 []）
    must_cover = _validate_str_list(q.get("must_cover"), qw, "must_cover")
    if q.get("must_cover") is not None and not must_cover:
        raise QuestionFileError(
            "%s must_cover 须至少 1 项（显式空数组=空门无意义，请缺省该键）" % qw)
    must_cite_type = _validate_must_cite_type(q.get("must_cite_type"), qw)
    if must_cite_type is not None and citation_req is not None:
        raise QuestionFileError(
            "%s must_cite_type 与 citation_req 互斥（一题只许一种引用口径，防判据"
            "打架——按条款号正主判走 citation_req，按来源等级判走 must_cite_type）"
            % qw)
    hard_gate = _validate_hard_gate(q.get("hard_gate"), qw)
    if hard_gate is not None and expected_type == "abstain":
        raise QuestionFileError(
            "%s hard_gate 与 expected_type=abstain 互斥（拒答题无可执行步骤语义）"
            % qw)
    return {"id": qid, "query": query, "category": str(q.get("category") or ""),
            "judge_type": jtype, "anchors": anchors,
            "domain": q_domain, "domains": sorted({a["domain"] for a in anchors
                                                   if a.get("domain")}),
            "expect_miss_layer": layer or "", "expect_domain": dom_spec,
            "answer_points": answer_points, "must_not": must_not,
            "citation_req": citation_req, "expected_type": expected_type,
            "hard_negatives": hard_negs,
            "must_cover": must_cover, "must_cite_type": must_cite_type,
            "hard_gate": hard_gate,
            "retest": bool(q.get("retest", False)),
            "note": str(q.get("note") or "")}


def _validate_paper(p, i, path):
    """卷对象校验+规范化。"""
    where = "%s 卷#%d" % (os.path.basename(path), i)
    if not isinstance(p, dict):
        raise QuestionFileError("%s 须为对象" % where)
    pid = p.get("paper_id")
    if not isinstance(pid, str) or not pid.strip():
        raise QuestionFileError("%s paper_id 须为非空字符串" % where)
    where = "%s（%s）" % (where, pid)
    qs = p.get("questions")
    if not isinstance(qs, list) or not qs:
        raise QuestionFileError("%s questions 须为非空数组" % where)
    questions = [_validate_question(q, i, where) for i, q in enumerate(qs)]
    ids = [q["id"] for q in questions]
    if len(set(ids)) != len(ids):
        dup = sorted({x for x in ids if ids.count(x) > 1})
        raise QuestionFileError("%s 题号重复：%s" % (where, "、".join(dup)))
    # 卷级 rubric 档位标记（2026-10-12 rubric v3.1 修订案施工面）：缺省/"v3"=v3
    # 老键（老卷行为与既有逐字节不变——不落键不注入）；"v3.1"=给每题注入
    # answer_rubric="v3.1"（build_answer_messages 据此条件注入修订段）；其他值拒收。
    # 2026-10-12 采纳后前瞻口径：新评测件建卷即标 "v3.1"（新卷默认走 v3.1 判卷）；
    # 存量卷显式钉 "v3" 冻结（老读数零扰动），缺省 "v3" 机制不动。
    rub = p.get("answer_rubric") or "v3"
    if rub not in ("v3", "v3.1"):
        raise QuestionFileError(
            "%s answer_rubric 须为 \"v3\"/\"v3.1\"（缺省 v3），得 %r" % (where, rub))
    if rub == "v3.1":
        for q in questions:
            q["answer_rubric"] = "v3.1"
    return {"schema_version": p.get("schema_version", PAPER_SCHEMA_VERSION),
            "paper_id": pid, "title": str(p.get("title") or ""),
            "source_md": str(p.get("source_md") or ""),
            "paper_note": str(p.get("paper_note") or ""),
            "pass_lines": _validate_pass_lines(p.get("pass_lines"), where),
            "questions": questions}


def load_question_file(path):
    """读外部题卷 JSON → 规范化卷对象列表。

    文件形态三选一：单卷对象／{"papers":[...]}／卷数组。非法抛 QuestionFileError
    （main 捕获退 2）。返回的卷对象结构与 schema 一一对应，questions 已规范化为
    anchors 形态（扁平简写已合成单锚）。
    """
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise QuestionFileError("JSON 解析失败：%s（%s）" % (path, e))
    if isinstance(data, dict) and isinstance(data.get("questions"), list):
        papers = [data]
    elif isinstance(data, dict) and isinstance(data.get("papers"), list):
        papers = data["papers"]
    elif isinstance(data, list):
        papers = data
    else:
        raise QuestionFileError(
            "题卷文件顶层须为卷对象、{\"papers\":[...]} 或卷数组：%s" % path)
    if not papers:
        raise QuestionFileError("题卷文件不含任何卷：%s" % path)
    out, seen = [], set()
    for i, p in enumerate(papers, 1):
        paper = _validate_paper(p, i, path)
        if paper["paper_id"] in seen:
            raise QuestionFileError("卷 id 重复：%s" % paper["paper_id"])
        seen.add(paper["paper_id"])
        out.append(paper)
    return out


def paper_questions(papers):
    """内置卷 → QUESTIONS；外部卷列表 → 各卷题目按序展平（嵌入按此序一批走）。"""
    return QUESTIONS if papers is None else [q for p in papers for q in p["questions"]]


# ---------------------------------------------------------------------------
# 判定与汇总
# ---------------------------------------------------------------------------
def _mrr_ndcg(grades):
    """分级排序质量指标（改造三 2026-09-28 R1；纯函数零 API）：grades=rank 升序
    逐位增益序列（primary 锚=1.0、secondary=0.5、未命中=0；调用方截 @10）。

    返回 (mrr, ndcg)：
    - MRR@k = 首个非零增益位次的倒数（k=len(grades)；全零=0）；
    - nDCG@k = DCG/IDCG（线性增益折损制：DCG=Σ g_i/log2(i+1)，i 从 0 起；
      IDCG=同增益集理想降序排布的 DCG；IDCG=0（全零）→ 0.0）。
    只测不判——不进任何通过线（不动现有四线/六线硬线口径）。"""
    mrr = 0.0
    for i, g in enumerate(grades):
        if g > 0:
            mrr = 1.0 / (i + 1)
            break
    dcg = sum(g / math.log2(i + 2) for i, g in enumerate(grades))
    idcg = sum(g / math.log2(i + 2)
               for i, g in enumerate(sorted(grades, reverse=True)))
    return mrr, (dcg / idcg if idcg > 0 else 0.0)


def _question_anchors(q):
    """题 → 规范化锚列表。A 卷扁平题（QUESTIONS/QUESTIONS_B 形态）实时合成单
    primary 锚（不改原 dict）；外部题卷题已由 loader 规范化为 anchors 形态
    （v2 答案型题可为空列表——判走空锚，pass 由 --answers 通道承担）。"""
    if "anchors" in q:
        return q["anchors"]
    return [{"expect_doc": q["expect_doc"], "version": q.get("version", ""),
             "expect_locator_pattern": q["expect_locator_pattern"],
             "criterion": q["criterion"], "role": "primary",
             "domain": q.get("domain")}]


def judge_question(q, hits, meta_by_id):
    """单题判定（v2：内置扁平题 + 外部题卷多锚/expect_miss 型，口径向后兼容）。

    q     —— 题目（A 卷扁平形态或 loader 规范化 anchors 形态皆可）；
    hits  —— retrieve.search 的 top-k 结果（rank 升序）；
    meta_by_id —— id → chunk 全字段 dict（retrieve 只随行 META_FIELDS，doc_id/
              locator 需本模块从库文件重扫补齐，见 load_meta_by_id）。

    判据分线（D5，内置卷同源）：criterion=top5 → 预期文档进 top-5 即过（locator
    锚为辅助信号）；criterion=top10_locator → 预期文档进 top-10 且其 locator 模式
    锚中（参数/表值类须能回行级/参数卡出处）。多锚题：relevance=任一 primary 锚
    满足其 criterion 即过（secondary 只回显）；expect_miss=全部锚 miss 才达标，
    任一锚命中记"意外命中"。扁平单锚题的输出与历史版本逐字段一致。

    附加维度 expect_domain（题级可选，2026-09-19 C 卷实操层翻型件）：判 criterion
    深度（top5/top10）内是否出现任一指定域块（域级粒度，match 字段白名单——防自证，
    详见 schema 注释）；独立回显 domain_hit/domain_rank/domain_hit_doc，**不计入
    单题 pass**（pass 仍由 judge_type 口径定）；题配了 expect_domain 时，命中该域
    的 top-5 块不计跨域（预期域命中非污染）。

    排序质量（改造三 2026-09-28 R1，只测不判）：顺带按 top-10 逐位分级（primary
    锚=1.0、secondary=0.5、未命中=0）补算 MRR@10 与 nDCG@10（_mrr_ndcg；锚匹配
    复用本函数循环内的 doc_match，不另起炉灶），键 mrr_at_10/ndcg_at_10——不进
    任何通过线、不改单题 pass。

    难负例负锚（R3 前瞻字段，2026-09-28，只测不判——纪律同 MRR/nDCG）：题带
    hard_negatives 时对 top-5 逐块与各 spec 做 doc_match 归一匹配（与正主锚
    同一匹配器，不另起炉灶），命中记 hard_neg_hits=[{rank,doc,spec,reason}]、
    hard_neg_count=len(hits)、hard_neg_n=配置负锚数（汇总分母用）——**不进单题
    pass**（负锚命中是 precision 信号非判据；门禁定线留给后续）。

    返回 dict：pass/top5_ok/locator_ok/hit_rank/hit_doc/hit_locator/hit_score/
    cross_hits（top-5 中预期域之外的命中数）+ 题面字段回显 + judge_type/
    unexpected_hit/anchor_hits（逐锚明细）+ expect_domain/domain_hit/
    domain_rank/domain_criterion/domain_hit_doc（未配置题为 ""/None）+
    mrr_at_10/ndcg_at_10（排序质量，只测不判）+ hard_neg_hits/hard_neg_count/
    hard_neg_n（难负例负锚，只测不判；未配置题恒 []/0/0）。
    """
    anchors = _question_anchors(q)
    jtype = q.get("judge_type") or "relevance"
    doms = set(q.get("domains") or [])
    if not doms:
        doms = {a["domain"] for a in anchors if a.get("domain")}
        if not doms and q.get("domain"):
            doms = {q["domain"]}
    dspec = _norm_domain_spec(q.get("expect_domain"))
    states = [{"rank": None, "meta": None, "top5": False, "loc": False}
              for _ in anchors]
    best = best_meta = None
    cross = 0
    grades = []   # 改造三：top-10 逐位分级增益（primary=1.0／secondary=0.5／未命中=0）
    for h in hits:
        meta = meta_by_id.get(h["id"]) or {}
        matched = False
        g = 0.0
        for a, st in zip(anchors, states):
            if doc_match(meta, a["expect_doc"]):
                matched = True
                g = max(g, 1.0 if a.get("role", "primary") == "primary" else 0.5)
                if st["rank"] is None:
                    st["rank"], st["meta"] = h["rank"], meta
                if h["rank"] <= 5:
                    st["top5"] = True
                if not st["loc"] and _compiled(a["expect_locator_pattern"]).search(
                        locator_text(meta)):
                    st["loc"] = True
        if h["rank"] <= 10:
            grades.append(g)
        if matched and best is None:
            best, best_meta = h, meta
        if h["rank"] <= 5 and doms and not (doms & hit_domains(meta)) \
                and not _meta_in_domain(meta, dspec):
            cross += 1
    # expect_domain 域判定：首个域内块（rank 升序扫全部 hits 回显位次；域中=位次
    # 落 criterion 深度内）——域级粒度判"该域是否被检索到"，不判具体哪张卡。
    dom_hit = dom_rank = None
    dom_doc = ""
    if dspec:
        dom_hit = False  # 已配置即有判定值（False=域 miss）；None 留给未配置题
        depth = 5 if dspec["criterion"] == "top5" else 10
        for h in hits:
            meta = meta_by_id.get(h["id"]) or {}
            if _meta_in_domain(meta, dspec):
                dom_rank = h["rank"]
                dom_doc = str(meta.get("doc_id") or meta.get("src")
                              or meta.get("id") or "")
                dom_hit = h["rank"] <= depth
                break
    # 难负例负锚判定（R3 前瞻字段，2026-09-28，**只测不判**）：top-5 逐块与各负锚
    # spec 做 doc_match 归一匹配（复用正主锚同一匹配器）；命中只记 precision 信号
    # （hard_neg_hits/hard_neg_count），绝不进单题 pass 亦不计跨域——门禁定线留后续。
    hard_negs = q.get("hard_negatives") or []
    hard_neg_hits = []
    for h in hits:
        if h["rank"] > 5:
            continue
        meta = meta_by_id.get(h["id"]) or {}
        for hn in hard_negs:
            if doc_match(meta, [hn["spec"]]):
                hard_neg_hits.append(
                    {"rank": h["rank"],
                     "doc": str(meta.get("doc_id") or meta.get("src")
                                or meta.get("id") or ""),
                     "spec": hn["spec"], "reason": hn.get("reason", "")})

    def _anchor_ok(a, st):
        if a["criterion"] == "top5":
            return st["top5"]
        return st["rank"] is not None and st["rank"] <= 10 and st["loc"]  # top10_locator

    prim = [(a, st) for a, st in zip(anchors, states)
            if a.get("role", "primary") == "primary"]
    top5_ok = any(st["top5"] for st in states)
    locator_ok = any(st["loc"] for st in states)
    if jtype == "expect_miss":
        unexpected = any(st["rank"] is not None for st in states)
        passed = not unexpected  # miss 即达标
    else:
        unexpected = False
        passed = any(_anchor_ok(a, st) for a, st in prim)
    crit_display = q.get("criterion")
    if crit_display is None:
        crit_display = "+".join(sorted({a["criterion"] for a, _ in prim})) or "-"
    mrr10, ndcg10 = _mrr_ndcg(grades)
    return {
        "id": q["id"], "category": q.get("category", ""),
        "domain": q.get("domain") or ("／".join(sorted(doms)) if doms else ""),
        "domains": sorted(doms), "judge_type": jtype,
        "criterion": crit_display, "query": q.get("query", ""),
        "note": q.get("note", ""), "retest": q.get("retest", False),
        "pass": passed, "top5_ok": top5_ok, "locator_ok": locator_ok,
        "hit_rank": best["rank"] if best else None,
        "hit_doc": (str(best_meta.get("doc_id") or best_meta.get("src")
                     or best_meta.get("id") or "")) if best else "",
        "hit_locator": locator_text(best_meta)[:60] if best else "",
        "hit_score": best["score"] if best else None,
        "cross_hits": cross,
        "unexpected_hit": unexpected,
        "expect_miss_layer": q.get("expect_miss_layer") or "",
        "expect_domain": dspec["domain"] if dspec else "",
        "domain_hit": dom_hit,
        "domain_rank": dom_rank,
        "domain_criterion": dspec["criterion"] if dspec else "",
        "domain_hit_doc": dom_doc,
        "anchor_hits": [{"doc": "／".join(a["expect_doc"]),
                         "role": a.get("role", "primary"),
                         "criterion": a["criterion"],
                         "hit_rank": st["rank"], "locator_ok": st["loc"],
                         "ok": _anchor_ok(a, st)}
                        for a, st in zip(anchors, states)],
        "mrr_at_10": mrr10, "ndcg_at_10": ndcg10,
        "hard_neg_hits": hard_neg_hits, "hard_neg_count": len(hard_neg_hits),
        "hard_neg_n": len(hard_negs),
    }


# ---------------------------------------------------------------------------
# 管线视图通道（--pipeline-view，门禁双视图=C 线收口批 2026-10-08 夜；依据=
# 运营/门禁口径偏差复核-BM25段-20261003.md 建议②落地+用户批 C 线路径；
# 判据预登记=建库/work/词面通道复放-20261008/门禁双视图-判据预登记-20261008.md）
#
# 语义：默认关（PIPELINE_VIEW["on"]=False）=本模块零调用面、输出与历史逐字节
# 一致；开启时每题在既有纯余弦判定外，另按下方生产键面镜像经 importlib 只读
# 装载仓根 rag.py 跑 RagService.retrieve，取终证据 top5（sources 窗）复用同一
# judge_question 判卷（禁另写判卷）——门禁证书双视图并列，判定面归 eval_gate
# 的卷线 "view" 键绑定。查询向量=复用本次运行已就绪的内存向量（零新增 API）。
# ---------------------------------------------------------------------------
PIPELINE_VIEW = {"on": False, "svc": None, "rag": None, "route": None,
                 "embed_map": {}, "n_hit": 0, "n_gate": 0, "n_miss_vec": 0,
                 "n_err": 0, "loaded": None, "rag_md5": "", "rag_md5_ok": None}

# 生产键面镜像（快照 2026-10-08 拨键批后现役态；同构源=建库/scripts/
# mq同构评测-20261006.py CLOUD_RAG + 运营/测试体系-20261007/拨键执行单-
# b类round-20261008.md 三键翻转面。⚠️库态联动纪律：生产拨键/换库变更须
# 同步本镜像并决策，禁自动跟改）
PIPELINE_CFG = {
    "enabled": True, "topk": 5, "max_context_chars": 6000,
    "store_path": "建库/vectors/embeddings.jsonl",
    "timeout_seconds": 3, "embed_model": "text-embedding-v4",
    "mq_enabled": True, "mq_single_variant": True, "mq_wall_clock": False,
    "mq_n_variants": 2, "mq_model": "qwen3.8-flash",
    "hybrid_bm25_enabled": True, "hybrid_gated_enabled": True,
    "lexical_boost": False,
    "same_source_fold_enabled": True, "same_source_fold_scope": "tables+asn1",
    "b_evict_enabled": True,
    "family_select_enabled": True, "family_select_scope": "miit+clone",
    "family_select_words": "full", "clone_fold_min_margin": 1,
    "spec_suppress_enabled": True,
    "route_enabled": True, "route_min_confidence": 1,
    "route_conflict_policy": "fallback", "route_vocab": None,
    "route_light_topk": 3, "route_table_facet": False, "route_doc_direct": True,
    "table_downweight_enabled": True, "table_downweight_factor": 0.85,
    "table_downweight_scope": "tables",
    "table_downweight_docs": ["38.133", "38.300", "36.213", "36.101", "38.101",
                              "36.413", "38.413", "38.104", "38.533", "36.104",
                              "36.314", "38.314", "38.803", "38.306", "38.212",
                              "36.212", "38.423", "36.423", "38.473", "38.401"],
    # 2026-10-13 L2 重上窗：镜像随拨键后生产键面扩为乙案 20 值（尾 append 15 新值；
    # 清单=建库/logs/扩容-L2前置复算-20261007/复算.json 草案乙；36.104 白名单同号表
    # 单点泄漏=观测位在档不扩白名单；生产 config 拨键归 L2 重上换库窗载荷）。
    "table_downweight_whitelist": ["5\\.6 Table 5\\.6-1", "^7\\.2\\.3 "],
    "domain_downweight": {"telecomhall": 0.05, "ydt": 0.85, "handwritten": 0.85},  # 2026-10-09 丙配额轮备选案：quota 治 C25 单doc洪泛后 C17 系ydt 多doc语义占位（扩锚不成立=投诉流程锚监管条款）——域降权 0.85（表降权标准因子先例）；判据=C17 回且 G42/G43 保持，破则弃（配额轮-判据预登记 备选案）。2026-10-12 Wave4 增 handwritten:0.85（F2 域席位治理决策：五卡入席挤占 C17/C24 锚的检索结构面处置；仿真绑定读数=合围-F2域席位治理-20261012/仿真-pipe-k1_dw085.json top5_n_pipeline=25/28；判据=C 卷管线 25/28 复现且 A/B/Y/S1 面零退化，破则停线；生产 config 拨键归换库窗载荷）
    "domain_doc_quota": {"miit": 1, "ydt": 1},  # 2026-10-09 丙配额轮：ydt 域内
    # 每 doc ≤1 席（案丙 miit:1 同款；过程日志 59 决策分支 a；判据预登记=
    # 建库/work/乙AB-20261009/配额轮-判据预登记-20261009.md）
    "decrowd_candidates": 60,
    "doc_quota_enabled": False, "meta_filter_v1": False,
    "score_threshold": 0.4, "cover_gate_enabled": True,
    "clause_family_rerank": True, "clause_family_rerank_words": "full",
    "faiss_enabled": True,
    "embed_monthly_budget_enabled": False,
    "retrieval_snapshot_dir": None,
}
PIPELINE_RAG_MD5 = "bc1219c482348bcacb3f4ea43dcd5fff"   # rag.py 0584389 终版锚


class PipelineEmbedMiss(RuntimeError):
    """管线视图查询向量缺口（绝不转 API）——该题管线面记 state=embed_miss。"""


def _pipeline_embed_fn(q):
    v = PIPELINE_VIEW["embed_map"].get(str(q or ""))
    if v is None:
        raise PipelineEmbedMiss("pipeline embed cache miss")
    return list(v)


def _pipeline_variant_fn(q):
    return []          # 空变体=生产同构退化路（单条原查询，零真实生成）


def _pipeline_noop_log(msg):
    pass


def init_pipeline_view(questions, qvecs, say=print):
    """按生产键面镜像装载复刻 RagService（importlib 只读装载仓根 rag.py）。

    - embed_map=题面→向量（复用调用方已就绪的内存向量，零新增 API）；
    - rag.md5 与锚不符=注记不阻断（漂移面如实入证书）；
    - 装载失败=on 翻 False 整体降级 cos-only（显式打印，不伪绿）。
    """
    import hashlib
    from importlib.util import spec_from_file_location, module_from_spec
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    rag_path = os.path.join(root, "rag.py")
    try:
        with open(rag_path, "rb") as f:
            md5 = hashlib.md5(f.read()).hexdigest()
        PIPELINE_VIEW["rag_md5"] = md5
        PIPELINE_VIEW["rag_md5_ok"] = (md5 == PIPELINE_RAG_MD5)
        if not PIPELINE_VIEW["rag_md5_ok"]:
            say("[pipeline] ⚠ rag.py md5 漂移：%s ≠ 锚 %s（读数带此注记）"
                % (md5[:8], PIPELINE_RAG_MD5[:8]))
        spec = spec_from_file_location("smoke_pipeline_rag", rag_path)
        rag = module_from_spec(spec)
        spec.loader.exec_module(rag)
        svc = rag.RagService(embed_fn=_pipeline_embed_fn,
                             log=_pipeline_noop_log, base_dir=root,
                             variant_fn=_pipeline_variant_fn)
        svc.initialize(json.loads(json.dumps(PIPELINE_CFG)))
        assert getattr(svc, "loaded", False), "pipeline 库装载失败"
        st = svc.stats
        PIPELINE_VIEW["loaded"] = st.get("loaded")
        PIPELINE_VIEW["svc"], PIPELINE_VIEW["rag"] = svc, rag
        try:
            from importlib.util import spec_from_file_location as _sf
            s2 = _sf("smoke_pipeline_route", os.path.join(root, "route_domain.py"))
            route = module_from_spec(s2)
            s2.loader.exec_module(route)
            PIPELINE_VIEW["route"] = route
        except Exception:
            PIPELINE_VIEW["route"] = None
            say("[pipeline] route_domain 装载失败（route_res=None 形降级）")
    except Exception as e:
        PIPELINE_VIEW["on"] = False
        say("[pipeline] ⚠ 复刻装载失败，整体降级 cos-only：%s" % type(e).__name__)
        return
    m = {}
    for q, qv in zip(questions, qvecs):
        t = str(q.get("query", ""))
        if t and qv is not None and t not in m:
            m[t] = qv
    PIPELINE_VIEW["embed_map"] = m
    say("[pipeline] 复刻装载毕 loaded=%s（镜像=拨键批后生产键面；embed_map=%d 题）"
        % (PIPELINE_VIEW["loaded"], len(m)))


def pipeline_eval(q, meta_by_id):
    """单题管线视图判定（复用 judge_question；返回 dict 或 None=未启用/无向量）。"""
    if not (PIPELINE_VIEW["on"] and PIPELINE_VIEW["svc"] is not None):
        return None
    query = str(q.get("query", ""))
    if query not in PIPELINE_VIEW["embed_map"]:
        PIPELINE_VIEW["n_miss_vec"] += 1
        return {"state": "embed_miss", "top5_ok": None, "hit_rank": None,
                "hit_doc": ""}
    try:
        route_res = None
        if PIPELINE_VIEW["route"] is not None:
            route_res = PIPELINE_VIEW["route"].classify(
                query, min_confidence=1, conflict_policy="fallback",
                doc_direct_enabled=True)
        result = PIPELINE_VIEW["svc"].retrieve(query, route_res)
    except PipelineEmbedMiss:
        PIPELINE_VIEW["n_miss_vec"] += 1
        return {"state": "embed_miss", "top5_ok": None, "hit_rank": None,
                "hit_doc": ""}
    except Exception:
        PIPELINE_VIEW["n_err"] += 1
        return {"state": "err", "top5_ok": None, "hit_rank": None, "hit_doc": ""}
    rag = PIPELINE_VIEW["rag"]
    if isinstance(result, rag.LowScoreResult) or \
            isinstance(result, rag.CoverageMissResult) or result is None:
        PIPELINE_VIEW["n_gate"] += 1
        state = ("low_score" if isinstance(result, rag.LowScoreResult)
                 else "coverage_miss" if isinstance(result, rag.CoverageMissResult)
                 else "miss_none")
        return {"state": state, "top5_ok": False, "hit_rank": None, "hit_doc": ""}
    ev, srcs = result
    hits = [{"id": s.get("id"), "rank": i, "score": float(s.get("score") or 0.0)}
            for i, s in enumerate(srcs or [], 1)]
    r2 = judge_question(q, hits, meta_by_id)
    PIPELINE_VIEW["n_hit"] += 1
    return {"state": "hit", "top5_ok": bool(r2["top5_ok"]),
            "hit_rank": r2["hit_rank"], "hit_doc": r2["hit_doc"]}


def _attach_pipeline(r, q, meta_by_id):
    """把管线视图判定字段并入 cosine 判定 dict r（只增不改既有键）。"""
    p = pipeline_eval(q, meta_by_id)
    if p is None:
        return
    r["pipeline_state"] = p["state"]
    r["pipeline_top5_ok"] = p["top5_ok"]
    r["pipeline_hit_rank"] = p["hit_rank"]
    r["pipeline_hit_doc"] = p["hit_doc"]


def pipeline_paper_metrics(results):
    """卷级管线视图指标（口径同 summarize_paper 的 top5_n/top5_rate：分母=
    relevance 题；管线窗=终证据 top5，top10_locator 判据在管线视图下窗截断、
    只取 top5_ok 口径——判据预登记 §三已注记）。"""
    rel = [r for r in results if r.get("judge_type", "relevance") == "relevance"]
    have = [r for r in rel if r.get("pipeline_top5_ok") is not None]
    if not have:
        return None
    top5_n = sum(1 for r in have if r["pipeline_top5_ok"])
    return {"top5_n_pipeline": top5_n, "n_rel_pipeline": len(have),
            "top5_rate_pipeline": round(top5_n / len(have), 6) if have else 0.0}


def pipeline_cert_block():
    """证书顶层 views 块（cosine=既有口径注记；pipeline=镜像快照+覆盖面）。"""
    st = PIPELINE_VIEW
    return {"cosine": {
                "channel": "cosine",
                "note": "纯余弦独立仪器视图（不读 rag 配置，键值与键集不动）"},
            "pipeline": {
                "config_snapshot": "生产键面镜像 2026-10-08 拨键批后"
                                   "（CLOUD_RAG+词面双键+fold_scope+spec_suppress）",
                "rag_md5": st["rag_md5"], "rag_md5_anchor_ok": st["rag_md5_ok"],
                "loaded": st["loaded"], "window": "sources_top5",
                "counts": {"hit": st["n_hit"], "gate": st["n_gate"],
                           "embed_miss": st["n_miss_vec"], "err": st["n_err"]},
                "note": "判卷复用 judge_question；top10_locator 判据窗截断只取"
                        " top5_ok；生产键面变更须同步镜像并决策"}}


# ---------------------------------------------------------------------------
# 判卷侧"父-子同文豁免"规则（甲，S1 负控治理 2026-09-28 选项一）
#
# 语义对齐件=建库/scripts/s1_negctrl_eval.py try_judge_exempt（离线验证在档：
# 甲单走 4/15 仅销 S1V-15 形式 FAIL，运营/S1治理离线验证结果-20260928.md）。
# 机制：型3 子款负控题的形式 FAIL（同款族父条压入 top-3 构成串号）在回源实证
# "父条与正主子款块文本同文"（实质误导面近零）且 top-5 无错误数值块时，不计
# 串号 FAIL——判卷口径修正，零动检索。规则触发必须挂块级同文证据（chunk id+
# 归一化全文比对留痕），不挂题面相似度（防口径自证松动，方案 §二路径甲）。
# 本件为共享判卷规则的生产落点（判定语义对齐件；s1_negctrl_eval 内嵌同款判其
# S1 卷，判卷口径未来并入 judge 校准转正时消费本函数——方案 §五.7 在册）。
# ---------------------------------------------------------------------------
_EXEMPT_SUB_RE = re.compile(r"( 款\d+)$")


def clause_sub_suffix(loc):
    """款号后缀（如" 款2"；无款返回 None）。"""
    m = _EXEMPT_SUB_RE.search(str(loc or ""))
    return m.group(1) if m else None


def clause_parent_of(loc):
    """父条 locator：剥除款号后缀（无款原样返回）。"""
    loc = str(loc or "")
    m = _EXEMPT_SUB_RE.search(loc)
    return loc[: len(loc) - len(m.group(1))] if m else loc


def _exempt_norm(s):
    """同文比对归一：去全部空白+小写（CJK 无空格语义，ASCII 大小写不敏感）。"""
    return re.sub(r"\s+", "", str(s or "")).lower()


def _exempt_body(content):
    """块正文=剥除首行【…】定位头后的正文（父/子同文比对用，头行两边同构）。"""
    parts = str(content or "").split("\n", 1)
    return parts[1] if len(parts) > 1 else parts[0]


def family_trap_ranks(hits, meta_by_id, sub_locator, top=3):
    """同款族串号块判定：top-N 内与正主子款同款族（同条款号、非子款本身）的块。

    返回 [(rank, locator), ...]（rank 升序）。族判定=locator 等于父条（子款
    locator 剥款号后缀）或为父条的其他款（父条+' 款N'）——对应 S1 负控型3 的
    "父条/兄弟子款"串号形态；跨附录同名等非同族陷阱不在本判定面（甲豁免的
    触发面本就收口在同款族父子形态）。
    """
    sub_locator = str(sub_locator or "")
    parent = clause_parent_of(sub_locator)
    out = []
    for h in hits[: max(1, int(top))]:
        meta = meta_by_id.get(h["id"]) or {}
        loc = str(meta.get("locator") or "")
        if loc == sub_locator:
            continue  # 正主子款本身不算串号（C棒口径）
        if loc == parent or loc.startswith(parent + " 款"):
            out.append((h["rank"], loc))
    return out


def try_judge_exempt(hits, meta_by_id, sub_locator, trap3=None):
    """甲：父-子同文豁免 → (fired, evidence)（四要件逐项留痕，任一不满足不豁免）。

    hits 形态=judge_question 同款（[{"rank","score","id"},...]，rank 升序，
    判定面=top-5）；meta_by_id=id→chunk 全字段（locator/content 必备）；
    sub_locator=正主子款 locator（款级）；trap3 缺省=family_trap_ranks(hits,
    meta_by_id, sub_locator, top=3)（调用方持 hint 点名陷阱清单时可显式传入，
    语义=s1_negctrl_eval.try_judge_exempt 的 trap3 参数）。

    四要件（对齐 s1_negctrl_eval 甲实现，语义一致）：
      ① 型3 FAIL 由正主款族父条构成：子款与父条均在 top-5，且 top-3 串号块
         恰为父条（无其他串号块）；
      ② 同文实证：子款正文（剥【…】头行+去空白归一）⊆ 父条正文；
      ③ 父条余文（剥离子款正文后）不含任何数字——父条不携带兄弟子款数值
         （区别于 3.2.1/1.2.3 等"父条含双值"歧义源）；
      ④ top-5 其余块无与正主答案同位数的异值数字（无错误数值块）。
    """
    def _hit_by_loc(loc):
        for h in hits:
            meta = meta_by_id.get(h["id"]) or {}
            if str(meta.get("locator") or "") == loc:
                return h, meta
        return None, None

    sub_locator = str(sub_locator or "")
    sub_hit, sub_meta = _hit_by_loc(sub_locator)
    if sub_hit is None:
        return False, {"note": "正主子款不在 top-5"}
    parent_loc = clause_parent_of(sub_locator)
    parent_hit, parent_meta = _hit_by_loc(parent_loc)
    if parent_hit is None:
        return False, {"note": "父条不在 top-5"}
    if trap3 is None:
        trap3 = family_trap_ranks(hits, meta_by_id, sub_locator, top=3)
    other_trap3 = [(r, loc) for r, loc in trap3 if loc != parent_loc]
    if not any(loc == parent_loc for _, loc in trap3) or other_trap3:
        return False, {"note": "FAIL 非单纯由父条构成", "top3_串号": trap3}
    child_body = _exempt_norm(_exempt_body(sub_meta.get("content")))
    parent_body = _exempt_norm(_exempt_body(parent_meta.get("content")))
    if not child_body or child_body not in parent_body:
        return False, {"note": "父子正文非同文（子款正文⊄父条正文）"}
    extra = parent_body.replace(child_body, "", 1)
    if re.search(r"\d", extra):
        return False, {"note": "父条余文含数字（携带其他数值，数值歧义源）",
                       "余文数字": re.findall(r"\d+", extra)}
    child_digits = set(re.findall(r"\d+", child_body))
    digit_lens = {len(d) for d in child_digits}
    conflict = []
    for h in hits:
        if h["id"] in (sub_hit["id"], parent_hit["id"]):
            continue
        meta = meta_by_id.get(h["id"]) or {}
        for d in re.findall(r"\d+", _exempt_norm(meta.get("content"))):
            if len(d) in digit_lens and d not in child_digits:
                conflict.append({"locator": str(meta.get("locator") or ""), "数字": d})
                break
    if conflict:
        return False, {"note": "top-5 存在同位数异值块（错误数值块）", "冲突": conflict}
    return True, {"规则": "父-子同文豁免",
                  "父条": {"chunk_id": parent_hit["id"], "locator": parent_loc,
                           "rank": parent_hit["rank"]},
                  "子款": {"chunk_id": sub_hit["id"], "locator": sub_locator,
                           "rank": sub_hit["rank"]},
                  "同文实证": "子款正文⊆父条正文（剥【…】头行+去空白归一）",
                  "父条余文数字": "无", "top5_异值块": "无"}


def summarize(results):
    """四指标 vs 通过线（口径同题卷卷首）+ 排序质量 MRR/nDCG 均值 + 难负例负锚
    命中率（后两者只测不判）。返回 dict，含 all_pass。"""
    n = len(results)
    top5_n = sum(1 for r in results if r["top5_ok"])
    mon = [r for r in results if r["category"] == "监管数字"]
    par = [r for r in results if r["category"] == "表格值/参数卡"]
    mon_hits = sum(1 for r in mon if r["pass"])
    par_hits = sum(1 for r in par if r["pass"])
    cross_total = sum(r["cross_hits"] for r in results)
    top5_rate = (top5_n / n) if n else 0.0
    mrr10 = (sum(r.get("mrr_at_10", 0.0) for r in results) / n) if n else 0.0
    ndcg10 = (sum(r.get("ndcg_at_10", 0.0) for r in results) / n) if n else 0.0
    # 难负例负锚（R3，只测不判）：内置卷现无带负锚题 → 恒 0/0/None，仅保键位
    # 对称（_builtin_paper_json 取固定键集，json 输出零变化）
    hard_neg_qs = [r for r in results if r.get("hard_neg_n")]
    hard_neg_hit_qs = sum(1 for r in hard_neg_qs if r.get("hard_neg_count"))
    checks = {
        "top5_rate": top5_rate >= PASS_LINES["top5_rate_min"],
        "monitor_hits": mon_hits >= PASS_LINES["monitor_hits_min"],
        "param_hits": par_hits >= PASS_LINES["param_hits_min"],
        "cross_domain": cross_total <= PASS_LINES["cross_domain_max"],
    }
    return {"n": n, "top5_n": top5_n, "top5_rate": top5_rate,
            "monitor_hits": mon_hits, "monitor_n": len(mon),
            "param_hits": par_hits, "param_n": len(par),
            "cross_total": cross_total, "checks": checks,
            "mrr_at_10": mrr10, "ndcg_at_10": ndcg10,
            "hard_neg_total": len(hard_neg_qs),
            "hard_neg_hit_questions": hard_neg_hit_qs,
            "hard_neg_hit_rate": (hard_neg_hit_qs / len(hard_neg_qs))
            if hard_neg_qs else None,
            "all_pass": all(checks.values())}


def summarize_paper(results, pass_lines=None):
    """外部卷通用指标（relevance 四指标测量值 + expect_miss"miss 即达标"率）。

    与内置卷 summarize 的差别：类别名不设限（B/C/Y 类目各异），监管/参数两线按
    题的预期域与判据线归类——监管域命中=预期域含"监管"的 relevance 题过题数；
    参数/行级出处=含 primary top10_locator 锚的 relevance 题过题数。pass_lines
    为 None 时只测不判（checks=None，all_pass 恒 True，不计入退出码）；设线的卷
    缺哪类题则该线视为过（缺类不罚，报告标注"卷内无此类"）。
    """
    rel = [r for r in results if r.get("judge_type", "relevance") == "relevance"]
    mis = [r for r in results if r.get("judge_type") == "expect_miss"]
    dom = [r for r in results if r.get("expect_domain")]

    def _is_monitor(r):
        ds = r.get("domains") or ([r["domain"]] if r.get("domain") else [])
        return "监管" in ds

    def _is_param(r):
        if r.get("criterion") == "top10_locator":  # 扁平单锚形态
            return True
        return any(a.get("criterion") == "top10_locator"
                   and a.get("role", "primary") == "primary"
                   for a in r.get("anchor_hits", []))  # 多锚形态只认 primary

    mon = [r for r in rel if _is_monitor(r)]
    par = [r for r in rel if _is_param(r)]
    top5_n = sum(1 for r in rel if r["top5_ok"])
    mon_hits = sum(1 for r in mon if r["pass"])
    par_hits = sum(1 for r in par if r["pass"])
    cross_total = sum(r["cross_hits"] for r in results)
    miss_pass = sum(1 for r in mis if r["pass"])
    unexpected_n = sum(1 for r in mis if r.get("unexpected_hit"))
    dom_hits = sum(1 for r in dom if r.get("domain_hit"))
    top5_rate = (top5_n / len(rel)) if rel else 0.0
    miss_rate = (miss_pass / len(mis)) if mis else None
    dom_rate = (dom_hits / len(dom)) if dom else None
    # 排序质量（改造三）：relevance 题口径（expect_miss 题锚=预期 miss，无"应命中
    # 分级"语义，不计入分母）
    mrr10 = (sum(r.get("mrr_at_10", 0.0) for r in rel) / len(rel)) if rel else 0.0
    ndcg10 = (sum(r.get("ndcg_at_10", 0.0) for r in rel) / len(rel)) if rel else 0.0
    # 难负例负锚（R3 前瞻字段，2026-09-28，只测不判）：分母=带负锚题数
    # （hard_neg_n>0），分子=有负锚进 top-5 的题数；零带负锚卷三键 0/0/None，
    # 不进 checks（无通过线键——门禁定线留后续）
    hard_neg_qs = [r for r in results if r.get("hard_neg_n")]
    hard_neg_hit_qs = sum(1 for r in hard_neg_qs if r.get("hard_neg_count"))
    checks, all_pass = None, True
    if pass_lines:
        def _chk(key, ok_fn):
            return (key not in pass_lines) or ok_fn()  # 未设该线=不判；设了但卷内无此类题=不罚
        checks = {
            "top5_rate": _chk("top5_rate_min", lambda: (
                (not rel) or top5_rate >= pass_lines["top5_rate_min"])),
            "monitor_hits": _chk("monitor_hits_min", lambda: (
                (not mon) or mon_hits >= pass_lines["monitor_hits_min"])),
            "param_hits": _chk("param_hits_min", lambda: (
                (not par) or par_hits >= pass_lines["param_hits_min"])),
            "cross_domain": _chk("cross_domain_max", lambda: (
                cross_total <= pass_lines["cross_domain_max"])),
            "expect_miss_rate": _chk("expect_miss_rate_min", lambda: (
                (not mis) or miss_rate >= pass_lines["expect_miss_rate_min"])),
            "domain_rate": _chk("domain_rate_min", lambda: (
                (not dom) or dom_rate >= pass_lines["domain_rate_min"])),
        }
        all_pass = all(checks.values())
    return {"n": len(results), "n_rel": len(rel), "n_miss": len(mis),
            "top5_n": top5_n, "top5_rate": top5_rate,
            "monitor_hits": mon_hits, "monitor_n": len(mon),
            "param_hits": par_hits, "param_n": len(par),
            "cross_total": cross_total,
            "miss_pass": miss_pass, "miss_rate": miss_rate,
            "unexpected_hits": unexpected_n,
            "n_domain": len(dom), "domain_hits": dom_hits, "domain_rate": dom_rate,
            "mrr_at_10": mrr10, "ndcg_at_10": ndcg10,
            "hard_neg_total": len(hard_neg_qs),
            "hard_neg_hit_questions": hard_neg_hit_qs,
            "hard_neg_hit_rate": (hard_neg_hit_qs / len(hard_neg_qs))
            if hard_neg_qs else None,
            "checks": checks, "all_pass": all_pass, "pass_lines": pass_lines}


# ---------------------------------------------------------------------------
# 统计切片报告（--slices；2026-09-28 第 3 批 E3——默认关=输出逐字节零变化：
# 不给 flag 时本节函数零调用，--json papers[].slices 键与 md 报表"切片"段均不出现。
# 纪律同 MRR/nDCG/hard_negatives：只测不判，不进任何通过线、不改单题 pass）
# ---------------------------------------------------------------------------
SLICE_UNSET = "未标注"
# 四维固定键序（json papers[].slices 键集=测试断言面）
SLICE_DIMS = ("domain", "criterion", "category", "difficulty")


def difficulty_of_note(note):
    """题卷 note 难度标注解析：含 "Difficult" → Difficult；含 "Basic" → Basic；
    均无 → 未标注。大小写敏感（题卷先例=首词大写："Basic；命题依据…"／
    "Difficult（…）。命题依据…"，见 答案卷-1.0 两 part）；两词同现按 Difficult
    认（从严取难）。"""
    s = str(note or "")
    if "Difficult" in s:
        return "Difficult"
    if "Basic" in s:
        return "Basic"
    return SLICE_UNSET


def _slice_domain(r):
    """切片用题级 domain：judge 结果 domain（锚域并集，如 "3gpp"／"监管"／
    "3gpp／监管"）；空缺时回退 expect_domain 域名（如 "合成卡"——C 卷新域题
    锚域标注与预期域同现时以锚域为准）；再空缺=未标注。"""
    return r.get("domain") or r.get("expect_domain") or SLICE_UNSET


def slice_results(results):
    """judge 结果列表 → 四维切片 {dim: {组: {n, top5_rate, judge_pass_rate}}}。

    - 组键：domain=_slice_domain；criterion=judge 结果判据（top5／top10_locator／
      多锚并集"top5+top10_locator"）；category=题级类别；difficulty=note 解析；
    - 每组三测量值：n=组内题数；top5_rate=top5_ok 均值（expect_miss 题同口径
      计入——"意外命中率"即该组该值的补）；judge_pass_rate=单题判过均值
      （expect_miss 题=miss 即达标口径）；
    - 只测不判：不进 checks/通过线；纯函数零 IO，组按字典序稳定输出。
    """
    def _one(rs):
        n = len(rs)
        return {"n": n,
                "top5_rate": (sum(1 for r in rs if r.get("top5_ok")) / n) if n else 0.0,
                "judge_pass_rate": (sum(1 for r in rs if r.get("pass")) / n) if n else 0.0}

    def _by(keyfn):
        groups = {}
        for r in results:
            groups.setdefault(keyfn(r), []).append(r)
        return {k: _one(rs) for k, rs in sorted(groups.items())}

    return {
        "domain": _by(_slice_domain),
        "criterion": _by(lambda r: r.get("criterion") or SLICE_UNSET),
        "category": _by(lambda r: r.get("category") or SLICE_UNSET),
        "difficulty": _by(lambda r: difficulty_of_note(r.get("note"))),
    }


# ---------------------------------------------------------------------------
# 库加载辅助（doc_id/locator 元数据补齐）
# ---------------------------------------------------------------------------
def load_meta_by_id(path):
    """重扫库文件 → {id: chunk 全字段 dict}（retrieve.load_library 不随行 doc_id/locator）。"""
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue  # 在飞续写中间态行，跳过（口径同 retrieve）
            if isinstance(obj, dict) and obj.get("id"):
                out[obj["id"]] = obj
    return out


# ---------------------------------------------------------------------------
# query 向量化（--yes 放行后；embed_common 通道：退避/维度校验/脱敏）
# ---------------------------------------------------------------------------
def embed_queries(queries, cfg, api_settings=None, embed_fn=None, say=print):
    """批量向量化。返回 (vecs, total_prompt_tokens)。

    - 按 cfg["batch"] 分批（API 批量上限 10，配置层已校验）；
    - 每批后核累计估算费用 ≥ red_line_cny 即熔断（口径同 run_pipeline）；
    - embed_fn 可注入假函数（--self-test/单测零 API 零计费）。
    """
    if embed_fn is None:
        if api_settings is None:
            raise ValueError("真跑须给 api_settings 或注入 embed_fn")
        embed_fn = lambda texts: embed_common.embed_batch(texts, cfg, api_settings)
    vecs, total_tokens = [], 0
    n_batches = (len(queries) + cfg["batch"] - 1) // cfg["batch"]
    for bi, i in enumerate(range(0, len(queries), cfg["batch"]), 1):
        part = queries[i:i + cfg["batch"]]
        vs, usage, retried, err = embed_fn(part)
        if err:
            raise RuntimeError("嵌入批 %d/%d 失败：%s" % (
                bi, n_batches, json.dumps(err, ensure_ascii=False)))
        if len(vs) != len(part):
            raise RuntimeError("嵌入批 %d 返回条数 %d ≠ %d" % (bi, len(vs), len(part)))
        total_tokens += usage.get("prompt_tokens", 0)
        est = embed_common.estimate_cost_cny(total_tokens, cfg["price_per_mtok"])
        say("[embed] 批 %d/%d：n=%d tokens=%d retries=%d 累计估 %.6f 元" % (
            bi, n_batches, len(part), usage.get("prompt_tokens", 0), retried, est))
        if est >= cfg["red_line_cny"]:
            raise RuntimeError("红线熔断：累计估算 %.4f 元 ≥ %.2f 元红线，中止" % (
                est, cfg["red_line_cny"]))
        vecs.extend(vs)
    return vecs, total_tokens


# ---------------------------------------------------------------------------
# 机读 JSON 结果（--json；schema v1；2026-09-23 批A3①——只增不改：不给 json_path
# 时全部函数零调用，md 报表与 stdout 与历史版本逐字节一致）
# ---------------------------------------------------------------------------
def _stream_md5(path, chunk_bytes=1 << 20):
    """库文件流式 md5（库 ~660MB，禁整读内存；1MB 分块）。"""
    h = hashlib.md5()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk_bytes)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _lib_json_block(path, stats):
    """库文件 → json lib 块（rows=loaded 有效行数；_dim=向量维度；bad_lines=坏行数）。"""
    return {"path": path, "md5": _stream_md5(path), "rows": stats.get("loaded"),
            "_dim": stats.get("dim"), "bad_lines": stats.get("bad_lines")}


# ---------------------------------------------------------------------------
# 全量版本快照（--snapshot；2026-09-28 第 3 批 D2——默认关=输出逐字节零变化：
# 不给 flag 时本节函数零调用，--json 键集/md 报表/stdout 与历史版本逐字节一致）
# ---------------------------------------------------------------------------
def _file_sha16(path, chunk_bytes=1 << 20):
    """文件 sha256 前 16 位（流式读，禁整读内存）。**口径注**：hex[:16] 形态同
    synth_cards.template_sha256，但取整文件字节流——synth_cards 是按模板节拼装后
    取值（登记值 step1=4721238c7148ae94 等），两者数值不同用途不同：此处登记
    文件级指纹（快照对比用），不与生卡台账值互推。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk_bytes)
            if not b:
                break
            h.update(b)
    return h.hexdigest()[:16]


def _valid_line_count(path):
    """jsonl 有效行数（口径同 retrieve.load_library 的 loaded：空行/坏 JSON 行不计，
    在飞续写中间态行跳过——不整读内存，只数行不解析 embedding）。"""
    n = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                json.loads(line)
            except json.JSONDecodeError:
                continue
            n += 1
    return n


def _chunks_rows(cfg):
    """cfg["src_files"] 各切块源 jsonl → {配置原样路径: 有效行数}；文件缺失记 null
    （快照用途=如实登记环境，不因缺文件炸——对比时 null 即差异信号）。"""
    out = {}
    for p in (cfg.get("src_files") or []):
        rp = pipeline_config.resolve_path(p)
        out[str(p)] = _valid_line_count(rp) if os.path.exists(rp) else None
    return out


def _prompt_template_sha(cfg, prompts_dir=None):
    """synth prompt 模板文件 → {文件名: sha16}（按 cfg["synth_prompt_version"] 拼
    scripts/prompts/synth_step{1,2}_{ver}.md；cfg 无版本键/文件缺失 → 该位 null）。
    prompts_dir 供单测注入夹具目录（缺省=本件同目录 prompts/，只读不写）。"""
    out = {}
    ver = cfg.get("synth_prompt_version")
    if not ver:
        return out
    base = prompts_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "prompts")
    for step in (1, 2):
        name = "synth_step%d_%s.md" % (step, ver)
        p = os.path.join(base, name)
        out[name] = _file_sha16(p) if os.path.exists(p) else None
    return out


# 快照固定键序（测试断言面；改动=breaking，须同步 tests/test_snapshot_slices.py）
SNAPSHOT_KEYS = ("lib_path", "lib_md5", "lib_rows", "lib_bad_lines", "lib_dim",
                 "chunks_rows", "prompt_templates", "synth_prompt_version",
                 "model", "dims", "topk", "price_per_mtok", "red_lines",
                 "harness_sha16", "python")


def build_snapshot(cfg, lib_block, topk=None):
    """运行环境全量版本快照（--snapshot 门控；lib_block 复用 --json 已算的 lib 块，
    不二次流式读库算 md5）。"""
    return {
        "lib_path": lib_block["path"], "lib_md5": lib_block["md5"],
        "lib_rows": lib_block["rows"], "lib_bad_lines": lib_block["bad_lines"],
        "lib_dim": lib_block["_dim"],
        "chunks_rows": _chunks_rows(cfg),
        "prompt_templates": _prompt_template_sha(cfg),
        "synth_prompt_version": cfg.get("synth_prompt_version"),
        "model": cfg["model"], "dims": cfg["dims"],
        "topk": topk, "price_per_mtok": cfg["price_per_mtok"],
        "red_lines": {"embed": cfg["red_line_cny"],
                      "cr": cfg["cr_red_line_cny"],
                      "synth": cfg["synth_red_line_cny"]},
        "harness_sha16": _file_sha16(os.path.abspath(__file__)),
        "python": "%d.%d.%d" % sys.version_info[:3],
    }


_SNAP_MISSING = "<缺键>"


def snapshot_diff(new, old):
    """两快照 → {键: {"new": v, "old": v}}（仅差异键；dict 值展开为"父.子"平键——
    如 chunks_rows.3gpp.jsonl——表格友好；缺键侧记 <缺键>）。纯函数零 IO。"""
    out = {}
    for k in sorted(set(new) | set(old)):
        vn, vo = new.get(k, _SNAP_MISSING), old.get(k, _SNAP_MISSING)
        if vn == vo:
            continue
        if isinstance(vn, dict) and isinstance(vo, dict):
            for sk in sorted(set(vn) | set(vo)):
                svn, svo = vn.get(sk, _SNAP_MISSING), vo.get(sk, _SNAP_MISSING)
                if svn != svo:
                    out["%s.%s" % (k, sk)] = {"new": svn, "old": svo}
        else:
            out[k] = {"new": vn, "old": vo}
    return out


def _snapshot_diff_lines(diff):
    """两快照 diff → md 报表"快照对比"段行（空 diff=零行=不出现该段）。"""
    if not diff:
        return []
    lines = ["### 快照对比（--snapshot；新=--vectors 待评库，旧=--compare 基线；仅列差异键）",
             "", "| 键 | 新 | 旧 |", "|---|---|---|"]
    for k in sorted(diff):
        lines.append("| %s | %s | %s |" % (
            _cell(k), _cell(diff[k]["new"]), _cell(diff[k]["old"])))
    return lines


def _verdict_of(r):
    """judge 结果 → verdict 枚举：relevance→"pass"/"fail"；expect_miss→"miss_ok"/
    "unexpected_hit"（pass 布尔并存=r["pass"] 原值，机读侧两口径任取）。"""
    if r.get("judge_type") == "expect_miss":
        return "unexpected_hit" if r.get("unexpected_hit") else "miss_ok"
    return "pass" if r["pass"] else "fail"


def _question_json_row(paper_id, r, hits, faith_res=None, old=None,
                       answer_res=None, answers_on=False):
    """单题 json 行（schema v1）。top1_cosine=hits[0]["score"]；gate_score=防御性
    max（纯余弦降序=同值，分列防口径混列）；无 hits 均 None。old=(旧rank, 旧top1)
    仅 compare 模式给（追加 old_hit_rank/old_top1_cosine 两键，新库为 lib 主口径）。
    answer_res/answers_on（--answers 答案评测通道）：通道开启时追加 answer_judge
    键（结果 dict 或 null=降级/非评审对象）；通道关闭不给键（输出与历史逐字节一致）。"""
    top1 = hits[0]["score"] if hits else None
    gate = max(h["score"] for h in hits) if hits else None
    row = {"qid": r["id"], "paper_id": paper_id,
           "category": r.get("category", ""), "domain": r.get("domain", ""),
           "judge_type": r.get("judge_type", "relevance"),
           "verdict": _verdict_of(r), "pass": bool(r["pass"]),
           "hit_rank": r["hit_rank"], "hit_doc": r["hit_doc"],
           "top1_cosine": top1, "gate_score": gate,
           "score_type": SCORE_TYPE_COSINE,
           "top5_ids": [h["id"] for h in hits[:5]],
           "top5_scores": [h["score"] for h in hits[:5]],
           "faithfulness": faith_res}
    if answers_on:
        row["answer_judge"] = answer_res
    if old is not None:
        row["old_hit_rank"], row["old_top1_cosine"] = old
    if r.get("pipeline_state") is not None:   # 管线视图（--pipeline-view 开态才有）
        row["pipeline"] = {"state": r["pipeline_state"],
                           "top5_ok": r["pipeline_top5_ok"],
                           "hit_rank": r["pipeline_hit_rank"],
                           "hit_doc": r["pipeline_hit_doc"]}
    return row


def _builtin_paper_json(summary, faith_metrics=None, ans_metrics=None, slices=None,
                        pipeline=None):
    """内置验收卷 A → 单 paper json 块（checks 六键：summarize 四键实测 +
    expect_miss_rate/domain_rate 恒 None；metrics=测量值 dict+排序质量两键）。
    slices（--slices 门控，E3 2026-09-28）：给定才追加 "slices" 键（四维切片），
    不给=键集与历史版本逐字节一致。"""
    checks = dict(summary["checks"])
    checks["expect_miss_rate"] = None
    checks["domain_rate"] = None
    metrics = {k: summary[k] for k in ("n", "top5_n", "top5_rate", "monitor_hits",
                                       "monitor_n", "param_hits", "param_n", "cross_total")}
    metrics["mrr_at_10"] = summary.get("mrr_at_10", 0.0)
    metrics["ndcg_at_10"] = summary.get("ndcg_at_10", 0.0)
    if faith_metrics:
        metrics.update(faith_metrics)
    if ans_metrics:
        metrics.update(ans_metrics)
    if pipeline:
        metrics.update(pipeline)
    block = {"paper_id": BUILTIN_PAPER_ID, "title": "公开源语料库一期验收卷A（内置 18 条）",
             "n": summary["n"], "pass_lines": dict(PASS_LINES), "checks": checks,
             "all_pass": summary["all_pass"], "metrics": metrics}
    if slices is not None:
        block["slices"] = slices
    return block


def _paper_json_block(paper, summary, faith_metrics=None, ans_metrics=None,
                      slices=None, pipeline=None):
    """外部题卷 → paper json 块（checks 原样透传 summarize_paper：设线卷=六键 bool，
    未设线卷=None；metrics=测量值全集+排序质量两键）。slices（--slices 门控，
    E3 2026-09-28）：给定才追加 "slices" 键，不给=键集与历史版本逐字节一致。"""
    metrics = {k: summary[k] for k in
               ("n", "n_rel", "n_miss", "top5_n", "top5_rate", "monitor_hits", "monitor_n",
                "param_hits", "param_n", "cross_total", "miss_pass", "miss_rate",
                "unexpected_hits", "n_domain", "domain_hits", "domain_rate")}
    metrics["mrr_at_10"] = summary.get("mrr_at_10", 0.0)
    metrics["ndcg_at_10"] = summary.get("ndcg_at_10", 0.0)
    # 难负例负锚（R3，只测不判）：仅有带负锚题的卷才给三键——无负锚卷 metrics
    # 键集与历史版本逐字节一致（默认行为零变化）
    if summary.get("hard_neg_total"):
        metrics["hard_neg_total"] = summary["hard_neg_total"]
        metrics["hard_neg_hit_questions"] = summary["hard_neg_hit_questions"]
        metrics["hard_neg_hit_rate"] = summary["hard_neg_hit_rate"]
    if faith_metrics:
        metrics.update(faith_metrics)
    if ans_metrics:
        metrics.update(ans_metrics)
    if pipeline:
        metrics.update(pipeline)
    block = {"paper_id": paper["paper_id"], "title": paper.get("title", ""),
             "n": summary["n"], "pass_lines": paper.get("pass_lines"),
             "checks": summary["checks"], "all_pass": summary["all_pass"],
             "metrics": metrics}
    if slices is not None:
        block["slices"] = slices
    return block


def build_json_payload(mode, cfg, lib_path, lib_stats, papers_blocks, question_rows,
                       topk, prompt_tokens, n_queries, compare_path=None,
                       compare_stats=None, snapshot_on=False,
                       lib_block=None, compare_block=None, pipeline_block=None):
    """装配 schema v1 顶层 payload（lib md5 流式算；compare_lib 非对比模式=null）。

    mode ∈ builtin|paper|compare|paper_compare（内置 A 卷归一为单 paper）。
    snapshot_on（--snapshot 门控，D2 2026-09-28）：True 时顶层追加 "snapshot"
    （运行环境全量快照）；对比模式再追加 "compare_snapshot"+"snapshot_diff"（仅
    差异键）；False=键集与历史版本逐字节一致。lib_block/compare_block 供调用方
    传入已算好的 lib 块（复用 --compare 快照摘要已做的 md5 流式读，免二次读库），
    缺省内部自算。
    channel 键恒 "cosine"=纯余弦独立仪器视图（不读 rag 配置、不代表产线管线形态；
    口径注记依据=运营/门禁口径偏差复核-BM25段-20261003.md，键值与键集不动）。"""
    lib_b = lib_block if lib_block is not None else _lib_json_block(lib_path, lib_stats)
    cmp_b = compare_block if compare_block is not None else (
        _lib_json_block(compare_path, compare_stats) if compare_path else None)
    payload = {
        "schema": JSON_SCHEMA_TAG,
        "ran_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": mode,
        "lib": lib_b,
        "compare_lib": cmp_b,
        "channel": "cosine",
        "score_caliber": dict(SCORE_CALIBER),
        "config": {"model": cfg["model"], "dims": cfg["dims"], "topk": topk,
                   "price_per_mtok": cfg["price_per_mtok"]},
        "usage": {"n_queries": n_queries, "prompt_tokens": prompt_tokens,
                  "est_cost_cny": embed_common.estimate_cost_cny(
                      prompt_tokens, cfg["price_per_mtok"])},
        "papers": papers_blocks,
        "questions": question_rows,
    }
    if pipeline_block is not None:   # 双视图证书（--pipeline-view 开态；键集只增）
        payload["pipeline_view"] = pipeline_block
    if snapshot_on:
        payload["snapshot"] = build_snapshot(cfg, lib_b, topk=topk)
        if compare_path:
            payload["compare_snapshot"] = build_snapshot(cfg, cmp_b, topk=topk)
            payload["snapshot_diff"] = snapshot_diff(payload["snapshot"],
                                                     payload["compare_snapshot"])
    return payload


def write_json_result(json_path, payload, say=print):
    """机读 JSON 落盘（父目录缺失则建；覆盖式——机读件含 ran_at 时间戳字段，不做
    追加）+ 固定单行回显（--json 给定时 stdout 唯一新增行）。"""
    d = os.path.dirname(json_path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    say("[json] 已写 → %s" % json_path)


# ---------------------------------------------------------------------------
# faithfulness 代理指标（--faithfulness；2026-09-23 批A3③——judge 形态复用批A
# citation_check：懒 import（仓根 sys.path 注入只在 flag 开启时）、复用
# _extract_json_obj/_call_with_deadline/VERDICTS；默认关=零 API 零 import 面）
# ---------------------------------------------------------------------------
FAITH_SYSTEM_PROMPT = (
    "你是证据支持度评审器（离线检索质量代理指标）。给定用户问题、该题的金标锚"
    "（预期出处文档/版本/locator 正则）与检索返回的 top-5 证据块，判定证据集整体"
    "对回答该题（锚定主题）的支持程度。判定标准：\n"
    "supports=证据直接覆盖金标锚所指的问题内容（据此可给出确定性回答）；\n"
    "partial=仅部分覆盖，或数值/条件与锚预期有出入；\n"
    "unsupported=证据与锚/问题矛盾，或完全未覆盖所问内容；\n"
    "not_relevant=证据与问题无关。\n"
    "只输出一个 JSON 对象，不要解释、不要代码围栏，格式：\n"
    '{"verdict": "supports", "reason": "一句话理由"}\n'
    "verdict 只能取 supports/partial/unsupported/not_relevant；"
    "reason 为不超过 80 字的中文一句话。")

_CC_MOD = None  # citation_check 懒加载缓存（flag 关闭时恒 None=零 import 面）


def _citation_check_module():
    """懒加载批A citation_check（仓根注入 sys.path；import 失败向上抛，由
    build_faith_ctx 统一转 err 降级，绝不阻塞检索主流程）。"""
    global _CC_MOD
    if _CC_MOD is None:
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        if root not in sys.path:
            sys.path.insert(0, root)
        import citation_check
        _CC_MOD = citation_check
    return _CC_MOD


def build_faith_messages(q, hits, meta_by_id):
    """(题, top-k hits, 库 meta) → judge messages（system+user 两条；纯函数零网络）。

    金标锚=题面 expect_doc/version/locator 正则**原样**呈给 judge（多锚题逐锚列，
    标注 primary/secondary）；证据=top-5 各块 doc_id/version/locator+content 截
    FAITH_EVIDENCE_MAX_CHARS（对齐 citation_check.QUOTE_MAX_CHARS）。"""
    anchor_lines = []
    for i, a in enumerate(_question_anchors(q), 1):
        anchor_lines.append("[锚%d%s] expect_doc=%s｜version=%s｜locator正则=%s｜criterion=%s" % (
            i, "" if a.get("role", "primary") == "primary" else "(次)",
            "／".join(a["expect_doc"]), a.get("version") or "-",
            a["expect_locator_pattern"], a["criterion"]))
    ev_lines = []
    for h in hits[:5]:
        m = meta_by_id.get(h["id"]) or {}
        head = " ".join(str(m.get(k) or "").strip()
                        for k in ("doc_id", "version", "locator")).strip() or str(h["id"])
        content = " ".join(str(m.get("content") or "").split())[:FAITH_EVIDENCE_MAX_CHARS]
        ev_lines.append("[证据%d] rank=%d score=%.6f %s\n内容：%s" % (
            h["rank"], h["rank"], h["score"], head, content))
    user = ("【用户问题】\n" + str(q.get("query") or "").strip() +
            "\n\n【金标锚（题面预期出处，原样呈现）】\n" + "\n".join(anchor_lines) +
            "\n\n【检索 top-5 证据块】\n" + "\n\n".join(ev_lines) +
            "\n\n请按系统要求只输出 JSON 对象。")
    return [{"role": "system", "content": FAITH_SYSTEM_PROMPT},
            {"role": "user", "content": user}]


def parse_faith_json(raw):
    """judge 原始输出 → {"verdict","score","reason"} 或 None（复用 citation_check.
    _extract_json_obj 剥围栏/首{末}截取 + VERDICTS 白名单严校验；畸形一律 None=
    静默降级，不抛出）。"""
    cc = _citation_check_module()
    obj = cc._extract_json_obj(raw)
    if obj is None:
        return None
    v = obj.get("verdict")
    if v not in cc.VERDICTS:
        return None
    reason = " ".join(str(obj.get("reason") or "").split())[:cc.REASON_MAX_CHARS]
    return {"verdict": v, "score": FAITH_SCORES[v], "reason": reason}


def load_faith_settings(cfg):
    """judge 凭据/通道（形态同 cr_contextualize.load_chat_api_settings：环境变量优先）。

    BAILIAN_GEN_API_KEY/BAILIAN_GEN_BASE_URL 两者齐备（run_sub.sh 注入）→ 免密钥
    文件；否则读 cfg["key_path"] 密钥文件 {"base_url","api_key"}。api_url=base.
    rstrip("/")+cfg["cr_chat_path"]（默认 /compatible-mode/v1/chat/completions，
    pipeline_config 既有键原样复用）。返回值敏感：禁打印/落盘（报错只报字段名）。"""
    chat_path = cfg.get("cr_chat_path") or "/compatible-mode/v1/chat/completions"
    env_key = os.environ.get("BAILIAN_GEN_API_KEY", "")
    env_base = os.environ.get("BAILIAN_GEN_BASE_URL", "")
    if env_key and env_base:
        return {"api_url": env_base.rstrip("/") + chat_path, "key": env_key}
    path = os.path.expanduser(cfg["key_path"])
    if not os.path.exists(path):
        raise FileNotFoundError(
            "缺 BAILIAN_GEN_API_KEY/BAILIAN_GEN_BASE_URL 环境变量且密钥文件不存在"
            "（订阅通道应经 run_sub.sh 启动）")
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    for field in ("base_url", "api_key"):
        if not d.get(field):
            raise RuntimeError("密钥文件缺 %s 字段或为空" % field)
    return {"api_url": d["base_url"].rstrip("/") + chat_path, "key": d["api_key"]}


def make_faith_judge(api_key, model, api_url, usage_sink, say=print,
                     tag="faith", max_tokens=512, temperature=0, seed=None):
    """生产 judge callable 实体（批A3③ 开放项 (a) 案：不触批A 已交付件与其测试面，
    自立薄调用——字段逐抄 citation_check.token_plan_judge 口径（temperature=0/
    enable_thinking=False/stream=False/key 绝不回显绝不落日志），
    **加捕 response.usage** 入 usage_sink（token_plan_judge 不回传 usage 系 (a) 案
    动因）。urllib 标准库形态。返回 callable(messages, timeout)→content 字符串；
    失败抛异常（_call_with_deadline 统一转 None 降级）。
    tag/max_tokens（2026-09-28 答案通道复用面）：stdout 前缀与回包上限可配——
    缺省 "faith"/512 与历史行为逐字节一致；--answers 通道传 "answers"/768。
    temperature=0 确定性口径（2026-09-28 G3 终轮修1，消除 G09/G15 型采样波动）：
    请求体恒带 temperature=0（评审要确定性，口径同 citation_check/CR 管线）；通道
    拒绝该参数（HTTP 4xx 且错误体点名 temperature）时粘性降级不传并原调用重试一次
    （打日志行留痕，降级对本次及后续全部调用生效）——订阅通道实测接受该参数
    （rubric轮 40/40 ok=1），降级路径=前瞻兼容面非预期触发。
    temperature/seed（2026-10-11 提升计划波1 B3 judge k 采样面）：缺省 0/None
    与历史行为逐字节一致；B3 k 重复采样时传 temperature>0 + 逐样本 seed（如
    seed=base+i）——seed 进请求体（同 seed 同输入理想可复现），通道拒绝该参数
    （HTTP 4xx 且错误体点名 seed）时同款粘性降级不传并重试一次（降级=采样失去
    可复现性，调用方须留 caveat）。"""
    state = {"send_temperature": True, "send_seed": True}

    def _post(body, timeout):
        req = urllib.request.Request(
            api_url, data=json.dumps(body).encode(),
            headers={"Authorization": "Bearer " + api_key,
                     "Content-Type": "application/json"})
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read())
            content = data["choices"][0]["message"].get("content") or ""
            if not content.strip():
                raise ValueError("judge 回包 content 为空")
            u = data.get("usage") or {}
            usage_sink["input_tokens"] += int(u.get("prompt_tokens") or 0)
            usage_sink["output_tokens"] += int(u.get("completion_tokens") or 0)
            say("[%s] judge chars=%d ok=1 dur=%.2fs" % (
                tag, len(content), time.time() - t0))
            return content
        except Exception as e:  # 只报异常类型名，不带任何请求细节/key
            say("[%s] judge ok=0 dur=%.2fs err=%s" % (
                tag, time.time() - t0, type(e).__name__))
            raise

    def _judge(messages, timeout):
        body = {"model": model, "messages": messages,
                "max_tokens": max_tokens, "stream": False,
                # qwen3 系兼容口默认开思考（计费+拖慢），评审任务显式关闭
                "enable_thinking": False}
        if state["send_temperature"]:
            # 缺省 0=评审确定性（G3 终轮修1）；B3 k 采样面传 >0 值（行为逐字节兼容：
            # 缺省请求体与历史完全一致）
            body["temperature"] = temperature
        if seed is not None and state["send_seed"]:
            body["seed"] = seed       # k 采样可复现面（缺省不传=历史行为不变）
        try:
            return _post(body, timeout)
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")[:400]
            except Exception:
                pass
            low = detail.lower()
            degraded = False
            if "temperature" in low and state["send_temperature"]:
                state["send_temperature"] = False   # 粘性降级：本次及后续调用均不传
                body.pop("temperature", None)
                say("[%s] judge 通道不支持 temperature 参数（HTTP %d），本轮起降级不传"
                    "（评审确定性口径失效，同输入判定可能漂移）" % (tag, e.code))
                degraded = True
            if "seed" in low and seed is not None and state["send_seed"]:
                state["send_seed"] = False           # 粘性降级：同款口径
                body.pop("seed", None)
                say("[%s] judge 通道不支持 seed 参数（HTTP %d），本轮起降级不传"
                    "（k 采样失去可复现性，调用方须留 caveat）" % (tag, e.code))
                degraded = True
            if not degraded:
                raise                # 非 temperature/seed 参数面的 HTTP 拒绝：原样上抛
            return _post(body, timeout)
    return _judge


def build_faith_ctx(cfg, timeout=None, limit=0, model=None, say=print, judge=None,
                    temperature=0, seed=None):
    """main 层装配 faith 上下文（只在 --faithfulness 且 --yes 时调用；flag 关闭
    路径零 import 零网络零环境变量读取）。

    judge 可注入（单测 mock）；缺省走生产实现（load_faith_settings+make_faith_judge）。
    凭据缺失/citation_check import 失败 → ctx["err"] 置位：运行期打 [faith] 报错行+
    全题 null 降级（不中断检索主流程、不改 rc）。usage 累计器随 ctx 走（calls=尝试
    次数，run_faithfulness 计；tokens=实收 usage，生产 judge 计）。
    temperature/seed（2026-10-11 B3 k 采样面）：透传 make_faith_judge，缺省 0/None
    与历史行为逐字节一致（faith 通道无 jsonl 幂等缓存，无缓存键联动面）。"""
    ctx = {"judge": judge,
           "timeout": float(timeout if timeout and timeout > 0 else FAITH_TIMEOUT_DEFAULT),
           "limit": int(limit or 0), "model": model or FAITH_JUDGE_MODEL,
           "err": None,
           "usage": {"calls": 0, "input_tokens": 0, "output_tokens": 0},
           "ledger": pipeline_config.resolve_path(cfg["cr_usage_log"]),
           "cfg_keys": {"price_in": cfg["cr_price_in_per_mtok"],
                        "price_out": cfg["cr_price_out_per_mtok"]}}
    if ctx["judge"] is None:
        try:
            _citation_check_module()   # 懒 import 失败在此暴露 → 统一降级
            st = load_faith_settings(cfg)
            ctx["judge"] = make_faith_judge(st["key"], ctx["model"], st["api_url"],
                                            ctx["usage"], say,
                                            temperature=temperature, seed=seed)
        except Exception as e:
            ctx["err"] = ("凭据/依赖未就绪（%s：%s）——faithfulness 全部按 null 降级"
                          % (type(e).__name__, embed_common.scrub(str(e))[:200]))
    return ctx


def run_faithfulness(entries, faith, meta_by_id, say=print):
    """逐题 faithfulness 评审（md 报表零变化；[faith] 行只走 stdout）。

    entries = [(paper_id, q, hits, r), ...] 运行序（paper 模式按卷给序展平）；
    评审对象=hit_rank 非 None 的题（含 expect_miss 意外命中题），按运行序至多
    faith["limit"] 题（≤0=不限，全局计数）。返回 (results, judged, stats)：
    results/judged 与 entries 平行的列表（结果 dict|None；是否实际发起 judge），
    stats={"judged","null"}。卷级均值由调用方按 paper_id 分组（faith_paper_metrics，
    口径=非 null 题均值，null 计数单列）。失败纪律：judge 异常/墙钟超时/输出畸形
    一律该题 null 静默降级——不抛出、不阻塞、不改 rc。"""
    results = [None] * len(entries)
    judged = [False] * len(entries)
    stats = {"judged": 0, "null": 0}
    if faith is None:
        return results, judged, stats
    if faith.get("err"):
        say("[faith] %s" % faith["err"])
        return results, judged, stats
    cc = _citation_check_module()
    budget = float(faith.get("timeout") or FAITH_TIMEOUT_DEFAULT)
    limit = int(faith.get("limit") or 0)
    judge = faith["judge"]
    usage = faith["usage"]
    for i, (_pid, q, hits, r) in enumerate(entries):
        if r.get("hit_rank") is None:
            continue                              # 非评审对象（无命中无证据可评）
        if limit > 0 and stats["judged"] >= limit:
            continue                              # --limit 截断（按运行序全局计数）
        stats["judged"] += 1
        judged[i] = True
        usage["calls"] += 1
        qid = r["id"]
        messages = build_faith_messages(q, hits, meta_by_id)
        raw = cc._call_with_deadline(lambda: judge(messages, budget),
                                     budget + cc._WATCHDOG_SLACK_S,
                                     "faith-%s" % qid, say)
        res = parse_faith_json(raw) if raw is not None else None
        if raw is not None and res is None:
            say("[faith] %s judge 输出畸形（JSON 解析/白名单校验失败），按 null 降级" % qid)
        results[i] = res
        if res is None:
            stats["null"] += 1
            say("[faith] %s → null（降级：失败/超时/畸形）" % qid)
        else:
            say("[faith] %s → verdict=%s score=%.1f reason=%s" % (
                qid, res["verdict"], res["score"], res["reason"] or "-"))
    return results, judged, stats


def faith_usage_est_cny(faith):
    """生成侧费用估算（cr_price_in/out_per_mtok=flash 京区快照单价；订阅通道
    est_cny 仅量级参照非现金——run_sub.sh 注释口径；2026-09-28 起与答案通道共用
    _judge_usage_est_cny 实现）。"""
    return _judge_usage_est_cny(faith)


def faith_usage_line(faith, say=print):
    """用量如实打印（仅 flag 开启时走到；tokens=生产 judge 实收 usage）。"""
    u = faith["usage"]
    say("[faith] 用量：calls=%d input_tokens=%d output_tokens=%d est≈%.6f 元"
        "（订阅通道配额消耗非现金，est 仅量级参照）" % (
            u["calls"], u["input_tokens"], u["output_tokens"], faith_usage_est_cny(faith)))


def append_faith_ledger(faith, say=print):
    """生成用量.jsonl 追加 1 行（20 元单列台账；stage=smoke_faithfulness；
    形态对齐既有行制：{ts,stage,model,n,input_tokens,output_tokens,retries,
    est_cny,usage_basis}。零调用不写行；ledger=None（单测）跳过）。"""
    u = faith["usage"]
    if not u["calls"] or not faith.get("ledger"):
        return
    line = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "stage": FAITH_STAGE,
            "model": faith["model"], "n": u["calls"],
            "input_tokens": u["input_tokens"], "output_tokens": u["output_tokens"],
            "retries": 0, "est_cny": round(faith_usage_est_cny(faith), 6),
            "usage_basis": "订阅通道配额消耗非现金，est 仅量级参照（run_sub.sh 口径）"}
    d = os.path.dirname(faith["ledger"])
    if d:
        os.makedirs(d, exist_ok=True)
    with open(faith["ledger"], "a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")
    say("[faith] 台账 生成用量.jsonl 追加 1 行：stage=%s n=%d est≈%.6f 元（量级参照）"
        % (FAITH_STAGE, u["calls"], line["est_cny"]))


def faith_paper_metrics(entries, results, judged, paper_id):
    """卷级 faithfulness 指标（仅 flag 开启时入 papers[].metrics）：mean=非 null 题
    均值（全 null/零评审 → None）；judged=实际发起 judge 题数；null=降级题数单列。"""
    idx = [i for i, (pid, _q, _h, _r) in enumerate(entries)
           if pid == paper_id and judged[i]]
    scores = [results[i]["score"] for i in idx if results[i] is not None]
    return {"faithfulness_mean": (sum(scores) / len(scores)) if scores else None,
            "faithfulness_judged": len(idx),
            "faithfulness_null": len(idx) - len(scores)}


# ---------------------------------------------------------------------------
# 答案评测通道（--answers；2026-09-28 评测体系第 1 批 G1——judge 形态/退避/降级
# 纪律逐条复用 --faithfulness 面：懒 import、_call_with_deadline 看门狗、失败逐题
# null 静默降级不改 rc、凭据缺失整通道跳过；默认关=零 API 零 import 面）
# ---------------------------------------------------------------------------
ANSWER_SYSTEM_PROMPT = (
    "你是问答机生成端答案评审器。给定用户问题、金标锚（预期出处）、必答要点/"
    "禁答点/引用要求/题型，以及检索 top-5 证据块，分两步工作：\n"
    "第一步（生成）：只依据证据块写出将交付给用户的答案（不超过 150 字，引用处标注"
    " [证据n]）；expected_type=abstain 时，证据不足以确定性回答即明确拒答并说明缺什么。\n"
    "第二步（评审）：按以下固定 rubric 逐维判定：\n"
    "faithfulness=答案各要点均被证据支撑，无编造（对照证据原文核）；\n"
    "citation=对照本题【引用要求（citation_req）】的 docs 正主清单核对答案引用（题未给"
    " citation_req 时才按\"引用真实存在于证据集且确实支撑\"口径评）：引用落在 docs 清单"
    "内且证据真实支撑 → pass；引用的是 docs 清单件的同族架构文档（同一制式下描述整体"
    "架构/流程的总纲概述件，典型如 NR 的 TS 38.300 之于具体规范件 TS 38.331、LTE 的"
    " TS 36.300 之于 TS 36.331）且所引内容实质支撑答案 → partial；引用 docs 清单外且"
    "所引文档与正主非同族架构关系的其他文档（含跨制式混引，如 NR 题引 LTE 件；凡同族"
    "架构文档且实质支撑者一律判 partial，不得按清单外判 fail）、引用不支撑所述内容或"
    "编造引用 → fail；\n"
    "completeness=必答要点 answer_points 全部覆盖（abstain 题按\"拒答且说明缺口\"口径评）；\n"
    "version=涉及的规范版本/条款号表述与金标锚一致（答案不涉及时取 na）；\n"
    "abstention=abstain 题是否正确拒答（normal 题恒取 na）；出现禁答点（must_not）"
    "相关内容时对应维取 fail 并在 reason 点名。\n"
    "每维只能取 pass/fail/na（na=该维不适用）；唯一例外：citation 维可再取 partial"
    "（同族架构文档实引），partial 不单独判整题未过，但 reason 须点名\"指定=某件、"
    "实引=某件\"。reason 核对引用时必须对照本题 citation_req 的 docs 原文点名正主清单"
    "（如\"citation_req 正主=TS 38.213/38.214，答案实引 TS 38.331 属清单外\"），不得以"
    "\"引用了某真实规范\"笼统带过。\n"
    "只输出一个 JSON 对象，不要解释、不要代码围栏，格式：\n"
    '{"answer": "…", "faithfulness": "pass", "citation": "pass", '
    '"completeness": "pass", "version": "na", "abstention": "na", '
    '"reason": "一句话理由"}\n'
    "reason 为不超过 80 字的中文一句话。")


def _answer_eligible(q):
    """答案评审对象门控：带 answer_points（非空）或 expected_type=abstain 的题
    （abstain 题 profile 常无要点，其评审目的恰是"空证据下正确拒答"）。"""
    return bool(q.get("answer_points")) or q.get("expected_type") == "abstain"


def _answer_spec_parts(q):
    """schema v2 评审要素呈现（answer_points/must_not/citation_req/expected_type）——
    --answers 与 --answers-external 两通道共用段（纯函数；逐字段口径与 G1 首版逐字节
    同纹，抽取不改文面）。"""
    parts = []
    aps = [str(p) for p in (q.get("answer_points") or []) if str(p).strip()]
    if aps:
        parts.append("【必答要点（answer_points，completeness 维对照）】\n" + "\n".join(
            "%d. %s" % (i, p) for i, p in enumerate(aps, 1)))
    mns = [str(m) for m in (q.get("must_not") or []) if str(m).strip()]
    if mns:
        parts.append("【禁答点（must_not，出现即对应维 fail）】\n" + "\n".join(
            "%d. %s" % (i, m) for i, m in enumerate(mns, 1)))
    cr = q.get("citation_req")
    if cr:
        parts.append("【引用要求（citation_req）】docs=%s｜note=%s" % (
            "／".join(cr.get("docs") or []) or "（未指定）", cr.get("note") or "（未指定）"))
    parts.append("【题型（expected_type）】%s%s" % (
        q.get("expected_type") or "normal",
        "（无答案应拒答型：证据不足以确定性回答即拒答）"
        if q.get("expected_type") == "abstain" else ""))
    return parts


# ---------------------------------------------------------------------------
# 第10卷条件注入（设计稿 §四；2026-10-12 实施件②）：三字段判据仅对带字段的题
# 注入（追加扩展段于既有 system 提示之后）；不带新字段的老题扩展段恒 ""——
# messages 逐字节不变，幂等缓存全命中（存量卷零复判零费用，单测硬断言在档）。
# ---------------------------------------------------------------------------
_SOURCE_LEVEL_MAP_STATE = {"data": None}


def load_source_level_map(path=None):
    """来源等级映射档 → dict（懒加载进程内缓存；纯读零网络）。

    缺档/坏档 → {}（=无任何来源可折算，must_cite_type 题一切按表外处理——如实
    保守不猜级；--answers 通道对照表行会逐条标"表外"如实可见）。"""
    if path is None:
        if _SOURCE_LEVEL_MAP_STATE["data"] is not None:
            return _SOURCE_LEVEL_MAP_STATE["data"]
        p = SOURCE_LEVEL_MAP_PATH
    else:
        p = path
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or not isinstance(data.get("rules"), dict):
            raise ValueError("缺 rules 对象")
    except Exception:
        return {}
    if path is None:
        _SOURCE_LEVEL_MAP_STATE["data"] = data
    return data


def source_level_of(doc_id, chunk_id=None, level_map=None):
    """doc/块 → "L1"|"L2"|"L3"|None（等级折算；与生产 G 徽标 _source_tier_of 同源
    口径，优先序=chunk_exact（导读卡 L3 先判）→doc_exact→prefix；其余 None=表外）。

    level_map 可注入（单测面）；缺省读 来源等级映射-1.0.json。合成卡/导读卡域的
    doc_id 与 3GPP TS/TR 撞名，doc 级不可分——块级 chunk_exact 名单分域（同生产）。"""
    m = level_map if level_map is not None else load_source_level_map()
    rules = m.get("rules") or {}
    cid, doc = str(chunk_id or ""), str(doc_id or "")
    lv = (rules.get("chunk_exact") or {}).get(cid)
    if lv:
        return lv
    lv = (rules.get("doc_exact") or {}).get(doc)
    if lv:
        return lv
    for prefix, level in rules.get("prefix") or []:
        if isinstance(prefix, str) and prefix and doc.startswith(prefix):
            return level
    return None


def source_level_satisfies(level, min_level):
    """等级达标判定（纯函数）：权威序 L1＞L2＞L3（rank 小者权威），level 满足
    min_level ⟺ rank(level) ≤ rank(min_level)；任一侧未知名 → False。"""
    a = _SOURCE_LEVEL_ORDER.get(level)
    b = _SOURCE_LEVEL_ORDER.get(min_level)
    return a is not None and b is not None and a <= b


def _source_level_table_lines(hits=None, meta_by_id=None, level_map=None):
    """must_cite_type 等级对照表行（纯函数；judge 不自由裁量定级的机制面）。

    --answers 通道（hits 给定）：本题 top-5 证据块逐块折算（[证据n] doc→等级，
    块级 chunk_exact 分域同生产徽标）；--answers-external 盲判面（hits=None）：
    映射档 doc_inventory 全量（按答案文本引用的来源名对照，不见证据面）。"""
    m = level_map if level_map is not None else load_source_level_map()
    lines = []
    if hits is not None:
        for h in hits[:5]:
            meta = (meta_by_id or {}).get(h.get("id")) or {}
            doc = str(meta.get("doc_id") or "")
            lv = source_level_of(doc, h.get("id"), m)
            lines.append("[证据%d] %s → %s" % (
                h.get("rank") or 0, doc or str(h.get("id")) or "?",
                lv or "表外（无等级）"))
        if not lines:
            lines.append("（检索无证据块——无可折算来源，实引一律按表外处理）")
        return lines
    for entry in m.get("doc_inventory") or []:
        if isinstance(entry, dict) and entry.get("doc_id"):
            lines.append("%s → %s" % (entry["doc_id"], entry.get("level")))
    if not lines:
        lines.append("（映射档无 doc 清单——所有来源按表外处理）")
    return lines


def _answer_rubric_ext(q, hits=None, meta_by_id=None, level_map=None):
    """第10卷扩展判据段（条件注入；纯函数零网络）→ str。

    三字段全缺的老题恒返 ""（build_answer_*_messages 的 system 提示逐字节不变
    ——幂等缓存全命中，存量卷零复判）。带字段的题按字段逐段注入：
    must_cover→completeness 加严（逐项必中，缺任一即 fail）；must_cite_type→
    citation 改判（实引来源按对照表折算 ≥min_level，表外=不满足任何等级）；
    hard_gate→整题前置硬门（先硬门后五维，任一启用门不满足=整题 fail，输出须
    追加 hard_gate_pass 键）。段首带 ANSWER_RUBRIC_EXT_VERSION 版本键（对档用）。"""
    segs = []
    mc = [str(x) for x in (q.get("must_cover") or []) if str(x).strip()]
    if mc:
        segs.append(
            "【必答操作方向（must_cover，completeness 维加严判据）】\n"
            + "\n".join("%d. %s" % (i, p) for i, p in enumerate(mc, 1))
            + "\n本题 completeness 维改按下口径判：上述操作方向逐项必中（答案须逐项"
              "提到），缺任一项即 completeness=fail（不按比例扣分）；answer_points"
              " 仅作余量参照。")
    mct = q.get("must_cite_type")
    if mct:
        ml = mct.get("min_level")
        segs.append(
            "【引用等级要求（must_cite_type，citation 维改判口径）】min_level=%s｜"
            "note=%s\n本题 citation 维不按 citation_req docs 正主判，改按下口径判："
            "答案实引来源按下方来源等级对照表折算等级，至少一条实引来源等级达标即 "
            "pass（等级权威序 L1＞L2＞L3，达标=该源等级为 %s 或更权威）；对照表外"
            "来源=不满足任何等级（防编造）；不要求条款号/规范号。\n来源等级对照表"
            "（doc→等级；表外=无等级）：\n%s" % (
                ml, mct.get("note") or "（未指定）", ml,
                "\n".join(_source_level_table_lines(hits, meta_by_id, level_map))))
    hg = q.get("hard_gate")
    if hg:
        enabled = [k for k in ("executable_steps", "specific_params") if hg.get(k)]
        gate_desc = {"executable_steps":
                     "executable_steps=是否给出可执行步骤（编号步骤/排查次序/操作"
                     "动作，泛泛而谈不算）",
                     "specific_params":
                     "specific_params=是否给出具体参数（参数名+取值/门限/单位）"}
        segs.append(
            "【硬门（hard_gate，先于五维判定的整题前置门）】启用门=%s｜note=%s\n"
            "判定优先序=先硬门后五维：任一启用门不满足 → 整题 fail（五维仍逐维输出"
            "供诊断，但不翻身）。输出 JSON 须追加键 \"hard_gate_pass\": "
            "{\"executable_steps\": \"pass|fail|na\", \"specific_params\": "
            "\"pass|fail|na\"}（未启用的门取 na，启用门须给 pass/fail）。\n启用门"
            "判据：%s" % (
                "、".join(enabled), hg.get("note") or "（未指定）",
                "；".join(gate_desc[k] for k in enabled)))
    if not segs:
        return ""
    return ("\n\n【扩展判据（%s；条件注入=仅本题带相应字段时本段存在）】\n"
            % ANSWER_RUBRIC_EXT_VERSION + "\n\n".join(segs))


def _answer_rubric_v31_on(q):
    """rubric v3.1 激活判定（纯函数）：显式参数（模块态 ANSWER_RUBRIC_V31["on"]，
    main --answers-rubric v3.1 置位）或卷级标记（loader 注入 q["answer_rubric"]=
    "v3.1"，题卷卷对象 answer_rubric 字段）任一为真即激活。缺省两路皆关——
    老卷 system 提示逐字节不变（幂等缓存全命中，存量读数零扰动）。"""
    return bool(ANSWER_RUBRIC_V31["on"]) or q.get("answer_rubric") == "v3.1"


def _answer_rubric_v31_segment():
    """rubric v3.1 修订段（激活卷/显式参数时条件注入；纯函数零网络）→ str。

    两处修订以"优先于上文 v3 判文对应句"的覆盖形态追加于 system 提示（注入形态
    同 _answer_rubric_ext——段首带版本键，注入即入 msg_sha16 幂等缓存键：老键行
    与本段 sha 必不相同=自动分离，互不掩没）。修订案源=报告-外部模型锚-
    20261012.md §六（faithfulness reason 二分/completeness 判文+abstain 分支
    单列）；citation partial 塌缩建议不在本段（另轮）。"""
    return (
        "\n\n【rubric v3.1 修订（%s；条件注入=仅激活卷/显式参数时本段存在；"
        "以下两句口径优先于上文判文的对应句）】\n"
        "faithfulness：判定标准不变；要点不被证据支撑时 reason 须二分归因——"
        "编造=凭空捏造数值/参数名/条款号或与证据原文矛盾；超证=内容与规范/金标锚"
        "一致但 top-5 证据块未覆盖该要点。超证要点在 RAG 纪律下仍判 fail，但 "
        "reason 必含字样\"超证-检索缺口\"（归因检索面，建库侧据此分诊检索缺口），"
        "不得写\"编造\"；确属编造才在 reason 点名\"编造\"。\n"
        "completeness：只按必答要点（answer_points）逐条核覆盖——引用形态/出处/"
        "条款号/版本问题一律归 citation/version 维评，不得写进 completeness 判由；"
        "abstain 题 completeness 分支单列=正确拒答（abstention 维判 pass）即 "
        "completeness=pass，拒答中说明缺了什么属备注，不作 pass 门槛。"
        % ANSWER_RUBRIC_V31_VERSION)


def build_answer_messages(q, hits, meta_by_id):
    """(题, top-k hits, 库 meta) → 答案评审 messages（system+user 两条；纯函数零网络）。

    呈现=金标锚（原样，同 build_faith_messages）+ schema v2 四字段（answer_points
    逐条／must_not 逐条／citation_req docs+note／expected_type）+ top-5 证据块
    （截 FAITH_EVIDENCE_MAX_CHARS，与 faithfulness 通道同口径）。"""
    anchor_lines = []
    for i, a in enumerate(_question_anchors(q), 1):
        anchor_lines.append("[锚%d%s] expect_doc=%s｜version=%s｜locator正则=%s｜criterion=%s" % (
            i, "" if a.get("role", "primary") == "primary" else "(次)",
            "／".join(a["expect_doc"]), a.get("version") or "-",
            a["expect_locator_pattern"], a["criterion"]))
    parts = _answer_spec_parts(q)
    ev_lines = []
    for h in hits[:5]:
        m = meta_by_id.get(h["id"]) or {}
        head = " ".join(str(m.get(k) or "").strip()
                        for k in ("doc_id", "version", "locator")).strip() or str(h["id"])
        content = " ".join(str(m.get("content") or "").split())[:FAITH_EVIDENCE_MAX_CHARS]
        ev_lines.append("[证据%d] rank=%d score=%.6f %s\n内容：%s" % (
            h["rank"], h["rank"], h["score"], head, content))
    if not ev_lines:
        ev_lines.append("（检索无证据块）")
    user = ("【用户问题】\n" + str(q.get("query") or "").strip() +
            "\n\n【金标锚（题面预期出处，原样呈现）】\n" + "\n".join(anchor_lines) +
            "\n\n" + "\n\n".join(parts) +
            "\n\n【检索 top-5 证据块】\n" + "\n\n".join(ev_lines) +
            "\n\n请按系统要求先给答案再逐维评审，只输出 JSON 对象。")
    # 第10卷条件注入（设计稿 §四）：带三字段的题追加扩展判据段于 system 提示后；
    # 老题 ext 恒 ""——system 提示与既有逐字节同纹（幂等缓存零失效，单测硬断言）。
    # rubric v3.1 修订段（2026-10-12）：激活卷/显式参数时插于 base 与 ext 段之间
    # （两段互不依赖可叠加；未激活恒不出现——老卷 system 逐字节不变）。
    return [{"role": "system",
             "content": ANSWER_SYSTEM_PROMPT
             + (_answer_rubric_v31_segment() if _answer_rubric_v31_on(q) else "")
             + _answer_rubric_ext(q, hits, meta_by_id)},
            {"role": "user", "content": user}]


def parse_answer_json(raw, hard_gate=None):
    """judge 原始输出 → {"answer","dims","pass","reason"} 或 None（复用
    citation_check._extract_json_obj 剥围栏/首{末}截取；五维键齐全且取值在白名单，
    缺任一键/越权值/非 dict 一律 None=静默降级不抛出）。白名单 v2（G3 校准轮）：
    partial 仅 citation 维合法（同族架构文档实引），其余维取 partial=畸形整题 null。
    pass=至少一维被评（非 na）且全部被评维 pass（citation 维 partial 亦放行——
    同族实引不单独阻断整题，G18 型口径）。

    hard_gate（第10卷 §3c，2026-10-11 设计稿）：题带硬门时传入 loader 规范化
    dict——judge 输出须含 hard_gate_pass 键（逐门 pass/fail，未启用门 na）；缺键/
    越权值/未知门键/启用门取 na 一律 None（畸形整题降级，白名单纪律同五维）。
    整题 pass=五维全过且全部启用门 pass（判定优先序=hard_gate→五维→整题 pass，
    设计稿 §四）。老题（hard_gate=None）解析行为与结果 dict 形状逐字节不变。"""
    cc = _citation_check_module()
    obj = cc._extract_json_obj(raw)
    if not isinstance(obj, dict):
        return None
    dims = {}
    for k in ANSWER_DIMS:
        v = obj.get(k)
        allowed = ANSWER_DIM_VALUES if k == "citation" else _ANSWER_DIM_VALUES_STRICT
        if v not in allowed:
            return None
        dims[k] = v
    hg_out = None
    if hard_gate:
        hg_raw = obj.get("hard_gate_pass")
        if not isinstance(hg_raw, dict) \
                or any(k not in ("executable_steps", "specific_params") for k in hg_raw):
            return None
        hg_out = {}
        for k in ("executable_steps", "specific_params"):
            v = hg_raw.get(k, "na")
            if v not in ("pass", "fail", "na"):
                return None
            if hard_gate.get(k) and v == "na":
                return None      # 启用门缺判（na）=畸形（扩展段明示启用门须 pass/fail）
            hg_out[k] = v
    answer = " ".join(str(obj.get("answer") or "").split())[:ANSWER_ANSWER_MAX_CHARS]
    reason = " ".join(str(obj.get("reason") or "").split())[:cc.REASON_MAX_CHARS]
    evaluated = [v for v in dims.values() if v != "na"]
    passed = bool(evaluated) and all(v in ("pass", "partial") for v in evaluated)
    if hg_out is not None:
        passed = passed and all(hg_out[k] == "pass"
                                for k in ("executable_steps", "specific_params")
                                if hard_gate.get(k))
        return {"answer": answer, "dims": dims, "pass": passed, "reason": reason,
                "hard_gate_pass": hg_out}
    return {"answer": answer, "dims": dims, "pass": passed, "reason": reason}


def _answer_judge_with_retry(judge, messages, budget, cc, usage, say, tag, who,
                             hard_gate=None):
    """judge 单题调用+解析，null 前同输入重试 1 次（2026-09-28 J1b 轮 1 销项②，
    --answers 与 --answers-external 两通道共用）：首次失败（异常/墙钟超时/输出畸形
    ——轮 1 参-P18#B 型单发解析噪声、网络瞬断）不再直接 null 降级，先**同输入**
    重试 1 次；温度 0 确定性口径下重试的增益场景=网络瞬断/限流抖动（畸形输出重试
    大概率同纹，二次失败即认降级）。返回 res 或 None——null 降级与 result=null
    留痕纪律由调用方原样执行（null 行不进缓存不改形态）。usage.calls 按尝试口径
    累计（重试 +1；台账 n=真实 API 尝试数）。tag/who：stdout 前缀与单题标识
    （qid 或 qid#arm；看门狗标签="%s-%s"，与历史行同纹）。hard_gate（第10卷
    §3c）：透传 parse_answer_json（题带硬门时校验 hard_gate_pass 键；缺省 None=
    老题解析行为不变）。"""
    dl_label = "%s-%s" % (tag, who)
    usage["calls"] += 1
    raw = cc._call_with_deadline(lambda: judge(messages, budget),
                                 budget + cc._WATCHDOG_SLACK_S, dl_label, say)
    res = parse_answer_json(raw, hard_gate=hard_gate) if raw is not None else None
    if res is not None:
        return res
    if raw is not None:
        say("[%s] %s judge 输出畸形（JSON 解析/五维白名单校验失败），同输入重试 1 次"
            % (tag, who))
    else:
        say("[%s] %s judge 调用失败/超时，同输入重试 1 次（温度 0 下重试针对网络瞬断）"
            % (tag, who))
    usage["calls"] += 1
    raw = cc._call_with_deadline(lambda: judge(messages, budget),
                                 budget + cc._WATCHDOG_SLACK_S, dl_label, say)
    return parse_answer_json(raw, hard_gate=hard_gate) if raw is not None else None


def build_answer_ctx(cfg, timeout=None, limit=0, model=None, say=print, judge=None,
                     jsonl=None, stage=ANSWER_STAGE, tag="answers",
                     temperature=0, seed=None):
    """main 层装配答案评测通道上下文（只在 --answers 且 --yes 时调用；纪律同
    build_faith_ctx：flag 关=零 import 零网络零环境变量读取）。

    judge 可注入（单测 mock）；缺省走生产实现（load_faith_settings+make_faith_judge
    tag="answers"/max_tokens=768）。凭据缺失/citation_check import 失败 → ctx["err"]
    置位：运行期打 [answers] 报错行+整通道跳过全题 null（不中断检索主流程、不改 rc；
    零 key/无网络环境的整体降级面）。usage 累计器随 ctx 走。jsonl（2026-09-28 G3
    材料持久化，--answers-jsonl）：judge 输入 ctx 与输出五维明细逐题落盘点（None=
    不落盘；main 层缺省给日期档名）。stage/tag（2026-09-28 J1b 外部答案盲判通道
    复用面）：台账 stage 字面与 stdout 前缀可配——缺省 answer_judge/"answers" 与
    历史行为逐字节一致，--answers-external 传 answer_judge_external/"answers-ext"
    （台账分账纪律：J1b 判卷与 G1 生成自评用量不混淆，协议 §3.1）。
    ext_text_max_chars（2026-09-28 轮 1 销项①）：外部通道答案文本截长（cfg 键
    answer_external_text_max_chars 可覆盖，缺省 ANSWER_EXTERNAL_TEXT_MAX_CHARS
    =4000）——--answers 通道不用（其证据截长 FAITH_EVIDENCE_MAX_CHARS 另口径）。
    temperature/seed（2026-10-11 B3 k 采样面）：透传 make_faith_judge，并把采样
    短串存 ctx["sampling"]（缺省 None）——run_answer_judge/run_answer_external_
    judge 幂等缓存键入采样段，k 次采样不被默认参数缓存掩没；缺省与历史行为
    逐字节一致（缓存键/行制均不变）。"""
    ctx = {"judge": judge,
           "timeout": float(timeout if timeout and timeout > 0 else ANSWER_TIMEOUT_DEFAULT),
           "limit": int(limit or 0), "model": model or ANSWER_JUDGE_MODEL,
           "err": None,
           "usage": {"calls": 0, "input_tokens": 0, "output_tokens": 0},
           "jsonl": jsonl, "stage": stage, "tag": tag,
           "sampling": _judge_sampling_tag(temperature, seed),
           "ext_text_max_chars": _resolve_ext_text_max_chars(cfg),
           "ledger": pipeline_config.resolve_path(cfg["cr_usage_log"]),
           "cfg_keys": {"price_in": cfg["cr_price_in_per_mtok"],
                        "price_out": cfg["cr_price_out_per_mtok"]}}
    if ctx["judge"] is None:
        try:
            _citation_check_module()   # 懒 import 失败在此暴露 → 统一降级
            st = load_faith_settings(cfg)
            ctx["judge"] = make_faith_judge(st["key"], ctx["model"], st["api_url"],
                                            ctx["usage"], say, tag=tag,
                                            max_tokens=ANSWER_MAX_TOKENS,
                                            temperature=temperature, seed=seed)
            # 确定性口径证据行（G3 终轮修1）：运行日志留 temperature=0 生效痕迹，
            # 供两轮稳定性对拍对档（通道拒绝该参数时上方另有降级日志行）
            say("[%s] judge 确定性口径：temperature=0（消除采样波动面；"
                "通道拒绝该参数时自动降级不传并打行）" % tag)
        except Exception as e:
            ctx["err"] = ("凭据/依赖未就绪（%s：%s）——答案评测通道整体跳过，"
                          "全部按 null 降级" % (
                              type(e).__name__, embed_common.scrub(str(e))[:200]))
    return ctx


def _answer_msg_sha16(messages):
    """judge 输入指纹（幂等缓存键成分）：messages 全文 sha16——rubric（system 提示）、
    题面/要点/禁答/引用要求、top-5 证据任何一变动即失效重判。"""
    blob = json.dumps(messages, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _judge_sampling_tag(temperature, seed):
    """采样参数 → 幂等缓存键采样段（2026-10-11 B3 k 采样面）：非默认采样
    （temperature≠0 或 seed 非空）返回 "t<temperature>s<seed>" 形短串；默认
    （temperature=0 且 seed=None）返回 None——缓存键不含采样段=与历史键逐字节
    一致（旧行为不变，既有缓存不失效）。"""
    t = 0 if temperature is None else float(temperature)
    if t == 0 and seed is None:
        return None
    return "t%gs%s" % (t, seed)


def _answer_cache_key(paper_id, qid, sampling=None, judge_model=None):
    """幂等缓存键：卷内题唯一（多卷连跑防 qid 撞车）。sampling（2026-10-11
    B3 k 采样面）：非默认采样参数短串入键（"@t0.7s101" 后缀）——同题不同
    采样参数各自独立缓存，k 次采样不被默认参数缓存掩没；缺省 None 与历史
    键逐字节一致。judge_model（2026-10-24 判官隔离面）：非空判官模型名缀
    "$<model>" 段——不同判官同题各自独立缓存（msg_sha16 只纹 messages 全文，
    不含模型名，不同判官同输入同 sha，无此段即互相掩没串档）；行制自带
    "model" 键（G3 材料持久化起恒落）→ load 侧可从旧行无损复原本段=旧缓存
    续用不失效；无 model 的极旧行键不含本段、运行期查找键恒含（actx["model"]
    恒有值）→ 永不命中=安全降级重判（防串档优先，宁可重判一次）。"""
    key = "%s/%s" % (paper_id, qid)
    if sampling:
        key = "%s@%s" % (key, sampling)
    if judge_model:
        key = "%s$%s" % (key, judge_model)
    return key


def load_answer_jsonl_cache(path):
    """既有 answer_judge jsonl → {缓存键: {"msg_sha16","result"}}（同键末次出现优先；
    result=null 行不进缓存——降级不留缓存，重跑必须重判；坏行跳过=断电半行幂等容错，
    由 append 侧补换行兜底）。缓存键：--answers 行=paper/qid；--answers-external 行
    带 arm 键 → paper/qid#arm（同题两臂各自独立缓存，2026-09-28 J1b 外部盲判件）；
    行带 sampling 键（2026-10-11 B3 k 采样面）→ 键再缀 "@t…s…" 采样段——非默认
    采样行与默认行互不掩没，默认行（无 sampling 键）键形与历史逐字节一致；行带
    model 键（2026-10-24 判官隔离面）→ 键再缀 "$<model>" 判官段——同文件两判官
    行各自入桶互不掩没（根治跨判官串档=分立材料文件手工防串档不再需要）；行无
    model 键（G3 行制前极旧行）→ 键不含判官段、运行期查找键恒含 → 不命中安全
    重判。"""
    cache = {}
    if not path or not os.path.exists(path):
        return cache
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            res = obj.get("result")
            sha = obj.get("msg_sha16")
            if not isinstance(sha, str) or not sha or not isinstance(res, dict):
                continue
            qid = obj.get("qid") or ""
            arm = obj.get("arm")
            if isinstance(arm, str) and arm:
                qid = "%s#%s" % (qid, arm)
            model = obj.get("model")
            cache[_answer_cache_key(obj.get("paper_id") or "", qid,
                                    obj.get("sampling"),
                                    model if isinstance(model, str) else None)] = {
                "msg_sha16": sha, "result": res}
    return cache


def answer_jsonl_line(paper_id, q, hits, meta_by_id, messages, res, model,
                      sampling=None):
    """单题持久化行（judge 输入 ctx + 输出明细，纯函数零网络）：题面/要点/禁答/
    引用要求/题型 + top-5 证据（doc_id/version/locator + content，截长口径同
    build_answer_messages）+ msg_sha16（幂等缓存键成分）+ 五维结果（res=None=该题
    降级，只留审计痕不进缓存）。sampling（2026-10-11 B3 k 采样面）：非 None 时
    行内落 "sampling" 键（缓存键成分）；缺省 None 不落键——默认行与历史行制逐字节
    一致。"""
    evs = []
    for h in hits[:5]:
        m = meta_by_id.get(h["id"]) or {}
        evs.append({"rank": h["rank"], "score": h["score"], "id": h["id"],
                    "doc_id": str(m.get("doc_id") or ""),
                    "version": str(m.get("version") or ""),
                    "locator": str(m.get("locator") or ""),
                    "content": " ".join(str(m.get("content") or "").split())
                               [:FAITH_EVIDENCE_MAX_CHARS]})
    line = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "rubric": (ANSWER_RUBRIC_V31_VERSION if _answer_rubric_v31_on(q)
                       else ANSWER_RUBRIC_VERSION),
            "model": model,
            "paper_id": paper_id, "qid": q.get("id"),
            "query": str(q.get("query") or ""),
            "answer_points": [str(p) for p in (q.get("answer_points") or [])],
            "must_not": [str(p) for p in (q.get("must_not") or [])],
            "citation_req": q.get("citation_req"),
            "expected_type": q.get("expected_type") or "normal",
            "msg_sha16": _answer_msg_sha16(messages),
            "evidence_top5": evs,
            "result": res}
    # 第10卷三字段（2026-10-11 设计稿）：带字段的题行内落键+扩展判据版本键
    # （rubric_ext）；老题不落键——行制与历史逐字节一致。
    if q.get("must_cover") or q.get("must_cite_type") or q.get("hard_gate"):
        line["must_cover"] = [str(p) for p in (q.get("must_cover") or [])]
        line["must_cite_type"] = q.get("must_cite_type")
        line["hard_gate"] = q.get("hard_gate")
        line["rubric_ext"] = ANSWER_RUBRIC_EXT_VERSION
    if sampling:
        line["sampling"] = sampling
    return line


def append_answer_jsonl_line(path, line):
    """逐题追加+flush+fsync（幂等缓存先例：断电/中断后已写行保留，重跑按缓存键
    续跑免重复计费；文件末尾缺换行的断电半行先补换行隔离，读取侧坏行跳过兜底）。"""
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    prefix = ""
    if os.path.exists(path) and os.path.getsize(path) > 0:
        with open(path, "rb") as f:
            f.seek(-1, os.SEEK_END)
            if f.read(1) != b"\n":
                prefix = "\n"
    with open(path, "a", encoding="utf-8") as f:
        if prefix:
            f.write(prefix)
        f.write(json.dumps(line, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def _say_answer_result(say, qid, res, tag="answers"):
    """单题结果行（五维全量回显——G3 元复核过程日志"log 只打两维"的修补面；null 降级
    行由调用方另行打印）。tag（2026-09-28 外部答案盲判通道复用面）：stdout 前缀可配
    ——缺省 "answers" 与历史行为逐字节一致，--answers-external 传 "answers-ext"。"""
    say("[%s] %s → pass=%s faithfulness=%s citation=%s completeness=%s "
        "version=%s abstention=%s reason=%s" % (
            tag, qid, "过" if res["pass"] else "未过",
            res["dims"]["faithfulness"], res["dims"]["citation"],
            res["dims"]["completeness"], res["dims"]["version"],
            res["dims"]["abstention"], res["reason"] or "-"))


def run_answer_judge(entries, actx, meta_by_id, say=print):
    """逐题答案评审（[answers] 行只走 stdout；md 报表零变化）。

    entries = [(paper_id, q, hits, r), ...] 运行序；评审对象=带 answer_points（或
    expected_type=abstain）的题（不设 hit_rank 门槛——abstain 题恰需评"空证据下
    是否正确拒答"），按运行序至多 actx["limit"] 题（≤0=不限；与 --faithfulness
    各自全局计数，互不挤占）。返回 (results, judged, stats)（形态同 run_faithfulness：
    与 entries 平行的结果 dict|None 列表／是否实际覆盖评审（含缓存复用）／
    {"judged","null","cached"}——usage.calls 只计新调用）。
    失败纪律：judge 异常/墙钟超时/输出畸形先同输入重试 1 次（2026-09-28 轮 1 销项②，
    _answer_judge_with_retry），再失败该题 null 静默降级——不抛出、不阻塞、不改 rc。
    材料持久化+幂等缓存（actx["jsonl"]，2026-09-28 G3 元复核升级前置）：每题
    judge 前后逐题落 jsonl（输入 ctx+输出五维明细，res=null 亦留审计行）；既有
    文件里同缓存键且 msg_sha16 同纹（rubric/题面/证据全文一致）的题免调用复用
    （零新增计费零新增写行），失配即重判并追加新行（末次行为准）。缓存键含
    判官模型段（2026-10-24 判官隔离面）——两判官同材料文件各自独立缓存。"""
    results = [None] * len(entries)
    judged = [False] * len(entries)
    stats = {"judged": 0, "null": 0, "cached": 0}
    if actx is None:
        return results, judged, stats
    if actx.get("err"):
        say("[answers] %s" % actx["err"])
        return results, judged, stats
    cc = _citation_check_module()
    budget = float(actx.get("timeout") or ANSWER_TIMEOUT_DEFAULT)
    limit = int(actx.get("limit") or 0)
    judge = actx["judge"]
    usage = actx["usage"]
    jsonl = actx.get("jsonl")
    tag = actx.get("tag") or "answers"
    smp = actx.get("sampling")   # B3 k 采样面：非默认采样入缓存键（默认 None=历史键）
    cache = load_answer_jsonl_cache(jsonl)
    for i, (pid, q, hits, r) in enumerate(entries):
        if not _answer_eligible(q):
            continue                              # 非评审对象（无要点且非 abstain 题）
        if limit > 0 and stats["judged"] >= limit:
            continue                              # --limit 截断（按运行序全局计数）
        stats["judged"] += 1
        judged[i] = True
        qid = r["id"]
        messages = build_answer_messages(q, hits, meta_by_id)
        hit = cache.get(_answer_cache_key(pid, qid, smp, actx.get("model")))
        if hit and hit["msg_sha16"] == _answer_msg_sha16(messages):
            results[i] = hit["result"]            # 幂等缓存命中：免调用复用（零计费）
            stats["cached"] += 1
            say("[answers] %s 命中持久化缓存（msg_sha16 同纹，免调用复用）" % qid)
            _say_answer_result(say, qid, hit["result"])
            continue
        res = _answer_judge_with_retry(judge, messages, budget, cc, usage, say,
                                       tag, qid, hard_gate=q.get("hard_gate"))
        results[i] = res
        if jsonl:
            append_answer_jsonl_line(
                jsonl, answer_jsonl_line(pid, q, hits, meta_by_id, messages, res,
                                         actx["model"], sampling=smp))
        if res is None:
            stats["null"] += 1
            say("[answers] %s → null（降级：失败/超时/畸形）" % qid)
        else:
            _say_answer_result(say, qid, res)
    return results, judged, stats


def _judge_usage_est_cny(ctx):
    """生成侧费用估算（ctx.usage × cfg_keys 单价；订阅通道 est_cny 仅量级参照
    非现金——run_sub.sh 注释口径；faith/answers 两通道共用）。"""
    u, k = ctx["usage"], ctx["cfg_keys"]
    return (u["input_tokens"] / 1e6 * k["price_in"]
            + u["output_tokens"] / 1e6 * k["price_out"])


def answer_usage_line(actx, say=print):
    """答案通道用量如实打印（仅 --answers 且 --yes 时走到；tag 可配——外部盲判通道
    传 "answers-ext"，缺省与历史行为一致）。"""
    u = actx["usage"]
    say("[%s] 用量：calls=%d input_tokens=%d output_tokens=%d est≈%.6f 元"
        "（订阅通道配额消耗非现金，est 仅量级参照）" % (
            actx.get("tag") or "answers",
            u["calls"], u["input_tokens"], u["output_tokens"],
            _judge_usage_est_cny(actx)))


def append_answer_ledger(actx, say=print):
    """生成用量.jsonl 追加 1 行（stage 缺省=answer_judge，外部盲判通道传
    answer_judge_external 分账；行格式=台账 2026-09-28 现行九键 {ts,stage,model,
    batch,n,input_tokens,output_tokens,retries,est_cny}）。零调用不写行；ledger=None
    （单测）跳过。"""
    u = actx["usage"]
    if not u["calls"] or not actx.get("ledger"):
        return
    stage = actx.get("stage") or ANSWER_STAGE
    line = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "stage": stage,
            "model": actx["model"], "batch": 0, "n": u["calls"],
            "input_tokens": u["input_tokens"], "output_tokens": u["output_tokens"],
            "retries": 0, "est_cny": round(_judge_usage_est_cny(actx), 6)}
    d = os.path.dirname(actx["ledger"])
    if d:
        os.makedirs(d, exist_ok=True)
    with open(actx["ledger"], "a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")
    say("[%s] 台账 生成用量.jsonl 追加 1 行：stage=%s n=%d est≈%.6f 元（量级参照）"
        % (actx.get("tag") or "answers", stage, u["calls"], line["est_cny"]))


def answer_paper_metrics(entries, results, judged, paper_id):
    """卷级答案评测指标（仅 --answers 开启时入 papers[].metrics）：faithfulness_rate=
    非 null 题中 faithfulness 维 pass 的比例（全 null/零评审 → None）；judged=实际
    覆盖评审题数（含持久化缓存复用）；null=降级题数；pass=被评维全过题数（v2 口径：
    citation 维 partial 亦放行——同族架构文档实引不阻断整题）。

    第10卷扩展汇总键（2026-10-11 设计稿 §四：只统计带字段的题；hard_gate 已折入
    单题 pass，此处另出硬门自身通过率与 must_cover 命中率代理读数——must_cover
    逐项必中口径下 completeness=pass 即命中）。老卷零此类题 → 两键不出现，
    --json 输出与既往逐字节一致。"""
    idx = [i for i, (pid, _q, _h, _r) in enumerate(entries)
           if pid == paper_id and judged[i]]
    ok = [results[i] for i in idx if results[i] is not None]
    faith_n = sum(1 for x in ok if x["dims"]["faithfulness"] == "pass")
    out = {"answer_judged": len(idx), "answer_null": len(idx) - len(ok),
           "answer_pass": sum(1 for x in ok if x["pass"]),
           "faithfulness_rate": (faith_n / len(ok)) if ok else None}
    hg_idx = [i for i in idx if entries[i][1].get("hard_gate")]
    if hg_idx:
        hg_ok = [(entries[i][1]["hard_gate"], results[i]) for i in hg_idx
                 if results[i] is not None]
        out["hard_gate_pass_rate"] = (
            sum(1 for hg, r in hg_ok
                if all((r.get("hard_gate_pass") or {}).get(k) == "pass"
                       for k in ("executable_steps", "specific_params") if hg.get(k)))
            / len(hg_ok)) if hg_ok else None
    mc_idx = [i for i in idx if entries[i][1].get("must_cover")]
    if mc_idx:
        mc_ok = [results[i] for i in mc_idx if results[i] is not None]
        out["must_cover_hit_rate"] = (
            sum(1 for x in mc_ok if x["dims"]["completeness"] == "pass")
            / len(mc_ok)) if mc_ok else None
    return out


# ---------------------------------------------------------------------------
# 外部答案盲判通道（--answers-external；2026-09-28 J1b 开考工程件——评已有外部答案）
#
# 与 --answers 的关系：--answers=judge 基于检索 top-5 证据**现场生成答案并自评**
# （生成/评审同体）；本通道评**已有外部答案**（RAG 臂/裸考臂产出的答案文本，两臂
# A/B 匿名盲判）——judge 只评审不生成（生成/评审分离的架构债顺带了结，评固定文本
# 天然可复现）。判卷输入=卷题 schema v2 字段（query/answer_points/must_not/
# citation_req/expected_type）+答案文本；**不见**检索证据块/金标锚/臂身份（J1b 判卷
# 协议草案-20260928 §1.2-1 盲态纪律）。两臂 A/B 匿名映射表归组织侧，本 harness
# 原样记 arm 标签（A/B 匿名或 bare/rag 实名）。零检索零嵌入：不读向量库、不嵌
# query（判卷无需证据，嵌入费恒零）。
# ---------------------------------------------------------------------------
# 外部答案 JSONL 输入行：{"qid": 卷内题号, "arm": "A"|"B"|"bare"|"rag"（大小写/
# 裸考等别名宽容归一）, "answer_text": 答案文本（null/空白=未答，按错计零调用——
# 协议 §1.2-4 未答=错）}
# 台账 stage 字面（与 G1 的 answer_judge 分账——协议 §3.1 建议专用字面）
ANSWER_EXTERNAL_STAGE = "answer_judge_external"
# stdout 行前缀（与 --answers 的 [answers] 分读）
ANSWER_EXTERNAL_TAG = "answers-ext"
# rubric 版本标识：五维判定/白名单/pass 折叠口径与 ANSWER_RUBRIC_VERSION v3 同款
# （含 citation 维 partial 档与 fail 档排他条件、judge temperature=0），评审对象换为
# 固定外部答案文本（无生成步；faithfulness/citation 无证据集对照口径）。幂等缓存仍
# 按 messages 全文 sha16 失效（rubric 在 system 提示内，措辞一变即全量重判）。
# v3-ext2（2026-09-28 轮 1 销项③）：citation 同族 partial 档加固——同族判定须答案
# 实引该族文档且内容实质支撑，仅提及族名不算（轮 1 一份同族 partial 误判 fail 的
# 反向加固+一份仅提族名误放；键回填修复-20260928.md §五"judge rubric 违例"类）
ANSWER_EXTERNAL_RUBRIC_VERSION = "answer_rubric/v3-ext2-20260928"
# 材料持久化缺省档名模板（%s=YYYYMMDD；与 --answers 的 answer_judge-%s.jsonl 分档）
ANSWER_EXTERNAL_JSONL_REL = "logs/answer_external-%s.jsonl"
# 臂呈现/配对序：A/B 匿名在前；实名臂 rag 先于 bare——恰两臂时 Δpp=前者−后者，
# rag−bare 方向即 J1b 协议 §2.2 的 RAG−裸考口径
EXTERNAL_ARM_ORDER = ("A", "B", "rag", "bare")
# 臂标签归一表（输入宽容：大小写不敏感、裸考中文别名都认；输出恒规范形）
_EXTERNAL_ARM_ALIASES = {"a": "A", "b": "B", "arma": "A", "armb": "B",
                         "arm_a": "A", "arm_b": "B", "arm1": "A", "arm2": "B",
                         "rag": "rag", "bare": "bare", "裸考": "bare",
                         "裸考臂": "bare", "rag臂": "rag"}
# 外部答案文本评审呈现上限（防超长答案撑爆 judge 输入）。2026-09-28 轮 1 销项①：
# 2000→4000——轮 1 RAG 6 份/裸考 9 份超限被截（参-P14 型 3012 字截后缺结论半，
# 键回填修复-20260928.md §五"截断类"）；cfg 键 answer_external_text_max_chars
# （pipeline_config，--config JSON 可覆盖）经 _resolve_ext_text_max_chars 生效，
# 坏值/非正数回本常量
ANSWER_EXTERNAL_TEXT_MAX_CHARS = 4000
# 占位键模板标记（2026-09-28 轮 1 销项④防线一）：轮 1 事故=题卷 answer_points 全为
# 占位模板（"【键占位·单位半】…轮 0 键冻结时回填实际答案…"），judge 把占位句当要点
# 对照产生系统性失真（RAG −35.0pp/裸考 +5.0pp，键回填修复-20260928.md §一）——
# 外部盲判通道前置结构检查：任一条含此字样即整通道拒收退 2（占位键不进判卷面）
ANSWER_POINTS_PLACEHOLDER_MARK = "键占位"

ANSWER_EXTERNAL_SYSTEM_PROMPT = (
    "你是问答机外部答案盲判评审器（评一份已完成的外部作答：不生成答案、不改写作答、"
    "不猜测作答者身份）。给定用户问题、必答要点/禁答点/引用要求/题型，以及【待评审答案】"
    "全文，按以下固定 rubric 逐维判定：\n"
    "faithfulness=答案各陈述与必答要点/题面无矛盾，无凭空编造的数值、结论或出处"
    "（本模式不呈现证据集，无法核证且无明显矛盾时取 na）；\n"
    "citation=对照本题【引用要求（citation_req）】的 docs 正主清单核对答案引用（题未给"
    " citation_req 时按\"引用表述与题面出处信息一致\"口径评，答案不涉引用时取 na）：引用落在"
    " docs 清单内且表述一致 → pass；引用的是 docs 清单件的同族架构文档（同一制式下描述整体"
    "架构/流程的总纲概述件，典型如 NR 的 TS 38.300 之于具体规范件 TS 38.331、LTE 的"
    " TS 36.300 之于 TS 36.331）且实质支撑所述内容 → partial（同族判定须答案实引该族的"
    "具体文档且内容实质支撑所述结论；仅提及族名/系列名而无具体文号实引不算同族 partial，"
    "按题未给 citation_req 时的引用一致性口径或引用缺失评，不得放宽放行）；引用 docs 清单外"
    "且与正主非同族架构关系的其他文档（含跨制式混引，如 NR 题引 LTE 件；凡同族架构文档且"
    "答案实引、实质支撑者一律判 partial，不得按清单外判 fail）、引用与所述内容不符或编造"
    "引用 → fail；\n"
    "completeness=必答要点 answer_points 全部覆盖（数值与单位均须对上——单位错或数量级错"
    "即该要点未覆盖；abstain 题按\"拒答且说明缺口\"口径评）；\n"
    "version=涉及的规范版本/条款号/文号表述与题面版本信息一致（答案不涉及时取 na）；\n"
    "abstention=abstain 题是否正确拒答（normal 题恒取 na）；答案出现禁答点（must_not）"
    "相关内容时对应维取 fail 并在 reason 点名。\n"
    "每维只能取 pass/fail/na（na=该维不适用）；唯一例外：citation 维可再取 partial"
    "（同族架构文档实引），partial 不单独判整题未过，但 reason 须点名\"指定=某件、"
    "实引=某件\"。reason 核对引用时必须对照本题 citation_req 的 docs 原文点名正主清单"
    "（如\"citation_req 正主=TS 38.213/38.214，答案实引 TS 38.331 属清单外\"），不得以"
    "\"引用了某真实规范\"笼统带过。\n"
    "只输出一个 JSON 对象，不要解释、不要代码围栏、不要复述答案，格式：\n"
    '{"faithfulness": "pass", "citation": "pass", "completeness": "pass", '
    '"version": "na", "abstention": "na", "reason": "一句话理由"}\n'
    "reason 为不超过 80 字的中文一句话。")


class ExternalAnswersError(ValueError):
    """外部答案文件非法（--answers-external 前置失败，退出码 2）。"""


def check_no_placeholder_answer_points(papers):
    """外部盲判通道题卷结构检查（轮 1 销项④防线一，纯函数零 IO）：任一题
    answer_points 含占位模板标记（ANSWER_POINTS_PLACEHOLDER_MARK="键占位"字样）
    → 抛 ExternalAnswersError（main 捕获退 2，整通道拒收）——防轮 1 型占位键
    判卷事故复现（占位句当要点对照产生系统性失真）。检查面=全卷全题（含无外部
    答案的题——占位键是题卷缺陷，与答案文件无关，前置一刀切）。"""
    for paper in papers:
        for q in paper["questions"]:
            for p in (q.get("answer_points") or []):
                if ANSWER_POINTS_PLACEHOLDER_MARK in str(p):
                    raise ExternalAnswersError(
                        "题卷 %s 题 %s answer_points 含占位模板（'%s'字样：键回填未执行，"
                        "不得据以判卷）——外部盲判整通道拒收退 2，请回填实际键文后重跑"
                        "（运营/J1b盲判-202610/键回填修复-20260928.md）" % (
                            paper.get("paper_id") or "-", q.get("id") or "-",
                            ANSWER_POINTS_PLACEHOLDER_MARK))


def _resolve_ext_text_max_chars(cfg):
    """外部通道答案文本截长解析（轮 1 销项①）：cfg.answer_external_text_max_chars
    （pipeline_config 键，--config JSON 可覆盖）优先，坏值/非正数回模块常量
    ANSWER_EXTERNAL_TEXT_MAX_CHARS=4000（pipeline_config.validate 已拦非正数，
    此处兜底防测试/程序化注入 dict 绕过校验）。"""
    try:
        v = int(cfg.get("answer_external_text_max_chars"))
    except (TypeError, ValueError):
        return ANSWER_EXTERNAL_TEXT_MAX_CHARS
    return v if v > 0 else ANSWER_EXTERNAL_TEXT_MAX_CHARS


def load_external_answers(path, papers):
    """读外部答案 JSONL → {qid: {arm: answer_text|None}}（前置校验；失败抛
    ExternalAnswersError，main 捕获退 2）。

    校验：每行须为含 qid/arm/answer_text 三键的对象（answer_text 可 null/空白=
    未答）；arm 按别名表归一到 A/B/bare/rag；qid 须在卷内存在且为评审对象
    （answer_points 非空或 expected_type=abstain）；(qid, arm) 不得重复（静默末次
    为准会吞输入错，前置拒收）。空文件（零有效行）拒收。前置另含题卷结构检查
    （轮 1 销项④）：answer_points 含"键占位"占位模板 → 整通道拒收（见
    check_no_placeholder_answer_points）。"""
    check_no_placeholder_answer_points(papers)
    qmap = {}
    for p in papers:
        for q in p["questions"]:
            qmap[q["id"]] = q
    out = {}
    with open(path, encoding="utf-8") as f:
        for ln, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                raise ExternalAnswersError("第 %d 行 JSON 解析失败（%s）：%s" % (ln, path, e))
            if not isinstance(obj, dict):
                raise ExternalAnswersError("第 %d 行须为对象：%s" % (ln, path))
            qid = obj.get("qid")
            if not isinstance(qid, str) or not qid.strip():
                raise ExternalAnswersError("第 %d 行 qid 须为非空字符串：%s" % (ln, path))
            qid = qid.strip()
            where = "第 %d 行（%s）" % (ln, qid)
            arm_raw = obj.get("arm")
            if not isinstance(arm_raw, str) or not arm_raw.strip():
                raise ExternalAnswersError("%s arm 须为非空字符串" % where)
            arm = _EXTERNAL_ARM_ALIASES.get(arm_raw.strip().lower())
            if arm is None:
                raise ExternalAnswersError(
                    "%s arm=%r 不在归一表（A/B/bare/rag——匿名或实名二选一）" % (where, arm_raw))
            q = qmap.get(qid)
            if q is None:
                raise ExternalAnswersError("%s 不在题卷内（%s）" % (where, path))
            if not _answer_eligible(q):
                raise ExternalAnswersError(
                    "%s 无 answer_points 且非 abstain，非外部评审对象" % where)
            if "answer_text" not in obj:
                raise ExternalAnswersError("%s 缺 answer_text 键（未答须显式给 null）" % where)
            at = obj.get("answer_text")
            if at is not None and not isinstance(at, str):
                raise ExternalAnswersError("%s answer_text 须为字符串或 null（未答）" % where)
            if arm in out.setdefault(qid, {}):
                raise ExternalAnswersError("%s 重复臂 %s：(qid, arm) 不得重复" % (where, arm))
            out[qid][arm] = at.strip() if isinstance(at, str) and at.strip() else None
    if not out:
        raise ExternalAnswersError("外部答案文件不含任何有效行：%s" % path)
    return out


def build_answer_external_messages(q, answer_text, max_chars=None):
    """(题, 外部答案文本) → 外部答案盲判 messages（system+user 两条；纯函数零网络）。

    盲态纪律（协议 §1.2-1）：judge 只见题面+schema v2 评审要素+答案文本——**不含**
    检索证据块、金标锚（expect_doc/locator 等检索侧字段）、臂标号（防按臂猜倾向）。
    答案文本截 max_chars 兜底（缺省 ANSWER_EXTERNAL_TEXT_MAX_CHARS=4000，轮 1
    销项①；run_answer_external_judge 传 actx 的 cfg 覆盖值）。answer_points 位置
    加判卷基准注记"以卷内实际键文为准"（轮 1 销项④防线二——与防线一结构检查双保险：
    万一占位模板再进判卷面，judge 亦有明示不得据占位句对照；措辞入 messages 即入
    msg_sha16 幂等缓存键）。"""
    text = str(answer_text or "").strip()
    try:
        limit = int(max_chars) if max_chars else ANSWER_EXTERNAL_TEXT_MAX_CHARS
    except (TypeError, ValueError):
        limit = ANSWER_EXTERNAL_TEXT_MAX_CHARS
    if limit <= 0:
        limit = ANSWER_EXTERNAL_TEXT_MAX_CHARS
    if len(text) > limit:
        text = text[:limit]
    parts = _answer_spec_parts(q)
    for i, part in enumerate(parts):
        if part.startswith("【必答要点"):
            parts[i] = part.replace(
                "维对照）】",
                "维对照；判卷基准=以卷内实际键文为准，遇占位模板（含\"键占位\"字样）"
                "不得据以判卷）】")
            break
    user = ("【用户问题】\n" + str(q.get("query") or "").strip() +
            "\n\n" + "\n\n".join(parts) +
            "\n\n【待评审答案（外部作答全文）】\n" + (text or "（空）") +
            "\n\n请按系统要求只评审不生成，只输出 JSON 对象。")
    # 第10卷条件注入（设计稿 §四）：盲判面同款条件注入——老题 ext 恒 ""（system
    # 提示逐字节同纹）；带 must_cite_type 的题对照表=映射档 doc 清单（不见证据面）。
    return [{"role": "system",
             "content": ANSWER_EXTERNAL_SYSTEM_PROMPT + _answer_rubric_ext(q)},
            {"role": "user", "content": user}]


def _external_cache_key(paper_id, qid, arm, sampling=None, judge_model=None):
    """外部通道幂等缓存键：卷/题/臂三元——同题两臂各自独立缓存。sampling
    （2026-10-11 B3 k 采样面）：非 None 缀采样段，口径同 _answer_cache_key；
    judge_model（2026-10-24 判官隔离面）：非 None 缀 "$<model>" 判官段，同法
    同口径——两判官共用同一 --answers-jsonl 材料文件不串档。"""
    return _answer_cache_key(paper_id, "%s#%s" % (qid, arm), sampling, judge_model)


def _unanswered_result():
    """未答合成结果（协议 §1.2-4：未答=错）：五维全 na、pass=False、零 judge 调用。"""
    return {"answer": "", "dims": {k: "na" for k in ANSWER_DIMS},
            "pass": False, "reason": "未答：answer_text 空，按错计（不调 judge）"}


def answer_external_jsonl_line(paper_id, q, arm, answer_text, messages, res, model,
                               sampling=None):
    """外部通道单题持久化行（judge 输入 ctx+输出明细；纯函数零网络）。与 --answers 的
    answer_jsonl_line 同款行制，差异：arm 键（幂等缓存键成分）+answer_text 全文（评审
    对象本体，审计须完整）+evidence_top5 恒 []（盲判不见证据）；未答行 msg_sha16=""
    （不进缓存——未答判定恒定，无需缓存）。sampling（2026-10-11 B3 k 采样面）：非
    None 时行内落键，口径同 answer_jsonl_line。"""
    line = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "rubric": ANSWER_EXTERNAL_RUBRIC_VERSION, "model": model,
            "paper_id": paper_id, "qid": q.get("id"), "arm": arm,
            "query": str(q.get("query") or ""),
            "answer_points": [str(p) for p in (q.get("answer_points") or [])],
            "must_not": [str(p) for p in (q.get("must_not") or [])],
            "citation_req": q.get("citation_req"),
            "expected_type": q.get("expected_type") or "normal",
            "answer_text": answer_text,
            "msg_sha16": (_answer_msg_sha16(messages) if messages is not None else ""),
            "evidence_top5": [],
            "result": res}
    # 第10卷三字段（同 answer_jsonl_line 条件落键；老题行制不变）
    if q.get("must_cover") or q.get("must_cite_type") or q.get("hard_gate"):
        line["must_cover"] = [str(p) for p in (q.get("must_cover") or [])]
        line["must_cite_type"] = q.get("must_cite_type")
        line["hard_gate"] = q.get("hard_gate")
        line["rubric_ext"] = ANSWER_RUBRIC_EXT_VERSION
    if sampling:
        line["sampling"] = sampling
    return line


def run_answer_external_judge(papers, ext, actx, say=print):
    """逐题×臂外部答案盲判（[answers-ext] 行只走 stdout；其他模式输出零变化）。

    papers=loader 规范化卷列表；ext=load_external_answers 产物 {qid:{arm:text|None}}；
    行序=卷序/题序/臂序（EXTERNAL_ARM_ORDER）。返回 (rows, stats)：
    rows=[{paper_id,qid,arm,answer_text,res,cached,unanswered}]，
    stats={"judged","null","cached","unanswered"}。失败纪律同 run_answer_judge
    （异常/超时/畸形先同输入重试 1 次再逐份 null 静默降级不抛出不改 rc——轮 1
    销项②；凭据缺失整通道跳过全 null）；幂等缓存键=paper/qid#arm+messages
    sha16+判官模型段（arm 入键——同题两臂独立缓存；judge model 入键——
    2026-10-24 判官隔离面，两判官共用材料文件互不掩没）。答案文本截长=
    actx["ext_text_max_chars"]
    （轮 1 销项①：cfg 键 answer_external_text_max_chars 可覆盖，缺省 4000）。"""
    rows = []
    stats = {"judged": 0, "null": 0, "cached": 0, "unanswered": 0}
    if actx is None:
        return rows, stats
    tag = actx.get("tag") or "answers"

    def _tasks():
        for paper in papers:
            for q in paper["questions"]:
                arms = ext.get(q["id"])
                if not arms:
                    continue                      # 本题无外部答案（子集交付合法）
                for arm in EXTERNAL_ARM_ORDER:
                    if arm in arms:
                        yield paper, q, arm, arms[arm]

    if actx.get("err"):
        say("[%s] %s" % (tag, actx["err"]))
        for paper, q, arm, text in _tasks():
            stats["judged"] += 1
            stats["null"] += 1
            rows.append({"paper_id": paper["paper_id"], "qid": q["id"], "arm": arm,
                         "answer_text": text, "res": None, "cached": False,
                         "unanswered": text is None})
        return rows, stats
    cc = _citation_check_module()
    budget = float(actx.get("timeout") or ANSWER_TIMEOUT_DEFAULT)
    limit = int(actx.get("limit") or 0)
    judge = actx["judge"]
    usage = actx["usage"]
    jsonl = actx.get("jsonl")
    smp = actx.get("sampling")   # B3 k 采样面：非默认采样入缓存键（默认 None=历史键）
    cache = load_answer_jsonl_cache(jsonl)
    for paper, q, arm, text in _tasks():
        if limit > 0 and stats["judged"] >= limit:
            continue                              # --limit 截断（按行序全局计数）
        stats["judged"] += 1
        qid = q["id"]
        row = {"paper_id": paper["paper_id"], "qid": qid, "arm": arm,
               "answer_text": text, "res": None, "cached": False,
               "unanswered": text is None}
        rows.append(row)
        if text is None:                          # 未答=错：合成结果零调用（协议 §1.2-4）
            stats["unanswered"] += 1
            row["res"] = _unanswered_result()
            if jsonl:
                append_answer_jsonl_line(
                    jsonl, answer_external_jsonl_line(
                        paper["paper_id"], q, arm, None, None, row["res"],
                        actx["model"], sampling=smp))
            say("[%s] %s#%s → 未答（空答案按错计，不调 judge）" % (tag, qid, arm))
            continue
        messages = build_answer_external_messages(
            q, text, max_chars=actx.get("ext_text_max_chars"))
        hit = cache.get(_external_cache_key(paper["paper_id"], qid, arm, smp,
                                            actx.get("model")))
        if hit and hit["msg_sha16"] == _answer_msg_sha16(messages):
            row["res"], row["cached"] = hit["result"], True
            stats["cached"] += 1
            say("[%s] %s#%s 命中持久化缓存（msg_sha16 同纹，免调用复用）" % (tag, qid, arm))
            _say_answer_result(say, "%s#%s" % (qid, arm), row["res"], tag=tag)
            continue
        res = _answer_judge_with_retry(judge, messages, budget, cc, usage, say,
                                       tag, "%s#%s" % (qid, arm),
                                       hard_gate=q.get("hard_gate"))
        row["res"] = res
        if jsonl:
            append_answer_jsonl_line(
                jsonl, answer_external_jsonl_line(
                    paper["paper_id"], q, arm, text, messages, res,
                    actx["model"], sampling=smp))
        if res is None:
            stats["null"] += 1
            say("[%s] %s#%s → null（降级：失败/超时/畸形）" % (tag, qid, arm))
        else:
            _say_answer_result(say, "%s#%s" % (qid, arm), res, tag=tag)
    return rows, stats


def answer_external_paper_summary(paper, ext, rows):
    """卷级两臂汇总：逐臂 {judged,null,unanswered,pass,pass_rate}+恰两臂卷的逐题配对
    +delta_pp。

    口径（协议 §2.2）：通过率分母=非 null 行（未答按错计**在**分母内——协议"未答计
    错"；judge 失败 null 降级**不**在分母——harness 侧失败非作答错）；配对=同题两臂
    均有非 null 判定的题（Δpp 逐题配对口径）；delta_pp=（EXTERNAL_ARM_ORDER 前臂
    −后臂）×100——A/B 匿名卷= A−B，bare/rag 实名卷= rag−bare（J1b RAG−裸考方向），
    开盲后按映射表归位。"""
    pid_rows = [r for r in rows if r["paper_id"] == paper["paper_id"]]
    arms_all = []
    for r in pid_rows:
        if r["arm"] not in arms_all:
            arms_all.append(r["arm"])
    ordered = [a for a in EXTERNAL_ARM_ORDER if a in arms_all]
    arms = {}
    for arm in ordered:
        rs = [r for r in pid_rows if r["arm"] == arm]
        ok = [r for r in rs if r["res"] is not None]
        n_pass = sum(1 for r in ok if r["res"]["pass"])
        arms[arm] = {"judged": len(rs), "null": len(rs) - len(ok),
                     "unanswered": sum(1 for r in rs if r["unanswered"]),
                     "pass": n_pass,
                     "pass_rate": (n_pass / len(ok)) if ok else None}
    pairing = delta = None
    if len(ordered) == 2:
        a, b = ordered
        pa = {r["qid"]: r["res"]["pass"] for r in pid_rows
              if r["arm"] == a and r["res"] is not None}
        pb = {r["qid"]: r["res"]["pass"] for r in pid_rows
              if r["arm"] == b and r["res"] is not None}
        both = [q for q in pa if q in pb]
        pairing = {"arms": [a, b], "n_pairable": len(both),
                   "both_pass": sum(1 for q in both if pa[q] and pb[q]),
                   "pass_only_first": sum(1 for q in both if pa[q] and not pb[q]),
                   "pass_only_second": sum(1 for q in both if pb[q] and not pa[q]),
                   "both_fail": sum(1 for q in both if not pa[q] and not pb[q])}
        ra, rb = arms[a]["pass_rate"], arms[b]["pass_rate"]
        if ra is not None and rb is not None:
            delta = (ra - rb) * 100.0
    return {"arms": arms, "pairing": pairing, "delta_pp": delta}


def _external_report_block(papers, ext_path, ext, rows, summaries, actx, mode_tag):
    """外部答案盲判报告块（追加式；仅本模式写入——其他模式 md 报表零变化）。"""
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    arms_all = []
    for arms in ext.values():
        for a in arms:
            if a not in arms_all:
                arms_all.append(a)
    n_rec = sum(len(v) for v in ext.values())
    lines = ["---", "## 外部答案盲判评测 | %s | %s" % (ts, mode_tag), ""]
    lines.append("- 外部答案文件：%s（%d 份答案／%d 题；臂：%s）" % (
        ext_path, n_rec, len(ext), "、".join(arms_all) or "-"))
    lines.append("- judge：model=%s rubric=%s timeout=%.0fs 答案文本截长=%d 字"
                 "（cfg 键 answer_external_text_max_chars 可覆盖；订阅通道配额非现金，est 仅量级参照）" % (
                     actx["model"], ANSWER_EXTERNAL_RUBRIC_VERSION, actx["timeout"],
                     actx.get("ext_text_max_chars") or ANSWER_EXTERNAL_TEXT_MAX_CHARS))
    lines.append("- 盲判口径：judge 只见题面+必答要点/禁答点/引用要求+答案文本——不见检索"
                 "证据/金标锚/作答过程/臂身份；臂标签按输入原样记录（A/B 匿名映射表归组织侧）")
    lines.append("- 未答口径：answer_text 空=未答按错计（协议 §1.2-4，零 judge 调用）；"
                 "null=judge 失败降级，不计 pass 率分母")
    lines.append("")
    for paper, summ in zip(papers, summaries):
        pid_rows = [r for r in rows if r["paper_id"] == paper["paper_id"]]
        if not pid_rows:
            continue
        lines.append("#### 卷 %s（%d 题中 %d 题有外部答案）" % (
            paper["paper_id"], len(paper["questions"]),
            sum(1 for q in paper["questions"] if q["id"] in ext)))
        lines.append("")
        lines.append("| 题号 | 臂 | 判过 | faithfulness | citation | completeness | version | abstention | 理由 |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for r in pid_rows:
            res = r["res"]
            if res is None:
                verdict, cells = "**null（降级）**", ["-"] * 5
            elif r["unanswered"]:
                verdict, cells = "**未过（未答）**", ["-"] * 5
            else:
                verdict = "**过**" if res["pass"] else "**未过**"
                cells = [res["dims"][k] for k in ANSWER_DIMS]
            lines.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
                r["qid"], r["arm"], verdict, cells[0], cells[1], cells[2],
                cells[3], cells[4], _cell(res["reason"] if res else "")))
        lines.append("")
        lines.append("##### 两臂汇总")
        lines.append("")
        lines.append("| 臂 | 评审 n | pass | pass 率 | 未答 | null 降级 |")
        lines.append("|---|---|---|---|---|---|")
        for arm, m in summ["arms"].items():
            lines.append("| %s | %d | %d | %s | %d | %d |" % (
                arm, m["judged"], m["pass"],
                ("%.1f%%" % (m["pass_rate"] * 100)) if m["pass_rate"] is not None else "-",
                m["unanswered"], m["null"]))
        if summ["pairing"]:
            pr = summ["pairing"]
            a, b = pr["arms"]
            lines.append("")
            lines.append("- 逐题配对（两臂均有有效判定 %d 题）：双过 %d／仅%s过 %d／仅%s过 %d／双不过 %d" % (
                pr["n_pairable"], pr["both_pass"], a, pr["pass_only_first"],
                b, pr["pass_only_second"], pr["both_fail"]))
        if summ["delta_pp"] is not None:
            a, b = summ["pairing"]["arms"]
            lines.append("- **Δpp（%s − %s）= %+.1f pp**（逐臂 pass 率差；开盲后按映射表"
                         "归位 RAG/裸考方向）" % (a, b, summ["delta_pp"]))
        lines.append("")
    u = actx["usage"]
    lines.append("- judge 用量：calls=%d input_tokens=%d output_tokens=%d est≈%.6f 元"
                 "（订阅通道配额非现金，量级参照；台账 stage=%s）" % (
                     u["calls"], u["input_tokens"], u["output_tokens"],
                     _judge_usage_est_cny(actx), actx.get("stage") or ANSWER_STAGE))
    lines.append("- 判读注：本块为外部答案盲判（J1b 判卷协议 §二）；单题过=被评维全过"
                 "（citation partial 放行）；judge-人工一致率与人工裁决归判卷协议流程，"
                 "不在本 harness 面")
    lines.append("")
    return "\n".join(lines)


def build_external_json_payload(papers, ext_path, ext, rows, summaries, actx):
    """外部答案盲判机读 payload（schema 头同 smoke_accept.json/v1；lib/compare_lib
    恒 null——零检索模式；questions 行=题级 {qid,arm,五维,pass}，papers 块=两臂汇总
    +逐题配对+Δpp——J1b Δpp 的机读数据源）。"""
    u = actx["usage"]
    return {
        "schema": JSON_SCHEMA_TAG,
        "ran_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": "answers_external",
        "lib": None,
        "compare_lib": None,
        "channel": "blind_judge",
        "config": {"judge_model": actx["model"],
                   "rubric": ANSWER_EXTERNAL_RUBRIC_VERSION,
                   "timeout": actx["timeout"],
                   "answer_text_max_chars": (actx.get("ext_text_max_chars")
                                             or ANSWER_EXTERNAL_TEXT_MAX_CHARS),
                   "answers_file": ext_path,
                   "answers_jsonl": actx.get("jsonl")},
        "usage": {"calls": u["calls"], "input_tokens": u["input_tokens"],
                  "output_tokens": u["output_tokens"],
                  "est_cny": round(_judge_usage_est_cny(actx), 6)},
        "papers": [{"paper_id": p["paper_id"],
                    "n_questions": len(p["questions"]),
                    "n_answered_questions": sum(1 for q in p["questions"]
                                                if q["id"] in ext),
                    "arms": s["arms"], "pairing": s["pairing"],
                    "delta_pp": s["delta_pp"]}
                   for p, s in zip(papers, summaries)],
        "questions": [{"paper_id": r["paper_id"], "qid": r["qid"], "arm": r["arm"],
                       "unanswered": r["unanswered"], "cached": r["cached"],
                       "pass": r["res"]["pass"] if r["res"] else None,
                       "dims": dict(r["res"]["dims"]) if r["res"] else None,
                       "reason": r["res"]["reason"] if r["res"] else ""}
                      for r in rows]}


def execute_external_answers_run(cfg, papers, ext_path, ext, actx, report_path,
                                 json_path=None, say=print):
    """外部答案盲判模式主流程（零检索零嵌入：不读向量库、不嵌 query——判卷无需证据）。

    报告追加式落 report_path（缺省=题卷评测.md）；--json 给定落机读件
    （mode=answers_external）；用量/台账纪律同 --answers（stage=answer_judge_external
    分账）。恒退 0——判卷质量不是 harness 失败（判卷未过/null 只入报告与机读件；
    前置失败在 main 拦截退 2）。"""
    rows, stats = run_answer_external_judge(papers, ext, actx, say)
    answer_usage_line(actx, say)
    append_answer_ledger(actx, say)
    summaries = [answer_external_paper_summary(p, ext, rows) for p in papers]
    block = _external_report_block(papers, ext_path, ext, rows, summaries, actx,
                                   mode_tag="[--yes 真跑 --answers-external]")
    append_report(report_path, block)
    say(block)
    say("[报告] 已追加 → %s" % report_path)
    if json_path:
        write_json_result(json_path,
                          build_external_json_payload(papers, ext_path, ext, rows,
                                                      summaries, actx), say)
    return 0


# ---------------------------------------------------------------------------
# 报告（追加式带时间戳；同内容打屏，方便现场读）
# ---------------------------------------------------------------------------
def _cell(v):
    """markdown 表格单元格净化：竖线/换行不破表。"""
    return str(v if v is not None else "-").replace("|", "／").replace("\n", " ")


def _report_block(cfg, lib_path, lib_stats, results, summary, prompt_tokens,
                  cost_cny, mode_tag, topk, slices_on=False):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    std_n = summary["n"] - summary["monitor_n"] - summary["param_n"]
    lines = []
    lines.append("---")
    lines.append("## 验收冒烟·公开源一期 | %s | %s" % (ts, mode_tag))
    lines.append("")
    lines.append("- 库：%s（loaded=%s dim=%s bad_lines=%s）" % (
        lib_path, lib_stats.get("loaded"), lib_stats.get("dim"), lib_stats.get("bad_lines")))
    lines.append("- 配置：model=%s dims=%s topk=%d 单价=%s 元/Mtok 红线=%.1f 元" % (
        cfg["model"], cfg["dims"], topk, cfg["price_per_mtok"], cfg["red_line_cny"]))
    lines.append("- 题卷：%d 条（监管数字 %d / 标准条款 %d / 表格值参数卡 %d）；同源主档：%s" % (
        summary["n"], summary["monitor_n"], std_n, summary["param_n"],
        pipeline_config.resolve_path(PAPER_PATH_REL)))
    lines.append("")
    lines.append("### 逐条结果")
    lines.append("")
    lines.append("| 编号 | 类别 | 判据 | 位次 | 命中出处 | locator | score | loc锚 | 跨域top5 | 判过 | 备注 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in results:
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            r["id"], r["category"], r["criterion"], r["hit_rank"] if r["hit_rank"] else "-",
            _cell(r["hit_doc"]) or "-", _cell(r["hit_locator"]) or "-",
            ("%.6f" % r["hit_score"]) if r["hit_score"] is not None else "-",
            "是" if r["locator_ok"] else "否", r["cross_hits"],
            "**过**" if r["pass"] else "**未过**", _cell(r["note"])))
    lines.append("")
    lines.append("### 四指标 vs 通过线")
    lines.append("")
    c = summary["checks"]
    lines.append("| 指标 | 实测 | 通过线 | 判定 |")
    lines.append("|---|---|---|---|")
    lines.append("| top-5 相关率 | %d/%d = %.1f%% | ≥%d%% | %s |" % (
        summary["top5_n"], summary["n"], summary["top5_rate"] * 100,
        round(PASS_LINES["top5_rate_min"] * 100), "过" if c["top5_rate"] else "**未过**"))
    lines.append("| 监管域命中 | %d/%d | ≥%d | %s |" % (
        summary["monitor_hits"], summary["monitor_n"], PASS_LINES["monitor_hits_min"],
        "过" if c["monitor_hits"] else "**未过**"))
    lines.append("| 参数/表值行级出处 | %d/%d | ≥%d | %s |" % (
        summary["param_hits"], summary["param_n"], PASS_LINES["param_hits_min"],
        "过" if c["param_hits"] else "**未过**"))
    lines.append("| 跨域污染 | %d 处 | ≤%d | %s |" % (
        summary["cross_total"], PASS_LINES["cross_domain_max"],
        "过" if c["cross_domain"] else "**未过**"))
    lines.append("")
    lines.append("**总判：%s**（四线全过才算验收通过）" % ("过" if summary["all_pass"] else "**未过**"))
    lines.append("")
    lines.append("- 排序质量：MRR@10 = %.4f／nDCG@10 = %.4f（分级 primary=1.0、secondary=0.5、"
                 "未命中=0，线性增益折损；只测不判，不计入通过线）" % (
                     summary.get("mrr_at_10", 0.0), summary.get("ndcg_at_10", 0.0)))
    lines.append("- 总费用：prompt_tokens=%d → %.6f 元（单价 %s 元/Mtok；D5 预算口径单批约 0.003 元）" % (
        prompt_tokens, cost_cny, cfg["price_per_mtok"]))
    lines.append("- 版本口径：3GPP 12 件已回填 Rel-18 published（2026-09-17 自 raw/3gpp/清单.md）；S16 已换锚为功控 TPC 映射表（原带宽-PRB 表在 V18.3.0 已移除）")
    lines.append("- 判读注：跨域污染按 source_domain（监管/3gpp）粒度机器判；知识域内细判留人眼复核")
    if slices_on:
        lines.extend(_slices_report_lines(slice_results(results)))
    lines.append("")
    return "\n".join(lines)


def _compare_report_block(cfg, new_lib_path, old_lib_path, stats_new, stats_old,
                          rows, sum_new, sum_old, prompt_tokens, cost_cny, topk,
                          mode_tag, snapshot_lines=None, slices_on=False):
    """对比模式报告块：逐题对照表 + top-5 相关率 vs 旧基线汇总 + 四指标两列对照。"""
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    imp = [r["id"] for r in rows if r["change"].startswith("改善")]
    reg = [r["id"] for r in rows if r["change"].startswith("退化")]
    flat = len(rows) - len(imp) - len(reg)
    diff_base = (sum_new["top5_rate"] - OLD_BASELINE_TOP5_RATE) * 100
    diff_old = (sum_new["top5_rate"] - sum_old["top5_rate"]) * 100
    lines = []
    lines.append("---")
    lines.append("## 验收冒烟·公开源一期·新旧库对比 | %s | %s" % (ts, mode_tag))
    lines.append("")
    lines.append("- 新库（待评）：%s（loaded=%s dim=%s bad_lines=%s）" % (
        new_lib_path, stats_new.get("loaded"), stats_new.get("dim"),
        stats_new.get("bad_lines")))
    lines.append("- 旧库（对照）：%s（loaded=%s dim=%s bad_lines=%s）" % (
        old_lib_path, stats_old.get("loaded"), stats_old.get("dim"),
        stats_old.get("bad_lines")))
    lines.append("- 配置：model=%s dims=%s topk=%d 单价=%s 元/Mtok 红线=%.1f 元" % (
        cfg["model"], cfg["dims"], topk, cfg["price_per_mtok"], cfg["red_line_cny"]))
    lines.append("- 费用口径：18 条 query 向量化**仅一次**、两库复用——嵌入费与单库跑一致（检索层本地计算零费）")
    lines.append("")
    lines.append("### 逐题对照（新库=--vectors 待评；旧库=--compare 基线）")
    lines.append("")
    lines.append("| 题号 | 类别 | 判据 | 新rank | 旧rank | 新top1分 | 旧top1分 | 旧判→新判 | 变化 |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            r["id"], r["category"], r["criterion"],
            r["new_rank"] if r["new_rank"] else "-",
            r["old_rank"] if r["old_rank"] else "-",
            ("%.6f" % r["new_top1"]) if r["new_top1"] is not None else "-",
            ("%.6f" % r["old_top1"]) if r["old_top1"] is not None else "-",
            "%s→%s" % ("过" if r["old_pass"] else "未过",
                       "过" if r["new_pass"] else "未过"),
            ("**%s**" % r["change"]) if r["change"].startswith(("改善", "退化"))
            else r["change"]))
    lines.append("")
    lines.append("### 汇总：top-5 相关率 vs 旧基线")
    lines.append("")
    lines.append("| 口径 | top-5 相关率 | 四线总判 |")
    lines.append("|---|---|---|")
    lines.append("| 新库（待评，本次实测） | %d/%d = %.1f%% | %s |" % (
        sum_new["top5_n"], sum_new["n"], sum_new["top5_rate"] * 100,
        "过" if sum_new["all_pass"] else "**未过**"))
    lines.append("| 旧库（对照，本次实测） | %d/%d = %.1f%% | %s |" % (
        sum_old["top5_n"], sum_old["n"], sum_old["top5_rate"] * 100,
        "过" if sum_old["all_pass"] else "**未过**"))
    lines.append("| 旧基线（2026-09-17 验收首跑） | %.1f%%（13/18） | —— |" % (
        OLD_BASELINE_TOP5_RATE * 100))
    lines.append("")
    lines.append("- 判定变化：改善 %d 题%s / 退化 %d 题%s / 持平 %d 题" % (
        len(imp), ("（" + "、".join(imp) + "）") if imp else "",
        len(reg), ("（" + "、".join(reg) + "）") if reg else "", flat))
    lines.append("- 增减：新库相关率 vs 旧基线 %+.1f 点（判定线 ≥%d%%）；vs 本次旧库实测 %+.1f 点" % (
        diff_base, round(PASS_LINES["top5_rate_min"] * 100), diff_old))
    lines.append("")
    lines.append("### 四指标对照（新库为判据主体；旧库仅参考）")
    lines.append("")
    lines.append("| 指标 | 新库 | 旧库 | 通过线 |")
    lines.append("|---|---|---|---|")
    lines.append("| top-5 相关率 | %d/%d = %.1f%% | %d/%d = %.1f%% | ≥%d%% |" % (
        sum_new["top5_n"], sum_new["n"], sum_new["top5_rate"] * 100,
        sum_old["top5_n"], sum_old["n"], sum_old["top5_rate"] * 100,
        round(PASS_LINES["top5_rate_min"] * 100)))
    lines.append("| 监管域命中 | %d/%d | %d/%d | ≥%d |" % (
        sum_new["monitor_hits"], sum_new["monitor_n"],
        sum_old["monitor_hits"], sum_old["monitor_n"],
        PASS_LINES["monitor_hits_min"]))
    lines.append("| 参数/表值行级出处 | %d/%d | %d/%d | ≥%d |" % (
        sum_new["param_hits"], sum_new["param_n"],
        sum_old["param_hits"], sum_old["param_n"],
        PASS_LINES["param_hits_min"]))
    lines.append("| 跨域污染 | %d 处 | %d 处 | ≤%d |" % (
        sum_new["cross_total"], sum_old["cross_total"],
        PASS_LINES["cross_domain_max"]))
    lines.append("| 排序质量 MRR@10／nDCG@10 | %.4f／%.4f | %.4f／%.4f | ——（只测不判） |" % (
        sum_new.get("mrr_at_10", 0.0), sum_new.get("ndcg_at_10", 0.0),
        sum_old.get("mrr_at_10", 0.0), sum_old.get("ndcg_at_10", 0.0)))
    lines.append("")
    lines.append("**总判（按新库四线）：%s**" % ("过" if sum_new["all_pass"] else "**未过**"))
    lines.append("")
    lines.append("- 总费用：prompt_tokens=%d → %.6f 元（单价 %s 元/Mtok；两库复用同一批 query 向量，不翻倍）" % (
        prompt_tokens, cost_cny, cfg["price_per_mtok"]))
    lines.append("- 判读注：判定变化按单题 criterion 判过与否归类；top1 分=该库检索 rank-1 的余弦分"
                "（预期文档的位次与得分见 rank 列与单库报告，非同一口径）")
    # --snapshot（快照对比段）/--slices（切片段）门控追加；两者均关=逐字节一致
    lines.extend(snapshot_lines or [])
    if slices_on:
        lines.extend(_slices_report_lines(slice_results(
            [r["new_r"] for r in rows])))   # 切片主体=新库（判据主体同口径）
    lines.append("")
    return "\n".join(lines)


def append_report(report_path, block):
    """追加落档（带时间戳块，不覆盖历史）；父目录缺失则建。"""
    d = os.path.dirname(report_path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(report_path, "a", encoding="utf-8") as f:
        f.write(block + "\n")


# ---------------------------------------------------------------------------
# 外部题卷模式：报告与主流程（--questions-file；判定复用 judge_question）
# ---------------------------------------------------------------------------
def _fmt_rate(num, den):
    """x/y = z.z% 形态（分母 0 → "-"）。"""
    return "-" if not den else "%d/%d = %.1f%%" % (num, den, num / den * 100)


def _miss_rate_str(summary):
    if summary["n_miss"] == 0:
        return "-（本卷无 expect_miss 型）"
    return "%s（意外命中 %d 题）" % (
        _fmt_rate(summary["miss_pass"], summary["n_miss"]), summary["unexpected_hits"])


def _dom_rate_str(summary):
    """expect_domain 域命中率单元格（分母 0 → "-"）。"""
    if summary["n_domain"] == 0:
        return "-（本卷无 expect_domain 型）"
    return _fmt_rate(summary["domain_hits"], summary["n_domain"])


def _domain_judge_cell(r):
    """域判定单元格：未配置="-"；域中=位次回显；域 miss=首位次回显（深度外/未见）。"""
    if not r.get("expect_domain"):
        return "-"
    if r.get("domain_hit"):
        return "域中@%s" % r["domain_rank"]
    if r.get("domain_rank") is not None:
        return "域miss(rank%s)" % r["domain_rank"]
    return "域miss"


# 切片段维度中文名（--slices 文本报告用；E3 2026-09-28）
_SLICE_DIM_NAMES = {"domain": "域（domain）", "criterion": "判据（criterion）",
                    "category": "类别（category）", "difficulty": "难度（note Basic/Difficult）"}


def _slices_report_lines(slices):
    """切片 json → md 报表"切片"段行（--slices 门控；**仅有切片差异时显示**——
    某维 ≥2 组才出该维表，四维全单组 → 整段零行不出现；只测不判段）。"""
    lines = []
    for dim in SLICE_DIMS:
        groups = slices.get(dim) or {}
        if len(groups) < 2:
            continue
        if not lines:
            lines = ["### 切片（--slices；top5_rate／judge_pass_rate 为组内均值，"
                     "只测不判；expect_miss 题按 miss 即达标计 judge_pass）", ""]
        lines.append("#### 切片·%s" % _SLICE_DIM_NAMES[dim])
        lines.append("")
        lines.append("| 组 | n | top5_rate | judge_pass_rate |")
        lines.append("|---|---|---|---|")
        for k, g in groups.items():
            lines.append("| %s | %d | %.1f%% | %.1f%% |" % (
                _cell(k), g["n"], g["top5_rate"] * 100, g["judge_pass_rate"] * 100))
        lines.append("")
    # 末尾空行交给调用方统一补（本函数结尾不带空行，与 _snapshot_diff_lines 同约）
    return lines[:-1] if lines and lines[-1] == "" else lines


def _paper_judge_cell(r):
    """判过单元格：relevance=过/未过；expect_miss=达标(miss)/意外命中。"""
    if r["judge_type"] == "expect_miss":
        return "**意外命中**" if r["unexpected_hit"] else "达标(miss)"
    return "**过**" if r["pass"] else "**未过**"


def _paper_rows_lines(lines, results):
    """逐题结果表 + 多锚题的锚明细行 + expect_miss 层登记 + expect_domain 域判定。"""
    lines.append("")
    lines.append("#### 逐条结果")
    lines.append("")
    lines.append("| 编号 | 类别 | 判型 | 判据 | 位次 | 命中出处 | locator | score | loc锚 | 跨域top5 | 判定 | 域判定 | 备注 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in results:
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            r["id"], _cell(r["category"]) or "-", r["judge_type"], r["criterion"],
            r["hit_rank"] if r["hit_rank"] else "-",
            _cell(r["hit_doc"]) or "-", _cell(r["hit_locator"]) or "-",
            ("%.6f" % r["hit_score"]) if r["hit_score"] is not None else "-",
            "是" if r["locator_ok"] else "否", r["cross_hits"],
            _paper_judge_cell(r), _domain_judge_cell(r), _cell(r["note"])))
    multi = [r for r in results if len(r.get("anchor_hits", [])) > 1]
    if multi:
        lines.append("")
        lines.append("锚明细（primary 计过／secondary 只回显）：")
        for r in multi:
            parts = []
            for a in r["anchor_hits"]:
                tag = "%s[%s]" % (a["doc"], a["criterion"])
                if a["role"] == "secondary":
                    tag += "(次)"
                st = ("rank%s" % a["hit_rank"]) if a["hit_rank"] else "miss"
                if a["hit_rank"] and a["locator_ok"]:
                    st += "·loc中"
                parts.append("%s→%s" % (tag, st))
            lines.append("- %s：%s" % (r["id"], "；".join(parts)))
    layer = [r for r in results if r.get("expect_miss_layer")]
    if layer:
        lines.append("")
        lines.append("预期 miss 层登记：%d 条（答案层属性，检索层不做机器判定；"
                     "当前库 miss 属有效预期）：" % len(layer))
        for r in layer:
            lines.append("- %s：%s" % (r["id"], r["expect_miss_layer"]))
    domq = [r for r in results if r.get("expect_domain")]
    if domq:
        lines.append("")
        lines.append("expect_domain 域判定：%d 条（域级粒度判\"该域是否被检索到\"，"
                     "不锚具体卡——防自证；命中 %d）：" % (
                         len(domq), sum(1 for r in domq if r.get("domain_hit"))))
        for r in domq:
            lines.append("- %s：预期域 %s[%s] → %s" % (
                r["id"], r["expect_domain"], r.get("domain_criterion") or "-",
                _domain_judge_cell(r)))


def _paper_summary_lines(lines, paper, summary):
    """单卷指标段（设线与否两种列）。"""
    lines.append("")
    if summary["pass_lines"]:
        lines.append("#### 指标 vs 通过线")
        lines.append("")
        pl = summary["pass_lines"]
        c = summary["checks"]
        lines.append("| 指标 | 实测 | 通过线 | 判定 |")
        lines.append("|---|---|---|---|")
        lines.append("| top-5 相关率（relevance %d 题） | %s | ≥%s | %s |" % (
            summary["n_rel"], _fmt_rate(summary["top5_n"], summary["n_rel"]),
            _pct(pl.get("top5_rate_min")), "过" if c["top5_rate"] else "**未过**"))
        lines.append("| 监管域命中 | %s | ≥%s | %s |" % (
            _fmt_rate(summary["monitor_hits"], summary["monitor_n"]),
            pl.get("monitor_hits_min", "-"),
            "卷内无此类" if not summary["monitor_n"]
            else ("过" if c["monitor_hits"] else "**未过**")))
        lines.append("| 参数/表值行级出处 | %s | ≥%s | %s |" % (
            _fmt_rate(summary["param_hits"], summary["param_n"]),
            pl.get("param_hits_min", "-"),
            "卷内无此类" if not summary["param_n"]
            else ("过" if c["param_hits"] else "**未过**")))
        lines.append("| 跨域污染 | %d 处 | ≤%s | %s |" % (
            summary["cross_total"], pl.get("cross_domain_max", "-"),
            "过" if c["cross_domain"] else "**未过**"))
        lines.append("| expect_miss 达标率 | %s | ≥%s | %s |" % (
            _miss_rate_str(summary),
            pl.get("expect_miss_rate_min", "-"),
            "卷内无此类" if not summary["n_miss"]
            else ("过" if c["expect_miss_rate"] else "**未过**")))
        lines.append("| expect_domain 域命中率 | %s | ≥%s | %s |" % (
            _dom_rate_str(summary),
            pl.get("domain_rate_min", "-"),
            "卷内无此类" if not summary["n_domain"]
            else ("过" if c["domain_rate"] else "**未过**")))
        # 难负例负锚命中（R3 前瞻字段，只测不判）：仅有带负锚题时出现该行，
        # 无负锚卷输出与历史版本逐字节一致；无通过线键——门禁定线留后续
        if summary.get("hard_neg_total"):
            lines.append("| 难负例负锚命中（top-5） | %s | ——（只测不判） | — |" % (
                _fmt_rate(summary["hard_neg_hit_questions"],
                          summary["hard_neg_total"])))
        lines.append("")
        lines.append("**卷判（%s）：%s**" % (
            paper["paper_id"], "过" if summary["all_pass"] else "**未过**"))
        lines.append("")
        lines.append("- 排序质量：MRR@10 = %.4f／nDCG@10 = %.4f（relevance %d 题口径；分级 "
                     "primary=1.0、secondary=0.5、未命中=0，线性增益折损；只测不判，"
                     "不计入通过线）" % (summary.get("mrr_at_10", 0.0),
                                       summary.get("ndcg_at_10", 0.0),
                                       summary.get("n_rel", 0)))
    else:
        lines.append("#### 指标（本卷未设通过线——测量值，增益对比用）")
        lines.append("")
        lines.append("| 指标 | 实测 |")
        lines.append("|---|---|")
        lines.append("| top-5 相关率（relevance %d 题） | %s |" % (
            summary["n_rel"], _fmt_rate(summary["top5_n"], summary["n_rel"])))
        lines.append("| 监管域命中 | %s |" % _fmt_rate(
            summary["monitor_hits"], summary["monitor_n"]))
        lines.append("| 参数/表值行级出处 | %s |" % _fmt_rate(
            summary["param_hits"], summary["param_n"]))
        lines.append("| 跨域污染 | %d 处 |" % summary["cross_total"])
        lines.append("| expect_miss 达标率 | %s |" % _miss_rate_str(summary))
        lines.append("| expect_domain 域命中率 | %s |" % _dom_rate_str(summary))
        # 难负例负锚命中（R3 前瞻字段，只测不判）：仅有带负锚题时出现该行，
        # 无负锚卷输出与历史版本逐字节一致
        if summary.get("hard_neg_total"):
            lines.append("| 难负例负锚命中（top-5，只测不判） | %s |" % _fmt_rate(
                summary["hard_neg_hit_questions"], summary["hard_neg_total"]))
        lines.append("| MRR@10 | %.4f |" % summary.get("mrr_at_10", 0.0))
        lines.append("| nDCG@10 | %.4f |" % summary.get("ndcg_at_10", 0.0))
        lines.append("")
        lines.append("- 排序质量注：分级 primary=1.0、secondary=0.5、未命中=0，线性增益"
                     "折损，relevance 题口径；只测不判，不计入通过线")


def _pct(v):
    return ("%.0f%%" % (v * 100)) if isinstance(v, (int, float)) else "-"


def _paper_report_block(cfg, lib_path, lib_stats, paper_summaries,
                        prompt_tokens, cost_cny, mode_tag, topk, slices_on=False):
    """外部题卷模式报告块：逐卷（逐条结果+指标）+ 总表 + 费用。paper_summaries =
    [(paper, results, summary), ...]（按 --questions-file 给序）。slices_on
    （--slices 门控，E3）：逐卷追加"切片"段（仅有切片差异的维度显示）。"""
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    n_total = sum(len(rs) for _, rs, _ in paper_summaries)
    lines = []
    lines.append("---")
    lines.append("## 题卷评测 | %s | %s" % (ts, mode_tag))
    lines.append("")
    lines.append("- 库：%s（loaded=%s dim=%s bad_lines=%s）" % (
        lib_path, lib_stats.get("loaded"), lib_stats.get("dim"), lib_stats.get("bad_lines")))
    lines.append("- 配置：model=%s dims=%s topk=%d 单价=%s 元/Mtok 红线=%.1f 元" % (
        cfg["model"], cfg["dims"], topk, cfg["price_per_mtok"], cfg["red_line_cny"]))
    lines.append("- 题卷：%d 卷 %d 题（%s）" % (
        len(paper_summaries), n_total, "；".join(
            "%s %d 题" % (p["paper_id"], len(rs)) for p, rs, _ in paper_summaries)))
    for paper, results, summary in paper_summaries:
        lines.append("")
        lines.append("### 卷：%s（%d 题）" % (paper["paper_id"], len(results)))
        if paper.get("title"):
            lines.append("")
            lines.append("- %s（源：%s）" % (paper["title"], paper.get("source_md") or "-"))
        if paper.get("paper_note"):
            lines.append("- %s" % paper["paper_note"])
        _paper_rows_lines(lines, results)
        _paper_summary_lines(lines, paper, summary)
        if slices_on:
            seg = _slices_report_lines(slice_results(results))
            if seg:                      # 无切片差异 → 整段零行零空行（门控不露面）
                lines.extend(seg)
                lines.append("")
    lines.append("")
    lines.append("### 总表（各卷分别汇总）")
    lines.append("")
    lines.append("| 卷 | 题数 | top-5 相关率 | 监管命中 | 参数行级 | 跨域 | expect_miss 达标率 | 域命中率 | 通过线 |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for paper, results, summary in paper_summaries:
        lines.append("| %s | %d | %s | %s | %s | %d | %s | %s | %s |" % (
            paper["paper_id"], summary["n"],
            _fmt_rate(summary["top5_n"], summary["n_rel"]),
            _fmt_rate(summary["monitor_hits"], summary["monitor_n"]),
            _fmt_rate(summary["param_hits"], summary["param_n"]),
            summary["cross_total"], _miss_rate_str(summary),
            _dom_rate_str(summary),
            "过" if summary["all_pass"] else ("**未过**" if summary["pass_lines"]
                                              else "未设线")))
    failed = [p["paper_id"] for p, _, s in paper_summaries if not s["all_pass"]]
    lines.append("")
    lines.append("**总判：%s**（按各卷通过线；未设线的卷不计入判定%s）" % (
        "过" if not failed else "**未过（%s）**" % "、".join(failed),
        "" if not failed else "，未过卷见上"))
    lines.append("")
    lines.append("- 总费用：prompt_tokens=%d → %.6f 元（单价 %s 元/Mtok）" % (
        prompt_tokens, cost_cny, cfg["price_per_mtok"]))
    lines.append("- 判读注：relevance=任一 primary 锚满足其判据即过（secondary 只回显）；"
                "expect_miss=全锚 miss 才达标，意外命中已标注留人眼复核；"
                "预期 miss 层为登记性标注（答案层属性），不参与机器判定；"
                "expect_domain=指定域块进 criterion 深度即\"域中\"（域级判定，"
                "不锚具体卡——防自证，不计入单题 pass）")
    lines.append("")
    return "\n".join(lines)


def _paper_compare_report_block(cfg, new_lib_path, old_lib_path, stats_new,
                                stats_old, paper_summaries, prompt_tokens,
                                cost_cny, topk, mode_tag, snapshot_lines=None,
                                slices_on=False):
    """外部题卷对比模式报告块：逐卷（逐题对照+两态汇总）+ 总表。旧 72.2% 基线
    仅内置验收卷 A 有，外部卷不引（不跨卷类比）。paper_summaries =
    [(paper, rows, sum_new, sum_old), ...]。snapshot_lines（--snapshot 门控，
    D2：两快照 diff 摘要段行）/slices_on（--slices 门控，E3：逐卷切片段，主体=
    新库判据同口径）均默认关=输出与历史版本逐字节一致。"""
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    n_total = sum(len(rows) for _, rows, _, _ in paper_summaries)
    lines = []
    lines.append("---")
    lines.append("## 题卷评测·新旧库对比 | %s | %s" % (ts, mode_tag))
    lines.append("")
    lines.append("- 新库（待评）：%s（loaded=%s dim=%s bad_lines=%s）" % (
        new_lib_path, stats_new.get("loaded"), stats_new.get("dim"), stats_new.get("bad_lines")))
    lines.append("- 旧库（对照）：%s（loaded=%s dim=%s bad_lines=%s）" % (
        old_lib_path, stats_old.get("loaded"), stats_old.get("dim"), stats_old.get("bad_lines")))
    lines.append("- 配置：model=%s dims=%s topk=%d 单价=%s 元/Mtok 红线=%.1f 元" % (
        cfg["model"], cfg["dims"], topk, cfg["price_per_mtok"], cfg["red_line_cny"]))
    lines.append("- 题卷：%d 卷 %d 题；费用口径：全部 query 向量化**仅一次**、两库复用"
                "（嵌入费与单库跑一致；旧 72.2%% 基线仅验收卷 A 有，本表不引）" % (
                    len(paper_summaries), n_total))
    for paper, rows, sum_new, sum_old in paper_summaries:
        lines.append("")
        lines.append("### 卷：%s（%d 题）" % (paper["paper_id"], len(rows)))
        lines.append("")
        lines.append("#### 逐题对照（新库=--vectors 待评；旧库=--compare 基线）")
        lines.append("")
        lines.append("| 题号 | 类别 | 判型 | 新rank | 旧rank | 新top1分 | 旧top1分 | 旧判→新判 | 变化 |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for r in rows:
            lines.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
                r["id"], _cell(r["category"]) or "-", r["judge_type"],
                r["new_rank"] if r["new_rank"] else "-",
                r["old_rank"] if r["old_rank"] else "-",
                ("%.6f" % r["new_top1"]) if r["new_top1"] is not None else "-",
                ("%.6f" % r["old_top1"]) if r["old_top1"] is not None else "-",
                "%s→%s" % (_paper_judge_cell(r["old_r"]), _paper_judge_cell(r["new_r"])),
                ("**%s**" % r["change"]) if r["change"].startswith(("改善", "退化"))
                else r["change"]))
        imp = [r["id"] for r in rows if r["change"].startswith("改善")]
        reg = [r["id"] for r in rows if r["change"].startswith("退化")]
        lines.append("")
        lines.append("- 判定变化：改善 %d 题%s / 退化 %d 题%s / 持平 %d 题" % (
            len(imp), ("（" + "、".join(imp) + "）") if imp else "",
            len(reg), ("（" + "、".join(reg) + "）") if reg else "",
            len(rows) - len(imp) - len(reg)))
        lines.append("")
        lines.append("#### 两态汇总（新库为判据主体；旧库仅对照参考）")
        lines.append("")
        lines.append("| 指标 | 新库 | 旧库 |")
        lines.append("|---|---|---|")
        lines.append("| top-5 相关率 | %s | %s |" % (
            _fmt_rate(sum_new["top5_n"], sum_new["n_rel"]),
            _fmt_rate(sum_old["top5_n"], sum_old["n_rel"])))
        lines.append("| 监管域命中 | %s | %s |" % (
            _fmt_rate(sum_new["monitor_hits"], sum_new["monitor_n"]),
            _fmt_rate(sum_old["monitor_hits"], sum_old["monitor_n"])))
        lines.append("| 参数/表值行级出处 | %s | %s |" % (
            _fmt_rate(sum_new["param_hits"], sum_new["param_n"]),
            _fmt_rate(sum_old["param_hits"], sum_old["param_n"])))
        lines.append("| 跨域污染 | %d 处 | %d 处 |" % (
            sum_new["cross_total"], sum_old["cross_total"]))
        lines.append("| expect_miss 达标率 | %s | %s |" % (
            _miss_rate_str(sum_new), _miss_rate_str(sum_old)))
        lines.append("| expect_domain 域命中率 | %s | %s |" % (
            _dom_rate_str(sum_new), _dom_rate_str(sum_old)))
        lines.append("| 排序质量 MRR@10／nDCG@10 | %.4f／%.4f | %.4f／%.4f |" % (
            sum_new.get("mrr_at_10", 0.0), sum_new.get("ndcg_at_10", 0.0),
            sum_old.get("mrr_at_10", 0.0), sum_old.get("ndcg_at_10", 0.0)))
        if sum_new["pass_lines"]:
            lines.append("")
            lines.append("**卷判（按新库，%s）：%s**" % (
                paper["paper_id"], "过" if sum_new["all_pass"] else "**未过**"))
        if slices_on:
            seg = _slices_report_lines(slice_results(
                [r["new_r"] for r in rows]))   # 切片主体=新库（判据主体同口径）
            if seg:                  # 无切片差异 → 整段零行零空行（门控不露面）
                lines.extend(seg)
                lines.append("")
    lines.append("")
    lines.append("### 总表（各卷分别汇总，按新库）")
    lines.append("")
    lines.append("| 卷 | 题数 | 新 top-5 相关率 | 旧 top-5 相关率 | 改善/退化 | expect_miss 达标率（新） | 通过线（新） |")
    lines.append("|---|---|---|---|---|---|---|")
    for paper, rows, sum_new, sum_old in paper_summaries:
        imp = sum(1 for r in rows if r["change"].startswith("改善"))
        reg = sum(1 for r in rows if r["change"].startswith("退化"))
        lines.append("| %s | %d | %s | %s | +%d/-%d | %s | %s |" % (
            paper["paper_id"], sum_new["n"],
            _fmt_rate(sum_new["top5_n"], sum_new["n_rel"]),
            _fmt_rate(sum_old["top5_n"], sum_old["n_rel"]), imp, reg,
            _miss_rate_str(sum_new),
            "过" if sum_new["all_pass"] else ("**未过**" if sum_new["pass_lines"]
                                              else "未设线")))
    failed = [p["paper_id"] for p, _, s, _ in paper_summaries if not s["all_pass"]]
    lines.append("")
    lines.append("**总判（按新库各卷通过线）：%s**" % (
        "过" if not failed else "**未过（%s）**" % "、".join(failed)))
    lines.append("")
    lines.append("- 总费用：prompt_tokens=%d → %.6f 元（单价 %s 元/Mtok；两库复用同一批 query 向量，不翻倍）" % (
        prompt_tokens, cost_cny, cfg["price_per_mtok"]))
    lines.append("- 判读注：判定变化按单题判过与否归类（expect_miss 型按达标与否）；"
                "top1 分=该库检索 rank-1 的余弦分（非预期文档位次口径）")
    lines.extend(snapshot_lines or [])   # --snapshot 门控：两快照 diff 摘要段
    lines.append("")
    return "\n".join(lines)


def execute_paper_run(cfg, lib_path, papers, qvecs, prompt_tokens, report_path,
                      topk, mode_tag="[--yes 真跑 --questions-file]", say=print,
                      json_path=None, faith=None, answers=None,
                      snapshot_on=False, slices_on=False):
    """外部题卷模式检索+判定+报告（判定复用 judge_question，逐卷分别汇总+总表）。

    退出码：设通过线的卷有线未过 → 1；否则跑完即 0。库空抛 RuntimeError、
    向量数与题数不符抛 RuntimeError（main 捕获均退 2）。

    json_path（批A3①）/faith（批A3③）/answers（2026-09-28 答案评测通道）均可选，
    不给时行为与历史版本逐字节一致；json_path 给定 → 报告后写机读 JSON
    （mode="paper"）并追加 "[json] 已写" 单行；answers 给定 → 题级追加 answer_judge
    键、卷级 metrics 追加 answer_*/faithfulness_rate 键（md 报表零变化）。
    snapshot_on（--snapshot，D2 2026-09-28：--json 顶层追加 snapshot 键）/
    slices_on（--slices，E3 2026-09-28：papers[].slices+md 逐卷"切片"段）默认关。
    """
    recs, dim, stats = retrieve.load_library(lib_path)
    if not recs:
        raise RuntimeError("库为空：%s" % lib_path)
    questions = paper_questions(papers)
    if len(qvecs) != len(questions):
        raise RuntimeError("query 向量数 %d ≠ 题数 %d" % (len(qvecs), len(questions)))
    meta_by_id = load_meta_by_id(lib_path)
    if PIPELINE_VIEW["on"]:
        init_pipeline_view(questions, qvecs, say)
    paper_summaries, i = [], 0
    entries = []   # 批A3：[(paper_id, q, hits, r)] 运行序展平（faith/--json 共用）
    for paper in papers:
        results = []
        for q in paper["questions"]:
            hits = retrieve.search(qvecs[i], recs, topk=topk,
                                   exclude_answers=True, dim=dim)
            r = judge_question(q, hits, meta_by_id)
            if PIPELINE_VIEW["on"]:
                _attach_pipeline(r, q, meta_by_id)
            results.append(r)
            entries.append((paper["paper_id"], q, hits, r))
            i += 1
        paper_summaries.append(
            (paper, results, summarize_paper(results, paper.get("pass_lines"))))
    cost = embed_common.estimate_cost_cny(prompt_tokens, cfg["price_per_mtok"])
    block = _paper_report_block(cfg, lib_path, stats, paper_summaries,
                                prompt_tokens, cost, mode_tag, topk,
                                slices_on=slices_on)
    append_report(report_path, block)
    say(block)
    say("[报告] 已追加 → %s" % report_path)
    # ---- 批A3③ faithfulness（flag 关=零调用零新增输出；md 报表零变化）----
    faith_metrics_by_pid = {}
    if faith is not None:
        fres, fjudged, _fs = run_faithfulness(entries, faith, meta_by_id, say)
        faith_usage_line(faith, say)
        append_faith_ledger(faith, say)
        for paper in papers:
            faith_metrics_by_pid[paper["paper_id"]] = faith_paper_metrics(
                entries, fres, fjudged, paper["paper_id"])
    else:
        fres = [None] * len(entries)
    # ---- 答案评测通道（--answers；flag 关=零调用零新增输出；md 报表零变化）----
    ans_metrics_by_pid = {}
    if answers is not None:
        ares, ajudged, _ast = run_answer_judge(entries, answers, meta_by_id, say)
        answer_usage_line(answers, say)
        append_answer_ledger(answers, say)
        for paper in papers:
            ans_metrics_by_pid[paper["paper_id"]] = answer_paper_metrics(
                entries, ares, ajudged, paper["paper_id"])
    else:
        ares = [None] * len(entries)
    # ---- 批A3① --json（不给=零写盘零输出）----
    if json_path:
        pblocks = [_paper_json_block(paper, summary,
                                     faith_metrics_by_pid.get(paper["paper_id"]),
                                     ans_metrics_by_pid.get(paper["paper_id"]),
                                     slices=slice_results(results) if slices_on else None,
                                     pipeline=(pipeline_paper_metrics(results)
                                               if PIPELINE_VIEW["on"] else None))
                   for paper, results, summary in paper_summaries]
        qrows = [_question_json_row(pid, r, hits, faith_res=fr,
                                    answer_res=ar, answers_on=answers is not None)
                 for (pid, _q, hits, r), fr, ar in zip(entries, fres, ares)]
        payload = build_json_payload("paper", cfg, lib_path, stats, pblocks, qrows,
                                     topk, prompt_tokens, len(questions),
                                     snapshot_on=snapshot_on,
                                     pipeline_block=(pipeline_cert_block()
                                                     if PIPELINE_VIEW["on"] else None))
        write_json_result(json_path, payload, say)
    failed = [p["paper_id"] for p, _, s in paper_summaries if not s["all_pass"]]
    return 1 if failed else 0


def execute_paper_compare_run(cfg, new_lib_path, old_lib_path, papers, qvecs,
                              prompt_tokens, report_path, topk,
                              mode_tag="[--yes 真跑 --questions-file --compare]",
                              say=print, json_path=None, faith=None, answers=None,
                              snapshot_on=False, slices_on=False):
    """外部题卷对比模式：同卷对两库各检索一遍（qvecs 两库复用，只嵌一次）。

    判定口径与单库跑完全同源；退出码按【新库】各卷通过线定 0/1；旧 72.2% 基线
    仅内置验收卷 A 有，外部卷报告不引（不跨卷类比）。

    json_path（批A3①，mode="paper_compare"）/faith（批A3③，评审对象=新库 hits，
    新库为 lib 主口径）/answers（2026-09-28 答案评测通道，评审对象=新库 hits）
    均可选，不给时行为与历史版本逐字节一致。snapshot_on（--snapshot，D2
    2026-09-28：两快照 diff 摘要段+json 三键）/slices_on（--slices，E3：逐卷
    切片段，主体=新库）均默认关=输出与历史版本逐字节一致。
    """
    libs = {}
    for tag, path in (("new", new_lib_path), ("old", old_lib_path)):
        recs, dim, stats = retrieve.load_library(path)
        if not recs:
            raise RuntimeError("库为空：%s" % path)
        libs[tag] = (recs, dim, stats, load_meta_by_id(path))
    questions = paper_questions(papers)
    if len(qvecs) != len(questions):
        raise RuntimeError("query 向量数 %d ≠ 题数 %d" % (len(qvecs), len(questions)))
    paper_summaries, i = [], 0
    entries, olds = [], []   # 批A3：新库 (paper_id,q,hits,r) + 旧库 (rank,top1)
    for paper in papers:
        rows, results_new, results_old = [], [], []
        for q in paper["questions"]:
            row = {"id": q["id"], "category": q.get("category", ""),
                   "judge_type": q.get("judge_type", "relevance")}
            per = {}
            for tag, results in (("new", results_new), ("old", results_old)):
                recs, dim, _stats, meta_by_id = libs[tag]
                hits = retrieve.search(qvecs[i], recs, topk=topk,
                                       exclude_answers=True, dim=dim)
                r = judge_question(q, hits, meta_by_id)
                results.append(r)
                row[tag + "_rank"] = r["hit_rank"]
                row[tag + "_top1"] = hits[0]["score"] if hits else None
                row[tag + "_r"] = r
                per[tag] = (hits, r)
            row["change"] = _compare_change(row["old_r"]["pass"], row["new_r"]["pass"])
            rows.append(row)
            entries.append((paper["paper_id"], q, per["new"][0], per["new"][1]))
            olds.append((row["old_rank"], row["old_top1"]))
            i += 1
        paper_summaries.append((paper, rows,
                                summarize_paper(results_new, paper.get("pass_lines")),
                                summarize_paper(results_old, paper.get("pass_lines"))))
    cost = embed_common.estimate_cost_cny(prompt_tokens, cfg["price_per_mtok"])
    # --snapshot（D2）：两库各建全量快照出 diff 摘要（lib 块只算一次，json 复用）
    lib_blocks, snapshot_lines = {}, None
    if snapshot_on:
        lib_blocks = {"new": _lib_json_block(new_lib_path, libs["new"][2]),
                      "old": _lib_json_block(old_lib_path, libs["old"][2])}
        snapshot_lines = _snapshot_diff_lines(snapshot_diff(
            build_snapshot(cfg, lib_blocks["new"], topk=topk),
            build_snapshot(cfg, lib_blocks["old"], topk=topk)))
    block = _paper_compare_report_block(
        cfg, new_lib_path, old_lib_path, libs["new"][2], libs["old"][2],
        paper_summaries, prompt_tokens, cost, topk, mode_tag,
        snapshot_lines=snapshot_lines, slices_on=slices_on)
    append_report(report_path, block)
    say(block)
    say("[报告] 已追加 → %s" % report_path)
    # ---- 批A3③ faithfulness（评审对象=新库 hits）----
    faith_metrics_by_pid = {}
    if faith is not None:
        fres, fjudged, _fs = run_faithfulness(entries, faith, libs["new"][3], say)
        faith_usage_line(faith, say)
        append_faith_ledger(faith, say)
        for paper in papers:
            faith_metrics_by_pid[paper["paper_id"]] = faith_paper_metrics(
                entries, fres, fjudged, paper["paper_id"])
    else:
        fres = [None] * len(entries)
    # ---- 答案评测通道（--answers；评审对象=新库 hits；新库为 lib 主口径）----
    ans_metrics_by_pid = {}
    if answers is not None:
        ares, ajudged, _ast = run_answer_judge(entries, answers, libs["new"][3], say)
        answer_usage_line(answers, say)
        append_answer_ledger(answers, say)
        for paper in papers:
            ans_metrics_by_pid[paper["paper_id"]] = answer_paper_metrics(
                entries, ares, ajudged, paper["paper_id"])
    else:
        ares = [None] * len(entries)
    # ---- 批A3① --json（新库为 lib 主口径；题级追加 old_* 两键）----
    if json_path:
        pblocks = [_paper_json_block(paper, sum_new,
                                     faith_metrics_by_pid.get(paper["paper_id"]),
                                     ans_metrics_by_pid.get(paper["paper_id"]),
                                     slices=(slice_results([r["new_r"] for r in rows])
                                             if slices_on else None))
                   for paper, rows, sum_new, _sum_old in paper_summaries]
        qrows = [_question_json_row(pid, r, hits, faith_res=fr, old=old,
                                    answer_res=ar, answers_on=answers is not None)
                 for (pid, _q, hits, r), fr, old, ar in zip(entries, fres, olds, ares)]
        payload = build_json_payload("paper_compare", cfg, new_lib_path, libs["new"][2],
                                     pblocks, qrows, topk, prompt_tokens, len(questions),
                                     compare_path=old_lib_path,
                                     compare_stats=libs["old"][2],
                                     snapshot_on=snapshot_on,
                                     lib_block=lib_blocks.get("new"),
                                     compare_block=lib_blocks.get("old"))
        write_json_result(json_path, payload, say)
    failed = [p["paper_id"] for p, _, s, _ in paper_summaries if not s["all_pass"]]
    return 1 if failed else 0


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def execute_run(cfg, lib_path, qvecs, prompt_tokens, report_path, topk,
                mode_tag="[--yes 真跑]", say=print, json_path=None, faith=None,
                answers=None, snapshot_on=False, slices_on=False):
    """检索+判定+报告（向量已就绪；--self-test/单测可注入夹具向量零网络跑全流程）。

    json_path（批A3①，mode="builtin"，内置 A 卷归一为单 paper）/faith（批A3③）/
    answers（2026-09-28 答案评测通道——内置卷题目无 schema v2 字段=零评审对象，
    通道开启只打印用量零调用行）均可选，不给时行为与历史版本逐字节一致。
    snapshot_on（--snapshot，D2 2026-09-28：--json 顶层追加 snapshot 键）/
    slices_on（--slices，E3 2026-09-28：papers[].slices+md"切片"段）均默认关。
    """
    recs, dim, stats = retrieve.load_library(lib_path)
    if not recs:
        raise RuntimeError("库为空：%s" % lib_path)
    if len(qvecs) != len(QUESTIONS):
        raise RuntimeError("query 向量数 %d ≠ 题数 %d" % (len(qvecs), len(QUESTIONS)))
    meta_by_id = load_meta_by_id(lib_path)
    if PIPELINE_VIEW["on"]:
        init_pipeline_view(QUESTIONS, qvecs, say)
    results, triples = [], []
    for q, qv in zip(QUESTIONS, qvecs):
        hits = retrieve.search(qv, recs, topk=topk, exclude_answers=True, dim=dim)
        r = judge_question(q, hits, meta_by_id)
        if PIPELINE_VIEW["on"]:
            _attach_pipeline(r, q, meta_by_id)
        results.append(r)
        triples.append((q, hits, r))
    summary = summarize(results)
    cost = embed_common.estimate_cost_cny(prompt_tokens, cfg["price_per_mtok"])
    block = _report_block(cfg, lib_path, stats, results, summary,
                          prompt_tokens, cost, mode_tag, topk, slices_on=slices_on)
    append_report(report_path, block)
    say(block)
    say("[报告] 已追加 → %s" % report_path)
    # ---- 批A3③ faithfulness（flag 关=零调用零新增输出；md 报表零变化）----
    faith_metrics = None
    entries = [(BUILTIN_PAPER_ID, q, h, r) for q, h, r in triples]
    if faith is not None:
        fres, fjudged, _fs = run_faithfulness(entries, faith, meta_by_id, say)
        faith_usage_line(faith, say)
        append_faith_ledger(faith, say)
        faith_metrics = faith_paper_metrics(entries, fres, fjudged, BUILTIN_PAPER_ID)
    else:
        fres = [None] * len(entries)
    # ---- 答案评测通道（--answers；内置卷无 schema v2 题=零评审对象）----
    ans_metrics = None
    if answers is not None:
        ares, ajudged, _ast = run_answer_judge(entries, answers, meta_by_id, say)
        answer_usage_line(answers, say)
        append_answer_ledger(answers, say)
        ans_metrics = answer_paper_metrics(entries, ares, ajudged, BUILTIN_PAPER_ID)
    else:
        ares = [None] * len(entries)
    # ---- 批A3① --json（不给=零写盘零输出）----
    if json_path:
        qrows = [_question_json_row(BUILTIN_PAPER_ID, r, h, faith_res=fr,
                                    answer_res=ar, answers_on=answers is not None)
                 for (_q, h, r), fr, ar in zip(triples, fres, ares)]
        payload = build_json_payload(
            "builtin", cfg, lib_path, stats,
            [_builtin_paper_json(summary, faith_metrics, ans_metrics,
                                 slices=slice_results(results) if slices_on else None,
                                 pipeline=(pipeline_paper_metrics(results)
                                           if PIPELINE_VIEW["on"] else None))],
            qrows, topk, prompt_tokens, len(QUESTIONS), snapshot_on=snapshot_on,
            pipeline_block=(pipeline_cert_block() if PIPELINE_VIEW["on"] else None))
        write_json_result(json_path, payload, say)
    return 0 if summary["all_pass"] else 1


# ---------------------------------------------------------------------------
# 新旧库 A/B 对比模式（--compare；2026-09-18 重嵌前置件）
# ---------------------------------------------------------------------------
def _compare_change(old_pass, new_pass):
    """单题判定变化归类：改善/退化/持平（口径=单题 criterion 判过与否，两库同题同判据）。"""
    if old_pass and not new_pass:
        return "退化(过→未过)"
    if new_pass and not old_pass:
        return "改善(未过→过)"
    return "持平(过)" if new_pass else "持平(未过)"


def execute_compare_run(cfg, new_lib_path, old_lib_path, qvecs, prompt_tokens,
                        report_path, topk, mode_tag="[--yes 真跑 --compare]", say=print,
                        json_path=None, faith=None, answers=None,
                        snapshot_on=False, slices_on=False):
    """对比模式检索+判定+报告：同题卷对两库各检索一遍（qvecs 两库复用）。

    - 判定口径与单库跑完全同源（judge_question/summarize 原样复用，不另起炉灶）；
    - qvecs 由 main 统一嵌入**一次**后传入——两库共用同一批 query 向量，嵌入费与
      单库跑一致（对比不产生第二遍查询嵌入费）；
    - 逐题记录：新/旧 hit_rank、新/旧检索 top-1 分、新/旧判过、变化归类；
    - 退出码按【新库】四指标定 0/1（旧库指标仅对照参考）；库空抛 RuntimeError、
      query 向量与库维度不符抛 ValueError（main 捕获均退 2）。

    json_path（批A3①，mode="compare"：新库为 lib 主口径，题级追加 old_hit_rank/
    old_top1_cosine 两键）/faith（批A3③，评审对象=新库 hits）/answers（2026-09-28
    答案评测通道，评审对象=新库 hits）均可选，不给时行为与历史版本逐字节一致。
    snapshot_on（--snapshot，D2 2026-09-28）：两快照 diff 摘要进 md 报表"快照
    对比"段+--json 追加 snapshot/compare_snapshot/snapshot_diff 三键；slices_on
    （--slices，E3）：切片主体=新库。均默认关=输出与历史版本逐字节一致。
    """
    libs = {}
    for tag, path in (("new", new_lib_path), ("old", old_lib_path)):
        recs, dim, stats = retrieve.load_library(path)
        if not recs:
            raise RuntimeError("库为空：%s" % path)
        libs[tag] = (recs, dim, stats, load_meta_by_id(path))
    if len(qvecs) != len(QUESTIONS):
        raise RuntimeError("query 向量数 %d ≠ 题数 %d" % (len(qvecs), len(QUESTIONS)))
    rows, results_new, results_old = [], [], []
    triples, olds = [], []   # 批A3：新库 (q,hits,r) + 旧库 (rank,top1)
    for q, qv in zip(QUESTIONS, qvecs):
        row = {"id": q["id"], "category": q["category"], "criterion": q["criterion"]}
        per = {}
        for tag, results in (("new", results_new), ("old", results_old)):
            recs, dim, _stats, meta_by_id = libs[tag]
            hits = retrieve.search(qv, recs, topk=topk, exclude_answers=True, dim=dim)
            r = judge_question(q, hits, meta_by_id)
            results.append(r)
            row[tag + "_rank"] = r["hit_rank"]
            row[tag + "_top1"] = hits[0]["score"] if hits else None
            row[tag + "_pass"] = r["pass"]
            per[tag] = (hits, r)
        row["change"] = _compare_change(row["old_pass"], row["new_pass"])
        rows.append(row)
        triples.append((q, per["new"][0], per["new"][1]))
        olds.append((row["old_rank"], row["old_top1"]))
    sum_new, sum_old = summarize(results_new), summarize(results_old)
    cost = embed_common.estimate_cost_cny(prompt_tokens, cfg["price_per_mtok"])
    # --snapshot（D2）：两库各建全量快照出 diff 摘要（lib 块只算一次，json 复用）
    lib_blocks, snapshot_lines = {}, None
    if snapshot_on:
        lib_blocks = {"new": _lib_json_block(new_lib_path, libs["new"][2]),
                      "old": _lib_json_block(old_lib_path, libs["old"][2])}
        snapshot_lines = _snapshot_diff_lines(snapshot_diff(
            build_snapshot(cfg, lib_blocks["new"], topk=topk),
            build_snapshot(cfg, lib_blocks["old"], topk=topk)))
    block = _compare_report_block(cfg, new_lib_path, old_lib_path,
                                  libs["new"][2], libs["old"][2], rows,
                                  sum_new, sum_old, prompt_tokens, cost, topk,
                                  mode_tag, snapshot_lines=snapshot_lines,
                                  slices_on=slices_on)
    append_report(report_path, block)
    say(block)
    say("[报告] 已追加 → %s" % report_path)
    # ---- 批A3③ faithfulness（评审对象=新库 hits；新库为主口径）----
    faith_metrics = None
    entries = [(BUILTIN_PAPER_ID, q, h, r) for q, h, r in triples]
    if faith is not None:
        fres, fjudged, _fs = run_faithfulness(entries, faith, libs["new"][3], say)
        faith_usage_line(faith, say)
        append_faith_ledger(faith, say)
        faith_metrics = faith_paper_metrics(entries, fres, fjudged, BUILTIN_PAPER_ID)
    else:
        fres = [None] * len(entries)
    # ---- 答案评测通道（--answers；评审对象=新库 hits；内置卷=零评审对象）----
    ans_metrics = None
    if answers is not None:
        ares, ajudged, _ast = run_answer_judge(entries, answers, libs["new"][3], say)
        answer_usage_line(answers, say)
        append_answer_ledger(answers, say)
        ans_metrics = answer_paper_metrics(entries, ares, ajudged, BUILTIN_PAPER_ID)
    else:
        ares = [None] * len(entries)
    # ---- 批A3① --json（不给=零写盘零输出）----
    if json_path:
        qrows = [_question_json_row(BUILTIN_PAPER_ID, r, h, faith_res=fr, old=old,
                                    answer_res=ar, answers_on=answers is not None)
                 for (_q, h, r), fr, old, ar in zip(triples, fres, olds, ares)]
        payload = build_json_payload(
            "compare", cfg, new_lib_path, libs["new"][2],
            [_builtin_paper_json(sum_new, faith_metrics, ans_metrics,
                                 slices=slice_results(results_new) if slices_on else None)],
            qrows, topk, prompt_tokens, len(QUESTIONS),
            compare_path=old_lib_path, compare_stats=libs["old"][2],
            snapshot_on=snapshot_on,
            lib_block=lib_blocks.get("new"), compare_block=lib_blocks.get("old"))
        write_json_result(json_path, payload, say)
    return 0 if sum_new["all_pass"] else 1


def dry_run(cfg, lib_path, report_path, topk, say=print, compare_path=None,
            papers=None, questions_files=None, json_path=None, faith_on=False,
            answers_on=False, snapshot_on=False, slices_on=False,
            answers_jsonl=None, answers_external_path=None, answers_external=None):
    """默认模式：零网络零计费，只打印将做什么（不读密钥、不嵌入、不判分）。

    compare_path 给定时（--compare 对比模式）顺带预览旧库在位情况；papers 给定时
    （--questions-file 外部题卷模式）逐卷预览题数/判型/锚数；两者均默认 None，
    不给时行为与历史版本完全一致。json_path（批A3①）给定时 dry-run **不写 json**，
    只在放行命令回显里追加 --json 参数；faith_on（批A3③）/answers_on（2026-09-28
    答案评测通道）各只多打一行提示——参数缺省时输出与历史版本逐字节一致。
    snapshot_on/slices_on（2026-09-28 D2/E3）：只在放行命令回显追加对应 flag
    （不给 --json 时 --snapshot 仍生效于 --compare 文本摘要段）；缺省时输出
    与历史版本逐字节一致。answers_jsonl（2026-09-28 G3 材料持久化）：answers_on
    时多打一行落点预览（dry-run 不写 jsonl）。
    answers_external（2026-09-28 J1b 外部答案盲判模式）：给定=零检索零嵌入预览
    ——跳过库文件/嵌入费预览（本模式不读库不嵌 query），改打外部答案文件概览与
    run_sub.sh 放行命令；dry-run 零 judge 调用零计费。
    """
    say("[dry-run] 未加 --yes：零网络零计费，只打印将做什么（不读密钥文件）")
    say("[dry-run] 配置：model=%s dims=%s batch=%s 单价=%s 元/Mtok 红线=%.1f 元" % (
        cfg["model"], cfg["dims"], cfg["batch"], cfg["price_per_mtok"], cfg["red_line_cny"]))
    ext_on = answers_external is not None
    if ext_on:
        say("[dry-run] 外部答案盲判模式（--answers-external）：零检索零嵌入——不读向量库、"
            "不嵌 query，judge 只评答案文本（盲判口径：不见证据/金标锚/臂身份）；"
            "答案文本截长 %d 字（cfg 键 answer_external_text_max_chars 可覆盖，"
            "轮 1 销项①：2000→4000）" % _resolve_ext_text_max_chars(cfg))
        n_rec = sum(len(v) for v in answers_external.values())
        n_unans = sum(1 for arms in answers_external.values()
                      for t in arms.values() if t is None)
        arms_all = []
        for arms in answers_external.values():
            for a in arms:
                if a not in arms_all:
                    arms_all.append(a)
        say("[dry-run] 外部答案文件：%s → %d 份答案 / %d 题（臂：%s；未答 %d 份按错计零调用）" % (
            answers_external_path, n_rec, len(answers_external),
            "、".join(arms_all) or "-", n_unans))
    if not ext_on and os.path.exists(lib_path):
        recs, dim, stats = retrieve.load_library(lib_path)
        say("[dry-run] 库文件：%s → loaded=%s dim=%s bad_lines=%s（只读预览）" % (
            lib_path, stats["loaded"], stats["dim"], stats["bad_lines"]))
    elif not ext_on:
        say("[dry-run] 库文件：%s —— 【库未建】（真跑将报\"库未建\"退退出码 2，不空跑）" % lib_path)
    if compare_path:
        if os.path.exists(compare_path):
            _recs, _dim, cstats = retrieve.load_library(compare_path)
            say("[dry-run] 对比模式旧库：%s → loaded=%s dim=%s bad_lines=%s（真跑两库各检索一遍；"
                "查询向量化仅一次、两库复用）" % (
                    compare_path, cstats["loaded"], cstats["dim"], cstats["bad_lines"]))
        else:
            say("[dry-run] 对比模式旧库：%s —— 【缺失】（真跑将报\"库未建\"退退出码 2，不空跑）"
                % compare_path)
    questions = paper_questions(papers)
    if papers:
        for p in papers:
            qs = p["questions"]
            n_rel = sum(1 for q in qs if q["judge_type"] == "relevance")
            n_miss = len(qs) - n_rel
            n_layer = sum(1 for q in qs if q.get("expect_miss_layer"))
            n_dom = sum(1 for q in qs if q.get("expect_domain"))
            n_prim = sum(1 for q in qs for a in q["anchors"]
                         if a.get("role", "primary") == "primary")
            n_sec = sum(1 for q in qs for a in q["anchors"]
                        if a.get("role") == "secondary")
            say("[dry-run] 题卷 %s：%d 条（relevance %d / expect_miss %d；主锚 %d / "
                "次级锚 %d；预期 miss 层登记 %d；expect_domain 域判定 %d；%s）" % (
                p["paper_id"], len(qs), n_rel, n_miss, n_prim, n_sec, n_layer, n_dom,
                "设通过线" if p.get("pass_lines") else "未设通过线"))
        for p in papers:
            for q in p["questions"]:
                anchors = "；".join(
                    "%s%s[%s|loc %s]" % ("(次)" if a.get("role") == "secondary" else "",
                                         "／".join(a["expect_doc"]),
                                         a["criterion"], a["expect_locator_pattern"])
                    for a in q["anchors"])
                suffix = ""
                if q.get("expect_miss_layer"):
                    suffix += "｜预期 miss 层：" + q["expect_miss_layer"]
                if q.get("expect_domain"):
                    dspec = _norm_domain_spec(q["expect_domain"])
                    if dspec:
                        suffix += "｜expect_domain：%s[%s]" % (
                            dspec["domain"], dspec["criterion"])
                say("  %s [%s|%s|%s] %s → 预期 %s%s" % (
                    q["id"], q.get("category") or "-", q["judge_type"],
                    "+".join(sorted({a["criterion"] for a in q["anchors"]
                                     if a.get("role", "primary") == "primary"})),
                    q["query"], anchors, suffix))
    else:
        n_ret = sum(1 for q in QUESTIONS if q["retest"])
        say("[dry-run] 题卷：%d 条（监管数字 %d / 标准条款 %d / 表格值参数卡 %d；旧失手复测 %d）" % (
            len(QUESTIONS),
            sum(1 for q in QUESTIONS if q["category"] == "监管数字"),
            sum(1 for q in QUESTIONS if q["category"] == "标准条款"),
            sum(1 for q in QUESTIONS if q["category"] == "表格值/参数卡"), n_ret))
        for q in QUESTIONS:
            say("  %s [%s|%s] %s → 预期 %s（locator 锚 %s）%s" % (
                q["id"], q["category"], q["criterion"], q["query"],
                "／".join(q["expect_doc"]), q["expect_locator_pattern"],
                "｜" + q["note"] if q["note"] else ""))
    qf = "".join(" --questions-file " + f for f in (questions_files or []))
    js = (" --json " + json_path) if json_path else ""
    if ext_on:
        say("[dry-run] 将做：%d 份外部答案逐份 judge 评审（未答零调用；订阅通道配额非现金，"
            "est 仅量级参照 ≈0.002 元/题）→ 报告追加至 %s" % (
                sum(len(v) for v in answers_external.values()), report_path))
        say("[dry-run] 放行：run_sub.sh %s --yes%s --answers-external %s%s" % (
            os.path.basename(__file__), qf, answers_external_path, js))
        say("[dry-run] 材料持久化：--answers-jsonl %s —— 真跑逐题落 judge 输入/输出明细"
            "（幂等缓存，qid#arm 入键；dry-run 不写 jsonl；零 judge 调用零写）"
            % (answers_jsonl or "（缺省=logs/answer_external-<日期>.jsonl）"))
    else:
        est_tokens = int(sum(len(q["query"]) for q in questions) * 0.7)  # 中文≈0.63 token/字符，取0.7保守
        est_cny = embed_common.estimate_cost_cny(est_tokens, cfg["price_per_mtok"])
        n_batches = (len(questions) + cfg["batch"] - 1) // cfg["batch"]
        say("[dry-run] 将做：%d 条 query 分 %d 批向量化（估 ~%d token ≈ %.6f 元%s）"
            " → 逐条检索 top-%d → 判定 → 报告追加至 %s" % (
                len(questions), n_batches, est_tokens, est_cny,
                "" if papers else "；D5 口径约 0.003 元内", topk, report_path))
        d2e3 = (" --snapshot" if snapshot_on else "") + (" --slices" if slices_on else "")
        say("[dry-run] 放行：python3 %s --yes%s%s%s%s" % (
            os.path.basename(__file__), qf,
            (" --compare " + compare_path) if compare_path else "", js, d2e3))
    if json_path:
        say("[dry-run] --json 已给定：%s —— dry-run 不写机读件（真跑成功后落盘并回显 [json] 一行）"
            % json_path)
    if faith_on:
        say("[dry-run] faithfulness：--faithfulness 已给定 —— dry-run 零 judge 调用零计费；"
            "真跑须订阅通道环境注入（自带 run_ipv4）：run_sub.sh %s --yes --faithfulness%s%s"
            % (os.path.basename(__file__), qf, js))
    if answers_on:
        say("[dry-run] 答案评测：--answers 已给定 —— dry-run 零 judge 调用零计费（内置干跑）；"
            "真跑评审对象=带 answer_points（或 expected_type=abstain）的题，须订阅通道环境"
            "注入（自带 run_ipv4）：run_sub.sh %s --yes --answers%s%s"
            % (os.path.basename(__file__), qf, js))
        say("[dry-run] 材料持久化：--answers-jsonl %s —— 真跑逐题落 judge 输入/输出明细"
            "（幂等缓存；dry-run 不写 jsonl；零 judge 调用零写）"
            % (answers_jsonl or "（--answers 未给定，不生效）"))
    return 0


# ---------------------------------------------------------------------------
# --self-test：离线自检（假向量夹具；验证判定/报告/闸门，不发网络）
# ---------------------------------------------------------------------------
def _fixture_records():
    """确定性夹具库（固定 4 维向量，无随机，跨机可复现）。

    覆盖：监管（miit）×6、3GPP ×7 两域；条款块（clause 号 locator）与参数卡块
    （参数名 locator）两类出处粒度。监管块向量落 z/w 象限、3GPP 块落 x/y 象限，
    域间近正交、域内近同向，使 top-5 判定的夹具期望值稳定可推演。
    """
    def mk(i, vec, doc, ver, loc, sec, dom, src):
        return {"id": "F%02d" % i, "doc_id": doc, "version": ver, "locator": loc,
                "section": sec, "source_domain": dom, "src": src, "content": sec,
                "embedding": vec}
    return [
        mk(1, [0.0, 0.0, 1.0, 0.0], "信息产业部令第36号", "2005", "附录2 2.2.4",
           "2.2.4 通话中断率（掉话率）：掉话率≤5％", "miit",
           "建库/L3/01-电信服务规范-信息产业部令第36号-2005.md"),
        mk(2, [0.0, 0.0, 0.0, 1.0], "工信部联通信〔2023〕257号", "2023", "二、主要目标",
           "2025年底下行均值接入速率不低于220Mbps，上行不低于45Mbps", "miit",
           "建库/L3/02-信号升格专项行动.md"),
        mk(3, [0.0, 0.0, 1.0, 1.0], "2025年通信业统计公报", "2026-01", "（四）基站数",
           "5G基站为483.8万个", "miit", "建库/L3/03-2025年通信业统计公报.md"),
        mk(4, [1.0, 0.0, 0.0, 0.0], "TS 36.331", "V16.1.0", "5.5.4.4",
           "5.5.4.4 Event A3: neighbour becomes offset better than serving", "3gpp",
           "raw/3gpp/TS36.331-V16.md"),
        mk(5, [1.0, 1.0, 0.0, 0.0], "TS 36.331", "V16.1.0", "reportConfigEUTRA 参数卡",
           "a3-Offset INTEGER(0..30) 步进2，0..60dB", "3gpp", "raw/3gpp/TS36.331-V16.md"),
        mk(6, [0.0, 1.0, 0.0, 0.0], "TS 36.214", "V18.1.0", "5.1.1",
           "5.1.1 RSRP / 5.1.2 RSRQ", "3gpp", "raw/3gpp/TS36.214-V18.md"),
        mk(7, [0.1, 1.0, 0.0, 0.0], "TS 38.215", "V17.0.0", "5.1.1",
           "SS-RSRP / CSI-RSRP 定义", "3gpp", "raw/3gpp/TS38.215-V17.md"),
        mk(8, [1.0, 0.2, 0.0, 0.0], "TS 36.213", "V18.3.0", "表 5.1.1.1-2",
           "TPC 命令域映射（累积 -1/0/+1/+3 dB）", "3gpp", "raw/3gpp/TS36.213-V18.md"),
        mk(9, [1.0, 0.0, 0.0, 1.0], "TS 38.214", "V17.1.0", "5.2.2",
           "CQI 表 5.2.2.1-2/-3/-4", "3gpp", "raw/3gpp/TS38.214-V17.md"),
        mk(10, [1.0, 0.1, 0.0, 0.0], "TS 38.331", "V17.2.0", "ssb-periodicityServingCell",
            "SSB 周期枚举 sf5..sf160", "3gpp", "raw/3gpp/TS38.331-V17.md"),
        mk(11, [0.0, 0.0, 1.0, 0.1], "信息产业部令第36号", "2005", "第十三条",
            "对用户投诉自接到之日起15个工作日内答复", "miit",
            "建库/L3/01-电信服务规范-信息产业部令第36号-2005.md"),
        mk(12, [0.0, 0.0, 0.9, 0.1], "2025年通信业统计公报", "2026-01", "（二）用户规模",
            "移动电话用户总数18.27亿户", "miit", "建库/L3/03-2025年通信业统计公报.md"),
        mk(13, [0.0, 0.0, 0.1, 0.9], "工信部联通信〔2023〕257号", "2023", "二、主要目标",
            "2025年底 ≥220Mbps / ≥45Mbps", "miit", "建库/L3/02-信号升格专项行动.md"),
    ]


def _old_library_records():
    """对比模式夹具旧库（确定性，无随机）：= _fixture_records() 去 F01（S01 监管
    目标块）+ 6 条与 S01 查询向量近同向的 3GPP 干扰块——S01 在旧库 rank=7 未过、
    新库 rank=1 过，制造可判定的"改善"；其余题对夹具查询向量两库排序同构不翻转。
    """
    recs = [r for r in _fixture_records() if r["id"] != "F01"]
    for i in range(1, 7):
        recs.append({"id": "D%02d" % i, "doc_id": "TS 38.331", "version": "Rel-18 V18.10.0",
                     "locator": "5.x", "section": "对比夹具干扰块 %d" % i,
                     "source_domain": "3gpp", "src": "raw/3gpp/TS38.331-V18.md",
                     "content": "对比夹具干扰块（无正文字义）",
                     "embedding": [0.0, 0.0, 1.0, 0.01]})
    return recs


def self_test():
    """离线自检（零网络零计费）：夹具库验证 doc/locator 判定、判据分线、跨域计数、
    报告追加不覆盖、dry-run 默认零调用、库缺失退出码。全过打印 SELF-TEST PASS。"""
    failures = []

    def check(cond, msg):
        if not cond:
            failures.append(msg)

    with tempfile.TemporaryDirectory(prefix="qa-smokeacc-") as td:
        lib = os.path.join(td, "fixture.jsonl")
        recs_raw = _fixture_records()
        with open(lib, "w", encoding="utf-8") as f:
            for r in recs_raw:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        recs, dim, stats = retrieve.load_library(lib)
        meta_by_id = load_meta_by_id(lib)
        check(stats["loaded"] == len(recs_raw) and dim == 4, "夹具库加载 %s" % stats)
        vec_of = lambda rid: list(next(r for r in recs_raw if r["id"] == rid)["embedding"])
        q_by_id = {q["id"]: q for q in QUESTIONS}

        # A) S01 直检监管目标块：top1 命中 + locator 锚中 + 零跨域（监管域夹具占满 top-5）
        hits = retrieve.search(vec_of("F01"), recs, topk=10, dim=dim)
        r = judge_question(q_by_id["S01"], hits, meta_by_id)
        check(r["pass"] and r["top5_ok"] and r["hit_rank"] == 1 and r["locator_ok"]
              and r["cross_hits"] == 0, "A S01 夹具直检应过：%s" % r)
        # B) S01 题面向 3GPP 干扰向量：预期块掉出 top-5 → 未过，且 top-5 全 3GPP 计跨域
        hits = retrieve.search(vec_of("F04"), recs, topk=10, dim=dim)
        r = judge_question(q_by_id["S01"], hits, meta_by_id)
        check(not r["pass"] and not r["top5_ok"] and r["hit_rank"] > 5
              and r["cross_hits"] >= 1, "B S01 干扰向应未过且计跨域：%s" % r)
        # C) S14 分线：预期文档 top-1 但无 hysteresis 行级出处 → 未过（有 doc 无出处不过线）
        hits = retrieve.search(vec_of("F05"), recs, topk=10, dim=dim)
        r = judge_question(q_by_id["S14"], hits, meta_by_id)
        check(not r["pass"] and r["top5_ok"] and not r["locator_ok"],
              "C S14 有 doc 无行级出处应未过（分线）：%s" % r)
        # D) S13 同向量命中参数卡块（a3-Offset/reportConfigEUTRA locator）→ 过
        r = judge_question(q_by_id["S13"], hits, meta_by_id)
        check(r["pass"] and r["locator_ok"] and r["hit_rank"] == 1,
              "D S13 参数卡直检应过：%s" % r)
        # E) 题库完整性（与题卷同源的机器面校验）
        try:
            check_questions()
        except AssertionError as e:
            failures.append("E 题库完整性：%s" % e)
        # F) execute_run 全流程（夹具向量）+ 报告追加两次不覆盖
        report = os.path.join(td, "r.md")
        cfg = dict(pipeline_config.DEFAULTS)
        qvecs = [vec_of("F01")] + [vec_of("F10")] * 17
        rc = execute_run(cfg, lib, qvecs, 1234, report, 10,
                         mode_tag="[self-test 夹具]", say=lambda *a, **k: None)
        check(rc in (0, 1), "F execute_run 退出码 %s" % rc)
        with open(report, encoding="utf-8") as f:
            body1 = f.read()
        execute_run(cfg, lib, qvecs, 1234, report, 10,
                    mode_tag="[self-test 夹具]", say=lambda *a, **k: None)
        with open(report, encoding="utf-8") as f:
            body2 = f.read()
        check(all(qid in body1 for qid in q_by_id) and "四指标" in body1
              and "总费用" in body1, "F 报告应含 18 行与四指标与费用")
        check(len(body2) > len(body1) and body2.count("## 验收冒烟") == 2,
              "F 报告应追加不覆盖")
        # G) dry-run 默认零调用（嵌入与密钥函数都装炸弹）；--yes 库缺失退 2 且不触密钥
        orig_embed, orig_api = embed_common.embed_batch, embed_common.load_api_settings

        def _bomb(*a, **k):
            raise AssertionError("dry-run/库缺失路径不应触达 API 层")
        embed_common.embed_batch = _bomb
        embed_common.load_api_settings = _bomb
        try:
            rc = main(["--report-path", os.path.join(td, "dry.md"),
                       "--vectors", os.path.join(td, "nope.jsonl")])
            check(rc == 0, "G dry-run 库缺失应退 0（只警示）：%s" % rc)
            rc = main(["--yes", "--report-path", os.path.join(td, "dry.md"),
                       "--vectors", os.path.join(td, "nope.jsonl")])
            check(rc == 2, "G --yes 库缺失应退 2：%s" % rc)
        finally:
            embed_common.embed_batch = orig_embed
            embed_common.load_api_settings = orig_api

        # H) 对比模式（--compare 夹具双库）：S01 改善可判定、报告含对照表与 72.2% 基线；
        #    同库自对比全持平（同一批向量复用两库、无串库）；dry-run 带 --compare 零 API；
        #    --yes 旧库缺失退 2 且先于读密钥
        old_lib = os.path.join(td, "fixture_old.jsonl")
        with open(old_lib, "w", encoding="utf-8") as f:
            for r in _old_library_records():
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        cmp_md = os.path.join(td, "cmp.md")
        rc = execute_compare_run(cfg, lib, old_lib, qvecs, 1234, cmp_md, 10,
                                 mode_tag="[self-test 对比夹具]", say=lambda *a, **k: None)
        check(rc in (0, 1), "H 对比模式退出码 %s" % rc)
        with open(cmp_md, encoding="utf-8") as f:
            cbody = f.read()
        check("新旧库对比" in cbody and "逐题对照" in cbody and "72.2%" in cbody
              and "**改善(未过→过)**" in cbody and old_lib in cbody,
              "H 对比报告应含对照表/72.2%基线/改善标记/旧库路径")
        rc = execute_compare_run(cfg, lib, lib, qvecs, 1234,
                                 os.path.join(td, "cmp2.md"), 10,
                                 mode_tag="[self-test 对比夹具]", say=lambda *a, **k: None)
        with open(os.path.join(td, "cmp2.md"), encoding="utf-8") as f:
            cbody2 = f.read()
        check("改善(未过→过)" not in cbody2 and "退化(过→未过)" not in cbody2
              and cbody2.count("持平") >= 18, "H 同库自对比应全持平（复用无串库）")
        embed_common.embed_batch = _bomb
        embed_common.load_api_settings = _bomb
        try:
            rc = main(["--vectors", lib, "--compare", old_lib,
                       "--report-path", os.path.join(td, "cmp3.md")])
            check(rc == 0, "H 对比 dry-run 应退 0（零网络）：%s" % rc)
            rc = main(["--yes", "--vectors", lib,
                       "--compare", os.path.join(td, "nope-old.jsonl"),
                       "--report-path", os.path.join(td, "cmp3.md")])
            check(rc == 2, "H --yes --compare 旧库缺失应退 2（先于读密钥）：%s" % rc)
        finally:
            embed_common.embed_batch = orig_embed
            embed_common.load_api_settings = orig_api

        # I) 外部题卷模式（--questions-file）：加载规范化/多锚任一过/expect_miss
        #    "miss 即达标"/expect_domain 域判定/execute_paper_run 逐卷+总表报告/
        #    CLI 坏题卷退 2/dry-run 零 API
        paper = {
            "schema_version": 1, "paper_id": "自检卷", "title": "self-test 夹具卷",
            "source_md": "", "paper_note": "", "pass_lines": None,
            "questions": [
                {"id": "T01", "category": "监管数字", "query": "掉话率监管红线是多少",
                 "judge_type": "relevance",
                 "anchors": [{"expect_doc": ["信息产业部令第36号"],
                              "expect_locator_pattern": r"2\.2\.4|掉话率",
                              "criterion": "top5", "role": "primary", "domain": "监管"}]},
                {"id": "T02", "category": "参数卡", "query": "a3-Offset 取值范围",
                 "judge_type": "relevance",
                 "anchors": [{"expect_doc": ["TS 36.331"],
                              "expect_locator_pattern": r"a3-?offset|reportconfigeutra",
                              "criterion": "top10_locator", "role": "primary",
                              "domain": "3gpp"}]},
                {"id": "T03", "category": "实操", "query": "排障流程案例",
                 "judge_type": "expect_miss",
                 "anchors": [{"expect_doc": ["实操案例卡"],
                              "expect_locator_pattern": r"案例",
                              "criterion": "top10_locator", "role": "primary"}],
                 "expect_miss_layer": "实操语料＝当前库无，预期 miss 属有效预期"},
                {"id": "T04", "category": "实操", "query": "随机接入失败排障案例",
                 "judge_type": "relevance",
                 "anchors": [{"expect_doc": ["TS 36.213"],
                              "expect_locator_pattern": r"6\.1|random access",
                              "criterion": "top5", "role": "primary", "domain": "3gpp"}],
                 "expect_domain": True},
            ]}
        pfile = os.path.join(td, "paper.json")
        with open(pfile, "w", encoding="utf-8") as f:
            json.dump(paper, f, ensure_ascii=False)
        loaded = load_question_file(pfile)
        check(len(loaded) == 1 and loaded[0]["paper_id"] == "自检卷"
              and len(loaded[0]["questions"]) == 4, "I 题卷加载/规范化")
        check(loaded[0]["questions"][3]["expect_domain"]["domain"] == "合成卡"
              and loaded[0]["questions"][3]["expect_domain"]["criterion"] == "top5",
              "I expect_domain 简写应规范化为合成卡域+top5")
        pvec = [vec_of("F01"), vec_of("F05"), vec_of("F01"), vec_of("F10")]
        prc = execute_paper_run(cfg, lib, loaded, pvec, 42,
                                os.path.join(td, "paper.md"), 10,
                                mode_tag="[self-test 题卷夹具]",
                                say=lambda *a, **k: None)
        check(prc == 0, "I execute_paper_run 未设线卷应退 0（跑完即 0）：%s" % prc)
        with open(os.path.join(td, "paper.md"), encoding="utf-8") as f:
            pbody = f.read()
        check("题卷评测" in pbody and "卷：自检卷" in pbody and "总表" in pbody
              and all(t in pbody for t in ("T01", "T02", "T03", "T04"))
              and "达标(miss)" in pbody and "预期 miss 层登记：1 条" in pbody,
              "I 题卷报告应含逐卷/总表/expect_miss 标注/登记层")
        check("域判定" in pbody and "expect_domain 域判定：1 条" in pbody
              and "域miss" in pbody and "expect_domain 域命中率" in pbody,
              "I 题卷报告应含 expect_domain 域判定列/小节/汇总行")
        # T03 expect_miss 判定：库内无"实操案例卡"doc → 全锚 miss → 达标
        hits_t3 = retrieve.search(vec_of("F01"), recs, topk=10, dim=dim)
        r3 = judge_question(loaded[0]["questions"][2], hits_t3, meta_by_id)
        check(r3["pass"] and not r3["unexpected_hit"] and r3["hit_rank"] is None,
              "I expect_miss 应 miss 即达标：%s" % r3)
        # T04 expect_domain 判定（夹具库无合成卡域块 → 域 miss；spec 锚判过不受影响）
        hits_t4 = retrieve.search(vec_of("F10"), recs, topk=10, dim=dim)
        r4 = judge_question(loaded[0]["questions"][3], hits_t4, meta_by_id)
        check(r4["domain_hit"] is False and r4["domain_rank"] is None
              and r4["pass"], "I T04 夹具库应域 miss 且锚判定不受影响：%s" % r4)
        # expect_domain 命中路径：手工合成卡 meta（域标识字段形态三种逐一验）+ 深度外回显
        q4 = loaded[0]["questions"][3]
        for rank_i, m in (
                (1, {"id": "SY1", "doc_id": "TS 36.213", "layer": "合成卡"}),
                (3, {"id": "SY2", "doc_id": "TS 36.213", "corpus_type": "case_card"}),
                (5, {"id": "SY3", "doc_id": "TS 36.213", "source_domain": "synthetic"}),
                (7, {"id": "SY4", "doc_id": "TS 36.213", "chunk_type": "case_card"})):
            hits_m = [{"rank": r, "id": m["id"] if r == rank_i else "G99",
                       "score": 0.9 - r * 0.05} for r in range(1, 8)]
            mm = {"G99": {"id": "G99", "doc_id": "TS 38.331", "source_domain": "3gpp"},
                  m["id"]: m}
            rr = judge_question(q4, hits_m, mm)
            want_hit = rank_i <= 5
            check(rr["domain_hit"] is want_hit and rr["domain_rank"] == rank_i,
                  "I expect_domain %s 形态 rank%d 应 hit=%s：%s" % (
                      list(m.keys())[-1], rank_i, want_hit, rr))
        bad = os.path.join(td, "bad.json")
        with open(bad, "w", encoding="utf-8") as f:
            f.write('{"paper_id":"坏卷","questions":[{"id":"X1"}]}')
        rc = main(["--questions-file", bad,
                   "--report-path", os.path.join(td, "bad.md")])
        check(rc == 2, "I 坏题卷（缺题面）应退 2：%s" % rc)
        embed_common.embed_batch = _bomb
        embed_common.load_api_settings = _bomb
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main(["--questions-file", pfile, "--vectors", lib,
                           "--report-path", os.path.join(td, "pdry.md")])
            check(rc == 0, "I 题卷 dry-run 应退 0（零网络）：%s" % rc)
            check("--questions-file" in buf.getvalue()
                  and "自检卷" in buf.getvalue(), "I 题卷 dry-run 应预览题卷与放行命令")
        finally:
            embed_common.embed_batch = orig_embed
            embed_common.load_api_settings = orig_api

    if failures:
        print("\nSELF-TEST FAIL（%d 项）:" % len(failures), file=sys.stderr)
        for m in failures:
            print("  - " + m, file=sys.stderr)
        return 1
    print("SELF-TEST PASS（判定/分线/跨域/报告/闸门/退出码/对比/题卷/域判定 九面全过，零网络）")
    return 0


def check_questions():
    """题库完整性断言（单测与 --self-test 共用）：18 条连续编号、三类×6、复测恰 S01-S03。"""
    ids = [q["id"] for q in QUESTIONS]
    assert len(QUESTIONS) == 18, "须 18 条，得 %d" % len(QUESTIONS)
    assert ids == ["S%02d" % i for i in range(1, 19)], "编号须 S01-S18 连续：%s" % ids
    for cat, want in (("监管数字", 6), ("标准条款", 6), ("表格值/参数卡", 6)):
        got = sum(1 for q in QUESTIONS if q["category"] == cat)
        assert got == want, "%s 须 %d 条，得 %d" % (cat, want, got)
    assert [q["id"] for q in QUESTIONS if q["retest"]] == ["S01", "S02", "S03"], \
        "旧失手复测须恰为 S01/S02/S03"
    for q in QUESTIONS:
        assert q["query"] and isinstance(q["expect_doc"], list) and q["expect_doc"], \
            "%s 题面/expect_doc 非空" % q["id"]
        assert q["criterion"] in ("top5", "top10_locator"), "%s criterion 非法" % q["id"]
        re.compile(q["expect_locator_pattern"], re.IGNORECASE)  # 可编译
        assert q["domain"] in ("监管", "3gpp"), "%s domain 非法" % q["id"]
        if q["domain"] == "3gpp":
            assert q["version"].startswith("Rel-18 V18."), "%s 3GPP 版本须为已回填的 Rel-18 形态" % q["id"]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(
        description="公开源语料库一期验收冒烟 harness（D5 18 条；默认 dry-run 零 API，"
                    "--yes 放行计费；--self-test 离线自检；--questions-file 外部题卷；"
                    "详见模块 docstring）",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog="""示例：
  python3 smoke_accept.py                 # dry-run：打印计划（零网络零计费）
  python3 smoke_accept.py --yes           # 真跑（18 条约 0.003 元，报告追加 logs/）
  python3 smoke_accept.py --self-test     # 离线自检（假向量夹具）
  python3 smoke_accept.py --yes --compare 建库/vectors-backup-20260918-公开源一期/embeddings.jsonl
                                          # 新旧库 A/B 对比（查询向量只嵌一次两库复用）
  python3 smoke_accept.py --questions-file scripts/题卷/独立B.json
                                          # dry-run 外部题卷（B/C/Y 卷一键可跑）
  python3 smoke_accept.py --yes --questions-file scripts/题卷/独立C实操.json \
                                      --questions-file scripts/题卷/独立Y意译.json
                                          # 多卷连跑（逐卷汇总+总表，报告追加 logs/题卷评测.md）
  run_sub.sh smoke_accept.py --yes --questions-file 题卷/J1b卷.json \
                              --answers-external 运营/J1b盲判-202610/外部答案-轮1.jsonl
                                          # 外部答案盲判（J1b 两臂 A/B：评已有答案不生成，
                                          #   零检索零嵌入；两臂汇总+逐题配对+Δpp）
退出码：0=四线全过（题卷模式=设线的卷全过）；1=有线未过；2=库未建/前置失败
        （含题卷文件/schema 非法、外部答案文件非法/须联卷/互斥 flag）。""")
    ap.add_argument("--yes", action="store_true",
                    help="放行计费闸：真实嵌入全部 query 并跑判定（默认 dry-run 零网络）")
    ap.add_argument("--topk", type=int, default=10,
                    help="每题检索深度（默认 10；须 ≥10——参数/表值类判 top-10 线）")
    ap.add_argument("--report-path", help="报告落点（默认：内置卷 logs/验收冒烟-公开源一期.md；"
                                          "题卷模式 logs/题卷评测.md；均追加式）")
    ap.add_argument("--vectors", help="库文件路径（默认取 pipeline_config 的 out_vecs）")
    ap.add_argument("--compare", metavar="旧库路径",
                    help="对比模式：同题卷对 --vectors 待评库与旧库各检索一遍（查询向量化仅一次、"
                         "两库复用，嵌入费与单库跑一致）；输出逐题对照+新相关率 vs 旧 72.2%% 基线；"
                         "同受 --yes 计费闸约束，退出码按新库四线定")
    ap.add_argument("--questions-file", action="append", metavar="题卷json",
                    help="外部题卷 JSON（可重复给多卷；单文件亦可含 papers 数组）。给定后以题卷"
                         "替代内置验收卷 A 跑同套判定（relevance 型四指标 + expect_miss 型"
                         "\"miss 即达标\"率 + 题级 expect_domain 域判定（C 卷实操层翻型件，"
                         "域级粒度不锚具体卡），逐卷汇总+总表）；与 --vectors/--compare 正交组合；"
                         "不给则默认行为完全不变；schema 见 logs/评测harness统一-20260918.md"
                         "与 logs/C卷翻型准备-20260919.md")
    ap.add_argument("--json", metavar="路径",
                    help="机读结果 JSON 落点（批A3①，schema smoke_accept.json/v1）：卷级 "
                         "checks 六键+all_pass+pass_lines+库 md5（流式算）+行数；题级 "
                         "top1_cosine 与 gate_score 分列+score_type+top5_ids/scores+"
                         "faithfulness。md 报表与 stdout 口径零变化（仅追加 [json] 一行）；"
                         "dry-run 不写；rc=2 前置失败不写；不给则默认行为完全不变")
    ap.add_argument("--snapshot", action="store_true",
                    help="全量版本快照（2026-09-28 第 3 批 D2，默认关=输出逐字节零变化）："
                         "--json 顶层追加 snapshot 运行环境键全集——库 md5/有效行数/坏行/"
                         "维度、chunks 各源 jsonl 行数、synth prompt 模板 sha16、模型/维度/"
                         "topk/单价、三条红线值（embed/cr/synth）、harness 自身 sha16、"
                         "python 版本；--compare 模式另追加 compare_snapshot+snapshot_diff "
                         "两键，且 md 报表追加\"快照对比\"段（仅差异键——含库 md5/行数/"
                         "维度等；两快照全同则段不出现）")
    ap.add_argument("--pipeline-view", action="store_true",
                    help="管线视图双证书（2026-10-08 C 线收口批，默认关=输出逐字节"
                         "零变化）：每题另按生产键面镜像（拨键批后现役态快照）经"
                         " importlib 只读装载仓根 rag.py 跑 RagService.retrieve，"
                         "取终证据 top5 复用同一 judge_question 判卷；查询向量复用"
                         "本次运行已嵌入的内存向量（零新增 API）；--json 顶层增 "
                         "pipeline_view 块+逐题 pipeline 键+卷级 *_pipeline 指标；"
                         "判定面归 eval_gate 卷线 view 键绑定")
    ap.add_argument("--slices", action="store_true",
                    help="统计切片报告（2026-09-28 第 3 批 E3，默认关=输出逐字节零变化）："
                         "四维切片——按 domain（题级 domain，空缺回退 expect_domain 如"
                         "合成卡）、按 criterion（top5/top10_locator）、按 category、"
                         "按难度（note 含 Basic/Difficult 字样解析，均无=未标注）；各组给 "
                         "n/top5_rate/judge_pass_rate 均值（只测不判，不进通过线）；"
                         "--json papers[].slices 四键 + md 报表\"切片\"段（仅有切片差异"
                         "——该维 ≥2 组——的维度显示）")
    ap.add_argument("--faithfulness", action="store_true",
                    help="faithfulness 代理指标（批A3③，默认关=零 API 零 import 面）："
                         "top-5 证据对题面金标锚的支持度（评证据不评生成）；judge 复用批A "
                         "citation_check 形态走订阅通道（经 run_sub.sh 启动注入环境+run_ipv4）；"
                         "失败/超时/畸形逐题降级 null 不阻塞不改退出码；用量打印+登记 "
                         "生成用量.jsonl stage=smoke_faithfulness")
    ap.add_argument("--faithfulness-timeout", type=float, default=FAITH_TIMEOUT_DEFAULT,
                    metavar="秒",
                    help="faithfulness judge 单题墙钟预算（默认 %.0f 秒——本机 flash 经 "
                         "run_ipv4 实测 ~7.8s，citation_check 默认 3s 会系统性超时；"
                         "主会话 2026-09-23 核定）" % FAITH_TIMEOUT_DEFAULT)
    ap.add_argument("--faithfulness-model", default=FAITH_JUDGE_MODEL, metavar="模型",
                    help="faithfulness judge 模型（默认 %s，订阅通道授权档同 cr_model）"
                         % FAITH_JUDGE_MODEL)
    ap.add_argument("--answers", action="store_true",
                    help="生成端答案评测通道（2026-09-28 评测体系第 1 批 G1，默认关="
                         "零 API 零 import 面）：对带 answer_points（或 expected_type="
                         "abstain）的题，judge（qwen3.8-flash，enable_thinking=false，"
                         "复用 --faithfulness 调用骨架/退避/降级纪律）基于 top-5 证据"
                         "生成答案并按固定 rubric 出五维判定（faithfulness/citation/"
                         "completeness/version/abstention），每题 pass/fail+理由，卷级"
                         "汇总 faithfulness_rate；失败/超时/畸形逐题降级 null 不阻塞"
                         "不改退出码；零 key/无网络整通道跳过并注明；用量登记 生成用量."
                         "jsonl stage=answer_judge（题卷 schema v2 字段见模块 docstring）")
    ap.add_argument("--answers-timeout", type=float, default=ANSWER_TIMEOUT_DEFAULT,
                    metavar="秒",
                    help="答案评测 judge 单题墙钟预算（默认 %.0f 秒，口径同 "
                         "--faithfulness-timeout）" % ANSWER_TIMEOUT_DEFAULT)
    ap.add_argument("--answers-model", default=ANSWER_JUDGE_MODEL, metavar="模型",
                    help="答案评测 judge 模型（默认 %s，订阅通道授权档同 cr_model）"
                         % ANSWER_JUDGE_MODEL)
    ap.add_argument("--answers-jsonl", metavar="路径",
                    help="答案评测材料持久化 jsonl 落点（2026-09-28 G3 元复核升级前置，"
                         "--answers/--answers-external 时生效；--answers 缺省=建库/logs/"
                         "answer_judge-<日期>.jsonl，--answers-external 缺省=建库/logs/"
                         "answer_external-<日期>.jsonl）：逐题落 judge 输入 ctx（--answers="
                         "题面/要点/禁答/引用要求/top-5 证据文本；--answers-external=题面/"
                         "要点/禁答/引用要求/答案文本全文）与输出五维明细（answer/dims/"
                         "pass/reason），追加式逐题 flush；幂等缓存（--answers=paper/qid、"
                         "--answers-external=paper/qid#arm + messages 全文 sha16 同纹免"
                         "调用复用，null 降级行只留痕不进缓存；2026-10-24 起缓存键含判官"
                         "模型段 $<model>——不同判官同材料文件天然隔离不串档，同判官旧"
                         "缓存无损续用）；零 judge 调用零写")
    ap.add_argument("--answers-external", metavar="答案jsonl",
                    help="外部答案盲判通道（2026-09-28 J1b 开考件，默认关=零 API 零 "
                         "import 面）：评**已有外部答案**（RAG 臂/裸考臂产出的答案文本，"
                         "两臂 A/B 匿名或 bare/rag 实名）——judge 只评审不生成（评固定文本"
                         "天然可复现，生成/评审分离）；输入 JSONL 每行 {qid,arm,"
                         "answer_text}（arm 归一 A/B/bare/rag；answer_text 空=未答按错计"
                         "零调用）；judge 只见题面+answer_points/must_not/citation_req+"
                         "答案文本（盲判口径：不见证据/金标锚/臂身份），五维判定同 rubric "
                         "v3；输出题级 {qid,arm,五维,pass}+两臂汇总（逐臂 pass 率+恰两臂卷"
                         "逐题配对+Δpp）；零检索零嵌入（不读库不嵌 query）；须联 "
                         "--questions-file，与 --answers/--compare/--faithfulness 不组合；"
                         "幂等缓存（qid#arm 入键）/台账纪律同 --answers，stage="
                         "answer_judge_external 分账；--answers-jsonl/--answers-timeout/"
                         "--answers-model/--limit 复用")
    ap.add_argument("--judge-stage", metavar="字面",
                    help="外部答案盲判通道台账 stage 覆写（2026-09-28 J1b 开考增位，"
                         "缺省=answer_judge_external 与历史行为逐字节一致；J1b 轮 1 "
                         "实跑传 j1b_judge 分账——协议 §3.1/工作区 README 四节口径；"
                         "仅 --answers-external 时生效）")
    ap.add_argument("--judge-temperature", type=float, default=0, metavar="T",
                    help="judge 采样温度（2026-10-11 提升计划波1 B3 k 采样面，"
                         "--faithfulness/--answers/--answers-external 三通道通用）："
                         "缺省 0=评审确定性口径，历史行为逐字节不变；k 重复采样传 "
                         ">0 值（如 0.7）。非默认时幂等缓存键自动缀采样段，"
                         "与默认参数行互不掩没")
    ap.add_argument("--judge-seed", type=int, default=None, metavar="S",
                    help="judge 采样种子（B3 k 采样面，与 --judge-temperature 配套）："
                         "缺省不传=历史行为逐字节不变；逐样本传不同 seed（如 base+i）"
                         "可得 k 次采样方差且整体可复现。通道拒绝 seed 参数时粘性降级"
                         "不传并打行（采样失去可复现性）")
    ap.add_argument("--answers-rubric", default="v3", metavar="v3|v3.1",
                    choices=("v3", "v3.1"),
                    help="答案评测 rubric 档位（2026-10-12 v3.1 修订案，仅 --answers "
                         "通道生效）：缺省 v3=判卷提示与幂等缓存键逐字节不变（老卷"
                         "老读数零扰动）；v3.1=启用修订段（版本键 answer_rubric/v3.1-"
                         "20261012 入 jsonl 行 rubric 键）——faithfulness reason 面"
                         "编造/超证二分归因（超证仍 fail 但必标\"超证-检索缺口\"）+"
                         "completeness 只按必答要点核覆盖（引用形态归 citation/"
                         "version；abstain 题正确拒答即 pass）。与卷级标记（题卷卷对象"
                         " answer_rubric=\"v3.1\"）等效，两路任一生效。2026-10-12"
                         " 采纳后前瞻默认：新评测件建卷即标 v3.1（存量卷已钉 v3）")
    ap.add_argument("--limit", type=int, default=0, metavar="N",
                    help="judge 评审题数上限（按运行序全局计数；N≤0 或缺省=不限）。"
                         "随 --faithfulness 与 --answers/--answers-external 各自生效、"
                         "各自计数——对检索/判定/md 报告无任何影响")
    ap.add_argument("--config", help="JSON 配置文件（透传 pipeline_config）")
    ap.add_argument("--self-test", action="store_true", help="离线自检（零网络零计费）")
    args = ap.parse_args(argv)

    if args.pipeline_view:           # 双视图开态（默认关=全链零变化）
        PIPELINE_VIEW["on"] = True

    if args.answers_rubric == "v3.1":    # rubric v3.1 显式参数路（默认关=v3 零扰动）
        ANSWER_RUBRIC_V31["on"] = True

    if args.self_test:
        return self_test()

    try:
        cfg = pipeline_config.load_config(args.config)
    except (pipeline_config.ConfigError, OSError, ValueError) as e:
        print("错误：配置加载失败：%s" % e, file=sys.stderr)
        return 2
    if args.topk < 10:
        ap.error("--topk 须 ≥10（参数/表值类判 top-10 线）")
    papers = None
    if args.questions_file:
        papers = []
        try:
            for pf in args.questions_file:
                papers.extend(load_question_file(pipeline_config.resolve_path(pf)))
        except (QuestionFileError, OSError) as e:
            print("错误：题卷文件加载失败：%s" % e, file=sys.stderr)
            return 2
    lib_path = args.vectors or pipeline_config.resolve_path(cfg["out_vecs"])
    compare_path = pipeline_config.resolve_path(args.compare) if args.compare else None
    report_path = pipeline_config.resolve_path(
        args.report_path or (PAPER_REPORT_REL if papers else DEFAULT_REPORT_REL))
    # 批A3①：机读 JSON 落点（不给=历史行为逐字节不变）
    json_path = pipeline_config.resolve_path(args.json) if args.json else None
    # 答案材料持久化落点（--answers-jsonl；2026-09-28 G3 元复核升级前置）：仅 --answers
    # 时生效，缺省=日期档名（追加式；幂等缓存细节见 run_answer_judge）
    answers_jsonl_path = None
    if args.answers:
        answers_jsonl_path = pipeline_config.resolve_path(
            args.answers_jsonl or (ANSWER_JSONL_REL % time.strftime("%Y%m%d")))
    elif args.answers_external:
        answers_jsonl_path = pipeline_config.resolve_path(
            args.answers_jsonl or (ANSWER_EXTERNAL_JSONL_REL % time.strftime("%Y%m%d")))
    # 外部答案盲判通道（--answers-external；2026-09-28 J1b）：纯评审模式（零检索零
    # 嵌入）——与 --answers（两代评审通道二选一）/--compare/--faithfulness（检索依赖
    # 通道）/--snapshot/--slices（快照/切片=检索面产物）不组合；须联 --questions-file
    # （外部答案按卷题对齐）。答案文件前置校验失败 → 2（同题卷文件非法口径）。
    ext_answers_path = ext_answers = None
    if args.answers_external:
        _incompat = [f for f, on in (("--answers", args.answers),
                                     ("--compare", args.compare),
                                     ("--faithfulness", args.faithfulness),
                                     ("--snapshot", args.snapshot),
                                     ("--slices", args.slices)) if on]
        if _incompat:
            print("错误：--answers-external 与 %s 不组合（外部答案盲判=零检索零嵌入的"
                  "纯评审模式）" % "、".join(_incompat), file=sys.stderr)
            return 2
        if not papers:
            print("错误：--answers-external 须与 --questions-file 联用（外部答案按卷题对齐）",
                  file=sys.stderr)
            return 2
        ext_answers_path = pipeline_config.resolve_path(args.answers_external)
        try:
            ext_answers = load_external_answers(ext_answers_path, papers)
        except (ExternalAnswersError, OSError) as e:
            print("错误：外部答案文件加载失败：%s" % e, file=sys.stderr)
            return 2

    if not args.yes:
        return dry_run(cfg, lib_path, report_path, args.topk, compare_path=compare_path,
                       papers=papers, questions_files=args.questions_file,
                       json_path=json_path, faith_on=args.faithfulness,
                       answers_on=args.answers, snapshot_on=args.snapshot,
                       slices_on=args.slices, answers_jsonl=answers_jsonl_path,
                       answers_external_path=ext_answers_path,
                       answers_external=ext_answers)

    # 外部答案盲判模式真跑：零检索零嵌入——不核库、不读嵌入密钥、不嵌 query（判卷
    # 无需证据，嵌入费恒零）；judge 通道凭据在 build_answer_ctx 内自理（缺失 →
    # ctx.err 整通道跳过全 null，不中断不改 rc；真跑须经 run_sub.sh 启动注入环境）
    if args.answers_external:
        answers_ctx = build_answer_ctx(cfg, timeout=args.answers_timeout,
                                       limit=args.limit, model=args.answers_model,
                                       jsonl=answers_jsonl_path,
                                       stage=args.judge_stage or ANSWER_EXTERNAL_STAGE,
                                       tag=ANSWER_EXTERNAL_TAG,
                                       temperature=args.judge_temperature,
                                       seed=args.judge_seed)
        try:
            return execute_external_answers_run(cfg, papers, ext_answers_path,
                                                ext_answers, answers_ctx,
                                                report_path, json_path=json_path)
        except (RuntimeError, ValueError) as e:
            print("错误：外部答案评审失败：%s" % e, file=sys.stderr)
            return 2

    # --yes 真跑：先核库（不空跑、且在触碰密钥文件之前），再读密钥嵌入
    missing = [p for p in ((lib_path, compare_path) if compare_path else (lib_path,))
               if not os.path.exists(p)]
    if missing:
        print("错误：库未建（%s 不存在）——先完成建库嵌入，再跑验收。退出码 2，不空跑。" % (
            "、".join(missing)), file=sys.stderr)
        return 2
    if compare_path and os.path.samefile(lib_path, compare_path):
        print("警示：--compare 旧库与待评库为同一文件（%s），逐题对照将全为持平。" % lib_path,
              file=sys.stderr)
    try:
        api_settings = embed_common.load_api_settings(cfg["key_path"], cfg["embeddings_path"])
    except (FileNotFoundError, RuntimeError, ValueError) as e:
        print("错误：密钥/端点就绪失败：%s" % e, file=sys.stderr)
        return 2
    try:
        qvecs, tokens = embed_queries([q["query"] for q in paper_questions(papers)],
                                      cfg, api_settings=api_settings)
    except (RuntimeError, ValueError) as e:
        print("错误：query 向量化失败：%s" % e, file=sys.stderr)
        return 2
    # 批A3③：faith 上下文只在 --faithfulness 且 --yes 时装配（flag 关=零 import 面
    # 零环境变量读取）；凭据缺失 → ctx.err 置位，运行期 [faith] 报错行+全 null 降级，
    # 不中断检索主流程（真跑须经 run_sub.sh 启动注入订阅通道环境）
    faith_ctx = None
    if args.faithfulness:
        faith_ctx = build_faith_ctx(cfg, timeout=args.faithfulness_timeout,
                                    limit=args.limit, model=args.faithfulness_model,
                                    temperature=args.judge_temperature,
                                    seed=args.judge_seed)
    # 答案评测通道上下文（2026-09-28 G1）：只在 --answers 且 --yes 时装配（纪律同
    # faith：flag 关=零 import 面零环境变量读取；凭据缺失 → ctx.err 置位，运行期
    # [answers] 报错行+整通道跳过全题 null，不中断检索主流程不改 rc）
    answers_ctx = None
    if args.answers:
        answers_ctx = build_answer_ctx(cfg, timeout=args.answers_timeout,
                                       limit=args.limit, model=args.answers_model,
                                       jsonl=answers_jsonl_path,
                                       temperature=args.judge_temperature,
                                       seed=args.judge_seed)
    try:
        if compare_path:
            if papers:
                return execute_paper_compare_run(cfg, lib_path, compare_path, papers,
                                                 qvecs, tokens, report_path, args.topk,
                                                 json_path=json_path, faith=faith_ctx,
                                                 answers=answers_ctx,
                                                 snapshot_on=args.snapshot,
                                                 slices_on=args.slices)
            return execute_compare_run(cfg, lib_path, compare_path, qvecs, tokens,
                                       report_path, args.topk,
                                       json_path=json_path, faith=faith_ctx,
                                       answers=answers_ctx,
                                       snapshot_on=args.snapshot,
                                       slices_on=args.slices)
        if papers:
            return execute_paper_run(cfg, lib_path, papers, qvecs, tokens,
                                     report_path, args.topk,
                                     json_path=json_path, faith=faith_ctx,
                                     answers=answers_ctx,
                                     snapshot_on=args.snapshot,
                                     slices_on=args.slices)
        return execute_run(cfg, lib_path, qvecs, tokens, report_path, args.topk,
                           json_path=json_path, faith=faith_ctx, answers=answers_ctx,
                           snapshot_on=args.snapshot, slices_on=args.slices)
    except (RuntimeError, ValueError) as e:
        print("错误：检索/判定/报告失败：%s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
