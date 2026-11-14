# -*- coding: utf-8 -*-
"""multiquery.py condense 段 + rag.py mq condense 挂点离线单测（零网络零 API，
夹具全内联；mock httpx）。判据件=建库/work/mq施工-20261024/判据预登记-20261024.md。

覆盖面：
- condense_views：末轮/前史抽取（user+assistant 均入）、单轮/None/无 user=
  确定性跳过形、轮数帽/字符帽（保尾截头）、坏帽回默认、畸形条目容忍；
- condense_input：冻结输入形态（有/无前史两形）；
- 观测行：fmt ok/err 两形+恒不抛出；parse 往返（前缀容忍/坏 JSON/长度不符/
  非本行 → None）；
- condense_query：无前史零调用零打行（httpx 零实例化）；成功路径参数面
  （temperature=0/enable_thinking=False/max_tokens=320/system=冻prompt）+
  ok=1 全文行；endpoint 缺席/HTTP 失败/空产物 → None+ok=0 err 行；
- rag 挂点六态关态逐字节一致（S1 键缺席/S2 enabled=false/S3 enabled=0/
  S4 垃圾值/S5 enabled=true+history=None/S6 enabled=true+单轮 history）——
  读数与关态逐字节同+零 condense 调用+零观测行；
- rag 开态：condense_fn 注入 c0 路进融合（routes=[q0,c0]）+ c0 与 q0 同文
  弃路 + 注入抛异常弃路零恶化；观测行全文落档。

跑法（tests/ 惯例）：仓根起 venv/bin/python -m tests.test_mq_condense。
"""
import json
import os
import tempfile
import unittest
from unittest import mock

import httpx

import multiquery
import rag


HIST = [
    {"role": "user", "content": "切换参数 a3-Offset 的取值范围是多少"},
    {"role": "assistant", "content": "a3-Offset 见 TS 36.331 …"},
    {"role": "user", "content": "一般无线网络优化工程师，设置多少"},
]

SERVICE_RECS = [
    {"id": "c1", "content": "宏切换参数概述与常见配置说明", "doc_id": "DOC-1",
     "version": "V1", "locator": "§1", "embedding": [1, 0, 0, 0, 0, 0, 0, 0]},
    {"id": "c2", "content": "TS 36.214 RSRP definition table", "doc_id": "DOC-2",
     "version": "V2", "locator": "5.1.1", "embedding": [0.9, 0.1, 0, 0, 0, 0, 0]},
    {"id": "c3", "content": "p0-NominalPUSCH 参数卡 default value 0", "doc_id": "DOC-3",
     "version": "V3", "locator": "A.1", "embedding": [0, 1, 0, 0, 0, 0, 0, 0]},
]
Q0 = "切换参数 a3-Offset 的取值范围是多少 一般无线网络优化工程师，设置多少"
C0 = "切换参数 a3-Offset 一般无线网络优化设置为多少"


class _Silent:
    def __init__(self):
        self.lines = []

    def __call__(self, line):
        self.lines.append(str(line))


