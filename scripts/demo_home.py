#!/usr/bin/env python3
"""Write a synthetic Hermes home and z0live voice traces, for screenshots and demos.

Three profiles over 30 days, four providers, subagents, side tasks and a week of voice calls. Every value
comes from a fixed seed; nothing is read from a real Hermes home. Message rows carry no text.

  python3 scripts/demo_home.py DIR            # writes DIR/home and DIR/voice-traces
  HERMES_HOME=DIR/home bin/hermes-stats snapshot demo.html --voice-traces DIR/voice-traces
"""
from __future__ import annotations

import argparse
import itertools
import json
import random
import sqlite3
import time
from pathlib import Path

# The columns stats_hermes reads, a subset of Hermes's own schema.
SCHEMA = """
CREATE TABLE sessions (
    id TEXT PRIMARY KEY, source TEXT NOT NULL, model TEXT, billing_provider TEXT,
    parent_session_id TEXT, started_at REAL NOT NULL, ended_at REAL, cwd TEXT);
CREATE TABLE messages (
    id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, tool_name TEXT, timestamp REAL, finish_reason TEXT,
    _compressed_summary INTEGER DEFAULT 0, display_kind TEXT, display_metadata TEXT, message_uid TEXT);
CREATE TABLE session_model_usage (
    session_id TEXT, model TEXT, billing_provider TEXT, task TEXT, api_call_count INTEGER,
    input_tokens INTEGER, output_tokens INTEGER, cache_read_tokens INTEGER, cache_write_tokens INTEGER,
    reasoning_tokens INTEGER, estimated_cost_usd REAL, actual_cost_usd REAL, first_seen REAL, last_seen REAL);
"""

# model: (provider, $ per 1M input tokens, $ per 1M output tokens). Made-up prices.
MODELS = {
    "claude-opus-5-5": ("anthropic", 5.0, 25.0),
    "gpt-6.2": ("openai", 2.5, 10.0),
    "gpt-6.2-mini": ("openai", 0.4, 1.6),
    "gemini-4-carbon": ("google", 1.25, 5.0),
    "qwen3-coder-30b": ("ollama", 0.0, 0.0),
}
# profile: (main model, sessions per day, projects)
PROFILES = {
    "default": ("claude-opus-5-5", (4, 12), ["demo-app", "docs-site", "infra"]),
    "research": ("gpt-6.2", (1, 5), ["papers", "notebooks"]),
    "ops": ("gemini-4-carbon", (1, 4), ["status-page", "infra"]),
}
TOOLS = ["terminal", "read_file", "patch", "search_files", "write_file", "web_search", "browser_navigate",
         "delegate_task", "todo"]
TOOL_WEIGHTS = [30, 25, 15, 12, 6, 5, 3, 2, 2]
SOURCES, SOURCE_WEIGHTS = ["cli", "telegram", "desktop", "cron"], [50, 25, 20, 5]
DAYS = 30


def _cost(model: str, tokens_in: int, tokens_out: int) -> float:
    _, p_in, p_out = MODELS[model]
    return round((tokens_in * p_in + tokens_out * p_out) / 1e6, 6)


class Store:
    def __init__(self) -> None:
        self.sessions: list[tuple] = []
        self.messages: list[tuple] = []
        self.usage: list[tuple] = []
        self.ids = itertools.count(1)

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(path)
        db.executescript(SCHEMA)
        db.executemany("INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?)", self.sessions)
        db.executemany("INSERT INTO messages VALUES (?,?,?,?,?,?,0,?,?,?)", self.messages)
        db.executemany("INSERT INTO session_model_usage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", self.usage)
        db.commit()
        db.close()

    def session(self, rng: random.Random, sid: str, start: float, model: str, project: str, *,
                source: str, parent: str | None = None, turns: int) -> float:
        """One conversation: user turns, model calls, tool calls, and its usage rows. Returns its end time."""
        provider = MODELS[model][0]
        t, calls, tokens_in, tokens_out, cache = start, 0, 0, 0, 0
        context = rng.randint(6_000, 14_000)
        for _ in range(turns):
            t += rng.uniform(20, 240)
            self.messages.append((next(self.ids), sid, "user", None, t, None, None, None, None))
            for step in range(rng.choice([1, 1, 2, 2, 3, 4, 6])):
                t += rng.uniform(2, 25)
                calls += 1
                context += rng.randint(800, 4_000)
                tokens_in += context
                cache += int(context * rng.uniform(0.55, 0.9))
                tokens_out += rng.randint(150, 1_800)
                final = step == 0 and rng.random() < 0.3
                kind = "failed_turn" if rng.random() < 0.015 else None
                meta = json.dumps({"interrupted": True}) if rng.random() < 0.01 else None
                self.messages.append((next(self.ids), sid, "assistant", None, t,
                                      "stop" if final else "tool_calls", kind, meta, None))
                if final:
                    break
                for tool in rng.choices(TOOLS, TOOL_WEIGHTS, k=rng.randint(1, 3)):
                    t += rng.uniform(0.2, 18)
                    self.messages.append((next(self.ids), sid, "tool", tool, t, None, None, None, None))
            t += rng.uniform(3, 20)
            calls += 1
            tokens_out += rng.randint(200, 900)
            tokens_in += context
            self.messages.append((next(self.ids), sid, "assistant", None, t, "stop", None, None, None))
        uncached = max(tokens_in - cache, 0)
        self.sessions.append((sid, source, model, provider, parent, start, t, f"/home/demo/{project}"))
        self.usage.append((sid, model, provider, "", calls, tokens_in, tokens_out, cache, 0,
                           tokens_out // 4, _cost(model, uncached, tokens_out) + _cost(model, cache, 0) / 10,
                           0, start, t))
        if turns >= 8:  # long sessions compact, on the main model
            n = turns // 8
            self.usage.append((sid, model, provider, "compression", n, context * n, 2_000 * n, 0, 0, 0,
                               _cost(model, context * n, 2_000 * n), 0, t - 60, t - 60))
        self.usage.append((sid, model, provider, "title_generation", 1, 1_200, 20, 0, 0, 0,
                           _cost(model, 1_200, 20), 0, start + 30, start + 30))
        if rng.random() < 0.4:
            n = rng.randint(1, 6)
            self.usage.append((sid, "gpt-6.2-mini", "openai", "approval", n, 900 * n, 10 * n, 0, 0, 0,
                               _cost("gpt-6.2-mini", 900 * n, 10 * n), 0, start + 60, t))
        return t


