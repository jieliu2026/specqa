# -*- coding: utf-8 -*-
"""route_domain.py 独立单测（词表 v2=2026-09-29 D9 批档；期 1 已挂接 b337415）。

覆盖面（施工单+设计稿 §2.3/§2.4/§2.5/§3.3）：五域各正向命中、红线否决最高
优先（概念+参数混合→veto=1）、误分类反例 ≥10 条 veto 拦截 100%（表值+
"是什么/由哪些组成"混合形态，G07 型必入）、veto 无关闭参数锁死、多域冲突
fallback（D5）、零命中 fallback、doc 号直判与多 doc 号并现、条款号定位形、
置信度等权计数与 route_min_confidence、doc_in_domain 域面判定（doc_id 前缀
纪律/缺字段兜底/合成卡不并参数面/D1 口径含 KPI TS 5 件）、词表逐字锁死
（D9：扩改须决策——改词表必红此卷）、HIGH_STAKES import 复用（禁复制）、
空/异常输入健壮性、确定性、[rag-route] 打点行。

词表 v2 增补面（2026-09-29 D9 批档=过程日志三节 12②；呈报=期1路由挂接-20260929.md
§四 五条）：VocabV2VerbatimTest 锁死 v2 新增 tuple/常量（v1 锁死卷零改动
=v1 面逐字未动）+五条修订逐条断言（①单位/出处疑问形 veto ②"几+单位"形
veto ③单数字记号形 veto+事件名排除 ④库外域负信号抑制域定向 ⑤口径域置信
下限=2）。"""
import inspect
import unittest

import citation_check as cc
import route_domain as rd


class VocabVerbatimTest(unittest.TestCase):
    """词表初稿逐字锁死（设计稿 §2.3 表格；扩改须决策禁自动生效=D9——
    任何改动必先红本类，提醒走决策面）。"""

    def test_concept_signals_verbatim(self):
        self.assertEqual(rd.CONCEPT_SIGNALS, (
            "是什么", "什么是", "定义", "概念", "含义", "什么意思", "区别",
            "作用", "原理", "工作机制", "如何理解", "概述", "简介", "场景",
            "案例", "排查思路", "优化思路", "怎么处理", "流程是什么", "为什么"))

    def test_koujing_signals_verbatim(self):
        self.assertEqual(rd.KOUJING_SIGNALS, (
            "KPI", "指标", "计数器", "counter", "公式", "计算", "统计口径",
            "定义式", "性能测量", "PM", "话务量", "接通率", "掉话率", "掉线率",
            "切换成功率", "MOS", "CQI 口径", "测量定义", "上报口径"))

    def test_jiangan_signals_verbatim(self):
        self.assertEqual(rd.JIANGAN_SIGNALS, (
            "工信部", "信产部", "信息产业部", "36号令", "257号", "统计公报",
            "电信服务规范", "监管", "部令", "文号", "申诉", "服务质量标准",
            "红线值", "合规", "备案", "行政处罚"))

    def test_param_extension_verbatim(self):
        self.assertEqual(rd.PARAM_EXTRA_SIGNALS, ("ASN.1", "IE", "字段"))
        self.assertEqual(rd.PARAM_COUNT_SIGNALS,
                         ("最多可配", "几个", "几档", "几级", "几类"))
        self.assertEqual(rd.TABLE_DENSE_DOCS,
                         ("38.133", "36.101", "36.133", "32.425"))

    def test_table_signals_verbatim(self):
        self.assertEqual(rd.TABLE_SIGNALS, (
            "表", "Table", "对照表", "查表", "附录", "Annex", "矩阵",
            "频段表", "配置表", "映射表", "栅格"))

    def test_domains_and_redline_face(self):
        self.assertEqual(rd.DOMAINS, ("概念", "口径", "监管数字", "参数", "精确表"))
        self.assertEqual(rd.REDLINE_DOMAINS, ("监管数字", "参数", "精确表"))

    def test_high_stakes_import_not_copy(self):
        # import 复用禁复制：必须是 citation_check 同一对象（单锚纪律）
        self.assertIs(rd.HIGH_STAKES_KEYWORDS, cc.HIGH_STAKES_KEYWORDS)
        self.assertIs(rd.HIGH_STAKES_PATTERNS, cc.HIGH_STAKES_PATTERNS)


