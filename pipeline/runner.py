"""
runner.py

Orchestrates the MVP v1 investigation pipeline for a single scenario:

    1. Load the scenario (scenario_loader)
    2. Run the simulated classifier on the symptom description (simulated_classifier)
    3. Load relevant knowledge base files (knowledge_loader)
    4. Build a controlled prompt — the answer key never touches this step
    5. Call Gemini once → produces Stage 1 (triage) + Stage 2 (hypotheses)
       + Stage 3 (investigation plan)
    6. Save the output to outputs/
    7. Print a summary

MVP v1 scope: one Gemini call, Stages 1-3 only.
Not yet implemented: Stage 4 (engineer feedback), Stage 5 (synthesis),
Stage 6 (final report). Those come in MVP v2.

Usage:
    python pipeline/runner.py DHCP-001
    python pipeline/runner.py SERVFAIL-002
    python pipeline/runner.py scenario_dhcp_001.txt
"""

import os
import sys
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Path fix — allows running this file directly from the project root
#
# When you run `python pipeline/runner.py`, Python adds the pipeline/
# directory to sys.path, not the project root. That means imports like
# `from pipeline.scenario_loader import ...` would fail.
#
# This line inserts the project root at the front of sys.path so all
# pipeline module imports work correctly regardless of how you run this.
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from google import genai

from pipeline.scenario_loader import load_scenario
from pipeline.simulated_classifier import classify_incident
from pipeline.knowledge_loader import load_knowledge_base, format_for_prompt


# ---------------------------------------------------------------------------
# Directory where generated reports are saved
# Created automatically on first run if it does not exist.
# ---------------------------------------------------------------------------
OUTPUTS_DIR = Path(__file__).parent.parent / "outputs"


# ---------------------------------------------------------------------------
# Prompt construction
#
# This is the most important function in this file.
# It decides exactly what Gemini sees — no more, no less.
#
# Inputs that DO go into the prompt:
#   - symptom_description  (what the engineer reported)
#   - classifier_output    (incident type, confidence, matched signals)
#   - knowledge_chunks     (curated DDI domain knowledge)
#
# Inputs that NEVER go into the prompt:
#   - scenario.answer_key  (expected triage, hypotheses, investigation plan)
#
# The answer key isolation is enforced here, not just documented.
# If you ever find yourself passing scenario.answer_key into this
# function, that is the leakage problem — stop and question it.
# ---------------------------------------------------------------------------

def build_prompt(symptom_description: str,
                 classifier_output,
                 knowledge_chunks: list) -> str:
    """
    Assemble the full context and instructions for Gemini's first call.

    Args:
        symptom_description: Raw engineer report from the scenario loader.
        classifier_output:   ClassifierOutput from simulated_classifier.
        knowledge_chunks:    List of KnowledgeChunk from knowledge_loader.

    Returns:
        A single formatted string ready to send to Gemini.
    """
    # Format matched signals as a readable list for the prompt
    signals_text = (
        "\n".join(f"  - {s}" for s in classifier_output.matched_signals)
        if classifier_output.matched_signals
        else "  (no specific signals matched)"
    )

    # Format all knowledge chunks with source headers
    knowledge_text = format_for_prompt(knowledge_chunks)

    prompt = f"""You are a DDI (DNS, DHCP, IPAM) incident investigation assistant.

Your role is to reason systematically about network incidents using the domain \
knowledge provided, generate ranked hypotheses about the root cause, and produce \
a structured investigation plan for a human engineer to execute.

You do not resolve incidents. You do not access live systems. \
Your output is always subject to human review before any action is taken.

=====================================
INCIDENT REPORT (as logged by the engineer):
=====================================
{symptom_description}

=====================================
AUTOMATED CLASSIFIER OUTPUT:
=====================================
Incident type : {classifier_output.incident_type}
Confidence    : {classifier_output.confidence:.0%}
Matched signals:
{signals_text}

=====================================
DOMAIN KNOWLEDGE:
=====================================
{knowledge_text}

=====================================
INSTRUCTIONS:
=====================================
Using only the incident report, classifier output, and domain knowledge above, \
produce the following three sections. Follow the format exactly.

STAGE 1 — TRIAGE
- Confirm or adjust the incident classification and briefly explain why
- Scope: is this localized (one subnet / one site) or potentially widespread?
- Severity: assign one of Low / Medium / Medium-High / High / Critical \
with a one-sentence justification

STAGE 2 — HYPOTHESES (ranked by likelihood)
List 3 to 4 hypotheses for the root cause. For each hypothesis:
- State it clearly and concisely
- Assign likelihood: low / medium / high
- Explain your reasoning based on the symptom pattern described, \
not just the knowledge base content

STAGE 3 — INVESTIGATION PLAN
For each hypothesis in Stage 2, define one specific investigation step. \
For each step:
- Describe exactly what to check (be specific: which log, metric, table, or field)
- State what finding would confirm that hypothesis
- State what finding would rule out that hypothesis

End your entire response with this line, exactly as written:
HUMAN REVIEW REQUIRED — These findings must be reviewed and approved by a qualified engineer before any remediation is attempted."""

    return prompt


