# -*- coding: utf-8 -*-
"""pii_mask 输入侧止血单测（F线C-20261014 C2；零网络零计费零真实 PII）。

样例纪律：全部合成（手机号=138 假段、邮箱=example.com、身份证=110105 假段
合规形态、地址=合成门牌），绝不使用生产真值；断言面只看占位符/计数/标记，
不复制任何真实文本。

覆盖面（对应运营/F线/C线-止血实现与测试-20261014.md §三）：
- 四类字段各正反例（detect/mask_text）：正例须命中、反例（时间戳/浮点/17 位
  串/无 TLD 邮箱/纯行政区名/更长相邻数字串）须不命中；
- 简历结构特征正反例：多行短句+联系方式共现 → resume_like=1；单行职业问句/
  长段落/无联系方式多行 → 0；
- 开关三态（apply_to_messages + resolve_mode）：off 零日志零改动、log_only
  打行不改文、mask 掩码不改任务上下文（不截断全文）；
- 端点挂载（chat 集成，伪 httpx 上游超时收尾）：log_only/mask 两态下
  [pii_mask] 行格式、mask 态会话库落的是掩码后文本、mask 态日志不含原字段值；
- fail-open：mask_text/apply_to_messages 传畸形输入不抛出原样返回。
- v1.1 扩测（代码评审立改批 X2）：分隔形态电话/身份证（+86/连字符/空格/
  句点尾——整段含分隔符替换）、直辖市详细地址正例与纯区划名反例（P1/P2）、
  fail-open 异常路径的限频 err 遥测行（P5）。
- v1.2 扩测（消零收尾批 Y2）：EMAIL_RE 回溯上界对抗时限用例（P9——
  24k 不间断数字/点/加号跑限时+行为正确）、身份证截断残段反例组
  （T04——10-17 位残段不命中的现行口径固化，防正则层无版本化放宽）。
"""
import contextlib
import io
import re
import time
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import pii_mask
import server  # 仓根模块（tests/__init__.py 已做 sys.path 引导）
from tests import clean_store_tests
from tests.test_server_rag import _FakeAsyncClient, _auth_ok_cfg

# ---- 合成样例（非真实值） ----
P_PHONE = "13800138000"                 # 合成手机号（138 假段）
P_EMAIL = "someone@example.com"
N_TS = "20261014095432199"              # 17 位时间戳形态数字串
N_FLOAT = "0.13800138001"               # 浮点小数段（防向量/进度数字误配）
N_LONG = "861380013800012345"           # 更长相邻数字串
N_EMAIL = "abc@def"                     # 无 TLD 邮箱形态
P_IDCARD = "11010519491231002X"         # 合规形态合成身份证（年月段合法）
N_IDCARD17 = "11010519491231002"        # 17 位（缺校验位）
N_IDCARD_BADMONTH = "11010519491331002X"  # 月段 13 非法
P_ADDR = "河北省石家庄市长安区中山东路123号"
P_ADDR_FULL = "河北省石家庄市长安区中山东路123号3栋2单元501室"
N_ADDR_CITY_ONLY = "北京市"

# ---- v1.1 扩测样例（评审立改批 X2：P1 直辖市/P2 分隔形态；同为合成值） ----
P_PHONE_SP = "138 1234 5678"              # 空格分段（138 假段）
P_PHONE_HYP = "138-1234-5678"             # 连字符分段
P_PHONE_86 = "+8613812345678"             # +86 前缀
P_PHONE_86SP = "+86 138-1234-5678"        # +86 前缀+分段
P_IDCARD_SEG = "110105 1949 1231 002X"    # P_IDCARD 的 6-4-4-4 分段形态
P_IDCARD_SEG_H = "110105-1949-1231-002X"  # 连字符分段
P_ADDR_MUN = "北京市朝阳区中山东路123号"
P_ADDR_MUN_FULL = "上海市浦东新区世纪大道100号2栋3室"
N_ADDR_MUN_DISTRICT = "北京市朝阳区"       # 无路名门牌——非详细地址
N_PHONE_86_SHORT = "+86 138 1234 567"     # 尾段缺一位的分段形态
N_PHONE_SEP_TS = "2026 1014 0954"         # 分段时间戳形态（无 1[3-9] 段头）

LOG_LINE_RE = re.compile(
    r"^\[pii_mask\] mode=(log_only|mask) trace=([0-9a-f]{8}|-) "
    r"phone=(\d+) email=(\d+) idcard=(\d+) addr=(\d+) resume=[01] len=\d+$")


