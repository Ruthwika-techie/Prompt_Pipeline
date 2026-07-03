"""
pipeline.py
===========
Bug Report Triage — Prompt Pipeline
Day 2 Homework · GenAI & Agentic AI Engineering
------------------------------------------------
Transforms a raw bug description + stack trace into a structured
bug report with root cause analysis, severity rating, and a
suggested fix.

Pipeline stages
---------------
  Stage 1 · UNDERSTAND   Role Prompting + Structured Output
                         Extracts: title, component, environment,
                         steps_to_reproduce, error_message, stack_trace_summary
  Stage 2 · REASON       Chain-of-Thought
                         Thinks step-by-step to determine: root_cause,
                         severity, affected_users, reasoning
  Stage 3 · PRODUCE      Goal-Oriented Prompting
                         Writes a complete structured bug report with
                         suggested fix and acceptance criteria
  Stage 4 · CRITIQUE     Self-Check Critic
                         Grades Stage 3 output against 6 criteria; sends it
                         back for a redo if it fails (max 3 iterations)

JSON flows between every stage — no raw prose is passed forward.

Usage
-----
  python pipeline.py                        # runs all 3 built-in test cases
  python pipeline.py --input "..."          # supply a custom bug description
  python pipeline.py --test 1              # run a single built-in test case
  python pipeline.py --output report.json  # save final JSON report to a file
  python pipeline.py --test 2 --output out/report.json
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import textwrap
from typing import Any

# ── Force UTF-8 output on Windows (cp1252 can't handle box-drawing chars) ────
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv
from openai import OpenAI

# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────

load_dotenv()

MODEL       = "openai/gpt-4o-mini"
MAX_RETRIES = 3
TEMPERATURE = 0.2

# ─────────────────────────────────────────────
# Prompts
# ─────────────────────────────────────────────

# ── Stage 1 ── UNDERSTAND (Role + Structured Output) ──────────────────────────

STAGE1_SYSTEM = """\
You are a Senior QA Engineer with 10 years of experience triaging software bugs.
Your job is to read a raw bug report or user complaint and extract key information
into a clean, structured JSON object.

OUTPUT FORMAT — return ONLY this JSON, nothing else:
{
  "title":               "<short one-line summary of the bug>",
  "component":           "<affected module/service/feature>",
  "environment":         "<OS, browser, version, or 'unknown' if not stated>",
  "steps_to_reproduce":  ["<step 1>", "<step 2>", "..."],
  "error_message":       "<exact error text or 'none'>",
  "stack_trace_summary": "<first meaningful frame or 'none'>",
  "reporter_description": "<the original complaint in one sentence>",
  "missing_fields":      ["<list any key fields that are absent>"]
}

Rules:
- If a field cannot be determined, use "unknown" (strings) or [] (arrays).
- For missing_fields, list fields like "environment", "steps_to_reproduce", etc.
- Do NOT add commentary, markdown, or code fences. Return JSON only.
- If the input is gibberish or completely unrelated to software bugs, return:
  {"error": "unprocessable_input", "reason": "<why>", "stage_failed": 1}
"""

STAGE1_USER = """\
Raw bug report:
---
{text}
---
Extract all fields and return the JSON object.
"""

# ── Stage 2 ── REASON (Chain-of-Thought) ──────────────────────────────────────

STAGE2_SYSTEM = """\
You are a Principal Software Engineer performing root cause analysis.
You will receive structured bug information (JSON) from Stage 1.

Think step by step before reaching your conclusion. Your reasoning MUST be
visible in the "reasoning" field — show your chain of thought, not just the answer.

OUTPUT FORMAT — return ONLY this JSON, nothing else:
{
  "reasoning": "<your step-by-step thinking: what does the error mean? what component? what is the most likely cause? consider alternatives and rule them out>",
  "root_cause": "<concise root cause in one sentence>",
  "root_cause_category": "<one of: null_pointer | race_condition | config_error | api_contract | memory_leak | auth_failure | data_validation | dependency_failure | ui_logic | other>",
  "severity": "<one of: critical | high | medium | low>",
  "severity_justification": "<one sentence explaining the severity rating>",
  "affected_users": "<one of: all | most | some | few>",
  "confidence": "<one of: high | medium | low>"
}

