#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""甲案试点入口 qa-pilot（pilot_server.py，2026-10-25 部署窗施工）

独立 FastAPI 应用：与生产 server.py 进程级/文件级双隔离——
- 零 import server.py / rag.py / 任何生产模块；零检索注入（不装载库/不挂 rag）；
- 配置=pilot_config.json（自带 port/参数/限流/口令三键；不读不写 config.json）；
- journal=[pilot] 行族（journalctl -u qa-pilot 物理分流，生产 [chat] 零新增）；
- 台账=pilot/logs/pilot-生成用量.jsonl（[pilot] 行↔台账行 trace 键 1:1）。

冻结纪律（观察窗冻结件包-20261025 §二/§三/§四.2）：
- system prompt=pilot_system_prompt.txt，启动时 sha256 断言=13dd72c6…（不符=拒启）；
- 层二 disclaimer 文案 sha256=b99a2d8a…（不符=拒启）；每答流收尾无条件恰 1 条；
- 生成参数快照 model/temperature/max_tokens=qwen3.7-max/0.3/2048（启动断言）；
- 轻口令门：独立试点口令（≠生产），PBKDF2 三键校验（同产 hash_passcode.py 式）。

SSE 事件序（§3.2）：
  : trace_id=<8hex>  →  {"type":"form","form":...}  →  {"delta":...}×N
  →  {"type":"disclaimer","text":...}（恰 1 条无条件）  →  {"done":true,"usage":...}

密件纪律：key 只从环境变量读入内存，绝不落日志/台账/错误信息。

================================================================================
留痕最小开关补丁 v2（2026-10-30 重制；批复链=过程日志 252 号㊁→件三执行单→255 号③）
================================================================================
本文件=远端现役基线（2026-10-27 费停双闸版；基线档=基线-远端现役-20261027.py，
sha256=323e63a7476db4acfdb22a430ac68c10d31262c6abd165facdd4b98edf0a4447）的
补丁副本，除下列补丁点外与该基线逐字节一致（④为 state 行内加一键=diff 上唯一
一处"-"行；其余全部纯"+"）。
【v1 废档说明】pilot_server-留痕.py（sha=3999455f62fb0634…43e3abb）系对照
  2026-10-25 仓内旧基线（sha=22cd88d6…5c939）备制=基线错版——若上云会整体
  抹掉费停双闸；2026-10-30 22:52 部署预检被 R3（sha 对不上即停）拦下，云端
  零改动；v1 件留档不删、已标废，继任件=本 v2。
【费闸零触碰声明】下列补丁点对费停双闸（feegate 四配置键/FEEGATE_STATE_FILE/
  UA 黑名单/_feegate_* 全家/_degraded_page/chat 降级短路/health feegate_down 键/
  台账 v2 增键 dev+auto/_feegate_account 调用）零增删改——只在外围纯加法。
补丁点（行号=基线-远端现役-20261027.py 基准）：
  ① 基线 31 行 import time 后 +1 行 datetime 导入（窗尾时刻构造用）；
  ② 基线 45 行 FEEDBACK_LEDGER 后 +6 行：TRACE_LEDGER 路径+窗尾时刻常量；
  ③ 基线 413 行 _append_ledger 后 +19 行：_append_trace_row 函数
    （恰五字段/零身份键/窗尾停写/写败静默）；
  ④ 基线 566-567 行 state 字典第二行改写：+"answer_parts": [] 一键
    （答案正文累积容器；本补丁唯一非纯插入点）；
  ⑤⑥⑦ 基线 584/653/700 行三处 out_chars 自增点旁各 +1 行
    state["answer_parts"].append(...)（与字数计数同一挂点，纯加法）；
  ⑧ 基线 729 行 _feegate_account(...) 调用后 +2 行：拼答案原文调
    _append_trace_row（真答收尾处=台账与费闸入计之后、journal 打点行之前，
    不打断基线的台账↔费闸相邻对）。
【费闸降级路径与留痕的关系（v2 新核）】降级短路在 pilot_chat 入口独立早退
  （_gen_degraded 生成器：trace 注释行+feegate 事件+done 三发即收），根本
  不进入 gen() 的 finally——故费停降级响应（降级页/降级 SSE）不产生任何
  留痕行（降级页不是真答）；挂点无需收紧，天然不覆盖降级路径。
行为：窗内（部署生效 → 2026-11-03 15:13:00 Asia/Shanghai）每完成一真答，
  向 pilot/logs/pilot-留痕-窗内.jsonl 追加一行 jsonl，恰五字段
  ts/trace/form/q/a；零身份键（绝不落 IP/设备代号/UA/cookie）。窗尾时刻
  过后自动停写（不写新行、不报错、不改服务行为）；写失败静默降级不伤主链。
  不碰清单全保：冻结断言/口令门/限流/页面/费停双闸/现有台账与反馈两件/
  日志格式原样。
