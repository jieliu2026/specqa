#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
embed_common.py —— 嵌入管线公共机制模块（2026-09-17 工程化重构轮立档）

收口原先 embed_run.py / embed_run2.py 逐字重复的机制代码（过程日志四节工程债①）：
  - 百炼 OpenAI 兼容 embeddings API 调用（urllib，标准库）
  - 429/5xx 指数退避重试（≤max_retry 次，单次睡眠封顶 retry_max_sleep）
  - HTTP 400 batch 超限自动对半拆（递归，半批各算一次用量）
  - 进度幂等：done_ids 集合 + tmp/os.replace 原子写，重启跳过已完成不重复计费
  - 用量逐批登记 jsonl；红线熔断：累计估算花费 ≥ red_line_cny 即取消待跑批停线
  - 并发调度（ThreadPoolExecutor）与失败批落档
  - 密钥/URL 脱敏 scrub（sk-* key 形态与 URL host 一律不外泄）
  - 子项帽（F线语料专项 v3.1 §五 技术强制，2026-10-14 D线施工）：付费调用声明
    sub_item（ydt_embed/three_arm/anchor_judge/calibration/misc_embed/misc_gen），
    无子项余额即拒绝；子项用量落台账新字段 sub_item（向后兼容：旧字段不动只加
    新字段，历史行无 sub_item 不归任何子项）。不改既有红线/月度闸行为（月度闸
    40/50 与累计台账线 50 并行不叠加的既有结论不动）。

边界与纪律：
  - 本模块只管"机制"，不管语料源（chunk 从哪来、怎么切、id 怎么派生）——
    新语料源方案另案设计；chunk_l1.py 系旧课件切块器，冻结为遗留参照，不在新管线内。
  - import 零副作用（过程日志四节工程债④）：不读密钥文件、不建目录、不联网；
    密钥解析延后到 load_api_settings() 运行时调用，本模块可被安全 import 做单测。
  - 网络与时间依赖（urlopen/sleep）全部可注入，离线单测零 API 调用零计费。
  - 进度/用量/异常台账路径由调用方传入（值来自 pipeline_config），本模块不自持配置。
