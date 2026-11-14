# -*- coding: utf-8 -*-
"""deploy_check.py 单测：⑪ SLA 状态机读数 + ⑫ 嵌入预算拨键呈现
（2026-10-14 产品维度升级收口 §三/§10 接口冻结，工作区 C 部署核验面）。

零 API、零云端连接、零密值：_StubCloud 按 CMD 特征串注入预置响应（与
Cloud.run 同签名），只测判定分支与 --dry-run 四场景形态（内置 fixture，
报告落 /tmp 不入仓）。鸡生蛋纪律：本测先写、deploy_check.py 后改。

两新项=「程序呈现、不阻断」级（§六分级：WARN/INFO 不入 has_fail，**绝不
产生 FAIL**——SLA 开窗与否/预算调线由用户裁定，程序只呈现）。

⑪ 覆盖：FORMAL 达标=INFO / INSUFFICIENT=WARN+SLA_UNKNOWN / 缺期（最新档
距今>14 天=缺期≥2）=WARN+SLA_UNKNOWN / json 损坏（含顶层非对象）=WARN /
核心字段缺=WARN / sla_state 非法=WARN / 期数倒退=WARN / OBSERVING=WARN
观察期读数 / FORMAL 连续未达=WARN「连续未达 N 期，开窗时由用户裁定」/
p95>8000ms 与成功率<95% 同未达分支 / 观测未起=INFO「首窗周五 08:30」/
取数通道失败=WARN 不红；
⑫ 覆盖：达标（True/40.0/50.0=本专项拨键口径 §五）=INFO / 值不符=WARN /
坏值=WARN / 缺键=WARN / budget≥cap（预警线触到熔断线）=WARN / 取数通道
失败=WARN 不红；
fixture 分发：CMD_OBS_SLA/CMD_EMBEDBUDGET 三场景路由 + ⑫ 安全红线（命令
=远端 python3 三键提取、绝不 cat 整个 config.json；fixture 同理只含三键行）；
dry-run 四场景：ok/ok-off（⑪INFO 观测未起+⑫INFO 达标、FAIL=0、汇总零
WARN——与既往汇总行形态一致）/ oldver（⑪INFO+⑫WARN 缺键）/ offline（⑪⑫
双 WARN 取数通道、不崩）。

运行：<repo>/venv/bin/python -m pytest tests/test_deploy_check_sla_budget.py -v
   或 python3 <repo>/tests/test_deploy_check_sla_budget.py -v
"""
import contextlib
import io
import json
import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import deploy_check as dc  # noqa: E402

# 判定注入用"现在"（缺期分支确定性：最新档 2026-10-09 距今 5 天=新鲜，
# 2026-09-11 距今 33 天=缺期≥2）
NOW = datetime(2026, 10, 14)


class _StubCloud:
    """按命令特征串返回预置响应（与 Cloud.run 同签名，零云端连接）。"""

    def __init__(self, mapping):
        self.mapping = mapping

    def run(self, cmd, timeout=60, stdin_data=None):
        for key, resp in self.mapping.items():
            if key in cmd:
                return resp
        return 0, "", ""


def run_check(fn, *args, **kwargs):
    """单 check 函数 → (Report, 该编号结果)；stdout 静音。"""
    rep = dc.Report()
    with contextlib.redirect_stdout(io.StringIO()):
        fn(rep, *args, **kwargs)
    return rep, rep.results[-1]


def _obs_body(**over):
    """§10 冻结 schema 的完整机读档样例（FORMAL 达标基线，可覆写突变）。"""
    d = {"period": "2026-10-09", "sample_total": 61, "ops": 9, "real": 52,
         "unknown": 0, "bot": 0, "success_count": 50, "fail_count": 1,
         "cancelled": 1, "success_rate": 0.962, "p50_ms": 1234,
         "p95_ms": 6120, "p99_ms": 8800, "sla_state": "FORMAL",
         "consecutive_miss": 0, "formal_since": "2026-09-25",
         "metric_version": "ttfb-v1", "identity_rules_version": "id-r-v1"}
    d.update(over)
    return d


def _obs_resp(filenames, body_dict=None, body_text=None):
    """构造 CMD_OBS_SLA 输出：ls 段（次新在前、最新在后）+ __OBSLAT__ + cat 段。"""
    listing = "".join(f + "\n" for f in filenames)
    if body_text is None:
        body_text = json.dumps(_obs_body(**(body_dict or {})), ensure_ascii=False)
    return (0, listing + "__OBSLAT__\n" + body_text + "\n", "")


