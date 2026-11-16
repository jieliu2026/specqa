# -*- coding: utf-8 -*-
"""GET /api/version 端点单测（基础信息位：无鉴权非敏感，前端/脚本自检用）。
离线零网络零 key。运行：venv/bin/python -m tests.test_version_endpoint
"""
import unittest

from fastapi.testclient import TestClient

import server


class VersionEndpointTest(unittest.TestCase):
    def test_version_shape(self):
        with TestClient(server.app) as client:
            r = client.get("/api/version")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["name"], "specqa")
        self.assertIsInstance(body["version"], str)
        self.assertRegex(body["version"], r"^\d+\.\d+\.\d+$")


if __name__ == "__main__":
    unittest.main(verbosity=2)
