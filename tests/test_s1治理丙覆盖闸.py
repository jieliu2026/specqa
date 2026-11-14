# -*- coding: utf-8 -*-
"""S1 负控治理·丙（off_topic 覆盖闸增强）离线单测（2026-09-28 选项一）。

对象=rag.py cover_gate_miss_words/CoverageMissResult（题面含库外域安全词形而
证据集全部块文本不含该词 → 覆盖闸态，串联在 0.40 低分闸之后不替代）+
server.py coverage_miss 分支（off_topic 事件复用、sources 不下发、[chat] 分态
打点）。样例覆盖：S1V-20 型拦截（卫星·经 vocab 注入——2026-10-24 移词后卫星/
空口/携号转网三词已入库域移出词表，机制回归走注入面）/S1V-17 型拦截（空口·同
前）/宽带装机型拦截（现役词表词）/域内零误拦（词表词与证据同现不触发；裸词
"5G"不在表不触发——B 卷 CSI-RSRP 保护）。移词决策=2026-10-24 用户（施工档=
建库/work/移词施工-20261024/施工报告.md）。
零网络（stub embed_fn+伪上游 httpx）。"""
import asyncio
import contextlib
import io
import json
import os
import tempfile
import unittest
from unittest import mock

import rag
import server  # 仓根模块（tests/__init__.py 已做 sys.path 引导）
from tests import clean_store_tests  # chat 型限流免疫（2026-10-02 迭代轮泛化）

# —— S1V-20 型夹具：同名指标三块满占 top-3（通话中断率族），题面"卫星"全缺 ——
Q_SAT = "卫星通信的通话中断率监管红线是多少"
# —— 现役词表词题面（宽带装机=2026-10-24 移词后仅存词形，0 块真库外）——
Q_BB = "宽带装机时限是多久"
HITS_SAT = [
    {"rank": 1, "score": 0.79, "rec": {"id": "a", "doc_id": "信息产业部令第36号",
     "version": "（2005）", "locator": "附录4 4.2.2 通话中断率 款1",
     "content": "【附录4】\n通话中断率（掉话率）≤5%。"}, "idx": 0},
    {"rank": 2, "score": 0.75, "rec": {"id": "b", "doc_id": "信息产业部令第36号",
     "version": "（2005）", "locator": "附录1 1.2.7 通话中断率 款1",
     "content": "【附录1】\n通话中断率≤5×10⁻³。"}, "idx": 1},
    {"rank": 3, "score": 0.70, "rec": {"id": "c", "doc_id": "信息产业部令第36号",
     "version": "（2005）", "locator": "附录2 2.2.4 通话中断率（掉话率） 款1",
     "content": "【附录2】\n无线信道拥塞期间的通话中断率≤8%。"}, "idx": 2},
]


