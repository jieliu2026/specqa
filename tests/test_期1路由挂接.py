# -*- coding: utf-8 -*-
"""期 1 路由分类器挂接单测（2026-09-29 施工；设计稿 运营/设计稿-分层放行与路由
-20260929.md §2.3"实现挂点"+§2.4 硬门控；批档 D1-D9=过程日志三节 9）。

五组断言面：
1. server 关断零漂移（route_enabled=false：无 rt= 键/无 [rag-route] 行/trace
   gate_detail 无 route 键/retrieve 单参调用）与开态三观测面（rt= 键、
   [rag-route] 打点行不含题面、trace route 键）；
2. rag 选席约束（域面收窄生效）/检索后兜底（候选<topk 或域内最大余弦<0.40 →
   回退全量+fallback=1 打点）/mq 变体继承（各路同一份 route_res 不重复分类）；
3. config 坏值回默认（clean_route_params：min_confidence/conflict_policy/
   vocab/light_topk/table_facet/doc_direct）；
4. veto 服务端反例（G07 型"精确表/参数题伪装概念题"≥10 条，拦截率 100%——
   §2.4 硬门控测试断言面；词表本体零改动=D9）；
5. 契约防御位（veto=1 时 doc_direct 仅观测禁收窄；route 键唯一生效面）。

判定器/词表零依赖网络：全部离线夹具（先例=tests/test_server_rag.py 伪上游、
tests/test_rag.py write_fixture）。
"""
import contextlib
import io
import json
import os
import tempfile
import unittest
from unittest import mock

import httpx
from fastapi.testclient import TestClient

import rag
import route_domain
import server  # 仓根模块（tests/__init__.py 已做 sys.path 引导）
from tests.test_rag import QUERY, write_fixture

CONCEPT_RES = route_domain.classify("什么是切换")          # route=domain 概念
VETO_RES = route_domain.classify("T310 定时器的默认值是多少")  # veto=1 fallback
DOC_RES = route_domain.classify("TS 38.331 里说了什么")     # route=doc_direct
ON_PARAMS = rag.clean_route_params(dict(rag.DEFAULT_RAG_CONFIG, route_enabled=True))


def _hit(rank, score, doc_id, rid=None, chunk_type="clause", corpus_type="",
         source_domain=""):
    rec = {"id": rid or f"{doc_id}#{rank}", "doc_id": doc_id, "version": "V",
           "locator": "§1", "content": "内容", "chunk_type": chunk_type,
           "corpus_type": corpus_type, "source_domain": source_domain}
    return {"rank": rank, "score": score, "rec": rec}


