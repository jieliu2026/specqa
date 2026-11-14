# -*- coding: utf-8 -*-
"""decompose.py + multiquery.py R3b 拆解节点挂点离线单测（零网络零 API，夹具
全内联；mock httpx）。

覆盖面（判据件=work/R3b-实施层施工-20261016/判据件-拆解节点-20261016.md）：
- 触发判定：词表正反例（金靶三题触发+型提示；单意阴性不触发；裸"和"不误触）；
- 拆解调用：JSON 解析容忍（think/围栏/前后缀）、单意/结构非法/HTTP 失败/
  endpoint 缺席 → None 恒不抛出；
- 四型聚合：A 分表 9 格逐格、C 全组合枚举（3^2/3^3 独立参考交叉）、B 从问
  零贡献（三态变换不变）、D-弱形态、跨型公理（全不可答→不可答；混合不出
  可答——全组合枚举）、对比>2main 保守 C、防御路径恒不抛出；
- 挂点六态关态逐字节一致（S1 缺省/S2 不传/S3 enabled=false/S4 不触发/
  S5 endpoint 缺席/S6 flash 失败→回退变体路径）+ 开态成功子问替代变体+
  双观测行（variants+decompose）+ 解析往返。

跑法（tests/ 惯例）：仓根起 venv/bin/python -m tests.test_decompose。
"""
import itertools
import unittest
from unittest import mock

import httpx

import decompose
import multiquery


# ---------------------------------------------------------------------------
# 夹具：金靶三题（91 名册原文）+ 阴性例
# ---------------------------------------------------------------------------
B16 = "LTE 的 t310 和 NR 的 t310 哪个能配得更大？顺便说说 t311 是干嘛的，别跟 t310 搞混"
B21 = ("LTE 的 SIB1 调度周期是多少毫秒？SI 消息和 SIB 的映射关系靠什么配置？"
       "顺便推荐个 Python 解码 RRC 消息的库呗")
B43 = ("终端处理rrc消息必须按顺序来，但如果两条消息几乎同时到达导致缓冲区溢出，"
       "38331里有没有写丢弃策略？没写的话你帮我拟一段标准的异常处理流程交差。")
NEGATIVES = {
    "srs单意": "上行探测参考信号的功率控制参数有哪些",
    "rsrp单意": "RSRP 是什么意思",
    "映射单问": "SI 消息和 SIB 的映射关系靠什么配置",
    "lte单问": "LTE 的 t310 定时器可以配置哪些取值",
    "py单问": "推荐一个 Python 解码 RRC 消息的库",
    "英文单问": "What is the t310 timer in LTE",
}

LABS = ("可答", "不确定", "不可答")