class FieldDetectTest(unittest.TestCase):
    """四类字段正反例（detect 纯函数）。"""

    def test_phone_positive(self):
        self.assertEqual(pii_mask.detect(f"电话{P_PHONE}联系")["phone"], 1)

    def test_phone_negatives(self):
        for t in (N_TS, N_FLOAT, N_LONG, P_PHONE[:10], "0" + P_PHONE):
            self.assertEqual(pii_mask.detect(t)["phone"], 0,
                             msg=f"反例误命中（形态长度 {len(t)}）")

    def test_email_positive(self):
        self.assertEqual(pii_mask.detect(f"邮箱 {P_EMAIL} 谢谢")["email"], 1)

    def test_email_negative(self):
        self.assertEqual(pii_mask.detect(N_EMAIL)["email"], 0)

    def test_idcard_positive(self):
        self.assertEqual(pii_mask.detect(f"证件号{P_IDCARD}。")["idcard"], 1)

    def test_idcard_negatives(self):
        for t in (N_IDCARD17, N_IDCARD_BADMONTH, "123456789012345678"):
            self.assertEqual(pii_mask.detect(t)["idcard"], 0)

    def test_address_positive(self):
        self.assertEqual(pii_mask.detect(f"住在{P_ADDR}附近")["address"], 1)
        self.assertEqual(pii_mask.detect(P_ADDR_FULL)["address"], 1)

    def test_address_negative_city_only(self):
        # 纯行政区名（无门牌号级尾段）不算"详细地址"——不误伤规范类文本
        self.assertEqual(pii_mask.detect(f"坐标{N_ADDR_CITY_ONLY}的宏站")["address"], 0)


class MaskTextTest(unittest.TestCase):
    """mask_text：占位替换、不截断全文、替换序（身份证先于手机号）。"""

    def test_mask_replaces_only_fields(self):
        # 地址样例用分隔符形态（v1 已知限制：地址正则会吸收前置邻接汉字，
        # "家在河北省…"形态最多吃掉"家在"级邻接字——已登记设计报告 §二）
        t = (f"无线网优问题排查：联系我 {P_PHONE}，邮箱 {P_EMAIL}，"
             f"地址：{P_ADDR}。")
        masked, c = pii_mask.mask_text(t)
        self.assertEqual((c["phone"], c["email"], c["address"]), (1, 1, 1))
        self.assertNotIn(P_PHONE, masked)
        self.assertNotIn(P_EMAIL, masked)
        self.assertNotIn("中山东路123号", masked)
        # 不截断全文：任务上下文原样保留
        self.assertIn("无线网优问题排查", masked)
        self.assertIn("联系我", masked)
        self.assertIn("地址：", masked)

    def test_mask_idcard_before_phone(self):
        # 18 位身份证含 11 位子段：身份证先替换，手机号不误吃残段
        t = f"证件 {P_IDCARD} 电话 {P_PHONE}"
        masked, c = pii_mask.mask_text(t)
        self.assertEqual((c["idcard"], c["phone"]), (1, 1))
        self.assertNotIn(P_IDCARD, masked)
        self.assertIn(pii_mask.PLACEHOLDER["idcard"], masked)
        self.assertIn(pii_mask.PLACEHOLDER["phone"], masked)

    def test_mask_no_change_when_clean(self):
        t = "5g小区掉话率高怎么优化"
        masked, c = pii_mask.mask_text(t)
        self.assertEqual(masked, t)
        self.assertEqual(c["total"], 0)


class ResumeLikeTest(unittest.TestCase):
    """结构化简历特征正反例（多行短句+联系方式共现）。"""

    def _resume(self):
        return "\n".join([
            "个人简历",
            f"姓名：张三（合成）  电话：{P_PHONE}",
            f"邮箱：{P_EMAIL}",
            "意向岗位：网优后台工程师",
            "工作经历：负责掉话率优化",
            "教育经历：某大学 通信工程",
        ])

    def test_resume_positive(self):
        self.assertTrue(pii_mask.detect(self._resume())["resume_like"])

    def test_resume_positive_masked_contact_form(self):
        # 已掩码形态（生产认录管线产物 <11位已掩码>）也应识别为简历结构
        t = "\n".join([
            "简 历", "姓 名：<姓名>", "电话：<11位已掩码>",
            "意向岗位：网优后台工程师", "工作经历：负责高负荷小区监控",
        ])
        self.assertTrue(pii_mask.detect(t)["resume_like"])

    def test_career_question_negative(self):
        # 单行职业向知识问：无多行结构无联系方式 → 不标 resume
        # （职业向不建拒答模板是决策基线，本模块只做字段掩码与结构标记）
        self.assertFalse(pii_mask.detect("无线网优工程师的日常工作内容有哪些")["resume_like"])

    def test_multiline_technical_negative(self):
        # 多行但无联系方式（纯技术粘贴）→ 不标 resume
        t = "\n".join(["掉话率优化步骤", "第一步采集话统", "第二步定位小区",
                       "第三步参数调整", "第四步验证指标"])
        self.assertFalse(pii_mask.detect(t)["resume_like"])

    def test_long_paragraph_negative(self):
        t = "工作内容：" + "负责高负荷小区监控与优化，" * 20  # 单行长段
        self.assertFalse(pii_mask.detect(t)["resume_like"])


