"""
scenario_loader.py

Loads synthetic scenario files and exposes them to the pipeline
in a way that prevents answer leakage to Gemini.

Core design principle:
    Scenario files contain both inputs and expected outputs in one document.
    This loader acts as the gatekeeper: it parses everything, but exposes
    only the runtime input fields (symptom_description, feedback_rounds) as
    named attributes that the pipeline can safely use.

    Everything else — expected triage, hypotheses, investigation plan,
    synthesis, report — goes into answer_key. The evaluator will use that
    later. The pipeline stages should never read from it.

    This means Gemini can never accidentally see the answer, because the
    answer is not in any attribute the pipeline is designed to access.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Directory where scenario .txt files live
#
# Path(__file__) is this script: pipeline/scenario_loader.py
# .parent       is the pipeline/ directory
# .parent.parent is the project root
# / "scenarios" is the scenarios/ folder at the root
# ---------------------------------------------------------------------------
SCENARIOS_DIR = Path(__file__).parent.parent / "scenarios"

# The separator line used throughout all scenario files — 37 = signs
SEPARATOR = "=" * 37


# ---------------------------------------------------------------------------
# Output type
#
# This dataclass is what load_scenario() returns.
# The pipeline imports this type and only ever accesses:
#   scenario.symptom_description  — to start the investigation
#   scenario.get_feedback(round)  — to pass engineer findings per round
#   scenario.has_multiple_rounds()— to decide whether to loop
#
# It should never access scenario.answer_key at runtime.
# ---------------------------------------------------------------------------

@dataclass
class ScenarioData:
    """
    A parsed scenario with runtime inputs and answer key cleanly separated.

    Safe for pipeline use (can go to Gemini):
        id                  — e.g. "DHCP-001"
        incident_type       — e.g. "DHCP Scope Exhaustion"
        difficulty          — e.g. "Baseline" or "Hard"
        symptom_description — raw engineer report, first input to the pipeline
        feedback_rounds     — list of engineer findings, one entry per loop
                              index 0 = round 1, index 1 = round 2, etc.

    NOT safe for pipeline use (evaluation only):
        answer_key          — dict of all other parsed sections
                              (expected triage, hypotheses, synthesis, report)
    """

    id: str
    incident_type: str
    difficulty: str
    symptom_description: str
    feedback_rounds: list

    answer_key: dict = field(default_factory=dict)

    def get_feedback(self, round_number: int = 1) -> str:
        """
        Get engineer feedback for a specific investigation round.

        Args:
            round_number: 1-indexed. Round 1 is the first feedback.

        Returns:
            The feedback text, or empty string if that round doesn't exist.
        """
        idx = round_number - 1
        if 0 <= idx < len(self.feedback_rounds):
            return self.feedback_rounds[idx]
        return ""

    def has_multiple_rounds(self) -> bool:
        """
        True if this scenario has more than one feedback round —
        meaning the pipeline will need to loop at least once.
        """
        return len(self.feedback_rounds) > 1

    def summary(self) -> str:
        """One-line description for logging and debugging."""
        rounds = len(self.feedback_rounds)
        return (
            f"[{self.id}] {self.incident_type} | "
            f"{self.difficulty} | "
            f"{rounds} feedback round(s)"
        )


# ---------------------------------------------------------------------------
# Internal helpers
# These functions are not meant to be used by other modules directly.
# They are the machinery behind load_scenario().
# ---------------------------------------------------------------------------

def _find_scenario_file(identifier: str) -> Path:
    """
    Locate a scenario file by any of these inputs:
      - Full path:    "/absolute/path/to/scenario_dhcp_001.txt"
      - Filename:     "scenario_dhcp_001.txt"
      - Scenario ID:  "DHCP-001" or "SERVFAIL-002"

    For scenario IDs, we first try to construct the expected filename
    (DHCP-001 → scenario_dhcp_001.txt), then fall back to scanning all
    .txt files for a matching SCENARIO: header line.
    """
    p = Path(identifier)

    # Full absolute path provided and it exists — use it directly
    if p.is_absolute() and p.exists():
        return p

    # Has .txt extension — look for it by name in the scenarios directory
    if p.suffix == ".txt":
        candidate = SCENARIOS_DIR / p.name
        if candidate.exists():
            return candidate

    # Treat as scenario ID — convert to expected filename and check
    # "DHCP-001"     → "scenario_dhcp_001.txt"
    # "SERVFAIL-002" → "scenario_servfail_002.txt"
    normalized = identifier.lower().replace("-", "_")
    candidate = SCENARIOS_DIR / f"scenario_{normalized}.txt"
    if candidate.exists():
        return candidate

    # Fall back: scan all .txt files for a matching SCENARIO: header
    for f in sorted(SCENARIOS_DIR.glob("*.txt")):
        first_line = f.read_text(encoding="utf-8").splitlines()[0].strip()
        if first_line == f"SCENARIO: {identifier.upper()}":
            return f

    raise FileNotFoundError(
        f"Could not find a scenario file for '{identifier}'.\n"
        f"Searched in: {SCENARIOS_DIR}\n"
        f"Files found: {[f.name for f in sorted(SCENARIOS_DIR.glob('*.txt'))]}"
    )


def _parse_metadata(header_block: str) -> dict:
    """
    Parse the top block of the file (before the first separator) into
    a dict with keys: id, incident_type, difficulty.

    Example input:
        SCENARIO: DHCP-001
        INCIDENT TYPE: DHCP Scope Exhaustion
        DIFFICULTY: Baseline (single-pass diagnosable, minimal red herrings)
    """
    metadata = {}
    for line in header_block.strip().splitlines():
        line = line.strip()
        if line.startswith("SCENARIO:"):
            metadata["id"] = line.replace("SCENARIO:", "", 1).strip()
        elif line.startswith("INCIDENT TYPE:"):
            metadata["incident_type"] = line.replace("INCIDENT TYPE:", "", 1).strip()
        elif line.startswith("DIFFICULTY:"):
            metadata["difficulty"] = line.replace("DIFFICULTY:", "", 1).strip()
    return metadata


def _parse_sections(file_content: str) -> dict:
    """
    Split the file by separator lines and return a dict of {header: content}.

    After splitting by SEPARATOR, the parts alternate:
        parts[0]  = metadata block (before first separator)
        parts[1]  = first section header
        parts[2]  = first section content
        parts[3]  = second section header
        parts[4]  = second section content
        ...

    We step through pairs (header, content) starting at index 1,
    skipping the END SCENARIO marker at the end.
    """
    parts = file_content.split(SEPARATOR)
    sections = {}

    for i in range(1, len(parts) - 1, 2):
        header = parts[i].strip()
        content = parts[i + 1].strip() if (i + 1) < len(parts) else ""

        if not header or header == "END SCENARIO":
            continue

        sections[header] = content

    return sections


def _extract_round_number(header: str) -> int:
    """
    Extract the investigation round number from a STAGE 4 header.
    Returns 1 if no explicit round number is found (baseline scenarios).

    Examples:
        "STAGE 4 — HUMAN INPUT ... — ROUND 1"  → 1
        "STAGE 4 — HUMAN INPUT ... — ROUND 2"  → 2
        "STAGE 4 — HUMAN INPUT ..."             → 1
    """
    match = re.search(r"ROUND\s+(\d+)", header, re.IGNORECASE)
    return int(match.group(1)) if match else 1


def _clean_quoted_content(text: str) -> str:
    """
    Strip surrounding quotation marks from symptom/feedback content.

    The scenario files wrap these sections in double quotes for readability
    as ticket-style text. The pipeline works with the raw text content,
    so we strip them here.
    """
    text = text.strip()
    if text.startswith('"') and text.endswith('"'):
        text = text[1:-1].strip()
    return text


# ---------------------------------------------------------------------------
# Public interface — this is the only function other modules should call
# ---------------------------------------------------------------------------

def load_scenario(identifier: str) -> ScenarioData:
    """
    Load and parse a scenario file. Returns a ScenarioData object with
    runtime inputs and the answer key cleanly separated.

    Args:
        identifier: A scenario ID ("DHCP-001"), a filename
                    ("scenario_dhcp_001.txt"), or a full path.

    Returns:
        ScenarioData with symptom_description and feedback_rounds ready
        for pipeline use, and answer_key for evaluation use only.

    Raises:
        FileNotFoundError: if no matching scenario file can be found.
        ValueError: if the file is missing required header fields.
    """
    path = _find_scenario_file(identifier)
    content = path.read_text(encoding="utf-8")

    # Parse the metadata block (before the first separator)
    parts = content.split(SEPARATOR)
    metadata = _parse_metadata(parts[0])

    # Validate that required fields are present
    required = ("id", "incident_type", "difficulty")
    missing = [k for k in required if k not in metadata]
    if missing:
        raise ValueError(
            f"Scenario file '{path.name}' is missing required fields: {missing}"
        )

    # Parse all sections into a header → content dict
    sections = _parse_sections(content)

    # --- Extract symptom description (runtime input, safe for Gemini) ------

    symptom_description = ""
    for header, body in sections.items():
        if "SYMPTOM DESCRIPTION" in header:
            symptom_description = _clean_quoted_content(body)
            break

    if not symptom_description:
        raise ValueError(
            f"Scenario file '{path.name}' is missing a SYMPTOM DESCRIPTION section."
        )

    # --- Extract engineer feedback rounds (runtime input, safe for Gemini) --
    #
    # Each STAGE 4 — HUMAN INPUT section becomes one feedback round.
    # We collect them all, sort by round number, and flatten to a list.
    # feedback_rounds[0] = round 1, feedback_rounds[1] = round 2, etc.

    feedback_by_round = {}
    for header, body in sections.items():
        if "STAGE 4" in header and "HUMAN INPUT" in header:
            round_num = _extract_round_number(header)
            feedback_by_round[round_num] = _clean_quoted_content(body)

    feedback_rounds = [feedback_by_round[r] for r in sorted(feedback_by_round)]

    # --- Everything else goes into answer_key (NOT for Gemini) -------------
    #
    # This includes: classifier output, triage, hypotheses, investigation
    # plan, synthesis, and report sections. The evaluator will use these
    # to score the pipeline's actual output later.

    answer_key = {
        header: body
        for header, body in sections.items()
        if "SYMPTOM DESCRIPTION" not in header
        and not ("STAGE 4" in header and "HUMAN INPUT" in header)
    }

    return ScenarioData(
        id=metadata["id"],
        incident_type=metadata["incident_type"],
        difficulty=metadata["difficulty"],
        symptom_description=symptom_description,
        feedback_rounds=feedback_rounds,
        answer_key=answer_key,
    )


# ---------------------------------------------------------------------------
# Manual smoke test
# Run directly: python pipeline/scenario_loader.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    test_ids = ["DHCP-001", "SERVFAIL-001", "SERVFAIL-002"]

    print("=" * 60)
    print("scenario_loader.py — smoke test")
    print("=" * 60)

    for scenario_id in test_ids:
        print(f"\nLoading: {scenario_id}")
        try:
            s = load_scenario(scenario_id)
            print(f"  Summary         : {s.summary()}")
            print(f"  Symptom (first 80 chars):")
            print(f"    {s.symptom_description[:80]}...")
            print(f"  Feedback round 1 (first 80 chars):")
            print(f"    {s.get_feedback(1)[:80]}...")
            if s.has_multiple_rounds():
                print(f"  Feedback round 2 (first 80 chars):")
                print(f"    {s.get_feedback(2)[:80]}...")
            print(f"  Answer key sections ({len(s.answer_key)}):")
            for header in s.answer_key:
                print(f"    - {header}")
        except (FileNotFoundError, ValueError) as e:
            print(f"  ERROR: {e}")

    print("\n" + "=" * 60)
    print("Smoke test complete.")
    print("=" * 60)