class VocabV2VerbatimTest(unittest.TestCase):
    """词表 v2 新增面逐字锁死（2026-09-29 D9 批档=过程日志三节 12②；五条呈报面
    外禁扩——改 v2 词表必红本类，v1 面零改动由 VocabVerbatimTest 承接）。"""

    def test_v2_unit_source_verbatim(self):
        self.assertEqual(rd.PARAM_V2_UNIT_SOURCE_KEYWORDS, ("上报值",))
        self.assertEqual([n for n, _ in rd.PARAM_V2_UNIT_SOURCE_RES],
                         ["v2:单位疑问形", "v2:出处疑问形"])

    def test_v2_count_signals_verbatim(self):
        self.assertEqual(rd.PARAM_V2_COUNT_SIGNALS, (
            "几 dB", "几 dBm", "几 ms", "几毫秒", "几秒", "几 MHz", "几 kHz",
            "几 GHz", "几 km", "几公里", "几米", "几分钟", "几小时", "几 %",
            "几个百分点", "几字节"))

    def test_v2_symbol_face_verbatim(self):
        self.assertEqual(rd.PARAM_V2_SYMBOL_EXCLUDE,
                         frozenset(("A1", "A2", "A3", "A4", "A5", "A6",
                                    "B1", "B2")))
        self.assertEqual(rd.PARAM_V2_SYMBOL_CONTEXT, (
            "含义", "定义", "是什么", "什么意思", "取值", "门限", "阈值",
            "配置", "参数", "默认值", "单位", "出处", "数值"))
        self.assertEqual(rd.PARAM_V2_SYMBOL_NAME,
                         "v2:单数字记号+参数语境(p0/N1型)")

    def test_v2_ood_signals_verbatim(self):
        self.assertEqual(rd.OOD_SIGNALS, (
            "微波炉", "电磁炉", "菜谱", "食谱", "做饭", "烹饪", "外卖",
            "点餐", "淘宝", "京东", "拼多多", "抖音", "快手", "微信",
            "支付宝", "股票", "炒股", "基金", "理财", "彩票", "高考",
            "中考", "考研", "志愿填报", "分数线", "星座", "运势", "旅游",
            "攻略", "挂号", "医保", "社保", "房贷", "车贷", "育儿", "减肥",
            "健身", "游戏", "电竞", "电影", "电视剧", "综艺", "足球",
            "篮球", "天气"))

    def test_v2_koujing_floor_verbatim(self):
        self.assertEqual(rd.KOUJING_MIN_CONFIDENCE, 2)

    def test_v2_does_not_touch_v1_tuples(self):
        # v1 初稿面逐字零改动（D9 呈报纪律：五条外禁改任何词表条目）
        self.assertEqual(rd.PARAM_COUNT_SIGNALS,
                         ("最多可配", "几个", "几档", "几级", "几类"))
        self.assertEqual(rd.PARAM_EXTRA_SIGNALS, ("ASN.1", "IE", "字段"))


class V2Fix1UnitSourceTest(unittest.TestCase):
    """修订①G12/ANSG12 型单位/出处疑问形（参数类活险，最高优先）。"""

    G12 = ("RSRP 与 RSRQ 分别以什么单位上报？其定义出处 LTE 与 NR 各在哪件规范")

    def test_g12_exact_shape_vetoed(self):
        res = rd.classify(self.G12)
        self.assertEqual(res["veto"], 1)          # 活险翻正：不再落概念面定向
        self.assertEqual(res["route"], "fallback")
        self.assertEqual(res["fallback"], 1)
        self.assertIn("v2:单位疑问形", res["hits"]["参数"])
        self.assertIn("v2:出处疑问形", res["hits"]["参数"])

    def test_unit_question_forms(self):
        for q in ("RSRP 以什么单位上报", "该参数的单位是什么",
                  "上报单位是 dBm 吗", "SINR 单位为何种量纲"):
            res = rd.classify(q)
            self.assertTrue(res["hits"]["参数"], q)
            self.assertEqual(res["veto"], 1, q)

    def test_source_question_forms(self):
        for q in ("定义出处在哪", "该门限出处是哪件规范", "这个参数出自哪份规范"):
            self.assertEqual(rd.classify(q)["veto"], 1, q)

    def test_generic_danwei_no_false_hit(self):
        # 防"单位"泛词误伤（§四.1）：裸"单位"（工作/施工单位语境）不触参数面
        res = rd.classify("施工单位的资质概述")
        self.assertEqual(res["hits"]["参数"], [])
        self.assertEqual(res["veto"], 0)

    def test_shangbaozhi_keyword(self):
        res = rd.classify("RSRP 上报值的量化面概述")
        self.assertIn("上报值", res["hits"]["参数"])
        self.assertEqual(res["veto"], 1)


class V2Fix2CountUnitTest(unittest.TestCase):
    """修订②G38 型"几+单位"形（veto 缺口闭合核）。"""

    G38 = ("PRACH 功控除了 powerRampingStep，还有个配套参数 preambleBoostStep "
           "一般建议配几 dB？现网想两个一起调。")

    def test_g38_exact_shape_vetoed(self):
        res = rd.classify(self.G38)
        self.assertEqual(res["veto"], 1)          # 缺口闭合：veto=1
        self.assertEqual(res["route"], "fallback")
        self.assertIn("几 dB", res["hits"]["参数"])

    def test_ji_unit_combinations(self):
        for q in ("建议配几dB", "时延几毫秒算正常", "带宽占用几 MHz",
                  "覆盖半径几公里", "等待几秒后重发", "误差几个百分点"):
            res = rd.classify(q)
            self.assertEqual(res["veto"], 1, q)
            self.assertTrue(res["hits"]["参数"], q)

    def test_v1_count_signals_intact(self):
        # v1 数量疑问词面照常（"最多可配几个"既有断言面同源）
        res = rd.classify("SSB 波束最多可配几个")
        self.assertEqual(res["veto"], 1)
        self.assertIn("最多可配", res["hits"]["参数"])
        self.assertIn("几个", res["hits"]["参数"])


