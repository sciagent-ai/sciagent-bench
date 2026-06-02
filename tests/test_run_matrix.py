"""Run-matrix smoke: confirm --skip-completed honors an existing results.csv.

We register a fake adapter on the run_matrix module, drive a 2-cell matrix,
then re-run with --skip-completed and confirm only the second cell is
exercised on the second run.
"""
import csv
import pathlib

import yaml

import run_matrix
from adapters.base import AdapterBase, CellResult


class _ToyAdapter(AdapterBase):
    """Counts invocations on the class so tests can assert how many cells ran."""
    calls: list[str] = []

    def __init__(self, label: str = ""):
        self.label = label

    def run(self, task_spec, llm, workdir, budget):
        _ToyAdapter.calls.append(self.label)
        workdir = pathlib.Path(workdir)
        workdir.mkdir(parents=True, exist_ok=True)
        (workdir / "result.txt").write_text(f"hello from {self.label}\n", encoding="utf-8")
        return CellResult(
            success=True,
            error=None,
            verdict="verified",
            confidence=1.0,
            score=1.0,
            cost_llm_usd=0.01,
            cost_compute_usd=0.0,
            cost_storage_usd=0.0,
            cost_total_usd=0.01,
            tokens_in=100,
            tokens_out=10,
            iterations=1,
            tool_calls=0,
            user_asks=0,
            wall_seconds=0.1,
            notes="",
            artifacts_dir=workdir,
            raw_provenance_log=None,
        )


def _write_yaml(path: pathlib.Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


def test_skip_completed_skips_first_cell(tmp_path, monkeypatch):
    repo = tmp_path / "bench"
    (repo / "tasks").mkdir(parents=True)
    (repo / "matrices").mkdir(parents=True)
    _write_yaml(repo / "tasks" / "toy.yaml", {
        "id": "toy",
        "prompt": "echo hi",
        "budget": {"wall_time_seconds": 60, "cost_usd": 0.10},
    })
    _write_yaml(repo / "matrices" / "toy.yaml", {
        "cells": [
            {"id": "toy__a", "task": "toy", "adapter": "toy",
             "adapter_config": {"label": "A"}, "llm": "fake/model"},
            {"id": "toy__b", "task": "toy", "adapter": "toy",
             "adapter_config": {"label": "B"}, "llm": "fake/model"},
        ]
    })

    monkeypatch.setattr(run_matrix, "REPO_ROOT", repo)
    monkeypatch.setitem(run_matrix.ADAPTERS, "toy", _ToyAdapter)

    results_root = tmp_path / "out"
    _ToyAdapter.calls = []

    rc = run_matrix.main([
        "--task", "toy",
        "--matrix", str(repo / "matrices" / "toy.yaml"),
        "--results-root", str(results_root),
        "--ts", "RUN1",
    ])
    assert rc == 0
    assert _ToyAdapter.calls == ["A", "B"]

    csv_path = results_root / "RUN1" / "toy" / "results.csv"
    assert csv_path.exists()
    with csv_path.open() as f:
        rows = list(csv.DictReader(f))
    assert {r["cell_id"] for r in rows} == {"toy__a", "toy__b"}

    # Re-run with the same ts dir AND --skip-completed: nothing should run.
    _ToyAdapter.calls = []
    rc = run_matrix.main([
        "--task", "toy",
        "--matrix", str(repo / "matrices" / "toy.yaml"),
        "--results-root", str(results_root),
        "--ts", "RUN1",
        "--skip-completed",
    ])
    assert rc == 0
    assert _ToyAdapter.calls == []


def test_resume_after_partial_run(tmp_path, monkeypatch):
    """Hand-craft a partial results.csv with one row, then resume —
    only the remaining cell should run."""
    repo = tmp_path / "bench"
    (repo / "tasks").mkdir(parents=True)
    (repo / "matrices").mkdir(parents=True)
    _write_yaml(repo / "tasks" / "toy.yaml", {
        "id": "toy", "prompt": "echo hi",
        "budget": {"wall_time_seconds": 60, "cost_usd": 0.10},
    })
    _write_yaml(repo / "matrices" / "toy.yaml", {
        "cells": [
            {"id": "toy__a", "task": "toy", "adapter": "toy",
             "adapter_config": {"label": "A"}, "llm": "fake/model"},
            {"id": "toy__b", "task": "toy", "adapter": "toy",
             "adapter_config": {"label": "B"}, "llm": "fake/model"},
        ]
    })

    monkeypatch.setattr(run_matrix, "REPO_ROOT", repo)
    monkeypatch.setitem(run_matrix.ADAPTERS, "toy", _ToyAdapter)

    results_root = tmp_path / "out"
    csv_path = results_root / "RUN2" / "toy" / "results.csv"
    csv_path.parent.mkdir(parents=True)

    from adapters.base import CSV_FIELDS
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        w.writerow({k: "" for k in CSV_FIELDS} | {
            "cell_id": "toy__a", "task": "toy", "adapter": "toy",
            "llm": "fake/model", "success": "True", "verdict": "verified",
        })

    _ToyAdapter.calls = []
    rc = run_matrix.main([
        "--task", "toy",
        "--matrix", str(repo / "matrices" / "toy.yaml"),
        "--results-root", str(results_root),
        "--ts", "RUN2",
        "--skip-completed",
    ])
    assert rc == 0
    assert _ToyAdapter.calls == ["B"]
