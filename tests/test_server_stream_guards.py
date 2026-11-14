# -*- coding: utf-8 -*-
"""server.py SSE 流守卫与输入链换序单测（消零收尾 Y1，2026-10-15）。

覆盖两处立改（规格源=work/代码评审-20261015/分级发现表.md F7/P3 条目）：
- F7（gen 上游行循环双守卫）：①静默心跳——上游静默超 SSE_IDLE_PING_S 秒补发
  ": ping" SSE 注释行（前端两版 handle() 只认 "data:" 前缀=安全忽略，与
  ": trace_id=" 行同款契约）；②整体上限 SSE_TOTAL_LIMIT_S——到点走既有
  upstream_timeout 降级（SSE 事件/错误落库/trace 打点同现行超时路，不裸抛）。
  两常数均模块级可 patch 注入小值。
- P3（输入链换序）：pii_mask 挪到 8000 字符截断**之前**——跨边界身份证在
  截断前整段可见：log_only 默认态观测行整段命中（消息零改动）；mask 态
  payload=掩码后截断形态（占位符在、原号整段不在）。off/模块缺席 fail-open
  另有既有测试面（test_pii_mask / test_server_import_pii 等），此处含默认态
  零外溢对照。

体例=tests/test_server_clause_hook.py（自含伪上游 mock，零网络零真实 key）。
"""
import asyncio
import contextlib
import io
import json
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import server  # 仓根模块（tests/__init__.py 已做 sys.path 引导）
from tests import clean_store_tests  # chat 型限流免疫（2026-10-02 迭代轮泛化）

SOURCES = [
    {"doc_id": "信息产业部令第36号", "version": "2005（发文年份）",
     "locator": "附录1 1.2.1 拨号时延 款1", "score": 0.80, "quote": "平均值≤2.8秒"},
]
EVIDENCE = "以下为检索到的语料片段……\n\n[出处1] 平均值≤2.8秒"
TOKENS = ["见附录1 ", "1.2.1 款1 ", "的规定。"]

# P3 用例输入：7990 字填充 + 18 位身份证（[7990, 8007] 跨 8000 截过程日志）+ 尾部
# 填充——旧行为（截断先于掩码）只余前 10 位残段，四正则均不命中；换序后整段
# 可见。身份证形态=区划 110101 + 1990-03-07 + 顺序码（IDCARD_RE 合法年月日段）。
# 填充取 7990 使掩码后占位符完整落在 8000 内（占位符跨界被切半无 PII 泄露面，
# 但断言要占位符完整可检）。
PAD_HEAD = "前" * 7990
IDCARD = "110101199003078515"
PAD_TAIL = "后" * 100
LONG_CONTENT = PAD_HEAD + IDCARD + PAD_TAIL          # 8108 字符


class _HitSvc:
    """retrieve 恒 hit 的桩（lifespan 启动日志要读 stats）。"""
    stats = {}

    def retrieve(self, query, route_res=None, history=None):
        return (EVIDENCE, SOURCES)


def _tok_stream_factory(tokens, first_delay=0.0):
    """正常上游流工厂：可选首行前静默（心跳用例），随后逐 token data: 行。"""
    def make():
        class _OkStream:
            status_code = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def aiter_lines(self):
                if first_delay:
                    await asyncio.sleep(first_delay)  # 首 delta 前静默窗
                for tok in tokens:
                    yield "data: " + json.dumps(
                        {"choices": [{"delta": {"content": tok}}]},
                        ensure_ascii=False)
                    await asyncio.sleep(0.01)
                yield "data: " + json.dumps(
                    {"usage": {"total_tokens": 9}, "choices": []})
                yield "data: [DONE]"

            async def aread(self):
                return b""

        return _OkStream()
    return make


def _hang_stream_factory():
    """永久静默上游流工厂（整体超时用例）：aiter_lines 永不产出。"""
    def make():
        class _HangStream:
            status_code = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def aiter_lines(self):
                await asyncio.Event().wait()   # 永不置位=上游挂起
                yield "data: unreachable"

            async def aread(self):
                return b""

        return _HangStream()
    return make


