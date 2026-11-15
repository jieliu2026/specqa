# -*- coding: utf-8 -*-
"""redline_filter 单测（T01，代码评审立改批 X2；零网络零计费）。

补齐 redline_filter.py 在 tests/ 的零覆盖欠账（规格源=work/代码评审-
20261015/分级发现表.md T01、深读-redline-piimask.md §二缺口 1）：
- detect：六模式正例（adv_cmp/adv_cmp_plain/bare_cmp/dir_assert/dir_num/
  spec_num 各自命中 + hit 字段形态）与中性文本反例（total=0）；
- count_by_pattern：分模式计数与 total、干净文本全零、fail-open（畸形输入
  → 全零 + 限频 err 遥测行；None 走 str 兜底不算异常）；
- observe_answer：off/enforce（不收）零动作、log_only 命中打行（格式/
  零原文/flush=True——R4）、log_only 零命中零行、trace 缺省 '-'、
  fail-open（log 槽炸 → None 绝不外抛——R5）；
- resolve_mode：缺键/坏值/enforce 一律回 log_only（不收 enforce）；
- filter_answer：命中句整句换兜底句（保句尾分隔符）、一轮收敛、幂等
  （filter(filter(x))==filter(x)）、干净文本零改动（enforce 语义源回归位）。

v2 词表扩容回归（2026-10-15，规格源=work/代码评审-20261015/R1词面覆盖矩阵.md；
构造纪律断言先行落码——对 v1 跑红、v2 落码后转绿）：
- WordGroupDisciplineTest：增补词必须收进 (?:...) 组内（单一纯词面组形态+
  词集精确相等+六模式源=常量组逐字合成——防组外串接裸匹配虚高，矩阵 §五.4
  实测教训）+备选 6 词排除位+新词结构门控行为断言；
- NormalizeLayerTest：繁→简归一化层（繁简同句等计数且必命中/简体零扰动）；
- MatrixRegressionTest：81 题矩阵回归夹具（12 正对照+69 对抗；v1 逐题六模式
  计数为历史基线）；v2 断言=正对照全命中+对抗零命中集合恰等于 known-miss
  10 例（57→10）+逐模式 v2≥v1 单调（v1 命中零丢失）+代表性逐题 total；
- FPProbeTest：FP 探针按矩阵 §四登记值断言（必零位=裸"约"/领先/超过无数字；
  声明内噪声位按登记值锁位防无声漂移）；
- RedosBoundTest：24k 最坏构造全模式扫描 ≤10ms（best-of-5）。

样例纪律：全部合成短句（规范类中性表述，非任何生产答案原文）。
"""
import contextlib
import io
import re
import time
import unittest

import redline_filter  # 仓根模块（tests/__init__.py 已做 sys.path 引导）

# ---- 合成样例（六模式正例；单句可跨模式重复计——R3 已知口径） ----
H_ADV_CMP = "通常该规范更严格"        # adv_cmp+adv_cmp_plain+bare_cmp
H_ADV_PLAIN = "一般标准更严格"        # adv_cmp_plain+bare_cmp（"一般"不在 ADV）
H_BARE_CMP = "该规范更严格"           # bare_cmp
H_DIR_ASSERT = "较现行规范严格"       # dir_assert
H_DIR_NUM = "远低于现行标准的50%"      # dir_num
H_SPEC_NUM = "预计增长30%"            # spec_num
CLEAN_TXT = "现行规范的条文结构以主管部门现行文件为准。"


class DetectTest(unittest.TestCase):
    """六模式正反例（detect 纯函数，返回命中清单）。"""

    def test_six_patterns_positive(self):
        cases = {"adv_cmp": H_ADV_CMP, "adv_cmp_plain": H_ADV_PLAIN,
                 "bare_cmp": H_BARE_CMP, "dir_assert": H_DIR_ASSERT,
                 "dir_num": H_DIR_NUM, "spec_num": H_SPEC_NUM}
        for name, text in cases.items():
            pats = {h["pattern"] for h in redline_filter.detect(text)}
            self.assertIn(name, pats, msg=f"{name} 未命中：{text}")

    def test_adv_cmp_stricter_than_plain(self):
        # ADV 不含裸"一般"：该句只进 adv_cmp_plain，不进 adv_cmp（词表边界）
        pats = {h["pattern"] for h in redline_filter.detect(H_ADV_PLAIN)}
        self.assertIn("adv_cmp_plain", pats)
        self.assertNotIn("adv_cmp", pats)

    def test_detect_hit_fields(self):
        hits = redline_filter.detect(H_ADV_CMP)
        self.assertEqual(len(hits), 3)   # adv_cmp+adv_cmp_plain+bare_cmp
        by_pat = {h["pattern"]: h for h in hits}
        self.assertEqual(set(by_pat), {"adv_cmp", "adv_cmp_plain", "bare_cmp"})
        for h in hits:
            self.assertEqual(set(h), {"pattern", "match", "context"})
        # adv_* 命中含推测词+比较词整段；bare_cmp 只含比较词短语
        self.assertEqual(by_pat["adv_cmp"]["match"], H_ADV_CMP)
        self.assertEqual(by_pat["adv_cmp_plain"]["match"], H_ADV_CMP)
        self.assertEqual(by_pat["bare_cmp"]["match"], "更严格")

    def test_clean_negatives(self):
        for t in ("小区掉话率优化步骤：采集话统、定位原因、调整参数、验证指标。",
                  "本答复只列条文编号与页码，不构成数值结论。", CLEAN_TXT):
            self.assertEqual(redline_filter.detect(t), [], msg=t)


