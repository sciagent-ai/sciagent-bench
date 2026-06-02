"""Bench-side post-hoc verifier.

Same prompt template that sciagent's LLM verification gate uses, copied at
install time into `prompts/verification_llm.md` (not imported — DESIGN_BENCH.md
§1.2 bars `from sciagent.*`). Used to score Claude Code cells and sciagent
verifier-OFF cells uniformly with the sciagent verifier-ON cells, so the
verifier-on/off ablation isolates *agent access during the run*, not *how
scoring happens*.
"""
from __future__ import annotations

import json
import pathlib
import re
from typing import Optional

import litellm

_PROMPT_PATH = pathlib.Path(__file__).resolve().parent.parent / "prompts" / "verification_llm.md"

_VALID_VERDICTS = {"verified", "refuted", "insufficient"}


def _extract_json(text: str) -> dict:
    """Pull the first JSON object out of an LLM response.

    The verifier prompt asks for a bare JSON object, but models sometimes
    wrap it in ```json fences or prose. Try strict parse first, then a
    regex fallback for the first {...} block.
    """
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        try:
            return json.loads(fence.group(1))
        except json.JSONDecodeError:
            pass
    brace = re.search(r"\{.*\}", text, re.DOTALL)
    if brace:
        try:
            return json.loads(brace.group(0))
        except json.JSONDecodeError:
            pass
    return {}


def verify(
    task_prompt: str,
    claim_text: str,
    workdir: pathlib.Path,
    session_log_path: Optional[pathlib.Path],
    verifier_model: str,
    verification_criteria: dict,
) -> dict:
    """Run the verifier on a finished cell.

    Returns {"verdict", "confidence", "issues", "reasoning"}. Missing fields
    in the LLM output default to verdict="none", confidence=0.0 so a malformed
    response can't masquerade as a passing verdict.
    """
    template = _PROMPT_PATH.read_text(encoding="utf-8")
    criteria_block = json.dumps(verification_criteria, indent=2)
    session_log_line = (
        f"Session log: {session_log_path}"
        if session_log_path is not None
        else "Session log: (none — this cell ran without a sciagent provenance log)"
    )
    user_msg = (
        f"{session_log_line}\n"
        f"Workdir: {workdir}\n\n"
        f"## Original task\n\n{task_prompt}\n\n"
        f"## Verification criteria\n\n```json\n{criteria_block}\n```\n\n"
        f"## Claimed result\n\n{claim_text}\n"
    )

    response = litellm.completion(
        model=verifier_model,
        messages=[
            {"role": "system", "content": template},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.0,
        max_tokens=4096,
    )
    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        content = ""

    parsed = _extract_json(content) if content else {}
    verdict = parsed.get("verdict")
    if verdict not in _VALID_VERDICTS:
        verdict = "none"
    try:
        confidence = float(parsed.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    return {
        "verdict": verdict,
        "confidence": confidence,
        "issues": parsed.get("issues") or [],
        "reasoning": parsed.get("reasoning") or "",
    }
