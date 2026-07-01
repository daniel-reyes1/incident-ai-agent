"""
simulated_classifier.py

Simulates the incident classification layer that, in a production system,
would be replaced by EfficientIP's real R&D detection model.

Design principles:
- Deterministic and rule-based: no randomness, no ML, no Gemini calls
- Takes raw symptom text as input — same interface a real classifier would use
- Returns a structured result: incident type, confidence, matched signals
- This file is the one and only replacement point for the real classifier

This boundary is intentional. Everything downstream in the pipeline
consumes only the output of classify_incident(), never the scenario file's
pre-written classifier label. That means swapping in R&D's real model later
is a one-file change with no ripple effects anywhere else.
"""

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Output type
#
# A dataclass is just a clean way to define a structured object with named
# fields. Think of it as a tidy dictionary where the keys are fixed.
# The pipeline always gets back the same shape, regardless of which incident
# type was detected.
# ---------------------------------------------------------------------------

@dataclass
class ClassifierOutput:
    incident_type: str          # One of the 10 DDI incident type labels
    confidence: float           # 0.0 – 1.0 (scaled, not raw)
    matched_signals: list       # Human-readable list of what triggered the match
    explanation: str            # One-sentence summary of the classification decision


# ---------------------------------------------------------------------------
# Signal definitions
#
# This is the core of the classifier. For each of the 10 incident types,
# we define a list of (phrase, label) pairs:
#
#   phrase — a lowercase string we search for inside the symptom text
#   label  — a human-readable description of what that signal means,
#             which appears in the matched_signals output
#
# These phrases were drawn directly from how the scenario symptom
# descriptions were written, so they reflect realistic incident ticket
# language rather than invented keywords.
#
# Important: a phrase match only fires if the phrase appears as a
# substring of the lowercased symptom text. This is intentionally simple —
# no fuzzy matching, no stemming. Simple is auditable.
# ---------------------------------------------------------------------------

