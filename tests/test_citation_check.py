# -*- coding: utf-8 -*-
"""citation_check.py 纯逻辑离线单测（深度提升批A）：judge messages 构建、
A1 三类 verdict/label 与 JSON 畸形→None、A2 assess 解析与降级、墙钟超时→None、
高危面题本地启发式分类、token_plan_judge 请求形态（伪 httpx 零网络）。"""
import json
import time
import unittest
from unittest import mock

import citation_check as cc


SOURCES = [
    {"doc_id": "TS 36.331", "version": "V17", "locator": "§5.2.2", "score": 0.9,
     "quote": "T310 缺省值 1000 ms，N310 缺省值 n4"},
    {"doc_id": "YD/T 5089", "version": "2018", "locator": "表3", "score": 0.7,
     "quote": "无线链路失败判定计数示例"},
]


def _ok_judge(raw):
    """恒回固定字符串的 judge stub（记录调用参数）。"""
    calls = []

    def judge(messages, timeout):
        calls.append((messages, timeout))
        return raw
    judge.calls = calls
    return judge


class BuildJudgeMessagesTest(unittest.TestCase):
    def test_shape_and_required_fields(self):
        msgs = cc.build_judge_messages("T310 默认值？", "T310 默认 1000ms。", SOURCES)
        self.assertEqual(len(msgs), 2)
        self.assertEqual([m["role"] for m in msgs], ["system", "user"])
        # system 提示词要求严格 JSON：两枚举族与输出格式都在场
        sysc = msgs[0]["content"]
        for token in ("supports", "partial", "unsupported", "not_relevant",
                      "grounded", "inferred", "JSON"):
            self.assertIn(token, sysc)
        # user 消息含题面/正文/逐源编号+doc_id+quote
        u = msgs[1]["content"]
        self.assertIn("T310 默认值？", u)
        self.assertIn("T310 默认 1000ms。", u)
        self.assertIn("[出处1] TS 36.331 V17 §5.2.2", u)
        self.assertIn("[出处2] YD/T 5089", u)
        self.assertIn("T310 缺省值 1000 ms", u)

    def test_tolerates_bad_entries(self):
        # 非 dict 条目跳过、quote 缺失按空、None 输入不抛
        msgs = cc.build_judge_messages(None, None, [None, "x", {"doc_id": "D"}])
        self.assertIn("[出处1] D", msgs[1]["content"])
        self.assertEqual(len(msgs), 2)

    def test_build_assess_messages_shape(self):
        msgs = cc.build_assess_messages("T310 默认值？", "证据文本ABC")
        self.assertEqual([m["role"] for m in msgs], ["system", "user"])
        self.assertIn("sufficient", msgs[0]["content"])
        self.assertIn("insufficient", msgs[0]["content"])
        self.assertIn("证据文本ABC", msgs[1]["content"])
        self.assertIn("T310 默认值？", msgs[1]["content"])


