# -*- coding: utf-8 -*-
"""hash_passcode.py 口令哈希生成器离线单测（2026-09-21 批 2 前置件，
配套 运营/优化提升-20260921/服务端会话设计稿-20260921.md §3）。

覆盖：固定盐+口令确定性向量（与 hashlib.pbkdf2_hmac 直算对照，含中文/带
符号口令）、默认盐 16 字节、随机盐两跑不同、迭代数可配且影响派生键、输出
hex 合法性（hash=64 位/salt=32 位）、三键行粘进 JSON 可解析、空口令与非法
迭代数/盐长拒绝、CLI --stdin 子进程端到端（三键落 stdout、金丝雀口令在
stdout/stderr 零残留、输出回捞值与服务端同式直算复核、argv 面无口令入口）。
零网络零 API；迭代数全部 ≤5000，整件秒级。"""
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import unittest
from unittest import mock

import hash_passcode  # 仓根模块（tests/__init__.py 已做 sys.path 引导）

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "hash_passcode.py")
FIXED_SALT = bytes(range(16))  # 固定向量盐：00..0f


class DeriveVectorTest(unittest.TestCase):
    """确定性向量：derive_hex 与 hashlib 直算逐位一致（服务端校验同式）。"""

    def test_matches_hashlib_direct(self):
        for pwd, iters in (("s3cret-pc", 1000), ("中文口令-批2前置", 2500),
                           ("with space & symbol!", 4096)):
            self.assertEqual(
                hash_passcode.derive_hex(pwd, FIXED_SALT, iters),
                hashlib.pbkdf2_hmac("sha256", pwd.encode("utf-8"),
                                    FIXED_SALT, iters).hex(),
                msg="pwd/iters=%r/%d" % (pwd[:4] + "…", iters))

    def test_same_inputs_same_digest(self):
        self.assertEqual(hash_passcode.derive_hex("a", FIXED_SALT, 10),
                         hash_passcode.derive_hex("a", FIXED_SALT, 10))


class GenerateTest(unittest.TestCase):
    def test_default_salt_is_16_bytes(self):
        r = hash_passcode.generate("pw", iterations=100)
        self.assertEqual(len(bytes.fromhex(r["passcode_salt"])), 16)

    def test_random_salt_differs_between_runs(self):
        r1 = hash_passcode.generate("pw", iterations=100)
        r2 = hash_passcode.generate("pw", iterations=100)
        self.assertNotEqual(r1["passcode_salt"], r2["passcode_salt"])
        self.assertNotEqual(r1["passcode_hash"], r2["passcode_hash"])

    def test_explicit_salt_roundtrip(self):
        r = hash_passcode.generate("pw", iterations=100, salt=FIXED_SALT)
        self.assertEqual(r["passcode_salt"], FIXED_SALT.hex())
        self.assertEqual(r["passcode_hash"],
                         hashlib.pbkdf2_hmac("sha256", b"pw", FIXED_SALT, 100).hex())

    def test_wrong_salt_length_rejected(self):
        with self.assertRaises(ValueError):
            hash_passcode.generate("pw", iterations=100, salt=b"0123456789")

    def test_iterations_configurable_and_affect_digest(self):
        r100 = hash_passcode.generate("pw", iterations=100, salt=FIXED_SALT)
        r200 = hash_passcode.generate("pw", iterations=200, salt=FIXED_SALT)
        self.assertEqual(r100["pbkdf2_iterations"], 100)
        self.assertNotEqual(r100["passcode_hash"], r200["passcode_hash"])

    def test_output_hex_validity_and_timing_field(self):
        r = hash_passcode.generate("pw", iterations=100)
        digest, salt = r["passcode_hash"], r["passcode_salt"]
        self.assertEqual(len(digest), 64)   # SHA-256 → 32 字节 → 64 hex
        self.assertEqual(len(salt), 32)     # 16 字节盐 → 32 hex
        int(digest, 16)   # 合法 hex（能解析即过）
        int(salt, 16)
        self.assertIsInstance(r["elapsed_ms"], float)
        self.assertGreaterEqual(r["elapsed_ms"], 0.0)
        self.assertNotIn("pw", json.dumps(r))  # 返回值不含口令本身

    def test_empty_passcode_rejected(self):
        with self.assertRaises(ValueError):
            hash_passcode.generate("", iterations=100)

    def test_bad_iterations_rejected(self):
        for bad in (0, -1, 1.5):
            with self.assertRaises(ValueError):
                hash_passcode.generate("pw", iterations=bad)