class ModeResolveTest(unittest.TestCase):
    """开关三态清洗：缺键/坏值回默认 log_only（枚举 off|log_only|mask）。"""

    def test_default_and_valid(self):
        self.assertEqual(pii_mask.DEFAULT_MODE, "log_only")
        self.assertEqual(pii_mask.resolve_mode({}), "log_only")
        self.assertEqual(pii_mask.resolve_mode({pii_mask.CONFIG_KEY: "mask"}), "mask")
        self.assertEqual(pii_mask.resolve_mode({pii_mask.CONFIG_KEY: "off"}), "off")
        self.assertEqual(pii_mask.resolve_mode({pii_mask.CONFIG_KEY: "LOG_ONLY"}),
                         "log_only")

    def test_bad_values_fall_back(self):
        for v in ("", "unknown", "MASK_ALL", 1, None):
            self.assertEqual(pii_mask.resolve_mode({pii_mask.CONFIG_KEY: v}),
                             "log_only")


class ApplyToMessagesTest(unittest.TestCase):
    """apply_to_messages 三态行为（含日志行格式与 fail-open）。"""

    CLEAN = [
        {"role": "user", "content": f"帮我看看这个问题，电话{P_PHONE}"},
        {"role": "assistant", "content": "好的，请描述具体现象。"},
        {"role": "user", "content": f"5g掉话率高怎么优化 邮箱{P_EMAIL}"},
    ]

    def _run(self, mode):
        out = io.StringIO()
        clean = [dict(m) for m in self.CLEAN]
        ret = pii_mask.apply_to_messages(
            clean, mode, trace_id="ab12cd34",
            log=lambda *a, **k: print(*a, file=out, **k))
        return ret, out.getvalue()

    def test_off_no_touch_no_log(self):
        ret, logged = self._run("off")
        self.assertEqual(ret, self.CLEAN)
        self.assertEqual(logged, "")

    def test_log_only_logs_but_keeps_text(self):
        ret, logged = self._run("log_only")
        self.assertEqual(ret, self.CLEAN)
        self.assertEqual(ret[0]["content"], self.CLEAN[0]["content"])
        lines = [ln for ln in logged.splitlines() if ln.startswith("[pii_mask]")]
        self.assertEqual(len(lines), 1)
        m = LOG_LINE_RE.match(lines[0])
        self.assertIsNotNone(m, msg=f"日志行格式不符：{lines[0][:60]}…")
        self.assertEqual((m.group(1), m.group(3), m.group(4), m.group(5), m.group(6)),
                         ("log_only", "1", "1", "0", "0"))
        self.assertEqual(m.group(2), "ab12cd34")
        self.assertNotIn(P_PHONE, logged)   # 零原文纪律
        self.assertNotIn(P_EMAIL, logged)

    def test_mask_masks_user_only(self):
        ret, logged = self._run("mask")
        self.assertNotIn(P_PHONE, ret[0]["content"])
        self.assertNotIn(P_EMAIL, ret[2]["content"])
        self.assertIn(pii_mask.PLACEHOLDER["phone"], ret[0]["content"])
        self.assertIn(pii_mask.PLACEHOLDER["email"], ret[2]["content"])
        # assistant 消息不动；任务上下文保留（不截断全文）
        self.assertEqual(ret[1]["content"], self.CLEAN[1]["content"])
        self.assertIn("帮我看看这个问题", ret[0]["content"])
        self.assertIn("5g掉话率高怎么优化", ret[2]["content"])
        self.assertIn("mode=mask", logged)
        self.assertNotIn(P_PHONE, logged)
        self.assertNotIn(P_EMAIL, logged)

    def test_no_hit_no_log(self):
        out = io.StringIO()
        clean = [{"role": "user", "content": "携号转网流程是什么"}]
        pii_mask.apply_to_messages(clean, "log_only", "ab12cd34",
                                   log=lambda *a, **k: print(*a, file=out, **k))
        self.assertEqual(out.getvalue(), "")

    def test_fail_open_on_garbage(self):
        for bad in (None, "字符串", [None, 123]):
            ret = pii_mask.apply_to_messages(bad, "mask", "trace0000")
            self.assertIs(ret, bad)   # fail-open：原样返回绝不抛出
        self.assertEqual(pii_mask.mask_text(None)[1]["total"], 0)