def hermes_home(home: Path, now: float, seed: int) -> None:
    for index, (profile, (main, per_day, projects)) in enumerate(PROFILES.items()):
        rng = random.Random(seed + index)
        store = Store()
        for day in range(DAYS):
            midnight = now - (DAYS - day) * 86_400
            for n in range(rng.randint(*per_day)):
                hour = rng.choices(range(24), [1, 1, 0, 0, 0, 0, 1, 2, 4, 6, 7, 7, 5, 6, 7, 7, 6, 5, 4, 4, 3, 3, 2, 2])[0]
                start = midnight + hour * 3600 + rng.uniform(0, 3500)
                if start > now - 600:
                    continue
                model = "qwen3-coder-30b" if profile == "research" and rng.random() < 0.25 else main
                sid = f"{profile[:3]}-{day:02d}-{n:02d}"
                store.session(rng, sid, start, model, rng.choice(projects), turns=rng.randint(1, 14),
                              source=rng.choices(SOURCES, SOURCE_WEIGHTS)[0])
                if profile == "default" and rng.random() < 0.15:  # fan out to subagents on the main model
                    for c in range(rng.randint(2, 5)):
                        store.session(rng, f"{sid}-sub{c}", start + 120 + c * 15, main, "demo-app",
                                      source="subagent", parent=sid, turns=rng.randint(1, 3))
        store.write(home / "state.db" if profile == "default" else home / "profiles" / profile / "state.db")


def voice_traces(root: Path, now: float, seed: int) -> None:
    rng = random.Random(seed + 99)
    for day in range(7):
        for n in range(rng.randint(1, 3)):
            wall = now - (7 - day) * 86_400 + rng.uniform(9, 21) * 3600
            if wall > now - 600:
                continue

            def ev(t: float, kind: str, **fields) -> str:
                return json.dumps({"ev": kind, "t": round(t, 3), "wall": round(wall + t, 3), **fields})

            lines = [ev(0.0, "call.created", engine="gpt-live", model="gpt-live-1", profile="default"),
                     ev(0.6, "call.negotiated", setup_s=round(rng.uniform(0.4, 1.2), 2))]
            t = 1.0
            for turn in range(rng.randint(3, 12)):
                speak = rng.uniform(1, 6)
                reply = rng.uniform(0.7, 3.2)
                lines += [ev(t, "audio.on", dir="input"), ev(t + speak, "audio.off", dir="input"),
                          json.dumps({"ev": "rx", "src": "provider", "type": "turn.done", "t": round(t + speak + 0.1, 3),
                                      "wall": round(wall + t + speak + 0.1, 3)}),
                          ev(t + speak + reply, "audio.on", dir="output")]
                if rng.random() < 0.12:
                    lines.append(ev(t + speak + reply + 0.5, "user.reaction", correction=rng.random() < 0.5,
                                    frustration=rng.random() < 0.2, repeat=rng.random() < 0.3,
                                    barge_in=rng.random() < 0.5))
                if rng.random() < 0.35:
                    did = f"d{turn}"
                    fast = rng.random() < 0.6
                    lines += [ev(t + speak + 0.2, "delegation.start", did=did),
                              ev(t + speak + 0.9, "lanes.tier", did=did, tier="fast",
                                 model="gemini-4-flash" if fast else None, first_s=round(rng.uniform(0.2, 0.6), 2),
                                 s=round(rng.uniform(0.6, 1.6), 2),
                                 errors={} if fast else {"gemini-4-flash": "SKIP", "qwen3-4b": "empty"}),
                              ev(t + speak + rng.uniform(3, 12), "delegation.done", did=did,
                                 s=round(rng.uniform(3, 12), 2), closed=False)]
                t += speak + reply + rng.uniform(4, 20)
            lines.append(ev(t + 2, "call.closed", seconds=round(t + 2, 2), reason="client_closed"))
            path = root / time.strftime("%Y-%m-%d", time.gmtime(wall)) / f"{time.strftime('%H%M%S', time.gmtime(wall))}-call{n}.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Write a synthetic Hermes home and z0live voice traces.")
    parser.add_argument("dir", type=Path, help="Writes DIR/home (a Hermes root) and DIR/voice-traces")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--now", type=float, default=None, help="Unix time the data ends at (default: now)")
    args = parser.parse_args()
    if (args.dir / "home").exists():
        parser.error(f"{args.dir / 'home'} exists; pick an empty directory")
    now = args.now or time.time()
    hermes_home(args.dir / "home", now, args.seed)
    voice_traces(args.dir / "voice-traces", now, args.seed)
    print(args.dir)


if __name__ == "__main__":
    main()
