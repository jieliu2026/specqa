# -*- coding: utf-8 -*-
"""乙案族选席（family selection R1-R5）+ 装载面三字段 离线单测（2026-09-29 施工）。

对象=rag.py：clean_family_select_params 坏值清洗、_rec_is_miit/_family_miit_key/
_family_clone_key 族键检索期推导、family_member_select（R1 父条成员级让位/
R2 族内 0 负项全保/R3 保底 1 席平局≤2 席/R4 克隆折叠仅明确时/R5 分数载体不动）、
META_FIELDS 八字段装载（含缺三字段行容错——现库实测 1,476 行 TS 38.133/38.214
缺 corpus_type/chunk_type/source_domain，装载必须不崩、族推导降级 None）、
sidecar v2 往返与 v1 拒载、RagService._decrowd_assemble 挂点（组装序=②③重打分
→族选席→①配额、overflow 回补防证据面缩水、mq truncate=False 不选席）。

结构断言：family_select_enabled=false（默认）零调用面=旧路径逐位等价。
样例=S1 真题块文（监管 221 行实测 locator/content 形态，公开规范文本非密件）。
零网络（stub embed_fn）、8 维夹具（真实库 1024 维，逻辑与维度无关）。
方案档：建库/logs/负控弱区chunk父子款方案-20260929.md §2.2。
"""
import json
import math
import os
import tempfile
import unittest

import rag


# —— S1 涉案真块文（id 前 8 位 → (doc_id, locator, chunk_type, content)）——
DOC36 = "信息产业部令第36号"
DOC257 = "工信部联通信〔2023〕257号"
# 块文=真库 content 形态（含父链语境头【…】——方案 §1.2：款块已带父链语境头，
# 257号款块头含年份="丙案监管侧已实现态"实证；负项计数吃整块文本，头在位是
# S1V-13 款3/款1 双 0 负项的前提）
REAL = {
    # S1V-12 族（1.2.3 网络接通率：父条+款1+款2；R14 改写题面锚=款2）
    "e458b795": (DOC36, "附录1 1.2.3 网络接通率", "条",
                 "【附录1｜1.2 通信质量标准 通信质量标准｜1.2.3 网络接通率 网络接通率】\n网络接通率\n固定网本地电话呼叫网络接通率≥95％；国内长途电话呼叫网络接通率≥93％。"),
    "e1b94d48": (DOC36, "附录1 1.2.3 网络接通率 款1", "款",
                 "【附录1｜1.2 通信质量标准 通信质量标准｜1.2.3 网络接通率 网络接通率】\n网络接通率固定网本地电话呼叫网络接通率≥95％；"),
    "ad5b1d14": (DOC36, "附录1 1.2.3 网络接通率 款2", "款",
                 "【附录1｜1.2 通信质量标准 通信质量标准｜1.2.3 网络接通率 网络接通率】\n国内长途电话呼叫网络接通率≥93％。"),
    # S1V-09 克隆族（计费差错率×5：锚 1.2.5 + 四跨附录克隆）
    "61bf4670": (DOC36, "附录1 1.2.5 计费差错率", "条",
                 "【附录1｜1.2 通信质量标准 通信质量标准｜1.2.5 计费差错率 计费差错率】\n计费差错率\n固定网本地及国内长途电话业务的计费差错率应≤10 -5（原版式为 10 的 -5 次方）。"),
    "a2332073": (DOC36, "附录2 2.1.2 计费差错率", "条",
                 "【附录2｜2.1 服务质量标准 服务质量标准｜2.1.2 计费差错率 计费差错率】\n计费差错率\n数字蜂窝移动通信业务的计费差错率应≤10 -4（原版式为 10 的 -4 次方）。"),
    "1b63777c": (DOC36, "附录3 3.2.4 计费差错率", "条",
                 "【附录3｜3.2 通信质量标准 通信质量标准｜3.2.4 计费差错率 计费差错率】\n计费差错率\n因特网数据传送业务的计费差错率应≤10 -4（原版式为 10 的 -4 次方）。"),
    "014f4432": (DOC36, "附录4 4.2.3 计费差错率", "条",
                 "【附录4｜4.2 通信质量标准 通信质量标准｜4.2.3 计费差错率 计费差错率】\n计费差错率\n国内IP电话业务的计费差错率应≤10 -4（原版式为 10 的 -4 次方）。"),
    "f220b255": (DOC36, "附录6 6.2.2 计费差错率", "条",
                 "【附录6｜6.2 通信质量标准 通信质量标准｜6.2.2 计费差错率 计费差错率】\n计费差错率\n电信租用信道业务的计费差错率应≤10 -4（原版式为 10 的 -4 次方）。"),
    # S1V-13（257号 （二）分支族：条+款1/2/3；双胞胎陷阱=（一）款2）
    "e5348bc5": (DOC257, "主要目标 （二）", "条",
                 "【主要目标｜（二） 到2025年底】\n到2025年底\n——超过12万个重点场所实现移动网络深度覆盖、3万公里铁路和50万公里公路、200条地铁线路实现移动网络连续覆盖。5G网络覆盖深度和广度持续完善，5G流量占比显著提升。\n——移动网络下行均值接入速率不低于220Mbps，上行均值接入速率不低于45Mbps，卡顿、时延等主要业务指标全面优化，移动网络达标速率占比不低于95%（即95%情形下达到相关速率标准要求）。"),
    "d0bd3689": (DOC257, "主要目标 （二） 款1", "款",
                 "【主要目标｜（二） 到2025年底】\n到2025年底——超过12万个重点场所实现移动网络深度覆盖、3万公里铁路和50万公里公路、200条地铁线路实现移动网络连续覆盖。"),
    "d8e54666": (DOC257, "主要目标 （二） 款2", "款",
                 "【主要目标｜（二） 到2025年底】\n5G网络覆盖深度和广度持续完善，5G流量占比显著提升。"),
    "e1e67ff2": (DOC257, "主要目标 （二） 款3", "款",
                 "【主要目标｜（二） 到2025年底】\n——移动网络下行均值接入速率不低于220Mbps，上行均值接入速率不低于45Mbps，卡顿、时延等主要业务指标全面优化，移动网络达标速率占比不低于95%（即95%情形下达到相关速率标准要求）。"),
    "4820a614": (DOC257, "主要目标 （一） 款2", "款",
                 "【主要目标｜（一） 到2024年底】\n——移动网络下行均值接入速率不低于200Mbps，上行均值接入速率不低于40Mbps，卡顿、时延等主要业务指标加快改善，移动网络达标速率占比不低于90%（即90%情形下达到相关速率标准要求）。"),
    # S1V-15（1.1.2 公开服务电话：父条+款1）
    "bd30e67a": (DOC36, "附录1 1.1.2 电信业务经营者应公开服务电话", "条",
                 "【附录1｜1.1 服务质量标准 服务质量标准｜1.1.2 电信业务经营者应公开服务电话 电信业务经营者应公开服务电话。固定电话业务的服务…】\n电信业务经营者应公开服务电话。固定电话业务的服务电话为\"10000\"（中国电信）、\"10060\"（中国网通）、\"10050\"（中国铁通）；用户拨打服务电话按当地市话费标准计收费用。"),
    "d41d47fb": (DOC36, "附录1 1.1.2 电信业务经营者应公开服务电话 款1", "款",
                 "【附录1｜1.1 服务质量标准 服务质量标准｜1.1.2 电信业务经营者应公开服务电话 电信业务经营者应公开服务电话。固定电话业务的服务…】\n固定电话业务的服务电话为\"10000\"（中国电信）、\"10060\"（中国网通）、\"10050\"（中国铁通）；"),
    # S1V-11（3.2.1 IP包丢失率：父条+款1/款2）
    "87e01bde": (DOC36, "附录3 3.2.1 IP包丢失率", "条",
                 "【附录3｜3.2 通信质量标准 通信质量标准｜3.2.1 IP包丢失率 IP包丢失率】\nIP包丢失率\n固定IP网络包丢失率≤2％；移动IP网络包丢失率≤5％。"),
    "ae8c7373": (DOC36, "附录3 3.2.1 IP包丢失率 款1", "款",
                 "【附录3｜3.2 通信质量标准 通信质量标准｜3.2.1 IP包丢失率 IP包丢失率】\nIP包丢失率固定IP网络包丢失率≤2％；"),
    "c0d29a1b": (DOC36, "附录3 3.2.1 IP包丢失率 款2", "款",
                 "【附录3｜3.2 通信质量标准 通信质量标准｜3.2.1 IP包丢失率 IP包丢失率】\n移动IP网络包丢失率≤5％。"),
    # S1V-06/01 面（接续时延：跨附录克隆对+款块；2.2.2 语境头含"数字蜂窝
    # 移动通信业务"=真库节标题形态）
    "a99a72f0": (DOC36, "附录1 1.2.2 接续时延", "条",
                 "【附录1｜1.2 通信质量标准 通信质量标准｜1.2.2 接续时延 接续时延】\n接续时延\n固定网本地及国内长途电话接续时延应≤规定值。"),
    "7aeb544f": (DOC36, "附录1 1.2.2 接续时延 款2", "款",
                 "【附录1｜1.2 通信质量标准 通信质量标准｜1.2.2 接续时延 接续时延】\n国内长途电话接续时延平均值≤规定值。"),
    "3cd734b9": (DOC36, "附录2 2.2.2 接续时延", "条",
                 "【附录2｜2.2 数字蜂窝移动通信业务的通信质量标准 通信质量标准｜2.2.2 接续时延 接续时延】\n接续时延\n数字蜂窝移动通信业务接续时延应≤规定值。"),
}