class ParseCitationJsonTest(unittest.TestCase):
    def test_plain_and_fenced_and_preamble(self):
        good = {"per_source": [{"index": 1, "verdict": "supports"}], "label": "grounded"}
        raw = json.dumps(good, ensure_ascii=False)
        for wrapped in (raw, "```json\n" + raw + "\n```", "评审如下：\n" + raw,
                        "```\n" + raw + "\n```"):
            parsed = cc.parse_citation_json(wrapped)
            self.assertIsNotNone(parsed, wrapped)
            self.assertEqual(parsed["label"], "grounded")
            self.assertEqual(parsed["per_source"], [{"index": 1, "verdict": "supports"}])

    def test_all_verdicts_and_labels_accepted(self):
        for v in cc.VERDICTS:
            for lb in cc.LABELS:
                raw = json.dumps({"per_source": [{"index": 1, "verdict": v}], "label": lb})
                parsed = cc.parse_citation_json(raw)
                self.assertEqual(parsed, {"label": lb, "per_source": [{"index": 1, "verdict": v}]})

    def test_malformed_returns_none(self):
        bad = ["", None, 42, "不是JSON", "{broken", "[]",
               json.dumps({"label": "grounded"}),                       # 缺 per_source
               json.dumps({"per_source": [], "label": "hallucinated"}),  # label 越界
               json.dumps({"per_source": "x", "label": "grounded"}),     # per_source 非列表
               json.dumps({"per_source": [{"index": 1, "verdict": "支持"}],
                           "label": "grounded"})]                        # 只有畸形条目仍合法？
        for raw in bad[:-1]:
            self.assertIsNone(cc.parse_citation_json(raw), repr(raw))
        # 末例：条目 verdict 越界→逐条丢弃，整体仍回 label（条目级宽容）
        parsed = cc.parse_citation_json(bad[-1])
        self.assertEqual(parsed, {"label": "grounded", "per_source": []})

    def test_entry_level_leniency(self):
        raw = json.dumps({"per_source": [
            {"index": "2", "verdict": "partial"},   # index 字符串整数→容忍
            {"index": 3, "verdict": "越界值"},       # verdict 越界→丢条目
            "junk",                                  # 非 dict→丢
            {"verdict": "supports"},                 # 缺 index→丢
            {"index": 1, "verdict": "supports"}],
            "label": "partial", "extra": 1})
        parsed = cc.parse_citation_json(raw)
        self.assertEqual(parsed["label"], "partial")
        self.assertEqual(parsed["per_source"],
                         [{"index": 2, "verdict": "partial"},
                          {"index": 1, "verdict": "supports"}])


class ParseAssessJsonTest(unittest.TestCase):
    def test_ok(self):
        raw = json.dumps({"verdict": "insufficient", "reason": "语料未覆盖 T310 默认值"},
                         ensure_ascii=False)
        self.assertEqual(cc.parse_assess_json(raw),
                         {"verdict": "insufficient", "reason": "语料未覆盖 T310 默认值"})
        self.assertEqual(cc.parse_assess_json('{"verdict":"sufficient"}')["reason"], "")

    def test_malformed_returns_none(self):
        for raw in ("", None, "文本", '{"verdict": "maybe", "reason": "x"}',
                    '{"reason": "x"}', "[1,2]"):
            self.assertIsNone(cc.parse_assess_json(raw), repr(raw))

    def test_reason_flattened_and_truncated(self):
        raw = json.dumps({"verdict": "insufficient", "reason": " 换\n行\t理由 " + "长" * 400},
                         ensure_ascii=False)
        out = cc.parse_assess_json(raw)
        self.assertNotIn("\n", out["reason"])
        self.assertEqual(len(out["reason"]), cc.REASON_MAX_CHARS)


