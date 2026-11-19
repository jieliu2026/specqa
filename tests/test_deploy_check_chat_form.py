# -*- coding: utf-8 -*-
"""deploy_check.py 单测：④ [chat] 打点三规则五态 + S1/S2 期望锚合格集 + 锚集数据档。

零 API、零云端连接、零密值：只测纯函数（parse_chat_line/check_chat_form/
_s1_anchor_ok/_s2_anchor_ok/_load_anchor_spec）与既有 --dry-run 自测形态
（内置样例日志，报告落 /tmp 不入仓）。
覆盖：三规则五态（hit/low_score/coverage_miss 行带 q=+top1= / miss 行只带
q= / off 行两字段皆无，五态行一律入判不跳过）、批1/批2（auth=/ttfb=/
cancelled=/cc=/ab=/rt=/trace=）两种 [chat] 形态字段序无关、旧版判读与新
违例判读两分、dry-run 四场景退出码；S1/S2 首位锚合格集三测；锚集数据档
装载校验（缺失/坏档 loud 失败）；⑧ rerank 探针 armed / ⑨ SOURCE_TIER
数据件在位 / ⑩ rerank 行为键三新项与 dry-run 不误红断言。

公开仓改造（T2.2）：期望锚集数据档 期望锚集-条款级.json 系版权件不随公开仓
分发——本件 setUpModule 构造**测试内合成锚集档**（tmp 文件，结构对齐
_validate_anchor_spec 全字段）并 monkeypatch deploy_check.ANCHOR_SPEC_FILE
+清 _ANCHOR_SPEC_CACHE（teardown 复原原值再清缓存，零跨件泄漏）；
S1/S2/锚集档三类断言全部改合成档驱动（语义同构：锚间 OR、锚内 contains
AND + regex、子款串号边界 (?![.\\d]) 拒绝、双证单证不放行）。dry-run 场景
不触锚集档（check_smoke 仅 --smoke 触发），④/⑧⑨⑩/dry-run 类零改动直迁。

运行：/home/jieliu/qa-bot/venv/bin/python -m pytest tests/test_deploy_check_chat_form.py -q
"""
import contextlib
import copy
import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import deploy_check as dc  # noqa: E402

# 批2 现行形态五态混合（auth= 插在 ip= 与 in_chars= 之间；low_score/coverage_miss
# 行 top1=触发闸门的余弦原始分/闸前观测值）+ 末行批1 旧形态 hit（混合形态自测
# 字段序无关；coverage_miss 合规例=2026-10-01 五态同步新锚）
MIXED_OK_LINES = [
    '[chat] ip=1.2.3.4 auth=body in_chars=19 rag=hit ttfb=1.1s dur=4.8s '
    'usage={\'a\': 1} cancelled=0 q="掉话率红线是多少" top1=0.8494 cc=off ab=off',
    '[chat] ip=1.2.3.4 auth=cookie in_chars=18 rag=low_score ttfb=1.3s dur=3.9s '
    'usage={\'a\': 1} cancelled=0 q="附近有什么好吃的餐厅" top1=0.1912 cc=off ab=off',
    '[chat] ip=1.2.3.4 auth=cookie in_chars=31 rag=coverage_miss ttfb=1.5s dur=2.1s '
    'usage={\'a\': 1} cancelled=0 q="卫星 NTN 的馈电链路怎么走" top1=0.5123 cc=off ab=off',
    '[chat] ip=1.2.3.4 auth=body in_chars=99 rag=miss ttfb=na dur=3.1s '
    'usage=None cancelled=0 q="t310 怎么配置" cc=off ab=off',
    '[chat] ip=1.2.3.4 auth=none in_chars=10 rag=off ttfb=0.9s dur=1.0s '
    'usage={\'t\': 5} cancelled=0',
    '[chat] ip=1.2.3.4 in_chars=18 rag=hit dur=4.2s usage={\'a\': 1} '
    'q="a3-Offset 取值范围" top1=0.8123',
]


def run_form(lines):
    """check_chat_form → (Report, ④ 结果元组)；stdout 静音。"""
    rep = dc.Report()
    with contextlib.redirect_stdout(io.StringIO()):
        dc.check_chat_form(rep, lines, smoke_ran=False)
    result = next(r for r in rep.results if r[0] == "④")
    return rep, result