# ---------------------------------------------------------------------------
# 组 3：config 坏值回默认（clean_route_params 一把尺）
# ---------------------------------------------------------------------------
class CleanRouteParamsTest(unittest.TestCase):
    def test_defaults_all_off(self):
        p = rag.clean_route_params(dict(rag.DEFAULT_RAG_CONFIG))
        self.assertEqual(p, {"enabled": False, "min_confidence": 1,
                             "policy": "fallback", "vocab": None,
                             "light_topk": 3, "table_facet": False,
                             "doc_direct": True})

    def test_bad_values_fall_back_to_defaults(self):
        bad = dict(rag.DEFAULT_RAG_CONFIG, route_enabled=True,
                   route_min_confidence="坏值", route_conflict_policy="priority",
                   route_vocab="不是list", route_light_topk=-2,
                   route_table_facet="", route_doc_direct=None)
        p = rag.clean_route_params(bad)
        self.assertTrue(p["enabled"])
        self.assertEqual(p["min_confidence"], 1)      # 坏值回 1
        self.assertEqual(p["policy"], "fallback")     # D5：priority 未启用一律回 fallback
        self.assertIsNone(p["vocab"])                 # 坏值回 null=内置词表
        self.assertEqual(p["light_topk"], 3)          # 越界回默认（下限钳 1 后仍回 3 档）
        self.assertFalse(p["table_facet"])
        self.assertFalse(p["doc_direct"])             # None=bool 假值=关

    def test_min_confidence_floor_and_numeric(self):
        p = rag.clean_route_params(dict(rag.DEFAULT_RAG_CONFIG,
                                        route_min_confidence=0))
        self.assertEqual(p["min_confidence"], 1)      # 下限钳 1
        p = rag.clean_route_params(dict(rag.DEFAULT_RAG_CONFIG,
                                        route_min_confidence=3))
        self.assertEqual(p["min_confidence"], 3)

    def test_vocab_list_of_str_preserved(self):
        p = rag.clean_route_params(dict(rag.DEFAULT_RAG_CONFIG,
                                        route_vocab=["a", "b"]))
        self.assertEqual(p["vocab"], ["a", "b"])      # 合法 list 透传（期 1 观测位）
        p = rag.clean_route_params(dict(rag.DEFAULT_RAG_CONFIG,
                                        route_vocab=[1, "a"]))
        self.assertIsNone(p["vocab"])                 # 含非 str 元素=坏值回 null

    def test_initialize_normalizes_route_keys(self):
        with tempfile.TemporaryDirectory() as td:
            store = os.path.join(td, "embeddings.jsonl")
            write_fixture(store)
            logs = []
            svc = rag.RagService(embed_fn=lambda q: list(QUERY), log=logs.append)
            svc.initialize({"store_path": store, "route_enabled": True,
                            "route_min_confidence": "x",
                            "route_conflict_policy": "priority"})
            self.assertTrue(svc._route["enabled"])
            self.assertEqual(svc._route["min_confidence"], 1)
            self.assertEqual(svc._route["policy"], "fallback")

    def test_route_enabled_without_module_degrades_off(self):
        p = rag.clean_route_params(dict(rag.DEFAULT_RAG_CONFIG, route_enabled=True))
        self.assertTrue(p["enabled"])                 # 模块在位=开
        with mock.patch.object(rag, "route_domain", None):
            p = rag.clean_route_params(dict(rag.DEFAULT_RAG_CONFIG,
                                            route_enabled=True))
            self.assertFalse(p["enabled"])            # 模块缺席=退关零收窄


# ---------------------------------------------------------------------------
# 组 5：契约防御位（route_constraint / route_rec_in）
# ---------------------------------------------------------------------------
class RouteConstraintContractTest(unittest.TestCase):
    def test_off_params_never_constrain(self):
        off = rag.clean_route_params(dict(rag.DEFAULT_RAG_CONFIG))
        self.assertIsNone(rag.route_constraint(off, CONCEPT_RES))
        self.assertIsNone(rag.route_constraint(off, DOC_RES))

    def test_route_key_is_the_only_effective_face(self):
        self.assertEqual(rag.route_constraint(ON_PARAMS, CONCEPT_RES),
                         ("domain", "概念"))
        self.assertEqual(rag.route_constraint(ON_PARAMS, DOC_RES),
                         ("doc", "TS 38.331"))
        self.assertIsNone(rag.route_constraint(ON_PARAMS, VETO_RES))

    def test_veto_doc_direct_observation_only(self):
        # §2.4：veto=1 时 doc_direct 仅观测禁收窄——手工构造不一致输入同样零收窄
        forged = dict(DOC_RES, veto=1, route="doc_direct")
        self.assertIsNone(rag.route_constraint(ON_PARAMS, forged))

    def test_fallback_and_garbage_inputs(self):
        self.assertIsNone(rag.route_constraint(ON_PARAMS, None))
        self.assertIsNone(rag.route_constraint(ON_PARAMS, "不是dict"))
        self.assertIsNone(rag.route_constraint(ON_PARAMS, {}))
        self.assertIsNone(rag.route_constraint(ON_PARAMS,
                                              {"route": "domain", "domain": "外星域"}))
        self.assertIsNone(rag.route_constraint(ON_PARAMS,
                                              {"route": "doc_direct", "doc_direct": ""}))

    def test_rec_in_doc_constraint_exact_match(self):
        c = ("doc", "TS 38.331")
        self.assertTrue(rag.route_rec_in({"doc_id": "TS 38.331"}, c))
        self.assertFalse(rag.route_rec_in({"doc_id": "TS 38.332"}, c))
        self.assertFalse(rag.route_rec_in({}, c))       # 缺字段容错
        self.assertFalse(rag.route_rec_in(None, c))

    def test_rec_in_domain_delegates_doc_in_domain(self):
        c = ("domain", "概念")
        self.assertTrue(rag.route_rec_in({"doc_id": "TR 36.805"}, c))
        self.assertTrue(rag.route_rec_in({"doc_id": "TS 36.805",
                                          "corpus_type": "case_card"}, c))
        self.assertFalse(rag.route_rec_in({"doc_id": "TS 38.331"}, c))

    def test_table_facet_off_means_full_ts_face(self):
        c = ("domain", "精确表")
        plain = {"doc_id": "TS 38.133", "chunk_type": "clause"}
        table = {"doc_id": "TS 38.133", "chunk_type": "table_row_group"}
        # 默认关=TS 全面不细分（防召回损失；细分属期 2 键面）
        self.assertTrue(rag.route_rec_in(plain, c, table_facet=False))
        self.assertTrue(rag.route_rec_in(table, c, table_facet=False))
        # 开=chunk_type 二级细分
        self.assertFalse(rag.route_rec_in(plain, c, table_facet=True))
        self.assertTrue(rag.route_rec_in(table, c, table_facet=True))

    def test_missing_metadata_row_falls_back_to_doc_id(self):
        # 附节不一致 3：1,476 行缺 source_domain/layer/corpus_type——doc_id 兜底
        bare = {"doc_id": "TS 38.133", "id": "x", "chunk_type": "clause"}
        self.assertTrue(rag.route_rec_in(bare, ("domain", "参数")))