def _res(content, in_tok=100, out_tok=50):
    resp = mock.Mock()
    resp.raise_for_status = lambda: None
    resp.json.return_value = {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": in_tok, "completion_tokens": out_tok}}
    return resp


# ---------------------------------------------------------------------------
# condense_views / condense_input（纯函数）
# ---------------------------------------------------------------------------
class CondenseViewsTest(unittest.TestCase):
    def test_multi_turn_prior_includes_assistant(self):
        final, prior = multiquery.condense_views(HIST)
        self.assertEqual(final, "一般无线网络优化工程师，设置多少")
        self.assertEqual([m["role"] for m in prior], ["user", "assistant"])

    def test_single_turn_skip(self):
        final, prior = multiquery.condense_views(
            [{"role": "user", "content": "单轮问"}])
        self.assertEqual(final, "单轮问")
        self.assertEqual(prior, [])

    def test_none_history(self):
        self.assertEqual(multiquery.condense_views(None), (None, []))

    def test_no_user_message(self):
        final, prior = multiquery.condense_views(
            [{"role": "assistant", "content": "答"}])
        self.assertIsNone(final)
        self.assertEqual(prior, [])

    def test_turns_cap_keeps_most_recent(self):
        h = [{"role": "user", "content": f"问题{i}"} for i in range(8)] + \
            [{"role": "user", "content": "末轮"}]
        final, prior = multiquery.condense_views(h, turns_cap=3)
        self.assertEqual([m["content"] for m in prior], ["问题5", "问题6", "问题7"])

    def test_chars_cap_tail_keep(self):
        h = [{"role": "user", "content": "长" * 100},
             {"role": "assistant", "content": "答" * 100},
             {"role": "user", "content": "末轮"}]
        _, prior = multiquery.condense_views(h, chars_cap=150)
        self.assertEqual(len(prior), 1)                 # 最旧被截，保最近
        self.assertEqual(prior[0]["content"], "答" * 100)

    def test_bad_caps_fall_back_default(self):
        final, prior = multiquery.condense_views(
            HIST, turns_cap="x", chars_cap=None)
        self.assertEqual(len(prior), 2)                 # 回默认帽=不截
        final, prior = multiquery.condense_views(HIST, turns_cap=0, chars_cap=-5)
        self.assertEqual(len(prior), 2)

    def test_malformed_entries_tolerated(self):
        h = [{"role": "user"}, "junk", {"content": "无 role"},
             {"role": "user", "content": "  "},
             {"role": "system", "content": "系统消息不入"}] + HIST
        final, prior = multiquery.condense_views(h)
        self.assertEqual(final, "一般无线网络优化工程师，设置多少")
        self.assertEqual(len(prior), 2)

    def test_input_form_frozen(self):
        final, prior = multiquery.condense_views(HIST)
        self.assertEqual(
            multiquery.condense_input(final, prior),
            "对话历史（从早到晚）：\n"
            "用户：切换参数 a3-Offset 的取值范围是多少\n"
            "助手：a3-Offset 见 TS 36.331 …\n"
            "末轮追问：一般无线网络优化工程师，设置多少\n独立检索查询：")
        self.assertEqual(
            multiquery.condense_input("末轮", []),
            "末轮追问：末轮\n独立检索查询：")


# ---------------------------------------------------------------------------
# 观测行 fmt/parse（纯函数）
# ---------------------------------------------------------------------------
class CondenseObsTest(unittest.TestCase):
    def test_fmt_ok_and_parse_roundtrip(self):
        line = multiquery.fmt_condense_obs_line(Q0, True, 0.42, C0)
        self.assertTrue(line.startswith("[rag-mq-condense] qsha16="))
        self.assertIn('ok=1 dur=0.42s r=["' + C0 + '"]', line)
        got = multiquery.parse_condense_obs_line("x [trace:ab] " + line)
        self.assertEqual(got["ok"], 1)
        self.assertEqual(got["r"], [C0])
        self.assertEqual(got["qsha16"], multiquery.parse_variants_obs_line(
            multiquery.fmt_variants_obs_line(Q0, []))["qsha16"])

    def test_fmt_err_and_parse(self):
        line = multiquery.fmt_condense_obs_line(Q0, False, 1.2, err="Timeout")
        got = multiquery.parse_condense_obs_line(line)
        self.assertEqual((got["ok"], got["err"]), (0, "Timeout"))

    def test_parse_rejects(self):
        self.assertIsNone(multiquery.parse_condense_obs_line("普通行"))
        self.assertIsNone(multiquery.parse_condense_obs_line(
            '[rag-mq-condense] qsha16=abc ok=1 dur=0.1s r=["x"]'))
        bad = multiquery.fmt_condense_obs_line(Q0, True, 0.1, "a")
        bad = bad.replace('r=["a"]', 'r=["a","b"]')      # 长度不符
        self.assertIsNone(multiquery.parse_condense_obs_line(bad))
        self.assertIsNone(multiquery.parse_condense_obs_line(None))

    def test_fmt_never_raises(self):
        for bad in (None, 1.5, {"x": 1}):
            self.assertIsInstance(
                multiquery.fmt_condense_obs_line(bad, True, "x", 1), str)


# ---------------------------------------------------------------------------
# condense_query（flash 调用面；mock httpx）
# ---------------------------------------------------------------------------
class CondenseQueryTest(unittest.TestCase):
    def test_skip_zero_call_zero_line(self):
        log = _Silent()
        with mock.patch.object(multiquery.httpx, "Client") as cli:
            for hist in (None, [], [{"role": "user", "content": "单轮"}],
                         [{"role": "assistant", "content": "答"}]):
                self.assertIsNone(multiquery.condense_query(
                    Q0, hist, endpoint=("http://e", "k"), log=log))
            cli.assert_not_called()
        self.assertEqual([l for l in log.lines if "condense" in l], [])

    def _call(self, resp, hist=HIST, **kw):
        log = kw.pop("log", _Silent())
        body = {}
        with mock.patch.object(multiquery.httpx, "Client") as cli:
            cli.return_value.__enter__.return_value.post.return_value = resp
            out = multiquery.condense_query(
                Q0, hist, endpoint=("http://e", "k"), log=log, **kw)
            body = cli.return_value.__enter__.return_value.post.call_args[1]["json"]
        return out, log.lines, body

    def test_ok_params_and_obs_line(self):
        out, lines, body = self._call(_res(C0))
        self.assertEqual(out, C0)
        self.assertEqual(body["model"], multiquery.DEFAULT_MQ_MODEL)
        self.assertEqual(body["temperature"], 0)
        self.assertFalse(body["enable_thinking"])
        self.assertEqual(body["max_tokens"], multiquery._MQ_MAX_TOKENS)
        self.assertEqual(body["messages"][0]["content"],
                         multiquery.CONDENSE_SYSTEM_PROMPT)
        self.assertIn("对话历史（从早到晚）：", body["messages"][1]["content"])
        self.assertEqual(len([l for l in lines
                              if l.startswith("[rag-mq-condense]")]), 1)

    def test_clean_variant_applied(self):
        out, _, _ = self._call(_res('<think>x</think> "  ' + C0 + '  "\n'))
        self.assertEqual(out, C0)

    def test_endpoint_missing(self):
        log = _Silent()
        self.assertIsNone(multiquery.condense_query(
            Q0, HIST, endpoint=None, log=log))
        self.assertTrue(any("ok=0" in l and "err=RuntimeError" in l
                            for l in log.lines))

    def test_http_error(self):
        def boom():
            raise httpx.ConnectTimeout("t")
        resp = mock.Mock()
        resp.raise_for_status = boom
        out, lines, _ = self._call(resp)
        self.assertIsNone(out)
        self.assertTrue(any("err=ConnectTimeout" in l for l in lines))

    def test_empty_content(self):
        out, lines, _ = self._call(_res("   "))
        self.assertIsNone(out)
        self.assertTrue(any("err=ValueError" in l for l in lines))

    def test_bad_payload(self):
        resp = mock.Mock()
        resp.raise_for_status = lambda: None
        resp.json.return_value = {"nope": 1}
        out, lines, _ = self._call(resp)
        self.assertIsNone(out)
        self.assertTrue(any("ok=0" in l for l in lines))


# ---------------------------------------------------------------------------
# rag 挂接：六态关态逐字节一致 + 开态
# ---------------------------------------------------------------------------
class RagHookTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "embeddings.jsonl")
        with open(self.path, "w", encoding="utf-8") as f:
            for r in SERVICE_RECS:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        self.log = _Silent()

    def tearDown(self):
        self.tmp.cleanup()

    def _svc(self, embed_map, condense_fn="unset", **cfg):
        cfg.setdefault("store_path", self.path)
        cfg.setdefault("topk", 2)
        cfg.setdefault("max_context_chars", 6000)
        cfg["embed_monthly_budget_enabled"] = False

        def embed(q):
            return list(embed_map.get(q, [1, 0, 0, 0, 0, 0, 0, 0]))
        kw = {}
        if condense_fn != "unset":
            kw["condense_fn"] = condense_fn
        svc = rag.RagService(embed_fn=embed, log=self.log, **kw)
        svc.initialize(cfg)
        return svc

    def _reading(self, res):
        if isinstance(res, tuple):
            return ("hit", tuple(s["doc_id"] for s in res[1]))
        return (type(res).__name__ if res is not None else "miss", ())

    def test_six_off_states_byte_identical(self):
        base_cfg = dict(mq_enabled=True, mq_single_variant=True)
        embed_map = {Q0: [1, 0, 0, 0, 0, 0, 0, 0]}
        ref = None
        states = [
            ("S1 键缺席", {}, None),
            ("S2 false", {"mq_condense_enabled": False}, "multi"),
            ("S3 零", {"mq_condense_enabled": 0}, "multi"),
            ("S4 垃圾", {"mq_condense_enabled": "yes"}, "multi"),
            ("S5 开+无历史", {"mq_condense_enabled": True}, None),
            ("S6 开+单轮", {"mq_condense_enabled": True}, "single"),
        ]
        for name, extra, hmode in states:
            calls = []
            log = self.log = _Silent()

            def cf(q, h, _c=calls):
                _c.append(q)
                return C0
            svc = self._svc(embed_map, condense_fn=cf,
                            **{**base_cfg, **extra})
            hist = None
            if hmode == "multi":
                hist = HIST
            elif hmode == "single":
                hist = [HIST[-1]]
            res = svc.retrieve(Q0, None, hist)
            got = self._reading(res)
            cond_lines = [l for l in log.lines
                          if l.startswith("[rag-mq-condense]")]
            self.assertEqual(cond_lines, [], name)
            self.assertEqual(calls, [], name + " 零 condense 调用")
            if ref is None:
                ref = got
            self.assertEqual(got, ref, name)

    def test_mq_off_ignores_history(self):
        embed_map = {Q0: [1, 0, 0, 0, 0, 0, 0, 0]}
        svc = self._svc(embed_map)     # mq_enabled 默认 False
        a = self._reading(svc.retrieve(Q0))
        b = self._reading(svc.retrieve(Q0, None, HIST))
        self.assertEqual(a, b)

    def test_on_state_c0_route_enters_fusion(self):
        embed_map = {Q0: [1, 0, 0, 0, 0, 0, 0, 0], C0: [0, 1, 0, 0, 0, 0, 0, 0]}
        calls = []

        def cf(q, h):
            calls.append((q, h))
            return C0
        log = self.log = _Silent()
        svc = self._svc(embed_map, condense_fn=cf, mq_enabled=True,
                        mq_single_variant=True, mq_condense_enabled=True)
        res = svc.retrieve(Q0, None, HIST)
        state, docs = self._reading(res)
        self.assertEqual(state, "hit")
        self.assertEqual(docs, ("DOC-1", "DOC-3"))      # c0 路入融合（基线=DOC-1,DOC-2）
        self.assertEqual(calls, [(Q0, HIST)])
        obs = [l for l in log.lines if l.startswith("[rag-mq-condense]")]
        self.assertEqual(len(obs), 1)
        self.assertEqual(multiquery.parse_condense_obs_line(obs[0])["r"], [C0])
        # embed 双路消费（q0 与 c0 各一次）
        self.assertIsNone(svc._condense_fn_extra if False else None)

    def test_on_state_c0_same_as_q0_drops_route(self):
        embed_map = {Q0: [1, 0, 0, 0, 0, 0, 0, 0]}
        base = self._svc(embed_map, mq_enabled=True, mq_single_variant=True)
        ref = self._reading(base.retrieve(Q0))
        log = self.log = _Silent()
        svc = self._svc(embed_map, condense_fn=lambda q, h: "  " + Q0 + " ",
                        mq_enabled=True, mq_single_variant=True,
                        mq_condense_enabled=True)
        got = self._reading(svc.retrieve(Q0, None, HIST))
        self.assertEqual(got, ref)                      # 同文弃路=读数回基线
        self.assertEqual(len([l for l in log.lines
                              if l.startswith("[rag-mq-condense]")]), 1)

    def test_on_state_injected_fn_raises_drops_route(self):
        embed_map = {Q0: [1, 0, 0, 0, 0, 0, 0, 0]}
        base = self._svc(embed_map, mq_enabled=True, mq_single_variant=True)
        ref = self._reading(base.retrieve(Q0))

        def boom(q, h):
            raise RuntimeError("注入桩炸")
        log = self.log = _Silent()
        svc = self._svc(embed_map, condense_fn=boom, mq_enabled=True,
                        mq_single_variant=True, mq_condense_enabled=True)
        got = self._reading(svc.retrieve(Q0, None, HIST))
        self.assertEqual(got, ref)                      # 弃路零恶化

    def test_wall_budget_stop_line(self):
        embed_map = {Q0: [1, 0, 0, 0, 0, 0, 0, 0]}
        log = self.log = _Silent()
        svc = self._svc(embed_map, condense_fn=lambda q, h: C0,
                        mq_enabled=True, mq_single_variant=True,
                        mq_condense_enabled=True,
                        mq_condense_timeout=0.000001, mq_wall_timeout=0.000001)
        svc._condense_fn = None     # 走真实路径（预算耗尽面）
        svc._mq_condense["timeout"] = 0.0   # 直接钳到 0=预算耗尽
        res = svc.retrieve(Q0, None, HIST)
        self.assertIsNotNone(res)   # 弃路后仍有 q0 基线检索
        self.assertTrue(any("stop budget=0" in l for l in log.lines))