class V2Fix3SingleDigitSymbolTest(unittest.TestCase):
    """修订③p0-Nominal 型单数字记号形（\\d{1,} 放宽+参数语境组合）。"""

    def test_p0_nominal_meaning_vetoed(self):
        res = rd.classify("p0-Nominal 的含义是什么")
        self.assertEqual(res["veto"], 1)          # 期 1 单测构造期新发现翻正
        self.assertIn(rd.PARAM_V2_SYMBOL_NAME, res["hits"]["参数"])
        self.assertEqual(res["route"], "fallback")

    def test_n1_shape_with_context(self):
        self.assertEqual(rd.classify("N1 接口的定义是什么")["veto"], 1)

    def test_event_names_excluded(self):
        # 事件名形（A1-A6/B1/B2）不入本面——PARAM_EVENT_RE 取值语境专闸承接，
        # "事件概念题不误 veto"既有纪律零回退（ConceptDomainTest 同断面）
        res = rd.classify("A3 和 A5 事件有什么区别")
        self.assertNotIn(rd.PARAM_V2_SYMBOL_NAME, res["hits"]["参数"])
        self.assertEqual(res["veto"], 0)
        self.assertEqual(res["domain"], "概念")

    def test_symbol_without_context_no_hit(self):
        # 记号形单独出现（无参数语境词）不触发——与事件名取值语境纪律同构
        res = rd.classify("p0-Nominal 相关的流程概述")
        self.assertNotIn(rd.PARAM_V2_SYMBOL_NAME, res["hits"]["参数"])
        self.assertEqual(res["veto"], 0)

    def test_two_digit_pattern_untouched(self):
        # HIGH_STAKES 复用面照常（T310 \\d{2,} 原生通道）
        res = rd.classify("T310 的默认值")
        self.assertIn("模式:参数名式记号", res["hits"]["参数"])
        self.assertEqual(res["veto"], 1)


class V2Fix4OodTest(unittest.TestCase):
    """修订④拒答型库外域负信号（G33/G34 型）：抑制域定向退全量。"""

    G33 = "家用微波炉加热饭菜的原理是什么？为什么金属容器不能放进去？"
    G34 = "孩子今年高考 620 分，报计算机还是电气工程专业好就业？"

    def test_g33_suppressed_to_fallback(self):
        res = rd.classify(self.G33)
        self.assertEqual(res["ood"], 1)
        self.assertIn("微波炉", res["ood_hits"])
        self.assertEqual(res["route"], "fallback")
        self.assertEqual(res["fallback"], 1)
        self.assertEqual(res["domain"], "概念")   # 观测面仍报告（生效面=route 键）

    def test_g34_suppressed_to_fallback(self):
        res = rd.classify(self.G34)
        self.assertEqual(res["ood"], 1)
        self.assertEqual(res["route"], "fallback")

    def test_clean_query_ood_zero(self):
        res = rd.classify("什么是 RLF")
        self.assertEqual(res["ood"], 0)
        self.assertEqual(res["ood_hits"], [])
        self.assertEqual(res["route"], "domain")

    def test_ood_does_not_override_veto_priority(self):
        # veto 仍最高优先（§2.4 硬门控零触碰）：库外域词+红线信号 → veto=1
        res = rd.classify("微波炉发射功率是多少 dBm")
        self.assertEqual(res["ood"], 1)
        self.assertEqual(res["veto"], 1)
        self.assertEqual(res["route"], "fallback")

    def test_ood_does_not_block_doc_direct(self):
        # doc 号直判通道（显式规范引用）不受库外域负信号影响
        res = rd.classify("TS 36.300 里与游戏攻略相关的条目概述")
        self.assertEqual(res["ood"], 1)
        self.assertEqual(res["doc_direct"], "TS 36.300")
        self.assertEqual(res["route"], "doc_direct")


class V2Fix5KoujingFloorTest(unittest.TestCase):
    """修订⑤实操泛指标词（C22 型）：口径域单域置信下限=2。"""

    C22_SHAPE = "重划要遵循哪些原则？最后验收指标门槛怎么定"

    def test_single_indicator_signal_no_route(self):
        res = rd.classify(self.C22_SHAPE)
        self.assertEqual(res["domain"], "口径")   # 观测面仍报告
        self.assertEqual(res["confidence"], 1)
        self.assertEqual(res["route"], "fallback")  # 单信号泛词不定向
        self.assertEqual(res["fallback"], 1)

    def test_two_koujing_signals_route(self):
        res = rd.classify("接通率指标怎么统计")
        self.assertEqual(res["domain"], "口径")
        self.assertEqual(res["confidence"], 2)    # 接通率+指标=2 ≥ 下限
        self.assertEqual(res["route"], "domain")

    def test_concept_floor_unchanged(self):
        # 概念域下限不受影响（conf=1 照常定向）
        res = rd.classify("什么是 RLF")
        self.assertEqual(res["confidence"], 1)
        self.assertEqual(res["route"], "domain")

    def test_global_min_confidence_still_applies(self):
        # route_min_confidence 全局下限与域下限叠加（max 语义；签名零触碰）
        res = rd.classify("接通率指标怎么统计", min_confidence=3)
        self.assertEqual(res["route"], "fallback")
        res2 = rd.classify("话务量指标用什么公式计算", min_confidence=3)
        self.assertEqual(res2["confidence"], 4)
        self.assertEqual(res2["route"], "domain")