Severity guide:
  critical = data loss / security breach / complete feature broken for all
  high     = major feature broken, no workaround
  medium   = feature degraded, workaround exists
  low      = cosmetic / minor inconvenience

Do NOT add markdown or code fences. Return JSON only.
"""

STAGE2_USER = """\
Stage 1 output (structured bug brief):
---
{stage1_json}
---
Perform root cause analysis step-by-step and return the JSON.
"""

# ── Stage 3 ── PRODUCE (Goal-Oriented + Constraints) ──────────────────────────

STAGE3_SYSTEM = """\
You are a Tech Lead writing the final formal bug report that will be filed in
the issue tracker and handed to the engineering team.

Your goal: produce a complete, actionable bug report that gives a developer
everything they need to find, reproduce, and fix the bug.

OUTPUT FORMAT — return ONLY this JSON, nothing else:
{
  "bug_report": {
    "title":               "<clear, searchable title>",
    "severity":            "<from Stage 2>",
    "component":           "<from Stage 1>",
    "environment":         "<from Stage 1>",
    "summary":             "<2–3 sentence plain-English description of the bug and its impact>",
    "steps_to_reproduce":  ["<numbered steps>"],
    "expected_behaviour":  "<what should happen>",
    "actual_behaviour":    "<what actually happens, including the error>",
    "root_cause":          "<from Stage 2>",
    "root_cause_category": "<from Stage 2>"
  },
  "suggested_fix": {
    "approach":            "<1–2 sentence description of the fix strategy>",
    "code_hint":           "<pseudocode or specific code change, or 'N/A' if not determinable>",
    "files_likely_affected": ["<filename or module>"]
  },
  "acceptance_criteria": [
    "<criterion 1 — testable>",
    "<criterion 2 — testable>"
  ],
  "follow_up_questions": ["<any clarifying questions needed, or [] if none>"]
}

Constraints:
- Every field must be filled. Use "unknown" only if truly indeterminate.
- summary must be readable by a non-technical product manager.
- acceptance_criteria must be testable and unambiguous.
- Do NOT add markdown or code fences. Return JSON only.
"""

STAGE3_USER = """\
Stage 1 (bug brief):
---
{stage1_json}
---
Stage 2 (root cause analysis):
---
{stage2_json}
---
Write the complete formal bug report JSON.
"""

# ── Stage 4 ── CRITIQUE (Self-Check Critic) ───────────────────────────────────

STAGE4_SYSTEM = """\
You are a strict QA Reviewer auditing a bug report before it is filed.
You will receive the final bug report JSON produced by Stage 3.

Grade it against these criteria — each is pass/fail:
  1. title        — clear, specific, and searchable (not generic like "App crashes")
  2. severity     — one of: critical | high | medium | low
  3. steps        — at least 2 concrete, numbered steps to reproduce
  4. root_cause   — a specific cause, not a vague restatement of the symptom
  5. suggested_fix — contains a real approach (not just "N/A" or "investigate")
  6. acceptance   — at least 2 testable, unambiguous acceptance criteria

OUTPUT FORMAT — return ONLY this JSON, nothing else:
{
  "passed": true | false,
  "score": <integer 0–6, one point per passing criterion>,
  "criteria": {
    "title":         {"pass": true|false, "note": "<one sentence>"},
    "severity":      {"pass": true|false, "note": "<one sentence>"},
    "steps":         {"pass": true|false, "note": "<one sentence>"},
    "root_cause":    {"pass": true|false, "note": "<one sentence>"},
    "suggested_fix": {"pass": true|false, "note": "<one sentence>"},
    "acceptance":    {"pass": true|false, "note": "<one sentence>"}
  },
  "improvement_notes": "<if passed=false: concise instructions for what Stage 3 must fix on its redo; empty string if passed=true>"
}

