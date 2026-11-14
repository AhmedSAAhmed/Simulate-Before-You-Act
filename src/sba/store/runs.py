"""Each run is an ICM folder (`runs/{run-id}/NN_stage/output/...` plus `check.md`).

Files are what a person opens; the database mirror is what survives Render's ephemeral disk.
"""

from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from sqlalchemy import Column, DateTime, Engine, Integer, MetaData, String, Table, Text, delete, insert, select

from sba.crm.service import utcnow

STAGES = ("01_intent", "02_simulate", "03_present", "04_execute", "05_verify")
RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
NAME = re.compile(r"^[a-z0-9_]+\.(json|md)$")

metadata = MetaData()
run_artifacts = Table(
    "sba_run_artifacts",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("run_id", String(64), nullable=False, index=True),
    Column("path", String(200), nullable=False),
    Column("content", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)


@dataclass
class RunStore:
    root: Path | None
    engine: Engine | None = None

    def __post_init__(self) -> None:
        if self.engine is not None:
            metadata.create_all(self.engine)

    @staticmethod
    def new_run_id(now: datetime | None = None) -> str:
        return f"r-{(now or utcnow()):%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"

    def save_request(self, run_id: str, text: str) -> None:
        self._put(run_id, "00_request.md", f"# Request\n\n{text}\n")

    def save(self, run_id: str, stage: str, name: str, content: BaseModel | dict[str, Any] | str) -> str:
        if stage not in STAGES or not NAME.match(name):
            raise ValueError(f"bad artifact {stage}/{name}")
        if isinstance(content, BaseModel):
            text = json.dumps(content.model_dump(mode="json"), ensure_ascii=False, indent=2)
        elif isinstance(content, dict):
            text = json.dumps(content, ensure_ascii=False, indent=2, default=str)
        else:
            text = content
        return self._put(run_id, f"{stage}/output/{name}", text)

    def save_check(self, run_id: str, stage: str, passed: bool, why: str = "") -> str:
        """First line `pass` or `fail: <why>`, as every stage contract's `## Check` requires."""
        if stage not in STAGES:
            raise ValueError(f"bad stage {stage}")
        line = "pass" if passed else f"fail: {why or 'unspecified'}"
        return self._put(run_id, f"{stage}/check.md", line + "\n")

    def load(self, run_id: str, relative: str) -> str | None:
        _check_id(run_id)
        if self.root is not None:
            path = self.root / run_id / relative
            if path.is_file():
                return path.read_text(encoding="utf-8")
        if self.engine is not None:
            with self.engine.connect() as conn:
                row = conn.execute(
                    select(run_artifacts.c.content)
                    .where(run_artifacts.c.run_id == run_id, run_artifacts.c.path == relative)
                    .order_by(run_artifacts.c.id.desc())
                ).first()
            return row[0] if row else None
        return None

    def status(self, run_id: str) -> dict[str, str | None]:
        """Each stage's check verdict, read from disk (or the mirror): status lives on disk."""
        out: dict[str, str | None] = {}
        for stage in STAGES:
            text = self.load(run_id, f"{stage}/check.md")
            out[stage] = text.splitlines()[0] if text else None
        return out

    def _put(self, run_id: str, relative: str, text: str) -> str:
        _check_id(run_id)
        if self.root is not None:
            path = self.root / run_id / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
        if self.engine is not None:
            with self.engine.begin() as conn:
                conn.execute(delete(run_artifacts).where(run_artifacts.c.run_id == run_id,
                                                         run_artifacts.c.path == relative))
                conn.execute(insert(run_artifacts).values(run_id=run_id, path=relative, content=text,
                                                          created_at=utcnow()))
        return relative


def _check_id(run_id: str) -> None:
    if not RUN_ID.match(run_id):
        raise ValueError(f"bad run id {run_id!r}")