回滚（copy-paste 三行，或直接跑备件包 回滚.sh）：
  cp /opt/qa-bot/pilot_server.py.bak-留痕部署前 /opt/qa-bot/pilot_server.py
  systemctl restart qa-pilot   # 回滚 restart=第二次，如实登记
  rm /opt/qa-bot/pilot/logs/pilot-留痕-窗内.jsonl   # 可选：清试写件（清理令归用户）
  （部署时备份件=远端现役费停双闸版，回滚即回到费闸在位态）
================================================================================
"""
import asyncio
import hashlib
import itertools
import json
import os
import re
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone   # 留痕补丁①：窗尾时刻构造
from collections import deque
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "pilot_config.json"
SYSTEM_PROMPT_FILE = BASE_DIR / "pilot_system_prompt.txt"
STATIC_INDEX = BASE_DIR / "pilot" / "static" / "index.html"
LOG_DIR = BASE_DIR / "pilot" / "logs"
USAGE_LEDGER = LOG_DIR / "pilot-生成用量.jsonl"
FEEDBACK_LEDGER = LOG_DIR / "pilot-反馈.jsonl"

# ---------- 留痕补丁②：留痕最小开关常量（件三执行单；过程日志 252 号㊁/255 号③） ----------
TRACE_LEDGER = LOG_DIR / "pilot-留痕-窗内.jsonl"   # 独立件：与台账同目录、追加写
_TRACE_WINDOW_END_DT = datetime(2026, 11, 3, 15, 13, 0,
                                tzinfo=timezone(timedelta(hours=8)))   # 首周窗关时刻
TRACE_WINDOW_END_S = int(_TRACE_WINDOW_END_DT.timestamp())   # epoch=1793689980；过此自动停写

# ---------- 冻结面（观察窗冻结件包 §二/§三/§四.2；执行期禁漂移） ----------
FROZEN_PROMPT_SHA = "13dd72c6089e7005cc8b7d5b3565e9f69a9f4bfef0ad6f8c2742ca8511bdc458"
FROZEN_DISCLAIMER_SHA = "b99a2d8ac644d2a728cca4f93ea69d5028f0e993c015b9596d7de4fdaa2b5954"
FROZEN_SNAPSHOT = {"model": "qwen3.7-max", "temperature": 0.3, "max_tokens": 2048}
DISCLAIMER_TEXT = ("本答由通用大模型直答生成，未经本站知识库检索验证"
                   "（严格正确性未验证），关键操作请按【答案形态】标注所指载体核实。")
STAGE = "甲案试点"
CHANNEL = "subscription"
EST_CNY_PER_MTOK = (2.4, 9.6)   # 订阅面等值参照 in/out（技术方案 §3.3）

# ---------- 上游（常量同 server.py 280-281 行取值拷贝） ----------
UPSTREAM = "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions"
API_KEY = os.environ.get("BAILIAN_TOKEN_PLAN_API_KEY", "")

# ---------- 打点/cookie/限流常数（生产同款机制，独立命名空间） ----------
DEVICE_COOKIE = "pilot_device"          # 8hex 起段（journal dev=<8hex>），365d
DEVICE_MAX_AGE_S = 365 * 86400
SESSION_COOKIE = "pilot_session"        # 轻口令门会话，7d（内存态）
SESSION_MAX_AGE_S = 7 * 86400
LOGIN_FAIL_LIMIT = 5                    # 同 IP 登录失败锁定阈值（10 分钟窗）
LOGIN_FAIL_WINDOW_S = 10 * 60
FEEDBACK_RATINGS = ("up", "partial", "down")   # 有用/部分有用/没用
FEEDBACK_NOTE_MAX = 500
FEEDBACK_TRACE_MAX = 64
Q_LOG_CHARS = 16                        # [pilot] q= 摘要截断（≤16 字，零题面纪律）
FORM_LABELS = ("指路", "经验", "混合")
FORM_LABEL_RE = re.compile(r"^【答案形态：(指路|经验|混合)】$")
SSE_IDLE_PING_S = 15.0                  # 上游静默保活注释行（同产 F7 契约）
SSE_TOTAL_LIMIT_S = 300.0               # 整体上限（异常长挂流兜底）

_trace_seq = itertools.count()


def _new_trace_id() -> str:
    """时间戳+进程内序号 → sha256 前 8 位 hex（生产 _new_trace_id 同式）。"""
    seq = next(_trace_seq)
    return hashlib.sha256(f"{time.time_ns()}:{seq}".encode()).hexdigest()[:8]


def _q_log_field(text: str, limit: int = Q_LOG_CHARS) -> str:
    """q= 摘要清洗（生产 _q_log_field 同款：控制字符折空格+双引号降级+截断）。"""
    if not text:
        return ""
    cleaned = "".join(
        "'" if ch == '"' else (" " if ch.isspace() or not ch.isprintable() else ch)
        for ch in text)
    return " ".join(cleaned.split())[:limit]


def _sha256(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


# ---------- 配置装载（pilot_config.json；缺省值=冻结快照口径） ----------
def _load_config() -> dict:
    cfg = {}
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
        if not isinstance(cfg, dict):
            cfg = {}
    except OSError:
        pass
    defaults = {
        "model": FROZEN_SNAPSHOT["model"],
        "temperature": FROZEN_SNAPSHOT["temperature"],
        "max_tokens": FROZEN_SNAPSHOT["max_tokens"],
        "max_history_messages": 40,
        "max_input_chars": 8000,
        "max_total_input_chars": 24000,
        "rate_limit_requests": 20,
        "rate_limit_window_seconds": 300,
        "passcode_body_enabled": True,
        # 直答转正窗 2026-10-27：费停双闸（计划 v1.2 费节；部署时 pilot_config 覆盖实值）
        "feegate_enabled": True,
        "feegate_total_cny": 20.0,
        "feegate_daily_cny": 2.0,
        "feegate_baseline_cny": 0.0,
    }
    merged = dict(defaults)
    merged.update(cfg)
    return merged


CONFIG = _load_config()

# ---------- 启动期冻结断言（任一不符=拒启：部署窗"对不上即停"的码内硬闸） ----------
with open(SYSTEM_PROMPT_FILE, encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read().strip()
if _sha256(SYSTEM_PROMPT) != FROZEN_PROMPT_SHA:
    raise SystemExit("[pilot-fatal] 冻结 prompt 哈希不符，拒启（对不上即停）")
if _sha256(DISCLAIMER_TEXT) != FROZEN_DISCLAIMER_SHA:
    raise SystemExit("[pilot-fatal] 冻结层二文案哈希不符，拒启（对不上即停）")
for _k, _v in FROZEN_SNAPSHOT.items():
    if CONFIG.get(_k) != _v:
        raise SystemExit(f"[pilot-fatal] 生成参数快照键 {_k}={CONFIG.get(_k)!r} "
                         f"与冻结值 {_v!r} 不符，拒启（禁漂移须另批）")

LOG_DIR.mkdir(parents=True, exist_ok=True)


# ---------- 直答转正窗 2026-10-27：费停双闸降级制（计划 v1.2 费节·随窗必建#1） ----------
# 双闸：总量线=feegate_baseline_cny+feegate_total_cny（默认 20 元≈2 个月正常用量余量）；
#       单日线=feegate_daily_cny（默认 2 元≈6.7 倍日均，Asia/Shanghai 日切）。
# 口径=直答入口真实流量费（est_cny 订阅等值折算），剔自动化行——判别三类镜像观察窗
# 冻结件包 §五：环回 127.0.0.x/::1 ∪ 脚本 UA 黑名单 ∪ "dev-" 前缀探针 dev 键。
# 触发=写状态文件（存在性=降级态判定，restart 不清=禁自动复位）+journal TRIPPED 呈报行；
# 人工复位=mv 状态文件归档，下一请求即恢复门面（秒级，无 restart）。
# 降级范围=直答入口（本服务）非全站：查库引用/workbench/route 在其他上游不受影响。
FEEGATE_STATE_FILE = LOG_DIR / "费闸-降级中.json"
FEEGATE_BANNER = "直答服务临时降级，查库引用版正常服务，已呈报人工处置"   # 计划 v1.2 原文
PAGE_VERSION = "20261027-转正窗"
AUTO_UA_BLACKLIST = ("python-urllib", "python-httpx", "python-requests",
                     "curl", "wget", "go-http-client", "batch2-merge-regression")
_feegate_lock = threading.Lock()
_feegate_cum = 0.0        # 总量累计（基线+v2 台账行非 auto）
_feegate_day = ""         # 当日 YYYY-MM-DD（Asia/Shanghai，ECS 时区已核）
_feegate_day_cum = 0.0    # 当日累计


def _feegate_enabled() -> bool:
    return bool(CONFIG.get("feegate_enabled", True))


def _is_auto_request(ip: str, ua: str, dev: str) -> bool:
    """自动化行判别（冻结件包 §五三类）——命中任一即 auto=1（台账/journal 落字段可审计）。"""
    if ip.startswith("127.") or ip == "::1":
        return True
    ua_l = (ua or "").lower()
    if any(k in ua_l for k in AUTO_UA_BLACKLIST):
        return True
    return dev.startswith("dev-")


def _feegate_scan_ledger() -> None:
    """启动期台账回放：v1 旧行（无 auto 键）由 feegate_baseline_cny 整体覆盖（部署时点
    冻结的全额累计，含试点期冒烟行——保守侧如实登记）；v2 行（有 auto 键）剔 auto=1
    计入总量与当日本。坏行跳过（fail-open 同产台账口径）。"""
    global _feegate_cum, _feegate_day, _feegate_day_cum
    _feegate_cum = float(CONFIG.get("feegate_baseline_cny") or 0.0)
    _feegate_day = time.strftime("%Y-%m-%d")
    _feegate_day_cum = 0.0
    try:
        with open(USAGE_LEDGER, encoding="utf-8") as f:
            for line in f:
                try:
                    o = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(o, dict) or "auto" not in o:
                    continue                      # v1 旧行=基线已覆盖
                if int(o.get("auto") or 0) == 1:
                    continue                      # 自动化行不计（口径冻结）
                est = float(o.get("est_cny") or 0.0)
                _feegate_cum += est
                if str(o.get("ts") or "")[:10] == _feegate_day:
                    _feegate_day_cum += est
    except OSError:
        pass


def _feegate_active() -> bool:
    """降级态=状态文件存在（每请求 stat，微秒级；restart 不清=禁自动复位天然成立）。"""
    return _feegate_enabled() and FEEGATE_STATE_FILE.exists()


def _feegate_trip(gate: str, est: float, trace: str) -> None:
    """触发降级：原子写状态文件+TRIPPED 呈报行（幂等：已降级不重写）。"""
    if FEEGATE_STATE_FILE.exists():
        return
    row = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "gate": gate,
           "banner": FEEGATE_BANNER,
           "cum": round(_feegate_cum, 6), "day": _feegate_day,
           "day_cum": round(_feegate_day_cum, 6), "est": round(est, 6),
           "trace": trace,
           "thresholds": {
               "total_line": round(float(CONFIG.get("feegate_baseline_cny") or 0.0)
                                   + float(CONFIG.get("feegate_total_cny") or 0.0), 6),
               "daily_cny": float(CONFIG.get("feegate_daily_cny") or 0.0)}}
    tmp = FEEGATE_STATE_FILE.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(FEEGATE_STATE_FILE)
    except OSError:
        pass   # 写失败不拖垮答案流；journal 呈报行仍在
    print(f"[pilot-feegate] TRIPPED gate={gate} cum={_feegate_cum:.6f} "
          f"day={_feegate_day} day_cum={_feegate_day_cum:.6f} est={est:.6f} "
          f"trace={trace} 处置=人工判别+人工复位（禁自动复位）", flush=True)


def _feegate_account(est: float, trace: str, is_auto: bool) -> None:
    """每答入计+双闸判别（auto 行/零费不入计）。单日闸先判（异常位=爬刷/失控主防线）。"""
    if not _feegate_enabled() or is_auto or est <= 0:
        return
    global _feegate_cum, _feegate_day, _feegate_day_cum
    with _feegate_lock:
        today = time.strftime("%Y-%m-%d")
        if today != _feegate_day:
            _feegate_day, _feegate_day_cum = today, 0.0
        _feegate_cum += est
        _feegate_day_cum += est
        if _feegate_day_cum >= float(CONFIG.get("feegate_daily_cny") or 0.0):
            _feegate_trip("daily", est, trace)
        elif _feegate_cum >= (float(CONFIG.get("feegate_baseline_cny") or 0.0)
                              + float(CONFIG.get("feegate_total_cny") or 0.0)):
            _feegate_trip("total", est, trace)


def _degraded_page() -> HTMLResponse:
    """降级页（费节·降级页三件①形态）：顶部横幅=计划原文；3 秒自动转查库引用版+
    手动按钮；查库引用/workbench/route 三入口照常可达；页脚版本号=降级/回滚态判别位。"""
    html = ("<!DOCTYPE html>\n<html lang=\"zh-CN\">\n<head>\n"
            "<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            "<title>直答服务临时降级</title>\n"
            "<meta http-equiv=\"refresh\" content=\"3; url=/ref\">\n"
            "<style>body{margin:0;font-family:-apple-system,'PingFang SC',"
            "'Microsoft YaHei',sans-serif;background:#f7f6f2;color:#1a1a1a;}"
            "#banner{position:sticky;top:0;background:#7a1f1f;color:#ffe3e3;"
            "font-weight:700;text-align:center;padding:12px 14px;font-size:15px;"
            "line-height:1.6;border-bottom:3px solid #c9971a;}"
            "main{max-width:640px;margin:0 auto;padding:22px 14px;text-align:center;}"
            ".btn{display:inline-block;margin:14px 6px 0;padding:12px 22px;"
            "font-size:15px;font-weight:700;background:#4a3200;color:#ffe9b3;"
            "border:none;border-radius:8px;text-decoration:none;}"
            ".btn.alt{background:#fff;color:#4a3200;border:1px solid #4a3200;}"
            "footer{text-align:center;font-size:12px;color:#8a8577;"
            "padding:18px 12px;line-height:1.7;}</style>\n</head>\n<body>\n"
            "<div id=\"banner\">" + FEEGATE_BANNER + "</div>\n<main>\n"
            "<p>3 秒后自动进入查库引用版（检索拼接问答，服务正常）。</p>\n"
            "<a class=\"btn\" href=\"/ref\">立即进入查库引用版</a>\n"
            "<a class=\"btn alt\" href=\"/workbench\">查证工作台</a>\n"
            "<a class=\"btn alt\" href=\"/route\">问人找档建议</a>\n"
            "</main>\n<footer>降级页 · 页面版本 " + PAGE_VERSION +
            "<br>直答入口恢复由人工判别后执行（人工复位，禁自动复位）</footer>\n"
            "<!-- page-version: " + PAGE_VERSION + " 降级态 -->\n"
            "</body>\n</html>\n")
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


_feegate_scan_ledger()   # 模块装载即回放（uvicorn 单进程；restart 后计数续账）


async def _lifespan(app: FastAPI):
    print(f"[pilot-start] 甲案试点入口就绪 model={CONFIG['model']} "
          f"temp={CONFIG['temperature']} mt={CONFIG['max_tokens']} 检索=零注入 "
          f"passcode={'on' if _passcode_gate() else 'off'} "
          f"prompt_sha={_sha256(SYSTEM_PROMPT)[:12]}… "
          f"disclaimer_sha={_sha256(DISCLAIMER_TEXT)[:12]}… "
          f"台账=pilot/logs/pilot-生成用量.jsonl 打点=[pilot]", flush=True)
    print(f"[pilot-start] 费闸={'on' if _feegate_enabled() else 'off'} "
          f"总闸线={float(CONFIG.get('feegate_baseline_cny') or 0.0) + float(CONFIG.get('feegate_total_cny') or 0.0):.2f}元 "
          f"(基线={float(CONFIG.get('feegate_baseline_cny') or 0.0):.6f}+闸宽={float(CONFIG.get('feegate_total_cny') or 0.0):.2f}) "
          f"日闸={float(CONFIG.get('feegate_daily_cny') or 0.0):.2f}元 "
          f"已计={_feegate_cum:.6f} 当日={_feegate_day_cum:.6f} "
          f"降级态={'是（禁自动复位，人工复位=归档状态文件）' if _feegate_active() else '否'} "
          f"版本={PAGE_VERSION}", flush=True)
    if not API_KEY:
        print("[pilot-start] 警告：BAILIAN_TOKEN_PLAN_API_KEY 未注入（上游调用将失败）",
              flush=True)
    yield


app = FastAPI(title="qa-pilot 甲案试点入口", docs_url=None, redoc_url=None,
              openapi_url=None, lifespan=_lifespan)

# ---------- 轻口令门（内存态会话/失败锁；5 人一周量级，重启=重新输口令一次性摩擦） ----------
_sessions: dict[str, float] = {}         # token -> created_ts
_login_fails: dict[str, deque] = {}      # ip -> deque[ts]


def _passcode_gate() -> bool:
    return bool(CONFIG.get("passcode_hash"))


async def _passcode_ok(supplied: str) -> bool:
    ph = str(CONFIG.get("passcode_hash") or "")
    salt_hex = str(CONFIG.get("passcode_salt") or "").strip()
    if not ph or not salt_hex:
        return False
    try:
        salt = bytes.fromhex(salt_hex)
        iterations = int(CONFIG.get("pbkdf2_iterations") or 600_000)
    except ValueError:
        return False
    derived = await asyncio.to_thread(
        lambda: hashlib.pbkdf2_hmac(
            "sha256", supplied.encode("utf-8"), salt, iterations).hex())
    return secrets.compare_digest(derived, ph)   # 常数时间比对


def _session_valid(token: str) -> bool:
    ts = _sessions.get(token)
    if ts is None:
        return False
    if time.time() - ts > SESSION_MAX_AGE_S:
        _sessions.pop(token, None)
        return False
    return True


def _login_lock_remaining(ip: str) -> int:
    now = time.time()
    dq = _login_fails.get(ip)
    if not dq:
        return 0
    while dq and now - dq[0] > LOGIN_FAIL_WINDOW_S:
        dq.popleft()
    return max(0, LOGIN_FAIL_LIMIT - len(dq)) if len(dq) >= LOGIN_FAIL_LIMIT else 0


# ---------- 限流（每 IP 滑窗，内存态） ----------
_rate_hits: dict[str, deque] = {}


def _rate_ok(ip: str) -> bool:
    now = time.time()
    window = float(CONFIG["rate_limit_window_seconds"])
    dq = _rate_hits.setdefault(ip, deque())
    while dq and now - dq[0] > window:
        dq.popleft()
    if len(dq) >= int(CONFIG["rate_limit_requests"]):
        return False
    dq.append(now)
    return True


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "?"


def _device_id(request: Request) -> str:
    dev = request.cookies.get(DEVICE_COOKIE, "")
    return dev if dev else secrets.token_hex(16)


def _set_device_cookie(resp, dev: str):
    resp.set_cookie(DEVICE_COOKIE, dev, httponly=True, samesite="lax", path="/",
                    max_age=DEVICE_MAX_AGE_S)


async def _auth(request: Request, body_passcode: str):
    """双轨鉴权（产件同款语义）：cookie 会话 / body 口令。返回 (ok, auth_via)。"""
    if _session_valid(request.cookies.get(SESSION_COOKIE, "")):
        return True, "cookie"
    if not _passcode_gate():
        return True, "none"
    supplied = (body_passcode or "").strip()
    if not supplied:
        return False, None
    if not CONFIG.get("passcode_body_enabled", True):
        return False, None
    if not await _passcode_ok(supplied):
        return False, None
    return True, "body"


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def _append_ledger(path: Path, row: dict):
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass   # 台账写失败不拖垮答案流；冒烟对拍步②会暴露


def _append_trace_row(trace_id: str, form_label: str, query: str,
                      answer_text: str):
    """留痕补丁③：窗内每完成一问答追加一行——恰五字段、零身份键、窗尾停写、写败静默。"""
    try:
        if time.time() >= TRACE_WINDOW_END_S:
            return   # 窗尾已过：不再写新行（不报错、不改服务行为）
        row = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "trace": trace_id,
            "form": form_label,
            "q": query,
            "a": answer_text,
        }
        with open(TRACE_LEDGER, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass   # 留痕写失败绝不伤答案流/台账主链（静默降级）


def _est_cny(usage: dict | None) -> float:
    if not usage:
        return 0.0
    it = int(usage.get("input_tokens") or 0)
    ot = int(usage.get("output_tokens") or 0)
    pin, pout = EST_CNY_PER_MTOK
    return round((it * pin + ot * pout) / 1e6, 6)


@app.get("/")
async def index(request: Request):
    # 直答转正窗 2026-10-27：费闸降级态=降级页（横幅+自动转查库引用版）
    if _feegate_active():
        return _degraded_page()
    resp = FileResponse(STATIC_INDEX)
    dev = _device_id(request)
    if DEVICE_COOKIE not in request.cookies:
        _set_device_cookie(resp, dev)
    return resp


@app.get("/pilot/health")
async def health():
    # feegate_down 键=费读数/巡检探针位（additive，ok 语义不变）
    return JSONResponse({"ok": True, "feegate_down": _feegate_active()})


@app.post("/pilot/login")
async def pilot_login(request: Request):
    ip = _client_ip(request)
    if _passcode_gate():
        remaining = _login_lock_remaining(ip)
        if remaining > 0:
            print(f"[pilot-login] ip={ip} ok=0 locked retry_after={remaining}s", flush=True)
            return JSONResponse({"error": "too_many_attempts",
                                 "retry_after_s": remaining}, status_code=429)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "bad_json"}, status_code=400)
    supplied = str((body or {}).get("passcode") or "").strip() if isinstance(body, dict) else ""
    if _passcode_gate() and not await _passcode_ok(supplied):
        dq = _login_fails.setdefault(ip, deque())
        dq.append(time.time())
        print(f"[pilot-login] ip={ip} ok=0", flush=True)   # 不记口令
        return JSONResponse({"error": "bad_passcode"}, status_code=401)
    _login_fails.pop(ip, None)
    token = secrets.token_urlsafe(24)
    _sessions[token] = time.time()
    print(f"[pilot-login] ip={ip} ok=1", flush=True)
    resp = JSONResponse({"ok": True})
    resp.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", path="/",
                    max_age=SESSION_MAX_AGE_S)
    return resp


@app.post("/pilot/feedback")
async def pilot_feedback(request: Request):
    ip = _client_ip(request)
    if not _rate_ok(ip):
        return JSONResponse({"error": "rate_limited"}, status_code=429)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "bad_json"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "bad_json"}, status_code=400)
    ok, via = await _auth(request, str(body.get("passcode") or ""))
    if not ok:
        return JSONResponse({"error": "login_required"}, status_code=401)
    rating = str(body.get("rating") or "").strip()
    if rating not in FEEDBACK_RATINGS:
        return JSONResponse({"error": "bad_rating"}, status_code=400)
    trace = str(body.get("trace_id") or "")[:FEEDBACK_TRACE_MAX]
    note = str(body.get("note") or "")[:FEEDBACK_NOTE_MAX]
    dev = request.cookies.get(DEVICE_COOKIE, "")[:8] or "-"
    _append_ledger(FEEDBACK_LEDGER, {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"), "trace": trace or "-",
        "rating": rating, "note": note, "dev": dev})
    print(f"[pilot-feedback] rating={rating} trace={_q_log_field(trace) or '-'} dev={dev}",
          flush=True)   # 零题面零 note
    return JSONResponse({"ok": True})


@app.post("/pilot/chat")
async def pilot_chat(request: Request):
    ip = _client_ip(request)
    # 直答转正窗 2026-10-27：费闸降级短路——零上游调用零台账行，SSE 发 feegate 事件
    # （页面呈现横幅+转查库引用版；横幅文案=计划 v1.2 原文）。
    if _feegate_active():
        _trace_deg = _new_trace_id()
        print(f"[pilot-feegate] blocked ip={ip} "
              f"dev={request.cookies.get(DEVICE_COOKIE, '')[:8] or '-'}", flush=True)

        def _gen_degraded():
            yield f": trace_id={_trace_deg}\n\n"
            yield _sse({"type": "feegate", "note": FEEGATE_BANNER})
            yield _sse({"done": True, "usage": None})

        return StreamingResponse(
            _gen_degraded(), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                     "X-QA-Trace-Id": _trace_deg})
    if not _rate_ok(ip):
        return JSONResponse({"error": "rate_limited"}, status_code=429)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "bad_json"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "bad_json"}, status_code=400)
    ok, auth_via = await _auth(request, str(body.get("passcode") or ""))
    if not ok:
        return JSONResponse({"error": "login_required"}, status_code=401)

    # ---- 输入校验与裁剪（同产三键：40 条/单条 8000/总量 24000，chars 口径） ----
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        return JSONResponse({"error": "bad_messages"}, status_code=400)
    messages = messages[-int(CONFIG["max_history_messages"]):]
    clean = []
    total = 0
    for m in messages:
        if not isinstance(m, dict):
            return JSONResponse({"error": "bad_messages"}, status_code=400)
        role, content = m.get("role"), m.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str) or not content.strip():
            return JSONResponse({"error": "bad_messages"}, status_code=400)
        content = content[: int(CONFIG["max_input_chars"])]
        total += len(content)
        clean.append({"role": role, "content": content})
    if clean[-1]["role"] != "user":
        return JSONResponse({"error": "bad_messages"}, status_code=400)
    if total > int(CONFIG["max_total_input_chars"]):
        return JSONResponse({"error": "input_too_long"}, status_code=413)

    trace_id = _new_trace_id()
    dev = _device_id(request)
    query = clean[-1]["content"]
    ua = (request.headers.get("user-agent") or "")[:80]
    is_auto = _is_auto_request(ip, ua, dev)   # 费闸口径：自动化行不入计（冻结件包 §五）
    payload = {
        "model": CONFIG["model"],
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + clean,
        "stream": True,
        "stream_options": {"include_usage": True},
        "temperature": CONFIG["temperature"],
        "max_tokens": CONFIG["max_tokens"],
        "enable_thinking": False,   # 冻结快照：显式关（技术方案 §五）
    }   # seed 不上行（冻结快照：从臂）
    state = {"usage": None, "form": "未标", "completed": False,
             "ttfb": None, "out_chars": 0, "answer_parts": []}   # 留痕补丁④

    async def gen():
        req_t0 = time.time()
        yield f": trace_id={trace_id}\n\n"
        buf = ""                 # 首行标签解析缓冲（解析出/判未标前 hold 住正文）
        body_started = [False]
        form_sent = [False]

        def _emit_form(value: str, rest: str):
            out = []
            if not form_sent[0]:
                state["form"] = value
                out.append(_sse({"type": "form", "form": value}))
                form_sent[0] = True
            if rest:
                body_started[0] = True
                state["out_chars"] += len(rest)
                state["answer_parts"].append(rest)   # 留痕补丁⑤
                out.append(_sse({"delta": rest}))
            return out

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(connect=15, read=180, write=30, pool=15)
            ) as client:
                async with client.stream(
                    "POST", UPSTREAM, json=payload,
                    headers={"Authorization": f"Bearer {API_KEY}"},
                ) as resp:
                    if resp.status_code != 200:
                        detail = (await resp.aread()).decode("utf-8", "replace")[:300]
                        yield _sse({"error": "upstream_error",
                                    "status": resp.status_code, "detail": detail})
                        state["completed"] = True
                        if not form_sent[0]:
                            state["form"] = "未标"
                            yield _sse({"type": "form", "form": "未标"})
                            form_sent[0] = True
                    else:
                        _deadline = time.monotonic() + SSE_TOTAL_LIMIT_S
                        _line_it = resp.aiter_lines().__aiter__()
                        _next_line = asyncio.ensure_future(_line_it.__anext__())
                        try:
                            while True:
                                if time.monotonic() >= _deadline:
                                    raise httpx.TimeoutException("sse total limit")
                                _idle = asyncio.ensure_future(asyncio.sleep(SSE_IDLE_PING_S))
                                await asyncio.wait({_next_line, _idle},
                                                   return_when=asyncio.FIRST_COMPLETED)
                                _idle.cancel()
                                if not _next_line.done():
                                    yield ": ping\n\n"
                                    continue
                                try:
                                    line = _next_line.result()
                                except StopAsyncIteration:
                                    break
                                _next_line = asyncio.ensure_future(_line_it.__anext__())
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
                                    # usage 键名归一：上游兼容口为 OpenAI 形
                                    # （prompt_tokens/completion_tokens），台账/est/日志
                                    # 统一用 input_tokens/output_tokens（2026-10-25
                                    # 冒烟第 1 轮断言② FAIL 的修正：零 token 记账缺陷）
                                    u = chunk["usage"]
                                    if isinstance(u, dict):
                                        state["usage"] = {
                                            "input_tokens": u.get(
                                                "input_tokens", u.get("prompt_tokens")),
                                            "output_tokens": u.get(
                                                "output_tokens", u.get("completion_tokens"))}
                                for choice in chunk.get("choices", []):
                                    text = (choice.get("delta") or {}).get("content")
                                    if not text:
                                        continue
                                    if state["ttfb"] is None:
                                        state["ttfb"] = time.time() - req_t0
                                    if body_started[0]:
                                        state["out_chars"] += len(text)
                                        state["answer_parts"].append(text)   # 留痕补丁⑥
                                        yield _sse({"delta": text})
                                        continue
                                    buf += text
                                    if "\n" in buf:
                                        first, _, rest = buf.partition("\n")
                                        m = FORM_LABEL_RE.match(first.strip())
                                        if m:
                                            # 标签行后空行剥除（prompt 契约）
                                            rest = rest.lstrip("\r\n") if rest.startswith(("\r", "\n")) else rest
                                            for ev in _emit_form(m.group(1), rest):
                                                yield ev
                                        else:
                                            for ev in _emit_form("未标", buf):
                                                yield ev
                                        buf = ""
                        finally:
                            _next_line.cancel()
                        # 流尽：无换行的残余缓冲（纯标签行或正文一行到底）
                        if not body_started[0] and buf:
                            m = FORM_LABEL_RE.match(buf.strip())
                            for ev in _emit_form(m.group(1) if m else "未标", "" if m else buf):
                                yield ev
                        state["completed"] = True
                        if not form_sent[0]:
                            yield _sse({"type": "form", "form": "未标"})
                            form_sent[0] = True
            # ---- 层二固定挂载：恰 1 条 disclaimer（无条件，模型生成内容无关）----
            # （本点=正常态与上游 4xx/5xx 态共同收尾位——两路均恰发 1 条；
            #  客户端中断时上方 yield 抛 GeneratorExit 直入 finally，不发不重复。）
            yield _sse({"type": "disclaimer", "text": DISCLAIMER_TEXT})
            yield _sse({"done": True, "usage": state["usage"]})
            state["completed"] = True
        except httpx.TimeoutException:
            yield _sse({"error": "upstream_timeout"})
            if not form_sent[0]:
                yield _sse({"type": "form", "form": "未标"})
                form_sent[0] = True
                state["form"] = "未标"
            if buf and not body_started[0]:
                # 未解析缓冲若以标签行开头则剥除（form 已判未标，标签行不入正文）
                first, nl, rest = buf.partition("\n")
                if FORM_LABEL_RE.match(first.strip()) and nl:
                    buf = rest.lstrip("\r\n")
                elif FORM_LABEL_RE.match(buf.strip()) and not nl:
                    buf = ""
                if buf:
                    state["out_chars"] += len(buf)
                    state["answer_parts"].append(buf)   # 留痕补丁⑦
                    yield _sse({"delta": buf})
                body_started[0] = True
            state["completed"] = True
            yield _sse({"type": "disclaimer", "text": DISCLAIMER_TEXT})
            yield _sse({"done": True, "usage": state["usage"]})
        except httpx.HTTPError as e:
            yield _sse({"error": "upstream_error", "status": 0,
                        "detail": type(e).__name__})
            if not form_sent[0]:
                yield _sse({"type": "form", "form": "未标"})
                form_sent[0] = True
                state["form"] = "未标"
            state["completed"] = True
            yield _sse({"type": "disclaimer", "text": DISCLAIMER_TEXT})
            yield _sse({"done": True, "usage": state["usage"]})
        finally:
            dur = time.time() - req_t0
            usage = state["usage"]
            est = _est_cny(usage)
            _append_ledger(USAGE_LEDGER, {
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"), "stage": STAGE,
                "model": CONFIG["model"], "trace": trace_id,
                "input_tokens": int(usage.get("input_tokens") or 0) if usage else 0,
                "output_tokens": int(usage.get("output_tokens") or 0) if usage else 0,
                "est_cny": est, "channel": CHANNEL, "form": state["form"],
                "cancelled": 0 if state["completed"] else 1,
                # 转正窗 v2 增键（费读数仪器面：按日切分 ts 既有+探针可剔可归因）
                "dev": dev[:8] or "-", "auto": 1 if is_auto else 0})
            _feegate_account(est, trace_id, is_auto)
            _append_trace_row(trace_id, state["form"], query,
                              "".join(state.get("answer_parts", ())))   # 留痕补丁⑧
            print(f"[pilot] ip={ip} dev={dev[:8]} auth={auth_via} in_chars={total} "
                  f"ttfb={'%.2fs' % state['ttfb'] if state['ttfb'] is not None else 'na'} "
                  f"dur={dur:.1f}s usage={usage} "
                  f"cancelled={'0' if state['completed'] else '1'} "
                  f"form={state['form']} auto={'1' if is_auto else '0'} "
                  f"q=\"{_q_log_field(query)}\"", flush=True)

    _headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                "X-QA-Trace-Id": trace_id}
    resp = StreamingResponse(gen(), media_type="text/event-stream", headers=_headers)
    if DEVICE_COOKIE not in request.cookies:
        _set_device_cookie(resp, dev)
    return resp
