# 🐞 Bug Report Triage — Prompt Pipeline

An AI-powered prompt pipeline that converts raw bug descriptions into structured, developer-ready bug reports using multiple LLM stages.

Built using **Prompt Engineering only** — no RAG, no tools, only structured prompt chaining.

---

## Overview

Instead of using one large prompt, this project breaks bug triage into multiple smaller stages.

### Input

* Raw bug descriptions
* User complaints
* Stack traces

### Output

* Structured bug report
* Root cause analysis
* Severity classification
* Suggested fix

---

## Features

* Multi-stage prompt pipeline
* JSON-based stage handoff
* Root cause analysis
* Severity detection
* Automatic report generation
* Self-critique & retry mechanism

---

## Architecture

```text id="6eh0eg"
Raw Input
   ↓
Stage 1: Understand
   ↓
Stage 2: Reason
   ↓
Stage 3: Produce
   ↓
Stage 4: Critique
   ↓
Final Bug Report
```

Each stage is a separate LLM call, and the output of one stage becomes input to the next.

---

## Pipeline Stages

### Stage 1 — Understand

Extract key bug details like title, environment, and error message.

### Stage 2 — Reason

Analyze severity and identify likely root cause.

### Stage 3 — Produce

Generate a complete structured bug report.

### Stage 4 — Critique

Validate output quality and retry if needed.

---

## Project Structure

```bash id="a3m3yc"
prompt_pipeline/
├── pipeline.py
├── requirements.txt
├── .env
└── README.md
```

---

## Setup

Clone repository:

```bash id="brb2g2"
git clone <repo-url>
cd prompt_pipeline
```

Install dependencies:

```bash id="0v4hih"
pip install -r requirements.txt
```

Create `.env`:

```env id="8b9mkr"
OPENROUTER_API_KEY=your_key_here
```

Get API key from:
[OpenRouter](https://openrouter.ai?utm_source=chatgpt.com)

---

## Usage

Run project:

```bash id="qh5k6m"
python pipeline.py
```

Custom input:

```bash id="b5n8k6"
python pipeline.py --input "App crashes while login"
```

---

## Example

### Input

```text id="y53gmj"
App crashes when uploading large files.
```

### Output

```json id="r6bd7d"
{
  "severity": "high",
  "root_cause": "memory overflow",
  "suggested_fix": "optimize upload buffer"
}
```

---

## Weak Link Analysis

The weakest stage is **Stage 2 (Reasoning)** because the model only sees text and cannot inspect actual source code or runtime logs. This may lead to inaccurate root cause predictions.

---

## Author

**THOTA RUTHWIKA**
B.Tech Student | GenAI & Agentic AI Engineering
