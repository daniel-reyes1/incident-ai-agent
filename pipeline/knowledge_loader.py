"""
knowledge_loader.py

Loads DDI domain knowledge from the knowledge_base/ directory and makes
it available to the pipeline as labelled context for Gemini.

Why this exists as a separate module:
    Gemini's general training data knows about DNS, DHCP and IPAM at a
    surface level. The knowledge base files contain curated, specific
    content — ranked root causes, diagnostic indicators, resolution paths —
    drawn from EfficientIP's own technical materials. Passing this as
    context steers Gemini toward domain-accurate reasoning rather than
    generic answers.

Current behaviour — load everything:
    For now, all 10 knowledge base files are loaded on every call.
    A future improvement is to load only the file matching the classified
    incident type, since there's no reason to include DHCP knowledge in
    a SERVFAIL investigation. That targeted retrieval is a one-function
    change once the pipeline is working end to end. Simple first.
"""

from dataclasses import dataclass
from pathlib import Path


# ---------------------------------------------------------------------------
# Path to the knowledge base directory
#
# Path(__file__) is this file: pipeline/knowledge_loader.py
# .parent        is pipeline/
# .parent.parent is the project root
# / "knowledge_base" is the knowledge_base/ folder at the root
# ---------------------------------------------------------------------------
KNOWLEDGE_BASE_DIR = Path(__file__).parent.parent / "knowledge_base"


# ---------------------------------------------------------------------------
# Output type
#
# Each file in the knowledge base becomes one KnowledgeChunk.
# The pipeline receives a list of these and can use source_name to
# identify which incident type a chunk belongs to, or just concatenate
# all content into one context block for Gemini.
# ---------------------------------------------------------------------------

@dataclass
class KnowledgeChunk:
    """
    Content from a single knowledge base file.

    Attributes:
        source_name  — the filename, e.g. "servfail_rate_spike.txt"
                       used for attribution and targeted retrieval later
        content      — the full text content of the file
    """
    source_name: str
    content: str

    def summary(self) -> str:
        """One-line description for logging."""
        words = len(self.content.split())
        return f"{self.source_name} ({words} words)"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_file(path: Path) -> KnowledgeChunk:
    """
    Read a single knowledge base file and return it as a KnowledgeChunk.
    Uses utf-8-sig to safely handle BOM if the file was created on Windows.
    """
    content = path.read_text(encoding="utf-8-sig").strip()
    return KnowledgeChunk(
        source_name=path.name,
        content=content,
    )


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def load_knowledge_base(incident_type: str = None) -> list:
    """
    Load knowledge base files and return them as a list of KnowledgeChunks.

    Args:
        incident_type: Optional. If provided, attempts to load only the
                       file matching that incident type. If no match is
                       found, falls back to loading all files.
                       If None, loads all files.

    Returns:
        List of KnowledgeChunk objects, one per loaded file.
        Always sorted alphabetically by filename for consistency.

    Raises:
        FileNotFoundError: if the knowledge_base/ directory does not exist.
        ValueError: if the directory exists but contains no .txt files.
    """
    if not KNOWLEDGE_BASE_DIR.exists():
        raise FileNotFoundError(
            f"Knowledge base directory not found: {KNOWLEDGE_BASE_DIR}\n"
            f"Expected a 'knowledge_base/' folder in the project root."
        )

    all_files = sorted(KNOWLEDGE_BASE_DIR.glob("*.txt"))

    if not all_files:
        raise ValueError(
            f"Knowledge base directory exists but contains no .txt files: "
            f"{KNOWLEDGE_BASE_DIR}"
        )

    # Targeted loading: if an incident type is given, try to find a matching file
    # Matching logic: normalise both the incident type and the filename to lowercase,
    # replace spaces and hyphens with underscores, and check for substring match.
    # Example: "SERVFAIL rate spike" → "servfail_rate_spike" → matches "servfail_rate_spike.txt"
    if incident_type:
        normalised = incident_type.lower().replace(" ", "_").replace("-", "_")
        matches = [f for f in all_files if normalised in f.stem]
        if matches:
            return [_load_file(f) for f in matches]
        # No match found — fall through to loading everything
        # (better to over-provide context than to provide none)

    return [_load_file(f) for f in all_files]


def format_for_prompt(chunks: list) -> str:
    """
    Format a list of KnowledgeChunks into a single string suitable for
    inclusion in a Gemini prompt.

    Each chunk is wrapped with a header showing its source filename so
    Gemini can attribute its reasoning to a specific knowledge source.

    Example output:
        === KNOWLEDGE: servfail_rate_spike.txt ===
        [file content here]

        === KNOWLEDGE: dhcp_scope_exhaustion.txt ===
        [file content here]
    """
    if not chunks:
        return ""

    sections = []
    for chunk in chunks:
        sections.append(
            f"=== KNOWLEDGE: {chunk.source_name} ===\n{chunk.content}"
        )

    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# Manual smoke test
# Run directly: python pipeline/knowledge_loader.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("knowledge_loader.py — smoke test")
    print("=" * 60)

    # Test 1: load everything
    print("\nTest 1: Load all knowledge base files")
    try:
        chunks = load_knowledge_base()
        print(f"  Loaded {len(chunks)} file(s):")
        for chunk in chunks:
            print(f"    - {chunk.summary()}")
    except (FileNotFoundError, ValueError) as e:
        print(f"  ERROR: {e}")

    # Test 2: targeted load by incident type
    print("\nTest 2: Targeted load — 'SERVFAIL rate spike'")
    try:
        chunks = load_knowledge_base(incident_type="SERVFAIL rate spike")
        print(f"  Loaded {len(chunks)} file(s):")
        for chunk in chunks:
            print(f"    - {chunk.summary()}")
    except (FileNotFoundError, ValueError) as e:
        print(f"  ERROR: {e}")

    # Test 3: targeted load that won't match — should fall back to all
    print("\nTest 3: Targeted load — unrecognised type (should fall back to all)")
    try:
        chunks = load_knowledge_base(incident_type="unknown incident type")
        print(f"  Loaded {len(chunks)} file(s) (fallback to all):")
        for chunk in chunks:
            print(f"    - {chunk.summary()}")
    except (FileNotFoundError, ValueError) as e:
        print(f"  ERROR: {e}")

    # Test 4: format_for_prompt on a single chunk
    print("\nTest 4: format_for_prompt on first chunk")
    try:
        chunks = load_knowledge_base()
        formatted = format_for_prompt(chunks[:1])
        preview = formatted[:200].replace("\n", " ")
        print(f"  Preview (first 200 chars): {preview}...")
    except (FileNotFoundError, ValueError) as e:
        print(f"  ERROR: {e}")

    print("\n" + "=" * 60)
    print("Smoke test complete.")
    print("=" * 60)