# ---------------------------------------------------------------------------
# 组 2：rag 选席约束 / 检索后兜底 / mq 继承
# ---------------------------------------------------------------------------
class RagSeatConstraintTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = os.path.join(self.tmp.name, "embeddings.jsonl")
        write_fixture(self.store)
        self.logs = []
        self.svc = rag.RagService(embed_fn=lambda q: list(QUERY),
                                  log=self.logs.append)
        self.svc.initialize({"store_path": self.store, "topk": 2,
                             "route_enabled": True})

    def tearDown(self):
        self.tmp.cleanup()

    def test_domain_narrowing_selects_in_domain_rows(self):
        hits = [_hit(1, 0.95, "TR 36.805"), _hit(2, 0.90, "TS 38.331"),
                _hit(3, 0.85, "TR 36.806"), _hit(4, 0.80, "TS 38.300"),
                _hit(5, 0.75, "TS 36.805", corpus_type="case_card")]
        out = self.svc._decrowd_assemble("q", hits, 2, truncate=True,
                                         route_res=CONCEPT_RES)
        self.assertEqual([h["rec"]["doc_id"] for h in out],
                         ["TR 36.805", "TR 36.806"])   # TS 正文块让位域面外
        self.assertFalse(any("[rag-route]" in line for line in self.logs))

    def test_route_off_or_fallback_zero_drift(self):
        hits = [_hit(1, 0.95, "TR 36.805"), _hit(2, 0.90, "TS 38.331"),
                _hit(3, 0.85, "TR 36.806")]
        base = self.svc._decrowd_assemble("q", hits, 2, truncate=True)
        off_params = rag.clean_route_params(dict(rag.DEFAULT_RAG_CONFIG))
        with mock.patch.object(self.svc, "_route", off_params):
            same1 = self.svc._decrowd_assemble("q", hits, 2, truncate=True,
                                               route_res=CONCEPT_RES)
        same2 = self.svc._decrowd_assemble("q", hits, 2, truncate=True,
                                           route_res=VETO_RES)  # veto=全量
        ids = lambda hs: [h["rec"]["id"] for h in hs]  # noqa: E731
        self.assertEqual(ids(base), ids(same1))
        self.assertEqual(ids(base), ids(same2))
        self.assertEqual(ids(base), ["TR 36.805#1", "TS 38.331#2"])

    def test_fallback_when_in_domain_below_topk(self):
        hits = [_hit(1, 0.95, "TR 36.805"), _hit(2, 0.90, "TS 38.331"),
                _hit(3, 0.85, "TS 38.300")]
        out = self.svc._decrowd_assemble("q", hits, 2, truncate=True,
                                         route_res=CONCEPT_RES)
        # 域内仅 1 行 < topk=2 → 回退全量（宁多勿漏）+ fallback=1 打点
        self.assertEqual([h["rec"]["doc_id"] for h in out],
                         ["TR 36.805", "TS 38.331"])
        route_lines = [line for line in self.logs if line.startswith("[rag-route]")]
        self.assertEqual(len(route_lines), 1)
        self.assertEqual(route_lines[0],
                         route_domain.format_log_line(dict(CONCEPT_RES,
                                                           fallback=1)))
        self.assertIn("fallback=1", route_lines[0])

    def test_fallback_when_in_domain_max_cosine_below_gate(self):
        hits = [_hit(1, 0.90, "TS 38.331"), _hit(2, 0.80, "TS 38.300"),
                _hit(3, 0.20, "TR 36.805"), _hit(4, 0.10, "TR 36.806")]
        out = self.svc._decrowd_assemble("q", hits, 2, truncate=True,
                                         route_res=CONCEPT_RES)
        # 域内候选足量但最大余弦 0.20 < 0.40 闸值 → 回退全量
        self.assertEqual([h["rec"]["doc_id"] for h in out],
                         ["TS 38.331", "TS 38.300"])
        self.assertIn("fallback=1",
                      [line for line in self.logs if line.startswith("[rag-route]")][0])

    def test_doc_direct_constraint(self):
        hits = [_hit(1, 0.95, "TS 38.331"), _hit(2, 0.90, "TS 38.331"),
                _hit(3, 0.85, "TS 38.300"), _hit(4, 0.80, "TR 36.805")]
        out = self.svc._decrowd_assemble("q", hits, 2, truncate=True,
                                         route_res=DOC_RES)
        self.assertEqual([h["rec"]["doc_id"] for h in out],
                         ["TS 38.331", "TS 38.331"])   # doc 面收窄生效

    def test_mq_depth_path_no_narrowing(self):
        # mq 深度路径（truncate=False）：不选席亦不做域过滤（RRF 融合语义纪律）
        hits = [_hit(1, 0.95, "TS 38.331"), _hit(2, 0.90, "TR 36.805")]
        out = self.svc._decrowd_assemble("q", hits, 2, truncate=False,
                                         keep=2, route_res=CONCEPT_RES)
        self.assertEqual([h["rec"]["doc_id"] for h in out],
                         ["TS 38.331", "TR 36.805"])

    def test_mq_routes_inherit_same_route_res(self):
        svc = rag.RagService(embed_fn=lambda q: list(QUERY), log=lambda line: None,
                             variant_fn=lambda q: ["variant one"])
        svc.initialize({"store_path": self.store, "topk": 2,
                        "mq_enabled": True, "route_enabled": True})
        seen = []
        one = [_hit(1, 0.5, "TS 38.331")]

        def _spy(q, vec, depth=None, route_res=None):
            seen.append(route_res)
            return [dict(h) for h in one]

        with mock.patch.object(svc, "_search_one", side_effect=_spy):
            svc.retrieve("什么是切换", route_res=CONCEPT_RES)
        self.assertEqual(len(seen), 2)                 # 原查询+1 变体两路
        self.assertTrue(all(r is CONCEPT_RES for r in seen))  # 同一份=继承不重复分类

    def test_search_one_passthrough_and_off_state(self):
        # route 关（enabled=false）：_search_one 带 route_res 也与 None 逐位一致
        off = rag.RagService(embed_fn=lambda q: list(QUERY), log=lambda line: None)
        off.initialize({"store_path": self.store, "topk": 2})
        a = off._search_one("q", list(QUERY), route_res=CONCEPT_RES)
        b = off._search_one("q", list(QUERY))
        self.assertEqual([h["rec"]["id"] for h in a], [h["rec"]["id"] for h in b])
        # retrieve 单参兼容（默认 route_res=None）
        self.assertIsNotNone(off.retrieve("问句"))

    def test_search_one_narrows_end_to_end(self):
        # 库内只有 DOC-* 行（全部域外）→ 概念题域面兜底回退全量 + fallback 打点
        self.svc.retrieve("什么是切换", route_res=CONCEPT_RES)
        self.assertTrue(any(line.startswith("[rag-route]") and "fallback=1" in line
                            for line in self.logs))


