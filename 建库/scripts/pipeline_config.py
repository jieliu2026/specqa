#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pipeline_config.py —— 建库嵌入管线单一配置定义（2026-09-17 工程化重构轮立档）

背景：模型/维度/批量/并发/价格/红线/密钥路径/输出路径等常量原先散在
embed_run.py / embed_run2.py / smoke_retrieval.py 三处重复定义，改价/换模型要动
多处——本模块归一为唯一定义点，改任何参数只动一处（或经配置文件/CLI 覆盖，
不动代码）。

三层覆盖关系（后者覆盖前者）：
  1. 模块内 DEFAULTS（本文件，代码默认值）
  2. JSON 配置文件（--config 指定；缺省不加载任何文件）
  3. CLI 覆盖（--set key=value，可重复）

import 零副作用：本模块不读任何文件、不建目录、不联网，可被安全 import 做单测。
密钥文件路径只是一个字符串配置项；密钥内容的解析延后到 embed_common.load_api_settings()
运行时调用。

路径约定：out_vecs/log_* 等相对路径一律相对于 BASE_DIR（= 建库/ 目录，即本
scripts/ 的上一级）；绝对路径原样使用。src_files 为切块源 jsonl 清单——2026-09-17
决策语料从零重建（源=权威公开文献，另行设计），故默认留空，由 --chunks 或配置
文件给出。