"""
import io
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

# 可重试的 HTTP 状态（429 限流 + 5xx 网关/服务端）
RETRYABLE_HTTP = (429, 500, 502, 503, 504)


def scrub(text):
    """日志/报错回显前脱敏：sk-* key 形态与 URL host 都不外泄（台账纪律）。"""
    text = re.sub(r"sk-[A-Za-z0-9_.\-]+", "sk-***", str(text))
    return re.sub(r"(https?://)[^/\s\"']+", r"\1***", text)


# ---------------------------------------------------------------------------
# 密钥与端点（运行时解析——import 阶段绝不触发）
# ---------------------------------------------------------------------------
def load_api_settings(key_path, embeddings_path="/compatible-mode/v1/embeddings"):
    """读取密钥文件 → {"api_url":…, "key":…}。

    环境变量优先：BAILIAN_EMBED_API_KEY 与 BAILIAN_EMBED_BASE_URL 两者齐备时
    免密钥文件（云端/临时环境跑管线不落 key 盘，与 rag.py 解析口径对齐）；
    否则读密钥文件，格式：{"base_url":…, "api_key":…}。只在真正要调 API 前调用；
    返回值属敏感内容，禁止打印/落盘（报错路径只报字段名，不报值）。
    """
    env_key = os.environ.get("BAILIAN_EMBED_API_KEY", "")
    env_base = os.environ.get("BAILIAN_EMBED_BASE_URL", "")
    if env_key and env_base:
        return {"api_url": env_base.rstrip("/") + embeddings_path, "key": env_key}
    path = os.path.expanduser(key_path)
    if not os.path.exists(path):
        raise FileNotFoundError("密钥文件不存在：%s（路径可在配置 key_path 调整）" % key_path)
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    for field in ("base_url", "api_key"):
        if not cfg.get(field):
            raise RuntimeError("密钥文件缺 %s 字段或为空" % field)
    return {"api_url": cfg["base_url"].rstrip("/") + embeddings_path, "key": cfg["api_key"]}


# ---------------------------------------------------------------------------
# chunk 与台账读写
# ---------------------------------------------------------------------------
def load_jsonl(path):
    """逐行读 jsonl（跳过空行）；坏行抛 ValueError（切块源应是静态干净文件）。"""
    items = []
    with open(path, encoding="utf-8") as f:
        for ln, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise ValueError("%s 第 %d 行非合法 JSON: %s" % (path, ln, e))
    return items


def load_chunks(paths):
    """多个切块源 jsonl 顺序拼接加载（行为同旧 embed_run：行序拼接）。"""
    chunks = []
    for p in paths:
        chunks.extend(load_jsonl(p))
    return chunks


def load_progress(progress_path):
    """读进度档 → (done_ids 集合, stats dict)；档不存在返回空态。"""
    if os.path.exists(progress_path):
        with open(progress_path, encoding="utf-8") as f:
            d = json.load(f)
        return set(d["done_ids"]), d
    return set(), {"done_ids": [], "total_prompt_tokens": 0, "requests": 0, "retries": 0, "batches": 0}


def save_progress(progress_path, done_ids, stats):
    """进度幂等原子写：先写 .tmp 再 os.replace（并发/中断不损坏进度档）。"""
    tmp = progress_path + ".tmp"
    payload = {"done_ids": sorted(done_ids), "total_prompt_tokens": stats["total_prompt_tokens"],
               "requests": stats["requests"], "retries": stats["retries"], "batches": stats["batches"]}
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    os.replace(tmp, progress_path)


def save_fails(err_path, fails):
    """失败批落档（可重跑入口续做）。"""
    with open(err_path, "w", encoding="utf-8") as f:
        json.dump(fails, f, ensure_ascii=False, indent=1)


def estimate_cost_cny(total_prompt_tokens, price_per_mtok):
    return total_prompt_tokens / 1e6 * price_per_mtok


# ---------------------------------------------------------------------------
# API 调用：重试退避 + 400 batch 超限对半拆
# ---------------------------------------------------------------------------
def call_api(texts, api_settings, model, dims, timeout=600, open_fn=None):
    """单次 embeddings 请求（无重试）。open_fn 可注入做离线单测。"""
    body = {"model": model, "input": list(texts), "dimensions": dims}
    req = urllib.request.Request(
        api_settings["api_url"], data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + api_settings["key"],
                 "Content-Type": "application/json"})
    opener = open_fn or urllib.request.urlopen
    with opener(req, timeout=timeout) as r:
        return json.loads(r.read())


def embed_batch(texts, cfg, api_settings, sleep_fn=None, open_fn=None):
    """带重试的批量向量化。返回 (vecs, usage, retried, err)——err 为 None 即成功。

    - 429/5xx/网络异常：指数退避 2^attempt 秒（封顶 cfg["retry_max_sleep"]），
      至多 cfg["max_retry"] 次重试后报错；
    - HTTP 400 且响应含 "batch size" 且 len(texts)>1：递归对半拆（半批各算一次用量）；
    - 维度不符视为错误（重试后仍报错）。
    sleep_fn/open_fn 可注入做离线单测。
    """
    sleep = sleep_fn if sleep_fn is not None else time.sleep
    max_retry = cfg["max_retry"]
    attempt = 0
    while True:
        attempt += 1
        try:
            d = call_api(texts, api_settings, cfg["model"], cfg["dims"],
                         timeout=cfg.get("request_timeout", 600), open_fn=open_fn)
            vecs = [None] * len(d["data"])
            for item in d["data"]:
                vecs[item["index"]] = item["embedding"]
            if any(v is None for v in vecs):
                raise RuntimeError("向量数不足")
            if len(vecs[0]) != cfg["dims"]:
                raise RuntimeError("维度不符: %d" % len(vecs[0]))
            return vecs, d["usage"], attempt - 1, None
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            if e.code == 400 and "batch size" in body and len(texts) > 1:
                mid = len(texts) // 2
                v1, u1, r1, e1 = embed_batch(texts[:mid], cfg, api_settings, sleep_fn, open_fn)
                v2, u2, r2, e2 = embed_batch(texts[mid:], cfg, api_settings, sleep_fn, open_fn)
                if e1 or e2:
                    return None, None, r1 + r2, e1 or e2
                u = {"prompt_tokens": u1["prompt_tokens"] + u2["prompt_tokens"]}
                return v1 + v2, u, r1 + r2, None
            if e.code in RETRYABLE_HTTP and attempt <= max_retry:
                sleep(min(2 ** attempt, cfg.get("retry_max_sleep", 120)))
                continue
            return None, None, attempt - 1, {"http": e.code, "body": scrub(body)[:200]}
        except Exception as ex:
            if attempt <= max_retry:
                sleep(min(2 ** attempt, cfg.get("retry_max_sleep", 120)))
                continue
            return None, None, attempt - 1, {"exc": scrub(repr(ex))[:200]}


# ---------------------------------------------------------------------------
# 并发编排：批量调度 + 进度幂等 + 用量登记 + 红线熔断
# ---------------------------------------------------------------------------
def run_pipeline(todo, cfg, api_settings, out_path, usage_path, progress_path,
                 done, stats, batch_size=None, workers=None, stage=None,
                 embed_fn=None, print_fn=None, text_fn=None,
                 sub_item=None, sub_caps=None):
    """把 todo chunk 列表并发向量化并落盘。返回汇总 dict。

    - todo：待做 chunk 列表（调用方已按 done_ids 过滤）；
    - cfg：pipeline_config.load_config() 产出的配置 dict；
    - api_settings：load_api_settings() 产物；embed_fn 注入时可为假对象（离线单测）；
    - done/stats：进度态（load_progress 产物，就地更新，本函数负责持久化）；
    - batch_size/workers：缺省取 cfg（embed 探测用法=单条批传 batch_size=1）；
    - stage：用量记录附加标记（如 "探测"）；
      - embed_fn：可注入的向量化函数 texts→(vecs, usage, retried, err)，
        缺省包装 embed_batch（真实 API）——单测注入假函数即零 API 零计费；
      - text_fn：chunk→嵌入文本 的取值函数（缺省 None=c["content"] 原文）。
        embed_run 开 cr_prepend_context 时传 CR 块首拼接函数（cr_context+"\n"+
        content）：只改送 API 的文本，落盘向量行仍存原 chunk 全字段（content 原文
        不动，id 仍为块 id）；默认 None 时行为与本参数加入前逐字节一致。
      - sub_item：子项帽声明（2026-10-14 D线施工，F线专项 §五 技术强制）。非 None 时：
        ①开跑前查子项余额（read 子项台账累计 + SUB_ITEM_CAPS_DEFAULT/sub_caps 帽值），
          无余额（剩余 ≤0）抛 SubItemCapExceeded（异常→调用方 exit 非零，零 API 调用）；
        ②每完成一批核子项累计（台账基线+本跑 tokens×cfg 价），≥ 帽即取消未启动批停线
          （在飞批完成并计费，语义同红线熔断），返回 sub_cap_hit=True；
        ③用量台账行附加 sub_item 字段（旧字段不动只加新字段）。None=零行为差
          （旧调用不声明 sub_item 照跑，红线/月度闸不受影响）。
      - sub_caps：{sub_item: 帽(元)} 覆盖层，叠加在 SUB_ITEM_CAPS_DEFAULT 上。

    红线熔断：每完成一批即核累计估算花费（比旧版每 10 批一核更严），
    ≥ cfg["red_line_cny"] 时取消未启动的批并停线；在飞批仍会完成并计费
    （继承旧实现语义，收尾时如实汇总）。返回 {"red_line_hit":…} 供调用方提示。
    子项帽与红线并行独立：任一先到先停，互不替代（红线=全线总闸，子项帽=专项分项闸）。
    """
    say = print_fn if print_fn is not None else (lambda *a, **k: print(*a, **k, flush=True))
    # 子项帽入口闸：开跑前（零 API 调用前）查余额，无余额即拒（异常→exit 非零）。
    sub_cap = None
    sub_base = 0.0
    sub_run_tokens = [0]           # 本跑 prompt_tokens（锁内累计，子项帽口径）
    sub_cap_hit = False
    if sub_item is not None:
        caps = dict(SUB_ITEM_CAPS_DEFAULT)
        if sub_caps:
            caps.update(sub_caps)
        if sub_item not in caps:
            raise ValueError("未知子项 %r（默认帽表：%s；新子项须经 sub_caps 显式补帽）"
                             % (sub_item, ", ".join(sorted(SUB_ITEM_CAPS_DEFAULT))))
        sub_cap = caps[sub_item]
        bal = require_sub_item_balance(usage_path, sub_item, cap=sub_cap,
                                       price_per_mtok=cfg["price_per_mtok"])
        sub_base = bal["used_cny"]
    batch_size = batch_size or cfg["batch"]
    workers = workers or cfg["workers"]
    embed = embed_fn or (lambda texts: embed_batch(texts, cfg, api_settings))
    get_text = text_fn if text_fn is not None else (lambda c: c["content"])
    lock = threading.Lock()

    batches = [(i, todo[i:i + batch_size]) for i in range(0, len(todo), batch_size)]
    n_batches = len(batches)

    def worker(batch_no, batch_chunks):
        vecs, usage, retried, err = embed([get_text(c) for c in batch_chunks])
        with lock:
            stats["requests"] += 1
            stats["retries"] += retried
            if err:
                fail_box.append({"batch": batch_no, "first_id": batch_chunks[0].get("id"), "err": err})
                return ("fail", batch_no, batch_chunks[0].get("id"), err)
            stats["batches"] += 1
            stats["total_prompt_tokens"] += usage.get("prompt_tokens", 0)
            if sub_item is not None:
                sub_run_tokens[0] += usage.get("prompt_tokens", 0)
            # 每批全量落盘在锁内一次完成（向量+用量+进度），批=原子事务：
            # 任何时点中断，进度档与已写向量行严格一致，恢复不重复计费。
            # 账面（ok/fail/usage）也在锁内记——红线 break 后主循环不再消费
            # 在飞批结果，但账实仍一致。
            n = 0
            for c, v in zip(batch_chunks, vecs):
                rec = dict(c)
                rec["embedding_model"] = cfg["model"]
                rec["dim"] = len(v)
                rec["embedding"] = v
                out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                done.add(c["id"])
                n += 1
            ok_box.append(n)
            ulog = {"ts": time.strftime("%H:%M:%S"), "batch": batch_no, "n": n,
                    "prompt_tokens": usage.get("prompt_tokens", 0), "retries": retried}
            if stage:
                ulog["stage"] = stage
            if sub_item is not None:
                ulog["sub_item"] = sub_item   # 新字段只追加，旧字段不动（向后兼容）
            ulog_f.write(json.dumps(ulog, ensure_ascii=False) + "\n")
            out_f.flush()
            ulog_f.flush()
            save_progress(progress_path, done, stats)
            return ("ok", batch_no, n, usage.get("prompt_tokens", 0))

    ok_box, fail_box = [], []
    red_line_hit = False
    est_cny = estimate_cost_cny(stats["total_prompt_tokens"], cfg["price_per_mtok"])
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(usage_path)), exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(progress_path)), exist_ok=True)
    with open(out_path, "a", encoding="utf-8") as out_f, \
         open(usage_path, "a", encoding="utf-8") as ulog_f:
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(worker, bn, bc): bn for bn, bc in batches}
            n_done = 0
            for fut in as_completed(futs):
                r = fut.result()
                n_done += 1
                if r[0] == "ok":
                    est_cny = estimate_cost_cny(stats["total_prompt_tokens"], cfg["price_per_mtok"])
                    if n_done % 10 == 0 or n_done == n_batches:
                        say("[进度] %d/%d 批 累计 prompt_tokens=%d 估 %.4f 元 用时 %.0fs" % (
                            n_done, n_batches, stats["total_prompt_tokens"], est_cny, time.time() - t0))
                    if est_cny >= cfg["red_line_cny"]:
                        say("[红线] 累计估算 %.4f 元 ≥ %.2f 元红线，停" % (est_cny, cfg["red_line_cny"]))
                        red_line_hit = True
                        for f2 in futs:
                            f2.cancel()
                        break
                    if sub_item is not None:
                        sub_est = sub_base + estimate_cost_cny(sub_run_tokens[0],
                                                               cfg["price_per_mtok"])
                        if sub_est >= sub_cap:
                            say("[子项帽] %s 累计估算 %.4f 元 ≥ %.2f 元子项帽，停"
                                "（超帽=停手呈报上调，禁降质）" % (sub_item, sub_est, sub_cap))
                            sub_cap_hit = True
                            for f2 in futs:
                                f2.cancel()
                            break
                else:
                    _, bn, cid, err = r
                    say("[失败] 批 %d（%s）：%s" % (bn, cid, json.dumps(err, ensure_ascii=False)[:160]))
        save_progress(progress_path, done, stats)

    return {"todo": len(todo), "ok_chunks": sum(ok_box), "fail_batches": len(fail_box),
            "fails": fail_box, "red_line_hit": red_line_hit, "done_ids": done, "stats": stats,
            "est_cost_cny": est_cny, "sub_cap_hit": sub_cap_hit}


# ---------------------------------------------------------------------------
# 子项帽（F线语料专项执行计划 v3.1 §五"预算硬闸"技术强制面；2026-10-14 D线施工）
# ---------------------------------------------------------------------------
# 专项子项帽默认表（元）。调用方可经 sub_caps 参数覆盖单值（run_pipeline）或 cap 参数
# （require_sub_item_balance）；红线（red_line_cny 累计台账线 50/预警 40）与 rag.py 服务端
# 月度闸 40/50 均不受本机制影响——三层并行：子项帽=专项分项闸，红线=全线总闸，月度闸=
# 服务端月度切片（与累计台账线共账并行不叠加，过程日志登记在案）。
# 帽值出处=运营/F线语料专项-执行计划-20261014.md §五（v3.1 质量优先配置）：
#   ydt_embed ≤8（容纳全量上界 7.1 元）/ three_arm 1.50（扩样 100 题判卷+重试全含）/
#   anchor_judge ≤1.0（锚包 LLM 判卷）/ calibration ≤0.5（北极星校准 ≥50 条）/
#   misc_embed ≤1 + misc_gen ≤1（其余）。总账档=运营/F线/D线-预算总账-20261014.md。
SUB_ITEM_CAPS_DEFAULT = {
    "ydt_embed": 8.0,      # 嵌入侧（台账=logs/embed用量.jsonl）
    "three_arm": 1.50,     # 生成侧（台账=logs/生成用量.jsonl）
    "anchor_judge": 1.0,   # 生成侧
    "calibration": 0.5,    # 生成侧（北极星校准）
    "misc_embed": 1.0,     # 嵌入侧
    "misc_gen": 1.0,       # 生成侧
}


class SubItemCapExceeded(RuntimeError):
    """子项帽无余额（剩余 ≤0）：付费调用拒绝执行。错误信息含子项名/已用/帽/余额。"""


def _row_est_cny(row, price_per_mtok):
    """台账行 → 估算金额（元）；无法估值返回 None。

    优先级：行内 est_cny（生成侧行制，逐笔真实口径）> 行内 price_per_mtok×
    prompt_tokens（33 行历史价格留痕行）> 调用方 price_per_mtok×prompt_tokens
    （嵌入侧缺省保守档 0.5）。两字段皆缺（diff 留痕行等）→ None，不计入。
    """
    if "est_cny" in row:
        try:
            return float(row["est_cny"])
        except (TypeError, ValueError):
            return None
    if "prompt_tokens" in row:
        p = row.get("price_per_mtok", price_per_mtok)
        try:
            return float(row["prompt_tokens"]) / 1e6 * float(p)
        except (TypeError, ValueError):
            return None
    return None


def read_sub_item_usage(usage_path, sub_item, price_per_mtok=0.5):
    """读台账 → 指定子项的累计估算金额（元）。

    行归属：仅 row["sub_item"]==sub_item 的行计入（历史行无该字段=不归任何子项，
    向后兼容）。行制：增量制行直接求和；累计制行（row_mode=="cumulative"）分段
    单调读取、段贡献=段末值（防 naive 重复计数，口径同 cr_contextualize.
    read_ledger_baseline 的 SYNTH 历史段处理）。台账不存在/无匹配行 → 0.0。
    坏行跳过（宁少勿炸，子项行由本机制自写、不应有坏行，出现即工程异常另行排查）。
    """
    if not os.path.exists(usage_path):
        return 0.0
    total, seg_last, seg_open = 0.0, None, False
    with open(usage_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("sub_item") != sub_item:
                continue
            est = _row_est_cny(row, price_per_mtok)
            if est is None:
                continue
            if row.get("row_mode") == "cumulative":
                if seg_open and est < seg_last:   # 值回落=段重置，旧段以末值闭合
                    total += seg_last
                seg_last, seg_open = est, True
            else:
                total += est
    if seg_open:
        total += seg_last                        # 未闭合段以当前末值计入
    return total


def sub_item_balance(usage_path, sub_item, cap=None, price_per_mtok=0.5):
    """查询子项余额（纯查询，不抛异常）→ dict(sub_item/used_cny/cap_cny/remaining_cny)。

    cap 缺省取 SUB_ITEM_CAPS_DEFAULT[sub_item]；表外子项名且未显式给 cap → KeyError
    （防拼错子项名静默无帽放水）。台账不存在视作已用 0。
    """
    if cap is None:
        cap = SUB_ITEM_CAPS_DEFAULT[sub_item]    # 表外名=KeyError（有意为之）
    used = read_sub_item_usage(usage_path, sub_item, price_per_mtok)
    return {"sub_item": sub_item, "used_cny": used, "cap_cny": float(cap),
            "remaining_cny": float(cap) - used}


def require_sub_item_balance(usage_path, sub_item, cap=None, price_per_mtok=0.5):
    """付费调用前必经闸：无余额（remaining ≤0）抛 SubItemCapExceeded，有余额返回余额 dict。

    错误信息含子项名/已用/帽/剩余余额（呈报超帽上调用）。异常未被调用方捕获时
    即 exit 非零——"无子项余额拒绝"的技术强制面。
    """
    bal = sub_item_balance(usage_path, sub_item, cap=cap, price_per_mtok=price_per_mtok)
    if bal["remaining_cny"] <= 0:
        raise SubItemCapExceeded(
            "[子项帽拒绝] %s 无余额：已用 %.4f 元 / 帽 %.2f 元 / 剩余 %.4f 元"
            "（台账 %s）——超帽处置=停手呈报上调，禁降质"
            % (sub_item, bal["used_cny"], bal["cap_cny"], bal["remaining_cny"], usage_path))
    return bal


if __name__ == "__main__":
    # 子项余额查询 CLI（零 API 零计费）：python3 embed_common.py [sub_item] [usage_path]
    #   无参=打印默认帽表全部子项对 embed 台账（缺省路径）的余额；生成侧子项请显式
    #   传 生成用量.jsonl 路径（three_arm/anchor_judge/calibration/misc_gen 的台账位）。
    import argparse
    ap = argparse.ArgumentParser(description="子项帽余额查询（只读，零 API）")
    ap.add_argument("sub_item", nargs="?", help="子项名（缺省=默认帽表全项）")
    ap.add_argument("usage_path", nargs="?",
                    default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                         "logs", "embed用量.jsonl"),
                    help="台账路径（缺省=建库/logs/embed用量.jsonl）")
    a = ap.parse_args()
    names = [a.sub_item] if a.sub_item else sorted(SUB_ITEM_CAPS_DEFAULT)
    for name in names:
        bal = sub_item_balance(a.usage_path, name)
        print("%-14s 已用 %8.4f / 帽 %6.2f / 剩余 %8.4f 元（台账 %s）"
              % (name, bal["used_cny"], bal["cap_cny"], bal["remaining_cny"], a.usage_path))