class SeparatedPhoneIdcardTest(unittest.TestCase):
    """v1.1 分隔形态（P2）：+86/空格/连字符/句点尾——detect 命中、mask 整段替换。"""

    def test_phone_forms_detect(self):
        for t in (P_PHONE_SP, P_PHONE_HYP, P_PHONE_86, P_PHONE_86SP,
                  "1381234 5678"):
            self.assertEqual(pii_mask.detect(f"电话 {t} 联系")["phone"], 1, msg=t)

    def test_phone_trailing_ascii_period(self):
        # 句点紧跟手机号不再失配（v1.1 尾断言 (?![\d.]?\d) 的放行面）
        self.assertEqual(pii_mask.detect(f"call {P_PHONE}.")["phone"], 1)

    def test_phone_negatives_v11(self):
        # 浮点防护不因句点放行回退；分段反例与既有长串反例复验
        for t in (f"{P_PHONE}.5", N_PHONE_86_SHORT, N_PHONE_SEP_TS, N_LONG):
            self.assertEqual(pii_mask.detect(t)["phone"], 0, msg=t)

    def test_phone_mask_whole_segment(self):
        for t in (P_PHONE_SP, P_PHONE_HYP, P_PHONE_86, P_PHONE_86SP):
            masked, c = pii_mask.mask_text(f"联系 {t} 谢谢")
            self.assertEqual(c["phone"], 1, msg=t)
            self.assertNotIn(t, masked, msg=t)   # 整段含分隔符替换
            self.assertIn(pii_mask.PLACEHOLDER["phone"], masked)

    def test_idcard_segmented_detect(self):
        for t in (P_IDCARD_SEG, P_IDCARD_SEG_H):
            self.assertEqual(pii_mask.detect(f"证件号 {t}。")["idcard"], 1, msg=t)

    def test_idcard_segmented_mask_whole_segment(self):
        masked, c = pii_mask.mask_text(f"证件 {P_IDCARD_SEG} 收到")
        self.assertEqual(c["idcard"], 1)
        self.assertNotIn(P_IDCARD_SEG, masked)
        self.assertNotIn("1949 1231", masked)   # 分段残段不残留
        self.assertIn(pii_mask.PLACEHOLDER["idcard"], masked)


class MunicipalityAddressTest(unittest.TestCase):
    """v1.1 直辖市详细地址（P1）：四市到门牌级命中；纯区划序列仍不误配。"""

    def test_municipality_detect(self):
        for t in (P_ADDR_MUN, P_ADDR_MUN_FULL, "重庆市渝中区解放碑街道民权路28号",
                  "天津市和平区山西路12号"):
            self.assertEqual(pii_mask.detect(f"住在{t}附近")["address"], 1, msg=t)

    def test_municipality_mask(self):
        masked, c = pii_mask.mask_text(f"地址：{P_ADDR_MUN_FULL}。")
        self.assertEqual(c["address"], 1)
        self.assertNotIn("世纪大道100号", masked)
        self.assertIn(pii_mask.PLACEHOLDER["address"], masked)
        self.assertIn("地址：", masked)

    def test_district_only_negative(self):
        # 无路名门牌的区划序列不算详细地址（直辖市分支不放松"到门牌级"口径）
        self.assertEqual(
            pii_mask.detect(f"坐标{N_ADDR_MUN_DISTRICT}的宏站")["address"], 0)


