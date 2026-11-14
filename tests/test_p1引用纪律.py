# -*- coding: utf-8 -*-
"""P1 生成端引用纪律（citation_discipline_enabled）离线单测（2026-09-29 施工）。

对象=server.py：rag 段键 citation_discipline_enabled（默认关=system 组装与
既往逐字节一致）+ CITATION_DISCIPLINE_NOTE 追加位（有证据注入才追加；与批A
A2 保守模板可叠加、纪律段在前）。端到端走伪上游（超时收流）捕获 payload，
零网络零真实 key；认证面注入明文测试口令（2026-10-07 起生产 config 只余哈希
三键，测试 CONFIG 剔三键+放编造测试口令，真实口令绝不入文件）。
"""
import contextlib
import io
import unittest
from unittest import mock

import httpx
from fastapi.testclient import TestClient

import server  # 仓根模块（tests/__init__.py 已做 sys.path 引导）
from tests import clean_store_tests  # chat 型限流免疫（2026-10-02 迭代轮泛化）


class _CaptureStream:
    async def __aenter__(self):
        raise httpx.TimeoutException("stub 上游超时")   # 伪上游：一律超时零网络

    async def __aexit__(self, *args):
        return False


class _CaptureClient:
    """伪 httpx.AsyncClient：捕获 stream 调用的 json payload（system 消息断言用）。"""
    captured = {}

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def stream(self, method, url, **kwargs):
        type(self).captured = kwargs.get("json") or {}
        return _CaptureStream()


class _StubSvc:
    """检索桩：hit 态返回固定证据；miss 态可配。"""
    stats = {}   # lifespan 启动日志要读 rag_service.stats

    def __init__(self, result):
        self._result = result

    def retrieve(self, query, route_res=None, history=None):
        return self._result


HIT = ("语料证据段", [{"doc_id": "TS 38.215", "version": "Rel-18",
                        "locator": "5.1.1", "score": 0.9}])


class DepthConfigParseTest(unittest.TestCase):
    def test_default_off(self):
        self.assertFalse(server._depth_config({})["citation_discipline_enabled"])
        self.assertFalse(
            server._depth_config({"rag": {}})["citation_discipline_enabled"])

    def test_enabled_true(self):
        d = server._depth_config({"rag": {"citation_discipline_enabled": True}})
        self.assertTrue(d["citation_discipline_enabled"])

    def test_truthy_non_bool_coerced(self):
        d = server._depth_config({"rag": {"citation_discipline_enabled": "yes"}})
        self.assertTrue(d["citation_discipline_enabled"])
        d = server._depth_config({"rag": {"citation_discipline_enabled": 0}})
        self.assertFalse(d["citation_discipline_enabled"])


class NoteContentTest(unittest.TestCase):
    def test_note_covers_three_disciplines(self):
        note = server.CITATION_DISCIPLINE_NOTE
        # TS 正文优先 / TR 卡降辅助 / 制式归属标注 / 条款号不编造 四要素在文
        self.assertIn("TS 件", note)
        self.assertIn("辅助", note)
        self.assertIn("TR", note)
        self.assertIn("制式归属", note)
        self.assertIn("5G NR", note)
        self.assertIn("LTE", note)
        self.assertIn("不得编造", note)

    def test_build_system_content_join_order(self):
        extra = "\n\n".join([server.CITATION_DISCIPLINE_NOTE,
                             server.ABSTAIN_SYSTEM_NOTE])
        out = server._build_system_content("P", "E", extra)
        # F18 围栏（2026-10-14）：evidence 外套 <qa_corpus> 标签，extra 在围栏外
        self.assertEqual(out,
                         "P\n\n<qa_corpus>\nE\n</qa_corpus>\n\n" + extra)
        self.assertLess(out.index(server.CITATION_DISCIPLINE_NOTE),
                        out.index(server.ABSTAIN_SYSTEM_NOTE))  # 纪律段在前


