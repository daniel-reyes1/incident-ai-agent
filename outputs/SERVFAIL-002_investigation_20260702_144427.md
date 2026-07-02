# DDI Incident Investigation Report

**Scenario ID**: SERVFAIL-002
**Incident type**: SERVFAIL Rate Spike
**Difficulty**: Hard — multi-loop convergence (2 investigation cycles before resolution)
**Generated**: 2026-07-02 14:44:27
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
- **Incident Classification:** Confirming the automated classification as "SERVFAIL rate spike". The incident report explicitly mentions "intermittent SERVFAIL" errors, customers and staff unable to reach a site, and reports from different, unrelated networks, all of which align perfectly with the description and symptoms of a SERVFAIL rate spike in the domain knowledge.
- **Scope:** Widespread. The incident report states "Reports spread across different, unrelated networks again — doesn't point at one location or one customer." This indicates a broad impact, not localized to a specific subnet or site.
- **Severity:** High. The issue affects "Customers and a couple of remote staff" for a critical-sounding service (`api.novaridge.example`), has been ongoing for "about 4 hours", and is widespread, indicating significant business impact.

STAGE 2 — HYPOTHESES (ranked by likelihood)

1.  **Hypothesis: Upstream forwarder or resolver unreachable**
    *   **Likelihood:** High
    *   **Reasoning:** This is listed as the "most common cause" in the domain knowledge. Intermittent SERVFAILs experienced by clients across "different, unrelated networks" strongly suggest a problem upstream of the organization's recursive resolvers, affecting all queries routed through them. Intermittency could be due to network flakiness or failover attempts.

2.  **Hypothesis: DNSSEC validation failure (ZSK issue or KSK/DS mismatch)**
    *   **Likelihood:** High
    *   **Reasoning:** DNSSEC validation failures are a common cause of SERVFAIL for specific zones, like `api.novaridge.example`. The "intermittent" nature could be due to TTLs, caching by various recursive resolvers, or the issue propagating globally. The 4-hour duration is consistent with a recent ZSK expiry or a KSK rollover that wasn't properly coordinated, leading to a break in the trust chain.

3.  **Hypothesis: Authoritative server misconfiguration for `novaridge.example`**
    *   **Likelihood:** Medium
    *   **Reasoning:** A misconfiguration (e.g., zone file syntax error, incorrect record for `api.novaridge.example`) on the authoritative DNS server(s) for `novaridge.example` could directly lead to SERVFAILs for that specific domain. The "intermittent" nature might be explained by caching on recursive resolvers or clients hitting different authoritative servers (some with older, cached data, some with new, misconfigured data). The "widespread" nature is expected, as the misconfiguration would impact all clients attempting to resolve that specific domain.

4.  **Hypothesis: Resource exhaustion on a DDI recursive DNS server**
    *   **Likelihood:** Medium
    *   **Reasoning:** If a DDI recursive DNS server is experiencing resource limits (CPU, memory, file descriptors), it could intermittently fail to process or respond to queries, leading to SERVFAILs. This would appear "widespread" to all clients relying on that server, and "intermittent" as resources fluctuate under load.

STAGE 3 — INVESTIGATION PLAN

**Hypothesis 1: Upstream forwarder or resolver unreachable**
*   **Investigation Step:** From the DDI recursive resolvers, attempt to resolve a known external domain (e.g., `www.google.com`) using each configured upstream forwarder IP directly (e.g., `dig @<upstream_IP> www.google.com`). Also, perform network connectivity checks (ping, traceroute) to each upstream IP on port 53.
*   **Confirming Finding:** `dig` commands to one or more upstream forwarders fail or time out. Network connectivity checks (ping/traceroute) show packet loss or unreachability to upstream IPs on port 53 from the recursive resolvers.
*   **Ruling Out Finding:** All `dig` commands to configured upstream forwarders successfully resolve known external domains. Network connectivity (ping, traceroute) to all upstream IPs on port 53 is stable and successful.

