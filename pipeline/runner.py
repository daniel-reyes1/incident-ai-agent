"""
runner.py — MVP v2

Orchestrates the full six-stage DDI investigation pipeline:

    Stage 1  — Triage                        (Gemini, Call 1)
    Stage 2  — Hypotheses                    (Gemini, Call 1)
    Stage 3  — Investigation plan            (Gemini, Call 1)
    Stage 4  — Engineer feedback             (from scenario, human-provided)
    Stage 5  — Synthesis + convergence       (Gemini, Call 2+)
    Stage 6  — Final report                  (Gemini, last call)

New in MVP v2 (vs MVP v1):
    - Stage 4: engineer findings ingested from the scenario's feedback rounds
    - Stage 5: Gemini evaluates findings against hypotheses and declares
               CONVERGENCE: RESOLVED or CONVERGENCE: LOOP REQUIRED
    - Loop-back: if not resolved, a new Stage 3 investigation plan is
                 generated and the next feedback round is consumed
    - Stage 6: final report generated once convergence is confirmed
    - All intermediate outputs accumulated and saved to one report file

Usage:
    python pipeline/runner.py DHCP-001
    python pipeline/runner.py SERVFAIL-002
"""

import os
import sys
from datetime import datetime
from pathlib import Path

# Add project root to sys.path so pipeline imports work when running directly
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from google import genai

from pipeline.scenario_loader import load_scenario
from pipeline.simulated_classifier import classify_incident
from pipeline.knowledge_loader import load_knowledge_base, format_for_prompt


OUTPUTS_DIR = Path(__file__).parent.parent / "outputs"
MAX_ROUNDS = 3  # Safety cap — prevents infinite loops if Gemini never converges


# ---------------------------------------------------------------------------
# Gemini helper
# ---------------------------------------------------------------------------

def call_gemini(client, prompt: str) -> str:
    """
    Send a prompt to Gemini and return the response text.
    All pipeline stages call this function — nothing else in the pipeline
    should call generate_content directly.
    """
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )
    return response.text


# ---------------------------------------------------------------------------
# Convergence detection
#
# After Stage 5, the pipeline reads one specific line in Gemini's output
# to decide whether to stop or loop:
#   CONVERGENCE: RESOLVED      → stop, generate final report
#   CONVERGENCE: LOOP REQUIRED → run another investigation cycle
#
# Simple string search — reliable and auditable.
# If neither line is found, we treat it as unresolved to be safe.
# ---------------------------------------------------------------------------

def is_resolved(synthesis_output: str) -> bool:
    """Returns True if Stage 5 output contains CONVERGENCE: RESOLVED."""
    return "CONVERGENCE: RESOLVED" in synthesis_output.upper()


# ---------------------------------------------------------------------------
# Prompt builders — one per Gemini call
# The answer key never touches any of these functions.
# ---------------------------------------------------------------------------

def build_stage1_3_prompt(symptom_description: str,
                          classifier_output,
                          knowledge_chunks: list) -> str:
    """Stage 1 (triage) + Stage 2 (hypotheses) + Stage 3 (investigation plan)."""
    signals_text = (
        "\n".join(f"  - {s}" for s in classifier_output.matched_signals)
        if classifier_output.matched_signals
        else "  (no specific signals matched)"
    )
    knowledge_text = format_for_prompt(knowledge_chunks)

    return f"""You are a DDI (DNS, DHCP, IPAM) incident investigation assistant.

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
- Explain your reasoning based on the symptom pattern described

STAGE 3 — INVESTIGATION PLAN
For each hypothesis in Stage 2, define one specific investigation step. \
For each step:
- Describe exactly what to check (be specific: which log, metric, table, or field)
- State what finding would confirm that hypothesis
- State what finding would rule out that hypothesis"""


