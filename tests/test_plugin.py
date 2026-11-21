"""Install Hermes Stats into a throwaway HERMES_HOME next to a neighbor plugin and load both with Hermes's loader.

Needs a Hermes install: `hermes` on PATH (or HERMES_BIN). Skipped without one. The loader probe runs on
Hermes's own Python, read from the `hermes` launcher (or HERMES_PYTHON). The neighbor is the catalog's
`/wrapped` video-recap plugin: NEIGHBOR_PLUGIN_REPO names a git checkout of it, at NEIGHBOR_PLUGIN_REF if set;
without it a stand-in with the same id, slash command, CLI command, tool and hook is installed instead.

Run: python3 -m unittest discover -s tests
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _load import load  # noqa: E402

plugin = load()
from test_stats_adapter import SECRET, _hermes, _voice  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
HERMES = os.environ.get("HERMES_BIN") or shutil.which("hermes")
GIT = ["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid", "-c", "commit.gpgsign=false"]

STUB_MANIFEST = """\
name: hermes-wrapped
version: "0.0.0"
description: Stand-in with the neighbor plugin's registrations, for the coexistence test.
provides_tools: [wrapped_make]
provides_hooks: [post_tool_call]
"""
STUB_INIT = '''\
def register(ctx):
    ctx.register_hook("post_tool_call", lambda **kw: None)
    ctx.register_command("wrapped", lambda raw_args="", **kw: "wrapped stub", description="stub")
    ctx.register_tool(name="wrapped_make", toolset="hermes-wrapped",
                      schema={"name": "wrapped_make", "description": "stub",
                              "parameters": {"type": "object", "properties": {}}},
                      handler=lambda args, **kw: "{}", description="stub")
    ctx.register_cli_command(name="wrapped", help="stub", setup_fn=lambda p: None, handler_fn=lambda a: 0)
'''

# Runs on Hermes's Python: discover plugins the way a session does, then call the loaded /stats handler.
PROBE = textwrap.dedent("""\
    import json, sys
    sys.path.insert(0, sys.argv[1])
    import hermes_bootstrap  # noqa: F401
    from hermes_cli.plugins import (discover_plugins, get_plugin_auxiliary_tasks, get_plugin_command_handler,
                                    get_plugin_commands, get_plugin_manager)
    discover_plugins()
    print("PROBE:" + json.dumps({
        "plugins": {p["name"]: p for p in get_plugin_manager().list_plugins()},
        "commands": {name: entry["plugin"] for name, entry in get_plugin_commands().items()},
        "aux": {t["key"]: t["plugin"] for t in get_plugin_auxiliary_tasks()},
        "stats_7d": get_plugin_command_handler("stats")("7d"),
    }, default=str))
""")


def _hermes_python_and_root():
    """(python, hermes-agent dir) from the `hermes` launcher, which execs Hermes's own interpreter."""
    out = subprocess.run([HERMES, "--version"], capture_output=True, text=True, timeout=120).stdout
    root = re.search(r"Install directory:\s*(\S+)", out)
    python = os.environ.get("HERMES_PYTHON")
    if not python:
        launcher = Path(HERMES).read_text(errors="replace")
        found = re.search(r"exec\s+'?(/\S*?python[\d.]*)'?\s", launcher)
        python = found.group(1) if found else None
    return python, (root.group(1) if root else None)


def _git_repo(src: Path) -> str:
    subprocess.run(GIT + ["init", "-q", str(src)], check=True)
    subprocess.run(GIT + ["-C", str(src), "add", "-A"], check=True)
    subprocess.run(GIT + ["-C", str(src), "commit", "-qm", "fixture"], check=True)
    return f"file://{src}"