# ---------------------------------------------------------------------------
# Output saving
# ---------------------------------------------------------------------------

def save_output(scenario_id: str, content: str) -> Path:
    """
    Save the generated investigation report to the outputs/ directory.

    Filename: {scenario_id}_investigation_{timestamp}.md
    The timestamp prevents overwriting previous runs during testing.

    Returns the path to the saved file.
    """
    OUTPUTS_DIR.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{scenario_id}_investigation_{timestamp}.md"
    output_path = OUTPUTS_DIR / filename

    output_path.write_text(content, encoding="utf-8")
    return output_path


# ---------------------------------------------------------------------------
# Main pipeline — MVP v1
# ---------------------------------------------------------------------------

def run_investigation(scenario_identifier: str) -> None:
    """
    Run the full MVP v1 investigation pipeline for one scenario.

    Stages covered:
        Stage 1 — Triage              (Gemini)
        Stage 2 — Hypotheses          (Gemini)
        Stage 3 — Investigation plan  (Gemini)

    Stages not yet covered (coming in MVP v2):
        Stage 4 — Engineer feedback input
        Stage 5 — Hypothesis synthesis and convergence decision
        Stage 6 — Final report generation
    """

    print("\n" + "=" * 60)
    print("DDI Copilot Investigator — MVP v1")
    print("=" * 60)

    # --- Step 1: Load the scenario ---------------------------------------
    print(f"\nLoading scenario: {scenario_identifier}")
    scenario = load_scenario(scenario_identifier)
    print(f"  {scenario.summary()}")

    # --- Step 2: Run the simulated classifier ----------------------------
    # The classifier takes the raw symptom text and returns a structured
    # label. This is the seam where R&D's real model will plug in later.
    print("\nRunning simulated classifier...")
    classifier_output = classify_incident(scenario.symptom_description)
    print(f"  Incident type : {classifier_output.incident_type}")
    print(f"  Confidence    : {classifier_output.confidence:.0%}")
    print(f"  Matched       : {len(classifier_output.matched_signals)} signal(s)")

    # --- Step 3: Load relevant knowledge ---------------------------------
    # Targeted load: tries to find the file matching the classified type.
    # Falls back to all files if no match — over-providing context is
    # safer than under-providing it.
    print("\nLoading knowledge base...")
    chunks = load_knowledge_base(incident_type=classifier_output.incident_type)
    source_names = [c.source_name for c in chunks]
    print(f"  Loaded {len(chunks)} file(s): {source_names}")

    # --- Step 4: Build the prompt ----------------------------------------
    # build_prompt() is the gatekeeper. Only the three inputs above
    # go in — the scenario's answer key does not.
    print("\nBuilding prompt...")
    prompt = build_prompt(scenario.symptom_description, classifier_output, chunks)
    word_count = len(prompt.split())
    print(f"  Prompt length: {word_count} words")

    # --- Step 5: Call Gemini ---------------------------------------------
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        print("\nERROR: GEMINI_API_KEY not found.")
        print("Make sure your .env file exists in the project root and contains:")
        print("  GEMINI_API_KEY=your_key_here")
        sys.exit(1)

    print("\nCalling Gemini (gemini-2.5-flash)...")
    print("  This may take 15-30 seconds...")

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )
    gemini_output = response.text
    print("  Response received.")

    # --- Step 6: Assemble and save the report ----------------------------
    report = f"""# DDI Incident Investigation Report

**Scenario ID**: {scenario.id}
**Incident type**: {scenario.incident_type}
**Difficulty**: {scenario.difficulty}
**Generated**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
**Pipeline version**: MVP v1 (Stages 1-3)

---

## Classifier Output

| Field | Value |
|-------|-------|
| Incident type | {classifier_output.incident_type} |
| Confidence | {classifier_output.confidence:.0%} |
| Matched signals | {len(classifier_output.matched_signals)} |

Signals matched: {", ".join(classifier_output.matched_signals) if classifier_output.matched_signals else "none"}

---

## Symptom Description

{scenario.symptom_description}

---

## Investigation (Gemini output — Stages 1-3)

{gemini_output}

---

*Generated by DDI Copilot Investigator — MVP v1.*
*Stage 4 (engineer feedback) and Stage 5 (synthesis) are not yet implemented.*
"""

    output_path = save_output(scenario.id, report)

    # --- Step 7: Print summary -------------------------------------------
    print("\n" + "=" * 60)
    print("Pipeline complete.")
    print("=" * 60)
    print(f"\nReport saved to:\n  {output_path}")
    print("\n--- Gemini output preview (first 400 chars) ---")
    print(gemini_output[:400])
    print("...\n")
    print(f"To read the full report in VS Code:")
    print(f"  code {output_path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("\nUsage: python pipeline/runner.py <scenario_id>")
        print("\nExamples:")
        print("  python pipeline/runner.py DHCP-001")
        print("  python pipeline/runner.py SERVFAIL-001")
        print("  python pipeline/runner.py SERVFAIL-002")
        sys.exit(1)

    run_investigation(sys.argv[1])
