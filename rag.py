#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rag.py —— qa-bot 检索增强问答（RAG）最小骨架。

设计基线（2026-09-17，RAG 接入骨架任务）：
- 向量库 建库/vectors/embeddings.jsonl 由并行建库代理在飞产出（约 2,000-2,500
  chunk、1024 维），本模块只读、按行容错加载；文件不存在=空库→调用方退裸答。
- 库文件每行 = chunk 元数据 + embedding（新库规范：元数据至少含
  id/content/doc_id/version/locator；多余字段容忍不透传）。
- 检索为纯标准库余弦（math.sumprod 点积），全量打分，tie-break 按库内行序。
- 查询向量化走百炼 OpenAI 兼容 embeddings 端点（单条批）；端点与 key：
  环境变量 BAILIAN_EMBED_BASE_URL/BAILIAN_EMBED_API_KEY 优先，否则运行时读
  ~/.bailian/config.json 的 base_url/api_key。key 绝不回显、绝不落日志。
- 一切失败兜底到 None（retrieve 返回 None=退裸答），绝不向上抛。
- 2026-09-18 增两路词法增强（均默认关=现状不变，零新增 API）：
  lexical_boost=余弦候选内词法重排；hybrid_bm25=BM25 独立通道并路混合
  （分词中文 2-gram+英文/数字段降 case，RRF/加权和融合，详见各段注释；
  二者同源词法信号，建议二选一，同开时 hybrid 优先）。
- 2026-09-18 再增 multi-query 查询改写（mq_* 键，默认关=零 API 零调用）：
  检索前用 qwen3.8-flash 生成 1-2 条查询变体（第一条英文翻译，治"中文意译
  对英文语料块"失分），原查询+变体各走现有检索通道后多路 RRF 融合截 topk；
  超时/生成失败一律优雅退单条原查询（零恶化），实现在 multiquery.py，
  开关矩阵与费用/延迟口径见下方 mq 段注释。
- 2026-09-21 增分数阈值闸门（score_threshold 键，默认 0.40 开）：retrieve
  得 hits 后读证据集内最大余弦原始分（纯余弦态=top1，见 gate_cosine 注释），
  低于阈值→返回 LowScoreResult（不注入证据、不下发 sources，服务端先发
  off_topic 事件再照常裸答）。阈值只挂余弦原始分，RRF/weighted 融合分与
  BM25 分绝不作载体（量级断档，依据见
  运营/优化提升-20260921/阈值分析-20260921.md）。
- 2026-09-26 增 faiss IndexFlatIP 加速件（faiss_enabled 键，默认关=现状
  逐字节不变、零新增 API）：true 时 _load 装载后以已归一化 float32 向量建
  IndexFlatIP（无训练零近似）缓存于 RagService，_search_one 各余弦通道
  （纯余弦/lexical 候选/hybrid 余弦路）改走 faiss，hit 形态不变，查询归一化
  仍 float64 同口径（仅入 faiss 前转 float32）；faiss 导入失败/建索引异常/
  检索异常一律 [rag-faiss] degrade 退纯余弦全量扫（纯加速件纪律，检索语义
  绝不变）。对拍依据：建库/logs/faiss对拍-20260926.md（60/60 排序逐位一致，
  max|Δscore|=1.7e-07）；施工报告：建库/logs/faiss接入施工-20260926.md。
- 2026-09-28 增 embedding 月度预算闸（embed_monthly_budget_enabled 键，
  默认关=现状逐字节不变、零新增 API）：true 时每次嵌入调用前查
  建库/logs/embed用量.jsonl 当月切片累计 ×0.5 元/百万 tok——过预警线
  （embed_monthly_budget_cny，默认 40）打 [rag-budget] warn 日志照常嵌入；
  过硬顶（embed_monthly_cap_cny，默认 50）拒绝嵌入退纯裸答（对齐红线
  50/预警 40 口径，过程日志三节 36① 的 2026-10-05 调线；2026-10-14 拨键批
  常量/注释/测试三面同步，前口径 25/20 系 09-26 调线）。台账 ts 无日期：按带日期
  锚行+时间回跳>2h 步进日重建月度归属（无锚=全归当月，保守口径）；
  台账只记建库管线侧用量，服务端查询嵌入不落台账（口径差在档）。
  施工报告：建库/logs/token月限tokenizer施工-20260928.md。
- 2026-09-28 S1 负控治理（选项一，甲/乙/丙三层落地；方案与离线验证见
  运营/S1负控治理方案-20260928.md、运营/S1治理离线验证结果-20260928.md）：
  乙=clause_family_rerank（同款族父条让位+限定词/主体词负项重排，order-only
  只重排 top-k 内部次序不改成员、挂 gate_cosine 闸前，键 clause_family_rerank
  默认开=选项一决策生效，config 置 false 即回滚旧行为）；
  丙=覆盖闸（题面含库外域安全词形而证据集全部块文本不含该词 → 返回
  CoverageMissResult，串联在 0.40 低分闸之后不替代，键 cover_gate_enabled
  默认开，词表 cover_gate_vocab 可覆盖——裸词"5G"禁入表：TS 38 语料证据文本
  不含"5G"字面，入表即误拦域内题，见离线验证档域内误伤节对照计数）。
  判卷侧甲（父-子同文豁免）不落本件，归 建库/scripts/smoke_accept.py。
  施工报告：建库/logs/S1治理实施-20260928.md。
- 2026-09-29 P0 检索层去挤占（四件套，全部默认关=现状逐字节不变、零新增 API；
  立案=运营/扩库靶子清单-20260928.md P0 行，施工报告=建库/logs/P0去挤占实施-
  20260929.md）：
  ① doc 配额（doc_quota_*，S1 乙路径的"扩展为成员级"形态）——top-k 组装时同一
    doc_id 席位数上限（默认 2），超限块让位、候选池深处补位；与乙的 order-only
    不同，本机制**改成员**，须配深候选池（decrowd_candidates）才有补位面；
  ② 38.133 表降权（table_downweight_*）——对命中降权规则的块（默认=doc_id 含
    "38.133" 且 locator 以 "Annex" 起的表格洪流块，18,368 块占库 35%）把通道
    排序分乘降权系数（默认 0.85）；余弦原始分另存 hit["cosine"]，gate_cosine
    读原始分——0.40 闸分零侵蚀（同乙的薄余量纪律）；
  ③ 制式信号压制（spec_suppress_*）——题面含明确制式信号（NR/5G/38.x 或
    LTE/E-UTRA/4G/36.x，词表=SPEC_SUPPRESS_BUILTIN_RULES 可配置覆盖）时，对
    异制式文档块（如 NR 问句下的 TS 36./TR 36. 块）乘压制系数（默认 0.85）；
    双侧信号同时在场（跨制式题）→ 歧义保护，一律不压制；词表维护纪律与丙层
    cover_gate_vocab 同机制：扩改须决策、与库态联动（如附录7 卫星条款/NTN
    语料未来入库须复核异制式判定词），禁自动生效；
  ④ 检索快照落盘（retrieval_snapshot_dir，默认 null=关）——retrieve() 每次
    调用追加一行 JSONL（查询文本+查询向量+通道 hits+闸态），给排序实验/归因
    补证据层（扩库靶子清单 §五"排序实验前置"）；写失败只 warn 一次绝不影响
    检索。快照文件含题面原文，属本地诊断件，生产默认不开。
  ①②③ 统称 decrowd 段：任一开启时 _search_one 各通道改用深候选池
  （decrowd_candidates，默认 20）出候选，按"降权/压制重打分 → 重排 → doc 配额
  选席 → 截 topk"组装；全关时各通道走原路径（与既往逐字节一致）。
- 2026-09-29 期 1 路由分类器挂接（route_* 七键，默认关=现状逐字节不变、零新增
  API；立案=运营/设计稿-分层放行与路由-20260929.md §2.2/§2.3/§2.4，批档 D1-D9
  =过程日志三节 9）：分类在 server.py chat 入口（route_domain.classify 一次，mq 变体
  继承不重复分类），本件只消费判定结果——retrieve(query, route_res=…) 把
  route_res 透传至 _search_one 各路，域面/doc 面作**选席约束**插入 decrowd
  同构位（重打分 → 选席之间；生效路由只读 route 键 ∈ {domain, doc_direct}，
  route=fallback（含 veto=1/冲突/零命中/置信不足/多号并现）一律全量检索零收窄，
  veto=1 时 doc_direct 键仅观测禁收窄）；检索后兜底=域过滤后候选 <topk 或域内
  最大余弦 <score_threshold（0.40 闸值）→ 回退全量并打 fallback=1 的
  [rag-route] 行（可观测态，纪律同 [rag-hybrid] 不含题面）；mq 深度路径
  （truncate=False）**路级**不选席亦不做域过滤——治理选席统一挂**融合级组装
  段**（mq_fused_select 键域，ADR-0018 2026-10-06 纪律修订："扭曲 RRF 融合
  语义"的关切仅适用于路级选席形态〔治理后位次进 RRF 投票〕，融合级选席在
  RRF 排序完成后施加、与该关切正交；域面过滤仍不入融合级——融合级段=doc
  配额选席〔①③〕only，路由约束/famsel 维持路级 truncate 位）。
  route_domain.py 缺席时 route_enabled 退关（warn 一行，其余检索不受影响）。
- 2026-10-01 试点 2 元数据过滤检索（meta_filter_v1，默认关=现状逐字节不变、零新增
  API；过程日志二节 2026-10-01 已采纳行，施工报告=建库/work/元数据过滤试点/报告-
  20261001.md）：检索后处理层用块级 version 做同族（同 doc_id）陈旧降权——装载期
  从已装载 recs（META_FIELDS 含 version，零额外 IO）构建"多版本族 doc→最新版"索引，
  命中族内非最新版本的块把通道排序分乘 stale_factor（默认 0.85），余弦原始分另存
  hit["cosine"]（gate_cosine 读原始分——0.40 闸载体零侵蚀，②③同款纪律）；空版本/
  不可解析版本（监管件"2026（发文年份）"形）恒不降权（未知≠陈旧，保守向）；
  effective_status 现库几乎全"现行"（区分度在 version），v1 只记录不消费。
  挂接位=decrowd 组装段（深候选池 decrowd_candidates 复用，与 ①②③ 同构）。
- 2026-10-03 增 B-evict 定向清位（b_evict_enabled 键，默认 false=现状逐字节
  不变、零新增 API；用户 2026-10-03 决策 #1b 候选B 采纳，呈报件=运营/呈报-
  丙闸扩型候选B-20261003.md；机制权威=建库/work/排序优化四期-20261003/丙闸
  跑测/跑测脚本-20261003.py 的 b_evict，evict 语义以它为准）：挂检索链尾
  （乙重排+同源折叠后、终 topk 截断与闸门段之前）；题面命中 B_EVICT_VOCAB
  （七词冻结=国内长途/无线信道/IP电话/呼叫建立/消息/成功/抖动）才激活——
  激活后以窗内 rank1 块的 B_STRONG 负项集为基准（n1=rank1 缺词数），逐出
  top10 窗内负项严格超基准（n(b)>n1）的块，幸存者原序取前 topk（席位不足
  如实缩减；rank1 恒幸存；W 空=零改动直过）。词表冻结纪律：B_EVICT_VOCAB
  单词增删=扩改须决策（重走预登记，禁自动生效）；七词禁入覆盖闸词表（面1/
  面3 双重判死在档）；库扩容若引入含判别词新条款（寻呼/短信指标类）须联动
  复核。激活时打一行 [rag-evict] q=<题面命中词> base=<n1> evicted=<n> 观测行
  （供 obs 未来教识与部署窗 journal 断言）。
- 2026-10-03 增表降权白名单（table_downweight_whitelist 键，默认 []=行为
  逐字节一致；用户 2026-10-03 决策 36.101 双值白名单形批，施工案=建库/work/
  排序优化四期-20261003/36101臂Ⅱ/判效报告-20261003.md §十）：消费点=
  decrowd_rescore 表降权谓词（②表因子分支）——locator 正则（re.search）
  命中白名单任一值的块静默跳过表因子（不乘 table_factor；③制式压制不受
  影响、cosine 闸载体不变、无新打点）。白名单正则扩值须决策（逐表登记制：
  36.101/36.213 升版或新表号入库须复核白名单）；坏正则单条丢弃（口径贴
  _clean_spec_rules，不整组回退）；null/非 list=无豁免。
- 2026-10-06 增案甲域降权（domain_downweight 键，默认 {}=现状逐字节不变、
  零新增 API；用户 2026-10-06 治理拨键批①采纳，拨值 {"telecomhall": 0.5}
  随部署窗 config 落——机制与拨值分离；仿真依据=运营/扩容-V4-挤占治理仿真
  呈报-20261006.md 案甲〔0.5 档零损伤+C 卷 +1 确定+6 可能+对抗卷条件 +8〕，
  挤占实证=建库/logs/扩容-V1-四卷门禁与锚复验-20261006.md）。语义=命中域
  （块 rec 的 source_domain 归一小写==键名）的通道排序分乘系数后参与重排，
  域内相对序不变（同域同乘子=保序）；余弦原始分恒存 hit["cosine"]、
  gate_cosine 读原始分——0.40 闸载体零侵蚀（②③/meta_filter 同款纪律）；
  附 domain_factor 键（仅命中块，评测归因直读）。挂接位=decrowd 组装段
  （decrowd_rescore/meta_filter_rescore 之后、路由选席/族选席/配额之前，
  乘子链=乘法交换律下与 ②③ 等价），深候选池复用 decrowd_candidates（域
  降权要有让位补位面）。键值域登记制：域名单/系数扩改须决策（与库态联动
  ——新语料域入库〔sharetechnote 等〕须复核域键，禁自动生效）；坏条目
  （非 dict 键值/系数 ∉(0,1]）单条丢弃不整组回退（口径贴 _clean_spec_rules）。
- 2026-10-06 增案丙域内 doc 配额（domain_doc_quota 键，默认 {}=现状逐字节
  不变、零新增 API；用户 2026-10-06 批准案丙 doc≤2 席位配额〔V4 案丙 fam
  粒度已否决勿实施〕，拨值 {"miit": 2} 随部署窗 config 落——机制与拨值分离；
  仿真依据=运营/扩容-V4-挤占治理仿真呈报-20261006.md 案丙〔doc≤2：零误伤+
  对抗卷 +4 确定+监管族内挤占 C19/S1V-05 唯一覆盖方向〕，残余红灯归因=
  建库/logs/扩容-V5-终态复验-20261006.md〔C19=工信部令第35号 5 席压 36号令
  正主；S1V-05=36号令附录8 族压附录6 正主〕）。语义=命中域（块 rec 的
  source_domain 归一==键名）内每 doc_id 在最终选席窗至多占 N 席，超限块
  让位、候选池深处补位——**轻路径实施**：现役 ① doc_quota_select
  （2026-09-29 P0①）已是 doc 级选席机制（同 doc 席位上限+两遍制回补），
  本键=其域表参数化扩展（domain_quotas 参数），非新选席机制；域表命中
  块以域值为准（覆盖 ① 全局档，更特异者胜），非域表域块回落 ① 全局配额
  （开时）、① 关时不限额。与既有席位机制交互（已核实无双重配额冲突）：
  famsel 族选席=doc 内父子款/克隆族（选席在前、overflow 并入配额回补池）；
  同源折叠族键=(doc_id, locator 主干) **非 doc 级**——配额（doc 级 ≤N）与
  折叠（同源单席）不同粒度序贯组合；案甲域降权=选席前乘子（乘法交换律
  下正交）。选席改成员不动分：cos 原始分恒存、gate_cosine 读原始分——
  0.40 闸载体零侵蚀（① 同款薄余量纪律）；开启即触发深候选池
  （decrowd_candidates 复用——让位要有补位面）；命中让位时 [rag-decrowd]
  行加 ddq=域名:上限 读数。域登记制：域名单/席位扩改须决策、与库态联动
  （监管新件/新语料域入库须复核域键），禁自动生效；坏条目（非整数/<1/
  空域名）单条丢弃不整组回退（口径贴 clean_domain_downweight_params）。
- 2026-10-06 R3C 增 ADR-0018 融合级配额段＋弱注入辅助闸（全部默认关=现状
  逐字节不变、零新增 API；决策链=过程日志三节37③ 用户 2026-10-06「按推荐走」
  全批，决策权威=决策/ADR-0018-mq融合路径配额与降权载体.md〔已采纳：甲2
  融合级配额段＋路级 keep 加深配套＋退化出口统一覆盖〕，设计稿=运营/扩容
  -R3设计稿-mq键效力修复-20261006.md §一/§四；证据面=建库/logs/扩容-V8R-
  退库终验与诊断-20261006.md §八 B 面三问＋C19 探针〔fused10 miit 6 席/
  35号令终 top5 3 席霸屏/正主缺席 fused10〕＋Q1 探针〔miit 弱匹配带
  0.565-0.619 整组硬注入〕）：
  ① 融合级配额段（mq_fused_select_enabled 键，默认 false=零调用面；附
    mq_fused_candidates 融合池深键，默认 null=数值零漂移）——_retrieve_mq
    的 RRF 融合输出之后、返回 retrieve() 链尾之前挂 doc_quota_select 选席段
    （_mq_fused_select：**纯函数复用、零新选席机制**）：参数面=① 全局配额
    （doc_quota_*）＋③ 域表（domain_doc_quota），窗=fold_win or topk（与
    单路 truncate 选席同窗口径），两遍制回补语义原样继承（证据面绝不因配额
    缩水）；键值/语义/清洗/豁免/闸分纪律全部不变，仅载体位扩展（治 ③ 在
    生产 mq 主路径零载体被绕过的结构性病灶——V5-V8"评测绿生产红"分叉面）。
    **统一出口**：融合正常出口与"仅剩原查询一路"退化出口同走本段（退化出口
    现状同样零载体=同病灶面）；mq 关/变体全灭退单条（truncate=True 路）已在
    路级选席，不重复施加。**甲2 深窗配套**（随主键自动生效，无独立键）：键开
    时路级 keep 由 depth（=max(topk, hybrid_candidates)=20）放粗到 decrowd
    池深（decrowd_candidates 现值 60）、rrf_fuse 截断放粗到 mq_fused_candidates
    （拨值建议 60）——RRF 池上限=路数×keep（2×20=40 实证），C19 正主 raw
    位次 (20,60] 带入窗的必要面；重打分本就在深池内完成，keep 只是截断位，
    路级零新增计算。选席在 RRF 排序完成后施加：不改 fused 分、不改各路输入
    列表，cos 原始分恒存、gate_cosine 读原始分——0.40 闸载体零侵蚀。观测=
    [rag-mq-quota] 行（quota/ddq/window/pool/yielded/backfilled/changed/
    exit=fused|degraded；不含题面，[rag-decrowd] 同纪律）——兼作 C19 型
    miit 席计数观测线（V8R 诊断建议 (c)）。[rag-mq] 归因行明细键开态超 10
    席时截前 10+尾注（关态融合窗恒 ≤10=读数零变化）。**在册纪律修订**
    （ADR-0018 决策⑤，三处注释同步）："路级（truncate=False）不选席：治理
    选席统一挂融合级组装段（mq_fused_select 键域）；'扭曲 RRF 融合语义'的
    关切仅适用于路级选席形态，融合级选席与该关切正交"。
  ② 弱注入辅助闸（weak_gate 嵌套键域，默认 {}=关=零调用面）——治 Q1 型
    弱匹配硬注入（全席原始 cos 弱带＋0.40 闸"一块过线全组放行"＋弱证据喂
    生成=投诉面形态之一）。挂点=retrieve() 0.40 主闸通过后、cover 闸后、
    build_evidence 前。判据=(a) 绝对弱带 gate_cosine < t_weak（候选带
    0.62-0.65，默认 0.65）∧ (b) 梯度平坦 集内 max−P50 < flat_delta（候选带
    0.05-0.08，默认 0.06）——**AND 组合**（单判据必误伤：Q3 正主题 0.6474
    邻界、同族正主 0.75 均一带实证在档）；判据载体=集内**原始余弦分布**
    （gate_cosine 同器提取面 max→max/P50/梯度），RRF 融合分绝不作载体。
    动作档（首批=A+B 零误拦面）：action="mark"=A 级观测打点（[rag-weakgate]
    行：weak/gate/p50/grad/t_weak/flat/keep_delta/blocks/dropped/action〔trim
    触发时附 trimmed=〕，不含题面）；action="annotate"=A+B 级降注（证据头部
    追加 WEAK_GATE_HINT 弱相关提示行，计入 max_context_chars 预算）——零改
    成员、零拒答，0.40 主闸语义零改动、不立第三拒答态（弱带态="放行＋处置"，
    与 low_score/coverage_miss 两态严格并列）；action="trim"=C 级减席
    （2026-10-07 落码转合法档：只保 cos≥gate−keep_delta 的前席、自带 B 级
    降注=减席+声明，改成员=全量回归判据先定后测）；转拒答=D 级禁用项
    （09-28 阈值050评估在档结论：维持 0.40、不上调、不立分数分层、禁硬拒型
    动作）。T_weak/Δ_flat/Δ_keep 终值归标定轮（设计稿 §四.5：现库在档明细
    0 元复算、判据先定后测、随窗冻结）。坏值回默认档（非 dict 容器整键回关；
    t_weak/flat_delta/keep_delta 非数字/NaN/越界 (0,1] 回默认；单一尺=
    clean_weak_gate_params，防两把尺）。
  ③ 表降权 docs（L2 26 件增补，设计稿件三）：**本批不拨值**——随 L2 重上批
    走（过程日志三节37③ 口径），config.example.json 只落预留位注记
    （_说明_表降权docs-L2预留位）。
- 2026-10-14 增 H 线查询-族定向加权（query_doc_factor 键，默认 []=现状逐字节
  不变、零新增 API；F线H 排序治理批，病灶依据=运营/F线/E线-锚包判定报告-
  20261014.md §二 ③类 17 条的"负例域挤占"三例〔YDT-014 审批流程题被 5264
  站址条款 top1 挤占/YDT-017 传输时延题被 4826 报告生成时延 top1 挤占/
  CARD-006 UPF 题被 RAN 合成卡 top1 吸引〕）。语义=题面命中规则信号词
  （query_words 任一词形，_ws_norm_text 归一包含匹配）时，命中目标面
  （doc_contains 子串 ∨ corpus_types 精确 ∨ source_domains 归一精确，并集）
  的块把通道排序分乘规则 factor（多规则连乘；∈(0,2]，<1 降权 >1 加权）；
  题面零命中=零改动直过（恒激活规则在清洗面禁入）。余弦原始分恒存
  hit["cosine"]、gate_cosine 读原始分——0.40 闸载体零侵蚀（②③/meta_filter/
  案甲同款薄余量纪律）；附 qdf_factor 键（仅命中块，评测归因直读）。挂接位
  =decrowd 组装段（案甲域降权之后、路由选席/族选席/配额之前，乘子链位），
  深候选池复用 decrowd_candidates（让位要有补位面）；激活时打 [rag-qdf] 行
  （rules/fired/hit_n，不含题面）。规则表维护纪律：清单/目标面/factor 扩改
  须决策、与库态联动（新语料域/新合成卡族入库须复核规则），禁自动生效；坏
  条目（缺信号词/缺目标面/factor ∉(0,2]）单条丢弃不整组回退（口径贴
  _clean_spec_rules）。单一清洗权威=clean_query_doc_factor_params（离线回放
  器同源复用，防线上/离线两把尺）。
- 2026-10-23 增 MMR 向量去冗余（mmr_enabled/mmr_lambda 键，波3 工程件，
  默认关=现状逐字节不变、零新增 API 零新索引；AG 增量档 §7.3 代查=现役
  decrowd_rescore 系 locator 正则/词法规则，向量维多样性是空白——本件补
  终 top-k 内部的向量维去冗余面）：挂点=retrieve() 链尾=clause_family_rerank
  （乙重排）+same_source_fold（同源折叠）+b_evict（定向清位）全部治理键
  生效后的终 topk 截断面之后、0.40 闸门段之前——选此挂点的理由：(i) 治理
  键全部先落=成员集合由既有机制独占决定，MMR 不绕过不削弱任何治理键
  （折叠殿后者已被截出窗、evict 逐出者已出局，MMR 只见幸存者）；(ii) 闸门
  段只读集合级统计（gate_cosine 取集内最大、覆盖闸/弱闸取集合面）——order-
  only 重排后读数不变，闸分载体零接触。语义=maximal marginal relevance
  同集合置换：λ·相关性（原始余弦，gate_cosine 同款提取面）−(1−λ)·与已选集
  的最大块间余弦（rec["vec"] 既有归一向量点积，O(n²) 纯标准库、n≤topk 毫秒
  级以下）逐席贪心选席（首取=相关性最高，tie→原位次；纯余弦态 λ=1=恒等
  置换，λ=0=纯多样性退化态，两边界合法）。硬纪律=不产生新分数、不污染闸分
  载体：hit 的 cosine/score 字段逐字节不动（输出=逐条 dict 拷贝，乙层同款
  先例），MMR 边际分只在选席瞬间存在不落 hit；rank 按 MMR 终序重编 1..n
  （build_evidence [出处N] 编号位，fold/evict 链尾同款口径），另附独立
  mmr_rank 键（MMR 选席序，纯观测面，闸分/证据组装零消费）；换位时打一行
  [rag-mmr] 观测行（n/moved/lambda/perm，不含题面，[rag-decrowd] 同纪律）。
  回滚=mmr_enabled 回 false 秒级（键面单键）。施工报告=建库/work/
  MMR去冗余-20261023/施工报告.md。