@unittest.skipUnless(HERMES, "no Hermes install (`hermes` on PATH or HERMES_BIN)")
class InstallAndLoadTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls.tmp.name)
        cls.home = tmp / "home"
        cls.voice_root = tmp / "voice-traces"
        cls.home.mkdir()
        cls.env = {**os.environ, "HERMES_HOME": str(cls.home), "HERMES_MOBILE_VOICE_TRACE_DIR": str(cls.voice_root)}

        # The working tree as it is, uncommitted edits included; no build output beyond the committed dist.
        stats_src = tmp / "stats-src"
        shutil.copytree(ROOT, stats_src, ignore=shutil.ignore_patterns(
            ".git", "node_modules", "__pycache__", ".pytest_cache", "audit-out"))
        wrapped_repo, wrapped_ref = os.environ.get("NEIGHBOR_PLUGIN_REPO"), os.environ.get("NEIGHBOR_PLUGIN_REF")
        if wrapped_repo:
            wrapped_url = f"file://{Path(wrapped_repo).expanduser().resolve()}"
        else:
            stub = tmp / "wrapped-src"
            stub.mkdir()
            (stub / "plugin.yaml").write_text(STUB_MANIFEST)
            (stub / "__init__.py").write_text(STUB_INIT)
            wrapped_url = _git_repo(stub)
        cls.installs = [cls._hermes("plugins", "install", _git_repo(stats_src), "--enable", "--yes-deps"),
                        cls._hermes("plugins", "install", wrapped_url, "--enable", "--yes-deps",
                                    *(["--ref", wrapped_ref] if wrapped_ref else []))]
        _hermes(cls.home)  # synthetic stores, written after install so Hermes never touched them
        _voice(cls.voice_root)
        cls.digests = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in cls.home.rglob("state.db")}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @classmethod
    def _hermes(cls, *args, timeout=300):
        return subprocess.run([HERMES, *args], capture_output=True, text=True, timeout=timeout, env=cls.env)

    def test_installs_succeed(self):
        for run in self.installs:
            self.assertEqual(run.returncode, 0, run.stdout[-2000:] + run.stderr[-2000:])
        self.assertTrue((self.home / "plugins" / "stats" / "plugin.yaml").is_file())
        self.assertTrue((self.home / "plugins" / "hermes-wrapped" / "plugin.yaml").is_file())

    def test_loader_loads_both_without_a_clash(self):
        python, agent_root = _hermes_python_and_root()
        if not (python and agent_root):
            self.skipTest("could not find Hermes's Python (set HERMES_PYTHON)")
        probe = Path(self.tmp.name) / "probe.py"
        probe.write_text(PROBE)
        run = subprocess.run([python, "-I", str(probe), agent_root], capture_output=True, text=True,
                             timeout=300, env=self.env)
        line = next((ln for ln in run.stdout.splitlines() if ln.startswith("PROBE:")), None)
        self.assertIsNotNone(line, run.stdout[-2000:] + run.stderr[-2000:])
        got = json.loads(line[len("PROBE:"):])
        for name in ("stats", "hermes-wrapped"):
            self.assertTrue(got["plugins"][name]["enabled"], got["plugins"][name])
            self.assertIsNone(got["plugins"][name]["error"])
        self.assertEqual((got["plugins"]["stats"]["tools"], got["plugins"]["stats"]["hooks"]), (0, 0))
        self.assertEqual(got["commands"]["stats"], "stats")
        self.assertEqual(got["commands"]["wrapped"], "hermes-wrapped")
        self.assertEqual(got["aux"].get("stats_insights"), "stats")
        self.assertIn("Hermes insights, last 7d", got["stats_7d"])
        self.assertNotIn(SECRET, got["stats_7d"])

    def test_hermes_cli_runs_both_commands(self):
        insights = self._hermes("stats", "insights", "--range", "7d")
        self.assertEqual(insights.returncode, 0, insights.stderr[-2000:])
        self.assertIn("Hermes insights, last 7d", insights.stdout)
        snapshot = Path(self.tmp.name) / "out" / "index.html"
        run = self._hermes("stats", "snapshot", str(snapshot))
        self.assertEqual(run.returncode, 0, run.stderr[-2000:])
        html = snapshot.read_text(encoding="utf-8")
        self.assertIn("<title>Hermes Stats</title>", html)
        self.assertIn("window.__HERMES_STATS__=", html)
        for text in (insights.stdout, html):
            self.assertNotIn(SECRET, text)
        self.assertEqual(self._hermes("wrapped", "--help").returncode, 0)
        self.assertEqual({p: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.home.rglob("state.db")},
                         self.digests)  # read-only


class RegisterTest(unittest.TestCase):
    def test_summaries_route_through_ctx_llm_on_the_plugins_own_task(self):
        ctx = mock.MagicMock()
        ctx.llm.complete.return_value = mock.Mock(text="ok", model="m-aux")
        plugin.register(ctx)
        self.assertEqual(ctx.register_auxiliary_task.call_args[0][0], "stats_insights")
        self.assertEqual(ctx.register_command.call_args[0][0], "stats")
        self.assertEqual(ctx.register_cli_command.call_args[1]["name"], "stats")
        ctx.register_tool.assert_not_called()
        ctx.register_hook.assert_not_called()
        from hermes_stats.stats_narrate import pick_llm

        llm = pick_llm(host=plugin._HOST_LLM)
        self.assertEqual(llm.complete([{"role": "user", "content": "{}"}]), ("ok", "m-aux"))
        self.assertEqual(ctx.llm.complete.call_args[1]["task"], "stats_insights")
        self.assertIsNone(pick_llm())  # from a checkout, without --llm-url: no model


if __name__ == "__main__":
    unittest.main()
