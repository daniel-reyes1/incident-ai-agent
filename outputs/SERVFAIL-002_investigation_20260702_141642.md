# DDI Incident Investigation Report

**Scenario ID**: SERVFAIL-002
**Incident type**: SERVFAIL Rate Spike
**Difficulty**: Hard — multi-loop convergence (2 investigation cycles before resolution)
**Generated**: 2026-07-02 14:16:42
**Pipeline version**: MVP v2 (Stages 1-6)
**Investigation rounds**: 2

---

## Classifier Output

| Field | Value |
|-------|-------|
| Incident type | SERVFAIL rate spike |
| Confidence | 82% |
| Matched signals | SERVFAIL errors mentioned, Site unreachability reported, Reports from unrelated networks, Intermittent failure pattern |

---

## Symptom Description

Customers and a couple of remote staff reporting intermittent SERVFAIL / 'site can't be reached' errors for api.novaridge.example, going on for about 4 hours now. Comes and goes, not every request. Reports spread across different, unrelated networks again — doesn't point at one location or one customer. No firewall alerts, nothing that looks like an attack.

---

## Stage 1-3 — Initial Investigation (Round 1)

STAGE 1 — TRIAGE

*   **Classification:** Confirm "SERVFAIL rate spike". The incident report explicitly mentions "intermittent SERVFAIL / 'site can't be reached' errors" for a specific domain, matching the core symptom and description of a SERVFAIL rate spike as defined in the domain knowledge.
*   **Scope:** Potentially widespread. Reports are "spread across different, unrelated networks," indicating a global impact for clients attempting to resolve `api.novaridge.example`, rather than an issue localized to a single network segment or site.
*   **Severity:** Medium-High. The issue affects customers and remote staff attempting to reach a likely critical API service (`api.novaridge.example`), causing intermittent outages for over 4 hours. This has a direct impact on business operations and user experience.

STAGE 2 — HYPOTHESES (ranked by likelihood)

1.  **Upstream forwarder or resolver unreachable**
    *   **Likelihood:** High
    *   **Reasoning:** This is listed as the most common cause for SERVFAILs in the domain knowledge. Intermittent SERVFAILs across "different, unrelated networks" strongly suggest a common upstream point of failure—the recursive resolvers responsible for resolving `api.novaridge.example` intermittently losing connectivity to their configured forwarders. This would cause intermittent resolution failures for any domain, including the specific `api.novaridge.example`.

2.  **DNSSEC validation failure**
    *   **Likelihood:** High
    *   **Reasoning:** DNSSEC validation failures are a frequent cause of SERVFAILs, particularly for specific domains like `api.novaridge.example`. The "intermittent" nature could be due to caching effects, or issues surrounding a key rollover (ZSK or KSK), where the signature might be intermittently invalid or expired, causing validating resolvers to fail intermittently. Widespread reports are consistent with DNSSEC validation failures affecting any validating resolver globally.

3.  **Zone transfer failure**
    *   **Likelihood:** Medium
    *   **Reasoning:** If secondary authoritative nameservers for `novaridge.example` are failing to receive updated zone data from the primary, they could be serving stale or incomplete information, leading to SERVFAILs for `api.novaridge.example`. The "intermittent" nature could arise if only some secondary servers are affected, or if the zone transfer process itself is sporadically failing, causing some clients to hit an unhealthy secondary while others hit a healthy one. The issue is specific to the `novaridge.example` zone, which aligns with the reported single affected domain.

STAGE 3 — INVESTIGATION PLAN

**Hypothesis 1: Upstream forwarder or resolver unreachable**

*   **What to check:** Check network connectivity (e.g., `ping`, `traceroute`) from the organization's recursive DNS servers to their configured upstream forwarders on port 53 (both UDP and TCP). Review the recursive DNS server's system logs and DNS query logs for errors indicating connection timeouts, refusals, or unreachability to upstream forwarders *during the last 4-6 hours*.
*   **Confirm:** Connectivity checks reveal packet loss, high latency, or complete unreachability to one or more upstream forwarders, or recursive DNS server logs show explicit errors (e.g., `SERVFAIL`, `timeout`, `network unreachable`) when attempting to query upstream forwarders for `api.novaridge.example`.
*   **Rule out:** Consistent and stable network connectivity to all configured upstream forwarders on port 53, with recursive DNS server logs showing successful and timely queries to upstream forwarders without error *during the incident window*.