Rules:
- passed = true only if ALL 6 criteria pass (score == 6).
- Be strict. A vague root_cause like "improper handling" with no mechanism fails.
- Do NOT add markdown or code fences. Return JSON only.
"""

STAGE4_USER = """\
Stage 3 bug report to audit:
---
{stage3_json}
---
Grade each criterion and return the JSON verdict.
"""

STAGE3_REDO_USER = """\
Your previous bug report was rejected by the QA reviewer.

Reviewer feedback:
---
{improvement_notes}
---

Failing criteria:
{failing_criteria}

Original Stage 1 brief:
---
{stage1_json}
---

Original Stage 2 analysis:
---
{stage2_json}
---

Rewrite the complete bug report JSON fixing every issue the reviewer raised.
Return ONLY valid JSON — no markdown, no code fences.
"""

MAX_CRITIQUE_ITERATIONS = 3   # max redo attempts before accepting best result

# ─────────────────────────────────────────────
# LLM client (OpenRouter)
# ─────────────────────────────────────────────

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            print("[ERROR] OPENROUTER_API_KEY not found in .env", file=sys.stderr)
            sys.exit(1)
        _client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
        )
    return _client


def call_llm(system_prompt: str, user_prompt: str, max_tokens: int = 800) -> str:
    """Single LLM call. Returns raw text response."""
    response = _get_client().chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        max_tokens=max_tokens,
        temperature=TEMPERATURE,
    )
    return response.choices[0].message.content.strip()


# ─────────────────────────────────────────────
# JSON parsing with retry
# ─────────────────────────────────────────────

def parse_json(raw: str) -> dict[str, Any]:
    """
    Parse raw LLM output as JSON.
    Strips markdown code fences if the model wraps its output.
    """
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        inner = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        cleaned = "\n".join(inner).strip()
    return json.loads(cleaned)


def call_with_json_retry(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 800,
    stage_name: str = "unknown",
) -> dict[str, Any]:
    """
    Call the LLM and parse JSON, retrying up to MAX_RETRIES times.
    On each failure the model is shown the exact error and asked to correct it.
    """
    current_user = user_prompt
    last_error: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        raw = call_llm(system_prompt, current_user, max_tokens)
        try:
            return parse_json(raw)
        except json.JSONDecodeError as exc:
            last_error = exc
            _warn(f"[{stage_name}] JSON parse error (attempt {attempt}/{MAX_RETRIES}): {exc}")
            _warn(f"  Bad output (first 200 chars): {raw[:200]}")
            # Feed the error back to the model so it can self-correct
            current_user = (
                f"Your previous response could not be parsed as JSON.\n\n"
                f"Parse error: {exc}\n\n"
                f"Problematic output:\n{raw}\n\n"
                f"Return ONLY valid JSON, no markdown, no code fences, no explanations."
            )

    raise RuntimeError(
        f"[{stage_name}] Failed to get valid JSON after {MAX_RETRIES} attempts. "
        f"Last error: {last_error}"
    )


# ─────────────────────────────────────────────
# Pipeline stages
# ─────────────────────────────────────────────

def stage1_understand(raw_text: str) -> dict[str, Any]:
    """
    Stage 1 — UNDERSTAND (Role Prompting + Structured Output)
    Reads the raw bug report and extracts structured fields as JSON.
    """
    user_prompt = STAGE1_USER.format(text=raw_text.strip())
    return call_with_json_retry(STAGE1_SYSTEM, user_prompt, max_tokens=600, stage_name="STAGE1")


def stage2_reason(brief: dict[str, Any]) -> dict[str, Any]:
    """
    Stage 2 — REASON (Chain-of-Thought)
    Performs step-by-step root cause analysis on the structured brief.
    """
    # Abort if Stage 1 flagged an error
    if "error" in brief:
        return {
            "error": "stage1_failed",
            "root_cause": "Could not extract bug information — see stage1 error.",
            "severity": "unknown",
            "reasoning": "Stage 1 returned an error; analysis skipped.",
        }
    stage1_json = json.dumps(brief, indent=2)
    user_prompt = STAGE2_USER.format(stage1_json=stage1_json)
    return call_with_json_retry(STAGE2_SYSTEM, user_prompt, max_tokens=800, stage_name="STAGE2")


def stage3_produce(brief: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
    """
    Stage 3 — PRODUCE (Goal-Oriented + Constraints)
    Generates a complete structured bug report with suggested fix.
    """
    # Propagate upstream errors gracefully
    if "error" in brief or "error" in analysis:
        return {
            "error": "upstream_stage_failed",
            "bug_report": None,
            "suggested_fix": None,
            "message": "Cannot produce report: an earlier stage failed.",
        }
    stage1_json = json.dumps(brief, indent=2)
    stage2_json = json.dumps(analysis, indent=2)
    user_prompt = STAGE3_USER.format(stage1_json=stage1_json, stage2_json=stage2_json)
    return call_with_json_retry(STAGE3_SYSTEM, user_prompt, max_tokens=1200, stage_name="STAGE3")


def stage4_critique(
    report: dict[str, Any],
    brief: dict[str, Any],
    analysis: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Stage 4 — CRITIQUE (Self-Check Critic)
    Grades the Stage 3 report against 6 criteria. If it fails, asks Stage 3
    to redo with the reviewer's notes. Loops up to MAX_CRITIQUE_ITERATIONS times.

    Returns (final_report, last_verdict).
    """
    # If upstream failed there is nothing to critique — pass through
    if "error" in report:
        verdict = {
            "passed": False,
            "score": 0,
            "criteria": {},
            "improvement_notes": "Upstream stage failed — no report to critique.",
        }
        return report, verdict

    current_report = report
    last_verdict: dict[str, Any] = {}

    for iteration in range(1, MAX_CRITIQUE_ITERATIONS + 1):
        stage3_json = json.dumps(current_report, indent=2)
        user_prompt = STAGE4_USER.format(stage3_json=stage3_json)
        verdict = call_with_json_retry(
            STAGE4_SYSTEM, user_prompt, max_tokens=800, stage_name="STAGE4"
        )
        last_verdict = verdict

        _section(
            f"STAGE 4 VERDICT (iteration {iteration}/{MAX_CRITIQUE_ITERATIONS})",
            json.dumps(verdict, indent=2),
        )

        if verdict.get("passed", False):
            # Report passed — no redo needed
            break

        if iteration == MAX_CRITIQUE_ITERATIONS:
            # Guard: hit the limit, accept best result so far
            _warn(
                f"[STAGE4] Max iterations ({MAX_CRITIQUE_ITERATIONS}) reached. "
                "Accepting last report as-is."
            )
            break

        # Build the list of failing criteria for the redo prompt
        failing = [
            f"  - {name}: {detail.get('note', '')}"
            for name, detail in verdict.get("criteria", {}).items()
            if not detail.get("pass", True)
        ]
        failing_str = "\n".join(failing) if failing else "  (see improvement_notes)"

        redo_user = STAGE3_REDO_USER.format(
            improvement_notes=verdict.get("improvement_notes", ""),
            failing_criteria=failing_str,
            stage1_json=json.dumps(brief, indent=2),
            stage2_json=json.dumps(analysis, indent=2),
        )
        _warn(f"[STAGE4] Report failed (score {verdict.get('score', '?')}/6) — requesting redo.")
        current_report = call_with_json_retry(
            STAGE3_SYSTEM, redo_user, max_tokens=1400, stage_name="STAGE3-REDO"
        )
        _section(f"STAGE 3 REDO (iteration {iteration})", json.dumps(current_report, indent=2))

    return current_report, last_verdict