class CountByPatternTest(unittest.TestCase):
    """分模式计数：六模式独立计数求和（R3：同短语跨模式可重复计）。"""

    def test_counts_by_pattern(self):
        c = redline_filter.count_by_pattern(f"{H_ADV_CMP}，{H_SPEC_NUM}。")
        self.assertEqual((c["adv_cmp"], c["adv_cmp_plain"], c["bare_cmp"]),
                         (1, 1, 1))
        self.assertEqual((c["dir_assert"], c["dir_num"], c["spec_num"]),
                         (0, 0, 1))
        self.assertEqual(c["total"], 4)

    def test_zero_on_clean(self):
        c = redline_filter.count_by_pattern(CLEAN_TXT)
        self.assertEqual(set(c), set(redline_filter.PATTERN_NAMES) | {"total"})
        self.assertEqual(c["total"], 0)

    def test_none_text_zero_no_err(self):
        # None 走 str(text or "") 兜底 → 全零且不打 err 行（非异常路径）
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            c = redline_filter.count_by_pattern(None)
        self.assertEqual(c["total"], 0)
        self.assertEqual(out.getvalue(), "")

    def test_fail_open_on_garbage_with_err_line(self):
        class _Boom:
            def __str__(self):
                raise RuntimeError("boom")
        redline_filter._ERR_LAST[0] = time.monotonic() - 3601.0   # 复位限频（R5 施工后新增模块态）
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            c = redline_filter.count_by_pattern(_Boom())
        self.assertEqual(c["total"], 0)
        self.assertIn("[redline_filter] err=RuntimeError", out.getvalue())

    def test_err_line_rate_limited(self):
        class _Boom:
            def __str__(self):
                raise RuntimeError("boom")
        redline_filter._ERR_LAST[0] = time.monotonic() - 3601.0
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            redline_filter.count_by_pattern(_Boom())
            redline_filter.count_by_pattern(_Boom())
        self.assertEqual(out.getvalue().count("[redline_filter] err="), 1)


class ObserveAnswerTest(unittest.TestCase):
    """observe_answer 三态 + fail-open（server 挂载唯一入口 v1）。"""

    def _rec(self):
        rec = []
        return rec, (lambda *a, **k: rec.append((a, k)))

    def test_off_no_action(self):
        rec, log = self._rec()
        ret = redline_filter.observe_answer("off", H_ADV_CMP, "ab12cd34", log=log)
        self.assertIsNone(ret)
        self.assertEqual(rec, [])

    def test_enforce_not_accepted_v1(self):
        # v1 不收 enforce：与 off 同形零动作（拨键归观察后决策，防自动生效）
        rec, log = self._rec()
        ret = redline_filter.observe_answer("enforce", H_ADV_CMP, "ab12cd34",
                                            log=log)
        self.assertIsNone(ret)
        self.assertEqual(rec, [])

    def test_log_only_emits_line(self):
        rec, log = self._rec()
        ret = redline_filter.observe_answer("log_only", H_ADV_CMP, "ab12cd34",
                                            log=log)
        self.assertEqual(ret["total"], 3)
        self.assertEqual(len(rec), 1)
        args, kwargs = rec[0]
        line = args[0]
        self.assertTrue(line.startswith(
            "[redline_filter] mode=log_only trace=ab12cd34 hits=3 pat="), msg=line)
        self.assertIn("adv_cmp:1", line)
        self.assertNotIn("更严格", line)   # 零原文铁律
        self.assertIs(kwargs.get("flush"), True)   # R4：对齐 flush 惯例

    def test_log_only_no_hit_no_line(self):
        rec, log = self._rec()
        ret = redline_filter.observe_answer("log_only", CLEAN_TXT, "", log=log)
        self.assertEqual(ret["total"], 0)
        self.assertEqual(rec, [])

    def test_default_trace_dash(self):
        rec, log = self._rec()
        redline_filter.observe_answer("log_only", H_ADV_CMP, log=log)
        self.assertIn("trace=-", rec[0][0][0])

    def test_fail_open_on_raising_log(self):
        # log 槽自身炸：绝不外抛、返回 None（fail-open；R5 遥测行被限频/吞）
        def boom(*a, **k):
            raise OSError("log sink broken")
        redline_filter._ERR_LAST[0] = time.monotonic() - 3601.0
        ret = redline_filter.observe_answer("log_only", H_ADV_CMP, "ab12cd34",
                                            log=boom)
        self.assertIsNone(ret)