def build_synthesis_prompt(symptom_description: str,
                           prior_investigation: str,
                           engineer_feedback: str,
                           round_number: int) -> str:
    """
    Stage 5 — synthesis and convergence decision.

    Gemini evaluates the engineer's findings against each hypothesis and
    declares CONVERGENCE: RESOLVED or CONVERGENCE: LOOP REQUIRED.
    The pipeline's is_resolved() function reads that line to branch.
    """
    return f"""You are reviewing engineer findings for a DDI incident investigation.

=====================================
ORIGINAL SYMPTOM DESCRIPTION:
=====================================
{symptom_description}

=====================================
PRIOR INVESTIGATION OUTPUT (Stages 1-3, Round {round_number}):
=====================================
{prior_investigation}

=====================================
STAGE 4 — ENGINEER FINDINGS (Round {round_number}):
=====================================
{engineer_feedback}

=====================================
INSTRUCTIONS — STAGE 5 SYNTHESIS:
=====================================
Review the engineer findings against each hypothesis and investigation step above.

For each hypothesis, state:
- Hypothesis: [restate it briefly]
- Status: CONFIRMED / RULED OUT / INSUFFICIENT EVIDENCE
- Evidence: which specific finding from Stage 4 supports this status decision

Status definitions — apply these precisely:
- CONFIRMED: the engineer's findings directly address the investigation step
  and support this hypothesis as the cause. You do not need absolute certainty.
  If the evidence is consistent with the hypothesis and all alternatives have
  been ruled out, use CONFIRMED. A scope at 100% utilization with users unable
  to obtain addresses is sufficient to confirm a scope exhaustion hypothesis —
  do not require a device count comparison to confirm what the symptoms already
  demonstrate.
- RULED OUT: the engineer's findings directly contradict what this hypothesis
  predicts. Use this when the data clearly eliminates the hypothesis.
- INSUFFICIENT EVIDENCE: use this only when the engineer could not complete
  the check, the data is missing, or the result is genuinely ambiguous with
  no clear direction. Do not use it simply because more data could theoretically
  be gathered — apply practical engineering judgment about whether the available
  evidence is sufficient to reach a working conclusion.
  
Special case — new finding in feedback: if the engineer's Stage 4 findings \
contain clear evidence for a specific cause that was not in the stated \
hypotheses but is consistent with the incident symptoms and the domain \
knowledge, you may declare CONVERGENCE: RESOLVED for that cause. State it \
as a new finding, explain why it fits the symptom pattern, and assign \
confidence as normal. Do not require evidence to match a formally stated \
hypothesis if the finding is unambiguous.

If one hypothesis is CONFIRMED and all others are RULED OUT, the decision is:
CONVERGENCE: RESOLVED

If no hypothesis can be confirmed and all are either ruled out or have
insufficient evidence, the decision is:
CONVERGENCE: LOOP REQUIRED

Then state the convergence decision on its own line, exactly as written:
CONVERGENCE: RESOLVED
CONVERGENCE: LOOP REQUIRED

If CONVERGENCE: RESOLVED, also state:
- CONFIRMED CAUSE: [one clear sentence naming the root cause]
- CONFIDENCE: [percentage, e.g. 94%]

If CONVERGENCE: LOOP REQUIRED, also state:
- MISSING EVIDENCE: [what specific data was not found or is ambiguous]
- EXHAUSTED HYPOTHESES: [list the hypotheses that have been ruled out]
- NEXT CHECKS: [what new area the engineer should investigate next]

End with this line exactly:
HUMAN REVIEW REQUIRED — These findings must be reviewed and approved \
by a qualified engineer before any remediation is attempted."""


def build_loop_investigation_prompt(symptom_description: str,
                                    round1_investigation: str,
                                    round1_synthesis: str,
                                    round_number: int,
                                    knowledge_chunks: list) -> str:
    """
    New Stage 2B + Stage 3 when the first synthesis returned LOOP REQUIRED.

    The original hypotheses have been exhausted. Gemini expands the
    hypothesis space and generates a new investigation plan.
    This only runs on hard multi-loop scenarios.
    """
    return f"""You are continuing a DDI incident investigation. The first round of \
engineer findings ruled out all original hypotheses without identifying a root cause. \
You must expand the hypothesis space.

=====================================
ORIGINAL SYMPTOM DESCRIPTION:
=====================================
{symptom_description}

=====================================
ROUND 1 — INVESTIGATION OUTPUT (Stages 1-3):
=====================================
{round1_investigation}

=====================================
ROUND 1 — SYNTHESIS RESULT (Stage 5):
=====================================
{round1_synthesis}

=====================================
DOMAIN KNOWLEDGE:
=====================================
{format_for_prompt(knowledge_chunks)}

=====================================
INSTRUCTIONS — STAGE 2B AND STAGE 3 (Round {round_number}):
=====================================
The original hypotheses have been exhausted. Using the domain knowledge above \
and the NEXT CHECKS identified in the round 1 synthesis, generate at least one \
new hypothesis that was not in the original list.

Prioritise hypotheses that directly address the NEXT CHECKS stated above. \
Do not generate generic server-health or infrastructure hypotheses that were \
already implicitly covered by the original investigation.

STAGE 2B — EXPANDED HYPOTHESIS
For each new hypothesis:
- State it clearly and concisely
- Assign likelihood: low / medium / high
- Explain why this hypothesis is consistent with the original symptom pattern \
AND with what was ruled out in round 1

STAGE 3 — INVESTIGATION PLAN (Round {round_number})
For each new hypothesis, define one specific investigation step:
- Describe exactly what to check
- State what finding would confirm that hypothesis
- State what finding would rule out that hypothesis"""