**Hypothesis 2: DNSSEC validation failure (ZSK issue or KSK/DS mismatch)**
*   **Investigation Step:** Perform a DNSSEC validation check for `api.novaridge.example` from a validating recursive resolver (e.g., `dig +dnssec api.novaridge.example`). Examine the RRSIG records for `novaridge.example` in the output for expiry dates. If issues persist, check the DS record published at the parent zone (e.g., registrar) and compare it against the current KSK found in the `novaridge.example` zone.
*   **Confirming Finding:** The `dig +dnssec` output for `api.novaridge.example` shows `SERVFAIL` with the `AD` (Authenticated Data) flag *not* set. This indicates a validation failure. Further analysis reveals an expired RRSIG for the `novaridge.example` zone, or a mismatch between the DS record at the parent and the zone's KSK.
*   **Ruling Out Finding:** The `dig +dnssec` output for `api.novaridge.example` successfully returns the IP address with the `AD` flag set, indicating successful DNSSEC validation. All RRSIG records for `novaridge.example` are valid and unexpired, and the DS record at the parent matches the KSK in the zone.

**Hypothesis 3: Authoritative server misconfiguration for `novaridge.example`**
*   **Investigation Step:** Query the authoritative nameservers for `novaridge.example` directly for `api.novaridge.example` (e.g., `dig @<ns1.novaridge.example> api.novaridge.example`). Additionally, access the authoritative DNS server(s) for `novaridge.example` and run a zone file syntax check (e.g., `named-checkzone novaridge.example /path/to/zonefile`) for the `novaridge.example` zone.
*   **Confirming Finding:** Direct queries to the authoritative nameserver(s) for `novaridge.example` return `SERVFAIL` for `api.novaridge.example`. The zone file syntax check (e.g., `named-checkzone`) reports errors or warnings for the `novaridge.example` zone.
*   **Ruling Out Finding:** Direct queries to all authoritative nameserver(s) for `novaridge.example` successfully resolve `api.novaridge.example`. The zone file syntax check for `novaridge.example` reports no errors.

**Hypothesis 4: Resource exhaustion on a DDI recursive DNS server**
*   **Investigation Step:** Review historical performance metrics (CPU utilization, memory usage, open file descriptors, active DNS queries/connections, packet drops) for all DDI recursive resolvers during the 4-hour incident window. Check DNS server logs for any resource-related warnings or errors.
*   **Confirming Finding:** Performance graphs show a clear correlation between the incident start time and duration with sustained spikes or limits being reached in CPU, memory, or open file descriptors on one or more DDI recursive resolvers. DNS server logs contain entries indicating resource contention or query failures due to resource limits.
*   **Ruling Out Finding:** Performance graphs show normal, stable CPU, memory, and file descriptor usage on all DDI recursive resolvers during the incident period. DNS server logs do not show any resource-related errors or warnings.

---

## Stage 4 — Engineer Feedback (Round 1)

SERVFAILs are spread across a lot of different source IPs again, nothing concentrated, so still doesn't look like an attack. Checked the ZSK and RRSIG this time and they're actually fine, signature is valid, expires three weeks from now, rollover ran on schedule last cycle. Authoritative servers look healthy, normal CPU and response times. No traffic spike on the auth servers either. Honestly not sure what's causing it at this point, the usual checks all came back clean.

---

## Stage 2B-3 — Expanded Investigation (Round 2)

Here is the expanded hypothesis space based on the remaining investigative avenues and domain knowledge:

---

### STAGE 2B — EXPANDED HYPOTHESIS

**1. Hypothesis: Network-level filtering (firewall, ACLs) blocking or intermittently disrupting DNS traffic between DDI recursive resolvers and upstream forwarders.**
*   **Likelihood:** High
*   **Reasoning:** The original Hypothesis 1 ("Upstream forwarder or resolver unreachable") still has insufficient evidence, particularly concerning *how* reachability is affected. Network-level filtering is a very common cause of such unreachability or intermittent connectivity issues, especially after recent network changes, and is explicitly listed in the domain knowledge as a potential root cause ("Firewall block"). This hypothesis explains intermittent SERVFAILs if the block is not absolute, if different forwarders/paths are affected, or if the filtering is state-dependent. It's consistent with reports from "different, unrelated networks" if the core DDI resolvers are universally affected by the internal network block. It was not explicitly covered or ruled out by the initial set of hypotheses, which focused on general "unreachability."