# S1 现行卷面题面（R14 改后态，建库/logs/S1独立验证卷-20260927.jsonl 同源）
Q09 = "固定网本地及国内长途电话业务的计费差错率要求做到什么数量级？"
Q11 = "手机移动 IP 网络的包丢失率上限是多少？"
Q12 = "家里座机打国内长途电话，网络接通率最低要达到百分之多少才算达标？"
Q13 = "'信号升格'专项行动要求到 2025 年底，移动网络下行均值接入速率不低于多少？"
Q15 = "家里的固定电话线原来是原中国网通的，服务电话应该打哪个号？"
QB12 = "数字蜂窝移动通信业务的计费差错率"   # B 卷 canary 题面

FAM_ON = {"enabled": True, "scope": "miit+clone", "words": "full",
          "clone_margin": 1}
FAM_MIIT = {"enabled": True, "scope": "miit", "words": "full",
            "clone_margin": 1}
FAM_OFF = {"enabled": False, "scope": "miit", "words": "full",
           "clone_margin": 1}


def _rec(rid, doc=None, loc=None, content=None, ct="监管", cht=None,
         sd="miit", version=""):
    """库行 rec 夹具（默认监管域；ct/sd 传 None=缺字段行形态）。"""
    if rid in REAL:
        d, real_loc, c, body = REAL[rid]
        doc = d if doc is None else doc
        loc = real_loc if loc is None else loc
        content = body if content is None else content
        cht = c if cht is None else cht
    r = {"id": rid, "content": content or "", "doc_id": doc or "",
         "version": version, "locator": loc or ""}
    if ct is not None:
        r["corpus_type"] = ct
    if cht is not None:
        r["chunk_type"] = cht
    if sd is not None:
        r["source_domain"] = sd
    return r


def _hit(rank, score, rid, **kw):
    return {"rank": rank, "score": score, "rec": _rec(rid, **kw),
            "idx": rank - 1}


def _pool(id_scores, **kw):
    return [_hit(i, s, rid, **kw) for i, (rid, s) in enumerate(id_scores, 1)]


def _ids(hits):
    return [h["rec"]["id"] for h in hits]


class CleanFamilySelectParamsTest(unittest.TestCase):
    """配置清洗：默认关；坏值回默认（口径贴 clean_decrowd_params）。"""

    def test_defaults_all_off(self):
        p = rag.clean_family_select_params(rag.DEFAULT_RAG_CONFIG)
        self.assertFalse(p["enabled"])
        self.assertEqual(p["scope"], "miit")
        self.assertEqual(p["words"], "full")
        self.assertEqual(p["clone_margin"], 1)

    def test_enabled_and_scope_clone(self):
        p = rag.clean_family_select_params(
            {"family_select_enabled": True, "family_select_scope": "miit+clone"})
        self.assertTrue(p["enabled"])
        self.assertEqual(p["scope"], "miit+clone")

    def test_bad_scope_falls_back(self):
        for bad in ("table", "MIIT ", "", None, 123, "bogus"):
            p = rag.clean_family_select_params({"family_select_scope": bad})
            # "MIIT " 归一后=miit 合法；其余回默认
            self.assertIn(p["scope"], ("miit",))

    def test_scope_case_normalized(self):
        p = rag.clean_family_select_params(
            {"family_select_scope": " MIIT+Clone "})
        self.assertEqual(p["scope"], "miit+clone")

    def test_bad_words_falls_back(self):
        for bad in ("bogus", "", None, 7):
            p = rag.clean_family_select_params({"family_select_words": bad})
            self.assertEqual(p["words"], "full")
        p = rag.clean_family_select_params({"family_select_words": "CORE"})
        self.assertEqual(p["words"], "core")

    def test_bad_margin_falls_back(self):
        for bad in ("x", None, float("nan")):
            p = rag.clean_family_select_params({"clone_fold_min_margin": bad})
            self.assertEqual(p["clone_margin"],
                             rag.DEFAULT_CLONE_FOLD_MIN_MARGIN)
        p = rag.clean_family_select_params({"clone_fold_min_margin": -1})
        self.assertEqual(p["clone_margin"], 1)

    def test_margin_zero_and_two_legal(self):
        self.assertEqual(
            rag.clean_family_select_params({"clone_fold_min_margin": 0})[
                "clone_margin"], 0)
        self.assertEqual(
            rag.clean_family_select_params({"clone_fold_min_margin": 2})[
                "clone_margin"], 2)

    def test_non_dict_cfg_tolerated(self):
        p = rag.clean_family_select_params(None)
        self.assertFalse(p["enabled"])
        self.assertEqual(p["scope"], "miit")


