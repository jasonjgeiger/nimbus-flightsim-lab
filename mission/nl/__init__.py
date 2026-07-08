"""Natural-language -> Mission IR compilers.

The compiler is *outside* the safety boundary: it only produces IR JSON. The
deterministic validator (mission.validate.compile_mission) is what decides
whether that IR is safe to fly, so a bad translation can never fly an unsafe
mission.

Backends (select via env NIMBUS_NL_BACKEND):
  - "rules" (default): offline, deterministic keyword/regex parser. No network.
  - "llm": OpenAI-compatible chat API (works with OpenAI, Azure, or a local
    Ollama/llama.cpp server). Configure with NIMBUS_LLM_* env vars.
"""
from __future__ import annotations

from mission.nl.base import NLCompileError, NLCompiler
from mission.nl.factory import get_compiler
from mission.nl.rules import RuleBasedCompiler

__all__ = ["NLCompiler", "NLCompileError", "RuleBasedCompiler", "get_compiler"]