INCIDENT_SIGNALS = {

    "SERVFAIL rate spike": [
        ("servfail",                    "SERVFAIL errors mentioned"),
        ("site can't be reached",       "Site unreachability reported"),
        ("site cannot be reached",      "Site unreachability reported"),
        ("external networks",           "Multiple external networks affected"),
        ("unrelated networks",          "Reports from unrelated networks"),
        ("validating resolver",         "Validating resolver behavior referenced"),
        ("intermittent",                "Intermittent failure pattern"),
        ("comes and goes",              "Intermittent failure pattern"),
    ],

    "DHCP scope exhaustion": [
        ("169.254",                     "APIPA self-assigned address (169.254.x.x) observed"),
        ("limited connectivity",        "Limited connectivity warning observed"),
        ("no network access",           "Full network access loss reported"),
        ("scope",                       "DHCP scope referenced"),
        ("lease",                       "DHCP lease referenced"),
        ("addresses leased",            "Lease utilization data mentioned"),
        ("getting worse as more",       "Gradual onset as more users connect"),
        ("worsens as more people",      "Gradual onset as more users connect"),
    ],

    "DNS resolution latency": [
        ("slow",                        "Slowness reported"),
        ("sluggish",                    "Sluggishness reported"),
        ("eventually loads",            "Eventual success implies degradation not outage"),
        ("latency",                     "Latency explicitly mentioned"),
        ("feels slow",                  "Perceived slowness reported"),
        ("noticeably slower",           "Noticeable degradation reported"),
        ("few seconds",                 "Multi-second delay mentioned"),
        ("trickle of complaints",       "Gradual complaint pattern, not a flood"),
    ],

    "IP address conflict": [
        ("ip address conflict",         "IP address conflict message observed"),
        ("ip conflict",                 "IP conflict reported"),
        ("duplicate ip",                "Duplicate IP referenced"),
        ("conflict popup",              "OS conflict popup observed"),
        ("conflict warning",            "Conflict warning observed"),
        ("followed the laptop",         "Issue follows device not port (rules out cabling)"),
        ("followed the device",         "Issue follows device not port (rules out cabling)"),
    ],

    "Configuration drift": [
        ("different results",           "Divergent results between servers"),
        ("diverge",                     "Server divergence mentioned"),
        ("secondary",                   "Secondary server referenced"),
        ("out of sync",                 "Sync issue referenced"),
        ("inconsistent",                "Inconsistency reported"),
        ("no change ticket",            "Missing change documentation"),
        ("no ticket",                   "Missing change documentation"),
        ("wasn't happening yesterday",  "Recent onset without logged change"),
    ],

    "Rogue device detection": [
        ("unrecognized",                "Unrecognized device reported"),
        ("unauthorized",                "Unauthorized device reported"),
        ("not in inventory",            "Device absent from inventory"),
        ("not registered",              "Device not registered"),
        ("rogue",                       "Rogue device explicitly mentioned"),
        ("unusual traffic",             "Unusual traffic pattern flagged"),
        ("nobody recognizes",           "Device not recognized by any team member"),
        ("doesn't match any known",     "No matching known asset found"),
    ],

    "Subnet misconfiguration": [
        ("subnet",                      "Subnet referenced"),
        ("policy not applying",         "Policy application failure reported"),
        ("rule not applying",           "Rule application failure reported"),
        ("firewall rule",               "Firewall rule referenced"),
        ("only part of",                "Partial scope of effect — not all users"),
        ("fragmented",                  "Fragmentation of address space mentioned"),
        ("not contiguous",              "Non-contiguous address space referenced"),
        ("address space",               "Address space referenced"),
    ],

    "DNS forwarding failure": [
        ("external sites",              "External site access failure"),
        ("external websites",           "External website access failure"),
        ("external domains",            "External domain resolution failure"),
        ("internal works",              "Internal resolution confirmed working"),
        ("internal fine",               "Internal resolution confirmed working"),
        ("forwarder",                   "Forwarder explicitly referenced"),
        ("forwarding",                  "DNS forwarding referenced"),
        ("upstream",                    "Upstream resolver referenced"),
        ("can't reach external",        "External reach failure"),
        ("cannot reach external",       "External reach failure"),
    ],

    "DDNS update failure": [
        ("by hostname",                 "Hostname-based access failure"),
        ("by name",                     "Name-based resolution failure"),
        ("not by name",                 "IP works but name does not"),
        ("reachable by ip",             "IP access works, name does not"),
        ("stale record",                "Stale DNS record referenced"),
        ("ddns",                        "DDNS explicitly mentioned"),
        ("dynamic dns",                 "Dynamic DNS referenced"),
        ("name resolution broken",      "Name resolution failure"),
        ("hostname",                    "Hostname resolution referenced"),
    ],

    "DNS hijacking indicators": [
        ("certificate",                 "Certificate warning observed"),
        ("wrong ip",                    "Unexpected IP returned"),
        ("hijack",                      "Hijacking explicitly mentioned"),
        ("poisoning",                   "Cache poisoning referenced"),
        ("unexpected ip",               "Unexpected IP returned"),
        ("redirected",                  "Unexpected redirection observed"),
        ("anomalous",                   "Anomalous resolver behavior flagged"),
        ("suspicious",                  "Suspicious behavior flagged"),
        ("doesn't match",               "Result mismatch observed"),
    ],

}


# ---------------------------------------------------------------------------
# Confidence scaling
#
# The raw score is simply: how many signals matched / how many signals exist
# for that type. A type with 3 matches out of 8 signals scores 0.375.
#
# We don't report this raw ratio directly, because a real classifier would
# never output 100% or 0% confidence — it would always express some
# uncertainty. We scale into a realistic range (0.70 – 0.95) instead.
#
# Formula: confidence = 0.70 + raw_score * (0.95 - 0.70)
#
# A type matching 2/8 signals → raw 0.25 → confidence 0.76
# A type matching 6/8 signals → raw 0.75 → confidence 0.89
# This matches the confidence range you'll see in the scenario files (76-95%).
# ---------------------------------------------------------------------------

_MIN_CONF = 0.70
_MAX_CONF = 0.95


def _scale_confidence(raw_score: float) -> float:
    scaled = _MIN_CONF + raw_score * (_MAX_CONF - _MIN_CONF)
    return round(scaled, 2)