# ----------------------------- ⑪ SLA 状态机读数 -----------------------------
class TestCheckSlaStatus(unittest.TestCase):
    """⑪ 各定级分支（判据=执行计划 §三 + 2026-10-14 任务书）：全分支状态
    ∈ {INFO, WARN}——程序呈现级，绝不 FAIL。"""

    def sla(self, resp, now=NOW):
        return run_check(dc.check_sla_status,
                         _StubCloud({"obs-latency-自动": resp}), now)

    def test_formal_met_info(self):
        """FORMAL 且达标（p95≤8s/成功率≥95%/零连续未达）→ INFO；evidence 呈现
        截至期号（文件名日期）/真实样本/成功率/p50/p95/p99/状态机态/
        consecutive_miss/formal_since/次新档，无 SLA_UNKNOWN。"""
        rep, r = self.sla(_obs_resp(["obs-latency-自动-20261002.json",
                                     "obs-latency-自动-20261009.json"]))
        self.assertEqual(r[0], "⑪")
        self.assertEqual(r[2], "INFO")
        self.assertFalse(rep.has_fail())
        ev = "\n".join(r[3])
        for frag in ("截至期号=2026-10-09", "次新", "real=52", "sample_total=61",
                     "success_rate=0.962", "p50=1234ms", "p95=6120ms",
                     "p99=8800ms", "sla_state=FORMAL", "consecutive_miss=0",
                     "formal_since=2026-09-25"):
            self.assertIn(frag, ev, frag)
        self.assertNotIn("SLA_UNKNOWN", ev)

    def test_insufficient_warn_sla_unknown(self):
        """INSUFFICIENT（真实样本<30）→ WARN + SLA_UNKNOWN（读数不可判）。"""
        rep, r = self.sla(_obs_resp(["obs-latency-自动-20261009.json"],
                                    {"sla_state": "INSUFFICIENT", "real": 12,
                                     "sample_total": 15, "formal_since": None}))
        self.assertEqual(r[2], "WARN")
        self.assertFalse(rep.has_fail())
        ev = "\n".join(r[3])
        self.assertIn("SLA_UNKNOWN", ev)
        self.assertTrue(any("样本不足" in h for h in r[4]), r[4])

    def test_stale_file_warn_missing_periods(self):
        """最新档距今>14 天（周报节奏缺期≥2）→ WARN + SLA_UNKNOWN（即便档内
        读数本身 FORMAL 达标——缺期优先，读数不代表当前）。"""
        rep, r = self.sla(_obs_resp(["obs-latency-自动-20260904.json",
                                     "obs-latency-自动-20260911.json"]))
        self.assertEqual(r[2], "WARN")
        self.assertFalse(rep.has_fail())
        ev = "\n".join(r[3])
        self.assertIn("SLA_UNKNOWN", ev)
        self.assertIn("缺期", ev)
        self.assertTrue(any("缺期" in h for h in r[4]), r[4])

    def test_corrupt_json_warn(self):
        """json 损坏（不可解析）→ WARN + SLA_UNKNOWN。"""
        rep, r = self.sla(_obs_resp(["obs-latency-自动-20261009.json"],
                                    body_text="{broken json"))
        self.assertEqual(r[2], "WARN")
        self.assertFalse(rep.has_fail())
        ev = "\n".join(r[3])
        self.assertIn("SLA_UNKNOWN", ev)
        self.assertIn("损坏", ev)

    def test_toplevel_not_object_warn(self):
        """json 顶层非对象（如数组）→ 同损坏分支 WARN。"""
        _, r = self.sla(_obs_resp(["obs-latency-自动-20261009.json"],
                                  body_text="[1, 2, 3]"))
        self.assertEqual(r[2], "WARN")
        self.assertIn("SLA_UNKNOWN", "\n".join(r[3]))

    def test_missing_core_field_warn(self):
        """核心字段缺（§10 schema 判读所需面）→ WARN + SLA_UNKNOWN 且点名缺键。"""
        d = _obs_body()
        del d["p99_ms"]
        rep, r = self.sla(_obs_resp(["obs-latency-自动-20261009.json"],
                                    body_text=json.dumps(d, ensure_ascii=False)))
        self.assertEqual(r[2], "WARN")
        self.assertFalse(rep.has_fail())
        ev = "\n".join(r[3])
        self.assertIn("SLA_UNKNOWN", ev)
        self.assertIn("p99_ms", ev)

    def test_illegal_sla_state_warn(self):
        """sla_state 非三态枚举值 → WARN + SLA_UNKNOWN（状态机态非法）。"""
        _, r = self.sla(_obs_resp(["obs-latency-自动-20261009.json"],
                                  {"sla_state": "WEIRD"}))
        self.assertEqual(r[2], "WARN")
        ev = "\n".join(r[3])
        self.assertIn("SLA_UNKNOWN", ev)
        self.assertIn("WEIRD", ev)

    def test_period_regression_warn(self):
        """期数倒退（最新档 json period 早于次新档文件名日期）→ WARN（§三：
        期数倒退=WARN——读数序不可信）。"""
        rep, r = self.sla(_obs_resp(["obs-latency-自动-20261002.json",
                                     "obs-latency-自动-20261009.json"],
                                    {"period": "2026-09-25"}))
        self.assertEqual(r[2], "WARN")
        self.assertFalse(rep.has_fail())
        self.assertIn("倒退", "\n".join(r[3]))

    def test_observing_warn_reading_level(self):
        """OBSERVING（真实样本 30–99）→ WARN 观察期读数级（§二：观察=WARN 级
        读数）——有读数故不标 SLA_UNKNOWN。"""
        rep, r = self.sla(_obs_resp(["obs-latency-自动-20261009.json"],
                                    {"sla_state": "OBSERVING", "real": 45,
                                     "formal_since": None}))
        self.assertEqual(r[2], "WARN")
        self.assertFalse(rep.has_fail())
        self.assertNotIn("SLA_UNKNOWN", "\n".join(r[3]))
        self.assertTrue(any("观察" in h for h in r[4]), r[4])

    def test_consecutive_miss_warn_user_decides(self):
        """FORMAL 且 consecutive_miss≥1 → WARN 且标「连续未达 N 期，开窗时由
        用户裁定」。"""
        rep, r = self.sla(_obs_resp(["obs-latency-自动-20261009.json"],
                                    {"consecutive_miss": 2}))
        self.assertEqual(r[2], "WARN")
        self.assertFalse(rep.has_fail())
        ev = "\n".join(r[3])
        self.assertIn("连续未达 2 期", ev)
        self.assertIn("用户裁定", ev)

    def test_p95_over_line_warn(self):
        """FORMAL 且 p95>8000ms（consecutive_miss=0）→ 同未达分支 WARN（SLA
        承诺线 p95≤8s，§0 基线2），标用户裁定。"""
        rep, r = self.sla(_obs_resp(["obs-latency-自动-20261009.json"],
                                    {"p95_ms": 9500}))
        self.assertEqual(r[2], "WARN")
        ev = "\n".join(r[3])
        self.assertIn("用户裁定", ev)
        self.assertIn("9500", ev)

    def test_success_rate_below_line_warn(self):
        """FORMAL 且成功率<95% → 同未达分支 WARN（§0 基线2 成功率线）。"""
        rep, r = self.sla(_obs_resp(["obs-latency-自动-20261009.json"],
                                    {"success_rate": 0.90}))
        self.assertEqual(r[2], "WARN")
        self.assertIn("用户裁定", "\n".join(r[3]))

    def test_not_started_info(self):
        """云端尚无任何 obs-latency json（脚本刚上云首窗未跑）→ INFO「SLA
        观测未起（首窗周五 08:30）」。"""
        rep, r = self.sla((0, "__OBSLAT__\n", ""))
        self.assertEqual(r[2], "INFO")
        self.assertFalse(rep.has_fail())
        ev = "\n".join(list(r[3]) + list(r[4]))
        self.assertIn("观测未起", ev)
        self.assertIn("首窗周五 08:30", ev)

    def test_channel_fail_warn_not_red(self):
        """取数通道失败（SSH 不可达）→ WARN + SLA_UNKNOWN（呈现级不阻断，
        不产生 FAIL——与 ⑨ 通道 FAIL 哲学分开，§六分级）。"""
        rep, r = self.sla((255, "", "ssh: connect to host root@203.0.113.9 "
                                    "port 22: Connection timed out"))
        self.assertEqual(r[2], "WARN")
        self.assertFalse(rep.has_fail())
        ev = "\n".join(r[3])
        self.assertIn("SLA_UNKNOWN", ev)
        self.assertTrue(any("取数通道" in h for h in r[4]), r[4])

    def test_all_branches_never_fail(self):
        """元断言：⑪ 全分支状态 ∈ {INFO, WARN}——「绝不产生 FAIL」的测试面。"""
        branches = [
            _obs_resp(["obs-latency-自动-20261009.json"]),                       # FORMAL 达标
            _obs_resp(["obs-latency-自动-20261009.json"],
                      {"sla_state": "INSUFFICIENT", "real": 5, "sample_total": 6}),  # 样本不足
            _obs_resp(["obs-latency-自动-20260911.json"]),                       # 缺期
            _obs_resp(["obs-latency-自动-20261009.json"], body_text="{bad"),     # 损坏
            _obs_resp(["obs-latency-自动-20261009.json"],
                      {"sla_state": "OBSERVING", "real": 45}),                   # 观察
            _obs_resp(["obs-latency-自动-20261009.json"],
                      {"consecutive_miss": 3}),                                  # 连续未达
            (0, "__OBSLAT__\n", ""),                                             # 未起
            (255, "", "ssh timed out"),                                          # 通道
        ]
        for resp in branches:
            _, r = self.sla(resp)
            self.assertIn(r[2], ("INFO", "WARN"), resp)