class ConceptDomainTest(unittest.TestCase):
    def test_unique_concept_hit_routes_domain(self):
        res = rd.classify("什么是 RLF")
        self.assertEqual(res["domain"], "概念")
        self.assertEqual(res["domains"], ["概念"])
        self.assertEqual(res["confidence"], 1)
        self.assertEqual((res["veto"], res["conflict"], res["fallback"]), (0, 0, 0))
        self.assertEqual(res["route"], "domain")
        self.assertIsNone(res["doc_direct"])

    def test_multi_concept_signals_confidence(self):
        res = rd.classify("RRC 重配置的作用和原理是什么，如何理解其工作机制")
        self.assertEqual(res["domain"], "概念")
        # 作用/原理/是什么/如何理解/工作机制 = 5 个等权信号
        self.assertEqual(res["confidence"], 5)
        self.assertEqual(res["route"], "domain")
        self.assertEqual(res["veto"], 0)

    def test_event_name_without_value_context_no_veto(self):
        # 事件名单独出现不触发参数域（设计稿口径=事件名+取值语境）
        res = rd.classify("A3 和 A5 事件有什么区别")
        self.assertEqual(res["domain"], "概念")
        self.assertEqual(res["veto"], 0)
        self.assertNotIn(rd.PARAM_EVENT_NAME, res["hits"]["参数"])


class KoujingDomainTest(unittest.TestCase):
    def test_unique_koujing_hit(self):
        res = rd.classify("话务量指标用什么公式计算")
        self.assertEqual(res["domain"], "口径")
        self.assertEqual(res["confidence"], 4)   # 话务量/指标/公式/计算
        self.assertEqual(res["veto"], 0)
        self.assertEqual(res["route"], "domain")

    def test_ascii_boundary_no_substring_false_hit(self):
        # PM/KPI/MOS/counter 带词边界：非独立 token 不命中
        res = rd.classify("CMOS 电池 kpis 的更换步骤")
        self.assertEqual(res["hits"]["口径"], [])


class JianganDomainTest(unittest.TestCase):
    def test_unique_jiangan_hit_still_veto(self):
        # 监管数字属红线三域：唯一命中也 veto=1 → 全量（§2.4 收窄让位）
        res = rd.classify("监管红线值和行政处罚的申诉流程")
        self.assertEqual(res["domain"], "监管数字")
        self.assertEqual(res["confidence"], 4)   # 监管/红线值/行政处罚/申诉
        self.assertEqual(res["veto"], 1)
        self.assertEqual(res["fallback"], 1)
        self.assertEqual(res["route"], "fallback")

    def test_percent_pattern_hit(self):
        res = rd.classify("服务质量标准是 95% 吗")
        self.assertIn(rd.JIANGAN_PCT_NAME, res["hits"]["监管数字"])
        self.assertIn("服务质量标准", res["hits"]["监管数字"])
        self.assertEqual(res["veto"], 1)

    def test_bulieti_alias_resolves_doc(self):
        res = rd.classify("36号令对文号备案合规的要求概述")
        self.assertIn("信息产业部令第36号", res["docs"])


class ParamDomainTest(unittest.TestCase):
    def test_high_stakes_reuse_face(self):
        res = rd.classify("T310 的默认值")
        self.assertEqual(res["domain"], "参数")
        self.assertIn("默认值", res["hits"]["参数"])          # KEYWORDS 复用
        self.assertIn("模式:参数名式记号", res["hits"]["参数"])  # PATTERNS[0] 复用
        self.assertEqual(res["veto"], 1)
        self.assertEqual(res["route"], "fallback")

    def test_unit_pattern_reuse_face(self):
        res = rd.classify("发射功率 -110dBm 说明什么")
        self.assertIn("模式:数值+单位", res["hits"]["参数"])
        self.assertEqual(res["veto"], 1)

    def test_extra_and_count_signals(self):
        res = rd.classify("RRCReconfiguration 消息的 IE 字段和 ASN.1 定义")
        hits = res["hits"]["参数"]
        self.assertIn("IE", hits)
        self.assertIn("字段", hits)
        self.assertIn("ASN.1", hits)
        self.assertIn(rd.PARAM_MSG_NAME, hits)
        res2 = rd.classify("SSB 波束最多可配几个")
        self.assertIn("最多可配", res2["hits"]["参数"])
        self.assertIn("几个", res2["hits"]["参数"])
        self.assertEqual(res2["veto"], 1)

    def test_event_with_value_context(self):
        res = rd.classify("A3 事件进入条件里的偏移怎么取值")
        self.assertIn(rd.PARAM_EVENT_NAME, res["hits"]["参数"])
        self.assertEqual(res["veto"], 1)

    def test_high_stakes_subset_of_veto(self):
        # 性质锁：凡生产 is_high_stakes_question 命中面，veto 必拦（复用面同源）
        cases = ["T310 默认值？", "取值范围是多少", "门限配置", "-95dBm 含义",
                 "N310 计数器", "p0-Nominal 30dB 配置值", "表值上限下限"]
        for t in cases:
            if cc.is_high_stakes_question(t):
                self.assertEqual(rd.classify(t)["veto"], 1, t)