"""
import hashlib
import json
import math
import os
import pickle
import re
import sys
import threading
import time
from array import array
from datetime import date, timedelta

import httpx

try:
    import multiquery  # mq_* 查询改写（默认关）；模块缺席时 mq 退关不影响其余检索
except Exception:  # pragma: no cover —— 部署漏带 multiquery.py 时 RagService 照常可用
    multiquery = None

try:
    import route_domain  # 期 1 路由域分类器（route_* 默认关）；缺席时路由退关
except Exception:  # pragma: no cover —— 部署漏带 route_domain.py 时 RagService 照常可用
    route_domain = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 新库规范元数据字段（缺失字段按 "" 参与组装，不判坏行）
# 2026-09-29 乙案：扩 corpus_type/chunk_type/source_domain 三字段（装载面缺口治理，
# 期1路由挂接遗留 1；族选席推导依赖 chunk_type/corpus_type 区分监管/3GPP 域）
META_FIELDS = ("id", "content", "doc_id", "version", "locator",
               "corpus_type", "chunk_type", "source_domain")

DEFAULT_STORE_PATH = os.path.join("建库", "vectors", "embeddings.jsonl")
DEFAULT_TOPK = 5
DEFAULT_MAX_CONTEXT_CHARS = 6000
DEFAULT_TIMEOUT_SECONDS = 3.0
DEFAULT_EMBED_MODEL = "text-embedding-v4"
EMBED_DIMENSIONS = 1024  # text-embedding-v4 请求维度（与建库管线一致）
EMBED_PATH = "/compatible-mode/v1/embeddings"

EVIDENCE_HEADER = "以下为检索到的语料片段，回答时优先依据语料，语料未覆盖的内容如实说明不确定"

# 词法重排（lexical boost）默认参数；rag 段配置键：
#   "lexical_boost": false      # 总开关（默认关=现状不变；true=余弦 top-N 后二次打分）
#   "lexical_lambda": 0.05      # λ：合成分 = 余弦 + λ×词法分（0=退化等价纯余弦）
#   "lexical_candidates": 20    # 余弦 top-N 候选进入重排
DEFAULT_LEXICAL_LAMBDA = 0.05
DEFAULT_LEXICAL_CANDIDATES = 20

# BM25 并路混合默认参数；rag 段配置键：
#   "hybrid_bm25_enabled": false  # 总开关（默认关=现状不变；true=BM25 独立通道
#   #   全库召回与余弦通道融合——与 lexical_boost 的候选内重排构造上不同，
#   #   可把余弦圈外的精确术语块（参数名/表名/TS 号）拉回 topk）
#   "bm25_k1": 1.5                # Okapi BM25 k1（词频饱和）
#   "bm25_b": 0.75                # b（文档长度归一强度：0=不归一，1=全归一）
#   "hybrid_candidates": 20       # 两路各取的候选深度（不足 topk 时取大者）
#   "hybrid_fusion": "rrf"        # 融合方式："rrf" | "weighted"
#   "hybrid_rrf_k": 60.0          # rrf 平滑常数（rank 从 1 起，贡献 1/(k+rank)）
#   "hybrid_bm25_weight": 0.3     # weighted 模式 BM25 路权重 w∈[0,1]；
#   #   融合分=(1-w)*cos'+w*bm25'（两路各按本路候选最大分归一到 [0,1]，未入路计 0）
#   "bm25_persist": false         # 索引持久化（波3 工程件 2026-10-23；默认关=
#   #   现状逐字节不变——每次启动全量重建）。true 时建成索引 pickle 落盘
#   #   <store>.bm25idx.pkl，下次装载校验通过即直载（省全量重建耗时）；
#   #   校验失败/文件坏/写失败一律无条件回退全量重建（纯加速件，同 sidecar
#   #   纪律，详见 BM25Index 后持久化节注释）。
#   #   直通键（刻意不入 DEFAULT_RAG_CONFIG）：键面守卫件
#   #   （tests/test_同源折叠扩展.py 等）钉死 DEFAULT 键增量、扩键须同步改
#   #   守卫件=超出本件触面；initialize 的 cfg.update 全量透传非 _ 键，
#   #   缺省（键缺）=关，语义与在册键一致。
DEFAULT_BM25_K1 = 1.5
DEFAULT_BM25_B = 0.75
DEFAULT_HYBRID_CANDIDATES = 20
DEFAULT_HYBRID_RRF_K = 60.0
DEFAULT_HYBRID_BM25_WEIGHT = 0.3

# 分数阈值闸门默认参数（2026-09-21 批1，诊断报告 P0-1 与 off_topic P1-4 双做）；
# rag 段配置键：
#   "score_threshold": 0.40   # 证据集内最大余弦原始分（纯余弦态=top1，混合/
#   #   重排序见 gate_cosine 注释）低于此值 → off_topic：不注入
#   #   证据、不下发 sources，retrieve 返回 LowScoreResult（服务端先发
#   #   {"type":"off_topic"} SSE 事件再照常裸答流式，[chat] 记 rag=low_score）。
#   #   口径：纯余弦态=hit["score"]（search 输出无 cosine 键，score 即余弦）；
#   #   lexical/hybrid 态=hit["cosine"]（rerank_hits/fuse_hits 已附）；mq 融合态
#   #   =hit["cosine"]（rrf_fuse_hit_lists 2026-09-21 起附，跨查询路取最大）。
#   #   RRF 融合分（≈0.016-0.033）/weighted 归一分/BM25 分绝不作阈值载体。
#   #   默认 0.40=域内 36 题 top1 下界 0.661 与域外样本 0.202 断带中点偏向
#   #   域内防误伤（依据：运营/优化提升-20260921/阈值分析-20260921.md §四）；
#   #   设 0 或 null=关闭闸门回退旧行为；0.45/0.50 留作近域题补测后的上调梯度。
DEFAULT_SCORE_THRESHOLD = 0.40

# multi-query 查询改写默认参数（计划内后备工序 D，默认关=零 API 零调用）；
# rag 段配置键（生成与融合实现在 multiquery.py，费用/延迟口径详见该件头注）：
#   "mq_enabled": False          # 总开关（默认关=现状不变；true=检索前生成查询变体）
#   "mq_n_variants": 2           # 变体条数，上限 2（越界钳 [0,2]；0=不产变体）
#   "mq_model": "qwen3.8-flash"  # 变体生成模型（与建库 CR 管线同款 flash 档）
#   "mq_timeout_seconds": 3.0    # 变体生成阶段总预算（秒）：逐变体串行 flash 调用、
#   #   每次超时取剩余预算；超时/失败优雅退单条原查询（零恶化），正常态延迟 +0.5-2s
#   "mq_wall_clock": False       # 预算硬墙钟（2026-09-21 迭代轮，默认 false=旧行为）：
#   #   per-op 超时不缚单调用墙钟（判定实测 flash 单调用 7.18s>3s 仍返回）；
#   #   true 时单调用线程化、剩余预算到点即弃——mq 延迟上界=预算而非端点延迟
#
# 批B4 增（2026-09-22，采用配方落地，建库/logs/hybrid-mq评测-20260919.md 配方节；
# 三键缺省=现行行为逐字节不变，回滚=删键）：
#   "mq_single_variant": False   # 单变体模式：true 时只生成 1 条变体（第 0 条=英文
#   #   翻译）与原查询合并检索，覆盖 mq_n_variants（配方形态=1 变体）；
#   #   变体生成失败/超时=静默降级只走原查询，[rag-mq] 打点区分降级原因
#   "mq_variant_timeout": None   # 变体生成阶段秒预算（新键，与整体墙钟分键）；
#   #   None=回退 mq_timeout_seconds（旧键继续有效，兼容现行配置）
#   "mq_wall_timeout": None      # mq 整体墙钟秒预算：变体生成+变体 embed/检索合计
#   #   不超此值，预算耗尽即弃剩余变体路走原查询（不拖原查询检索，零恶化）；
#   #   None=无整体预算（旧行为，生成阶段预算仍由 mq_variant_timeout 管）
#   坏值钳制口径贴批A server._depth_config 先例：非数字/NaN/越界 (0,30] 一律回
#   回退值（见 _norm_mq_budget）。采用配方建议档：mq_enabled=true +
#   mq_single_variant=true + mq_wall_clock=true + mq_wall_timeout=2.5。
#
# 与既有两开关的共存矩阵（mq 是最外层包裹：原查询+变体各自独立走一遍右侧通道，
# 通道内部 hybrid/lexical 的优先级规则不变；默认全关=现行行为，逐字节一致）：
#   mq hybrid lexical → 行为
#    0   0      0    → 现行默认：单查询纯余弦 topk（不调 flash 不多路）
#    0   1      ×    → 现行 hybrid：单查询 cos+BM25 融合（lexical 被短路+warn）
#    0   0      1    → 现行词法重排：单查询余弦候选内二次打分
#    1   0      0    → 每查询纯余弦（候选深度 max(topk, hybrid_candidates)）→多路 RRF
#    1   1      ×    → 每查询 cos+BM25 融合（lexical 仍被短路+warn）→多路 RRF
#    1   0      1    → 每查询词法重排 →多路 RRF
#   多路 RRF：fused(d)=Σ_查询路 1/(hybrid_rrf_k+该路 rank)，截 topk；平滑常数
#   复用 hybrid_rrf_k（默认 60），tie-break 查询序优先（原查询 q0 在前）。
#
# 费用口径（启用时）：每变体 = 1 次 flash 调用 + 1 次 embedding（默认 2 变体 →
#   每问至多 2 次 flash + 3 次 embed，含原查询）；启用评测时费用走生成侧台账口径。

# faiss IndexFlatIP 加速件（2026-09-26 接入，默认关=现状逐字节不变）；rag 段配置键：
#   "faiss_enabled": False     # 总开关（纯加速件）：true=装载后以已归一化向量建
#   #   IndexFlatIP 缓存于 RagService，_search_one 各余弦通道（纯余弦/lexical
#   #   候选/hybrid 余弦路）改走 faiss 检索（hit 形态不变，查询归一化口径不变）；
#   #   faiss 导入失败/建索引异常/检索异常 → [rag-faiss] degrade 退纯余弦全量扫
#   #   （服务不中断，行为=旧路径）；内存=索引持向量体单份拷贝（≈175MB/44871
#   #   行，见 build_faiss_index 注释）。对拍依据 建库/logs/faiss对拍-20260926.md。

# embedding 月度预算闸（2026-09-28 增，默认关=现行行为逐字节不变）；rag 段配置键：
#   "embed_monthly_budget_enabled": False  # 总开关：true 时 _embed 前查月度累计
#   "embed_monthly_budget_cny": 40          # 预警线（元）：月度累计 ≥ 此值打
#   #   [rag-budget] warn 日志，照常嵌入（只标记不拦）
#   "embed_monthly_cap_cny": 50             # 硬顶（元）：月度累计 ≥ 此值拒绝
#   #   嵌入（抛 EmbedBudgetExceeded → retrieve 兜底 None=退纯裸答 + 日志）
#   "embed_ledger_path": "建库/logs/embed用量.jsonl"  # 台账源（相对 qa-bot 根
#   #   或绝对路径；服务端查询嵌入不写该台账，闸只按建库管线侧累计口径拦——
#   #   查询侧 ~10 tok/问=0.000005 元/问量级，不计）
# 口径（对齐过程日志三节 36① 的 2026-10-05 调线：embedding 红线累计 50/预警 40；
#   #   更早 25/20 系 2026-09-26 调线，史在过程日志）：
#   - 月度累计 = 台账当月切片 prompt_tokens 求和 × EMBED_PRICE_CNY_PER_MTOK
#     （text-embedding-v4 在线牌价 0.5 元/百万 tok，台账口径收口档在档）；
#   - 台账 ts 字段无日期（仅个别行带日期锚）：月度归属=锚行日期+时间回跳
#     >LEDGER_DAY_GAP_S 步进一日重建（回跳≤2h 的跨午夜续跑会记到前一日，
#     只在月界且恰跨午夜时影响归属，登记在册）；无任何锚行=全归当月（保守
#     过拦口径）；坏行/缺文件=计 0（闸开，warn 一行）；
#   - 预警/硬顶坏值（非数字/≤0/NaN）一律回默认 40/50（防误配静默失效）；
#     预警 >硬顶时以硬顶钳预警（保持 block 先于 warn 的语义）。
DEFAULT_EMBED_MONTHLY_BUDGET_CNY = 40.0
DEFAULT_EMBED_MONTHLY_CAP_CNY = 50.0
EMBED_PRICE_CNY_PER_MTOK = 0.5
DEFAULT_EMBED_LEDGER_PATH = os.path.join("建库", "logs", "embed用量.jsonl")
LEDGER_DAY_GAP_S = 2 * 3600  # 台账日重建的时间回跳阈值（并发写乱序为分钟级，2h 安全带）

# S1 负控治理乙/丙（2026-09-28 选项一）；rag 段配置键：
#   "clause_family_rerank": True      # 乙总开关（默认开=选项一决策生效；false=
#   #   回滚旧行为=纯通道原序）。order-only：只重排证据集内部次序、不改成员
#   #   ——gate_cosine 读集内最大余弦，成员不变则 0.40 闸分不变（薄余量零侵蚀）。
#   "clause_family_rerank_words": "full"  # 乙负项词表档位：full=core+指标概念词
#   #   （默认，方案步 2 补强档）；core=方案 §二路径乙封闭词表。坏值回 full。
#   "cover_gate_enabled": True        # 丙总开关（默认开=选项一决策生效；false=
#   #   回滚）。串联在 0.40 低分闸之后：题面含库外域词表词而证据集全部块文本
#   #   （doc_id+version+locator+content 拼接，同 _rec_text 口径）不含该词 →
#   #   CoverageMissResult（不注入证据不下发 sources，服务端 off_topic 事件+
#   #   照常裸答，打点态 coverage_miss 与 low_score 严格区分）。
#   "cover_gate_vocab": null          # 丙词表覆盖键（list[str]；null/非 list=内置
#   #   安全词形）。维护纪律（方案 §五.4）：库扩容与词表联动——如附录7 卫星数值
#   #   条款未来入库，"卫星"词须同步移除，否则误拦；扩改须决策，禁自动生效。
#   #   裸词"5G"禁入表（域内误拦实证，见离线验证档）。
CLAUSE_RERANK_WORDS_CORE = (
    ("主体词", "固话"), ("主体词", "移动"), ("主体词", "蜂窝"), ("主体词", "IP电话"),
    ("主体词", "寻呼"), ("主体词", "卫星"), ("主体词", "租用"),
    ("限定词", "本地"), ("限定词", "国内长途"), ("限定词", "固定"),
    ("年份", "2024"), ("年份", "2025"),
)
CLAUSE_RERANK_WORDS_METRIC = (("指标词", "拨号"), ("指标词", "呼叫建立"), ("指标词", "抖动"))

# 丙内置安全词形（库外域词形；语义与离线验证档一致，禁用裸词"5G"）
# 2026-10-24 移词（用户决策；诊断=建库/work/波0自查-20261023/双诊断-20261024.md
# 诊断2，施工档=建库/work/移词施工-20261024/施工报告.md）：卫星/空口/携号转网
# 三词已随 2026-10-22 治本 rebuild（staging-v2 82,210）入库域——卫星 48 块/10
# doc（miit 39+ydt 5 等）、空口 68 块/17 doc（ydt 57 等）、携号转网 20 块/1 doc
# （=工信部信管〔2019〕242号全文）；宽带装机 0 块仍真库外——按 §五.4 库扩容
# 联动纪律移除三词、保留宽带装机。R6b-J067"名次 miss 被陈旧词硬拒 0 sources"
# 形态随之解除（移词修态标签+证据注入权，不保证 gold 引用；mq 配方未动）。
# 代价注记：移除即失去该词面保护——真库外题退 0.40 余弦闸兜底（泛证据照常
# 注入）；未来退库回填须反向联动把词加回（扩改仍须决策）。
COVER_GATE_VOCAB = ("宽带装机",)

# ---------------------------------------------------------------------------
# W2 方案一词面限域门控（2026-10-08 过程日志三节 44 D2 甲，默认关=现状逐字节
# 不变）；rag 段配置键：
#   "hybrid_gated_enabled": False  # 门控总开关（false/缺省/非法值=关；仅严格
#   #   布尔 true 开，口径同 clean_same_source_fold_params 先例）。与
#   #   hybrid_bm25_enabled 双键互锁：总闸 false 时门控形不生效（_search_one
#   #   hybrid 分支一字不动，零调用面）。
#   "hybrid_gate_vocab": null      # 触发词表覆盖键（list[str]；null/非 list=
#   #   内置 HYBRID_GATE_VOCAB；list=str 化去空）。
# 语义：双开时题面先经 hybrid_gate_hit 判定（词形包含 ∨ 正则命中，BM25
#   tokenize 前的题面级判定）——命中 → 现行 BM25 融合逻辑一字不动；未命中 →
#   跳过 BM25 融合落纯余弦路径（与 hybrid 关态逐字节一致；lexical_boost 同被
#   短路不复活——共存语义不变）。归因日志 [rag-hybrid-gate] 仅双开时打
#   （hit/miss 两态各一形，不含题面；关态零新观测面）。
# 词表维护纪律（与 cover_gate_vocab 同机制）：触发面收窄到确定受益题类
#   （监管指标全称/限定词形+3GPP 参数名式记号），词表与正则扩改须决策、与库态
#   联动，禁自动生效；裸泛词（"消息"/"成功"级）禁入表。已知风险=版本编号类
#   题面（Rel-18/v18/36.xxx 形）会触发，其零退化由离线复放判据把关（词表初稿
#   可在复放阶段离线迭代）。
# ---------------------------------------------------------------------------
# 触发词表初稿（tuple 冻结；不挂路由判定、不复用高危词表=D3 甲决策口径）。
# 抽取来源=真题面：S1 独立验证卷 S1V-06/07/12/13/14（国内长途/拨号时延/无线
# 信道/接通率/接入速率/时延抖动）+红线扩容卷 R03（子载波间隔）+答案卷/独立B/
# 对抗卷等在库题面的同类监管指标全称（接续时延/呼损/掉话率/通信中断率/计费
# 差错率/国内甚小口径，全库题卷扫描 3-50 卷命中）。
HYBRID_GATE_VOCAB = (
    "国内长途", "拨号时延", "接续时延", "呼损", "通信中断率",
    "计费差错率", "国内甚小口径", "子载波间隔", "无线信道", "接通率",
    "接入速率", "时延抖动", "掉话率高",
    # 2026-10-09 键微调批（过程日志 51a 三向治理）：「掉话率」裸词移除——运营
    # 台账 KPI 行顺带引用即触发=泛面误触发（C18 英文 TR×7 顶窗）；增益面
    # 零依赖裸词，对抗 45 逐位零翻转实证。扩改决策=过程日志 52（ADR-0020⑤）。
    # 同日修复窗（过程日志 54）：补搭配词「掉话率高」——真实运维问法（5g小区
    # 掉话率高怎么优化）需要词面把技术块拉回窗（TR36.805/36.300/188号），
    # 台账态"掉话率 1.9%"不含搭配词保持关态（C18 过线维持）；题库全卷面
    # 零命中搭配词=电池读数结构性沿用。扩改决策=过程日志 54（用户批）。
)
# 触发正则（tuple 冻结，re.Pattern；hybrid_gate_hit 对归一题面与原始题面双
# 匹配）：①连字符参数名形（p0-NominalPUSCH/a3-Offset/nprach-NumSubcarriers-R13）
# ②短前缀+2-4 位数字的定时器/计数器形（t310/n310/n311）③驼峰裸参数名形
# （subcarrierSpacing——_ws_norm 小写会破坏驼峰信号，靠原始题面匹配）④显式
# 规范号（36/37/38 系 2-3 位小数号；TS/TR 前缀形归一后仍以裸号在场，同式覆盖）。
# 正则实现独立于 citation_check/route_domain（D2 甲：限域门控形不挂路由判定）。
HYBRID_GATE_PATTERNS = (
    re.compile(r"(?<![a-z0-9])[a-z][a-z0-9]*(?:-[a-z0-9]+)+(?![a-z0-9])"),
    re.compile(r"(?<![a-z0-9])[a-z]{1,6}[0-9]{2,4}(?![a-z0-9])"),
    re.compile(r"(?<![A-Za-z0-9])[a-z]+[A-Z][A-Za-z0-9]*"),
    re.compile(r"(?<![0-9])(?:36|37|38)\.\d{2,3}"),
)

# ---------------------------------------------------------------------------
# R 线二期 S1 词面通道键族（2026-10-17 过程日志 103 续笔① a 施工；判据件 v2 配套
# =work/R线二期-S1判据件v2-20261017/施工方案件-rag新键-20261017.md）；rag 段
# 配置键（全部默认 null=关=现状逐字节不变，feature flag 形态）：
#   "hybrid_gate_vocab_extra": null    # 追加裸词面（list[str]；与生效词表 OR
#   #   合并——生效表=hybrid_gate_vocab 清洗面〔null=内置 13 词〕；null/非 list/
#   #   空 list=零追加，本批 v2 形集无此项、预留对称面）。
#   "hybrid_gate_patterns_extra": null # 追加正则面（list[str] 正则串；与内置
#   #   PATTERNS OR 合并，装载期预编译；坏正则单条丢弃不整组回退——口径贴
#   #   clean_decrowd_params 白名单段；拉丁单正则形挂此键，如 v2 形集 B1 蛇形
#   #   参数名/B4 行标号）。
#   "hybrid_gate_combo": null          # 组合形 AND 面（list of [ctx, sig,
#   #   conj?] 正则串列表项：ctx∧sig 为基式、conj 第三段可选——A2' 三段形用；
#   #   命中=任一形 ctx∧sig(∧conj) 成立，每段对归一题面∨原始题面双匹配〔与
#   #   影子臂 form_hit_v2 同器语义〕；单段正则形〔regex_only〕不挂此键——挂
#   #   patterns_extra；坏项〔长度 ∉[2,3]/坏正则〕单条丢弃+initialize 日志计数）。
#   "query_preprocess_entries": null   # 查询预处理词条（list of 词条 dict，
#   #   schema=S1 修订集 v2 词条集：combo 词条={id, kind:"combo", ctx, sig,
#   #   append}；提取词条={id, kind:"pattern", patterns,
#   #   append_kind:"unit_norm"|"std_norm"}；坏词条单条丢弃+计数）——_search_one
#   #   入口 q→q'（一律追加式 q'=q+" "+append，提取形=数值入规范形；触发但无
#   #   追加=不 fire），门控/BM25/qdf 三消费点全部吃 q'；嵌入调用点在
#   #   _search_one 之前=向量结构性不动（词面路 only）。默认 null=q'=q 恒等。
# 总判定（与上方 W2 门控的合并关系）：
#   gate_hit(q) = hybrid_gate_hit(q, 生效词表∪vocab_extra, PATTERNS∪
#                 patterns_extra) ∨ any(组合形命中)；
#   预处理生效面=一切进 _search_one 的 q（含 mq 变体路，mq 联动注记 NR-8）。
# 装载面指纹：initialize 对三门控键规范化形态（排序键 JSON dump）打一行
#   [rag-gate-extra] forms=N sha256=… 日志、词条键打 [rag-preprocess] 行
#   （计数+SHA，不含词面）——拨键执行单对账锚（修订集 v2 预注册 SHA=原 dict
#   排序键序列化形态，装载面保留原 dict 字段即同形）。
# 词表维护纪律（与 cover_gate_vocab/HYBRID_GATE_VOCAB 同机制照录）：触发面
#   收窄到确定受益题类，词表与正则扩改须决策、与库态联动（新语料域入库须复核
#   触发面），禁自动生效；裸泛词（"消息"/"成功"级）禁入表。任何形/词条增删改
#   =词表类扩改→NP 面误伤预估+红判 veto 回归位+D9 决策三前置（S2 规则库设计
#   四件套同款）。单一清洗权威=clean_hybrid_gate_extra_params/
#   clean_query_preprocess_entries（离线验证脚本同源复用，防两把尺）。
# ---------------------------------------------------------------------------
# ④b 分数带门控键（2026-10-18 检索召回优化组合案部署窗；默认 null=现状
# 逐字节不变，feature-flag 形态）；rag 段配置键：
#   "hybrid_gate_band_t": null  # 分数带阈值 t∈(0,1]（float；null/bool/越界/
#   #   非数=关=词面门控原语义）。语义：仅当词面门控命中时被消费——余弦候选
#   #   带（_search_cos top5 最大原始余弦，纯余弦路径同底座）≥ t → 强带语义
#   #   题不需要词面帮：翻 miss 落纯余弦（与门控 miss 同落点）；带 < t 才维持
#   #   现行 BM25 融合（弱带规范题词面受益通道保持）。词面 miss 不受本键影响。
#   #   开启时 [rag-hybrid-gate] miss 行带「词面命中但余弦带…」注记（观测面）。
#   #   读数之源=work/检索召回优化评估-20261018/（④b t=0.70 档；band 保护
#   #   效应=BX-N10/EV-S10 弱带题保持词面融合的机制在案）。
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# P0 检索层去挤占（2026-09-29，四件套全部默认关=现状逐字节不变）；rag 段配置键：
#   "doc_quota_enabled": False      # ① doc 配额总开关（S1 乙路径扩展：同 doc
#   #   席位上限从"重排"升级为"选席"——超限块让位、候选池深处补位，改成员）
#   "doc_quota_max": 2              # 同一 doc_id 在 top-k 内的席位上限（≥1；
#   #   坏值回默认。topk=5 时 2=最多占 40% 证据面，靶子清单 §二.1 建议档）
#   "doc_quota_exempt_docs": None   # 配额豁免 doc 子串清单（list[str]；null/非
#   #   list=无豁免。留作监管件等确需多席的 doc 应急口）
#   "table_downweight_enabled": False  # ② 表降权总开关（38.133 表格洪流，
#   #   18,368 块占库 35%——扩库靶子清单 §二.1 本库最大结构性挤占源）
#   "table_downweight_factor": 0.85  # 降权系数 ∈(0,1]（坏值回默认；1.0=等价关；
#   #   离线扫描建议值见 建库/logs/P0去挤占实施-20260929.md）
#   "table_downweight_docs": None   # 降权目标 doc_id 子串清单（null/非 list=
#   #   内置 ("38.133",)）
#   "table_downweight_scope": "annex"  # 目标块范围：annex=仅 locator 以
#   #   "Annex" 起的表格块（默认，微创面）；all=该 doc 全部块；tables=仅
#   #   chunk_type∈TABLE_CHUNK_TYPES 的表行组块（2026-10-02 scoped 变体：
#   #   「限表格块作用域」——doc 级降权误伤同 doc 条款/卡正主面时的细粒度
#   #   档，判效依据=建库/logs/检索排序治理-判效-20261002.md §四）。坏值回 annex
#   "spec_suppress_enabled": False  # ③ 制式信号压制总开关（跨制式撞名型，
#   #   靶子清单 §二.2：NR 问句检回 LTE 同名参数卡/反之）
#   "spec_suppress_factor": 0.85    # 压制系数 ∈(0,1]（坏值回默认；1.0=等价关）
#   "spec_suppress_rules": None     # 压制规则覆盖（list[dict]，键=name/
#   #   signal_patterns（正则，对去空白小写题面匹配）/suppress_doc_contains
#   #   （doc_id 子串）/factor（可选，缺省用 spec_suppress_factor）；null/非
#   #   list/清洗后为空=内置 SPEC_SUPPRESS_BUILTIN_RULES）。
#   #   词表维护纪律（与丙层 cover_gate_vocab 同机制）：扩改须用户决策、与库态
#   #   联动——附录7 卫星条款/NTN 等非 36/38 系语料未来入库时须同步复核信号词
#   #   与压制目标（防误压正主），禁自动生效。
#   "decrowd_candidates": 20        # ①②③ 任一开启时的共享深候选池（<topk 时
#   #   钳到 topk；坏值回默认）——降权/配额要有补位空间必须先取深再选席
#   "retrieval_snapshot_dir": None  # ④ 检索快照目录（null/空=关；相对路径锚
#   #   base_dir）。开启后 retrieve() 逐次追加 快照文件 retrieval-snapshot.jsonl：
#   #   {ts,query,vec,state,gate,threshold,hits[...]}——排序实验归因证据层。
#   #   含题面原文，本地诊断件，生产默认不开；写失败 warn 一次不影响检索。
# 闸分纪律：②③ 只乘通道排序分（hit["score"]），余弦原始分恒存 hit["cosine"]
#   （纯余弦态打分前补挂），gate_cosine 优先读 cosine——0.40 闸载体零侵蚀；
#   ① 改成员会换集内最大余弦的取值块，但域内题补位块余弦仍在 0.6+ 带
#   （离线对拍断言 gate_would_block 零翻转，见施工报告验证矩阵）。
DEFAULT_DECROWD_CANDIDATES = 20
DEFAULT_DOC_QUOTA_MAX = 2
DEFAULT_TABLE_DOWNWEIGHT_FACTOR = 0.85
DEFAULT_SPEC_SUPPRESS_FACTOR = 0.85
TABLE_DOWNWEIGHT_DOCS = ("38.133",)
TABLE_DOWNWEIGHT_ANNEX_PREFIX = "Annex"
# scope=tables 的表块判定集（2026-10-02 scoped 变体；现库表类块实测仅
# table_row_group 一型——扩型须同步此处与配置键说明，禁静默放宽）
TABLE_CHUNK_TYPES = ("table_row_group",)

# ---------------------------------------------------------------------------
# 乙案族选席（2026-09-29，默认关=现状逐字节不变；方案档 建库/logs/负控弱区
# chunk父子款方案-20260929.md §2.2）
#   family_select_enabled: false     # 族选席总开关（R1-R5 规则组）
#   family_select_scope: "miit"      # 族推导范围 miit|miit+clone（坏值回 miit）
#   family_select_words: "full"      # 负项词表档位 full|core（复用乙层词表，
#                                    # 坏值回 full；与 clause_family_rerank_words 同源）
#   clone_fold_min_margin: 1         # R4 克隆折叠最小负项差（≥0；坏值回 1）。
#                                    # 折叠前提（方案硬规则）=族内唯一 0 负项成员，平局（多
#                                    # 0 负项）一律不折叠=B12 canary 保护；本键只收紧差值
#                                    # 门槛：0/1 行为等价（次优负项恒 ≥1），≥2=差至少 2 才折叠
# ---------------------------------------------------------------------------
DEFAULT_FAMILY_SELECT_SCOPE = "miit"
DEFAULT_CLONE_FOLD_MIN_MARGIN = 1

# ---------------------------------------------------------------------------
# 试点 2 元数据过滤检索（2026-10-01，默认关=零调用面；过程日志二节 2026-10-01 已采纳
# 行；机制=检索后处理层同族块陈旧降权）；rag 段配置键：
#   "meta_filter_v1": False        # 总开关：true 时装载期构建版本族索引+检索后处理
#   #   降权（与 decrowd ①②③ 同构挂接：深候选池复用 decrowd_candidates）
#   "meta_stale_factor": 0.85      # 陈旧降权系数 ∈(0,1]（坏值回默认；1.0=等价关）
# 口径：族=同 doc_id 内 ≥2 个不同可解析版本（"Vx.y.z" 形，regex 抽取数字三元组）；
#   非最新版本块 score×factor，cosine 原始分恒存（0.40 闸载体零侵蚀）；空版本/
#   解析失败版本恒不降权不参与族判定（未知≠陈旧——监管件"2026（发文年份）"形
#   与 38.133 空版本 1,460 块天然不受影响）。现库多版本族 6 doc、陈旧块 128 块。
# ---------------------------------------------------------------------------
DEFAULT_META_STALE_FACTOR = 0.85

# ---------------------------------------------------------------------------
# 案甲域降权（2026-10-06 治理拨键批①，默认 {}=零调用面；拨值随部署窗 config 落
# ——机制与拨值分离）；rag 段配置键：
#   "domain_downweight": {}   # 域降权表（dict：{域名: 系数}）；空 dict/非 dict=关。
#   #   拨板形态（2026-10-06 决策，随部署窗）：{"telecomhall": 0.5}——治扩容批
#   #   telecomhall 论坛块对中文实操/日志题面的近邻挤占（V1 挤占实证：C 卷
#   #   cos-top5 占席 64/140；V4 仿真：0.5 档零损伤+C 卷 +1 确定+6 可能+对抗卷
#   #   条件 +8〔0.85 档对抗卷条件不成立，故定 0.5〕）。
#   # 语义：命中域=块 rec 的 source_domain 归一（strip+lower）==键名 → 通道
#   #   排序分乘系数参与重排（域内相对序不变=同域同乘子保序）；余弦原始分
#   #   恒存 cosine 键（0.40 闸载体零侵蚀，②③/meta_filter 同款纪律）。
#   # 维护纪律：域名单/系数扩改须决策、与库态联动（新语料域入库须复核域键），
#   #   禁自动生效；坏条目（系数 ∉(0,1]/空域名）单条丢弃不整组回退。
# ---------------------------------------------------------------------------
# 案丙域内 doc 配额（2026-10-06 治理拨键批②案丙，默认 {}=零调用面；拨值随
# 部署窗 config 落——机制与拨值分离）；rag 段配置键：
#   "domain_doc_quota": {}   # 域内 doc 配额表（dict：{域名: 席位上限}）；空
#   #   dict/非 dict=关。拨板形态（2026-10-06 决策，随部署窗）：{"miit": 2}
#   #   ——治监管族内挤占（V5 残余红灯：C19=工信部令第35号同件 5 席压 36号令
#   #   正主；S1V-05=36号令附录8 族压附录6 正主；V4 案丙 doc≤2=唯一已仿真
#   #   覆盖方向；fam 粒度已否决勿实施）。
#   # 语义：命中域=块 rec 的 source_domain 归一（strip+lower）==键名 → 该域
#   #   内每 doc_id 在最终选席窗（同源折叠开时=折叠窗，否则 topk）至多占
#   #   N 席，超限块让位、深候选池补位——=① doc_quota_select（P0①，2026-09-29）
#   #   的域表参数化扩展（轻路径，非新选席机制；两遍制回补语义原样继承：
#   #   证据面绝不因配额缩水）。域表值覆盖 ① 全局档（更特异者胜）；exempt
#   #   豁免优先于两者。选席不动分：cos 原始分恒存，0.40 闸载体零侵蚀。
#   # 维护纪律：域名单/席位上限扩改须决策、与库态联动（监管新件/新语料域
#   #   入库须复核域键），禁自动生效；坏条目单条丢弃不整组回退。
# ---------------------------------------------------------------------------

# 制式信号内置规则（③）：signal_patterns 对 _spec_norm_text（小写+空白折叠，
# 不删空白——ASCII 词边界环视依赖空格在位）题面匹配；边界防误报——"3.5GHz"
# 不触发 5G 信号（前置 [.0-9] 负断言+hz 负前瞻），"5GHz"同理；规范号信号须带
# 三位小数（38.213 型），版本号 V18.10.0 不触发。双侧规则同时命中（跨制式
# 题面，如"4G和5G 互操作"）→ 歧义保护不压制。
SPEC_SUPPRESS_BUILTIN_RULES = (
    {"name": "nr_query_suppress_lte_docs",
     "signal_patterns": (r"(?<![a-z0-9])nr(?![a-z0-9])",
                         r"(?<![0-9.])5g(?!hz)(?![a-z0-9])",
                         r"(?<![0-9])38\.\d{3}"),
     "suppress_doc_contains": ("TS 36.", "TR 36.")},
    {"name": "lte_query_suppress_nr_docs",
     "signal_patterns": (r"(?<![a-z0-9])lte(?![a-z0-9])",
                         r"(?<![a-z0-9])e-?utra(?![a-z0-9])",
                         r"(?<![0-9.])4g(?!hz)(?![a-z0-9])",
                         r"(?<![0-9])36\.\d{3}"),
     "suppress_doc_contains": ("TS 38.", "TR 38.")},
)

# ---------------------------------------------------------------------------
# 期 1 路由分类器挂接（2026-09-29，默认关=现状逐字节不变；键义见件头注与
# 运营/设计稿-分层放行与路由-20260929.md §2.3"实现挂点"）；rag 段配置键：
#   "route_enabled": False        # 总开关：true 时 server chat 入口对拼接后
#   #   query 调 route_domain.classify 一次（mq 变体继承不重复分类），
#   #   retrieve(query, route_res=…) 按生效路由做选席约束；false/缺省=零调用
#   #   零收窄（route_res 恒 None，各路径与既往逐字节一致）
#   "route_min_confidence": 1     # 唯一域定向最低信号数（classify 侧消费；
#   #   坏值回 1、下限钳 1）
#   "route_conflict_policy": "fallback"  # D5 批档：仅 "fallback" 合法（priority
#   #   未启用；其他值/坏值一律回 fallback）
#   "route_vocab": None           # null=内置词表（D9：词表扩改须用户决策禁自动
#   #   生效；期 1 classify 签名不支持词表注入，本键观测位——非 list 回 null）
#   "route_light_topk": 3         # 期 2 档 A 轻检索 topk（期 1 观测位不消费；
#   #   坏值回 3、下限钳 1）
#   "route_table_facet": False    # 精确表域二级细分（chunk_type∈{table_row_group,
#   #   asn1_card}）；默认关=精确表域按 TS 全面不细分，防召回损失（细分属期 2）
#   "route_doc_direct": True      # doc 号直判通道开关（随 route_enabled 生效；
#   #   false=doc 引用只观测不参与判定）
# 契约（§2.4 硬门控+classify docstring）：生效路由只读 route 键 ∈ {domain,
#   doc_direct}；veto=1 时 classify 已保证 route="fallback"（doc_direct 键仅
#   观测禁收窄），rag 侧再设 veto 防御位（不一致输入零收窄）；检索后兜底=域
#   过滤后候选 <topk 或域内最大余弦 <score_threshold（0.40 闸值；关闸时按
#   DEFAULT_SCORE_THRESHOLD）→ 回退全量+fallback=1 [rag-route] 打点。
DEFAULT_ROUTE_MIN_CONFIDENCE = 1
DEFAULT_ROUTE_LIGHT_TOPK = 3

DEFAULT_RAG_CONFIG = {
    "enabled": False,
    "topk": DEFAULT_TOPK,
    "max_context_chars": DEFAULT_MAX_CONTEXT_CHARS,
    "store_path": DEFAULT_STORE_PATH,
    "timeout_seconds": DEFAULT_TIMEOUT_SECONDS,
    "embed_retry_times": 0,     # 2026-10-13：查询嵌入传输层失败重试次数（默认 0=旧行为）
    "embed_model": DEFAULT_EMBED_MODEL,
    "lexical_boost": False,
    "lexical_lambda": DEFAULT_LEXICAL_LAMBDA,
    "lexical_candidates": DEFAULT_LEXICAL_CANDIDATES,
    "hybrid_bm25_enabled": False,
    "bm25_k1": DEFAULT_BM25_K1,
    "bm25_b": DEFAULT_BM25_B,
    "hybrid_candidates": DEFAULT_HYBRID_CANDIDATES,
    "hybrid_fusion": "rrf",
    "hybrid_rrf_k": DEFAULT_HYBRID_RRF_K,
    "hybrid_bm25_weight": DEFAULT_HYBRID_BM25_WEIGHT,
    # ---- W2 词面限域门控（2026-10-08 D2 甲，默认关=现状逐字节一致；键义见
    # 常量段注释块。与 hybrid_bm25_enabled 双键互锁：总闸 false 时门控形不
    # 生效；词表扩改须决策、与库态联动，纪律同 cover_gate_vocab）----
    "hybrid_gated_enabled": False,           # 门控总开关（仅严格布尔 true 开）
    "hybrid_gate_vocab": None,               # 触发词表覆盖（null=内置词表）
    # ---- R 线二期 S1 词面通道键族（2026-10-17，默认全 null=现状逐字节不变；
    # 键义与合并/清洗/装载语义见常量段注释块）----
    "hybrid_gate_vocab_extra": None,         # 追加裸词面（OR 合并；null=零追加）
    "hybrid_gate_patterns_extra": None,      # 追加正则面（OR 合并；坏条单丢）
    "hybrid_gate_combo": None,               # 组合形 AND 面（[ctx,sig,conj?]）
    "query_preprocess_entries": None,        # 查询预处理词条（null=q'=q 恒等）
    # ---- ④b 分数带门控（2026-10-18 检索召回优化组合案，默认 null=关=现状
    # 逐字节不变；键义见常量段注释块；仅词面门控命中时被消费）----
    "hybrid_gate_band_t": None,              # 分数带阈值 t（null=关；float∈(0,1]）
    "mq_enabled": False,
    "mq_n_variants": multiquery.DEFAULT_MQ_N_VARIANTS if multiquery else 2,
    "mq_model": multiquery.DEFAULT_MQ_MODEL if multiquery else "qwen3.8-flash",
    "mq_timeout_seconds": multiquery.DEFAULT_MQ_TIMEOUT_SECONDS if multiquery else 3.0,
    "mq_wall_clock": False,
    "mq_single_variant": False,     # 批B4：true=单变体配方（覆盖 mq_n_variants 为 1）
    "mq_variant_timeout": None,     # 批B4：生成阶段秒预算；None=回退 mq_timeout_seconds
    "mq_wall_timeout": None,        # 批B4：mq 整体墙钟秒预算；None=无整体预算（旧行为）
    # ---- mq condense 多轮独立化改写（2026-10-24 施工，默认全关=零调用零行为；
    # 键义/判据见 multiquery.py condense 段+建库/work/mq施工-20261024/判据预登记）----
    "mq_condense_enabled": False,   # 总开关（true=有前史时末轮+历史 flash 独立化改写
                                    #   成 c0 路挂 q0 后；不挤 MQ_MAX_N_VARIANTS 帽）
    "mq_condense_model": (multiquery.DEFAULT_MQ_MODEL if multiquery
                          else "qwen3.8-flash"),      # flash 档（禁旗舰）
    "mq_condense_timeout": (multiquery.DEFAULT_MQ_CONDENSE_TIMEOUT
                            if multiquery else 3.0),  # 单段秒预算（与 mq 墙钟取小）
    "mq_condense_history_turns": (multiquery.DEFAULT_MQ_CONDENSE_HISTORY_TURNS
                                  if multiquery else 4),   # 前史消息条数帽
    "mq_condense_history_chars": (multiquery.DEFAULT_MQ_CONDENSE_HISTORY_CHARS
                                  if multiquery else 1200),  # 前史字符帽（保尾截头）
    "score_threshold": DEFAULT_SCORE_THRESHOLD,
    "faiss_enabled": False,         # 2026-09-26：faiss IndexFlatIP 加速件（默认关=现状不变）
    "embed_monthly_budget_enabled": False,  # 2026-09-28：月度预算闸（默认关=现状不变）
    "embed_monthly_budget_cny": DEFAULT_EMBED_MONTHLY_BUDGET_CNY,
    "embed_monthly_cap_cny": DEFAULT_EMBED_MONTHLY_CAP_CNY,
    "embed_ledger_path": DEFAULT_EMBED_LEDGER_PATH,
    "clause_family_rerank": True,            # 2026-09-28 S1 治理乙：默认开（选项一决策）
    "clause_family_rerank_words": "full",    # 乙词表档位 full|core（坏值回 full）
    "cover_gate_enabled": True,              # 2026-09-28 S1 治理丙：默认开（选项一决策）
    "cover_gate_vocab": None,                # 丙词表覆盖（null=内置安全词形）
    # ---- P0 检索层去挤占（2026-09-29，全部默认关=现状逐字节不变；键义见上方注释块）----
    "doc_quota_enabled": False,              # ① doc 配额（同 doc_id 席位上限，改成员）
    "doc_quota_max": DEFAULT_DOC_QUOTA_MAX,
    "doc_quota_exempt_docs": None,           # 配额豁免 doc 子串清单（null=无豁免）
    "table_downweight_enabled": False,       # ② 38.133 表降权（Annex 表格块乘系数）
    "table_downweight_factor": DEFAULT_TABLE_DOWNWEIGHT_FACTOR,
    "table_downweight_docs": None,           # null=内置 ("38.133",)
    "table_downweight_scope": "annex",       # annex=仅 Annex 表格块 | all=整 doc
    "spec_suppress_enabled": False,          # ③ 制式信号压制（NR↔LTE 异制式块乘系数）
    "spec_suppress_factor": DEFAULT_SPEC_SUPPRESS_FACTOR,
    "spec_suppress_rules": None,             # null=内置 SPEC_SUPPRESS_BUILTIN_RULES
    "decrowd_candidates": DEFAULT_DECROWD_CANDIDATES,   # ①②③ 共享深候选池
    "retrieval_snapshot_dir": None,          # ④ 检索快照目录（null=关；本地诊断件）
    # ---- 期 1 路由分类器挂接（2026-09-29，默认关=现状逐字节不变；键义见上方注释块）----
    "route_enabled": False,                  # 总开关（server 分类一次+rag 选席约束）
    "route_min_confidence": DEFAULT_ROUTE_MIN_CONFIDENCE,
    "route_conflict_policy": "fallback",     # D5 批档：仅 fallback 合法
    "route_vocab": None,                     # null=内置词表（D9 决策纪律；期 1 观测位）
    "route_light_topk": DEFAULT_ROUTE_LIGHT_TOPK,   # 期 2 档 A 键（期 1 观测位）
    "route_table_facet": False,              # 精确表域细分（默认关=TS 全面不细分）
    "route_doc_direct": True,                # doc 号直判通道（随 route_enabled 生效）
    # ---- 乙案族选席（2026-09-29，默认关=现状逐字节不变；键义见上方注释块）----
    "family_select_enabled": False,           # 族选席总开关（R1-R5 规则组）
    "family_select_scope": DEFAULT_FAMILY_SELECT_SCOPE,
    "family_select_words": "full",            # 负项词表档位 full|core（复用乙层词表）
    "clone_fold_min_margin": DEFAULT_CLONE_FOLD_MIN_MARGIN,
    # ---- 试点 2 元数据过滤（2026-10-01，默认关=现状逐字节不变；键义见上方注释块）----
    "meta_filter_v1": False,                  # 元数据过滤总开关（同族陈旧降权）
    "meta_stale_factor": DEFAULT_META_STALE_FACTOR,
    # ---- 案甲域降权（2026-10-06 治理拨键批①，默认 {}=现状逐字节不变；键义见上方
    # 注释块。机制与拨值分离：拨板值 {"telecomhall": 0.5} 随部署窗 config 落，
    # 依据=运营/扩容-V4-挤占治理仿真呈报-20261006.md 案甲；库扩容联动复核口径
    # 同 spec_suppress_rules/cover_gate_vocab 系〔新语料域入库须复核域键〕）----
    "domain_downweight": {},                  # {域名: 系数}（{}=关；系数 ∈(0,1]）
    # ---- 案丙域内 doc 配额（2026-10-06 治理拨键批②案丙，默认 {}=现状逐字节
    # 不变；键义见上方注释块。机制与拨值分离：拨板值 {"miit": 2} 随部署窗
    # config 落，依据=运营/扩容-V4-挤占治理仿真呈报-20261006.md 案丙+V5 残余
    # 红灯归因（建库/logs/扩容-V5-终态复验-20261006.md）；库扩容联动复核口径
    # 同 domain_downweight 系〔监管新件/新语料域入库须复核域键〕）----
    "domain_doc_quota": {},                   # {域名: 席位上限}（{}=关；≥1）
    # ---- H 线查询-族定向加权（2026-10-14 F线H 排序治理，默认 []=现状逐字节
    # 不变；键义见件头注 2026-10-14 H 线段与 clean_query_doc_factor_params
    # docstring。机制与拨值分离：规则表扩改须决策、与库态联动（新语料域/新
    # 合成卡族入库须复核规则目标面），禁自动生效；坏条目单条丢弃不整组回退）----
    "query_doc_factor": [],                   # list[dict] 规则表（[]=关）
    # ---- ADR-0018 融合级配额段（2026-10-06 R3C，默认关=现状逐字节不变；键义
    # 见件头注 2026-10-06 R3C 段。机制与拨值分离：部署窗拨 mq_fused_select_enabled
    # =true＋mq_fused_candidates=60（甲2 深窗）；回滚=单键 false 秒级，keep/
    # 融合窗放粗随主键关断数值回退（缺省=现状表达式）。路级 keep 加深无独立键
    # ——载体=decrowd_candidates（现值 60 已拨，读 _decrowd["candidates"]）----
    "mq_fused_select_enabled": False,         # 融合级配额段总开关（仅严格布尔 true 开）
    "mq_fused_candidates": None,              # 融合池深（null=回退 fold_win or topk 零漂移）
    # ---- 弱注入辅助闸（2026-10-06 R3C，默认 {}=现状逐字节不变；键义见件头注
    # 2026-10-06 R3C 段。拨形 {"enabled": true, "t_weak": 0.65, "flat_delta":
    # 0.06, "action": "annotate"} 随部署窗 config 落；T_weak/Δ_flat 终值归标定轮
    # 冻结（设计稿 §四.5）；回滚=键回 {} 或删键（秒级）----
    "weak_gate": {},                          # {}=关；嵌套键域 enabled/t_weak/flat_delta/action
    # ---- 同源折叠（2026-10-03 检索链尾键，默认关=现状逐字节不变）----
    # 语义=fold1 单席族帽：挂 clause_family_rerank 之后、终 top5 截断之前，
    # 作用于已排序列表前 10 窗（不足 10 取全部）——族键=doc_id+locator 主干
    # （先剥尾 "(pN)" 再剥尾 "行组N[-–]N"），同族留窗内最前 1 席、超席者殿后
    # （保序，同集合置换），折叠序取前 topk=终证据集。依据与判卷=运营/呈报-
    # 纯折叠第二钥匙-20261003.md（过程日志三节 26②同日终拍采纳+ADR-0009 调线
    # 记录在档；试点=建库/work/纯折叠试点-20261003/ 三判据全过）。
    "same_source_fold_enabled": False,        # 总开关（false/缺省/非法值=关）
    # ---- 同源折叠族键扩展（2026-10-08 W4 D5 甲，默认 "tables"=现状逐字节
    # 一致；扩改须决策=过程日志三节 44 D5 甲→用户 2026-10-08 傍晚批）。scope=
    # "tables+asn1" 时 asn1_card 块族帽扩展（题面锚定形，仿真定形=建库/
    # work/词面通道复放-20261008/fold扩展-仿真定形-20261008.md：R01 t310
    # 位次 5→1、S1 23 行零翻坏）：
    #   ① 版本尾主干并族——locator 剥尾 "-rN/-RN" 后同 doc 同主干为一族
    #   （跨 IE 同名卡同并；tables 态同名 locator 已并族为其子集），族内
    #   留首席其余殿后；
    #   ② 异名兄弟并族——同 doc 同 IE（content "所属 IE：" 标记推导；hit
    #   rec 的 META_FIELDS 无 section）异名参数卡为一族，族内有题面锚
    #   （主干 ∈ 题面归一文本 _ws_norm_text 同器，主干长≥4 防泛词弱锚）
    #   时只留锚定主干首席、非锚成员殿后；族内无锚不动（零改面）。非
    #   asn1 块族键=tables 形不变；折叠全序仍=同集合置换。----
    "same_source_fold_scope": "tables",       # tables（默认）| tables+asn1
    # ---- B-evict 定向清位（2026-10-03 检索链尾键，默认关=现状逐字节不变）----
    # 语义=丙闸扩型候选B：挂乙重排+同源折叠后、终 topk 截断与闸门段之前——
    # 题面命中 B_EVICT_VOCAB（七词冻结，见常量段）才激活，rank1 负项基准逐出
    # 窗内负项严格超基准的块，幸存者原序取前 topk（rank1 恒幸存；W 空=零改动）。
    # 词表冻结纪律与 [rag-evict] 打点格式见件头注 2026-10-03 段；依据与判卷=
    # 运营/呈报-丙闸扩型候选B-20261003.md（跑测=建库/work/排序优化四期-20261003/
    # 丙闸跑测/，evict 语义以跑测脚本-20261003.py 为准）。
    "b_evict_enabled": False,                 # 总开关（false/缺省/非法值=关）
    # ---- 表降权白名单（2026-10-03，默认 []=现状逐字节不变）----
    # ②表降权消费位：locator 正则（re.search）命中白名单任一值的块静默跳过
    # 表因子（不乘 table_factor；③制式压制不受影响、cosine 闸载体不变、无新
    # 打点）。白名单正则扩值须决策（逐表登记制：36.101/36.213 升版或新表号
    # 入库须复核）；坏正则单条丢弃（口径贴 _clean_spec_rules，不整组回退）；
    # null/非 list=无豁免。依据=建库/work/排序优化四期-20261003/36101臂Ⅱ/
    # 判效报告-20261003.md §十（决策双值=该档 arm2w 键面）。
    "table_downweight_whitelist": [],         # locator 正则清单（[]=无豁免）
    # MMR 向量去冗余两键（2026-10-23 波3 工程件）不入 DEFAULT_RAG_CONFIG
    # ——直通键先例=2026-10-23 bm25_persist 同款（键面守卫钉死键增量：
    # tests/test_rag_evict_whitelist-20261003.py / test_同源折叠扩展.py 的
    # keyface delta 断言面）；clean_mmr_params 容忍缺键（缺省=关+默认 λ
    # 0.7），键义/挂点纪律见件头注 2026-10-23 段。
}

# mq 预算键上界（坏值钳制口径贴批A server._depth_config 的 timeout 键：越界
# (0,30] 回退，防误配零预算/长挂起）
MQ_BUDGET_MAX_SECONDS = 30.0


# ---------------------------------------------------------------------------
# 数值基础：点积（math.sumprod 为 3.12+ C 级实现，老版本退化为 zip 生成器）
# ---------------------------------------------------------------------------
if hasattr(math, "sumprod"):
    def _dot(a, b):
        return math.sumprod(a, b)
else:  # pragma: no cover
    def _dot(a, b):
        return sum(x * y for x, y in zip(a, b))


def _default_log(line: str) -> None:
    print(line, flush=True)


# ---------------------------------------------------------------------------
# 装载加速 sidecar（2026-09-24 装载瘦身选装件）：jsonl → bin+meta 二进制紧凑缓存
#
# 动机：jsonl 全量装载需逐行 json.loads + 1024 维文本浮点解析（本地 ~10-12s，
# 云端 2C2G 实测 25-35s）；sidecar 把已归一化向量以 float32 小端裸块存 .bin
# （count×dim×4B，无头）、块文本元数据存 .meta.json，装载=一次裸读+一次 json
# 解析，秒级完成（全量库实测见 运营/装载瘦身-20260924.md）。
# 纪律：
# - 默认"文件不存在=不生效"：不建 sidecar 时 load_store 行为与无本节完全一致；
# - 校验失败（源 size/mtime_ns 变化=库在飞续写或换库、bin 长度不符、meta 坏）
#   一律自动退回 jsonl 逐行装载，绝不抛出、绝不装载过期数据；
# - 手动构建：`python rag.py --build-sidecar <store_path>`（幂等覆盖，写坏可删
#   两件重建）；服务端不自动写 sidecar（云端部署不新增写动作，是否启用由
#   运维决策后落件）。
# ---------------------------------------------------------------------------
SIDECAR_SUFFIX = ".f32"
SIDECAR_VERSION = 2  # v2: META_FIELDS 扩至八字段（乙案 corpus_type/chunk_type/source_domain）


def sidecar_paths(store_path, bin_path=None, meta_path=None):
    """store 路径 → (bin_path, meta_path)（显式传入者优先）。"""
    return (bin_path or store_path + SIDECAR_SUFFIX + ".bin",
            meta_path or store_path + SIDECAR_SUFFIX + ".meta.json")


def build_sidecar(recs, dim, store_path, stats=None, bin_path=None, meta_path=None):
    """已装载 recs → 写 sidecar 两件（幂等覆盖）→ (bin_path, meta_path)。

    - 向量连排为 float32 小端裸块（字节序由 array.tofile 本机写出，读取侧
      非 little-endian 机自动 byteswap；count/dim 不入 bin 头，由 meta 承载）；
    - meta 记源文件 size/mtime_ns（过期校验锚点）+ 装载统计 + META_FIELDS 元数据
      （content 原文入 JSON，可读可 debug；2026-09-29 乙案扩至八字段）；
    - 只写 sidecar 两件与 meta 临时文件（os.replace 原子换入），不碰 store 原件；
      写失败抛异常由调用方自理。
    """
    bp, mp = sidecar_paths(store_path, bin_path, meta_path)
    vec = array("f")
    rows = []
    for r in recs:
        vec.extend(r["vec"])
        rows.append([r.get(k, "") for k in META_FIELDS])
    tmp_bin = bp + ".tmp"
    with open(tmp_bin, "wb") as f:
        if len(vec):
            vec.tofile(f)
    os.replace(tmp_bin, bp)
    st = os.stat(store_path)
    meta = {"version": SIDECAR_VERSION, "src": os.path.abspath(store_path),
            "src_size": st.st_size, "src_mtime_ns": st.st_mtime_ns,
            "count": len(recs), "dim": dim, "fields": list(META_FIELDS),
            "total_lines": (stats or {}).get("total_lines", len(recs)),
            "bad_lines": (stats or {}).get("bad_lines", 0),
            "rows": rows}
    tmp_meta = mp + ".tmp"
    with open(tmp_meta, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)
    os.replace(tmp_meta, mp)
    return bp, mp


def _try_load_sidecar(store_path, bin_path=None, meta_path=None):
    """校验并读 sidecar → (recs, dim, stats) 或 None（不适用/过期/坏 → None）。

    任何异常（文件缺失/权限/JSON 坏/长度不符）都吞掉返回 None，调用方退
    jsonl 装载——sidecar 是纯加速件，绝不改变装载语义。
    """
    try:
        bp, mp = sidecar_paths(store_path, bin_path, meta_path)
        st = os.stat(store_path)
        with open(mp, encoding="utf-8") as f:
            meta = json.load(f)
        if not isinstance(meta, dict) or meta.get("version") != SIDECAR_VERSION:
            return None
        # 过期校验：源文件 size/mtime 与构建时不一致（在飞续写/换库/被改）即弃
        if (meta.get("src_size") != st.st_size or
                meta.get("src_mtime_ns") != st.st_mtime_ns):
            return None
        count, dim = meta.get("count"), meta.get("dim")
        if not (isinstance(count, int) and not isinstance(count, bool) and count >= 0
                and isinstance(dim, int) and not isinstance(dim, bool) and dim > 0):
            return None
        if os.path.getsize(bp) != count * dim * array("f").itemsize:
            return None
        vecs = array("f")
        with open(bp, "rb") as f:
            vecs.fromfile(f, count * dim)
        if sys.byteorder != "little":  # pragma: no cover —— 大端机字节序对齐
            vecs.byteswap()
        rows = meta.get("rows")
        if not isinstance(rows, list) or len(rows) != count:
            return None
        recs = []
        for k, row in enumerate(rows):
            if not isinstance(row, list) or len(row) != len(META_FIELDS):
                return None
            rec = {"vec": vecs[k * dim:(k + 1) * dim]}
            for name, val in zip(META_FIELDS, row):
                rec[name] = val if isinstance(val, str) else ""
            recs.append(rec)
        stats = {"path": store_path, "total_lines": meta.get("total_lines", count),
                 "loaded": len(recs), "bad_lines": meta.get("bad_lines", 0),
                 "dim": dim, "missing": False, "sidecar": True}
        return recs, dim, stats
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 向量库加载（只读、按行容错）
# ---------------------------------------------------------------------------
def load_store(path, use_sidecar=True, sidecar_bin=None, sidecar_meta=None):
    """读 embeddings.jsonl → (recs, dim, stats)。

    - 每行一个 JSON 对象：chunk 元数据 + "embedding": [float, ...]。
    - 加载时归一化（float64 计算后存 float32）为单位向量存 array('f')；坏行
      （JSON 解析失败/无 embedding/非数值/维度不符/零向量）只跳过并计数，
      不中断——库文件在飞续写期间读到中间态行属预期（口径同
      建库/scripts/retrieve.py）。
    - 维度以首条合法向量定标，后续不一致按坏行跳过。
    - 文件不存在 → 空库（recs=[]，stats["missing"]=True），不抛异常。
    - recs 每条：{"vec": 归一化 array('f')（float32，4B/维）, META_FIELDS...}
    - use_sidecar=True（默认）且存在有效 sidecar（build_sidecar 产物）时走二
      进制快装（stats 多一 "sidecar": True 键）；sidecar 缺失/过期/坏一律退
      本函数的 jsonl 逐行路径——两路径产出 recs 逐位一致（sidecar 存的就是
      jsonl 路径算出的 float32 值）。sidecar_bin/meta 可显式指定缓存件位置
      （默认 store 同目录同名加 .f32 后缀）。

    内存口径（2026-09-24 装载瘦身）：归一化仍在 float64 里算完（x/n 除法与
    模长 n 均为双精度），仅落存时转 float32 array——每行 1024 维 4KB（tuple
    形态每行 ~32KB：1024 个 float 对象 24B/个 + 指针槽 8B/个），26,426 行向量
    本体 ~826MB→~108MB。检索打分（search 的 _dot=sumprod）取 array 元素时
    自动升 double 参与 float64 累加，行为与 tuple 逐点一致（差仅来自落存
    舍入 ~1e-7 量级，排序一致性验收见 运营/装载瘦身-20260924.md）。
    """
    recs = []
    stats = {"path": path, "total_lines": 0, "loaded": 0, "bad_lines": 0,
             "dim": None, "missing": False}
    if not os.path.exists(path):
        stats["missing"] = True
        return recs, None, stats
    if use_sidecar:
        got = _try_load_sidecar(path, sidecar_bin, sidecar_meta)
        if got is not None:
            return got
    dim = None
    with open(path, encoding="utf-8") as f:
        for line in f:
            stats["total_lines"] += 1
            line = line.strip()
            if not line:
                stats["bad_lines"] += 1
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                stats["bad_lines"] += 1
                continue
            if not isinstance(obj, dict):
                stats["bad_lines"] += 1
                continue
            emb = obj.get("embedding")
            if not isinstance(emb, list) or not emb or not all(
                    isinstance(x, (int, float)) and not isinstance(x, bool) for x in emb):
                stats["bad_lines"] += 1
                continue
            if dim is None:
                dim = len(emb)
            elif len(emb) != dim:
                stats["bad_lines"] += 1
                continue
            n = math.sqrt(_dot(emb, emb))
            if not math.isfinite(n) or n == 0.0:  # 零向量/含 NaN 无法定义余弦
                stats["bad_lines"] += 1
                continue
            rec = {"vec": array("f", (x / n for x in emb))}  # float64 归一化后落存 float32
            for k in META_FIELDS:
                v = obj.get(k)
                rec[k] = v if isinstance(v, str) else ""
            recs.append(rec)
    stats["loaded"] = len(recs)
    stats["dim"] = dim
    return recs, dim, stats


# ---------------------------------------------------------------------------
# 余弦检索（纯标准库）
# ---------------------------------------------------------------------------
def search(query_vec, recs, topk=DEFAULT_TOPK):
    """余弦 top-k 检索 → [hit, ...]（hit={"rank","score","rec","idx"}）。

    - query_vec 原始向量（加载时库向量已归一化，这里归一化 query 后点积）。
    - 排序 (-score, 库内行序)：同分 tie-break 确定性。
    - idx=库内行序（doc 身份，混合融合 fuse_hits 按它对齐两路；既有调用方可忽略）。
    - recs 为空（库空/未加载）→ None，调用方据此退裸答。
    - 维度不符/零向量 → ValueError（retrieve 兜底转 None；独立调用方需自理）。
    """
    if not recs:
        return None
    dim = len(recs[0]["vec"])
    if not isinstance(query_vec, (list, tuple)) or len(query_vec) != dim:
        raise ValueError(f"query 向量维度与库维度不符（期望 {dim}）")
    # 求模=math.hypot 缩放算法（2026-10-08 修复平方下溢：|x|<~2.2e-162 时
    # x·x 下溢 0 → 误判零向量；正常域与旧 sqrt 式一致至 1 ulp（2000 例采样
    # 实测最大相对偏差≈2.2e-16）。边界锁=tests/test_property.py A5）
    n = math.hypot(*query_vec)
    if not math.isfinite(n) or n == 0.0:
        raise ValueError("query 向量为零向量，无法计算余弦")
    qn = [x / n for x in query_vec]
    scored = [(_dot(qn, r["vec"]), i) for i, r in enumerate(recs)]
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [{"rank": rank, "score": score, "rec": recs[i], "idx": i}
            for rank, (score, i) in enumerate(scored[: max(1, int(topk))], 1)]


# ---------------------------------------------------------------------------
# faiss IndexFlatIP 加速件（默认关，2026-09-26 接入；RagService._search_cos 消费）
#
# 同型口径（对拍前提，建库/logs/faiss对拍-20260926.md §一）：库向量本就是
# float64 归一化后落存的 float32（load_store/sidecar 两路径产出逐位一致），
# IndexFlatIP 点积=余弦，库侧 np.frombuffer 位拷贝零转换零漂移；查询侧与
# 纯余弦路径同款 float64 归一化（math.hypot 求模+除法；2026-10-08 下溢修复同步）后转 float32 入
# faiss——两路唯一精度差=查询 float32 落存与 faiss float32 累加 vs 生产全程
# float64 累加（对拍实测 max|Δscore|=1.7e-07，60/60 排序逐位一致）。
# 内存纪律：不物化整库 numpy 矩阵，逐行 add 入索引（峰值=recs 向量体+索引
# 单份拷贝，无矩阵过渡态）；索引本体=向量体单份拷贝（44871×1024×4B≈175MB，
# 对拍报告 §五），与 array('f') 各持一份、不省也不费。
# ---------------------------------------------------------------------------
def build_faiss_index(recs, dim):
    """已装载 recs → faiss.IndexFlatIP（faiss/numpy 延迟导入，异常原样抛出）。

    - 调用方：RagService._load（faiss_enabled 开且库非空时）；独立调用需
      自理异常——本函数是纯构造件，降级语义在调用方。
    - 逐行 np.frombuffer(rec["vec"]) 位拷贝（array('f') 缓冲区即 float32
      小端裸块，零转换零漂移）；行维度与 dim 不符=坏数据，抛 ValueError。
    - faiss/numpy 未装（ImportError）或任何构造异常原样上抛，由 _load 捕获
      打 [rag-faiss] degrade 退纯余弦（faiss_enabled 默认关时零 import 成本）。
    """
    import numpy as np
    import faiss  # 延迟导入：默认关路径不依赖、零 import 开销
    index = faiss.IndexFlatIP(dim)
    row = np.empty((1, dim), dtype=np.float32)
    for rec in recs:
        v = rec["vec"]
        if len(v) != dim:
            raise ValueError(f"rec 向量维度不符（期望 {dim}，得 {len(v)}）")
        row[0] = np.frombuffer(v, dtype=np.float32)
        index.add(row)
    return index


# ---------------------------------------------------------------------------
# 词法重排（lexical boost）：纯标准库、确定性、零 API（2026-09-17 迭代）
#
# 动机：验收冒烟 S08/S09/S16/S17 暴露"中文题面对英文表格/定义块"的余弦排序失分
# ——目标块在库但排不进 top-5/top-10。重排对余弦 top-N 候选做二次打分：
#   合成分 = 余弦 + λ × 词法重合度 ∈ [0,1]，按 (-合成分, 余弦位次) 排序。
#
# 题面信号提取（lexical_signals，一次提取逐候选复用）：
#   1) 规范号（如 36.214 / TS 38.215）：权重 2.0，最强信号，匹配 doc_id/locator/content；
#   2) 技术标识/缩写词（ASCII 词元）：
#      - 含数字或大小写混合的标识符（t310 / a3-Offset / maxHARQ-Tx / 5G）权重 1.5；
#      - 全大写缩写词（RSRP / HARQ / NR）权重 1.0；纯小写英文词权重 0.3；
#      - 纯数字词元（≥4 位权重 1.2，3 位 0.4，≤2 位丢弃防噪）；
#      - 大小写敏感命中全额计分，仅大小写不敏感命中计 0.3 倍（防大小写变体漏配，
#        如题面 T310 vs ASN.1 卡内 t310）；
#   3) 中文关键词：去功能词后按字组（bigram）匹配，每字组权重 0.15。
# 词法分 = Σ命中权重 / Σ信号权重；题面无任何信号（纯功能词）→ 0.0，重排退化余弦序。
# ---------------------------------------------------------------------------
_SPEC_NUM_RE = re.compile(r"\b(3[68]\.\d{3})\b")
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*")
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")
_CJK_FILLERS = (  # 功能词（疑问/连接/泛化词），剥除后不参与字组信号
    "什么", "多少", "哪些", "如何", "怎么", "怎样", "分别", "以及", "要求", "规定",
    "定义", "指标", "参数", "取值", "枚举", "达到", "以下", "方面", "实现", "定下",
    "的", "了", "是", "在", "中", "与", "和", "或", "及", "到", "各", "有", "每",
    "个", "为", "基于", "之间", "承载",
)


def _ascii_token_weight(tok):
    """ASCII 词元权重；返回 None=丢弃（纯 ≤2 位数字，噪声面大）。"""
    if tok.isdigit():
        if len(tok) >= 4:
            return 1.2
        return 0.4 if len(tok) == 3 else None
    if tok.isalpha() and tok.isupper() and len(tok) >= 2:
        return 1.0
    if any(c.isdigit() for c in tok):
        return 1.5
    if len(tok) >= 4 and re.search(r"[a-z][A-Z]", tok):  # 驼峰标识（dB/dBm 类短词除外）
        return 1.5
    return 0.3


def lexical_signals(query):
    """题面 → 信号列表 [(kind, key, weight), ...]（去重、确定性）。"""
    sigs, seen = [], set()

    def add(kind, key, weight):
        k = (kind, key)
        if k not in seen:
            seen.add(k)
            sigs.append((kind, key, weight))

    spec_spans = []
    for m in _SPEC_NUM_RE.finditer(query):
        add("spec", m.group(1), 2.0)
        spec_spans.append(m.span())
    masked = list(query)  # 规范号区间打码后再切 ASCII 词元，防 36/214 片段噪声
    for s, e in spec_spans:
        for i in range(s, e):
            masked[i] = " "
    masked = "".join(masked)
    for m in _TOKEN_RE.finditer(masked):
        tok = m.group(0)
        w = _ascii_token_weight(tok)
        if w is not None:
            add("ascii", tok, w)
    for run in _CJK_RUN_RE.findall(query):
        for filler in _CJK_FILLERS:
            run = run.replace(filler, "|")
        for piece in run.split("|"):
            for i in range(len(piece) - 1):
                add("cjk", piece[i:i + 2], 0.15)
    return sigs


def lexical_score(query, text, sigs=None):
    """题面与块文本的词法重合度 ∈ [0,1]。

    text 为块的 doc_id+version+locator+content 拼接（见 _rec_text）；
    sigs 可预生成复用（同题面多候选场景）。无信号 → 0.0。
    """
    if sigs is None:
        sigs = lexical_signals(query)
    if not sigs:
        return 0.0
    low = text.lower()
    earned = total = 0.0
    for kind, key, weight in sigs:
        total += weight
        if kind == "spec":  # 规范号带数字边界防前缀误配（36.214 ≠ 36.2141）
            if re.search(r"(?<![0-9])%s(?![0-9])" % re.escape(key), text):
                earned += weight
        elif kind == "cjk":
            if key in text:
                earned += weight
        else:  # ascii：大小写敏感全额，仅不敏感命中计 0.3 倍
            if key in text:
                earned += weight
            elif key.lower() in low:
                earned += weight * 0.3
    return earned / total if total > 0 else 0.0


def _rec_text(rec):
    """词法匹配文本：doc_id+version+locator+content（缺失字段空串）。"""
    return " ".join(str(rec.get(k) or "") for k in ("doc_id", "version", "locator", "content"))


def rerank_hits(query, hits, lam=DEFAULT_LEXICAL_LAMBDA, text_of=None):
    """余弦候选二次词法打分 → 重排后的 hits（与 search 输出同形态）。

    - hits 为 search() 返回形态 [{"rank","score","rec"},...]（rank=余弦位次）；
      返回逐条 dict 拷贝，score=合成分（余弦+λ×词法），另附 cosine/lexical，
      rank 按 (-合成分, 余弦位次) 重编 1..n——同分 tie-break 确定性。
    - λ=0 时 IEEE 上 score+0.0×lex ≡ score、排序键退化为余弦序，等价纯余弦。
    - text_of(hit)→匹配文本，默认取 hit["rec"] 四字段拼接；调用方可用别的
      hit 形态（如离线检索扁平 hit）注入自定义取文函数。
    - lam<0 视为 0（防误配）；hits 空 → 原样返回。
    """
    if not hits:
        return []
    lam = max(0.0, float(lam))
    get_text = text_of or (lambda h: _rec_text(h["rec"]))
    sigs = lexical_signals(query)
    out = []
    for h in hits:
        rec_score = float(h["score"])
        lex = lexical_score(query, get_text(h), sigs) if sigs else 0.0
        item = dict(h)
        item["cosine"] = rec_score
        item["lexical"] = lex
        item["score"] = rec_score + lam * lex
        out.append(item)
    out.sort(key=lambda h: (-h["score"], h["rank"]))  # rank 此刻仍是余弦位次
    for i, h in enumerate(out, 1):
        h["rank"] = i
    return out


# ---------------------------------------------------------------------------
# S1 负控治理乙：同款族父条让位+限定词/主体词负项重排（order-only，2026-09-28）
#
# 机制（方案 §二路径乙；离线模拟对齐件=建库/scripts/s1_negctrl_eval.py
# clause_family_rerank_sim，语义移植保持一致）：
#   ① 父条让位——top-k 内同款族（同条款号）父块与子块并存时，父条（数值歧义
#      源：父条文本=各子款超集，常含双值）让位至证据集尾部；
#   ② 限定词/主体词负项重排——题面高权重信号（封闭小词表，core/full 两档）
#      在块文本缺失时记负项，按（负项数升序，通道序）重排；负项无相对差异时
#      退化回通道原序（方案对 07/10 型题的已知风险形态，如实保留）。
# order-only 硬约束：只重排证据集内部次序、不改成员集合——gate_cosine 读集内
# 最大余弦、build_evidence 按新次序编号 [出处N]，top-5 命中型判定结构性零误伤
# （0.40 薄余量零侵蚀；离线验证档 20 题+A/B/Y 逐题断言过）。
# ---------------------------------------------------------------------------
_CLAUSE_SUB_SUFFIX_RE = re.compile(r" 款\d+$")


def _ws_norm_text(s):
    """词法匹配归一：去全部空白+小写（CJK 无空格语义，ASCII 大小写不敏感——
    "IP 电话"与"IP电话"可互配）。"""
    return re.sub(r"\s+", "", s or "").lower()


def _clause_parent_flag(loc, locs):
    """父条判定：loc 无款号后缀，且证据集内存在 loc+' 款N' 形态的子款。"""
    if not loc or _CLAUSE_SUB_SUFFIX_RE.search(loc):
        return False
    prefix = loc + " 款"
    return any(loc.startswith(prefix) for loc in locs)


def clause_family_rerank(query, hits, words_mode="full"):
    """同款族父条让位+限定词/主体词负项重排（order-only）→ 重排后的 hits。

    - hits 为任一通道输出形态 [{"rank","score","rec"},...]（rank=通道位次）；
      返回逐条 dict 拷贝（输入不被修改），rank 按（父条标志，负项数，-score，
      原位次）重编 1..n——父条绝对让位至尾部，非父条按题面高权重信号缺失数
      升序、同负项回通道序（score 为通道排序分：纯余弦态=余弦，lexical/mq 态
      =通道合成分，同分以原位次 tie-break 确定性）；
    - 块文本口径=_rec_text（doc_id+version+locator+content 拼接），归一=_ws_norm_text；
    - words_mode：full=core+指标概念词（默认，离线验证档口径）；core=封闭小词表；
    - 只重排次序不改成员：集合恒等、gate_cosine 分数恒等（结构性保证，测试断言）；
      hits 空 → 原样返回。
    """
    if not hits:
        return hits
    qn = _ws_norm_text(query)
    vocab = CLAUSE_RERANK_WORDS_CORE + (
        CLAUSE_RERANK_WORDS_METRIC if words_mode == "full" else ())
    sigs = [_ws_norm_text(w) for _, w in vocab if _ws_norm_text(w) in qn]
    keyed = []
    for h in hits:
        rec = h["rec"]
        text = _ws_norm_text(_rec_text(rec))
        negs = len([w for w in sigs if w not in text])
        parent = _clause_parent_flag(str(rec.get("locator") or ""),
                                     [str(x["rec"].get("locator") or "") for x in hits])
        item = dict(h)
        keyed.append((1 if parent else 0, negs, -float(h["score"]), h["rank"], item))
    keyed.sort(key=lambda t: t[:4])
    out = [t[4] for t in keyed]
    for i, h in enumerate(out, 1):
        h["rank"] = i
    return out


# ---------------------------------------------------------------------------
# P0 检索层去挤占（decrowd）①②③ 核心纯函数（2026-09-29，默认关=零调用面；
# 键义/闸分纪律/词表联动纪律见上方常量段注释与件头注 2026-09-29 段）
#
# hit 形态约定：与 clause_family_rerank 同款 [{"rank","score","rec"},...]
# （rec 含 doc_id/locator）；离线扁平 hit（建库/scripts/retrieve.py 形态）须由
# 调用方挂 rec shim（h["rec"]=全字段 meta dict）后使用——同 rerank_hits 的
# text_of 注入先例，本段函数不另设取文参数。
# ---------------------------------------------------------------------------
def _norm_decrowd_factor(v, default):
    """降权/压制系数清洗：非数字/NaN/≤0/>1 → 默认档（1.0=等价关，属合法值；
    口径贴 _norm_budget_cny 先例：误配回已知安全档）。"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(f) or f <= 0.0 or f > 1.0:
        return default
    return f