# ----------------------------- ⑫ 嵌入预算拨键呈现 -----------------------------
class TestCheckEmbedBudget(unittest.TestCase):
    """⑫ 各分支（判据=执行计划 §三/§五 + 任务书）：全分支状态 ∈ {INFO, WARN}。"""

    def bud(self, resp):
        return run_check(dc.check_embed_budget,
                         _StubCloud({"embed_monthly_budget_enabled": resp}))

    @staticmethod
    def lines(enabled="True", budget="40.0", cap="50.0"):
        return (0, "embed_monthly_budget_enabled=%s\n"
                   "embed_monthly_budget_cny=%s\n"
                   "embed_monthly_cap_cny=%s\n" % (enabled, budget, cap), "")

    def test_match_info(self):
        """达标（enabled=true/budget=40.0/cap=50.0=本专项拨键口径）→ INFO；
        evidence 呈现三键现值+配置来源路径，提示含预警/熔断语义。"""
        rep, r = self.bud(self.lines())
        self.assertEqual(r[0], "⑫")
        self.assertEqual(r[2], "INFO")
        self.assertFalse(rep.has_fail())
        ev = "\n".join(r[3])
        self.assertIn("/opt/qa-bot/config.json", ev)
        for frag in ("embed_monthly_budget_enabled=True",
                     "embed_monthly_budget_cny=40.0",
                     "embed_monthly_cap_cny=50.0"):
            self.assertIn(frag, ev, frag)
        self.assertTrue(any("预警" in h and "熔断" in h for h in r[4]), r[4])

    def test_value_mismatch_warn(self):
        """值不符（budget=25 非本专项拨键口径 40）→ WARN 且点名期望值。"""
        rep, r = self.bud(self.lines(budget="25.0"))
        self.assertEqual(r[2], "WARN")
        self.assertFalse(rep.has_fail())
        ev = "\n".join(r[3])
        self.assertIn("25.0", ev)
        self.assertIn("40.0", ev)

    def test_enabled_false_warn(self):
        """enabled=false（预算闸整体关闭）→ WARN 值不符（期望 true）。"""
        _, r = self.bud(self.lines(enabled="False"))
        self.assertEqual(r[2], "WARN")
        self.assertIn("embed_monthly_budget_enabled=False", "\n".join(r[3]))

    def test_bad_value_warn(self):
        """坏值（cny 非数值）→ WARN。"""
        rep, r = self.bud(self.lines(budget="abc"))
        self.assertEqual(r[2], "WARN")
        self.assertFalse(rep.has_fail())
        self.assertIn("坏值", "\n".join(r[3]))

    def test_missing_key_warn(self):
        """缺键（rag 段无 cny 键——输出行缺）→ WARN 且点名缺键。"""
        out = ("embed_monthly_budget_enabled=True\n"
               "embed_monthly_cap_cny=50.0\n")
        rep, r = self.bud((0, out, ""))
        self.assertEqual(r[2], "WARN")
        self.assertFalse(rep.has_fail())
        ev = "\n".join(r[3])
        self.assertIn("缺键", ev)
        self.assertIn("embed_monthly_budget_cny", ev)

    def test_absent_marker_warn(self):
        """三键全 absent（旧版 config 无预算键）→ WARN 缺键。"""
        rep, r = self.bud(self.lines(enabled="<absent>", budget="<absent>",
                                     cap="<absent>"))
        self.assertEqual(r[2], "WARN")
        self.assertFalse(rep.has_fail())
        self.assertIn("缺键", "\n".join(r[3]))

    def test_budget_ge_cap_warn(self):
        """budget≥cap（预警线触到熔断线，拨键语义失效）→ WARN——即使数值
        恰与 40/50 口径无关也须点名语义矛盾。"""
        rep, r = self.bud(self.lines(budget="50.0", cap="50.0"))
        self.assertEqual(r[2], "WARN")
        self.assertFalse(rep.has_fail())
        ev = "\n".join(r[3])
        self.assertIn("≥", ev)
        self.assertTrue(any("语义" in h for h in r[4]), r[4])

    def test_channel_fail_warn_not_red(self):
        """取数通道失败 → WARN（呈现级不阻断，不产生 FAIL）。"""
        rep, r = self.bud((255, "", "ssh: connect timed out"))
        self.assertEqual(r[2], "WARN")
        self.assertFalse(rep.has_fail())
        self.assertTrue(any("取数通道" in h for h in r[4]), r[4])

    def test_all_branches_never_fail(self):
        """元断言：⑫ 全分支状态 ∈ {INFO, WARN}——「绝不产生 FAIL」的测试面。"""
        for resp in (self.lines(), self.lines(budget="25.0"),
                     self.lines(enabled="False"), self.lines(budget="abc"),
                     self.lines(budget="50.0", cap="50.0"),
                     (255, "", "ssh timed out")):
            _, r = self.bud(resp)
            self.assertIn(r[2], ("INFO", "WARN"), resp)