# ---------------------------------------------------------------------------
# 组 1：server 关断零漂移 + rt= 键 + trace route 键
# ---------------------------------------------------------------------------
class _FakeAsyncStream:
    async def __aenter__(self):
        raise httpx.TimeoutException("stub 上游超时")  # 伪上游：一律超时，零网络

    async def __aexit__(self, *args):
        return False


class _FakeAsyncClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def stream(self, *args, **kwargs):
        return _FakeAsyncStream()


class _OneArgSvc:
    """只实现单参 retrieve 的伪服务：server 若带 route_res 调用即 TypeError →
    rag=miss——关断零漂移的机械证明面。"""
    stats = {}

    def __init__(self):
        self.calls = []

    def retrieve(self, query, route_res=None, history=None):
        self.calls.append(query)
        return ("证据", [{"doc_id": "DOC-1", "version": "V", "locator": "§1",
                          "score": 0.9}])


class _TwoArgSvc:
    stats = {}

    def __init__(self):
        self.route_res = "未调用"

    def retrieve(self, query, route_res=None, history=None):
        self.route_res = route_res
        return ("证据", [{"doc_id": "DOC-1", "version": "V", "locator": "§1",
                          "score": 0.9}])


class ServerRouteHookTest(unittest.TestCase):
    def setUp(self):
        # 限流免疫（2026-10-01 迭代轮）：全套件里前置 /api/chat 测试会打满共享
        # rate_hits 滑窗（同 TestClient 源 IP）致本组 429 假红（过程日志⑫"5 失败
        # 仅首现"真因=测试间限流态污染非时间敏感）。按 server._store 自立约定
        # "mock.patch 换 _store_inst"挂干净临时库：真实 _Store 类零桩，且本组
        # 自身 hits 也不再写回共享库（双向免疫）。
        self._store_tmp = tempfile.TemporaryDirectory()
        self._clean_store = server._Store(os.path.join(self._store_tmp.name, "t.db"))

    def tearDown(self):
        self._store_tmp.cleanup()

    def _post_chat(self, svc, rag_cfg, content="什么是切换"):
        body = {"messages": [{"role": "user", "content": content}],
                "passcode": "pw-test"}  # 测试 CONFIG 明文测试口令，不涉真实口令
        cfg = dict(server.CONFIG, rag=dict(rag_cfg or {}))
        # 认证面修复（2026-10-07 起生产 config 只余哈希三键、无明文 passcode，
        # 直读明文键得空串→401 auth_expired）：剔哈希三键+放明文测试口令——
        # 保留哈希键会走 PBKDF2 比对分支照样 401（先例=test_server_clause_hook
        # .py 的 _cfg）；其余键原样=只动认证面零扰动。
        for k in ("passcode_hash", "passcode_salt", "pbkdf2_iterations"):
            cfg.pop(k, None)
        cfg["passcode"] = "pw-test"
        out = io.StringIO()
        with mock.patch.object(server, "API_KEY", "stub-key"), \
                mock.patch.object(server, "CONFIG", cfg), \
                mock.patch.object(server.httpx, "AsyncClient", _FakeAsyncClient), \
                mock.patch.object(server, "rag_service", svc), \
                mock.patch.object(server, "_store_inst", self._clean_store), \
                contextlib.redirect_stdout(out):
            with TestClient(server.app) as client:
                with client.stream("POST", "/api/chat", json=body) as resp:
                    self.assertEqual(resp.status_code, 200)
                    list(resp.iter_lines())
        return out.getvalue()

    @staticmethod
    def _chat_line(logged):
        return [line for line in logged.splitlines() if line.startswith("[chat]")][0]

    @staticmethod
    def _trace_retrieval(logged):
        for line in logged.splitlines():
            if line.startswith("[trace:") and '"stage":"retrieval"' in line:
                return json.loads(line.split("] ", 1)[1])
        return None

    def test_off_state_zero_drift(self):
        svc = _OneArgSvc()
        logged = self._post_chat(svc, {"enabled": True})   # route 键全缺省=关
        self.assertEqual(svc.calls, ["什么是切换"])          # 单参调用（带参会 TypeError→miss）
        self.assertIn("rag=hit", logged)
        self.assertNotIn(" rt=", logged)                     # [chat] 无 rt= 键
        self.assertNotIn("[rag-route]", logged)              # 无打点行
        gate = self._trace_retrieval(logged)["gate"]
        self.assertNotIn("route", gate)                      # trace 无 route 键
        self.assertEqual(gate, {"state": "hit"})

    def test_off_state_explicit_false_same(self):
        svc = _OneArgSvc()
        logged = self._post_chat(svc, {"enabled": True, "route_enabled": False})
        self.assertNotIn(" rt=", logged)
        self.assertNotIn("[rag-route]", logged)
        self.assertNotIn("route", self._trace_retrieval(logged)["gate"])

    def test_on_state_domain_route_observations(self):
        svc = _TwoArgSvc()
        logged = self._post_chat(svc, {"enabled": True, "route_enabled": True})
        self.assertIn("rag=hit", logged)
        # retrieve 收到 classify 结果（与直接 classify 同判定）
        self.assertIsInstance(svc.route_res, dict)
        self.assertEqual(svc.route_res["route"], "domain")
        self.assertEqual(svc.route_res["domain"], "概念")
        # [rag-route] 打点行=固定格式且不含题面
        route_lines = [line for line in logged.splitlines()
                       if line.startswith("[rag-route]")]
        self.assertEqual(route_lines,
                         [route_domain.format_log_line(svc.route_res)])
        self.assertNotIn("什么是切换", route_lines[0])
        # [chat] 尾 rt= 键
        self.assertIn(" rt=concept:d", self._chat_line(logged))
        # trace gate_detail 增 route 键（紧凑观测面）
        gate = self._trace_retrieval(logged)["gate"]
        self.assertEqual(gate["state"], "hit")
        self.assertEqual(gate["route"], {"route": "domain", "domain": "概念",
                                         "conf": 1, "veto": 0, "fallback": 0,
                                         "doc_direct": None})

    def test_on_state_veto_rt_field(self):
        svc = _TwoArgSvc()
        logged = self._post_chat(svc, {"enabled": True, "route_enabled": True},
                                 content="T310 定时器的默认值是多少")
        self.assertEqual(svc.route_res["veto"], 1)
        self.assertIn(" rt=param:v", self._chat_line(logged))
        self.assertIn("[rag-route] domain=参数", logged)

    def test_on_state_fallback_rt_field(self):
        svc = _TwoArgSvc()
        logged = self._post_chat(svc, {"enabled": True, "route_enabled": True},
                                 content="掉话率的统计口径是什么")  # 口径+概念冲突→fallback
        self.assertEqual(svc.route_res["route"], "fallback")
        chat = self._chat_line(logged)
        self.assertTrue(" rt=-:f" in chat or " rt=kpi:f" in chat
                        or " rt=concept:f" in chat)

    def test_on_state_doc_direct_rt_field(self):
        svc = _TwoArgSvc()
        logged = self._post_chat(svc, {"enabled": True, "route_enabled": True},
                                 content="TS 38.331 里说了什么")
        self.assertEqual(svc.route_res["route"], "doc_direct")
        self.assertIn(" rt=-:doc", self._chat_line(logged))

    def test_bad_config_values_do_not_break_chat(self):
        svc = _TwoArgSvc()
        logged = self._post_chat(svc, {"enabled": True, "route_enabled": True,
                                       "route_min_confidence": "坏值",
                                       "route_conflict_policy": "priority",
                                       "route_doc_direct": "yes"})
        self.assertIn("rag=hit", logged)   # classify 侧坏值清洗恒不抛出
        self.assertIn(" rt=", self._chat_line(logged))