def _clean_spec_rules(rules_raw):
    """spec_suppress_rules 清洗 → 规则 tuple。

    null/非 list → 内置 SPEC_SUPPRESS_BUILTIN_RULES；逐规则校验：
    signal_patterns 非空且全部可编译、suppress_doc_contains 非空字符串清单，
    坏规则单条丢弃（不整组回退——用户显式给表即尊重其意图）；显式空表
    []=清洗后无规则=机制空转（等价关，登记在册不回内置）。factor 键可选
    （越界回 spec_suppress_factor 全局系数，清洗在调用侧做）。
    """
    if not isinstance(rules_raw, list):
        return SPEC_SUPPRESS_BUILTIN_RULES
    out = []
    for r in rules_raw:
        if not isinstance(r, dict):
            continue
        pats, docs = r.get("signal_patterns"), r.get("suppress_doc_contains")
        if (not isinstance(pats, list) or not pats
                or not isinstance(docs, list)
                or not [d for d in docs if str(d).strip()]):
            continue
        ok = True
        for p in pats:
            try:
                re.compile(str(p))
            except re.error:
                ok = False
                break
        if not ok:
            continue
        rule = {"name": str(r.get("name") or "rule%d" % len(out)),
                "signal_patterns": tuple(str(p) for p in pats),
                "suppress_doc_contains": tuple(str(d) for d in docs if str(d).strip())}
        if r.get("factor") is not None:
            rule["factor"] = r.get("factor")   # 数值清洗延到 clean_decrowd_params
        out.append(rule)
    return tuple(out)


def clean_decrowd_params(cfg):
    """rag 配置段（DEFAULT_RAG_CONFIG 合并后形态）→ decrowd 清洗参数 dict。

    initialize 与离线验证脚本共用（同一套坏值回默认口径，防"线上/离线两把
    尺"）；全部键容忍缺失（缺失=默认档=全关）。
    """
    get = cfg.get if isinstance(cfg, dict) else (lambda k, d=None: d)
    try:
        quota_max = int(get("doc_quota_max", DEFAULT_DOC_QUOTA_MAX))
    except (TypeError, ValueError):
        quota_max = DEFAULT_DOC_QUOTA_MAX
    if quota_max < 1:
        quota_max = DEFAULT_DOC_QUOTA_MAX
    exempt = get("doc_quota_exempt_docs")
    exempt = (tuple(str(x) for x in exempt if str(x).strip())
              if isinstance(exempt, list) else ())
    docs = get("table_downweight_docs")
    docs = (tuple(str(x) for x in docs if str(x).strip())
            if isinstance(docs, list) and [x for x in docs if str(x).strip()]
            else TABLE_DOWNWEIGHT_DOCS)
    scope = str(get("table_downweight_scope") or "annex").strip().lower()
    if scope not in ("annex", "all", "tables"):
        scope = "annex"
    # 表降权白名单（2026-10-03，默认 []=无豁免）：locator 正则预编译（消费点=
    # decrowd_rescore ②表因子分支，命中即静默跳过降权）；null/非 list=()；
    # 坏正则单条丢弃（口径贴 _clean_spec_rules：不整组回退——用户显式给表即
    # 尊重其意图，坏条目不吞掉好条目）
    wl_raw = get("table_downweight_whitelist")
    wl = []
    if isinstance(wl_raw, list):
        for pat in wl_raw:
            ps = str(pat)
            if not ps.strip():
                continue
            try:
                wl.append(re.compile(ps))
            except re.error:
                continue
    whitelist = tuple(wl)
    try:
        cands = int(get("decrowd_candidates", DEFAULT_DECROWD_CANDIDATES))
    except (TypeError, ValueError):
        cands = DEFAULT_DECROWD_CANDIDATES
    if cands < 1:
        cands = DEFAULT_DECROWD_CANDIDATES
    spec_factor = _norm_decrowd_factor(get("spec_suppress_factor"),
                                       DEFAULT_SPEC_SUPPRESS_FACTOR)
    cleaned = _clean_spec_rules(get("spec_suppress_rules"))
    if cleaned is SPEC_SUPPRESS_BUILTIN_RULES:
        rules = cleaned            # 内置规则原样引用（零重建，身份可断言）
    else:
        rules = []
        for r in cleaned:
            r = dict(r)
            if "factor" in r:
                r["factor"] = _norm_decrowd_factor(r["factor"], spec_factor)
            rules.append(r)
        rules = tuple(rules)
    snap = get("retrieval_snapshot_dir")
    snap = str(snap).strip() if snap else None
    return {
        "quota_on": bool(get("doc_quota_enabled")),
        "quota_max": quota_max,
        "quota_exempt": exempt,
        "table_on": bool(get("table_downweight_enabled")),
        "table_factor": _norm_decrowd_factor(get("table_downweight_factor"),
                                             DEFAULT_TABLE_DOWNWEIGHT_FACTOR),
        "table_docs": docs,
        "table_scope": scope,
        "table_whitelist": whitelist,
        "spec_on": bool(get("spec_suppress_enabled")),
        "spec_factor": spec_factor,
        "spec_rules": tuple(rules),
        "candidates": cands,
        "snapshot_dir": snap or None,
    }


def clean_family_select_params(cfg):
    """rag 配置段 → 族选席清洗参数 dict（乙案 2026-09-29，默认关=零调用面）。

    坏值一律回默认（口径贴 clean_decrowd_params）；全部键容忍缺失。
    """
    get = cfg.get if isinstance(cfg, dict) else (lambda k, d=None: d)
    scope = str(get("family_select_scope") or DEFAULT_FAMILY_SELECT_SCOPE).strip().lower()
    if scope not in ("miit", "miit+clone"):
        scope = DEFAULT_FAMILY_SELECT_SCOPE
    words = str(get("family_select_words") or "full").strip().lower()
    if words not in ("full", "core"):
        words = "full"
    try:
        margin = int(get("clone_fold_min_margin", DEFAULT_CLONE_FOLD_MIN_MARGIN))
    except (TypeError, ValueError):
        margin = DEFAULT_CLONE_FOLD_MIN_MARGIN
    if margin < 0:
        margin = DEFAULT_CLONE_FOLD_MIN_MARGIN
    return {
        "enabled": bool(get("family_select_enabled")),
        "scope": scope,
        "words": words,
        "clone_margin": margin,
    }


# ---------------------------------------------------------------------------
# 乙案族选席核心纯函数（2026-09-29，默认关=零调用面；方案档 §2.2 R1-R5）
#
# hit 形态约定：与 clause_family_rerank / doc_quota_select 同款
# [{"rank","score","rec"},...]（rec 含 doc_id/locator/corpus_type/chunk_type/
# source_domain）；输入不被修改（逐条 dict 拷贝）。
# ---------------------------------------------------------------------------

# 监管层级族键推导：剥 locator 尾部" 款N"后缀 → 父条 locator 作为族键
# （与乙层 _CLAUSE_SUB_SUFFIX_RE 同款正则语义，单一语义源；监管行 locator 实测
# ASCII 空格分隔："附录1 1.2.1 拨号时延 款2"/"主要目标 （二） 款3"）
_FAMILY_MIIT_SUFFIX_RE = re.compile(r" 款\d+$")

# 克隆族指标名归一：取 locator 末段，去尾随空白/数字后缀
_FAMILY_CLONE_METRIC_RE = re.compile(r"[\s\d]+$")

# 克隆族条目形：仅 36号令 附录条目条块（locator 形如"附录N X.Y.Z 指标名"）。
# 款块与附录/节标题块（"附录N""附录N X.Y"）不入克隆族——款块末段"款N"归一后
# 会把同 doc 全部款块并成同名巨族，标题块会把"（一）（二）"跨 L2 标签混族；
# 本形过滤后全库实测恰为方案 §1.3 所计 6 族 20 块（业务咨询×6/计费差错率×5/
# 网络可用性×3/接续时延×2/网络接通率×2/通话中断率×2），与 02 脚本口径同构
_FAMILY_CLONE_ENTRY_RE = re.compile(r"^附录\d+\s+\d+\.\d+\.\d+\s")

# 监管域 doc 三件（镜像 route_domain.REG_DOCS——域判定与 doc_in_domain
# "监管数字"谓词同款口径：doc_id 三件精确为主、corpus_type/source_domain 为
# 辅助兜底。现库监管 221 行实测 corpus_type="监管"、source_domain="miit"，
# 无 corpus_type="miit" 取值；缺三字段 1,476 行均为 TS 前缀 3GPP 行，doc_id
# 不在三件、两辅助键空串恒不误入=安全向。doc 名单扩改须与 route_domain.REG_DOCS
# 同步并走决策纪律，禁自动生效）
_FAMILY_MIIT_REG_DOCS = ("信息产业部令第36号", "工信部联通信〔2023〕257号",
                         "2025年通信业统计公报")


def _rec_is_miit(rec):
    """库行 rec → 是否监管（miit）域行。恒不抛出；缺字段行保守 False。"""
    try:
        if str(rec.get("doc_id") or "") in _FAMILY_MIIT_REG_DOCS:
            return True
        if str(rec.get("corpus_type") or "") == "监管":
            return True
        return str(rec.get("source_domain") or "").strip().lower() == "miit"
    except Exception:  # pragma: no cover —— 防御位：判定面恒不抛出
        return False


def _family_miit_key(rec):
    """监管层级族键：("miit", doc_id, parent_locator)。

    - 款块（locator 以" 款N"结尾）→ 剥后缀得父条 locator（257号/统计公报的
      L2 标签分支族同键覆盖："主要目标 （二） 款3"→"主要目标 （二）"）；
    - 条块（无" 款N"后缀）→ 自身即父条 locator；
    - 非监管域（_rec_is_miit False，含缺三字段行）→ None（不参与层级族）。
    """
    if not _rec_is_miit(rec):
        return None
    doc = str(rec.get("doc_id") or "")
    loc = str(rec.get("locator") or "")
    parent_loc = _FAMILY_MIIT_SUFFIX_RE.sub("", loc)
    return ("miit", doc, parent_loc)


def _family_clone_key(rec):
    """克隆族键：("clone", doc_id, 指标名归一)。

    - 仅附录条目条块（_FAMILY_CLONE_ENTRY_RE 形）：款块归层级族、标题块不成
      条目（见常量注释的巨族/混族实证）；
    - 指标名=locator 末段去尾随空白/数字后缀，跨附录同名条目同族（方案 §1.3
      同名克隆族；"通话中断率（掉话率）"不与"通话中断率"归一=方案计数同款）；
    - 非监管域/非附录条目形/指标名空 → None。
    """
    if not _rec_is_miit(rec):
        return None
    loc = str(rec.get("locator") or "")
    if not loc or _FAMILY_MIIT_SUFFIX_RE.search(loc):
        return None
    if not _FAMILY_CLONE_ENTRY_RE.match(loc):
        return None
    parts = re.split(r"[\s\u3000]+", loc.strip())
    metric = parts[-1] if parts else loc
    metric = _FAMILY_CLONE_METRIC_RE.sub("", metric).strip()
    if not metric:
        return None
    doc = str(rec.get("doc_id") or "")
    return ("clone", doc, metric)


def _neg_count(rec, sigs):
    """负项计数：题面高权重信号在块文本中缺失的数量。

    复用 clause_family_rerank 同款口径（_ws_norm_text + _rec_text）。
    """
    text = _ws_norm_text(_rec_text(rec))
    return sum(1 for w in sigs if w not in text)


