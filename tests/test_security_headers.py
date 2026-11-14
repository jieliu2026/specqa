# -*- coding: utf-8 -*-
"""C2 安全响应头+CSP 两段式单测（2026-10-07，施工报告=
运营/测试体系-20261007/草案/C2-施工报告-20261007.md）。

覆盖：
  ① 宽松档三头基线锁：X-Content-Type-Options=nosniff、X-Frame-Options=DENY、
     Referrer-Policy=strict-origin-when-cross-origin 全站下发（页面/JSON/404
     三响应形态面——中间件覆盖一切路由）；
  ② HSTS 两态：默认（HTTP 直连态）绝不下发；https_enabled=true 时下发
     max-age=31536000（条件与 secure cookie 同构，见 _session_cookie 注）；
  ③ CSP 两段式第二段锁定（2026-10-07 转强制档）：只发 Content-Security-Policy
     （Report-Only 头绝不在位=转档完成）+分档关键指令（script-src 'self' 且绝无
     unsafe-inline——v-html 的 XSS 面；style-src 含 unsafe-inline——KaTeX
     内联样式必需；report-uri 指收集位；object-src 'none'/frame-ancestors
     'none'/base-uri 'self'）；
  ④ POST /api/csp-report：204+任意 body 形态兜底（空/非 JSON）；限流挂靠
     conv_hits 组（与三会话端点同账：灌满后 csp-report 与会话端点齐 429）。

全程零网络（不发真实上游请求）；每测试独立临时库文件（同 test_auth_rate
口径，不碰共享 QABOT_DB_PATH 限流账）。"""
import contextlib
import os
import re
import sqlite3
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import server  # 仓根模块（tests/__init__.py 已做 sys.path 引导+QABOT_DB_PATH 隔离）


# ---------- 配置底座（请求时读 server.CONFIG，逐测试 patch） ----------
_BASE = {
    "model": "stub-model", "bot_name": "测试机",
    "max_history_messages": 5, "max_input_chars": 8000,
    "max_total_input_chars": 24000, "temperature": 0.7, "max_tokens": 100,
    "rate_limit_requests": 20, "rate_limit_window_seconds": 300,
}


def _directive(csp_value: str, name: str):
    """CSP 串里抽单条指令的源清单（如 name='script-src' → "'self'"）。

    缺指令 → None。匹配吃指令名后到分号前的整段（含引号原样），供上层
    assertEqual 精确锁档 / assertIn 成员检查。"""
    m = re.search(r"(?:^|;\s*)" + re.escape(name) + r"\s+([^;]+)", csp_value)
    return m.group(1).strip() if m else None


class _StoreIsolatedTest(unittest.TestCase):
    """每测试一块全新临时库：server._store_inst 直注入 + 退出复位
    （csp-report 限流走 conv_hits，需隔离该账）。"""

    def setUp(self):
        fd, self.db = tempfile.mkstemp(prefix="qabot-sec-hdr-", suffix=".db")
        os.close(fd)
        server._store_inst = server._Store(self.db)

    def tearDown(self):
        st = server._store_inst
        server._store_inst = None
        if st is not None:
            try:
                st.close()
            except Exception:
                pass  # lifespan 退出可能已关
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(self.db + suffix)
            except FileNotFoundError:
                pass

    def _sql(self, sql, args=()):
        """测试侧直连库做断言（WAL 多连接读写安全）。"""
        conn = sqlite3.connect(self.db)
        try:
            rows = conn.execute(sql, args).fetchall()
            conn.commit()
            return rows
        finally:
            conn.close()

    @contextlib.contextmanager
    def _client_ctx(self, cfg):
        """统一 patch 面：CONFIG/API_KEY/关 RAG（本件无 chat 流，无需伪上游）。"""
        with contextlib.ExitStack() as stack:
            for p in (mock.patch.object(server, "CONFIG", cfg),
                      mock.patch.object(server, "API_KEY", "stub-key"),
                      mock.patch.object(server, "rag_service", None)):
                stack.enter_context(p)
            yield


class T1RelaxedHeadersTest(_StoreIsolatedTest):
    """① 宽松档三头全站（页面/JSON/404）+ ② HSTS 默认态不下发。"""

    def test_three_headers_on_page_json_and_404(self):
        with self._client_ctx(dict(_BASE)):
            with TestClient(server.app) as c:
                for path, want in (("/", 200), ("/api/health", 200),
                                   ("/no-such-route", 404)):
                    r = c.get(path)
                    with self.subTest(path=path, status=want):
                        self.assertEqual(r.status_code, want)
                        self.assertEqual(
                            r.headers.get("X-Content-Type-Options"), "nosniff")
                        self.assertEqual(r.headers.get("X-Frame-Options"), "DENY")
                        self.assertEqual(
                            r.headers.get("Referrer-Policy"),
                            "strict-origin-when-cross-origin")
                        # HTTP 直连态（默认）：HSTS 绝不下发
                        self.assertNotIn("Strict-Transport-Security", r.headers)

    def test_hsts_only_when_https_enabled(self):
        """② HTTPS 半边：https_enabled=true 才下发（与 secure cookie 同构）。"""
        with self._client_ctx(dict(_BASE, https_enabled=True)):
            with TestClient(server.app) as c:
                r = c.get("/api/health")
        self.assertEqual(r.headers.get("Strict-Transport-Security"),
                         "max-age=31536000")