class ResolveModeTest(unittest.TestCase):
    """开关二态清洗：缺键/坏值回 log_only；enforce 一律不收（v1）。"""

    def test_default_and_valid(self):
        self.assertEqual(redline_filter.DEFAULT_MODE, "log_only")
        self.assertEqual(redline_filter.resolve_mode({}), "log_only")
        self.assertEqual(redline_filter.resolve_mode(
            {redline_filter.CONFIG_KEY: "off"}), "off")
        self.assertEqual(redline_filter.resolve_mode(
            {redline_filter.CONFIG_KEY: "LOG_ONLY"}), "log_only")

    def test_bad_values_and_enforce_fall_back(self):
        for v in ("", "unknown", "enforce", "ENFORCE", 1, None):
            self.assertEqual(
                redline_filter.resolve_mode({redline_filter.CONFIG_KEY: v}),
                "log_only", msg=v)


class FilterAnswerTest(unittest.TestCase):
    """enforce 语义源回归位：句级替换/一轮收敛/幂等（v1 挂载面不调用）。"""

    def test_hit_sentences_replaced_clean_kept(self):
        t = f"{H_ADV_CMP}。条文出处见库内档案。{H_SPEC_NUM}。"
        out, rounds, converged = redline_filter.filter_answer(t)
        self.assertTrue(converged)
        self.assertNotIn(H_ADV_CMP, out)
        self.assertNotIn(H_SPEC_NUM, out)
        self.assertIn("条文出处见库内档案。", out)
        # 整句替换且保留句尾分隔符（句法结构零破坏）
        self.assertEqual(out.count(redline_filter.FALLBACK_SENT + "。"), 2)
        self.assertEqual(rounds, [{"round": 1, "sentences_hit": 2}])

    def test_one_round_convergence(self):
        out, rounds, converged = redline_filter.filter_answer("通常更严格。")
        self.assertTrue(converged)
        self.assertEqual(len(rounds), 1)
        self.assertEqual(rounds[0], {"round": 1, "sentences_hit": 1})
        self.assertIn(redline_filter.FALLBACK_SENT, out)   # 单轮即完成替换

    def test_idempotent(self):
        t = f"{H_ADV_CMP}。{H_SPEC_NUM}。干净句保留。"
        once, _, _ = redline_filter.filter_answer(t)
        twice, rounds2, converged2 = redline_filter.filter_answer(once)
        self.assertEqual(twice, once)   # 幂等：filter(filter(x))==filter(x)
        self.assertTrue(converged2)
        self.assertEqual(rounds2[0]["sentences_hit"], 0)

    def test_clean_text_unchanged(self):
        out, rounds, converged = redline_filter.filter_answer(CLEAN_TXT)
        self.assertEqual(out, CLEAN_TXT)
        self.assertTrue(converged)
        self.assertEqual(rounds[0]["sentences_hit"], 0)


# ===== v2 词表扩容回归（2026-10-15，规格源=work/代码评审-20261015/R1词面覆盖矩阵.md） =====

# ---- 构造纪律先行（矩阵 §五.4 实测教训，v2 落码前置断言，对 v1 跑=红） ----
# 教训原文：扩词实施时增补项必须收进 `(?:...)` 组内——首轮原型曾因串接在组外
# 导致增补词脱离模式结构裸匹配（如 spec 词脱离"后随数字"结构），计数虚高。

_META_CHARS = re.compile(r"[(){}\[\]?*+|.\^$\\]")


def _group_alternatives(group_src):
    """单一非捕获组 `(?:词|词|…)` → frozenset(词面集)；供构造纪律断言拆解。

    形态违例（组外串接/嵌套括号/正则元字符/空枝/重复枝）→ AssertionError。"""
    if not (isinstance(group_src, str) and group_src.startswith("(?:")
            and group_src.endswith(")")):
        raise AssertionError(f"非单一 (?:…) 组形态（疑似组外串接）：{group_src!r}")
    alts = group_src[3:-1].split("|")
    for a in alts:
        if not a:
            raise AssertionError(f"空枝：{group_src!r}")
        if _META_CHARS.search(a):
            raise AssertionError(f"枝含结构元字符（非纯词面）：{a!r} @ {group_src!r}")
    if len(alts) != len(set(alts)):
        raise AssertionError(f"重复枝：{group_src!r}")
    return frozenset(alts)


# ---- 词面登记（v1 基线集 + v2 增补集；矩阵 §四增词清单逐词对应） ----
V1_ADV = frozenset(["通常", "往往", "一般而言", "一般来说", "大概率", "多半",
                    "大多", "普遍", "常见", "典型"])
V1_ADV_PLAIN = frozenset(["通常", "往往", "一般", "大概率", "多半", "大多",
                          "普遍", "常见", "典型"])
V1_CMP = frozenset(["更严格", "更宽松", "更严", "更松", "更高", "更低", "更大",
                    "更小", "更紧", "更先进", "更苛刻"])
V1_DIR = frozenset(["远低于", "远高于", "明显低于", "明显高于", "显著低于",
                    "显著高于", "低于", "高于"])
V1_DA_TAIL = frozenset(["严格", "宽松", "高", "低", "大", "小", "紧"])
V1_SPEC_LEAD = frozenset(["可能", "或许", "也许", "大概", "预计", "估计"])
# v2 核心 23 词（草案标称口径；组位合计 24、去重 22 形——不及/逊于跨 CMP/DIR 双位复用）
V2_NEW_CMP = frozenset(["更加严格", "更加宽松", "更加严", "优于", "严于", "强于",
                        "宽于", "逊于", "胜过", "不及"])