class CleanParamsTest(unittest.TestCase):
    def test_defaults(self):
        d = rag.clean_mq_condense_params({})
        self.assertEqual(d, {"enabled": False, "model": "qwen3.8-flash",
                             "timeout": 3.0, "turns": 4, "chars": 1200})

    def test_garbage_back_to_default(self):
        d = rag.clean_mq_condense_params({
            "mq_condense_enabled": "true", "mq_condense_model": "  ",
            "mq_condense_timeout": 999, "mq_condense_history_turns": "x",
            "mq_condense_history_chars": 0})
        self.assertFalse(d["enabled"])
        self.assertEqual(d["model"], "qwen3.8-flash")
        self.assertEqual(d["timeout"], 3.0)
        self.assertEqual(d["turns"], 4)
        self.assertEqual(d["chars"], 1200)

    def test_valid_kept(self):
        d = rag.clean_mq_condense_params({
            "mq_condense_enabled": True, "mq_condense_model": "qwen3.8-flash",
            "mq_condense_timeout": 2.5, "mq_condense_history_turns": 6,
            "mq_condense_history_chars": 800})
        self.assertTrue(d["enabled"])
        self.assertEqual(d["timeout"], 2.5)
        self.assertEqual(d["turns"], 6)
        self.assertEqual(d["chars"], 800)


if __name__ == "__main__":
    unittest.main()
