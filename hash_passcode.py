#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""口令哈希生成器（2026-09-21 批 2 前置件，配套 运营/优化提升-20260921/服务端会话设计稿-20260921.md §3）

为批 2"服务端会话+限流持久化"的口令哈希改造（server.py 明文比对 → PBKDF2 校验）
预先生成 config 三键。路径偏离说明：设计稿写 scripts/hash_passcode.py，仓内无
scripts/ 目录（根级平铺，deploy_check.py 同层），故本件落仓根。

算法
----
hashlib.pbkdf2_hmac("sha256", pwd, salt, 600_000)，标准库零依赖（OWASP 2023
建议迭代量级；2 核机单次 ~100-200ms，login 冷路径可接受）。生成 16 字节
secrets 随机盐；输出三行可直接粘进 config.json 的键值（hex 形态）+实测耗时：
    "passcode_hash": "<64 位 hex>",       ← PBKDF2 派生键（hex）
    "passcode_salt": "<32 位 hex>",       ← 16 字节盐（hex）
    "pbkdf2_iterations": 600000,
config.example.json 的三键由批 2 施工时随 server.py 一起加，本件不改它；
过渡期服务端"读不到哈希键但见旧 passcode 明文→兼容校验+启动警告"。

口令输入（防 shell 历史残留：不提供任何把口令放进 argv 的入口）
----------------------------------------------------------------
默认交互式 getpass 两次输入确认（不回显）；脚本化用 --stdin（只读首行，
去行尾换行，不做确认）。口令绝不回显、绝不进任何输出/日志/错误信息。

用法
----
    python3 <repo>/hash_passcode.py                     # 交互式，600k 迭代
    python3 <repo>/hash_passcode.py --iterations 600000 # 同上，显式迭代数
    printf '口令占位符\\n' | python3 <repo>/hash_passcode.py --stdin

退出码：0=成功；2=输入错误（空口令/两次不一致/迭代数非法/中断）。
"""
import argparse
import getpass
import hashlib
import secrets
import sys
import time

DEFAULT_ITERATIONS = 600_000   # OWASP 2023 PBKDF2-HMAC-SHA256 建议量级
WARN_BELOW_ITERATIONS = 100_000  # 低于此值仅应测试用（stderr 警告，不阻断）
SALT_BYTES = 16                # 盐字节数（config 键 passcode_salt=32 位 hex）
HASH_NAME = "sha256"


def derive_hex(passcode, salt, iterations):
    """PBKDF2-HMAC-SHA256 派生键 → hex 字符串（服务端校验用同一式子对照）。"""
    return hashlib.pbkdf2_hmac(
        HASH_NAME, passcode.encode("utf-8"), salt, iterations).hex()


def new_salt():
    """16 字节密码学随机盐。"""
    return secrets.token_bytes(SALT_BYTES)


def generate(passcode, iterations=DEFAULT_ITERATIONS, salt=None):
    """口令 → {passcode_hash, passcode_salt, pbkdf2_iterations, elapsed_ms}。

    elapsed_ms 只计 PBKDF2 本体耗时（perf_counter 实测）。返回值不含口令本身。
    """
    if not passcode:
        raise ValueError("口令为空")
    if not isinstance(iterations, int) or iterations < 1:
        raise ValueError("iterations 须为 ≥1 的整数")
    if salt is None:
        salt = new_salt()
    elif len(salt) != SALT_BYTES:
        raise ValueError("salt 须为 %d 字节" % SALT_BYTES)
    t0 = time.perf_counter()
    digest = derive_hex(passcode, salt, iterations)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    return {"passcode_hash": digest, "passcode_salt": salt.hex(),
            "pbkdf2_iterations": iterations, "elapsed_ms": elapsed_ms}


def config_lines(result):
    """→ 三行可直接粘进 config.json 的键值行（2 空格缩进对齐现有排版，
    行尾带逗号——粘在非末键位即合法；粘在对象末键位需去掉末行逗号）。"""
    return [
        '  "passcode_hash": "%s",' % result["passcode_hash"],
        '  "passcode_salt": "%s",' % result["passcode_salt"],
        '  "pbkdf2_iterations": %d,' % result["pbkdf2_iterations"],
    ]


def prompt_passcode():
    """交互式取口令：getpass 两次输入（不回显），不一致/为空即拒绝。"""
    first = getpass.getpass("设置新口令（输入不回显）: ")
    again = getpass.getpass("再输入一次确认: ")
    if first != again:
        raise ValueError("两次输入不一致，未生成哈希")
    if not first:
        raise ValueError("口令为空")
    return first


def read_passcode_stdin():
    """--stdin 模式：读首行去行尾换行（其余空白不动，防误裁合法口令）。"""
    line = sys.stdin.readline()
    if line == "":
        raise ValueError("stdin 无输入（EOF）")
    return line.rstrip("\r\n")


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="hash_passcode.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,  # 保住 epilog 示例换行
        description="生成 config.json 口令哈希三键（PBKDF2-HMAC-SHA256，零依赖）。"
                    "口令只经交互式 getpass 或 --stdin 进入——不提供 argv 口令入口"
                    "（会进 shell 历史/ps），输出零口令残留。",
        epilog="示例：python3 <repo>/hash_passcode.py\n"
               "      printf '口令占位符\\n' | python3 <repo>/hash_passcode.py --stdin\n"
               "输出三行粘进 config.json 替换原 \"passcode\" 明文键即可。",
    )
    ap.add_argument("--stdin", action="store_true",
                    help="改从 stdin 读口令（脚本化用；只读首行，适合管道喂入，不回显不落盘）")
    ap.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS, metavar="N",
                    help=("PBKDF2 迭代次数（默认 %(default)s=OWASP 建议量级；"
                          "仅测试可调低，生产 config 勿低于 {:d}）").format(WARN_BELOW_ITERATIONS))
    args = ap.parse_args(argv)
    if args.iterations < 1:
        ap.error("--iterations 须为 ≥1 的整数")
    if args.iterations < WARN_BELOW_ITERATIONS:
        print("[warn] iterations=%d 低于 %d：仅测试用途，勿用于生产 config"
              % (args.iterations, WARN_BELOW_ITERATIONS), file=sys.stderr)

    try:
        if args.stdin:
            passcode = read_passcode_stdin()
        else:
            passcode = prompt_passcode()
    except ValueError as e:
        print("错误：%s" % e, file=sys.stderr)
        return 2
    except EOFError:  # 交互提示下 Ctrl-D
        print("输入流结束（未生成哈希）。", file=sys.stderr)
        return 2
    except KeyboardInterrupt:  # 提示下 Ctrl-C
        print("\n已取消（未生成哈希）。", file=sys.stderr)
        return 2
    try:
        result = generate(passcode, iterations=args.iterations)
    except ValueError as e:
        print("错误：%s" % e, file=sys.stderr)
        return 2
    finally:
        passcode = ""  # 尽力尽早去引用（str 不可变无法覆写，仅释放本地柄）

    print("已生成（PBKDF2-HMAC-SHA256，%d 次迭代）。把下面三行粘进 config.json"
          "（替换原 \"passcode\" 明文键；若粘在对象末键位，去掉末行行尾逗号）："
          % result["pbkdf2_iterations"])
    print()
    for line in config_lines(result):
        print(line)
    print()
    print("实测耗时：%.1f ms（iterations=%d；口令本身不回显、输出零残留）。"
          % (result["elapsed_ms"], result["pbkdf2_iterations"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
