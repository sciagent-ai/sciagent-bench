"""Claude Code stdout-summary parser.

`claude --print --output-format json` emits a single JSON object with cost
and token counts. The adapter falls back to text-mode regex if the JSON
doesn't parse — both paths are tested here.
"""
from adapters.claude_code import parse_claude_session_summary


def test_parses_json_summary():
    stdout = (
        '{"type": "result", "result": "The minimum field efficiency is 0.27.", '
        '"session_id": "abc123", "total_cost_usd": 0.1234, '
        '"duration_ms": 18432, "num_turns": 5, '
        '"usage": {"input_tokens": 12345, "output_tokens": 678}}'
    )
    out = parse_claude_session_summary(stdout)
    assert out["cost_usd"] == 0.1234
    assert out["tokens_in"] == 12345
    assert out["tokens_out"] == 678
    assert out["num_turns"] == 5
    assert "minimum field efficiency" in out["result_text"]


def test_parses_text_summary_fallback():
    stdout = (
        "...lots of progress output...\n"
        "Result: I ran the simulation and the MFE is 0.26.\n\n"
        "Total cost: $0.0421\n"
        "input_tokens: 8200\n"
        "output_tokens: 540\n"
        "num_turns: 3\n"
    )
    out = parse_claude_session_summary(stdout)
    assert out["cost_usd"] == 0.0421
    assert out["tokens_in"] == 8200
    assert out["tokens_out"] == 540
    assert out["num_turns"] == 3


def test_handles_empty_stdout():
    out = parse_claude_session_summary("")
    assert out["cost_usd"] == 0.0
    assert out["tokens_in"] is None
    assert out["tokens_out"] is None
    assert out["num_turns"] is None
    assert out["result_text"] is None


def test_text_only_alternate_cost_format():
    """Older Claude Code builds may print cost only — tokens absent."""
    stdout = "I did the thing.\nTotal cost: $0.10\n"
    out = parse_claude_session_summary(stdout)
    assert out["cost_usd"] == 0.10
    assert out["tokens_in"] is None
    assert out["tokens_out"] is None