def family_member_select(hits, q_text, fam_cfg, topk=None):
    """族选席（R1-R5）→ 新 hits（rank 重编 1..n）+ info dict。

    - hits：深候选池 hit 列表（已重打分、可能已经过 route constraint）；
    - q_text：查询文本（用于负项计数）；
    - fam_cfg：clean_family_select_params 产物；
    - topk：组装截断深度——R1 父条判定的共存窗口=hits[:topk]（组装前的
      证据集反事实面）；None/≤0=全池窗口（旧池面口径，留作差异复核对拍面）；
    - 返回 (selected_hits, overflow_hits, info)：
      selected_hits = 族选席保留的成员（保持原通道序中的相对序）；
      overflow_hits = 被 R1-R4 让位/折叠的成员（通道序；供 doc_quota_select
      回补池与无配额缺口回补消费——证据面绝不因选席缩水，方案 R1 回补语义）；
      info = {"families": N, "r1_drop": N, "r23_drop": N, "r4_fold": N,
              "kept": N} 打点用。

    规则组（方案档 §2.2）：
    R1 父条成员级让位：同款族子款在组装前 topk 窗口内共存时（乙层
       _clause_parent_flag 的证据集共存触发面不变、仅救济从 order-only 升级
       为成员级——方案 R1"S1 乙父条绝对让位从 order-only 升级为成员级"字面），
       父条出 selected → overflow；深池子款（窗口外）不触发让位——父条空席会
       把深处块（含型4 强锚诱导块）提进 top3，S1V-18 A 级实测教训=施工批
       差异修复 #6（池面口径实测全臂破 A 级线，窗口面保方案 5 对父子款病灶
       修复面零损失：12/13/14/11/15 的父子块在 base top5 全部窗口共存）；
    R2 族内 0 负项成员全保留（非 0 负项成员让位；族作用面=深池全体，
       S1V-13 的（二）款1 池 r7 经深池选席入集=方案推演同款）；
    R3 无 0 负项族保底 1 席（负项数,通道序 最优者）、平局保留至多 2 席；
    R4 克隆折叠仅唯一 0 负项且负项差 ≥ clone_margin 时（平局绝不折叠=
       B12 canary 硬规则，margin 只收紧差值门槛）；
    R5 gate_cosine 载体不动（hit["score"] 不改，本函数只改成员）。
    """
    info = {"families": 0, "r1_drop": 0, "r23_drop": 0, "r4_fold": 0, "kept": 0}
    fam_cfg = fam_cfg or {}
    if not hits or not fam_cfg.get("enabled"):
        return hits, [], info

    scope = fam_cfg.get("scope", DEFAULT_FAMILY_SELECT_SCOPE)
    words_mode = fam_cfg.get("words", "full")
    clone_margin = fam_cfg.get("clone_margin", DEFAULT_CLONE_FOLD_MIN_MARGIN)

    # 构建词表信号（复用乙层词表）
    qn = _ws_norm_text(q_text)
    vocab = CLAUSE_RERANK_WORDS_CORE + (
        CLAUSE_RERANK_WORDS_METRIC if words_mode == "full" else ())
    sigs = [_ws_norm_text(w) for _, w in vocab if _ws_norm_text(w) in qn]

    # ---- 族推导（检索期不落库）----
    # 每 hit 归属 0..2 族：层级族=监管行恒推导；克隆族=scope miit+clone 时推导。
    # 两族可重叠（附录条目父条块，如"附录1 1.2.2 接续时延"，既在 1.2.2 层级族
    # 又在跨附录"接续时延"克隆族）——处理序=先全部层级族（R1-R3）再克隆族
    # （R4），R4 只看 R1 让位后的活跃面，双族籍块的结果与池插入序无关（确定性）
    families = {}   # family_key -> [hit_index, ...]（通道序升序）
    for i, h in enumerate(hits):
        rec = h.get("rec") or {}
        mk = _family_miit_key(rec)
        if mk is not None:
            families.setdefault(mk, []).append(i)
        if scope == "miit+clone":
            ck = _family_clone_key(rec)
            if ck is not None:
                families.setdefault(ck, []).append(i)

    # 过滤掉单成员族（无需选席）
    multi_fams = {k: v for k, v in families.items() if len(v) > 1}
    info["families"] = len(multi_fams)
    if not multi_fams:
        return hits, [], info

    # ---- 预计算每个 hit 的负项数和父条标志 ----
    # R1 父条判定面=组装前 topk 窗口（乙层证据集共存语义的忠实升级，见
    # docstring R1 行；topk 缺省=全池窗口）
    try:
        _w = int(topk) if topk else 0
    except (TypeError, ValueError):
        _w = 0
    win = hits[: _w] if _w > 0 else hits
    win_locs = [str(h.get("rec", {}).get("locator") or "") for h in win]
    neg_cache = {}
    parent_cache = {}
    for i in set(idx for members in multi_fams.values() for idx in members):
        rec = hits[i].get("rec") or {}
        neg_cache[i] = _neg_count(rec, sigs)
        loc = str(rec.get("locator") or "")
        parent_cache[i] = _clause_parent_flag(loc, win_locs)

    # ---- R1-R4 选席 ----
    # 处理序：层级族（"miit"）先于克隆族（"clone"）——双族籍块先受 R1 让位，
    # R4 只见活跃面（确定性纪律，见族推导段注释）；sorted 稳定=组内保持插入序
    drop_set = set()   # 被让位/折叠的 hit index
    for fkey, members in sorted(multi_fams.items(),
                                key=lambda kv: kv[0][0] == "clone"):
        is_clone = fkey[0] == "clone"

        # R1: 父条成员级让位（仅层级族）
        if not is_clone:
            parent_indices = [i for i in members if parent_cache.get(i)]
            child_indices = [i for i in members if not parent_cache.get(i)]
            if parent_indices and child_indices:
                for pi in parent_indices:
                    drop_set.add(pi)
                    info["r1_drop"] += 1

        # 活跃成员（未被 R1 让位的）
        active = [i for i in members if i not in drop_set]
        if not active:
            continue

        # 按负项数分组
        neg_groups = {}
        for i in active:
            n = neg_cache.get(i, 0)
            neg_groups.setdefault(n, []).append(i)
        min_neg = min(neg_groups.keys())
        zero_neg = neg_groups.get(0, [])

        if is_clone:
            # R4: 克隆折叠——仅唯一 0 负项且负项差 ≥ clone_margin
            if len(zero_neg) == 1 and min_neg == 0:
                next_neg = sorted(k for k in neg_groups.keys() if k > 0)
                if next_neg and (next_neg[0] - min_neg) >= clone_margin:
                    # 折叠：保留唯一 0 负项，其余全部 drop
                    for i in active:
                        if i != zero_neg[0]:
                            drop_set.add(i)
                            info["r4_fold"] += 1
            # 否则不折叠（平局保护=B12 canary）
        else:
            # R2: 族内 0 负项成员全保留（保留数受 topk 与 ①doc 配额自然上限
            # 约束，不另设族内名额——方案 R2）
            # R3: 无 0 负项族保底 1 席、平局保留至多 2 席（平局不折叠原则）
            if zero_neg:
                # R2: 0 负项全保，非 0 负项 drop
                for i in active:
                    if neg_cache.get(i, 0) > 0:
                        drop_set.add(i)
                        info["r23_drop"] += 1
            else:
                # R3: 无 0 负项 → 最优者保 1 席，平局保至多 2 席。
                # 方案口径"（负项数,余弦）最优"：本函数作用于通道序候选池，
                # 监管域块不被 ②表降权/③制式压制触碰（乘子面=3GPP），通道序
                # 即余弦序——两口径在 scope=miit 作用面上等价
                best_neg = min_neg
                best_members = neg_groups[best_neg]
                if len(best_members) <= 2:
                    # 平局 ≤2 席全保
                    keep_set = set(best_members)
                else:
                    # >2 席平局只保前 2（按原通道序 tie-break）
                    keep_set = set(best_members[:2])
                for i in active:
                    if i not in keep_set:
                        drop_set.add(i)
                        info["r23_drop"] += 1

    # ---- 组装输出（保持原通道序）----
    selected = []
    overflow = []
    for i, h in enumerate(hits):
        item = dict(h)
        if i in drop_set:
            overflow.append(item)
        else:
            selected.append(item)

    # rank 重编
    for i, h in enumerate(selected, 1):
        h["rank"] = i
    for i, h in enumerate(overflow, 1):
        h["rank"] = i

    info["kept"] = len(selected)
    return selected, overflow, info


# ---------------------------------------------------------------------------
# 同源折叠核心纯函数（2026-10-03，默认关=零调用面；过程日志三节 26②同日终拍+
# ADR-0009 调线记录在档）。与 建库/work/纯折叠试点-20261003/折叠试点.py 的
# fold1 逐字等价（族键同器=建库/work/排序优化-20261002/消融.py fam_key）：
# 终序逐取，族首见留原位、同族超席者殿后（保序）——折叠全序=同集合置换，
# top5 族首覆盖只增不减（同族⇒同 doc）；判卷与呈报面=运营/呈报-纯折叠
# 第二钥匙-20261003.md。
# ---------------------------------------------------------------------------

# 族键剥尾正则（与 消融.py _PN/_RG 逐字同器，单一语义源）：先剥尾 "(pN)"
# （36.133 Annex 表分页形），再剥尾 "行组N"/"行组N-M"（横线含 ASCII - 与
# U+2013 –；36.133 "Annex A 表 行组N-M" 摘要形全表并族、36.101 "X.Y.Z 表"
# 同表并族）
_SAME_SOURCE_FOLD_PN_RE = re.compile(r"\s*\(p\d+\)$")
_SAME_SOURCE_FOLD_RG_RE = re.compile(r"\s*行组\d+(?:[-–]\d+)?$")

# 折叠窗深：作用于已排序列表的前 N 位（不足 N 取全部）
DEFAULT_SAME_SOURCE_FOLD_WINDOW = 10


def clean_same_source_fold_params(cfg):
    """同源折叠键清洗（容忍缺键/非法值→关；仅严格布尔 true 开启）。"""
    cfg = cfg if isinstance(cfg, dict) else {}
    return {"enabled": cfg.get("same_source_fold_enabled") is True}


def same_source_family_key(rec):
    """同源折叠族键=(doc_id, locator 主干)：先剥尾 "(pN)" 再剥尾 "行组N[-–]N"。

    缺字段行归 ("", "")=同族（=试点 fam_key 同器语义；生产 hit 恒有 rec，
    本位为纯函数边界登记）；恒不抛出。
    """
    rec = rec or {}
    loc = _SAME_SOURCE_FOLD_PN_RE.sub("", str(rec.get("locator") or "").strip())
    loc = _SAME_SOURCE_FOLD_RG_RE.sub("", loc)
    return (str(rec.get("doc_id") or ""), loc)


def same_source_fold1(hits):
    """fold1 单席族帽 → (折叠全序, 被折叠殿后列表)。

    - hits=已排序列表（[{"rank","score","rec"},...] 任一通道形态）；族键取
      hit["rec"]（缺 rec 行归 ("", "") 同族，见 same_source_family_key）；
      输入不被修改、不重编 rank（调用方按需重编）；
    - 折叠全序=同集合置换：族首按首见位次保留、同族超席者按原相对序殿后
      （=折叠试点.py fold1 / 消融.order_fold(seats=1) 语义）。
    """
    taken, deferred, seen = [], [], set()
    for h in hits:
        fk = same_source_family_key((h or {}).get("rec"))
        if fk in seen:
            deferred.append(h)
        else:
            seen.add(fk)
            taken.append(h)
    return taken + deferred, deferred


# ---------------------------------------------------------------------------
# 同源折叠族键扩展（2026-10-08 W4 D5 甲，默认 "tables"=零调用面；授权链=
# 过程日志三节 44 D5 甲→用户 2026-10-08 傍晚批）。归并形以离线仿真定形（判据
# =R01 t310 位次 5→1+S1 23 行零翻坏；三形位次表与选定理由=
# 建库/work/词面通道复放-20261008/fold扩展-仿真定形-20261008.md）：任务书
# B 形（IE 归属留首席）恰踩预警——正主 t310 在窗内位次殿后会被首席形挤出
# top5（R01 恶化）；A 形（仅版本尾主干）R01 零改善。选定形=主干并族+题面
# 锚定兄弟并族（下 same_source_fold_asn1）。
# ---------------------------------------------------------------------------
_SAME_SOURCE_FOLD_SCOPES = ("tables", "tables+asn1")
# 版本尾剥除：locator 尾部 "-rN/-RN"（nprach-NumSubcarriers-R13 → 主干
# nprach-NumSubcarriers；t319-RemoteUE-r17 → t319-RemoteUE——RemoteUE 系
# 功能限定非版本尾，不与 t319 并主干）
_SAME_SOURCE_FOLD_ASN1_VERSION_RE = re.compile(r"-[rR]\d+$")
# IE 名提取：asn1 参数卡 content 的 "所属 IE：XXX" 标记（hit rec 的
# META_FIELDS 八字段不含 section——装载面裁剪，IE 名只活在 content）
_SAME_SOURCE_FOLD_IE_RE = re.compile(r"所属\s*IE[：:]\s*([^\)）\n]+)")
# 题面锚主干最短长度（防 "nr" 类泛词弱锚——R03 实证：无护栏会把
# RF-Parameters 族整体殿后）
_SAME_SOURCE_FOLD_ANCHOR_MIN_LEN = 4


def clean_same_source_fold_scope(cfg):
    """同源折叠 scope 键清洗（容忍缺键/非法值→"tables"；扩改须决策）。

    与 clean_same_source_fold_params 分立成函数（不并入其返回面）：既有
    函数返回面被 tests/test_同源折叠.py 整字典断言钉死；scope 单键单尺
    （单一清洗权威）不变。非 str/不在 _SAME_SOURCE_FOLD_SCOPES → "tables"。
    """
    cfg = cfg if isinstance(cfg, dict) else {}
    scope = cfg.get("same_source_fold_scope")
    return scope if scope in _SAME_SOURCE_FOLD_SCOPES else "tables"


def same_source_fold_asn1(hits, query):
    """scope=tables+asn1 归并形（纯函数）→ (折叠全序, 被折叠殿后列表)。

    与 same_source_fold1 同契约：同集合置换、保相对序殿后、不改输入、不
    重编 rank；差异面仅 asn1_card 块（chunk_type 判定）族帽扩展：

    - 版本尾主干并族（恒生效）：asn1 卡按 (doc_id, locator 剥尾 "-rN/-RN"
      主干) 为族，族内留首席、超席殿后——含同名卡（tables 态同名 locator
      并族的同构扩展）与版本尾卡（-R13/14/15/-r16/-r17 形）与跨 IE 同名卡；
    - 异名兄弟并族（题面锚定激活）：同 (doc_id, IE)（IE 自 content
      "所属 IE：" 标记推导，缺标记=不参加兄弟族）异名参数卡为一族；族内
      存在题面锚（某成员主干 ∈ 题面归一文本，主干长≥
      _SAME_SOURCE_FOLD_ANCHOR_MIN_LEN）时非锚成员殿后、锚定主干留首席；
      族内无锚不动（零改面）；
    - 非 asn1 块族键=same_source_family_key（tables 形，现状语义逐字不变）；
    - query 空/None → 锚集恒空=仅主干并族面生效；hits 空 → ([], [])。
    """
    hits = list(hits or [])
    qn = _ws_norm_text(query)
    # 第一遍预扫：逐 hit 归类（tables 族键 or asn1 主干/IE 族）+ 题面锚集
    infos, trunk_set = [], set()
    for h in hits:
        rec = (h or {}).get("rec") or {}
        loc = str(rec.get("locator") or "").strip()
        if str(rec.get("chunk_type") or "") == "asn1_card" and loc:
            trunk = _ws_norm_text(_SAME_SOURCE_FOLD_ASN1_VERSION_RE.sub("", loc))
            m = _SAME_SOURCE_FOLD_IE_RE.search(str(rec.get("content") or ""))
            ie = _ws_norm_text(m.group(1).strip()) if m else ""
            infos.append({"asn1": True, "doc": str(rec.get("doc_id") or ""),
                          "trunk": trunk, "ie": ie})
            trunk_set.add(trunk)
        else:
            infos.append({"asn1": False,
                          "fam": same_source_family_key(rec)})
    anchors = {t for t in trunk_set
               if len(t) >= _SAME_SOURCE_FOLD_ANCHOR_MIN_LEN and t in qn}
    # 兄弟族锚定态：族内任一成员主干 ∈ 锚集 → 该 (doc, IE) 族锚定
    fam_anchor = {}
    for info in infos:
        if info["asn1"] and info["ie"]:
            fam = (info["doc"], info["ie"])
            fam_anchor[fam] = fam_anchor.get(fam, False) or info["trunk"] in anchors
    # 第二遍终序逐取：tables 首席 / 锚定主干首席 / 主干首席 / 兄弟非锚殿后
    taken, deferred = [], []
    seen_tables, seen_trunk, seen_anchor_trunk = set(), set(), set()
    for h, info in zip(hits, infos):
        if not info["asn1"]:
            if info["fam"] in seen_tables:
                deferred.append(h)
            else:
                seen_tables.add(info["fam"])
                taken.append(h)
        elif info["ie"] and fam_anchor.get((info["doc"], info["ie"])):
            fam = (info["doc"], info["ie"])
            if info["trunk"] in anchors:
                k = (info["doc"], info["trunk"])
                if k in seen_anchor_trunk:
                    deferred.append(h)
                else:
                    seen_anchor_trunk.add(k)
                    taken.append(h)
            else:
                deferred.append(h)
        else:
            k = (info["doc"], info["trunk"])
            if k in seen_trunk:
                deferred.append(h)
            else:
                seen_trunk.add(k)
                taken.append(h)
    return taken + deferred, deferred


# ---------------------------------------------------------------------------
# B-evict 定向清位（2026-10-03 丙闸扩型候选B 采纳，默认关=零调用面；键义、
# 词表冻结纪律与打点格式见件头注 2026-10-03 段）；rag 段配置键：
#   "b_evict_enabled": False   # 总开关（false/缺省/非法值=关；仅严格布尔 true 开）
# ---------------------------------------------------------------------------
# B_STRONG 七词冻结（=跑测脚本-20261003.py B_STRONG 同表；扩改须决策纪律见
# 件头注：单词增删=重走预登记与决策，禁自动生效；禁入覆盖闸词表）
B_EVICT_VOCAB = ("国内长途", "无线信道", "IP电话", "呼叫建立", "消息", "成功", "抖动")
# 清位窗深：作用于已排序列表前 N 位（不足 N 取全部）——与同源折叠窗同宽 10
DEFAULT_B_EVICT_WINDOW = 10


def clean_b_evict_params(cfg):
    """B-evict 键清洗（容忍缺键/非法值→关；仅严格布尔 true 开启）。"""
    cfg = cfg if isinstance(cfg, dict) else {}
    return {"enabled": cfg.get("b_evict_enabled") is True}


def b_evict_clear(hits, query, topk=DEFAULT_TOPK, window=DEFAULT_B_EVICT_WINDOW):
    """B-evict 定向清位（纯函数）→ (幸存者序列截 topk, info)。

    机制口径=丙闸跑测脚本-20261003.py b_evict 同器（evict 语义权威）：
    - 活跃词 W=B_EVICT_VOCAB∩题面（归一=_ws_norm_text：去全部空白+小写，
      "IP 电话"与"IP电话"互配）；W 空=零改动直过（activated=False 原样返回）；
    - 块负项 n(b)=W 缺失于块 _rec_text（doc_id+version+locator+content 拼接）
      的词数；基准 n1=n(窗内首位块)（首位=现役 rank1，乙+折叠后的终序首位）；
      n(b)>n1 的块逐出窗（严格超基准才逐），幸存者原序取前 topk（席位不足
      如实缩减；rank1 恒幸存无空集路径——n(rank1)=n1 不自逐）；
    - 输入不被修改、不重编 rank（调用方截 topk 后按需重编）；hits 空 →
      原样返回（activated=False）。
    """
    info = {"activated": False, "words": (), "base": None, "evicted": 0}
    if not hits:
        return hits, info
    qn = _ws_norm_text(query)
    words = [w for w in B_EVICT_VOCAB if _ws_norm_text(w) in qn]
    if not words:
        return hits, info
    topk = max(1, int(topk))
    win = list(hits[: max(topk, int(window))])
    negs = []
    for h in win:
        text = _ws_norm_text(_rec_text((h or {}).get("rec") or {}))
        negs.append(len([w for w in words if _ws_norm_text(w) not in text]))
    base = negs[0]                              # rank1 基准（窗内首位）
    keep = [h for h, n in zip(win, negs) if n <= base]
    out = keep[: topk]
    info = {"activated": True, "words": tuple(words), "base": base,
            "evicted": len(win) - len(keep), "seats": len(out)}
    return out, info


# ---------------------------------------------------------------------------
# MMR 向量去冗余（2026-10-23 波3 工程件，默认关=零调用面；键义、挂点纪律
# 与闸分载体纪律见件头注 2026-10-23 段）；rag 段配置键：
#   "mmr_enabled": False   # 总开关（false/缺省/非法值=关；仅严格布尔 true 开）
#   "mmr_lambda": 0.7      # λ 相关性权重 ∈[0,1]（含边界；坏值回 0.7；
#   #                      #   1=纯相关性稳定序（纯余弦态=恒等置换）、
#   #                      #   0=纯多样性贪心——两边界均为合法退化态）
# ---------------------------------------------------------------------------
DEFAULT_MMR_LAMBDA = 0.7


def clean_mmr_params(cfg):
    """MMR 键清洗（容忍缺键/非法值→关+默认 λ；仅严格布尔 true 开启）。

    - enabled：仅严格布尔 true 开（口径贴 clean_same_source_fold_params）；
    - lam：float∈[0,1]（含边界；bool/非数/NaN/越界回 DEFAULT_MMR_LAMBDA，
      口径贴 _norm_decrowd_factor/闸分载体提取面的 bool 排除先例：误配回
      已知安全档）。
    """
    cfg = cfg if isinstance(cfg, dict) else {}
    _lam = cfg.get("mmr_lambda")
    if isinstance(_lam, bool) or not isinstance(_lam, (int, float)):
        _lam = DEFAULT_MMR_LAMBDA
    try:
        lam = float(_lam)
    except (TypeError, ValueError):
        lam = DEFAULT_MMR_LAMBDA
    if not math.isfinite(lam) or lam < 0.0 or lam > 1.0:
        lam = DEFAULT_MMR_LAMBDA
    return {"enabled": cfg.get("mmr_enabled") is True, "lam": lam}


def _mmr_rel(h):
    """MMR 相关性项=原始余弦（gate_cosine 同款提取面：cosine 键优先、缺则
    score；非数/NaN/bool → 0.0）。只读既有键，不产生新分数。

    与相似度惩罚项同量纲（均为余弦 ∈[-1,1]）——λ 加权在 RRF 融合态亦语义
    有效（fused 分 ~1e-2 量级与余弦惩罚不可比，不作相关性载体）。
    """
    c = h["cosine"] if "cosine" in h else h.get("score")
    if isinstance(c, (int, float)) and not isinstance(c, bool) and math.isfinite(c):
        return float(c)
    return 0.0


def _mmr_pair_sim(rec_a, rec_b):
    """块间余弦=既有向量点积的余弦归一（rec["vec"]，装载期归一 array('f')）。

    - 归一除模（|a|·|b|）：生产向量已单位化（除 ≈1 修正 float32 落存舍入），
      测试注入的未归一向量同器得真余弦；零模/维度不符/缺 vec（None/非序列）
      → 0.0（保守向：无向量证据=不惩罚，恒不抛出）；
    - 纯 math 点积零依赖（numpy 仅 faiss 路径延迟导入——本件不引入新依赖）。
    """
    a = (rec_a or {}).get("vec")
    b = (rec_b or {}).get("vec")
    if not isinstance(a, (array, list, tuple)) or \
            not isinstance(b, (array, list, tuple)):
        return 0.0
    if len(a) == 0 or len(a) != len(b):
        return 0.0
    try:
        na = math.sqrt(_dot(a, a))
        nb = math.sqrt(_dot(b, b))
        if not math.isfinite(na) or not math.isfinite(nb) or na <= 0.0 or nb <= 0.0:
            return 0.0
        s = _dot(a, b) / (na * nb)
    except Exception:   # 理论态防御（坏元素等）：不惩罚不抛出
        return 0.0
    return s if math.isfinite(s) else 0.0


def mmr_reorder(hits, lam=DEFAULT_MMR_LAMBDA):
    """MMR（maximal marginal relevance）终 top-k 去冗余重排（纯函数，order-
    only 同集合置换）→ (重排后 hits, info)。

    - hits=治理链尾（乙重排+同源折叠+B-evict 全部生效、终 topk 截断后）的
      证据集 [{"rank","score","rec"},...]（任一通道形态）；hits 空/单条 →
      原样返回（不拷贝、不附键、不重编 rank，moved=0）；
    - 选席迭代：首取=相关性 _mmr_rel 最高（tie→原位次靠前）；此后逐席取
      argmax(λ·rel −(1−λ)·max_{j∈已选} sim(i,j))（块间余弦=_mmr_pair_sim，
      tie→原位次靠前）——全程确定性；λ=1 退化=按相关性稳定排序（纯余弦态
      score=cosine 且列表已按其降序 ⇒ 恒等置换）；λ=0 退化=纯多样性贪心
      （首取仍相关性首位，此后取与已选集最不相似者）；
    - 不产生新分数、不污染闸分载体：hit 的 cosine/score 键逐字节不动（输出
      =逐条 dict 拷贝，乙层 clause_family_rerank 同款先例；输入列表与元素
      零修改）；rank 按 MMR 终序重编 1..n（build_evidence [出处N] 编号位，
      fold/evict 链尾同款口径）；另附独立 mmr_rank 键（MMR 选席序 1..n——
      与重编 rank 数值恒同、独立成键的意义=闸分编号载体（rank）之外的纯观测
      面，闸分/证据组装/快照零消费，删读零行为差）；
    - info={"n","moved","perm"}：moved=换位数（终序第 i 席 ≠ 原第 i 席的计
      数），perm=MMR 终序的原下标序列（终序第 i 席取自原第 perm[i]+1 席）
      ——供 [rag-mmr] 观测行与测试对账；
    - O(n²) 点积、n≤topk（现值 5）：纯标准库毫秒级以下，零 API 零新索引。
    """
    hits = hits if hits else []
    n = len(hits)
    if n <= 1:   # 空/单条：原样返回（同对象不拷贝、不附键、不重编 rank）
        return hits, {"n": n, "moved": 0, "perm": list(range(n))}
    hits = list(hits)
    try:
        lam = float(lam)
    except (TypeError, ValueError):
        lam = DEFAULT_MMR_LAMBDA
    if not math.isfinite(lam):
        lam = DEFAULT_MMR_LAMBDA
    lam = min(1.0, max(0.0, lam))   # 直调防御位（clean_mmr_params 已钳）
    rels = [_mmr_rel(h) for h in hits]
    sim = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            s = _mmr_pair_sim(hits[i].get("rec"), hits[j].get("rec"))
            sim[i][j] = s
            sim[j][i] = s
    remaining = list(range(n))
    selected = []
    while remaining:
        if not selected:
            best = remaining[0]                 # 首取：相关性最高，tie 保首见
            for i in remaining[1:]:
                if rels[i] > rels[best]:
                    best = i
        else:
            best = None
            best_sc = None
            for i in remaining:                 # 升序遍历：tie 保原位次靠前
                sc = lam * rels[i] - (1.0 - lam) * max(sim[i][j] for j in selected)
                if best is None or sc > best_sc:
                    best, best_sc = i, sc
        selected.append(best)
        remaining.remove(best)
    out = [dict(hits[i]) for i in selected]
    moved = sum(1 for pos, i in enumerate(selected) if i != pos)
    for pos, h in enumerate(out, 1):
        h["rank"] = pos
        h["mmr_rank"] = pos
    return out, {"n": n, "moved": moved, "perm": selected}


def _spec_norm_text(s):
    """制式信号匹配归一：小写+空白折叠为单空格（**不删空白**——ASCII 信号的
    词边界环视依赖空格在位，"5G NR"删空白成"5gnr"会破坏 (?<![a-z0-9])nr 边界；
    CJK 不受影响，环视只排除 [a-z0-9]）。与乙/丙的 _ws_norm_text 分工不同。"""
    return re.sub(r"\s+", " ", str(s or "").lower())


def spec_suppress_fired_rules(query, rules):
    """题面 → 命中的制式压制规则清单（③）。

    - 匹配面=_spec_norm_text（小写+空白折叠），signal_patterns 逐条
      re.search（re 内建编译缓存）；
    - 歧义保护：≥2 条规则同时命中（跨制式题面，如"4G和5G 互操作""36.331 与
      38.331 对比"）→ 返回 []（一律不压制——异制式判定在双侧信号下无据）。
    """
    qn = _spec_norm_text(query)
    fired = [r for r in (rules or ())
             if any(re.search(p, qn) for p in r.get("signal_patterns", ()))]
    return [] if len(fired) > 1 else fired


def _table_scope_hit(scope, loc, chunk_type):
    """②表降权目标块判定（scope=annex|all|tables）。

    - annex=仅 locator 以 "Annex" 起（默认微创面）；all=全部块；
    - tables=仅 chunk_type∈TABLE_CHUNK_TYPES 的表行组块（2026-10-02 scoped
      变体：doc 级降权会误伤同 doc 条款/卡正主面时的细粒度档——判效依据=
      建库/logs/检索排序治理-判效-20261002.md §四）。
    """
    if scope == "tables":
        return str(chunk_type or "") in TABLE_CHUNK_TYPES
    if scope == "all":
        return True
    return str(loc or "").startswith(TABLE_DOWNWEIGHT_ANNEX_PREFIX)


def decrowd_rescore(query, hits, params):
    """②③ 降权/压制重打分（纯函数）→ (新 hits, fired_info)。

    - 每 hit 先补挂余弦原始分（纯余弦态 score 即余弦、无 cosine 键；lexical/
      hybrid/mq 态 rerank_hits/fuse_hits 已附）再把命中块的 score 乘系数：
      表降权系数 × 制式压制系数（双命中连乘）；gate_cosine 优先读 cosine 键
      ——0.40 闸载体恒为原始分（薄余量零侵蚀，乙同款纪律）；
    - 重排 (-score, 原通道位次) 后 rank 重编 1..n（同分 tie-break 确定性）；
      另附 decrowd_factor 键（仅命中块；评测归因直读）；
    - 输入 hits 不被修改（逐条 dict 拷贝）；params 两开关全关/hits 空 →
      原样返回（零拷贝零重排，quota-only 臂走此路）。
    """
    info = {"table_n": 0, "spec_rule": None, "spec_n": 0}
    if not hits:
        return hits, info
    table_on = bool(params.get("table_on"))
    fired = (spec_suppress_fired_rules(
                 query, params.get("spec_rules") or SPEC_SUPPRESS_BUILTIN_RULES)
             if params.get("spec_on") else [])
    if not table_on and not fired:
        return hits, info
    tf = float(params.get("table_factor", DEFAULT_TABLE_DOWNWEIGHT_FACTOR))
    tdocs = tuple(params.get("table_docs") or TABLE_DOWNWEIGHT_DOCS)
    tscope = str(params.get("table_scope") or "annex")
    wl_pats = tuple(params.get("table_whitelist") or ())   # 白名单[]=无豁免
    sf = float(params.get("spec_factor", DEFAULT_SPEC_SUPPRESS_FACTOR))
    sup_docs = tuple(fired[0].get("suppress_doc_contains", ())) if fired else ()
    sf = float(fired[0].get("factor", sf)) if fired else sf
    out = []
    for h in hits:
        rec = h.get("rec") or {}
        doc = str(rec.get("doc_id") or "")
        loc = str(rec.get("locator") or "")
        item = dict(h)
        if "cosine" not in item:
            item["cosine"] = item.get("score")   # 原始余弦（闸载体）补挂
        factor = 1.0
        # 表降权白名单（2026-10-03，默认空=本判定恒 False=行为逐字节一致）：
        # locator 命中白名单正则的块静默跳过 ②表因子（③制式不受影响；无打点）
        wl_hit = (any(p.search(loc) for p in wl_pats) if wl_pats else False)
        if (table_on and not wl_hit and any(t in doc for t in tdocs)
                and _table_scope_hit(tscope, loc, rec.get("chunk_type"))):
            factor *= tf
            info["table_n"] += 1
        if fired and any(d in doc for d in sup_docs):
            factor *= sf
            info["spec_n"] += 1
        if factor != 1.0:
            item["score"] = float(item.get("score") or 0.0) * factor
            item["decrowd_factor"] = round(factor, 6)
        out.append(item)
    out.sort(key=lambda x: (-float(x.get("score") or 0.0), x["rank"]))
    for i, h in enumerate(out, 1):
        h["rank"] = i
    if fired:
        info["spec_rule"] = fired[0].get("name")
    return out, info


def doc_quota_select(hits, topk, quota, exempt_docs=(), domain_quotas=None):
    """① doc 配额选席（纯函数，两遍制）→ 新 hits（rank 重编 1..n）。

    - 第一遍按通道序遍历：同 doc_id 席位计满限额即让位（跳过、由候选池
      深处异 doc 块补位）——与乙 order-only 不同，本函数**改成员**（扩库
      靶子清单 §二.4"同 doc 席位无配额"的治理件，G18 型同族霸屏直接对治）；
    - 第二遍回补：第一遍选不满 topk（单 doc 主导的候选池，如监管域题面
      证据几乎全落 信息产业部令第36号）时，让位块按原通道序回补至满——
      **证据面绝不因配额缩水**（S1 对拍实测教训：短缺语义会把正主块连带
      证据集一起削掉，A 级负控/正控破线；回补语义下配额只保证"异 doc 块
      优先插队"，2026-09-29 施工日修订）；
    - doc_id 空串的块不计数不受限（匿名块无从归户）；exempt_docs=doc_id
      子串豁免清单（命中即不限量、不参与让位——监管小件族豁免为推荐配置，
      见 config.example.json _说明_P0去挤占）；
    - domain_quotas（案丙 domain_doc_quota，2026-10-06 域表参数化扩展；
      默认 None/{}=与旧调用逐字节一致）：{域名: 席位上限}，域判定=块 rec
      的 source_domain 归一（_domain_of_rec；缺字段 ""=恒不命中，保守向）
      ——域表命中域内块以**域值为准**（覆盖全局 quota 档，更特异者胜）；
      非域表域块回落全局 quota；quota=None（① 全局配额关的域表模式）→
      非域表域块不限额；exempt 豁免优先于域表与全局档；
    - 输入不被修改（逐条 dict 拷贝）。
    """
    if not hits:
        return hits
    topk = max(1, int(topk))
    quota = None if quota is None else max(1, int(quota))
    exempt = tuple(exempt_docs or ())
    dq = dict(domain_quotas or {})
    counts = {}
    out, overflow = [], []
    for h in hits:
        if len(out) >= topk:
            break
        rec = h.get("rec") or {}
        doc = str(rec.get("doc_id") or "")
        if doc and not any(x in doc for x in exempt):
            q = dq.get(_domain_of_rec(rec)) if dq else None
            if q is None:
                q = quota
            if q is not None:
                if counts.get(doc, 0) >= q:
                    overflow.append(h)
                    continue
                counts[doc] = counts.get(doc, 0) + 1
        out.append(dict(h))
    for h in overflow:                      # 第二遍：让位块按原序回补至满
        if len(out) >= topk:
            break
        out.append(dict(h))
    for i, h in enumerate(out, 1):
        h["rank"] = i
    return out


# ---------------------------------------------------------------------------
# 试点 2 元数据过滤核心纯函数（2026-10-01，默认关=零调用面；键义/闸分纪律见上方
# 常量段注释与件头注 2026-10-01 段）。hit 形态约定：与 decrowd_rescore 同款
# [{"rank","score","rec"},...]（rec 含 doc_id/version）；输入不被修改（逐条 dict
# 拷贝，且池内零陈旧块时原样返回=零拷贝零重排，口径同 decrowd_rescore 早退分支）。
# ---------------------------------------------------------------------------
_VERSION_TRIPLE_RE = re.compile(r"[vV](\d+)\.(\d+)\.(\d+)")


def parse_version_key(version):
    """版本串 → 可比较数字三元组 (major, minor, patch)；不可解析 → None。

    覆盖现库形态："Rel-18 V18.10.0" → (18, 10, 0)。监管件"2026（发文年份）"/
    空串 → None（恒不参与陈旧判定——未知≠陈旧，保守向）。"""
    m = _VERSION_TRIPLE_RE.search(str(version or ""))
    if not m:
        return None
    return tuple(int(x) for x in m.groups())


def build_meta_version_index(recs):
    """已装载 recs → 版本族索引 {doc_id: (最新版本三元组, 最新版本串)}。

    - 族=同 doc_id 内 ≥2 个**不同**可解析版本（单版本/全空/全不可解析 doc 无条目
      =零降权面）；空版本与不可解析版本不参与族判定（38.133 空版本 1,460 块与
      监管件"发文年份"形天然不受影响）；
    - 纯派生件（零 IO、零外部数据源）：META_FIELDS 装载面已含 version——
      embeddings.jsonl 行本带 22+ 元数据但 load_store 只留 8 字段，version 在位
      即够 v1 用（effective_status 被装载面丢弃且现库几乎全"现行"，v1 不消费）；
    - 同三元组不同写法（"Rel-18 V18.10.0" vs "V18.10.0"）视为同版本：族判定按
      三元组集合去重，块侧判定同样按三元组比较（等值不降权）。
    """
    seen = {}
    for rec in recs or []:
        doc = str(rec.get("doc_id") or "")
        ver = str(rec.get("version") or "").strip()
        if not doc or not ver:
            continue
        key = parse_version_key(ver)
        if key is None:
            continue
        seen.setdefault(doc, {})[key] = ver
    return {doc: (max(vers), vers[max(vers)])
            for doc, vers in seen.items() if len(vers) >= 2}


def clean_meta_filter_params(cfg):
    """rag 配置段 → 元数据过滤清洗参数 dict（口径贴 clean_decrowd_params：
    坏值回默认、全键容忍缺失；离线验证脚本同源复用，防线上/离线两把尺）。"""
    get = cfg.get if isinstance(cfg, dict) else (lambda k, d=None: d)
    return {
        "enabled": bool(get("meta_filter_v1")),
        "stale_factor": _norm_decrowd_factor(get("meta_stale_factor"),
                                             DEFAULT_META_STALE_FACTOR),
    }


def meta_filter_rescore(hits, params, meta_index):
    """同族（同 doc_id）陈旧版本块降权重打分（纯函数）→ (新 hits, info)。

    - 命中族内非最新版本（parse_version_key 严格小于族最新三元组）的块把通道
      排序分乘 stale_factor；余弦原始分恒存 hit["cosine"]（缺键补挂——纯余弦态
      score 即余弦，lexical/hybrid/mq 态此前已附），gate_cosine 优先读 cosine
      ——0.40 闸载体零侵蚀（②③同款薄余量纪律）；
    - 附 meta_factor 键（仅陈旧块；评测归因直读，口径同 decrowd_factor）；
    - 重排 (-score, 原位次) 后 rank 重编 1..n（同分 tie-break 确定性）；
    - 池内零陈旧块 → 原样返回（零拷贝零重排，bit 级直通）；factor=1.0 时等价关
      （仍打 meta_factor 标记=1.0 不改分——观测位）；params 关/meta_index 空 →
      原样返回。输入 hits 不被修改。
    """
    info = {"stale_n": 0, "families": 0}
    if not hits:
        return hits, info
    if not (params or {}).get("enabled") or not meta_index:
        return hits, info
    factor = float((params or {}).get("stale_factor")
                   or DEFAULT_META_STALE_FACTOR)
    flags = []
    for h in hits:
        rec = h.get("rec") or {}
        fam = meta_index.get(str(rec.get("doc_id") or ""))
        key = parse_version_key(str(rec.get("version") or "")) \
            if fam is not None else None
        flags.append(fam is not None and key is not None and key < fam[0])
    if not any(flags):
        return hits, info           # 池内零陈旧块：bit 级直通（零拷贝零重排）
    docs_touched = set()
    out = []
    for h, stale in zip(hits, flags):
        item = dict(h)
        if "cosine" not in item:
            item["cosine"] = item.get("score")   # 原始余弦（闸载体）补挂
        if stale:
            docs_touched.add(str((h.get("rec") or {}).get("doc_id") or ""))
            info["stale_n"] += 1
            item["meta_factor"] = round(factor, 6)
            if factor != 1.0:
                item["score"] = float(item.get("score") or 0.0) * factor
        out.append(item)
    out.sort(key=lambda x: (-float(x.get("score") or 0.0), x["rank"]))
    for i, h in enumerate(out, 1):
        h["rank"] = i
    info["families"] = len(docs_touched)
    return out, info


# ---------------------------------------------------------------------------
# 案甲域降权核心纯函数（2026-10-06 治理拨键批①，默认 {}=零调用面；键义/闸分
# 纪律/域登记制见上方常量段注释与件头注 2026-10-06 段）。hit 形态约定：与
# decrowd_rescore/meta_filter_rescore 同款 [{"rank","score","rec"},...]（rec 含
# source_domain）；输入不被修改（逐条 dict 拷贝，且池内零命中域块时原样返回
# =零拷贝零重排，口径同 meta_filter_rescore 早退分支）。
# ---------------------------------------------------------------------------
def _domain_of_rec(rec):
    """库行 rec → 域键（source_domain strip+lower 归一；缺字段=""）。域判定面=
    source_domain 单一字段（telecomhall 域 2,078 行实测全带该字段；corpus_type/
    doc_id 前缀不作域源——语义单一，防多源判定漂移）。"""
    try:
        return str((rec or {}).get("source_domain") or "").strip().lower()
    except Exception:  # pragma: no cover —— 防御位：判定面恒不抛出
        return ""


def clean_domain_downweight_params(cfg):
    """rag 配置段 → 域降权清洗参数 dict（口径贴 clean_meta_filter_params/
    clean_decrowd_params：坏条目单条丢弃不整组回退、全键容忍缺失；离线验证
    脚本同源复用，防线上/离线两把尺）。

    - 键=域名（strip+lower 归一，空名弃）；值=系数 ∈(0,1]（1.0=合法等价关档；
      非 dict 形态（list/str 等）整键回 {}=关，防误配半生效）。
    """
    get = cfg.get if isinstance(cfg, dict) else (lambda k, d=None: d)
    raw = get("domain_downweight")
    rules = []
    if isinstance(raw, dict):
        for k, v in raw.items():
            dk = str(k).strip().lower()
            if not dk:
                continue
            f = _norm_decrowd_factor(v, None)   # None=坏值标记（域降权无全局默认档）
            if f is None:
                continue
            rules.append((dk, f))
    return {"enabled": bool(rules), "rules": tuple(rules)}