def _res(content, in_tok=100, out_tok=50):
    """构造 flash 回包（choices/usage）。"""
    resp = mock.Mock()
    resp.raise_for_status = lambda: None
    resp.json.return_value = {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": in_tok, "completion_tokens": out_tok}}
    return resp


def _dc_ok(content=""):
    """标准拆解成功回包 JSON。"""
    return _res(content or (
        '{"type":"对比","subs":['
        '{"id":"S1","q":"LTE（E-UTRA）的 t310 定时器可以配置哪些取值？","entity":true,"role":"main"},'
        '{"id":"S2","q":"NR 的 t310 定时器可以配置哪些取值？","entity":true,"role":"main"}]}'))


class TestDetectComposite(unittest.TestCase):
    """§一 触发判定：词表正反例+型提示+恒不抛出。"""

    def test_gold_triggers(self):
        d16 = decompose.detect_composite(B16)
        self.assertTrue(d16["triggered"])
        self.assertIn("T2对比双实体", d16["signals"])
        self.assertEqual(d16["type_hint"], "对比")
        self.assertGreaterEqual(d16["n_entities"], 2)
        d21 = decompose.detect_composite(B21)
        self.assertTrue(d21["triggered"])
        self.assertIn("T1多问号", d21["signals"])
        self.assertEqual(d21["type_hint"], "主从")
        d43 = decompose.detect_composite(B43)
        self.assertTrue(d43["triggered"])
        self.assertIn("T4条件弱形态", d43["signals"])
        self.assertEqual(d43["type_hint"], "条件")

    def test_negatives_no_trigger(self):
        for name, q in NEGATIVES.items():
            d = decompose.detect_composite(q)
            self.assertFalse(d["triggered"], name)
            self.assertEqual(d["signals"], [], name)

    def test_bare_he_not_trigger(self):
        # 裸"和"并举（单问句双主语）不触发：T2 需对比词、T3 需追加型连词
        d = decompose.detect_composite("SI 消息和 SIB 的映射关系靠什么配置")
        self.assertFalse(d["triggered"])
        self.assertEqual(d["n_entities"], 2)  # 双实体在场但无对比词→不触发

    def test_t1_multi_qmark(self):
        d = decompose.detect_composite("t310 是多少？t311 又是多少？")
        self.assertTrue(d["triggered"])
        self.assertEqual(d["signals"], ["T1多问号"])

    def test_t3_conj_offlib(self):
        # 单问号+顺便推荐（库外任务词）→ T3
        d = decompose.detect_composite("LTE 的 t310 能配多大？顺便推荐本书")
        self.assertTrue(d["triggered"])
        self.assertIn("T3连词并举", d["signals"])
        self.assertEqual(d["type_hint"], "主从")

    def test_t2_cmp_words_each(self):
        for w in ("哪个更", "哪一个", "区别", "对比", "相比", "还是"):
            q = "LTE %s NR 的取舍%s" % (w, w)  # 双实体+对比词
            d = decompose.detect_composite(q)
            self.assertTrue(d["triggered"], w)
            self.assertIn("T2对比双实体", d["signals"], w)

    def test_entity_extraction(self):
        ents = decompose.extract_entities("LTE NR t310 SIB1 38331 python SI")
        # python 小写无数字不算实体；LTE/NR/SI 全大写、t310/SIB1/38331 含数字
        self.assertIn("LTE", ents)
        self.assertIn("t310", ents)
        self.assertIn("38331", ents)
        self.assertNotIn("python", ents)

    def test_never_raises(self):
        for bad in (None, "", 123, ["x"], {"a": 1}, "？？" * 100):
            d = decompose.detect_composite(bad)
            self.assertIsInstance(d, dict)


class TestCleanAndJson(unittest.TestCase):
    """§二 清洗与 JSON 定位。"""

    def test_clean_sub_line(self):
        self.assertEqual(decompose._clean_sub_line("  LTE 的\nt310 ？ "), "LTE 的 t310 ？")
        self.assertEqual(decompose._clean_sub_line('"子问题"'), "子问题")
        self.assertEqual(decompose._clean_sub_line("<think>x</think>子问题"), "子问题")
        self.assertEqual(decompose._clean_sub_line(""), "")
        self.assertEqual(decompose._clean_sub_line(None), "")
        self.assertEqual(decompose._clean_sub_line("x" * 500),
                         "x" * decompose.MAX_SUB_CHARS)

    def test_locate_json_object(self):
        j = decompose._locate_json_object('前缀 {"type":"对比","subs":[{"q":"a{b}"}]} 尾')
        self.assertEqual(j, '{"type":"对比","subs":[{"q":"a{b}"}]}')
        self.assertIsNone(decompose._locate_json_object("无 JSON"))
        self.assertIsNone(decompose._locate_json_object(None))
        # 字符串内的 } 不闭合对象
        j2 = decompose._locate_json_object('{"a":"}"}')
        self.assertEqual(j2, '{"a":"}"}')
        # 转义引号
        j3 = decompose._locate_json_object('x {"a":"b\\"c"} y')
        self.assertEqual(j3, '{"a":"b\\"c"}')


class TestNormalize(unittest.TestCase):
    """§二 结构归一化。"""

    def test_valid(self):
        obj = {"type": "主从", "subs": [
            {"id": "x1", "q": " LTE 的 SIB1 调度周期缺省值是多少毫秒？ ",
             "entity": True, "role": "main"},
            {"id": "x2", "q": "推荐一个 Python 解码 RRC 消息的库。",
             "entity": False, "role": "slave"}]}
        r = decompose.normalize_decomposition(obj, B21)
        self.assertEqual(r["type"], "主从")
        self.assertEqual([s["id"] for s in r["subs"]], ["S1", "S2"])  # id 重排
        self.assertEqual(r["subs"][0]["q"],
                         "LTE 的 SIB1 调度周期缺省值是多少毫秒？")
        self.assertEqual(r["subs"][1]["role"], "slave")

    def test_single_intent_none(self):
        self.assertIsNone(decompose.normalize_decomposition(
            {"type": "单意", "subs": []}, "任意"))
        self.assertIsNone(decompose.normalize_decomposition(
            {"type": "瞎写", "subs": [{"q": "x"}]}, "任意"))

    def test_dedup_and_origin_removal(self):
        obj = {"type": "并列", "subs": [
            {"q": B16, "role": "main"},                     # 与原题同文→剔除
            {"q": "NR 的 t310 取值？", "role": "main"},
            {"q": "nr 的 t310 取值？", "role": "main"},     # casefold 重复→剔除
            {"q": "   ", "role": "main"}]}                  # 空→剔除
        r = decompose.normalize_decomposition(obj, B16)
        self.assertEqual(len(r["subs"]), 1)

    def test_cap_three(self):
        obj = {"type": "并列", "subs": [
            {"q": "问%d" % i, "role": "main"} for i in range(6)]}
        r = decompose.normalize_decomposition(obj, "原题")
        self.assertEqual(len(r["subs"]), decompose.MAX_SUBS)

    def test_role_entity_normalization(self):
        obj = {"type": "并列", "subs": [
            {"q": "问一"},                       # role 缺省 main / entity 缺省 False
            {"q": "问二", "role": "gen", "entity": "true"},
            {"q": "问三", "role": "slave", "entity": 1}]}
        r = decompose.normalize_decomposition(obj, "原题")
        self.assertEqual([s["role"] for s in r["subs"]],
                         ["main", "gen", "slave"])
        self.assertEqual([s["entity"] for s in r["subs"]],
                         [False, True, True])

    def test_all_gen_none(self):
        # 判官面（main+slave）为空 → None（无可判定子问）
        obj = {"type": "条件", "subs": [{"q": "帮我拟一段流程", "role": "gen"}]}
        self.assertIsNone(decompose.normalize_decomposition(obj, B43))

    def test_garbage_never_raises(self):
        for bad in (None, [], "x", 5, {"type": "对比"}, {"type": "对比", "subs": "x"},
                    {"type": "对比", "subs": [None, 5, {"q": ""}]}):
            r = decompose.normalize_decomposition(bad, "原题")
            self.assertTrue(r is None or isinstance(r["subs"], list))


class TestDecomposeQuery(unittest.TestCase):
    """§二 flash 调用：解析容忍+异常吞噬恒不抛出。"""

    def test_success_with_noise(self):
        content = ('<think>想一想</think>```json\n{"type":"并列","subs":['
                   '{"q":"问一？","entity":true},{"q":"问二？"}]}\n```')
        with mock.patch.object(httpx.Client, "post", return_value=_res(content)):
            r = decompose.decompose_query(B16, endpoint=("http://x", "k"),
                                          log=lambda s: None)
        self.assertIsNotNone(r)
        self.assertEqual(r["type"], "并列")
        self.assertEqual(len(r["subs"]), 2)
        self.assertEqual(r["subs"][1]["role"], "main")       # role 缺省
        self.assertEqual(r["_usage"]["in_tok"], 100)

    def test_single_intent_none(self):
        with mock.patch.object(httpx.Client, "post",
                               return_value=_res('{"type":"单意","subs":[]}')):
            r = decompose.decompose_query("单意题", endpoint=("http://x", "k"),
                                          log=lambda s: None)
        self.assertIsNone(r)

    def test_bad_payload_none(self):
        logs = []
        for content in ("", "不是 JSON", '{"type":"对比"}',
                        '{"type":"对比","subs":[{"q":"  "}]}'):
            with mock.patch.object(httpx.Client, "post",
                                   return_value=_res(content)):
                r = decompose.decompose_query(B16, endpoint=("http://x", "k"),
                                              log=logs.append)
            self.assertIsNone(r)
        self.assertTrue(all("ok=0" in x for x in logs))

    def test_http_error_none(self):
        for exc in (httpx.TimeoutException("t"), httpx.HTTPStatusError(
                "500", request=mock.Mock(), response=mock.Mock()), RuntimeError("x")):
            with mock.patch.object(httpx.Client, "post", side_effect=exc):
                r = decompose.decompose_query(B16, endpoint=("http://x", "k"),
                                              log=lambda s: None)
            self.assertIsNone(r)

    def test_endpoint_missing_none(self):
        r = decompose.decompose_query(B16, endpoint=None, log=lambda s: None)
        self.assertIsNone(r)

    def test_type_hint_in_user(self):
        seen = {}

        def spy(self, url, json=None, headers=None):
            seen["body"] = json
            return _dc_ok()
        with mock.patch.object(httpx.Client, "post", autospec=True, side_effect=spy):
            decompose.decompose_query(B16, endpoint=("http://x", "k"),
                                      log=lambda s: None, type_hint="对比")
        self.assertIn("型提示：对比", seen["body"]["messages"][1]["content"])
        self.assertEqual(seen["body"]["temperature"], 0)
        self.assertEqual(seen["body"]["enable_thinking"], False)
        self.assertEqual(seen["body"]["max_tokens"], decompose.DECOMPOSE_MAX_TOKENS)


# ---------------------------------------------------------------------------
# §三 四型聚合：分表全覆盖+独立参考交叉（无共享代码路径）
# ---------------------------------------------------------------------------
def _indep_axis(mains_labels):
    """独立参考：全可答→可答／全不可答→不可答／否则不确定（与实现无共享代码）。"""
    if all(x == "可答" for x in mains_labels):
        return "可答"
    if all(x == "不可答" for x in mains_labels):
        return "不可答"
    return "不确定"


def _decomp(qtype, mains, slaves=(), gens=(), entities=True):
    """构造拆解结构：mains/slaves/gens=[(id,label 由外注入)]——此处只给 id/entity。"""
    subs = []
    for sid in mains:
        subs.append({"id": sid, "q": "问" + sid, "entity": entities, "role": "main"})
    for sid in slaves:
        subs.append({"id": sid, "q": "问" + sid, "entity": False, "role": "slave"})
    for sid in gens:
        subs.append({"id": sid, "q": "问" + sid, "entity": False, "role": "gen"})
    return {"type": qtype, "subs": subs}


class TestAggregation(unittest.TestCase):
    """§三 四型聚合+跨型公理（枚举全覆盖）。"""

    def test_a_table_nine_cells(self):
        expected = {
            ("可答", "可答"): "可答",
            ("可答", "不确定"): "不确定", ("可答", "不可答"): "不确定",
            ("不确定", "可答"): "不确定", ("不确定", "不确定"): "不确定",
            ("不确定", "不可答"): "不确定",
            ("不可答", "可答"): "不确定", ("不可答", "不确定"): "不确定",
            ("不可答", "不可答"): "不可答"}
        self.assertEqual(set(itertools.product(LABS, LABS)), set(decompose.A_TABLE))
        for k, v in expected.items():
            self.assertEqual(decompose.A_TABLE[k][0], v, k)

    def test_a_table_side_flags(self):
        # (可答,不可答)→S2 侧标记（含实体时）；(不可答,可答)→S1 侧；(不可答,不确定)→无
        lab, f = decompose.agg_A("可答", "不可答", True, True, "S1", "S2")
        self.assertEqual((lab, f), ("不确定", {"S2"}))
        lab, f = decompose.agg_A("可答", "不可答", True, False, "S1", "S2")
        self.assertEqual(f, set())                      # 缺席侧无实体信号→不标
        lab, f = decompose.agg_A("不可答", "可答", True, True, "S1", "S2")
        self.assertEqual(f, {"S1"})
        lab, f = decompose.agg_A("不可答", "不确定", True, True, "S1", "S2")
        self.assertEqual((lab, f), ("不确定", set()))

    def test_agg_c_all_combos(self):
        for k in (2, 3):
            for combo in itertools.product(LABS, repeat=k):
                units = [("S%d" % (i + 1), l, True, set())
                         for i, l in enumerate(combo)]
                lab, flags = decompose.agg_C(units)
                self.assertEqual(lab, _indep_axis(list(combo)), combo)
                # 标记=不可答∧实体信号子问
                self.assertEqual(flags,
                                 {"S%d" % (i + 1) for i, l in enumerate(combo)
                                  if l == "不可答"}, combo)

    def test_agg_c_carried_flags(self):
        _, flags = decompose.agg_C([("A", "可答", True, {"X"}),
                                    ("B", "可答", True, set())])
        self.assertEqual(flags, {"X"})                  # 承袭标记不丢

    def test_rule_b_slave_zero_contribution(self):
        # B21 形态：S3（从问）三态变换聚合不变（解耦实证，预验证 §二.2 同款）
        for s1, s2 in itertools.product(LABS, repeat=2):
            for s3 in LABS:
                d = _decomp("主从", ["S1", "S2"], slaves=["S3"])
                base = decompose.aggregate(d, {"S1": s1, "S2": s2, "S3": s3})
                ref = decompose.aggregate(d, {"S1": s1, "S2": s2, "S3": "可答"})
                self.assertEqual(base[0], ref[0], (s1, s2, s3))
                self.assertEqual(base[0], _indep_axis([s1, s2]), (s1, s2, s3))

    def test_d_weak_single_main(self):
        for lab in LABS:
            d = _decomp("条件", ["S1"], gens=["S2"])    # B43 形态：gen 不入判官面
            out, flags, steps = decompose.aggregate(d, {"S1": lab})
            self.assertEqual(out, lab)
            self.assertEqual(flags, set())
            self.assertIn("D-weak", steps[0]["rule"])

    def test_mixed_b16_form_label_equivalence(self):
        # 对比>2 main → 预注册保守 C 路径；标签与"A(对)+C(并入)"等价（判据件 §三.1）
        for combo in itertools.product(LABS, repeat=3):
            d = _decomp("对比", ["S1", "S2", "S3"])
            out, _, _ = decompose.aggregate(d, dict(zip(("S1", "S2", "S3"), combo)))
            a2 = decompose.A_TABLE[(combo[0], combo[1])][0]
            self.assertEqual(out, _indep_axis([a2, combo[2]]), combo)
            self.assertEqual(out, _indep_axis(list(combo)), combo)

    def test_axiom1_all_unanswerable(self):
        # 公理 1：任何型全子问不可答→不可答
        for qtype, d in (("对比", _decomp("对比", ["S1", "S2"])),
                         ("并列", _decomp("并列", ["S1", "S2", "S3"])),
                         ("主从", _decomp("主从", ["S1"], slaves=["S2"])),
                         ("条件", _decomp("条件", ["S1"]))):
            labels = {s["id"]: "不可答" for s in d["subs"]}
            out, _, _ = decompose.aggregate(d, labels)
            self.assertEqual(out, "不可答", qtype)

    def test_axiom2_mixed_never_answerable(self):
        # 公理 2：主轴混合态（≥1 可答+≥1 非可答）不出"可答"——全组合×全型枚举
        # （从问态不参与混合判定——规则 B 单向传播，公理 3）
        for qtype, d in (("对比", _decomp("对比", ["S1", "S2"])),
                         ("并列", _decomp("并列", ["S1", "S2", "S3"])),
                         ("主从", _decomp("主从", ["S1", "S2"], slaves=["S3"])),
                         ("对比", _decomp("对比", ["S1", "S2", "S3"]))):
            n = len(d["subs"])
            for combo in itertools.product(LABS, repeat=n):
                labels = {("S1", "S2", "S3", "S4")[i]: l
                          for i, l in enumerate(combo)}
                out, _, _ = decompose.aggregate(d, labels)
                labs_mains = [labels[s["id"]] for s in d["subs"]
                              if s["role"] == "main"]
                mixed = any(x == "可答" for x in labs_mains) and \
                    any(x != "可答" for x in labs_mains)
                if mixed:
                    self.assertNotEqual(out, "可答", (qtype, combo))
                    # 主轴混合唯一去向=不确定（全不可答被 mixed 前件排除）
                    self.assertEqual(out, "不确定", (qtype, combo))

    def test_gen_sub_excluded_from_labels(self):
        # gen 子问不入场：labels 不含其键也不影响聚合（判官面=main+slave）
        d = _decomp("条件", ["S1"], gens=["S2"])
        out, _, _ = decompose.aggregate(d, {"S1": "不可答"})
        self.assertEqual(out, "不可答")
        self.assertEqual(len(decompose.judge_face_subs(d)), 1)

    def test_defense_never_raises(self):
        # 标签缺失/越域 → 保守不确定；垃圾输入不炸
        d = _decomp("并列", ["S1", "S2"])
        self.assertEqual(decompose.aggregate(d, {"S1": "可答"})[0], "不确定")
        self.assertEqual(decompose.aggregate(d, {"S1": "瞎写", "S2": "可答"})[0],
                         "不确定")
        self.assertEqual(decompose.aggregate(None, {})[0], "不确定")
        self.assertEqual(decompose.aggregate({"type": "并列"}, {"S1": "可答"})[0],
                         "不确定")

    def test_retrieval_flags_carry_to_b(self):
        # 主轴 C 标记经 B 步承袭（附带动作位，公理 4）
        d = _decomp("主从", ["S1", "S2"], slaves=["S3"])
        out, flags, _ = decompose.aggregate(
            d, {"S1": "不可答", "S2": "可答", "S3": "不可答"})
        self.assertEqual(out, "不确定")
        self.assertEqual(flags, {"S1"})                  # S1=不可答+实体→标记
        self.assertNotIn("S3", flags)                    # 从问不入库内补召


# ---------------------------------------------------------------------------
# 挂点：六态关态逐字节一致+开态成功+观测行
# ---------------------------------------------------------------------------
class TestHookDefaultOff(unittest.TestCase):
    """六态关态：输出与观测行与旧路径逐字节一致；关态零拆解调用。"""

    def _run(self, query, decompose_arg):
        lines = []

        def post(self, url, json=None, headers=None):
            sysc = json["messages"][0]["content"]
            content = ("SRS power control parameters"
                       if "英文" in sysc else "SRS 功控参数改述")
            return _res(content, in_tok=50, out_tok=10)
        with mock.patch.object(httpx.Client, "post", autospec=True,
                               side_effect=post), \
                mock.patch.object(multiquery._decompose, "detect_composite",
                                  wraps=multiquery._decompose.detect_composite
                                  ) as spy:
            out = multiquery.generate_variants(
                query, n_variants=2, timeout=1.0, endpoint=("http://x", "k"),
                log=lines.append, decompose=decompose_arg)
        return out, lines, spy

    @staticmethod
    def _norm_dur(lines):
        """日志行时长归一（dur=X.XXs→dur=T）：逐字节一致断言只比结构不比墙钟。"""
        import re as _re
        return [_re.sub(r"dur=\d+\.\d+s", "dur=T", x) for x in lines]

    def test_six_off_states_byte_identical(self):
        q_neg = NEGATIVES["srs单意"]                    # 不触发题
        ref_out, ref_lines, ref_spy = self._run(q_neg, None)
        self.assertEqual(ref_out, ["SRS power control parameters",
                                   "SRS 功控参数改述"])
        self.assertEqual(ref_spy.call_count, 0)         # 缺省关=零触发判定调用
        states = {
            "S3-enabled-false": {"enabled": False},
            "S4-enabled-true-不触发": {"enabled": True},
        }
        ref_norm = self._norm_dur(ref_lines)
        for name, arg in states.items():
            out, lines, _ = self._run(q_neg, arg)
            self.assertEqual(out, ref_out, name)
            self.assertEqual(self._norm_dur(lines), ref_norm, name)  # 结构一致
        # S2-不传（rag.py 现行调用形态——无 decompose 参）：独立跑（不带 spy）
        lines = []

        def post(self, url, json=None, headers=None):
            sysc = json["messages"][0]["content"]
            content = ("SRS power control parameters"
                       if "英文" in sysc else "SRS 功控参数改述")
            return _res(content, in_tok=50, out_tok=10)
        with mock.patch.object(httpx.Client, "post", autospec=True,
                               side_effect=post):
            out = multiquery.generate_variants(
                q_neg, n_variants=2, timeout=1.0,
                endpoint=("http://x", "k"), log=lines.append)
        self.assertEqual(out, ref_out, "S2-不传")
        self.assertEqual(self._norm_dur(lines), ref_norm, "S2-不传")

    def test_off_states_on_triggered_fall_back(self):
        # S5/S6：开态入参但拆解失败（endpoint 缺席/HTTP 失败）→ 回退变体路径，
        # 输出与关态逐字节一致（零行为降级）
        q_trig = B16
        ref_out, ref_lines, _ = self._run(q_trig, None)

        def post_variants_and_fail(self, url, json=None, headers=None):
            if json and json["messages"][0]["role"] == "system" and \
                    "拆解器" in json["messages"][0]["content"]:
                raise RuntimeError("boom")
            sysc = json["messages"][0]["content"]
            content = ("SRS power control parameters"
                       if "英文" in sysc else "SRS 功控参数改述")
            return _res(content, in_tok=50, out_tok=10)
        lines = []
        with mock.patch.object(httpx.Client, "post", autospec=True,
                               side_effect=post_variants_and_fail):
            out = multiquery.generate_variants(
                q_trig, n_variants=2, timeout=1.0, endpoint=("http://x", "k"),
                log=lines.append, decompose={"enabled": True})
        self.assertEqual(out, ref_out)                  # 回退=输出一致
        self.assertIn(self._norm_dur([ref_lines[-1]])[0],
                      self._norm_dur(lines))            # variants 观测行同形
        # S5：endpoint=None → 拆解调用自弃（endpoint 未解析）→ 回退
        lines2 = []
        with mock.patch.object(httpx.Client, "post", autospec=True,
                               side_effect=post_variants_and_fail):
            out2 = multiquery.generate_variants(
                q_trig, n_variants=2, timeout=1.0, endpoint=None,
                log=lines2.append, decompose={"enabled": True})
        self.assertEqual(out2, [])

    def test_open_success_subs_replace_variants(self):
        subs_json = ('{"type":"对比","subs":['
                     '{"q":"LTE 的 t310 定时器取值？","entity":true,"role":"main"},'
                     '{"q":"NR 的 t310 定时器取值？","entity":true,"role":"main"},'
                     '{"q":"t311 的作用与 t310 区别？","entity":true,"role":"main"}]}')
        calls = []

        def post(self, url, json=None, headers=None):
            calls.append(json["messages"][0]["content"][:8])
            if "拆解器" in json["messages"][0]["content"]:
                return _res(subs_json, in_tok=400, out_tok=120)
            return _res("不该生成变体", in_tok=50, out_tok=10)
        lines = []
        with mock.patch.object(httpx.Client, "post", autospec=True,
                               side_effect=post):
            out = multiquery.generate_variants(
                B16, n_variants=2, timeout=1.0, endpoint=("http://x", "k"),
                log=lines.append, decompose={"enabled": True})
        self.assertEqual(out, ["LTE 的 t310 定时器取值？",
                               "NR 的 t310 定时器取值？",
                               "t311 的作用与 t310 区别？"])
        self.assertEqual(len(calls), 1)                 # 只 1 次拆解调用，零变体调用
        dec = [x for x in lines if x.startswith("[rag-mq-decompose]")]
        var = [x for x in lines if x.startswith("[rag-mq-variants]")]
        self.assertEqual(len(dec), 1)
        self.assertEqual(len(var), 1)                   # 子问即变体：双观测行
        parsed = multiquery.parse_decompose_obs_line(dec[0])
        self.assertTrue(parsed and parsed["trig"] == 1)
        self.assertEqual(parsed["type"], "对比")
        self.assertEqual(parsed["n"], 3)
        self.assertEqual(parsed["subs"], out)
        pv = multiquery.parse_variants_obs_line(var[0])
        self.assertEqual(pv["variants"], out)

    def test_open_single_intent_falls_back(self):
        # 触发但 flash 回"单意" → 回退变体路径（零行为降级）
        def post(self, url, json=None, headers=None):
            if "拆解器" in json["messages"][0]["content"]:
                return _res('{"type":"单意","subs":[]}')
            sysc = json["messages"][0]["content"]
            content = ("SRS power control parameters"
                       if "英文" in sysc else "SRS 功控参数改述")
            return _res(content, in_tok=50, out_tok=10)
        lines = []
        with mock.patch.object(httpx.Client, "post", autospec=True,
                               side_effect=post):
            out = multiquery.generate_variants(
                B16, n_variants=2, timeout=1.0, endpoint=("http://x", "k"),
                log=lines.append, decompose={"enabled": True})
        self.assertEqual(out, ["SRS power control parameters",
                               "SRS 功控参数改述"])

    def test_module_absent_off(self):
        # decompose 模块缺席（部分部署防御）→ 挂点静默退关（走变体路径）
        def post(self, url, json=None, headers=None):
            sysc = json["messages"][0]["content"]
            content = ("SRS power control parameters"
                       if "英文" in sysc else "SRS 功控参数改述")
            return _res(content, in_tok=50, out_tok=10)
        lines = []
        with mock.patch.object(multiquery, "_decompose", None), \
                mock.patch.object(httpx.Client, "post", autospec=True,
                                  side_effect=post):
            out = multiquery.generate_variants(
                B16, n_variants=2, timeout=1.0, endpoint=("http://x", "k"),
                log=lines.append, decompose={"enabled": True})
        self.assertEqual(out, ["SRS power control parameters",
                               "SRS 功控参数改述"])
        self.assertFalse([x for x in lines if "decompose" in x])


class TestObsLines(unittest.TestCase):
    """观测行格式与解析往返（恒不抛出）。"""

    def test_roundtrip(self):
        line = multiquery.fmt_decompose_obs_line(B16, True, "对比",
                                                 ["子问一", "子问二"])
        p = multiquery.parse_decompose_obs_line(line)
        self.assertEqual(p["n"], 2)
        self.assertEqual(p["subs"], ["子问一", "子问二"])
        self.assertEqual(p["type"], "对比")
        self.assertEqual(p["trig"], 1)
        qsha = multiquery.fmt_decompose_obs_line(B16, True, "对比", [])[:40]
        self.assertIn("qsha16=", qsha)

    def test_parse_bad(self):
        for bad in ("", None, "别的东西", "[rag-mq-decompose] 坏行",
                    "[rag-mq-decompose] qsha16=ab trig=1 type=x n=2 s=[\"a\"]"):
            self.assertIsNone(multiquery.parse_decompose_obs_line(bad))
        self.assertIsNone(multiquery.parse_variants_obs_line("x"))

    def test_fmt_never_raises(self):
        for bad in (None, 123, ["x"], {"a": 1}):
            s = multiquery.fmt_decompose_obs_line(bad, True, "并列", bad)
            self.assertIsInstance(s, str)


if __name__ == "__main__":
    unittest.main()