# ─────────────────────────────────────────────
# Pipeline runner
# ─────────────────────────────────────────────

def run(raw_text: str, label: str = "") -> dict[str, Any]:
    """
    Run all four stages and print each step's input/output.
    Returns the final (post-critique) report.
    """
    _header(f"PIPELINE RUN{': ' + label if label else ''}")
    _section("INPUT", raw_text)

    # ── Stage 1 ──
    _stage_banner("STAGE 1 · UNDERSTAND", "Role Prompting + Structured Output")
    _print_prompt_preview(STAGE1_SYSTEM, STAGE1_USER.format(text=raw_text))
    brief = stage1_understand(raw_text)
    _section("STAGE 1 OUTPUT", json.dumps(brief, indent=2))

    # ── Stage 2 ──
    _stage_banner("STAGE 2 · REASON", "Chain-of-Thought")
    _section("STAGE 2 INPUT", json.dumps(brief, indent=2))
    analysis = stage2_reason(brief)
    _section("STAGE 2 OUTPUT", json.dumps(analysis, indent=2))

    # ── Stage 3 ──
    _stage_banner("STAGE 3 · PRODUCE", "Goal-Oriented Prompting + Constraints")
    _section("STAGE 3 INPUT", "[Stage 1 JSON] + [Stage 2 JSON]  (see above)")
    report = stage3_produce(brief, analysis)
    _section("STAGE 3 OUTPUT", json.dumps(report, indent=2))

    # ── Stage 4 ──
    _stage_banner("STAGE 4 · CRITIQUE", "Self-Check Critic + Redo Loop")
    report, verdict = stage4_critique(report, brief, analysis)
    passed = verdict.get("passed", False)
    score  = verdict.get("score", "?")
    _section(
        f"STAGE 4 FINAL — {'✓ PASSED' if passed else '✗ ACCEPTED AFTER MAX RETRIES'} "
        f"(score {score}/6)",
        json.dumps(report, indent=2),
    )

    _footer()
    return report