class FamilyKeyDerivationTest(unittest.TestCase):
    """族键检索期推导：域判定三口径+层级族剥款后缀+克隆族附录条目形。"""

    def test_is_miit_three_routes(self):
        # doc_id 三件精确为主
        self.assertTrue(rag._rec_is_miit(
            {"doc_id": "信息产业部令第36号", "corpus_type": "",
             "source_domain": ""}))
        self.assertTrue(rag._rec_is_miit(
            {"doc_id": "工信部联通信〔2023〕257号"}))
        self.assertTrue(rag._rec_is_miit(
            {"doc_id": "2025年通信业统计公报"}))
        # corpus_type=监管 辅助（真库 221 行实测取值）
        self.assertTrue(rag._rec_is_miit(
            {"doc_id": "x", "corpus_type": "监管", "source_domain": ""}))
        # source_domain=miit 辅助（大小写归一）
        self.assertTrue(rag._rec_is_miit(
            {"doc_id": "x", "corpus_type": "", "source_domain": " MIIT "}))

    def test_is_miit_negative_faces(self):
        # 3gpp 行/合成卡行/缺三字段行（1,476 行形态：doc_id=TS 前缀）一律 False
        self.assertFalse(rag._rec_is_miit(
            {"doc_id": "TS 38.133", "corpus_type": "3gpp",
             "source_domain": "3gpp"}))
        self.assertFalse(rag._rec_is_miit(
            {"doc_id": "TS 36.101", "corpus_type": "case_card",
             "chunk_type": "case_card", "source_domain": "synthetic"}))
        self.assertFalse(rag._rec_is_miit(
            {"doc_id": "TS 38.133", "corpus_type": "", "source_domain": ""}))
        self.assertFalse(rag._rec_is_miit({"doc_id": "TS 38.214"}))
        # 防御位：非 dict/空输入恒不抛出
        self.assertFalse(rag._rec_is_miit(None))
        self.assertFalse(rag._rec_is_miit("不是dict"))

    def test_miit_key_strips_sub_suffix(self):
        k = rag._family_miit_key(_rec("ad5b1d14"))
        self.assertEqual(k, ("miit", DOC36, "附录1 1.2.3 网络接通率"))
        # 父条自身=同键（父子同族）
        self.assertEqual(rag._family_miit_key(_rec("e458b795")), k)

    def test_miit_key_l2_branch_family(self):
        # 257号/统计公报分支族=L2 标签（方案 §2.2）
        k = rag._family_miit_key(_rec("e1e67ff2"))
        self.assertEqual(k, ("miit", DOC257, "主要目标 （二）"))
        self.assertEqual(rag._family_miit_key(_rec("e5348bc5")), k)
        # L1 与 L2 不同族（"主要目标"≠"主要目标 （二）"）
        self.assertNotEqual(
            rag._family_miit_key(_rec("x", doc=DOC257, loc="主要目标",
                                      ct="监管", cht="条")), k)

    def test_miit_key_non_miit_none(self):
        self.assertIsNone(rag._family_miit_key(
            _rec("g1", doc="TS 38.133", loc="Annex A.1", ct="3gpp",
                 cht="table_row_group", sd="3gpp")))
        # 缺三字段行=族推导降级 None（安全向：不入族、原样通过）
        self.assertIsNone(rag._family_miit_key(
            {"id": "m1", "doc_id": "TS 38.133", "locator": "9.2.7.3",
             "content": "x", "version": ""}))

    def test_clone_key_entry_forms(self):
        # 附录条目条块 → (clone, doc, 指标名)
        self.assertEqual(
            rag._family_clone_key(_rec("61bf4670")),
            ("clone", DOC36, "计费差错率"))
        # 跨附录同名同族
        self.assertEqual(rag._family_clone_key(_rec("a2332073"))[2],
                         "计费差错率")
        # 括注名不归一（方案 §1.3 计数口径：通话中断率（掉话率）独立）
        k = rag._family_clone_key(
            _rec("x", loc="附录2 2.2.4 通话中断率（掉话率）", cht="条"))
        self.assertEqual(k[2], "通话中断率（掉话率）")

    def test_clone_key_exclusions(self):
        # 款块不入克隆族（末段"款N"归一会并成巨族——实现级防线）
        self.assertIsNone(rag._family_clone_key(_rec("ad5b1d14")))
        self.assertIsNone(rag._family_clone_key(
            _rec("x", loc="附录8 款1", cht="款")))
        # 附录/节标题块不入（附录N、附录N X.Y 两段形）
        self.assertIsNone(rag._family_clone_key(
            _rec("x", loc="附录1", cht="条")))
        self.assertIsNone(rag._family_clone_key(
            _rec("x", loc="附录1 1.1 服务质量标准", cht="条")))
        # 257号 L2/款块不入（非附录条目形——"（一）"跨 L2 混族防线）
        self.assertIsNone(rag._family_clone_key(_rec("4820a614")))
        self.assertIsNone(rag._family_clone_key(
            _rec("x", doc=DOC257, loc="主要目标 （一）", ct="监管",
                 cht="条")))
        # 非监管域/空 locator
        self.assertIsNone(rag._family_clone_key(
            _rec("g", doc="TS 38.133", loc="Annex A.1", ct="3gpp",
                 sd="3gpp", cht="table_row_group")))
        self.assertIsNone(rag._family_clone_key(
            _rec("x", loc="", cht="条")))

    def test_dual_family_membership_exists(self):
        # 附录条目父条块=双族籍（层级族+克隆族同场，真库 1.2.2/1.2.3/1.2.7/4.2.2 型）
        r = _rec("a99a72f0")
        self.assertIsNotNone(rag._family_miit_key(r))
        self.assertIsNotNone(rag._family_clone_key(r))

    def test_family_keys_never_throw(self):
        for bad in (None, {}, "x", {"locator": 123, "doc_id": None}):
            try:
                rag._family_miit_key(bad if isinstance(bad, dict) else {})
                rag._family_clone_key(bad if isinstance(bad, dict) else {})
            except Exception as e:  # pragma: no cover
                self.fail("族键推导抛出：%r" % e)