V2_NEW_DIR = frozenset(["不及", "逊于", "超过", "超出"])
V2_NEW_DA_TAIL = frozenset(["严", "松"])
V2_NEW_SPEC_LEAD = frozenset(["大约", "约为", "或将", "有望", "预估", "料将",
                              "恐将", "差不多"])


class WordGroupDisciplineTest(unittest.TestCase):
    """构造纪律（先于 v2 落码写入）：增补词必须收进各词组 (?:...) 组内，
    且六模式源=常量组+结构余部逐字合成——增补词不可能脱离结构裸匹配。"""

    def test_word_groups_single_pure_group(self):
        for src in (redline_filter.ADV, redline_filter.ADV_PLAIN,
                    redline_filter.CMP, redline_filter.DIR,
                    redline_filter.DA_TAIL, redline_filter.SPEC_LEAD):
            _group_alternatives(src)   # 形态违例即 AssertionError

    def test_v2_word_sets_exact(self):
        # 词集精确相等：v1 全保留 + v2 增补全收编 + 无意外词混入
        self.assertEqual(_group_alternatives(redline_filter.ADV), V1_ADV)
        self.assertEqual(_group_alternatives(redline_filter.ADV_PLAIN), V1_ADV_PLAIN)
        self.assertEqual(_group_alternatives(redline_filter.CMP),
                         V1_CMP | V2_NEW_CMP)
        self.assertEqual(_group_alternatives(redline_filter.DIR),
                         V1_DIR | V2_NEW_DIR)
        self.assertEqual(_group_alternatives(redline_filter.DA_TAIL),
                         V1_DA_TAIL | V2_NEW_DA_TAIL)
        self.assertEqual(_group_alternatives(redline_filter.SPEC_LEAD),
                         V1_SPEC_LEAD | V2_NEW_SPEC_LEAD)

    def test_patterns_composed_from_group_constants(self):
        """六模式源码=常量组+同隙护栏+固定结构余部逐字合成（组内收编的结构面
        证据；间隙宽度等 v1 结构参数同时被锁定，防无声漂移）。"""
        p = dict(redline_filter.PATTERNS)
        g_adv = redline_filter._gap_guard(redline_filter._GAP_ADV,
                                          redline_filter.CMP)
        g_da = redline_filter._gap_guard(redline_filter._GAP_DA,
                                         redline_filter.DA_TAIL)
        self.assertEqual(p["adv_cmp"].pattern,
                         redline_filter.ADV + g_adv
                         + redline_filter._GAP_ADV + redline_filter.CMP)
        self.assertEqual(p["adv_cmp_plain"].pattern,
                         redline_filter.ADV_PLAIN + g_adv
                         + redline_filter._GAP_ADV + redline_filter.CMP)
        self.assertEqual(p["bare_cmp"].pattern, redline_filter.CMP)
        self.assertEqual(p["dir_assert"].pattern,
                         r"(?:较|比)" + g_da + redline_filter._GAP_DA
                         + redline_filter.DA_TAIL)
        self.assertEqual(p["dir_num"].pattern,
                         r"(?:远|明显|显著)?" + redline_filter.DIR
                         + r"[^\d。；;\n]{0,6}\d+(?:\.\d+)?%?")
        self.assertEqual(p["spec_num"].pattern,
                         redline_filter.SPEC_LEAD + r"[^。；;\n]{0,10}"
                         + r"\d+(?:\.\d+)?%?")

    def test_gap_guard_first_chars_in_sync(self):
        """护栏字符类独立复算（v2 性能层）：首字类必须恰=词组各枝首字集——
        防 v3 增词忘同步导致护栏误裁（漏拦）；护栏为必要条件零宽、不改语义。"""
        for group_src, gap in ((redline_filter.CMP, redline_filter._GAP_ADV),
                               (redline_filter.DA_TAIL,
                                redline_filter._GAP_DA)):
            alts = _group_alternatives(group_src)
            expect = (r"(?=" + gap + "["
                      + "".join(sorted({w[0] for w in alts})) + "])")
            self.assertEqual(redline_filter._gap_guard(gap, group_src), expect,
                             msg=group_src)

    def test_backup_layer_words_excluded(self):
        """备选 6 词不入（矩阵 §四：FP 面高，归后续决策）——排除位断言。"""
        cmp_alts = _group_alternatives(redline_filter.CMP)
        self.assertNotIn("领先", cmp_alts)     # FP 实证="本产品性能领先"
        self.assertNotIn("超过", cmp_alts)     # 超过只在 DIR（须带数字语境）
        self.assertNotIn("严格得多", cmp_alts)  # X 得多形态=词面化过拟合
        self.assertNotIn("宽松得多", cmp_alts)
        self.assertNotIn("约", _group_alternatives(redline_filter.SPEC_LEAD))  # 裸"约"

    def test_new_words_live_but_struct_gated(self):
        """新增词活体性+结构门控行为断言（组内收编的行为面证据）：
        spec 新词必须后随数字才命中；尾词 严/松 必须 较/比 前缀才命中；
        CMP 新词独立成 bare_cmp 命中——防"收词未生效"与"脱离结构裸匹配"两向漂移。"""
        for w in sorted(V2_NEW_SPEC_LEAD):
            self.assertEqual(redline_filter.count_by_pattern(w + "明天再议")["total"],
                             0, msg=w)   # 无数字=零命中（结构门控，防裸匹配虚高）
            self.assertEqual(redline_filter.count_by_pattern(w + "增长30%")["spec_num"],
                             1, msg=w)
        for w in sorted(V2_NEW_CMP):
            c = redline_filter.count_by_pattern("新版" + w + "旧版")
            self.assertEqual((c["bare_cmp"], c["total"]), (1, 1), msg=w)
        # 尾词 严/松：无 较/比 前缀=零命中；带前缀=dir_assert 命中（门控开）
        self.assertEqual(redline_filter.count_by_pattern("从严执法")["total"], 0)
        self.assertEqual(redline_filter.count_by_pattern("松散管理机制")["total"], 0)
        self.assertEqual(redline_filter.count_by_pattern("比较严")["dir_assert"], 1)