# ─────────────────────────────────────────────
# Test inputs
# ─────────────────────────────────────────────

TEST_INPUTS = [
    # ── Test 1: Normal, well-described bug with stack trace ──────────────────
    (
        "Test 1 — Normal (clear bug + stack trace)",
        """\
App crashes on login when the password contains special characters like !@#.

Steps:
1. Open the app on Chrome 124 / Windows 11
2. Enter a valid email
3. Enter a password with special chars e.g. "P@ssw0rd!"
4. Click "Sign In"

Expected: User logs in successfully.
Actual: 500 Internal Server Error is returned. The backend logs show:

  File "auth/views.py", line 87, in login_view
    token = jwt.encode({"user": user.id}, settings.SECRET_KEY)
  TypeError: a bytes-like object is required, str given

Using Django 4.2, PyJWT 2.8.0, PostgreSQL 15.
"""
    ),

    # ── Test 2: Tricky — vague complaint, no stack trace, wrong language ─────
    (
        "Test 2 — Tricky (vague + partial info only)",
        """\
The dashboard just doesn't load anymore. It worked yesterday.
I'm getting some kind of white screen. No error message shown.
I use it on my laptop. Tried refreshing but still blank.
Please fix ASAP — I need this for my presentation tomorrow.
"""
    ),

    # ── Test 3: Broken — gibberish input ─────────────────────────────────────
    (
        "Test 3 — Broken (gibberish / unprocessable input)",
        """\
asdfghjkl zxcvbnm qwerty 12345 !!!???
pizza banana helicopter lorem ipsum dolor sit amet
this is not a bug report lol
"""
    ),
]


# ─────────────────────────────────────────────
# Display helpers
# ─────────────────────────────────────────────

WIDTH = 80


def _header(title: str) -> None:
    print("\n" + "═" * WIDTH)
    print(f"  {title}")
    print("═" * WIDTH)


