"""Load ICM files (stage contracts and factory references) as model prompts.

The folder structure is the agent architecture: editing `stages/01_intent/CONTEXT.md`
changes what the planner is told, with no code change.
"""

from __future__ import annotations

from functools import lru_cache

from sba.config import ROOT


@lru_cache(maxsize=16)
def _read(relative: str) -> str:
    path = (ROOT / relative).resolve()
    if ROOT.resolve() not in path.parents:
        raise ValueError(f"{relative} is outside the workspace")
    return path.read_text(encoding="utf-8")


def load(*relative_paths: str) -> str:
    """Concatenate files, each under a header naming its path."""
    return "\n\n".join(f"===== {p} =====\n{_read(p)}" for p in relative_paths)


def exists(relative: str) -> bool:
    return (ROOT / relative).is_file()