def domain_downweight_rescore(hits, params):
    """案甲域降权重打分（纯函数）→ (新 hits, info)。

    - 命中域（_domain_of_rec(rec) ∈ rules）的块把通道排序分乘该域系数；余弦
      原始分恒存 hit["cosine"]（缺键补挂——纯余弦态 score 即余弦，lexical/
      hybrid/mq 态此前已附），gate_cosine 优先读 cosine——0.40 闸载体零侵蚀
      （②③/meta_filter 同款薄余量纪律）；
    - 域内相对序不变：同域块同乘一个系数=保序（乘性降权定理，V4 案甲解析面）；
    - 附 domain_factor 键（仅命中块；评测归因直读，口径同 decrowd_factor/
      meta_factor）；重排 (-score, 原位次) 后 rank 重编 1..n（同分 tie-break
      确定性，同款排序键）；
    - 池内零命中域块 → 原样返回（零拷贝零重排，bit 级直通）；params 关/空
      rules → 原样返回；hits 空 → 原样返回。输入 hits 不被修改。
    """
    info = {"domain_n": 0, "domains": ()}
    if not hits:
        return hits, info
    rules = dict((params or {}).get("rules") or ())
    if not rules:
        return hits, info
    hit_domains = set()
    factors = []
    for h in hits:
        dom = rules.get(_domain_of_rec(h.get("rec") or {}))
        factors.append(dom)
        if dom is not None:
            hit_domains.add(_domain_of_rec(h.get("rec") or {}))
    if not hit_domains:
        return hits, info           # 池内零命中域块：bit 级直通（零拷贝零重排）
    out = []
    for h, dom in zip(hits, factors):
        item = dict(h)
        if dom is not None:
            if "cosine" not in item:
                item["cosine"] = item.get("score")   # 原始余弦（闸载体）补挂
            info["domain_n"] += 1
            item["domain_factor"] = round(dom, 6)
            if dom != 1.0:
                item["score"] = float(item.get("score") or 0.0) * dom
        out.append(item)
    out.sort(key=lambda x: (-float(x.get("score") or 0.0), x["rank"]))
    for i, h in enumerate(out, 1):
        h["rank"] = i
    info["domains"] = tuple(sorted(hit_domains))
    return out, info


def clean_domain_doc_quota_params(cfg):
    """rag 配置段 → 案丙域内 doc 配额清洗参数 dict（口径贴
    clean_domain_downweight_params：坏条目单条丢弃不整组回退、全键容忍缺失；
    离线验证脚本同源复用，防线上/离线两把尺）。

    - 键=域名（strip+lower 归一，空名弃；归一后同名后者覆盖前者=dict 归一
      轮次序，确定性）；值=席位上限 int ≥1（数值化失败/<1 单条丢弃；int
      数值化沿 doc_quota_max 现役清洗口径，不单立尺）；
    - domain_doc_quota 非 dict（list/str 等）→ 整键回 {}=关（防误配半生效）。
    """
    get = cfg.get if isinstance(cfg, dict) else (lambda k, d=None: d)
    raw = get("domain_doc_quota")
    table = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            dk = str(k).strip().lower()
            if not dk:
                continue
            try:
                qv = int(v)
            except (TypeError, ValueError):
                continue
            if qv < 1:
                continue
            table[dk] = qv
    return {"enabled": bool(table), "table": table}


# ---------------------------------------------------------------------------
# H 线查询-族定向加权（2026-10-14 F线H 排序治理，默认 []=零调用面=现状逐字节
# 不变；键义与维护纪律见件头注 2026-10-14 H 线段）。hit 形态约定：与
# domain_downweight_rescore 同款 [{"rank","score","rec"},...]（rec 含 doc_id/
# corpus_type/source_domain）；输入不被修改（逐条 dict 拷贝，池内零命中块时
# 原样返回=零拷贝零重排，口径同 domain_downweight_rescore 早退分支）。
# ---------------------------------------------------------------------------
def clean_query_doc_factor_params(cfg):
    """rag 配置段 → 查询-族定向加权清洗参数 dict（口径贴
    clean_domain_downweight_params：坏条目单条丢弃不整组回退、全键容忍缺失；
    离线验证脚本同源复用，防线上/离线两把尺——单一清洗权威）。

    - query_doc_factor 非 list → 整键回 []=关（防误配半生效）；
    - 规则 dict 必含：query_words（非空 str 清单，空清单规则弃——无信号面=
      恒激活规则禁入）；目标选择器 ≥1 项（doc_contains / corpus_types /
      source_domains，均为 str 清单、strip 去空）；factor 数值 ∈(0,2]
      （<1 降权、>1 加权、1.0=合法等价关档；_norm_decrowd_factor 上界 1.0
      不适用于加权向，此处独立钳 (0,2]）；
    - name 缺省 ruleN（口径贴 _clean_spec_rules）。
    """
    get = cfg.get if isinstance(cfg, dict) else (lambda k, d=None: d)
    raw = get("query_doc_factor")
    rules = []
    if isinstance(raw, list):
        for r in raw:
            if not isinstance(r, dict):
                continue
            words = [str(w).strip() for w in (r.get("query_words") or ())
                     if str(w).strip()]
            if not words:
                continue
            docs = [str(d).strip() for d in (r.get("doc_contains") or ())
                    if str(d).strip()]
            ctypes = [str(c).strip() for c in (r.get("corpus_types") or ())
                      if str(c).strip()]
            sdoms = [str(s).strip().lower() for s in (r.get("source_domains") or ())
                     if str(s).strip()]
            if not (docs or ctypes or sdoms):
                continue
            try:
                f = float(r.get("factor"))
            except (TypeError, ValueError):
                continue
            if not math.isfinite(f) or f <= 0.0 or f > 2.0:
                continue
            rules.append({"name": str(r.get("name") or "rule%d" % len(rules)),
                          "query_words": tuple(words),
                          "doc_contains": tuple(docs),
                          "corpus_types": tuple(ctypes),
                          "source_domains": tuple(sdoms),
                          "factor": f})
    return {"enabled": bool(rules), "rules": tuple(rules)}


def query_doc_factor_fired_rules(query, rules):
    """题面 → 激活规则集（信号位：query_words 任一词形经 _ws_norm_text 归一
    （去全部空白+小写）后为归一题面子串 → 该规则激活——"IP 电话/核心网"级
    复合词形可互配，b_evict/丙层同款归一器）。恒不抛出。"""
    try:
        qn = _ws_norm_text(query)
        fired = []
        for r in (rules or ()):
            for w in r.get("query_words", ()):
                wn = _ws_norm_text(w)
                if wn and wn in qn:
                    fired.append(r)
                    break
        return fired
    except Exception:  # pragma: no cover —— 防御位：判定面恒不抛出
        return []


def _qdf_rule_hit(rec, rule):
    """块 rec → 是否命中规则目标面（doc_contains 子串 ∨ corpus_types 精确 ∨
    source_domain 归一精确；任一选择器任一值命中即真——目标面=并集语义，
    规则粒度的窄化由配表时单选择器单值实现）。"""
    rec = rec or {}
    doc = str(rec.get("doc_id") or "")
    for d in rule.get("doc_contains", ()):
        if d in doc:
            return True
    fam = str(rec.get("corpus_type") or "")
    for c in rule.get("corpus_types", ()):
        if c == fam:
            return True
    dom = _domain_of_rec(rec)
    for s in rule.get("source_domains", ()):
        if s == dom:
            return True
    return False


def query_doc_factor_rescore(hits, query, params):
    """查询-族定向加权重打分（纯函数）→ (新 hits, info)。

    - 激活规则（题面命中任一 query_word）对命中目标面的块把通道排序分乘
      规则 factor（多规则连乘）；**题面零命中任何规则信号=零改动直过**
      （恒激活规则在清洗面禁入=题面信号是本机制的必要条件）；
    - 余弦原始分恒存 hit["cosine"]（缺键补挂——纯余弦态 score 即余弦，
      lexical/hybrid/mq 态此前已附），gate_cosine 优先读 cosine——0.40 闸
      载体零侵蚀（②③/meta_filter/domain_downweight 同款薄余量纪律）；
    - 附 qdf_factor 键（仅命中块，连乘值；评测归因直读，口径同
      decrowd_factor/domain_factor）；重排 (-score, 原位次) 后 rank 重编
      1..n（同分 tie-break 确定性，同款排序键）；
    - 池内零命中块 → 原样返回（零拷贝零重排，bit 级直通）；params 关/空
      rules → 原样返回；hits 空 → 原样返回。输入 hits 不被修改。
    """
    info = {"fired": 0, "hit_n": 0, "rules": ()}
    if not hits:
        return hits, info
    fired = query_doc_factor_fired_rules(
        query, (params or {}).get("rules") or ())
    if not fired:
        return hits, info
    info["fired"] = len(fired)
    info["rules"] = tuple(r.get("name") or "?" for r in fired)
    factors, n_hit = [], 0
    for h in hits:
        f = 1.0
        for r in fired:
            if _qdf_rule_hit((h or {}).get("rec") or {}, r):
                f *= float(r.get("factor", 1.0))
        factors.append(f)
        if f != 1.0:
            n_hit += 1
    if not n_hit:
        return hits, info           # 池内零命中块：bit 级直通（零拷贝零重排）
    info["hit_n"] = n_hit
    out = []
    for h, f in zip(hits, factors):
        item = dict(h)
        if f != 1.0:
            if "cosine" not in item:
                item["cosine"] = item.get("score")   # 原始余弦（闸载体）补挂
            item["qdf_factor"] = round(f, 6)
            item["score"] = float(item.get("score") or 0.0) * f
        out.append(item)
    out.sort(key=lambda x: (-float(x.get("score") or 0.0), x["rank"]))
    for i, h in enumerate(out, 1):
        h["rank"] = i
    return out, info


# ---------------------------------------------------------------------------
# ADR-0018 融合级配额段＋弱注入辅助闸（2026-10-06 R3C，默认关=零调用面；键义
# 与在册纪律修订见件头注 2026-10-06 R3C 段；决策权威=决策/ADR-0018-mq融合
# 路径配额与降权载体.md〔已采纳，决策链=过程日志三节37③〕，设计稿=运营/扩容-R3
# 设计稿-mq键效力修复-20261006.md §一/§四。清洗纯函数，离线验证脚本同源复用
# ——与 clean_decrowd_params 同款"一把尺"纪律）
# ---------------------------------------------------------------------------
DEFAULT_WEAK_GATE_T_WEAK = 0.65       # (a) 绝对弱带上界（候选带 0.62-0.65，终值归标定轮）
DEFAULT_WEAK_GATE_FLAT_DELTA = 0.06   # (b) 梯度平坦阈 max−P50（候选带 0.05-0.08，终值归标定轮）
# 动作档：mark=A 级观测打点｜annotate=A+B 级降注｜trim=C 级减席（改成员，
# 2026-10-07 落码转合法档：只保 cos≥gate−keep_delta 的前席、自带 B 级降注
# =减席+声明；全量回归判据先定后测=设计稿 §4.3/§4.5）；D 级转拒答=禁用项
# （09-28 在档结论直接冲突，仅登记不设计）
WEAK_GATE_ACTIONS = ("mark", "annotate", "trim")
WEAK_GATE_DEFAULT_ACTION = "annotate"
# C 级减席保留带宽度：设计候选带 0.05-0.10 首值，终值归标定轮；
# C 级减席阈=只保 cos≥gate−Δ_keep 的前席
DEFAULT_WEAK_GATE_KEEP_DELTA = 0.05
# B 级降注提示行（build_evidence header_extra 位；紧附 EVIDENCE_HEADER 之后、
# 计入 max_context_chars 预算；措辞扩改须决策——prompt 级改动面）
WEAK_GATE_HINT = ("\n（注意：本次检索到的材料与问题的相关性较弱，以下语料仅供"
                  "背景参考，回答时请如实说明不确定性。）")
# [rag-mq] 归因行明细席位数上限（键开态融合池放粗到 60 时截前 10+尾注；关态
# 融合窗恒 ≤10=读数零变化，设计内观测面调整）
_MQ_LOG_DETAIL_MAX = 10


def clean_mq_fused_select_params(cfg):
    """ADR-0018 融合级配额段键清洗（容忍缺键/非法值→关；enabled 仅严格布尔
    true 开启——fold/evict 键同款口径）；mq_fused_candidates null/坏值/<1 →
    None=回退 (fold_win or topk) 数值零漂移（int 数值化沿 doc_quota_max 现役
    口径：bool→1、字符串整数→int、浮点截断，不单立尺）。"""
    cfg = cfg if isinstance(cfg, dict) else {}
    cands = cfg.get("mq_fused_candidates")
    if cands is not None:
        try:
            cands = int(cands)
        except (TypeError, ValueError):
            cands = None
        if cands is not None and cands < 1:
            cands = None
    return {"enabled": cfg.get("mq_fused_select_enabled") is True,
            "candidates": cands}


def _norm_weak_gate_num(v, default):
    """t_weak/flat_delta 数值化：非数字/NaN/越界 (0,1] 回默认档（坏值回默认=
    已知安全档，口径贴 clean_decrowd_params/_norm_score_threshold 先例）。"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(f) or f <= 0.0 or f > 1.0:
        return default
    return f


def clean_weak_gate_params(cfg):
    """弱注入辅助闸键清洗（嵌套 weak_gate 键域）→ 参数 dict。

    - weak_gate 非 dict（list/str 等）→ 整键回关（防误配半生效，口径贴
      clean_domain_downweight_params/clean_domain_doc_quota_params）；
    - enabled 仅严格布尔 true 开启；t_weak/flat_delta/keep_delta 坏值回默认
      档（_norm_weak_gate_num，域 (0,1]）；action 坏值回默认 "annotate"
      （坏值回默认=已知安全档，键族纪律；trim=C 级减席已转合法档）。
    """
    get = cfg.get if isinstance(cfg, dict) else (lambda k, d=None: d)
    raw = get("weak_gate")
    if not isinstance(raw, dict):
        raw = {}
    action = str(raw.get("action") or WEAK_GATE_DEFAULT_ACTION).strip().lower()
    if action not in WEAK_GATE_ACTIONS:
        action = WEAK_GATE_DEFAULT_ACTION
    return {"enabled": raw.get("enabled") is True,
            "t_weak": _norm_weak_gate_num(raw.get("t_weak"),
                                          DEFAULT_WEAK_GATE_T_WEAK),
            "flat_delta": _norm_weak_gate_num(raw.get("flat_delta"),
                                              DEFAULT_WEAK_GATE_FLAT_DELTA),
            "keep_delta": _norm_weak_gate_num(raw.get("keep_delta"),
                                              DEFAULT_WEAK_GATE_KEEP_DELTA),
            "action": action}


# ---------------------------------------------------------------------------
# 期 1 路由挂接参数清洗与选席约束（2026-09-29，默认关=零调用面；纯函数，
# 离线验证脚本同源复用——与 clean_decrowd_params 同款"一把尺"纪律）
# ---------------------------------------------------------------------------
def clean_route_params(cfg):
    """rag 配置段（DEFAULT_RAG_CONFIG 合并后形态）→ 路由挂接参数 dict。

    坏值一律回默认（口径贴 clean_decrowd_params：误配回已知安全档）；
    route_enabled=true 而 route_domain 模块缺席 → enabled=False（退关零收窄，
    warn 在 initialize 侧打）。route_vocab/route_light_topk 为期 1 观测位
    （classify 签名不支持词表注入=D9 决策面；轻检索 topk 归期 2 档 A 消费）。
    """
    get = (cfg or {}).get
    try:
        mc = int(get("route_min_confidence", DEFAULT_ROUTE_MIN_CONFIDENCE))
    except (TypeError, ValueError):
        mc = DEFAULT_ROUTE_MIN_CONFIDENCE
    mc = max(1, mc)
    policy = get("route_conflict_policy")
    policies = (route_domain.CONFLICT_POLICIES if route_domain is not None
                else ("fallback",))
    if policy not in policies:
        policy = "fallback"
    vocab = get("route_vocab")
    if not (vocab is None or (isinstance(vocab, list)
                              and all(isinstance(w, str) for w in vocab))):
        vocab = None   # 坏值回 null=内置词表
    try:
        ltk = int(get("route_light_topk", DEFAULT_ROUTE_LIGHT_TOPK))
    except (TypeError, ValueError):
        ltk = DEFAULT_ROUTE_LIGHT_TOPK
    if ltk < 1:
        ltk = DEFAULT_ROUTE_LIGHT_TOPK   # 坏值（越界）回默认（min_confidence 的
        # 下限钳 1 口径系 classify 侧同款语义，此处贴 decrowd 键"坏值回默认"纪律）
    return {"enabled": bool(get("route_enabled")) and route_domain is not None,
            "min_confidence": mc,
            "policy": policy,
            "vocab": vocab,
            "light_topk": ltk,
            "table_facet": bool(get("route_table_facet")),
            "doc_direct": bool(get("route_doc_direct", True))}


def route_constraint(params, route_res):
    """挂接参数 + server 端 classify 结果 → 生效选席约束；None=零收窄。

    契约（§2.4 硬门控）：只读 route 键 ∈ {"domain","doc_direct"}；route=
    "fallback"（veto=1/多域冲突/零命中/置信不足/多号并现/库外号）一律 None；
    veto=1 时 doc_direct 键仅观测禁收窄（classify 已保证该态 route=fallback，
    此处再设 veto 防御位——手工构造的不一致输入同样零收窄）。恒不抛出。
    返回形态：("domain", 域名) 或 ("doc", doc_id)。
    """
    try:
        if not (params or {}).get("enabled") or route_domain is None:
            return None
        if not isinstance(route_res, dict) or route_res.get("veto"):
            return None
        r = route_res.get("route")
        if r == "domain":
            dom = route_res.get("domain")
            return ("domain", dom) if dom in route_domain.DOMAINS else None
        if r == "doc_direct":
            doc = str(route_res.get("doc_direct") or "")
            return ("doc", doc) if doc else None
        return None
    except Exception:  # pragma: no cover —— 防御位：判定面恒不抛出
        return None


def route_rec_in(rec, constraint, table_facet=False):
    """库行元数据 rec → 是否属选席约束面（委托 route_domain.doc_in_domain 单锚）。

    - ("doc", doc_id)：doc_id 精确等值（classify 侧已做库形态归一）；
    - ("domain", 精确表) 且 table_facet=False（默认）：按 TS 全面不细分
      （=参数域谓词同构面，防 chunk_type 细分召回损失；细分属期 2 键面）；
    - 其余域委托 doc_in_domain（doc_id 前缀为准+缺字段行兜底，1,476 行
      不一致 2/3 的在册纪律）。恒不抛出：异常/未知形态一律 False（保守=
      该行不入域面，兜底回退机制接住召回）。
    """
    try:
        if route_domain is None or not constraint:
            return False
        kind, val = constraint
        if kind == "doc":
            return str((rec or {}).get("doc_id") or "") == val
        if val == "精确表" and not table_facet:
            return route_domain.doc_in_domain(rec, "参数")
        return route_domain.doc_in_domain(rec, val)
    except Exception:  # pragma: no cover —— 防御位
        return False


def _decrowd_round6(v):
    """快照/日志用安全圆整：非数值 → None。"""
    try:
        return round(float(v), 6)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# BM25 并路混合检索：纯标准库、零新增 API、默认关（2026-09-18）
#
# 动机与定位（与 lexical_boost 的区别，共存语义）：
# - lexical_boost 是**候选内重排**：只在余弦 top-N 候选内做二次词法打分，
#   只改"圈内的序"，余弦圈外的块拉不回（2026-09-18 评测：λ*=0 不开启）；
# - hybrid_bm25 是**并路混合**：BM25 独立通道全库召回（倒排索引直查），
#   与余弦通道各自出候选后融合（RRF 或加权和），可把余弦圈外的精确术语块
#   （参数名/表名/TS 号）拉回 topk——构造上与重排不同，互补面在"圈外召回"；
# - 两者同源（词法信号），叠加=同信号重复计权，**建议二选一**，默认皆关。
#   两开关同开时 hybrid 优先、lexical_boost 不生效（initialize 打 warn 一行）。
#
# 内存纪律（云端 ECS 总内存 1736M、服务现 used ~854M）：
# - 索引随向量库加载时构建并缓存；hybrid 关（默认）时不建=零内存零耗时；
# - postings 用 array('I') 双数组（doc 序号+词频各 4B/posting）压缩，相比
#   list[tuple] 形态每 posting 省 ~50B；估算/实测数字见 运营/BM25实现-20260918.md。
# ---------------------------------------------------------------------------
_BM25_ASCII_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def bm25_tokenize(text):
    """BM25 分词 → token 列表（保留重复，tf 由计数得）。

    规则（题面与块文本同一套，保证两侧对称）：
    - 中文连续段（CJK 统一表意区）→ 2-gram 滑窗（单字不成词）；
    - 英文/数字连续段（可含内连字符，保 p0-NominalPUSCH / a3-Offset 整词）→ 降 case；
    - 其余（标点/空白/全角符号）为切界不产 token；空文本/纯切界 → []。
    """
    if not text:
        return []
    low = text.lower()
    toks = []
    for run in _CJK_RUN_RE.findall(low):
        for i in range(len(run) - 1):
            toks.append(run[i:i + 2])
    ascii_toks = _BM25_ASCII_RE.findall(low)
    toks.extend(ascii_toks)
    # 分词补形（2026-10-09 键微调批，过程日志 51a）：连字符复合词保留整词外
    # 加发切分子词（两侧对称零删除）——治复合词形分裂投票（题面
    # ServingCell 形只命中部分变体块，BM25 票被锁死在个别块、余弦顶块
    # 拿不到票，RRF 让两路中游块夺冠=C03 反失机制）。实证=C03 正主回
    # src1；45 题净零换位（A89↔A94）。
    for t in ascii_toks:
        if "-" in t:
            toks.extend(p for p in t.split("-") if p)
    return toks


class BM25Index:
    """倒排索引 + Okapi BM25 打分（build 一次、search 多次、纯内存）。

    - build(recs)：recs 为 load_store 产物（只读 META_FIELDS 文本，不碰 vec）；
      文本口径同词法重排的 _rec_text（doc_id+version+locator+content），
      doc_id/locator 里的 TS 号/条款号参与索引，利好精确术语召回。
    - 形态：{term: array('I') doc 行序} + {term: array('I') tf}（两数组平行），
      df=len(序号数组)；doc 长度 array('I')；avgdl=总 token 数/文档数。
    - 打分（Lucene 口径，idf 恒正无负分支）：
      score(d,q) = Σ_t qtf_t × idf_t × tf(t,d)·(k1+1) / (tf(t,d)+k1·(1-b+b·dl/avgdl))
      其中 idf_t = ln(1+(N-df+0.5)/(df+0.5))，qtf 为题面 token 重复次数。
    - search 返回与 rag.search 同形态的 hits（含 idx），可直接参与 fuse_hits。
    """

    def __init__(self):
        self.recs = []          # 建索引时的 recs 引用（不复制，零额外文本内存）
        self._post_ids = {}     # term -> array('I') 库内行序
        self._post_tfs = {}     # term -> array('I') 词频（与 _post_ids 平行）
        self._doc_len = array("I")
        self.avgdl = 0.0
        self.n_docs = 0
        self.n_terms = 0
        self.n_postings = 0
        self.postings_bytes = 0  # postings 双数组裸字节数（监控/估算用）

    @classmethod
    def build(cls, recs, text_of=None):
        """recs → BM25Index。text_of(hit 文本) 默认 _rec_text；建索引 O(全量文本)。"""
        idx = cls()
        idx.recs = recs
        get_text = text_of or _rec_text
        doc_len = []
        post_ids, post_tfs = idx._post_ids, idx._post_tfs
        for i, rec in enumerate(recs):
            toks = bm25_tokenize(get_text(rec))
            doc_len.append(len(toks))
            tf = {}
            for t in toks:
                tf[t] = tf.get(t, 0) + 1
            for t, f in tf.items():
                ids = post_ids.get(t)
                if ids is None:
                    post_ids[t] = array("I", [i])
                    post_tfs[t] = array("I", [f])
                else:
                    ids.append(i)
                    post_tfs[t].append(f)
        idx.n_docs = len(recs)
        idx._doc_len = array("I", doc_len)
        idx.avgdl = (sum(doc_len) / idx.n_docs) if idx.n_docs else 0.0
        idx.n_terms = len(post_ids)
        for t, ids in post_ids.items():
            tfs = post_tfs[t]
            idx.n_postings += len(ids)
            idx.postings_bytes += (ids.buffer_info()[1] * ids.itemsize +
                                   tfs.buffer_info()[1] * tfs.itemsize)
        return idx

    def search(self, query, topk=DEFAULT_TOPK, k1=DEFAULT_BM25_K1, b=DEFAULT_BM25_B):
        """题面 → BM25 top-k → [hit,...]（rank/score/rec/idx，排序 (-score, 行序)）。

        - 空 token（空串/纯标点/单个汉字）→ []（调用方自然退单路余弦）；
        - k1 钳 ≥0、b 钳 [0,1]（防误配坏参数，不抛错）；
        - 索引空（无 postings/avgdl=0，即全库文本无 token）→ []。
        """
        toks = bm25_tokenize(query)
        if not toks or not self._post_ids or self.avgdl <= 0:
            return []
        k1 = max(0.0, float(k1))
        b = min(1.0, max(0.0, float(b)))
        qtf = {}
        for t in toks:
            qtf[t] = qtf.get(t, 0) + 1
        n = self.n_docs
        doc_len = self._doc_len
        avgdl = self.avgdl
        scores = {}
        for t, q in qtf.items():
            ids = self._post_ids.get(t)
            if ids is None:
                continue
            tfs = self._post_tfs[t]
            df = len(ids)
            idf = math.log(1.0 + (n - df + 0.5) / (df + 0.5))
            for i, f in zip(ids, tfs):
                dl = doc_len[i]
                scores[i] = scores.get(i, 0.0) + q * idf * (
                    f * (k1 + 1.0) / (f + k1 * (1.0 - b + b * dl / avgdl)))
        order = sorted(scores, key=lambda i: (-scores[i], i))
        return [{"rank": rank, "score": scores[i], "rec": self.recs[i], "idx": i}
                for rank, i in enumerate(order[: max(1, int(topk))], 1)]


# ---------------------------------------------------------------------------
# BM25 索引持久化（波3 工程件，2026-10-23；默认关=现状零变化）
#
# 动机：hybrid 开态下 82,210 块冷建倒排索引实测 ≈14.7s（171 号提交），每次
# 启动/重载全量重付；本件把建好的索引 pickle 落盘（store 同目录
# <store>.bm25idx.pkl），下次装载校验通过即直载——纯加速件，语义纪律同装载
# sidecar（2026-09-24）：校验失败/文件坏/键关一律无条件回退全量重建路径，
# 绝不抛出、绝不装载过期数据。
#
# 校验锚点（任一不符 → 弃缓存回退重建）：
# - fmt 版本 + 索引口径指纹（bm25_tokenize 分词规则或 _rec_text 消费字段变更
#   须改 BM25_INDEX_FINGERPRINT 串，旧缓存自动失效，禁自动沿用）；
# - 源 store 的 size+mtime_ns（同 sidecar 过期校验锚点：库在飞续写/换库即弃）；
# - 块数 n_docs 与向量维 dim 与当前装载面一致；
# - 结构逐项校验：doc_len 长度=块数、每词 ids/tfs 双数组等长且非空、typecode
#   为 'I'、avgdl 与 doc_len 现算值一致（派生统计不信缓存存值，现算即校验）。
#
# 安全：反序列化走 _BM25Unpickler（find_class 只放行 array.array——缓存数据
# 形态只有 dict/str/int/float/array），被篡改的缓存件无法借 pickle 执行任意
# 代码，只会被判坏回退重建。
#
# 纪律：缓存件只含 postings 双数组/doc_len/avgdl 派生面，不含块文本（recs
# 引用装载面、不落盘，装载后重新挂当前库 recs）；写=临时文件+os.replace
# 原子换入；写失败只 warn（现役索引已在内存，检索不受影响）。回退法=删缓存
# 件或将 bm25_persist 置 false 即回现状全量重建。
# ---------------------------------------------------------------------------
BM25_CACHE_SUFFIX = ".bm25idx.pkl"
BM25_CACHE_FMT = 1
# 索引口径指纹：分词规则（2026-10-09 连字符补形后口径）+索引文本字段面。
# 任一侧变更必须改本串（改串=全量旧缓存自动失效回退重建）。
BM25_INDEX_FINGERPRINT = ("cjk2gram+ascii-hyphen-split@2026-10-09"
                          "|text:doc_id+version+locator+content")


class _BM25Unpickler(pickle.Unpickler):
    """受限反序列化器（防 pickle 代码执行）：只放行 array 模块的 array 类与
    _array_reconstructor（协议≥3 下 array 的官方重建函数，纯构造无执行面），
    其余类（os/system/builtins.eval 等）一律拒——被篡改的缓存件只会被判坏
    回退重建，绝不执行。"""

    def find_class(self, module, name):
        if module == "array" and name in ("array", "_array_reconstructor"):
            import array as _array_mod
            return getattr(_array_mod, name)
        raise pickle.UnpicklingError(f"bm25 cache: class denied {module}.{name}")


def bm25_cache_path(store_path, cache_path=None):
    """store 路径 → BM25 缓存件路径（显式传入者优先；默认 store 同目录加后缀）。"""
    return cache_path or store_path + BM25_CACHE_SUFFIX


def save_bm25_index(idx, store_path, dim, cache_path=None):
    """BM25Index → pickle 落盘（幂等覆盖，临时文件+os.replace 原子换入）。

    只存 postings 双数组/doc_len/avgdl 派生面（recs 不落盘）；meta 记源 store
    size/mtime_ns（过期校验锚点，同 sidecar 口径）。写失败抛异常由调用方自理
    （调用方只 warn，不回退现役索引）。
    """
    cp = bm25_cache_path(store_path, cache_path)
    st = os.stat(store_path)
    payload = {
        "fmt": BM25_CACHE_FMT,
        "fingerprint": BM25_INDEX_FINGERPRINT,
        "src_size": st.st_size, "src_mtime_ns": st.st_mtime_ns,
        "n_docs": idx.n_docs, "dim": dim,
        "doc_len": idx._doc_len, "avgdl": idx.avgdl,
        "post_ids": idx._post_ids, "post_tfs": idx._post_tfs,
    }
    tmp = cp + ".tmp"
    with open(tmp, "wb") as f:
        pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(tmp, cp)
    return cp


def try_load_bm25_index(store_path, recs, dim, cache_path=None):
    """校验并读 BM25 缓存 → BM25Index 或 None（不适用/过期/坏 → None）。

    任何异常（文件缺失/坏 pickle/锚点不符/结构不符）都吞掉返回 None，调用方
    无条件回退 BM25Index.build 全量重建——纯加速件，绝不改变装载语义。
    """
    try:
        cp = bm25_cache_path(store_path, cache_path)
        st = os.stat(store_path)
        with open(cp, "rb") as f:
            payload = _BM25Unpickler(f).load()
        if not isinstance(payload, dict):
            return None
        if (payload.get("fmt") != BM25_CACHE_FMT or
                payload.get("fingerprint") != BM25_INDEX_FINGERPRINT or
                payload.get("src_size") != st.st_size or
                payload.get("src_mtime_ns") != st.st_mtime_ns or
                payload.get("n_docs") != len(recs) or
                payload.get("dim") != dim):
            return None
        idx = BM25Index()
        doc_len = payload.get("doc_len")
        post_ids, post_tfs = payload.get("post_ids"), payload.get("post_tfs")
        if (not isinstance(doc_len, array) or doc_len.typecode != "I" or
                len(doc_len) != len(recs) or
                not isinstance(post_ids, dict) or not isinstance(post_tfs, dict) or
                len(post_ids) != len(post_tfs)):
            return None
        for t, ids in post_ids.items():
            tfs = post_tfs.get(t)
            if (not isinstance(t, str) or not isinstance(ids, array) or
                    ids.typecode != "I" or not isinstance(tfs, array) or
                    tfs.typecode != "I" or len(ids) != len(tfs) or not ids):
                return None
        # 派生统计现算（同 build 口径）——现算即校验，不信缓存存值
        n_docs = len(recs)
        avgdl = (sum(doc_len) / n_docs) if n_docs else 0.0
        if abs(avgdl - float(payload.get("avgdl", -1.0))) > 1e-9 * max(1.0, avgdl):
            return None
        idx.recs = recs
        idx._post_ids = post_ids
        idx._post_tfs = post_tfs
        idx._doc_len = doc_len
        idx.avgdl = avgdl
        idx.n_docs = n_docs
        idx.n_terms = len(post_ids)
        for t, ids in post_ids.items():
            tfs = post_tfs[t]
            idx.n_postings += len(ids)
            idx.postings_bytes += (ids.buffer_info()[1] * ids.itemsize +
                                   tfs.buffer_info()[1] * tfs.itemsize)
        return idx
    except Exception:
        return None


def hybrid_gate_hit(q_text, vocab=None, patterns=None):
    """题面词面门控判定（纯函数，W2 方案一，2026-10-08）→ bool。

    BM25 tokenize 前的题面级判定（_search_one hybrid 分支挂点）：
    - 词形：vocab 任一词经 _ws_norm_text 归一（去全部空白+小写）后为归一题面
      子串（"IP 电话"与"IP电话"互配，b_evict 同口径）；
    - 正则：patterns 任一式对**归一题面或原始题面**搜索命中——驼峰式裸参数名
      （subcarrierSpacing 形）的驼峰信号会被小写归一破坏，须保留原始题面匹配面；
    - 空词表+空正则=False；空/None 题面=False；vocab/patterns 非 list 形
      （tuple 等）同样可迭代；模式串（str）自动 re.compile（测试注入面）。
    词表与正则维护纪律见常量段注释块（扩改须决策，禁自动生效）。
    """
    if not q_text:
        return False
    qn = _ws_norm_text(q_text)
    for w in vocab or ():
        wn = _ws_norm_text(str(w))
        if wn and wn in qn:
            return True
    for p in (patterns or ()):
        rx = p if hasattr(p, "search") else re.compile(str(p))
        if rx.search(qn) or rx.search(q_text):
            return True
    return False


def clean_hybrid_gate_extra_params(cfg):
    """rag 配置段（DEFAULT_RAG_CONFIG 合并后形态）→ 门控注入键族装载面 dict。

    R 线二期 S1 新键族（2026-10-17；键义见常量段注释块）：vocab_extra 与生效
    词表、patterns_extra 与内置 PATTERNS 均 OR 合并（预编译），combo 为
    ctx∧sig(∧conj) 组合形 AND 面；initialize 与离线验证脚本共用（同一套
    坏值口径，防"线上/离线两把尺"）。全部键容忍缺失（缺失=默认空=合并后即
    原表=现状逐字节一致——feature flag 关态零行为面）。坏正则/坏项单条丢弃
    不整组回退（口径贴 clean_decrowd_params 白名单段：用户显式给表即尊重
    意图，坏条目不吞好条目），丢弃数计入 dropped 供 initialize 日志。

    返回 dict：vocab/patterns=合并后判定面（词表 tuple、正则 tuple of
    re.Pattern）；combos=tuple of 段元组（每形 2-3 个预编译 re.Pattern）；
    n_forms/dropped/face_sha256=装载面指纹（规范化形态排序键 JSON dump 的
    SHA256，不含元数据键——拨键执行单对账锚）。
    """
    get = cfg.get if isinstance(cfg, dict) else (lambda k, d=None: d)
    base_vocab = get("hybrid_gate_vocab")
    base_vocab = ([str(w) for w in base_vocab if str(w).strip()]
                  if isinstance(base_vocab, list) else list(HYBRID_GATE_VOCAB))
    vx = get("hybrid_gate_vocab_extra")
    vocab_extra = ([str(w) for w in vx if str(w).strip()]
                   if isinstance(vx, list) else [])
    px = get("hybrid_gate_patterns_extra")
    patterns_extra, px_dropped = [], 0
    if isinstance(px, list):
        for pat in px:
            ps = str(pat)
            if not ps.strip():
                continue
            try:
                patterns_extra.append(re.compile(ps))
            except re.error:
                px_dropped += 1
    cb = get("hybrid_gate_combo")
    combos, combo_face, cb_dropped = [], [], 0
    if isinstance(cb, list):
        for item in cb:
            if not isinstance(item, list) or not 2 <= len(item) <= 3:
                cb_dropped += 1
                continue
            segs, bad = [], False
            for s in item:
                ss = str(s)
                if not ss.strip():
                    bad = True
                    break
                try:
                    segs.append((ss, re.compile(ss)))
                except re.error:
                    bad = True
                    break
            if bad:
                cb_dropped += 1
                continue
            combos.append(tuple(rx for _ss, rx in segs))
            combo_face.append([ss for ss, _rx in segs])
    face = {"combo": combo_face,
            "patterns_extra": [p.pattern for p in patterns_extra],
            "vocab_extra": vocab_extra}
    return {
        "vocab": tuple(base_vocab) + tuple(vocab_extra),
        "patterns": tuple(HYBRID_GATE_PATTERNS) + tuple(patterns_extra),
        "combos": tuple(combos),
        "vocab_extra": tuple(vocab_extra),
        "patterns_extra": tuple(patterns_extra),
        "n_forms": len(vocab_extra) + len(patterns_extra) + len(combos),
        "dropped": px_dropped + cb_dropped,
        "face_sha256": hashlib.sha256(json.dumps(
            face, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
    }


def hybrid_gate_combo_hit(q_text, combos):
    """组合形 AND 门控判定（R 线二期 S1 新键族，2026-10-17）→ bool。

    combos=装载面段元组（每形 2-3 个预编译 re.Pattern：ctx∧sig 基式、conj
    第三段可选）：任一形全段成立即 True；每段=对归一题面（_ws_norm_text：
    去全部空白+小写）**或原始题面**搜索命中——与 hybrid_gate_hit 正则面/
    影子臂 form_hit_v2 同器的双匹配（驼峰/大小写信号在归一面丢失，须保留
    原始题面匹配面）。空/None 题面=False；combos 空=False（默认关态短路不
    进循环）。语义与影子臂 form_hit_v2 逐字同器（AND 合取与段判定次序无关，
    桥接断言=施工方案件 §四 2）。
    """
    if not q_text:
        return False
    qn = _ws_norm_text(q_text)
    for segs in combos or ():
        hit = True
        for rx in segs:
            if not (rx.search(qn) or rx.search(q_text)):
                hit = False
                break
        if hit:
            return True
    return False


def entry_fire(text, e):
    """查询预处理词条触发判定（R 线二期 S1，2026-10-17；影子臂同器移植）→ bool。

    combo 词条=ctx∧sig 合取（每段归一面∨原始面双匹配，与 hybrid_gate_hit/
    form_hit 同器语义）；提取词条（kind="pattern"）=patterns 任一命中即触发。
    空/None 题面=False。
    """
    if not text:
        return False
    qn = _ws_norm_text(text)
    if e["kind"] == "combo":
        rc, rs = re.compile(e["ctx"]), re.compile(e["sig"])
        return bool((rc.search(qn) or rc.search(text))
                    and (rs.search(qn) or rs.search(text)))
    for p in e["patterns"]:
        rx = re.compile(p)
        if rx.search(qn) or rx.search(text):
            return True
    return False


def entry_append(text, e):
    """词条追加串（影子臂同器移植）→ str 或 None。

    combo 词条=append 原样返回；提取形=数值入规范形（unit_norm：兆→MHz、
    千分之一→‰；std_norm：YD/GB 行标号→"YD/T n"/"GB/T n" 形）；None=触发
    但无追加=不 fire（追加式纪律：替换式仅限提取形的规范化段——追加规范形
    而非替换原词面）。
    """
    qn = _ws_norm_text(text)
    if e["kind"] == "combo":
        return e["append"]
    parts = []
    if e["append_kind"] == "unit_norm":
        m = re.search(r"([0-9]+(?:\.[0-9]+)?)兆", qn) or \
            re.search(r"([0-9]+(?:\.[0-9]+)?)\s*兆", text)
        if m:
            parts.append("%s MHz" % m.group(1))
        if "千分之一" in qn or "千分之一" in text:
            parts.append("‰ 0.001")
        return (" " + " ".join(parts)) if parts else None
    if e["append_kind"] == "std_norm":
        for p in e["patterns"]:
            rx = re.compile(p)
            m = rx.search(qn) or rx.search(text)
            if m:
                num = m.group(1) if m.groups() else ""
                prefix = "YD/T" if p.lstrip("(?<").startswith("YD") or "YD" in p[:20] \
                    else "GB/T"
                parts.append("%s %s" % (prefix, num))
        return (" " + " ".join(parts)) if parts else None
    return None


def preprocess_query(text, entries):
    """q → q'（追加式；词条序=装载序，确定性）→ (q', fired_ids)。

    R 线二期 S1 查询预处理（2026-10-17）：entry_fire 触发且 entry_append 非
    None 才追加（fired 只计实际追加了串的词条）；无任何追加=q'=q 恒等。
    消费位=_search_one 入口（门控/BM25/qdf 三消费点全部吃 q'；嵌入调用点在
    其前=向量不动）。生效面声明：一切进 _search_one 的 q 都过本器（非 L1
    目标题独享；含 mq 变体路——NR-8 联动注记）。
    """
    if not text:
        return text, []
    parts, fired = [], []
    for e in entries:
        if entry_fire(text, e):
            ap = entry_append(text, e)
            if ap:
                parts.append(ap.strip())
                fired.append(e["id"])
    if not parts:
        return text, []
    return text + " " + " ".join(parts), fired


def clean_query_preprocess_entries(cfg):
    """rag 配置段 → 查询预处理词条装载面 dict（R 线二期 S1，2026-10-17）。

    query_preprocess_entries：null/非 list=空（默认关=q'=q 恒等=等价现态）；
    词条 schema=S1 修订集 v2 词条集原 schema（combo 词条={id, kind:"combo",
    ctx, sig, append}；提取词条={id, kind:"pattern", patterns,
    append_kind:"unit_norm"|"std_norm"}）——通过校验的词条 dict 原样保留
    （含 template/rationale 等元数据字段：装载面 SHA 与预注册集排序键序列化
    同形，对账直通）。坏词条（非 dict/缺 id/键型不符）单条丢弃+计数
    （initialize 日志 [rag-preprocess] dropped 位，不进题面）。与
    clean_hybrid_gate_extra_params 同为单一清洗权威（离线复放器同源复用）。
    """
    get = cfg.get if isinstance(cfg, dict) else (lambda k, d=None: d)
    raw = get("query_preprocess_entries")
    entries, dropped = [], 0
    if isinstance(raw, list):
        for e in raw:
            ok = False
            if isinstance(e, dict) and isinstance(e.get("id"), str) \
                    and e["id"].strip():
                if e.get("kind") == "combo":
                    ok = all(isinstance(e.get(k), str) and e.get(k).strip()
                             for k in ("ctx", "sig", "append"))
                elif e.get("kind") == "pattern":
                    ok = (isinstance(e.get("patterns"), list) and e["patterns"]
                          and all(isinstance(p, str) and p.strip()
                                  for p in e["patterns"])
                          and e.get("append_kind") in ("unit_norm", "std_norm"))
            if ok:
                entries.append(e)
            else:
                dropped += 1
    return {
        "entries": tuple(entries),
        "n": len(entries),
        "dropped": dropped,
        "face_sha256": hashlib.sha256(json.dumps(
            entries, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
    }


def fuse_hits(cos_hits, bm_hits, topk=DEFAULT_TOPK, mode="rrf",
              rrf_k=DEFAULT_HYBRID_RRF_K, bm25_weight=DEFAULT_HYBRID_BM25_WEIGHT):
    """余弦/BM25 两路候选 → 融合 → 截 topk（输出可直接喂 build_evidence）。

    - 输入两路 hits（rag.search / BM25Index.search 形态，需含 idx=库内行序），
      任一路可空/None（空路=单路退化，该路不计贡献，序保持该路原序）；
    - rrf 模式：fused(d) = Σ_该 d 入选的路 1/(rrf_k + 该路 rank)（rank 从 1 起）；
    - weighted 模式：两路各自按本路候选最大分归一到 [0,1]（max≤0 的路整体计 0；
      未入某路的 doc 该路计 0），fused = (1-w)*cos' + w*bm25'，w=bm25_weight∈[0,1]；
    - 排序 (-fused, cos_rank 缺省 +inf, bm25_rank 缺省 +inf, idx)：同分确定性；
    - 输出 hit 在输入形态上另附：channels（"cos"/"bm25"/"cos+bm25"）、
      cosine/bm25（两路原始分，未入路为 None）、cos_rank/bm25_rank（未入路 None）
      ——评测归因直接读这几个键；输入 hits 不被修改（输出为新 dict）。
    """
    cos_by = {h["idx"]: h for h in (cos_hits or [])}
    bm_by = {h["idx"]: h for h in (bm_hits or [])}
    idxs = set(cos_by) | set(bm_by)
    if not idxs:
        return []
    mode = "weighted" if str(mode) == "weighted" else "rrf"
    w = min(1.0, max(0.0, float(bm25_weight)))
    k = float(rrf_k)
    if not math.isfinite(k) or k <= 0.0:
        k = DEFAULT_HYBRID_RRF_K
    cos_max = max((h["score"] for h in cos_by.values()), default=0.0)
    bm_max = max((h["score"] for h in bm_by.values()), default=0.0)
    out = []
    for i in idxs:
        ch, bm = cos_by.get(i), bm_by.get(i)
        if mode == "rrf":
            fused = 0.0
            if ch is not None:
                fused += 1.0 / (k + ch["rank"])
            if bm is not None:
                fused += 1.0 / (k + bm["rank"])
        else:
            cn = (ch["score"] / cos_max) if ch is not None and cos_max > 0 else 0.0
            bn = (bm["score"] / bm_max) if bm is not None and bm_max > 0 else 0.0
            fused = (1.0 - w) * cn + w * bn
        out.append({"score": fused, "rec": (ch or bm)["rec"], "idx": i,
                    "channels": "cos+bm25" if ch is not None and bm is not None
                    else ("cos" if ch is not None else "bm25"),
                    "cosine": ch["score"] if ch is not None else None,
                    "bm25": bm["score"] if bm is not None else None,
                    "cos_rank": ch["rank"] if ch is not None else None,
                    "bm25_rank": bm["rank"] if bm is not None else None})
    out.sort(key=lambda h: (-h["score"],
                            h["cos_rank"] if h["cos_rank"] is not None else 1 << 30,
                            h["bm25_rank"] if h["bm25_rank"] is not None else 1 << 30,
                            h["idx"]))
    keep = out[: max(1, int(topk))]
    for rank, h in enumerate(keep, 1):
        h["rank"] = rank
    return keep


def _fmt_hybrid_line(hits, cos_n, bm_n, mode):
    """混合检索归因日志行：每 hit 的通道来源+两路原始分+融合分（评测直接读）。"""
    parts = [f"mode={mode} cos_n={cos_n} bm25_n={bm_n} hits={len(hits)}"]
    for h in hits:
        rec = h["rec"]
        name = rec.get("doc_id") or rec.get("id") or "?"
        cos_s = "na" if h["cosine"] is None else f"{h['cosine']:.4f}"
        bm_s = "na" if h["bm25"] is None else f"{h['bm25']:.4f}"
        parts.append(f"#{h['rank']} {name}|{rec.get('locator') or ''}"
                     f"|ch={h['channels']}|cos={cos_s}|bm25={bm_s}"
                     f"|fused={h['score']:.5f}")
    return "[rag-hybrid] " + " ; ".join(parts)


def _fmt_mq_line(lists, hits):
    """multi-query 融合归因日志行：各查询路深度+每 hit 出自哪些查询+融合分。

    形态对齐 _fmt_hybrid_line（评测归因直接读；不含查询/变体文本，口径同
    [rag-embed] 纪律）：
      [rag-mq] queries=3 lens=20/20/20 hits=5 ; #1 DOC-3|A.1|q=q0+q1|fused=0.03279
    """
    lens = "/".join(str(len(q)) for q in lists)
    parts = [f"queries={len(lists)} lens={lens} hits={len(hits)}"]
    # 明细席位上限（2026-10-06 R3C）：mq_fused_select 键开态融合池放粗到
    # mq_fused_candidates（60）时截前 10+尾注，防 journal 行爆炸；关态融合窗
    # 恒 ≤10（fold_win or topk）=读数与既往逐字节一致
    for h in hits[: _MQ_LOG_DETAIL_MAX]:
        rec = h["rec"]
        name = rec.get("doc_id") or rec.get("id") or "?"
        parts.append(f"#{h['rank']} {name}|{rec.get('locator') or ''}"
                     f"|q={h['queries']}|fused={h['score']:.5f}")
    if len(hits) > _MQ_LOG_DETAIL_MAX:
        parts.append(f"...(+{len(hits) - _MQ_LOG_DETAIL_MAX})")
    return "[rag-mq] " + " ; ".join(parts)


# ---------------------------------------------------------------------------
# 分数阈值闸门（off_topic 双做，2026-09-21 批1）
# ---------------------------------------------------------------------------
class LowScoreResult:
    """off_topic 闸门标记：retrieve() 在证据集余弦低于 score_threshold 时返回。

    携带触发分数与阈值（cosine=余弦原始分口径，纯余弦态即 top1 分；服务端
    [chat] top1= 打点与复验采集直接读）；evidence/sources 均不产出——调用方
    据此走"不下发 sources、先发 off_topic 事件、照常裸答流式"分支。检索失败
    兜底语义不变（异常仍返回 None=rag=miss，与本标记严格区分）。
    """

    __slots__ = ("cosine", "threshold")

    def __init__(self, cosine, threshold):
        self.cosine = float(cosine)
        self.threshold = float(threshold)

    def __repr__(self):  # 调试友好；只含分数，无任何敏感值
        return f"LowScoreResult(cosine={self.cosine:.4f}, threshold={self.threshold})"


class CoverageMissResult:
    """覆盖闸标记（S1 治理丙，2026-09-28）：题面含库外域词表词（安全词形）而
    证据集全部块文本（_rec_text 口径）不含该词时 retrieve() 返回——检索面零支撑
    的硬拒（与生成侧"语料未覆盖"软声明分工，方案 §二路径丙）。

    携带触发词清单 words 与闸前余弦观测值（cosine=证据集最大余弦原始分，
    threshold=低分闸生效阈值；串联语义=过 0.40 线之后仍可触发本闸）；evidence/
    sources 均不产出——调用方走与 LowScoreResult 同构的分支（不注入证据、不下发
    sources、先发 off_topic 事件再照常裸答流式），打点态 coverage_miss 与
    low_score 严格区分。
    """

    __slots__ = ("words", "cosine", "threshold")

    def __init__(self, words, cosine, threshold):
        self.words = tuple(str(w) for w in words)
        self.cosine = float(cosine)
        self.threshold = float(threshold)

    def __repr__(self):  # 调试友好；只含词形与分数，无任何敏感值
        return (f"CoverageMissResult(words={'/'.join(self.words)}, "
                f"cosine={self.cosine:.4f}, threshold={self.threshold})")


def gate_cosine(hits):
    """hits（任一通道输出形态）→ 阈值闸门用的余弦原始分；无可用余弦 → None。

    - 取证据集（top-k）内**最大**余弦原始分：纯余弦态排序即余弦序，首名=最大，
      与阈值分析"top1 命中"口径逐字一致（全部标定数据均采自纯余弦态）；
    - hybrid/lexical 态融合或重排会改序：精确术语块（余弦 0-0.2、BM25/词法强）
      被抬到首位是词法增强的设计目的，按 top1 字面口径会误拦这类域内命中
      （test_bm25 加权融合/词法重排两测的在册行为即此形态）；取集内最好语义
      分既保住"宁可放行"取向（阈值分析 §四），又对域外题等价拦（域外题
      整集余弦都低，max 与 top1 同落闸下）；
    - 纯余弦态 hit 无 cosine 键（score 即余弦）；lexical/hybrid/mq 态已附
      cosine 键（rerank_hits / fuse_hits / rrf_fuse_hit_lists）；
    - 全部无值（理论态）→ None=不闸（调用方按通过处理）。
    """
    best = None
    for h in hits:
        c = h["cosine"] if "cosine" in h else h.get("score")
        if isinstance(c, (int, float)) and not isinstance(c, bool) and math.isfinite(c):
            c = float(c)
            if best is None or c > best:
                best = c
    return best


def weak_gate_eval(hits, params):
    """弱注入辅助闸判据 (a)∧(b)（纯函数，2026-10-06 R3C）→ info dict。

    不改成员、不改分、不拦截——软处置辅助面（0.40 主闸语义零改动、不立第三
    拒答态；设计稿=运营/扩容-R3设计稿-mq键效力修复-20261006.md §四）：
    - (a) 绝对弱带：gate_cosine（集内最大原始余弦，与 0.40 主闸同器读数）
      < t_weak——Q1 形 0.619 触发/Q2 形 0.6735 不触发/Q3 形 0.6474 邻界
      （在档锚点）；
    - (b) 梯度平坦：集内 max − P50 < flat_delta（无主导正主、整组弱匹配——
      Q1 span 0.054 平坦形；同族正主多块 0.75 均一带也平坦，但距弱带远，
      AND(a) 后零误触=单判据必误伤的组合化解）；
    - 判据载体=集内**原始余弦分布**（gate_cosine 同款提取面：纯余弦态读
      score、lexical/hybrid/mq 态读 cosine 键）——RRF 融合分绝不作载体
      （设计明文继承，0.40 闸分纪律同款）；
    - 集内可用余弦 <2（理论态）→ grad=None=(b) 不可判=不触发（保守向）；
      hits 空/params 关 → weak=False 恒不抛出。
    """
    info = {"weak": False, "gate": None, "p50": None, "grad": None, "n": 0}
    if not hits or not (params or {}).get("enabled"):
        return info
    coss = []
    for h in hits:
        c = h["cosine"] if "cosine" in h else h.get("score")
        if isinstance(c, (int, float)) and not isinstance(c, bool) \
                and math.isfinite(c):
            coss.append(float(c))
    if not coss:
        return info
    s = sorted(coss)
    n = len(s)
    p50 = s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0
    gate = s[-1]
    grad = (gate - p50) if n >= 2 else None
    info.update({"gate": gate, "p50": p50, "grad": grad, "n": n})
    # 阈值防御位：调用方恒传 clean_weak_gate_params 产物（两键恒在位）；直调
    # 缺键/坏值回默认档（纯函数恒不抛出，gate_cosine 同款保守向）
    try:
        t_w = float(params.get("t_weak", DEFAULT_WEAK_GATE_T_WEAK))
        f_d = float(params.get("flat_delta", DEFAULT_WEAK_GATE_FLAT_DELTA))
    except (TypeError, ValueError):
        return info
    info["weak"] = bool(grad is not None and gate < t_w and grad < f_d)
    return info


def _norm_score_threshold(v):
    """score_threshold 配置值清洗 → 生效阈值。null/0/负数/NaN=0.0（关闸）；
    坏值（非数字）回默认 0.40（防误配静默失效而非静默关闭）。"""
    if v is None:
        return 0.0
    try:
        t = float(v)
    except (TypeError, ValueError):
        return DEFAULT_SCORE_THRESHOLD
    if not math.isfinite(t) or t <= 0.0:
        return 0.0
    return t


def cover_gate_miss_words(query, hits, vocab=None):
    """丙：覆盖闸探查 → 触发词清单（空 list=不触发）。

    口径=方案 §二路径丙（离线模拟对齐件 s1_negctrl_eval.cover_gate_sim，语义
    移植保持一致）：题面（归一=去空白+小写）含词表词，而证据集**全部**块文本
    （_rec_text 拼接后同归一）不含该词 → 该词触发（须全缺才触发，任一块含词
    即放行——域内题证据块与主体词同现不误拦）。vocab 可注入（测试/配置覆盖），
    缺省=内置安全词形 COVER_GATE_VOCAB（裸词"5G"禁入表，域内误拦实证在档）。
    """
    words = [str(w) for w in (vocab if vocab is not None else COVER_GATE_VOCAB)
             if str(w).strip()]
    qn = _ws_norm_text(query)
    texts = [_ws_norm_text(_rec_text(h["rec"])) for h in (hits or [])]
    return [w for w in words if _ws_norm_text(w) in qn
            and all(_ws_norm_text(w) not in t for t in texts)]


def _norm_mq_budget(v, fallback):
    """mq 预算键清洗（批B4，2026-09-22）→ 生效秒预算或 fallback。

    钳制口径贴批A server._depth_config 的 timeout 键先例：
    - None（键未配）→ fallback（mq_variant_timeout 回退旧键 mq_timeout_seconds；
      mq_wall_timeout 回退 None=无整体预算，即旧行为）；
    - 非数字/NaN/越界 (0, MQ_BUDGET_MAX_SECONDS] → fallback（防误配零预算
      静默关断或超大值长挂起——误配回到已知安全档而非就近钳边）。"""
    if v is None:
        return fallback
    try:
        f = float(v)
    except (TypeError, ValueError):
        return fallback
    if f != f or not (0.0 < f <= MQ_BUDGET_MAX_SECONDS):
        return fallback
    return f


def clean_mq_condense_params(cfg):
    """mq condense 键族清洗（2026-10-24 施工，默认关=零调用面零漂移）→ dict。

    键义/费帽/观测面详见 multiquery.py condense 段+建库/work/mq施工-20261024/
    判据预登记-20261024.md §1.1；清洗纪律（防两把尺——离线复放脚本同源复用）：
    - enabled：仅严格布尔 true 开（hybrid_gated_enabled 先例：误配回安全关）；
    - model：str 化，缺省/空回 multiquery.DEFAULT_MQ_MODEL（flash 档，禁旗舰）；
    - timeout：_norm_mq_budget 钳 (0,MQ_BUDGET_MAX_SECONDS] 回
      DEFAULT_MQ_CONDENSE_TIMEOUT（防误配零预算静默关断）；
    - turns/chars：int 钳 (0,hi] 回默认（零帽/超大帽=误配回安全档而非就近钳边）。
    """
    d = cfg if isinstance(cfg, dict) else {}
    _mq_def_model = (multiquery.DEFAULT_MQ_MODEL if multiquery
                     else "qwen3.8-flash")
    _mq_def_t = (multiquery.DEFAULT_MQ_CONDENSE_TIMEOUT if multiquery else 3.0)
    _mq_def_turns = (multiquery.DEFAULT_MQ_CONDENSE_HISTORY_TURNS
                     if multiquery else 4)
    _mq_def_chars = (multiquery.DEFAULT_MQ_CONDENSE_HISTORY_CHARS
                     if multiquery else 1200)

    def _int_cap(v, default, hi):
        try:
            n = int(v)
        except (TypeError, ValueError):
            return default
        return n if 0 < n <= hi else default

    return {
        "enabled": d.get("mq_condense_enabled") is True,
        "model": (str(d.get("mq_condense_model"))
                  if isinstance(d.get("mq_condense_model"), str)
                  and str(d.get("mq_condense_model")).strip() else _mq_def_model),
        "timeout": _norm_mq_budget(d.get("mq_condense_timeout"), _mq_def_t),
        "turns": _int_cap(d.get("mq_condense_history_turns"), _mq_def_turns, 1000),
        "chars": _int_cap(d.get("mq_condense_history_chars"), _mq_def_chars, 100000),
    }


# ---------------------------------------------------------------------------
# embedding 月度预算闸（2026-09-28 增，默认关；闸点=RagService._embed 前）
# ---------------------------------------------------------------------------
class EmbedBudgetExceeded(RuntimeError):
    """月度硬顶标记：_embed 检出台账当月累计 ≥ embed_monthly_cap_cny 时抛出，
    retrieve 兜底捕获 → 返回 None=退纯裸答（日志 rag=miss err=EmbedBudgetExceeded
    与 [rag-budget] block 行双标记）。"""


def _norm_budget_cny(v, default):
    """预警/硬顶键清洗：非数字/NaN/≤0 → 默认（防误配静默失效而非静默关闭，
    口径贴 _norm_score_threshold 先例）。"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(f) or f <= 0.0:
        return default
    return f


