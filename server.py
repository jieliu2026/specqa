#!/usr/bin/env python3
"""qa-bot 后端：单文件 FastAPI 服务。

- POST /api/chat  SSE 流式转发百炼 Token Plan 订阅端点（OpenAI 兼容）
                  config.json rag 段 enabled=true 时先做检索增强（详见 rag.py）：
                  命中→证据并入 system 消息、流式开始前先发 {"sources":[...]} 事件；
                  检索失败/库缺失→自动退裸答（日志 rag=off/miss），绝不影响主链路；
                  top1 余弦低于 rag.score_threshold（默认 0.40）→不注入证据、
                  不下发 sources，先发 {"type":"off_topic"} 事件再照常裸答流式
                  （日志 rag=low_score，前端提示"本次未命中语料"）
- 深度提升批A（2026-09-22，默认全关=现状不变；实现 citation_check.py，
  配置 rag 段 citation_check_*/abstain_* 六键，键义见 config.example.json）：
  A1 引文忠实度=hit 路径正文收尾后 judge 逐源校验，成功在 done 前发
  {"type":"citation_check",overall,per_source} 事件（抽样 citation_check_sample）；
  A2 二次拒答=hit 路径高危面题（本地启发式）先评证据充分性，insufficient →
  sources 事件前发 {"type":"evidence_insufficient",reason} 并给 system 消息
  追加保守模板指令。judge 失败/超时一律静默降级照常回答，绝不影响主链路；
  [chat] 日志尾部附 cc=off/skip/ok/err 与 ab=off/pass/insuff（rag=off 轮不打，
  既有 q=/top1=/ttfb 口径不动）
- 期 1 路由分类器挂接（2026-09-29，rag 段 route_* 七键，默认关=现状逐字节
  一致；设计稿=运营/设计稿-分层放行与路由-20260929.md §2.3"实现挂点"）：
  route_enabled 开时 chat 入口对拼接后 query 调 route_domain.classify 一次
  （mq 变体继承不重复分类），打一行 [rag-route] domain=X conf=N veto=0/1
  fallback=0/1（不含题面，纪律同 [rag-hybrid]；rag 侧检索后兜底再打同格式
  fallback=1 行）；[chat] 尾附 rt=<域简写>:<态>（v=veto/d=域定向/doc=doc 直判/
  f=全量回退，如 rt=concept:f、rt=param:v）；trace gate_detail 增 route 键；
  判定结果经 retrieve(query, route_res) 透传 rag 侧作选席约束（关断时单参
  调用，与既往逐字节一致）
- GET  /          聊天页面（frontend/dist/index.html 优先，缺件回退 static/index.html；
                  前端批次0 双态服务面，详见 / 路由处注）
- GET  /api/health 健康检查（分级：GET 只回 {"ok":true} 关侦察面；带有效会话
                  cookie 或 POST 带正确口令（校验同 /api/chat）才回
                  model/bot_name/has_key 完整字段；未配置口令的本地开发态
                  维持旧全量返回，key 绝不外泄）
- POST /api/login 口令换服务端会话（批2，设计稿 §2-§3）：校验 PBKDF2 哈希
                  （无哈希键时明文兼容期）→ 建 sessions 行 → Set-Cookie
                  qabot_session（HttpOnly+SameSite=Lax+Path=/+Max-Age 7d；
                  config https_enabled=true 才带 Secure，HTTPS 通道钩子）
                  登录失败限速（批2遗留补强）：同 IP 10 分钟窗 5 次失败后锁
                  登录，第 6 次起 429（对口令也 429——锁检查先于 PBKDF2，
                  防研磨暴力+计时侧信道+CPU 耗损）；成功登录清该 IP 计数
- POST /api/logout 删会话行+清 cookie

/api/chat 鉴权（批2 双轨）：cookie 会话有效→放行（裁剪后上下文落
sessions.msgs_json，≤max_history_messages）；否则回落 body passcode 双轨
（config passcode_body_enabled 默认 true；false 时 body 口令 401 收口——
收口判据看 [chat] 日志 auth=body 命中是否归零）。限流滑窗与会话均持久化
data/qa.db（SQLite WAL，标准库零依赖；惰性过期清理，无后台线程；环境变量
QABOT_DB_PATH 可覆盖路径，测试注入用）。

安全约定：订阅 key 只从环境变量 BAILIAN_TOKEN_PLAN_API_KEY 读入内存，
不写日志、不下发前端；日志只记 IP/字数/时长/首字时延（ttfb）/用量，rag 轮
另附截断 80 字符的查询摘要 q= 与最高相关分 top1=（hit 态=通道排序分，
low_score 态=触发闸门的余弦原始分；查询属用户内容不入密件名单，清洗+脱长
后落日志，供 建库/scripts/miss_attribution.py miss 归因）。embed 端点与 key
的解析纪律见 rag.py（环境变量优先，否则 ~/.bailian/config.json，绝不回显）。

token 月限+tokenizer 真实化（2026-09-28，默认全关/默认口径=现行行为逐字节
不变；施工报告 建库/logs/token月限tokenizer施工-20260928.md）：
- input_limit_unit（顶层键，默认 "chars"）：输入裁剪口径。chars=现行
  max_input_chars/max_total_input_chars 字符口径逐字节不变；"tokens" 时两键
  数值按 token 口径解释（计数器三档见 _probe_real_tokenizer 注释：本机 qwen
  tokenizer.json/tiktoken 真件优先，无则校准近似计数器）。
- rag 段 embed_monthly_budget_* 三键（embedding 月度预算闸）见 rag.py。

S1 负控治理（2026-09-28 选项一，运营/S1负控治理方案-20260928.md）：
- 丙覆盖闸态 rag=coverage_miss：retrieve 返回 CoverageMissResult（题面含库外域
  安全词形而证据集全缺该词）时不注入证据、不下发 sources，先发 {"type":
  "off_topic"} 事件（事件类型复用=前端零改动）再照常裸答流式；与 low_score
  严格分态打点，top1=闸前证据集最大余弦观测值。乙（order-only 同款族重排）
  只动 rag.py 检索内部次序，本件零改动。甲（判卷豁免）在 建库/scripts/
  smoke_accept.py。报告：建库/logs/S1治理实施-20260928.md。

E1 全链路 trace（2026-09-28 第 3 批工程任务，结构化日志）：
- 每个问答请求生成短 trace_id（时间戳+序号的 sha256 前 8 位 hex），三行结构化
  日志（[trace:xxxxxxxx] 前缀 + 紧凑 JSON 体，人类可读+机器可解析）：
  ①检索完成行 stage=retrieval（rag 态/top1/gate 判定/top-k 摘要
    [{id,doc,locator,score,is_answer,gate}]，id 经 rag.py build_evidence 挂钩点
    透传，is_answer 服务面未装载 section 字段恒 null）；
  ②LLM 完成行 stage=llm（模型/in/out/total tokens/耗时/ttfb/status）；
  ③引用映射行 stage=citations（答案 [出处N] 标记与 doc_id/locator 自然引用 →
    chunk 对齐，oob=引用了不存在编号）。
- trace_id 关联：[chat] 行尾追加 trace= 字段（尾附安全，miss_attribution 只解析
  前段 KV）；请求期 rag.py 打点经 log 路由加 [trace:xxx] 前缀（无请求上下文=
  启动行原样）；SSE 流首行发 ": trace_id=xxx" 注释行（SSE 规范注释，前端
  handle() 只认 data: 行零影响——不进 data 事件是因既有测试对首数据事件做
  逐字段精确断言且测试文件不在本次改动边界内）。
- 兼容纪律：既有 [chat]/[rag-embed]/[rag] 行的格式与字段原样保留（miss_attribution
  正则均 search 式，前缀/尾附不破坏解析）；新增 trace 行是附加行。

P1 生成端引用纪律（2026-09-29，扩库靶子清单 P1 行；rag 段键
citation_discipline_enabled，默认关=system 组装与既往逐字节一致、零新增 API）：
- true 且本题有证据注入时，system 消息末尾段落级追加 CITATION_DISCIPLINE_NOTE
  （TS 正文优先/TR 案例卡降辅助/制式归属标注/条款号不编造四条），治 citation
  维"参数卡冒充流程条款、TR 卡 rank1 引错正主"型失分（G01/G02/G12/G13/G18 型）；
- 与批A A2 保守模板可叠加（纪律段在前、A2 段在后）；prompt 级改动，答案卷
  复跑验证归评测会话（本仓只做施工+单测）。

批次D 多会话+跨设备历史同步·后端面（2026-10-03，前端侧另轮；config 顶层键
conversations_enabled 默认 true，false=回退键：三端点 404、chat 双写跳过、
device cookie 仍种）：
- device cookie qabot_device（值=secrets.token_urlsafe(24)，HttpOnly+
  SameSite=Lax+Path=/+Max-Age 365d，https_enabled=true 才带 Secure——与
  login 会话 cookie 同口径）：设备识别与登录会话解耦，重登录不丢历史；种植点
  =GET /、/api/chat 与三会话端点（请求未带即种；SSE 的 StreamingResponse 与
  FileResponse 均为 Response 子类，直接 set_cookie 最小侵入）；
- _Store 增两新表 conversations/messages（device_id 归属隔离；索引
  (device_id,updated_at) 与 (conv_id,id)）与五方法
  create_conversation/get_conversations/get_messages/append_message/
  touch_conversation/delete_conversation；登录路径（create_session）顺手惰性
  清理 90 天未动会话+孤儿消息+messages 行数帽 5 万（对齐既有惰性清理风格）；
- 三新端点（鉴权与 /api/chat 同门=有效会话 cookie 或口令任一过级；限速=独立
  conv_hits 小表每 IP 60 次/分，刻意不占 /api/chat 的 rate_hits 滑窗预算）：
  GET /api/conversations（updated_at desc 限 50，回 {ok,conversations:
  [{id,title,updated_at,last_role}...]}）、GET /api/conversations/{id}/messages
  （sources 解析失败给 null；不存在/非本 device → 404 {"error":"not_found"}）、
  DELETE /api/conversations/{id}（同 404 口径）；
- /api/chat 双写（SSE data 事件断言面零改动，只 additive 加响应头）：请求头
  X-QA-Conv-Id（可选 int；缺省/非法/非本设备一律自动建新会话——定案：缺省
  自动建新，避免隐式续写歧义，前端续写显式带 id）；user 消息请求解析后落库、
  assistant 完整回复流收尾后落库（错误收尾 content=错误 SSE 事件 JSON 原文，
  不做特判，前端恢复时自行按 error 形态呈现；用户断流不落半截答案）；sources
  存 messages.sources_json；SSE 响应头附 X-QA-Conv-Id: <id>；会话标题=首条
  user 消息前 24 字符。

批次E 反馈闭环+追问同流尾巴（2026-10-03，前端按钮与追问 chip 归下一前端轮）：
- E1 反馈端点（默认启用）：POST /api/feedback，body {trace_id?, rating, note?,
  passcode?}；rating 白名单 up/down、note 截 500 字符；鉴权=_conv_auth 同门
  （会话 cookie/body 口令/X-QA-Passcode 头任一过级，401 形态对齐 /api/chat）；
  限速复用 conv_hits 小表（与三会话端点合计每 IP 60 次/分——反馈是低频动作，
  分表各管各账纪律不动）；畸形 400 {"error":"bad_request"}，成功 {"ok":true}；
  数据落 feedback 表（id/ts REAL/trace_id/rating/note/conv_id，conv_id 取请求头
  X-QA-Conv-Id 合法整数否则 NULL）；journal 打 [feedback] rating= trace= conv=
  （note 内容绝不入日志——隐私纪律）。
- E1 trace 关联：/api/chat SSE 响应头新增 X-QA-Trace-Id（additive，照批次D
  X-QA-Conv-Id 先例）——前端下轮提交反馈凭此头关联 trace_id。
- E2 追问同流尾巴（config 顶层键 followup_tail_enabled，默认 false=生产行为
  零变化；试点判据见 运营/追问尾巴试点eval-20261003.md）：开启时 system 消息
  末尾追加 FOLLOWUP_TAIL_NOTE（正文结束后另起一行 <<<FOLLOWUP>>> 标记+2-3 行
  "- "追问建议）；流式转发改缓冲剥除——每段 delta 先并累积缓冲，扫描
  "\\n<<<FOLLOWUP>>>" 首次出现，只下发安全前缀（防标记跨 delta 拆半漏发：
  缓冲尾部按标记前缀最长重叠扣住），标记出现后进入截留收集态直到流结束；
  流自然结束仍未见标记则扣住的悬尾补发（正文一部分）。净文本作用面（三处
  纪律）：citation_gate/A1 judge/trace citations/批次D 落库 content 的
  answer_parts 只累积已下发安全前缀——尾巴绝不进闸、绝不进 messages 上下文
  回传、绝不落会话库。done 事件后发 {"type":"followups","items":[...]}
  （"- "行解析；非字符串/单条>200 字符/条数 0 或>3 整体丢弃不发）。

二期批A 重新生成改替换·案①服务端替换（2026-10-03，体验包；判据预登记=
运营/前端二期-批次A-20261003/判据预登记.md）：
- /api/chat 新增可选请求头 X-QA-Regen: 1（仅该值严格生效）——与显式合法
  X-QA-Conv-Id 续写组合时，双写 user 侧落库前先删该会话末轮（最后一条
  user 消息及其后全部消息，孤 user 断流形态一并覆盖），再写本轮 user；
  重新生成后服务端历史与前端一致（旧轮不残留，恢复会话旧答不重现）。
- 头缺省/值非 1/conv id 缺省或非法或非本设备 → 行为与既往逐字节一致
  （自动建新会话，regen 静默忽略）；conversations_enabled=false → 双写
  整体跳过，regen 头自然无效。既有端点/事件面/SSE data 断言面零改动。

二期批次B/C 后端面（2026-10-03，体验包；判据预登记=运营/前端二期-批次B-
20261003/判据预登记.md §三 与 运营/前端二期-批次C-20261003/判据预登记.md §一；
additive：既有端点/事件面零改动）：
- POST /api/conversations/import（批次B 旧记录导入）：body {messages:
  [{role,content,sources?},…], passcode?}——导入器只认 role/content/sources
  三键（白名单重建，transient/富显示字段端侧已剥），服务端再整单校验
  （feedback rating 同风格：严格白名单整单拒，不做部分接受），畸形一律 400
  {"error":"bad_request"}：body 非 JSON/非对象；messages 缺失/非 list/空
  list；条目非对象；role 越白名单（只认 user/assistant）；content 非
  string/空串/单条 >16000 字符；条数 >200；sources 非 list 或含非 dict 项/
  单条 sources >20 项。门序=开关 conversations_enabled（false→404）→
  conv_hits 同账限速（429）→_conv_auth（401 三态，_conv_auth 读 body 口令
  后 handler 二次 request.json() 照 feedback 先例——starlette 缓存 body）→
  body。建会话 create_conversation(device_id,'本地历史（导入）')（标题固定
  不随首条内容生成）+逐条 append_message（user 条 sources_json 恒 None，
  assistant 条有合法 sources 则 json.dumps 存 sources_json）；零 LLM 调用
  纯落库（导入量不增加任何 LLM 成本，200 条帽纯属请求载荷防御线——
  max_history_messages 是上下文裁剪线不是存储线）；updated_at 由
  append_message 内联 touch，导入毕即列表最新；会话挂本 device
  （_ensure_device 种 cookie 同三端点）；200 {"ok":true,"id":会话id}，不防
  重复导入（端侧标记键防重弹，快照键兜底）；journal 只打 [import] ip=
  n=条数 conv= id（消息内容/sources 绝不入日志——同 feedback note 纪律）。
- PATCH /api/conversations/{conv_id}（批次C C1 会话重命名）：body
  {"title":...}，成功 {"ok":true}（不回显 title——前端本地已置，对齐
  DELETE 形态）；门序照抄三会话端点（开关 404→conv_hits 同账 429→
  _conv_auth 401→conv id 非整数/超 SQLite 64 位绑定域 404→非本 device 或
  不存在 404 {"error":"not_found"}，归属校验进 store 方法 WHERE 照
  delete_conversation 形态，新增 _Store.rename_conversation）；title 口径=
  strip 后 1-100 字符：非 string（缺键/数字/数组/对象）→400 bad_request
  （显式类型校验不宽容 coerce——title 是载荷本体，非 feedback 附属字段）、
  strip 后空→400（截断兜不住空串，防误触清空标题）、超 100 →服务端截断到
  100 入库不 400（宽容先例=feedback note 截 500/create 标题截 24）；rename
  只 UPDATE title 不 touch updated_at/last_msg_id（排序键=消息时刻，改名
  不是消息，不得扰动 C2 最近活跃序）；journal 只打 [conv] rename ip= ok=
  （标题内容绝不入日志）。

部署窗件2·rerank log-only 影子探针（2026-10-12；姿态=ADR-0011 2026-10-12
终条：rerank 作真空/域外拒答信号标定面，绝不沿用余弦阈值、不碰闸分、陷阱判别
面归余弦闸+裁判；设计草案=建库/work/拒答信号标定-20261012/报告-20261012.md
§四）：检索完成后（hit/low_score/coverage_miss 三态）异步 fire-and-forget
守护线程取当次检索纯余弦 top-50 候选（rag.RagService.rerank_probe_candidates
只读旁路，retrieve() 主链路一行未动）调 qwen3.7-text-rerank 打分一次——journal
一行 [rerank_probe]（查询哈希+时间+0.75/0.85/0.95 三阈值过线计数+最高分+token
数+gold=na 金靶无关）+台账一行 stage=rerank_log（建库/logs/生成用量.jsonl）。
铁律=主链路行为零变化（探针开/关 SSE 逐字节一致）、超时 3s 失败只记跳过不重试
不阻塞、key 绝不落日志。config 顶层键 rerank_log_enabled（默认 true，试验目的
就是采数）/rerank_log_monthly_cap_cny（默认 5 元软顶：当月 rerank_log 台账累计
超顶自动跳过探针+warn 一次）。评测面零扰动：探针只挂 /api/chat，离线 harness
直连 rag 模块零探针。

F线C 输入侧 PII 止血（2026-10-14，F线语料专项 C 线）：chat 输入校验/截断后
挂 pii_mask.apply_to_messages（config 顶层键 pii_mask_mode 三态
off|log_only|mask，默认 log_only=只打 [pii_mask] 命中观测行〔零原文〕不实际
掩码，观察一周后启用 mask 归决策）；mask 态对 user 消息四类敏感字段（手机号/
邮箱/身份证/详细地址）占位替换、不截断全文，一切下游消费（session 落库/会话
双写/检索查询/LLM payload/q= 摘要）拿到的已是掩码后文本；模块缺席/异常=
fail-open 原样放行。详见 pii_mask.py 与 运营/F线/C线-止血实现与测试-20261014.md。
"""
import asyncio
import contextvars
import hashlib
import hmac
import itertools
import json
import logging
import math
import os
import random
import re
import secrets
import sqlite3
import threading
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(BASE_DIR, "config.json"), encoding="utf-8") as f:
    CONFIG = json.load(f)
SYSTEM_PROMPT_FILE = os.path.join(BASE_DIR, "system_prompt.txt")
_system_prompt_cache = ""


# 扫描噪声小改（2026-09-25，运营/扫描噪声小改-20260925.md）：公网扫描器向
# 8000 端口发垃圾字节（多为 TLS 探针）时，uvicorn 协议层（h11 与 httptools
# 两路径同文）各记一条 WARNING "Invalid HTTP request received."，单行、无
# traceback、响应照回 400——纯日志级噪声（周报口径 7 天 125 行，占 WARNING
# 面 88.7%）。此处对 uvicorn.error 记录器挂过滤器：仅把这一条消息降为 INFO
# （保留 journal 取证轨迹与扫描量趋势，退出 WARNING/Invalid 告警面），其余
# WARNING 一律原样放行。过滤器挂在使用 logging.getLogger 的单例记录器上，
# 本机 serve.py 与云端 run-cloud.sh（uvicorn server:app）双启动面同样生效。
class _DemoteScanNoise(logging.Filter):
    _DEMOTE = ("Invalid HTTP request received.",)

    def filter(self, record: logging.LogRecord) -> bool:
        if record.getMessage() in self._DEMOTE:
            record.levelno = logging.INFO
            record.levelname = "INFO"
        return True


logging.getLogger("uvicorn.error").addFilter(_DemoteScanNoise())


# 每问重读，兑现 README 刷新即生效承诺；读失败回退上次成功值
def _system_prompt() -> str:
    global _system_prompt_cache
    try:
        with open(SYSTEM_PROMPT_FILE, encoding="utf-8") as f:
            _system_prompt_cache = f.read().strip()
    except OSError:
        pass
    return _system_prompt_cache


_system_prompt()  # 启动时预读一次作缓存

API_KEY = os.environ.get("BAILIAN_TOKEN_PLAN_API_KEY", "")
UPSTREAM = "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions"

# ---------- F7 SSE 流守卫常数（评审 2026-10-15 立改，消零收尾 Y1） ----------
# 静默心跳：上游行间静默超此秒数 → 向客户端补发一行 ": ping" SSE 规范注释行。
# 前端两版（Vue dist 与 legacy static）handle() 均只认 "data:" 前缀的段，
# 注释行安全忽略（与既有 ": trace_id=" 行同款契约，源码亲核 2026-10-15）；
# 作用=防将来经反代/CDN 的空闲掐连（常见 60s 空闲超时）。15s=评审建议区间
# 15-30s 下限。测试注入小值时 patch 本模块属性即可（消费位裸名查模块全局）。
SSE_IDLE_PING_S = 15.0
# 整体上限：gen 上游流段（连接建立 → [DONE]）全程帽子，单位秒。依据=正常
# 生成 P95 远低于此（max_tokens 2048 上限；httpx read=180s 只兜单次读静默、
# 不设全程帽），300s 仅防异常长挂流：到点 raise httpx.TimeoutException 借
# 既有 upstream_timeout 降级路径收尾（SSE 事件/错误落库/trace 打点三处同
# 现行超时路，不裸抛）。收尾段各检测器（judge/闸）自带超时，不在本帽内。
SSE_TOTAL_LIMIT_S = 300.0

# ---------- RAG（检索增强，默认关闭；库缺失/检索失败一律退裸答，绝不拖垮请求） ----------
try:
    from rag import CoverageMissResult, LowScoreResult, RagService
    from rag import resolve_embed_endpoint as _rag_resolve_embed_endpoint
except Exception as _e:  # rag 模块本身不可用时退化为关闭，不影响主服务
    RagService = None
    LowScoreResult = ()
    CoverageMissResult = ()
    _rag_resolve_embed_endpoint = None  # rerank 探针端点解析面随 rag 缺席退跳过
    print(f"[startup] rag 模块加载失败（退关闭）err={type(_e).__name__}", flush=True)

# ---------- 深度提升批A（A1 引文忠实度 + A2 二次拒答；默认全关，模块缺席退关闭） ----------
try:
    import citation_check
except Exception as _e:  # 部署漏带等：两开关视同 false，其余链路不受影响
    citation_check = None
    print(f"[startup] citation_check 模块加载失败（批A退关闭）err={type(_e).__name__}", flush=True)

# ---------- 引用程序闸（二期 Phase 2 检测面：A1 前置的确定性核对，默认关） ----------
try:
    import citation_gate
except Exception as _e:  # 模块缺席=闸退关闭，行为与既往逐字节一致
    citation_gate = None
    print(f"[startup] citation_gate 模块加载失败（检测面退关闭）err={type(_e).__name__}", flush=True)

# ---------- 款号一致性检查（排序优化四期 P2 #1a 检测面，2026-10-03，默认关） ----------
try:
    import citation_clause_check
except Exception as _e:  # 模块缺席=检查退关闭，行为与既往逐字节一致
    citation_clause_check = None
    print(f"[startup] citation_clause_check 模块加载失败（检测面退关闭）err={type(_e).__name__}", flush=True)

# ---------- 期 1 路由域分类器（2026-09-29，默认关；模块缺席退关闭） ----------
try:
    import route_domain
except Exception as _e:  # 部署漏带等：route_enabled 视同 false，其余链路不受影响
    route_domain = None
    print(f"[startup] route_domain 模块加载失败（期1路由退关闭）err={type(_e).__name__}", flush=True)

# ---------- F线C 输入侧止血：PII 掩码（2026-10-14；config 顶层键 pii_mask_mode
# 三态 off|log_only|mask，默认 log_only=只打 [pii_mask] 命中观测行〔零原文〕不实际
# 掩码，观察一周后启用 mask 归决策；mask=四类敏感字段〔手机号/邮箱/身份证/详细
# 地址〕占位替换不截断全文。模块缺席=退关闭（不挂载不掩码不日志）；实现与测试
# 详见 pii_mask.py 模块头注+运营/F线/C线-止血实现与测试-20261014.md） ----------
try:
    import pii_mask
except Exception as _e:  # 部署漏带等：掩码面退关闭，主链路不受影响
    pii_mask = None
    print(f"[startup] pii_mask 模块加载失败（输入侧止血退关闭）err={type(_e).__name__}", flush=True)

# ---------- F线 CD2 毕业季职业向探测器在线挂载（2026-10-14；config 顶层键
# career_log 二态 on|off，默认 off——on 时 [chat] 行尾附 career=hit|- 纯标注
# 〔log-only：零原文零掩码零答题行为影响〕，规则=career_detect.py vC1.2
# 〔344 条金标回测 P=1.0/R=0.9586/F1=0.9789〕。模块缺席=退关闭不挂载（fail-open，
# 同 pii_mask 模式）。呈报位=运营/F线/CD2-观测挂载呈报-20261014.md） ----------
try:
    import career_detect
except Exception as _e:  # 部署漏带等：探测器退关闭，主链路不受影响
    career_detect = None
    print(f"[startup] career_detect 模块加载失败（探测器退关闭）err={type(_e).__name__}", flush=True)

# ---------- F线Q 红线答案过滤器在线挂载（YDT-013 确定性检测，2026-10-14；
# 冻结点3 终审决策③：生产化形态=log-only 检测先行、enforce〔句级拦截〕待观察
# 数据决策——沿 pii_mask 先例）。config 顶层键 redline_filter_mode 二态
# off|log_only，默认 log_only=只打 [redline_filter] 命中观测行〔trace/计数/
# 模式名，零原文〕不改答案不影响 SSE 事件面。模块缺席=退关闭（fail-open，
# 同 pii_mask/career_detect 模式）；规则=redline_filter.py v1（P 线 p2_filter
# 生产化；模式表=O 线 O5 机检六模式预注册逐字复用）） ----------
try:
    import redline_filter
except Exception as _e:  # 部署漏带等：过滤器退关闭，主链路不受影响
    redline_filter = None
    print(f"[startup] redline_filter 模块加载失败（过滤器退关闭）err={type(_e).__name__}", flush=True)


def _rag_config(config: dict):
    """解析 config.json 的 rag 段：缺失/非对象/enabled 非 true → None（=关闭，行为与无此段完全一致）。"""
    rag = config.get("rag") if isinstance(config, dict) else None
    if not isinstance(rag, dict) or not rag.get("enabled"):
        return None
    return rag


# F18 注入隔离围栏（2026-10-14 施工，提案=work/代码评审-20261015/F18-注入围栏
# 提案.md）：evidence 段在 system 侧组装时整体外套类 XML 标签，向模型声明检索
# 语料是资料不是指令。围栏只在 server 组装层外包——rag.build_evidence 输出
# 零触碰（仍以 EVIDENCE_HEADER 开头，rag 侧 startswith 断言面不破）；标签名
# 用 ASCII（qa_corpus）避免与语料内中文撞形；token 增量=两行标签，可忽略。
QA_CORPUS_FENCE_OPEN = "<qa_corpus>"
QA_CORPUS_FENCE_CLOSE = "</qa_corpus>"


def _build_system_content(system_prompt: str, evidence, extra: str = None):
    """system 消息组装：有证据时 system_prompt + 空行 + 围栏语料段；无证据照旧裸 system_prompt。

    evidence 非空时外套 <qa_corpus>…</qa_corpus> 围栏（F18，2026-10-14）：开标签
    独占一行，EVIDENCE_HEADER 仍是围栏内首行，闭标签独占一行；无证据（None/空串）
    不加标签=裸答路径与既往逐字节一致。

    extra（批A A2，2026-09-22）：非空时段落级追加在末尾（如证据不足保守模板
    ABSTAIN_SYSTEM_NOTE），位于围栏之外；缺省 None=无追加段。"""
    if evidence:
        evidence = f"{QA_CORPUS_FENCE_OPEN}\n{evidence}\n{QA_CORPUS_FENCE_CLOSE}"
    parts = [p for p in (system_prompt, evidence, extra) if p]
    return "\n\n".join(parts)


# ---------- 深度提升批A 配置（rag 段六键，默认全关=现状不变、零新增 API） ----------
DEPTH_FLAG_DEFAULTS = {
    "citation_check_enabled": False,   # A1 总开关
    "citation_check_model": "",        # judge 模型（空=同 chat 模型 CONFIG["model"]）
    "citation_check_sample": 1.0,      # A1 抽样率 [0,1]（1.0=每问必检）
    "citation_check_timeout": 3.0,     # A1 judge 秒预算（墙钟看门狗另加 0.5s 宽限）
    "abstain_enabled": False,          # A2 总开关
    "abstain_timeout": 3.0,            # A2 judge 秒预算
    "citation_discipline_enabled": False,  # P1 生成端引用纪律（2026-09-29，默认关）
    "citation_gate_enabled": False,        # 引用程序闸（二期 Phase 2 检测面，2026-10-01，默认关）
    "citation_clause_check_enabled": False,  # 款号一致性检查（四期 #1a 检测面，2026-10-03，默认关）
    "answer_anchor_format": "off",         # M1 锚定段（U线三刀 M1，2026-10-17；evidence_first=开）
}

# A2 证据不足时的保守模板指令（措辞贴 system_prompt 现有风格：诚实/出处/建议核实）
ABSTAIN_SYSTEM_NOTE = (
    "另外注意：本题涉及精确数值或参数取值，而检索语料可能覆盖不足。请保守作答："
    "先明确说明语料未能充分覆盖本题；凡给出数值、门限或取值范围，逐条标注出处"
    "（规范号/条款号），语料中没有的绝不编造；结尾建议用户以官方规范原文为准，"
    "重要结论提请人工复核。")

# P1 生成端引用纪律（2026-09-29，扩库靶子清单 P1 行：TS 正文优先/TR 卡降辅助/
# 制式归属标注——对 citation 维失分题（G01/G02/G12/G13/G18 型）的 prompt 级
# 治理；citation_discipline_enabled=true 且有证据注入时段落级追加在 system
# 末尾，默认关=system 组装与既往逐字节一致。零 API、纯本地拼接。
# 2026-10-03 追加第 4 条引用密度（排序优化四期 #1a：治款号试点 6/11 答零款号
# 声明的稀疏面；用户已批的 prompt 级生产文本变更，上产随下个部署窗）
CITATION_DISCIPLINE_NOTE = (
    "引用纪律（语料库为多规范混合库，作答引用时遵守）：\n"
    "1. 正式规范（TS 件）正文块优先作为答案依据与引用出处；TR 技术报告、案例卡"
    "只作辅助佐证，不得以其替代 TS 正文回答定义、流程、数值类问题。\n"
    "2. 引用须标注制式归属：TS 38.x/32.x/28.55x 为 5G NR 侧规范，TS 36.x 为 "
    "LTE 侧规范；问题明确制式时不得引用异制式规范条文作答（同名参数在两代规范"
    "中定义可能不同）。\n"
    "3. 出处写到规范号+条款号级（如 TS 38.215 5.1.1）；语料中未出现的条款号、"
    "版本号不得编造。\n"
    "4. 引用密度：答案中每个关键数值/指标结论处至少附一处条款号级出处（附录号/"
    "条号/款号或 Table 表号），不得只落文档级（只给规范号/文件名不给条款定位）。")

# E2 追问同流尾巴（2026-10-03 批次E；config 顶层键 followup_tail_enabled 默认
# false=system 组装与既往逐字节一致）。开启时段落级追加在 system 末尾（在
# P1 纪律段/批A A2 保守模板之后），命令模型在正文后输出标记行+2-3 条追问建议；
# 服务端流式剥除标记与尾巴只下发净正文（见 _followup_holdback），尾巴在 done
# 后以 {"type":"followups"} 事件另行下发。试点 eval=运营/追问尾巴试点eval-20261003.md。
FOLLOWUP_TAIL_NOTE = (
    "回答正文结束后另起一行输出标记 <<<FOLLOWUP>>>，随后 2-3 行每行一条以"
    "\"- \"开头的后续追问建议（基于本题与命中语料，短句）。")

# M1 证据引用锚定段（U线-可操作性 三刀 M1，2026-10-17 施工；设计件=work/
# U线-可操作性-20261017/M1锚定段-设计件-20261017.md §1，段文 333 字符逐字）。
# 与一期纪律段（已空 Δ 证伪）的机制差异=格式段非纪律段：无覆写声明/无头部
# 声明/无分型契约/无沿用声明；键开即**无条件常开注入**（设计件 §6"实施时
# 不得顺手加门"——无词表门无题型门，与一期 `and _method_query_hit(clean)`
# 的差异点即本刀假设核心）；适用域自含于段首（围栏内有语料时遵守），生产
# 退闸裸答态无围栏即无锚可给=段自然空转（设计件 §3.3）。注入位=_extra_notes
# 组装段 ABSTAIN 之后 E2 之前；token 增量 ≈+230 in tok/笔（设计件 §3.5）。
M1_ANCHOR_NOTE = (
    "证据引用锚定格式（回答所依据的语料片段在 <qa_corpus> 围栏内时遵守）：\n"
    "1. 每个关键结论（参数取值、门限判定、操作步骤、原因定位等）先给块级来源"
    "锚，紧随其后将结论翻译为操作判据：锚=出处编号与条款级出处同现，即"
    "「[出处N] 文档号（或文档名） 条款号/表名」，N 为围栏出处清单中的编号；"
    "判据=可据以执行的具体面——参数给数值与单位、门限给判定边界与适用条件、"
    "步骤给先后次序与检查点。\n"
    "2. 锚与判据成对紧邻（行文或表内均可），不另列出处清单；编号须与围栏出处"
    "清单一致；围栏未覆盖的内容不给锚、不编条款号，照常如实说明并建议核实渠"
    "道。\n"
    "3. 本条只约束引用与判据的表述格式：锚与判据并入原有结论句、行文与表格即"
    "可，先给结论、简洁、有条理的回答要求不变。")

# 甲·意图缺口通识标注（设计稿 v3-甲，2026-10-09 批）：方法论问法（怎么优化/
# 排查处理类）而库内证据只有规范条文时，SSE 预事件位下发确定性标注事件——
# 不依赖模型服从（评审 P1）。文案为非断言式：不对库内"有无操作方法"做事实
# 断言（评审 Q2），且不含「（citation_gate._QUOTE_RE 会把「…」当逐字摘录做
# hard 校验——评审 P20）。
INSIGHT_GAP_NOTE = (
    "以下为通用优化思路，非本库出处内容；具体参数与操作请以库内条文和现网实测为准")