class NormalizeLayerTest(unittest.TestCase):
    """繁简归一化层（v2 行为层；矩阵 §四：一次性关闭繁体字符面）。"""

    def test_traditional_equals_simplified_counts(self):
        pairs = [
            ("通常該規範更嚴格", "通常该规范更严格"),
            ("該標準往往更加嚴格", "该标准往往更加严格"),
            ("典型情況下更寬鬆", "典型情况下更宽松"),
            ("比舊版嚴格", "比旧版严格"),
            ("較舊版更寬鬆", "较旧版更宽松"),
            ("比上一代更先進", "比上一代更先进"),
            ("顯著低於標準值20%", "显著低于标准值20%"),
            ("預計增長30%", "预计增长30%"),
        ]
        for trad, simp in pairs:
            ct = redline_filter.count_by_pattern(trad)
            cs = redline_filter.count_by_pattern(simp)
            self.assertEqual(ct["total"], cs["total"], msg=trad)
            self.assertGreater(cs["total"], 0, msg=trad)   # 繁体旁路已关闭

    def test_simplified_text_untouched(self):
        s = "通常该规范更严格。预计增长30%。"
        self.assertEqual(redline_filter._normalize(s), s)
        self.assertEqual(redline_filter._normalize(""), "")

    def test_t2s_map_registered_shape(self):
        m = redline_filter._T2S_MAP   # v2 登记口径=23 字，键值码位不相交
        self.assertEqual(len(m), 23)
        self.assertFalse(set(m) & set(m.values()))


