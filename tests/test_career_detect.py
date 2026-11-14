# -*- coding: utf-8 -*-
"""career_detect 毕业季探测器单测（F线 CD2-2，2026-10-14；零网络零计费零真实题面）。

样例纪律：全部合成（形态取自运营/F线/C线-探测器校准报告-20261014.md 归因面
——TP 支路分布〔面试/简历/JD 解读/岗位职责/岗位名词残片〕与 vC1.0 十二例
FP 形态〔职称+技术问句〕、§三漏报归因面〔上下文残片〕），绝不复制生产真实
用户问句；断言面只看 bool/支路名/字段值。

覆盖面：
- 六支路正例（合成形态）与归因面反例（优化意图/技术术语/外场活动/
  vC1.0 职称+技术问句 FP 形态/上下文残片 FN 面——后者如实登记为预期 False）；
- is_career_question fail-open（畸形输入不抛出恒 False）；
- 开关三态（resolve_mode）：缺键/坏值=off（默认关）、on、大小写清洗；
- [chat] 行字段断言（/api/chat 集成，伪 httpx 上游超时收尾）：
  on+职业问=career=hit、on+技术问=career=-、缺键（默认 off）=[chat] 行
  无 career= 字段（与既往逐字节一致）；标注零原文零掩码。
"""
import contextlib
import io
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import career_detect
import server  # 仓根模块（tests/__init__.py 已做 sys.path 引导）
from tests import clean_store_tests
from tests.test_server_rag import _FakeAsyncClient, _auth_ok_cfg

# ---- 合成正例（六支路各一，形态对齐校准报告 §一 TP 支路分布） ----
POSITIVE_CASES = {
    "面试": "无线网优岗位面试一般会问到哪些内容",
    "简历": "帮我修改通顺一下简历里的工作经历这一段",
    "JD解读": "这个岗位具体是做什么的",
    "岗位职责": "网优工程师的工作内容有哪些",
    "岗位名词残片": "LTE后台分析工程师",
    # 兜底支路可达形态：多行+联系方式但无 S2 简历词（否则被简历支路优先截走）
    "简历粘贴兜底": "电话 13800138000\n邮箱 someone@example.com\n方向 无线网络优化",
}

# ---- 合成反例（形态对齐校准报告 §二排除面 + §三 vC1.0 FP 归因 + FN 残片面） ----
NEGATIVE_CASES = {
    # vC1.0 十二例 FP 形态（职称+技术问句；vC1.1 收紧后须为负——修复范式回归面）
    "vC1.0FP_职称加技术问句": "网优工程师，处理弱覆盖有哪些手段",
    "vC1.0FP_KPI日常优化": "后台网优工程师，KPI日常优化",
    # 优化/处置意图排除（EXC_OPTIMIZE）
    "优化意图": "切换参数该怎么优化才能降低掉话率",
    # 技术术语（EXC_TECH_TERM，JD 支路排除）
    "技术术语": "SSB波束权值这是什么意思",
    # 外场活动词（EXC_ACTIVITY，职责支路排除）
    "外场活动": "做路测的时候CQT点位怎么安排",
    # 纯技术实操问（无任何职业向信号）
    "纯技术问": "a3-Offset参数取值范围是多少",
    # 上下文残片面（校准报告 §三：单条问面零信号词，探测器原理上不可达——
    # 如实登记为预期 False，观察面低估 ~4% 的已知界）
    "上下文残片_FN已知界": "覆盖加接通加掉线",
}


class DetectCareerTest(unittest.TestCase):
    """detect_career/is_career_question 支路判定（合成正反例）。"""

    def test_positive_branches(self):
        for expect_branch, text in POSITIVE_CASES.items():
            hit, branch, detail = career_detect.detect_career(text)
            self.assertTrue(hit, msg=f"正例未命中：{expect_branch}")
            self.assertEqual(branch, expect_branch,
                             msg=f"支路不符：期望 {expect_branch} 实得 {branch}")
            self.assertTrue(career_detect.is_career_question(text))

    def test_negative_cases(self):
        for name, text in NEGATIVE_CASES.items():
            hit, branch, _ = career_detect.detect_career(text)
            self.assertFalse(hit, msg=f"反例误命中：{name}（支路={branch}）")
            self.assertFalse(career_detect.is_career_question(text))

    def test_detail_keys_zero_rawtext(self):
        _hit, _branch, detail = career_detect.detect_career(
            "网优工程师的日常工作内容有哪些")
        self.assertEqual(sorted(detail), ["contact", "duty", "exc_act", "exc_opt",
                                          "exc_term", "interview", "jd",
                                          "multi_line", "resume", "title"])
        self.assertTrue(all(isinstance(v, bool) for v in detail.values()))
        self.assertTrue(detail["duty"])

    def test_version_parity_with_calibration(self):
        # 版本化纪律：在线模块与校准脚本终版 vC1.2 同源（血统一致性锚）
        self.assertIn("vC1.2", career_detect.DETECTOR_VERSION)
        # 词表体量守恒（防误删词条的退化守卫；精确值=校准脚本逐常量复制——
        # EXC_OPTIMIZE 实为 25 词条，校准报告 §二"23 式"系名义表述）
        self.assertEqual(len(career_detect.SIG_INTERVIEW), 8)
        self.assertEqual(len(career_detect.SIG_RESUME), 28)
        self.assertEqual(len(career_detect.SIG_DUTY), 21)
        self.assertEqual(len(career_detect.SIG_JD), 5)
        self.assertEqual(len(career_detect.EXC_OPTIMIZE), 25)

    def test_fail_open_on_garbage(self):
        for bad in (None, 123, "", object()):
            self.assertFalse(career_detect.is_career_question(bad))
            self.assertEqual(career_detect.career_branch(bad), "-")