# ----------------------------- fixture 分发与安全红线 -----------------------------
class TestFixtureDispatchAndSafety(unittest.TestCase):
    """CMD_OBS_SLA/CMD_EMBEDBUDGET 的 dry-run 分发路径 + ⑫ 密件红线。"""

    def test_obs_sla_routed_all_scenarios(self):
        """三场景 CMD_OBS_SLA 均路由到 obslat fixture（不落空返回兜底）；
        ok/ok-off/oldver=观测未起（无档，部署窗口预期基线）。"""
        for scen in ("ok", "ok-off", "oldver"):
            rc, out, err = dc.Cloud(scenario=scen).run(dc.CMD_OBS_SLA)
            self.assertEqual(rc, 0, scen)
            self.assertIn("__OBSLAT__", out, scen)
            before, _sep, after = out.partition("__OBSLAT__")
            self.assertEqual(before.strip(), "", scen)   # 无档 → 观测未起
            self.assertEqual(after.strip(), "", scen)

    def test_embed_budget_routed_ok_and_oldver(self):
        """ok/ok-off 路由到三键达标 fixture；oldver 路由到三键 absent。"""
        for scen in ("ok", "ok-off"):
            rc, out, err = dc.Cloud(scenario=scen).run(dc.CMD_EMBEDBUDGET)
            self.assertEqual(rc, 0, scen)
            self.assertIn("embed_monthly_budget_enabled=True", out, scen)
            self.assertIn("embed_monthly_budget_cny=40.0", out, scen)
            self.assertIn("embed_monthly_cap_cny=50.0", out, scen)
        rc, out, err = dc.Cloud(scenario="oldver").run(dc.CMD_EMBEDBUDGET)
        self.assertEqual(rc, 0)
        self.assertEqual(out.count("<absent>"), 3)

    def test_embed_budget_command_never_cats_config(self):
        """⑫ 安全红线：远端命令=python3 -c 三键提取，绝不 cat 整个
        config.json（含密件）。"""
        self.assertIn("python3 -c", dc.CMD_EMBEDBUDGET)
        self.assertIn("json.load", dc.CMD_EMBEDBUDGET)
        self.assertNotIn("cat ", dc.CMD_EMBEDBUDGET)
        self.assertNotIn("passcode", dc.CMD_EMBEDBUDGET)

    def test_embed_budget_fixture_only_three_keys(self):
        """⑫ fixture 同理只含三键行——任何场景的 embedbudget 输出除三键外
        零其他 config 键（密件纪律）。"""
        allowed = {"embed_monthly_budget_enabled",
                   "embed_monthly_budget_cny", "embed_monthly_cap_cny"}
        for scen, fx in dc.FIXTURES.items():
            keys = {line.split("=", 1)[0]
                    for line in fx["embedbudget"][1].splitlines() if line.strip()}
            self.assertEqual(keys, allowed, scen)

    def test_obs_sla_command_readonly_shape(self):
        """⑪ 命令形态：ls -1 排序取最新+次新 + cat 最新（任务书口径），
        路径锚 /opt/qa-bot/建库/logs/。"""
        self.assertIn("ls -1", dc.CMD_OBS_SLA)
        self.assertIn("tail -n 2", dc.CMD_OBS_SLA)
        self.assertIn("cat ", dc.CMD_OBS_SLA)
        self.assertIn("/opt/qa-bot/建库/logs/", dc.CMD_OBS_SLA)
        self.assertIn("__OBSLAT__", dc.CMD_OBS_SLA)