class TableDomainTest(unittest.TestCase):
    def test_table_signals_veto(self):
        res = rd.classify("查表得到的频段表在哪个附录")
        self.assertEqual(res["domain"], "精确表")
        for sig in ("表", "查表", "频段表", "附录"):
            self.assertIn(sig, res["hits"]["精确表"])
        self.assertEqual(res["veto"], 1)

    def test_prb_with_table_context(self):
        res = rd.classify("PRB 与带宽组合的映射表怎么用")
        self.assertIn(rd.TABLE_PRB_NAME, res["hits"]["精确表"])
        self.assertEqual(res["veto"], 1)

    def test_prb_without_table_context_no_table_hit(self):
        # S16 型：PRB 无表语境 → 精确表不触发（参数面由 多少/10MHz 承接）
        res = rd.classify("LTE 各系统带宽对应的 PRB 数是多少（如 10MHz）")
        self.assertNotIn(rd.TABLE_PRB_NAME, res["hits"]["精确表"])
        self.assertEqual(res["hits"]["精确表"], [])
        self.assertEqual(res["domain"], "参数")

    def test_table_dense_doc_signal(self):
        res = rd.classify("38.133 中 RSRP 门限要求是什么")
        self.assertIn("表密集doc号:38.133", res["hits"]["精确表"])
        self.assertEqual(res["veto"], 1)


class VetoPriorityTest(unittest.TestCase):
    def test_concept_plus_param_mix_veto_wins(self):
        # 概念+参数混合信号 → veto=1 最高优先，禁入一切减轻档（route=fallback）
        res = rd.classify("T310 定时器的定义是什么")
        self.assertEqual(res["veto"], 1)
        self.assertEqual(res["conflict"], 1)
        self.assertEqual(res["fallback"], 1)
        self.assertEqual(res["route"], "fallback")
        self.assertEqual(res["domains"], ["概念", "参数"])
        self.assertIsNone(res["domain"])

    def test_strong_concept_cannot_outvote_single_param_signal(self):
        q = ("概述无线接入网架构的概念与场景，简介其工作机制与原理，"
             "并解释 N310 的含义")
        res = rd.classify(q)
        self.assertGreaterEqual(len(res["hits"]["概念"]), 5)
        self.assertEqual(res["veto"], 1)          # 单个参数信号即否决
        self.assertEqual(res["route"], "fallback")

    def test_veto_has_no_off_switch(self):
        # §2.4：硬门控为代码级纪律不设关闭键——签名面无任何 veto/减轻档开关
        params = set(inspect.signature(rd.classify).parameters)
        self.assertEqual(params, {"query", "min_confidence",
                                  "conflict_policy", "doc_direct_enabled"})
        # 参数组合穷举：红线题 veto/fallback 恒 1（任何配置不可击穿）
        for mc in (0, 1, 99, "bad", None):
            for policy in ("fallback", "priority", "x", None):
                for dd in (True, False):
                    res = rd.classify("T310 默认值是多少", min_confidence=mc,
                                      conflict_policy=policy,
                                      doc_direct_enabled=dd)
                    self.assertEqual(res["veto"], 1)
                    self.assertEqual(res["fallback"], 1)
                    self.assertEqual(res["route"], "fallback")


class MisclassifyVetoTest(unittest.TestCase):
    """误分类反例 ≥10 条（表值+"是什么/由哪些组成"混合形态）：veto 拦截
    必须 100%（§3.3 风险 1 测试断言面；G07 型必入）。"""

    CASES = (
        # G07 型（在册校准案例，数量疑问词扩充对症面）——必入
        "5G NR 的 SSB（Synchronization Signal Block）由哪些信号组成？"
        "时频结构多大？SS burst set 单载波最大个数如何定",
        "MCS 对照表是什么，各编号对应什么调制阶数",
        "PRB 与系统带宽的对照表内容是什么",
        "T310 定时器的含义是什么",
        "a3-Offset 的取值范围是什么",
        "NR 中 SSB 周期最多可配几个",
        "38.133 中 RSRP 门限要求是什么",
        "掉话率的红线值是多少，怎么理解",
        "10MHz 带宽对应多少 PRB，查哪张表",
        "RRCReconfiguration 消息能携带哪些字段",
        "表 5.6-1 说的是什么内容",
        "A3 事件进入条件里的偏移怎么取值",
        "p0-Nominal 的配置值是什么，由哪些部分组成",
    )

    def test_all_counterexamples_vetoed(self):
        self.assertGreaterEqual(len(self.CASES), 10)
        for q in self.CASES:
            res = rd.classify(q)
            self.assertEqual(res["veto"], 1, q)
            self.assertEqual(res["fallback"], 1, q)
            self.assertEqual(res["route"], "fallback", q)

    def test_g07_exact_question_vetoed(self):
        res = rd.classify("5G NR 的 SSB 由哪些信号组成")
        self.assertEqual(res["veto"], 1)
        self.assertIn(rd.PARAM_COMPOSE_NAME, res["hits"]["参数"])