**Hypothesis 2: DNSSEC validation failure**

*   **What to check:** Perform a DNSSEC validation check for `api.novaridge.example` using `dig +dnssec api.novaridge.example @[recursive_resolver_IP]` from an affected network/client, and potentially online DNSSEC debugging tools. Specifically, inspect the `RCODE` (expecting `SERVFAIL`), the `ad` flag (missing or incorrect), and the validity periods of the Zone Signing Key (ZSK) and Key Signing Key (KSK) signatures. Check the DNS management system's audit logs or alerts for any DNSSEC key expiration warnings or failed rollover events for `novaridge.example` around the incident start time.
*   **Confirm:** DNSSEC validation tools report a broken chain of trust, an expired ZSK, or a KSK/DS record mismatch for `api.novaridge.example`. The DNS management system logs show warnings or errors related to DNSSEC key expiration or signing failures for the `novaridge.example` zone.
*   **Rule out:** DNSSEC validation successfully completes (`AD` flag is present, RCODE is NOERROR), all signatures for `api.novaridge.example` are valid and unexpired, and no DNSSEC key expiration alerts were triggered for the zone *during the incident window*.

**Hypothesis 3: Zone transfer failure**

*   **What to check:** Connect to all primary and secondary authoritative DNS servers for `novaridge.example`. On the secondary servers, review zone transfer logs (e.g., `BIND` logs showing AXFR/IXFR events) for any failures, errors, or skipped transfers related to `novaridge.example` in the last 4-6 hours. Compare the serial numbers of the `novaridge.example` zone on the primary and all secondary servers using `dig @[server_IP] novaridge.example SOA`.
*   **Confirm:** Zone transfer logs on one or more secondary authoritative servers show recurring failures (e.g., `REFUSED`, `TSIG error`, `connection timed out`) for `novaridge.example` from the primary server. The serial number of the `novaridge.example` zone on one or more secondary servers is older than the primary, indicating a stale zone.
*   **Rule out:** Zone transfer logs on all secondary authoritative servers show consistent successful AXFR/IXFR transfers for `novaridge.example`, and the SOA serial numbers for the `novaridge.example` zone are identical across all primary and secondary authoritative DNS servers *during the incident window*.

---

## Stage 4 — Engineer Feedback (Round 1)

SERVFAILs are spread across a lot of different source IPs again, nothing concentrated, so still doesn't look like an attack. Checked the ZSK and RRSIG this time and they're actually fine, signature is valid, expires three weeks from now, rollover ran on schedule last cycle. Authoritative servers look healthy, normal CPU and response times. No traffic spike on the auth servers either. Honestly not sure what's causing it at this point, the usual checks all came back clean.

---

## Stage 2B-3 — Expanded Investigation (Round 2)

Here's the expanded hypothesis and investigation plan for Round 2:

---

### STAGE 2B — EXPANDED HYPOTHESIS

**Hypothesis 4: Authoritative DNS server misconfiguration or internal error processing `api.novaridge.example` queries.**