def build_report_prompt(symptom_description: str,
                        classifier_output,
                        all_investigation_outputs: list,
                        all_feedback_rounds: list,
                        final_synthesis: str) -> str:
    """Stage 6 — final report generation."""
    investigation_history = ""
    for i, (inv, fb) in enumerate(zip(all_investigation_outputs, all_feedback_rounds), 1):
        investigation_history += f"\n--- Round {i} Investigation ---\n{inv}\n"
        investigation_history += f"\n--- Round {i} Engineer Feedback ---\n{fb}\n"

    return f"""You are generating the final investigation report for a DDI incident.

=====================================
SYMPTOM DESCRIPTION:
=====================================
{symptom_description}

=====================================
CLASSIFIER OUTPUT:
=====================================
Incident type : {classifier_output.incident_type}
Confidence    : {classifier_output.confidence:.0%}

=====================================
FULL INVESTIGATION HISTORY:
=====================================
{investigation_history}

=====================================
FINAL SYNTHESIS (Stage 5):
=====================================
{final_synthesis}

=====================================
INSTRUCTIONS — STAGE 6 REPORT:
=====================================
Using the full investigation history above, produce a clean final report \
in the following format exactly:

CAUSE:
[One clear paragraph explaining the root cause, why it produced the observed \
symptoms, and any relevant technical context.]

EVIDENCE TRAIL:
[List each piece of evidence supporting the confirmed cause, one item per line \
starting with a dash.]

REMEDIATION STEPS:
[Numbered list. Label each as Immediate, Medium-term, or Long-term.]

HUMAN SIGN-OFF: [ ] Reviewed and approved by: ___________  Date: ___________"""


# ---------------------------------------------------------------------------
# Output saving
# ---------------------------------------------------------------------------

def save_output(scenario_id: str, content: str) -> Path:
    """Save the full investigation report to outputs/."""
    OUTPUTS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{scenario_id}_investigation_{timestamp}.md"
    output_path = OUTPUTS_DIR / filename
    output_path.write_text(content, encoding="utf-8")
    return output_path


def _build_loop_sections(all_investigations: list, all_feedback: list) -> str:
    """Render round 2+ sections for the assembled report."""
    sections = ""
    for i in range(1, len(all_investigations)):
        round_num = i + 1
        sections += f"## Stage 2B-3 — Expanded Investigation (Round {round_num})\n\n"
        sections += all_investigations[i] + "\n\n---\n\n"
        if i < len(all_feedback):
            sections += f"## Stage 4 — Engineer Feedback (Round {round_num})\n\n"
            sections += all_feedback[i] + "\n\n---\n\n"
    return sections


# ---------------------------------------------------------------------------
# Main pipeline — MVP v2
# ---------------------------------------------------------------------------