# 方法论问法信号词表（触发条件一；设计稿 v2 §一.2 枚举逐字誊抄）。独立于
# route_domain.CONCEPT_SIGNALS 各自维护、本件不 import（评审 P17：route_domain
# 词表扩改须决策且有软锚，且 CONCEPT_SIGNALS 归概念域、方法论判定不能挂靠）。
# 扩改须决策禁自动生效（D9 纪律同款）。
METHOD_QUERY_SIGNALS = (
    "怎么优化", "如何优化", "怎么处理", "如何处理", "怎么排查",
    "排查思路", "优化思路", "优化方法", "处理方法", "操作方法",
    "具体操作", "怎么整治", "整治方案", "怎么提升", "如何提升", "怎么降低",
)

# 话术批（扩源专项 v3.4，2026-10-16）：off_topic 事件可选 note——按缺失主题
# 给"该领域暂未收录，建议参考 XX 渠道"确定性引导（预研-拒答话术-20261016
# §三 路径甲；管道先例=insight_gap note，服务端下发/前端 esc+截长渲染）。
# 简历职业类按职业向闭项决策维持域外如实：静态守卫词命中即零 note（不挂
# career_detect——其铁律=纯标注零答题行为影响）；永不覆盖面条目（外审
# P2-13）文案固定置首、任何后续扩表不得改写其语义与优先级；主题映射的
# 词形与引导语取自预研档 §三示例表。扩改须决策禁自动生效（D9 纪律同款）。
OFF_TOPIC_CAREER_GUARD = ("简历", "面试", "求职", "跳槽", "职业规划")
OFF_TOPIC_NOTE_PINNED = (
    (("MML", "mml", "网管"),
     "该领域涉及设备商内部文档，建议参考您所在运营商的内部网管手册或设备商技术支持"),
    (("题库", "真题", "认证考试", "HCIA", "HCIP", "HCIE"),
     "建议参考华为人才在线官方大纲"),
)
OFF_TOPIC_NOTE_TOPICS = (
    (("卫星",), "卫星通信（NTN）内容暂未收录，可参考 3GPP NTN 系列规范（TS 38.300 等）"),
    (("空口",), "空口信令细节可参考 3GPP TS 38.331/38.323/38.413 等对应篇"),
    (("携号转网",), "该业务办理口径本库暂未收录，建议参考工信部携号转网专区或运营商营业厅/官方 App"),
    (("宽带装机",), "装机流程属运营商属地业务，建议咨询当地装维/10000 号"),
)


def _off_topic_note(query, words=None):
    """话术批（2026-10-16）：off_topic note 归类器。守卫序=职业向（闭项决策
    维持域外如实）→ 永不覆盖面（P2-13，题面匹配）→ 主题映射；coverage_miss
    以闸触发词 words 查主题表（词表可经 cover_gate_vocab 配置，words 为权威
    口径），未命中或不适用（low_score/rerank_refused）再以题面关键词归类；
    均无命中返回 None（事件零 note=旧形态逐字节兼容，旧前端忽略新字段）。"""
    q = query or ""
    if any(k in q for k in OFF_TOPIC_CAREER_GUARD):
        return None
    for keys, note in OFF_TOPIC_NOTE_PINNED:
        if any(k in q for k in keys):
            return note
    for w in (words or ()):
        for keys, note in OFF_TOPIC_NOTE_TOPICS:
            if any(k in w for k in keys):
                return note
    for keys, note in OFF_TOPIC_NOTE_TOPICS:
        if any(k in q for k in keys):
            return note
    return None


# ---------- U线-可操作性 三刀 M5：无问句粘贴分诊（2026-10-17 施工；设计件=
# work/U线-可操作性-20261017/M5分诊-设计件-20261017.md） ----------
# 检测=门A（否定形必要条件：无问号 ∧ 不命中闭项疑问词表——命中任一直接放行
# 分诊照旧全链路）∧ 结构臂计分 ≥T（推荐档 T=2）：清单标记/长度/职责动词
# （≥2 去重命中才计）/简历版式词/名词堆叠（缩略语去重 ≥3 或顿号链 ≥2）。
# NR-4 组合形：单词命中永不单独触发——疑问词表只做否定形、技术名词只以密度
# 作弱证据（域内 ubiquitous，裸词即陷阱）。词表三张闭项，扩改须决策禁自动
# 生效（纪律同 METHOD_QUERY_SIGNALS / off_topic 话术批）。打点禁记题面
# （纪律同 [insight-gap]，只记 len/臂计数）。键关=判定块整段不进、检测函数
# 零调用，SSE 流与既往逐字节一致（设计件 §4.3）；触发轮省一次检索嵌入+一次
# 注定宏观的 LLM 生成（净省费）。
PASTE_INTERROGATIVES = (
    "多少", "怎么", "怎样", "如何", "为什么", "为啥", "啥", "什么", "哪", "吗",
    "呢", "是否", "谁", "几", "多久", "干嘛", "干啥", "请问", "还是", "能不能",
    "可否", "有没有",
    "what", "how", "why", "which", "where", "who",
)
PASTE_DUTY_WORDS = (
    "负责", "监控", "提取", "输出", "制定", "实施", "分析", "核查", "排查",
    "筛查", "处理", "维护", "调整", "编写", "汇报", "通报", "统计", "落地",
    "整治", "支撑", "保障", "验证",
)
PASTE_RESUME_WORDS = (
    "简历", "工作经历", "教育经历", "求职意向", "意向岗位", "相关技能",
    "基本信息", "邮箱", "性别", "民族", "本科", "大专", "学历", "公司名称",
    "自我介绍", "面试官", "持有", "认证",
)
PASTE_ACRONYMS = (
    "PRB", "RRC", "KPI", "SINR", "RSRP", "MR", "CHR", "MLB", "CA", "CIO",
    "TM3", "TM2", "E-RAB", "TOP", "QCI", "TA",
)
# ---------- 修复窗 2026-10-26 ①：祈使意图放行臂（过程日志 238⑤；诊断报告=
# work/急诊断-20261026/诊断报告-P0无法使用-20261026.md §四/§五.1） ----------
# P0 根因①修法：M5 门A 只认问号/疑问词，"帮我规整简历"类祈使句必中 res 臂
# 单臂+2 阈值被顶回（conv506 创始人三措辞七次全中实证）。本臂=门A 增补第二
# 否定形必要条件，两档词面：
#   PASTE_IMPERATIVE_MARKERS 任一命中即放行——祈使标记单臂即强意图（离线
#     验证集 84 题零命中，单词面零误放）；
#   PASTE_TASK_WORDS 去重命中 ≥2 才放行——任务动词多词并现=成句指令（conv506
#     措辞二"进行规整，细化和优化"三词并现形态）；单词命中不放行：域内 JD
#     粘贴 ubiquitous"优化"（离线集 33/84 含之）、帧A R6b-J075 含"优化+修改"，
#     单词面放行=防刷面洞开（词表剔除 修改 即此因：修改/优化 二词并现于帧A
#     在档题面）。词表三张闭项纪律同上，扩改须决策禁自动生效。
PASTE_IMPERATIVE_MARKERS = (
    "帮我", "帮忙", "麻烦", "烦请", "劳驾", "请把", "请将", "请帮", "请你",
    "请您", "求你", "求您", "帮把",
)
PASTE_TASK_WORDS = (
    "整理", "规整", "细化", "改写", "润色", "梳理", "完善", "提炼", "精简",
    "扩写", "扩充", "打磨", "重写", "优化",
)


def _paste_imperative_release(q):
    """修复窗① 祈使意图放行判定（纯本地零网络，恒不抛出）→ bool。

    True=该轮应放行进正常问答：命中任一祈使标记，或任务动词去重命中 ≥2，
    或"请+任务动词"紧邻形（请整理/请优化…——覆盖无标记礼貌祈使，且避开
    裸"请"子串误放：请示/申请/邀请在 JD 粘贴常见）。异常/空输入一律
    False（fail-open 纪律同 _paste_triage_hit——放行臂失效退回 M5 原行为）。"""
    try:
        if not isinstance(q, str) or not q:
            return False
        if any(w in q for w in PASTE_IMPERATIVE_MARKERS):
            return True
        if len({w for w in PASTE_TASK_WORDS if w in q}) >= 2:
            return True
        return any(("请" + w) in q for w in PASTE_TASK_WORDS)
    except Exception:
        return False

# 清单标记臂（§1.3）：①-⑳ 圈号；N、；N./N．（后随非数字——排除 4.8/2026.10
# 小数日期形）；N）；•●▶❶❷❸❹ 项目符。计数 m：m≥2→+2，m=1→+1。
RE_PASTE_LIST_ITEM = re.compile(
    r"[①-⑳]"
    r"|[0-9]{1,4}\s*、"
    r"|[0-9]+\s*[.．](?![0-9])"
    r"|[0-9]{1,4}\s*）"
    r"|[•●▶❶❷❸❹]")


def _paste_triage_hit(q, threshold=2, len_lo=50, len_hi=120,
                      imperative_gate=True):
    """M5 无问句粘贴判定（纯本地零网络，恒不抛出）→ (fired, score, arms)。

    门A=否定形必要条件（问号/闭项疑问词在场 → (False, 0, []) 直接放行）；
    结构臂计分 ≥threshold 触发（§1.4 伪码逐条落法）。arms=命中臂名列表
    （打点用，不含题面）；异常/空输入一律 (False, 0, []) 放行（fail-open
    纪律同 _method_query_hit）。
    修复窗 2026-10-26 ①：门A 增补祈使意图放行（imperative_gate=False 关闭
    该臂=修复前原行为，留作打点对照分/回归位；默认 True=生产态）。"""
    try:
        q = q if isinstance(q, str) else ""
        if not q:
            return (False, 0, [])
        if "?" in q or "？" in q:
            return (False, 0, [])
        if any(w in q for w in PASTE_INTERROGATIVES):
            return (False, 0, [])
        if imperative_gate and _paste_imperative_release(q):
            return (False, 0, [])
        arms, score = [], 0
        m = len(RE_PASTE_LIST_ITEM.findall(q))
        if m >= 2:
            score += 2
            arms.append("list")
        elif m == 1:
            score += 1
            arms.append("list")
        if len(q) >= len_hi:
            score += 2
            arms.append("len")
        elif len(q) >= len_lo:
            score += 1
            arms.append("len")
        if len({w for w in PASTE_DUTY_WORDS if w in q}) >= 2:
            score += 1
            arms.append("duty")
        if any(w in q for w in PASTE_RESUME_WORDS):
            score += 2
            arms.append("res")
        if (len({w for w in PASTE_ACRONYMS if w in q}) >= 3
                or q.count("、") >= 2):
            score += 1
            arms.append("nouns")
        return (score >= threshold, score, arms)
    except Exception:
        return (False, 0, [])


def _paste_triage_enabled() -> bool:
    """config 顶层键 paste_triage_enabled（**默认 false**——拨开属部署窗动作；
    false=判定块整段不进、检测函数零调用，/api/chat 行为与既往逐字节一致；
    形态同 followup_tail_enabled / rerank_refusal_enabled 先例，设计件 §4.2）。"""
    return bool(CONFIG.get("paste_triage_enabled", False))


def _paste_triage_threshold() -> int:
    """config 顶层键 paste_triage_threshold（默认 2=设计件 §1.4 推荐档；坏值/
    非 int/bool/出 [2,5] 设计验证包络一律回默认——越界回默认口径同
    rerank_refusal_threshold）。"""
    v = CONFIG.get("paste_triage_threshold", 2)
    if isinstance(v, bool) or not isinstance(v, int) or not 2 <= v <= 5:
        return 2
    return v


def _paste_triage_len_bounds():
    """config 顶层键 paste_triage_len_lo / paste_triage_len_hi（默认 50/120=
    设计件 §4.2 线上建议档——离线验证底截断于 80 字，长度臂线上区分力更高
    （§2.5）；坏值/非 int/越序（lo≥hi 或非正）整对回默认）。"""
    lo = CONFIG.get("paste_triage_len_lo", 50)
    hi = CONFIG.get("paste_triage_len_hi", 120)
    if (isinstance(lo, bool) or not isinstance(lo, int)
            or isinstance(hi, bool) or not isinstance(hi, int)
            or not 0 < lo < hi):
        return (50, 120)
    return (lo, hi)


# §3.2 话术（口吻对齐 off_topic 话术批：非断言式+给行动出口）。note 硬上限
# 200 字对齐前端截长；罐头正文以 delta 流式下发——前端对零 delta 收尾的轮落
# "本轮没有返回内容"错误兜底，罐头正文既是分诊文案主载体也防该坑。三选例句
# 自带疑问词（多少/怎么/什么）——用户照抄任一例句下一轮必过门A 进正常检索，
# 引导话术与检测规则闭环（设计件 §3.2 设计自洽点）。
PASTE_TRIAGE_NOTE = (
    "你贴的内容像是一段工作职责或资料粘贴，暂时没有看出你要问的问题。"
    "请告诉我你想做什么，我再检索作答。")
PASTE_TRIAGE_BODY = (
    "你贴的内容像是一段职责/资料粘贴，我还不知道你的问题是什么。请从下面"
    "三个方向里选一个，用一句话回复（把对象补上即可）：\n"
    "\n"
    "① **查定义、查取值**——例如：PRB 利用率的定义是什么？a3-Offset 的取值"
    "范围是多少？\n"
    "② **排查指标问题**——例如：切换成功率劣化怎么排查？\n"
    "③ **调参数、要步骤**——例如：网管上怎么调整 MLB 门限？单站验证的流程"
    "是什么？\n"
    "\n"
    "也可以直接用你自己的话提问。")

# ---------- 修复窗 2026-10-26 ②：同会话罐头去重+出路（过程日志 238⑤；报告
# §五.2）——同会话第二次触发分诊换"出路文案"（指明换个问法：带"帮我…"
# 或问号即直达作答），第三次起直接放行该轮进正常问答（死循环终结位：
# conv506 七连顶回形态不可再演）。note ≤200 字对齐前端截长（同上）。 ----------
PASTE_TRIAGE_EXIT_NOTE = (
    "本会话再次收到资料粘贴，我仍没有看到你想问的问题。直接把要做的事写成"
    "一句话发来，我马上开始处理。")
PASTE_TRIAGE_EXIT_BODY = (
    "同一段资料又发来了一次，我还是不知道你的目标是什么。请把要做的事直接"
    "写成一句话发给我，例如：\n"
    "\n"
    "- 「**帮我整理这份简历，细化工作经历**」\n"
    "- 「**把上面的内容改写成一段自我介绍**」\n"
    "- 「**这份简历有哪些不足，该怎么改？**」\n"
    "\n"
    "只要带上「帮我……」这类说法、或以问号结尾，我就会直接开始作答；再收到"
    "一次纯粘贴时，我会直接按资料内容尝试作答。")
# 修复窗②/④ 共用：会话键（设备 id 前 8 位——cookie 在位即稳定，测试态
# 无 cookie 每请求新造=互不串扰）→ 该会话分诊触发计数（含本轮）。内存态
# restart 清零（会话级短窗计数可接受）；键数 >4096 整表重置防无界增长。
_PASTE_TRIAGE_SEEN = {}
_PASTE_TRIAGE_SEEN_LOCK = threading.Lock()


def _depth_config(config):
    """批A 六键解析（config.json rag 段）：缺失/坏值一律回默认（全关、抽样 1.0、
    预算 3s）。sample 钳 [0,1]；timeout 越界 (0,30] 回默认（防误配零预算/长挂起）。"""
    rag = config.get("rag") if isinstance(config, dict) else None
    if not isinstance(rag, dict):
        rag = {}
    out = dict(DEPTH_FLAG_DEFAULTS)
    out["citation_check_enabled"] = bool(rag.get("citation_check_enabled"))
    out["abstain_enabled"] = bool(rag.get("abstain_enabled"))
    out["citation_discipline_enabled"] = bool(rag.get("citation_discipline_enabled"))
    out["citation_gate_enabled"] = bool(rag.get("citation_gate_enabled"))
    out["citation_clause_check_enabled"] = bool(rag.get("citation_clause_check_enabled"))
    # M1 锚定段（U线三刀 M1，2026-10-17）：取值 off/evidence_first（设计件 §6
    # 键名 answer_anchor_format 沿用咨询原文）；非 evidence_first 一律回 off
    # （坏值回默认 fail-closed，口径同本函数其余键）
    out["answer_anchor_format"] = (
        "evidence_first"
        if str(rag.get("answer_anchor_format") or "").strip() == "evidence_first"
        else "off")
    out["citation_check_model"] = str(rag.get("citation_check_model") or "").strip()
    for k in ("citation_check_sample", "citation_check_timeout", "abstain_timeout"):
        try:
            v = float(rag.get(k, DEPTH_FLAG_DEFAULTS[k]))
        except (TypeError, ValueError):
            v = DEPTH_FLAG_DEFAULTS[k]
        if v != v:  # NaN
            v = DEPTH_FLAG_DEFAULTS[k]
        out[k] = v
    out["citation_check_sample"] = min(1.0, max(0.0, out["citation_check_sample"]))
    for k in ("citation_check_timeout", "abstain_timeout"):
        if not (0 < out[k] <= 30.0):
            out[k] = DEPTH_FLAG_DEFAULTS[k]
    return out


# ---------- 期 1 路由分类器挂接（rag 段 route_* 七键之服务端消费面，2026-09-29；
# 默认关=现状逐字节一致。设计稿 §2.3"实现挂点"：chat 入口 build_retrieval_query
# 之后、retrieve 之前对拼接后 query 调 route_domain.classify 一次（mq 变体继承
# 域判定不重复分类=零新增调用）；min_confidence/conflict_policy/doc_direct 的
# 坏值清洗由 classify 侧承担（恒不抛出），此处只做 enabled 布尔化与键透传） ----------
ROUTE_RT_DOMAIN = {"概念": "concept", "口径": "kpi", "监管数字": "reg",
                   "参数": "param", "精确表": "table"}


def _route_config(config):
    """期 1 路由键解析（config.json rag 段）：缺失/非对象 → 全默认（关）。

    enabled=False（默认）时 chat 入口零 classify 调用、[chat] 无 rt= 字段、
    trace gate_detail 无 route 键、retrieve 单参调用——与既往逐字节一致。"""
    rag = config.get("rag") if isinstance(config, dict) else None
    if not isinstance(rag, dict):
        rag = {}
    return {"enabled": bool(rag.get("route_enabled")) and route_domain is not None,
            "min_confidence": rag.get("route_min_confidence", 1),
            "conflict_policy": rag.get("route_conflict_policy", "fallback"),
            "doc_direct": bool(rag.get("route_doc_direct", True))}


def _route_rt_field(res):
    """classify 结果 → [chat] 尾 rt= 字段值（设计稿 §2.3 例：rt=concept:f /
    rt=param:v）。域面=五域英文简写（无域命中 → -）；态面按优先序：
    v=veto 1（红线否决最高优先）｜d=route "domain" 生效定向｜doc=route
    "doc_direct" 生效直判｜f=route "fallback" 全量检索（冲突/零命中/置信不足/
    多号并现）。"""
    res = res or {}
    dom = ROUTE_RT_DOMAIN.get(res.get("domain"), "-")
    if res.get("veto"):
        sfx = "v"
    else:
        sfx = {"domain": "d", "doc_direct": "doc"}.get(res.get("route"), "f")
    return f"{dom}:{sfx}"


def _route_trace_detail(res):
    """classify 结果 → trace gate_detail 的 route 键（紧凑观测面，不含题面；
    E1 trace 消费端=评测会话/obs_weekly 期 3 切片）。"""
    res = res or {}
    return {"route": res.get("route"), "domain": res.get("domain"),
            "conf": res.get("confidence"), "veto": res.get("veto"),
            "fallback": res.get("fallback"),
            "doc_direct": res.get("doc_direct")}


def _make_depth_judge(model):
    """批A judge 生产实现：闭包绑定 Token Plan 订阅通道（端点/key 同 /api/chat
    主链路：UPSTREAM + 环境变量 BAILIAN_TOKEN_PLAN_API_KEY，key 绝不落日志）。
    测试用 mock.patch 换 citation_check.token_plan_judge 或本函数。"""
    def judge(messages, timeout):
        return citation_check.token_plan_judge(
            messages, api_key=API_KEY, model=model, upstream=UPSTREAM, timeout=timeout)
    return judge


# ---------- tokenizer 真实化（限流面，2026-09-28；默认 chars=现行逐字节不变） ----------
# input_limit_unit 顶层键（默认 "chars"）："tokens" 时 max_input_chars/
# max_total_input_chars 两键数值按 token 口径解释（键名不改，配置面免迁移）。
# token 计数器三档（探测顺序固定，结果缓存于 _tokenizer_state；默认 chars 口径
# 零探测零开销）：
#   ① 真 tokenizer：本机 qwen tokenizer 件优先——环境变量 QABOT_TOKENIZER_JSON
#      指定的 tokenizer.json，或 HF 缓存 ~/.cache/huggingface/hub/models--Qwen--*/
#      snapshots/*/tokenizer.json（tokenizers 包加载，~百 ms 一次性）；次选
#      tiktoken（已装且 cl100k_base 可离线加载时；无网加载失败静默跳过）。
#   ② 校准近似计数器（无真件时的现役档）：token ≈ CJK字符数×0.79 + 其余字符
#      数×0.42（ceil 取整，限流保守向）。系数由建库历史台账双锚回测校准：
#      - 查询面 38 题/985 tok 锚（建库/logs/hybrid-mq评测-vec缓存.json）→ cjk 0.79
#      - 语料面 30,124 块/16,717,356 tok 锚（09-24 云侧 CR 重嵌台账）→ 其他 0.42
#      默认粗档（cjk 1.0/其他 0.25）回测误差：查询面 +15.4%、语料面 −38.5%
#      （校准后双锚归零——2 锚拟合 2 系数，非独立验证；误差与口径详见施工报告）。
#   ③ 口径差异登记：近似档对纯英文散文高估（0.42 vs 实测 ~0.25，限流偏严=安全
#      向）、对中文题面低估于默认粗档（0.79 vs 1.0）；换真 tokenizer 档后
#      [tokenizer] tier= 日志一行可核；两档切换会改变截过程日志位置（chars 口径
#      完全不受影响）。
TOKENIZER_CJK_COEF = 0.79
TOKENIZER_OTHER_COEF = 0.42

_tokenizer_state = {"tier": None, "counter": None}   # tier: "qwen"|"tiktoken"|"approx"


def _hybrid_token_count(text, cjk_coef=TOKENIZER_CJK_COEF, other_coef=TOKENIZER_OTHER_COEF):
    """校准近似计数器（档②）：CJK（U+4E00-U+9FFF，与建库切块统计同口径）×
    cjk_coef + 其余字符（含空白/标点/换行，与回测锚同口径）× other_coef。

    返回 float（回测/校准用精确值）；限流口径经 count_tokens ceil 取整。"""
    cjk = 0
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff":
            cjk += 1
    return cjk * cjk_coef + (len(text) - cjk) * other_coef


def _probe_real_tokenizer():
    """档①探测（零网络纪律：只认本机已有件，不触发任何下载）→ (tier, counter)。

    - QABOT_TOKENIZER_JSON 指定件 → tokenizers.Tokenizer.from_file；
    - HF 缓存 Qwen 系 tokenizer.json（glob 快扫）→ 同上；
    - tiktoken 已装且编码可从本地缓存加载 → encode 计数（cl100k_base 近似档：
      非 Qwen 词表，量级参照用；无缓存需联网下载，ImportError/OSError 静默跳过）；
    - 全无 → (None, None)，调用方落档②。
    """
    import glob as _glob
    import os as _os
    cands = []
    env_p = _os.environ.get("QABOT_TOKENIZER_JSON", "").strip()
    if env_p and _os.path.isfile(env_p):
        cands.append(env_p)
    try:
        cands.extend(sorted(_glob.glob(_os.path.expanduser(
            "~/.cache/huggingface/hub/models--Qwen--*/snapshots/*/tokenizer.json"))))
    except Exception:
        pass
    for p in cands:
        try:
            from tokenizers import Tokenizer  # venv 已装（transformers 依赖件）
            tok = Tokenizer.from_file(p)
            return "qwen", (lambda t, _tok=tok: len(_tok.encode(t, add_special_tokens=False).ids))
        except Exception:
            continue
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")  # 无网/无缓存会抛，吞掉落档②
        return "tiktoken", (lambda t, _e=enc: len(_e.encode(t)))
    except Exception:
        pass
    return None, None


def _ensure_token_counter():
    """惰性解析计数器（首次 tokens 口径调用时探测一次并缓存）→ (tier, counter)。"""
    if _tokenizer_state["counter"] is None:
        tier, counter = _probe_real_tokenizer()
        if counter is None:
            tier, counter = "approx", _hybrid_token_count
        _tokenizer_state["tier"] = tier
        _tokenizer_state["counter"] = counter
        print(f"[tokenizer] tier={tier}（input_limit_unit=tokens 口径计数器就绪）",
              flush=True)
    return _tokenizer_state["tier"], _tokenizer_state["counter"]


def count_tokens(text):
    """text → token 数（int，ceil 保守向）。档①真 tokenizer 优先，落档②近似。"""
    tier, counter = _ensure_token_counter()
    n = counter(text)
    return int(n) if isinstance(n, int) else math.ceil(n)


def truncate_to_tokens(text, limit, count=None):
    """保前缀截断：最长 text[:k] 使 count(text[:k]) ≤ limit（二分，count 单调）。

    count 缺省 count_tokens（真件/近似自动选档）；limit ≤0 → ""；限内原样返回
    （与 chars 口径 content[:n] 的保头语义对齐）。"""
    cnt = count or count_tokens
    if limit <= 0:
        return ""
    n = cnt(text)
    if n <= limit:
        return text
    lo, hi = 0, len(text)   # 不变量：cnt(text[:lo]) ≤ limit < cnt(text[:hi])
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if cnt(text[:mid]) <= limit:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo]


def _input_unit(config):
    """input_limit_unit 键清洗 → "chars"（默认/坏值回默认）| "tokens"。

    容错口径：缺失/非字符串/未知值一律回 "chars"（=现行行为，回退路径=键回默认）。"""
    v = config.get("input_limit_unit") if isinstance(config, dict) else None
    v = str(v or "").strip().lower()
    return "tokens" if v == "tokens" else "chars"


# ---------- 多轮检索查询构造（2026-09-18 修实测短板，确定性、零额外 API） ----------
# 实测暴露：多轮对话先贴大段材料再短追问（"继续/然后呢"），只拿末条 user 消息做
# 查询向量化时只剩几个字（云端日志 [rag-embed] chars=8-10），检索回无关语料。
# 对策：末条 user 消息太短则向前拼最近 user 消息补充主题上下文。
RETRIEVAL_MIN_CHARS = 30   # 去空白后低于此长度才触发向前拼接
RETRIEVAL_MAX_CHARS = 600  # 拼接态查询总长上限（防 token 浪费）


def _nonspace_len(text: str) -> int:
    """去空白（含全角空格/换行/制表）后的字符数——长度口径以实际信息量为准。"""
    return len("".join(text.split()))


def build_retrieval_query(messages, min_chars=RETRIEVAL_MIN_CHARS,
                          max_chars=RETRIEVAL_MAX_CHARS) -> str:
    """clean 消息列表 → 检索查询（纯函数）。

    规则：
    - 取最后一条 user 消息为 base；base 去空白后 ≥ min_chars → 原样返回
      （与历史行为完全一致，不看更早消息）。
    - base 过短 → 向前找最近的上一条 user 消息（跳过 assistant），拼
      query = 上一条 + "\\n" + base；拼后去空白仍 < min_chars 可再拼更前一条
      （最多拼 2 条更早 user 消息，防止无限回溯）。
    - 无更前 user 可拼 → base 原样返回（retrieve 内部自会 strip）。
    - 拼接态总长超 max_chars → 保尾部截断：base（当前追问）必然完整保留，
      超出部分从更早上下文的开头裁掉。
    """
    users = [m.get("content") for m in messages
             if isinstance(m, dict) and m.get("role") == "user"
             and isinstance(m.get("content"), str)]
    if not users:
        return ""
    base = users[-1]
    if _nonspace_len(base) >= min_chars:
        return base
    parts = [base.strip()]
    cur = _nonspace_len(parts[0])
    joined = False
    for prev in reversed(users[:-1]):
        if cur >= min_chars or len(parts) >= 3:  # 已够长 / 已拼满 2 条更早消息
            break
        p = prev.strip()
        if not p:
            continue
        parts.insert(0, p)
        cur += _nonspace_len(p)
        joined = True
    if not joined:
        return base
    query = "\n".join(parts)
    return query[-max_chars:] if len(query) > max_chars else query


# ---------- 检索打点字段（q=/top1=，供 建库/scripts/miss_attribution.py 归因消费） ----------
RAG_LOG_Q_CHARS = 80  # q= 字段截断上限（查询是用户内容，超长只留前缀脱长）


def _q_log_field(text: str, limit: int = RAG_LOG_Q_CHARS) -> str:
    """检索查询 → [chat] 行 q="..." 字段值（清洗规则与 miss_attribution.py 的
    k="..." 正则逐字段对齐：值内不得含双引号/空白，否则解析中途截断）。

    - 控制字符/换行/不可打印字符折成空格（单行、日志安全）；
    - 内嵌双引号降级为单引号（防 KV 正则误截断）；
    - 连续空白折叠一格，截断到 limit 字符；空查询 → 空串。
    """
    if not text:
        return ""
    cleaned = "".join(
        "'" if ch == '"' else (" " if ch.isspace() or not ch.isprintable() else ch)
        for ch in text)
    return " ".join(cleaned.split())[:limit]


# ---------- E1 全链路 trace（2026-09-28：trace_id 生成/贯穿/结构化行，见件头注） ----------
_trace_seq = itertools.count()          # 进程内序号（next 原子，GIL 保护）
_trace_id_var = contextvars.ContextVar("qabot_trace_id", default=None)
# asyncio.to_thread 会复制当前 contextvars 上下文进工作线程——请求协程里 set 的
# trace_id 在 rag_service.retrieve（含其内部打点）里可见，rag.py 打点据此加前缀。
_TRACE_ID_RE = re.compile(r"^[0-9a-f]{8}$")   # trace_id 形态（测试/消费方核验用）
_CITE_MARKER_RE = re.compile(r"[出处来源]\s*0*(\d{1,3})")   # 答案引用标记（1 起编号）


def _new_trace_id() -> str:
    """时间戳+进程内序号 → sha256 前 8 位 hex（如 3fa2b91c）。

    8 hex=32 bit：个人问答机量级下碰撞可忽略；时间戳参与哈希保证跨进程/跨重启
    也几乎不撞。"""
    seq = next(_trace_seq)
    return hashlib.sha256(f"{time.time_ns()}:{seq}".encode()).hexdigest()[:8]


def _rag_trace_log(line: str) -> None:
    """rag.py 打点路由（RagService 构造注入）：请求上下文内加 [trace:xxx] 前缀，
    启动期/无上下文=原样输出（与 rag._default_log 逐字节一致）。"""
    tid = _trace_id_var.get()
    if tid:
        print(f"[trace:{tid}] {line}", flush=True)
    else:
        print(line, flush=True)


def _trace_line(trace_id: str, obj: dict) -> None:
    """结构化 trace 行：[trace:xxxx] 前缀 + 紧凑 JSON 体（单行，机器可解析：
    行首 [trace: 起至 ] 为 id，其后空格分隔一个 JSON 对象）。"""
    print(f"[trace:{trace_id}] "
          f"{json.dumps(obj, ensure_ascii=False, separators=(',', ':'))}", flush=True)


def _norm_cite_text(s) -> str:
    """引用匹配归一：去全部空白+小写（"TS 36.331"与"ts36.331"可互配）。"""
    return re.sub(r"\s+", "", str(s or "")).lower()


def _citation_alignment(answer_text: str, sources) -> dict:
    """答案引用 → chunk 对齐结果（纯函数，citations trace 行与单测共用）。

    - marker：答案出现 [出处N]/[来源N]/出处N 字样（编号 1 起=证据块编号口径）；
    - text_hit：doc_id/version/locator 归一后作为子串出现在答案归一文本
      （自然行文引用；纯数字形 locator 加数字边界，防 14.2 误配 4.2）；
    - oob：标记引用了超出 sources 编号的编号（对齐失败信号，归因用）。
    """
    ans = _norm_cite_text(answer_text)
    marker_ns = {int(m) for m in _CITE_MARKER_RE.findall(answer_text or "")}
    chunks, oob = [], []
    for n in marker_ns:
        if not (1 <= n <= len(sources or [])):
            oob.append(n)
    for i, s in enumerate(sources or [], 1):
        rec = s if isinstance(s, dict) else {}
        marker = i in marker_ns
        text_hit = False
        for key in ("doc_id", "version", "locator"):
            needle = _norm_cite_text(rec.get(key))
            if not needle:
                continue
            if re.fullmatch(r"[0-9.]+", needle):   # 纯数字形（4.2 / 2018）：边界匹配
                if re.search(r"(?<![0-9.])%s(?![0-9.])" % re.escape(needle), ans):
                    text_hit = True
                    break
            elif needle in ans:
                text_hit = True
                break
        chunks.append({"n": i, "id": str(rec.get("id") or ""),
                       "doc": str(rec.get("doc_id") or ""),
                       "locator": str(rec.get("locator") or ""),
                       "marker": marker, "text_hit": text_hit})
    uncited_n = sum(1 for c in chunks if not (c["marker"] or c["text_hit"]))
    return {"n_sources": len(sources or []), "chunks": chunks,
            "cited_n": len(chunks) - uncited_n, "uncited_n": uncited_n,
            "oob": sorted(oob)}


# ---------------------------------------------------------------------------
# G 徽标（备发包-20261012，默认关）：sources 事件附加 source_tier 纯增字段
# ---------------------------------------------------------------------------
# 分级口径=元数据规则层-草案.py SOURCE_TIER_MAP 已决策位（提升计划波2 G 线，
# 过程日志 61 登记）：TS 条款/YD-T 行标/工信部件=L1；TR 研究体/miit 统计公报/
# 合成卡主体/溯源卡=L2；导读卡（id 名单）/手写卡=L3。2026-10-19 govstd 域
# 扩入（职责域供给批 tier 决策，过程日志 122 号续笔③）：govstandards 教学
# 专业标准件=doc 级 L1（第五组常量 SOURCE_TIER_GOVSTD_DOCS）。映射面为部署窗冻结快照
# （生成自 f32.meta.json+导读卡两 staging 档，2026-10-12 本地 47,092 块口径；
# 46,697 系冻结时点遗留数字，2026-10-12 数据化施工批勘正=判据档 §六疑点1），
# 换库后未入表的新 doc：走 TS/YD-T/TR 前缀规则或返回 None=不加字段不渲染
# （缺级不猜级）。synthetic 域块级 id 名单必须存在——其 doc_id 与 3gpp TS/TR
# 撞名（如 TS 36.331 双域在役），仅 doc 前缀规则分不开域。
SOURCE_TIER_MIIT_STAT_DOCS = frozenset((
    "2025年通信业统计公报", "2026年上半年通信业经济运行情况",
    "2026年前8个月通信业经济运行情况"))
