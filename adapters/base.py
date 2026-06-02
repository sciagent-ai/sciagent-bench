"""Adapter base class + CellResult dataclass.

Every adapter ingests a task spec + LLM id + budget and returns a CellResult
populated with verdict, score, per-axis cost, and pointers to artifacts on
disk. The four cost axes are kept separate per DESIGN_BENCH.md §5.1 / H6 so
cloud-incapable systems (Claude Code, raw LLM) report 0.0 for compute and
storage rather than None — Pareto math treats absence and "didn't use it"
identically only if the float is explicitly 0.0.
"""
from __future__ import annotations

import pathlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

# Verdict to score mapping. `none` means no verifier ran (or it errored out).
_VERDICT_SCORE = {
    "verified": 1.0,
    "refuted": 0.0,
    "insufficient": 0.3,
    "none": 0.0,
}


def score_from_verdict(verdict: str, confidence: float) -> float:
    """Map (verdict, confidence) -> score in [0, 1].

    `verified` weighted by confidence; `refuted` is 0; `insufficient` is a
    fixed partial-credit floor at 0.3 (still scaled by confidence so a
    low-confidence `insufficient` lands below 0.3).
    """
    base = _VERDICT_SCORE.get(verdict, 0.0)
    c = max(0.0, min(1.0, float(confidence)))
    return base * c if verdict in ("verified", "insufficient") else base


@dataclass
class CellResult:
    success: bool
    error: Optional[str]
    verdict: str
    confidence: float
    score: float
    cost_llm_usd: float
    cost_compute_usd: float
    cost_storage_usd: float
    cost_total_usd: float
    tokens_in: Optional[int]
    tokens_out: Optional[int]
    iterations: Optional[int]
    tool_calls: Optional[int]
    user_asks: int
    wall_seconds: float
    notes: str
    artifacts_dir: pathlib.Path
    raw_provenance_log: Optional[pathlib.Path]

    def as_csv_row(self) -> dict:
        """Flat dict suitable for csv.DictWriter."""
        return {
            "success": self.success,
            "error": self.error or "",
            "verdict": self.verdict,
            "confidence": f"{self.confidence:.3f}",
            "score": f"{self.score:.3f}",
            "cost_llm_usd": f"{self.cost_llm_usd:.4f}",
            "cost_compute_usd": f"{self.cost_compute_usd:.4f}",
            "cost_storage_usd": f"{self.cost_storage_usd:.4f}",
            "cost_total_usd": f"{self.cost_total_usd:.4f}",
            "tokens_in": "" if self.tokens_in is None else self.tokens_in,
            "tokens_out": "" if self.tokens_out is None else self.tokens_out,
            "iterations": "" if self.iterations is None else self.iterations,
            "tool_calls": "" if self.tool_calls is None else self.tool_calls,
            "user_asks": self.user_asks,
            "wall_seconds": f"{self.wall_seconds:.2f}",
            "notes": self.notes,
            "artifacts_dir": str(self.artifacts_dir),
            "raw_provenance_log": str(self.raw_provenance_log) if self.raw_provenance_log else "",
        }


CSV_FIELDS = [
    "cell_id",
    "task",
    "adapter",
    "llm",
    "success",
    "error",
    "verdict",
    "confidence",
    "score",
    "cost_llm_usd",
    "cost_compute_usd",
    "cost_storage_usd",
    "cost_total_usd",
    "tokens_in",
    "tokens_out",
    "iterations",
    "tool_calls",
    "user_asks",
    "wall_seconds",
    "notes",
    "artifacts_dir",
    "raw_provenance_log",
]


class AdapterBase(ABC):
    """Interface every cell adapter implements.

    The matrix YAML's `adapter_config` block is unpacked into the
    concrete adapter's constructor; `run` is uniform across adapters.
    """

    @abstractmethod
    def run(
        self,
        task_spec: dict,
        llm: str,
        workdir: pathlib.Path,
        budget: dict,
    ) -> CellResult: ...