*   **Likelihood:** High
*   **Reasoning:** A `SERVFAIL` response from an authoritative server indicates an internal problem, rather than just a non-existent domain (`NXDOMAIN`) or a refusal (`REFUSED`). While "Authoritative servers look healthy, normal CPU and response times" was reported, this is a high-level aggregate view. It doesn't rule out specific issues within the DNS software itself (e.g., BIND, PowerDNS, NSD) or a misconfiguration that only affects the resolution of `api.novaridge.example` or dependencies required for it.
    *   **Consistency with original symptom:**
        *   **Intermittent SERVFAILs for `api.novaridge.example`:** A specific misconfiguration (e.g., a broken CNAME chain, a non-existent glue record, a syntax error in a rarely accessed part of the zone file, or an issue with dynamically updated records) might only manifest intermittently, or when specific authoritative servers (in a cluster or Anycast setup) are hit by queries for this domain. An intermittent internal process failure (e.g., database lookup failure for dynamic zones, resource exhaustion for specific query types) could also cause this.
        *   **'site can't be reached' errors:** This is the direct user impact of a `SERVFAIL` from an authoritative source.
        *   **Spread across different, unrelated networks:** If the authoritative servers themselves have a problem with the `novaridge.example` zone data or processing, any recursive resolver in the world querying them for `api.novaridge.example` would potentially encounter the issue.
    *   **Consistency with ruled-out findings:**
        *   **DNSSEC validation failure ruled out:** This hypothesis is independent of DNSSEC signing. The problem would lie with the content or internal processing of the `api.novaridge.example` record itself, not its cryptographic signatures or trust chain.

---

### STAGE 3 — INVESTIGATION PLAN (Round 2)

**Hypothesis 4: Authoritative DNS server misconfiguration or internal error processing `api.novaridge.example` queries.**

*   **What to check:**
    1.  **Direct Query & Trace:**
        *   Perform a `dig +trace api.novaridge.example` to identify all currently delegated authoritative nameservers for `novaridge.example`.
        *   For *each identified authoritative nameserver's IP address*, perform multiple direct queries using `dig @[auth_server_IP] api.novaridge.example` (e.g., 5-10 times consecutively, and again after a short delay). Observe the RCODE and any error messages in the output.
    2.  **Authoritative Server Logs:**
        *   Connect to *all* primary and secondary authoritative DNS servers for `novaridge.example`.
        *   Review the DNS server logs (e.g., `syslog`, `named.log`, PowerDNS `pdns.log`) for errors, warnings, or anomalies specifically related to `api.novaridge.example` queries, zone parsing, zone loading, or internal database lookups (if using a dynamic backend) during the last 4-6 hours.
        *   Look for specific messages such as "zone file error", "internal server error", "backend query failed", "resource exhausted processing query", "CNAME loop detected", or "invalid record encountered".
    3.  **Zone Configuration Review:**
        *   Examine the raw zone file for `novaridge.example` (or the configuration in the backend database/management system for dynamic zones) on the primary authoritative server.
        *   Pay close attention to the `api.novaridge.example` record and any records it depends on (e.g., CNAME targets, NS records, glue records). Look for:
            *   Syntax errors, missing data, or malformed entries.
            *   CNAME records pointing to non-existent domains or creating loops.
            *   A records pointing to non-existent or unconfigured IP addresses if the server performs internal health checks.
            *   Conditional logic or dynamic generation scripts for `api.novaridge.example` that might fail intermittently.

*   **Confirm:**
    1.  Direct queries to one or more specific authoritative nameservers intermittently or consistently return a `SERVFAIL` RCODE for `api.novaridge.example`, while others might respond correctly.
    2.  Authoritative server logs show explicit error messages (e.g., "zone parse error", "internal query failure", "database lookup failed for API record") correlated with the incident timeline and specific to `api.novaridge.example` or its related zone data.
    3.  A manual review of the zone configuration or dynamic record source reveals a clear misconfiguration, malformed record, or problematic dependency for `api.novaridge.example`.

*   **Rule out:**
    1.  All direct queries to all identified authoritative nameservers for `novaridge.example` consistently return a `NOERROR` RCODE with the correct `api.novaridge.example` record.
    2.  Authoritative server logs show no errors, warnings, or anomalies related to `api.novaridge.example` or general query processing during the incident window.
    3.  The zone configuration and records related to `api.novaridge.example` are syntactically correct, logically sound, and free of issues that could cause `SERVFAIL`.

---

## Stage 4 — Engineer Feedback (Round 2)

Pulled the DS record from the registrar and compared it against our current KSK hash, and they don't match. Looked into it further and there was a KSK rollover done about 5 weeks ago as part of routine key maintenance, but whoever did it apparently didn't push the updated DS record to the registrar afterward, so the registrar's been holding a DS record pointing at our old, retired KSK this whole time. Makes sense why it's intermittent too, depends on which resolvers cached the old chain of trust versus which ones are doing a fresh validation now.