SOURCE_TIER_MIIT_DOCS = frozenset((
    "信息产业部令第36号", "国务院、中央军委令第672号", "国务院令第291号",
    "工信部令第35号", "工信部信管〔2019〕242号", "工信部信管函〔2026〕258号",
    "工信部联通信〔2023〕257号", "工信部规〔2026〕188号"))
# govstd 域（govstandards 教学专业标准件，2026-10-19 职责域供给批 tier 决策扩入，
# 用户"同意"采 L1；过程日志 122 号续笔③）：doc 级 L1，与统计公报/工信部件两集互不
# 相交（doc_exact 内不分先后）；键名与 建库/chunks/staging-zhiyu-moe-20261018.jsonl
# 块 doc_id 逐字一致（44 行，专项单测=keyface 断言）。
SOURCE_TIER_GOVSTD_DOCS = frozenset((
    "通信系统运行管理专业教学标准（高等职业教育专科）",))
SOURCE_TIER_SYNTHETIC_IDS = frozenset((
    "003177e7650b4db8", "003a71973e6acb96", "0080f827caaab4e8", "011a29a256d5c812", "02565159390ca02a", "03ceb7310874f019" ,
    "04517a0b896f5aea", "055767cba7e5626e", "064db558de6847eb", "06829a0810720a61", "081b5619e08ac4ec", "0858092a506fabe2" ,
    "099a36a0490b5801", "09b38026147fe699", "09c51fadb18d28f3", "0aa2ae92fb1dfaca", "0c3e6a15071125fe", "0ce8c4d6cf806302" ,
    "0d03585fde51c85b", "0d7640dba1d9faf2", "0e772a08efddcb5b", "0e79f44170bb2015", "0ef47a78bee97c73", "0fb6b4261d9b9e59" ,
    "101259695c4db304", "10aca1c6c5dd111c", "10e302d31ba3a444", "112ea03c98a1418b", "1163cb92dcc06bdf", "11e0dd9243219ada" ,
    "14280106a0669a37", "143e73e26d9d0643", "14575567529003d1", "14956e95424c49d0", "156f86df6da8eb91", "18276254d6f2a48d" ,
    "18db5575d7a27713", "198b03d599c9eb33", "19d13b6203ce904b", "1ab4ce2948840d09", "1ac5883be0af2e67", "1c8fdf50b1be8fba" ,
    "1d4a9496449e87d7", "1e465af435f5e7b2", "1eb72e511334d997", "200b88116963958c", "203f3304037cf9d8", "20491685b2d482f1" ,
    "205e131a2bbc3b64", "20951a3e3d35ce07", "21cd7ba9d391f099", "22b422601f40c332", "233c4ad6500b45c9", "235ca0124a9c8486" ,
    "24b4c5b0404d03b3", "25bc9087a7965ee8", "2652d0aa5efa1218", "274e1d70df72cb23", "2834a1e72054c838", "29a418a9386d930b" ,
    "2bf7f5f9797ed355", "2bfc5987b28f98bd", "2ee9671adde588b1", "2f4a9770332d53d2", "334b0f6dc9bb3b62", "33cddd3b7dc9cbed" ,
    "34ee4b501fc490f5", "360a5c9a015cab64", "3657252f3c0101f5", "36baefc06838fbc5", "370bfc82f3471cba", "3728b50e79c2fbaa" ,
    "37af1d81f1e5ee2a", "37e758559f38e1d0", "382744264bd55cd8", "39687a6e816bc9fd", "3b02a20e4b79a47d", "3e03d1c3169e636e" ,
    "3e814f5d79dbe330", "3f566c31dddf38ae", "40c3541ed3e25924", "411e16d5ea742bdf", "42032b0126506c88", "425682ef055b92a9" ,
    "45c6d578caf0f378", "4643dc9451879b1d", "48121af3d1dd0689", "498315cb9d3b4a4c", "49ac755c2be050ca", "4b3f4c83d1a4d08d" ,
    "4b59b41fb3cbdca3", "4cc16b4b919a6893", "4d615b1a9f942a45", "4dcbab0c277c9f29", "4ef5315959fc064f", "4efa051c50e3af40" ,
    "50bd674a30153e99", "50f0f96c83c78fa9", "51d33bbcca1a89bb", "52c557aa8b922314", "53863f0a64238b75", "53ad6c84973de677" ,
    "547c46cb20743ac6", "54b76c3e6e595895", "553d804e1301cd84", "55a982ef2c48030b", "562ead486589e7bd", "573676476d909608" ,
    "5ab312f2e6e7945d", "5ada7e130ec3a429", "5b115c266fa384c9", "5b354de32b5aacf2", "5c164ce4520cc48a", "5d8c6c93bf8d401e" ,
    "5f3373e2f0166904", "5f63496382c1cf75", "60e6f7ffffef8555", "612edb198c7f15a1", "6139fe1f730c3163", "62494787ab39d4a8" ,
    "6269314ce7beaf64", "62eb62c30292a755", "6320d42e1dbab038", "63c2255accc5b3a2", "6406c699c73bea88", "646b35fa22a2f764" ,
    "652b6cdb9e1d55e2", "653e7d476f6162fc", "660ef8f9218759e8", "6718f1264fc899dd", "673930c061cc9bbd", "69013ec077a0ce91" ,
    "6955a5e6301a2ec2", "6a3dd559376d93e6", "6b4d158de67c4925", "6d74a1720af6b98d", "6e82189a6c2b1d9d", "704353a7d7a58523" ,
    "71b7f69c581152d1", "728f426c39214f51", "73543200737f48aa", "74efeff4c7886299", "75db209c46a2d038", "781a96223f6203c9" ,
    "7864c7d1f8fee92c", "7a37a22e38282cb6", "7b60ea48624d0440", "7bacdb3a53fae023", "7be16aa401491da8", "7c6b02de4459ecba" ,
    "7c88e6341dea1b40", "7c8e6d7bc199302d", "7ebb293040756642", "7ec88aab049dd101", "7f06f3d01b123a6a", "7f28ef9c7181b64a" ,
    "7f3ea78990e1d9ff", "7f5c4ecd7ba6381e", "8094cda1a3d305f0", "81a6f221c1ddd9d9", "834ecac309a6f531", "837d248e7147ac0b" ,
    "847f71cd10bad471", "85432dad50f409c5", "85e2e241344a5ea7", "861cc1a943682c02", "869c902bfc645db9", "86b05b9a37d03436" ,
    "88a4d6e1ab2e6cc0", "895a51dc8ddb8ba7", "89d34d73f4137c69", "8b6ddac24c366486", "8d4fdfe8a8f3e5de", "8de0142bdc8cf473" ,
    "8fddc3d145d1788e", "919ec0eab73a5fa5", "95939fd54e8b3172", "9639328c0a90237c", "9657425ea3dd1a04", "96feb1564c758859" ,
    "972d170f22e291f0", "9779f520d4b2ba5e", "97beabfdaf7129ba", "987cf127bbad2ebf", "98bd4661537d5f0d", "9947cc6f47cb999c" ,
    "9c4b7596ceadb59c", "a0add7ae04474601", "a0d94dc858df0de9", "a0e83214ce401cbf", "a154a2e8f3ada09b", "a15ab430bc47632a" ,
    "a23c03b3291c021b", "a269f2315d1da2ee", "a31233cdfb2d1343", "a319b19c17f71726", "a385ce67ba3413c0", "a49e7adb6356fbcf" ,
    "a63d0c51903f1a1e", "a82ba902d26b5009", "aac021ea1ee43090", "ac519f8172190022", "b1bf13868574bd1c", "b756eb506365e34b" ,
    "b87af04c0b779c5f", "b88e9f4591f06bf9", "ba5b8b456905f9e1", "ba8afca3ccede1d1", "baa92ac70092a859", "baadc700c8b01546" ,
    "be46aa82d23beed3", "beb1857b43d458d2", "beb1a1b8c56033e2", "bf9cf474c7c5b4cb", "c0062b8948798b84", "c0ea27b27c9c418d" ,
    "c0f39d75cef7ee75", "c1e5df1f4f3a8daf", "c2cb9f8953fce497", "c2cefe465005af7e", "c355220e9998fa9e", "c36f5fe89676d170" ,
    "c3f7eaa7fd134f53", "c4483797f76b7439", "c478ac66c4af2eec", "c63d0ce253b58ce3", "c71933d51fa9cdf3", "c86039448a59f91a" ,
    "c9087e49ae28c650", "c965fb47f5c7ba67", "cb450ed3be8d06ad", "cbcedce45616153e", "cbfd840fc7758981", "ccf4025b382b8e14" ,
    "cebd99b9c6a1164c", "cec4762f1ef27f10", "d0474eee94dea508", "d0954cd9aa0bc9ee", "d24d9a4b06df9a5d", "d26f09610aed0b83" ,
    "d2c46aa6737b18fa", "d38f99917e5f1e52", "d514ec258c51bc87", "d52ac2a87580171c", "d65a973ef0ce6786", "d65e293da6121756" ,
    "d78edd56292fcd45", "d8182820792c72a9", "d8849d492c2fb43e", "d96ff4dd2501cc7d", "d970fad3a9f235b0", "d9f774a589838549" ,
    "da0e2f032f8bee79", "da1c999ee7508473", "da8da28ba992f1f7", "dad02caa6846d185", "db1aac27c4a46d74", "dbf0e6eb996b805c" ,
    "dce002f4ed9300a0", "dd5198924c276bc9", "de25e4d3f48bd5eb", "deb39da1eca7f91e", "ded2ba896889c55d", "ded462d238647460" ,
    "df3a5b876c4e9fd3", "df75f82c5cccf668", "dfb26a8aec286835", "e2f569de1999439c", "e3520be96c63bcce", "e3a24e7001ebde98" ,
    "e3bd00bcb9795abb", "e54f94fc4dd39479", "e6c043018df825d3", "e6f81e547ca13115", "e8359340adf0478d", "e8740058400290ff" ,
    "e96dcfc76c7931b0", "e9c3ebabb566a9a4", "ea3e6fdf0deb25e1", "eade2a568984f103", "eb811a86d1a22f77", "ebd6560af2b9cf8a" ,
    "ecdb7db8fda1bd6a", "ed4a5b84e8728af2", "ed91f2d2aa93f771", "ee06c1a3c13fd063", "ee537c1c758cbbe2", "ee55a812f4a7b28f" ,
    "f0c0fe5d847b5989", "f44e2a6206cf3e51", "f46f46f056dd7c28", "f4de3f64f8550e3b", "f4ed86fd365797e0", "f69867f679a84d82" ,
    "f8938b8da9466788", "f9888da5ddee58cc", "f9c941dc06d59441", "f9e47aa647c2ad52", "fa4e48461e847258", "fab710db879cc32b" ,
    "fb6d45094b55717f", "fb9fc99d85081102", "fbc161fa7cb2f702", "ff9ff810342aa56f",
))
SOURCE_TIER_DAODU_IDS = frozenset((
    "04517a0b896f5aea", "055767cba7e5626e", "09b38026147fe699", "0ef47a78bee97c73", "0fb6b4261d9b9e59", "10aca1c6c5dd111c",
    "1163cb92dcc06bdf", "14280106a0669a37", "143e73e26d9d0643", "156f86df6da8eb91", "198b03d599c9eb33", "1c8fdf50b1be8fba",
    "203f3304037cf9d8", "20491685b2d482f1", "20951a3e3d35ce07", "235ca0124a9c8486", "25bc9087a7965ee8", "2f4a9770332d53d2",
    "33cddd3b7dc9cbed", "360a5c9a015cab64", "3657252f3c0101f5", "36baefc06838fbc5", "370bfc82f3471cba", "382744264bd55cd8",
    "3e03d1c3169e636e", "3e814f5d79dbe330", "3f566c31dddf38ae", "45c6d578caf0f378", "4ef5315959fc064f", "50f0f96c83c78fa9",
    "51d33bbcca1a89bb", "53ad6c84973de677", "55a982ef2c48030b", "5ada7e130ec3a429", "62eb62c30292a755", "652b6cdb9e1d55e2",
    "6718f1264fc899dd", "69013ec077a0ce91", "6a3dd559376d93e6", "6d74a1720af6b98d", "71b7f69c581152d1", "728f426c39214f51",
    "73543200737f48aa", "7a37a22e38282cb6", "7c6b02de4459ecba", "7ec88aab049dd101", "7f28ef9c7181b64a", "847f71cd10bad471",
    "895a51dc8ddb8ba7", "919ec0eab73a5fa5", "9657425ea3dd1a04", "9c4b7596ceadb59c", "a154a2e8f3ada09b", "a23c03b3291c021b",
    "ba5b8b456905f9e1", "ba8afca3ccede1d1", "baadc700c8b01546", "be46aa82d23beed3", "c0ea27b27c9c418d", "c2cb9f8953fce497",
    "c355220e9998fa9e", "c3f7eaa7fd134f53", "c4483797f76b7439", "cb450ed3be8d06ad", "d0954cd9aa0bc9ee", "d2c46aa6737b18fa",
    "d65a973ef0ce6786", "d970fad3a9f235b0", "d9f774a589838549", "dd5198924c276bc9", "de25e4d3f48bd5eb", "e2f569de1999439c",
    "e3bd00bcb9795abb", "e54f94fc4dd39479", "e6c043018df825d3", "e8359340adf0478d", "e9c3ebabb566a9a4", "ea3e6fdf0deb25e1",
    "ebd6560af2b9cf8a", "ee06c1a3c13fd063", "ee537c1c758cbbe2", "ee55a812f4a7b28f", "f4ed86fd365797e0", "f69867f679a84d82",
    "f9e47aa647c2ad52", "fab710db879cc32b", "fb6d45094b55717f", "fbc161fa7cb2f702",))


# ---------------------------------------------------------------------------
# SOURCE_TIER 数据化装载层（合围-工程基建一期 2026-10-12；设计稿=建库/work/
# 合围-工程基建一期-20261012/设计稿-SOURCE_TIER数据化-20261012.md）：分级
# 规则以 data/source-tier.json（schema=来源等级映射/v1，判卷侧映射件的同源
# 逐字节副本）为主装载体，启动一次装载（模块装配点，不逐问重读）；任一
# 校验失败→回退上方五组 frozenset 常量快照（同一冻结快照的另一装载体，行为
# 零变化）+ [source-tier] 告警恰一行（warn-once）；文件态正常装载零输出
# （零噪音，判据 E2）。五组常量（含 2026-10-19 扩入的 govstd 组）保留为回退
# 快照+地板，不删（AST 守卫
# test_smoke_accept_vol10ext 与 tests/test_source_tier.py 均锚常量名，E5）。
# overlay 领先回退态语义（设计稿 §2.5/§十②，精确口径）：换库窗数据件可
# 领先常量（文件 ⊇ 常量地板），此时若回退，新 id 的块级缺级不猜级——无
# doc 级规则的新 doc→None 不加字段；撞名 doc→走既有前缀规则；回退态对
# 任意输入恒等于改造前常量级联（E2），子集降级为设计内建语义，非违约。
# ---------------------------------------------------------------------------
_SOURCE_TIER_DATA_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "source-tier.json")
_SOURCE_TIER_SCHEMA = "来源等级映射/v1"
_SOURCE_TIER_LEVELS = ("L1", "L2", "L3")
_SOURCE_TIER_PRECEDENCE = ["chunk_exact", "doc_exact", "prefix"]
_SOURCE_TIER_MAX_BYTES = 1 << 20            # 数据件 >1MB 即拒（防误指大件）
_SOURCE_TIER_SAMPLE_N = 8                   # 确定性抽样：每组排序后等距取 8 id


class _SourceTierRules:
    """装载终态规则对象（chunk_exact/doc_exact 查表 + prefix 元组序列）。"""
    __slots__ = ("chunk_exact", "doc_exact", "prefix")

    def __init__(self, chunk_exact, doc_exact, prefix):
        self.chunk_exact = chunk_exact
        self.doc_exact = doc_exact
        self.prefix = prefix


# 回退快照：四组常量 + 与 _source_tier_of 尾段逐字同的前缀元组，导入期拼装
_FROZEN_PREFIX = (("TS ", "L1"), ("YD/T", "L1"), ("TR ", "L2"))
_FROZEN_RULES = _SourceTierRules(
    {**{cid: "L2" for cid in SOURCE_TIER_SYNTHETIC_IDS},
     **{cid: "L3" for cid in SOURCE_TIER_DAODU_IDS}},   # 导读 L3 子集覆写合成 L2（生成器同向）
    {**{d: "L2" for d in SOURCE_TIER_MIIT_STAT_DOCS},
     **{d: "L1" for d in SOURCE_TIER_MIIT_DOCS},       # doc 级三集互不相交，合并=分步独立查
     **{d: "L1" for d in SOURCE_TIER_GOVSTD_DOCS}},    # govstd 域 doc 级 L1（2026-10-19 扩入）
    _FROZEN_PREFIX)