class _OkClient:
    """httpx.AsyncClient 桩：记录上游 payload，stream() 返回注入的流工厂产物。"""

    def __init__(self, stream_factory):
        self._factory = stream_factory
        self.payloads = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def stream(self, method, url, json=None, headers=None, **k):
        self.payloads.append(json)
        return self._factory()


def _cfg(extra=None):
    cfg = {
        "model": "stub-model", "passcode": "pw-test", "bot_name": "测试机",
        "max_history_messages": 40, "max_input_chars": 8000,
        "max_total_input_chars": 24000, "temperature": 0.7, "max_tokens": 100,
        "rate_limit_requests": 20, "rate_limit_window_seconds": 300,
    }
    cfg.update(extra or {})
    return cfg


def _run_chat(stream_factory, content="拨号时延的规定是什么",
              cfg_extra=None, srv_patches=()):
    """一次 /api/chat 全链路（伪上游）→ (原始 SSE 行, data 事件, 日志, 上游 payload)。"""
    body = {"messages": [{"role": "user", "content": content}],
            "passcode": "pw-test"}
    out = io.StringIO()
    holder = {}

    def _mk_client(*a, **k):
        holder["client"] = _OkClient(stream_factory)
        return holder["client"]

    patches = [
        mock.patch.object(server.httpx, "AsyncClient", _mk_client),
        mock.patch.object(server, "CONFIG", _cfg(cfg_extra)),
        mock.patch.object(server, "API_KEY", "stub-key"),
        mock.patch.object(server, "rag_service", _HitSvc()),
        contextlib.redirect_stdout(out),
    ] + list(srv_patches)
    with contextlib.ExitStack() as st:
        for p in patches:
            st.enter_context(p)
        with TestClient(server.app) as client:
            with client.stream("POST", "/api/chat", json=body) as resp:
                assert resp.status_code == 200
                lines = list(resp.iter_lines())
    events = [json.loads(ln[5:].strip()) for ln in lines
              if ln.startswith("data:")]
    payload = holder["client"].payloads[-1] if holder.get("client") else None
    return lines, events, out.getvalue(), payload


def _types(events):
    return [e.get("type") or ("sources" if "sources" in e else
                              "delta" if "delta" in e else
                              "done" if e.get("done") else "?") for e in events]


def _pii_lines(logged):
    return [ln for ln in logged.splitlines() if ln.startswith("[pii_mask]")]


def _ping_count(lines):
    return sum(1 for ln in lines if ln.strip() == ": ping")


# ---------------------------------------------------------------- P3 换序 --
@clean_store_tests
class MaskBeforeTruncateTest(unittest.TestCase):
    """P3：掩码先于 8000 字符截断——跨边界身份证整段可见。"""

    def test_log_only_cross_boundary_idcard_hit(self):
        # 默认 log_only 态：观测行整段命中（旧行为=残段不命中）且消息零改动
        _lines, _events, logged, payload = _run_chat(
            _tok_stream_factory(TOKENS), content=LONG_CONTENT)
        lines = _pii_lines(logged)
        self.assertEqual(len(lines), 1)
        self.assertIn("mode=log_only", lines[0])
        self.assertIn("idcard=1", lines[0])          # 整段命中（换序核心断言）
        self.assertIn("len=8108", lines[0])          # 观测面=截断前全文
        # log_only 零改动：上游 payload 的 user 内容=原文前 8000 字符
        user_content = payload["messages"][-1]["content"]
        self.assertEqual(user_content, LONG_CONTENT[:8000])
        self.assertEqual(_types(_events),
                         ["sources", "delta", "delta", "delta", "done"])

    def test_mask_mode_masks_then_truncates(self):
        # mask 态：下游拿到掩码后截断形态——占位符在、原号整段不在
        _lines, _events, logged, payload = _run_chat(
            _tok_stream_factory(TOKENS), content=LONG_CONTENT,
            cfg_extra={"pii_mask_mode": "mask"})
        self.assertIn("mode=mask", _pii_lines(logged)[0])
        user_content = payload["messages"][-1]["content"]
        self.assertEqual(len(user_content), 8000)     # 截断仍 8000（掩码后口径）
        self.assertIn("<身份证号>", user_content)      # 掩码生效
        self.assertNotIn(IDCARD, user_content)        # 原号整段消失，无残段
        self.assertTrue(_events[-1]["done"])          # 主链路不受影响

    def test_default_state_no_pii_zero_noise(self):
        # 默认态零外溢对照：无 PII 的常规输入=零观测行、事件序照常
        _lines, events, logged, _payload = _run_chat(
            _tok_stream_factory(TOKENS))
        self.assertEqual(_pii_lines(logged), [])      # total=0 不打行
        self.assertEqual(_types(events),
                         ["sources", "delta", "delta", "delta", "done"])