class ConfigLinesTest(unittest.TestCase):
    def test_three_pasteable_lines_parse_as_json(self):
        r = hash_passcode.generate("pw", iterations=100, salt=FIXED_SALT)
        lines = hash_passcode.config_lines(r)
        self.assertEqual(len(lines), 3)
        # 去整体末尾逗号后应能直接拼成合法 JSON 对象，且值与 generate 结果一致
        obj = json.loads("{\n" + "\n".join(lines).rstrip(",") + "\n}")
        self.assertEqual(obj, {"passcode_hash": r["passcode_hash"],
                               "passcode_salt": r["passcode_salt"],
                               "pbkdf2_iterations": 100})


class PromptTest(unittest.TestCase):
    def test_match_returns_first_input(self):
        with mock.patch("getpass.getpass", side_effect=["abc", "abc"]):
            self.assertEqual(hash_passcode.prompt_passcode(), "abc")

    def test_mismatch_rejected(self):
        with mock.patch("getpass.getpass", side_effect=["abc", "abd"]):
            with self.assertRaises(ValueError):
                hash_passcode.prompt_passcode()

    def test_empty_rejected(self):
        with mock.patch("getpass.getpass", side_effect=["", ""]):
            with self.assertRaises(ValueError):
                hash_passcode.prompt_passcode()


class MainPathTest(unittest.TestCase):
    """main() 输入路径：--stdin 成功态与提示下 EOF/Ctrl-D 的干净退出（无堆栈）。"""

    def test_main_stdin_ok(self):
        with mock.patch("sys.stdin", io.StringIO("mainpw\n")):
            rc = hash_passcode.main(["--stdin", "--iterations", "200"])
        self.assertEqual(rc, 0)

    def test_main_prompt_eof_exits_cleanly(self):
        with mock.patch("getpass.getpass", side_effect=EOFError):
            self.assertEqual(hash_passcode.main([]), 2)


class CliEndToEndTest(unittest.TestCase):
    """子进程跑真脚本（--stdin 低迭代数）：输出形态+口令零残留。"""

    def _run(self, argv, stdin_text):
        return subprocess.run([sys.executable, SCRIPT] + argv, input=stdin_text,
                              text=True, capture_output=True, timeout=60)

    def test_stdin_mode_keys_in_stdout_and_no_leak(self):
        canary = "CANARY-pc-7f3a9"
        p = self._run(["--stdin", "--iterations", "500"], canary + "\n")
        self.assertEqual(p.returncode, 0, msg=p.stderr[-300:])
        self.assertNotIn(canary, p.stdout)   # 口令不落 stdout
        self.assertNotIn(canary, p.stderr)   # 口令不落 stderr
        self.assertIn('"passcode_hash"', p.stdout)
        self.assertIn('"passcode_salt"', p.stdout)
        self.assertIn('"pbkdf2_iterations": 500', p.stdout)
        # 输出回捞的哈希/盐用服务端同式直算复核（端到端确定性）
        h = re.search(r'"passcode_hash": "([0-9a-f]{64})"', p.stdout)
        s = re.search(r'"passcode_salt": "([0-9a-f]{32})"', p.stdout)
        self.assertTrue(h and s, msg=p.stdout[-300:])
        self.assertEqual(
            h.group(1),
            hashlib.pbkdf2_hmac("sha256", canary.encode("utf-8"),
                                bytes.fromhex(s.group(1)), 500).hex())

    def test_stdin_empty_input_fails_cleanly(self):
        p = self._run(["--stdin", "--iterations", "500"], "")
        self.assertNotEqual(p.returncode, 0)
        self.assertNotIn("Traceback", p.stderr)  # 干净报错非崩溃
        self.assertIn("错误", p.stderr)

    def test_no_argv_passcode_surface(self):
        # 防 shell 历史残留的硬约束：CLI 不提供任何吃口令的 argv 选项
        p = self._run(["--help"], "")
        self.assertEqual(p.returncode, 0)
        for opt in ("--passcode", "--password", "--pwd"):
            self.assertNotIn(opt, p.stdout)
            self.assertNotIn(opt, p.stderr)

    def test_bad_iterations_flag_rejected(self):
        p = self._run(["--stdin", "--iterations", "0"], "x\n")
        self.assertNotEqual(p.returncode, 0)
        self.assertNotIn("Traceback", p.stderr)


if __name__ == "__main__":
    unittest.main()