def _load_source_tier_rules(path):
    """尝试自 path 装载分级规则（纯函数：零打印零抛出，可注入路径=测试位）。

    返回 (rules, mode, reason)：成功=(_SourceTierRules, "file", "")；任何失败
    =(_FROZEN_RULES, "fallback", 原因类别)——缺件/IO/JSON 坏/结构校验不过/
    超体积全覆盖（判据 E2 三失败态）。三件校验：
    ① schema 版本：schema=="来源等级映射/v1" 且 precedence==固定序；
    ② 结构与值域：prefix=二维数组 [非空 str, L1|L2|L3]；doc_exact/chunk_exact
       =dict 且键非空、值∈{L1,L2,L3}（"L4" 等越界即拒）；
    ③ 常量地板+确定性抽样：88 导读 id 全在 chunk_exact 且=L3、211 合成 id
       全在且=L2、12 doc 分级不变（3 stat+8 miit+1 govstd，2026-10-19 govstd
       扩表批起；文件 ⊇ 常量地板，错代/半改/截断即拒）；
       五组各抽 8 id（排序后等距）复核与常量分级同纹。
    """
    try:
        try:
            if os.path.getsize(path) > _SOURCE_TIER_MAX_BYTES:
                return _FROZEN_RULES, "fallback", "oversize"
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return _FROZEN_RULES, "fallback", "missing_file"
        except json.JSONDecodeError:
            return _FROZEN_RULES, "fallback", "bad_json"
        except (OSError, ValueError):        # 含编码错/目录误指等 IO 面
            return _FROZEN_RULES, "fallback", "unreadable"
        if not isinstance(data, dict) or data.get("schema") != _SOURCE_TIER_SCHEMA:
            return _FROZEN_RULES, "fallback", "bad_schema"
        rules = data.get("rules")
        if not isinstance(rules, dict):
            return _FROZEN_RULES, "fallback", "bad_shape"
        if rules.get("precedence") != _SOURCE_TIER_PRECEDENCE:
            return _FROZEN_RULES, "fallback", "bad_precedence"
        prefix = rules.get("prefix")
        if not isinstance(prefix, list) or not prefix:
            return _FROZEN_RULES, "fallback", "bad_shape"
        for entry in prefix:
            if not (isinstance(entry, list) and len(entry) == 2
                    and isinstance(entry[0], str) and entry[0]
                    and entry[1] in _SOURCE_TIER_LEVELS):
                return _FROZEN_RULES, "fallback", "bad_shape"
        for key in ("doc_exact", "chunk_exact"):
            table = rules.get(key)
            if not isinstance(table, dict):
                return _FROZEN_RULES, "fallback", "bad_shape"
            for k, v in table.items():
                if not k or v not in _SOURCE_TIER_LEVELS:
                    return _FROZEN_RULES, "fallback", "bad_shape"
        chunk_exact = rules["chunk_exact"]
        doc_exact = rules["doc_exact"]
        # ③ 常量地板：四组全量在场且分级同纹（overlay 领先期=⊇ 不变量）
        for cid in SOURCE_TIER_DAODU_IDS:
            if chunk_exact.get(cid) != "L3":
                return _FROZEN_RULES, "fallback", "floor_violation"
        for cid in SOURCE_TIER_SYNTHETIC_IDS - SOURCE_TIER_DAODU_IDS:
            if chunk_exact.get(cid) != "L2":
                return _FROZEN_RULES, "fallback", "floor_violation"
        for d in SOURCE_TIER_MIIT_STAT_DOCS:
            if doc_exact.get(d) != "L2":
                return _FROZEN_RULES, "fallback", "floor_violation"
        for d in SOURCE_TIER_MIIT_DOCS:
            if doc_exact.get(d) != "L1":
                return _FROZEN_RULES, "fallback", "floor_violation"
        for d in SOURCE_TIER_GOVSTD_DOCS:
            if doc_exact.get(d) != "L1":
                return _FROZEN_RULES, "fallback", "floor_violation"
        # ③ 确定性抽样：五组各抽 8 id（排序后等距）复核同纹（地板全量外的廉价冗余）
        for table, group, level in (
                (chunk_exact, SOURCE_TIER_DAODU_IDS, "L3"),
                (chunk_exact, SOURCE_TIER_SYNTHETIC_IDS - SOURCE_TIER_DAODU_IDS, "L2"),
                (doc_exact, SOURCE_TIER_MIIT_STAT_DOCS, "L2"),
                (doc_exact, SOURCE_TIER_MIIT_DOCS, "L1"),
                (doc_exact, SOURCE_TIER_GOVSTD_DOCS, "L1")):
            ids = sorted(group)
            for i in range(_SOURCE_TIER_SAMPLE_N):
                if table.get(ids[i * len(ids) // _SOURCE_TIER_SAMPLE_N]) != level:
                    return _FROZEN_RULES, "fallback", "floor_violation"
        return (_SourceTierRules(chunk_exact, doc_exact,
                                 tuple((p, lv) for p, lv in prefix)),
                "file", "")
    except Exception:                        # 纯函数承诺兜底：任何意外折为 fallback 不抛出
        return _FROZEN_RULES, "fallback", "unexpected_error"


_SOURCE_TIER_WARN_ONCE = False               # warn-once 旗标（进程内告警恰一行）


def _apply_source_tier_rules(path=_SOURCE_TIER_DATA_PATH):
    """装配点：load→校验→落模块态（模块级恰调用一次，见下方赋值行）；fallback
    态打 [source-tier] 告警恰一行，文件态零输出（零噪音，判据 E2）。可注入路径
    =测试位。"""
    global _SOURCE_TIER_WARN_ONCE
    rules, mode, reason = _load_source_tier_rules(path)
    if mode != "file" and not _SOURCE_TIER_WARN_ONCE:
        print(f"[source-tier] 数据件装载失败，回退内置快照（行为不变） reason={reason}",
              flush=True)
        _SOURCE_TIER_WARN_ONCE = True
    return rules, mode


_SOURCE_TIER_RULES, _SOURCE_TIER_LOAD_MODE = _apply_source_tier_rules()


def _source_tier_of(doc_id, chunk_id):
    """doc/块 → 'L1'|'L2'|'L3'|None（装载规则：chunk_exact→doc_exact→prefix，
    与改造前常量级联恒等——DAODU⊆SYNTHETIC 且文件态导读 L3 覆写合成 L2，
    单查≡双集级联；None=不加字段）。"""
    cid = str(chunk_id or "")
    doc = str(doc_id or "")
    lv = _SOURCE_TIER_RULES.chunk_exact.get(cid)   # 块级先判（导读 L3/合成 L2，doc 撞名分域）
    if lv:
        return lv
    lv = _SOURCE_TIER_RULES.doc_exact.get(doc)     # 统计公报 L2/工信部件 L1/govstd L1（集间无交）
    if lv:
        return lv
    for prefix, level in _SOURCE_TIER_RULES.prefix:
        if doc.startswith(prefix):                 # TS /YD-T→L1、TR →L2（保序，含 F3 新件规则位）
            return level
    return None


def _annotate_source_tier(sources):
    """sources 列表逐条附加 source_tier（开关开时调用；纯增键，缺级/非 dict 跳过，
    已有键不覆写——幂等）。"""
    for s in (sources or []):
        if isinstance(s, dict) and "source_tier" not in s:
            tier = _source_tier_of(s.get("doc_id"), s.get("id"))
            if tier:
                s["source_tier"] = tier


def _usage_tok(usage, key):
    """usage dict → 安全数值（非数值/缺失 → None，trace llm 行字段用）。"""
    v = (usage or {}).get(key)
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


# ---------- 探针查询向量复用·装配钩子（合围环3 施工件3=2-A 接线，2026-10-12） ----------
# 2-A 已在 rag.rerank_probe_candidates 备好 query_vec 形参（直传跳过补嵌）；
# 本钩子把"主链已算查询向量"接到探针/闸路两处消费点——机制=装配期对本服务
# 实例做两层包装（只包 server 模块级 rag_service，评测 harness 自建实例零触碰）：
#   ① _embed 记录器：每次真嵌入后记录 (查询文本 → 向量)（单槽+锁）；
#   ② rerank_probe_candidates 注入器：调用方未显式传 query_vec 且查询文本与
#      槽内一致（strip 后比对，对齐 retrieve/探针两侧的清洗口径）→ 直传槽内
#      向量复用（每问省一次补嵌，[rag-embed] 2→1 行=工程基建一期判据 E11 已
#      登记的唯一有意差异）；不一致（mq 变体/并发竞态/换题）→ query_vec=None
#      回退自查补嵌=旧行为——宁可多嵌一次，绝不错传向量（探针读数零污染）。
# 判读锚（工程基建一期 判据-预登记.md E10/E11）：直传与自查两路同库同题输出
# 逐字段一致（同一向量入同一 _search_cos）；embed 实调每问 -1。rag.py 零改动
# （2-A 已完工定型，禁碰其已定面——接线全部落在 server 侧）。
def _wire_rag_probe_vec_reuse(svc):
    """装配钩子：原地包装 svc 的 _embed/rerank_probe_candidates（→ svc 原样
    返回）。任何失败原样返回未包装 svc=回退旧行为（fail-open，绝不因接线
    拖垮检索主链路）。"""
    try:
        orig_embed = svc._embed
        orig_probe = svc.rerank_probe_candidates
        state = {"q": None, "vec": None}
        lock = threading.Lock()

        def _embed_recorded(text):
            vec = orig_embed(text)
            with lock:
                state["q"], state["vec"] = text, vec
            return vec

        def _probe_with_vec(query, n=50, query_vec=None):
            qv = query_vec
            if qv is None:
                q = (query or "").strip()
                with lock:
                    if q and state["q"] == q:
                        qv = state["vec"]
            return orig_probe(query, n, query_vec=qv)

        svc._embed = _embed_recorded
        svc.rerank_probe_candidates = _probe_with_vec
    except Exception:
        pass
    return svc


rag_service = None
if _rag_config(CONFIG) is not None and RagService is not None:
    try:
        rag_service = RagService(log=_rag_trace_log)
        rag_service.initialize(_rag_config(CONFIG))
        # 环3 施工件3：2-A 接线（探针/闸路复用主链查询向量，见上方钩子注释）
        _wire_rag_probe_vec_reuse(rag_service)
    except Exception as e:  # 初始化失败只降级不炸服务（只报异常类型名）
        print(f"[startup] rag 初始化失败（退裸答）err={type(e).__name__}", flush=True)
        rag_service = None


# ---------- 修复窗 2026-10-26 ③：restart 预热（过程日志 238⑤；诊断报告 §五.3） ----------
# 根因②修法：换库/部署 restart 后首问 TTFB 17-20s（10-26 两实测 17.23/20.57s，
# 常温态 3-7s）。预热=装载完成后后台线程跑一次 warm-up 检索（内含一次查询
# 嵌入——暖按量 embed 端点 TLS 连接+faiss/bm25 冷页）+一次最小 LLM 预请求
# （暖订阅 UPSTREAM TLS+provider 会话——流式首 token 冷启动为主 Contributor）。
# 费面：嵌入 1 次+生成 1 次 max_tokens=8 ≈0.001 元级/restart，逐笔入执行档。
def _startup_warmup_enabled() -> bool:
    """config 顶层键 startup_warmup_enabled（**默认 true**——纯运维加速件非
    用户行为面；false=零调用零打点，形态对齐 paste_triage_enabled 键先例）。"""
    return bool(CONFIG.get("startup_warmup_enabled", True))


def _startup_warmup():
    """预热线程体（daemon，恒不抛出；pytest 环境零执行=测试面零网络零副作用）。"""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return  # 测试面直退（PYTEST_CURRENT_TEST 全程在位；manual unittest 形在别处守）
    # ① warm-up 检索：一次真实 retrieve（内嵌一次查询嵌入）。outcome 取值与
    #    [rag-search] 行同词表（hit|miss|LowScoreResult|CoverageMissResult 类名）。
    try:
        _t0 = time.monotonic()
        _r = rag_service.retrieve("切换成功率劣化怎么排查", None, None)
        _o = ("hit" if isinstance(_r, tuple)
              else "miss" if _r is None else type(_r).__name__)
        print(f"[warmup] retrieve outcome={_o} "
              f"ms={round((time.monotonic() - _t0) * 1000.0, 1)}", flush=True)
    except Exception as e:  # 预热失败绝不影响服务（fail-open，只记类型名）
        print(f"[warmup] retrieve err={type(e).__name__}", flush=True)
    # ② 最小 LLM 预请求（非流式 max_tokens=8；API_KEY 缺席直跳）
    if not API_KEY:
        return
    try:
        _t1 = time.monotonic()
        with httpx.Client(
                timeout=httpx.Timeout(connect=15, read=60, write=15, pool=15)
        ) as _c:
            _resp = _c.post(UPSTREAM, json={
                "model": CONFIG["model"],
                "messages": [{"role": "user", "content": "预热"}],
                "temperature": 0.1,
                "max_tokens": 8,
                "enable_thinking": False,  # 同生产直答口径（2026-10-07 关思考决策）
            }, headers={"Authorization": f"Bearer {API_KEY}"})
        print(f"[warmup] llm status={_resp.status_code} "
              f"ms={round((time.monotonic() - _t1) * 1000.0, 1)}", flush=True)
    except Exception as e:
        print(f"[warmup] llm err={type(e).__name__}", flush=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not API_KEY:
        print("[startup] 警告：未设置 BAILIAN_TOKEN_PLAN_API_KEY，/api/chat 将不可用", flush=True)
    print(f"[startup] model={CONFIG['model']} passcode={'on' if CONFIG.get('passcode') or CONFIG.get('passcode_hash') else 'off'}", flush=True)
    if CONFIG.get("passcode") and not CONFIG.get("passcode_hash"):
        # 兼容期警告（设计稿 §3）：明文口令仍可校验，应尽快换哈希三键
        print("[startup] 警告：口令为明文兼容模式（config 无 passcode_hash），"
              "请用仓根 hash_passcode.py 生成三键替换明文键", flush=True)
    elif CONFIG.get("passcode") and CONFIG.get("passcode_hash"):
        # C8（2026-10-07）：哈希在位时明文键只余配置失陷面（校验已走哈希），应删
        print("[startup] 警告：passcode 明文键与哈希键同时在位（校验走哈希），"
              "请删除明文 passcode 键消除配置失陷面", flush=True)
    if rag_service is None:
        print("[startup] rag=off", flush=True)
    else:
        st = rag_service.stats
        print(f"[startup] rag=on loaded={st.get('loaded')} bad_lines={st.get('bad_lines')} "
              f"dim={st.get('dim')}{' missing=1' if st.get('missing') else ''}", flush=True)
    print(f"[startup] frontend={FRONTEND_MODE}", flush=True)  # dist=Vue 构建产物 / legacy=旧 static 单页
    print(f"[startup] conversations={'on' if _conversations_enabled() else 'off'}", flush=True)  # 批次D 开关面
    print(f"[startup] followup_tail={'on' if _followup_tail_enabled() else 'off'}", flush=True)  # 批次E E2 开关面
    print(f"[startup] insight_gap_note={'on' if _insight_gap_note_enabled() else 'off'}", flush=True)  # 意图缺口批甲开关面
    print(f"[startup] anchor_format={_depth_config(CONFIG)['answer_anchor_format']}", flush=True)  # U线 M1 锚定段开关面（evidence_first|off，默认 off）
    print(f"[startup] paste_triage={'on' if _paste_triage_enabled() else 'off'}"
          f" T={_paste_triage_threshold()}", flush=True)  # U线 M5 分诊开关面（默认关）
    print(f"[startup] feedback_bad={'on' if _feedback_bad_enabled() else 'off'}",
          flush=True)  # 差评回流供弹线开关面（决策位⑥，默认开=观察面）
    print(f"[startup] rerank_log={'on' if _rerank_log_enabled() else 'off'}"
          f" cap={_rerank_log_cap_cny():g}cny", flush=True)  # 件2 log-only 探针开关面
    print(f"[startup] pii_mask={pii_mask.resolve_mode(CONFIG) if pii_mask is not None else 'off(模块缺席)'}",
          flush=True)  # F线C 输入侧止血开关面（off|log_only|mask）
    print(f"[startup] career_log={career_detect.resolve_mode(CONFIG) if career_detect is not None else 'off(模块缺席)'}",
          flush=True)  # F线 CD2 毕业季探测器开关面（on|[off]，默认 off）
    print(f"[startup] redline_filter={redline_filter.resolve_mode(CONFIG) if redline_filter is not None else 'off(模块缺席)'}",
          flush=True)  # F线Q 红线答案过滤器开关面（off|[log_only]，默认 log_only；enforce 归观察后决策）
    # 修复窗③：restart 预热线程（rag 在位且键开才发；daemon 不阻端口绑定，
    # 预热期间到达的首问不受阻——检索线程安全性与正常并发请求同面）。pytest
    # 守卫双位（派发点+线程体）：测试面零网络零副作用，防 daemon 线程延迟
    # 调度穿越测试窗口。
    _wm = (rag_service is not None and _startup_warmup_enabled()
           and not os.environ.get("PYTEST_CURRENT_TEST"))
    if _wm:
        threading.Thread(target=_startup_warmup, daemon=True,
                         name="qa-warmup").start()
    print(f"[startup] warmup={'on' if _wm else 'off'}", flush=True)
    yield
    global _store_inst
    if _store_inst is not None:
        _store_inst.close()
        _store_inst = None


app = FastAPI(title="qa-bot", lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)
# C8（2026-10-07）：关闭 /docs /redoc /openapi.json 三默认面——未鉴权暴露
# API 全结构（渗透自测 CONF-02 发现）；内网单用户无消费方，关=零成本收面


# ---------- C2：安全响应头 + CSP 两段式第一段（2026-10-07，Report-Only 起步） ----------
# 宽松档三头全站下发；CSP 先以 Content-Security-Policy-Report-Only 观察跑
# （第二段转强制=改头名 Content-Security-Policy 并重跑验收，违例收集位见
# POST /api/csp-report 端点注）。HSTS 与 secure cookie 同构：仅 config
# https_enabled=true 时下发（HTTP 直连态下发无意义且首访无效，条件口径与
# _session_cookie/_set_device_cookie 一致）。
_CSP_REPORT_ONLY = (
    "default-src 'self'; "            # 择稳妥档：未显式列出的资源类兜底同源
                                      # （'none' 过紧，worker/manifest 等漏列即误报）
    "script-src 'self'; "             # 绝不加 unsafe-inline：BotMessage.vue v-html
                                      # 渲染 markdown+KaTeX，inline script 即 XSS 面
                                      # （index.html 内联主题脚本已外提，见前端注）
    "style-src 'self' 'unsafe-inline'; "  # unsafe-inline=KaTeX/markdown 渲染产内联
                                      # style 所必需，后人勿顺手收紧（收紧即公式/
                                      # 代码高亮样式失效）
    "font-src 'self' data:; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "frame-ancestors 'none'; "
    "report-uri /api/csp-report"      # Report-Only 不空转：违例走上报端点
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """全站安全响应头（中间件面，一切路由含挂载的 /assets 与 404 均覆盖）。"""
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if CONFIG.get("https_enabled", False):
        resp.headers["Strict-Transport-Security"] = "max-age=31536000"
    resp.headers["Content-Security-Policy"] = _CSP_REPORT_ONLY
    return resp

# ---------- 批2：SQLite 持久层（设计稿 §1，标准库零依赖、WAL、2G 内存友好） ----------
# 单文件 data/qa.db；写操作经 asyncio.to_thread 进来（check_same_thread=False+
# 一把串行锁保证跨线程安全）。会话过期/限流窗口外行均为惰性清理（登录/校验
# 路径上顺手 DELETE），不做后台线程。环境变量 QABOT_DB_PATH 覆盖路径（测试注入）。
DB_PATH = os.environ.get("QABOT_DB_PATH") or os.path.join(BASE_DIR, "data", "qa.db")
SESSION_COOKIE = "qabot_session"
SESSION_MAX_AGE_S = 7 * 86400   # 会话有效期（cookie Max-Age 与库内 last_seen 过期同口径）
RATE_ROWS_CAP = 100_000         # rate_hits 行数上限（超限触发惰性清理，防无限膨胀）
RATE_CAP_CHECK_EVERY = 32       # 每隔 N 次插入做一次行数检查（个人问答机量级足够）
LOGIN_FAIL_LIMIT = 5            # 同 IP 登录失败锁定阈值（窗口内第 5 次失败后上锁）
LOGIN_FAIL_WINDOW_S = 10 * 60   # 登录失败计数滑窗（10 分钟）
# ---- 批次D：多会话+跨设备历史同步（2026-10-03，件头注"批次D"节） ----
DEVICE_COOKIE = "qabot_device"        # 设备识别长命 cookie（与登录会话解耦）
DEVICE_MAX_AGE_S = 365 * 86400        # device cookie 有效期（1 年）
CONV_MAX_AGE_S = 90 * 86400           # 会话惰性清理：90 天未动（登录路径顺手删）
MESSAGES_ROWS_CAP = 50_000            # messages 行数帽（惰性清理触发线）
CONVERSATIONS_LIMIT = 50              # 会话列表长度帽（updated_at desc）
CONV_RATE_LIMIT = 60                  # 三会话端点合计每 IP 上限（宽松防扫档）
CONV_RATE_WINDOW_S = 60               # 会话端点限速滑窗（1 分钟）
# ---- 批次E：反馈闭环 + 追问同流尾巴（2026-10-03，件头注"批次E"节） ----
FEEDBACK_RATINGS = ("up", "down")       # E1 rating 白名单
FEEDBACK_NOTE_MAX = 500                 # E1 note 截长上限（字符）
FEEDBACK_TRACE_MAX = 64                 # E1 trace_id 截长上限（真值 8 hex，防巨型塞库）
FOLLOWUP_MARKER = "\n<<<FOLLOWUP>>>"    # E2 尾巴分隔标记（含前导换行——正文与尾巴的切点）
FOLLOWUP_ITEM_MAX_CHARS = 200           # E2 单条追问建议长度上限（超出整体丢弃）
FOLLOWUP_ITEM_MAX_N = 3                 # E2 条数上限（2-3 条契约，超出整体丢弃）
# ---- 二期批次B/C：旧记录导入 + 会话重命名（2026-10-03，件头注"二期批次B/C"节） ----
IMPORT_CONV_TITLE = "本地历史（导入）"   # B：导入会话固定标题（不随首条内容生成，可辨识导入档）
IMPORT_MAX_MESSAGES = 200              # B：导入条数硬帽（请求载荷防御线，非存储线；=5×max_history_messages）
IMPORT_MSG_MAX_CHARS = 16000           # B：单条 content 上限（≈2×max_input_chars，覆盖现实分布）
IMPORT_MSG_SOURCES_MAX = 20            # B：单条 sources 条数上限
RENAME_TITLE_MAX = 100                 # C1：重命名标题截长上限（strip 后 1-100；与前端显示层防御对齐）


class _Store:
    """sessions + rate_hits + login_fails 的 SQLite 持久层（同步方法，调用侧 asyncio.to_thread 包裹）。"""

    def __init__(self, path: str):
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        self._inserts = 0
        self._login_inserts = 0
        self._conv_hits_inserts = 0
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS sessions("
                "token TEXT PRIMARY KEY, created_at REAL NOT NULL, "
                "last_seen REAL NOT NULL, msgs_json TEXT)")
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS rate_hits("
                "ip TEXT NOT NULL, ts REAL NOT NULL, PRIMARY KEY(ip, ts))")
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS login_fails("
                "ip TEXT NOT NULL, ts REAL NOT NULL, PRIMARY KEY(ip, ts))")
            # 批次D 两新表（IF NOT EXISTS=云端存量库零迁移，首启动自动补建）
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS conversations("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, device_id TEXT NOT NULL, "
                "title TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL, "
                "updated_at REAL NOT NULL, last_msg_id INTEGER)")
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS messages("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, conv_id INTEGER NOT NULL, "
                "role TEXT NOT NULL, content TEXT NOT NULL, sources_json TEXT, "
                "created_at REAL NOT NULL)")
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_conversations_device "
                "ON conversations(device_id, updated_at)")
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conv_id, id)")
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS conv_hits("
                "ip TEXT NOT NULL, ts REAL NOT NULL, PRIMARY KEY(ip, ts))")
            # 批次E 反馈表（E1，IF NOT EXISTS=存量库零迁移；note 上限由写侧截长保证）
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS feedback("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, "
                "trace_id TEXT, rating TEXT NOT NULL, note TEXT, conv_id INTEGER)")
            self._conn.commit()

    # ---- 会话（token=secrets.token_urlsafe(32)；msgs_json 只存裁剪后 clean 上下文） ----
    def create_session(self, msgs_json):
        """建会话行；登录路径顺手惰性清理过期行（last_seen < now-7d，§1）。

        批次D：同一路径顺手清 90 天未动会话+孤儿消息+messages 行数帽
        （对齐既有惰性清理风格：无后台线程，登录低频路径上顺手做）。"""
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self._lock:
            self._conn.execute(
                "INSERT INTO sessions(token, created_at, last_seen, msgs_json) "
                "VALUES(?, ?, ?, ?)", (token, now, now, msgs_json))
            self._conn.execute(
                "DELETE FROM sessions WHERE last_seen < ?", (now - SESSION_MAX_AGE_S,))
            # 批次D 惰性清理①：过期会话先删本体、消息靠孤儿清理兜（一条 SQL 同时
            # 收 90 天前会话的消息与历史孤儿）；②行数帽：超 5 万条删最旧
            self._conn.execute(
                "DELETE FROM conversations WHERE updated_at < ?",
                (now - CONV_MAX_AGE_S,))
            self._conn.execute(
                "DELETE FROM messages WHERE conv_id NOT IN (SELECT id FROM conversations)")
            if self._conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] > MESSAGES_ROWS_CAP:
                self._conn.execute(
                    "DELETE FROM messages WHERE id IN "
                    "(SELECT id FROM messages ORDER BY id DESC LIMIT -1 OFFSET ?)",
                    (MESSAGES_ROWS_CAP,))
            self._conn.commit()
        return token

    def get_session(self, token):
        """取未过期会话行（msgs_json,）；过期行顺手删除并视为无会话。"""
        cutoff = time.time() - SESSION_MAX_AGE_S
        with self._lock:
            row = self._conn.execute(
                "SELECT msgs_json FROM sessions WHERE token=? AND last_seen>=?",
                (token, cutoff)).fetchone()
            if row is None:
                self._conn.execute(
                    "DELETE FROM sessions WHERE token=? AND last_seen<?",
                    (token, cutoff))
                self._conn.commit()
        return row

    def touch_session(self, token, msgs_json):
        """cookie 会话命中后更新 last_seen 与裁剪后上下文。"""
        with self._lock:
            self._conn.execute(
                "UPDATE sessions SET last_seen=?, msgs_json=? WHERE token=?",
                (time.time(), msgs_json, token))
            self._conn.commit()

    def delete_session(self, token):
        with self._lock:
            self._conn.execute("DELETE FROM sessions WHERE token=?", (token,))
            self._conn.commit()

    def purge_expired_sessions(self):
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM sessions WHERE last_seen < ?",
                (time.time() - SESSION_MAX_AGE_S,))
            self._conn.commit()
            return cur.rowcount

    # ---- 限流（语义等价旧 deque 滑窗：计数 ts>now-win；插入后顺手删窗口外行） ----
    def rate_ok(self, ip, limit, window, now=None):
        """同 IP 滑窗计数+落库（重启不清零）；每次问答 3 条 SQL，个人量级无压力。"""
        now = time.time() if now is None else now
        cutoff = now - window
        with self._lock:
            n = self._conn.execute(
                "SELECT COUNT(*) FROM rate_hits WHERE ip=? AND ts>?",
                (ip, cutoff)).fetchone()[0]
            if n >= limit:
                return False
            # 同 ip 同 ts 微秒撞车时 REPLACE 兜底（PRIMARY KEY(ip,ts)）
            self._conn.execute(
                "INSERT OR REPLACE INTO rate_hits(ip, ts) VALUES(?, ?)", (ip, now))
            self._conn.execute(
                "DELETE FROM rate_hits WHERE ip=? AND ts<=?", (ip, cutoff))
            self._conn.commit()
        self._inserts += 1
        if self._inserts % RATE_CAP_CHECK_EVERY == 0:
            self._rate_cap_check(now, window)
        return True

    def _rate_cap_check(self, now, window):
        """容量保护：行数超 cap 先清窗口外；仍超（滑窗内攻击态）全表重置兜底。"""
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) FROM rate_hits").fetchone()[0]
            if total <= RATE_ROWS_CAP:
                return
            self._conn.execute("DELETE FROM rate_hits WHERE ts<=?", (now - window,))
            left = self._conn.execute("SELECT COUNT(*) FROM rate_hits").fetchone()[0]
            dropped = total - left
            if left > RATE_ROWS_CAP:
                self._conn.execute("DELETE FROM rate_hits")
            self._conn.commit()
        print(f"[rate] rate_hits 超 {RATE_ROWS_CAP} 行触发清理：清窗口外 {dropped} 行"
              f"{'，仍超限已全表重置（滑窗内攻击态兜底）' if left > RATE_ROWS_CAP else ''}",
              flush=True)

    # ---- 登录失败限速（批2 遗留补强：防 PBKDF2 研磨暴力+CPU 耗损面） ----
    # 独立 login_fails 小表（同 rate_hits 形态），不动存量表结构=云端库零迁移。
    # 锁定=窗口内失败数 ≥ limit；被 429 拒绝的尝试不计数不续锁（对齐 rate_ok：
    # 拒绝态不插行），最早一次失败滑出窗口即自然解锁。
    def login_lock_remaining(self, ip, limit, window, now=None):
        """同 IP 窗口内失败数 ≥ limit → 返回解锁剩余秒数（最早失败滑出窗口时刻）；
        未锁返回 0。计数落库（重启不清零），语义与 rate_ok 滑窗一致。"""
        now = time.time() if now is None else now
        with self._lock:
            n, oldest = self._conn.execute(
                "SELECT COUNT(*), MIN(ts) FROM login_fails WHERE ip=? AND ts>?",
                (ip, now - window)).fetchone()
            if n < limit:
                return 0
            return max(1, int(oldest + window - now))

    def record_login_fail(self, ip, window, now=None):
        """记一次登录失败（同 ip 同 ts 微秒撞车 REPLACE 兜底，与 rate_hits 同法）；
        顺手删该 IP 窗口外旧行；每 32 次插入全局清一次窗口外行（防表膨胀）。"""
        now = time.time() if now is None else now
        cutoff = now - window
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO login_fails(ip, ts) VALUES(?, ?)", (ip, now))
            self._conn.execute(
                "DELETE FROM login_fails WHERE ip=? AND ts<=?", (ip, cutoff))
            self._conn.commit()
        self._login_inserts += 1
        if self._login_inserts % RATE_CAP_CHECK_EVERY == 0:
            with self._lock:
                self._conn.execute("DELETE FROM login_fails WHERE ts<=?", (cutoff,))
                self._conn.commit()

    def clear_login_fails(self, ip):
        """登录成功清该 IP 失败计数（后续失败从 0 重新起数）。"""
        with self._lock:
            self._conn.execute("DELETE FROM login_fails WHERE ip=?", (ip,))
            self._conn.commit()

    # ---- 批次D：多会话历史（conversations + messages 两表；全部沿用 _lock 串行，
    # 调用侧 asyncio.to_thread 包裹。归属隔离=device_id 进 WHERE，跨设备互不可见） ----
    def create_conversation(self, device_id, title=""):
        """建会话行 → conv_id（标题=首条 user 消息前 24 字符，调用方裁好传入）。"""
        now = time.time()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO conversations(device_id, title, created_at, "
                "updated_at, last_msg_id) VALUES(?, ?, ?, ?, NULL)",
                (device_id, str(title or ""), now, now))
            self._conn.commit()
            return cur.lastrowid

    def get_conversations(self, device_id, limit=CONVERSATIONS_LIMIT):
        """本 device 会话列表（updated_at desc 限 limit）→
        [{id,title,updated_at,last_role}]；last_role=会话内最末消息角色（空会话 null）。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT c.id, c.title, c.updated_at, "
                "(SELECT m.role FROM messages m WHERE m.conv_id=c.id "
                " ORDER BY m.id DESC LIMIT 1) AS last_role "
                "FROM conversations c WHERE c.device_id=? "
                "ORDER BY c.updated_at DESC, c.id DESC LIMIT ?",
                (device_id, limit)).fetchall()
        return [{"id": r[0], "title": r[1], "updated_at": r[2],
                 "last_role": r[3]} for r in rows]

    def get_messages(self, conv_id, device_id):
        """conv 不存在或非本 device → None（端点 404 口径）；否则
        [(role, content, sources_json)] 按 id 升序（个人问答机会话量级，全量取无压力）。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT id FROM conversations WHERE id=? AND device_id=?",
                (conv_id, device_id)).fetchone()
            if row is None:
                return None
            return self._conn.execute(
                "SELECT role, content, sources_json FROM messages "
                "WHERE conv_id=? ORDER BY id", (conv_id,)).fetchall()

    def append_message(self, conv_id, role, content, sources_json=None):
        """追加消息并顺手 touch 会话（updated_at+last_msg_id 同一把锁一个事务，
        省一次锁往返——touch_conversation 的 UPDATE 已内联在此）。返回消息 id。"""
        now = time.time()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO messages(conv_id, role, content, sources_json, created_at) "
                "VALUES(?, ?, ?, ?, ?)", (conv_id, role, content, sources_json, now))
            self._conn.execute(
                "UPDATE conversations SET updated_at=?, last_msg_id=? WHERE id=?",
                (now, cur.lastrowid, conv_id))
            self._conn.commit()
            return cur.lastrowid

    def touch_conversation(self, conv_id):
        """单独 touch（无新消息的时间序维护位；append_message 已内联同款 UPDATE）。"""
        now = time.time()
        with self._lock:
            self._conn.execute(
                "UPDATE conversations SET updated_at=?, last_msg_id=COALESCE("
                "(SELECT MAX(id) FROM messages WHERE conv_id=?), last_msg_id) "
                "WHERE id=?", (now, conv_id, conv_id))
            self._conn.commit()

    def delete_last_round(self, conv_id):
        """二期批A regen 删轮：删该会话最后一条 user 消息及其后全部消息
        （其后常态恰 1 条配对 assistant；孤 user 形态=断流时 user 已落而
        assistant 未落，其后无消息——一并覆盖）。会话无 user 消息 → 0 不动。
        删后 last_msg_id 回落 COALESCE(MAX(id),NULL)、updated_at 顺手 touch。
        归属校验不在本方法（调用链 _conversation_writeback 已校验归属命中）。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT id FROM messages WHERE conv_id=? AND role='user' "
                "ORDER BY id DESC LIMIT 1", (conv_id,)).fetchone()
            if row is None:
                return 0
            cur = self._conn.execute(
                "DELETE FROM messages WHERE conv_id=? AND id>=?", (conv_id, row[0]))
            n = cur.rowcount
            now = time.time()
            self._conn.execute(
                "UPDATE conversations SET updated_at=?, last_msg_id=COALESCE("
                "(SELECT MAX(id) FROM messages WHERE conv_id=?), NULL) WHERE id=?",
                (now, conv_id, conv_id))
            self._conn.commit()
            return n

    def delete_conversation(self, conv_id, device_id):
        """删会话+其消息（归属校验在 WHERE 内；不存在/非本 device → False 不动消息）。"""
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM conversations WHERE id=? AND device_id=?",
                (conv_id, device_id))
            n = cur.rowcount
            if n:  # 只有归属命中才清消息——防误删他 device 会话的消息
                self._conn.execute("DELETE FROM messages WHERE conv_id=?", (conv_id,))
            self._conn.commit()
            return n > 0

    def rename_conversation(self, conv_id, device_id, title):
        """二期批次C C1 重命名：只 UPDATE title（不 touch updated_at/last_msg_id
        ——排序键=消息时刻，改名不是消息，不得扰动 C2 最近活跃序）。归属校验在
        WHERE 内（照 delete_conversation 形态）：不存在/非本 device → False 不动。"""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE conversations SET title=? WHERE id=? AND device_id=?",
                (title, conv_id, device_id))
            self._conn.commit()
            return cur.rowcount > 0

    # ---- 批次E：反馈落库（E1；调用侧 asyncio.to_thread 包裹，沿用 _lock 串行） ----
    def add_feedback(self, trace_id, rating, note, conv_id):
        """插一行反馈（ts=服务端时刻；trace_id/note/conv_id 均可 NULL）→ 行 id。"""
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO feedback(ts, trace_id, rating, note, conv_id) "
                "VALUES(?, ?, ?, ?, ?)",
                (time.time(), trace_id, rating, note, conv_id))
            self._conn.commit()
            return cur.lastrowid

    # ---- 批次D：三会话端点限速（独立 conv_hits 小表，同 rate_hits 形态） ----
    # 刻意不复用 rate_hits：会话端点（列表轮询等）的行若落 rate_hits 会吃掉
    # /api/chat 的 20 次/300s 滑窗预算（既有频控行为漂移），分表各管各账
    # （先例=login_fails 独立小表）。60 次/分为宽松防扫档，正常前端远够用。
    def conv_rate_ok(self, ip, limit=CONV_RATE_LIMIT, window=CONV_RATE_WINDOW_S, now=None):
        """三会话端点合计每 IP 滑窗限速（语义同 rate_ok；重启不清零）。"""
        now = time.time() if now is None else now
        cutoff = now - window
        with self._lock:
            n = self._conn.execute(
                "SELECT COUNT(*) FROM conv_hits WHERE ip=? AND ts>?",
                (ip, cutoff)).fetchone()[0]
            if n >= limit:
                return False
            self._conn.execute(
                "INSERT OR REPLACE INTO conv_hits(ip, ts) VALUES(?, ?)", (ip, now))
            self._conn.execute(
                "DELETE FROM conv_hits WHERE ip=? AND ts<=?", (ip, cutoff))
            self._conn.commit()
        self._conv_hits_inserts += 1
        if self._conv_hits_inserts % RATE_CAP_CHECK_EVERY == 0:
            with self._lock:
                self._conn.execute("DELETE FROM conv_hits WHERE ts<=?", (cutoff,))
                self._conn.commit()
        return True

    def close(self):
        with self._lock:
            self._conn.close()


_store_inst = None
_store_init_lock = threading.Lock()  # F14（评审 2026-10-15）：首建竞态互斥（双检锁）


def _store() -> _Store:
    """惰性单例（首请求才建 data/ 目录与库文件；测试用 mock.patch 换 _store_inst）。

    F14（评审 2026-10-15）：check-then-set 加双检锁，防并发首建各出 _Store
    （先建连接泄漏+进程内串行纪律被绕开）。用 threading.Lock 而非 asyncio.Lock：
    _store() 是同步函数（体内无 await 位），线程锁对事件循环线程与 to_thread
    参数求值位一概成立。"""
    global _store_inst
    if _store_inst is None:
        with _store_init_lock:
            if _store_inst is None:
                _store_inst = _Store(DB_PATH)
    return _store_inst


# ---------- 口令校验（设计稿 §3：PBKDF2 优先，兼容期明文回退） ----------
def _pbkdf2_hex(supplied: str, salt_hex: str, iterations: int) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", supplied.encode("utf-8"), bytes.fromhex(salt_hex), iterations).hex()


def _passcode_gate() -> bool:
    """是否设了访问口令（哈希或兼容明文任一在位）。"""
    return bool(CONFIG.get("passcode_hash") or CONFIG.get("passcode"))


async def _passcode_ok(supplied: str) -> bool:
    """口令校验：有 passcode_hash 三键→PBKDF2-HMAC-SHA256（hmac 常数时间比对）；
    无哈希键但见旧 passcode 明文→兼容校验（过渡期，启动日志已警告）；都没设=开放态。
    PBKDF2 单次 ~100-200ms，经 to_thread 跑防阻塞事件循环。"""
    ph = CONFIG.get("passcode_hash")
    if ph:
        salt = str(CONFIG.get("passcode_salt") or "").strip()
        try:
            iterations = int(CONFIG.get("pbkdf2_iterations") or 600_000)
        except (TypeError, ValueError):
            iterations = 600_000
        if iterations < 100_000:
            # C8（2026-10-07）：下限守门——低于 100k 的合法形态值视为无效配置
            # 回落默认（与缺键/坏值回落同构），防配置错值静默削弱研磨成本
            iterations = 600_000
        if not salt:
            return False  # 哈希键在但盐残缺：按不通过处理，不给明文回退开后门
        try:
            derived = await asyncio.to_thread(_pbkdf2_hex, supplied, salt, iterations)
        except ValueError:  # salt 非 hex 等
            return False
        return hmac.compare_digest(derived, str(ph).strip().lower())
    pc = CONFIG.get("passcode")
    if not pc:
        return True
    return supplied == pc


# ---------- 每 IP 滑动窗口限流（持久化态，重启不清零） ----------
async def _rate_ok(ip: str) -> bool:
    return await asyncio.to_thread(
        _store().rate_ok, ip,
        int(CONFIG["rate_limit_requests"]),
        float(CONFIG["rate_limit_window_seconds"]))


def _client_ip(request: Request) -> str:
    # trusted_proxy_header（config 键，默认空）=不信任任何可伪造的代理头，取
    # socket 对端（与旧口径一致）；将来 HTTPS/CDN 通道定了再填（如
    # CF-Connecting-IP），取值按逗号分隔取第一段、空值回退 socket 对端
    hdr = str(CONFIG.get("trusted_proxy_header") or "").strip()
    if hdr:
        val = request.headers.get(hdr, "")
        first = val.split(",")[0].strip() if val else ""
        if first:
            return first
    return request.client.host if request.client else "?"


def _session_cookie(token: str, resp: JSONResponse) -> JSONResponse:
    """会话 cookie 统一种法：HttpOnly+SameSite=Lax+Path=/+Max-Age 7d；
    Secure 只在 config https_enabled=true 时带（HTTP 直连态带了反而丢 cookie）。"""
    resp.set_cookie(
        SESSION_COOKIE, token, httponly=True, samesite="lax", path="/",
        max_age=SESSION_MAX_AGE_S, secure=bool(CONFIG.get("https_enabled", False)))
    return resp


# ---------- 批次D：device cookie + conversations_enabled 开关 + 会话端点鉴权 ----------
def _conversations_enabled() -> bool:
    """config 顶层键 conversations_enabled（默认 true；false=回退键：三端点 404、
    chat 双写跳过、device cookie 仍种）。坏值（非布尔真值）按 bool 语义清洗。"""
    return bool(CONFIG.get("conversations_enabled", True))


def _device_id_from(request: Request) -> str:
    """读取（或新造）设备 id：qabot_device cookie 在位即用；缺失新造
    token_urlsafe(24)。新造值须由调用方在最终响应上 _set_device_cookie/
    _ensure_device 种下（GET /、/api/chat、三会话端点为种植点）。"""
    dev = request.cookies.get(DEVICE_COOKIE, "")
    return dev if dev else secrets.token_urlsafe(24)


def _set_device_cookie(resp, dev: str):
    """device cookie 种法（口径对齐 _session_cookie：HttpOnly+SameSite=Lax+
    Path=/+Max-Age 365d；https_enabled=true 才带 Secure）。"""
    resp.set_cookie(
        DEVICE_COOKIE, dev, httponly=True, samesite="lax", path="/",
        max_age=DEVICE_MAX_AGE_S, secure=bool(CONFIG.get("https_enabled", False)))


def _ensure_device(request: Request, response, dev: str = None) -> str:
    """统一种植 helper：cookie 在位原样返回；缺失新造并种到 response 上
    （StreamingResponse/FileResponse 均为 Response 子类，set_cookie 通用）。
    dev 传入已解析值时用它种 cookie——必须与查询/落库用的是同一个 id（缺失态
    两次 _device_id_from 会各造一个不同 token，数据挂在浏览器没收到的 id 上）。"""
    dev = dev if dev is not None else _device_id_from(request)
    if DEVICE_COOKIE not in request.cookies:
        _set_device_cookie(response, dev)
    return dev


# ---------- 批次E：E2 追问同流尾巴（开关+剥除纯函数，2026-10-03） ----------
def _followup_tail_enabled() -> bool:
    """config 顶层键 followup_tail_enabled（默认 false；false=生产行为零变化：
    system 组装、流式转发、落库与既往逐字节一致）。坏值按 bool 语义清洗。"""
    return bool(CONFIG.get("followup_tail_enabled", False))


# ---------- 意图缺口批甲：通识标注开关+词表命中（设计稿 v3-甲，2026-10-09） ----------
def _insight_gap_note_enabled() -> bool:
    """config 顶层键 insight_gap_note_enabled（默认 false；false=生产行为零
    变化：SSE 事件流与既往逐字节一致）。坏值按 bool 语义清洗。"""
    return bool(CONFIG.get("insight_gap_note_enabled", False))

# ---------- G 徽标（备发包-20261012，默认关）：sources 附 source_tier 纯增字段 ----------
def _source_tier_enabled() -> bool:
    """config 顶层键 source_tier_enabled（默认 false；false=SSE sources 事件、
    会话 sources_json 落库与恢复面与既往逐字节一致）。坏值按 bool 语义清洗。"""
    return bool(CONFIG.get("source_tier_enabled", False))



def _method_query_hit(clean) -> bool:
    """方法论问法信号命中：对当前轮用户题面（clean 末条 content）做词表子串
    匹配——用裸题面而非 build_retrieval_query 拼接产物，历史文本中的信号词
    不得触发本轮标注。clean 为消息列表（/api/chat 清洗段产出），形态异常
    一律 False（纯函数、绝不抛出）。"""
    try:
        last = clean[-1]
        q = last.get("content") if isinstance(last, dict) else None
    except Exception:
        return False
    return isinstance(q, str) and any(s in q for s in METHOD_QUERY_SIGNALS)


def _ydt_evidence_in_window(rag_sources):
    """丙/ydt 域证据在席判定（2026-10-12 标注同现修复）：sources 任一条
    doc_id（strip 后）以 "YD/T" 起头 → True。判定面=doc_id 前缀单源——
    services 面拿到的 sources 系 build_evidence 产物（只透传 id/doc_id/
    version/locator/score/quote，无 source_domain），前缀口径与 G 徽标
    _FROZEN_PREFIX 的 ("YD/T", "L1") 同面；ydt 切块件硬断言全量
    source_domain=="ydt"（域↔前缀一一对应，无跨域撞名）。形态异常一律
    False（纯函数、绝不抛出）。"""
    try:
        for s in rag_sources or []:
            if (isinstance(s, dict)
                    and str(s.get("doc_id") or "").strip().startswith("YD/T")):
                return True
    except Exception:
        pass
    return False


def _followup_holdback(buf: str) -> int:
    """buf 尾部与标记前缀的最大重叠长度（纯函数）——标记可能跨 delta 被拆成
    两半（如 "\\n<<<FOLL" + "OWUP>>>"），缓冲尾部凡是标记前缀的后缀都可能是
    未来标记的开头，必须扣住不下发；空缓冲/无重叠 → 0。"""
    for k in range(min(len(buf), len(FOLLOWUP_MARKER) - 1), 0, -1):
        if buf.endswith(FOLLOWUP_MARKER[:k]):
            return k
    return 0


def _parse_followup_items(raw: str):
    """截留尾巴文本 → 追问建议条目（纯函数）。

    "- " 开头行、剥前缀与首尾空白；非 "-" 行（模型话痨/空行）不构成条目忽略；
    任一条目剥后为空或 >200 字符、解析后条数 <1 或 >3 → None（整体丢弃不发，
    保守契约宁缺毋滥——畸形尾巴绝不以次充好下发前端）。"""
    items = []
    for ln in str(raw or "").splitlines():
        ln = ln.strip()
        if not ln.startswith("-"):
            continue
        item = ln[1:].strip()
        if not item or len(item) > FOLLOWUP_ITEM_MAX_CHARS:
            return None
        items.append(item)
    return items if 1 <= len(items) <= FOLLOWUP_ITEM_MAX_N else None


# ---------- rerank log-only 影子探针（部署窗件2，2026-10-12） ----------
# 姿态（ADR-0011 2026-10-12 终条，采定口径）：rerank 作**真空/域外拒答信号**
# 标定面——单独标定阈值（本探针只采数不打闸）、绝不沿用余弦阈值、陷阱判别面
# 归余弦闸+裁判（职责边界不动）。设计草案=建库/work/拒答信号标定-20261012/
# 报告-20261012.md §四（影子试点判据预登记草案，判读线数值留白归用户）。
#
# 铁律三条（本段存在的前提，违反任何一条即回滚本段）：
# ① 主链路行为零变化：探针在检索完成后由**异步 fire-and-forget 守护线程**
#   执行（检索候选经 rag.RagService.rerank_probe_candidates 只读旁路获取），
#   请求路径只付一次 Thread.start()（µs 级）；绝不改检索结果、绝不碰闸分
#   载体（gate_cosine/score_threshold 零接触）、绝不改答案 SSE 流/事件序/
#   落库面——探针开与关的 SSE 输出逐字节一致（单测铁断言）。
# ② 超时 3s、失败/超时只记跳过、不重试、不阻塞：探线程内任何异常只打一行
#   [rerank_probe] err=/skip= journal，绝不向主链路传播。
# ③ key 绝不入任何日志/输出/台账：端点解析复用 rag.resolve_embed_endpoint
#   既有面（环境变量 BAILIAN_EMBED_BASE_URL/BAILIAN_EMBED_API_KEY 优先，
#   否则 ~/.bailian/config.json），err 行只记异常类名。
#
# 采数面：qwen3.7-text-rerank@top-50（标定报告读数主格=d50、新代引擎数据占优
# +陷阱面零触碰）；journal 一行 [rerank_probe]（查询哈希+时间+三阈值过线计数
# 0.75/0.85/0.95+最高分+token 数+金靶无关 gold=na——线上无金靶标注，最高分=
# 池 max 口径）；台账入账 stage=rerank_log（建库/logs/生成用量.jsonl 同款追加，
# 0.5 元/百万 token 口径，与既有 rerank 判死/探底实验行同制）。
# 评测面零扰动：探针只挂 server /api/chat 检索完成处——离线评测 harness 直连
# rag 模块（retrieve()/scripts），不经本挂点=零探针；rag.py 侧 rerank_probe_
# candidates 为新增只读方法，retrieve() 主链路一行未动。
RERANK_LOG_MODEL = "qwen3.7-text-rerank"
RERANK_LOG_POOL_DEPTH = 50          # 候选池深（标定报告 d50 读数主格）
RERANK_LOG_THRESHOLDS = (0.75, 0.85, 0.95)   # 宽松/均衡/保守三候选档
RERANK_LOG_PRICE_CNY_PER_MTOK = 0.5          # rerank 台账同价口径
RERANK_LOG_TIMEOUT_S = 3.0                   # 探针硬超时（超时=记跳过不重试）
RERANK_LOG_RERANK_PATH = "/compatible-api/v1/reranks"
RERANK_LOG_LEDGER = os.path.join(BASE_DIR, "建库", "logs", "生成用量.jsonl")
_rerank_log_lock = threading.Lock()          # 台账读/写串行化（探线程并发安全）
_rerank_log_cap_warned = False               # 月顶 warn-once 旗标（进程内）
_rerank_log_endpoint = {"url": None, "key": None}   # 端点解析缓存（成功才缓存）


def _rerank_log_enabled() -> bool:
    """config 顶层键 rerank_log_enabled（**默认 true**——log-only 试验目的就是
    采数；false=零探针零日志零台账，/api/chat 行为与既往逐字节一致）。坏值按
    bool 语义清洗。"""
    return bool(CONFIG.get("rerank_log_enabled", True))


def _rerank_log_cap_cny() -> float:
    """config 顶层键 rerank_log_monthly_cap_cny（默认 5.0 元**软顶**：当月
    stage=rerank_log 台账累计 ≥cap → 自动跳过探针+warn 一次；软顶=跳过采数
    不影响主链路）。坏值/NaN/≤0 一律回默认（越界回默认口径）。"""
    try:
        v = float(CONFIG.get("rerank_log_monthly_cap_cny", 5.0))
    except (TypeError, ValueError):
        return 5.0
    if v != v or v <= 0:
        return 5.0
    return v


def _rerank_month_spend(path=None):
    """台账当月 stage=rerank_log 切片累计 est_cny（软顶判别用）。

    - ts 前缀 YYYY-MM 当月判别（台账行制=ts/stage/est_cny）；ts 缺失/坏形
      的 rerank_log 行**保守计入当月**（费用安全向）；
    - 台账文件不存在 → 0.0（合法初态：首笔 append 自建目录）；
    - 其他读失败 → None（不可判读，调用方按保守跳过处理）。
    """
    p = path or RERANK_LOG_LEDGER
    month = time.strftime("%Y-%m")
    total = 0.0
    try:
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(o, dict) or o.get("stage") not in (
                        "rerank_log", "rerank_gate"):
                    continue
                ts = str(o.get("ts") or "")
                if ts[:7] != month and ts[:2] == "20":
                    continue  # 带合法年份锚的他月行：正常归月排除
                # ts 无当月锚（缺失/坏形）→ 保守计入当月（费用安全向）
                try:
                    total += float(o.get("est_cny") or 0.0)
                except (TypeError, ValueError):
                    continue
        return total
    except FileNotFoundError:
        return 0.0
    except OSError:
        return None


def _rerank_log_resolve_endpoint():
    """rerank 端点解析（复用 rag.resolve_embed_endpoint 鉴权面）→ (url, key)
    或 None（解析失败=探针跳过；key 绝不落日志）。进程内成功态缓存一次。"""
    if _rerank_log_endpoint["url"] and _rerank_log_endpoint["key"]:
        return _rerank_log_endpoint["url"], _rerank_log_endpoint["key"]
    if _rag_resolve_embed_endpoint is None:
        return None
    try:
        base, key = _rag_resolve_embed_endpoint()
    except Exception:
        return None
    if not base or not key:
        return None
    url = base.rstrip("/") + RERANK_LOG_RERANK_PATH
    _rerank_log_endpoint["url"], _rerank_log_endpoint["key"] = url, key
    return url, key


def _rerank_api_call(query, docs, timeout=RERANK_LOG_TIMEOUT_S):
    """qwen3.7-text-rerank 打分（httpx 同步单发；零重试铁律）→ (scores, tokens)。

    - 单批 ≤50 文（E 判死实验 BATCH_DOCS=50 上限内，50 候选=单次调用零拆批）；
    - 非 200/JSON 畸形/无 results → 抛异常（调用方只记异常类名）；文档文本
      超长防御截 6000 字符（现库块 ~512 token 量级，常态零触发——截断口径
      不改变与标定池的可比性）；
    - 返回 scores 按 documents 下标对位（缺失项不计分）。
    """
    endpoint = _rerank_log_resolve_endpoint()
    if endpoint is None:
        raise RuntimeError("rerank endpoint unresolved")
    docs = [str(d)[:6000] for d in docs]
    body = {"model": RERANK_LOG_MODEL, "query": query, "documents": docs}
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(endpoint[0], json=body,
                           headers={"Authorization": "Bearer " + endpoint[1]})
        resp.raise_for_status()
        data = resp.json()
    results = data.get("results") or []
    scores = [None] * len(docs)
    for r in results:
        i = r.get("index")
        v = r.get("relevance_score")
        if isinstance(i, int) and 0 <= i < len(docs) \
                and isinstance(v, (int, float)) and not isinstance(v, bool):
            scores[i] = float(v)
    tokens = int((data.get("usage") or {}).get("total_tokens") or 0)
    return scores, tokens


def _rerank_ledger_append(tokens, n_docs, est_cny, path=None, stage="rerank_log",
                          note="线上log-only影子探针（三阈值判读采数，ADR-0011 姿态）"):
    """台账追加一行（stage 默认 rerank_log；行为级拦截调用方传 stage=rerank_gate，
    note 换拦截口径——月顶软顶两段共享同账，建库/logs/生成用量.jsonl 行制同款追加；
    建目录自愈、写失败只返 False 绝不抛——探针侧兜底纪律）。"""
    p = path or RERANK_LOG_LEDGER
    line = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "stage": stage,
            "model": RERANK_LOG_MODEL, "batch": "d50", "n": int(n_docs),
            "input_tokens": int(tokens), "retries": 0,
            "est_cny": round(est_cny, 6),
            "note": note}
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with _rerank_log_lock:
            with open(p, "a", encoding="utf-8") as f:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
        return True
    except OSError:
        return False


def _rerank_probe_tag(query, n=12) -> str:
    """查询哈希（sha256 前 n hex，默认 12=既有 [rerank_probe]/[rerank_gate]
    行口径；环3 q 行取 16）——journal 行不落题面原文（隐私纪律，
    对齐 [chat] q= 摘要面更收紧：探针行零题面）。"""
    return hashlib.sha256((query or "").encode("utf-8")).hexdigest()[:n]


def _rerank_probe_q_line(query, pool_max):
    """[rerank-probe-q] 逐题扩维行（环3 施工件2，2026-10-12；纯增——只在探针
    成功打分轮由 worker 落一行，skip/err 轮零行；探针关（rerank_log_enabled
    =false）= worker 不跑=零行）。分面闸影子读数面：qhash=sha256 前 16 hex、
    len=查询长度（build_retrieval_query 产物体原样计数，与复放 roster len 口径
    一致，不 strip）、pool_max=池 max、face=vac|prac（与分面闸同源路由）、
    t_v/hit_v 与 t_p/hit_p=两面阈值与过线旗（pool_max ≥ t 记 1——影子期两面
    读数并行采集，环4 拨键复核面）。零题面原文；不属台账（费额在
    [rerank_probe] 主行）。"""
    qh = _rerank_probe_tag(query, 16)
    ln = len(query or "")
    face = _rerank_refusal_face(query)
    tv = _rerank_refusal_threshold_vacuum()
    tp = _rerank_refusal_threshold_practical()
    print(f"[rerank-probe-q] qhash={qh} len={ln} pool_max={pool_max:.4f}"
          f" face={face} t_v={tv:g} hit_v={1 if pool_max >= tv else 0}"
          f" t_p={tp:g} hit_p={1 if pool_max >= tp else 0}", flush=True)


def _rerank_log_probe_worker(rag_svc, query, rag_state, trace_id,
                             an_sources=None):
    """探线程主体（fire-and-forget；任何失败只打 [rerank_probe] journal 行，
    绝不抛出向主链路传播——铁律②③的落点）。an_sources=本次请求 retrieve 的
    融合序 sources（hit 轮传入；U5 形态B 判官证据面=作答同源，主链路零成本
    传引用）。"""
    global _rerank_log_cap_warned
    qh = _rerank_probe_tag(query)
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    base = f"[rerank_probe] ts={ts} q={qh} st={rag_state} trace={trace_id}"
    try:
        try:
            cands = rag_svc.rerank_probe_candidates(query, RERANK_LOG_POOL_DEPTH)
        except Exception as e:  # 候选面失败（补嵌超时等）：记跳过
            print(f"{base} err={type(e).__name__} skip=1", flush=True)
            return
        if not cands:
            print(f"{base} skip=empty_pool", flush=True)
            return
        spend = _rerank_month_spend()
        if spend is None:
            print(f"{base} skip=ledger_unreadable", flush=True)
            return
        cap = _rerank_log_cap_cny()
        if spend >= cap:
            if not _rerank_log_cap_warned:
                _rerank_log_cap_warned = True
                print(f"{base} skip=cap cum={spend:.4f} cap={cap:.2f} warn=1"
                      "（当月 rerank_log 台账超软顶，跳过探针——本进程只 warn 一次）",
                      flush=True)
            return
        if _rerank_log_resolve_endpoint() is None:
            print(f"{base} skip=no_endpoint", flush=True)
            return
        scores, tokens = _rerank_api_call(query, [c["text"] for c in cands])
        vals = [v for v in scores if v is not None]
        if not vals:
            print(f"{base} skip=no_scores", flush=True)
            return
        mx = max(vals)
        cnt = {t: sum(1 for v in vals if v >= t) for t in RERANK_LOG_THRESHOLDS}
        est = tokens / 1e6 * RERANK_LOG_PRICE_CNY_PER_MTOK
        # 金靶无关（gold=na）：线上无金靶标注，最高分=池 max 口径（离线标定的
        # 金靶/产线两口径区分留给影子期抽样人工标注，探针行不掺入）
        print(f"{base} n={len(cands)} max={mx:.4f}"
              f" c075={cnt[0.75]} c085={cnt[0.85]} c095={cnt[0.95]}"
              f" tok={tokens} cny={est:.6f} gold=na", flush=True)
        _rerank_probe_q_line(query, mx)   # 环3 施工件2：分面影子读数逐题行
        # U线（U2 影子 2026-10-15 / U5 形态B 消费面同窗实装）：answerability
        # 观测行——band 命中（vac ∧ [lo,hi) ∧ hit 态）才落行；enabled=true 时
        # 同点位判官调用+缓存写入（探线程顺风车，计划 §1.3 挂点①/§2.5 形态B；
        # skip/err 轮到不了此处=零行零调用）
        _answerability_shadow_line(query, rag_state, mx, an_sources, rag_svc)
        if not _rerank_ledger_append(tokens, len(cands), est):
            print(f"{base} err=LedgerWriteFail skip=1", flush=True)
    except Exception as e:  # 铁律②：只记跳过（异常类名，绝不带 key/URL）
        print(f"{base} err={type(e).__name__} skip=1", flush=True)


def _rerank_log_fire(rag_svc, query, rag_state, trace_id, an_sources=None):
    """检索完成后的探针入口 → Thread | None（不 fire=None）。

    挂点外置在 server /api/chat（离线评测 harness 直连 rag 模块=零探针的
    论证落点）；守护线程 fire-and-forget，请求路径绝不 join/await（铁律①）。
    rag_state 只认 hit/low_score/coverage_miss（miss=检索失败/空库无候选面，
    探针无数据意义不 fire）。an_sources=hit 轮的融合序 sources（U5 判官证据
    面，传引用零主链路成本）。"""
    if rag_svc is None or not _rerank_log_enabled() \
            or rag_state not in ("hit", "low_score", "coverage_miss") \
            or not (query or "").strip():
        return None
    t = threading.Thread(target=_rerank_log_probe_worker,
                         args=(rag_svc, query, rag_state, trace_id,
                               an_sources),
                         daemon=True, name="rerank-log-probe")
    t.start()
    return t


# ================= rerank 行为级拒答拦截（0.75 档决策 2026-10-12） =================
# 评审件=建库/work/百问探针-20261012/评审-阈值档-20261012.md §五（预案照案施工）。
# 与 log-only 探针**双轨分立**：双键独立（rerank_refusal_enabled 默认 false=
# 行为与既往逐字节一致；rerank_refusal_threshold 默认 0.75）、journal 行分立
# （[rerank_gate] vs [rerank_probe]）、台账 stage 分立（rerank_gate vs rerank_log）、
# 月顶软顶两段共账（超顶=拦截退化不拦只放行+warn，探针采数同时跳过）。
# 铁律：同步调用在 hit 路径检索完成后（预算 3s 超时）；任何失败/超时/超顶一律
# **fail-open 放行**（拦截面故障绝不挡答案）；绝不碰闸分载体（余弦闸 0.40 先行，
# rerank 为第二信号——E/百问实证余弦闸对真无支持零分辨力）；拒答分支=不注入证据、
# 不下发 sources、先发 off_topic 同构事件再照常裸答流式（前端零改动）。
_rerank_gate_cap_warned = False


def _rerank_refusal_enabled() -> bool:
    """config 顶层键 rerank_refusal_enabled（**默认 false**——拨开属部署窗动作；
    false=零拦截零 journal，/api/chat 行为与既往逐字节一致）。"""
    return bool(CONFIG.get("rerank_refusal_enabled", False))


def _rerank_refusal_threshold() -> float:
    """config 顶层键 rerank_refusal_threshold（决策 0.75 档；坏值/NaN/出 (0,1)
    一律回默认——越界回默认口径同 rerank_log 族）。环3 分面闸落位后本键=真空
    面阈值的缺省回退源（rerank_refusal_threshold_vacuum 缺键时消费本值——既有
    部署只拨旧键时真空面语义连续；实操面阈值独立成键不回退本值）。"""
    try:
        v = float(CONFIG.get("rerank_refusal_threshold", 0.75))
    except (TypeError, ValueError):
        return 0.75
    if v != v or not (0.0 < v < 1.0):
        return 0.75
    return v


# ---- 环3 分面闸三键（合围-E线判别器 环3 施工，2026-10-12；推荐参数=复放-L2L3
# 全过组合：cut=113 字（58 题长度联合分布 p50）、t_真空=0.75（0.7413 与 0.75
# 两点读数同，取 0.75）、t_实操=0.4923（C28 第 2 低 pool_max 边界锚）——**贴线
# slack=0 已登记**，线上键值以环4 影子读数复核后才可拨（判读线档 §六；施工
# 完成≠拨键，拨键归用户）。路由规则=判据档 §四 s_d ≥ c → 真空面，即
# len(查询) ≤ cut → 真空面阈值，否则实操面阈值（查询=build_retrieval_query
# 产物体，与复放 roster len 口径一致；2026-10-12 数据面核实 58 题无 len==113
# 题，与复放脚本严格大于语义在读数面等价）。----
def _rerank_refusal_threshold_vacuum() -> float:
    """config 顶层键 rerank_refusal_threshold_vacuum（真空面/短题面阈值，默认
    0.75；缺键时回退既有单键 rerank_refusal_threshold 的清洗值）；坏值/NaN/
    出 (0,1) 回默认 0.75（越界回默认口径同 rerank_log 族）。"""
    if "rerank_refusal_threshold_vacuum" not in CONFIG:
        return _rerank_refusal_threshold()
    try:
        v = float(CONFIG.get("rerank_refusal_threshold_vacuum"))
    except (TypeError, ValueError):
        return 0.75
    if v != v or not (0.0 < v < 1.0):
        return 0.75
    return v


def _rerank_refusal_threshold_practical() -> float:
    """config 顶层键 rerank_refusal_threshold_practical（实操面/长题面阈值，
    默认 0.4923=复放-L2L3 全过组合读数位；不回退旧单键——旧键语义归真空面）；
    坏值/NaN/出 (0,1) 回默认。"""
    try:
        v = float(CONFIG.get("rerank_refusal_threshold_practical", 0.4923))
    except (TypeError, ValueError):
        return 0.4923
    if v != v or not (0.0 < v < 1.0):
        return 0.4923
    return v


def _rerank_refusal_facet_cut() -> float:
    """config 顶层键 rerank_refusal_facet_cut（分面切点，默认 113 字=58 题
    长度联合分布 p50；数值非 bool 且 ≥0 才受，坏值/NaN/负数回默认）。"""
    raw = CONFIG.get("rerank_refusal_facet_cut", 113)
    if isinstance(raw, bool):
        return 113.0
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return 113.0
    if v != v or v < 0:
        return 113.0
    return v


def _rerank_refusal_face(query) -> str:
    """面别路由（②a 题面长度判别器，判据档 §四：s_d ≥ c → 真空面）：
    len(查询) ≤ cut → 真空面 "vac"，否则实操面 "prac"。查询长度不 strip
    （build_retrieval_query 产物体原样计数=复放 roster len 口径）。"""
    return "vac" if len(query or "") <= _rerank_refusal_facet_cut() else "prac"


def _rerank_refusal_threshold_for(query) -> float:
    """查询 → 适用面阈值（分面闸施工件1：vac 面=_rerank_refusal_threshold_
    vacuum()，prac 面=_rerank_refusal_threshold_practical()）。"""
    if _rerank_refusal_face(query) == "vac":
        return _rerank_refusal_threshold_vacuum()
    return _rerank_refusal_threshold_practical()


def _rerank_gate_check(rag_svc, query):
    """同步拦截判定（hit 路径检索完成后调用）→ (refused, pool_max, err)。

    refused=False+err 非 None = fail-open 放行（cap/empty_pool/no_endpoint/
    no_scores/异常类名）；refused=False+err=None+pool_max 非 None = 阈值上方
    正常放行。台账 stage=rerank_gate（成功打分才入账）。"""
    global _rerank_gate_cap_warned
    try:
        spend = _rerank_month_spend()
        if spend is None:
            return False, None, "ledger_unreadable"
        cap = _rerank_log_cap_cny()
        if spend >= cap:
            if not _rerank_gate_cap_warned:
                _rerank_gate_cap_warned = True
                print(f"[rerank_gate] skip=cap cum={spend:.4f} cap={cap:.2f}"
                      " warn=1（当月 rerank 两段台账超软顶，拦截退化不拦——"
                      "本进程只 warn 一次）", flush=True)
            return False, None, "cap"
        cands = rag_svc.rerank_probe_candidates(query, RERANK_LOG_POOL_DEPTH)
        if not cands:
            return False, None, "empty_pool"
        if _rerank_log_resolve_endpoint() is None:
            return False, None, "no_endpoint"
        scores, tokens = _rerank_api_call(query, [c["text"] for c in cands])
        vals = [v for v in scores if v is not None]
        if not vals:
            return False, None, "no_scores"
        est = tokens / 1e6 * RERANK_LOG_PRICE_CNY_PER_MTOK
        _rerank_ledger_append(
            tokens, len(cands), est, stage="rerank_gate",
            note="行为级拒答拦截0.75档（百问探针评审，ADR-0011 拒答信号姿态）")
        pool_max = max(vals)
        # 环3 施工件1：分面阈值（len(查询) ≤ cut → 真空面阈值，否则实操面）
        thr = _rerank_refusal_threshold_for(query)
        return pool_max < thr, pool_max, None
    except Exception as e:  # fail-open：拦截面故障绝不挡答案（只记异常类名）
        return False, None, type(e).__name__


def _rerank_gate_trace(query, trace_id, refused, pool_max, err):
    """[rerank_gate] journal 行（与探针 [rerank_probe] 双轨分立对拍；零题面，
    q=sha256 前 12 hex 同探针纪律）。"""
    qh = _rerank_probe_tag(query)
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    decision = "skip" if err else ("refuse" if refused else "pass")
    print(f"[rerank_gate] ts={ts} q={qh} trace={trace_id} decision={decision}"
          + (f" err={err}" if err else "")
          + (f" max={pool_max:.4f}" if pool_max is not None else "")
          # 环3 分面闸：thr=当题适用面阈值（vac=0.75 档 / prac=0.4923 档）
          + ("" if err else f" thr={_rerank_refusal_threshold_for(query):g}"),
          flush=True)


# ================= U线 answerability（U2 影子 + U5 形态B 消费面，2026-10-15） =================
# 计划=运营/U线-可答性判别引擎-执行计划-20261015.md（§1.3 挂点选型=①探线程顺风车
# ——候选② rag.py weak_gate 同位不采；§1.2 v1 作用面=vac（len≤113）；§2.2 band=
# [band_lo, band_hi) 含下不含上、vac 面专属；§2.5 形态B=异步预判+缓存消费）。
# **U5 形态B 实装（2026-10-15，过程日志 90⑥ 更正登记的补件）**：判官调用器（探线程
# 内，enabled 时 band 命中→v2 冻结块拼装→qwen3.8-flash→首词协议→LRU 缓存）+
# /api/chat 主路径缓存消费（回答前 qhash16 查缓存，µs 级纯 dict）+观测行 verdict
# 扩展键。判据正本=运营/U线-U3判据件v2-20261015.md（§1.4 冻结块=下方常量逐字，
# 测试件从判据件代码栅栏确定性提取并断言 11,573 字符逐字节一致；§1.2 证据构造=
# 本次请求 retrieve 融合序 top-5、content 换行→空格前 500 字切片；§1.5 调用参数
# =enable_thinking=False/temperature=0/top_k=1/max_tokens=32；§二=首词协议+同参
# 重试 1 次→null+连续 3 次失败熔断）。
# 铁律沿 rerank 探针三条（本文件 1813-1829 段）：①主链路零等待——判官由探线程
# （_rerank_log_probe_worker 成功打分轮）异步调用，主路径只做缓存 dict 查询；②
# 零题面原文进 journal——观测行纯 KV+qhash16（判官消息体不落任何日志）；③
# answerability_judge_enabled 默认 false=零行为差（false 时主路径缓存查询与判官
# 调用全被闸死，/api/chat 输出与既往逐字节一致，单测铁断言；回滚=单键
# enabled=false+重启即回 U2 观测层形态，U5 部署窗执行单 §三）。
# 三态合规映射（计划 §1.4）：可答→现状照旧；不可答/不确定→既有 low_score 兜底
# 形态（不注入证据/不下发 sources/off_topic 同构事件/裸答流式——状态机零新增、
# 复用 low_score 态字）；判官失败/超时/熔断=fail-open 放行（判官面故障绝不挡
# 答案）+不写缓存（novel 首问缺省放行=形态B 已知产品语义，计划 §2.5）。
# 键族=server 顶层平键（对齐 rerank_refusal_* 先例；非 rag 段嵌套）；
# judge_model/timeout_s/cache_size 三键消费于本段（cache 先例=建库/work/合围-
# E线判别器-20261012/施工-rerank_facet_llm-草稿-20261015.py）。
# 与既有闸关系（计划 §1.5）：只在 rag_state=hit 触发（low_score/coverage_miss 已
# 走兜底不触发，观测行同面）；E 线 rerank_refused 键独立互不消费；rag.py 零触碰
# （判官证据块按 chunk id 从已装载库只读解析，见 _answerability_recs_by_id）。


def _answerability_params() -> dict:
    """U线 answerability 键族单一尺（坏值/越界回默认，口径同 rerank_log 族
    _rerank_log_cap_cny 与 rerank_refusal 族 _rerank_refusal_threshold：
    float 键坏值/NaN/出界回默认；timeout 键越界 (0,30] 回默认贴批A
    _depth_config；cache 键非正 int（bool 剔除）回默认）。

    - answerability_judge_enabled（默认 False——拨开属 U4 评审动作，禁自动生效）
    - answerability_band_lo / _hi（默认 0.75 / 0.95，band=[lo,hi) 含下不含上；
      lo ≥ hi=band 空集非法 → 两界双双回默认）
    - answerability_judge_model（默认 qwen3.8-flash；非 str/空白回默认）
    - answerability_timeout_s（默认 1.5，U3/U5 消费）
    - answerability_cache_size（默认 8192，U3/U5 消费）
    """
    def _band_edge(key, default):
        try:
            v = float(CONFIG.get(key, default))
        except (TypeError, ValueError):
            return default
        if v != v or not (0.0 < v < 1.0):
            return default
        return v

    lo = _band_edge("answerability_band_lo", 0.75)
    hi = _band_edge("answerability_band_hi", 0.95)
    if lo >= hi:
        lo, hi = 0.75, 0.95
    try:
        timeout = float(CONFIG.get("answerability_timeout_s", 1.5))
    except (TypeError, ValueError):
        timeout = 1.5
    if timeout != timeout or not (0.0 < timeout <= 30.0):
        timeout = 1.5
    cache = CONFIG.get("answerability_cache_size", 8192)
    if not isinstance(cache, int) or isinstance(cache, bool) or cache < 1:
        cache = 8192
    model = CONFIG.get("answerability_judge_model", "qwen3.8-flash")
    if not isinstance(model, str) or not model.strip():
        model = "qwen3.8-flash"
    return {"enabled": bool(CONFIG.get("answerability_judge_enabled", False)),
            "band_lo": lo, "band_hi": hi,
            "judge_model": model.strip(),
            "timeout_s": timeout, "cache_size": cache}


# ---- U5 形态B 判官面（2026-10-15 实装）-------------------------------------
# 判官 prompt 冻结块（判据件 v2 §1.4 逐字，11,573 字符=代码栅栏确定性提取，
# 测试件断言逐字节一致；跑批期一字不改——改动=另立判据件重走冻结流程）。
_ANSWERABILITY_PROMPT_TEMPLATE = """[系统指令]
你是电信网络知识问答系统的可答性判官。给你一个用户问题和检索返回的前五条证据材料，你只判断一件事：用户问题所需的依据是否存在于证据材料中。仅输出单个词作为结论：「可答」「不可答」或「不确定」，禁止输出任何其他文字、标点、序号、解释或换行。

