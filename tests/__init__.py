# -*- coding: utf-8 -*-
"""qa-bot 离线测试包：全部零网络（embed 用 stub/伪 client，不发真实请求）。

sys.path 引导：保证从任意 cwd 都能 `python3 -m unittest` 发现并导入仓根模块。

批2（2026-09-21）：会话/限流持久化落地后，走 /api/chat 的用例会真实写库；
本包导入时把 QABOT_DB_PATH 默认指到一次性临时目录（server.py 导入前生效），
保证测试不污染 data/qa.db 运行密件、也不因 testclient 累计限流行自触发 429。
真实库路径（data/qa.db）只由正式服务进程使用。
"""
import atexit
import os
import shutil
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

if not os.environ.get("QABOT_DB_PATH"):
    _DB_DIR = tempfile.mkdtemp(prefix="qabot-test-db-")
    os.environ["QABOT_DB_PATH"] = os.path.join(_DB_DIR, "qa.db")
    atexit.register(shutil.rmtree, _DB_DIR, ignore_errors=True)


# ---------------------------------------------------------------------------
# chat 型测试限流免疫装饰器（2026-10-02 迭代轮泛化；首案=2026-10-01 路由组
# 429 假红：全套件共享 QABOT_DB_PATH 进程级单例，同 TestClient 源 IP 的
# rate_hits 滑窗会被前置 chat 测试打满，后跑的类误触 429）。用法：
#   @clean_store_tests
#   class MyFlowTest(unittest.TestCase): ...
# 每个测试方法自动挂干净 server._Store（真实类零桩；rate_hits/sessions 双向
# 隔离——本类的灌入也不写回共享库）。限流专测类（test_auth_rate）与自带
# _store_inst 隔离的类勿用，避免盖掉被测对象。
# ---------------------------------------------------------------------------
def clean_store_tests(cls):
    """类装饰器：为类的全部 test_* 方法挂每测干净 _Store（免 setUp 链、零侵入）。"""
    for name in dir(cls):
        if not name.startswith("test"):
            continue
        fn = getattr(cls, name)
        if not callable(fn):
            continue
        setattr(cls, name, _with_clean_store(fn))
    return cls


def _with_clean_store(fn):
    import functools
    import os
    import tempfile
    from unittest import mock

    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        import server
        tmp = tempfile.TemporaryDirectory()
        try:
            with mock.patch.object(server, "_store_inst",
                                   server._Store(os.path.join(tmp.name, "t.db"))):
                return fn(self, *args, **kwargs)
        finally:
            tmp.cleanup()
    return wrapper
