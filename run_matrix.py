#!/usr/bin/env python3
"""Run a bench matrix end-to-end.

Loads `tasks/<task_id>.yaml`, loads a matrix YAML, iterates cells, dispatches
to the right adapter, and writes `results/<TS>/<task>/results.csv` one row
at a time so a crash mid-sweep leaves the rows written so far intact.

Usage:
  ./run_matrix.py --task photonics --matrix matrices/photonics_smoke.yaml
  ./run_matrix.py --task photonics --matrix matrices/photonics_smoke.yaml --skip-completed
"""
from __future__ import annotations

import argparse
import csv
import dataclasses
import datetime as _dt
import pathlib
import shutil
import sys
import traceback

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from adapters.base import CSV_FIELDS  # noqa: E402
from adapters.sciagent import SciagentAdapter  # noqa: E402
from adapters.claude_code import ClaudeCodeAdapter  # noqa: E402


ADAPTERS = {
    "sciagent": SciagentAdapter,
    "claude_code": ClaudeCodeAdapter,
}


def _load_yaml(path: pathlib.Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _stage_inputs(task: dict, workdir: pathlib.Path) -> None:
    """Copy task inputs into workdir per their declared relative paths."""
    for entry in task.get("inputs") or []:
        rel = entry.get("path")
        src = entry.get("source")
        if not rel or not src:
            continue
        if str(src).startswith(("fetch ", "git clone ", "http")):
            # Network sources are the agent's responsibility — we don't pre-fetch.
            continue
        src_path = pathlib.Path(src)
        if not src_path.exists():
            print(f"  warn: input source missing: {src_path}", file=sys.stderr)
            continue
        dest = (workdir / rel).resolve()
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src_path.is_dir():
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(src_path, dest)
        else:
            shutil.copy2(src_path, dest)


def _completed_cell_ids(results_csv: pathlib.Path) -> set[str]:
    if not results_csv.exists():
        return set()
    done: set[str] = set()
    with results_csv.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cid = row.get("cell_id")
            if cid:
                done.add(cid)
    return done


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True, help="Task id (matches tasks/<id>.yaml)")
    parser.add_argument("--matrix", required=True, type=pathlib.Path)
    parser.add_argument("--results-root", type=pathlib.Path, default=REPO_ROOT / "results")
    parser.add_argument("--ts", default=None, help="Override the timestamp dir (used by --skip-completed to resume)")
    parser.add_argument("--skip-completed", action="store_true",
                        help="Skip cells whose id is already in the existing results.csv")
    args = parser.parse_args(argv)

    task_path = REPO_ROOT / "tasks" / f"{args.task}.yaml"
    if not task_path.exists():
        print(f"error: task not found: {task_path}", file=sys.stderr)
        return 2
    task = _load_yaml(task_path)

    matrix_path = args.matrix if args.matrix.is_absolute() else REPO_ROOT / args.matrix
    matrix = _load_yaml(matrix_path)
    cells = [c for c in (matrix.get("cells") or []) if c.get("task") == args.task]
    if not cells:
        print(f"error: no cells for task '{args.task}' in {matrix_path}", file=sys.stderr)
        return 2

    ts = args.ts or _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = args.results_root / ts / args.task
    out_dir.mkdir(parents=True, exist_ok=True)
    results_csv = out_dir / "results.csv"

    already_done: set[str] = set()
    if args.skip_completed:
        already_done = _completed_cell_ids(results_csv)

    write_header = not results_csv.exists()
    with results_csv.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if write_header:
            writer.writeheader()
            f.flush()

        for cell in cells:
            cell_id = cell["id"]
            if cell_id in already_done:
                print(f"[skip] {cell_id} — already in results.csv")
                continue

            adapter_name = cell["adapter"]
            adapter_cls = ADAPTERS.get(adapter_name)
            if adapter_cls is None:
                print(f"[err] unknown adapter '{adapter_name}' for cell {cell_id}", file=sys.stderr)
                continue
            adapter = adapter_cls(**(cell.get("adapter_config") or {}))

            cell_dir = out_dir / cell_id
            cell_dir.mkdir(parents=True, exist_ok=True)
            _stage_inputs(task, cell_dir)

            print(f"[run] {cell_id} → {cell_dir}")
            try:
                result = adapter.run(
                    task_spec=task,
                    llm=cell["llm"],
                    workdir=cell_dir,
                    budget=task.get("budget") or {},
                )
            except Exception as exc:  # adapter crashed before returning a CellResult
                traceback.print_exc()
                row = {
                    "cell_id": cell_id,
                    "task": args.task,
                    "adapter": adapter_name,
                    "llm": cell["llm"],
                    "success": False,
                    "error": f"adapter raised: {exc.__class__.__name__}: {exc}",
                    "verdict": "none",
                    "confidence": "0.000",
                    "score": "0.000",
                    "cost_llm_usd": "0.0000",
                    "cost_compute_usd": "0.0000",
                    "cost_storage_usd": "0.0000",
                    "cost_total_usd": "0.0000",
                    "tokens_in": "",
                    "tokens_out": "",
                    "iterations": "",
                    "tool_calls": "",
                    "user_asks": 0,
                    "wall_seconds": "0.00",
                    "notes": "",
                    "artifacts_dir": str(cell_dir),
                    "raw_provenance_log": "",
                }
                writer.writerow(row)
                f.flush()
                continue

            row = {
                "cell_id": cell_id,
                "task": args.task,
                "adapter": adapter_name,
                "llm": cell["llm"],
                **result.as_csv_row(),
            }
            writer.writerow(row)
            f.flush()
            print(
                f"  → verdict={result.verdict}@{result.confidence:.2f} "
                f"score={result.score:.2f} cost=${result.cost_total_usd:.4f} "
                f"wall={result.wall_seconds:.1f}s"
            )

    print(f"\nResults: {results_csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