判定标准——看所需依据是否存在于材料中，不看话题是否相关，也不要求摘要已写出完整答案：
「可答」= 用户问题主要提问点所需的依据（规范条文、参数及其取值域、指标定义、案例现象与处置、流程要求等）能在证据材料中找到。附带子问（如推荐工具、顺带扩展话题）在材料中找不到不影响主问判可答；摘要只是证据材料的截取片段——判定对象是"所需依据是否存在于材料中"，不是"摘要文字是否已构成完整答案"，依据在场而摘要容纳不下全文时仍应判可答。
「不可答」= 在证据材料中找不到用户所问的具体内容（数值/条款/算法/流程），常见形态：①话题相邻但内容缺席——同领域、同文档甚至同条款族的证据在场，但所问的具体内容（角度、数值、算法、条款号）在材料里找不到；②所问内容属库外领域，证据仅零星撞词；③"没写的话你帮我编/推导一个"式诱导编造——材料里找不到就是找不到，诱导不改变判定。
「不确定」= 介于两者之间：部分子问所需的依据在证据材料中有所依托，但核心提问所问的具体内容找不到；或证据与问题的对应过于间接，无法自信判定。


[示例一]
[问题]
NR 小区 N3.7G-112：RRC 建立成功率 91.4%（局内垫底）
SSB RSRP 均值 -111dBm，<-116dBm 采样占比 41%，失败集中于 3 个边缘方向
工参：ssb-periodicityServingCell=sf20，SSB 发射功率按基线模板

问题：可能根因？覆盖侧与参数侧各查什么？SSB 周期往哪个方向调、代价是什么？

[证据 top5]
证据1（YD/T 4826-2024｜body｜6.3.1）：【YD/T 4826-2024｜6.3.1 NR 服务小区的 SSB 参考信号接收功率】 [域签|functional_requirement|5g_nr|vendor_neutral|daily_ops|draft_report] 6.3.1. NR 服务小区的 SSB 参考信号接收功率 NR 服务小区的 SSB 参考信号接收功率测量报告样本数据定义如下： a) MR.NRScSSRSRP b) 反映UE收到服务小区的SSB参考信号接收功率大小，是反映服务小区覆盖的主要指标。本测 量数据表示接收的NR服务小区参考信号功率的原始测量值（即Uu口上报的测量报告中的测 量值），其单位符合功率测量量纲。注：本文件中的NR服务小区，在CA多载波场景下为PCell 小区，即NR PCell小区对应NR服务小区。 c) UE d) 3GPP TS38.214，4.1节；3GPP TS38.133，10.1.6节；3GPP TS38.215，5.1节。 e) 取值范围如表1所示，取值类型为整型。 表 1 取值范围 OMC-R 北向接口上报值 3GPP 规定的上报值 测量数据区间分布（单位 dBm） 
证据2（YD/T 4826-2024｜body｜6.3.5）：【YD/T 4826-2024｜6.3.5 NR 服务小区的 SSB 参考信号信噪比】 [域签|functional_requirement|5g_nr|vendor_neutral|daily_ops|draft_report] 6.3.5. NR 服务小区的 SSB 参考信号信噪比 NR 服务小区的 SSB 参考信号信噪比测量报告样本数据定义如下： a) MR.NRScSSSINR b) 反映UE接收的服务小区SSB参考信号的信号与干扰加噪声比，定义为承载辅同步信号的资源 单元的功率的线性平均值除以资源上的噪声和干扰功率的线性平均值， 是反映小区下行信 号质量的主要指标。 c) UE d) 3GPP TS38.214，4.1节；3GPP TS38.133，10.1.16节；3GPP TS38.215，5.1节。 e) 取值范围如表5所示，取值类型为整型。 表 5 取值范围 OMC-R 北向接口上报值 3GPP 规定的上报值 测量数据区间分布（单位 dB） 0 SS-SINR_00 SS-SINR -23 1 SS-SINR_01 -23 SS-SINR <-22.5 2 SS-
证据3（TS 38.331｜asn1_card｜ssb-periodicityServingCell）：[TS 38.331 (NR) Rel-18 V18.11.0 ASN.1 参数卡 | ssb-periodicityServingCell] 参数：ssb-periodicityServingCell（所属 IE：ServingCellConfigCommon） 类型：ENUMERATED 取值域：ENUMERATED {ms5, ms10, ms20, ms40, ms80, ms160, spare2, spare1} 出处：clause 5.2.2.4 说明：The IE ServingCellConfigCommon is used to configure cell specific parameters of a UE's serving cell. The IE contains parameters which a UE would typically acquire from SSB, MIB or SIBs when accessing the cell from IDLE. With this IE, the ne…
证据4（TS 36.331｜case_card｜5.3.3.6）：[合成案例卡|源自 TS 36.331 Rel-18 V18.10.0 clause 5.3.3.6|投诉处理（LTE）|connEstFailOffset、connEstFailCount、numberOfPreamblesSent] 【现象】用户投诉在特定区域反复出现RRC连接建立失败，导致手机无法接入网络或频繁掉线。现场表现为信号格正常但业务发起时长时间无响应，最终提示连接失败。 【排查步骤】 1. 提取UE侧VarConnEstFailReport中的failedCellId与measResultFailedCell字段，确认失败发生的具体小区及当时的RSRP/RSRQ测量值。 2. 核查numberOfPreamblesSent与contentionDetected字段，判断随机接入过程中前导码发送次数及是否发生竞争解决失败。 3. 检查connEstFailCount与connEstFailOffset配置，验证T300超时后UE是否正确应用了临时偏置以规避该小区。 4. 分析maxTxPowerReached标志位，确认最后一次前导码发送是否达到最大发射功率，以排除上行覆
证据5（YD/T 4826-2024｜body｜6.3.2）：【YD/T 4826-2024｜6.3.2 已定义邻区关系和未定义邻区关系 NR 小区的 SSB 参考信号接收功率】 [域签|functional_requirement|5g_nr|vendor_neutral|daily_ops|draft_report] 6.3.2. 已定义邻区关系和未定义邻区关系 NR 小区的 SSB 参考信号接收功率 已定义邻区关系和未定义邻区关系 NR 小区的 SSB 参考信号接收功率测量报告样本数据定义如 下： a) MR.NRNcSSRSRP b) 反映UE处在某一个服务小区下接收到的已定义邻区关系和未定义邻区关系的邻区SSB参考信 号接收功率的大小，是决定切换的主要参考。未定义邻区为OMC-R邻区配置列表中未配置的 邻区。本测量数据表示接收的NR已定义邻区关系和未定义邻区关系的邻区参考信号接收功 率的原始测量值（即Uu口上报的测量报告中的测量值），其单位符合功率测量量纲。 c) UE d) 3GPP TS 38.214，4.1节；3GPP TS38.133，10.1.6节；3GPP TS38.215，5.1节 e) 取值范围如表2所示，取值类型为整型
判定：可答


[示例二]
[问题]
想批量改 LTE 切换的 A3 迟滞和触发时间，华为站走 MML 脚本、中兴站走网管工单。除了命令语法别写错，改前改后还得做哪些事？参数基线归谁审批、改坏了怎么回退、混网两家的值怎么防越改越飘？给一套能直接落到我们制度里的参数修改管理流程要点。

[证据 top5]
证据1（HW-20261012-04｜case_card｜HW-20261012-04）：[手写实操卡·AI填值|HW-20261012-04|切换失败排查（MRO 三分法）|迟滞 Hysteresis、触发时间 Time to Trigger、小区独立偏移 CIO、小区重选参数组（如 Qoffset/Qhyst）、切换执行定时器（如 T304 链路面）、Tstore_UE_cntxt、切换触发最大偏差（Maximum deviation of Handover Trigger）、切换成功率统计口径与劣化门限] 【现象】本卡面向切换失败排查场景，供切换成功率劣化伴掉话类工单按 MRO 三分法定位取用（对应骨架题 F2-04）。库内现象锚：HO 参数错设可致乒乓切换、切换失败与 RLF，MRO 主目标=减少 HO 相关 RLF（依据=TR 36.902 §4.5.1）。 【排查步骤】 1. 拉取 RLF 报告与切换统计：UE 保存最近一次 RLF/切换失败信息，重新接入 LTE 时指示报告可用，保留至网络提取或 48 小时（依据=TS 36.300 §22.4.5）；报告要素=最后服务小区 E-CGI（未知则 PCI＋频点）、重建尝试小区 E-CGI、上次切换初始化时服务小区
证据2（TS 36.300｜case_card｜22.4.2.4）：[合成案例卡|源自 TS 36.300 Rel-18 V18.8.0 clause 22.4.2.4|投诉处理（LTE）|Maximum deviation of Handover Trigger、Minimum time between Handover Trigger changes、Tstore_UE_cntxt] 【现象】用户投诉在移动过程中频繁掉话或连接失败，且通话中切换体感差。一线排查发现网络侧MRO自动调整参数后，切换触发点偏离过大或调整过于频繁，导致UE在小区边缘无法及时完成切换而掉线。 【排查步骤】 1. 提取eNB侧MRO日志，检查Handover Trigger的自动调整值是否超出OAM配置的Maximum deviation of Handover Trigger允许范围 2. 核对两次Handover Trigger变更的时间间隔，确认是否小于Minimum time between Handover Trigger changes设定的最小时间间隔 3. 查询Tstore_UE_cntxt参数配置状态，确认该参数已由OAM系统正确配置以支持Too Late和
证据3（TS 36.331｜case_card｜5.5.4.4）：[中文导读卡|源自 TS 36.331 Rel-18 V18.11.0 clause 5.5.4.4|D22-事件定义-LTE（LTE）] 【条款导读】该条款定义了 LTE 移动性管理中的 Event A3（邻区优于服务小区）事件。UE 需根据不等式 A3-1 判断进入条件，根据不等式 A3-2 判断离开条件。计算涉及邻区与服务小区的测量值（Mn, Mp）、频率/小区特定偏移（Ofn, Ocn, Ofp, Ocp）、迟滞参数 Hys 及事件偏移量 Off。若配置 usePSCell 为真则使用 PSCell 否则使用 PCell 作为参考。 【术语与表号指引】 1. Event A3：邻区质量优于主服务小区或辅服务小区一定偏移量的移动性事件 2. a3-Offset：定义在 reportConfigEUTRA 中用于此事件的偏移参数 Off 3. hysteresis：定义在 reportConfigEUTRA 中用于此事件的迟滞参数 Hys 4. entering condition：当满足不等式 A3-1 时视为进入条件成立 5. leaving condition：当满足不等式 
证据4（TS 36.331｜asn1_card｜a3-Offset）：[TS 36.331 (LTE) Rel-18 V18.11.0 ASN.1 参数卡 | a3-Offset] 参数：a3-Offset（所属 IE：ReportConfigEUTRA） 类型：INTEGER 取值域：INTEGER -30..30；单位 dB，实际值=字段值×0.5 dB（步进 0.5） 出处：clause 5.5.4.2 说明：Offset value to be used in EUTRA measurement report triggering condition for event a3/ a6/ c2, or to be used in conditional reconfiguration trigger condition for cond event a3. The actual value is field value * 0.5 dB. a5-Threshold1/ a5-Thr…
证据5（TR 36.839｜case_card｜5.2.2）：[合成案例卡|源自 TR 36.839 Rel-11 V11.1.0 clause 5.2.2|投诉处理（LTE）|Time of stay、MTS、Ping-pong rate] 【现象】手机信号格在满格与低格之间频繁跳动，像在反复切换。用户投诉移动过程中通话或数据业务出现明显中断感，疑似发生乒乓切换。 【排查步骤】 1. 提取切换日志中 RRCConnectionReconfigurationComplete 消息发送时间戳，计算 UE 在目标小区的 Time of stay。 2. 将计算出的 Time of stay 与预定义的 MTS（推荐值 1 second）对比，若小于 MTS 则判定为 Ping-pong 事件。 3. 统计 Ping-pong rate，口径为 ping-pongs 数量除以排除切换失败后的成功切换总数。 4. 核查切换失败场景下的日志记录，确认 Handover failure 时未错误记录 Time of stay，避免干扰统计。 【根因】UE 在源小区与目标小区间快速往返且在小区的驻留时间低于最小驻留时间（minimum time of stay
判定：可答