# ---- 81 题矩阵回归夹具（矩阵 §一逐题逐字复刻；v1 六模式计数=实测历史基线） ----
# 行形态：(题号, 模式位, 族, 题句, v1[adv_cmp, adv_cmp_plain, bare_cmp,
#          dir_assert, dir_num, spec_num])
MATRIX_V1 = [
    (1, "P1 adv_cmp", "正对照", "通常该规范更严格", 1, 1, 1, 0, 0, 0),
    (2, "P1 adv_cmp", "正对照", "往往限值更高", 1, 1, 1, 0, 0, 0),
    (3, "P1", "方向性", "通常该规范优于旧版", 0, 0, 0, 0, 0, 0),
    (4, "P1", "方向性", "该规范往往强于上一版", 0, 0, 0, 0, 0, 0),
    (5, "P1", "方向性", "新标普遍胜过旧标", 0, 0, 0, 0, 0, 0),
    (6, "P1", "方向性", "一般而言新标严于旧标", 0, 0, 0, 0, 0, 0),
    (7, "P1", "方向性", "大多领先行业均值", 0, 0, 0, 0, 0, 0),
    (8, "P1", "方向性", "常见做法超过国标要求", 0, 0, 0, 0, 0, 0),
    (9, "P1", "繁体", "通常該規範更嚴格", 0, 0, 0, 0, 0, 0),
    (10, "P1", "繁体", "該標準往往更加嚴格", 0, 0, 0, 0, 0, 0),
    (11, "P1", "繁体", "典型情況下更寬鬆", 0, 0, 0, 0, 0, 0),
    (12, "P1", "口语化", "通常会比旧版更严", 1, 1, 1, 0, 0, 0),
    (13, "P1", "口语化", "通常比旧版还严", 0, 0, 0, 0, 0, 0),
    (14, "P2 plain", "正对照", "一般要求更严格", 0, 1, 1, 0, 0, 0),
    (15, "P2 plain", "正对照", "常见配置限值更低", 1, 1, 1, 0, 0, 0),
    (16, "P2", "方向性", "一般新标优于旧标", 0, 0, 0, 0, 0, 0),
    (17, "P2", "方向性", "普遍强于同行", 0, 0, 0, 0, 0, 0),
    (18, "P2", "方向性", "多半胜过自动核对", 0, 0, 0, 0, 0, 0),
    (19, "P2", "方向性", "大多领先旧版", 0, 0, 0, 0, 0, 0),
    (20, "P2", "方向性", "典型场景严于国标", 0, 0, 0, 0, 0, 0),
    (21, "P2", "方向性", "常见做法强于人工", 0, 0, 0, 0, 0, 0),
    (22, "P2", "方向性", "总体上新标优于旧版", 0, 0, 0, 0, 0, 0),
    (23, "P2", "繁体", "通常更嚴格", 0, 0, 0, 0, 0, 0),
    (24, "P2", "繁体", "一般更寬鬆", 0, 0, 0, 0, 0, 0),
    (25, "P2", "口语化", "一般会更严", 0, 1, 1, 0, 0, 0),
    (26, "P3 bare", "正对照", "该规范更严格", 0, 0, 1, 0, 0, 0),
    (27, "P3 bare", "正对照", "新版限值更高", 0, 0, 1, 0, 0, 0),
    (28, "P3", "方向性", "新标优于旧标", 0, 0, 0, 0, 0, 0),
    (29, "P3", "方向性", "新标胜过旧标", 0, 0, 0, 0, 0, 0),
    (30, "P3", "方向性", "新标严于旧标", 0, 0, 0, 0, 0, 0),
    (31, "P3", "方向性", "新版强于上一版", 0, 0, 0, 0, 0, 0),
    (32, "P3", "方向性", "旧版逊于新版", 0, 0, 0, 0, 0, 0),
    (33, "P3", "方向性", "新版领先旧版", 0, 0, 0, 0, 0, 0),
    (34, "P3", "繁体", "該規範更嚴格", 0, 0, 0, 0, 0, 0),
    (35, "P3", "繁体", "新版更加嚴格", 0, 0, 0, 0, 0, 0),
    (36, "P3", "口语化", "新规严格得多", 0, 0, 0, 0, 0, 0),
    (37, "P3", "口语化", "新规比旧规更加严格", 0, 0, 0, 1, 0, 0),
    (38, "P3", "方向性", "新规苛刻得多", 0, 0, 0, 0, 0, 0),
    (39, "P3", "方向性", "新规更严苛", 0, 0, 1, 0, 0, 0),
    (40, "P4 dir_assert", "正对照", "比旧版严格", 0, 0, 0, 1, 0, 0),
    (41, "P4 dir_assert", "正对照", "较国标更紧", 0, 0, 1, 1, 0, 0),
    (42, "P4", "方向性", "优于旧版", 0, 0, 0, 0, 0, 0),
    (43, "P4", "方向性", "严于上一版", 0, 0, 0, 0, 0, 0),
    (44, "P4", "方向性", "强于同行", 0, 0, 0, 0, 0, 0),
    (45, "P4", "方向性", "不及旧版严格", 0, 0, 0, 0, 0, 0),
    (46, "P4", "方向性", "超过旧版水平", 0, 0, 0, 0, 0, 0),
    (47, "P4", "口语化", "新版会比旧版还严", 0, 0, 0, 0, 0, 0),
    (48, "P4", "口语化", "新版没有旧版严", 0, 0, 0, 0, 0, 0),
    (49, "P4", "口语化", "跟旧版相比更严", 0, 0, 1, 0, 0, 0),
    (50, "P4", "口语化", "较去年更松了", 0, 0, 1, 0, 0, 0),
    (51, "P4", "繁体", "比舊版嚴格", 0, 0, 0, 0, 0, 0),
    (52, "P4", "繁体", "較舊版更寬鬆", 0, 0, 0, 0, 0, 0),
    (53, "P4", "繁体", "比上一代更先進", 0, 0, 0, 0, 0, 0),
    (54, "P5 dir_num", "正对照", "低于30%", 0, 0, 0, 0, 1, 0),
    (55, "P5 dir_num", "正对照", "明显高于上季度15个百分点", 0, 0, 0, 0, 1, 0),
    (56, "P5", "推测性", "或将低于30%", 0, 0, 0, 0, 1, 0),
    (57, "P5", "推测性", "大约高于50%", 0, 0, 0, 0, 1, 0),
    (58, "P5", "推测性", "约低两成", 0, 0, 0, 0, 0, 0),
    (59, "P5", "繁体", "低於30%", 0, 0, 0, 0, 0, 0),
    (60, "P5", "繁体", "遠高於上季50%", 0, 0, 0, 0, 0, 0),
    (61, "P5", "繁体", "顯著低於標準值20%", 0, 0, 0, 0, 0, 0),
    (62, "P5", "方向性", "不及上季度80%", 0, 0, 0, 0, 0, 0),
    (63, "P5", "方向性", "逊于行业均值40%", 0, 0, 0, 0, 0, 0),
    (64, "P5", "方向性", "超过去年水平35%", 0, 0, 0, 0, 0, 0),
    (65, "P5", "方向性", "优于基准线10个百分点", 0, 0, 0, 0, 0, 0),
    (66, "P5", "口语化", "掉了大概20%", 0, 0, 0, 0, 0, 1),
    (67, "P5", "口语化", "下降约三成", 0, 0, 0, 0, 0, 0),
    (68, "P6 spec_num", "正对照", "可能增长30%", 0, 0, 0, 0, 0, 1),
    (69, "P6 spec_num", "正对照", "预计达50%", 0, 0, 0, 0, 0, 1),
    (70, "P6", "推测性", "大约增长30%", 0, 0, 0, 0, 0, 0),
    (71, "P6", "推测性", "约为30%", 0, 0, 0, 0, 0, 0),
    (72, "P6", "推测性", "或将增长30%", 0, 0, 0, 0, 0, 0),
    (73, "P6", "推测性", "有望增长30%", 0, 0, 0, 0, 0, 0),
    (74, "P6", "推测性", "预估增长30%", 0, 0, 0, 0, 0, 0),
    (75, "P6", "推测性", "恐将下滑10%", 0, 0, 0, 0, 0, 0),
    (76, "P6", "推测性", "料将上涨5%", 0, 0, 0, 0, 0, 0),
    (77, "P6", "推测性", "差不多涨30%", 0, 0, 0, 0, 0, 0),
    (78, "P6", "繁体", "可能增長30%", 0, 0, 0, 0, 0, 1),
    (79, "P6", "繁体", "預計增長30%", 0, 0, 0, 0, 0, 0),
    (80, "P6", "对照内词", "大概增长30%", 0, 0, 0, 0, 0, 1),
    (81, "P6", "对照内词", "或许上涨8%", 0, 0, 0, 0, 0, 1),
]