# ----------------------------- dry-run 四场景 -----------------------------
class TestDryRunSlaAndBudget(unittest.TestCase):
    """既有 --dry-run 自测形态补两新项：ok/ok-off 全绿退出码 0（⑪ INFO 观测
    未起+⑫ INFO 达标，汇总零 WARN——与既往汇总行形态一致）；oldver ⑫ 缺键
    WARN；offline ⑪⑫ 双 WARN 取数通道不崩。"""

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

    def test_ok_scenario_new_items_info(self):
        rc, out = self.dry("--dry-run=ok", "--expect-loaded=0")
        self.assertEqual(rc, 0, out[-800:])
        self.assertIn("## ⑪ SLA 状态机读数（obs-latency-自动-*.json 最新档） — INFO", out)
        self.assertIn("观测未起", out)
        self.assertIn("首窗周五 08:30", out)
        self.assertIn("## ⑫ 嵌入预算拨键呈现（config rag 段预算三键） — INFO", out)
        self.assertIn("FAIL=0", out)
        # 报告头命令清单补行：⑪⑫ 两条只读命令在列（__OBSLAT__ 分隔符为证）
        self.assertIn("__OBSLAT__", out)
        self.assertIn("embed_monthly_budget_enabled", out)
        # ok 场景 ⑪⑫ 均 INFO → 汇总行零 WARN 段（与既往逐字节一致）
        summary = next(line for line in out.splitlines() if line.startswith("## 汇总："))
        self.assertNotIn("WARN=", summary)

    def test_ok_off_scenario_new_items_info(self):
        rc, out = self.dry("--dry-run=ok-off", "--hybrid-off", "--expect-loaded=0")
        self.assertEqual(rc, 0, out[-800:])
        self.assertIn("## ⑪ SLA 状态机读数（obs-latency-自动-*.json 最新档） — INFO", out)
        self.assertIn("## ⑫ 嵌入预算拨键呈现（config rag 段预算三键） — INFO", out)
        self.assertIn("FAIL=0", out)

    def test_oldver_scenario_budget_missing_warn(self):
        rc, out = self.dry("--dry-run=oldver")
        self.assertEqual(rc, 1)
        self.assertIn("## ⑪ SLA 状态机读数（obs-latency-自动-*.json 最新档） — INFO", out)
        self.assertIn("## ⑫ 嵌入预算拨键呈现（config rag 段预算三键） — WARN", out)
        self.assertIn("缺键", out)

    def test_offline_scenario_channel_warn_no_crash(self):
        rc, out = self.dry("--dry-run=offline")
        self.assertEqual(rc, 1)
        self.assertIn("## ⑪ SLA 状态机读数（obs-latency-自动-*.json 最新档） — WARN", out)
        self.assertIn("SLA_UNKNOWN", out)
        self.assertIn("## ⑫ 嵌入预算拨键呈现（config rag 段预算三键） — WARN", out)


if __name__ == "__main__":
    unittest.main()