[示例三]
[问题]
36.331 里 ANR 邻区关系自配置的具体算法公式是哪一条？把邻区检测门限的数学推导也给我

[证据 top5]
证据1（YD/T 4747-2024｜body｜7.1.3）：【YD/T 4747-2024｜7.1.3 满配邻区处理】 7.1.3 满配邻区处理 测试编号：7.1.3 测试项目：满配邻区处理 测试分项：满配邻区处理（SA） 测试目的：系统内邻区关系达到满配规格后能够正确处理，比如替换出指定邻区或保持邻区 关系列表不变 测试条件： a) NR小区A存在系统内邻区关系X，且系统内邻区关系达到满配规格，除了X外其他邻区 属性设置为NO Remove； b) NR小区A和待发现邻区对应NR小区B状态正常，无邻区关系。A和B为同频小区； c) 至少一部测试终端，具备待发现邻区的普通测量和ANR测量的相关能力。 测试步骤： 步骤1： 设置NR系统内自动邻区发现和添加的相关配置策略，ANR优化模式设置为“受控 模式”，设置检测周期和相关策略门限； 步骤2： 经过一个统计周期后，邻区关系X业务排序最后，且允许删除；设置其他邻区为切 换白列表（No Remove），不允许删除； 步骤3： 测试终端在服务小区A接入并发起业务； 步骤4： 移动测试终端触发上报邻区B的测量报告（包括B的频点、PCI、信号强度基本信息 等）； 步骤5： NR小区A使用对应频点和PCI信
证据2（YD/T 4826-2024｜body｜6.3.20）：【YD/T 4826-2024｜6.3.20 已定义邻区关系和未定义邻区关系的 LTE物理小区识别码】 [域签|functional_requirement|5g_nr|vendor_neutral|daily_ops|draft_report] 6.3.20. 已定义邻区关系和未定义邻区关系的 LTE物理小区识别码 已定义邻区关系和未定义邻区关系的 LTE 物理小区识别码测量报告样本数据定义如下： a) MR.LteNcPci b) UE进行系统内切换时对已定义邻区关系和未定义邻区关系的 LTE邻小区进行测量，在LTE已 定义邻区关系和未定义邻区关系的 邻区载波上进行测量时解调出的 LTE已定义邻区关系和 未定义邻区关系的邻区载波的物理小区识别码(PCI)。未定义邻区为OMC-R邻区配置列表中 未配置的邻区。NSA场景下不要求测量，填写NIL即可。 c) 不适用 d) 3GPP TS 36.300。 e) 整型，取值范围为0..503。 f) LTE邻区优化，非单独测量数据，仅用于标识测量报告关联的对象。
证据3（YD/T 4826-2024｜body｜6.3.15）：【YD/T 4826-2024｜6.3.15 已定义邻区关系和未定义邻区关系的 NR 邻区载波号】 [域签|functional_requirement|5g_nr|vendor_neutral|daily_ops|draft_report] 6.3.15. 已定义邻区关系和未定义邻区关系的 NR 邻区载波号 已定义邻区关系和未定义邻区关系的 NR 邻区载波号测量报告样本数据定义如下： a) MR.NRNcArfcn b) UE进行系统内切换时对已定义邻区关系和未定义邻区关系的NR邻小区进行测量，在NR已定 义邻区关系和未定义邻区关系的邻区载波上进行测量时解调出的NR已定义邻区关系和未定 义邻区关系的邻区载波的Arfcn。未定义邻区为OMC-R邻区配置列表中未配置的邻区。 c) 不适用 d) 3GPP TS38.104，5.4节。 e) 整型，取值范围为0…3279165 f) 非单独测量数据，仅用于标识测量报告关联的对象。
证据4（YD/T 4747-2024｜body｜7.1.2）：【YD/T 4747-2024｜7.1.2 基于Xn 配置更新的邻区互配添加】 7.1.2 基于Xn 配置更新的邻区互配添加 测试编号：7.1.2 测试项目：邻区添加 测试分项：基于 Xn 配置数据更新的邻区互配添加（SA） 测试目的：验证基于 Xn 配置数据更新的邻区互配发现和添加 测试条件： a) NR小区A和NR小区B分属不同的gNodeB，两个gNodeB间存在Xn； b) 小区A、B间存在单向邻区关系（B->A）。 测试步骤： 步骤1： 设置服务小区A邻区互配策略； 步骤2： 服务小区A通过Xn配置数据交互检测到B->A单向邻区关系； 步骤3： 服务小区A到邻区B的邻区关系自动配置更新。 预期结果：服务小区 A、B间双向邻区关系添加成功 备注：
证据5（YD/T 4747-2024｜body｜7.1.1）：【YD/T 4747-2024｜7.1.1 基于终端CGI 测量的邻区发现和添加】 7.1.1 基于终端CGI 测量的邻区发现和添加 测试编号：7.1.1 测试项目：邻区添加 测试分项：基于终端 CGI 测量的邻区发现和添加（SA） 测试目的：验证基于终端邻区全局标识测量方式的邻区添加 测试条件： a) NR小区A和待发现邻区对应NR小区B，C状态正常，A和B、 A和C间无邻区关系。B和 A为同频，C和A为异频，服务小区A、B、C对应gNB分别为gNB1，gNB2，gNB3； b) 至少一部测试终端，具备待发现邻区的普通测量和ANR测量的相关能力。 传输设备 光/电口 GE光口 OMC gNodeB2 （Cell2）Xn连接 5GC gNodeB1 （Cell1,Cell3） （）  测试步骤： 步骤1： 设置系统内ANR相关策略，ANR优化模式设置为“自由模式”； 步骤2： 移动测试终端触发上报邻区B的测量报告（包括B的频点、PCI、信号强度基本信息 等）； 步骤3： 服务小区A使用对应频点和PCI信息，指示测试终端发起对邻区B的相关广播消息的 读取和上报；观察空口相关信令； 步骤4
判定：不可答


[示例四]
[问题]
38.331 里 hysteresis、a3-Offset 这些切换参数，厂商默认值和现网推荐配置表在第几章？给个推荐取值清单

[证据 top5]
证据1（HW-20261012-04｜case_card｜HW-20261012-04）：[手写实操卡·AI填值|HW-20261012-04|切换失败排查（MRO 三分法）|迟滞 Hysteresis、触发时间 Time to Trigger、小区独立偏移 CIO、小区重选参数组（如 Qoffset/Qhyst）、切换执行定时器（如 T304 链路面）、Tstore_UE_cntxt、切换触发最大偏差（Maximum deviation of Handover Trigger）、切换成功率统计口径与劣化门限] 【现象】本卡面向切换失败排查场景，供切换成功率劣化伴掉话类工单按 MRO 三分法定位取用（对应骨架题 F2-04）。库内现象锚：HO 参数错设可致乒乓切换、切换失败与 RLF，MRO 主目标=减少 HO 相关 RLF（依据=TR 36.902 §4.5.1）。 【排查步骤】 1. 拉取 RLF 报告与切换统计：UE 保存最近一次 RLF/切换失败信息，重新接入 LTE 时指示报告可用，保留至网络提取或 48 小时（依据=TS 36.300 §22.4.5）；报告要素=最后服务小区 E-CGI（未知则 PCI＋频点）、重建尝试小区 E-CGI、上次切换初始化时服务小区
证据2（TS 38.331｜asn1_card｜a3-Hysteresis-r18）：[TS 38.331 (NR) Rel-18 V18.11.0 ASN.1 参数卡 | a3-Hysteresis-r18] 参数：a3-Hysteresis-r18（所属 IE：ReportConfigNR） 类型：INTEGER（类型引用 Hysteresis） 取值域：INTEGER 0..30 出处：clause 5.3.10.5 说明：The IE ReportConfigNR specifies criteria for triggering of an NR measurement reporting event or of a CHO, CPA or CPC event or of an L2 U2N relay measurement reporting event. For events labelled AN with N equal to 1, 2 and so on, measurement…
证据3（TS 38.133｜table_row_group｜Annex A 表 行组13-18）：[TS 38.133 (NR) Rel-18 V18.13.0 clause Annex A 表格 ] 表格摘要：本表 4 列 × 21 数据行；列 = 1) Parameter Unit；2) Test configuration；3) Value；4) Comment。表题：（无题注，见表头/语境行） 表格语境：NR TS 38.133 Rel-18 V18.13.0 clause Annex A｜中文关键词：配置 Parameter Unit = A3-Offset | Test configuration = dB | Value = Config 1 | Comment = -11 Parameter Unit = Hysteresis | Test configuration = dB | Value = Config 1 | Comment = 0 ≈ Parameter Unit = CP length | Test configuration = Config 1 | Value = Normal Parameter Unit = TimeToTrigger | Te
证据4（TS 36.331｜asn1_card｜a3-Offset）：[TS 36.331 (LTE) Rel-18 V18.11.0 ASN.1 参数卡 | a3-Offset] 参数：a3-Offset（所属 IE：ReportConfigEUTRA） 类型：INTEGER 取值域：INTEGER -30..30；单位 dB，实际值=字段值×0.5 dB（步进 0.5） 出处：clause 5.5.4.2 说明：Offset value to be used in EUTRA measurement report triggering condition for event a3/ a6/ c2, or to be used in conditional reconfiguration trigger condition for cond event a3. The actual value is field value * 0.5 dB. a5-Threshold1/ a5-Thr…
证据5（TS 36.133｜table_row_group｜Annex A Table A.8.11.4.1-1 行组13-18）：[TS 36.133 (LTE) Rel-18 V18.13.0 clause Annex A 表格 Table A.8.11.4.1-1 General test parameters for combined E-UTRA TDD inter-frequency and UTRA TDD cel…] 表格摘要：本表 4 列 × 25 数据行；列 = 1) Parameter；2) Unit；3) Value；4) Comment。表题：General test parameters for combined E-UTRA TDD inter-frequency and UTRA TDD cells search under fading propagation conditions 表格语境：LTE TS 36.133 Rel-18 V18.13.0 clause Annex A Parameter = Ofn | Unit = dB | Value = 0 | Comment = Parameter for A3 and B2 event Parameter = Ocn | Un
判定：不确定
[待判]
[问题]
{题面}