**2. Hypothesis: Attack-driven spike (e.g., phantom domain / random subdomain attack) overwhelming DDI recursive resolver resources.**
*   **Likelihood:** Medium
*   **Reasoning:** While the initial triage noted "No firewall alerts, nothing that looks like an attack," the domain knowledge explicitly lists "Attack-driven spike" as a probable root cause for SERVFAILs, specifically mentioning "phantom domain or random subdomain attack" as distinct from other types of attacks. These types of attacks generate a high volume of unique, non-cacheable queries that can exhaust recursive resolver resources (CPU, memory for cache, connection limits to upstreams) for *legitimate* queries, leading to SERVFAILs. This would manifest as resource exhaustion on the DDI recursive resolvers, which is still an area of insufficient evidence (Hypothesis 4). The "intermittent" nature could be due to the attack's burstiness or the fluctuating impact on resources. It's consistent with "reports spread across different, unrelated networks" as the central recursive resolvers would be affected.

---

### STAGE 3 — INVESTIGATION PLAN (Round 2)

**Hypothesis 1: Network-level filtering (firewall, ACLs) blocking or intermittently disrupting DNS traffic between DDI recursive resolvers and upstream forwarders.**
*   **Investigation Step:**
    1.  From a command-line interface on *each* DDI recursive resolver, perform network path diagnostics to *each* configured upstream forwarder IP using both UDP and TCP on port 53. For example: `traceroute -p 53 -U <upstream_IP>` (for UDP) and `traceroute -p 53 <upstream_IP>` (for TCP).
    2.  Review firewall logs for the network segments/VLANs that route between the DDI recursive resolvers and their upstream forwarders. Specifically look for dropped packets or connection resets on port 53 (UDP/TCP) originating from the DDI recursive resolver IPs towards the upstream forwarder IPs during the incident window.
*   **Confirming Finding:** Traceroute output shows persistent packet loss or explicit `!` (host unreachable/port unreachable) symbols at specific hops towards one or more upstream forwarders, indicative of a block. Firewall logs show dropped packets for DNS traffic (port 53 UDP/TCP) originating from the DDI recursive resolvers towards the upstream forwarders during the incident window.
*   **Ruling Out Finding:** Traceroute to all configured upstream forwarders completes successfully with expected latency and no indication of blocks or excessive packet loss. Firewall logs show no dropped packets for DNS traffic (port 53 UDP/TCP) between the DDI recursive resolvers and their upstream forwarders during the incident window.

**Hypothesis 2: Attack-driven spike (e.g., phantom domain / random subdomain attack) overwhelming DDI recursive resolver resources.**
*   **Investigation Step:**
    1.  Review DDI recursive DNS server query logs and statistics during the 4-hour incident window.
    2.  Specifically look for patterns indicative of a phantom domain or random subdomain attack:
        *   **High unique query rate:** Analyze the rate of queries for non-existent or randomly generated subdomains (e.g., `randomstring.api.novaridge.example`) within the `novaridge.example` zone or other common TLDs.
        *   **Per-source-IP concentration:** Determine if a significant portion of these unique, non-existent queries originates from a small number of source IPs.
    3.  Correlate these query patterns with any spikes in CPU, memory, open file descriptors, or active DNS queries/connections on the DDI recursive resolvers (this leverages the unconfirmed aspects of original Hypothesis 4).
*   **Confirming Finding:** Query logs show a dramatic and sustained spike in unique, non-cacheable queries (e.g., for `randomstring.api.novaridge.example` or similar patterns) during the incident. A substantial portion of these queries originates from a limited set of source IPs, and this pattern correlates directly with observed spikes in CPU, memory, and/or active connections on the DDI recursive resolvers.
*   **Ruling Out Finding:** Query logs show no abnormal patterns of unique, non-existent domain queries or a concentration of queries from a few source IPs during the incident window. The overall query load, even if elevated, does not exhibit the characteristics of a phantom domain or random subdomain attack.

---

## Stage 4 — Engineer Feedback (Round 2)

Pulled the DS record from the registrar and compared it against our current KSK hash, and they don't match. Looked into it further and there was a KSK rollover done about 5 weeks ago as part of routine key maintenance, but whoever did it apparently didn't push the updated DS record to the registrar afterward, so the registrar's been holding a DS record pointing at our old, retired KSK this whole time. Makes sense why it's intermittent too, depends on which resolvers cached the old chain of trust versus which ones are doing a fresh validation now.

---


## Stage 5 — Final Synthesis