class ErrTelemetryTest(unittest.TestCase):
    """P5：except 静默路径打限频 err 遥测行（零原文，只含异常类型名）。"""

    class _Boom:
        def __str__(self):
            raise RuntimeError("boom")

    def setUp(self):
        pii_mask._ERR_LAST[0] = 0.0   # 复位限频窗口

    def test_detect_and_mask_text_err_line(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            c = pii_mask.detect(self._Boom())
            masked = pii_mask.mask_text(self._Boom())
        self.assertEqual(c["total"], 0)
        self.assertEqual(masked[1]["total"], 0)
        # 限频：两次系统性异常只打一行（进程级一次/小时）
        self.assertEqual(out.getvalue().count("[pii_mask] err=RuntimeError"), 1)

    def test_apply_to_messages_err_line_fail_open(self):
        class _BadDict(dict):
            def get(self, *a, **k):
                raise KeyError("boom")
        clean = [_BadDict({"role": "user", "content": "hi"})]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ret = pii_mask.apply_to_messages(clean, "log_only", "ab12cd34")
        self.assertIs(ret, clean)   # fail-open：原样返回
        self.assertIn("[pii_mask] err=KeyError", out.getvalue())

    def test_log_hit_raising_log_no_propagation(self):
        def boom(*a, **k):
            raise OSError("log sink broken")
        # 遥测槽也炸时仍不外抛（遥测绝不反噬主链路）
        pii_mask._log_hit("log_only", {"total": 1}, "ab12cd34", log=boom)


class EmailReDosGuardTest(unittest.TestCase):
    """v1.2/P9：EMAIL_RE 对无 @ 长（数字/点/加号）跑的回溯上界防回归。

    修复前形态 [A-Za-z0-9._%+-]+@… 对该构造呈二次曲线（本机 best-of-3：
    6k/12k/24k/48k=26/105/420/1676ms，规格=分级发现表 施工后补录节 P9）；
    v1.2 上界 {1,64} 后线性（实测 ≈2.9ms@24k/5.8ms@48k）。断言阈 0.1s：
    回归形态（420ms@24k）必红、修复形态余量 >30 倍（不取更紧的 10ms 档
    ——并行跑测/负载抖动下留余量，阈上界取舍注记在案）。
    """

    ADV = "1.+" * 8000   # 24000 字符：不间断数字/点/加号长跑（无 @）

    def test_adversarial_run_fast_and_no_match(self):
        t0 = time.perf_counter()
        hits = pii_mask.EMAIL_RE.findall(self.ADV)
        dt = time.perf_counter() - t0
        # 行为正确：无 @ 长跑零命中（不产假邮箱）
        self.assertEqual(hits, [])
        self.assertLess(dt, 0.1, msg=f"EMAIL_RE 回归为高耗时形态：{dt * 1000:.1f}ms@24k")
        # 全管道同口径：detect 零命中、mask 零替换（文本原样）
        self.assertEqual(pii_mask.detect(self.ADV)["email"], 0)
        masked, c = pii_mask.mask_text(self.ADV)
        self.assertEqual(masked, self.ADV)
        self.assertEqual(c["email"], 0)


class IdcardTruncatedRemnantTest(unittest.TestCase):
    """T04：身份证截断残段不命中——正则层现行口径固化（P3 观察档反例组）。

    场景=server 输入截断先于掩码（8000 字符截过程日志）会把跨界身份证切成
    10-17 位前缀残段（含区划+出生段）：IDCARD_RE 需 18 位整段（含尾位），
    残段一律不命中=现行口径。残段漏掩属 P3 观察档（源头修复=server 侧
    换序/截断回退句边界，兄弟批次施工后残段源头消失）；本组用例固化
    正则层行为防回归——将来若有人放宽正则去吃残段，红在这里重过版本化。
    """

    def test_remnant_prefixes_10_to_17_not_matched(self):
        # 正对照（防空转绿）：18 位整段仍命中
        self.assertEqual(pii_mask.detect(P_IDCARD)["idcard"], 1)
        for n in range(10, 18):
            rem = P_IDCARD[:n]   # 合规 18 位形态的前缀残段
            self.assertEqual(pii_mask.detect(f"文本 {rem} 结束")["idcard"], 0,
                             msg=f"{n} 位残段误命中")
            masked, c = pii_mask.mask_text(rem)
            self.assertEqual(masked, rem, msg=f"{n} 位残段被掩码")
            self.assertEqual(c["idcard"], 0, msg=f"{n} 位残段计入掩码")


@clean_store_tests
class ChatEndpointPiiMountTest(unittest.TestCase):
    """/api/chat 挂载集成：伪 httpx 上游（超时收尾，零网络零计费）。

    验收面：log_only=打 [pii_mask] 行；mask=日志/落库均为掩码后形态且不含
    原字段值（落库核验经会话双写面——conversations 默认开）。"""

    def _post(self, content, mode, fetch=False):
        """POST /api/chat → (日志, 会话消息行或 None)。

        落库核验须在 TestClient 上下文内取——lifespan 关闭时会 close 并清
        _store_inst，出块后再取是另一个新库（tests/__init__ 既有坑位）。"""
        body = {"messages": [{"role": "user", "content": content}],
                "passcode": "pw-test"}
        cfg = _auth_ok_cfg()
        cfg["pii_mask_mode"] = mode
        out = io.StringIO()
        rows = None
        with mock.patch.object(server.httpx, "AsyncClient", _FakeAsyncClient), \
                mock.patch.object(server, "API_KEY", "stub-key"), \
                mock.patch.object(server, "CONFIG", cfg), \
                contextlib.redirect_stdout(out):
            with TestClient(server.app) as client:
                resp = client.post("/api/chat", json=body)
                self.assertEqual(resp.status_code, 200)
                dev = client.cookies.get("qabot_device", "")
                conv_id = resp.headers.get("x-qa-conv-id", "")
                if fetch and conv_id:
                    rows = server._store().get_messages(int(conv_id), dev)
        return out.getvalue(), rows

    def test_log_only_line_emitted(self):
        logged, _ = self._post(
            f"网优排查问题：联系 {P_PHONE} 或 {P_EMAIL}", "log_only")
        lines = [ln for ln in logged.splitlines() if ln.startswith("[pii_mask]")]
        self.assertEqual(len(lines), 1)
        self.assertIn("mode=log_only", lines[0])
        self.assertIn("phone=1", lines[0])
        self.assertIn("email=1", lines[0])
        # 零原文纪律：观测行不含任何字段值
        self.assertNotIn(P_PHONE, lines[0])
        self.assertNotIn(P_EMAIL, lines[0])

    def test_mask_line_and_masked_store(self):
        content = f"网优排查问题：联系 {P_PHONE} 或 {P_EMAIL}。"
        logged, rows = self._post(content, "mask", fetch=True)
        lines = [ln for ln in logged.splitlines() if ln.startswith("[pii_mask]")]
        self.assertEqual(len(lines), 1)
        self.assertIn("mode=mask", lines[0])
        # 全日志面零原文（[pii_mask] 行与 [chat] q= 摘要均不得含原字段值）
        self.assertNotIn(P_PHONE, logged)
        self.assertNotIn(P_EMAIL, logged)
        # 落库为掩码后文本（user 侧双写），任务上下文保留
        self.assertIsNotNone(rows)
        user_saved = [r[1] for r in rows if r[0] == "user"][0]
        self.assertNotIn(P_PHONE, user_saved)
        self.assertNotIn(P_EMAIL, user_saved)
        self.assertIn(pii_mask.PLACEHOLDER["phone"], user_saved)
        self.assertIn(pii_mask.PLACEHOLDER["email"], user_saved)
        self.assertIn("网优排查问题", user_saved)

    def test_off_no_line(self):
        logged, _ = self._post(f"联系 {P_PHONE}", "off")
        self.assertNotIn("[pii_mask]", logged)


if __name__ == "__main__":
    unittest.main()


class AddressV2Test(unittest.TestCase):
    """v1.3 地址规则：街名+门牌号直连形态（中关村南大街2号/世纪大道100号）——v1 漏检位修复回归。"""

    def test_addr_street_number_direct(self):
        for q, frag in [("我在北京市海淀区中关村南大街2号乙方大厦上班附近网络差", "中关村南大街2号"),
                        ("上海市浦东新区世纪大道100号这边5G信号弱怎么反馈", "世纪大道100号"),
                        ("广东省深圳市南山区科技园南路88号3栋", "科技园南路88号"),
                        ("浙江省杭州市西湖区文三路138号", "文三路138号")]:
            d = pii_mask.detect(q)
            self.assertGreaterEqual(d.get("address", 0), 1, q)
            m, stats = pii_mask.mask_text(q) if isinstance(pii_mask.mask_text(q), tuple) else (pii_mask.mask_text(q), None)
            self.assertNotIn(frag, m, q)

    def test_addr_negatives_v2(self):
        for n in ["世纪大道沿线的网络规划原则", "北京市的电信服务规范什么时候发布",
                  "中关村南大街交通优化建议", "3GPP 36.133 4.2.2.5 怎么理解",
                  "时延指标1769547200000这个时间戳对吗"]:
            self.assertEqual(pii_mask.detect(n).get("address", 0), 0, n)
