# -*- coding: utf-8 -*-
"""3c /metrics 指标三行（计划-管理面建设-20261030.md §七.3c；过程日志 319 号④
2026-11-01 并窗编码）单测。

覆盖面：
- _metrics_round 打点：轮计数累加；错误轮判 llm_status=="error"；tokens 取
  provider usage total_tokens 原值（缺失/bool/非数值不计）；任何异常恒不抛出
  （打点绝不影响请求主链）；
- /metrics 三行形态：恰三行 qa_bot_* 计数指标（rounds/errors/llm_tokens）+
  头部 # 注释行，media_type=text/plain；
- 环回卫（公网零暴露双闸的端点面）：socket 对端 127.0.0.1/::1 且无
  X-Forwarded-For → 200；带 X-Forwarded-For（Caddy 反代必带形态）或非环回
  对端 → 404。

零网络零计费：纯函数断言 + TestClient 本地请求；_client_ip 以 mock 注入
（非环回代表用 TEST-NET 203.0.113.0/24，不涉任何真实 IP）。
"""
import re
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import server  # 仓根模块（tests/__init__.py 已做 sys.path 引导）


class MetricsRoundUnitTest(unittest.TestCase):
    """_metrics_round 纯函数面（不启 app）。"""

    def setUp(self):
        with server._METRICS_LOCK:
            server._METRICS.update(rounds=0, errors=0, llm_tokens=0)

    def _snap(self):
        with server._METRICS_LOCK:
            return dict(server._METRICS)

    def test_round_error_token_accumulation(self):
        server._metrics_round("done", {"total_tokens": 100})
        server._metrics_round("done", {"total_tokens": 55})
        server._metrics_round("error", None)
        server._metrics_round("cancelled", {"total_tokens": 7})
        snap = self._snap()
        self.assertEqual(snap["rounds"], 4)
        self.assertEqual(snap["errors"], 1)      # 仅 llm_status=="error"
        self.assertEqual(snap["llm_tokens"], 162)  # 100+55+7 原值合计

    def test_bad_usage_never_counts_or_throws(self):
        server._metrics_round("done", None)                    # 缺 usage
        server._metrics_round("done", {"total_tokens": True})  # bool 不计
        server._metrics_round("done", {"total_tokens": "x"})   # 非数值不计
        server._metrics_round(None, "garbage")                 # 异形态恒不抛
        snap = self._snap()
        self.assertEqual(snap["rounds"], 4)
        self.assertEqual(snap["errors"], 0)
        self.assertEqual(snap["llm_tokens"], 0)


class MetricsEndpointTest(unittest.TestCase):
    """/metrics 端点：三行形态 + 环回卫（mock _client_ip 注入对端）。"""

    def setUp(self):
        with server._METRICS_LOCK:
            server._METRICS.update(rounds=3, errors=1, llm_tokens=909)

    def _get(self, peer="127.0.0.1", xff=None):
        with mock.patch.object(server, "_client_ip", lambda req: peer):
            with TestClient(server.app) as client:
                headers = {"X-Forwarded-For": xff} if xff else {}
                return client.get("/metrics", headers=headers)

    def test_loopback_three_lines(self):
        resp = self._get(peer="127.0.0.1")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.headers["content-type"].startswith("text/plain"))
        lines = resp.text.strip("\n").split("\n")
        metric_lines = [l for l in lines if not l.startswith("#")]
        self.assertEqual(len(metric_lines), 3)           # 指标恰三行
        for l in metric_lines:
            self.assertRegex(l, r"^qa_bot_[a-z_]+ \d+$")
        names = [l.split()[0] for l in metric_lines]
        self.assertEqual(set(names), {"qa_bot_chat_rounds_total",
                                      "qa_bot_chat_errors_total",
                                      "qa_bot_llm_tokens_total"})
        self.assertIn("qa_bot_chat_rounds_total 3", metric_lines)
        self.assertIn("qa_bot_chat_errors_total 1", metric_lines)
        self.assertIn("qa_bot_llm_tokens_total 909", metric_lines)

    def test_ipv6_loopback_allowed(self):
        self.assertEqual(self._get(peer="::1").status_code, 200)

    def test_xff_header_denied(self):
        # Caddy 反代必带 X-Forwarded-For——即使对端环回也按"非直连本机"拒
        self.assertEqual(
            self._get(peer="127.0.0.1", xff="203.0.113.9").status_code, 404)

    def test_remote_peer_denied(self):
        self.assertEqual(
            self._get(peer="203.0.113.7").status_code, 404)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