[证据 top5]
证据1（{doc_id}｜{chunk_type}｜{locator}）：{内容摘要}
证据2（{doc_id}｜{chunk_type}｜{locator}）：{内容摘要}
证据3（{doc_id}｜{chunk_type}｜{locator}）：{内容摘要}
证据4（{doc_id}｜{chunk_type}｜{locator}）：{内容摘要}
证据5（{doc_id}｜{chunk_type}｜{locator}）：{内容摘要}
判定："""
# （冻结块=判据件 v2 §1.4 代码栅栏逐字；测试件确定性提取断言 11,573）

_ANSWERABILITY_VERDICTS = ("可答", "不可答", "不确定")

# 判官结论 LRU 缓存（qhash16 → verdict；容量=answerability_cache_size 写入时
# 生效；dict 保序+get 提位实现 LRU，锁护多探线程写/事件循环读并发）。
_answerability_cache = {}
_answerability_cache_lock = threading.Lock()
# 连续失败熔断（判据件 v2 §二：连续 3 次 API 超时/协议失败 → 停手复核——生产
# 形态=判官面停呼+观测行 verdict=skip，判官面故障绝不挡答案；进程重启/拨键
# 复位。任一成功清零）。
_answerability_fail_streak = 0
_answerability_breaker_warned = False
# 已装载库只读索引（chunk id → rec；判官证据块 content/chunk_type 解析面。
# rag.py 零触碰——只读 rag_service._recs 一次建 map，随服务对象身份缓存）。
_answerability_recs_cache = {"svc": None, "by_id": None}


def _answerability_cache_get(qh):
    """LRU 读（µs 级：锁内 dict get+提位）→ verdict 或 None（miss）。"""
    with _answerability_cache_lock:
        v = _answerability_cache.pop(qh, None)
        if v is not None:
            _answerability_cache[qh] = v      # 提位=最近使用
        return v


def _answerability_cache_put(qh, verdict, cap):
    """LRU 写（命中三态才写；失败/超时/skip 一律不写=fail-open 零缓存零路由）。"""
    try:
        cap = max(1, int(cap))
    except (TypeError, ValueError):
        cap = 8192
    with _answerability_cache_lock:
        _answerability_cache.pop(qh, None)
        _answerability_cache[qh] = verdict
        while len(_answerability_cache) > cap:
            oldest = next(iter(_answerability_cache))
            del _answerability_cache[oldest]


def _answerability_recs_by_id(rag_svc):
    """判官证据面解析：sources（retrieve 融合序产物，含 chunk id）→ content/
    chunk_type。只读 getattr(rag_svc, "_recs")（公共面无按 id 取块访问器；
    rag.py 零触碰纪律下的最小只读旁路），按服务对象身份缓存一次
    （62,512 块 map 构建一次 ~几十 ms，此后纯 dict 命中）。失败=None=判官跳过。"""
    if rag_svc is None:
        return None
    with _answerability_cache_lock:
        if _answerability_recs_cache["svc"] is rag_svc \
                and _answerability_recs_cache["by_id"] is not None:
            return _answerability_recs_cache["by_id"]
    try:
        recs = getattr(rag_svc, "_recs", None)
    except Exception:
        return None
    if not recs:
        return None
    by_id = {}
    for r in recs:
        try:
            by_id[str(r.get("id") or "")] = r
        except Exception:
            continue
    with _answerability_cache_lock:
        _answerability_recs_cache["svc"] = rag_svc
        _answerability_recs_cache["by_id"] = by_id
    return by_id


def _answerability_first_word(out):
    """首词协议解析（判据件 v2 §二逐字）：strip 后首词；带标点=不通过。"""
    s = (out or "").strip()
    parts = s.split()
    return parts[0] if parts else ""


def _answerability_build_message(query, sources, by_id):
    """v2 冻结块槽位代入（§1.2 构造规则，生产与跑批同构）：题面=query 原文；
    证据N=（doc_id｜chunk_type｜locator）：content 换行→空格后前 500 字符切片
    （超长截断不加省略标记——确定性切片零自由裁量；u3c 装配脚本同款 \r/\n 双
    替换）。槽位先于题面替换（防题面含槽位形文本被二次代入）；任一 id 解析
    失败=None=判官跳过（fail-open）。"""
    entries = []
    for s in sources[:5]:
        rec = by_id.get(str(s.get("id") or "")) if isinstance(s, dict) else None
        if rec is None:
            return None
        snippet = (str(rec.get("content") or "")
                   .replace("\r", " ").replace("\n", " "))[:500]
        entries.append("证据%d（%s｜%s｜%s）：%s" % (
            len(entries) + 1, str(rec.get("doc_id") or ""),
            str(rec.get("chunk_type") or ""), str(s.get("locator") or ""),
            snippet))
    msg = _ANSWERABILITY_PROMPT_TEMPLATE
    for i, entry in enumerate(entries, 1):
        slot = ("证据%d（{doc_id}｜{chunk_type}｜{locator}）：{内容摘要}" % i)
        if slot not in msg:
            return None
        msg = msg.replace(slot, entry, 1)
    if "{doc_id}" in msg or "{内容摘要}" in msg or "{题面}" not in msg:
        return None            # 残留槽位=代入不完整，fail-open 不发判官
    return msg.replace("{题面}", str(query or ""), 1)


def _answerability_llm_call(message, p):
    """判官单发（UPSTREAM 常量同款订阅通道；httpx 同步单发、零重试铁律对齐
    _rerank_api_call 样板）→ 回复文本。非 200/JSON 畸形/超时=抛异常（调用方
    兜底=fail-open 不写缓存）。调用参数=判据件 v2 §1.5：temperature=0、
    top_k=1、max_tokens=32、enable_thinking=False（禁 max_tokens=1：「不确定」
    截成残词）。"""
    body = {"model": p["judge_model"],
            "messages": [{"role": "user", "content": message}],
            "temperature": 0, "top_k": 1, "max_tokens": 32,
            "enable_thinking": False, "stream": False}
    with httpx.Client(timeout=p["timeout_s"]) as client:
        resp = client.post(UPSTREAM, json=body,
                           headers={"Authorization": "Bearer " + API_KEY})
        resp.raise_for_status()
        data = resp.json()
    choices = data.get("choices") or [{}]
    return str((((choices[0].get("message") or {}).get("content")) or ""))


def _answerability_judge_maybe(qh, rag_svc, query, sources, p):
    """判官调用器（探线程内串行；限频天然满足）→ (judged, verdict, judge_ms)。

    - judged=False（verdict=None/judge_ms=0）=本次不调判官（观测行 verdict=
      skip）：熔断开 / API_KEY 未配 / 缓存已有结论（同题不重复耗额）/ 证据面
      不可用（无 sources、非 5 块、块索引缺失、槽位代入失败）。
    - judged=True, verdict∈三态=协议通过（缓存写入由调用方执行）；verdict=None
      =判过但失败（首词不通过同参重试 1 次→null；传输失败/超时→null）=fail-open
      不写缓存，连续失败计数 +1（任一成功清零；连续 3 次熔断停呼）。"""
    global _answerability_fail_streak, _answerability_breaker_warned
    if _answerability_fail_streak >= 3:
        if not _answerability_breaker_warned:
            _answerability_breaker_warned = True
            print("[answerability] breaker_open fail_streak=3（判官连续 3 次"
                  "失败熔断：本进程跳过判官调用，fail-open 放行——复核后重启或"
                  "拨键复位）", flush=True)
        return False, None, 0
    if not API_KEY or not UPSTREAM:
        return False, None, 0
    if _answerability_cache_get(qh) is not None:
        return False, None, 0                    # 缓存命中=不重复调判官
    srcs = [s for s in (sources or []) if isinstance(s, dict)]
    if len(srcs) < 5:
        return False, None, 0                    # 证据面≠5 块=跳过（已知界）
    by_id = _answerability_recs_by_id(rag_svc)
    if by_id is None:
        return False, None, 0
    msg = _answerability_build_message(query, srcs, by_id)
    if msg is None:
        return False, None, 0
    verdict = None
    t0 = time.monotonic()
    try:
        w = _answerability_first_word(_answerability_llm_call(msg, p))
        if w in _ANSWERABILITY_VERDICTS:
            verdict = w
        else:                                     # 同参重试 1 次（v2 §二）
            w = _answerability_first_word(_answerability_llm_call(msg, p))
            verdict = w if w in _ANSWERABILITY_VERDICTS else None
    except Exception:
        verdict = None                            # 传输失败/超时→null（fail-open）
    judge_ms = int((time.monotonic() - t0) * 1000)
    with _answerability_cache_lock:
        if verdict in _ANSWERABILITY_VERDICTS:
            _answerability_fail_streak = 0
        else:
            _answerability_fail_streak += 1
    return True, verdict, judge_ms


def _answerability_shadow_line(query, rag_state, pool_max, sources=None,
                               rag_svc=None):
    """[answerability] 观测行（U2 KV+U5 verdict 扩展键）：band 命中=面别 vac ∧
    band_lo ≤ pool_max < band_hi（含下不含上）∧ rag_state=hit 三条件齐时，由
    探线程落一行——KV=qhash16+pool_max+face+band_lo+band_hi+verdict+judge_ms
    （零题面原文；判官消息体绝不落日志）。verdict 三态/null=判过（判官调用后
    ms 打点）；skip=本次未调判官（熔断/缓存命中/证据面缺/未配钥——enabled=
    false 时本函数零行零动作=U2 纯观测关态语义）。命中三态即写 LRU 缓存
    （qhash16→verdict，供 /api/chat 主路径消费）；失败/超时=不写缓存。纯
    print+本地字典操作，绝不抛出。

    v1 作用面=vac（计划 §1.2：prac 面不覆盖=已知界）。"""
    try:
        p = _answerability_params()
        if not p["enabled"] or rag_state != "hit":
            return
        face = _rerank_refusal_face(query)
        if face != "vac":
            return
        if not (p["band_lo"] <= pool_max < p["band_hi"]):
            return
        qh = _rerank_probe_tag(query, 16)
        judged, verdict, judge_ms = _answerability_judge_maybe(
            qh, rag_svc, query, sources, p)
        if verdict in _ANSWERABILITY_VERDICTS:
            _answerability_cache_put(qh, verdict, p["cache_size"])
        v_field = ("skip" if not judged else (verdict or "null"))
        print(f"[answerability] qhash={qh} pool_max={pool_max:.4f} face={face}"
              f" band_lo={p['band_lo']:g} band_hi={p['band_hi']:g}"
              f" verdict={v_field} judge_ms={judge_ms}", flush=True)
    except Exception:
        pass          # 观测面绝不向探线程外传播（铁律②同款）


async def _conv_auth(request: Request):
    """三会话端点鉴权（与 /api/chat 同门）：有效 SESSION_COOKIE 会话，或口令
    （GET/DELETE 无 body 时从 X-QA-Passcode 头取，POST 语义同 chat 的 body 双轨）
    任一过级。返回 None=过级；否则返回对齐 /api/chat 形态的 401 JSONResponse
    （auth_expired/login_required/bad_passcode 三态同码）。"""
    token = request.cookies.get(SESSION_COOKIE, "")
    if token and await asyncio.to_thread(_store().get_session, token):
        return None
    supplied = ""
    try:
        body = await request.json()
    except Exception:
        body = None
    if isinstance(body, dict):
        supplied = str(body.get("passcode") or "").strip()
    if not supplied:
        supplied = str(request.headers.get("x-qa-passcode") or "").strip()
    if not _passcode_gate():
        return None  # 未配口令的本地开放态（口径同 /api/health）
    if not supplied:
        return JSONResponse({"error": "auth_expired"}, status_code=401)
    if not CONFIG.get("passcode_body_enabled", True):
        return JSONResponse({"error": "login_required"}, status_code=401)
    if not await _passcode_ok(supplied):
        return JSONResponse({"error": "bad_passcode"}, status_code=401)
    return None


async def _conversation_writeback(store, device_id: str, conv_header, user_text: str,
                                  regen: bool = False) -> int:
    """/api/chat 会话双写·user 侧（抽成独立函数便于单测）：解析 X-QA-Conv-Id 头
    （可选 int）——合法且归属本 device → 续写该会话；缺省/非整数/不存在/非本
    设备一律自动新建（定案：缺省自动建新会话，避免隐式续写歧义；前端续写时
    显式带 id，续写不合法时静默换新会话、经响应头 X-QA-Conv-Id 告知前端新 id）。
    本条 user 消息随开/建一并落库；新建会话标题=首条 user 消息前 24 字符。
    二期批A regen（案①服务端替换，2026-10-03）：regen=True 且归属命中续写时，
    先删该会话末轮（最后一条 user 及其后全部消息，含孤 user 断流形态）再写
    本轮——重新生成后服务端历史与前端一致（旧轮不残留）。regen 仅对显式
    合法 conv id 生效；缺省/非法/非本设备 → 自动建新会话路径，regen 静默
    忽略（新会话无旧轮可删）。"""
    conv_id = None
    if conv_header is not None:
        try:
            conv_id = int(str(conv_header).strip())
        except ValueError:
            conv_id = None
    if conv_id is not None:
        rows = await asyncio.to_thread(store.get_messages, conv_id, device_id)
        if rows is not None:  # 归属命中 → 续写
            if regen:
                await asyncio.to_thread(store.delete_last_round, conv_id)
            await asyncio.to_thread(
                store.append_message, conv_id, "user", user_text, None)
            return conv_id
    conv_id = await asyncio.to_thread(
        store.create_conversation, device_id, (user_text or "")[:24])
    await asyncio.to_thread(store.append_message, conv_id, "user", user_text, None)
    return conv_id


@app.post("/api/login")
async def login(request: Request):
    """口令换会话（批2 §2）：校验→建 sessions 行→种 HttpOnly cookie。
    失败限速（批2 遗留补强）：同 IP 10 分钟窗 5 次失败后上锁，第 6 次起 429——
    锁检查先于 PBKDF2（锁定期内对口令也 429，防研磨计时侧信道+CPU 耗损面）；
    被 429 拒绝的尝试不计数不续锁；成功登录清该 IP 计数；开放态（未配口令）
    不启用（无研磨面，也避免历史残留计数误伤）。"""
    ip = _client_ip(request)
    if _passcode_gate():
        remaining = await asyncio.to_thread(
            _store().login_lock_remaining, ip, LOGIN_FAIL_LIMIT, LOGIN_FAIL_WINDOW_S)
        if remaining > 0:
            print(f"[login] ip={ip} ok=0 locked retry_after={remaining}s", flush=True)
            return JSONResponse(
                {"error": "too_many_attempts", "retry_after_s": remaining,
                 "message": "尝试次数过多，请稍后再试"}, status_code=429)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "bad_json"}, status_code=400)
    if not isinstance(body, dict):  # JSON 数组等非对象 body→400，防 .get 裸炸 500
        return JSONResponse({"error": "bad_json"}, status_code=400)
    supplied = str(body.get("passcode") or "").strip()
    if _passcode_gate() and not await _passcode_ok(supplied):
        print(f"[login] ip={ip} ok=0", flush=True)  # 不记口令/token
        await asyncio.to_thread(
            _store().record_login_fail, ip, LOGIN_FAIL_WINDOW_S)
        return JSONResponse({"error": "bad_passcode"}, status_code=401)
    await asyncio.to_thread(_store().clear_login_fails, ip)
    token = await asyncio.to_thread(_store().create_session, None)
    print(f"[login] ip={ip} ok=1", flush=True)
    return _session_cookie(token, JSONResponse({"ok": True}))


@app.post("/api/logout")
async def logout(request: Request):
    """登出：删会话行+清 cookie（本地 msgs 不动，前端自理）。"""
    token = request.cookies.get(SESSION_COOKIE, "")
    if token:
        await asyncio.to_thread(_store().delete_session, token)
    print(f"[logout] ip={_client_ip(request)}", flush=True)
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


@app.api_route("/api/health", methods=["GET", "POST"])
async def health(request: Request):
    """分级健康检查（2026-09-21 批1：关无鉴权侦察面；批2：会话 cookie 也可过级）。

    - 未过级（GET/POST 均无有效会话 cookie 且 POST 无正确口令）→ 只回 {"ok": true}
      （不泄露模型名/部署细节；口令绝不入 URL——防落入 uvicorn 访问日志）；
    - 过级三途：有效会话 cookie / POST 带正确口令（body {"passcode": ...}，
      校验同 /api/chat，且自评审 F1 2026-10-15 起挂 login_fails 同账锁=失败
      记账/成功清零/锁定期 429）/ 未配置 passcode 的本地开发态（维持旧全量返回，
      服务本就无访问门槛，无边际泄露，保守兼容选择）；
    - 过级回完整字段 model/bot_name/has_key（前端健康检查与 bot_name 用）。
    """
    def _full():
        return {"ok": True, "model": CONFIG["model"],
                "bot_name": CONFIG.get("bot_name", "网优工程师的qa-bot"), "has_key": bool(API_KEY)}

    if not _passcode_gate():
        return _full()
    token = request.cookies.get(SESSION_COOKIE, "")
    if token and await asyncio.to_thread(_store().get_session, token):
        return _full()
    if request.method == "POST":
        try:
            body = await request.json()
        except Exception:
            body = None
        if body is not None and not isinstance(body, dict):
            # F2（评审 2026-10-15）：合法 JSON 非对象（数组/字符串等）→ 400，防
            # (body or {}).get 裸炸 AttributeError 500（照 login 守卫形态）
            return JSONResponse({"error": "bad_json"}, status_code=400)
        supplied = str((body or {}).get("passcode") or "").strip()
        if supplied:
            # F1（评审 2026-10-15 立改）：POST 口令分支挂 login_fails 同账锁（照
            # /api/login 形态）——锁检查先于 PBKDF2，堵未认证 CPU 研磨/绕 login
            # 锁的口令 oracle；失败同账记账、成功清零；锁定期 429 响应形态与
            # login 逐字一致，其余未过级响应形态不变（不新增口令对错 oracle）。
            ip = _client_ip(request)
            remaining = await asyncio.to_thread(
                _store().login_lock_remaining, ip, LOGIN_FAIL_LIMIT, LOGIN_FAIL_WINDOW_S)
            if remaining > 0:
                print(f"[health] ip={ip} locked retry_after={remaining}s", flush=True)
                return JSONResponse(
                    {"error": "too_many_attempts", "retry_after_s": remaining,
                     "message": "尝试次数过多，请稍后再试"}, status_code=429)
            if await _passcode_ok(supplied):
                await asyncio.to_thread(_store().clear_login_fails, ip)
                return _full()
            await asyncio.to_thread(
                _store().record_login_fail, ip, LOGIN_FAIL_WINDOW_S)
    return {"ok": True}


# ---------- 3c：/metrics 指标三行（计划-管理面建设-20261030.md §七.3c＋§十二；
# 过程日志 319 号④ 2026-11-01 并窗编码） ----------
# 指标三行=问答轮/错误轮/LLM tokens（仪表盘⑤与控制台 delta 面"真人问/费/
# 错误率"三行词汇的进程原值面：真人筛法〔判读线 v2.1 剔自动化三类+探针剔键〕
# 与费价换算归消费侧——本端点不造价不筛人，费面口径纪律不动）。纯内存累计，
# restart 清零（消费侧 delta 面自行对拍基线，同控制台 delta_prev 先例）。
_METRICS = {"rounds": 0, "errors": 0, "llm_tokens": 0}
_METRICS_LOCK = threading.Lock()


def _metrics_round(llm_status, usage):
    """3c：每问答轮收尾打点（[chat] 锚点行同位；恒不抛出=打点绝不影响请求）。

    rounds=进入 SSE 生成器并走到收尾的轮（含用户断流 cancelled 与分诊罐头轮）；
    errors=llm_status=="error" 轮（上游非 200/超时/断流异常降级收尾口径）；
    llm_tokens=provider usage total_tokens 原值合计（缺 usage 不计）。"""
    try:
        with _METRICS_LOCK:
            _METRICS["rounds"] += 1
            if llm_status == "error":
                _METRICS["errors"] += 1
            _t = (usage or {}).get("total_tokens")
            if isinstance(_t, (int, float)) and not isinstance(_t, bool):
                _METRICS["llm_tokens"] += int(_t)
    except Exception:
        pass


@app.get("/metrics")
async def metrics(request: Request):
    """3c 指标三行（Prometheus 文本 exposition 子集；GET 免鉴权=环回卫面）。

    公网零暴露双闸：①socket 面=run-cloud.sh uvicorn --host 127.0.0.1（319①
    案②，8000 不再对外监听）；②端点面=请求源环回卫——socket 对端非
    127.0.0.1/::1，或带 X-Forwarded-For 头（Caddy 反代必带——防未来误绑
    0.0.0.0 时经域名/反代外泄）一律 404。密值零入指标（只计数与 token 数）。"""
    if (_client_ip(request) not in ("127.0.0.1", "::1")
            or request.headers.get("x-forwarded-for")):
        return JSONResponse({"error": "not_found"}, status_code=404)
    with _METRICS_LOCK:
        _rounds, _errors, _tokens = (_METRICS["rounds"], _METRICS["errors"],
                                     _METRICS["llm_tokens"])
    _body = (
        "# 3c 指标三行（计划-管理面建设 §七.3c）：问答轮/错误轮/LLM tokens\n"
        "# （进程内存态 restart 清零；费=消费侧按价换算，端点不造价）\n"
        f"qa_bot_chat_rounds_total {_rounds}\n"
        f"qa_bot_chat_errors_total {_errors}\n"
        f"qa_bot_llm_tokens_total {_tokens}\n")
    return Response(_body, media_type="text/plain; charset=utf-8")


# ---------- C2：CSP Report-Only 上报收集位（2026-10-07） ----------
@app.post("/api/csp-report")
async def csp_report(request: Request):
    """CSP 违例上报端点（Report-Only 档的收集面，观察期不落任何盘）。

    - 无鉴权：浏览器 report-uri 自动上报不带会话语义，套门即全灭；防刷挂
      conv_hits 限流组（60 次/分，与三会话端点同账——刻意不复用 rate_hits，
      防上报挤占 /api/chat 频控预算，先例同批次D conv_hits 分账）。
    - 只打一行 journal（ip+违例指令名；报告体含用户页面上下文，不入日志
      ——对齐 [chat] q= 摘要纪律），不落盘存储（转强制档时再议留存）。
    - 任何 body 形态（空/非 JSON/超长）都 204：上报处理失败不该让浏览器
      重试刷日志。
    """
    ip = _client_ip(request)
    if not await asyncio.to_thread(_store().conv_rate_ok, ip,
                                   CONV_RATE_LIMIT, CONV_RATE_WINDOW_S):
        return JSONResponse({"error": "rate_limited", "retry_after_s": 60},
                            status_code=429)
    directive = ""
    try:
        body = await request.json()
    except Exception:
        body = None
    doc = body.get("csp-report") if isinstance(body, dict) else None
    if isinstance(doc, dict):
        directive = str(doc.get("violated-directive")
                        or doc.get("effective-directive") or "")
    # F21（评审 2026-10-15）：directive 原样入 journal 可被 JSON 换行伪造日志行——
    # 套既有 _q_log_field 清洗（控制字符折空格+截 80），journal 单行完整性优先。
    print(f"[csp-report] ip={ip} directive={_q_log_field(directive or '-')}", flush=True)
    return Response(status_code=204)


# ---------- 批次D：多会话历史三端点（鉴权同 /api/chat 门；列表低频不套 chat 滑窗，
# 用独立 conv_hits 小表 60 次/分防扫——分表防会话轮询吃掉 chat 频控预算） ----------
@app.get("/api/conversations")
async def conversations_list(request: Request):
    """本 device 会话列表：{ok, conversations:[{id,title,updated_at,last_role}...]}
    （updated_at desc 限 50；last_role=会话内最末消息角色，空会话 null）。"""
    if not _conversations_enabled():
        return JSONResponse({"error": "not_found"}, status_code=404)
    ip = _client_ip(request)
    if not await asyncio.to_thread(_store().conv_rate_ok, ip, CONV_RATE_LIMIT, CONV_RATE_WINDOW_S):
        return JSONResponse({"error": "rate_limited", "retry_after_s": 60}, status_code=429)
    resp401 = await _conv_auth(request)
    if resp401 is not None:
        return resp401
    dev = _device_id_from(request)
    rows = await asyncio.to_thread(_store().get_conversations, dev, CONVERSATIONS_LIMIT)
    resp = JSONResponse({"ok": True, "conversations": rows})
    _ensure_device(request, resp, dev)
    return resp


@app.get("/api/conversations/{conv_id}/messages")
async def conversation_messages(conv_id: str, request: Request):
    """会话消息恢复：{ok, messages:[{role,content,sources,pending:false}...]}
    （sources=解析 sources_json，失败/非 list 给 null；conv 不存在或非本
    device → 404 {"error":"not_found"}；非整数 id 同 404 口径）。"""
    if not _conversations_enabled():
        return JSONResponse({"error": "not_found"}, status_code=404)
    ip = _client_ip(request)
    if not await asyncio.to_thread(_store().conv_rate_ok, ip, CONV_RATE_LIMIT, CONV_RATE_WINDOW_S):
        return JSONResponse({"error": "rate_limited", "retry_after_s": 60}, status_code=429)
    resp401 = await _conv_auth(request)
    if resp401 is not None:
        return resp401
    dev = _device_id_from(request)
    try:
        cid = int(str(conv_id).strip())
    except ValueError:
        return JSONResponse({"error": "not_found"}, status_code=404)
    if not (1 <= cid <= 2**63 - 1):
        # 超 SQLite 64 位绑定域的巨整数 id 一律 404（防未处理 OverflowError 500）
        return JSONResponse({"error": "not_found"}, status_code=404)
    rows = await asyncio.to_thread(_store().get_messages, cid, dev)
    if rows is None:
        return JSONResponse({"error": "not_found"}, status_code=404)
    msgs = []
    for role, content, sources_json in rows:
        try:
            src = json.loads(sources_json) if sources_json else None
        except ValueError:
            src = None
        if not isinstance(src, list):
            src = None  # 坏档防御：只认 list 形态（写侧恒为 sources 数组）
        msgs.append({"role": role, "content": content, "sources": src,
                     "pending": False})
    resp = JSONResponse({"ok": True, "messages": msgs})
    _ensure_device(request, resp, dev)
    return resp


@app.delete("/api/conversations/{conv_id}")
async def conversation_delete(conv_id: str, request: Request):
    """删会话（连带消息）：{ok}；不存在或非本 device → 404 {"error":"not_found"}。"""
    if not _conversations_enabled():
        return JSONResponse({"error": "not_found"}, status_code=404)
    ip = _client_ip(request)
    if not await asyncio.to_thread(_store().conv_rate_ok, ip, CONV_RATE_LIMIT, CONV_RATE_WINDOW_S):
        return JSONResponse({"error": "rate_limited", "retry_after_s": 60}, status_code=429)
    resp401 = await _conv_auth(request)
    if resp401 is not None:
        return resp401
    dev = _device_id_from(request)
    try:
        cid = int(str(conv_id).strip())
    except ValueError:
        return JSONResponse({"error": "not_found"}, status_code=404)
    if not (1 <= cid <= 2**63 - 1):
        # 超 SQLite 64 位绑定域的巨整数 id 一律 404（防未处理 OverflowError 500）
        return JSONResponse({"error": "not_found"}, status_code=404)
    ok = await asyncio.to_thread(_store().delete_conversation, cid, dev)
    if not ok:
        return JSONResponse({"error": "not_found"}, status_code=404)
    resp = JSONResponse({"ok": True})
    _ensure_device(request, resp, dev)
    return resp


# ---------- 二期批次B：旧记录导入端点（POST /api/conversations/import；门序=
# 开关→限速→鉴权→body 照三会话端点，conv_hits 同账 60 次/分；零 LLM 纯落库；
# 判据=运营/前端二期-批次B-20261003/判据预登记.md §三） ----------
@app.post("/api/conversations/import")
async def conversations_import(request: Request):
    """批次B 旧记录导入：body {messages:[{role,content,sources?},…], passcode?}。

    - 白名单重建=只认 role/content/sources 三键（transient/富显示字段端侧已
      剥），服务端再整单校验（feedback rating 同风格：严格白名单整单拒，不做
      部分接受），畸形一律 400 {"error":"bad_request"}：body 非 JSON/非对象；
      messages 缺失/非 list/空 list；条目非对象；role 越白名单（只认
      user/assistant）；content 非 string/空串/单条 >16000 字符；条数 >200；
      sources 非 list 或含非 dict 项/单条 sources >20 项。
    - create_conversation(device_id,'本地历史（导入）')（标题固定不随首条内容
      生成）+逐条 append_message（user 条 sources_json 恒 None；assistant 条
      合法 sources 则 json.dumps 存）；零 LLM 调用；updated_at 由
      append_message 内联 touch，导入毕即列表最新。
    - 会话挂本 device（_ensure_device 种 cookie 同三端点）；200
      {"ok":true,"id":会话id}；不防重复导入（端侧标记键防重弹，快照键兜底）。
    - journal 只打 [import] ip= n=条数 conv= id（消息内容/sources 绝不入日志）。"""
    if not _conversations_enabled():
        return JSONResponse({"error": "not_found"}, status_code=404)
    ip = _client_ip(request)
    if not await asyncio.to_thread(_store().conv_rate_ok, ip, CONV_RATE_LIMIT, CONV_RATE_WINDOW_S):
        return JSONResponse({"error": "rate_limited", "retry_after_s": 60},
                            status_code=429)
    resp401 = await _conv_auth(request)
    if resp401 is not None:
        return resp401
    try:
        body = await request.json()  # _conv_auth 已消费 body（starlette 缓存，照 feedback 先例）
    except Exception:
        return JSONResponse({"error": "bad_request"}, status_code=400)
    if not isinstance(body, dict):  # JSON 数组等非对象 body → 400，防 .get 裸炸
        return JSONResponse({"error": "bad_request"}, status_code=400)
    msgs = body.get("messages")
    if not isinstance(msgs, list) or not msgs:
        return JSONResponse({"error": "bad_request"}, status_code=400)
    if len(msgs) > IMPORT_MAX_MESSAGES:
        return JSONResponse({"error": "bad_request"}, status_code=400)
    clean = []
    for m in msgs:
        if not isinstance(m, dict):
            return JSONResponse({"error": "bad_request"}, status_code=400)
        role, content = m.get("role"), m.get("content")
        if role not in ("user", "assistant"):
            return JSONResponse({"error": "bad_request"}, status_code=400)
        if not isinstance(content, str) or not content:
            return JSONResponse({"error": "bad_request"}, status_code=400)
        if len(content) > IMPORT_MSG_MAX_CHARS:
            return JSONResponse({"error": "bad_request"}, status_code=400)
        sources = m.get("sources")
        if sources is not None and (
                not isinstance(sources, list)
                or len(sources) > IMPORT_MSG_SOURCES_MAX
                or any(not isinstance(s, dict) for s in sources)):
            return JSONResponse({"error": "bad_request"}, status_code=400)
        clean.append((role, content, sources))

    # ---- F线C·P4（评审 2026-10-15 立改）：import 旁路挂载 pii_mask——user 条复用
    # /api/chat 同款 apply_to_messages（全仓挂载自此两处）。mask 态四类字段掩码后
    # 才落库；log_only（默认态）只打 [pii_mask] 观测行、消息原样返回=落库内容零
    # 变化；off/模块缺席/任何异常=fail-open 原样放行（语义与 chat 挂点逐字对齐；
    # assistant 条是端侧带回的本机生成物，apply_to_messages 按设计不动）。 ----
    if pii_mask is not None:
        _masked = pii_mask.apply_to_messages(
            [{"role": r, "content": c} for r, c, _src in clean],
            pii_mask.resolve_mode(CONFIG))
        clean = [(m["role"], m["content"], src)
                 for m, (_r, _c, src) in zip(_masked, clean)]
    dev = _device_id_from(request)
    store = _store()
    conv_id = await asyncio.to_thread(store.create_conversation, dev, IMPORT_CONV_TITLE)
    for role, content, sources in clean:
        # user 条 sources 恒 None（端侧本就丢弃 user 条 sources；服务端同口径不存）
        src_json = (json.dumps(sources, ensure_ascii=False)
                    if role == "assistant" and sources else None)
        await asyncio.to_thread(store.append_message, conv_id, role, content, src_json)
    print(f"[import] ip={ip} n={len(clean)} conv={conv_id}", flush=True)
    resp = JSONResponse({"ok": True, "id": conv_id})
    _ensure_device(request, resp, dev)
    return resp


# ---------- 二期批次C C1：会话重命名端点（PATCH /api/conversations/{conv_id}；
# 门序照抄三会话端点=开关 404→conv_hits 同账 429→_conv_auth 401→id 域 404→
# 归属 404；判据=运营/前端二期-批次C-20261003/判据预登记.md §一） ----------
@app.patch("/api/conversations/{conv_id}")
async def conversation_rename(conv_id: str, request: Request):
    """C1 会话重命名：body {"title":...}，成功 {"ok":true}（不回显 title——
    前端本地已置，对齐 DELETE 形态）。

    - title 口径（strip 后 1-100）：非 string（缺键/数字/数组/对象）→ 400
      bad_request（显式类型校验不宽容 coerce——title 是载荷本体，非 feedback
      的附属字段）；strip 后空 → 400（截断兜不住空串，防误触把标题清空）；
      超 100 → 服务端截断到 100 入库（不 400——宽容先例：feedback note 截
      500/create 标题截 24，400 会逼前端先做长度校验多一拍交互）。
    - rename 只 UPDATE title 不 touch updated_at/last_msg_id（排序键=消息
      时刻，改名不是消息，不得扰动 C2 最近活跃序）；不存在/非本 device →
      404 {"error":"not_found"}（归属校验进 store 方法 WHERE，照 delete 形态）。
    - journal 只打 [conv] rename ip= ok=（标题内容绝不入日志——对齐 feedback
      的 note 纪律）。"""
    if not _conversations_enabled():
        return JSONResponse({"error": "not_found"}, status_code=404)
    ip = _client_ip(request)
    if not await asyncio.to_thread(_store().conv_rate_ok, ip, CONV_RATE_LIMIT, CONV_RATE_WINDOW_S):
        return JSONResponse({"error": "rate_limited", "retry_after_s": 60},
                            status_code=429)
    resp401 = await _conv_auth(request)
    if resp401 is not None:
        return resp401
    dev = _device_id_from(request)
    try:
        cid = int(str(conv_id).strip())
    except ValueError:
        return JSONResponse({"error": "not_found"}, status_code=404)
    if not (1 <= cid <= 2**63 - 1):
        # 超 SQLite 64 位绑定域的巨整数 id 一律 404（防未处理 OverflowError 500）
        return JSONResponse({"error": "not_found"}, status_code=404)
    try:
        body = await request.json()  # _conv_auth 已消费 body（starlette 缓存，同 feedback 双解析）
    except Exception:
        return JSONResponse({"error": "bad_request"}, status_code=400)
    if not isinstance(body, dict):  # JSON 数组等非对象 body → 400，防 .get 裸炸
        return JSONResponse({"error": "bad_request"}, status_code=400)
    title = body.get("title")
    if not isinstance(title, str):
        return JSONResponse({"error": "bad_request"}, status_code=400)
    title = title.strip()[:RENAME_TITLE_MAX]
    if not title:
        return JSONResponse({"error": "bad_request"}, status_code=400)
    ok = await asyncio.to_thread(_store().rename_conversation, cid, dev, title)
    if not ok:
        return JSONResponse({"error": "not_found"}, status_code=404)
    print(f"[conv] rename ip={ip} ok=1", flush=True)
    resp = JSONResponse({"ok": True})
    _ensure_device(request, resp, dev)
    return resp


# ---------- 批次E：反馈端点（E1，默认启用；鉴权同三会话端点门，限速复用
# conv_hits 小表——反馈是低频动作，与三会话端点合计 60 次/分每 IP 足用，
# 分表各管各账纪律不动：不占 /api/chat 的 rate_hits 预算） ----------
@app.post("/api/feedback")
async def feedback(request: Request):
    """E1 反馈闭环（默认启用）：body {trace_id?, rating, note?, passcode?}。

    - rating 白名单 up/down（缺失/其余 → 400 {"error":"bad_request"}）；note 截
      500 字符；trace_id 可选（前端取 /api/chat SSE 响应头 X-QA-Trace-Id 回填）；
      conv_id 取请求头 X-QA-Conv-Id（可选，非整数/超 SQLite 64 位绑定域 → NULL，
      只作运营关联线索，不做归属校验——反馈载荷不含会话内容，无越界面）。
    - 鉴权=_conv_auth 同门（会话 cookie / body passcode / X-QA-Passcode 头），
      401 形态对齐 /api/chat；限速复用 conv_hits（429 形态对齐三会话端点）。
    - journal 只打 [feedback] rating= trace= conv=（note 内容绝不入日志）。"""
    ip = _client_ip(request)
    if not await asyncio.to_thread(
            _store().conv_rate_ok, ip, CONV_RATE_LIMIT, CONV_RATE_WINDOW_S):
        return JSONResponse({"error": "rate_limited", "retry_after_s": 60},
                            status_code=429)
    resp401 = await _conv_auth(request)
    if resp401 is not None:
        return resp401
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "bad_request"}, status_code=400)
    if not isinstance(body, dict):  # JSON 数组等非对象 body → 400，防 .get 裸炸
        return JSONResponse({"error": "bad_request"}, status_code=400)
    rating = body.get("rating")
    if rating not in FEEDBACK_RATINGS:
        return JSONResponse({"error": "bad_request"}, status_code=400)
    trace_id = str(body.get("trace_id") or "").strip()[:FEEDBACK_TRACE_MAX] or None
    note = str(body.get("note") or "").strip()[:FEEDBACK_NOTE_MAX] or None
    conv_id = None
    _raw_cid = str(request.headers.get("x-qa-conv-id") or "").strip()
    if _raw_cid:
        try:
            _cid = int(_raw_cid)
        except ValueError:
            _cid = None
        if _cid is not None and 1 <= _cid <= 2**63 - 1:
            conv_id = _cid   # 巨整数头静默落 NULL（防 SQLite 绑定域 OverflowError）
    await asyncio.to_thread(
        _store().add_feedback, trace_id, rating, note, conv_id)
    # F21（评审 2026-10-15）：trace 原样入 journal 可被 JSON 换行伪造日志行——套
    # _q_log_field 清洗（仅洗 journal 行，存储值不动；trace_id 真值 8 hex 无损）。
    print(f"[feedback] ip={ip} rating={rating} trace={_q_log_field(trace_id or '-')} "
          f"conv={conv_id if conv_id is not None else '-'}", flush=True)
    resp = JSONResponse({"ok": True})
    _ensure_device(request, resp)
    return resp


# ---------- 差评回流供弹线（扩源形状战 v5 计划 §2 决策位⑥，2026-10-17 施工；
# 纯旁路增量：不触 /api/chat 链路、不触 E1 /api/feedback 与 feedback 表、
# 不触 M1 锚定段/M5 分诊/S1 词面通道；鉴权与限速沿 E1 点击路径先例） ----------
FEEDBACK_BAD_Q_MAX = 2000                # 差评回流 题面截长（字符，前端同值预截）
FEEDBACK_BAD_A_MAX = 4000                # 差评回流 答面截长（字符，答面全文截断制）
FEEDBACK_BAD_REASONS = ("missed_point", "too_generic", "no_source", "other")
FEEDBACK_BAD_LOG = os.path.join(BASE_DIR, "建库", "logs", "差评回流.jsonl")
_feedback_bad_lock = threading.Lock()    # jsonl 追加串行化（_rerank_log_lock 同款）


def _feedback_bad_enabled() -> bool:
    """config 顶层键 feedback_bad_enabled（**默认 true**——采集系观察面非
    行为面：只旁路记账不动问答链路，与 rerank_log_enabled 默认开同姿态；
    false=端点 404 退场，零落盘零打点零限速记账，与键不存在逐字节一致）。"""
    return bool(CONFIG.get("feedback_bad_enabled", True))


def _feedback_bad_path() -> str:
    """落盘路径（config 顶层键 feedback_bad_path 可配；坏值/空串回默认
    建库/logs/差评回流.jsonl——越界回默认口径同 rerank_log 族）。"""
    p = CONFIG.get("feedback_bad_path")
    if isinstance(p, str) and p.strip():
        return p.strip()
    return FEEDBACK_BAD_LOG


def _feedback_bad_append(rec) -> bool:
    """差评回流 jsonl 追加一行（建目录自愈、锁内追加、写失败只返 False
    绝不抛——_rerank_ledger_append 同款兜底纪律）。"""
    p = _feedback_bad_path()
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with _feedback_bad_lock:
            with open(p, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return True
    except OSError:
        return False


@app.post("/api/feedback/bad")
async def feedback_bad(request: Request):
    """差评回流采集点（决策位⑥；默认启用）：body {question, answer,
    reasons?, trace_id?, passcode?}。

    - question/answer 必填字符串（题面原文/答面全文），服务端截长
      2000/4000 字符；reasons 可选码表白名单（missed_point=没答到点/
      too_generic=太宏观/no_source=缺出处/other=其他），非白名单项静默
      丢弃、去重保序、缺省空表；
    - 鉴权=_conv_auth 同门（E1 点击路径先例：会话 cookie / body passcode /
      X-QA-Passcode 头），401 形态对齐 /api/chat；限速复用 conv_hits 小表
      （与三会话端点+E1 合计 60 次/分每 IP，不占 /api/chat 预算）；
    - feedback_bad_enabled=false → 404 {"error":"not_found"}（限速账也不
      记=真零行为；前端按 404 收起采集点提示未启用）；
    - 落盘=jsonl 追加（路径 feedback_bad_path 可配，默认
      建库/logs/差评回流.jsonl），字段最小化={ts, conv_id, trace_id,
      question, answer, reasons}——**不采任何用户身份信息**（无 IP/UA/
      device/账号面；PII 最小化条款，见施工说明）；写失败 500
      {"error":"persist_failed"}；
    - journal 只打 [feedback_bad] ip= rating=down trace= conv= reasons=
      （题面/答面内容绝不入日志——E1 note 纪律同款）。"""
    ip = _client_ip(request)
    if not _feedback_bad_enabled():
        return JSONResponse({"error": "not_found"}, status_code=404)
    if not await asyncio.to_thread(
            _store().conv_rate_ok, ip, CONV_RATE_LIMIT, CONV_RATE_WINDOW_S):
        return JSONResponse({"error": "rate_limited", "retry_after_s": 60},
                            status_code=429)
    resp401 = await _conv_auth(request)
    if resp401 is not None:
        return resp401
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "bad_request"}, status_code=400)
    if not isinstance(body, dict):  # JSON 数组等非对象 body → 400，防 .get 裸炸
        return JSONResponse({"error": "bad_request"}, status_code=400)
    question = body.get("question")
    answer = body.get("answer")
    if not isinstance(question, str) or not question.strip() \
            or not isinstance(answer, str) or not answer.strip():
        return JSONResponse({"error": "bad_request"}, status_code=400)
    question = question.strip()[:FEEDBACK_BAD_Q_MAX]
    answer = answer.strip()[:FEEDBACK_BAD_A_MAX]
    reasons = []
    raw_reasons = body.get("reasons")
    if isinstance(raw_reasons, list):
        for r in raw_reasons:
            if isinstance(r, str) and r in FEEDBACK_BAD_REASONS \
                    and r not in reasons:
                reasons.append(r)
    trace_id = str(body.get("trace_id") or "").strip()[:FEEDBACK_TRACE_MAX] or None
    conv_id = None
    _raw_cid = str(request.headers.get("x-qa-conv-id") or "").strip()
    if _raw_cid:
        try:
            _cid = int(_raw_cid)
        except ValueError:
            _cid = None
        if _cid is not None and 1 <= _cid <= 2**63 - 1:
            conv_id = _cid   # 巨整数头静默落 NULL（防 SQLite 绑定域同款口径）
    rec = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "conv_id": conv_id,
           "trace_id": trace_id, "question": question, "answer": answer,
           "reasons": reasons}
    if not await asyncio.to_thread(_feedback_bad_append, rec):
        print(f"[feedback_bad] ip={ip} write_error=1", flush=True)
        return JSONResponse({"error": "persist_failed"}, status_code=500)
    print(f"[feedback_bad] ip={ip} rating=down "
          f"trace={_q_log_field(trace_id or '-')} "
          f"conv={conv_id if conv_id is not None else '-'} "
          f"reasons={','.join(reasons) if reasons else '-'}", flush=True)
    resp = JSONResponse({"ok": True})
    _ensure_device(request, resp)
    return resp


# ---------- 前端批次0：Vue 构建产物服务面（dist 优先，缺件回退旧 static 单页） ----------
# 构建产物在 frontend/dist/（并行批次产出）；本模块导入时判定一次：dist/index.html
# 存在→启用，否则回退 static/index.html（旧件保留作回退位）。判定结果打一行
# [startup] frontend=dist/legacy（见 lifespan），构建产物出现后重启即切换。
FRONTEND_DIST = os.path.join(BASE_DIR, "frontend", "dist")
if os.path.isfile(os.path.join(FRONTEND_DIST, "index.html")):
    INDEX_HTML = os.path.join(FRONTEND_DIST, "index.html")
    FRONTEND_MODE = "dist"
else:
    INDEX_HTML = os.path.join(BASE_DIR, "static", "index.html")
    FRONTEND_MODE = "legacy"


class _ImmutableAssets(StaticFiles):
    """StaticFiles 不支持自定义响应头：子类覆写 file_response 给 /assets/
    资产统一加 immutable 长缓存（Vite 构建产物文件名带内容指纹，内容变即换名）。"""

    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return resp


# 仅当 dist/assets/ 存在时挂载（StaticFiles 实例化即校验目录存在）；未挂时
# /assets/* 落 FastAPI 默认 404，不炸服务
if os.path.isdir(os.path.join(FRONTEND_DIST, "assets")):
    app.mount("/assets",
              _ImmutableAssets(directory=os.path.join(FRONTEND_DIST, "assets")),
              name="assets")


@app.get("/")
async def index(request: Request):
    # index 不缓存（部署后即取新）；/assets/ 指纹资产走上面的 immutable 长缓存
    # 批次D：GET / 是 device cookie 首要种植点（页面加载先于一切 API 调用）。
    # 最小侵入实现：FileResponse 也是 Response 子类，建好后 set_cookie 再返回
    # （不转 JSONResponse/不换 Response 形态，dist/legacy 双态行为零变化）。
    resp = FileResponse(INDEX_HTML, headers={"Cache-Control": "no-cache"})
    _ensure_device(request, resp)  # 无数据挂接，种下即用（cookie 值即后续请求的 dev）
    return resp


# 公安备案官方电子图标（用户 2026-09-28 提供），页脚公安备案号前缀；长缓存因文件随版本换名
@app.get("/static/beian-police.png")
async def beian_police_png():
    return FileResponse(os.path.join(BASE_DIR, "static", "beian-police.png"),
                        media_type="image/png",
                        headers={"Cache-Control": "public, max-age=604800"})


@app.post("/api/chat")
async def chat(request: Request):
    req_t0 = time.time()  # 请求开始（TTFB=首个 delta 时刻-此刻）
    trace_id = _new_trace_id()  # E1 trace：本请求全链路贯穿 id（见件头注）
    if not API_KEY:
        return JSONResponse({"error": "server_no_key"}, status_code=500)
    ip = _client_ip(request)
    if not await _rate_ok(ip):
        return JSONResponse({"error": "rate_limited", "retry_after_s": 60}, status_code=429)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "bad_json"}, status_code=400)
    if not isinstance(body, dict):  # JSON 数组等非对象 body→400，防 .get 裸炸 500（F2，评审 2026-10-15，照 login 形态）
        return JSONResponse({"error": "bad_json"}, status_code=400)

    # ---- 鉴权（批2 双轨，设计稿 §2）：cookie 会话 → body passcode ----
    auth_via = None
    token = request.cookies.get(SESSION_COOKIE, "")
    if token and await asyncio.to_thread(_store().get_session, token):
        auth_via = "cookie"
        # B311 消音理由（评审 S4 豁免）：决策采样非密码学——惰性过期清理的概率
        # 触发；口令/令牌面一律 secrets+PBKDF2（hash_passcode.py 零 random 已亲验）。
        if random.random() < 0.125:  # 校验路径上的概率性惰性过期清理（§1，不做后台线程）  # nosec B311
            await asyncio.to_thread(_store().purge_expired_sessions)
    else:
        token = None
        supplied = str(body.get("passcode") or "").strip()
        if _passcode_gate():
            if not supplied:
                # 无任何可用凭据（cookie 缺失/失效且未带口令）：前端据此弹口令栏
                return JSONResponse({"error": "auth_expired"}, status_code=401)
            if not CONFIG.get("passcode_body_enabled", True):
                # 双轨收口开关（默认 true=双轨期；false 时 body 口令不再放行）
                return JSONResponse({"error": "login_required"}, status_code=401)
            if not await _passcode_ok(supplied):
                return JSONResponse({"error": "bad_passcode"}, status_code=401)
            auth_via = "body"  # [chat] 日志统计 body-passcode 命中，归零后可收口

    # 校验并裁剪对话历史
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        return JSONResponse({"error": "bad_messages"}, status_code=400)
    messages = messages[-CONFIG["max_history_messages"]:]
    # ---- F线C 输入侧止血（PII 掩码挂载，2026-10-14；P3 换序 2026-10-15 评审
    # 立改：掩码挪到字符截断**之前**——先对整段原文掩码再截断，跨 8000 边界的
    # 身份证/手机号不再被切出残段漏掩（残段含区划+出生段，四正则均不命中）。
    # 挂点仍=一切下游消费〔session 落库/会话双写/检索查询/LLM payload/q= 摘要〕
    # 之前。log_only 默认态只打 [pii_mask] 命中观测行（零原文）不改消息，检测
    # 面从截断后文本变为截断前全文（跨边界实体整段可见=观测增强）；mask 态
    # 下游拿到掩码后截断形态（total 计数/413 判定同基于掩码后文本）；off 态
    # 零动作。模块缺席/任何异常=fail-open 原样放行（apply_to_messages 内部
    # 已兜底：非 dict/非 user/非 str 条目跳过，未校验输入安全且不污染原对象）。 ----
    if pii_mask is not None:
        messages = pii_mask.apply_to_messages(
            messages, pii_mask.resolve_mode(CONFIG), trace_id=trace_id)
    # 截断口径（2026-09-28）：input_limit_unit=tokens 时按 token 口径截断/计量；
    # 默认 chars 分支=现行表达式原样（逐字节不变）
    tok_unit = _input_unit(CONFIG) == "tokens"
    if tok_unit:
        _ensure_token_counter()
    clean = []
    total = 0
    for m in messages:
        if not isinstance(m, dict):
            return JSONResponse({"error": "bad_messages"}, status_code=400)
        role, content = m.get("role"), m.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str) or not content.strip():
            return JSONResponse({"error": "bad_messages"}, status_code=400)
        if tok_unit:
            content = truncate_to_tokens(content, CONFIG["max_input_chars"])
            total += count_tokens(content)
        else:
            content = content[: CONFIG["max_input_chars"]]
            total += len(content)
        clean.append({"role": role, "content": content})
    if clean[-1]["role"] != "user":
        return JSONResponse({"error": "bad_messages"}, status_code=400)
    if total > CONFIG["max_total_input_chars"]:
        return JSONResponse({"error": "input_too_long"}, status_code=413)

    # ---- F线 CD2 毕业季探测器 log-only 标注（2026-10-14）：对末条 user 消息
    # （pii_mask 之后=掩码后形态，职业向词面不受四类字段掩码影响）判一次
    # 职业向；on 态标 career_field=hit|-，off/模块缺席/任何异常=空（[chat] 不打
    # career= 字段，行为与既往逐字节一致——fail-open 纯本地计算零网络） ----
    career_field = ""
    if career_detect is not None and career_detect.resolve_mode(CONFIG) == "on":
        try:
            career_field = ("hit" if career_detect.is_career_question(
                clean[-1]["content"]) else "-")
        except Exception:
            career_field = ""

    # cookie 会话：更新 last_seen 并把裁剪后上下文落 msgs_json（§1，≤max_history_messages）
    if token:
        await asyncio.to_thread(
            _store().touch_session, token,
            json.dumps(clean, ensure_ascii=False))

    # ---- 批次D：多会话历史双写·user 侧（conversations_enabled=false 时跳过双写，
    # device cookie 仍种——回退键只关功能面不关设备身份面）。dev 在开关外解析：
    # 最终 StreamingResponse 需要用它补种 cookie。 ----
    dev = _device_id_from(request)
    conv_id = None
    if _conversations_enabled():
        try:
            conv_id = await _conversation_writeback(
                _store(), dev, request.headers.get("x-qa-conv-id"),
                clean[-1]["content"],
                regen=(request.headers.get("x-qa-regen") or "").strip() == "1")
        except Exception as e:  # 双写任何失败绝不影响主链路（降级纪律同 rag）
            print(f"[conv] user 侧落库失败 err={type(e).__name__}", flush=True)

    # ---- U线 M5 无问句粘贴分诊（2026-10-17）：挂点=会话双写之后、RAG 检索
    # 之前（设计件 §4.1——粘贴轮照常入会话历史，下一轮分诊应答可拼前文；
    # 触发轮省一次检索嵌入+一次注定宏观的生成）。计分对象=末条 user 掩码
    # 截断后文本（与下游一致）；键关=本块整段不进（§4.3 关态零行为）。
    # 打点禁记题面：只记 len/score/臂名。
    # 修复窗 2026-10-26 ①②④（过程日志 238⑤）：①祈使臂放行（检测器内生效，
    # 此处补对照分打点）；②同会话分层=首触原罐头/次触出路文案/三触起直接
    # 放行该轮；④[paste_triage] 行增 n=/key=/act= 三字段（触发计数/会话键/
    # 放行-拦截态：block|block_exit|release_imperative|release_repeat），
    # 仅结构臂过阈才打（放行与否都打，非触发轮零噪声照旧）。----
    paste_triaged = False
    _pt_act, _pt_n = "", 0  # ④观测位：本轮处置态/同会话第 n 次触发（含本轮）
    if _paste_triage_enabled():
        _pt_q = clean[-1]["content"]
        _pt_lo, _pt_hi = _paste_triage_len_bounds()
        paste_triaged, _pt_score, _pt_arms = _paste_triage_hit(
            _pt_q, _paste_triage_threshold(), _pt_lo, _pt_hi)
        # 对照分：关①臂跑一次（纯本地）——结构臂是否过阈+过阈分值，供放行
        # 态打点（gated 调用在放行轮返 score=0，无观测价值）
        _pt_ufired, _pt_uscore, _pt_uarms = _paste_triage_hit(
            _pt_q, _paste_triage_threshold(), _pt_lo, _pt_hi,
            imperative_gate=False)
        if _pt_ufired:
            with _PASTE_TRIAGE_SEEN_LOCK:
                if len(_PASTE_TRIAGE_SEEN) > 4096:
                    _PASTE_TRIAGE_SEEN.clear()
                _pt_key = f"dev:{dev[:8]}" if dev else "na"
                _pt_n = _PASTE_TRIAGE_SEEN.get(_pt_key, 0) + 1
                _PASTE_TRIAGE_SEEN[_pt_key] = _pt_n
            if not paste_triaged:
                _pt_act = "release_imperative"     # ①祈使臂放行（本应触发）
            elif _pt_n >= 3:
                paste_triaged = False              # ②三触起直接放行该轮
                _pt_act = "release_repeat"
            elif _pt_n == 2:
                _pt_act = "block_exit"             # ②次触=出路文案
            else:
                _pt_act = "block"                  # 首触=原罐头
            print(f"[paste_triage] fired={1 if paste_triaged else 0} "
                  f"len={len(_pt_q)} score={_pt_uscore} "
                  f"arms={','.join(_pt_uarms) or '-'} n={_pt_n} "
                  f"key={_pt_key} act={_pt_act}", flush=True)

    # RAG 检索（enabled 且构造出非空查询才尝试；任何失败退裸答，绝不影响主链路）
    rag_state, evidence, rag_sources = "off", None, None
    rag_q, rag_top1 = "", None  # 打点：清洗截断后的查询摘要 + 最高相关分（hit 时有值）
    query = ""  # 检索查询（rag_service 在位才构造；hit 分支的批A judge 复用）
    gate_detail = {"state": "off"}  # E1 trace：gate 判定细节（分态在下方覆写）
    search_dur_ms = None  # E1 检索计时（F线B 2026-10-14）：服务面检索跨度（ms，单调钟）；
                          # rag 侧 [rag-search] 行另给同源观测（含 outcome 词表）——双通道
    route_res, rt_field = None, None  # 期 1 路由：classify 结果 + [chat] rt= 字段（关=None 零漂移）
    if paste_triaged:
        # M5 分诊态：不检索不构造查询（q= 空打点、无 top1，[chat] rag=
        # paste_triage 与 miss 同形态——deploy_check parse_chat_line 只认
        # 既有五态，本行不入判不致误判）
        rag_state = "paste_triage"
        gate_detail = {"state": "paste_triage"}
    elif rag_service is not None:
        rag_state = "miss"
        gate_detail = {"state": "miss"}
        query = build_retrieval_query(clean)  # 末条 user 过短则拼前文，防检索查询退化为几个字
        rag_q = _q_log_field(query)
        if query:
            # 期 1 路由分类器（route_enabled 门控，默认关=零调用零打点）：对拼接后
            # query 判一次，mq 变体在 rag 侧继承本判定不重复分类；classify 恒不抛出，
            # 外层再兜异常（任何失败=route_res None=无路由现行行为）
            _rc = _route_config(CONFIG)
            if _rc["enabled"]:
                try:
                    route_res = route_domain.classify(
                        query, min_confidence=_rc["min_confidence"],
                        conflict_policy=_rc["conflict_policy"],
                        doc_direct_enabled=_rc["doc_direct"])
                except Exception:
                    route_res = None
                if route_res is not None:
                    # [rag-route] 打点（format_log_line 固定格式，不含题面文本——
                    # 纪律同 [rag-hybrid]；rag 侧检索后兜底会再打 fallback=1 同格式行）
                    print(route_domain.format_log_line(route_res), flush=True)
                    rt_field = _route_rt_field(route_res)
            try:
                _search_t0 = time.monotonic()  # E1 检索计时起表（F线B；单调钟）
                # trace_id 经 ContextVar 进 worker 线程：retrieve 内部 rag.py 打点
                # 由 _rag_trace_log 路由加 [trace:xxx] 前缀（finally 复位防泄漏）
                _tk = _trace_id_var.set(trace_id)
                try:
                    # history=clean（2026-10-24 mq condense 施工·案甲历史传入位）：
                    # 裁剪后 messages（user+assistant，≤max_history_messages）随
                    # query 传入 rag；**仅 mq_condense_enabled 且有前史时被消费**
                    # ——键关/单轮=零调用零行为差（L0/L1 断言面），q0 构造不动。
                    if route_res is not None:
                        result = await asyncio.to_thread(
                            rag_service.retrieve, query, route_res, clean)
                    else:
                        result = await asyncio.to_thread(
                            rag_service.retrieve, query, None, clean)
                finally:
                    _trace_id_var.reset(_tk)
            except Exception:
                result = None
            # E1 检索计时收口：含 to_thread 调度开销的服务面跨度（用户所感检索时延）；
            # 异常路同收（except 已兜 result=None）。rerank 拒答闸在 trace 行之后，不计入。
            search_dur_ms = round((time.monotonic() - _search_t0) * 1000.0, 1)
            if isinstance(result, LowScoreResult):
                # 低分 off_topic：不注入证据、不下发 sources（top1=触发闸门的
                # 余弦原始分口径，阈值复验采集用；归因工具按 rag=low_score 识别）
                rag_state = "low_score"
                rag_top1 = result.cosine
                gate_detail = {"state": "low_score", "thr": result.threshold,
                               "observed": result.cosine}
            elif isinstance(result, CoverageMissResult):
                # 覆盖闸 off_topic（S1 治理丙，2026-09-28）：题面含库外域安全词形
                # 而证据集全缺该词——检索面零支撑的硬拒，行为与低分态同构（不注入
                # 证据、不下发 sources、先发 off_topic 事件再照常裸答流式），打点态
                # coverage_miss 与 low_score 严格区分（top1=闸前证据集最大余弦）
                rag_state = "coverage_miss"
                rag_top1 = result.cosine
                gate_detail = {"state": "coverage_miss", "words": list(result.words),
                               "thr": result.threshold, "observed": result.cosine}
            elif result is not None:
                evidence, rag_sources = result
                rag_state = "hit"
                if _source_tier_enabled() and rag_sources:
                    # G 徽标（备发包-20261012，默认关）：sources 纯增 source_tier
                    # 字段（SSE 事件/会话落库/恢复面同源共享——enrich 在
                    # conv_sources_json 组装与 yield 之前；trace topk/citation
                    # 判卷只认各自白名单键，零涉动）
                    _annotate_source_tier(rag_sources)
                gate_detail = {"state": "hit"}
                _scores = [s.get("score") for s in (rag_sources or [])
                           if isinstance(s.get("score"), (int, float))
                           and not isinstance(s.get("score"), bool)]
                rag_top1 = max(_scores) if _scores else None

    # 期 1 路由：gate_detail 增 route 键（分类生效才有；关断零增量=既有 trace
    # 形态逐字节一致。rag 侧检索后兜底不回写本键，其可观测面=[rag-route] 行）
    if route_res is not None:
        gate_detail["route"] = _route_trace_detail(route_res)

    # E1 trace ①检索完成行：top-k 摘要+rag_state+gate 判定（is_answer：服务面
    # sources 未承载答案类标记时为 null——建库侧 is_answer_chunk 口径需 section
    # 字段，服务装载（META_FIELDS）不带；sources 扩展该键后此处自动透传）
    _topk = []
    if rag_state == "hit":
        for _s in (rag_sources or []):
            _ia = _s.get("is_answer") if isinstance(_s, dict) else None
            _topk.append({"id": str((_s.get("id") if isinstance(_s, dict) else None) or ""),
                          "doc": str((_s.get("doc_id") if isinstance(_s, dict) else None) or ""),
                          "locator": str((_s.get("locator") if isinstance(_s, dict) else None) or ""),
                          "score": (_s.get("score") if isinstance(_s, dict)
                                    and isinstance(_s.get("score"), (int, float))
                                    and not isinstance(_s.get("score"), bool) else None),
                          "is_answer": bool(_ia) if isinstance(_ia, bool) else None,
                          "gate": "pass"})   # 入证据集；闸态轮不产出 sources（见 gate_detail）
    _trace_line(trace_id, {
        "stage": "retrieval", "ts": round(time.time(), 3), "rag": rag_state,
        "q": rag_q, "q_chars": len(query), "top1": rag_top1,
        "gate": gate_detail, "topk": _topk,
        # E1 检索计时（F线B 2026-10-14）：dur_s=obs_weekly 前向兼容位
        # （latency retrieval_dur_s 自动采用）；未测得（rag off/空查询）=null 不入统计
        "dur_s": (round(search_dur_ms / 1000.0, 3)
                  if search_dur_ms is not None else None)})

    # rerank log-only 影子探针（部署窗件2，2026-10-12，默认开）：检索完成后异步
    # fire-and-forget（守护线程，请求路径零等待）——只采数不打闸，绝不改检索
    # 结果/闸分/答案流（铁律见探针段头注；rag=miss 不 fire）。an_sources=hit 轮
    # 融合序 sources（U5 判官证据面=作答同源，传引用）
    _rerank_log_fire(rag_service, query, rag_state, trace_id,
                     an_sources=rag_sources)

    # rerank 行为级拒答拦截（0.75 档决策 2026-10-12；双键默认关=零增量）：hit
    # 路径同步第二信号——池 max < 阈值 → 转 rerank_refused 态（不注入证据、不下发
    # sources、off_topic 同构事件+裸答流式，与 low_score 家族同构）。fail-open
    # 铁律：cap/超时/任何异常一律放行（拦截面故障绝不挡答案）；月顶超=退化不拦。
    if rag_state == "hit" and _rerank_refusal_enabled() and (query or "").strip():
        _ref, _pmax, _gerr = await asyncio.to_thread(
            _rerank_gate_check, rag_service, query)
        _rerank_gate_trace(query, trace_id, _ref, _pmax, _gerr)
        if _ref:
            rag_state = "rerank_refused"
            gate_detail = {"state": "rerank_refused",
                           "thr": _rerank_refusal_threshold_for(query),
                           "observed": round(_pmax, 6) if _pmax is not None else None}
            evidence, rag_sources = None, []

    # U线 U5 形态B 消费面（2026-10-15）：enabled 时回答前查判官结论 LRU 缓存
    # （qhash16→verdict，纯 dict 查询 µs 级零等待）。缓存 verdict∈{不可答,
    # 不确定}→转既有 low_score 兜底形态（不注入证据/不下发 sources/off_topic
    # 同构事件/裸答流式——计划 §1.4 三态映射表，状态机零新增=复用 low_score
    # 态字；gate_detail src 键=归因面标记，不入状态机）；缓存 可答 或 miss=
    # 现状照旧（fail-open permissive——判官后置运行，novel 首问放行=形态B
    # 已知产品语义，计划 §2.5）。enabled=false=本块整段不进：缓存查询与判官
    # 调用全被开关闸死（行为零差铁律；回滚=单键 false+重启）。vac 面守卫=
    # 写入面同款面别路由（防 facet_cut 拨动后跨面消费）。
    if rag_state == "hit" and _answerability_params()["enabled"] \
            and _rerank_refusal_face(query) == "vac":
        _an_verdict = _answerability_cache_get(_rerank_probe_tag(query, 16))
        if _an_verdict in ("不可答", "不确定"):
            rag_state = "low_score"
            evidence, rag_sources = None, None
            gate_detail = {"state": "low_score", "src": "answerability",
                           "verdict": _an_verdict}

    # ---- 深度提升批A（默认全关；只在 hit 路径挂 judge，任何失败静默降级照常回答） ----
    cc_state, ab_state = "off", "off"   # [chat] 尾部字段：cc=off/skip/ok/err，ab=off/pass/insuff
    cc_armed, ab_reason, judge = False, None, None
    depth = _depth_config(CONFIG)
    if rag_state == "hit" and citation_check is not None and (
            depth["citation_check_enabled"] or depth["abstain_enabled"]):
        judge = _make_depth_judge(depth["citation_check_model"] or CONFIG["model"])
        if depth["abstain_enabled"] and citation_check.is_high_stakes_question(query):
            # A2：高危面题（精确数值/参数名/取值范围/表值类）先评证据充分性；
            # insufficient → 保守模板入 system + evidence_insufficient 事件先于 sources；
            # judge 超时/异常/畸形 → None=照常回答仅打日志（ab=pass）
            res = await asyncio.to_thread(
                citation_check.assess_evidence, query, evidence, judge,
                depth["abstain_timeout"])
            if isinstance(res, dict) and res.get("verdict") == "insufficient":
                ab_state = "insuff"
                ab_reason = str(res.get("reason") or "")
            else:
                ab_state = "pass"
                if res is None:
                    print(f"[abstain] ip={ip} judge 失败/超时，照常回答（ab=pass）", flush=True)
        if depth["citation_check_enabled"] and rag_sources:
            cc_state = "skip"   # 抽样未中/正文为空即止步于此（不打 judge）
            # B311 消音理由（评审 S4 豁免）：决策采样非密码学——引用抽检的概率触发。
            if random.random() < depth["citation_check_sample"]:  # nosec B311
                cc_armed = True

    # 意图缺口批甲（设计稿 v3-甲，2026-10-09 批）：通识标注触发三条件=方法论
    # 词表命中（当前轮题面）∧ rag=hit ∧ 非弃答互锁（评审 P3：A2 insuff 态恒
    # 不触发——与 evidence_insufficient 互斥不同现）。键默认关=零行为变化。
    # 2026-10-12 同现修复（过程日志 60⑤/642 在案）：三条件齐而窗内已含丙/ydt 行标
    # 证据（doc_id "YD/T" 前缀）→ 抑制标注（gap_supp）——v3 立标时库内只有规范
    # 条文，丙并入（2026-10-10）后"库内只有条文"前提不再恒真，标注文案
    # "非本库出处内容"在丙证据在席时为误挂；键关分支零进入=关态逐字节不变。
    gap_fire, gap_supp = False, False
    if (_insight_gap_note_enabled() and rag_state == "hit"
            and ab_state != "insuff" and _method_query_hit(clean)):
        if _ydt_evidence_in_window(rag_sources):
            gap_supp = True   # 候选成立但丙在席：抑制事件、打 supp 行（gen 内）
        else:
            gap_fire = True

    # system 追加段（P1 引用纪律 2026-09-29 默认关 + 批A A2 保守模板 + 批次E
    # E2 追问尾巴 2026-10-03 默认关）：三段全关时 extra=None（有证据则输出含
    # F18 围栏，无证据时才与既往逐字节一致）
    tail_on = _followup_tail_enabled()  # E2：本请求的尾巴开关（gen 闭包沿用）
    _extra_notes = []
    if depth["citation_discipline_enabled"] and evidence:
        _extra_notes.append(CITATION_DISCIPLINE_NOTE)
    if ab_state == "insuff":
        _extra_notes.append(ABSTAIN_SYSTEM_NOTE)
    if depth["answer_anchor_format"] == "evidence_first":
        # M1 锚定段（设计件 §6）：键开=无条件常开注入（无词表门无题型门，
        # 不得顺手加门）；围栏缺席时段首适用域自含=裸答态自然空转（§3.3）
        _extra_notes.append(M1_ANCHOR_NOTE)
    if tail_on:
        _extra_notes.append(FOLLOWUP_TAIL_NOTE)  # E2 指令段（恒最后：格式类指令）
    # 批次D：assistant 侧落库的 sources 载体（hit 轮=sources 数组 JSON 原文，恢复
    # 面与 SSE sources 事件同源；其余态 None）
    conv_sources_json = (json.dumps(rag_sources, ensure_ascii=False)
                         if rag_sources is not None else None)
    payload = {
        "model": CONFIG["model"],
        "messages": [{"role": "system", "content": _build_system_content(
            _system_prompt(), evidence,
            "\n\n".join(_extra_notes) or None)}] + clean,
        "stream": True,
        "stream_options": {"include_usage": True},
        "temperature": CONFIG.get("temperature", 0.7),
        "max_tokens": CONFIG.get("max_tokens", 2048),
        # qwen3 系兼容口默认开思考模式，正文预算被思考挤占，生产直答任务显式关闭（2026-10-07 生产 reasoning 占比 72% 实证）
        "enable_thinking": False,
    }
    _gen_seed = CONFIG.get("generation_seed")
    if isinstance(_gen_seed, int) and not isinstance(_gen_seed, bool):
        # 一致性收敛批（2026-10-13）：固定采样种子随请求上行（键缺省/非 int
        # 不传=旧行为逐字节不变）。定位=收敛采样面；百炼服务端非确定性仍在
        # （过程日志条目13：temp=0 亦不可复现），不承诺逐字节一致。
        payload["seed"] = _gen_seed

    async def gen():
        nonlocal cc_state  # 批A A1 收尾态（ok/err）要在 finally 的 [chat] 行可见
        t0 = time.time()
        usage = None
        ttfb = None  # 首 delta 时刻-请求开始（无 delta 的错误流收尾记 na）
        completed = False  # 服务端自然收尾（done/错误事件已发）＝非用户断流（§5 观测）
        answer_parts = []  # 批A A1：正文累计（引文忠实度校验的评审对象；E2 开时
        # 只累积已下发安全前缀=净文本——尾巴绝不进闸/不进回传/不落库，三处纪律
        # 共用这一份累计）
        tail_pending = ""   # E2：未判定安全的累积缓冲（含扣住的标记前缀重叠）
        tail_after = ""     # E2：标记出现后的截留文本（收尾解析 followups 用）
        tail_hit = False    # E2：标记已出现（进入截留收集态直到流结束）
        wb_text = None  # 批次D：assistant 侧落库文本（None=不落：断流/未到自然收尾）；
        # 自然收尾=完整回复（done）或错误消息（定案：错误 SSE 事件 JSON 原文落库，
        # 不做特判——前端恢复时按 content 自身的 error 形态呈现）；用户断流
        # （CancelledError）无"完整回复"，不落半截答案
        llm_status = "cancelled"  # E1 trace llm 行状态：默认断流，各收尾分支覆写
        # E1 trace：SSE 流首带 trace_id。用 SSE 规范注释行（": xxx"）而非 data 事件
        # 可选字段——前端 handle() 与既有测试均只认 data: 行（零影响），而既有测试
        # 对首数据事件（sources/off_topic/…）有逐字段精确断言，不进 data 事件体
        yield f": trace_id={trace_id}\n\n"
        if rag_state in ("low_score", "coverage_miss", "rerank_refused"):
            # 低分/覆盖闸/rerank 拦截 off_topic 信号先于流式正文（前端复用同一
            # 提示位，S1 治理丙与 rerank 拒答的新态沿用既有前端零改动——事件
            # 类型复用=零部署面；回答本身照常裸答流式，09-17"直接输出、不管"
            # 边界内，只改注不注入弱/零支撑证据）
            _ot_ev = {"type": "off_topic"}
            # 话术批（2026-10-16）：可选 note=按缺失主题的渠道引导（归类器
            # _off_topic_note；无命中零 note=旧事件形态逐字节兼容）。coverage_miss
            # 用 gate_detail.words（闸触发词在手）查表，其余态题面归类。
            _ot_note = _off_topic_note(query, gate_detail.get("words"))
            if _ot_note:
                _ot_ev["note"] = _ot_note
            yield _sse(_ot_ev)
        if ab_state == "insuff":
            # 批A A2：证据不足注意条先于 sources（前端复用 offtopic 提示位渲染；
            # reason 前端走 esc() 转义，服务端只压长度不转义——展示层职责分离）
            yield _sse({"type": "evidence_insufficient", "reason": ab_reason})
        if gap_fire:
            # 意图缺口批甲：确定性标注事件先于 sources（评审 P1：不依赖模型服从；
            # 前端复用 offtopic 提示位渲染 insight_gap 分支，随本批前端小改上产）。
            # 计数打点禁记题面（纪律同 [feedback]）；domain 仅观测用不参与触发。
            yield _sse({"type": "insight_gap", "note": INSIGHT_GAP_NOTE})
            _gap_dom = (rt_field or "-").split(":", 1)[0]
            print(f"[insight-gap] fired=1 domain={_gap_dom}", flush=True)
        elif gap_supp:
            # 2026-10-12 同现修复：候选成立但丙/ydt 证据在席 → 零事件零标注，
            # 只打抑制观测行。行标签 [insight-gap-supp] 系 obs GAP_RE
            # （\[insight-gap\]\s+）不可匹配形态（"gap" 后随 "-" 非 "]"）——
            # gap.lines/fired/触发率口径零漂移（obs 零破坏），抑制面纯增可 grep；
            # cause= 抑制分型（现值 ydt），domain 形态同 fired 行。
            _gap_dom = (rt_field or "-").split(":", 1)[0]
            print(f"[insight-gap-supp] cause=ydt domain={_gap_dom}", flush=True)
        if rag_sources:  # 出处先于流式正文下发（前端气泡底部出处条用）
            yield _sse({"sources": rag_sources})
        try:
            if paste_triaged:
                # M5 分诊分支（沿上方 off_topic 分支先例并列新增，设计件 §4.1）：
                # off_topic note 事件 → 罐头 delta → done 收尾，不进 LLM client
                # 块（省一次注定宏观的生成）。罐头正文=分诊文案主载体+防前端零
                # delta 收尾错误兜底；wb_text 落罐头正文（会话历史可拼前文）；
                # E2 追问尾巴同轮天然互斥（宿主是流式正文，分诊轮无标记）。
                # return 走 finally：assistant 落库/trace llm 行/[chat] 行照发。
                # 修复窗②（2026-10-26）：同会话第二次触发（act=block_exit）换
                # 出路文案（PASTE_TRIAGE_EXIT_*）——原罐头三选项全是语料域方向
                # 无简历出路、且三连一字不差（conv506 实证）；三触起 act=
                # release_repeat 已在触发位放行，不进本分支。
                _pt_exit = _pt_act == "block_exit"
                _pt_note = (PASTE_TRIAGE_EXIT_NOTE if _pt_exit
                            else PASTE_TRIAGE_NOTE)
                _pt_body = (PASTE_TRIAGE_EXIT_BODY if _pt_exit
                            else PASTE_TRIAGE_BODY)
                yield _sse({"type": "off_topic", "note": _pt_note})
                yield _sse({"delta": _pt_body})
                answer_parts.append(_pt_body)
                yield _sse({"done": True, "usage": None})
                wb_text = _pt_body
                llm_status = "done"
                completed = True
                return
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(connect=15, read=180, write=30, pool=15)
            ) as client:
                async with client.stream(
                    "POST", UPSTREAM, json=payload,
                    headers={"Authorization": f"Bearer {API_KEY}"},
                ) as resp:
                    if resp.status_code != 200:
                        detail = (await resp.aread()).decode("utf-8", "replace")[:300]
                        _err_ev = {"error": "upstream_error", "status": resp.status_code, "detail": detail}
                        yield _sse(_err_ev)
                        wb_text = json.dumps(_err_ev, ensure_ascii=False)  # 批次D：错误原文落库
                        llm_status = "error"
                        completed = True
                        return
                    # F7（评审 2026-10-15）：上游行迭代挂双守卫——①静默心跳：
                    # 上游行间静默超 SSE_IDLE_PING_S 秒补发 ": ping" SSE 注释行
                    # （前端 handle() 只认 data: 前缀=安全忽略，与 ": trace_id="
                    # 行同款契约；防将来经反代/CDN 空闲掐连）；②整体上限
                    # SSE_TOTAL_LIMIT_S：到点 raise httpx.TimeoutException 借下方
                    # 既有 except 降级收尾（事件/落库/打点三处同现行超时路）。
                    # 实现取"读 task 永不中途取消"形态：pending 行读取 task 与
                    # 空闲计时器 asyncio.wait 竞速，静默侧只发注释行——绝不用
                    # wait_for 裹 __anext__（超时取消后的流迭代重入安全性无
                    # 上游保证）；httpx read=180 超时/断连异常经 task.result()
                    # 原样重抛 → 既有 except 路径零变化。StopAsyncIteration
                    # 须就地接住（异步生成器体内冒出会被转 RuntimeError）。
                    _deadline = time.monotonic() + SSE_TOTAL_LIMIT_S
                    _line_it = resp.aiter_lines().__aiter__()
                    _next_line = asyncio.ensure_future(_line_it.__anext__())
                    try:
                        while True:
                            if time.monotonic() >= _deadline:
                                raise httpx.TimeoutException("sse total limit")
                            _idle = asyncio.ensure_future(
                                asyncio.sleep(SSE_IDLE_PING_S))
                            await asyncio.wait(
                                {_next_line, _idle},
                                return_when=asyncio.FIRST_COMPLETED)
                            _idle.cancel()
                            if not _next_line.done():
                                yield ": ping\n\n"   # 上游静默：保活注释行
                                continue
                            try:
                                line = _next_line.result()
                            except StopAsyncIteration:
                                break   # 流尽=与 async for 自然结束同构
                            _next_line = asyncio.ensure_future(
                                _line_it.__anext__())
                            if not line.startswith("data:"):
                                continue
                            data = line[5:].strip()
                            if data == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data)
                            except json.JSONDecodeError:
                                continue
                            if chunk.get("usage"):
                                usage = chunk["usage"]
                            for choice in chunk.get("choices", []):
                                # 思考段（reasoning_content）不外发，只转发正文 content
                                text = (choice.get("delta") or {}).get("content")
                                if not text:
                                    continue
                                if ttfb is None:
                                    ttfb = time.time() - req_t0
                                if not tail_on:
                                    # E2 关=现行路径逐字节一致（铁门：citation_sse 全绿）
                                    answer_parts.append(text)  # 批A A1 累计正文
                                    yield _sse({"delta": text})
                                    continue
                                # E2 开：delta 先并累积缓冲，扫描标记位置，只下发安全
                                # 前缀；标记出现后转截留收集态（标记跨 delta 拆半由
                                # _followup_holdback 扣住尾部防漏发）
                                if tail_hit:
                                    tail_after += text
                                    continue
                                tail_pending += text
                                _pos = tail_pending.find(FOLLOWUP_MARKER)
                                if _pos != -1:
                                    _safe = tail_pending[:_pos]
                                    tail_after = tail_pending[_pos + len(FOLLOWUP_MARKER):]
                                    tail_pending = ""
                                    tail_hit = True
                                else:
                                    _k = _followup_holdback(tail_pending)
                                    if len(tail_pending) <= _k:
                                        continue  # 整段都可能是标记前缀，全扣住
                                    _safe = tail_pending[:len(tail_pending) - _k]
                                    tail_pending = tail_pending[len(tail_pending) - _k:]
                                if _safe:
                                    answer_parts.append(_safe)
                                    yield _sse({"delta": _safe})
                    finally:
                        _next_line.cancel()   # 断流/异常/整体超时路径清 pending 读 task
            if tail_on and not tail_hit and tail_pending:
                # E2：流自然结束仍未见标记——扣住的悬尾是正文一部分（含被当成
                # 潜在标记前缀扣住的结尾字符），补发后净文本完整
                answer_parts.append(tail_pending)
                yield _sse({"delta": tail_pending})
                tail_pending = ""
            if depth["citation_gate_enabled"] and citation_gate is not None \
                    and rag_state == "hit" and evidence:
                # 引用程序闸（二期 Phase 2，2026-10-01 前端化）：正文收尾后程序核对
                # [证据N] 编号与「逐字摘录」命中——打日志并发 citation_gate 事件
                # （不改答案；前端出处条渲染核验 chip，字段全为程序值零注入面；
                # 生产 evidence 6000 字截断面会引入少量漏配噪声，消费口径见
                # 运营/拨键增补-裁判独立化-20260930.md 并入面）
                _g_ans = "".join(answer_parts).strip()
                if _g_ans:
                    # F8（评审 2026-10-15）：同步正则检测器挪 to_thread（同 A1 judge
                    # 先例），防 evidence 全文扫描阻塞事件循环
                    _g = await asyncio.to_thread(
                        citation_gate.check_text,
                        _g_ans, evidence, len(rag_sources or []))
                    print(f"[rag-gate] ip={ip} cites={_g['n_cites']} "
                          f"quotes={_g['n_quotes']} hard={_g['hard']} "
                          f"warn={_g['warn']} ok={1 if _g['ok'] else 0}", flush=True)
                    yield _sse({"type": "citation_gate", "ok": bool(_g["ok"]),
                                "cites": int(_g["n_cites"]), "quotes": int(_g["n_quotes"]),
                                "hard": int(_g["hard"]), "warn": int(_g["warn"])})
            if depth["citation_clause_check_enabled"] and citation_clause_check is not None \
                    and rag_state == "hit" and rag_sources:
                # 款号一致性检查挂点（排序优化四期 P2 #1a，2026-10-03，默认关）：正文
                # 收尾后纯程序核对答案声明款号 vs sources locator 对齐——打日志行
                # [citation-clause] face=decl|none oob=N 并发 citation_clause 事件。
                # 检测态绝不改答案（只观测语义同 citation_gate）；check_claims 恒不
                # 抛出，外层再兜一层 try=引用失败/异常放行+err（恒不抛出纪律）
                _cl_ans = "".join(answer_parts).strip()
                if _cl_ans:
                    try:
                        # F8（评审 2026-10-15）：同步检测器挪 to_thread（同上）
                        _cl = await asyncio.to_thread(
                            citation_clause_check.check_claims, _cl_ans, rag_sources)
                        print(f"[citation-clause] ip={ip} "
                              f"face={'decl' if _cl.get('n_claims') else 'none'} "
                              f"oob={len(_cl.get('oob') or [])} "
                              f"claims={int(_cl.get('n_claims') or 0)} "
                              f"err={_cl.get('err') or '-'}", flush=True)
                        yield _sse({"type": "citation_clause",
                                    "ok": bool(_cl.get("ok")),
                                    "claims": int(_cl.get("n_claims") or 0),
                                    "oob": len(_cl.get("oob") or []),
                                    "err": _cl.get("err")})
                    except Exception as _e:
                        print(f"[citation-clause] ip={ip} err={type(_e).__name__}（放行）",
                              flush=True)
            if cc_armed:
                # 批A A1：正文收尾后逐源引文忠实度校验；成功 → citation_check 事件
                # 先于 done；judge 失败/超时/畸形/空正文 → 静默跳过（cc=err/skip），
                # 绝不影响答案与 done（降级纪律同 rag）
                answer_text = "".join(answer_parts).strip()
                cc = None
                if answer_text:
                    cc = await asyncio.to_thread(
                        citation_check.check_citation, query, answer_text,
                        rag_sources, judge, depth["citation_check_timeout"])
                if isinstance(cc, dict) and cc.get("label") in citation_check.LABELS:
                    yield _sse({"type": "citation_check", "overall": cc["label"],
                                "per_source": cc.get("per_source") or []})
                    cc_state = "ok"
                else:
                    if answer_text:
                        cc_state = "err"
                        print(f"[citation] ip={ip} judge 失败/超时/畸形，静默跳过", flush=True)
                    else:
                        print(f"[citation] ip={ip} 空正文跳过校验（cc=skip）", flush=True)
            yield _sse({"done": True, "usage": usage})
            if tail_on:
                # E2：done 之后发追问建议事件（截留尾巴解析；解析不出合规条目
                # ——条数 0/>3、单条超 200 字符——整体丢弃不发，绝不以次充好）
                _fu = _parse_followup_items(tail_after)
                if _fu:
                    yield _sse({"type": "followups", "items": _fu})
            wb_text = "".join(answer_parts)  # 批次D：完整回复=净正文（E2 尾巴已剥除）
            llm_status = "done"
            completed = True
        except httpx.TimeoutException:
            _err_ev = {"error": "upstream_timeout"}
            yield _sse(_err_ev)
            wb_text = json.dumps(_err_ev, ensure_ascii=False)  # 批次D：错误原文落库
            llm_status = "timeout"
            completed = True
        except Exception as e:  # 兜底：只报异常类型，不外泄内部细节
            _err_ev = {"error": "upstream_error", "detail": type(e).__name__}
            yield _sse(_err_ev)
            wb_text = json.dumps(_err_ev, ensure_ascii=False)  # 批次D：错误原文落库
            llm_status = "error"
            completed = True
        finally:
            # 批次D：assistant 完整回复流收尾后落库（错误消息 content=错误 SSE 事件
            # JSON 原文；断流 wb_text=None 不落）。失败只打点不抛出（纪律同 rag）
            if conv_id is not None and wb_text is not None:
                try:
                    await asyncio.to_thread(
                        _store().append_message, conv_id, "assistant",
                        wb_text, conv_sources_json)
                except Exception as e:
                    print(f"[conv] assistant 侧落库失败 err={type(e).__name__}", flush=True)
            # cancelled=1：客户端断开（用户点停止/关页）导致协程被注入取消，
            # 未走到自然收尾——账单与 miss 归因不误读（§5）；CancelledError 是
            # BaseException，不会被上面 except Exception 吞掉
            # E1 trace ②LLM 完成行（模型/token 用量/耗时/收尾态）+ ③引用映射行
            #（hit 轮有正文才打：答案引用→chunk id 对齐）——均先于 [chat] 锚点行
            _trace_line(trace_id, {
                "stage": "llm", "ts": round(time.time(), 3),
                "model": CONFIG["model"], "status": llm_status,
                "dur_s": round(time.time() - t0, 2),
                "ttfb_s": round(ttfb, 2) if ttfb is not None else None,
                "in_tok": _usage_tok(usage, "prompt_tokens"),
                "out_tok": _usage_tok(usage, "completion_tokens"),
                "total_tok": _usage_tok(usage, "total_tokens")})
            _ans_text = "".join(answer_parts).strip()
            # F线Q 红线答案过滤器 log-only 观测（2026-10-14；冻结点3 终审决策③）：
            # 答案完成面（llm_status=done 且非空）六模式确定性检测，命中>0 打一行
            # [redline_filter]（trace/计数/模式名，零原文）——不改答案不影响任何
            # SSE 事件（检测先于 [chat] 锚点行落账，观测行序同 [rag-search] 惯例）；
            # off/模块缺席/任何异常=零动作零日志（fail-open，同 pii_mask 模式）。
            # enforce（句级拦截替换）归观察数据决策后另窗实现（v1 不挂）。
            if redline_filter is not None and llm_status == "done" and _ans_text:
                try:
                    # F8（评审 2026-10-15）：同步检测器挪 to_thread（同上）
                    await asyncio.to_thread(
                        redline_filter.observe_answer,
                        redline_filter.resolve_mode(CONFIG), _ans_text,
                        trace_id=trace_id)
                except Exception:
                    pass
            if rag_sources and _ans_text:
                _trace_line(trace_id, dict(
                    stage="citations", ts=round(time.time(), 3),
                    **_citation_alignment(_ans_text, rag_sources)))
            extras = ""
            if rag_state != "off":  # off=未启用 RAG：无查询无分数，不打（与现状逐字节一致）
                extras += f' q="{rag_q}"'
                if rag_state in ("hit", "low_score", "coverage_miss", "rerank_refused"):
                    # miss 时省略 top1（归因脚本按缺失处理，不误判）；low_score 的
                    # top1=触发闸门的余弦原始分（与 hit 的通道排序分口径差异在档）；
                    # coverage_miss 同带余弦观测值（闸前证据集最大余弦）；
                    # rerank_refused 保留原 hit 通道排序分（rerank 判定分在
                    # [rerank_gate] 行——deploy_check 核验同口径，2026-10-12）
                    extras += f" top1={'%.4f' % rag_top1 if rag_top1 is not None else 'na'}"
                # 批A 打点放既有字段之后（miss_attribution.py 只解析前段，尾部追加安全）：
                # cc=off 关/skip 未检（抽样未中/空正文/无 sources）/ok 已发事件/err judge 失败；
                # ab=off 关或非高危面/pass 充分或 judge 失败照常答/insuff 已发保守提示
                extras += f" cc={cc_state} ab={ab_state}"
            # 期 1 路由 rt= 键（设计稿 §2.3：如 rt=concept:f / rt=param:v；关断
            # 不打=既有 [chat] 行逐字节一致。尾部 KV 追加，miss_attribution
            # 逐字段解析只认已知键，未知尾键忽略——trace= 同款安全位）
            if rt_field:
                extras += f" rt={rt_field}"
            # trace= 尾附（E1）：[chat] 锚点行 ↔ trace 行的关联键（KV 尾部追加，
            # miss_attribution 逐字段解析只认已知键，未知尾键忽略）
            extras += f" trace={trace_id}"
            # 一致性反馈归因批（2026-10-13）：dev=/ua= 尾附——按设备归因"同题
            # 不同答"类反馈。dev=设备 cookie 短哈希前 8 位（防全 id 暴露）；ua
            # 去空白截 60 字符（防 KV 断词）；消费纪律=运营归因，不入对外报告。
            _ua = "_".join((request.headers.get("user-agent") or "").split())[:60] or "-"
            extras += f" dev={dev[:8]} ua={_ua}"
            # F线 CD2 毕业季探测器 log-only 标注（2026-10-14）：on 态尾附
            # career=hit|-（零原文零掩码纯标注）；off/缺席/异常=不打字段
            # （[chat] 行与既往逐字节一致。尾部 KV 追加，未知尾键忽略——
            # dev=/ua=/trace= 同款安全位）
            if career_field:
                extras += f" career={career_field}"
            _metrics_round(llm_status, usage)  # 3c：轮收尾打点（恒不抛出）
            print(f"[chat] ip={ip} auth={auth_via or 'none'} in_chars={total} rag={rag_state} "
                  f"ttfb={'%.2fs' % ttfb if ttfb is not None else 'na'} "
                  f"dur={time.time() - t0:.1f}s usage={usage}"
                  f" cancelled={'0' if completed else '1'}{extras}", flush=True)

    # 批次D：SSE 响应头附 X-QA-Conv-Id（additive，data 事件断言面零改动——前端
    # 续写凭此 id 显式带回 X-QA-Conv-Id 请求头；开关关/无会话时不带）；
    # 批次E E1：恒附 X-QA-Trace-Id（同款 additive——前端下轮提交 /api/feedback
    # 凭此头关联 trace_id，SSE data 事件面零改动）
    _sse_headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                    "X-QA-Trace-Id": trace_id}
    if conv_id is not None:
        _sse_headers["X-QA-Conv-Id"] = str(conv_id)
    _resp = StreamingResponse(gen(), media_type="text/event-stream", headers=_sse_headers)
    if DEVICE_COOKIE not in request.cookies:
        _set_device_cookie(_resp, dev)
    return _resp


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"