class CoverGateWordsTest(unittest.TestCase):
    """cover_gate_miss_words：拦截/放行/词表纪律。"""

    def test_satellite_miss_fires(self):
        # 2026-10-24 移词：卫星已入库域（48 块/10 doc）→ 移出词表，缺省不再
        # 触发；机制经 vocab 注入面回归（题面在场∧证据全缺 → 照常触发）
        self.assertNotIn("卫星", rag.COVER_GATE_VOCAB)
        self.assertEqual(rag.cover_gate_miss_words(Q_SAT, HITS_SAT), [])
        self.assertEqual(rag.cover_gate_miss_words(Q_SAT, HITS_SAT, vocab=["卫星"]),
                         ["卫星"])

    def test_air_interface_miss_fires(self):
        # 2026-10-24 移词：空口已入库域（68 块/17 doc）→ 移出词表；机制经注入
        # 面回归（S1V-17 型：证据全缺"空口"，"5G"不在表，只有"空口"触发）
        q = "5G 空口时延 1ms 写在哪个附录"
        self.assertNotIn("空口", rag.COVER_GATE_VOCAB)
        self.assertEqual(rag.cover_gate_miss_words(q, HITS_SAT), [])
        self.assertEqual(rag.cover_gate_miss_words(q, HITS_SAT, vocab=["空口"]),
                         ["空口"])

    def test_portability_removed_broadband_in_vocab(self):
        # 携号转网已入库域（242号全文 20 块）→ 移出（R6b-J067 硬拒形态解除）；
        # 宽带装机 0 块真库外 → 保留为现役词表词
        self.assertNotIn("携号转网", rag.COVER_GATE_VOCAB)
        self.assertIn("宽带装机", rag.COVER_GATE_VOCAB)
        self.assertEqual(rag.cover_gate_miss_words("携号转网生效时长", HITS_SAT), [])
        self.assertEqual(rag.cover_gate_miss_words(Q_BB, HITS_SAT), ["宽带装机"])

    def test_bare_5g_never_fires(self):
        # 域内保护：裸词"5G"不入表（TS 38 语料证据不含"5G"字面，入表即误拦 B 卷）
        self.assertNotIn("5G", rag.COVER_GATE_VOCAB)
        self.assertEqual(rag.cover_gate_miss_words("全国5G基站总数多少", HITS_SAT), [])

    def test_word_in_evidence_passes(self):
        # 域内零误拦：任一块文本含词即放行（须全缺才触发）
        hits = [dict(h) for h in HITS_SAT]
        hits[0]["rec"] = dict(hits[0]["rec"],
                              content="【附录4】\n宽带装机时限与通话中断率≤5%。")
        self.assertEqual(rag.cover_gate_miss_words(Q_BB, hits), [])

    def test_word_in_locator_or_docid_counts(self):
        # 块文本口径=_rec_text（doc_id+version+locator+content 拼接）
        hits = [dict(h) for h in HITS_SAT]
        hits[1]["rec"] = dict(hits[1]["rec"], locator="附录9 9.1 宽带装机 通话中断率")
        self.assertEqual(rag.cover_gate_miss_words(Q_BB, hits), [])

    def test_whitespace_normalization_both_sides(self):
        q = "宽带 装机"
        hits = [dict(h) for h in HITS_SAT]
        hits[0]["rec"] = dict(hits[0]["rec"], content="【附录】\n宽 带装 机时限。")
        self.assertEqual(rag.cover_gate_miss_words(q, hits), [])

    def test_vocab_override(self):
        self.assertEqual(rag.cover_gate_miss_words("北斗短报文覆盖", HITS_SAT,
                                                   vocab=["北斗短报文"]),
                         ["北斗短报文"])
        self.assertEqual(rag.cover_gate_miss_words(Q_SAT, HITS_SAT,
                                                   vocab=["北斗短报文"]), [])

    def test_empty_hits_all_words_fire(self):
        fired = rag.cover_gate_miss_words(Q_BB, [])
        self.assertEqual(fired, ["宽带装机"])  # 无证据=全缺（ retrieve 层不会到这：
        # hits 空早退 None；本例锁定函数级口径）


class CoverageMissResultTest(unittest.TestCase):
    def test_payload_and_repr(self):
        r = rag.CoverageMissResult(["卫星"], 0.7934, 0.40)
        self.assertEqual(r.words, ("卫星",))
        self.assertEqual(r.cosine, 0.7934)
        self.assertEqual(r.threshold, 0.40)
        self.assertIn("卫星", repr(r))
        self.assertIn("0.7934", repr(r))
        self.assertNotIn("key", repr(r).lower())


