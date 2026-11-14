# -*- coding: utf-8 -*-
"""C3 口令哈希安全单测（2026-10-07，配套 运营/测试体系-20261007/草案/
C3-施工报告-20261007.md 与 C3-云端runbook-20261007.md）。

覆盖（C3 施工四件之③）：
  ① 哈希三键生效：stub 口令+固定盐低迭代向量 → server._passcode_ok 过/拒；
  ② 明文兼容回退双态：仅明文键（过/拒/精确比对）+ 双键全无（开放态 True、
     闸门关）；
  ③ 盐唯一性：hash_passcode.generate 两跑盐不同 → 哈希不同（同口令）；
  ④ pbkdf2_iterations 低于下限（<100000）：C8（2026-10-07）起视为无效配置
     回落 600_000（下限守门）；夹具迭代数一律用 ≥100_000
     不强制，生产防线=config 核对 600000（runbook 步骤②含）；缺键/坏值
     （非整数）回落 600_000；
  ⑤ 盐守门：哈希在位但盐空/非 hex → False，且明文键同时在位也不给回退
     开后门（server.py _passcode_ok 盐残缺分支）；
  ⑥ 双键在位哈希优先：哈希三键+明文键 → 按哈希校验（明文口令对不上=False）；
  ⑦ 启动告警双态：明文且无哈希 → lifespan 打印明文兼容模式警告；双键在位
     → **现行为不告警**（server.py:746 条件为"明文且无哈希"，双键态明文
     残留不告警=C3 发现的缺口，如实断言现状，改进归 server.py 辖区非本件）。

零网络零 API（不起服务、不发请求）；迭代数测试内 ≤2000，唯 600_000 回落
验证两跑（类级共享一枚 600k 向量）合计 ~0.5s，整件秒级。"""
import asyncio
import contextlib
import io
import unittest
from unittest import mock

import hash_passcode  # 仓根模块（tests/__init__.py 已做 sys.path 引导）
import server         # 同上；QABOT_DB_PATH 已隔离到一次性临时目录

FIXED_SALT = bytes(range(16))     # 固定向量盐：00..0f（与 test_hash_passcode 同规）
STUB_PW = "c3-stub-口令"          # stub 口令向量（中文+符号，utf-8 编码路径覆盖）


def _ok(supplied):
    """同步包装 server._passcode_ok（每呼独立事件循环，供 unittest 直用）。"""
    return asyncio.run(server._passcode_ok(supplied))


def _three_keys(pw, iterations, salt=FIXED_SALT):
    r = hash_passcode.generate(pw, iterations=iterations, salt=salt)
    return {"passcode_hash": r["passcode_hash"],
            "passcode_salt": r["passcode_salt"],
            "pbkdf2_iterations": r["pbkdf2_iterations"]}


class HashThreeKeysTest(unittest.TestCase):
    """① 哈希三键生效：正确口令过、错口令拒（常数时间比对路径）。"""

    def test_correct_passcode_accepted(self):
        with mock.patch.dict(server.CONFIG, _three_keys(STUB_PW, 100_000), clear=True):
            self.assertTrue(_ok(STUB_PW))

    def test_wrong_passcode_rejected(self):
        with mock.patch.dict(server.CONFIG, _three_keys(STUB_PW, 100_000), clear=True):
            self.assertFalse(_ok(STUB_PW + "x"))
            self.assertFalse(_ok(""))
            self.assertFalse(_ok(STUB_PW.upper() if STUB_PW.upper() != STUB_PW
                                 else STUB_PW + "X"))

    def test_gate_on_with_hash_only(self):
        with mock.patch.dict(server.CONFIG, _three_keys(STUB_PW, 100_000), clear=True):
            self.assertTrue(server._passcode_gate())


class PlaintextCompatTest(unittest.TestCase):
    """② 明文兼容回退双态 + 开放态：无哈希键才走明文比对（精确相等）。"""

    def test_plaintext_correct_and_wrong(self):
        with mock.patch.dict(server.CONFIG, {"passcode": "plain-stub"}, clear=True):
            self.assertTrue(_ok("plain-stub"))       # 双态之一：口令对
            self.assertFalse(_ok("plain-stub "))     # 双态之二：多一空格即拒（精确比对）
            self.assertFalse(_ok("PLAIN-STUB"))      # 大小写敏感
            self.assertTrue(server._passcode_gate())

    def test_open_mode_when_no_keys(self):
        with mock.patch.dict(server.CONFIG, {}, clear=True):
            self.assertTrue(_ok("anything"))         # 开放态：都放行
            self.assertFalse(server._passcode_gate())


class SaltUniquenessTest(unittest.TestCase):
    """③ 盐唯一性：同口令两跑默认随机盐 → 盐不同且哈希不同。"""

    def test_two_generations_differ(self):
        r1 = hash_passcode.generate(STUB_PW, iterations=200)
        r2 = hash_passcode.generate(STUB_PW, iterations=200)
        self.assertNotEqual(r1["passcode_salt"], r2["passcode_salt"])
        self.assertNotEqual(r1["passcode_hash"], r2["passcode_hash"])
        # 反证固定盐可复现（唯一性来自随机盐而非时钟/随机哈希面）
        r3 = hash_passcode.generate(STUB_PW, iterations=200, salt=FIXED_SALT)
        r4 = hash_passcode.generate(STUB_PW, iterations=200, salt=FIXED_SALT)
        self.assertEqual(r3["passcode_hash"], r4["passcode_hash"])