class RouteRtFieldTest(unittest.TestCase):
    """_route_rt_field 纯函数：域简写×态面全形。"""

    def test_shapes(self):
        self.assertEqual(server._route_rt_field(CONCEPT_RES), "concept:d")
        self.assertEqual(server._route_rt_field(VETO_RES), "param:v")
        self.assertEqual(server._route_rt_field(DOC_RES), "-:doc")
        self.assertEqual(server._route_rt_field(None), "-:f")
        self.assertEqual(server._route_rt_field({}), "-:f")
        koujing = route_domain.classify("KPI 指标的计算公式面怎么理解")
        rt = server._route_rt_field(koujing)
        self.assertTrue(rt.endswith(":d") or rt.endswith(":f"))

    def test_route_config_defaults_off(self):
        rc = server._route_config({})
        self.assertFalse(rc["enabled"])
        rc = server._route_config({"rag": {"route_enabled": True}})
        self.assertTrue(rc["enabled"])
        self.assertEqual(rc["min_confidence"], 1)
        self.assertEqual(rc["conflict_policy"], "fallback")
        self.assertTrue(rc["doc_direct"])


# ---------------------------------------------------------------------------
# 组 4：veto 服务端反例（G07 型，§2.4/§3.3 风险 1 测试断言面；拦截率 100% 硬门）
# ---------------------------------------------------------------------------
class VetoCounterexampleTest(unittest.TestCase):
    """精确表/参数题伪装概念题（表值+是什么/由哪些组成句式混合形态）——G07
    （"SSB 由哪些信号组成"，在册校准案例）必入。全部 veto=1、route=fallback、
    rt= 态面 v、rag 侧零收窄。词表本体零改动（D9）。"""

    COUNTEREXAMPLES = [
        "SSB 由哪些信号组成",                              # G07 原句式（在册校准案例）
        "38.133 附录里 PRB 和带宽的组合对照表是什么内容",     # 表值+是什么
        "T310 定时器的默认值是什么",                         # 参数名+是什么
        "T310 的含义是什么",                               # 参数名+含义（概念词在场仍 veto）
        "N310 的取值范围是什么",
        "小区重选优先级由哪些参数组成",                       # 由哪些…组成
        "随机接入前导格式对照表是什么",
        "A3 事件的触发门限是多少 dB",                        # 数值+单位
        "频段表里 n78 的上下行频率范围是什么",
        "切换迟滞 Hysteresis 的默认值是多少",
        "RSRP 上报值的量化表由哪些档位组成",
        "36.101 的表值是什么",
    ]

    def test_all_counterexamples_vetoed(self):
        self.assertGreaterEqual(len(self.COUNTEREXAMPLES), 10)  # ≥10 条断言面
        for q in self.COUNTEREXAMPLES:
            res = route_domain.classify(q)
            self.assertEqual(res["veto"], 1, q)
            self.assertEqual(res["route"], "fallback", q)
            self.assertEqual(res["fallback"], 1, q)
            # 服务端观测面：rt= 态面 v
            self.assertEqual(server._route_rt_field(q and res)[-2:], ":v", q)
            # rag 侧零收窄（veto 时 doc_direct 仅观测禁收窄的契约同位面）
            self.assertIsNone(rag.route_constraint(ON_PARAMS, res), q)

    def test_g07_specific(self):
        res = route_domain.classify("SSB 由哪些信号组成")
        self.assertEqual(res["veto"], 1)
        self.assertIn("参数", res["domains"])   # 数量疑问词扩充面（由哪些…组成）命中

    def test_high_stakes_subset_property_holds(self):
        # 与 A2 生产口径同源：HIGH_STAKES 命中面 ⊆ veto 面（红线词面单锚性质锁）
        import citation_check
        for q in self.COUNTEREXAMPLES:
            if citation_check.is_high_stakes_question(q):
                self.assertEqual(route_domain.classify(q)["veto"], 1, q)


class CompileTest(unittest.TestCase):
    def test_py_compile(self):
        import py_compile
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for f in ("rag.py", "server.py", "route_domain.py", "citation_check.py"):
            py_compile.compile(os.path.join(root, f), doraise=True)


if __name__ == "__main__":
    unittest.main()