def parse_ledger_ts(ts):
    """台账 ts 字段 → (date|None, 当日秒数|None)。

    现行台账两形态：'HH:MM:SS'（无日期，绝大多数行）与
    'YYYY-MM-DD HH:MM:SS'（带日期锚行，如 2026-09-21 rerank试点行）；
    纯日期 'YYYY-MM-DD' → (date, None)。其余/坏值 → (None, None)。
    """
    s = str(ts or "").strip()
    if not s:
        return None, None
    parts = s.split()
    day = None
    idx = 0
    if len(parts[0].split("-")) == 3:
        try:
            y, m, d = (int(x) for x in parts[0].split("-"))
            day = date(y, m, d)
        except ValueError:
            return None, None
        idx = 1
    secs = None
    if len(parts) > idx:
        bits = parts[idx].split(":")
        if len(bits) in (2, 3) and all(b.isdigit() for b in bits):
            h, mi = int(bits[0]), int(bits[1])
            sec = int(bits[2]) if len(bits) == 3 else 0
            if 0 <= h < 24 and 0 <= mi < 60 and 0 <= sec < 60:
                secs = h * 3600 + mi * 60 + sec
    return day, secs


def ledger_month_tokens(path, year_month, day_gap_s=LEDGER_DAY_GAP_S):
    """embed用量台账 → year_month（'YYYY-MM'）切片 prompt_tokens 求和（int）。

    月度归属重建（现行台账 ts 无日期的实态）：
    - 带日期行=锚（按行内日期归属）；锚前行段反向步进、锚后行段正向步进：
      相邻行当日时间回跳（正向）/前跳（反向）> day_gap_s 即跨一日
      （date±1 天，跨月自动进位）；时间不可解析行沿用前行归属（防御）；
    - 无任何锚行 → 全部行归所查当月（保守过拦：宁可多计不漏计）；
    - 文件缺失/坏行/坏 ts 一律计 0，绝不抛出（闸是运营件，不拦请求）。
    已知边界（在册）：≤day_gap_s 的跨午夜续跑记到前一日——只在月界且恰有
    此形态续跑时影响归属（当前台账 6,007 行全落 2026-09，不受影响）。
    """
    if not os.path.exists(path):
        return 0
    rows = []
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
            day, secs = parse_ledger_ts(obj.get("ts"))
            pt = obj.get("prompt_tokens")
            tok = pt if isinstance(pt, (int, float)) and not isinstance(pt, bool) else 0
            rows.append((day, secs, tok))
    if not rows:
        return 0
    anchors = [i for i, r in enumerate(rows) if r[0] is not None]
    if not anchors:
        return int(sum(r[2] for r in rows))  # 无锚：全归当月（保守）
    months = [None] * len(rows)

    # 正向步进：各锚行 → 下一锚行（或 EOF）之间的无日期行
    for k, ai in enumerate(anchors):
        end = anchors[k + 1] if k + 1 < len(anchors) else len(rows)
        cur_day = rows[ai][0]
        prev_secs = rows[ai][1]
        months[ai] = cur_day.strftime("%Y-%m")
        for j in range(ai + 1, end):
            day_j, secs_j, _ = rows[j]
            if day_j is not None:  # 防御（锚列表之外的带日期行不会出现）
                months[j] = day_j.strftime("%Y-%m")
                cur_day, prev_secs = day_j, secs_j
                continue
            if (secs_j is not None and prev_secs is not None
                    and secs_j < prev_secs - day_gap_s):
                cur_day = cur_day + timedelta(days=1)
            if months[j] is None:
                months[j] = cur_day.strftime("%Y-%m")
            if secs_j is not None:
                prev_secs = secs_j
    # 反向步进：首锚行之前的无日期行
    first = anchors[0]
    cur_day = rows[first][0]
    next_secs = rows[first][1]
    for j in range(first - 1, -1, -1):
        day_j, secs_j, _ = rows[j]
        if day_j is not None:  # 防御
            months[j] = day_j.strftime("%Y-%m")
            cur_day, next_secs = day_j, secs_j
            continue
        if (secs_j is not None and next_secs is not None
                and secs_j > next_secs + day_gap_s):
            cur_day = cur_day - timedelta(days=1)
        if months[j] is None:
            months[j] = cur_day.strftime("%Y-%m")
        if secs_j is not None:
            next_secs = secs_j
    return int(sum(r[2] for r, m in zip(rows, months) if m == year_month))


# ---------------------------------------------------------------------------
# 证据文本组装
# ---------------------------------------------------------------------------
# sources.quote（2026-09-22 深度提升批A 增，只增不删）：该 chunk 正文前
# SOURCE_QUOTE_CHARS 字符、压平空白——供 server.py 引文忠实度校验（A1，
# citation_check.build_judge_messages）与前端出处悬浮预览消费；不参与
# evidence_text 组装，不影响 max_context_chars 预算口径。
SOURCE_QUOTE_CHARS = 200


def _fmt_source(rec):
    """出处条目：doc_id + version + locator（空段跳过）。"""
    parts = [rec.get(k, "") for k in ("doc_id", "version", "locator")]
    return " ".join(p for p in parts if p)


def _quote_of(content):
    """chunk 正文 → sources.quote：压平换行/连续空白，截前 SOURCE_QUOTE_CHARS 字符。"""
    return " ".join(str(content or "").split())[:SOURCE_QUOTE_CHARS]


def build_evidence(hits, max_context_chars=DEFAULT_MAX_CONTEXT_CHARS,
                   header_extra=""):
    """hits（search 返回）→ (evidence_text, sources)。

    格式：
      以下为检索到的语料片段，回答时优先依据语料，语料未覆盖的内容如实说明不确定
      [出处1] <content>
      [出处2] <content>

      出处清单：
      [出处1] <doc_id version locator>
      [出处2] <doc_id version locator>

    - 总长受 max_context_chars 截断，按块粒度丢尾（块内不截断）；
      连首块都放不下（超限）→ 返回 (None, None)，调用方退裸答。
    - sources 与实际保留的块一一对应（被丢尾的块不出现在 sources 里）。
    - header_extra（2026-10-06 R3C 弱注入辅助闸 B 级降注位，默认 ""=输出与
      既往逐字节一致）：紧附 EVIDENCE_HEADER 之后的追加串，**计入预算试算**
      （丢尾行为与头部同尺，弱注不白吃预算）；消费方=retrieve() weak 触发
      且 action=annotate 时传 WEAK_GATE_HINT（[出处N] 结构零触碰，
      citation_gate/前端对 header 形态的既有断言面=startswith(EVIDENCE_HEADER)
      不破——提示行在其后）。
    """
    limit = int(max_context_chars)
    header_extra = str(header_extra or "")
    footer_head = "\n\n出处清单：\n"
    kept_blocks, kept_srcs, sources = [], [], []
    used = len(EVIDENCE_HEADER) + len(header_extra)   # 头部 + 已保留块的累计长度
    src_len = 0                   # 出处清单已保留行的累计长度（含行间 \n）
    for hit in hits:
        rec = hit["rec"]
        block = f"\n\n[出处{hit['rank']}] {rec.get('content', '')}"
        src_line = f"[出处{hit['rank']}] {_fmt_source(rec)}"
        cand_src_len = src_len + (len(src_line) if not kept_srcs else 1 + len(src_line))
        # 试算：加入本块后 evidence 的精确总长
        if used + len(block) + len(footer_head) + cand_src_len > limit:
            break  # 按块丢尾：本块及之后的块全部放弃
        kept_blocks.append(block)
        kept_srcs.append(src_line)
        # "id"（2026-09-28 E1 trace 挂钩点，最小侵入）：chunk 级唯一 id 透传进
        # sources，供 server.py 检索 trace 行做 答案引用→chunk 对齐（消费方按
        # s.get("id") 读，缺键容错；前端/判卷侧忽略多余键，行为零变化）
        sources.append({"id": rec.get("id", ""), "doc_id": rec.get("doc_id", ""),
                        "version": rec.get("version", ""),
                        "locator": rec.get("locator", ""), "score": round(hit["score"], 6),
                        "quote": _quote_of(rec.get("content", ""))})
        used += len(block)
        src_len = cand_src_len
    if not kept_blocks:
        return None, None
    evidence = (EVIDENCE_HEADER + header_extra + "".join(kept_blocks) +
                footer_head + "\n".join(kept_srcs))
    return evidence, sources


# ---------------------------------------------------------------------------
# 查询向量化（百炼 OpenAI 兼容 embeddings，单条批）
# ---------------------------------------------------------------------------
def resolve_embed_endpoint(env=None, config_path="~/.bailian/config.json"):
    """端点与 key 解析 → (base_url, api_key)。

    优先级：环境变量 BAILIAN_EMBED_BASE_URL / BAILIAN_EMBED_API_KEY（逐字段），
    缺者读 ~/.bailian/config.json 的 base_url/api_key。文件不存在/字段缺失/
    JSON 坏 → 原样抛异常，由调用方兜底（RagService.retrieve 转 None）。
    返回值含敏感内容，禁止打印/落日志。
    """
    if env is None:
        env = os.environ
    base = env.get("BAILIAN_EMBED_BASE_URL") or ""
    key = env.get("BAILIAN_EMBED_API_KEY") or ""
    if not base or not key:
        path = os.path.expanduser(config_path)
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
        base = base or str(cfg.get("base_url") or "")
        key = key or str(cfg.get("api_key") or "")
    if not base or not key:
        raise RuntimeError("embed 端点解析失败：base_url/api_key 缺失")
    return base, key


# 模块级共享 embed 连接（2026-10-12 合围 Wave 2-A：查询嵌入与探针补嵌复用
# 同一只 httpx.Client，省每问一次 TCP+TLS 握手）。懒初始化+双检锁；请求级
# 并发安全由 httpx.Client 自身保证（官方口径：Client 可被多线程并发发请求）
# ——主链线程与探针守护线程共用。鉴权头按调用逐次构造（key 绝不烘入共享
# client）；超时烘入构造参数、异参调用自动回退 per-call 新建（见 _embed_post）。
_embed_client_state = None        # None 或 (client, 构造时烘入的 timeout)
_embed_client_lock = threading.Lock()


def _get_embed_client(timeout):
    """→ (client, 构造时 timeout) 或 None（构造失败=调用方回退 per-call 新建）。

    - 懒初始化+双检锁：并发首调只构造一次（is_closed 判读用 getattr 宽容
      形态，伪桩/旧版无该属性时视为可用）；
    - client 已关（is_closed）→ 锁内重建（共享态自愈位）；
    - 构造异常 → None（fail-open：embed_query 回退旧行为，不拖垮主链路）。
    """
    global _embed_client_state
    st = _embed_client_state
    if st is not None and not getattr(st[0], "is_closed", False):
        return st
    with _embed_client_lock:
        st = _embed_client_state
        if st is not None and not getattr(st[0], "is_closed", False):
            return st
        try:
            client = httpx.Client(timeout=timeout)
        except Exception:
            return None
        _embed_client_state = (client, timeout)
        return _embed_client_state


def _drop_embed_client(broken):
    """共享 client 弃置（传输失败回退时调用）：缓存仍是同一实例才清位，
    并尽力关闭（close 失败静默——fail-open 姿态，沿 [rag-faiss] degrade 先例）。"""
    global _embed_client_state
    with _embed_client_lock:
        st = _embed_client_state
        if st is None or st[0] is not broken:
            return
        _embed_client_state = None
    try:
        close = getattr(broken, "close", None)
        if close is not None:
            close()
    except Exception:
        pass


def _embed_post(url, payload, headers, timeout):
    """单次 embeddings POST → 已解析响应体。

    共享 client 优先（超时一致才复用）；**仅传输失败**（post 抛异常：连接/
    读超时/池满/连接关闭等）回退旧行为=per-call 新建 Client 重发一次并弃置
    共享态自愈；服务端响应态（raise_for_status 的 HTTP 状态错/json 坏体）
    **不重试**——沿旧行为单次失败上抛，防按量 API 面双发。"""
    st = _get_embed_client(timeout)
    if st is not None and st[1] == timeout:
        client = st[0]
        try:
            resp = client.post(url, json=payload, headers=headers)
        except Exception:
            _drop_embed_client(client)   # 共享连接疑似失效：弃置+回退旧行为
        else:
            resp.raise_for_status()
            return resp.json()
    with httpx.Client(timeout=timeout) as client:   # 旧行为：每次新建
        resp = client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()


def embed_query(text, *, model=DEFAULT_EMBED_MODEL, dimensions=EMBED_DIMENSIONS,
                timeout=DEFAULT_TIMEOUT_SECONDS, endpoint=None, log=None):
    """单条文本向量化 → list[float]。失败抛异常（调用方兜底），绝不回显 key。

    2026-10-12 合围 Wave 2-A：HTTP 传输改走模块级共享 httpx.Client（懒初始
    化，见 _get_embed_client；传输失败回退 per-call 新建）；超时仍按调用参数
    生效（共享 client 构造时烘入，异参调用自动走 per-call），鉴权头/journal
    行格式/失败抛出语义与旧版一致。

    每次调用记一行用量日志（对齐 server.py [chat] 行风格，只含时间/字符数/
    tokens/成败，无 key 无 URL）：
      [rag-embed] chars=123 tokens=8 ok=1 dur=0.31s
      [rag-embed] chars=123 ok=0 dur=3.02s err=ConnectTimeout
    """
    say = log or _default_log
    t0 = time.time()
    try:
        base, key = endpoint or resolve_embed_endpoint()
        url = base.rstrip("/") + EMBED_PATH
        data = _embed_post(url, {"model": model, "input": [text],
                                 "dimensions": dimensions},
                           {"Authorization": f"Bearer {key}"}, timeout)
        vec = data["data"][0]["embedding"]
        if not isinstance(vec, list) or not vec or not all(
                isinstance(x, (int, float)) and not isinstance(x, bool) for x in vec):
            raise ValueError("embed 返回体无合法 embedding")
        tokens = (data.get("usage") or {}).get("total_tokens", "")
        say(f"[rag-embed] chars={len(text)} tokens={tokens if tokens != '' else 'na'} "
            f"ok=1 dim={len(vec)} dur={time.time() - t0:.2f}s")
        return [float(x) for x in vec]
    except Exception as e:  # 只报异常类型名，不带任何请求细节
        say(f"[rag-embed] chars={len(text)} ok=0 dur={time.time() - t0:.2f}s "
            f"err={type(e).__name__}")
        raise