# ---------------------------------------------------------------------------
# Public interface
#
# This is the only function the rest of the pipeline should ever call.
# Nothing else in this file needs to be imported anywhere else.
# ---------------------------------------------------------------------------

def classify_incident(symptom_text: str) -> ClassifierOutput:
    """
    Classify a raw symptom description into one of the 10 DDI incident types.

    Args:
        symptom_text: Free-text symptom description from an engineer or
                      helpdesk ticket. No preprocessing required — pass it
                      in exactly as written.

    Returns:
        ClassifierOutput with incident_type, confidence (0.0-1.0),
        matched_signals (list of human-readable labels), and explanation.
    """
    # Lowercase once here so every signal check doesn't have to
    text = symptom_text.lower()

    # Score every incident type by counting how many of its signals appear
    # in the symptom text
    scores = {}
    for incident_type, signals in INCIDENT_SIGNALS.items():

        matched_labels = []
        seen_labels = set()  # Prevents two phrases with the same label
                             # from being counted or displayed twice

        for phrase, label in signals:
            if phrase in text and label not in seen_labels:
                matched_labels.append(label)
                seen_labels.add(label)

        raw_score = len(matched_labels) / len(signals)
        scores[incident_type] = {
            "matched": matched_labels,
            "raw_score": raw_score,
        }

    # Pick the highest-scoring type
    best_type = max(scores, key=lambda t: scores[t]["raw_score"])
    best = scores[best_type]

    # Handle the edge case where nothing matched at all
    if best["raw_score"] == 0.0:
        return ClassifierOutput(
            incident_type="unknown",
            confidence=0.0,
            matched_signals=[],
            explanation=(
                "No signals matched any of the 10 known incident types. "
                "Manual triage required."
            ),
        )

    confidence = _scale_confidence(best["raw_score"])
    n_matched = len(best["matched"])
    n_total = len(INCIDENT_SIGNALS[best_type])

    explanation = (
        f"Classified as '{best_type}' based on {n_matched} of {n_total} "
        f"defined signals matched (raw rate: {best['raw_score']:.0%}, "
        f"scaled confidence: {confidence:.0%})."
    )

    return ClassifierOutput(
        incident_type=best_type,
        confidence=confidence,
        matched_signals=best["matched"],
        explanation=explanation,
    )


# ---------------------------------------------------------------------------
# Manual smoke test
#
# This block only runs when you execute this file directly:
#   python pipeline/simulated_classifier.py
#
# It does NOT run when another module imports classify_incident().
# Use this to verify the classifier is working before wiring it into
# the rest of the pipeline.
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    test_cases = [
        (
            "DHCP exhaustion",
            "Multiple users on the 3rd floor reporting no network access. "
            "Affected devices show 169.254.x.x addresses or limited connectivity "
            "on Windows. Started around 8:45am, getting worse as more people "
            "arrive and connect."
        ),
        (
            "SERVFAIL",
            "Intermittent SERVFAIL errors for api.novaridge.example reported from "
            "multiple unrelated external networks. Comes and goes. No firewall alerts."
        ),
        (
            "DNS hijacking",
            "A couple of employees saw a certificate warning visiting our intranet "
            "portal. IT noticed an anomalous answer in the resolver logs — an "
            "unexpected IP that doesn't match our server."
        ),
        (
            "DNS forwarding failure",
            "Branch office can resolve internal company domains fine but cannot "
            "reach any external websites. Other locations unaffected. The upstream "
            "forwarder may be involved."
        ),
        (
            "IP conflict",
            "Two laptops getting IP address conflict popups and dropping off the "
            "network. Issue followed the laptop when we swapped the cable, not "
            "the port."
        ),
    ]

    print("=" * 60)
    print("simulated_classifier.py — smoke test")
    print("=" * 60)

    for label, symptom in test_cases:
        result = classify_incident(symptom)
        print(f"\nTest case : {label}")
        print(f"  Type       : {result.incident_type}")
        print(f"  Confidence : {result.confidence:.0%}")
        print(f"  Signals    : {result.matched_signals}")
        print(f"  Explanation: {result.explanation}")

    print("\n" + "=" * 60)
    print("Smoke test complete.")
    print("=" * 60)