class ConflictFallbackTest(unittest.TestCase):
    def test_concept_koujing_conflict_no_veto(self):
        res = rd.classify("掉话率的定义是什么")
        self.assertEqual(res["conflict"], 1)
        self.assertEqual(res["domains"], ["概念", "口径"])   # DOMAINS 稳定序
        self.assertIsNone(res["domain"])
        self.assertEqual(res["confidence"], 0)
        self.assertEqual(res["veto"], 0)
        self.assertEqual(res["fallback"], 1)
        self.assertEqual(res["route"], "fallback")

    def test_priority_policy_not_enabled(self):
        # D5 批档：priority 档未启用——显式传入也一律按 fallback
        res = rd.classify("掉话率的定义是什么", conflict_policy="priority")
        self.assertEqual(res["conflict"], 1)
        self.assertEqual(res["route"], "fallback")
        self.assertEqual(res["fallback"], 1)


class ZeroHitFallbackTest(unittest.TestCase):
    def test_zero_hit(self):
        res = rd.classify("今天天气怎么样")
        self.assertIsNone(res["domain"])
        self.assertEqual(res["domains"], [])
        self.assertEqual((res["veto"], res["conflict"], res["fallback"]), (0, 0, 1))
        self.assertEqual(res["route"], "fallback")
        self.assertEqual(res["confidence"], 0)
        self.assertEqual(res["hits"], {d: [] for d in rd.DOMAINS})

    def test_min_confidence_gate(self):
        res = rd.classify("什么是 RLF", min_confidence=2)
        self.assertEqual(res["domain"], "概念")     # 观测面仍报告
        self.assertEqual(res["confidence"], 1)
        self.assertEqual(res["fallback"], 1)        # 不足 → 不定向
        self.assertEqual(res["route"], "fallback")


class DocDirectTest(unittest.TestCase):
    def test_prefixed_doc_direct_bypasses_domain(self):
        res = rd.classify("TS 36.300 中切换流程概述")
        self.assertEqual(res["docs"], ["TS 36.300"])
        self.assertEqual(res["doc_direct"], "TS 36.300")
        self.assertEqual(res["route"], "doc_direct")
        self.assertEqual(res["fallback"], 0)
        self.assertEqual(res["domain"], "概念")     # 观测面仍报告

    def test_bare_number_resolves_via_known_table(self):
        res = rd.classify("36.331 里随机接入的简介")
        self.assertEqual(res["doc_direct"], "TS 36.331")
        res2 = rd.classify("36.805 的研究概述")
        self.assertEqual(res2["doc_direct"], "TR 36.805")   # 号表解析 TR 前缀

    def test_prefix_typo_tolerated_by_number_table(self):
        res = rd.classify("TS 36.805 的概述")   # 库内实为 TR 36.805
        self.assertEqual(res["doc_direct"], "TR 36.805")

    def test_reg_alias_doc_direct(self):
        res = rd.classify("信号升格行动的目标概述")
        self.assertEqual(res["doc_direct"], "工信部联通信〔2023〕257号")
        self.assertEqual(res["route"], "doc_direct")
        self.assertEqual(res["veto"], 0)

    def test_veto_overrides_doc_direct(self):
        # §2.4：veto 题一律全量——doc 直判收窄让位（doc_direct 仅观测报告）
        res = rd.classify("电信服务规范的申诉要求概述")
        self.assertEqual(res["doc_direct"], "信息产业部令第36号")
        self.assertEqual(res["veto"], 1)
        self.assertEqual(res["route"], "fallback")
        self.assertEqual(res["fallback"], 1)

    def test_multi_doc_cooccurrence_fallback(self):
        res = rd.classify("TS 36.300 与 TS 38.300 的概述有何区别")
        self.assertEqual(res["docs"], ["TS 36.300", "TS 38.300"])
        self.assertIsNone(res["doc_direct"])
        self.assertEqual(res["fallback"], 1)
        self.assertEqual(res["route"], "fallback")

    def test_unknown_spec_ref_fallback(self):
        res = rd.classify("TS 24.008 的 Attach 流程概述")
        self.assertEqual(res["docs"], [])
        self.assertEqual(res["docs_unresolved"], ["TS 24.008"])
        self.assertIsNone(res["doc_direct"])
        self.assertEqual(res["route"], "fallback")

    def test_doc_direct_disabled(self):
        res = rd.classify("TS 36.300 中切换流程概述", doc_direct_enabled=False)
        self.assertIsNone(res["doc_direct"])
        self.assertEqual(res["docs"], ["TS 36.300"])   # 观测面保留
        self.assertEqual(res["route"], "domain")
        self.assertEqual(res["domain"], "概念")

    def test_same_doc_twice_is_single(self):
        res = rd.classify("TS 38.300 概述，再看 TS38.300 简介")
        self.assertEqual(res["docs"], ["TS 38.300"])
        self.assertEqual(res["doc_direct"], "TS 38.300")

    # ---- mutmut 试点回补②（E3 报告 §三/§五.4，2026-10-08）：
    # resolve_docs 前缀号+裸号混现形无断言，裸号循环 continue→break 变异体
    # 存活——旧断言面里混现形缺席，裸号循环的 continue 分支（前缀已计号跳过）
    # 从未与"后继裸号仍被解析"组合断言过。以下三条钉死混现形语义。----
    def test_prefix_and_bare_mixed_forms_both_resolved(self):
        # "TS 36.300" 的号段带空格也会被裸号正则命中→continue 跳过；
        # break 变异体会在此提前断链，38.331 永不入 docs → 单 doc 直判（错路由）
        res = rd.classify("TS 36.300 和 38.331 的概述有什么区别")
        self.assertEqual(res["docs"], ["TS 36.300", "TS 38.331"])
        self.assertEqual(res["docs_unresolved"], [])
        self.assertIsNone(res["doc_direct"])     # 两 doc 并现 → 退全量
        self.assertEqual(res["fallback"], 1)
        self.assertEqual(res["route"], "fallback")

    def test_bare_before_prefix_also_resolves_both(self):
        # 逆序混现（裸号在前）：解析次序不影响成员完整性
        res = rd.classify("38.331 与 TS 36.300 的区别")
        self.assertEqual(res["docs"], ["TS 36.300", "TS 38.331"])
        self.assertEqual(res["route"], "fallback")

    def test_same_number_bare_reprise_continues_parsing(self):
        # 最短杀形：前缀号同号裸现（必踩 continue）+ 后继新裸号（须继续解析）
        res = rd.classify("TS 36.300 与 36.331 的差异对比")
        self.assertEqual(res["docs"], ["TS 36.300", "TS 36.331"])
        self.assertIsNone(res["doc_direct"])
        self.assertEqual(res["route"], "fallback")


