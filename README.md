# Bug Report Triage — Prompt Pipeline

> **Day 2 Homework · GenAI & Agentic AI Engineering**

Transforms a raw, unstructured bug description or user complaint into a fully
structured, actionable bug report — complete with root cause analysis, severity
rating, suggested fix, and acceptance criteria — using a **four-stage LLM prompt
pipeline** built with nothing but well-engineered prompts.

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Data Flow](#data-flow)
4. [Stage Design & Prompt Techniques](#stage-design--prompt-techniques)
5. [JSON Contracts](#json-contracts)
6. [Error Handling](#error-handling)
7. [Setup](#setup)
8. [Usage](#usage)
9. [Sample Output](#sample-output)
10. [Project Structure](#project-structure)
11. [Weak-Link Analysis](#weak-link-analysis)

---

## Overview

Most real-world tasks are too complex for a single LLM prompt. This project
demonstrates the **prompt pipeline pattern**: a chain of focused prompts where
each stage does exactly one job and hands its result — as structured JSON — to
the next stage.

The task chosen is **Bug Report Triage**:

```
Input:  a raw, messy user complaint or bug description
Output: a complete, professional bug report ready to file in Jira / GitHub Issues
```

No RAG, no tools, no vector databases — only prompts and the JSON flowing between them.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        BUG REPORT TRIAGE PIPELINE                       │
│                                                                          │
│   raw text                                                               │
│      │                                                                   │
│      ▼                                                                   │
│  ┌─────────┐   brief JSON    ┌─────────┐  analysis JSON  ┌──────────┐   │
│  │ STAGE 1 │ ──────────────► │ STAGE 2 │ ───────────────► │ STAGE 3 │   │
│  │UNDERSTAND│                │  REASON │                  │ PRODUCE  │   │
│  │         │                 │         │                  │          │   │
│  │Role +   │                 │Chain-of-│                  │Goal +    │   │
│  │Struct.  │                 │Thought  │                  │Constrain │   │
│  │Output   │                 │         │                  │ts        │   │
│  └─────────┘                 └─────────┘                  └────┬─────┘   │
│                                                                │         │
│                                                      report JSON         │
│                                                                │         │
│                                                                ▼         │
│                                                          ┌──────────┐    │
│                                                          │ STAGE 4  │    │
│                                                          │CRITIQUE  │    │
│                                                          │          │    │
│                                                          │Self-Check│    │
│                                                          │+ Redo    │    │
│                                                          └────┬─────┘    │
│                                                               │          │
│                               ┌───────────────────────────── │ ──────┐  │
│                               │   passed?                     │       │  │
│                               │   yes ──► final report ◄──────┘       │  │
│                               │   no  ──► redo Stage 3 (max 3x) ──►──┘  │
│                               └───────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

Each stage is a **separate LLM call**. The output of one is the input to the next.
No stage reads raw prose from a previous stage — only structured JSON.

---

## Data Flow

```
Raw bug text
    │
    │  STAGE 1 — UNDERSTAND
    │  system: Senior QA Engineer (role prompt)
    │  task:   extract structured fields from raw text
    │
    ▼
{
  "title": "...",
  "component": "...",
  "environment": "...",
  "steps_to_reproduce": [...],
  "error_message": "...",
  "stack_trace_summary": "...",
  "reporter_description": "...",
  "missing_fields": [...]
}
    │
    │  STAGE 2 — REASON
    │  system: Principal Engineer (chain-of-thought)
    │  task:   think step-by-step, determine root cause + severity
    │
    ▼
{
  "reasoning": "step-by-step thinking...",
  "root_cause": "...",
  "root_cause_category": "data_validation | config_error | ...",
  "severity": "critical | high | medium | low",
  "severity_justification": "...",
  "affected_users": "all | most | some | few",
  "confidence": "high | medium | low"
}
    │
    │  STAGE 3 — PRODUCE
    │  system: Tech Lead (goal-oriented + constraints)
    │  task:   write complete formal bug report from stages 1+2
    │
    ▼
{
  "bug_report": { title, severity, component, environment,
                  summary, steps_to_reproduce,
                  expected_behaviour, actual_behaviour,
                  root_cause, root_cause_category },
  "suggested_fix": { approach, code_hint, files_likely_affected },
  "acceptance_criteria": [...],
  "follow_up_questions": [...]
}
    │
    │  STAGE 4 — CRITIQUE
    │  system: Strict QA Reviewer (self-check critic)
    │  task:   grade report on 6 criteria; redo Stage 3 if failed
    │
    ▼
Final report (passed 6/6) or best attempt after 3 iterations
```

---

## Stage Design & Prompt Techniques

### Stage 1 · UNDERSTAND — Role Prompting + Structured Output

**Technique:** The system prompt assigns the model a concrete expert persona
("Senior QA Engineer with 10 years of experience") and specifies an exact JSON
schema as the only acceptable output format.

**Why this works:** Role prompting activates domain-relevant knowledge and
vocabulary. Structured output with an explicit schema and "return JSON only"
instruction prevents the model from adding commentary or markdown wrappers.

**Bad-input handling:** If the input is gibberish or completely unrelated to
software bugs, the stage returns a structured error object:
```json
{"error": "unprocessable_input", "reason": "...", "stage_failed": 1}
```
This sentinel propagates cleanly through all downstream stages without crashing.

---

### Stage 2 · REASON — Chain-of-Thought

**Technique:** The system prompt explicitly instructs the model to *think step
by step* before committing to an answer, and requires the reasoning to be visible
in a `"reasoning"` field in the output JSON.

**Why this works:** Forcing the model to show its work before reaching a
conclusion dramatically reduces confident-but-wrong answers. The explicit
`reasoning` field in the schema means the chain-of-thought is both required and
inspectable — you can read exactly *why* the model concluded what it did.

**Severity guide** is embedded in the prompt to anchor the model's judgment:
```
critical = data loss / security breach / complete feature broken for all
high     = major feature broken, no workaround
medium   = feature degraded, workaround exists
low      = cosmetic / minor inconvenience
```

---

### Stage 3 · PRODUCE — Goal-Oriented Prompting + Constraints

**Technique:** The system prompt defines a clear goal ("give a developer
everything they need to find, reproduce, and fix the bug"), specifies an exact
output schema, and adds explicit constraints (every field filled, summary
readable by a PM, acceptance criteria must be testable).

**Why this works:** Goal-oriented prompting keeps the model focused on the
end-user of the output (a developer filing a ticket). Constraints prevent lazy
outputs — e.g., "use 'unknown' only if truly indeterminate" stops the model
from defaulting to unknown for everything.

**Inputs:** Receives both Stage 1 JSON (facts) and Stage 2 JSON (analysis)
simultaneously, so it can synthesise all available information into one report.

---

### Stage 4 · CRITIQUE — Self-Check Critic + Redo Loop

**Technique:** A separate "strict QA Reviewer" LLM call audits the Stage 3
output against 6 named, pass/fail criteria. If any criterion fails, the specific
failure notes are fed back into Stage 3 as a redo prompt. This loop runs up to
3 times before accepting the best result.

**The 6 criteria:**
| # | Criterion | What fails it |
|---|-----------|---------------|
| 1 | title | Generic ("App crashes") with no specifics |
| 2 | severity | Not one of: critical / high / medium / low |
| 3 | steps | Fewer than 2 concrete, numbered steps |
| 4 | root_cause | Vague restatement of symptom, no mechanism |
| 5 | suggested_fix | Just "N/A" or "investigate further" |
| 6 | acceptance | Fewer than 2 testable, unambiguous criteria |

**Why this works:** The model acting as its own critic catches quality issues
that slipped through the production stage. Sending the specific failure notes
back (not just "try again") gives Stage 3 targeted instructions to fix.

**Max-iterations guard:** `MAX_CRITIQUE_ITERATIONS = 3` prevents infinite loops.
If the report still hasn't passed after 3 redos, the best result so far is
accepted and the run completes.

---

## JSON Contracts

Every stage-to-stage handoff is a typed JSON contract. If a stage returns
invalid JSON, `call_with_json_retry()` retries up to 3 times, feeding the exact
parse error back to the model so it can self-correct.

### Stage 1 → Stage 2 (bug brief)
```json
{
  "title": "string",
  "component": "string",
  "environment": "string",
  "steps_to_reproduce": ["string"],
  "error_message": "string",
  "stack_trace_summary": "string",
  "reporter_description": "string",
  "missing_fields": ["string"]
}
```

### Stage 2 → Stage 3 (root cause analysis)
```json
{
  "reasoning": "string",
  "root_cause": "string",
  "root_cause_category": "null_pointer|race_condition|config_error|api_contract|memory_leak|auth_failure|data_validation|dependency_failure|ui_logic|other",
  "severity": "critical|high|medium|low",
  "severity_justification": "string",
  "affected_users": "all|most|some|few",
  "confidence": "high|medium|low"
}
```

### Stage 3 → Stage 4 (full bug report)
```json
{
  "bug_report": {
    "title": "string",
    "severity": "critical|high|medium|low",
    "component": "string",
    "environment": "string",
    "summary": "string",
    "steps_to_reproduce": ["string"],
    "expected_behaviour": "string",
    "actual_behaviour": "string",
    "root_cause": "string",
    "root_cause_category": "string"
  },
  "suggested_fix": {
    "approach": "string",
    "code_hint": "string",
    "files_likely_affected": ["string"]
  },
  "acceptance_criteria": ["string"],
  "follow_up_questions": ["string"]
}
```

### Stage 4 verdict
```json
{
  "passed": true,
  "score": 6,
  "criteria": {
    "title":         {"pass": true,  "note": "string"},
    "severity":      {"pass": true,  "note": "string"},
    "steps":         {"pass": false, "note": "string"},
    "root_cause":    {"pass": true,  "note": "string"},
    "suggested_fix": {"pass": true,  "note": "string"},
    "acceptance":    {"pass": true,  "note": "string"}
  },
  "improvement_notes": "string"
}
```

---

## Error Handling

| Situation | How it's handled |
|-----------|-----------------|
| Gibberish / non-bug input | Stage 1 returns `{"error": "unprocessable_input", ...}` |
| Stage 1 error | Stage 2 detects `"error"` key, skips analysis, returns `{"error": "stage1_failed", ...}` |
| Any upstream error | Stage 3 detects error, returns `{"error": "upstream_stage_failed", ...}` |
| Upstream error in Stage 4 | Stage 4 detects error, skips critique, passes through with score 0 |
| Invalid JSON from LLM | `call_with_json_retry()` retries up to 3 times with the parse error shown to the model |
| Stage 4 never passes | After `MAX_CRITIQUE_ITERATIONS = 3` redos, accepts best result and continues |

---

## Setup

### 1. Clone

```bash
git clone <repo-url>
cd prompt_pipeline
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure API key

Create a `.env` file in the project root:

```
OPENROUTER_API_KEY=sk-or-v1-...
```

Get a free key at [openrouter.ai](https://openrouter.ai) → Keys → Create Key.

The pipeline calls `openai/gpt-4o-mini` via OpenRouter. To use a different
model, change the `MODEL` constant near the top of `pipeline.py`.

---

## Usage

```bash
# Run all 3 built-in test cases
python pipeline.py

# Run a single built-in test case
python pipeline.py --test 1   # clear bug with stack trace
python pipeline.py --test 2   # vague complaint, partial info
python pipeline.py --test 3   # gibberish / unprocessable input

# Run with your own bug description
python pipeline.py --input "App crashes when I upload a file larger than 10 MB."

# Save the final JSON report to a file
python pipeline.py --test 1 --output report.json
python pipeline.py --output reports/all.json          # all 3 as a JSON list
python pipeline.py --input "..." --output my_report.json
```

Parent directories for `--output` are created automatically.

---

## Sample Output

### Input (Test 1 — clear bug with stack trace)

```
App crashes on login when the password contains special characters like !@#.

Steps:
1. Open the app on Chrome 124 / Windows 11
2. Enter a valid email
3. Enter a password with special chars e.g. "P@ssw0rd!"
4. Click "Sign In"

Expected: User logs in successfully.
Actual: 500 Internal Server Error. Backend logs show:
  File "auth/views.py", line 87, in login_view
    token = jwt.encode({"user": user.id}, settings.SECRET_KEY)
  TypeError: a bytes-like object is required, str given

Using Django 4.2, PyJWT 2.8.0, PostgreSQL 15.
```

### Final report (Stage 4 · PASSED 6/6)

```json
{
  "bug_report": {
    "title": "App crashes on login with special characters in password",
    "severity": "high",
    "component": "Authentication",
    "environment": "Windows 11, Chrome 124",
    "summary": "The application crashes when users attempt to log in with a password containing special characters, returning a 500 Internal Server Error. This prevents affected users from accessing their accounts entirely.",
    "steps_to_reproduce": [
      "Open the app on Chrome 124 / Windows 11",
      "Enter a valid email address",
      "Enter a password containing special characters e.g. 'P@ssw0rd!'",
      "Click 'Sign In'"
    ],
    "expected_behaviour": "User is logged in successfully regardless of special characters in the password.",
    "actual_behaviour": "A 500 Internal Server Error is returned. Backend logs show TypeError: a bytes-like object is required, str given at auth/views.py line 87.",
    "root_cause": "jwt.encode() in PyJWT 2.x returns a string, but the code passes settings.SECRET_KEY as bytes, causing a TypeError at token generation.",
    "root_cause_category": "data_validation"
  },
  "suggested_fix": {
    "approach": "Ensure SECRET_KEY is passed as a string (not bytes) to jwt.encode(), or decode it before use. PyJWT 2.x changed the return type and key type expectations from 1.x.",
    "code_hint": "token = jwt.encode({'user': user.id}, settings.SECRET_KEY.decode('utf-8'), algorithm='HS256')",
    "files_likely_affected": ["auth/views.py", "settings.py"]
  },
  "acceptance_criteria": [
    "Users can log in successfully with passwords containing !@#$%^&*() without any server errors.",
    "No 500 errors appear in backend logs when authenticating with special-character passwords."
  ],
  "follow_up_questions": []
}
```

### Input (Test 3 — gibberish)

```
asdfghjkl zxcvbnm qwerty 12345 !!!???
pizza banana helicopter lorem ipsum dolor sit amet
```

### Output (error propagated cleanly)

```json
{
  "error": "upstream_stage_failed",
  "bug_report": null,
  "suggested_fix": null,
  "message": "Cannot produce report: an earlier stage failed."
}
```

---

## Project Structure

```
prompt_pipeline/
├── pipeline.py        # Entire pipeline — prompts, stages, CLI, display
├── requirements.txt   # Pinned dependencies (openai, python-dotenv)
├── .env               # API key — NOT committed to git
├── .gitignore         # Excludes .env and reports/
└── README.md          # This file
```

`pipeline.py` is intentionally a single file. The four logical sections are:

| Lines | Section |
|-------|---------|
| 1–30 | Module docstring + imports |
| 31–60 | Configuration (model, retries, temperature) |
| 61–220 | Prompts (STAGE1–4 system + user templates) |
| 221–280 | LLM client + `call_llm()` + `call_with_json_retry()` |
| 281–420 | Pipeline stage functions (`stage1_` through `stage4_`) |
| 421–470 | `run()` — chains stages, prints each step |
| 471–510 | Built-in test inputs |
| 511–570 | Display helpers + weak-link reflection constant |
| 571–620 | `main()` — argparse CLI entry point |

---

## Weak-Link Analysis

The weakest stage is **Stage 2 (REASON)**.

**The problem:** While chain-of-thought forces the model to show its reasoning,
that reasoning is based entirely on the *text pattern* of the error message. The
model has no access to the actual source code, dependency versions, or runtime
state. A `TypeError` can mean a dozen different things depending on the code —
Stage 2 has to guess which one from text alone.

**How you'd know it's failing:** Stage 3 produces a generic fix like
"implement proper input validation" or "add null checks" rather than pointing at
a specific line, function, or dependency version mismatch.

**What would fix it:**

| Day | Improvement |
|-----|------------|
| Day 4 | Feed Stage 2 the actual source file contents around the failing frame using RAG. The model would see the exact code and could reason about the real type mismatch instead of guessing. |
| Day 6–8 | Add a tool-call to query an error monitoring system (e.g., Sentry) or run the test suite. The model could *confirm* the root cause empirically instead of inferring it from text. |

This is the skeleton of an agent — on Day 4 it gets memory (retrieval), on
Days 6–8 it gets tools (actions). The prompt pipeline built here is the same
architecture, just without those additions yet.