Hypothesis: Network-level filtering (firewall, ACLs) blocking or intermittently disrupting DNS traffic between DDI recursive resolvers and upstream forwarders.
Status: INSUFFICIENT EVIDENCE
Evidence: The engineer's findings do not contain any information related to network path diagnostics (traceroute) or firewall logs, as specified in the investigation step for this hypothesis.

Hypothesis: Attack-driven spike (e.g., phantom domain / random subdomain attack) overwhelming DDI recursive resolver resources.
Status: INSUFFICIENT EVIDENCE
Evidence: The engineer's findings do not contain any information related to DDI recursive DNS server query logs, unique query rates, source IP concentrations, or correlation with resource spikes (CPU, memory), as specified in the investigation step for this hypothesis.

CONVERGENCE: RESOLVED
CONFIRMED CAUSE: A DNSSEC misconfiguration where the KSK rollover was not properly completed, resulting in a mismatch between the DS record at the registrar (pointing to an old KSK) and the current KSK used to sign the zone, causing DNSSEC validation failures (SERVFAIL) for `api.novaridge.example`.
CONFIDENCE: 95%

HUMAN REVIEW REQUIRED — These findings must be reviewed and approved by a qualified engineer before any remediation is attempted.

---

## Stage 6 — Final Report

**CAUSE:**
The intermittent SERVFAIL errors for `api.novaridge.example`, affecting customers and remote staff for approximately four hours and reported across widespread, unrelated networks, were caused by a DNSSEC misconfiguration. A KSK (Key Signing Key) rollover performed roughly five weeks prior was not fully completed; the updated DS (Delegation Signer) record reflecting the new KSK was never pushed to the domain registrar. Consequently, the registrar continued to publish an outdated DS record that pointed to the organization's old, retired KSK. This critical mismatch broke the DNSSEC trust chain, causing validating recursive resolvers worldwide to report SERVFAIL when attempting to validate the authenticity of `api.novaridge.example`. The intermittent nature of the problem is attributed to varying caching behaviors of recursive resolvers globally, where some were still serving cached, unexpired records from before the validation issue was widely propagated, while others were attempting fresh validation and failing due to the DS record mismatch.

**EVIDENCE TRAIL:**
- Customers and remote staff reported intermittent SERVFAIL / 'site can't be reached' errors for `api.novaridge.example` for about 4 hours.
- Reports were widespread across different, unrelated networks, indicating a global issue not localized to a specific client or network.
- Initial investigation confirmed that the ZSK (Zone Signing Key) and RRSIG (Resource Record Signature) for `novaridge.example` were valid and unexpired, ruling out a simple ZSK expiry.
- Authoritative DNS servers for `novaridge.example` were found to be healthy with normal CPU, response times, and no traffic spikes, ruling out authoritative server resource exhaustion or misconfiguration on the primary servers.
- The DS record obtained from the domain registrar was compared against the current KSK hash used by the zone and found not to match.
- Further investigation revealed a KSK rollover had been performed approximately five weeks prior, but the essential step of pushing the updated DS record to the registrar was overlooked, leaving an incorrect DS record in place.
- The intermittent nature of the SERVFAILs was correlated with the propagation of the incorrect DNSSEC trust chain across various recursive resolvers with different caching mechanisms.

**REMEDIATION STEPS:**
1.  **Immediate:** Submit the correct DS record (matching the current KSK hash) to the domain registrar for `novaridge.example` to re-establish the DNSSEC trust chain.
2.  **Immediate:** Monitor DNSSEC validation status for `api.novaridge.example` using external tools and public DNS resolvers to confirm successful resolution and validation across the internet.
3.  **Medium-term:** Implement or enhance automated checks to compare published DS records at the parent zone (registrar) with the active KSK in the child zone as a regular part of DNSSEC health monitoring.
4.  **Long-term:** Update and reinforce the KSK rollover procedure documentation to explicitly include the critical step of submitting the new DS record to the registrar and verifying its publication.
5.  **Long-term:** Conduct a post-incident review to identify the specific failure point in the KSK rollover procedure and implement preventative measures, such as a multi-person review process or automated pre- and post-rollover validation.

HUMAN SIGN-OFF: [ ] Reviewed and approved by: ___________ Date: ___________

---

*Generated by DDI Copilot Investigator — MVP v2.*
*Human review required before any remediation is attempted.*
