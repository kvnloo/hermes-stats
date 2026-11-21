"""Hermes Stats: the Oh My Pi `omp stats` dashboard over Hermes's session stores and z0live voice traces.

Surfaces:
  /stats [24h|7d|30d|90d|all]           slash command: what to change, as text, with no model call
  hermes stats serve|snapshot|insights  terminal command (also bin/hermes-stats from a checkout)
  auxiliary.stats_insights              the model that writes summaries, only when asked

Read-only. It registers no tools and no hooks, and it never reads message text.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("hermes_stats")

RANGE_WORDS = {"day": "24h", "today": "24h", "week": "7d", "month": "30d", "quarter": "90d"}

_HOST_LLM: Any = None  # ctx.llm, set by register(); None when run from a checkout


def _stats_command(raw_args: str = "", **_: Any) -> str:
    """`/stats [range]`: findings as text, at once, with no model call. A summary appears only when one
    was already generated for this exact data (dashboard or CLI)."""
    from .stats_api import RANGES
    from .stats_narrate import pick_llm
    from .stats_server import hermes_home, insights_text

    word = ((raw_args or "").split()[:1] or ["7d"])[0].lower()
    range_name = RANGE_WORDS.get(word, word)
    if range_name not in RANGES:
        return f"Unknown range {word!r}. Try /stats 24h, 7d, 30d, 90d or all."
    try:
        return insights_text(hermes_home(), range_name, pick_llm(host=_HOST_LLM))
    except Exception as exc:  # a slash command must answer, never raise into the chat
        log.warning("stats: insights failed", exc_info=True)
        return f"Insights couldn't be computed: {exc}"


def _cli_setup(parser) -> None:
    from .stats_server import setup_cli

    setup_cli(parser)


def _cli(args) -> int:
    from .stats_server import run_cli

    return run_cli(args, host_llm=_HOST_LLM)


def register(ctx) -> None:
    global _HOST_LLM
    from .stats_narrate import TASK

    _HOST_LLM = getattr(ctx, "llm", None)
    # auxiliary.stats_insights in config.yaml picks the model; unset, Hermes chooses one.
    ctx.register_auxiliary_task(
        TASK,
        display_name="Hermes Stats summaries",
        description="Writes the Insights summary from aggregates and findings only, never message text",
    )
    ctx.register_command(
        "stats",
        _stats_command,
        description="Hermes Stats: what to change, from your usage (no model call)",
        args_hint="[24h | 7d | 30d | 90d | all]",
    )
    ctx.register_cli_command(
        name="stats",
        help="Hermes Stats: usage dashboard, static snapshot, insights",
        setup_fn=_cli_setup,
        handler_fn=_cli,
    )