# ---------------------------------------------------------------------------
# RagService：惰性加载 + 检索编排（一切失败兜底 None）
# ---------------------------------------------------------------------------
class RagService:
    """RAG 服务对象：initialize(config) 惰性加载库；retrieve(query) 出证据。

    - initialize 只记录配置并尝试一次加载；库文件缺失不报错（空库），
      retrieve 时若库仍空会再探一次文件（建库完成后无需重启服务即可生效）。
    - retrieve 任何环节失败（库空/维度不符/embed 异常/超限放不下首块）→ None，
      绝不抛出——调用方据此走裸答，RAG 永不让请求失败。
    - embed_fn 可注入 stub（离线测试零网络）；默认真实调用 embed_query。
    - variant_fn 可注入 mock 变体生成器（离线测试零网络，返回变体字符串列表，
      结果仍走统一清洗去重）；默认走 multiquery.generate_variants 真实 flash
      调用（mq_enabled=true 时才发起）。
    """

    def __init__(self, embed_fn=None, log=None, base_dir=None, variant_fn=None,
                 condense_fn=None):
        self._embed_fn = embed_fn
        self._log = log or _default_log
        self._base_dir = base_dir or BASE_DIR
        self._cfg = dict(DEFAULT_RAG_CONFIG)
        self._recs = None  # None=未加载；[]=空库（文件缺失/全坏行）
        self._dim = None
        self._stats = {}
        self._bm25 = None  # hybrid 开时的 BM25Index 缓存（随库加载构建；关=None）
        self._faiss = None  # faiss_enabled 开时的 IndexFlatIP 缓存（随库加载构建；关/降级=None）
        self._variant_fn = variant_fn  # mq 变体生成注入位（默认 None=真实调用）
        # mq condense 路注入位（2026-10-24 施工，variant_fn 先例）：签名
        # condense_fn(q0, history)→str；默认 None=真实 flash 调用（键开且有
        # 前史时才发起）；注入路径清洗/去重/打行与真实路径同一套规则。
        self._condense_fn = condense_fn
        # mq condense 键族清洗参数（2026-10-24 施工，默认关=零调用面；
        # initialize 以生效 config 重新清洗覆盖）
        self._mq_condense = clean_mq_condense_params(self._cfg)
        self._lock = threading.Lock()  # 并发 retrieve 下的加载互斥
        # 月度预算闸缓存（2026-09-28）：(台账 path, mtime_ns, size, 月) → 当月累计元；
        # _ledger_warned=台账缺失只 warn 一次（防每问刷屏）
        self._budget_cache = None
        self._ledger_warned = False
        # P0 去挤占（2026-09-29，默认全关）：清洗参数 + 快照写失败只 warn 一次
        self._decrowd = clean_decrowd_params(self._cfg)
        self._snapshot_warned = False
        # 期 1 路由挂接（2026-09-29，默认关）：清洗参数（enabled=False 时零调用面）
        self._route = clean_route_params(self._cfg)
        # 乙案族选席（2026-09-29，默认关）：清洗参数（enabled=False 时零调用面）
        self._famsel = clean_family_select_params(self._cfg)
        # 试点 2 元数据过滤（2026-10-01，默认关）：清洗参数+版本族索引（装载期建）
        self._metaf = clean_meta_filter_params(self._cfg)
        self._meta_index = None
        # 案甲域降权（2026-10-06，默认 {}=关）：清洗参数（enabled=False 时零调用面）
        self._domain_dw = clean_domain_downweight_params(self._cfg)
        # 案丙域内 doc 配额（2026-10-06，默认 {}=关）：清洗参数（enabled=False
        # 时零调用面）
        self._domain_doc_quota = clean_domain_doc_quota_params(self._cfg)
        # H 线查询-族定向加权（2026-10-14 F线H，默认 []=关）：清洗参数
        # （enabled=False 时零调用面）
        self._qdf = clean_query_doc_factor_params(self._cfg)
        # ADR-0018 融合级配额段（2026-10-06 R3C，默认关）：清洗参数
        # （enabled=False 时零调用面，_retrieve_mq 现状逐字节一致）
        self._mqsel = clean_mq_fused_select_params(self._cfg)
        # 弱注入辅助闸（2026-10-06 R3C，默认 {}=关）：清洗参数（enabled=False
        # 时零调用面，retrieve() 链尾现状逐字节一致）
        self._weakgate = clean_weak_gate_params(self._cfg)
        # 同源折叠（2026-10-03，默认关）：清洗参数（enabled=False 时零调用面；
        # scope=2026-10-08 W4 D5 甲扩展键，默认 "tables"=现状，扩改须决策）
        self._fold = clean_same_source_fold_params(self._cfg)
        self._fold["scope"] = clean_same_source_fold_scope(self._cfg)
        # B-evict 定向清位（2026-10-03，默认关）：清洗参数（enabled=False 时
        # 零调用面；挂检索链尾=乙+折叠后、截 topk 前）
        self._bevict = clean_b_evict_params(self._cfg)
        # MMR 向量去冗余（2026-10-23 波3 工程件，默认关）：清洗参数
        # （enabled=False 时零调用面；挂链尾终截断面后、闸门段前）
        self._mmr = clean_mmr_params(self._cfg)
        # R 线二期 S1 词面通道键族（2026-10-17，默认空=零行为面）：门控注入/
        # 查询预处理装载面（initialize 重新清洗覆盖；纯函数清洗器同源复用）
        self._gate_extra = clean_hybrid_gate_extra_params(self._cfg)
        self._qpp = clean_query_preprocess_entries(self._cfg)

    # -- 配置与加载 ---------------------------------------------------------
    def initialize(self, config):
        """config 为 config.json 的 rag 段（dict）；容忍缺键（用默认值）。"""
        cfg = dict(DEFAULT_RAG_CONFIG)
        if isinstance(config, dict):
            cfg.update({k: v for k, v in config.items() if not k.startswith("_")})
        cfg["store_path"] = self._abs_store(cfg["store_path"])
        cfg["score_threshold"] = _norm_score_threshold(cfg.get("score_threshold"))
        # 批B4 mq 三键归一（缺省=现行行为不变）：单变体布尔化；生成预算坏值
        # 回退旧键 mq_timeout_seconds（再坏回 multiquery 默认 3s）；整体墙钟
        # 预算坏值回退 None=关（钳制口径见 _norm_mq_budget）
        cfg["mq_single_variant"] = bool(cfg.get("mq_single_variant"))
        cfg["mq_variant_timeout"] = _norm_mq_budget(
            cfg.get("mq_variant_timeout"),
            _norm_mq_budget(cfg.get("mq_timeout_seconds"),
                            multiquery.DEFAULT_MQ_TIMEOUT_SECONDS if multiquery
                            else 3.0))
        cfg["mq_wall_timeout"] = _norm_mq_budget(cfg.get("mq_wall_timeout"), None)
        cfg["faiss_enabled"] = bool(cfg.get("faiss_enabled"))  # 缺省/false=现行纯余弦路径
        # 月度预算闸归一（2026-09-28，缺省=关=现行行为逐字节不变）：坏值回默认
        # 40/50（对齐过程日志三节 36① 的 2026-10-05 调线口径）；预警>硬顶时钳到硬顶
        cfg["embed_monthly_budget_enabled"] = bool(cfg.get("embed_monthly_budget_enabled"))
        cfg["embed_monthly_budget_cny"] = _norm_budget_cny(
            cfg.get("embed_monthly_budget_cny"), DEFAULT_EMBED_MONTHLY_BUDGET_CNY)
        cfg["embed_monthly_cap_cny"] = _norm_budget_cny(
            cfg.get("embed_monthly_cap_cny"), DEFAULT_EMBED_MONTHLY_CAP_CNY)
        if cfg["embed_monthly_budget_cny"] > cfg["embed_monthly_cap_cny"]:
            cfg["embed_monthly_budget_cny"] = cfg["embed_monthly_cap_cny"]
        _lp = str(cfg.get("embed_ledger_path") or DEFAULT_EMBED_LEDGER_PATH)
        cfg["embed_ledger_path"] = (_lp if os.path.isabs(_lp)
                                    else os.path.join(self._base_dir, _lp))
        self._budget_cache = None  # 配置重载（initialize 复入）即弃缓存
        # S1 治理乙/丙键归一（2026-09-28 选项一，默认开=决策生效；坏值回默认档，
        # 口径贴 faiss_enabled/_norm_score_threshold 先例：误配回已知安全档）
        cfg["clause_family_rerank"] = bool(cfg.get("clause_family_rerank"))
        _wm = str(cfg.get("clause_family_rerank_words") or "full").strip().lower()
        cfg["clause_family_rerank_words"] = _wm if _wm in ("core", "full") else "full"
        cfg["cover_gate_enabled"] = bool(cfg.get("cover_gate_enabled"))
        _cv = cfg.get("cover_gate_vocab")
        cfg["cover_gate_vocab"] = ([str(w) for w in _cv if str(w).strip()]
                                   if isinstance(_cv, list) else list(COVER_GATE_VOCAB))
        # W2 词面限域门控键归一（2026-10-08，默认关=现状逐字节不变；仅严格
        # 布尔 true 开，口径贴 clean_same_source_fold_params 先例；词表三形仿
        # cover_gate_vocab：null/非 list=内置 list(HYBRID_GATE_VOCAB)，list=
        # str 化去空条目）
        cfg["hybrid_gated_enabled"] = cfg.get("hybrid_gated_enabled") is True
        _gv = cfg.get("hybrid_gate_vocab")
        cfg["hybrid_gate_vocab"] = ([str(w) for w in _gv if str(w).strip()]
                                    if isinstance(_gv, list)
                                    else list(HYBRID_GATE_VOCAB))
        # R 线二期 S1 门控注入键族+查询预处理键归一（2026-10-17，默认全空=
        # 现状逐字节不变；清洗集中在 clean_hybrid_gate_extra_params/
        # clean_query_preprocess_entries——离线验证脚本同源复用，防两把尺；
        # 合并基准=上方清洗后的生效词表〔vocab_extra 追加语义〕）
        self._gate_extra = clean_hybrid_gate_extra_params(cfg)
        self._qpp = clean_query_preprocess_entries(cfg)
        # ④b 分数带门控键归一（2026-10-18 检索召回优化组合案，默认 null=现状
        # 逐字节不变；仅 float∈(0,1] 生效，null/bool/越界/非数回 None=关——
        # 口径贴 hybrid_gated_enabled 先例：误配回已知安全档）
        _bt = cfg.get("hybrid_gate_band_t")
        if isinstance(_bt, bool) or not isinstance(_bt, (int, float)):
            _bt = None
        else:
            _bt = float(_bt)
            if not (0.0 < _bt <= 1.0):
                _bt = None
        cfg["hybrid_gate_band_t"] = _bt
        # P0 去挤占键归一（2026-09-29，默认全关=现状逐字节不变；坏值回默认档）：
        # 清洗集中在 clean_decrowd_params（离线验证脚本同源复用，防两把尺）；
        # 快照目录相对路径锚 base_dir（同 store_path/embed_ledger_path 口径）
        self._decrowd = clean_decrowd_params(cfg)
        _snap = self._decrowd.get("snapshot_dir")
        if _snap and not os.path.isabs(_snap):
            _snap = os.path.join(self._base_dir, _snap)
        self._decrowd["snapshot_dir"] = _snap
        self._snapshot_warned = False
        # 期 1 路由挂接键归一（2026-09-29，默认关=现状逐字节不变；坏值回默认档；
        # 清洗集中在 clean_route_params——离线验证脚本同源复用，防两把尺）
        self._route = clean_route_params(cfg)
        # 乙案族选席键归一（2026-09-29，默认关=现状逐字节不变；坏值回默认档）
        self._famsel = clean_family_select_params(cfg)
        # 试点 2 元数据过滤键归一（2026-10-01，默认关=现状逐字节不变；坏值回默认档）
        self._metaf = clean_meta_filter_params(cfg)
        # 案甲域降权键归一（2026-10-06，默认 {}=现状逐字节不变；坏条目单条丢弃
        # 不整组回退，单一尺=clean_domain_downweight_params，防两把尺）
        self._domain_dw = clean_domain_downweight_params(cfg)
        # 案丙域内 doc 配额键归一（2026-10-06，默认 {}=现状逐字节不变；坏条目
        # 单条丢弃不整组回退，单一尺=clean_domain_doc_quota_params，防两把尺）
        self._domain_doc_quota = clean_domain_doc_quota_params(cfg)
        # H 线查询-族定向加权键归一（2026-10-14 F线H，默认 []=现状逐字节不变；
        # 坏条目单条丢弃不整组回退，单一尺=clean_query_doc_factor_params，防两把尺）
        self._qdf = clean_query_doc_factor_params(cfg)
        # ADR-0018 融合级配额段键归一（2026-10-06 R3C，默认关=现状逐字节不变；
        # 缺键/非法值回 false、candidates 坏值回 null=零漂移，单一尺=
        # clean_mq_fused_select_params，防两把尺）
        self._mqsel = clean_mq_fused_select_params(cfg)
        cfg["mq_fused_select_enabled"] = self._mqsel["enabled"]
        cfg["mq_fused_candidates"] = self._mqsel["candidates"]
        # 弱注入辅助闸键归一（2026-10-06 R3C，默认 {}=关=现状逐字节不变；坏值
        # 回默认档，单一尺=clean_weak_gate_params，防两把尺）
        self._weakgate = clean_weak_gate_params(cfg)
        # 同源折叠键归一（2026-10-03，默认关=现状逐字节不变；缺键/非法值回 false，
        # 单一尺=clean_same_source_fold_params，防两把尺；scope 键 2026-10-08
        # W4 D5 甲增：缺键/非法值回 "tables"=现状，单一尺=
        # clean_same_source_fold_scope——独立函数不并入 params 返回面，该返回
        # 面被 tests/test_同源折叠.py 整字典断言钉死）
        cfg["same_source_fold_enabled"] = \
            clean_same_source_fold_params(cfg)["enabled"]
        cfg["same_source_fold_scope"] = clean_same_source_fold_scope(cfg)
        self._fold = clean_same_source_fold_params(cfg)
        self._fold["scope"] = cfg["same_source_fold_scope"]
        # B-evict 定向清位键归一（2026-10-03，默认关=现状逐字节不变；缺键/非法
        # 值回 false，单一尺=clean_b_evict_params，防两把尺）
        cfg["b_evict_enabled"] = clean_b_evict_params(cfg)["enabled"]
        self._bevict = clean_b_evict_params(cfg)
        # MMR 向量去冗余键归一（2026-10-23 波3 工程件，默认关=现状逐字节
        # 不变；缺键/非法值回 false/0.7，单一尺=clean_mmr_params，防两把尺）
        self._mmr = clean_mmr_params(cfg)
        cfg["mmr_enabled"] = self._mmr["enabled"]
        cfg["mmr_lambda"] = self._mmr["lam"]
        # mq condense 键族归一（2026-10-24 施工，默认关=零调用面零漂移；
        # 缺键/非法值回默认档，单一尺=clean_mq_condense_params，防两把尺）
        self._mq_condense = clean_mq_condense_params(cfg)
        cfg["mq_condense_enabled"] = self._mq_condense["enabled"]
        self._cfg = cfg
        if cfg.get("hybrid_bm25_enabled") and cfg.get("lexical_boost"):
            # 共存语义：同源词法信号建议二选一；同开时 hybrid 优先（见 _search_one）
            self._log("[rag] warn: hybrid_bm25 与 lexical_boost 同开，"
                      "lexical_boost 不生效（建议二选一）")
        if cfg.get("mq_enabled") and multiquery is None:
            # multiquery.py 缺席（如部署漏带）：mq 退关（retrieve 视同未启用）
            self._log("[rag] warn: multiquery 模块不可用，mq_enabled 退关"
                      "（其余检索不受影响）")
        if bool(cfg.get("route_enabled")) and route_domain is None:
            # route_domain.py 缺席（如部署漏带）：路由退关（零收窄，其余检索不受影响）
            self._log("[rag] warn: route_domain 模块不可用，route_enabled 退关"
                      "（其余检索不受影响）")
        # R 线二期 S1 键族装载指纹行（2026-10-17；仅装载面非空时打——默认空=
        # 零新观测面；计数+SHA 不含词面，拨键执行单对账锚）
        if self._gate_extra["n_forms"]:
            self._log("[rag-gate-extra] forms=%d sha256=%s…（门控注入键族装载；"
                      "坏形丢弃 dropped=%d；不含词面）"
                      % (self._gate_extra["n_forms"],
                         self._gate_extra["face_sha256"][:16],
                         self._gate_extra["dropped"]))
        if self._qpp["n"]:
            self._log("[rag-preprocess] entries=%d sha256=%s…（查询预处理词条"
                      "装载；坏词条丢弃 dropped=%d；不含词面）"
                      % (self._qpp["n"], self._qpp["face_sha256"][:16],
                         self._qpp["dropped"]))
        self._load()

    def _abs_store(self, path):
        p = str(path) if path else DEFAULT_STORE_PATH
        return p if os.path.isabs(p) else os.path.join(self._base_dir, p)

    def _load(self):
        with self._lock:
            recs, dim, stats = load_store(self._cfg["store_path"])
            self._recs, self._dim, self._stats = recs, dim, stats
            # 试点 2（2026-10-01）：meta_filter_v1 开时随库装载构建版本族索引
            # （纯派生件零 IO；库重载=重建，空库=空索引）
            self._meta_index = (build_meta_version_index(recs)
                                if (self._metaf or {}).get("enabled") else None)
            say = (f"[rag-store] loaded={stats['loaded']} bad_lines={stats['bad_lines']} "
                   f"dim={stats['dim']}{' missing=1' if stats['missing'] else ''}"
                   f"{' sidecar=1' if stats.get('sidecar') else ''}")
            bm25_say = None
            if self._cfg.get("hybrid_bm25_enabled") and recs:
                # 索引随库加载构建并缓存（库重载=重建）；建失败不拖垮加载（退单路）。
                # bm25_persist 开（默认关=下方路径逐字节同现状）时先试缓存件直载；
                # 缓存不适用/坏/落盘失败一律无条件回退全量重建（纯加速件纪律）
                persist = bool(self._cfg.get("bm25_persist"))
                try:
                    t0 = time.time()
                    ix = (try_load_bm25_index(self._cfg["store_path"], recs, dim)
                          if persist else None)
                    if ix is not None:
                        self._bm25 = ix
                        bm25_say = (f"[rag-bm25] load docs={ix.n_docs} terms={ix.n_terms} "
                                    f"postings={ix.n_postings} avgdl={ix.avgdl:.1f} "
                                    f"arr_mb={ix.postings_bytes / 1048576:.1f} "
                                    f"dur={time.time() - t0:.2f}s（cache 命中）")
                    else:
                        self._bm25 = BM25Index.build(recs)
                        ix = self._bm25
                        bm25_say = (f"[rag-bm25] build docs={ix.n_docs} terms={ix.n_terms} "
                                    f"postings={ix.n_postings} avgdl={ix.avgdl:.1f} "
                                    f"arr_mb={ix.postings_bytes / 1048576:.1f} "
                                    f"dur={time.time() - t0:.2f}s")
                        if persist:
                            # 建成即落盘（原子换入）；写失败只 warn——现役索引已在
                            # 内存检索不受影响，下次启动重走 build+落盘
                            try:
                                ts = time.time()
                                save_bm25_index(ix, self._cfg["store_path"], dim)
                                bm25_say += (f" persist=save"
                                             f" save_dur={time.time() - ts:.2f}s")
                            except Exception as e:
                                bm25_say += f" persist=save_fail err={type(e).__name__}"
                except Exception as e:  # 内存不足等：hybrid 退单路余弦，检索仍可用
                    self._bm25 = None
                    bm25_say = f"[rag-bm25] build fail err={type(e).__name__}（退单路余弦）"
            else:
                self._bm25 = None
            faiss_say = None
            if self._cfg.get("faiss_enabled") and recs:
                # faiss 索引随库加载构建并缓存（库重载=重建）；构建前先清空旧
                # 索引（并发检索退纯余弦，绝不用旧索引对新库）。import 失败/
                # 建索引异常不拖垮加载：[rag-faiss] degrade 退纯余弦（纯加速件）
                self._faiss = None
                try:
                    t0 = time.time()
                    index = build_faiss_index(recs, dim)
                    self._faiss = index
                    faiss_say = (f"[rag-faiss] build ntotal={index.ntotal} d={dim} "
                                 f"dur={time.time() - t0:.2f}s")
                except Exception as e:  # faiss 未装/内存不足等：检索语义不变
                    self._faiss = None
                    faiss_say = (f"[rag-faiss] degrade reason=build "
                                 f"err={type(e).__name__}（退纯余弦）")
            else:
                self._faiss = None
        self._log(say)  # 锁外打印，避免长 IO 串行化日志
        if bm25_say:
            self._log(bm25_say)
        if faiss_say:
            self._log(faiss_say)

    @property
    def stats(self):
        return dict(self._stats)

    @property
    def loaded(self):
        return bool(self._recs)

    # -- 检索编排 -----------------------------------------------------------
    def _embed(self, text):
        """单条查询向量化（注入位优先；口径与原 retrieve 内联实现一致）。

        2026-09-28：embed_monthly_budget_enabled 开时先过月度预算闸（台账
        当月切片累计 ×0.5 元/百万 tok）：≥硬顶 → 抛 EmbedBudgetExceeded
        （retrieve 兜底 None=退纯裸答）；≥预警 → 打 [rag-budget] warn 照常
        嵌入；开关关=本方法与旧行为逐字节一致（零日志零文件读）。
        """
        if self._cfg.get("embed_monthly_budget_enabled"):
            self._budget_gate()
        # 2026-10-13 一致性收敛批：embed_retry_times（默认 0=零行为变化）开时对
        # 超时/网络类传输失败追加重试（每次重试打一行 [rag-embed] retry）；HTTP
        # 响应错与预算闸不重试——沿 _embed_post 防双发纪律，只吸收传输层抖动
        # （embed 偶发超时退裸答=同题"有据/无据"摆动主源）。
        attempts = 1 + max(0, int(self._cfg.get("embed_retry_times") or 0))
        for _attempt in range(attempts):
            try:
                if self._embed_fn is not None:
                    return self._embed_fn(text)
                return embed_query(text, model=self._cfg["embed_model"],
                                   timeout=self._cfg["timeout_seconds"])
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                if _attempt + 1 >= attempts:
                    raise
                self._log(f"[rag-embed] retry={_attempt + 1}/{attempts - 1} "
                          f"err={type(e).__name__}（传输层失败，重试）")

    def _budget_gate(self):
        """月度预算闸：查台账当月累计 → 硬顶抛出 / 预警打日志 / 正常静默。"""
        cny = self._budget_month_cny()
        cap = float(self._cfg["embed_monthly_cap_cny"])
        budget = float(self._cfg["embed_monthly_budget_cny"])
        if cny >= cap:
            self._log(f"[rag-budget] block monthly={cny:.2f}cny cap={cap:.2f}cny"
                      "（月度硬顶，拒绝嵌入退裸答）")
            raise EmbedBudgetExceeded(f"monthly {cny:.4f} >= cap {cap:.2f}")
        if cny >= budget:
            self._log(f"[rag-budget] warn monthly={cny:.2f}cny budget={budget:.2f}cny"
                      f" cap={cap:.2f}cny（月度累计过预警线，照常嵌入）")

    def _budget_month_cny(self):
        """台账当月切片累计（元）；(path, mtime_ns, size, 月) 键控缓存。

        台账缺失 → 计 0（闸开）+ warn 一行（每服务实例一次，防每问刷屏）；
        台账被续写（mtime/size 变化）缓存自动失效重读。
        """
        path = self._cfg["embed_ledger_path"]
        month = time.strftime("%Y-%m")
        try:
            st = os.stat(path)
            key = (path, st.st_mtime_ns, st.st_size, month)
        except OSError:
            if not self._ledger_warned:
                self._ledger_warned = True
                self._log("[rag-budget] warn ledger_missing（台账缺失计 0，闸开；"
                          "部署面请核对 embed_ledger_path）")
            return 0.0
        if self._budget_cache is not None and self._budget_cache[0] == key:
            return self._budget_cache[1]
        tok = ledger_month_tokens(path, month)
        cny = tok / 1e6 * EMBED_PRICE_CNY_PER_MTOK
        self._budget_cache = (key, cny)
        return cny

    def _search_cos(self, query_vec, topk=DEFAULT_TOPK):
        """余弦 top-k 检索：faiss 开且索引在位走 IndexFlatIP，否则现行 search。

        - 输出与模块级 rag.search 完全同形态（rank/score/rec/idx）；recs 空 →
          None（同现行，调用方退裸答）；recs 空（库空/未加载）时索引也必为
          None，直接委托 search。
        - 查询归一化口径与纯余弦路径严格一致：float64 求模（math.hypot）+
          float64 除法（与 search 同式），仅入 faiss 前转 float32——两路唯一
          精度差即对拍报告 §一口径（max|Δscore|=1.7e-07，排序逐位一致）。
        - faiss 返回分 float32，按 (-score, 库内行序) 重排对齐生产确定性
          tie-break（比特级同分块的相对位次=行序，语义无损）；faiss 未填满
          k 位（idx=-1）截断，与 search 的 topk 截断同构。
        - 维度不符/零向量 → ValueError（与 search 同语义同文案，调用方兜底
          不变）；faiss/numpy 检索期异常 → [rag-faiss] degrade 退纯余弦
          全量扫（服务不中断，行为=旧路径）。
        """
        if self._faiss is None or not self._recs:
            return search(query_vec, self._recs, topk)
        dim = len(self._recs[0]["vec"])
        if not isinstance(query_vec, (list, tuple)) or len(query_vec) != dim:
            raise ValueError(f"query 向量维度与库维度不符（期望 {dim}）")
        # 求模=math.hypot（与 search 同式；2026-10-08 防平方下溢修复同步改）
        n = math.hypot(*query_vec)
        if not math.isfinite(n) or n == 0.0:
            raise ValueError("query 向量为零向量，无法计算余弦")
        try:
            import numpy as np  # faiss 路径专用；纯余弦环境零依赖
            k = max(1, int(topk))
            q = np.array([[x / n for x in query_vec]], dtype=np.float32)
            scores, idxs = self._faiss.search(q, k)
            pairs = sorted(((float(s), int(i)) for s, i in zip(scores[0], idxs[0])
                            if i >= 0), key=lambda t: (-t[0], t[1]))
            return [{"rank": rank, "score": score, "rec": self._recs[i], "idx": i}
                    for rank, (score, i) in enumerate(pairs, 1)]
        except Exception as e:  # faiss 运行时异常：退纯余弦全量扫（行为=旧路径）
            self._log(f"[rag-faiss] degrade reason=search err={type(e).__name__}"
                      "（退纯余弦）")
            return search(query_vec, self._recs, topk)

    def _decrowd_on(self):
        """P0 去挤占 ①②③、乙案族选席、试点 2 元数据过滤、案甲域降权、案丙
        域内 doc 配额或 H 线查询-族定向加权任一开启（快照④独立，不触发深候选池）。"""
        d = self._decrowd or {}
        f = self._famsel or {}
        m = self._metaf or {}
        w = self._domain_dw or {}
        q = self._domain_doc_quota or {}
        g = self._qdf or {}
        return bool(d.get("quota_on") or d.get("table_on") or d.get("spec_on")
                    or f.get("enabled") or m.get("enabled")
                    or w.get("enabled") or q.get("enabled") or g.get("enabled"))

    def _decrowd_assemble(self, q, hits, topk, truncate=True, keep=None,
                          route_res=None, fold_window=None):
        """decrowd 组装段：②③ 重打分（→案甲域降权/meta 陈旧降权乘子）→（truncate
        时）路由选席约束 → 乙案族选席 → ① 配额选席（含案丙域内 doc 配额域表）
        + 截 topk。

        - truncate=False（mq 深度路径）：只重打分不做**路级**选席——路级不
          选席，治理选席统一挂**融合级组装段**（mq_fused_select 键域，
          _retrieve_mq 融合输出与退化出口的统一挂位=_mq_fused_select；
          ADR-0018 2026-10-06 在册纪律修订："扭曲 RRF 融合语义"的关切仅
          适用于路级选席形态〔治理后位次进 RRF 投票〕，融合级选席在 RRF
          排序完成后施加、不改 fused 分、不改各路输入，与该关切正交）；
          路由域面约束同纪律不生效（期 1 挂接；域面过滤亦不入融合级——
          融合级段=doc 配额选席〔①③〕only）；keep 给定时截回调用方请求的
          深度（与旧版 search(vec, n) 返回 n 条语义对齐；ADR-0018 甲2：
          mq_fused_select_enabled 开时 _retrieve_mq 传 keep=decrowd 池深，
          重打分本就在深池内完成、keep 只是截断位=路级零新增计算）；
        - fold_window（同源折叠开时>topk，默认 None=现行截 topk 不变）：只放粗
          truncate 分支的组装截断深度（选席窗口=topk 不变——famsel R1 共存窗/
          配额回补语义零触碰，=折叠试点 full10 构造的 6-10 深位观测面）；
        - 期 1 路由选席约束（route_res 经 route_constraint 判定生效才走到；
          默认关=零调用面）：重打分后、族选席/配额前按域面/doc 面过滤候选——
          检索后兜底=域内候选 <topk 或域内最大余弦 <score_threshold（0.40
          闸值；关闸时按 DEFAULT_SCORE_THRESHOLD）→ 回退全量并打 fallback=1
          的 [rag-route] 行（可观测态，不含题面）；
        - 乙案族选席（family_select_enabled=true 时生效，默认关=零调用面）：
          路由约束后、配额前插入族级成员选席（R1-R5），overflow 并入配额回补池；
          打 [rag-famsel] 行（不含题面）；
        - 案丙域内 doc 配额（domain_doc_quota 非空时生效，默认 {}=零调用面）：
          与 ① 配额同点选席（域表参数化，非新分支）——① 关时仅域表命中域
          受限、非域表域块不限额；
        - 命中/换序/换员时打一行 [rag-decrowd]（不含题面文本，同
          [rag-hybrid] 归因行纪律）。
        """
        if not hits:
            return hits
        d = self._decrowd or {}
        rescored, info = decrowd_rescore(q, hits, d)
        # 试点 2（2026-10-01）：同族陈旧版本降权——挂 ②③ 重打分之后、路由选席/
        # 族选席/配额之前（乘子链与 ②③ 连乘，序=乘法交换律下等价；②③ 全关时
        # decrowd_rescore 早退零拷贝，本层自补 cosine 键后独立成链）
        if (self._metaf or {}).get("enabled") and self._meta_index:
            rescored, m_info = meta_filter_rescore(rescored, self._metaf,
                                                   self._meta_index)
            info["meta_n"] = m_info.get("stale_n", 0)
        # 案甲域降权（2026-10-06，默认 {}=零执行）：挂 ②③/meta_filter 乘子之后、
        # 路由选席/族选席/配额之前（乘子链=乘法交换律下与 ②③ 等价；②③/meta 全关
        # 时 decrowd_rescore 早退零拷贝，本层自补 cosine 键后独立成链）
        if (self._domain_dw or {}).get("enabled"):
            rescored, dw_info = domain_downweight_rescore(rescored,
                                                          self._domain_dw)
            info["domain_n"] = dw_info.get("domain_n", 0)
        # H 线查询-族定向加权（2026-10-14 F线H，默认 []=零执行）：挂案甲域降权
        # 之后、路由选席/族选席/配额之前（乘子链位；题面零命中规则信号=零改动
        # 直过——per-rule 打 [rag-qdf] 观测行，不含题面）
        if (self._qdf or {}).get("enabled"):
            rescored, qdf_info = query_doc_factor_rescore(rescored, q,
                                                           self._qdf)
            if qdf_info.get("fired"):
                self._log("[rag-qdf] rules=%s fired=%d hit_n=%d（查询-族定向"
                          "加权：题面命中规则信号，命中目标块分乘 factor）"
                          % (",".join(qdf_info["rules"]), qdf_info["fired"],
                             qdf_info["hit_n"]))
                info["qdf_n"] = qdf_info.get("hit_n", 0)
        base = rescored
        constraint = route_constraint(self._route, route_res) if truncate else None
        if constraint:
            facet = bool((self._route or {}).get("table_facet"))
            kept = [h for h in rescored
                    if route_rec_in(h.get("rec"), constraint, facet)]
            thr = float(self._cfg.get("score_threshold")
                        or DEFAULT_SCORE_THRESHOLD)
            kcos = gate_cosine(kept) if kept else None
            if len(kept) >= topk and (kcos is None or kcos >= thr):
                base = kept
            elif route_domain is not None:
                # 检索后兜底：域面太薄（候选不足/域内最大余弦低于闸值）→ 回退
                # 全量，宁多勿漏；打点=同格式 [rag-route] 行 fallback 置 1
                self._log(route_domain.format_log_line(
                    dict(route_res, fallback=1)))
        # 乙案族选席（2026-09-29，默认关=零调用面；truncate 时生效，与配额同纪律）
        fam_overflow = []
        fam_info = {"families": 0, "r1_drop": 0, "r23_drop": 0,
                    "r4_fold": 0, "kept": 0}
        if truncate and (self._famsel or {}).get("enabled"):
            pre_fam_n = len(base)
            base, fam_overflow, fam_info = family_member_select(
                base, q, self._famsel, topk=topk)
            if fam_info.get("r1_drop") or fam_info.get("r23_drop") \
                    or fam_info.get("r4_fold"):
                self._log("[rag-famsel] families=%d r1_drop=%d r23_drop=%d "
                          "r4_fold=%d in=%d kept=%d" % (
                              fam_info["families"], fam_info["r1_drop"],
                              fam_info["r23_drop"], fam_info["r4_fold"],
                              pre_fam_n, fam_info["kept"]))
        # 案丙域内 doc 配额（2026-10-06，默认 {}=零执行）：与 ① 同点选席
        # （doc_quota_select 域表参数化）——① 关时 quota 传 None=非域表域块
        # 不限额，仅域表命中域受限；① 开时域表值覆盖全局档（更特异者胜）
        ddq = (self._domain_doc_quota or {}).get("table") or {}
        quota_glob = bool(d.get("quota_on"))
        if truncate and (quota_glob or ddq):
            # 族选席 overflow 并入候选池供配额回补消费（两遍制第二遍语义）
            if fam_overflow:
                pool_for_quota = base + fam_overflow
            else:
                pool_for_quota = base
            selected = doc_quota_select(
                pool_for_quota, (fold_window or topk),
                d.get("quota_max") if quota_glob else None,
                d.get("quota_exempt") or (),
                domain_quotas=ddq)
        elif truncate:
            selected = base[: (fold_window or topk)]
            if fam_overflow and len(selected) < topk:
                # 族选席回补语义（方案 R1：池深不足时按回补兜底，证据面绝不
                # 缩水——doc_quota_select 两遍制第二遍同款；配额开时 overflow
                # 已并入配额池，不走本分支）
                selected = selected + fam_overflow[: topk - len(selected)]
                for i, h in enumerate(selected, 1):
                    h["rank"] = i
        else:
            selected = rescored[: max(1, int(keep))] if keep else rescored
        before = [h["rec"].get("id") for h in hits[: len(selected)]]
        after = [h["rec"].get("id") for h in selected]
        if info["table_n"] or info["spec_n"] or info.get("meta_n") \
                or info.get("domain_n") or before != after:
            # 案丙 ddq 读数（2026-10-06）：域表拨形紧凑串（域名:上限，多域
            # 逗号连、域名序确定性），关态 "-"（无既有日志消费者，观测面安全）
            ddq_s = (",".join("%s:%d" % (k, ddq[k]) for k in sorted(ddq))
                     if ddq else "-")
            self._log("[rag-decrowd] table_n=%d spec=%s spec_n=%d meta_n=%d "
                      "domain_n=%d quota=%s ddq=%s famsel=%s in=%d out=%d" % (
                          info["table_n"], info["spec_rule"] or "-",
                          info["spec_n"], info.get("meta_n", 0),
                          info.get("domain_n", 0),
                          ("on:%d" % d.get("quota_max")) if d.get("quota_on")
                          else "off",
                          ddq_s,
                          ("on:%d/%d" % (fam_info.get("r1_drop", 0),
                                         fam_info.get("r4_fold", 0)))
                          if (self._famsel or {}).get("enabled") else "off",
                          len(hits), len(selected)))
        return selected

    def _search_one(self, q, vec, depth=None, route_res=None):
        """单条查询走现有检索通道（hybrid>lexical>纯余弦，开关语义与现状一致）。

        - depth=None → 各通道现行候选深度（hybrid/lexical 用各自 candidates 键，
          纯余弦取 topk）——mq 关时恒为 None，行为与旧版逐字节一致；
        - mq 路径传 depth=统一候选深度 max(topk, hybrid_candidates)：hybrid/
          lexical 分支本就 ≥topk 不受影响，纯余弦分支按 depth 取候选，
          给多路 RRF 留足融合面。
        - faiss_enabled 开时三个分支的余弦底座统一走 _search_cos（faiss 索引
          复用同一份；hybrid/lexical/mq 通道语义与 hit 形态均不变，纯加速件）。
        - P0 去挤占（decrowd）任一开启时（2026-09-29）三分支统一改走深候选池
          max(topk, decrowd_candidates)：②③ 重打分 → ① 配额选席 → 截 topk；
          hybrid/lexical 保持既有"恒截 topk"语义（mq 深度路径同截，与旧版
          一致），纯余弦分支 mq 深度路径只重打分不选席不截断（route 级深列表
          语义保留）。全关时本方法与 P0 接入前逐字节一致。
        - 期 1 路由挂接（2026-09-29，默认关=零调用面）：route_res（server 端
          classify 结果）经 route_constraint 判定生效时同样改走深候选池（域面
          过滤要有补位空间），选席约束与检索后兜底在 _decrowd_assemble 内；
          mq 各路统一透传同一份 route_res（变体继承域判定不重复分类）。
        - 同源折叠开时（2026-10-03，默认关）：返回列表放粗到前
          max(topk, DEFAULT_SAME_SOURCE_FOLD_WINDOW) 位（不足取全部）给
          retrieve 链尾折叠消费；关态各截断表达式数值回退 topk 零漂移。
        - R 线二期 S1 查询预处理钩子（2026-10-17，默认空=零行为面）：入口
          q→q'（追加式，preprocess_query；词面路 only）——门控/BM25/qdf 三
          消费点全部吃 q'，嵌入调用点在本方法之前=向量结构性不动；entries
          空 → q'=q 恒等。门控判定同时并入 S1 注入键族（vocab_extra/
          patterns_extra OR 面+combo AND 面——默认空=合并后即原表=现状）。
        - ④b 分数带门控（2026-10-18 检索召回优化组合案，默认 null=零行为面）：
          词面门控命中且余弦候选带（cos top5 最大原始余弦）≥ t 时翻 miss 落
          纯余弦（强带语义题不需要词面帮）；带 < t 维持现行融合；t=null=门控
          原语义逐字节不变（feature-flag）。
        """
        topk = max(1, int(self._cfg["topk"]))
        n = depth if depth and int(depth) > 0 else None
        decrowd = self._decrowd_on()
        # R 线二期 S1 查询预处理钩子（2026-10-17，默认空=零行为面；词面路
        # only：下方门控①/BM25②/qdf③（经 _decrowd_assemble 传参）全部消费
        # q'，嵌入已在调用方完成=vec 结构性不动；fired 观测面留离线复放器）
        if self._qpp["entries"]:
            q = preprocess_query(q, self._qpp["entries"])[0]
        deep = decrowd or route_constraint(self._route, route_res) is not None
        pool = (max(topk, int((self._decrowd or {}).get("candidates")
                              or DEFAULT_DECROWD_CANDIDATES))
                if deep else None)
        # 同源折叠开时返回窗深列表（前 fold_window 位给链尾折叠；关态
        # fold_win=None，下列各表达式数值回退 topk——与现行逐字节一致）
        fold_win = (max(topk, DEFAULT_SAME_SOURCE_FOLD_WINDOW)
                    if (self._fold or {}).get("enabled") else None)
        # W2 词面限域门控（2026-10-08 过程日志三节 44 D2 甲，默认关=零调用面；键义
        # 见常量段注释块）：仅 hybrid_bm25 与 hybrid_gated 双开（严格布尔）时
        # 活跃——题面未命中门控信号 → 跳过 BM25 融合落下方纯余弦路径（与 hybrid
        # 关态逐字节一致；lexical_boost 同被短路不复活——共存语义不变）；命中 →
        # 现行融合逻辑一字不动。归因日志 [rag-hybrid-gate] 仅双开时打（hit/miss
        # 两态各一形，不含题面；关态零新观测面）。
        _gate_miss = False
        if (self._cfg.get("hybrid_bm25_enabled")
                and self._cfg.get("hybrid_gated_enabled") is True):
            # R 线二期 S1 注入键族（2026-10-17，默认空=合并后即原表=现状逐字节
            # 一致）：vocab/patterns=生效词表∪vocab_extra、内置 PATTERNS∪
            # patterns_extra（装载期预编译）；combo=组合形 AND 面（ctx∧sig
            # (∧conj)，与影子臂 form_hit_v2 同器——桥接断言在案）
            _ge = self._gate_extra
            _gh = hybrid_gate_hit(q, _ge["vocab"], _ge["patterns"])
            if not _gh and _ge["combos"]:
                _gh = hybrid_gate_combo_hit(q, _ge["combos"])
            # ④b 分数带门控（2026-10-18 检索召回优化组合案；band_t null=本段
            # 零执行=现状逐字节不变）：词面命中且余弦候选带（_search_cos top5
            # 最大原始余弦，纯余弦路径同底座）≥ t → 强带语义题不需要词面帮
            # ——翻 miss 落纯余弦；带 < t 才维持现行 BM25 融合（弱带规范题
            # 词面受益通道保持；band 保护效应=评估档 BX-N10/EV-S10 在案）
            _bt = self._cfg.get("hybrid_gate_band_t")
            _band_flip_note = ""
            if _gh and _bt is not None:
                _ch = self._search_cos(vec, 5) or []
                _band = max((h["score"] for h in _ch[:5]), default=None)
                if _band is not None and _band >= _bt:
                    _gh = False
                    _band_flip_note = (
                        "（词面命中但余弦带 %.6f ≥ t %.2f，跳过 BM25 融合"
                        "走纯余弦〔④b 分数带门控〕）" % (_band, _bt))
            self._log("[rag-hybrid-gate] state=%s%s" % (
                "hit" if _gh else "miss",
                (("（题面命中门控信号，BM25 路参与融合）" if _gh
                  else _band_flip_note or
                  "（题面未命中门控信号，跳过 BM25 融合走纯余弦）"))))
            _gate_miss = not _gh
        if self._cfg.get("hybrid_bm25_enabled") and not _gate_miss:
            # 并路混合：余弦+BM25 各取候选 → 融合 → 截 topk（lexical_boost
            # 同开时被此分支短路不生效——同源信号二选一，见 initialize warn）
            cand = pool or n or max(topk, int(self._cfg["hybrid_candidates"]))
            cos_hits = self._search_cos(vec, cand) or []
            bm_hits = (self._bm25.search(q, cand, float(self._cfg["bm25_k1"]),
                                         float(self._cfg["bm25_b"]))
                       if self._bm25 is not None else [])
            mode = str(self._cfg["hybrid_fusion"])
            hits = fuse_hits(cos_hits, bm_hits,
                             topk=(pool if deep else (fold_win or topk)),
                             mode=mode, rrf_k=float(self._cfg["hybrid_rrf_k"]),
                             bm25_weight=float(self._cfg["hybrid_bm25_weight"]))
            self._log(_fmt_hybrid_line(hits, len(cos_hits), len(bm_hits), mode))
            if deep:
                hits = self._decrowd_assemble(q, hits, topk, truncate=True,
                                              route_res=route_res,
                                              fold_window=fold_win)
            return hits
        if self._cfg.get("lexical_boost") and not self._cfg.get("hybrid_bm25_enabled"):
            # 词法重排开：余弦取 top-N 候选（N≥topk）→ 二次打分 → 截回 topk。
            # hybrid_bm25 开时恒被短路（含门控 miss 态——miss 落下方纯余弦路径
            # 不复活 lexical，共存语义不变；此守卫在既有态下行为不变：hybrid
            # 开时本分支先前亦不可达）
            cand = pool or n or max(topk, int(self._cfg["lexical_candidates"]))
            hits = self._search_cos(vec, cand)
            if hits:
                hits = rerank_hits(q, hits, float(self._cfg["lexical_lambda"]))
                if deep:
                    hits = self._decrowd_assemble(q, hits, topk, truncate=True,
                                                  route_res=route_res,
                                                  fold_window=fold_win)
                else:
                    hits = hits[: (fold_win or topk)]
            return hits
        hits = self._search_cos(vec, (max(n or topk, pool) if deep
                                      else (n if n is not None
                                            else (fold_win or topk))))
        if deep:
            hits = self._decrowd_assemble(q, hits or [], topk,
                                          truncate=(n is None), keep=n,
                                          route_res=route_res,
                                          fold_window=fold_win)
        return hits

    def _gen_variants(self, q, budget=None):
        """mq 变体生成：variant_fn 注入优先（离线测试），否则真实 flash 调用。

        任何失败（multiquery 模块缺席/端点未解析/全部调用失败）→ []，retrieve
        据此退单条原查询（零恶化）。返回前统一清洗（去重/截长/条数钳
        [0, mq_n_variants]，注入路径与真实路径同一套规则）。

        批B4（2026-09-22）：
        - mq_single_variant=true → n 强制 1（配方=单变体 en，覆盖 mq_n_variants；
          VARIANT_SPECS 顺序保证第 0 条即英文翻译）；
        - budget=生成阶段秒预算（调用方 _retrieve_mq 按 mq_variant_timeout 与
          mq_wall_timeout 剩余取小后传入）；None=用 cfg["mq_variant_timeout"]
          （initialize 已归一为 float，坏值回退旧键 mq_timeout_seconds）；
        - 日志 [rag-mq] variants 行加 single=0/1 字段，与降级打点
          （degrade reason=...）配合区分"配方单变体"与"多变体旧态"。
        """
        single = bool(self._cfg.get("mq_single_variant"))
        n = (multiquery.clamp_n_variants(self._cfg.get("mq_n_variants"))
             if multiquery is not None else 0)
        if single:
            n = 1
        try:
            if multiquery is None:
                raise RuntimeError("multiquery 模块不可用")
            if self._variant_fn is not None:
                raw = self._variant_fn(q)
                got = multiquery.clean_variants(
                    q, raw if isinstance(raw, list) else [], n)
            else:
                if budget is None:
                    budget = self._cfg["mq_variant_timeout"]
                endpoint = resolve_embed_endpoint()
                got = multiquery.generate_variants(
                    q, n_variants=n, model=str(self._cfg["mq_model"]),
                    timeout=float(budget),
                    endpoint=endpoint, log=self._log,
                    wall_clock=bool(self._cfg.get("mq_wall_clock")))
            self._log(f"[rag-mq] variants asked={n} got={len(got)}"
                      f" single={1 if single else 0}")
            return got
        except Exception as e:  # 只报异常类型名；退单条原查询
            self._log(f"[rag-mq] gen fail err={type(e).__name__}（退单条原查询）")
            return []

    def _condense_route(self, q, history, t0=None):
        """mq condense 路生成（键开才被调用，2026-10-24 施工）→ (c0|None, 是否实调)。

        - 无前史（确定性跳过，防滑坡条款唯一跳过形态）→ (None, False)：
          **零调用零打行且发生在端点解析之前**（L1 单轮零调用直证）；
        - condense_fn 注入优先（离线测试/harness 复放，variant_fn 先例）：
          注入产物走同一套 clean_variant 清洗；观测行由本侧包裹打
          （真实/注入两路径 [rag-mq-condense] 同形——改写全文恒落 journal，
          R5 定谳教训零豁免）；
        - 预算：mq_condense_timeout 与 mq 整体墙钟剩余取小（decompose
          _clamp_decompose_timeout 先例）；耗尽 → 弃路（打 stop 行）；
        - 任何失败 → (None, True)：弃该路零恶化（routes 退回现状，绝不抛出）。
        """
        try:
            cc = self._mq_condense or {}
            final, prior = multiquery.condense_views(
                history, cc.get("turns"), cc.get("chars"))
            if not final or not prior:
                return None, False               # 无前史：零调用零打行（L1 面）
            if self._condense_fn is not None:
                t0c = time.monotonic()
                raw = self._condense_fn(q, history)
                c0 = multiquery.clean_variant(raw) if isinstance(raw, str) else ""
                dur = time.monotonic() - t0c
                try:
                    if c0:
                        self._log(multiquery.fmt_condense_obs_line(
                            q, True, dur, c0))
                    else:
                        self._log(multiquery.fmt_condense_obs_line(
                            q, False, dur, err="EmptyRewrite"))
                except Exception:
                    pass
                return (c0 or None), True
            budget = float(cc.get("timeout"))
            wall = self._cfg.get("mq_wall_timeout")
            if wall and t0 is not None:
                _rem = wall - (time.monotonic() - t0)
                budget = min(budget, _rem) if _rem > 0 else 0.0
            if budget <= 0:
                self._log("[rag-mq-condense] stop budget=0（弃该路）")
                return None, True
            endpoint = resolve_embed_endpoint()
            c0 = multiquery.condense_query(
                q, history, model=str(cc.get("model")), timeout=budget,
                endpoint=endpoint, log=self._log,
                wall_clock=bool(self._cfg.get("mq_wall_clock")),
                turns_cap=cc.get("turns"), chars_cap=cc.get("chars"))
            return c0, True
        except Exception as e:  # 挂点异常吞噬：弃该路（恒不抛出）
            self._log(f"[rag-mq-condense] hook fail err={type(e).__name__}"
                      "（弃该路）")
            return None, True

    def _retrieve_mq(self, q, route_res=None, history=None):
        """mq 开时的检索编排：原查询+变体各走 _search_one → 多路 RRF 截 topk。

        - mq condense 路（2026-10-24 施工，默认关=零执行零漂移）：键开且有
          前史 → c0 独立化改写路插在 q0 之后、既有变体之前（独立计数不挤
          MQ_MAX_N_VARIANTS 帽；融合形态=RRF(q0,c0,…) 试点胜出形）；挂点与
          失败语义见 _condense_route；无前史=确定性跳过零调用零打行。
        - 变体生成失败/零变体（且无 condense 路） → 退单条原查询（与 mq 关
          同构，零恶化）；
        - 单个变体 embed/检索失败只跳过该路（原查询失败=整体 miss，同现状）；
        - 融合平滑常数复用 hybrid_rrf_k；每查询候选深度统一
          max(topk, hybrid_candidates)。
        - 期 1 路由挂接（默认关=零调用面）：route_res 透传各路 _search_one——
          mq 变体继承 server 端一次分类不重复判定；域面约束只在各路选席位
          生效（truncate=True 路），mq 深度路径不做路级域过滤（路级不选席
          纪律同款；域面过滤亦不入融合级，ADR-0018 修订表述见
          _decrowd_assemble）。
        - ADR-0018 融合级配额段（2026-10-06 R3C，mq_fused_select_enabled
          默认 false=零调用面、现状逐字节一致）：键开时——
          (i) 甲2 深窗配套：路级 keep（=depth，truncate=False 分支截断位）
            放粗到 decrowd 池深（decrowd_candidates，现值 60），rrf_fuse
            截断放粗到 mq_fused_candidates（null=回退 fold_win or topk）
            ——RRF 池上限=路数×keep（2×20=40 实证），C19 正主 raw (20,60]
            带入窗的必要面；重打分本就在深池内完成，路级零新增计算；
          (ii) 融合输出后挂 doc_quota_select 选席段（_mq_fused_select：
            ① 全局配额＋③ 域表参数面，窗=fold_win or topk，两遍制回补
            继承——纯函数复用零新选席机制）；
          (iii) 统一出口：融合正常出口与"仅剩原查询一路"退化出口同走本段
            （退化出口现状同样零载体=同病灶面）；mq 关/变体全灭退单条
            （variants=[] 早退，truncate=True 路）已在路级选席，不重复施加；
          (iv) 观测=[rag-mq-quota] 行（不含题面）；[rag-mq] 归因行明细超
            10 席截前 10+尾注（关态融合窗恒 ≤10=读数零变化）。

        批B4 整体墙钟预算（mq_wall_timeout，2026-09-22）：
        - 预算覆盖 mq 增量部分=变体生成+变体 embed/检索（生成阶段预算取
          min(mq_variant_timeout, wall 剩余)）；原查询路**不受预算截断**——
          预算耗尽=弃剩余变体路走已得路/原查询，绝不拖也绝不砍基础检索
          （零恶化口径同现有退化路径）；
        - 打点区分降级原因：reason=no_variants（生成失败/超时/全被清洗）与
          reason=wall_budget phase=gen|routes（墙钟耗尽，gen=生成阶段被切、
          routes=变体路阶段被切，cut=被弃路数）。
        """
        wall = self._cfg.get("mq_wall_timeout")  # initialize 已归一；None=无整体预算
        budget = self._cfg.get("mq_variant_timeout")
        t0 = time.monotonic()
        # mq condense 路（2026-10-24 施工，默认关=本段零执行零漂移；设计稿案甲
        # 挂点=既有变体生成之前）：键开且有前史 → flash 独立化改写 c0，挂 q0
        # 之后、既有变体之前（**不挤 MQ_MAX_N_VARIANTS 帽**，独立恰 1 路）；
        # 无前史=确定性跳过零调用零打行（L1 面）；任何失败弃路零恶化。
        # condense 计入 mq 整体墙钟预算（实调后才扣减生成阶段剩余预算——关态/
        # 跳过态预算算术与施工前逐字节同）。
        c0 = None
        cond_called = False
        if (self._mq_condense or {}).get("enabled"):
            c0, cond_called = self._condense_route(q, history, t0=t0)
        if wall:
            if cond_called:
                _rem = max(0.0, wall - (time.monotonic() - t0))
                gen_budget = min(budget, _rem) if budget else _rem
            else:
                gen_budget = min(budget, wall) if budget else wall
        else:
            gen_budget = budget
        variants = self._gen_variants(q, budget=gen_budget)
        if not variants and not c0:
            # 生成失败/零变体（且无 condense 路）：退单条原查询（depth=None=与
            # mq 关路径逐字节同构）
            reason = ("wall_budget phase=gen" if wall and
                      time.monotonic() - t0 >= wall else "no_variants")
            self._log(f"[rag-mq] degrade reason={reason}（退单条原查询）")
            return self._search_one(q, self._embed(q), route_res=route_res)
        topk = max(1, int(self._cfg["topk"]))
        depth = max(topk, int(self._cfg["hybrid_candidates"]))
        # 同源折叠开时终截断放粗到折叠窗（关态 fold_win=None 数值回退 topk；
        # mq 路 6-10 深位=各路 RRF 融合序，折叠窗语义与单查询路一致）
        fold_win = (max(topk, DEFAULT_SAME_SOURCE_FOLD_WINDOW)
                    if (self._fold or {}).get("enabled") else None)
        if fold_win:
            depth = max(depth, fold_win)
        # ADR-0018 甲2 深窗配套（2026-10-06 R3C，默认关=本表达式零执行零漂移）：
        # 键开时路级 keep（=depth）放粗到 decrowd 池深——RRF 池上限=路数×keep
        # （2×20=40 实证），C19 正主 raw 位次 (20,60] 带入窗的必要面；重打分
        # 本就在深池内完成（_search_one pool=max(topk, decrowd_candidates)），
        # keep 只是截断位=路级零新增计算；关断即数值回退（回滚面=主键单键）
        msel = self._mqsel or {}
        mq_sel_on = bool(msel.get("enabled"))
        if mq_sel_on:
            depth = max(depth,
                        max(topk, int((self._decrowd or {}).get("candidates")
                                      or DEFAULT_DECROWD_CANDIDATES)))
        routes = [q]
        # c0 路挂位（q0 恒在恒首——设计稿硬边界 1，勿拆勿改）：与 q0 归一同文
        # → 弃路（无信息增益）；与末轮追问同文 → **保留**（试点胜出形：自含
        # 末轮的复述路=去稀释增益所在，判据预登记 §1.3；RRF 列表序=查询序，
        # q0 在前保序优先语义原样承载）。
        if c0 and (" ".join(str(c0).split())).casefold() \
                != (" ".join(str(q).split())).casefold():
            routes.append(c0)
        routes += variants
        lists = []
        for i, qt in enumerate(routes):
            if i > 0 and wall and time.monotonic() - t0 >= wall:
                # 墙钟耗尽：弃剩余变体路（已得路照用；只剩原查询路则退单条）
                self._log(f"[rag-mq] degrade reason=wall_budget phase=routes "
                          f"cut={len(routes) - i}（弃剩余变体路，不拖原查询检索）")
                break
            try:
                lists.append(self._search_one(qt, self._embed(qt), depth=depth,
                                              route_res=route_res) or [])
            except Exception as e:
                if i == 0:
                    raise  # 原查询失败=整体 miss（与 mq 关时语义一致）
                self._log(f"[rag-mq] variant{i} 检索失败 err={type(e).__name__}"
                          "（跳过该变体）")
        window = fold_win or topk
        if len(lists) <= 1:  # 仅剩原查询一路（变体全灭/被墙钟弃）：退单条，截回窗深
            # ADR-0018 统一出口（2026-10-06 R3C）：退化出口与融合正常出口同走
            # 融合级配额段——现状退化出口同样零载体（同病灶面，设计稿 §五第 1 轮
            # ②新发现）；键关=现状前缀截断逐字节不变
            if not lists:
                return None
            if mq_sel_on:
                return self._mq_fused_select(lists[0], window,
                                             exit_face="degraded")
            return lists[0][: window]
        fused = multiquery.rrf_fuse_hit_lists(
            lists, topk=((msel.get("candidates") or window) if mq_sel_on
                         else window),
            rrf_k=float(self._cfg["hybrid_rrf_k"]))
        self._log(_fmt_mq_line(lists, fused))
        if mq_sel_on:
            return self._mq_fused_select(fused, window, exit_face="fused")
        return fused

    def _mq_fused_select(self, hits, window, exit_face="fused"):
        """ADR-0018 融合级配额段（2026-10-06 R3C；mq_fused_select_enabled=true
        才被调用，默认关=零调用面）→ 选席后 hits（rank 重编 1..n）。

        - **纯函数复用**=doc_quota_select（与单路 truncate 选席同器，零新选席
          机制）：参数面=① 全局配额（doc_quota_*，开时 quota_max、关时 None=
          非域表域块不限额）＋③ 域表（domain_doc_quota，域值覆盖全局档——更
          特异者胜）、doc_quota_exempt_docs 豁免优先于两者；窗=fold_win or
          topk（与单路 truncate 选席同窗口径）；两遍制回补语义原样继承（证据
          面绝不因配额缩水，S1 在册教训）；
        - 键值/语义/清洗/豁免/闸分纪律全部不变，仅载体位扩展；选席在 RRF 排序
          完成后施加：不改 fused 分、不改各路输入列表（在册纪律修订表述=
          "路级不选席，选席统一挂融合级组装段"，ADR-0018 决策⑤）；选席不改
          分：cos 原始分恒存、gate_cosine 读原始分——0.40 闸载体零侵蚀；
        - 融合正常出口与"仅剩原查询一路"退化出口统一走本段（exit_face 区分）；
        - 观测=[rag-mq-quota] 行：quota=on:N/off、ddq=域:上限（关态 "-"）、
          window=选席窗、pool=融合池深、yielded=让位席、backfilled=深位回补、
          changed=窗内成员/序变化 0/1、exit=fused|degraded——不含题面
          （[rag-decrowd] 同纪律），兼作 C19 型 miit 席计数观测线（V8R 诊断
          建议 (c)）。
        """
        if not hits:
            return hits
        d = self._decrowd or {}
        ddq = (self._domain_doc_quota or {}).get("table") or {}
        quota_glob = bool(d.get("quota_on"))
        selected = doc_quota_select(
            hits, window,
            d.get("quota_max") if quota_glob else None,
            d.get("quota_exempt") or (),
            domain_quotas=ddq)
        before = [((h.get("rec") or {}).get("id")) for h in hits[: window]]
        after = [((h.get("rec") or {}).get("id")) for h in selected]
        yielded = len(set(before) - set(after))
        backfilled = len(set(after) - set(before))
        ddq_s = (",".join("%s:%d" % (k, ddq[k]) for k in sorted(ddq))
                 if ddq else "-")
        self._log("[rag-mq-quota] quota=%s ddq=%s window=%d pool=%d "
                  "yielded=%d backfilled=%d changed=%d exit=%s" % (
                      ("on:%d" % d.get("quota_max")) if quota_glob else "off",
                      ddq_s, window, len(hits), yielded, backfilled,
                      1 if before != after else 0, exit_face))
        return selected

    def _dump_snapshot(self, query, vec, hits, state, extra=None):
        """④ 检索快照落盘（retrieval_snapshot_dir 开启才走到；默认关=零调用面）。

        - 追加一行 JSONL 到 <dir>/retrieval-snapshot.jsonl：
          {ts, query, vec（mq 路=None，多变体无单一向量）, state, gate/threshold,
          hits:[{rank,score,cosine,decrowd_factor?,channels?,id,doc_id,locator}]}；
        - 诊断件纪律：写失败（目录不可建/磁盘满等）warn 一次后静默，绝不抛、
          绝不影响检索主链路；文件含题面原文，本地诊断用途，生产默认不开；
        - 用途：排序实验/归因的查询向量+证据快照层（扩库靶子清单 §五"排序
          实验前置"；answers 通道离线侧钩子见 建库/scripts/retrieve.py 头注）。
        """
        d = (self._decrowd or {}).get("snapshot_dir")
        if not d:
            return
        try:
            os.makedirs(d, exist_ok=True)
            rows = []
            for h in (hits or []):
                rec = h.get("rec") or {}
                # cosine 口径同 gate_cosine：纯余弦态无 cosine 键（score 即余弦）
                _cos = h["cosine"] if "cosine" in h else h.get("score")
                row = {"rank": h.get("rank"),
                       "score": _decrowd_round6(h.get("score")),
                       "cosine": _decrowd_round6(_cos),
                       "id": str(rec.get("id") or ""),
                       "doc_id": str(rec.get("doc_id") or ""),
                       "locator": str(rec.get("locator") or "")}
                if h.get("decrowd_factor") is not None:
                    row["decrowd_factor"] = h["decrowd_factor"]
                if h.get("channels"):
                    row["channels"] = h["channels"]
                rows.append(row)
            line = {"ts": round(time.time(), 3), "query": str(query or ""),
                    "vec": [float(x) for x in vec] if vec is not None else None,
                    "state": state, "n_hits": len(rows), "hits": rows}
            if extra:
                line.update(extra)
            with open(os.path.join(d, "retrieval-snapshot.jsonl"), "a",
                      encoding="utf-8") as f:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
        except Exception as e:  # 诊断件绝不拖垮检索：warn 一次后静默
            if not self._snapshot_warned:
                self._snapshot_warned = True
                self._log(f"[rag-snapshot] warn write fail err={type(e).__name__}"
                          "（快照降级，检索不受影响）")

    def rerank_probe_candidates(self, query, n=50, query_vec=None):
        """rerank log-only 影子探针数据面（2026-10-12 部署窗件2；姿态=ADR-0011
        2026-10-12 终条：rerank 作真空/域外**拒答信号**标定面——绝不沿用余弦
        阈值、不碰闸分载体、不改检索结果与答案流）。

        纯余弦 top-n 候选池快照（E 判死实验 d50 池的同构复刻：判据-预登记与
        标定报告的候选池=本地纯余弦排序，本方法对同一查询+同一已装载库态
        确定性重现该池）。**只读旁路，主链路行为零变化铁律**：
        - retrieve() 主链路一行不动（本方法独立于 retrieve 存在，检索结果/
          gate_cosine 闸分/证据组装零接触）；
        - 独立补嵌查询向量（探线程内完成，embed 用量照常打 [rag-embed] 行
          ——服务端查询嵌入 ~10 tok/问不计台账口径不变）+ 独立 _search_cos
          （faiss 开时与主链路共用同一只读索引，IndexFlatIP 并发 search 安全）；
          2026-10-12 合围 Wave 2-A：新增可选参 query_vec——调用方已算出主链
          查询向量时直传复用（跳过补嵌=每问省一次 embed 实调，[rag-embed]
          行相应少一行=判据 E11 登记在案的唯一有意差异）；None=现行为逐字节
          不变（自查补嵌；缺 vec/旧调用形态回退自查，兼容底线不炸不静默
          错池）。向量入同一 _search_cos，候选池与打分零变化；坏向量（维度
          不符等）由 _search_cos 原样抛出，探针调用方兜底记跳过（契约不变）。
        - 只读 self._recs，不写任何检索共享态；失败原样抛出，由探针调用方
          兜底记跳过（绝不向主链路传播）。
        → [{id, doc_id, locator, cos, text}]（不足 n 取全部；空查询/空库=[]）。
        """
        q = (query or "").strip()
        depth = max(1, int(n))
        if not q or not self._recs:
            return []
        vec = query_vec if query_vec is not None else self._embed(q)
        hits = self._search_cos(vec, depth) or []
        out = []
        for h in hits[: depth]:
            rec = h.get("rec") or {}
            sc = h.get("score")
            out.append({"id": str(rec.get("id") or ""),
                        "doc_id": str(rec.get("doc_id") or ""),
                        "locator": str(rec.get("locator") or ""),
                        "cos": (round(float(sc), 6)
                                if isinstance(sc, (int, float))
                                and not isinstance(sc, bool) else None),
                        "text": str(rec.get("content") or "")})
        return out

    def retrieve(self, query, route_res=None, history=None):
        """→ (evidence_text, sources)、LowScoreResult（低分 off_topic）、
        CoverageMissResult（覆盖闸 off_topic，2026-09-28 S1 治理丙）或 None。

        mq_enabled=true 时先走 multi-query 编排（变体生成+多路 RRF，退化
        路径见 _retrieve_mq）；默认关=单查询现行行为，零额外调用。
        history（2026-10-24 mq condense 施工，案甲可选参，默认 None=向后兼容
        零行为）：server 侧 chat 入口传入裁剪后 messages（user+assistant）；
        **仅 mq_condense_enabled 且有前史时被消费**（末轮 user 之前的消息），
        键关/无前史=零调用零行为差（L0/L1 断言面），绝不改动 q0 的构造。
        clause_family_rerank 开（默认）时在闸门前做 order-only 同款族重排
        （父条让位+限定词/主体词负项，只改次序不改成员——S1 治理乙）。
        same_source_fold_enabled 开（2026-10-03 检索链尾键，默认关=零执行）
        时在乙层之后、闸门之前做同源折叠：已排序列表前 10 窗（不足取全部）
        fold1 单席族帽折叠后截回 topk（=运营/呈报-纯折叠第二钥匙-20261003.md
        采纳语义；乙层只作用于终 topk 头部，窗内 6-10 位原序殿后）。
        same_source_fold_scope="tables+asn1"（2026-10-08 W4 D5 甲扩展键，默认
        "tables"=现状逐字节一致）时族帽扩展：asn1 参数卡版本尾主干并族+同 doc
        同 IE 异名兄弟题面锚定并族（same_source_fold_asn1；仿真定形与判效=
        建库/work/词面通道复放-20261008/fold扩展-仿真定形-20261008.md）。
        b_evict_enabled 开（2026-10-03 检索链尾键，默认关=零执行）时在同源
        折叠之后、终 topk 截断与闸门段之前做 B-evict 定向清位：题面命中
        B_EVICT_VOCAB（七词冻结）才激活，rank1 负项基准逐出窗内负项严格超
        基准的块，幸存者原序取前 topk（rank1 恒幸存；W 空=零改动；激活时打
        [rag-evict] 行）。
        mmr_enabled 开（2026-10-23 波3 工程件检索链尾键，默认关=零执行）时
        在上述治理键全部生效后的终 topk 截断面之后、闸门段之前做 MMR 向量
        去冗余重排（order-only 同集合置换：λ·原始余弦相关性−(1−λ)·已选集
        最大块间余弦的贪心选席；cosine/score 字段逐字节不动，rank 按 MMR
        终序重编并附独立 mmr_rank 观测键；换位时打 [rag-mmr] 行；键义与
        挂点理由见件头注 2026-10-23 段）。
        score_threshold>0 时在 build_evidence 前闸门：证据集最大余弦原始分低于
        阈值 → LowScoreResult（不注入证据不下发 sources）；cover_gate_enabled
        开（默认）时串联第二道：题面含库外域词表词而证据集全缺该词 →
        CoverageMissResult（S1 治理丙，串联不替代 0.40 线）；任何环节失败仍
        返回 None=退裸答（rag=miss，与两闸标记严格区分）。
        weak_gate 开时（2026-10-06 R3C 弱注入辅助闸，默认 {}=关=零执行）在
        两闸通过后、build_evidence 前做 (a) 绝对弱带 ∧ (b) 梯度平坦判定：
        weak 触发且 action=annotate 时证据头部追加弱相关提示行（计入
        max_context_chars 预算），action=mark/annotate 均打 [rag-weakgate]
        观测行——零改成员、零拒答、不立第三拒答态（键义/判据/动作档详见
        件头注 2026-10-06 R3C 段②）。
        retrieval_snapshot_dir 开启时（P0 ④，默认关）各返回路径统一经
        _dump_snapshot 落一行查询向量+证据快照（vec 捕获只在快照开启时改走
        局部变量，调用序与默认路径一致；mq 路 vec=None）。
        route_res（期 1 路由挂接，2026-09-29）：server 端 route_domain.classify
        结果透传位——route_enabled 关/缺省/None 时零消费（各路径与既往逐字节
        一致）；生效判定与选席约束/检索后兜底见 _search_one/_decrowd_assemble。
        """
        snap_on = bool((self._decrowd or {}).get("snapshot_dir"))
        vec_snap = None
        # E1 检索计时埋点（F线B，2026-10-14；执行计划 §五 性能门禁 v3）：
        # search_start/search_end 双时标——dur 差值用单调钟（time.monotonic，
        # 防系统调时跳变），start/end 另落 epoch 毫秒（与 trace 行 ts 同源对齐）；
        # 收口在下方 finally，全部返回路径（含异常兜底）统一打一行 [rag-search]
        # 行级观测行（经 log 路由在请求上下文内带 [trace:xxx] 前缀；无上下文=
        # 启动期/脚本期原样，与 _default_log 一致）。outcome 取值与 _dump_snapshot
        # 快照 outcome 位同词表（归因面对齐）；新增行级标记 obs_weekly 既有正则
        # 组零命中=零消费，不破既有解析面。
        search_t0 = time.monotonic()
        search_ts0_ms = time.time() * 1000.0
        search_outcome = "miss_error"   # 各返回路径覆写；异常路径保持缺省
        try:
            if not self._recs:  # 空库重探：库文件可能初始化后才生成
                self._load()
                if not self._recs:
                    search_outcome = "miss_empty_store"
                    self._dump_snapshot(query, None, None, "miss_empty_store")
                    return None
            q = (query or "").strip()
            if not q:
                search_outcome = "miss_empty_query"
                self._dump_snapshot(query, None, None, "miss_empty_query")
                return None
            topk = max(1, int(self._cfg["topk"]))
            if self._cfg.get("mq_enabled") and multiquery is not None:
                hits = self._retrieve_mq(q, route_res=route_res,
                                         history=history)
            elif snap_on:
                vec_snap = self._embed(q)   # 快照开启：向量留档（调用序同下）
                hits = self._search_one(q, vec_snap, route_res=route_res)
            else:
                hits = self._search_one(q, self._embed(q), route_res=route_res)
            if not hits:
                search_outcome = "miss"
                self._dump_snapshot(q, vec_snap, hits, "miss")
                return None
            # [S1 治理乙] order-only 同款族重排（默认开；clause_family_rerank=false
            # 回滚旧行为）：挂 gate_cosine 闸前，只重排证据集内部次序、不改成员。
            # 同源折叠开时证据面=终序前 fold_win 位，乙层仍只作用于终 topk 头部
            # （=折叠试点 full10 构造：乙重排 top5 + 窗内 6-10 位原序殿后）
            fold_on = bool((self._fold or {}).get("enabled"))
            fold_win = (max(topk, DEFAULT_SAME_SOURCE_FOLD_WINDOW)
                        if fold_on else 0)
            if self._cfg.get("clause_family_rerank"):
                head = hits[: topk] if fold_on else hits
                rer = clause_family_rerank(
                    q, head, str(self._cfg.get("clause_family_rerank_words") or "full"))
                if [h["rec"].get("id") for h in rer] != \
                        [h["rec"].get("id") for h in head]:
                    self._log("[rag] family_rerank moved（同款族父条让位/限定词"
                              "负项重排：order-only，成员与闸分不变）")
                hits = (rer + hits[topk: fold_win]) if fold_on else rer
            # [同源折叠] 检索链尾键（2026-10-03，默认关=本段零执行；过程日志三节 26②
            # 同日终拍+ADR-0009 调线在档）：作用于已排序列表前 fold_win 位（不足
            # 取全部），fold1 单席族帽（同族超席殿后保集合置换）后截回 topk=终
            # 证据集；rank 重编 1..n（build_evidence [出处N] 编号位）
            # [B-evict 定向清位] 检索链尾键（2026-10-03，默认关=零执行；呈报件
            # 采纳语义）：挂乙重排+同源折叠后、终 topk 截断与闸门段之前——题面
            # 命中 B_EVICT_VOCAB 才激活，rank1 负项基准逐出窗内负项严格超基准
            # 的块，幸存者原序取前 topk（rank1 恒幸存；W 空=零改动直过）
            evict_on = bool((self._bevict or {}).get("enabled"))
            if fold_on:
                window = hits[: fold_win]
                # 族键形按 scope 选（2026-10-08 W4 D5 甲）：tables=现状
                # fold1 逐字节不变（含日志）；tables+asn1=asn1 参数卡主干
                # 并族+题面锚定兄弟并族（same_source_fold_asn1，仿真定形）
                fold_asn1 = (self._fold or {}).get("scope") == "tables+asn1"
                if fold_asn1:
                    folded, deferred = same_source_fold_asn1(window, q)
                else:
                    folded, deferred = same_source_fold1(window)
                if deferred:
                    self._log("[rag-fold] window=%d deferred=%d%s（同源折叠：同族"
                              "超席殿后保集合置换，终 topk 只取族首）" % (
                                  len(window), len(deferred),
                                  " scope=tables+asn1" if fold_asn1 else ""))
                if evict_on:
                    folded, ev = b_evict_clear(folded, q, topk=topk,
                                               window=fold_win)
                    if ev["activated"]:
                        self._log("[rag-evict] q=%s base=%d evicted=%d（B-evict "
                                  "定向清位：rank1 负项基准逐出超基准块，"
                                  "幸存者原序取前 topk）" % (
                                      "/".join(ev["words"]), ev["base"],
                                      ev["evicted"]))
                hits = folded[: topk]
                for i, h in enumerate(hits, 1):
                    h["rank"] = i
            elif evict_on:
                # evict 单开（折叠关）：作用于乙重排后的已排序终序（窗=折叠关态
                # 的现行 topk 深度）——逐出/缩减语义同构，无 6-10 位晋位面
                hits, ev = b_evict_clear(hits, q, topk=topk)
                if ev["activated"]:
                    self._log("[rag-evict] q=%s base=%d evicted=%d（B-evict "
                              "定向清位：rank1 负项基准逐出超基准块，"
                              "幸存者原序取前 topk）" % (
                                  "/".join(ev["words"]), ev["base"],
                                  ev["evicted"]))
                for i, h in enumerate(hits, 1):
                    h["rank"] = i
            # [MMR 向量去冗余] 波3 工程件（2026-10-23，默认关=本段零执行）：
            # 挂点=乙重排+同源折叠+B-evict 全部治理键生效后的终 topk 截断面
            # 之后、0.40 闸门段之前——order-only 同集合置换（只动终 top-k 内部
            # 次序，成员集合恒等；折叠殿后/evict 逐出者已不在列表=不可复活，
            # 治理键零绕过零削弱），不产生新分数、闸分载体零接触（闸门段只读
            # 集合级统计，重排后读数不变）；换位时打一行 [rag-mmr] 观测行
            # （不含题面，[rag-decrowd] 同纪律）
            if (self._mmr or {}).get("enabled") and len(hits) > 1:
                hits, mmr_info = mmr_reorder(hits, self._mmr.get("lam"))
                if mmr_info["moved"]:
                    self._log("[rag-mmr] n=%d moved=%d lambda=%.2f perm=%s"
                              "（MMR 去冗余：终 top-k 内部次序重排，"
                              "成员与闸分不变）" % (
                                  mmr_info["n"], mmr_info["moved"],
                                  float(self._mmr.get("lam")),
                                  "/".join(str(p + 1) for p in mmr_info["perm"])))
            thr = float(self._cfg.get("score_threshold") or 0.0)
            if thr > 0.0:  # 阈值闸门（0=关）：只挂余弦原始分，融合分绝不作载体
                gate = gate_cosine(hits)
                if gate is not None and gate < thr:
                    self._log(f"[rag] low_score cos={gate:.4f} thr={thr:.2f}"
                              "（证据集余弦低于阈值，不注入证据）")
                    search_outcome = "low_score"
                    self._dump_snapshot(q, vec_snap, hits, "low_score",
                                        {"gate_cosine": gate, "threshold": thr})
                    return LowScoreResult(gate, thr)
            # [S1 治理丙] 覆盖闸（默认开；cover_gate_enabled=false 回滚）：串联在
            # 低分闸之后不替代——题面含库外域词表词而证据集全部块文本不含该词
            if self._cfg.get("cover_gate_enabled"):
                fired = cover_gate_miss_words(q, hits, self._cfg.get("cover_gate_vocab"))
                if fired:
                    search_outcome = "coverage_miss"
                    gcos = gate_cosine(hits)
                    gtxt = "na" if gcos is None else f"{gcos:.4f}"
                    self._log(f"[rag] coverage_miss words={'/'.join(fired)} "
                              f"cos={gtxt} thr={thr:.2f}"
                              "（库外域词题面在场、证据集全缺，不注入证据）")
                    self._dump_snapshot(q, vec_snap, hits, "coverage_miss",
                                        {"words": list(fired),
                                         "gate_cosine": gcos, "threshold": thr})
                    return CoverageMissResult(fired, gcos if gcos is not None else 0.0,
                                              thr)
            # [弱注入辅助闸]（2026-10-06 R3C，weak_gate 默认 {}=关=零调用面；
            # 设计稿=运营/扩容-R3设计稿-mq键效力修复-20261006.md §四，决策=
            # 过程日志三节37③）：挂点=0.40 主闸通过后、cover 闸后、build_evidence
            # 前（A/B 级无位次约束；C 级减席二期归 cover 闸后置位）。判据=(a)
            # gate_cosine < t_weak ∧ (b) 集内 max−P50 < flat_delta（AND 组合，
            # 单判据必误伤在档）；载体=集内原始余弦分布（gate_cosine 同器提取
            # 面，RRF 融合分绝不作载体）。动作=A 级观测打点（[rag-weakgate]
            # 行）＋B 级降注（action=annotate：证据头部追加 WEAK_GATE_HINT，
            # 计入预算）——零改成员、零拒答：0.40 主闸语义零改动、不立第三
            # 拒答态（弱带态="放行＋处置"，与 low_score/coverage_miss 两态
            # 严格并列）。
            wg = self._weakgate or {}
            weak_info = weak_gate_eval(hits, wg) if wg.get("enabled") else None
            wg_action = wg.get("action")
            trim_fired = bool(weak_info and weak_info["weak"]
                              and wg_action == "trim")
            trimmed_n = 0
            if trim_fired:
                # C 级减席（2026-10-07 落码，设计稿 §4.3）：只保块载体分 ≥
                # gate−keep_delta 的前席——载体口径=weak_gate_eval 同款
                # （cosine 键优先、缺则 score），RRF 融合分绝不作载体；gate
                # 载体块=max 块恒在（不会空窗）、保序保 rank（纯过滤，不动
                # 折叠/evict 段的重排位）、无载体分块保守保留（不可判不
                # 动作）——减席在 build_evidence 之前（超长弱块不再吃预算
                # 丢尾），mq 路与单路共用此段一处生效。
                floor = weak_info["gate"] - float(
                    wg.get("keep_delta", DEFAULT_WEAK_GATE_KEEP_DELTA))
                kept = []
                for h in hits:
                    c = h["cosine"] if "cosine" in h else h.get("score")
                    if not (isinstance(c, (int, float))
                            and not isinstance(c, bool)
                            and math.isfinite(c)) or float(c) >= floor:
                        kept.append(h)
                trimmed_n = len(hits) - len(kept)
                hits = kept
            header_extra = (WEAK_GATE_HINT
                            if (weak_info and weak_info["weak"]
                                and wg_action in ("annotate", "trim")) else "")
            evidence, sources = build_evidence(
                hits, self._cfg["max_context_chars"], header_extra=header_extra)
            if weak_info is not None:
                def _f4(v):
                    return "na" if v is None else "%.4f" % v
                msg = ("[rag-weakgate] weak=%d gate=%s p50=%s grad=%s "
                       "t_weak=%.2f flat=%.2f keep_delta=%.2f blocks=%d "
                       "dropped=%d action=%s" % (
                           1 if weak_info["weak"] else 0,
                           _f4(weak_info["gate"]), _f4(weak_info["p50"]),
                           _f4(weak_info["grad"]),
                           float(wg.get("t_weak")), float(wg.get("flat_delta")),
                           float(wg.get("keep_delta",
                                        DEFAULT_WEAK_GATE_KEEP_DELTA)),
                           len(sources or []),
                           len(hits) - len(sources or []),
                           wg_action))
                if trim_fired:
                    msg += " trimmed=%d" % trimmed_n
                self._log(msg)
            if evidence is None:
                search_outcome = "miss_evidence_overflow"
                self._dump_snapshot(q, vec_snap, hits, "miss_evidence_overflow")
                return None
            self._log(f"[rag] retrieve ok chars={len(evidence)} blocks={len(sources)}")
            search_outcome = "hit"
            self._dump_snapshot(q, vec_snap, hits, "hit",
                                {"blocks": len(sources)})
            return evidence, sources
        except Exception as e:  # 兜底：只报异常类型名，退裸答
            self._log(f"[rag] retrieve miss err={type(e).__name__}")
            self._dump_snapshot(query, vec_snap, None, "miss_error",
                                {"err": type(e).__name__})
            return None
        finally:
            # E1 检索计时收口（F线B，2026-10-14）：所有返回路径统一一行；
            # dur=单调钟差（ms 一位小数），start/end=epoch 毫秒。观测面自身
            # 兜底——打点任何失败绝不影响 retrieve 返回契约（退裸答纪律）。
            try:
                _ts1_ms = time.time() * 1000.0
                self._log("[rag-search] start_ms=%.1f end_ms=%.1f dur_ms=%.1f "
                          "outcome=%s" % (
                              search_ts0_ms, _ts1_ms,
                              (time.monotonic() - search_t0) * 1000.0,
                              search_outcome))
            except Exception:
                pass


if __name__ == "__main__":  # pragma: no cover —— 运维工具入口，非服务路径
    # 手动构建装载加速 sidecar：python rag.py --build-sidecar <store_path>
    # （幂等覆盖；库在飞续写期间勿建——sidecar 锚定构建时刻的 size/mtime）
    if len(sys.argv) == 3 and sys.argv[1] == "--build-sidecar":
        _store = sys.argv[2]
        _recs, _dim, _st = load_store(_store, use_sidecar=False)
        _bp, _mp = build_sidecar(_recs, _dim, _store, stats=_st)
        print(f"[sidecar] built recs={len(_recs)} dim={_dim} "
              f"bin={_bp} meta={_mp}", flush=True)
    else:
        print("用法：python rag.py --build-sidecar <store_path>", flush=True)