class RetrieveCoverGateTest(unittest.TestCase):
    """retrieve() 全链：串联 0.40 线之后、开关可关、词表可配。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "embeddings.jsonl")
        with open(self.path, "w", encoding="utf-8") as f:
            for r in (  # 查询向量=[1,0,..]：top1 余弦 1.0（远过 0.40 线）
                {"id": "a", "content": "【附录4】\n通话中断率（掉话率）≤5%。",
                 "doc_id": "信息产业部令第36号", "version": "（2005）",
                 "locator": "附录4 4.2.2 通话中断率 款1",
                 "embedding": [1, 0, 0, 0, 0, 0, 0, 0]},
                {"id": "b", "content": "【附录1】\n通话中断率≤5×10⁻³。",
                 "doc_id": "信息产业部令第36号", "version": "（2005）",
                 "locator": "附录1 1.2.7 通话中断率 款1",
                 "embedding": [0.7, 0.7, 0, 0, 0, 0, 0, 0]},
            ):
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        self.lines = []

    def tearDown(self):
        self.tmp.cleanup()

    def _service(self, **cfg):
        cfg.setdefault("store_path", self.path)
        cfg.setdefault("topk", 2)
        cfg.setdefault("max_context_chars", 6000)
        svc = rag.RagService(embed_fn=lambda q: [1, 0, 0, 0, 0, 0, 0, 0],
                             log=self.lines.append)
        svc.initialize(cfg)
        return svc

    def test_coverage_miss_after_threshold_gate(self):
        # 宽带装机型（现役词表词）：余弦 1.0 过 0.40 线仍被覆盖闸拦（串联不替代）
        svc = self._service()
        r = svc.retrieve(Q_BB)
        self.assertIsInstance(r, rag.CoverageMissResult)
        self.assertEqual(r.words, ("宽带装机",))
        self.assertAlmostEqual(r.cosine, 1.0, places=3)  # 闸前证据集最大余弦
        self.assertEqual(r.threshold, 0.40)
        self.assertTrue(any(ln.startswith("[rag] coverage_miss") for ln in self.lines))
        self.assertFalse(any("low_score" in ln for ln in self.lines))
        # 移词回归（R6b-J067 形态哨兵）：移出词卫星/携号转网题面在场不再拦
        for q in (Q_SAT, "携号转网流程"):
            ev, srcs = svc.retrieve(q)
            self.assertTrue(ev.startswith(rag.EVIDENCE_HEADER))

    def test_word_present_in_store_passes_through(self):
        # 域内零误拦：证据块含词表词（如库扩容后）→ 正常 hit 不拦
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"id": "s", "content": "【附录9】\n宽带装机时限城镇平均≤3日。",
                                "doc_id": "信息产业部令第36号", "version": "（2005）",
                                "locator": "附录9 9.1 宽带装机",
                                "embedding": [0.99, 0.1, 0, 0, 0, 0, 0, 0]},
                               ensure_ascii=False) + "\n")
        svc = self._service()
        ev, srcs = svc.retrieve(Q_BB)
        self.assertTrue(ev.startswith(rag.EVIDENCE_HEADER))

    def test_low_score_takes_precedence(self):
        # 串联序：先 0.40 低分闸（远域题整集余弦低）——LowScoreResult 优先返回
        # （本题面含词表词，若序倒置将误报 coverage_miss——串联序哨兵）
        svc = self._service()
        svc._embed_fn = lambda q: [0, 0, 0, 0, 1, 0, 0, 0]  # 正交：余弦 0
        r = svc.retrieve(Q_BB)
        self.assertIsInstance(r, rag.LowScoreResult)
        self.assertFalse(any("coverage_miss" in ln for ln in self.lines))

    def test_switch_off_disables_gate(self):
        svc = self._service(cover_gate_enabled=False)
        ev, srcs = svc.retrieve(Q_BB)
        self.assertTrue(ev.startswith(rag.EVIDENCE_HEADER))  # 回滚旧行为

    def test_vocab_config_override(self):
        svc = self._service(cover_gate_vocab=["北斗短报文"])
        ev, _ = svc.retrieve(Q_BB)
        self.assertTrue(ev.startswith(rag.EVIDENCE_HEADER))  # 宽带装机已不在生效词表
        self.assertEqual(svc._cfg["cover_gate_vocab"], ["北斗短报文"])

    def test_default_config_on_per_option1(self):
        self.assertTrue(rag.DEFAULT_RAG_CONFIG["cover_gate_enabled"])
        self.assertIsNone(rag.DEFAULT_RAG_CONFIG["cover_gate_vocab"])
        # 2026-10-24 移词后词表=宽带装机单词形（卫星/空口/携号转网已入库域移出）
        self.assertEqual(rag.COVER_GATE_VOCAB, ("宽带装机",))


# ---------- server 面：伪上游（同 test_server_low_score_and_health 口径） ----------
class _OkStream:
    status_code = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def aiter_lines(self):
        for tok in ("语料", "未覆盖"):
            yield "data: " + json.dumps(
                {"choices": [{"delta": {"content": tok}}]}, ensure_ascii=False)
            await asyncio.sleep(0.01)
        yield "data: " + json.dumps({"usage": {"total_tokens": 9}, "choices": []})
        yield "data: [DONE]"

    async def aread(self):
        return b""


class _OkClient:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def stream(self, *a, **k):
        return _OkStream()


class _CovSvc:
    """retrieve 恒回 CoverageMissResult 的桩（S1V-20 型：词=卫星、余弦过线）。"""
    stats = {}

    def retrieve(self, query, route_res=None, history=None):
        return rag.CoverageMissResult(["卫星"], 0.7934, 0.40)


class _HitSvc:
    stats = {}

    def retrieve(self, query, route_res=None, history=None):
        return ("证据", [{"doc_id": "信息产业部令第36号", "version": "（2005）",
                         "locator": "附录4 4.2.2 款1", "score": 0.79}])


_FAKE_CONFIG = {
    "model": "stub-model", "passcode": "pw-test", "bot_name": "测试机",
    "max_history_messages": 40, "max_input_chars": 8000,
    "max_total_input_chars": 24000, "temperature": 0.7, "max_tokens": 100,
    "rate_limit_requests": 20, "rate_limit_window_seconds": 300,
}


def _post_chat(client_cls, svc, messages=None):
    from fastapi.testclient import TestClient
    body = {"messages": messages or [{"role": "user", "content": "卫星通信通话中断率"}],
            "passcode": "pw-test"}
    out = io.StringIO()
    with mock.patch.object(server.httpx, "AsyncClient", client_cls), \
            mock.patch.object(server, "CONFIG", _FAKE_CONFIG), \
            mock.patch.object(server, "API_KEY", "stub-key"), \
            mock.patch.object(server, "rag_service", svc), \
            contextlib.redirect_stdout(out):
        with TestClient(server.app) as client:
            with client.stream("POST", "/api/chat", json=body) as resp:
                assert resp.status_code == 200
                events = [json.loads(ln[5:].strip()) for ln in resp.iter_lines()
                          if ln.startswith("data:")]
    return events, out.getvalue()


@clean_store_tests
class ServerCoverageMissFlowTest(unittest.TestCase):
    def test_off_topic_event_sources_withheld_and_log_state(self):
        events, logged = _post_chat(_OkClient, _CovSvc())
        # 话术批（2026-10-16）：闸触发词"卫星"命中主题映射 → 事件带 note 渠道
        # 引导（words 在手=词形权威口径；事件类型仍复用 off_topic，前端零改契约
        # 破面已随话术批同步两版前端）
        self.assertEqual(events[0], {"type": "off_topic",
                                     "note": "卫星通信（NTN）内容暂未收录，可参考 3GPP NTN 系列规范（TS 38.300 等）"})
        self.assertTrue(events[-1].get("done"))            # 照常裸答流式
        self.assertFalse(any("sources" in e for e in events))  # 不下发 sources
        line = [ln for ln in logged.splitlines() if "[chat]" in ln][0]
        self.assertIn("rag=coverage_miss", line)           # 与 low_score 严格分态
        self.assertNotIn("rag=low_score", line)
        self.assertIn("top1=0.7934", line)                 # 闸前余弦观测口径
        self.assertIn('q="卫星通信通话中断率"', line)
        self.assertNotIn("stub-key", logged)               # 密件纪律

    def test_hit_flow_unaffected(self):
        events, logged = _post_chat(_OkClient, _HitSvc())
        self.assertEqual(events[0].get("sources")[0]["doc_id"], "信息产业部令第36号")
        line = [ln for ln in logged.splitlines() if "[chat]" in ln][0]
        self.assertIn("rag=hit", line)


if __name__ == "__main__":
    unittest.main()