注：chunk_l1.py 系旧课件切块器，已冻结为遗留参照，不属于新管线，不受本配置管辖。
"""
import json
import os

# 建库/ 根目录（scripts/ 的上一级）；所有默认相对路径锚于此
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 单一定义点：全部管线参数默认值（JSON 兼容类型；路径为相对 BASE_DIR 的字符串）
DEFAULTS = {
    "model": "text-embedding-v4",          # 嵌入模型
    "dims": 1024,                          # 向量维度
    "batch": 10,                           # 每请求条数上限（API 批量上限 10）
    "workers": 12,                         # 并发路数（实测单请求 ~270s 排队，12 路 ≈2.7 请求/分钟 << QPM 30）
    "max_retry": 5,                        # 429/5xx 指数退避最大次数
    "price_per_mtok": 0.5,                 # 元/百万 token（保守档；batch 档 0.25 经 CLI/配置覆盖）
    "red_line_cny": 200.0,                 # 红线熔断：累计估算花费 ≥ 此值即停。2026-10-15 用户调线
                                            # 50→200（预警 160；依据=盘点后扩源窗放量，余量 ≈165 元≈38 万
                                            # 块当量；前口径 50/40 系 2026-10-05 决策 25→50 覆盖语料扩容，
                                            # 更早 25/20 系 2026-09-26 决策，历史在档），
                                            # 预警带 160.0 元（运营人工监视口径，代码无机械键）；
                                            # 授权登记=过程日志-qa-bot-产品家-20260916.md 三节 embed 红线条目，
                                            # 专项档=建库/logs/CR合并专项-20260923.md（备份 .bak-20260923-红线对齐前）
    "key_path": "~/.bailian/config.json",  # 密钥文件（含 base_url/api_key）；只在运行时解析
    "embeddings_path": "/compatible-mode/v1/embeddings",  # 拼在 base_url 后的端点路径
    "request_timeout": 600,                # 单请求超时（秒）
    "retry_max_sleep": 120,                # 指数退避单次睡眠上限（秒）
    # 输出/台账路径（相对 BASE_DIR）
    "out_vecs": "vectors/embeddings.jsonl",
    "log_usage": "logs/embed用量.jsonl",
    "log_progress": "logs/embed进度.json",
    "log_err": "logs/embed异常.json",
    "log_probe": "logs/embed单条探测.json",
    # 切块源 jsonl 清单（相对 BASE_DIR；新语料源就绪后填入，或经 --chunks 覆盖）
    "src_files": [],
    # ---- CR（Contextual Retrieval 块首上下文化）管线键（2026-09-18 立档，归 cr_contextualize.py 用）----
    # 惯例对齐 embed 侧：重试/超时参数复用上面 max_retry/retry_max_sleep/request_timeout/key_path，
    # 不另设 cr_ 前缀副本（同一百炼通道同一退避口径，改一处全局生效）。
    "cr_model": "qwen3.8-flash",        # 生成模型（过程日志三节 5 授权档：qwen3.8-flash）
    "cr_workers": 2,                    # 并发路数（贴限流保守档；qwen3.8-flash 京区动态限流）
    "cr_batch": 10,                     # 原子落盘批大小：每 cr_batch 个 chunk 结果一次性行
                                        # （写缓存+台账+进度+核红线）；单请求恒 1 chunk（生成接口无批量）
    "cr_prefix_min_tokens": 50,         # 语境前缀目标长度下限（token，Anthropic 口径，进 prompt）
    "cr_prefix_max_tokens": 100,        # 语境前缀目标长度上限（token）
    "cr_max_out_tokens": 200,           # API max_tokens 上限（给 50-100 token 目标留截断余量）
    "cr_price_in_per_mtok": 0.8,        # 生成输入价（元/百万 token；qwen3.8-flash 京区原价快照 2026-09-18）
    "cr_price_out_per_mtok": 2.7,       # 生成输出价（元/百万 token；同上，跑前以控制台当期价复核）
    "cr_red_line_cny": 200.0,           # 生成侧台账红线（过程日志三节 5：单列台账超限停手；
                                        # 2026-10-23 调线 80→200 元（预警 160；过程日志 187 号）；前口径 80/64 系
                                        # 2026-10-16 留守授权④自动加线（触 50 自动加至 80 在案；决策登记=三节94；
                                        # 更早 30→50 系 2026-10-15 决策），与 synth_red_line_cny
                                        # 同档对齐——真累计 ≈27.1 在闸内）
    "cr_chat_path": "/compatible-mode/v1/chat/completions",  # 拼在 base_url 后的生成端点路径
    "cr_skip_domains": [],              # CR 黑名单：命中 corpus_type 或 source_domain 的件不参与 CR
                                        # （原样过录进输出，不加 cr_context；默认空=全部参与，含监管件）
    # embed_run 消费侧开关（键名归 cr_ 组但归嵌入管线用，cr_contextualize.py 不读）：
    # true 时重嵌的嵌入文本=cr_context+"\n"+content（块首拼接口径，Anthropic Contextual
    # Retrieval；切块源应指向 chunks-cr/ 装配产物）。缺/空 cr_context 的块退原文嵌入并
    # 计数警告。默认 false=嵌入文本仍为 content 原文，行为与本键加入前完全一致。
    # 注意：CR 前后同 id 但嵌入文本不同（预期换库语义，id 仍为块 id）；换库重嵌须
    # 换 out_vecs/log_progress 等输出路径，否则进度幂等按同 id 跳过（embed_run 会警告）。
    "cr_prepend_context": False,
    # CR 输出/台账路径（相对 BASE_DIR）：chunks-cr/ 与原 chunks/ 分离，不覆盖原块
    "cr_out_dir": "chunks-cr",
    "cr_cache": "chunks-cr/cr结果.jsonl",   # id→cr_context 结果缓存（过程日志续跑依据，逐批追加）
    "cr_usage_log": "logs/生成用量.jsonl",  # 生成侧单列台账（过程日志三节 5 口径，红线基线从这读）
    "cr_progress": "logs/cr进度.json",      # done_ids+统计（幂等口径同 embed进度）
    "cr_err": "logs/cr异常.json",           # 失败批落档（重跑自动续做）
    # ---- 合成案例卡管线键（2026-09-18 立档，归 synth_cards.py 用；设计稿-合成案例卡 D3）----
    # 惯例对齐 CR 管线：重试/超时/密钥路径复用上面 max_retry/retry_max_sleep/request_timeout/
    # key_path 与 cr_chat_path（同一百炼生成通道，同一退避口径）；台账 synth_log_usage 与
    # cr_usage_log 同一文件（20 元单列台账，09-29 R22① 批档 cr 线 12→20 与 synth 同档），
    # stage="SYNTH" 行与 stage="CR" 行互为红线基线
    # （分账不混记：各管线读台账时排除自己的 stage 行作基线）。embed 侧不读任何 synth_* 键。
    "synth_model": "qwen3.8-flash",        # 生卡模型（过程日志三节 5 授权档；精确名以控制台为准）
    "synth_price_in_cny_per_mtok": 0.8,    # 生成输入价（元/百万 token；qwen3.8-flash 京区原价快照
                                            # 2026-09-18，同 cr 价目口径；跑前以控制台当期价复核）
    "synth_price_out_cny_per_mtok": 2.7,   # 生成输出价（元/百万 token；同上）
    "synth_red_line_cny": 200.0,           # 生成侧台账红线（过程日志三节 5：2026-10-23 调线 80→200 元
                                            # （预警 160；过程日志 187 号）；前口径 80/64 系 2026-10-16 留守授权④
                                            # 自动加线 50→80；与 CR 分账同档累加（更早 30→50 系 2026-10-15 决策），逐批核，越线停手报备）
    "synth_workers": 2,                    # 并发路数（起步 2 试探，稳后升 4；D3 批处理默认）
    "synth_cards_per_batch": 20,           # 原子落盘批大小：每 N 张卡结果一次提交（卡文件+台账+进度）
    "synth_prompt_version": "v3-注入后",   # prompt 模板版本（scripts/prompts/synth_step{1,2}_{ver}.md；
                                            # 2026-09-24 期2挂接轮 v2→v3-注入后（运营/决策单-期2-P1P4-
                                            # 20260923.md 用户批「全按默认」）：loader 按 ver 拼名直指
                                            # 成品件 synth_step{1,2}_v3-注入后.md，base 草案 v3 件不动
                                            # （--in-place 同步路径备而不用）；v3=20260923 四域起草版+
                                            # 词表定稿文本注入（P2(a) 文本替换/P3 乙案两表同权）。
                                            # 模板 sha16：step1=4721238c7148ae94（=草案值不变，P4）/
                                            # step2=e7a29ce3c7a7f9bb（注入后终版登记值，P2 报告 §一）。
                                            # 回滚=本键改回 v2（v0-v2 六件在位；备份 .bak-20260924-挂接前）；
                                            # v2=20260920 重生成轮三补丁：200-400 字带硬约束/参数表
                                            # 非空否则如实 skip/许可-义务表述纪律（卡 1 反例内嵌）；
                                            # v1=20260919 修复轮（引文防破格/裸参数名/单单位/卡型分派），
                                            # step1 v2=step1 v1 原样副本（facts 空表连坐核查结论=不涉及））
    "synth_source_manifest": "scripts/synth_manifest.json",  # D2 九源族配额清单（200 卡）
    "synth_out_cards": "chunks/合成卡.jsonl",   # 卡产物（新文件，与现行三 jsonl 分离，防自证文件级隔离）
    "synth_log_usage": "logs/生成用量.jsonl",   # 生成侧单列台账（stage="SYNTH" 行落此）
    "synth_temperature": 0.2,              # 步 2 生卡温度（D3 口径 0.2；步 1 抽事实恒 0）
    "synth_gate_audit_v2": True,           # 审计四靶点机械闸总开关（2026-09-20 校准轮，报告=建库/
                                            # logs/机械闸增强-20260920.md）：False=整体回退（v1 闸口径）
    "synth_gate_symbol": True,             # 靶点1a 比较式符号逐字回源（拦硬猜不等式）
    "synth_gate_math_token": True,         # 靶点1b 数学记号段逐字（Δ/∆/Σ 转写形回源）
    "synth_gate_polarity": True,           # 靶点1c 许可-义务极性反转（does not need 被义务化）
    "synth_gate_meaning": True,            # 靶点2 meaning 摘源双门（词干重叠，中英名词桥）
    "synth_gate_meaning_overlap_min": 0.5, # 靶点2 重叠率门（严格大于才放行；42 卡校准值）
    "synth_gate_meaning_hits_min": 4,      # 靶点2 绝对命中门（≥N 词干命中即放行，救正确全称释义）
    "synth_gate_range_set": True,          # 靶点3 取值域逐项集合比对（防截短，含"共N项"省略声明口径）
    "synth_gate_range_owner": True,        # 靶点3 姊妹闸（20260925 修闸轮，期2 19 卡外部审计 §四.1）：
                                            # 值域三点对齐——命中块与参数名同块+命中块所属 IE 与卡面
                                            # 声明一致；防"借锚张冠李戴"（卡16/18：UE 能力 RAT-Type
                                            # 枚举冒充 mobility 命令 targetRAT-Type 值域）。False=回退
                                            # 旧"任一参数块子串命中"口径（应急开关，回退须登记）
    "synth_gate_meaning_quote_sentence": True,  # 靶点2 引句证据完整句级比对（20260925 修闸轮，审计
                                            # §四.2 卡01 引句前缀截句尾缝隙）：引文命中处须句界对齐
                                            #（整句等值/完整句连跑）。False=回退旧碎片子串口径。
                                            # 存量 65 卡 meaning 零引句（20260922 校准记录），零行为差
    # ---- 期2 闸扩展包（2026-09-22 小修轮，O5 决策全采纳；设计稿-合成卡四域 §三/§七.4）----
    # 总开关 synth_gate_ext=False → 整包回退（=20260920 v2 闸口径，含库外规范号旧正则）；
    # 细分键逐条可关可配，默认值=设计稿建议档。校准硬标准：--check-cards 对存量 65 卡复跑
    # 拦下数恒为 0（新闸不得追伤已放行卡；报告=运营/期2-synth管线小修-20260922.md）。
    "synth_gate_ext": True,                # 期2 闸扩展包总开关
    "synth_gate_length_band": True,        # G0 正文长度带机械闸（审计发现 #7：越带全靠人工的闸化）
    "synth_len_band_min": 200,             # G0 下限（终审口径：拼装正文去锚点行 CJK 计数）
    "synth_len_band_max": 400,             # G0 上限
    "synth_gate_spec_ref_cjk_guard": True, # G0' 规范号正则中文邻接保护（审计发现 #6："TS 36.304的"漏放）
    "synth_gate_spec_ref_source_verbatim": True,  # G0' 配套豁免：规范号逐字见于本源节文本=忠实转述放行
                                            #（65 卡校准所需：卡 18/19 的 36.304 系源文自引；豁免面仍比旧洞紧）
    "synth_gate_confidence_downgrade": True,  # G0'' 符号缺失 clause 产卡置信强制降"中"（终审 §四-3 黄灯；
                                            # 结构性降档不罚，同靶点4殿首重排口径；--check-cards 侧只出建议不拦）
    "synth_symbol_missing_clauses": ["5.5.4.9", "5.5.4.11", "5.5.4.17"],
                                            # G0'' 符号缺失 clause 清单（36.331 事件族 markdown 化丢符号实测：
                                            # C1-1/W1-1/H2-1 裸参数名序列；清单随语料审计增补）
    "synth_gate_vendor_blacklist": True,   # A-5 厂商词黑名单闸（版权红线机械面，全字段扫，命中即拒零容忍）
    "synth_vendor_blacklist_words": ["华为", "華為", "中兴", "中興", "爱立信", "愛立信", "诺基亚",
                                     "諾基亞", "诺基亚贝尔", "大唐", "三星", "富士通", "Huawei",
                                     "HUAWEI", "ZTE", "Ericsson", "Nokia", "Samsung", "Fujitsu",
                                     "大唐移动", "中兴通讯", "华为技术"],
    "synth_gate_mml_form": True,           # A-5 MML 命令形态正则（全大写命令词+参数赋值串，如 MOD xxx:）
    "synth_mml_command_words": ["MOD", "SET", "ADD", "RMV", "LST", "DSP", "CFG", "STR", "STP", "RST"],
    "synth_gate_meaning_mode": "dual",     # 靶点2 门制：dual=现行三选一（整段逐字/带引句/词干双门）；
                                            # quote=带源引句单门（整段逐字仍放行；词干门关闭）。
                                            # 校准记录（20260922）：全局 quote 或全局 overlap_min 0.6 均追伤
                                            # 存量 65 卡（0.6 拦卡 45/50；179/188 条 meaning 走词干门）→
                                            # 收紧默认按设计稿 A-2 域特化到厂商参数域（下行键）
    "synth_gate_meaning_strict_domains": ["厂商参数"],  # quote 单门适用域清单（空表=全域）
    "synth_gate_step_entity": True,        # B-6 空洞步骤闸（轻量）：steps 每条须含 ≥1 可回源实体
    "synth_step_entity_hollow_max": 1,     # B-6 纯话术无实体步骤容忍上限（≥2 条即拒；设计稿"≥2 条即拒"）
    "synth_step_entity_domains": ["投诉处理"],  # B-6 适用域（空表=全域）
    "synth_gate_engineering_data": True,   # C-5 工参数据红线（经纬度/站名/方位角形态机械拒，运营敏感）
    "synth_engineering_data_domains": ["规划核查"],  # C-5 适用域（空表=全域）
    "synth_gate_allowed_docs": True,       # D-4 族级双文档白名单闸：卡内规范号引用 ⊆ {主文档}∪allowed_docs
                                            # 且每个被引文档在 source_chunk_ids 有对应块（双锚强制）
    "synth_source_ids_max": 3,             # source_chunk_ids 上限（单文档族维持 3，现行口径）
    "synth_source_ids_max_multi_doc": 4,   # 多文档族（族带 allowed_docs 键）上限 3→4（O5 决策）
    "synth_prior_manifests": ["scripts/synth_manifest.json"],
                                            # 跨期 claimed_params 去重基线清单（期1 manifest；与当前 manifest
                                            # 同文件自动跳过；文件缺失警告跳过不阻断）
    "synth_gate_param_mutex": True,         # 供给端机制 C 案·同锚参数序列互斥闸总开关（2026-09-26
                                            # 施工轮，设计=建库/logs/供给端机制设计-20260926.md）：占用集
                                            # 自举+计划期 settled_mutex 持久过滤+步 2 转向提示+落定期主线程
                                            # 硬闸，拦"同锚参数集全同/子集"跨批/批内冗余卡（段2 61%/TR
                                            # 47.6% 尸检同病灶根治）。False=闸关全路径零触碰（旧行为逐位
                                            # 复现，进度档不写新键）
    "synth_param_mutex_mode": "subset",     # 互斥模式：subset=全同或子集皆拦（默认，两轮审计 35 例冗余
                                            # 参数关系校准面）；equal=仅拦全同（过拦退档旋钮，启用须登记）
    "synth_param_mutex_baselines": ["chunks/合成卡.jsonl"],
                                            # 占用集自举基线卡件（相对 BASE_DIR，跨批占用面，只读；与
                                            # synth_out_cards 同文件自动去重；缺失警告跳过不阻断——云端
                                            # 镜像文件集差异容忍，synth_prior_manifests 先例）
    # ---- 版本溯源卡闸包（2026-09-30 溯源卡物料化批立档；设计稿=建库/work/并库预备-20260929/
    # 03-溯源卡卡面设计-20260929.md §3.4 五闸 G-V1..G-V5 + §5.2 扩展点 4）----
    # 只对 card_type="版本溯源卡" 生效（存量案例卡/参数核查单卡路径零触碰——校准硬标准
    # =--check-cards 对存量 189 卡拦下数与改前逐位一致）。总开关 False=溯源卡退化为
    # 仅 schema 校验（G-V 闸面全关，应急回退须登记）。细分键逐条可关。
    "synth_gate_version": True,             # G-V 版本断言闸包总开关（版本溯源卡专属）
    "synth_gate_version_quote_verbatim": True,   # G-V1 断言逐字闸：release_assertion_quotes 每条
                                            # 逐字命中断言行标题+introduced_release 版本号数字
                                            # 在断言行数字集内（复用步 3 数值回源闸哲学）
    "synth_gate_version_word_boundary": True,    # G-V2 旁证词界闸：corroboration 参数名按 token
                                            # 词界规则命中特性（禁裸子串；Seconds/secondary/
                                            # segmentNumber/ChOccupancy/MeasCondition 五型词形
                                            # 陷阱防线）+最早 -rNN 后缀≠引入版本号即拒（分段卡
                                            # 按声明段集合核）+WI 基线行优先细则（断言行主版本
                                            # 族不一致 loud 拒——38.133 DAPS 测试面 v17.0.0 反例）
    "synth_gate_version_polarity": True,     # G-V3 极性闸：断言/定义引文命中处回看 ≤4 词不得有
                                            # 否定词（not/no/without/never…；36.133 3.6.7
                                            # "not supported in Rel-17" 陷阱防线）
    "synth_gate_version_quote_complete": True,  # G-V4 引句完整闸：断言引文=CH 行标题整行字段级
                                            # 完整（截尾即拒）；特性定义引文句界对齐（复用
                                            # synth_gate_meaning_quote_sentence 的句级比对实现）
    "synth_gate_version_source_whitelist": True,  # G-V5 断言源白名单闸：版本断言只准出自族
                                            # assertion_ids 断言块（source_chunk_ids[0]=断言块
                                            # 殿首结构保证+逐条 source 白名单核）；定义引文只准
                                            # 出自库内正文锚块（禁引库外/记忆，D2 防自证同哲学）
    "synth_len_band_min_suyuan": 150,        # 溯源卡 G0 长度带下限（设计稿 §3.2：卡型阈值另立，
                                            # 溯源卡信息密度低于案例卡，下限 200→150 放宽）
    "synth_len_band_max_suyuan": 400,        # 溯源卡 G0 长度带上限
    "synth_fails_path": "logs/合成卡失败.json",
                                            # 失败/弃卡清单落档路径（2026-09-26 供给端机制轮配套，任务 D
                                            # 逐域独立失败档）：默认=原 FAILS_REL 常量同路径（零行为差）；
                                            # 分域跑法 --set 本键=logs/合成卡失败-段2.json 等逐域分档
                                            # （段1/段2/TR/期1/期2 互不覆写——扩量执行-20260925 工程债
                                            # "失败档逐域覆写致逐槽拒因史不可考"销项）
    "synth_wordlist_complaint": "../运营/期2-词表草案-20260922.md",
                                            # O11 词表挂接（2026-09-24 期2挂接轮，决策单 P2/P4 ②）：
                                            # 投诉话术词表定稿件（四类×5=20 条）；非空且文件存在则 sha256
                                            # 前 16 位入台账行（wordlist_sha_complaint=36a2c97da45de9c3）。
                                            # 相对路径锚 BASE_DIR（=建库/）——注意仓库根相对形「运营/…」经
                                            # resolve_path 会落 建库/运营/（不存在→sha 静默不附字段），故
                                            # 用 ../运营/ 形态（云端 /opt/qa-bot 同样解析，可移植）
    "synth_wordlist_param_scenario": "../运营/期2-词表草案-20260922.md",
                                            # O11 词表挂接（同上）：参数场景词表（四语境×LTE/NR=8 条，
                                            # P3 乙案两表同权）；定稿为单文件含两表 → 两键同路径，
                                            # 台账 wordlist_sha_param_scenario 与 complaint 同值
    # 内容哈希稳定 id（chunk_id.py 用）：参哈希字段清单与截短长度；字段取值见 chunk_id.py 注释
    "id_fields": ["layer", "src", "section", "section_seq", "content"],
    "id_len": 16,
    # 增量 diff 的定位键字段（判断"同位改文"用；速查行级等特殊语料建议加 line_no）
    "locator_fields": ["layer", "src", "section", "section_seq"],
    # ---- 冒烟判卷通道键（2026-09-28 J1b 轮 1 销项①立档，归 smoke_accept.py 用）----
    "answer_external_text_max_chars": 4000,
                                            # 外部答案盲判（--answers-external）judge 输入的
                                            # 答案文本截长（字）。2026-09-28 轮 1 销项：2000→4000
                                            # （轮 1 RAG 6 份/裸考 9 份超限被截，参-P14 型 3012
                                            # 字截后缺结论半——运营/J1b盲判-202610/键回填修复-
                                            # 20260928.md §五"截断类"）；smoke_accept.
                                            # ANSWER_EXTERNAL_TEXT_MAX_CHARS 同值兜底，
                                            # 本 cfg 键可覆盖（坏值/非正数回常量）
}

# 允许 CLI --set 覆盖的键 = DEFAULTS 全集（防拼错键静默失效）
_SETTABLE = set(DEFAULTS)

# 类型表（CLI 字符串转型用；int/float/str/list 四类）
_TYPES = {
    "dims": int, "batch": int, "workers": int, "max_retry": int,
    "price_per_mtok": float, "red_line_cny": float, "request_timeout": (int, float),
    "retry_max_sleep": (int, float), "id_len": int,
    "cr_workers": int, "cr_batch": int, "cr_prefix_min_tokens": int,
    "cr_prefix_max_tokens": int, "cr_max_out_tokens": int,
    "cr_price_in_per_mtok": float, "cr_price_out_per_mtok": float,
    "cr_red_line_cny": float,
    "synth_workers": int, "synth_cards_per_batch": int,
    "synth_price_in_cny_per_mtok": float, "synth_price_out_cny_per_mtok": float,
    "synth_red_line_cny": float, "synth_temperature": float,
    "synth_gate_meaning_overlap_min": float, "synth_gate_meaning_hits_min": int,
    "synth_len_band_min": int, "synth_len_band_max": int,
    "synth_step_entity_hollow_max": int,
    "synth_source_ids_max": int, "synth_source_ids_max_multi_doc": int,
    "synth_len_band_min_suyuan": int, "synth_len_band_max_suyuan": int,
    "answer_external_text_max_chars": int,
}


def resolve_path(p):
    """相对路径 → BASE_DIR 下绝对路径；绝对路径与 ~ 展开1原样处理。"""
    p = os.path.expanduser(p)
    if os.path.isabs(p):
        return p
    return os.path.join(BASE_DIR, p)


class ConfigError(ValueError):
    """配置非法（未知键/类型不符/取值越界）。"""


def _coerce(key, value):
    """按 DEFAULTS 值类型转 coerce CLI 字符串值；list 型接受逗号分隔或 JSON 数组。"""
    default = DEFAULTS[key]
    if isinstance(default, bool):
        if isinstance(value, str):
            v = value.strip().lower()
            if v not in ("true", "false", "1", "0"):
                raise ConfigError("%s 须为布尔（true/false）" % key)
            return v in ("true", "1")
        return bool(value)
    if isinstance(default, int) and not isinstance(default, bool):
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                raise ConfigError("%s 须为整数，得到 %r" % (key, value))
        if isinstance(value, float) and not value.is_integer():
            raise ConfigError("%s 须为整数" % key)
        return int(value)
    if isinstance(default, float):
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                raise ConfigError("%s 须为数值，得到 %r" % (key, value))
        return float(value)
    if isinstance(default, list):
        if isinstance(value, str):
            s = value.strip()
            if s.startswith("["):
                try:
                    return [str(x).strip() for x in json.loads(s)]
                except json.JSONDecodeError:
                    raise ConfigError("%s 须为逗号分隔字段清单或 JSON 数组" % key)
            return [x.strip() for x in s.split(",") if x.strip()]
        return [str(x) for x in value]
    return str(value)


def validate(d):
    """校验合并后的配置字典；非法抛 ConfigError。返回同一字典（便于链式）。"""
    for k, v in d.items():
        if k not in _SETTABLE:
            raise ConfigError("未知配置键 %r（可配置键：%s）" % (k, ", ".join(sorted(_SETTABLE))))
    if d["model"] != str(d["model"]) or not d["model"]:
        raise ConfigError("model 须为非空字符串")
    if d["dims"] <= 0:
        raise ConfigError("dims 须为正整数")
    if not 1 <= d["batch"] <= 10:
        raise ConfigError("batch 须在 1..10（API 批量上限 10）")
    if d["workers"] <= 0:
        raise ConfigError("workers 须为正整数")
    if d["max_retry"] < 0:
        raise ConfigError("max_retry 须为非负整数")
    if d["price_per_mtok"] < 0:
        raise ConfigError("price_per_mtok 须为非负数")
    if d["red_line_cny"] <= 0:
        raise ConfigError("red_line_cny 须为正数")
    if not 8 <= d["id_len"] <= 64:
        raise ConfigError("id_len 须在 8..64（sha256 十六进制 64 位内截短）")
    if not d["id_fields"]:
        raise ConfigError("id_fields 不可为空（至少含 content 才能保证内容敏感性）")
    if "content" not in d["id_fields"]:
        raise ConfigError("id_fields 须包含 content（否则改文不变 id，增量 diff 失真）")
    if not d["locator_fields"]:
        raise ConfigError("locator_fields 不可为空")
    # ---- CR 管线键校验（cr_contextualize.py 用；越界值在此拦下，防跑到一半才炸）----
    if d["cr_model"] != str(d["cr_model"]) or not d["cr_model"]:
        raise ConfigError("cr_model 须为非空字符串")
    if d["cr_workers"] <= 0:
        raise ConfigError("cr_workers 须为正整数")
    if not 1 <= d["cr_batch"] <= 1000:
        raise ConfigError("cr_batch 须在 1..1000（原子落盘批大小）")
    if not 10 <= d["cr_prefix_min_tokens"] <= 500:
        raise ConfigError("cr_prefix_min_tokens 须在 10..500")
    if not 10 <= d["cr_prefix_max_tokens"] <= 500:
        raise ConfigError("cr_prefix_max_tokens 须在 10..500")
    if d["cr_prefix_min_tokens"] > d["cr_prefix_max_tokens"]:
        raise ConfigError("cr_prefix_min_tokens 不得大于 cr_prefix_max_tokens")
    if d["cr_max_out_tokens"] < d["cr_prefix_max_tokens"]:
        raise ConfigError("cr_max_out_tokens 不得小于 cr_prefix_max_tokens（否则正常输出会被截断误判）")
    if d["cr_price_in_per_mtok"] < 0 or d["cr_price_out_per_mtok"] < 0:
        raise ConfigError("cr 价目须为非负数")
    if d["cr_red_line_cny"] <= 0:
        raise ConfigError("cr_red_line_cny 须为正数")
    if not d["cr_out_dir"] or not d["cr_chat_path"].startswith("/"):
        raise ConfigError("cr_out_dir 须非空且 cr_chat_path 须为以 / 起的端点路径")
    if not isinstance(d["cr_prepend_context"], bool):
        # 文件层不经 _coerce（CLI 层已转布尔），在此拦非布尔值（如 JSON 里写字符串/数字）
        raise ConfigError("cr_prepend_context 须为布尔（true/false）")
    # ---- 合成案例卡管线键校验（synth_cards.py 用；越界值在此拦下，防跑到一半才炸）----
    if d["synth_model"] != str(d["synth_model"]) or not d["synth_model"]:
        raise ConfigError("synth_model 须为非空字符串")
    if d["synth_price_in_cny_per_mtok"] < 0 or d["synth_price_out_cny_per_mtok"] < 0:
        raise ConfigError("synth 价目须为非负数")
    if d["synth_red_line_cny"] <= 0:
        raise ConfigError("synth_red_line_cny 须为正数")
    if d["synth_workers"] <= 0:
        raise ConfigError("synth_workers 须为正整数")
    if not 1 <= d["synth_cards_per_batch"] <= 1000:
        raise ConfigError("synth_cards_per_batch 须在 1..1000（原子落盘批大小）")
    if d["synth_prompt_version"] != str(d["synth_prompt_version"]) or not d["synth_prompt_version"]:
        raise ConfigError("synth_prompt_version 须为非空字符串（如 v0）")
    for k in ("synth_source_manifest", "synth_out_cards", "synth_log_usage"):
        if d[k] != str(d[k]) or not d[k]:
            raise ConfigError("%s 须为非空路径字符串" % k)
    if not 0 <= d["synth_temperature"] <= 2:
        raise ConfigError("synth_temperature 须在 0..2（生卡温度）")
    if not isinstance(d["synth_gate_audit_v2"], bool):
        # 文件层不经 _coerce（CLI 层已转布尔），在此拦非布尔值（如 JSON 里写字符串/数字）
        raise ConfigError("synth_gate_audit_v2 须为布尔（true/false）")
    for k in ("synth_gate_symbol", "synth_gate_math_token", "synth_gate_polarity",
              "synth_gate_meaning", "synth_gate_range_set",
              "synth_gate_range_owner", "synth_gate_meaning_quote_sentence"):
        if not isinstance(d[k], bool):
            raise ConfigError("%s 须为布尔（true/false）" % k)
    if not 0 <= d["synth_gate_meaning_overlap_min"] <= 1:
        raise ConfigError("synth_gate_meaning_overlap_min 须在 0..1（词干重叠率门）")
    if not 1 <= d["synth_gate_meaning_hits_min"] <= 50:
        raise ConfigError("synth_gate_meaning_hits_min 须在 1..50（词干绝对命中门）")
    # ---- 期2 闸扩展包键校验（20260922 小修轮，O5 决策；越界值在此拦下）----
    for k in ("synth_gate_ext", "synth_gate_length_band", "synth_gate_spec_ref_cjk_guard",
              "synth_gate_spec_ref_source_verbatim", "synth_gate_confidence_downgrade",
              "synth_gate_vendor_blacklist", "synth_gate_mml_form", "synth_gate_step_entity",
              "synth_gate_engineering_data", "synth_gate_allowed_docs"):
        if not isinstance(d[k], bool):
            raise ConfigError("%s 须为布尔（true/false）" % k)
    if not 50 <= d["synth_len_band_min"] <= d["synth_len_band_max"] <= 2000:
        raise ConfigError("synth_len_band_min/max 须满足 50 ≤ min ≤ max ≤ 2000（G0 长度带）")
    if d["synth_gate_meaning_mode"] not in ("dual", "quote"):
        raise ConfigError("synth_gate_meaning_mode 须为 dual（现行三选一）或 quote（带源引句单门）")
    for k in ("synth_symbol_missing_clauses", "synth_vendor_blacklist_words",
              "synth_mml_command_words", "synth_gate_meaning_strict_domains",
              "synth_step_entity_domains", "synth_engineering_data_domains",
              "synth_prior_manifests", "synth_param_mutex_baselines"):
        v = d[k]
        if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
            raise ConfigError("%s 须为字符串数组" % k)
    if not d["synth_vendor_blacklist_words"]:
        raise ConfigError("synth_vendor_blacklist_words 不可为空（A-5 版权红线词表；关闸走 synth_gate_vendor_blacklist=false）")
    if not d["synth_mml_command_words"]:
        raise ConfigError("synth_mml_command_words 不可为空（关闸走 synth_gate_mml_form=false）")
    if not 0 <= d["synth_step_entity_hollow_max"] <= 5:
        raise ConfigError("synth_step_entity_hollow_max 须在 0..5（B-6 空洞步骤容忍上限）")
    if not 1 <= d["synth_source_ids_max"] <= 10:
        raise ConfigError("synth_source_ids_max 须在 1..10")
    if not d["synth_source_ids_max"] <= d["synth_source_ids_max_multi_doc"] <= 12:
        raise ConfigError("synth_source_ids_max_multi_doc 须 ≥ synth_source_ids_max 且 ≤ 12（D-4 多文档放宽）")
    for k in ("synth_gate_meaning_mode", "synth_wordlist_complaint", "synth_wordlist_param_scenario"):
        if not isinstance(d[k], str):
            raise ConfigError("%s 须为字符串" % k)
    # ---- 版本溯源卡闸包键校验（2026-09-30 溯源卡物料化批；越界值在此拦下）----
    for k in ("synth_gate_version", "synth_gate_version_quote_verbatim",
              "synth_gate_version_word_boundary", "synth_gate_version_polarity",
              "synth_gate_version_quote_complete", "synth_gate_version_source_whitelist"):
        if not isinstance(d[k], bool):
            raise ConfigError("%s 须为布尔（true/false）" % k)
    if not 50 <= d["synth_len_band_min_suyuan"] <= d["synth_len_band_max_suyuan"] <= 2000:
        raise ConfigError("synth_len_band_min_suyuan/max_suyuan 须满足 50 ≤ min ≤ max ≤ 2000"
                          "（溯源卡 G0 长度带，设计稿 §3.2 卡型阈值另立口径）")
    # ---- 供给端机制 C 案键校验（2026-09-26 施工轮；越界值在此拦下）----
    if not isinstance(d["synth_gate_param_mutex"], bool):
        raise ConfigError("synth_gate_param_mutex 须为布尔（true/false）")
    if d["synth_param_mutex_mode"] not in ("subset", "equal"):
        raise ConfigError("synth_param_mutex_mode 须为 subset（全同/子集皆拦）或 equal（仅拦全同）")
    if d["synth_fails_path"] != str(d["synth_fails_path"]) or not d["synth_fails_path"]:
        raise ConfigError("synth_fails_path 须为非空路径字符串")
    # ---- 冒烟判卷通道键校验（smoke_accept.py 外部答案盲判用；越界值在此拦下）----
    if d["answer_external_text_max_chars"] <= 0:
        raise ConfigError("answer_external_text_max_chars 须为正整数（judge 输入答案文本截长）")
    return d


def load_config(path=None, overrides=None):
    """合并三层配置 → 校验 → 返回最终配置字典（新字典，不含路径解析；调用方按需 resolve_path）。

    path      —— JSON 配置文件路径（None=只用默认值；文件不存在直接报错，防静默用错基线）
    overrides —— {key: value} 覆盖层（通常是 CLI --set 解析结果；值可为字符串，按类型转）
    """
    d = dict(DEFAULTS)
    if path is not None:
        with open(resolve_path(path), encoding="utf-8") as f:
            file_cfg = json.load(f)
        if not isinstance(file_cfg, dict):
            raise ConfigError("配置文件 %s 顶层须为对象" % path)
        d.update(file_cfg)
    if overrides:
        for k, v in overrides.items():
            d[k] = _coerce(k, v)
    return validate(d)


def parse_set_args(pairs):
    """把 CLI --set key=value 参数对列表解析为 {key: str值}（转型延到 load_config 统一做）。"""
    out = {}
    for item in pairs:
        if "=" not in item:
            raise ConfigError("--set 须为 key=value 形式，得到 %r" % item)
        k, v = item.split("=", 1)
        k = k.strip()
        if k not in _SETTABLE:
            raise ConfigError("未知配置键 %r（可配置键：%s）" % (k, ", ".join(sorted(_SETTABLE))))
        out[k] = v
    return out


def dump_template():
    """输出可直接编辑使用的 JSON 配置模板（含注释性键名说明见 DEFAULTS）。"""
    return json.dumps(DEFAULTS, ensure_ascii=False, indent=2)


if __name__ == "__main__":  # python3 pipeline_config.py → 打印模板（重定向即为配置文件）
    print(dump_template())