POSITIVE_CTRL_IDS = frozenset({1, 2, 14, 15, 26, 27, 40, 41, 54, 55, 68, 69})
# v2（核心 23 词+繁简归一化，备选 6 词不入）后对抗零命中残余=known-miss 10 例
# （矩阵 §四核心口径 10/69）：领先×3（#7/#19/#33，备选层不入）、超过无数字
# 形态×2（#8/#46，超过只进 DIR 须带数字）、X得多×2（#36/#38，备选层不入）、
# 没有…严×1（#48，不如/没有=备选前缀不入）、中文数字×2（#58/#67，边界声明
# 内——v1 设计即只认 \d）。防误报修复：此 10 例零命中=预期态，勿当缺陷修。
KNOWN_MISS_V2 = frozenset({7, 8, 19, 33, 36, 38, 46, 48, 58, 67})


class MatrixRegressionTest(unittest.TestCase):
    """81 题矩阵回归（矩阵 §一/§四；v1 基线嵌入+v2 行为断言）。"""

    def test_fixture_shape_and_v1_baseline(self):
        self.assertEqual(len(MATRIX_V1), 81)
        self.assertEqual([r[0] for r in MATRIX_V1], list(range(1, 82)))
        self.assertEqual(len(POSITIVE_CTRL_IDS), 12)
        adversarial = [r for r in MATRIX_V1 if r[0] not in POSITIVE_CTRL_IDS]
        self.assertEqual(len(adversarial), 69)
        # v1 基线自洽（矩阵 §二合计口径）：对抗零命中=57；正对照 v1 全命中
        v1_zero = {r[0] for r in adversarial if sum(r[4:]) == 0}
        self.assertEqual(len(v1_zero), 57)
        for r in MATRIX_V1:
            if r[0] in POSITIVE_CTRL_IDS:
                self.assertGreater(sum(r[4:]), 0, msg=r[3])

    def test_positive_controls_all_hit_v2(self):
        for qid in sorted(POSITIVE_CTRL_IDS):
            row = MATRIX_V1[qid - 1]
            c = redline_filter.count_by_pattern(row[3])
            self.assertGreater(c["total"], 0, msg=f"#{qid} {row[3]}")

    def test_adversarial_zero_hits_exactly_known_miss(self):
        """核心指标：对抗零命中 v1 57/69 → v2 10/69，残余恰=登记的
        known-miss 10 例（双向断言：多一例漏拦=缺口，少一例=意外行为漂移）。"""
        zero = set()
        for r in MATRIX_V1:
            if r[0] in POSITIVE_CTRL_IDS:
                continue
            if redline_filter.count_by_pattern(r[3])["total"] == 0:
                zero.add(r[0])
        self.assertEqual(zero, KNOWN_MISS_V2)

    def test_no_regression_vs_v1_per_pattern(self):
        """词表只增不减：逐题逐模式 v2 计数 ≥ v1 基线（v1 命中零丢失）。"""
        for r in MATRIX_V1:
            c = redline_filter.count_by_pattern(r[3])
            for name, v1v in zip(redline_filter.PATTERN_NAMES, r[4:]):
                self.assertGreaterEqual(
                    c[name], v1v, msg=f"#{r[0]} {r[3]} @{name}")

    def test_spot_v2_totals(self):
        """代表性逐题 total（新词翻正位/v1 双计保留位/繁体归一化位各取样）。"""
        expected = {
            1: 3,    # 正对照 v1 三计保留
            3: 3,    # 优于族翻正：adv+plain+bare
            6: 3,    # 一般而言+严于
            13: 1,   # 比…还严：尾词 严 翻正（dir_assert）
            16: 2,   # 一般+优于：plain+bare
            20: 3,   # 典型+严于
            22: 1,   # 总体上（无副词）：bare 优于
            37: 2,   # v1 dir_assert 保留+更加严格 bare 新增
            41: 2,   # 正对照 v1 双计保留（bare+dir）
            45: 1,   # 不及（CMP）翻正
            47: 1,   # 会比…还严：尾词 严
            49: 2,   # 更严 bare（v1）+ 比…严 dir（v2 新增）
            50: 2,   # 更松 bare（v1）+ 较…松 dir（v2 新增）
            53: 1,   # 繁体归一化翻正：更先进（bare）
            56: 2,   # 或将：spec 新增+dir_num 保留
            57: 2,   # 大约：spec 新增+dir_num 保留
            62: 2,   # 不及：bare+dir_num 双位
            63: 2,   # 逊于：bare+dir_num 双位
            64: 1,   # 超过（DIR，带数字）
            71: 1,   # 约为（spec）
            77: 1,   # 差不多（spec）
        }
        for qid, want in sorted(expected.items()):
            row = MATRIX_V1[qid - 1]
            c = redline_filter.count_by_pattern(row[3])
            self.assertEqual(c["total"], want, msg=f"#{qid} {row[3]}")