class ClauseLocatorTest(unittest.TestCase):
    def test_clause_with_doc(self):
        res = rd.classify("TS 38.331 的 5.3.5.1 讲了什么内容")
        self.assertEqual(res["clause_hint"], 1)
        self.assertEqual(res["clause_locators"], ["5.3.5.1"])
        self.assertEqual(res["doc_direct"], "TS 38.331")
        self.assertEqual(res["route"], "doc_direct")

    def test_bare_clause_no_doc_direct(self):
        # 裸条款号无从解析 doc 面 → 不直判、走域规则（模块 docstring 解释性登记）
        res = rd.classify("5.3.5.1 规定内容的概述")
        self.assertEqual(res["clause_hint"], 1)
        self.assertIsNone(res["doc_direct"])
        self.assertEqual(res["route"], "domain")
        self.assertEqual(res["domain"], "概念")

    def test_version_not_clause(self):
        res = rd.classify("V18.10.0 里 RSSI 定义的概述")
        self.assertEqual(res["clause_hint"], 0)
        self.assertEqual(res["clause_locators"], [])
        # 已知宽 veto 面登记：V18 命中 HIGH_STAKES 参数名式记号（生产 A2 同源）
        self.assertEqual(res["veto"], 1)
        self.assertTrue(cc.is_high_stakes_question("V18.10.0 里 RSSI 定义的概述"))

    def test_g39_shape_clause_and_alias(self):
        res = rd.classify("《电信服务规范》附录2 第 2.2.9 条对高铁场景掉话率"
                          "的加严规定是多少")
        self.assertIn("2.2.9", res["clause_locators"])
        self.assertEqual(res["doc_direct"], "信息产业部令第36号")
        self.assertEqual(res["veto"], 1)          # 多少/附录 红线信号
        self.assertEqual(res["route"], "fallback")


class RobustnessTest(unittest.TestCase):
    def test_empty_and_weird_inputs_never_raise(self):
        for bad in (None, "", "   ", 0, 123, [], {}, (), set(), 3.5,
                    {"a": 1}, b"bytes", object()):
            res = rd.classify(bad)
            self.assertIsInstance(res, dict)
            self.assertIn(res["route"], ("doc_direct", "domain", "fallback"))
        # 空/None 面：零命中退全量（=现行行为，零恶化）
        for empty in (None, "", "   "):
            res = rd.classify(empty)
            self.assertEqual((res["veto"], res["conflict"], res["fallback"]),
                             (0, 0, 1))
            self.assertEqual(res["route"], "fallback")
            self.assertIsNone(res["domain"])

    def test_long_input_truncated(self):
        res = rd.classify("为什么" * 5000)
        self.assertEqual(res["domain"], "概念")
        self.assertEqual(res["confidence"], 1)    # 等权去重计数，与出现次数无关

    def test_deterministic(self):
        q = "TS 36.331 中 T310 定时器的定义是什么，5.3.5.1 有说明吗"
        self.assertEqual(rd.classify(q), rd.classify(q))

    def test_norm_query_face(self):
        self.assertEqual(rd.norm_query("  a \n\t b  "), "a b")
        self.assertEqual(rd.norm_query(None), "")
        self.assertEqual(len(rd.norm_query("x" * 9999)), rd.ROUTE_QUERY_MAX_CHARS)


