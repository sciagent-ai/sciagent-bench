"""Verifier invoker — uses litellm's built-in mock_response per the bench's
no-mocking-litellm rule. Confirms parse paths for a clean verdict, a
fenced-JSON response, and a malformed response (falls back to none/0.0).

We do NOT mock litellm.completion. Instead we monkeypatch a thin wrapper
around it that injects litellm's first-party `mock_response=` kwarg, so the
real litellm code path runs end-to-end and returns a synthetic completion.
"""
import functools

import litellm

from adapters import verifier_invoker


def _install_mock(monkeypatch, content: str):
    """Wrap litellm.completion so it receives `mock_response=content` —
    litellm then returns a synthetic ModelResponse with no API call."""
    real = litellm.completion

    @functools.wraps(real)
    def _wrapped(*args, **kwargs):
        kwargs.setdefault("mock_response", content)
        return real(*args, **kwargs)

    monkeypatch.setattr(verifier_invoker.litellm, "completion", _wrapped)


def test_verify_clean_json(tmp_path, monkeypatch):
    _install_mock(
        monkeypatch,
        '{"verdict": "verified", "confidence": 0.87, "issues": [], "reasoning": "ok"}',
    )
    out = verifier_invoker.verify(
        task_prompt="trivial task",
        claim_text="agent said it ran X",
        workdir=tmp_path,
        session_log_path=None,
        verifier_model="anthropic/claude-haiku-4-5-20251001",
        verification_criteria={"key_value": "x", "comparator": ">=", "threshold": 0.5},
    )
    assert out["verdict"] == "verified"
    assert out["confidence"] == 0.87
    assert out["issues"] == []
    assert "ok" in out["reasoning"]


def test_verify_handles_fenced_json(tmp_path, monkeypatch):
    _install_mock(
        monkeypatch,
        "Here is the JSON you asked for:\n\n"
        "```json\n"
        '{"verdict": "refuted", "confidence": 0.5, '
        '"issues": ["scope downgrade"], "reasoning": "the args ran a smoke variant"}\n'
        "```\n",
    )
    out = verifier_invoker.verify(
        task_prompt="t",
        claim_text="c",
        workdir=tmp_path,
        session_log_path=None,
        verifier_model="anthropic/claude-haiku-4-5-20251001",
        verification_criteria={},
    )
    assert out["verdict"] == "refuted"
    assert out["confidence"] == 0.5
    assert "scope downgrade" in out["issues"]


def test_verify_defaults_on_garbage(tmp_path, monkeypatch):
    _install_mock(monkeypatch, "not even close to json")
    out = verifier_invoker.verify(
        task_prompt="t",
        claim_text="c",
        workdir=tmp_path,
        session_log_path=None,
        verifier_model="anthropic/claude-haiku-4-5-20251001",
        verification_criteria={},
    )
    assert out["verdict"] == "none"
    assert out["confidence"] == 0.0


def test_verify_defaults_on_missing_fields(tmp_path, monkeypatch):
    _install_mock(monkeypatch, '{"reasoning": "model only returned text"}')
    out = verifier_invoker.verify(
        task_prompt="t",
        claim_text="c",
        workdir=tmp_path,
        session_log_path=None,
        verifier_model="anthropic/claude-haiku-4-5-20251001",
        verification_criteria={},
    )
    assert out["verdict"] == "none"
    assert out["confidence"] == 0.0
    assert "model only returned text" in out["reasoning"]