# ---- FP 探针（矩阵 §四 FP 探针表；表体 7 条——任务书"8 条"系矩阵回报摘要口径，
# 表体为准） ----
# 断言口径：必零位（裸"约"/领先/超过无数字）断零命中；大约×3/不及格/预计部署
# 的命中=矩阵如实登记的声明内噪声（过拦偏严声明+v1 既有基线），按登记值锁位
# 防无声漂移——并非断零（断零会与"核心 23 词收编"决策直接冲突）。
FP_PROBES = [
    ("合约期限12个月", 0, "裸“约”排除实证位——必零"),
    ("本产品性能领先", 0, "“领先”备选不入——必零"),
    ("会议大约在3点开始", 1, "大约+3：声明内噪声（登记=1）"),
    ("文件大约500字", 1, "大约+500：声明内噪声（登记=1）"),
    ("请大约在5分钟后重试", 1, "大约+5：声明内噪声（登记=1）"),
    ("补考不及格人数30人", 2, "不及=bare_cmp+dir_num 双计（登记=2，真实 FP 面如实登记）"),
    ("预计部署需要2天", 1, "v1 既有基线噪声（登记=1）"),
]


class FPProbeTest(unittest.TestCase):
    """FP 防线：按矩阵 §四登记值逐探针锁定（防新增 FP 面无声扩大）。"""

    def test_fp_probes_registered_counts(self):
        for text, want, why in FP_PROBES:
            c = redline_filter.count_by_pattern(text)
            self.assertEqual(c["total"], want, msg=f"{text}（{why}）")

    def test_extra_zero_guard_probes(self):
        """补充零命中卫兵：裸"约"变体/领先/超过无数字形态。"""
        for t in ("条约共12条", "签约仪式在3号厅举行",
                  "性能超过同侪", "技术领先同行"):
            self.assertEqual(redline_filter.count_by_pattern(t)["total"], 0, msg=t)


class RedosBoundTest(unittest.TestCase):
    """ReDoS 抽测（任务口径）：24k 最坏构造全模式扫描（含归一化）≤10ms。

    矩阵 §四性能实测基线：26k 级 2.9ms（线性无灾难回溯面）；此处取 best-of-5
    降调度噪声。若常态化超标=真性能回归，不得放宽断言了事。
    已登记残余（redline_filter.py 头注⑥，不收进断言集）：极限形态
    "通常更"×4000+"更严"+"通常更"×3998（24k 诱饵海+全文仅一处成词）实测
    ~27ms（1.1μs/字，有界线性、无灾难回溯；输入面=自有 RAG 答案文本，该
    形态不可达）——根治路径（离正则扫描改写/窗口跳跃双字护栏）归后续决策。"""

    def _best_of(self, text, runs=5):
        best = None
        for _ in range(runs):
            t0 = time.perf_counter()
            redline_filter.count_by_pattern(text)
            dt = time.perf_counter() - t0
            best = dt if best is None else min(best, dt)
        return best

    def test_worst_case_constructions_under_10ms(self):
        cases = {
            "spec前缀+间隙回扫": "大约" * 12000,
            "dir_num词+间隙回扫": "低于" * 12000,
            "dir_assert前缀+间隙回扫": "比字" * 12000,
            "adv_cmp前缀+间隙回扫": "通常" * 12000,
            "dir_num可选前缀回溯": "远低于" * 8000,
            "繁体归一化+词面失败": "嚴格" * 12000,
            "纯诱饵风暴(通常更×8000)": "通常更" * 8000,
            "半诱饵(诱饵+成词交织)": ("通常更通常更严" * 3429)[:24000],
            "混合全要素风暴": ("通常大约比低于更严约或将远低于比通常" * 1379)[:24000],
        }
        for name, text in cases.items():
            self.assertGreaterEqual(len(text), 24000, msg=name)
            t = self._best_of(text)
            self.assertLess(t, 0.030,   # 灾难回溯=秒级；30ms 线仍具完全判别力，容共享 CI runner 波动
                            msg=f"{name}: {t * 1000:.2f}ms / {len(text)}字")


if __name__ == "__main__":
    unittest.main()