class FamilyMemberSelectRulesTest(unittest.TestCase):
    """R1-R5 逐规则正负例（S1 真题块文样例，仿 S1 治理三件套）。"""

    # ---- R1 父条成员级让位 ----
    def test_r1_parent_dropped_when_children_present(self):
        pool = _pool([("e458b795", .85), ("e1b94d48", .83), ("ad5b1d14", .82)])
        sel, ovf, info = rag.family_member_select(pool, Q12, FAM_ON)
        self.assertNotIn("e458b795", _ids(sel))
        self.assertIn("e458b795", _ids(ovf))
        self.assertEqual(info["r1_drop"], 1)

    def test_r1_no_drop_without_children(self):
        # 父条单成员族（款块不在池）→ 族被过滤，父条原样保留
        pool = _pool([("e458b795", .85), ("c0d29a1b", .80)])
        sel, ovf, info = rag.family_member_select(pool, Q12, FAM_ON)
        self.assertEqual(_ids(sel), ["e458b795", "c0d29a1b"])
        self.assertEqual(ovf, [])
        self.assertEqual(info["r1_drop"], 0)

    def test_r1_window_semantics_deep_children_no_drop(self):
        # S1V-18 形态（差异修复 #6：R1 触发面=组装前 topk 窗口共存，乙层
        # _clause_parent_flag 语义忠实升级）：父条在窗口内但其子款深处池底
        # （窗口外）→ 不让位——池面语义会落父条致深处块提进 top3（A 级实测破线）
        pool = [_hit(1, .90, "w1", loc="附录3 3.2.2 IP网络时延 款1", cht="款",
                     content="IP网络时延款1内容"),
                _hit(2, .88, "w2", loc="附录1 1.2.1 拨号时延", cht="条",
                     content="拨号时延条内容"),
                _hit(3, .86, "w3", loc="附录9 9.9 其他指标", cht="条",
                     content="其他内容"),
                _hit(4, .84, "w4", loc="附录3 3.2.2 IP网络时延", cht="条",
                     content="IP网络时延条内容"),
                _hit(5, .82, "w5", loc="附录8 8.1 某指标", cht="条",
                     content="某指标内容"),
                _hit(6, .80, "d1", loc="附录1 1.2.1 拨号时延 款1", cht="款",
                     content="拨号时延款1"),
                _hit(7, .78, "d2", loc="附录1 1.2.1 拨号时延 款2", cht="款",
                     content="拨号时延款2")]
        # 窗口面（topk=5）：w4 子款 w1 在窗口 → 让位；w2 子款 d1/d2 窗口外 → 保留
        sel, ovf, info = rag.family_member_select(pool, "拨号时延的指标要求",
                                                  FAM_ON, topk=5)
        self.assertIn("w2", _ids(sel))
        self.assertNotIn("w4", _ids(sel))
        self.assertIn("w4", _ids(ovf))
        self.assertEqual(info["r1_drop"], 1)
        # 池面口径（topk 缺省=全池窗口，差异复核对拍面）：w2 也被让位
        sel_p, ovf_p, info_p = rag.family_member_select(
            pool, "拨号时延的指标要求", FAM_ON)
        self.assertNotIn("w2", _ids(sel_p))
        self.assertEqual(info_p["r1_drop"], 2)

    def test_r1_l1_not_parent_of_l2_branch(self):
        # "主要目标" 不是 "主要目标 （一） 款N" 的父条（L2 分支族隔离）
        pool = _pool([("e5348bc5", .85), ("4820a614", .83)])
        sel, ovf, info = rag.family_member_select(pool, Q13, FAM_ON)
        # （二）条 与 （一）款2 分属两族、各自单成员 → 零让位
        self.assertEqual(_ids(sel), ["e5348bc5", "4820a614"])
        self.assertEqual(info["r1_drop"], 0)

    # ---- R2 族内 0 负项全保留 ----
    def test_r2_zero_neg_kept_others_dropped(self):
        # S1V-12 全形态：R14 题面下款2 独 0 负项 → 独保，父/款1 溢出
        pool = _pool([("e458b795", .85), ("e1b94d48", .83), ("ad5b1d14", .82)])
        sel, ovf, info = rag.family_member_select(pool, Q12, FAM_ON)
        self.assertEqual(_ids(sel), ["ad5b1d14"])
        self.assertEqual(_ids(ovf), ["e458b795", "e1b94d48"])

    def test_r2_multi_zero_neg_all_kept(self):
        # S1V-13：（二）款3+款1 双 0 负项同保（题面含 2025+移动），款2 溢出
        pool = _pool([("e1e67ff2", .86), ("4820a614", .83), ("e5348bc5", .82),
                      ("d0bd3689", .77), ("d8e54666", .76)])
        sel, ovf, info = rag.family_member_select(pool, Q13, FAM_ON)
        self.assertIn("e1e67ff2", _ids(sel))
        self.assertIn("d0bd3689", _ids(sel))
        self.assertNotIn("d8e54666", _ids(sel))   # 款2 缺"移动"→1 负项
        self.assertNotIn("e5348bc5", _ids(sel))   # 父条 R1
        self.assertIn("4820a614", _ids(sel))      # （一）款2 单成员族保留
        self.assertEqual(info["r1_drop"], 1)

    def test_r2_no_signals_keeps_all_children(self):
        # 题面无词表信号（sigs 空）→ 全员 0 负项 → R2 全保（只 R1 让位父条）
        pool = _pool([("e458b795", .85), ("e1b94d48", .83), ("ad5b1d14", .82)])
        sel, ovf, info = rag.family_member_select(pool, "完全无关的问题文本",
                                                  FAM_ON)
        self.assertEqual(_ids(sel), ["e1b94d48", "ad5b1d14"])
        self.assertEqual(_ids(ovf), ["e458b795"])
        self.assertEqual(info["r23_drop"], 0)

    # ---- R3 保底 1 席、平局≤2 席 ----
    def test_r3_tie_two_keeps_both(self):
        # 同族两块均缺信号（各 1 负项平局、无 0 负项）→ 平局 2 席全保
        # （R3 平局不折叠——防题面信号不指向锚时族内错选把锚款挤出证据面）
        pool = [_hit(1, .83, "c1", loc="附录1 9.9.9 测试指标 款1", cht="款",
                     content="甲业务指标要求"),
                _hit(2, .82, "c2", loc="附录1 9.9.9 测试指标 款2", cht="款",
                     content="乙业务指标要求")]
        sel, ovf, info = rag.family_member_select(pool, "卫星业务的指标要求",
                                                  FAM_ON)
        self.assertEqual(_ids(sel), ["c1", "c2"])
        self.assertEqual(ovf, [])
        self.assertEqual(info["r23_drop"], 0)

    def test_r3_tie_over_two_keeps_first_two(self):
        pool = [_hit(1, .83, "c1", loc="附录1 9.9.9 测试指标 款1", cht="款",
                     content="甲业务指标要求"),
                _hit(2, .82, "c2", loc="附录1 9.9.9 测试指标 款2", cht="款",
                     content="乙业务指标要求"),
                _hit(3, .81, "c3", loc="附录1 9.9.9 测试指标 款3", cht="款",
                     content="丙业务指标要求")]
        sel, ovf, info = rag.family_member_select(pool, "卫星业务的指标要求",
                                                  FAM_ON)
        self.assertEqual(_ids(sel), ["c1", "c2"])   # 平局>2 保前 2（通道序）
        self.assertEqual(_ids(ovf), ["c3"])
        self.assertEqual(info["r23_drop"], 1)

    def test_r3_best_one_when_neg_differs(self):
        pool = [_hit(1, .83, "c1", loc="附录1 9.9.9 测试指标 款1", cht="款",
                     content="租用信道的指标要求"),      # 含"租用"→1 负项
                _hit(2, .82, "c2", loc="附录1 9.9.9 测试指标 款2", cht="款",
                     content="甲业务指标要求")]            # 缺两词→2 负项
        sel, ovf, info = rag.family_member_select(pool, "卫星租用业务",
                                                  FAM_ON)
        self.assertEqual(_ids(sel), ["c1"])   # 无 0 负项→保底 1 席=负项最少
        self.assertEqual(_ids(ovf), ["c2"])

    # ---- R4 克隆折叠仅明确时 ----
    def test_r4_fold_unique_zero_neg(self):
        # S1V-09 全形态：锚 1.2.5 独 0 负项（固定/本地/国内长途全含），
        # 四克隆 1-3 负项 → 折叠保 1，四陷阱全出
        pool = _pool([("61bf4670", .8427), ("a2332073", .7637),
                      ("f220b255", .7611), ("014f4432", .7565),
                      ("1b63777c", .7440)])
        sel, ovf, info = rag.family_member_select(pool, Q09, FAM_ON)
        self.assertEqual(_ids(sel), ["61bf4670"])
        self.assertEqual(len(ovf), 4)
        self.assertEqual(info["r4_fold"], 4)

    def test_r4_no_fold_tie_zero_neg(self):
        # 双 0 负项平局 → 不折叠（B12 canary 硬规则面）
        pool = [_hit(1, .84, "61bf4670"),
                _hit(2, .76, "a2332073"),
                _hit(3, .75, "x3", doc=DOC36, loc="附录5 5.3.1 计费差错率",
                     cht="条", content="固定网本地及国内长途电话业务的计费差错率补充")]
        # x3 与锚同含全部信号 → 双 0 负项
        sel, ovf, info = rag.family_member_select(pool, Q09, FAM_ON)
        self.assertIn("61bf4670", _ids(sel))
        self.assertIn("x3", _ids(sel))
        self.assertEqual(info["r4_fold"], 0)

    def test_r4_no_fold_without_zero_neg(self):
        # 全负项（无 0 负项成员）→ 克隆族不折叠（R4 只认唯一 0 负项）
        pool = _pool([("a2332073", .76), ("1b63777c", .75), ("014f4432", .74)])
        sel, ovf, info = rag.family_member_select(pool, "卫星业务的计费差错率",
                                                  FAM_ON)
        self.assertEqual(len(sel), 3)
        self.assertEqual(info["r4_fold"], 0)

    def test_r4_b12_canary_pattern_survives(self):
        # B12 题面：真库实测 2.1.2 块文含"数字蜂窝移动通信业务"全称=唯一 0 负项
        # → 折叠保 2.1.2（方案 §六Q3 预置分支二：折叠保留的正是移动域块，
        # B12 锚 pattern 2\.1\.2|计费差错率 仍命中）
        pool = _pool([("61bf4670", .84), ("a2332073", .76), ("f220b255", .75),
                      ("014f4432", .74), ("1b63777c", .73)])
        sel, ovf, info = rag.family_member_select(pool, QB12, FAM_ON)
        self.assertIn("a2332073", _ids(sel))
        import re as _re
        self.assertTrue(_re.search(r"2\.1\.2|计费差错率",
                                   sel[0]["rec"]["locator"] +
                                   sel[0]["rec"]["content"]))

    def test_r4_margin_two_stricter(self):
        # 唯一 0 负项但次优仅差 1 → margin=2 不折叠、margin=1 折叠
        pool = [_hit(1, .84, "61bf4670"),                       # 0 负项
                _hit(2, .76, "x2", doc=DOC36,
                     loc="附录5 5.3.1 计费差错率", cht="条",
                     content="本地及国内长途电话业务的计费差错率x")]  # 缺"固定"=1 负项
        fam_m2 = dict(FAM_ON, clone_margin=2)
        sel2, _, info2 = rag.family_member_select(pool, Q09, fam_m2)
        self.assertEqual(len(sel2), 2)       # 差 1 < 2 → 不折叠
        self.assertEqual(info2["r4_fold"], 0)
        sel1, _, info1 = rag.family_member_select(pool, Q09, FAM_ON)
        self.assertEqual(_ids(sel1), ["61bf4670"])   # 差 1 ≥ 1 → 折叠
        self.assertEqual(info1["r4_fold"], 1)

    def test_r4_margin_zero_equiv_one(self):
        # margin=0：折叠前提仍是唯一 0 负项（平局绝不折叠）；次优负项恒≥1 →
        # 差值门槛 0/1 行为等价（注释语义锁）
        pool = _pool([("61bf4670", .84), ("a2332073", .76), ("f220b255", .75)])
        fam0 = dict(FAM_ON, clone_margin=0)
        sel0, _, i0 = rag.family_member_select(pool, Q09, fam0)
        sel1, _, i1 = rag.family_member_select(pool, Q09, FAM_ON)
        self.assertEqual(_ids(sel0), _ids(sel1))
        self.assertEqual(i0["r4_fold"], i1["r4_fold"])
        # 平局下 margin=0 也不折叠
        pool_tie = [_hit(1, .84, "61bf4670"),
                    _hit(2, .76, "x3", doc=DOC36,
                         loc="附录5 5.3.1 计费差错率", cht="条",
                         content="固定网本地及国内长途电话业务的计费差错率补充")]
        sel, _, info = rag.family_member_select(pool_tie, Q09, fam0)
        self.assertEqual(len(sel), 2)
        self.assertEqual(info["r4_fold"], 0)

    def test_r4_scope_miit_no_clone_family(self):
        # scope=miit：克隆族不推导 → S1V-09 五连坐原样通过（各块单成员层级族）
        pool = _pool([("61bf4670", .8427), ("a2332073", .7637),
                      ("f220b255", .7611), ("014f4432", .7565),
                      ("1b63777c", .7440)])
        sel, ovf, info = rag.family_member_select(pool, Q09, FAM_MIIT)
        self.assertEqual(len(sel), 5)
        self.assertEqual(ovf, [])
        self.assertEqual(info["r4_fold"], 0)

    # ---- R5 分数载体不动 ----
    def test_r5_scores_untouched_ranks_renumbered(self):
        pool = _pool([("e458b795", .8477), ("e1b94d48", .8276),
                      ("ad5b1d14", .8257)])
        before = {h["rec"]["id"]: h["score"] for h in pool}
        sel, ovf, info = rag.family_member_select(pool, Q12, FAM_ON)
        for h in sel + ovf:
            self.assertEqual(h["score"], before[h["rec"]["id"]])
            self.assertNotIn("cosine", h)
        self.assertEqual([h["rank"] for h in sel], list(range(1, len(sel) + 1)))
        self.assertEqual([h["rank"] for h in ovf], list(range(1, len(ovf) + 1)))

    def test_r5_input_not_mutated(self):
        pool = _pool([("e458b795", .8477), ("e1b94d48", .8276),
                      ("ad5b1d14", .8257)])
        snapshot = json.dumps(pool, ensure_ascii=False, sort_keys=True,
                              default=str)
        rag.family_member_select(pool, Q12, FAM_ON)
        self.assertEqual(
            snapshot, json.dumps(pool, ensure_ascii=False, sort_keys=True,
                                 default=str))
        self.assertEqual([h["rank"] for h in pool], [1, 2, 3])

    # ---- S1 真题形态（方案静态推演表逐题对照）----
    def test_s1v11_shape(self):
        pool = _pool([("c0d29a1b", .9099), ("87e01bde", .8719),
                      ("ae8c7373", .8287)])
        sel, ovf, info = rag.family_member_select(pool, Q11, FAM_ON)
        self.assertEqual(_ids(sel), ["c0d29a1b"])      # 款2 独保（去豁免加固）
        self.assertEqual(_ids(ovf), ["87e01bde", "ae8c7373"])

    def test_s1v15_shape(self):
        pool = _pool([("bd30e67a", .7853), ("d41d47fb", .7776)])
        sel, ovf, info = rag.family_member_select(pool, Q15, FAM_ON)
        self.assertEqual(_ids(sel), ["d41d47fb"])      # 父条成员级出集
        self.assertEqual(_ids(ovf), ["bd30e67a"])

    # ---- 关态/空态/域外 ----
    def test_disabled_passthrough_identity(self):
        pool = _pool([("e458b795", .85), ("ad5b1d14", .82)])
        sel, ovf, info = rag.family_member_select(pool, Q12, FAM_OFF)
        self.assertIs(sel, pool)          # 原对象直通（零拷贝零扰动）
        self.assertEqual(ovf, [])
        self.assertEqual(info["families"], 0)

    def test_none_cfg_passthrough(self):
        pool = _pool([("e458b795", .85)])
        sel, ovf, _ = rag.family_member_select(pool, Q12, None)
        self.assertIs(sel, pool)

    def test_empty_hits(self):
        sel, ovf, info = rag.family_member_select([], Q12, FAM_ON)
        self.assertEqual(sel, [])
        self.assertEqual(ovf, [])

    def test_3gpp_and_missing_field_rows_untouched(self):
        # 3GPP 行与缺三字段行（1,476 行形态）不入任何族=原样通过（降级安全向）
        pool = [_hit(1, .9, "g1", doc="TS 38.133", loc="Annex A.1",
                     ct="3gpp", sd="3gpp", cht="table_row_group",
                     content="table row"),
                _hit(2, .8, "m1", doc="TS 38.133", loc="9.2.7.3",
                     ct=None, sd=None, cht=None, content="缺字段行"),
                _hit(3, .7, "cc", doc="TS 36.101", loc="4.2.1",
                     ct="case_card", sd="synthetic", cht="case_card",
                     content="合成卡")]
        sel, ovf, info = rag.family_member_select(pool, "5G NR 参数", FAM_ON)
        self.assertEqual(_ids(sel), ["g1", "m1", "cc"])
        self.assertEqual(ovf, [])
        self.assertEqual(info["families"], 0)

    def test_dual_family_deterministic_across_pool_orders(self):
        # 双族籍块（附录条目父条 1.2.2 + 克隆兄弟 2.2.2）：两种池序结果一致
        # ——层级族先于克隆族处理（R1 先让位父条，R4 只见活跃面）
        base = [("a99a72f0", .85), ("3cd734b9", .80), ("7aeb544f", .78)]
        alt = [("3cd734b9", .85), ("a99a72f0", .80), ("7aeb544f", .78)]
        s1, o1, _ = rag.family_member_select(_pool(base), Q12, FAM_ON)
        s2, o2, _ = rag.family_member_select(_pool(alt), Q12, FAM_ON)
        self.assertEqual(sorted(_ids(s1)), sorted(_ids(s2)))
        # 两序下 1.2.2 父条均 R1 让位、2.2.2 克隆兄弟存活（不被 R4 误折）
        self.assertNotIn("a99a72f0", _ids(s1))
        self.assertIn("3cd734b9", _ids(s1))
        self.assertNotIn("a99a72f0", _ids(s2))
        self.assertIn("3cd734b9", _ids(s2))

    def test_words_core_mode(self):
        # words=core：指标词不入 sigs——Q11 含"移动"（core 主体词）行为不变；
        # 构造仅指标词区分的形态：拨号（metric 档）在 core 下不计负项
        fam_core = dict(FAM_ON, words="core")
        pool = [_hit(1, .83, "c1", loc="附录1 9.9.9 测试指标 款1", cht="款",
                     content="甲业务"),
                _hit(2, .82, "c2", loc="附录1 9.9.9 测试指标 款2", cht="款",
                     content="拨号相关乙业务")]
        # 题面含"拨号"：full 档 c1 缺拨号=1 负项/c2=0 负项 → R2 独保 c2；
        # core 档 sigs 空 → 双 0 负项全保
        sel_f, _, _ = rag.family_member_select(pool, "拨号时延指标", FAM_ON)
        sel_c, _, _ = rag.family_member_select(pool, "拨号时延指标", fam_core)
        self.assertEqual(_ids(sel_f), ["c2"])
        self.assertEqual(_ids(sel_c), ["c1", "c2"])