class ModeResolveTest(unittest.TestCase):
    """开关二态清洗：缺键/坏值=off（默认关，启用归决策禁自动生效）。"""

    def test_default_off(self):
        self.assertEqual(career_detect.DEFAULT_MODE, "off")
        self.assertEqual(career_detect.resolve_mode({}), "off")

    def test_on_and_casefold(self):
        self.assertEqual(
            career_detect.resolve_mode({career_detect.CONFIG_KEY: "on"}), "on")
        self.assertEqual(
            career_detect.resolve_mode({career_detect.CONFIG_KEY: " ON "}), "on")

    def test_bad_values_fall_back_off(self):
        for v in ("", "unknown", "log_only", 1, None):
            self.assertEqual(
                career_detect.resolve_mode({career_detect.CONFIG_KEY: v}), "off",
                msg=f"坏值未回 off：{v!r}")


@clean_store_tests
class ChatEndpointCareerFieldTest(unittest.TestCase):
    """/api/chat 挂载集成（伪 httpx 上游超时收尾，零网络零计费）：
    [chat] 行 career= 字段三态断言。"""

    def _post(self, content, cfg_extra=None):
        body = {"messages": [{"role": "user", "content": content}],
                "passcode": "pw-test"}
        cfg = _auth_ok_cfg()
        cfg.update(cfg_extra or {})
        out = io.StringIO()
        with mock.patch.object(server.httpx, "AsyncClient", _FakeAsyncClient), \
                mock.patch.object(server, "API_KEY", "stub-key"), \
                mock.patch.object(server, "CONFIG", cfg), \
                contextlib.redirect_stdout(out):
            with TestClient(server.app) as client:
                resp = client.post("/api/chat", json=body)
                self.assertEqual(resp.status_code, 200)
        return [ln for ln in out.getvalue().splitlines() if ln.startswith("[chat] ")]

    def test_on_career_question_hit(self):
        lines = self._post("网优工程师的工作内容有哪些",
                           {career_detect.CONFIG_KEY: "on"})
        self.assertEqual(len(lines), 1)
        self.assertIn("career=hit", lines[0])
        # 尾附安全位：career= 在 dev=/ua= 之后（KV 尾部追加形态）
        self.assertGreater(lines[0].rindex("career=hit"),
                           lines[0].rindex("ua="))

    def test_on_tech_question_miss(self):
        lines = self._post("a3-Offset参数取值范围是多少",
                           {career_detect.CONFIG_KEY: "on"})
        self.assertEqual(len(lines), 1)
        self.assertIn("career=-", lines[0])
        self.assertNotIn("career=hit", lines[0])

    def test_off_no_field_bytes_identical_form(self):
        # 缺键（默认 off）：[chat] 行无 career= 字段——与挂载前形态一致
        lines = self._post("网优工程师的工作内容有哪些")
        self.assertEqual(len(lines), 1)
        self.assertNotIn("career=", lines[0])
        # 显式 off 同形态
        lines2 = self._post("网优工程师的工作内容有哪些",
                            {career_detect.CONFIG_KEY: "off"})
        self.assertNotIn("career=", lines2[0])

    def test_annotation_zero_rawtext(self):
        # 标注纪律：career= 字段值恒为 hit|-（零原文零掩码纯标注）
        lines = self._post("网优工程师的工作内容有哪些",
                           {career_detect.CONFIG_KEY: "on"})
        self.assertRegex(lines[0], r"career=(hit|-)\b")


if __name__ == "__main__":
    unittest.main()