class IterationsBehaviorTest(unittest.TestCase):
    """④ pbkdf2_iterations 实际行为：低于 100000 按原值用（无下限校验）；
    缺键/坏值回落 600_000。生产防线在生成与核对侧，服务端不强制。"""

    @classmethod
    def setUpClass(cls):
        r = hash_passcode.generate(STUB_PW, iterations=600_000, salt=FIXED_SALT)
        cls.keys_600k = {"passcode_hash": r["passcode_hash"],
                         "passcode_salt": r["passcode_salt"]}

    def test_below_100k_clamped_to_600k(self):
        # C8（2026-10-07）加固：<100000 视为无效配置回落 600_000——
        # 1500 迭代生成的哈希对不上（服务端按 600_000 派生→拒）；
        # 600k 生成的哈希即便配 1500 也对上（回落生效→过）。
        with mock.patch.dict(server.CONFIG, _three_keys(STUB_PW, 1500), clear=True):
            self.assertFalse(_ok(STUB_PW))
        cfg = dict(self.keys_600k, pbkdf2_iterations=1500)
        with mock.patch.dict(server.CONFIG, cfg, clear=True):
            self.assertTrue(_ok(STUB_PW))

    def test_missing_key_falls_back_to_600k(self):
        cfg = dict(self.keys_600k)                    # 无 pbkdf2_iterations 键
        with mock.patch.dict(server.CONFIG, cfg, clear=True):
            self.assertTrue(_ok(STUB_PW))             # 服务端 or 600_000 兜底
            self.assertFalse(_ok(STUB_PW + "x"))

    def test_bad_value_falls_back_to_600k(self):
        cfg = dict(self.keys_600k, pbkdf2_iterations="not-a-number")
        with mock.patch.dict(server.CONFIG, cfg, clear=True):
            self.assertTrue(_ok(STUB_PW))             # int() 失败 → 600_000


class SaltGuardTest(unittest.TestCase):
    """⑤ 盐守门：哈希在位但盐残缺/坏值 → 一律 False，明文键在位也不开回退门。"""

    def test_empty_salt_rejected_even_with_plaintext_present(self):
        good = _three_keys(STUB_PW, 100_000)
        cfg = dict(good, passcode_salt="", passcode="plain-stub")
        with mock.patch.dict(server.CONFIG, cfg, clear=True):
            self.assertFalse(_ok(STUB_PW))            # 哈希口令对也拒（盐残缺）
            self.assertFalse(_ok("plain-stub"))       # 且不给明文回退开后门

    def test_non_hex_salt_rejected(self):
        good = _three_keys(STUB_PW, 100_000)
        cfg = dict(good, passcode_salt="zz" * 16)     # 非 hex 盐
        with mock.patch.dict(server.CONFIG, cfg, clear=True):
            self.assertFalse(_ok(STUB_PW))


class HashPriorityTest(unittest.TestCase):
    """⑥ 双键在位哈希优先：明文键被无视（对明文键口令=错口令语义）。"""

    def test_hash_wins_over_plaintext(self):
        good = _three_keys(STUB_PW, 100_000)
        cfg = dict(good, passcode="plain-stub")
        with mock.patch.dict(server.CONFIG, cfg, clear=True):
            self.assertTrue(_ok(STUB_PW))             # 哈希口令过
            self.assertFalse(_ok("plain-stub"))       # 明文口令不回退生效


class StartupWarningTest(unittest.TestCase):
    """⑦ 启动告警双态（lifespan stdout 捕获）：明文且无哈希→告警；
    双键在位→现状不告警（缺口如实断言，见件头注）。"""

    def _lifespan_output(self, cfg):
        buf = io.StringIO()

        async def _go():
            async with server.lifespan(server.app):
                pass

        with mock.patch.dict(server.CONFIG, dict(cfg, model="stub-model"), clear=True):
            with contextlib.redirect_stdout(buf):
                asyncio.run(_go())
        return buf.getvalue()

    def test_plaintext_only_warns(self):
        out = self._lifespan_output({"passcode": "plain-stub"})
        self.assertIn("明文兼容模式", out)
        self.assertIn("hash_passcode.py", out)

    def test_hash_only_no_warning(self):
        out = self._lifespan_output(_three_keys(STUB_PW, 1000))
        self.assertNotIn("明文兼容模式", out)
        self.assertIn("passcode=on", out)

    def test_both_keys_warn_plaintext_residue(self):
        # C8（2026-10-07）加固：双键在位 → 告警"明文键残留应删"（不再是静默）；
        # 但校验面哈希优先不变（与 HashPriorityTest 互证）。
        cfg = dict(_three_keys(STUB_PW, 1000), passcode="plain-stub")
        out = self._lifespan_output(cfg)
        self.assertNotIn("明文兼容模式", out)
        self.assertIn("明文键", out)  # 残留告警文案（应删明文键）
        with mock.patch.dict(server.CONFIG, cfg, clear=True):
            self.assertFalse(_ok("plain-stub"))


if __name__ == "__main__":
    unittest.main()