---


## Stage 5 — Final Synthesis

- Hypothesis: Authoritative DNS server misconfiguration or internal error processing `api.novaridge.example` queries.
- Status: RULED OUT
- Evidence: The engineer findings identify the root cause as a DNSSEC validation failure due to an outdated DS record at the registrar, which directly contradicts this hypothesis's stated reasoning that "DNSSEC validation failure ruled out" and that "The problem would lie with the content or internal processing of the `api.novaridge.example` record itself, not its cryptographic signatures or trust chain." The identified cause is explicitly related to the DNSSEC trust chain, not internal authoritative server processing or record content issues as hypothesized.

CONVERGENCE: RESOLVED
- CONFIRMED CAUSE: The intermittent SERVFAIL errors are caused by a broken DNSSEC chain of trust for the `novaridge.example` domain; specifically, the DS record at the registrar was not updated after a KSK rollover, causing it to point to a retired key and leading to validation failures by DNSSEC-aware recursive resolvers.
- CONFIDENCE: 95%

HUMAN REVIEW REQUIRED — These findings must be reviewed and approved by a qualified engineer before any remediation is attempted.

---

## Stage 6 — Final Report

CAUSE:
The intermittent SERVFAIL errors for `api.novaridge.example` were caused by a broken DNSSEC chain of trust. Approximately five weeks prior to the incident, a Key Signing Key (KSK) rollover was performed for the `novaridge.example` domain as part of routine key maintenance. However, the critical step of updating the corresponding Delegation Signer (DS) record at the domain registrar was overlooked. Consequently, the registrar continued to publish a DS record pointing to the old, retired KSK. DNSSEC-validating recursive resolvers, upon attempting to validate the trust chain for `api.novaridge.example`, would find a mismatch between the current KSK in the zone and the outdated DS record at the parent zone. This mismatch led to validation failures, resulting in SERVFAIL responses for affected clients. The intermittent nature of the issue is attributed to varying DNS cache TTLs across different recursive resolvers; some resolvers were still serving cached, valid records from before the KSK rollover, while others were performing fresh validations and encountering the broken trust chain.

EVIDENCE TRAIL:
- Symptom description of "intermittent SERVFAIL / 'site can't be reached' errors" for `api.novaridge.example` spread across "different, unrelated networks."
- Initial investigation hypothesized DNSSEC validation failure as a high-likelihood cause due to its consistency with widespread intermittent SERVFAILs.
- Initial engineer feedback confirmed that the Zone Signing Key (ZSK) and RRSIG signatures were valid, ruling out issues with the internal key material or signing process itself, but not the overall trust chain.
- Round 2 engineer feedback explicitly stated: "Pulled the DS record from the registrar and compared it against our current KSK hash, and they don't match."
- Round 2 engineer feedback further elaborated: "there was a KSK rollover done about 5 weeks ago... whoever did it apparently didn't push the updated DS record to the registrar afterward, so the registrar's been holding a DS record pointing at our old, retired KSK this whole time."
- The engineer feedback provided the explanation for intermittency: "depends on which resolvers cached the old chain of trust versus which ones are doing a fresh validation now."

REMEDIATION STEPS:
1.  **Immediate:** Update the DS record at the domain registrar for `novaridge.example` to correctly reflect the hash of the current Key Signing Key (KSK).
2.  **Medium-term:** Review and update the standard operating procedure (SOP) for DNSSEC KSK rollovers to include explicit, mandatory steps for updating DS records at the registrar and verifying their propagation.
3.  **Long-term:** Implement automated monitoring and alerting specifically for DNSSEC trust chain integrity, including checks for DS record mismatches against published KSKs, and alerts for impending key expirations to prevent future manual oversights.

HUMAN SIGN-OFF: [ ] Reviewed and approved by: ___________ Date: ___________

---

*Generated by DDI Copilot Investigator — MVP v2.*
*Human review required before any remediation is attempted.*
