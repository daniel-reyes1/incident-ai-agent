# Project Context — DDI Incident Investigation Copilot

## Goal
Build a Google-stack AI prototype inspired by Infoblox IQ, focused on DDI incident investigation. This must not be a basic Gemini wrapper. The value is in structured workflow: classification handoff, hypothesis tracking, investigation planning, engineer feedback loops, synthesis, final report, and evaluation.

## Ground Rules
- Google-exclusive stack: Gemini, NotebookLM, Google tools only.
- No PII or customer-identifying data.
- No internal/proprietary/customer data.
- Use synthetic scenarios and public/synthetic knowledge only.
- Human review is mandatory before remediation.

## Current Repo
- `knowledge_base/`: DDI operational reference docs.
- `scenarios/`: 10 synthetic incident scenarios.
- `pipeline/`: product logic to build.
- `interface/`: future UI/API layer.
- `.env`: contains `GOOGLE_API_KEY`, never commit.
- `requirements.txt`: dependencies.

## Product Architecture
The system should process incidents through stages:

1. Raw symptom text
2. Simulated classifier
3. Triage
4. Hypothesis generation
5. Investigation plan
6. Engineer feedback ingestion
7. Hypothesis update
8. Final human-reviewed report
9. Evaluation against expected scenario outputs

## Important Design Decision
The simulated classifier should be a standalone rule-based function, not just reading the `Incident type` and `Confidence` lines from the scenario file.

Reason:
- It exercises the interface between detection/classification and investigation.
- It can later be replaced by R&D’s real classifier.
- It avoids making the prototype look like a prompt wrapper.

## Next Implementation Target
Build:
- `pipeline/scenario_loader.py`
- `pipeline/simulated_classifier.py`
- `pipeline/runner.py`

The runner should:
1. Load one scenario file.
2. Extract symptom description.
3. Run simulated classifier.
4. Compare classifier output to expected classifier output in the scenario.
5. Generate staged investigation output using Gemini.
6. Save report to `outputs/`.

## Critical Constraint
Do not pass the scenario’s own Stage 5/6 expected synthesis/report sections into Gemini. They are answer keys. Only pass:
- symptom description
- simulated classifier output
- relevant knowledge base
- stage-specific engineer feedback when appropriate.

## Demo Goal
Show that the copilot:
- does not merely answer a prompt,
- structures an investigation,
- tracks hypotheses,
- updates based on evidence,
- requires human review,
- and can be evaluated across 10 synthetic scenarios.
