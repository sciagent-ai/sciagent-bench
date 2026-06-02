"""Sciagent adapter parsing — uses the DBAASP smoke's anthropic-single-family
provenance.jsonl as a fixture. The full adapter shells to `sciagent run`;
this test exercises the pure-parsing helper that walks the JSONL.
"""
import pathlib

from adapters.sciagent import parse_provenance


FIXTURE = (
    pathlib.Path(__file__).parent
    / "fixtures"
    / "dbaasp_anthropic_provenance.jsonl"
)


def test_parse_provenance_populates_all_fields():
    out = parse_provenance(FIXTURE)
    # Verdict + confidence are pulled from the verification_result event.
    assert out["verdict"] == "verified"
    assert 0.0 < out["confidence"] <= 1.0
    # Session_end gives us iterations + wall.
    assert out["iterations"] is not None and out["iterations"] > 0
    assert out["wall_seconds"] > 0
    # tool_result rows contributed both tokens and cost.
    assert out["tokens_in"] and out["tokens_in"] > 0
    assert out["tokens_out"] and out["tokens_out"] > 0
    assert out["cost_llm_usd"] > 0
    # No compute / storage tool_results in this DBAASP run.
    assert out["cost_compute_usd"] == 0.0
    assert out["cost_storage_usd"] == 0.0
    # tool_call count: this run made 27 tool calls.
    assert out["tool_calls"] == 27
    # No ask_user in this DBAASP trajectory.
    assert out["user_asks"] == 0


def test_parse_provenance_verdict_is_last_one():
    """If multiple verification_result events appear, we keep the latest —
    the design doc's 'last verification_result event' rule. The DBAASP
    fixture has exactly one, so this asserts the single-event path."""
    out = parse_provenance(FIXTURE)
    assert out["verdict"] in ("verified", "refuted", "insufficient")