def run_investigation(scenario_identifier: str) -> None:
    """
    Run the full six-stage investigation pipeline for one scenario.

    Baseline scenarios (one feedback round): one pass through all six stages.
    Hard scenarios (two feedback rounds): loops at Stage 5 if evidence does
    not converge, then re-runs Stages 2B-3-4-5 before generating the report.
    """

    print("\n" + "=" * 60)
    print("DDI Copilot Investigator — MVP v2")
    print("=" * 60)

    # Step 1: Load scenario
    print(f"\nLoading scenario: {scenario_identifier}")
    scenario = load_scenario(scenario_identifier)
    print(f"  {scenario.summary()}")

    # Step 2: Classify
    print("\nRunning simulated classifier...")
    classifier_output = classify_incident(scenario.symptom_description)
    print(f"  Incident type : {classifier_output.incident_type}")
    print(f"  Confidence    : {classifier_output.confidence:.0%}")
    print(f"  Signals       : {len(classifier_output.matched_signals)} matched")

    # Step 3: Load knowledge
    print("\nLoading knowledge base...")
    chunks = load_knowledge_base(incident_type=classifier_output.incident_type)
    print(f"  Loaded {len(chunks)} file(s): {[c.source_name for c in chunks]}")

    # Step 4: Set up Gemini
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("\nERROR: GEMINI_API_KEY not found in .env file.")
        sys.exit(1)
    client = genai.Client(api_key=api_key)

    # Step 5: Stage 1-3 — triage, hypotheses, investigation plan
    print("\n[Stage 1-3] Generating triage, hypotheses, investigation plan...")
    stage1_3_output = call_gemini(
        client,
        build_stage1_3_prompt(scenario.symptom_description, classifier_output, chunks)
    )
    print("  Done.")

    # Accumulators for all rounds
    all_investigation_outputs = [stage1_3_output]
    all_feedback_rounds = []
    final_synthesis = ""
    current_investigation = stage1_3_output

    # Step 6: Stage 4-5 loop — feedback + synthesis, with optional loop-back
    for round_num in range(1, MAX_ROUNDS + 1):
        feedback = scenario.get_feedback(round_num)
        if not feedback:
            print(f"\n  No feedback available for round {round_num}. Stopping.")
            break

        print(f"\n[Stage 4] Ingesting engineer feedback (Round {round_num})...")
        all_feedback_rounds.append(feedback)
        print(f"  Feedback: {feedback[:100]}...")

        print(f"[Stage 5] Synthesising findings (Round {round_num})...")
        synthesis_output = call_gemini(
            client,
            build_synthesis_prompt(
                scenario.symptom_description,
                current_investigation,
                feedback,
                round_num
            )
        )
        final_synthesis = synthesis_output

        if is_resolved(synthesis_output):
            print(f"  CONVERGENCE: RESOLVED in round {round_num}.")
            break
        else:
            print(f"  CONVERGENCE: LOOP REQUIRED after round {round_num}.")
            next_feedback = scenario.get_feedback(round_num + 1)
            if not next_feedback:
                print("  No further feedback rounds available. Stopping loop.")
                break

            print(f"\n[Stage 2B-3] Generating expanded hypothesis (Round {round_num + 1})...")
            loop_investigation = call_gemini(
                client,
                build_loop_investigation_prompt(
                    scenario.symptom_description,
                    stage1_3_output,
                    synthesis_output,
                    round_num + 1,
                    chunks
                )
            )
            current_investigation = loop_investigation
            all_investigation_outputs.append(loop_investigation)
            print("  Done.")

    # Step 7: Stage 6 — final report
    print("\n[Stage 6] Generating final report...")
    report_output = call_gemini(
        client,
        build_report_prompt(
            scenario.symptom_description,
            classifier_output,
            all_investigation_outputs,
            all_feedback_rounds,
            final_synthesis
        )
    )
    print("  Done.")

    # Step 8: Assemble full report
    rounds_run = len(all_feedback_rounds)
    report = f"""# DDI Incident Investigation Report

**Scenario ID**: {scenario.id}
**Incident type**: {scenario.incident_type}
**Difficulty**: {scenario.difficulty}
**Generated**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
**Pipeline version**: MVP v2 (Stages 1-6)
**Investigation rounds**: {rounds_run}

---

## Classifier Output

| Field | Value |
|-------|-------|
| Incident type | {classifier_output.incident_type} |
| Confidence | {classifier_output.confidence:.0%} |
| Matched signals | {", ".join(classifier_output.matched_signals) if classifier_output.matched_signals else "none"} |

---

## Symptom Description

{scenario.symptom_description}

---

## Stage 1-3 — Initial Investigation (Round 1)

{all_investigation_outputs[0]}

---

## Stage 4 — Engineer Feedback (Round 1)

{all_feedback_rounds[0] if all_feedback_rounds else "No feedback recorded."}

---

{_build_loop_sections(all_investigation_outputs, all_feedback_rounds)}
## Stage 5 — Final Synthesis

{final_synthesis}

---

## Stage 6 — Final Report

{report_output}

---

*Generated by DDI Copilot Investigator — MVP v2.*
*Human review required before any remediation is attempted.*
"""

    output_path = save_output(scenario.id, report)

    # Step 9: Print summary
    print("\n" + "=" * 60)
    print("Pipeline complete.")
    print("=" * 60)
    print(f"\nScenario    : {scenario.id} — {scenario.incident_type}")
    print(f"Rounds      : {rounds_run}")
    print(f"Converged   : {'Yes' if is_resolved(final_synthesis) else 'No (check output)'}")
    print(f"\nReport saved to:\n  {output_path}")
    print(f"\nOpen in VS Code:\n  code {output_path}")


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