class T2CspEnforcedTest(_StoreIsolatedTest):
    """③ CSP 强制头在位+Report-Only 头绝不在位+分档关键指令锁（两段式第二段）。"""

    def test_enforced_header_and_key_directives(self):
        with self._client_ctx(dict(_BASE)):
            with TestClient(server.app) as c:
                r = c.get("/")
        with self.subTest("两段式第二段（转强制）：只发强制头，Report-Only 头绝不在位"):
            self.assertIn("Content-Security-Policy", r.headers)
            self.assertNotIn("Content-Security-Policy-Report-Only", r.headers)
        csp = r.headers["Content-Security-Policy"]
        with self.subTest("script-src='self' 且无 unsafe-inline（XSS 面）"):
            self.assertEqual(_directive(csp, "script-src"), "'self'")
        with self.subTest("style-src 含 unsafe-inline（KaTeX 内联样式必需）"):
            self.assertIn("'unsafe-inline'", _directive(csp, "style-src"))
        with self.subTest("default-src 择稳妥档 'self'"):
            self.assertEqual(_directive(csp, "default-src"), "'self'")
        with self.subTest("object-src 'none'"):
            self.assertEqual(_directive(csp, "object-src"), "'none'")
        with self.subTest("base-uri 'self'"):
            self.assertEqual(_directive(csp, "base-uri"), "'self'")
        with self.subTest("frame-ancestors 'none'"):
            self.assertEqual(_directive(csp, "frame-ancestors"), "'none'")
        with self.subTest("img/font 源含 data:（favicon/字体内联形态）"):
            self.assertIn("data:", _directive(csp, "img-src"))
            self.assertIn("data:", _directive(csp, "font-src"))
        with self.subTest("connect-src 'self'（API/SSE 同源面）"):
            self.assertEqual(_directive(csp, "connect-src"), "'self'")
        with self.subTest("report-uri 指收集位（Report-Only 不空转）"):
            self.assertEqual(_directive(csp, "report-uri"), "/api/csp-report")


class T3CspReportEndpointTest(_StoreIsolatedTest):
    """④ POST /api/csp-report：204+任意 body 形态兜底；限流挂 conv_hits 组同账。"""

    def test_post_204_any_body_shape(self):
        with self._client_ctx(dict(_BASE)):
            with TestClient(server.app) as c:
                r1 = c.post("/api/csp-report", json={
                    "csp-report": {"document-uri": "https://example.test/",
                                   "violated-directive": "script-src-elem",
                                   "blocked-uri": "inline"}})
                r2 = c.post("/api/csp-report", content=b"not-json")
                r3 = c.post("/api/csp-report")  # 空 body
        with self.subTest("标准报告体 204 空响应体"):
            self.assertEqual(r1.status_code, 204)
            self.assertEqual(r1.content, b"")
        with self.subTest("非 JSON body 兜底 204"):
            self.assertEqual(r2.status_code, 204)
        with self.subTest("空 body 兜底 204"):
            self.assertEqual(r3.status_code, 204)

    def test_rate_limit_shares_conv_group(self):
        """挂靠证明：csp-report 与三会话端点共用 conv_hits 账（灌满齐 429）。

        CONV_RATE_LIMIT 降档为 2 控制请求数；会话端点限流检查先于 401 鉴权，
        无 cookie 也触发 429——若 csp-report 未挂同账，此处会是 401 而非 429。"""
        with self._client_ctx(dict(_BASE)):
            with mock.patch.object(server, "CONV_RATE_LIMIT", 2):
                with TestClient(server.app) as c:
                    self.assertEqual(c.post("/api/csp-report").status_code, 204)
                    self.assertEqual(c.post("/api/csp-report").status_code, 204)
                    r = c.post("/api/csp-report")   # 第 3 次起 429
                    self.assertEqual(r.status_code, 429)
                    self.assertEqual(r.json(), {"error": "rate_limited",
                                                "retry_after_s": 60})
                    # 同账反向证：csp-report 灌满的 conv_hits 拦住会话端点
                    self.assertEqual(
                        c.get("/api/conversations").status_code, 429)
        with self.subTest("conv_hits 恰 2 行（被拒的第 3 次不插行）"):
            self.assertEqual(
                self._sql("SELECT COUNT(*) FROM conv_hits")[0][0], 2)


class T4DocsClosedTest(_StoreIsolatedTest):
    """⑤ C8（2026-10-07）：/docs、/redoc、/openapi.json 三默认面关闭（404）。

    渗透自测 CONF-02 发现：FastAPI 默认未鉴权暴露 API 全结构；内网单用户
    无消费方，docs_url/redoc_url/openapi_url 三参置 None 收面。"""

    def test_docs_redoc_openapi_all_closed(self):
        with self._client_ctx(dict(_BASE)):
            with TestClient(server.app) as c:
                for path in ("/docs", "/redoc", "/openapi.json"):
                    with self.subTest(path=path):
                        r = c.get(path)
                        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()
