# -*- coding: utf-8 -*-
"""deploy_check.py sanitize() 脱敏边界单测（2026-09-23 条款号误遮小修）。

病灶：报告脱敏把答案文本里点分条款号（如"规范第 5.5.4.7 节"）误判 IPv4 打成
<IP>——实证 运营/部署核验-20260923-1012.md S2"规范第 <IP>"；5 段链还会留
"<IP>.1"残尾。修复口径（安全优先，宁可多遮不可漏遮）：
  豁免仅两路——①5 段以上点分链（天然非 IPv4）；②条款语境词紧邻前置
  （第/节/条款/章节/附录/规范/规程/§/clause/section/TS/TR，容空白/冒号）。
  歧义形态（无前缀裸点分四段）仍遮；真 IP 形态仍遮=硬底线。

零 API、零云端连接、零密值：只测纯函数 sanitize()，样例 IP 一律文档段
（203.0.113.x/1.2.3.x）。覆盖：条款语境豁免（含 bug 原型串与前缀变体）/
裸点分四段仍遮 / 真 IP 形态仍遮（ip= 打点、ssh 回显、:port、句读贴邻）/
5 段以上链豁免 / 既有脱敏（回环/IPv6/key/Bearer/passcode/用户@主机）不回归 /
占位符持有-还原无残留。

运行：python3 <repo>/tests/test_deploy_check_sanitize.py -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import deploy_check as dc  # noqa: E402


class TestClauseContextExempt(unittest.TestCase):
    """条款语境紧邻前置 → 豁免（bug 修复主路）。"""

    def test_bug_prototype_s2_answer(self):
        """bug 原型串（部署核验-20260923-1012.md S2 答案摘录形态）整句原样。"""
        s = "根据 3GPP TS 36.331 (Rel-18 V18.10.0) 规范第 5.5.4.7 节，a3-Offset 取值…"
        self.assertEqual(dc.sanitize(s), s)

    def test_prefix_variants(self):
        """前置词变体：第/节/条款/章节/附录/规范/规程/§/clause/Clause/section/TS/TR。"""
        for s in ("第 5.5.4.7 节", "第5.5.4.7节", "节 5.5.4.7", "条款 5.5.4.7",
                  "章节 5.5.4.7", "附录 5.5.4.7", "规范 5.5.4.7", "规程 5.5.4.7",
                  "§5.5.4.7", "§ 5.5.4.7", "clause 5.5.4.7", "Clause 5.5.4.7",
                  "Clauses 5.5.4.7", "section 5.5.4.7", "Section 5.5.4.7",
                  "TS 5.5.4.7", "TR 5.5.4.7", "规范：5.5.4.7", "第: 5.5.4.7",
                  "第  5.5.4.7"):
            self.assertEqual(dc.sanitize(s), s, s)

    def test_prefix_inside_word_not_exempt(self):
        """英文词内伪前缀（myclause/MYTS）不构成语境 → 仍遮（豁免口径收紧）。"""
        self.assertEqual(dc.sanitize("myclause 5.5.4.7"), "myclause <IP>")
        self.assertEqual(dc.sanitize("MYTS 5.5.4.7"), "MYTS <IP>")

    def test_non_adjacent_prefix_not_exempt(self):
        """非紧邻（前置词与数字间隔实词/数字）→ 歧义，仍遮。"""
        self.assertEqual(dc.sanitize("TS 36.331 5.5.4.7"), "TS 36.331 <IP>")
        self.assertEqual(dc.sanitize("第 36 号文 5.5.4.7"), "第 36 号文 <IP>")

    def test_locator_3seg_untouched(self):
        """库内 locator 形态（附录2 2.2.4 款1，3 段点分）新旧皆不匹配、原样。"""
        s = "信息产业部令第36号|附录2 2.2.4 通话中断率（掉话率） 款1"
        self.assertEqual(dc.sanitize(s), s)


class TestBareFourSegStillMasked(unittest.TestCase):
    """歧义形态硬底线：无前缀裸点分四段一律仍遮（宁可多遮）。"""

    def test_bare_masked(self):
        self.assertEqual(dc.sanitize("裸条款号 5.5.4.7 无语境"), "裸条款号 <IP> 无语境")
        self.assertEqual(dc.sanitize("见 5.5.4.7"), "见 <IP>")
        self.assertEqual(dc.sanitize("1.2.3.4"), "<IP>")

    def test_bare_multi_occurrence_all_masked(self):
        self.assertEqual(dc.sanitize("1.2.3.4 与 5.6.7.8"), "<IP> 与 <IP>")


class TestRealIpStillMasked(unittest.TestCase):
    """真 IP 形态继续遮=硬底线：打点行/ssh 回显/:port/句读贴邻。"""

    def test_chat_log_line(self):
        s = ('[chat] ip=203.0.113.9 auth=body in_chars=19 rag=hit ttfb=1.1s '
             'dur=4.8s q="第 5.5.4.7 节是什么" top1=0.8494')
        got = dc.sanitize(s)
        self.assertIn("ip=<IP>", got)                 # 真 IP 遮
        self.assertIn("第 5.5.4.7 节", got)            # 同行条款号豁免
        self.assertNotIn("203.0.113.9", got)

    def test_ssh_error_and_port_and_punct(self):
        self.assertEqual(
            dc.sanitize("ssh: connect to host root@203.0.113.9 port 22: Connection timed out"),
            "ssh: connect to host root@<IP> port 22: Connection timed out")
        self.assertEqual(dc.sanitize("curl http://203.0.113.9:8000/api/health"),
                         "curl http://<IP>:8000/api/health")
        self.assertEqual(dc.sanitize("连 203.0.113.9。"), "连 <IP>。")
        self.assertEqual(dc.sanitize("see 203.0.113.9."), "see <IP>.")

    def test_dot_adjacent_ip_still_masked(self):
        """点号贴邻但非"数字.数字"链续接 → 照遮（链守卫只挡 \\d\\. 前缀，与旧 \\b 行为一致）。"""
        self.assertEqual(dc.sanitize("end.203.0.113.9"), "end.<IP>")
        self.assertEqual(dc.sanitize("...203.0.113.9"), "...<IP>")
        self.assertEqual(dc.sanitize("x.10.0.0.1"), "x.<IP>")

    def test_offline_fixture_line(self):
        """dry-run offline 场景回显（Cloud._fixture 原文）脱敏后无裸 IP。"""
        got = dc.sanitize("ssh: connect to host root@203.0.113.9 port 22: Connection timed out")
        self.assertNotIn("203.0.113.9", got)


class TestChain5Exempt(unittest.TestCase):
    """5 段以上点分链天然非 IPv4 → 整链豁免（旧行为留"<IP>.1"残尾）。"""

    def test_chains_intact(self):
        for s in ("5.5.4.7.1", "见 5.5.4.7.1 节", "9.4.1.2.1.3",
                  "1.2.3.4.5.6.7.8.9", "第 5.5.4.7.1"):
            self.assertEqual(dc.sanitize(s), s, s)

    def test_chain_with_real_ip_same_line(self):
        self.assertEqual(dc.sanitize("5.5.4.7.1 与 ip=10.0.0.1"),
                         "5.5.4.7.1 与 ip=<IP>")

    def test_word_glued_chain_untouched(self):
        """链首贴单词字符（x1.2.3.4.5）：链守卫挡中段起匹配，整体原样（旧行为会遮成
        x1.<IP>——5 段链天然非 IPv4，新行为按链豁免口径放行，取舍已登记）。"""
        self.assertEqual(dc.sanitize("x1.2.3.4.5"), "x1.2.3.4.5")


class TestNoRegression(unittest.TestCase):
    """既有脱敏语义不回归：回环豁免/IPv6/key/Bearer/passcode/用户@主机。"""

    def test_loopback_exempt(self):
        self.assertEqual(dc.sanitize("curl http://127.0.0.1:8000/api/health"),
                         "curl http://127.0.0.1:8000/api/health")
        self.assertEqual(dc.sanitize("localhost 与 ::1 保留"), "localhost 与 ::1 保留")

    def test_ipv6_key_bearer_passcode_at(self):
        self.assertEqual(dc.sanitize("IPv6 2001:db8::1234:5678 遮"), "IPv6 <IPv6> 遮")
        self.assertEqual(dc.sanitize("key sk-abcdefgh12345678"), "key <KEY>")
        self.assertEqual(dc.sanitize("Bearer abc.def.ghi"), "Bearer <TOKEN>")
        self.assertEqual(dc.sanitize('passcode="hunter2"'), 'passcode="<已脱敏>')
        self.assertEqual(dc.sanitize("user@host.example.com"), "<用户@主机>")

    def test_empty_and_none(self):
        self.assertEqual(dc.sanitize(""), "")
        self.assertIsNone(dc.sanitize(None))

    def test_no_placeholder_residue(self):
        """持有-还原机制无 \\x00 残留（含占位被 Bearer/passcode \\S+ 吞掉的形态）。"""
        for s in ("第 5.5.4.7 ip=1.2.3.4 5.5.4.7.1", "Bearer 第 9.9.9.9",
                  "token=第5.5.4.7", "第 5.5.4.7 和第 5.5.4.7"):
            self.assertNotIn("\x00", dc.sanitize(s), s)

    def test_swallowed_hold_fails_safe(self):
        """占位被 \\S+ 类规则吞掉 → 只会多遮不会漏遮（fail-safe 方向）。"""
        self.assertEqual(dc.sanitize("Bearer 第 5.5.4.7"), "Bearer <TOKEN>")
        self.assertEqual(dc.sanitize("token=第5.5.4.7"), "token=<已脱敏>")

    def test_fixture_journal_line_shape(self):
        """dry-run fixture 打点行整行：ip 遮、打点字段与 locator 原样（④判读不受影响）。"""
        line = ('[chat] ip=203.0.113.9 auth=body in_chars=19 rag=hit ttfb=1.1s dur=4.8s '
                "usage={'prompt_tokens': 810} cancelled=0 q=\"掉话率红线\" top1=0.8494 cc=off ab=off")
        got = dc.sanitize(line)
        self.assertIn("ip=<IP>", got)
        self.assertIn("rag=hit", got)
        self.assertIn("top1=0.8494", got)
        self.assertNotIn("203.0.113.9", got)


if __name__ == "__main__":
    unittest.main()