@clean_store_tests
class ChatHandlerDisciplineTest(unittest.TestCase):
    """/api/chat 端到端：开关三态（关/开+证据/开+无证据）的 system 消息形态。"""

    def _post_chat(self, svc, rag_cfg=None):
        _CaptureClient.captured = {}
        body = {"messages": [{"role": "user", "content": "5G NR 的 SS-RSRP 定义"}],
                "passcode": "pw-test"}   # 测试 CONFIG 明文测试口令，不涉真实口令
        cfg = dict(server.CONFIG)
        if rag_cfg is not None:
            cfg = dict(cfg, rag=rag_cfg)
        # 认证面修复（2026-10-07 起生产 config 只余哈希三键、无明文 passcode，
        # 直读明文键得空串→401 auth_expired）：剔哈希三键+放明文测试口令——
        # 保留哈希键会走 PBKDF2 比对分支照样 401（先例=test_server_clause_hook
        # .py 的 _cfg）；其余键原样=只动认证面零扰动。
        for k in ("passcode_hash", "passcode_salt", "pbkdf2_iterations"):
            cfg.pop(k, None)
        cfg["passcode"] = "pw-test"
        out = io.StringIO()
        with mock.patch.object(server, "CONFIG", cfg), \
                mock.patch.object(server, "API_KEY", "stub-key"), \
                mock.patch.object(server, "rag_service", svc), \
                mock.patch.object(server.httpx, "AsyncClient", _CaptureClient), \
                contextlib.redirect_stdout(out):
            with TestClient(server.app) as client:
                with client.stream("POST", "/api/chat", json=body) as resp:
                    self.assertEqual(resp.status_code, 200)
                    list(resp.iter_lines())
        logged = out.getvalue()
        self.assertNotIn("stub-key", logged)   # key 绝不落日志
        return _CaptureClient.captured

    def _system_of(self, captured):
        msgs = captured.get("messages") or []
        self.assertTrue(msgs and msgs[0]["role"] == "system")
        return msgs[0]["content"]

    def test_default_off_system_unchanged(self):
        cap = self._post_chat(_StubSvc(HIT),
                              rag_cfg={"citation_discipline_enabled": False})
        self.assertIs(cap["enable_thinking"], False)   # 生产直答关思考
        sysmsg = self._system_of(cap)
        self.assertIn("语料证据段", sysmsg)
        self.assertNotIn("引用纪律", sysmsg)
        # 关态=既往形态逐字节：system_prompt + 空行 + 证据（无追加段）
        self.assertEqual(sysmsg,
                         server._build_system_content(server._system_prompt(),
                                                      "语料证据段", None))

    def test_enabled_with_evidence_appends_note(self):
        cap = self._post_chat(_StubSvc(HIT),
                              rag_cfg={"citation_discipline_enabled": True})
        self.assertIs(cap["enable_thinking"], False)   # 生产直答关思考
        sysmsg = self._system_of(cap)
        self.assertIn(server.CITATION_DISCIPLINE_NOTE, sysmsg)
        self.assertLess(sysmsg.index("语料证据段"),
                        sysmsg.index("引用纪律"))   # 证据在前、纪律段末尾追加

    def test_enabled_without_evidence_no_note(self):
        # rag miss（无证据注入）→ 纪律段不追加（裸答提示面不加噪）
        cap = self._post_chat(_StubSvc(None),
                              rag_cfg={"citation_discipline_enabled": True})
        self.assertIs(cap["enable_thinking"], False)   # 生产直答关思考
        sysmsg = self._system_of(cap)
        self.assertNotIn("引用纪律", sysmsg)

    def test_enabled_with_low_score_result_no_note(self):
        # off_topic 闸态（LowScoreResult）同样无证据 → 不追加
        cap = self._post_chat(_StubSvc(server.LowScoreResult(0.2, 0.4)),
                              rag_cfg={"citation_discipline_enabled": True})
        self.assertIs(cap["enable_thinking"], False)   # 生产直答关思考
        sysmsg = self._system_of(cap)
        self.assertNotIn("引用纪律", sysmsg)

    def test_missing_rag_section_defaults_off(self):
        cap = self._post_chat(_StubSvc(HIT), rag_cfg=None)
        self.assertIs(cap["enable_thinking"], False)   # 生产直答关思考
        # 现网 config.json rag 段无本键（未决策启用）→ 不追加
        sysmsg = self._system_of(cap)
        self.assertNotIn("引用纪律", sysmsg)

    def test_payload_disables_thinking(self):
        # 生产直答关思考：qwen3 系兼容口默认开思考模式，正文预算被思考挤占，
        # payload 顶层显式 enable_thinking=False（2026-10-07 生产 reasoning 占比
        # 72% 实证；口径同 multiquery.py）
        cap = self._post_chat(_StubSvc(HIT))
        self.assertIs(cap["enable_thinking"], False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