# ---------------------------------------------------------------------------
# 合成锚集数据档（T2.2 公开仓改造）：结构对齐 _validate_anchor_spec 全字段，
# 内容全合成（无版权引文）；S1=条款双锚（款号边界），S2=参数卡族双锚。
# ---------------------------------------------------------------------------
SPEC_TEMPLATE = {
    "schema_version": 1,
    "frozen_date": "2026-11-18",
    "refresh_procedure": "测试内合成档（公开仓无版权锚集档；结构校验与判定语义自证）",
    "smokes": {
        "S1": {
            "question": "合成题一：条款X 1.1 的监管阈值是多少",
            "doc_id_any": ["合成文档A", "合成文档B"],
            "answer_pattern": "≤\\s*5\\s*%",
            "answer_note": "合成判据（阈值 5%）",
            "anchors": [
                {"anchor_id": "S1-锚1（条款X 1.1）",
                 "locator_contains": ["条款X", "1.1"],
                 "locator_regex": "1\\.1(?![.\\d])",
                 "evidence_blocks": [{"chunk_id": "synthetic-s1-a1"}],
                 "requirements": {"数值": "合成引文：阈值不超过 5%",
                                  "主体": "合成引文：主体业务词",
                                  "款义": "合成引文：款义限定词"}},
                {"anchor_id": "S1-锚2（条款Y 2.2）",
                 "locator_contains": ["条款Y", "2.2"],
                 "locator_regex": "2\\.2(?![.\\d])",
                 "evidence_blocks": [{"chunk_id": "synthetic-s1-a2"}],
                 "requirements": {"数值": "合成引文：阈值不超过 5%",
                                  "主体": "合成引文：主体业务词",
                                  "款义": "合成引文：款义限定词"}},
            ],
        },
        "S2": {
            "question": "合成题二：参数卡 alpha 的取值范围和步进是多少",
            "doc_id_any": ["合成规范TS"],
            "answer_pattern": "-30\\.\\.30",
            "answer_note": "合成判据（-30..30，步进 0.5）",
            "anchors": [
                {"anchor_id": "S2-锚1（alpha 参数卡）",
                 "locator_contains": ["alpha"],
                 "locator_regex": "alpha(?![A-Za-z0-9-])",
                 "evidence_blocks": [{"chunk_id": "synthetic-s2-a1"}],
                 "requirements": {"数值": "合成引文：-30..30",
                                  "主体": "合成引文：主体参数词",
                                  "款义": "合成引文：款义限定词"}},
                {"anchor_id": "S2-锚2（beta 参数卡）",
                 "locator_contains": ["beta"],
                 "locator_regex": "beta(?![A-Za-z0-9-])",
                 "evidence_blocks": [{"chunk_id": "synthetic-s2-a2"}],
                 "requirements": {"数值": "合成引文：-30..30",
                                  "主体": "合成引文：主体参数词",
                                  "款义": "合成引文：款义限定词"}},
            ],
        },
    },
}

_SPEC_ORIG = None       # 原锚集档路径（teardown 复原）
_SPEC_TMP = None        # 合成档 tmp 路径


