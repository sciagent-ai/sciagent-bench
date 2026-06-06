"""Claude Code stdout-summary parser.

`claude --print --output-format json` emits a single JSON object with cost
and token counts. The adapter falls back to text-mode regex if the JSON
doesn't parse — both paths are tested here.
"""
import pathlib

from adapters import claude_code
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


def test_locate_claude_transcript(tmp_path, monkeypatch):
    """Confirm the encoded-cwd path scheme — Claude Code stores transcripts
    at ~/.claude/projects/<cwd-with-/-replaced-by-->/<session_id>.jsonl.
    """
    fake_projects = tmp_path / "claude_projects"
    monkeypatch.setattr(claude_code, "_CLAUDE_PROJECTS", fake_projects)

    cwd = tmp_path / "some" / "project"
    cwd.mkdir(parents=True)
    encoded = str(cwd.resolve()).replace("/", "-")
    session = "abc-123-def"
    transcript_dir = fake_projects / encoded
    transcript_dir.mkdir(parents=True)
    (transcript_dir / f"{session}.jsonl").write_text("{}\n")

    found = claude_code._locate_claude_transcript(cwd, session)
    assert found is not None and found.exists()

    # Missing session_id → None.
    assert claude_code._locate_claude_transcript(cwd, None) is None
    # Missing file → None.
    assert claude_code._locate_claude_transcript(cwd, "nope") is None


def test_parses_session_id_from_json_summary():
    stdout = (
        '{"type": "result", "result": "ok", "session_id": "abc-123", '
        '"total_cost_usd": 0.1, "usage": {"input_tokens": 10, "output_tokens": 5}}'
    )
    out = parse_claude_session_summary(stdout)
    assert out["session_id"] == "abc-123"


def test_parses_stream_json_format():
    """stream-json: one JSON event per line; we scan for the final
    `result` event and pick session_id off any earlier event."""
    stdout = "\n".join([
        '{"type":"system","subtype":"init","session_id":"sid-stream-99"}',
        '{"type":"assistant","message":{"content":[{"type":"text","text":"Looking..."}]}}',
        '{"type":"stream_event","event":{"type":"content_block_delta"}}',
        '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Bash"}]}}',
        ('{"type":"result","subtype":"success","is_error":false,'
         '"result":"The MFE is 0.27","num_turns":11,'
         '"total_cost_usd":0.45,"session_id":"sid-stream-99",'
         '"usage":{"input_tokens":1200,"output_tokens":350}}'),
    ])
    out = parse_claude_session_summary(stdout)
    assert out["cost_usd"] == 0.45
    assert out["tokens_in"] == 1200
    assert out["tokens_out"] == 350
    assert out["num_turns"] == 11
    assert out["session_id"] == "sid-stream-99"
    assert "MFE is 0.27" in out["result_text"]


def test_extract_result_block_picks_last_assistant_text_from_stream_json():
    """Regression test: claude can exit mid-stream (e.g. max-turns hit)
    without emitting a `type:result` event. The fallback must return the
    last assistant text block — NOT the entire stdout dump, which was the
    bug that sent 3M tokens to the verifier."""
    from adapters.claude_code import _extract_result_block

    stdout = "\n".join([
        '{"type":"system","subtype":"init"}',
        '{"type":"assistant","message":{"content":[{"type":"text","text":"step 1"}]}}',
        '{"type":"user","message":{"content":[{"type":"tool_result","content":"ok"}]}}',
        '{"type":"assistant","message":{"content":[{"type":"text","text":"final claim: MFE = 0.19"}]}}',
    ])
    out = _extract_result_block(stdout)
    assert "MFE = 0.19" in out
    assert len(out) < 1000  # not the whole stream


def test_extract_result_block_returns_empty_when_no_signal():
    """If there's nothing parseable AND no Result: sentinel, return empty
    rather than dumping the full text."""
    from adapters.claude_code import _extract_result_block
    out = _extract_result_block("just some random text with no markers")
    assert out == ""


def test_stream_json_with_no_result_event_preserves_session_id():
    """Partial stream (timeout mid-run): no result event, but session_id
    is still recoverable from any earlier event so we can still locate the
    Claude Code transcript on disk."""
    stdout = "\n".join([
        '{"type":"system","subtype":"init","session_id":"sid-partial"}',
        '{"type":"assistant","message":{"content":[{"type":"text","text":"step 1"}]}}',
    ])
    out = parse_claude_session_summary(stdout)
    assert out["session_id"] == "sid-partial"
    assert out["cost_usd"] == 0.0
    assert out["tokens_in"] is None