class CheckCitationTest(unittest.TestCase):
    def _raw(self, label="grounded", verdicts=("supports", "partial")):
        return json.dumps({
            "per_source": [{"index": i + 1, "verdict": v} for i, v in enumerate(verdicts)],
            "label": label})

    def test_success_maps_index_to_doc_id(self):
        judge = _ok_judge(self._raw("partial", ("supports", "unsupported")))
        out = cc.check_citation("题", "答案", SOURCES, judge, timeout=2.0, log=lambda line: None)
        self.assertEqual(out, {"label": "partial", "per_source": [
            {"doc_id": "TS 36.331", "verdict": "supports"},
            {"doc_id": "YD/T 5089", "verdict": "unsupported"}]})
        # judge 收到 (messages, timeout) 两参
        msgs, t = judge.calls[0]
        self.assertEqual(t, 2.0)
        self.assertEqual(msgs[0]["role"], "system")

    def test_three_labels_roundtrip(self):
        for lb in ("grounded", "partial", "inferred"):
            out = cc.check_citation("题", "答", SOURCES, _ok_judge(self._raw(lb)),
                                    timeout=1.0, log=lambda line: None)
            self.assertEqual(out["label"], lb)

    def test_malformed_json_returns_none(self):
        for raw in ("不是JSON", "", '{"label":"grounded"}', '{"per_source":[],"label":"x"}'):
            out = cc.check_citation("题", "答", SOURCES, _ok_judge(raw),
                                    timeout=1.0, log=lambda line: None)
            self.assertIsNone(out, repr(raw))

    def test_judge_exception_returns_none(self):
        def boom(messages, timeout):
            raise RuntimeError("端点炸了")
        self.assertIsNone(cc.check_citation("题", "答", SOURCES, boom,
                                            timeout=1.0, log=lambda line: None))

    def test_judge_none_returns_none(self):
        self.assertIsNone(cc.check_citation("题", "答", SOURCES, _ok_judge(None),
                                            timeout=1.0, log=lambda line: None))

    def test_timeout_returns_none(self):
        def slow(messages, timeout):
            time.sleep(2.0)
            return self._raw()
        t0 = time.time()
        out = cc.check_citation("题", "答", SOURCES, slow, timeout=0.2, log=lambda line: None)
        self.assertIsNone(out)
        self.assertLess(time.time() - t0, 1.5)  # 墙钟看门狗=预算+0.5s 宽限内即弃

    def test_guards_skip_judge(self):
        judge = _ok_judge(self._raw())
        # 空 sources / 空正文 / judge 不可调用 → None 且不打 judge
        self.assertIsNone(cc.check_citation("题", "答", [], judge, log=lambda line: None))
        self.assertIsNone(cc.check_citation("题", "  ", SOURCES, judge, log=lambda line: None))
        self.assertIsNone(cc.check_citation("题", "答", SOURCES, None, log=lambda line: None))
        self.assertEqual(judge.calls, [])

    def test_out_of_range_index_dropped(self):
        raw = json.dumps({"per_source": [{"index": 9, "verdict": "supports"},
                                          {"index": 0, "verdict": "partial"}],
                          "label": "inferred"})
        out = cc.check_citation("题", "答", SOURCES, _ok_judge(raw),
                                timeout=1.0, log=lambda line: None)
        self.assertEqual(out, {"label": "inferred", "per_source": []})


class AssessEvidenceTest(unittest.TestCase):
    def test_sufficient_and_insufficient(self):
        for v in ("sufficient", "insufficient"):
            raw = json.dumps({"verdict": v, "reason": "理由"}, ensure_ascii=False)
            out = cc.assess_evidence("题", "证据", _ok_judge(raw),
                                     timeout=1.0, log=lambda line: None)
            self.assertEqual(out, {"verdict": v, "reason": "理由"})

    def test_malformed_and_exception_and_timeout_return_none(self):
        self.assertIsNone(cc.assess_evidence("题", "证据", _ok_judge("乱码"),
                                             timeout=1.0, log=lambda line: None))

        def boom(messages, timeout):
            raise RuntimeError("x")
        self.assertIsNone(cc.assess_evidence("题", "证据", boom,
                                             timeout=1.0, log=lambda line: None))

        def slow(messages, timeout):
            time.sleep(2.0)
            return '{"verdict": "sufficient"}'
        self.assertIsNone(cc.assess_evidence("题", "证据", slow,
                                             timeout=0.2, log=lambda line: None))

    def test_empty_evidence_skips_judge(self):
        judge = _ok_judge('{"verdict": "sufficient"}')
        self.assertIsNone(cc.assess_evidence("题", "  ", judge, log=lambda line: None))
        self.assertEqual(judge.calls, [])