def setUpModule():
    """合成锚集档落 tmp → monkeypatch 默认装载路径 + 清装载缓存。

    _load_anchor_spec 的注入面=path 参数（path 注入不进缓存）+ 模块级
    ANCHOR_SPEC_FILE 常量（默认路径调用点实时读模块全局）——本模块整体
    换默认路径，S1/S2/_s1_anchor_ok/_s2_anchor_ok 的无参调用面全走合成档。"""
    global _SPEC_ORIG, _SPEC_TMP
    fd, _SPEC_TMP = tempfile.mkstemp(suffix=".json", prefix="anchor-spec-synthetic-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(SPEC_TEMPLATE, f, ensure_ascii=False)
    _SPEC_ORIG = dc.ANCHOR_SPEC_FILE
    dc.ANCHOR_SPEC_FILE = _SPEC_TMP
    dc._ANCHOR_SPEC_CACHE.clear()


def tearDownModule():
    """复原默认路径原值 + 再清缓存（合成档不进其他测试件的进程内缓存）。"""
    global _SPEC_ORIG, _SPEC_TMP
    dc.ANCHOR_SPEC_FILE = _SPEC_ORIG
    dc._ANCHOR_SPEC_CACHE.clear()
    if _SPEC_TMP and os.path.exists(_SPEC_TMP):
        os.unlink(_SPEC_TMP)


class TestParseChatLine(unittest.TestCase):
    def test_five_states_both_formats(self):
        """五态 × 批1/批2 两种形态全部解析（low_score/coverage_miss 行不再被
        跳过/消失——两轮销账锚）。"""
        for line in MIXED_OK_LINES:
            p = dc.parse_chat_line(line)
            self.assertIsNotNone(p, line)
        self.assertEqual([dc.parse_chat_line(line)["rag"] for line in MIXED_OK_LINES],
                         ["hit", "low_score", "coverage_miss", "miss", "off", "hit"])

    def test_field_presence_flags(self):
        p = dc.parse_chat_line(MIXED_OK_LINES[1])   # low_score 批2 形态
        self.assertEqual(p["rag"], "low_score")
        self.assertTrue(p["q"])
        self.assertTrue(p["top1"])
        p = dc.parse_chat_line(MIXED_OK_LINES[2])   # coverage_miss：q= 与 top1= 同 low_score 规则
        self.assertEqual(p["rag"], "coverage_miss")
        self.assertTrue(p["q"])
        self.assertTrue(p["top1"])
        p = dc.parse_chat_line(MIXED_OK_LINES[3])   # miss：q= 有、top1= 无
        self.assertTrue(p["q"])
        self.assertFalse(p["top1"])
        p = dc.parse_chat_line(MIXED_OK_LINES[4])   # off：两字段皆无
        self.assertFalse(p["q"])
        self.assertFalse(p["top1"])

    def test_rt_field_parsed_and_optional(self):
        """期1 路由 rt= 键（2026-10-01 教识）：在场解析、缺省 None——容忍不误报。"""
        p = dc.parse_chat_line(MIXED_OK_LINES[2] + " rt=concept:f trace=a1b2c3d4")
        self.assertEqual(p["rt"], "concept:f")
        self.assertIsNone(dc.parse_chat_line(MIXED_OK_LINES[0])["rt"])

    def test_top1_na_counts_as_scored(self):
        """top1=na 属打点在场（缺分形态），规则判 PASS 不判违例。"""
        p = dc.parse_chat_line('[chat] ip=1.1.1.1 auth=body in_chars=5 rag=hit '
                               'ttfb=1s dur=1s cancelled=0 q="x" top1=na cc=off ab=off')
        self.assertTrue(p["top1"])

    def test_non_chat_line_ignored(self):
        self.assertIsNone(dc.parse_chat_line("[rag-embed] chars=19 ok=1"))


class TestCheckChatForm(unittest.TestCase):
    def test_five_state_mixed_compliant_pass(self):
        """五态混合全合规 → PASS，规则注记按五态分列计数（含 cov_miss=1）。"""
        _, r = run_form(MIXED_OK_LINES)
        self.assertEqual(r[2], "PASS")
        title = r[1]
        self.assertIn("hit=2 miss=1 low_score=1 cov_miss=1 off=1", title)
        self.assertIn("coverage_miss 行带 q=+top1=", title)
        self.assertIn("三规则", dc.check_chat_form.__doc__)

    def test_low_score_violation_detected(self):
        """low_score 行缺 top1= → 三规则违例 FAIL（四态入判不跳过的直接证明）。"""
        lines = MIXED_OK_LINES[:1] + [
            '[chat] ip=1.2.3.4 auth=cookie in_chars=18 rag=low_score ttfb=1.3s '
            'dur=3.9s cancelled=0 q="家常菜推荐" cc=off ab=off']
        _, r = run_form(lines)
        self.assertEqual(r[2], "FAIL")
        self.assertTrue(any("新版已部署但打点形态异常" in h for h in r[4]))

    def test_coverage_miss_violation_detected(self):
        """coverage_miss 缺字段（缺 top1= / 缺 q=）→ 三规则违例 FAIL
        （2026-10-01 五态同步：与 low_score 同规则分支的负例证明——
        教识前该态整行从抽验消失，缺字段不可见）。"""
        lines = MIXED_OK_LINES[:1] + [
            '[chat] ip=1.2.3.4 auth=cookie in_chars=31 rag=coverage_miss ttfb=1.5s '
            'dur=2.1s cancelled=0 q="卫星 NTN 的馈电链路怎么走" cc=off ab=off']
        _, r = run_form(lines)
        self.assertEqual(r[2], "FAIL")
        self.assertTrue(any("新版已部署但打点形态异常" in h for h in r[4]))
        lines2 = MIXED_OK_LINES[:1] + [
            '[chat] ip=1.2.3.4 auth=cookie in_chars=31 rag=coverage_miss ttfb=1.5s '
            'dur=2.1s cancelled=0 top1=0.5123 cc=off ab=off']
        _, r2 = run_form(lines2)
        self.assertEqual(r2[2], "FAIL")

    def test_rt_hint_reported_when_present(self):
        """期1 路由开态核读：[chat] 行带 rt= → 计数提示行在场、不判 FAIL。"""
        lines = [MIXED_OK_LINES[0] + " rt=concept:d trace=84bc4e58",
                 MIXED_OK_LINES[2] + " rt=concept:f trace=a1b2c3d4"]
        _, r = run_form(lines)
        self.assertEqual(r[2], "PASS")
        self.assertTrue(any("route 开态" in h and "共 2 轮" in h for h in r[4]))

    def test_miss_with_top1_violation(self):
        _, r = run_form(MIXED_OK_LINES[:1] + [
            '[chat] ip=1.2.3.4 auth=body in_chars=9 rag=miss dur=1s '
            'cancelled=0 q="x" top1=0.5'])
        self.assertEqual(r[2], "FAIL")

    def test_off_with_fields_violation(self):
        _, r = run_form(MIXED_OK_LINES[:1] + [
            '[chat] ip=1.2.3.4 auth=none in_chars=9 rag=off dur=1s '
            'cancelled=0 q="x"'])
        self.assertEqual(r[2], "FAIL")

    def test_oldver_reading(self):
        """hit 行全无 q=/top1= → 判读'云端仍是旧版 server.py'（两种 FAIL 判读之分）。"""
        _, r = run_form(['[chat] ip=1.2.3.4 in_chars=19 rag=hit dur=7.1s usage={\'a\': 1}'])
        self.assertEqual(r[2], "FAIL")
        self.assertTrue(any("旧版" in h for h in r[4]))

    def test_no_chat_lines_fail(self):
        _, r = run_form(["[rag-embed] chars=19 ok=1"])
        self.assertEqual(r[2], "FAIL")
        self.assertTrue(any("无 [chat] 行" in e for e in r[3]))


class TestDryRunScenarios(unittest.TestCase):
    """既有 --dry-run 自测形态：内置样例走同一套判定逻辑，不连云端、报告落 /tmp。"""

    def dry(self, *extra):
        argv_old = sys.argv
        sys.argv = ["deploy_check.py", *extra]
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = dc.main()
        finally:
            sys.argv = argv_old
        return rc, buf.getvalue()

    def test_ok_scenario_five_states_pass(self):
        """ok 场景（fixture 已刷新为批2 形态+批1 混合+五态/rt=）：全 PASS 退出码 0，
        ④ 计数含 low_score=1 与 cov_miss=1（样例低分拦截/负控覆盖闸行入判）、
        rt 核读提示在场。--expect-loaded=0：登底默认已动态取本机库行数（缺口修 A），
        夹具冻结值与之天然分叉——登底对照非本测靶面，0=只打印不强校验。"""
        rc, out = self.dry("--dry-run=ok", "--expect-loaded=0")
        self.assertEqual(rc, 0, out[-800:])
        self.assertIn("low_score=1", out)
        self.assertIn("cov_miss=1", out)
        self.assertIn("route 开态", out)
        self.assertIn("FAIL=0", out)

    def test_ok_off_scenario(self):
        rc, out = self.dry("--dry-run=ok-off", "--hybrid-off", "--expect-loaded=0")
        self.assertEqual(rc, 0, out[-800:])
        self.assertIn("low_score=1", out)
        self.assertIn("cov_miss=1", out)

    def test_oldver_scenario_fail(self):
        rc, out = self.dry("--dry-run=oldver")
        self.assertEqual(rc, 1)
        self.assertIn("旧版", out)

    def test_offline_scenario_fail_no_crash(self):
        rc, out = self.dry("--dry-run=offline")
        self.assertEqual(rc, 1)
        self.assertIn("FAIL", out)


class TestS1AnchorQualifiedSet(unittest.TestCase):
    """S1 首位锚合格集（公开仓=合成锚集档驱动；语义与真实档同构：锚间 OR、
    锚内 contains AND + regex、子款串号边界拒绝、双证单证不放行）。"""

    def test_qualified_anchors_pass(self):
        for loc in ("条款X 1.1 通话中断率 款1",
                    "条款X 1.1",
                    "条款Y 2.2 通话中断率",
                    "条款Y 2.2"):
            self.assertTrue(dc._s1_anchor_ok(loc), msg=loc)

    def test_unqualified_locators_rejected(self):
        # 同文件他条款/他锚面/子款串号/单证形态/空值一律不认
        for loc in ("条款X 1.2 指标定义",          # 同文件他条款
                    "条款Z 3.3",                  # 他锚面
                    "条款X 1.11",                 # 子款串号（边界拒绝）
                    "条款X 1.1.9",                # 子款深号
                    "附录Q 1.1 其他主体",          # 仅款号单证（缺文件双证）
                    "条款X 总则",                 # 仅文件单证（缺款号）
                    "", None,
                    "alpha 参数卡"):               # 他题锚（S2 面）
            self.assertFalse(dc._s1_anchor_ok(loc), msg=repr(loc))

    def test_false_positive_guard(self):
        # 款号子串不得误放大：条款Y 2.2 不含 条款X 双证形态
        self.assertNotIn("条款X", "条款Y 2.2 通话中断率 款1")
        self.assertTrue(dc._s1_anchor_ok("条款Y 2.2 通话中断率 款1"))
        # contains 单证不放行：命中 contains 而不命中 regex（子款串号）拒收
        self.assertFalse(dc._s1_anchor_ok("条款X 1.11"))
        # regex 单证不放行：命中 regex 而不命中 contains 拒收
        self.assertFalse(dc._s1_anchor_ok("附录Q 1.1 其他主体"))


class TestS2AnchorQualifiedSet(unittest.TestCase):
    """S2 首位锚合格集（公开仓=合成参数卡族双锚：alpha｜beta；集合吸收同族
    翻转，语义与真实档同构）。"""

    def test_qualified_card_locators_pass(self):
        for loc in ("alpha 参数卡", "beta 参数卡", "合成规范TS alpha 参数卡 款1"):
            self.assertTrue(dc._s2_anchor_ok(loc), msg=loc)

    def test_unqualified_locators_rejected(self):
        # 扩展卡形态（alpha-ext）/散文块/他参数/大小写形/空值不认
        for loc in ("alpha-ext 参数卡",       # contains 命中但 regex 边界拒收
                    "alphab 参数卡",          # 词尾粘连形态
                    "gamma 参数卡",           # 他参数卡
                    "5.5.4.4", "q-alphaCell", # 散文块/撞名词
                    "ALPHA 参数卡",           # 大小写不互认
                    "", None,
                    "条款X 1.1"):             # 他题锚（S1 面）
            self.assertFalse(dc._s2_anchor_ok(loc), msg=repr(loc))


class TestSmokeAnchorDataFile(unittest.TestCase):
    """锚集数据档装载校验（公开仓=合成档默认路径 + path 注入两面；禁静默回退）。

    覆盖：合成档经 monkeypatch 后的默认路径装载+结构校验过+缓存命中；
    缺失/JSON 坏/正则坏/三要件缺 → AnchorSpecError（loud）；path 注入不进缓存
    （测试隔离）；_smoke_anchor_ok 集合判定语义自证。"""

    def test_default_spec_loads_and_validates(self):
        spec = dc._load_anchor_spec()
        self.assertEqual(spec["schema_version"], 1)
        self.assertEqual(spec["frozen_date"], SPEC_TEMPLATE["frozen_date"])
        for sid in ("S1", "S2"):
            s = spec["smokes"][sid]
            self.assertTrue(s["doc_id_any"] and s["anchors"])
            for a in s["anchors"]:
                self.assertTrue(a["anchor_id"].strip())
                self.assertTrue(a["evidence_blocks"])
                for k in ("数值", "主体", "款义"):
                    self.assertTrue(a["requirements"][k].strip(),
                                "%s %s %s 三要件引文空" % (sid, a["anchor_id"], k))
        # 合格集=合成档两题各两锚（锚间 OR 吸收同族首位互换）
        self.assertEqual(len(spec["smokes"]["S1"]["anchors"]), 2)
        self.assertEqual(len(spec["smokes"]["S2"]["anchors"]), 2)
        # 默认路径装载已入缓存：二次调用返回同对象（单次进程一次读盘）
        self.assertIs(dc._load_anchor_spec(), spec)

    def test_missing_file_raises(self):
        with self.assertRaises(dc.AnchorSpecError):
            dc._load_anchor_spec(path="/nonexistent-锚集档.json")

    def _write_tmp_spec(self, mutate):
        """深拷贝合成模板后突变落 tmp（不污染模块缓存与模板）。"""
        spec = copy.deepcopy(SPEC_TEMPLATE)
        mutate(spec)
        fd, path = tempfile.mkstemp(suffix=".json", prefix="anchor-spec-mut-")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(spec, f, ensure_ascii=False)
        self.addCleanup(os.unlink, path)
        return path

    def test_bad_json_raises(self):
        fd, path = tempfile.mkstemp(suffix=".json", prefix="anchor-spec-bad-")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("{broken json")
        self.addCleanup(os.unlink, path)
        with self.assertRaises(dc.AnchorSpecError):
            dc._load_anchor_spec(path=path)

    def test_bad_locator_regex_raises(self):
        path = self._write_tmp_spec(
            lambda s: s["smokes"]["S1"]["anchors"][0].update(locator_regex="1\\.1(?![.\\d"))
        with self.assertRaises(dc.AnchorSpecError):
            dc._load_anchor_spec(path=path)

    def test_missing_requirements_raises(self):
        path = self._write_tmp_spec(
            lambda s: s["smokes"]["S1"]["anchors"][0]["requirements"].pop("数值"))
        with self.assertRaises(dc.AnchorSpecError):
            dc._load_anchor_spec(path=path)

    def test_missing_evidence_raises(self):
        path = self._write_tmp_spec(
            lambda s: s["smokes"]["S2"]["anchors"][0].update(evidence_blocks=[]))
        with self.assertRaises(dc.AnchorSpecError):
            dc._load_anchor_spec(path=path)

    def test_injected_path_bypasses_cache(self):
        # 显式 path 不进缓存：同一非法注入档连跑两次都抛（无缓存遮蔽）
        path = self._write_tmp_spec(
            lambda s: s["smokes"]["S1"].update(doc_id_any=[]))
        for _ in range(2):
            with self.assertRaises(dc.AnchorSpecError):
                dc._load_anchor_spec(path=path)

    def test_anchor_ok_matches_spec_semantics(self):
        # 集合判定语义：锚间 OR、锚内 contains AND + regex
        spec = dc._load_anchor_spec()
        self.assertTrue(dc._smoke_anchor_ok("S1", "条款Y 2.2 通话中断率", spec))
        self.assertFalse(dc._smoke_anchor_ok("S1", "1.1 单款号形态", spec))
        self.assertTrue(dc._smoke_anchor_ok("S2", "beta 参数卡", spec))


# ----------------------------- 2026-10-12 合围工程基建一期 2-C 三新项 -----------------------------
# ⑧ rerank 探针 armed（[startup] rerank_log 行）/⑨ SOURCE_TIER 数据件在位
# （data/source-tier.json，分级=INFO 缺件不红/WARN 件坏/FAIL 通道）/⑩ rerank
# 行为键状态呈现（config rerank_refusal_enabled 现值，不判红）。
class _StubCloud:
    """按命令特征串返回预置响应（与 Cloud.run 同签名，零云端连接）。"""

    def __init__(self, mapping):
        self.mapping = mapping

    def run(self, cmd, timeout=60, stdin_data=None):
        for key, resp in self.mapping.items():
            if key in cmd:
                return resp
        return 0, "", ""


def run_check(fn, *args):
    """单 check 函数 → (Report, 该编号结果)；stdout 静音。"""
    rep = dc.Report()
    with contextlib.redirect_stdout(io.StringIO()):
        fn(rep, *args)
    return rep, rep.results[-1]


def _jd(boot_lines, chat_lines=()):
    """构造 ⑧/⑩ 所需 jdata（对齐 check_loaded 返回键）。"""
    return {"boot_seg": list(boot_lines), "chat_lines": list(chat_lines)}


class TestCheckRerankArmed(unittest.TestCase):
    """⑧ 探针 armed：on=PASS / off=FAIL（有意关闭语义）/ 行缺=FAIL（未部署新版
    语义）——两种 FAIL 判读分开（沿 ④ 新旧版哲学）。"""

    def test_armed_on_pass(self):
        _, r = run_check(dc.check_rerank_armed, _jd([
            "[startup] rag=on loaded=66357 bad_lines=0 dim=1024",
            "[startup] rerank_log=on cap=5cny"]))
        self.assertEqual(r[2], "PASS")
        self.assertIn("cap=5cny", r[3][0])

    def test_armed_off_fail_intentional_reading(self):
        _, r = run_check(dc.check_rerank_armed, _jd([
            "[startup] rag=on loaded=66357 bad_lines=0 dim=1024",
            "[startup] rerank_log=off cap=5cny"]))
        self.assertEqual(r[2], "FAIL")
        self.assertTrue(any("有意关闭" in h for h in r[4]))
        self.assertTrue(any("部署动作" in h for h in r[4]))

    def test_line_missing_fail_oldver_reading(self):
        _, r = run_check(dc.check_rerank_armed, _jd([
            "[startup] rag=on loaded=14055 bad_lines=0 dim=1024"]))
        self.assertEqual(r[2], "FAIL")
        self.assertTrue(any("未部署新版" in h for h in r[4]))

    def test_malformed_line_fail(self):
        _, r = run_check(dc.check_rerank_armed, _jd([
            "[startup] rerank_log=broken"]))
        self.assertEqual(r[2], "FAIL")
        self.assertTrue(any("形态异常" in h for h in r[4]))


class TestCheckSourceTierFile(unittest.TestCase):
    """⑨ SOURCE_TIER 数据件在位：在位可解析=PASS / 件缺=INFO 不红（并行泳道
    施工期容忍，合入后自然转绿）/ 件在解析失败=WARN 不红 / 通道失败=FAIL。"""

    def test_present_and_parsable_pass(self):
        _, r = run_check(dc.check_source_tier_file, _StubCloud(
            {"ST_EXISTS": (0, "ST_EXISTS=1\nST_RULES=4\n", "")}))
        self.assertEqual(r[2], "PASS")
        self.assertIn("ST_RULES=4", r[3][0])

    def test_missing_file_info_not_red(self):
        rep, r = run_check(dc.check_source_tier_file, _StubCloud(
            {"ST_EXISTS": (0, "ST_EXISTS=0\n", "")}))
        self.assertEqual(r[2], "INFO")
        self.assertFalse(rep.has_fail())            # INFO 不计红
        self.assertTrue(any("部署不完整" in h and "而非" in h for h in r[4]))

    def test_present_but_unparsable_warn_not_red(self):
        rep, r = run_check(dc.check_source_tier_file, _StubCloud(
            {"ST_EXISTS": (1, "ST_EXISTS=1\n", "Traceback (most recent call last):\n"
                            "  json.decoder.JSONDecodeError: ...")}))
        self.assertEqual(r[2], "WARN")
        self.assertFalse(rep.has_fail())            # WARN 不计红（服务走回退快照）
        self.assertTrue(any("重传" in h for h in r[4]))

    def test_channel_fail_fail(self):
        _, r = run_check(dc.check_source_tier_file, _StubCloud(
            {"ST_EXISTS": (255, "", "ssh: connect to host ... timed out")}))
        self.assertEqual(r[2], "FAIL")
        self.assertTrue(any("取数通道" in h for h in r[4]))


class TestCheckRerankRefusalKey(unittest.TestCase):
    """⑩ 行为键状态呈现：关态=INFO（默认形态）/ 开态+gate 行=INFO 判读提示 /
    开态无行=INFO（未 restart 提示）/ 取数失败=INFO——一律不判红。"""

    def test_key_off_default_info(self):
        _, r = run_check(dc.check_rerank_refusal_key, _StubCloud(
            {"rerank_refusal_enabled":
             (0, "rerank_log_enabled=<absent=true>\n"
                 "rerank_refusal_enabled=<absent=false>\n", "")}),
            _jd(["[startup] rerank_log=on cap=5cny"]))
        self.assertEqual(r[2], "INFO")
        self.assertTrue(any("键关态" in h for h in r[4]))

    def test_key_on_with_gate_lines_info(self):
        _, r = run_check(dc.check_rerank_refusal_key, _StubCloud(
            {"rerank_refusal_enabled":
             (0, "rerank_log_enabled=True\nrerank_refusal_enabled=True\n", "")}),
            _jd(["[startup] rerank_log=on cap=5cny"],
                ["[rerank_probe] ts=2026-10-12 09:00:00 q=ab12cd34ef56 st=hit trace=t "
                 "n=50 max=0.8494 c075=2 c085=1 c095=0 tok=1 cny=0.001 gold=na",
                 "[rerank_gate] ts=2026-10-12 09:00:01 q=ab12cd34ef56 trace=t "
                 "decision=pass max=0.8494 thr=0.75"]))
        self.assertEqual(r[2], "INFO")
        self.assertTrue(any("键开态" in h and "1 条" in h for h in r[4]))
        self.assertTrue(any(line.startswith("[rerank_gate]") for line in r[3]))  # 证据含 gate 行

    def test_key_on_without_gate_lines_hint_restart(self):
        _, r = run_check(dc.check_rerank_refusal_key, _StubCloud(
            {"rerank_refusal_enabled":
             (0, "rerank_refusal_enabled=True\n", "")}),
            _jd(["[startup] rerank_log=on cap=5cny"]))
        self.assertEqual(r[2], "INFO")
        self.assertTrue(any("未 restart" in h or "无 hit 流量" in h for h in r[4]))

    def test_channel_fail_info_not_red(self):
        rep, r = run_check(dc.check_rerank_refusal_key, _StubCloud(
            {"rerank_refusal_enabled": (255, "", "ssh timed out")}), None)
        self.assertEqual(r[2], "INFO")
        self.assertFalse(rep.has_fail())


class TestDryRunNewItemsAndNoFalseRed(unittest.TestCase):
    """dry-run 三新项形态 + E8 不误红：ok/ok-off 场景既有 PASS 项（①②③⑤⑦④）
    全部不翻红、新项不引入 FAIL（⑧PASS/⑨PASS/⑩INFO）；oldver 场景 ⑧ 按
    '未部署新版'判读 FAIL（语义红，fixture 有意不补行）；offline 场景不崩。"""

    def dry(self, *extra):
        argv_old = sys.argv
        sys.argv = ["deploy_check.py", *extra]
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = dc.main()
        finally:
            sys.argv = argv_old
        return rc, buf.getvalue()

    def test_ok_scenario_new_items_green_and_no_false_red(self):
        rc, out = self.dry("--dry-run=ok", "--expect-loaded=0")
        self.assertEqual(rc, 0, out[-800:])
        # E8 不误红：既有五必跑项+④ 全 PASS
        for num, title in (("①", "服务活"), ("②", "startup 装载行"),
                           ("③", "[rag-bm25]"), ("⑤", "/health"),
                           ("⑦", "装载内存预估闸"), ("④", "[chat] 打点形态")):
            line = next(ln for ln in out.splitlines()
                        if ln.startswith("## %s" % num) and title in ln)
            self.assertTrue(line.endswith("PASS"), line)
        # 三新项：⑧PASS / ⑨PASS / ⑩INFO，零新增红
        self.assertIn("## ⑧ rerank 探针 armed（[startup] rerank_log 行） — PASS", out)
        self.assertIn("## ⑨ SOURCE_TIER 数据件在位（data/source-tier.json） — PASS", out)
        self.assertIn("## ⑩ rerank 行为键状态（config rerank_refusal_enabled 现值） — INFO", out)
        self.assertIn("FAIL=0", out)

    def test_ok_off_scenario_new_items_green(self):
        rc, out = self.dry("--dry-run=ok-off", "--hybrid-off", "--expect-loaded=0")
        self.assertEqual(rc, 0, out[-800:])
        self.assertIn("⑧", out)
        self.assertIn("## ⑨ SOURCE_TIER 数据件在位（data/source-tier.json） — PASS", out)
        self.assertIn("FAIL=0", out)

    def test_oldver_scenario_new_item_readings(self):
        rc, out = self.dry("--dry-run=oldver")
        self.assertEqual(rc, 1)
        # ⑧ 行缺=云端仍旧版判读（语义红，与"有意关闭"分开）
        self.assertIn("## ⑧ rerank 探针 armed（[startup] rerank_log 行） — FAIL", out)
        self.assertTrue(any("未部署新版" in line for line in out.splitlines()))
        # ⑨ 件缺=INFO 不红（泳道施工期容忍）；⑩ 键缺省关态 INFO
        self.assertIn("## ⑨ SOURCE_TIER 数据件在位（data/source-tier.json） — INFO", out)
        self.assertIn("## ⑩ rerank 行为键状态（config rerank_refusal_enabled 现值） — INFO", out)
        # 既有 oldver 语义红原样（②登底/④打点/③bm25），不受新项影响
        self.assertIn("旧版", out)

    def test_offline_scenario_no_crash_with_new_items(self):
        rc, out = self.dry("--dry-run=offline")
        self.assertEqual(rc, 1)
        self.assertIn("⑨", out)                     # 通道失败 FAIL（同①⑦哲学）
        self.assertIn("⑩", out)                     # 取数失败 INFO 不判红

    def test_summary_warn_suffix_only_when_warn(self):
        """汇总行 WARN 段仅 WARN>0 时呈现（无 WARN 场景与既往逐字节一致）。"""
        _rc, out = self.dry("--dry-run=ok", "--expect-loaded=0")
        summary = next(line for line in out.splitlines() if line.startswith("## 汇总："))
        self.assertNotIn("WARN=", summary)          # ok 场景无 WARN → 汇总行不变


if __name__ == "__main__":
    unittest.main()