def _footer() -> None:
    print("═" * WIDTH + "\n")


def _stage_banner(name: str, technique: str) -> None:
    print(f"\n{'─' * WIDTH}")
    print(f"  ▶ {name}")
    print(f"    Technique: {technique}")
    print(f"{'─' * WIDTH}")


def _section(title: str, content: str) -> None:
    print(f"\n  ── {title} ──")
    # Wrap long lines so output stays within WIDTH columns.
    # JSON blocks are indented with leading spaces; preserve them.
    for line in content.splitlines():
        stripped = line.lstrip()
        indent = " " * (len(line) - len(stripped))
        wrapped = textwrap.fill(
            stripped,
            width=WIDTH - 2,                # -2 for the "  " prefix
            initial_indent=f"  {indent}",
            subsequent_indent=f"  {indent}  ",
        )
        print(wrapped if wrapped else "")
    print()


def _print_prompt_preview(system: str, user: str) -> None:
    """Print a truncated preview of the prompts being sent."""
    sys_preview = system.strip().splitlines()[0][:100]
    usr_preview = user.strip()[:120].replace("\n", " ")
    print(f"\n  [Prompt preview]")
    print(f"    system : {sys_preview}...")
    print(f"    user   : {usr_preview}...")


def _warn(msg: str) -> None:
    print(f"\n  ⚠  {msg}", file=sys.stderr)


# ─────────────────────────────────────────────
# Weak-link reflection
# ─────────────────────────────────────────────

WEAK_LINK_REFLECTION = """
╔══════════════════════════════════════════════════════════════════════════════╗
║  WEAK-LINK REFLECTION                                                        ║
╚══════════════════════════════════════════════════════════════════════════════╝

The weakest stage is Stage 2 (REASON). While the chain-of-thought prompt forces
the model to think step-by-step, its root cause analysis is entirely based on
the text pattern of the error message — it has no access to the actual codebase,
dependency versions, or runtime state. This means it can confidently produce a
plausible-sounding but completely wrong root cause for ambiguous errors (e.g., a
"TypeError" could mean a dozen different things). You'd know it's failing when
the suggested fix from Stage 3 is generic ("add null checks") rather than
pointing at specific lines. On Day 4, feeding Stage 2 a retrieval context of
the actual file contents around the failing frame would dramatically sharpen its
analysis. On Days 6–8, a tool-call to run the test suite or query the error
monitoring system (e.g., Sentry) would let it confirm the root cause empirically
rather than inferring it from text alone.
"""


# ─────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bug Report Triage — Prompt Pipeline (Day 2 Homework)"
    )
    parser.add_argument(
        "--input", "-i",
        type=str,
        default=None,
        help="Custom bug description to run through the pipeline",
    )
    parser.add_argument(
        "--test", "-t",
        type=int,
        choices=[1, 2, 3],
        default=None,
        help="Run a single built-in test case (1, 2, or 3)",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        metavar="FILE",
        help="Save the final JSON report(s) to this file (e.g. report.json)",
    )
    args = parser.parse_args()

    reports: list[dict] = []

    if args.input:
        report = run(args.input, label="Custom Input")
        reports.append(report)
    elif args.test:
        label, text = TEST_INPUTS[args.test - 1]
        report = run(text, label=label)
        reports.append(report)
    else:
        # Run all 3 test cases
        for label, text in TEST_INPUTS:
            report = run(text, label=label)
            reports.append(report)

    print(WEAK_LINK_REFLECTION)

    # ── Save to file if --output was requested ────────────────────────────────
    if args.output:
        output_path = args.output
        # Create parent directories if they don't exist
        parent = os.path.dirname(output_path)
        if parent:
            os.makedirs(parent, exist_ok=True)

        # Write single report directly, multiple reports as a list
        payload = reports[0] if len(reports) == 1 else reports
        with open(output_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)

        print(f"  ✓  Report saved → {output_path}\n")


if __name__ == "__main__":
    main()