class HighStakesQuestionTest(unittest.TestCase):
    """A2 前置闸门：高危面题（精确数字/参数名/取值范围/表值类）本地启发式。"""

    POSITIVE = [
        "T310定时器的默认值是多少？",
        "p0-NominalPUSCH 的取值范围",
        "N310 门限怎么配",
        "上行最大发射功率是多少 dBm",
        "RSRP 上报门限的配置值",
        "切换迟滞 Hysteresis 参数值是多少",
        "表3 里 T304 的上限和下限",
    ]
    NEGATIVE = [
        "什么是切换",
        "你好",
        "介绍一下5G网络的基本架构",
        "请总结一下这份规范讲了什么",
        "",
        None,
    ]

    # 词表 v2 修订③双件同步面（2026-09-29 批，8de6185 遗留销项）：
    # 单数字记号形（p0/N1 型）+参数语境词组合触发；事件名形排除；无语境词不触发
    POSITIVE_V2_SYMBOL = [
        "p0-Nominal 的含义是什么",
        "N1 接口的定义是什么",
    ]
    NEGATIVE_V2_SYMBOL_EVENT = [
        "A3 和 A5 事件有什么区别",   # 事件名形（A1-A6/B1/B2）排除集承接
    ]
    NEGATIVE_V2_SYMBOL_NOCTX = [
        "p0-Nominal 相关的流程概述",  # 记号形单独出现（无参数语境词）不触发
    ]

    def test_positive_cases(self):
        for q in self.POSITIVE:
            self.assertTrue(cc.is_high_stakes_question(q), q)

    def test_negative_cases(self):
        for q in self.NEGATIVE:
            self.assertFalse(cc.is_high_stakes_question(q), repr(q))

    def test_v2_symbol_positive_cases(self):
        for q in self.POSITIVE_V2_SYMBOL:
            self.assertTrue(cc.is_high_stakes_question(q), q)

    def test_v2_symbol_event_names_excluded(self):
        for q in self.NEGATIVE_V2_SYMBOL_EVENT:
            self.assertFalse(cc.is_high_stakes_question(q), q)

    def test_v2_symbol_without_context_no_hit(self):
        for q in self.NEGATIVE_V2_SYMBOL_NOCTX:
            self.assertFalse(cc.is_high_stakes_question(q), q)


class SymbolVocabSyncTest(unittest.TestCase):
    """双件同源逐字锁（2026-09-29 双件同步批）：cc 三新常量与 route_domain 的
    PARAM_V2_SYMBOL_RE.pattern/EXCLUDE/CONTEXT 逐字一致——机制化防单侧漂移
    （任一侧改词表/正则必红本类；本体 import 复用同一性锁在
    tests/test_route_domain.py test_high_stakes_import_not_copy）。"""

    def test_symbol_constants_verbatim_identical(self):
        import route_domain as rd
        self.assertEqual(cc.HIGH_STAKES_SYMBOL_RE.pattern,
                         rd.PARAM_V2_SYMBOL_RE.pattern)
        self.assertEqual(cc.HIGH_STAKES_SYMBOL_EXCLUDE,
                         rd.PARAM_V2_SYMBOL_EXCLUDE)
        self.assertEqual(cc.HIGH_STAKES_SYMBOL_CONTEXT,
                         rd.PARAM_V2_SYMBOL_CONTEXT)


class CrossFileVetoPropertyTest(unittest.TestCase):
    """跨件性质锁扩例（先例=tests/test_route_domain.py
    test_high_stakes_subset_of_veto）：固定语料上凡 cc.is_high_stakes_question
    命中 → route 侧 veto=1（route_domain.py:53 单锚 import 链；修订③双件同步
    后扩入单数字记号形题面）。防空转断言：语料必含命中。"""

    CORPUS = [
        # v2 修订③单数字记号形（本批新增面）
        "p0-Nominal 的含义是什么",
        "N1 接口的定义是什么",
        "N311 参数的默认值",
        # 既有 HIGH_STAKES 面（关键词/双数字记号/数值+单位）
        "T310定时器的默认值是多少？",
        "p0-NominalPUSCH 的取值范围",
        "上行最大发射功率是多少 dBm",
        "-95dBm 的门限含义",
        # 事件名形：cc 侧不触发（排除集），route 侧概念域定向不受影响
        "A3 和 A5 事件有什么区别",
        "A3 事件进入条件里的偏移怎么取值",
        # 记号形无语境词：cc 侧不触发
        "p0-Nominal 相关的流程概述",
        # 纯概念题：两侧俱不触发红线
        "什么是切换",
        "SSB 波束最多可配几个",
    ]

    def test_high_stakes_hits_imply_route_veto(self):
        import route_domain as rd
        hits = 0
        for q in self.CORPUS:
            if cc.is_high_stakes_question(q):
                hits += 1
                self.assertEqual(rd.classify(q)["veto"], 1, q)
        self.assertGreater(hits, 0)   # 防空转：语料必含 cc 命中题面