# —— 服务级夹具库：12 块 8 维（cos(q)=1/sqrt(1+e²)，e 见注）——
SVC_FIXTURE = [
    # (id, doc, locator, chunk_type, corpus_type, source_domain, e, content)
    ("s0", DOC36, "附录1 1.2.3 网络接通率", "条", "监管", "miit", 0.00,
     REAL["e458b795"][3]),
    ("s1", DOC36, "附录1 1.2.3 网络接通率 款1", "款", "监管", "miit", 0.05,
     REAL["e1b94d48"][3]),
    ("s2", DOC36, "附录1 1.2.3 网络接通率 款2", "款", "监管", "miit", 0.10,
     REAL["ad5b1d14"][3]),
    ("k1", DOC36, "附录1 1.2.5 计费差错率", "条", "监管", "miit", 0.15,
     REAL["61bf4670"][3]),
    ("k2", DOC36, "附录2 2.1.2 计费差错率", "条", "监管", "miit", 0.20,
     REAL["a2332073"][3]),
    ("k3", DOC36, "附录3 3.2.4 计费差错率", "条", "监管", "miit", 0.25,
     REAL["1b63777c"][3]),
    ("k4", DOC36, "附录4 4.2.3 计费差错率", "条", "监管", "miit", 0.30,
     REAL["014f4432"][3]),
    ("g1", "TS 38.133", "Annex A.1", "table_row_group", "3gpp", "3gpp", 0.35,
     "table row g1"),
    ("g2", "TS 38.213", "12 (p1)", "clause", "3gpp", "3gpp", 0.40, "clause g2"),
    ("g3", "TR 36.805", "6.1.1", "clause", "3gpp", "3gpp", 0.45, "case g3"),
    ("m1", "TS 38.133", "9.2.7.3", None, None, None, 0.50, "缺三字段行 m1"),
    ("m2", "TS 38.214", "5.1.1", None, None, None, 0.55, "缺三字段行 m2"),
]
SVC_QUERY = [1, 0, 0, 0, 0, 0, 0, 0]
SVC_OFF_TOP5 = ["s0", "s1", "s2", "k1", "k2"]
# famsel 开（scope=miit+clone，题面 Q12 sigs=[国内长途]）：
#   1.2.3 族：R1 落 s0、R2 独保 s2（s1 溢出）；计费差错率克隆族：k1 独 0 负项
#   → R4 折 k2/k3/k4 → selected=[s2,k1,g1,g2,g3,...]
SVC_ON_TOP5 = ["s2", "k1", "g1", "g2", "g3"]


