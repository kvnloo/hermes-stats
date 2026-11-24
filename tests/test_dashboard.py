"""The dashboard tab: dashboard/plugin_api.py serves the client and the same API as `hermes stats serve`.

Needs FastAPI (Hermes ships it); skipped without it. Run: python3 -m unittest discover -s tests
"""

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_stats_adapter import SECRET, _hermes, _voice  # noqa: E402

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover - stdlib-only environment
    FastAPI = TestClient = None

API = Path(__file__).resolve().parents[1] / "dashboard" / "plugin_api.py"
BASE = "/api/plugins/stats"


@unittest.skipIf(FastAPI is None, "FastAPI is not installed")
class DashboardTabTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name) / "hermes"
        voice = Path(cls.tmp.name) / "voice-traces"
        _hermes(root)
        _voice(voice)
        env = {"HERMES_HOME": str(root / "profiles" / "alpha"), "HERMES_MOBILE_VOICE_TRACE_DIR": str(voice)}
        with mock.patch.dict(os.environ, env):
            spec = importlib.util.spec_from_file_location("hermes_dashboard_plugin_stats_test", API)
            assert spec is not None and spec.loader is not None and FastAPI and TestClient
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        app = FastAPI()
        app.include_router(module.router, prefix=BASE)
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_serves_the_client_with_relative_asset_paths(self):
        page = self.client.get(f"{BASE}/")
        self.assertEqual(page.status_code, 200)
        self.assertIn('src="index.js"', page.text)
        self.assertEqual(self.client.get(f"{BASE}/index.js").status_code, 200)
        self.assertEqual(self.client.get(f"{BASE}/plugin_api.py").status_code, 404)

    def test_api_reads_every_profile_from_a_profile_home(self):
        overall = self.client.get(f"{BASE}/api/stats/overview?range=all").json()["overall"]
        self.assertEqual(overall["totalRequests"], 7)
        insights = self.client.get(f"{BASE}/api/stats/insights?range=all")
        self.assertEqual(insights.status_code, 200)
        self.assertNotIn(SECRET, insights.text)

    def test_events_answer_once_so_a_buffering_proxy_delivers_them(self):
        events = self.client.get(f"{BASE}/api/events")
        self.assertEqual(events.headers["content-type"].split(";")[0], "text/event-stream")
        self.assertTrue(events.text.startswith("retry: "))
        self.assertIn("\ndata: {", events.text)

    def test_summary_posts_must_be_json(self):
        refused = self.client.post(f"{BASE}/api/insights/narrative", content=b"range=7d",
                                   headers={"content-type": "application/x-www-form-urlencoded"})
        self.assertEqual(refused.status_code, 415)


if __name__ == "__main__":
    unittest.main()