class _FakeResp:
    def __init__(self, data, status=200):
        self._data = data
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._data


class _FakeClient:
    captured = {}

    def __init__(self, *a, **k):
        _FakeClient.captured["init"] = k

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, json=None, headers=None):
        _FakeClient.captured.update(url=url, body=json, headers=headers)
        return _FakeResp({"choices": [{"message": {"content": '{"label":"grounded"}'}}]})


class TokenPlanJudgeTest(unittest.TestCase):
    """生产 judge 薄壳（伪 httpx 零网络）：请求形态、content 提取、失败抛出、key 不落日志。"""

    def test_request_shape_and_content(self):
        logs = []
        with mock.patch.object(cc.httpx, "Client", _FakeClient):
            out = cc.token_plan_judge(
                [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
                api_key="sk-secret", model="judge-model",
                upstream="https://stub/chat/completions", timeout=2.5,
                log=logs.append)
        self.assertEqual(out, '{"label":"grounded"}')
        cap = _FakeClient.captured
        self.assertEqual(cap["url"], "https://stub/chat/completions")
        self.assertEqual(cap["body"]["model"], "judge-model")
        self.assertEqual(cap["body"]["temperature"], 0)
        self.assertFalse(cap["body"]["stream"])
        self.assertFalse(cap["body"]["enable_thinking"])
        self.assertEqual(cap["headers"]["Authorization"], "Bearer sk-secret")
        self.assertEqual(cap["init"]["timeout"], 2.5)
        self.assertTrue(any("ok=1" in ln for ln in logs))
        self.assertFalse(any("sk-secret" in ln for ln in logs))  # key 绝不落日志

    def test_http_error_raises_and_logs_type_only(self):
        class _ErrClient(_FakeClient):
            def post(self, url, json=None, headers=None):
                return _FakeResp({}, status=500)
        logs = []
        with mock.patch.object(cc.httpx, "Client", _ErrClient):
            with self.assertRaises(RuntimeError):
                cc.token_plan_judge([], api_key="sk-secret", model="m",
                                    upstream="https://stub", timeout=1.0,
                                    log=logs.append)
        self.assertTrue(any("ok=0" in ln for ln in logs))
        self.assertFalse(any("sk-secret" in ln for ln in logs))

    def test_empty_content_raises(self):
        class _EmptyClient(_FakeClient):
            def post(self, url, json=None, headers=None):
                return _FakeResp({"choices": [{"message": {"content": "  "}}]})
        with mock.patch.object(cc.httpx, "Client", _EmptyClient):
            with self.assertRaises(ValueError):
                cc.token_plan_judge([], api_key="k", model="m",
                                    upstream="https://stub", log=lambda line: None)


class BudgetNormTest(unittest.TestCase):
    def test_bad_timeout_falls_back_to_default(self):
        self.assertEqual(cc._norm_budget(None), cc.DEFAULT_CC_TIMEOUT_SECONDS)
        self.assertEqual(cc._norm_budget("abc"), cc.DEFAULT_CC_TIMEOUT_SECONDS)
        self.assertEqual(cc._norm_budget(-1), cc.DEFAULT_CC_TIMEOUT_SECONDS)
        self.assertEqual(cc._norm_budget(0), cc.DEFAULT_CC_TIMEOUT_SECONDS)
        self.assertEqual(cc._norm_budget("2.5"), 2.5)


if __name__ == "__main__":
    unittest.main()