def _write_svc_store(path):
    with open(path, "w", encoding="utf-8") as f:
        for rid, doc, loc, cht, ct, sd, e, content in SVC_FIXTURE:
            vec = [1.0] + [0.0] * 7
            vec[1] = e
            row = {"id": rid, "content": content, "doc_id": doc,
                   "version": "", "locator": loc, "embedding": vec}
            if ct is not None:
                row["corpus_type"] = ct
                row["chunk_type"] = cht
                row["source_domain"] = sd
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


class _Log:
    def __init__(self):
        self.lines = []

    def __call__(self, line):
        self.lines.append(line)


class MetaFieldsLoadTest(unittest.TestCase):
    """META_FIELDS 八字段装载+缺三字段行容错+sidecar v2 往返/v1 拒载。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = os.path.join(self.tmp.name, "store.jsonl")
        _write_svc_store(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def test_meta_fields_eight_locked(self):
        self.assertEqual(
            rag.META_FIELDS,
            ("id", "content", "doc_id", "version", "locator",
             "corpus_type", "chunk_type", "source_domain"))

    def test_load_all_rows_missing_fields_tolerated(self):
        recs, dim, stats = rag.load_store(self.store, use_sidecar=False)
        # 缺三字段行（m1/m2，现库 1,476 行形态）不判坏行、不崩、缺字段→""
        self.assertEqual(stats["loaded"], len(SVC_FIXTURE))
        self.assertEqual(stats["bad_lines"], 0)
        by_id = {r["id"]: r for r in recs}
        self.assertEqual(set(by_id["m1"].keys()) - {"vec"},
                         set(rag.META_FIELDS))
        self.assertEqual(by_id["m1"]["corpus_type"], "")
        self.assertEqual(by_id["m1"]["chunk_type"], "")
        self.assertEqual(by_id["m1"]["source_domain"], "")
        self.assertEqual(by_id["s0"]["corpus_type"], "监管")
        self.assertEqual(by_id["s0"]["source_domain"], "miit")

    def test_non_string_field_values_coerced_empty(self):
        with open(self.store, "a", encoding="utf-8") as f:
            f.write(json.dumps({"id": "n1", "content": "x", "doc_id": 123,
                                "locator": None, "corpus_type": 5,
                                "embedding": [1.0] + [0.0] * 7}) + "\n")
        recs, _, stats = rag.load_store(self.store, use_sidecar=False)
        by_id = {r["id"]: r for r in recs}
        self.assertEqual(by_id["n1"]["doc_id"], "")
        self.assertEqual(by_id["n1"]["locator"], "")
        self.assertEqual(by_id["n1"]["corpus_type"], "")

    def test_sidecar_v2_roundtrip(self):
        recs_j, dim_j, stats_j = rag.load_store(self.store, use_sidecar=False)
        bp, mp = rag.build_sidecar(recs_j, dim_j, self.store, stats=stats_j)
        with open(mp, encoding="utf-8") as f:
            meta = json.load(f)
        self.assertEqual(meta["version"], 2)
        self.assertEqual(meta["fields"], list(rag.META_FIELDS))
        recs_s, dim_s, stats_s = rag.load_store(self.store)
        self.assertTrue(stats_s["sidecar"])
        self.assertEqual(dim_s, dim_j)
        self.assertEqual(len(recs_s), len(recs_j))
        for a, b in zip(recs_s, recs_j):
            self.assertEqual({k: a[k] for k in rag.META_FIELDS},
                             {k: b[k] for k in rag.META_FIELDS})
            self.assertEqual(list(a["vec"]), list(b["vec"]))

    def test_sidecar_v1_rejected_falls_back(self):
        # 云端旧 v1 五字段 sidecar 在位 → version 校验拒载、自动退 jsonl 路径
        recs_j, dim_j, stats_j = rag.load_store(self.store, use_sidecar=False)
        rag.build_sidecar(recs_j, dim_j, self.store, stats=stats_j)
        bp, mp = rag.sidecar_paths(self.store)
        with open(mp, encoding="utf-8") as f:
            meta = json.load(f)
        meta["version"] = 1
        meta["fields"] = list(rag.META_FIELDS[:5])
        meta["rows"] = [row[:5] for row in meta["rows"]]
        with open(mp, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)
        recs, _, stats = rag.load_store(self.store)
        self.assertFalse(stats.get("sidecar"))
        self.assertEqual(len(recs), len(recs_j))
        self.assertEqual({k: recs[0][k] for k in rag.META_FIELDS},
                         {k: recs_j[0][k] for k in rag.META_FIELDS})


class ServiceAssembleTest(unittest.TestCase):
    """服务级：关态逐位等价旧路径；开态组装序/回补/日志/mq 不选席。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "store.jsonl")
        _write_svc_store(self.path)
        self.log = _Log()

    def tearDown(self):
        self.tmp.cleanup()

    def _service(self, **cfg):
        cfg.setdefault("store_path", self.path)
        cfg.setdefault("topk", 5)
        svc = rag.RagService(embed_fn=lambda q: list(SVC_QUERY), log=self.log)
        svc.initialize(cfg)
        return svc

    def _ids(self, svc, q=Q12):
        return [h["rec"]["id"] for h in svc._search_one(q, list(SVC_QUERY))]

    def test_off_state_unchanged(self):
        svc = self._service()
        self.assertFalse(svc._decrowd_on())     # famsel 关+P0 关 → 深池不开
        self.assertEqual(self._ids(svc), SVC_OFF_TOP5)
        svc2 = self._service(family_select_enabled=False,
                             family_select_scope="miit+clone",
                             clone_fold_min_margin=0)
        self.assertEqual(self._ids(svc2), SVC_OFF_TOP5)

    def test_off_state_bitwise_equals_old_path(self):
        # P0 键开+famsel 关：_decrowd_assemble 输出与 P0 时代纯函数组装逐位一致
        svc = self._service(table_downweight_enabled=True,
                            table_downweight_factor=0.85,
                            decrowd_candidates=20,
                            family_select_enabled=False)
        hits = svc._search_one(Q12, list(SVC_QUERY))
        raw = rag.search(list(SVC_QUERY), svc._recs, 20)
        rescored, _ = rag.decrowd_rescore(Q12, raw, svc._decrowd)
        expected = rescored[:5]
        self.assertEqual([h["rec"]["id"] for h in hits],
                         [h["rec"]["id"] for h in expected])
        for a, b in zip(hits, expected):
            self.assertEqual(a["score"], b["score"])
            self.assertEqual(a["rank"], b["rank"])
        # famsel=off 打点形态
        dec = [ln for ln in self.log.lines if "[rag-decrowd]" in ln]
        self.assertTrue(dec and "famsel=off" in dec[0])
        self.assertFalse(any("[rag-famsel]" in ln for ln in self.log.lines))

    def test_on_state_selection(self):
        svc = self._service(family_select_enabled=True,
                            family_select_scope="miit+clone",
                            decrowd_candidates=20)
        self.assertTrue(svc._decrowd_on())      # famsel 开 → 深候选池生效
        self.assertEqual(self._ids(svc), SVC_ON_TOP5)
        fam = [ln for ln in self.log.lines if "[rag-famsel]" in ln]
        self.assertEqual(len(fam), 1)
        self.assertIn("r1_drop=1", fam[0])
        self.assertIn("r4_fold=3", fam[0])
        self.assertNotIn(Q12, fam[0])           # 打点不含题面（纪律断言）
        dec = [ln for ln in self.log.lines if "[rag-decrowd]" in ln]
        self.assertTrue(dec and "famsel=on:1/3" in dec[0])

    def test_on_state_scores_are_raw_cosine(self):
        # R5 服务级：选席只改成员，score 载体不动（gate_cosine 零侵蚀面）
        svc = self._service(family_select_enabled=True,
                            family_select_scope="miit+clone",
                            decrowd_candidates=20)
        hits = svc._search_one(Q12, list(SVC_QUERY))
        by_e = {rid: 1.0 / math.sqrt(1.0 + e * e)
                for rid, _, _, _, _, _, e, _ in SVC_FIXTURE}
        for h in hits:
            self.assertAlmostEqual(h["score"], by_e[h["rec"]["id"]], places=6)

    def test_overflow_backfill_keeps_evidence_full(self):
        # 池深=5（无富余）：族选席落 3 块后 base 仅 2 → overflow 按序回满
        # （方案 R1 回补语义：证据面绝不因选席缩水）
        svc = self._service(family_select_enabled=True,
                            family_select_scope="miit+clone",
                            decrowd_candidates=5)
        hits = svc._search_one(Q12, list(SVC_QUERY))
        self.assertEqual(len(hits), 5)
        self.assertEqual([h["rec"]["id"] for h in hits],
                         ["s2", "k1", "s0", "s1", "k2"])
        self.assertEqual([h["rank"] for h in hits], [1, 2, 3, 4, 5])

    def test_famsel_with_quota_overflow_in_pool(self):
        # famsel+配额同开：overflow 并入配额池（组装序=族选席→①配额）
        svc = self._service(family_select_enabled=True,
                            family_select_scope="miit+clone",
                            doc_quota_enabled=True, doc_quota_max=2,
                            decrowd_candidates=20)
        # base=[s2,k1,g1,g2,g3,m1...]：36号 2 席已满 → g1/g2/g3 依次入
        self.assertEqual(self._ids(svc), ["s2", "k1", "g1", "g2", "g3"])

    def test_mq_depth_path_no_selection(self):
        # truncate=False（mq 深度路径）：族选席/配额不生效，只重打分截回 keep
        svc = self._service(family_select_enabled=True,
                            family_select_scope="miit+clone",
                            decrowd_candidates=20)
        raw = rag.search(list(SVC_QUERY), svc._recs, 8)
        out = svc._decrowd_assemble(Q12, raw, 5, truncate=False, keep=8)
        self.assertEqual([h["rec"]["id"] for h in out],
                         [h["rec"]["id"] for h in raw])
        self.assertFalse(any("[rag-famsel]" in ln for ln in self.log.lines))

    def test_famsel_only_scope_miit_service(self):
        # scope=miit：只层级族——s0/s1 让位、克隆 k2-k4 不折叠（对照
        # test_on_state_selection 的 miit+clone 全量档）
        svc = self._service(family_select_enabled=True,
                            family_select_scope="miit",
                            decrowd_candidates=20)
        self.assertEqual(self._ids(svc), ["s2", "k1", "k2", "k3", "k4"])


if __name__ == "__main__":
    unittest.main()
