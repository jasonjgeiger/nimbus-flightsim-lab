"""Select an NL compiler backend from the environment.

    NIMBUS_NL_BACKEND = "rules" (default, offline) | "llm"
"""
from __future__ import annotations

import os

from mission.nl.base import NLCompiler
from mission.nl.rules import RuleBasedCompiler


def get_compiler(backend: str | None = None) -> NLCompiler:
    name = (backend or os.environ.get("NIMBUS_NL_BACKEND", "rules")).lower()
    if name in ("rules", "rule", "offline", "regex"):
        return RuleBasedCompiler()
    if name in ("llm", "openai", "cloud"):
        from mission.nl.llm import LLMCompiler

        return LLMCompiler()
    raise ValueError(f"unknown NL backend {name!r} (expected 'rules' or 'llm')")