# ------------------------------------------------------------------ F7 心跳 --
@clean_store_tests
class HeartbeatTest(unittest.TestCase):
    """F7①：上游静默超窗补发 ": ping" 注释行（默认 15s，测试注入 0.03s）。"""

    def test_ping_during_silence_then_normal_stream(self):
        lines, events, _logged, _payload = _run_chat(
            _tok_stream_factory(TOKENS, first_delay=0.12),
            srv_patches=(
                mock.patch.object(server, "SSE_IDLE_PING_S", 0.03),
                mock.patch.object(server, "SSE_TOTAL_LIMIT_S", 30.0),
            ))
        # 0.12s 静默窗 / 0.03s ≈ 4 跳，保守断言 ≥2（避开调度边缘）
        self.assertGreaterEqual(_ping_count(lines), 2)
        # 静默期后流恢复正常：3 delta + done（ping 行不进 data 事件面）
        self.assertEqual(_types(events),
                         ["sources", "delta", "delta", "delta", "done"])

    def test_no_ping_when_upstream_flowing(self):
        # 对照：上游逐行有产出（10ms/行 << 15s）=零 ping（既有流形态不变）
        lines, events, _logged, _payload = _run_chat(
            _tok_stream_factory(TOKENS))
        self.assertEqual(_ping_count(lines), 0)
        self.assertEqual(_types(events),
                         ["sources", "delta", "delta", "delta", "done"])


# -------------------------------------------------------------- F7 整体超时 --
@clean_store_tests
class TotalTimeoutTest(unittest.TestCase):
    """F7②：整体上限到点走既有 upstream_timeout 降级（注入 0.08s 上限）。"""

    def test_total_limit_degrades_to_upstream_timeout(self):
        lines, events, logged, _payload = _run_chat(
            _hang_stream_factory(),
            srv_patches=(
                mock.patch.object(server, "SSE_IDLE_PING_S", 0.02),
                mock.patch.object(server, "SSE_TOTAL_LIMIT_S", 0.08),
            ))
        # 降级事件=既有超时形态；无 done
        self.assertIn({"error": "upstream_timeout"}, events)
        self.assertFalse(any(e.get("done") for e in events))
        # 等待期内心跳照发（保活与超时两守卫并存）
        self.assertGreaterEqual(_ping_count(lines), 1)
        # trace llm 行 status=timeout + [chat] 自然收尾（cancelled=0）
        self.assertIn('"status":"timeout"', logged)
        chat_lines = [ln for ln in logged.splitlines()
                      if ln.startswith("[chat]")]
        self.assertTrue(chat_lines and "cancelled=0" in chat_lines[-1])

    def test_total_limit_default_far_above_normal(self):
        # 常数面：默认值=宽裕常数（300s），静默心跳=15s（评审区间下限）
        self.assertEqual(server.SSE_TOTAL_LIMIT_S, 300.0)
        self.assertEqual(server.SSE_IDLE_PING_S, 15.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