class DocInDomainTest(unittest.TestCase):
    """域面选席约束（§2.2；doc_id 前缀为准、元数据为辅、缺字段兜底）。"""

    CARD = {"doc_id": "TS 36.331", "corpus_type": "case_card",
            "chunk_type": "case_card", "source_domain": "synthetic"}
    TR = {"doc_id": "TR 36.839", "corpus_type": "3gpp",
          "chunk_type": "clause", "source_domain": "3gpp"}
    TS = {"doc_id": "TS 36.331", "corpus_type": "3gpp", "chunk_type": "clause"}
    MISSING = {"doc_id": "TS 38.133", "chunk_type": "table_row_group"}  # 1,476 行型
    REG = {"doc_id": "信息产业部令第36号", "corpus_type": "监管",
           "chunk_type": "条", "source_domain": "miit"}

    def test_card_goes_concept_not_param(self):
        self.assertTrue(rd.doc_in_domain(self.CARD, "概念"))
        self.assertTrue(rd.doc_in_domain(self.CARD, "口径"))
        self.assertFalse(rd.doc_in_domain(self.CARD, "参数"))
        self.assertFalse(rd.doc_in_domain(self.CARD, "精确表"))

    def test_tr_prefix_is_concept_not_param(self):
        # TR/TS 同 corpus_type=3gpp——区分唯靠 doc_id 前缀（附节不一致 2）
        self.assertTrue(rd.doc_in_domain(self.TR, "概念"))
        self.assertFalse(rd.doc_in_domain(self.TR, "参数"))

    def test_ts_chunk_faces(self):
        self.assertTrue(rd.doc_in_domain(self.TS, "参数"))
        self.assertFalse(rd.doc_in_domain(self.TS, "概念"))
        self.assertFalse(rd.doc_in_domain(self.TS, "精确表"))

    def test_missing_metadata_doc_id_fallback(self):
        # 附节不一致 3：缺三字段行按 doc_id 兜底，不得漏出参数/精确表域面
        self.assertTrue(rd.doc_in_domain(self.MISSING, "参数"))
        self.assertTrue(rd.doc_in_domain(self.MISSING, "精确表"))
        self.assertFalse(rd.doc_in_domain(self.MISSING, "概念"))

    def test_regulatory_face(self):
        self.assertTrue(rd.doc_in_domain(self.REG, "监管数字"))
        self.assertFalse(rd.doc_in_domain(self.REG, "参数"))
        aux = {"doc_id": "某新文号", "corpus_type": "监管"}
        self.assertTrue(rd.doc_in_domain(aux, "监管数字"))   # 元数据辅助兜底

    def test_kpi_ts_in_koujing_d1(self):
        # D1 批档：口径域面含 PM/KPI TS 5 件
        for d in sorted(rd.KPI_TS_DOCS):
            rec = {"doc_id": d, "corpus_type": "3gpp", "chunk_type": "clause"}
            self.assertTrue(rd.doc_in_domain(rec, "口径"), d)
            self.assertTrue(rd.doc_in_domain(rec, "参数"), d)
        self.assertEqual(len(rd.KPI_TS_DOCS), 5)

    def test_table_facet_scope(self):
        for ct in ("table_row_group", "asn1_card"):
            rec = {"doc_id": "TS 38.331", "chunk_type": ct}
            self.assertTrue(rd.doc_in_domain(rec, "精确表"))
        rec = {"doc_id": "TS 38.331", "chunk_type": "clause"}
        self.assertFalse(rd.doc_in_domain(rec, "精确表"))

    def test_bad_inputs(self):
        self.assertFalse(rd.doc_in_domain(None, "概念"))
        self.assertFalse(rd.doc_in_domain({}, "概念"))
        self.assertFalse(rd.doc_in_domain(self.TS, "未知域"))
        self.assertFalse(rd.doc_in_domain(self.TS, None))


class LogLineTest(unittest.TestCase):
    def test_format_matches_spec_and_no_query_text(self):
        res = rd.classify("掉话率的定义是什么")
        line = rd.format_log_line(res)
        self.assertEqual(line, "[rag-route] domain=- conf=0 veto=0 fallback=1")
        self.assertNotIn("掉话率", line)      # 打点不含题面文本（纪律同 [rag-hybrid]）
        res2 = rd.classify("什么是 RLF")
        self.assertEqual(rd.format_log_line(res2),
                         "[rag-route] domain=概念 conf=1 veto=0 fallback=0")
        self.assertEqual(rd.format_log_line(None),
                         "[rag-route] domain=- conf=0 veto=0 fallback=0")

    # ---- mutmut 试点回补①（E3 报告 §三/§五.4，2026-10-08）：
    # 旧三断言例 veto 恒为 0，veto=1 态打点行从未断言——format_log_line 的
    # .get("veto") 键名变异体（→.get(None)/.get("VETO")）存活。----
    def test_veto_one_state_in_log_line(self):
        res = rd.classify("电信服务规范的申诉要求是什么")   # 红线域词 → veto=1
        self.assertEqual(res["veto"], 1)                  # 前置：确系 veto=1 态
        self.assertEqual(rd.format_log_line(res),
                         "[rag-route] domain=- conf=0 veto=1 fallback=1")
        # veto 位数字非零且非题面文本（打点纪律）
        line = rd.format_log_line(res)
        self.assertIn("veto=1", line)
        self.assertNotIn("电信服务规范", line)


if __name__ == "__main__":
    unittest.main()
