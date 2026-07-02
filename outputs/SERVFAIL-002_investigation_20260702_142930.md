# DDI Incident Investigation Report

**Scenario ID**: SERVFAIL-002
**Incident type**: SERVFAIL Rate Spike
**Difficulty**: Hard — multi-loop convergence (2 investigation cycles before resolution)
**Generated**: 2026-07-02 14:29:30
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

*   **Confirm or adjust incident classification:** The automated classification of "SERVFAIL rate spike" is confirmed. The incident report's description of "intermittent SERVFAIL / 'site can't be reached' errors" for a specific domain, affecting various unrelated networks, aligns directly with the symptoms and description of a SERVFAIL rate spike in the domain knowledge.
*   **Scope:** This incident is widespread, affecting customers and remote staff across different, unrelated networks, and is specific to the `api.novaridge.example` domain.
*   **Severity:** Medium-High. Customers and staff are experiencing intermittent connectivity issues to a critical API for an extended period (4 hours), impacting service availability and user experience.

STAGE 2 — HYPOTHESES (ranked by likelihood)

1.  **DNSSEC validation failure for `api.novaridge.example`**
    *   **Likelihood:** High
    *   **Reasoning:** SERVFAIL for a specific domain, especially when intermittent and sustained for several hours, strongly points towards DNSSEC validation issues. This could be due to an expired Zone Signing Key (ZSK) or a Key Signing Key (KSK)/Delegation Signer (DS) mismatch, which often manifest as SERVFAIL for validating resolvers and can take time to resolve. Intermittency could arise if some resolvers have older valid caches or some servers in a cluster are failing validation.

2.  **Zone transfer failure for `novaridge.example` zone**
    *   **Likelihood:** High
    *   **Reasoning:** Intermittent SERVFAIL for a specific domain that is reported from multiple, unrelated networks is a classic symptom of secondary nameservers serving stale or missing zone data for `novaridge.example`. Clients querying an updated primary or successfully transferred secondary would resolve correctly, while those hitting a failing secondary would receive SERVFAIL, leading to the reported intermittent pattern.

3.  **Intermittent unreachability of authoritative servers for `novaridge.example` from recursive resolvers/forwarders**
    *   **Likelihood:** Medium-High
    *   **Reasoning:** While general upstream forwarder unreachability usually affects all domains, a specific network path issue or intermittent overload/failure on the authoritative nameservers *for novaridge.example* could cause recursive resolvers/forwarders to intermittently fail to reach them, resulting in SERVFAIL. The intermittent nature fits well with network instability.

STAGE 3 — INVESTIGATION PLAN

**For Hypothesis 1: DNSSEC validation failure for `api.novaridge.example`**

*   **What to check:** Check the DNSSEC status for `novaridge.example` using an external DNSSEC validation tool (e.g., `dnsviz.net`, `zonemaster.net` equivalent) and internal `dig +dnssec` queries from recursive resolvers. Pay close attention to the Zone Signing Key (ZSK) and Key Signing Key (KSK) expiration dates and verify that the Delegation Signer (DS) record published at the parent zone matches the current KSK.
*   **Confirming finding:** The DNSSEC validation tool or `dig +dnssec` output reports a broken chain of trust, an expired ZSK signature, or a KSK/DS mismatch for `novaridge.example` or its parent delegation.
*   **Ruling out finding:** The DNSSEC validation tool and `dig +dnssec` output consistently report a healthy and valid chain of trust for `novaridge.example` and its parent zone, with all keys and signatures within their valid periods.

**For Hypothesis 2: Zone transfer failure for `novaridge.example` zone**

*   **What to check:** Access the logs of all secondary DNS servers responsible for the `novaridge.example` zone. Specifically, review AXFR/IXFR zone transfer logs for any failures or errors that occurred in the last 4-6 hours. Additionally, compare the Serial Number (from the SOA record) of `novaridge.example` zone on the primary nameserver with all secondary nameservers.
*   **Confirming finding:** Zone transfer logs show recent AXFR/IXFR failures, errors, or timeouts, and secondary servers have a significantly older Serial Number (SOA) for `novaridge.example` compared to the primary, or are missing the zone entirely.
*   **Ruling out finding:** Zone transfer logs show successful AXFR/IXFR completions, and all secondary servers have the same, current Serial Number (SOA) for `novaridge.example` as reported by the primary nameserver.

**For Hypothesis 3: Intermittent unreachability of authoritative servers for `novaridge.example` from recursive resolvers/forwarders**

*   **What to check:** From several recursive resolvers/forwarders that are handling queries for `api.novaridge.example`, perform `dig @<authoritative_IP> api.novaridge.example` requests directly to the authoritative nameservers for `novaridge.example`. Simultaneously, run `ping` and `traceroute` commands from these recursive resolvers/forwarders to the authoritative nameserver IP addresses, monitoring for packet loss, high latency, or intermittent timeouts.
*   **Confirming finding:** Direct `dig` queries to the authoritative servers for `novaridge.example` from the recursive resolvers/forwarders intermittently fail or time out, or `ping`/`traceroute` results show intermittent packet loss, high latency, or route failures to these authoritative servers.
*   **Ruling out finding:** Direct `dig` queries to the authoritative servers for `novaridge.example` from the recursive resolvers/forwarders consistently succeed within expected latency, and `ping`/`traceroute` results show stable network connectivity with no significant packet loss or high latency.

---

## Stage 4 — Engineer Feedback (Round 1)

SERVFAILs are spread across a lot of different source IPs again, nothing concentrated, so still doesn't look like an attack. Checked the ZSK and RRSIG this time and they're actually fine, signature is valid, expires three weeks from now, rollover ran on schedule last cycle. Authoritative servers look healthy, normal CPU and response times. No traffic spike on the auth servers either. Honestly not sure what's causing it at this point, the usual checks all came back clean.

---

## Stage 2B-3 — Expanded Investigation (Round 2)

Okay, the first round of investigation has ruled out DNSSEC validation failure (H1) and highlighted missing evidence for zone transfer issues (H2) and authoritative server reachability (H3). The existing authoritative servers are reported to have "normal CPU and response times" and "no traffic spike."

Given this, we need to think about what else could cause intermittent SERVFAIL for a specific domain across various networks, *other than* the DNSSEC chain being broken, secondaries being stale, or authoritatives being unreachable.

Here are two new hypotheses that fit the criteria:

---

### STAGE 2B — EXPANDED HYPOTHESIS

**New Hypothesis 1: Intermittent Backend Dependency Failure on Authoritative DNS Servers.**

*   **State clearly and concisely:** The authoritative nameservers for `novaridge.example` rely on an internal backend system (e.g., a database, an internal API, a configuration management system) to retrieve the record data for `api.novaridge.example`. This backend system is intermittently failing, becoming unresponsive, or experiencing high latency, causing the authoritative DNS servers to fail in formulating a response and thus returning SERVFAIL.
*   **Likelihood:** High
*   **Reasoning:**
    *   **Consistent with original symptom pattern:** This directly explains why the issue is intermittent (backend goes up and down/slows down), specific to `api.novaridge.example` (if the backend only affects this data or a subset), and affects various networks (as all recursive resolvers eventually query the authoritative servers).
    *   **Consistent with what was ruled out in round 1:** This is entirely independent of DNSSEC validation (H1), as the chain of trust might be perfect, but the authoritative server cannot retrieve the *actual data* to sign or serve. It also differs from general authoritative server unreachability (H3) because the authoritative server itself is reachable and responsive, but its internal data source is failing. The "normal CPU and response times" for the DNS servers might not reflect issues with an *upstream dependency* that they rely on for data.

**New Hypothesis 2: Specific Authoritative DNS Server Process or Resource Exhaustion.**

*   **State clearly and concisely:** While overall CPU and network traffic are normal, a specific internal process, daemon, or resource pool (e.g., memory allocated for a specific zone's queries, number of file descriptors, or internal thread pool) on one or more authoritative DNS servers for `novaridge.example` is intermittently experiencing exhaustion, crashing, or misbehaving. This leads to SERVFAIL responses for a subset of queries for `api.novaridge.example` even if the server appears generally healthy.
*   **Likelihood:** Medium
*   **Reasoning:**
    *   **Consistent with original symptom pattern:** Intermittent internal failures or resource exhaustion within the DNS daemon itself would directly lead to intermittent SERVFAILs. It explains why not every request fails and why it's specific to the authoritative zone (and thus affects different networks).
    *   **Consistent with what was ruled out in round 1:** This is unrelated to DNSSEC validation (H1). The "normal CPU and response times" reported could be misleading if the problem is specific to a very particular internal resource or process that isn't reflected in aggregate metrics, or if the process quickly restarts after a failure. It's also distinct from general unreachability (H3) and zone transfer issues (H2).

---

### STAGE 3 — INVESTIGATION PLAN (Round 2)

**For New Hypothesis 1: Intermittent Backend Dependency Failure on Authoritative DNS Servers.**

*   **What to check:**
    *   Review the application logs of all authoritative DNS servers (e.g., BIND, PowerDNS, NSD logs) for error messages related to internal data lookups, database connections, API calls, or configuration issues specific to `novaridge.example` or dynamic record resolution during the incident window.
    *   If applicable, inspect the health and performance metrics (e.g., latency, error rates, connection pool exhaustion) of any internal database, API, or IPAM system that the authoritative DNS servers query to retrieve record data for `novaridge.example`.
*   **Confirming finding:** Authoritative DNS server logs show intermittent errors such as "database connection failed," "API timeout," "failed to fetch record data," or similar messages for `api.novaridge.example`. Alternatively, monitoring of the backend dependency shows intermittent high latency, error rates, or unavailability coinciding with the reported SERVFAIL incidents.
*   **Ruling out finding:** Authoritative DNS server logs show no errors related to internal backend data retrieval, and all identified backend dependencies (databases, APIs, IPAM) for `novaridge.example` show stable, healthy performance within normal operating parameters throughout the incident duration.

**For New Hypothesis 2: Specific Authoritative DNS Server Process or Resource Exhaustion.**

*   **What to check:**
    *   Examine system logs (e.g., `syslog`, `journalctl`) and specific DNS daemon logs (e.g., `named` logs for BIND, `pdns_server` logs for PowerDNS) on *all* authoritative servers for any signs of intermittent process crashes, restarts, segmentation faults, or "out of memory" errors.
    *   Monitor granular resource utilization metrics for the DNS server process itself, specifically looking for spikes in memory consumption (RSS/VSZ), file descriptor usage, or thread/process count that might correlate with the intermittent SERVFAILs, even if overall system CPU/memory appear normal.
*   **Confirming finding:** Logs show evidence of intermittent crashes, restarts, or specific resource exhaustion messages (e.g., "out of memory for zone," "too many open files") within the DNS daemon processes. Alternatively, granular monitoring shows intermittent spikes in specific resource usage for the DNS process (e.g., sudden increase in file descriptors or memory) that coincide with the reported SERVFAIL incidents.
*   **Ruling out finding:** Logs show no evidence of DNS daemon crashes, restarts, or specific resource exhaustion errors. Detailed, process-level monitoring of memory, file descriptors, and thread/process count for the DNS server software shows stable utilization well within normal operating parameters throughout the incident duration.

---

## Stage 4 — Engineer Feedback (Round 2)

Pulled the DS record from the registrar and compared it against our current KSK hash, and they don't match. Looked into it further and there was a KSK rollover done about 5 weeks ago as part of routine key maintenance, but whoever did it apparently didn't push the updated DS record to the registrar afterward, so the registrar's been holding a DS record pointing at our old, retired KSK this whole time. Makes sense why it's intermittent too, depends on which resolvers cached the old chain of trust versus which ones are doing a fresh validation now.

---


## Stage 5 — Final Synthesis

**New Hypothesis 1: Intermittent Backend Dependency Failure on Authoritative DNS Servers.**
*   **Status:** INSUFFICIENT EVIDENCE
*   **Evidence:** The engineer's findings focused on DNSSEC records at the registrar and did not report on reviewing authoritative DNS server logs for backend errors or inspecting health/performance metrics of internal backend systems as specified in the investigation plan for this hypothesis.

**New Hypothesis 2: Specific Authoritative DNS Server Process or Resource Exhaustion.**
*   **Status:** INSUFFICIENT EVIDENCE
*   **Evidence:** The engineer's findings focused on DNSSEC records at the registrar and did not report on examining system/DNS daemon logs for crashes or monitoring granular resource utilization metrics as specified in the investigation plan for this hypothesis.

CONVERGENCE: LOOP REQUIRED
MISSING EVIDENCE: Data for investigating "Intermittent Backend Dependency Failure on Authoritative DNS Servers" (specifically, authoritative DNS server logs for internal backend issues and health metrics of backend dependencies) and "Specific Authoritative DNS Server Process or Resource Exhaustion" (specifically, system/DNS daemon logs for process errors or crashes, and granular resource utilization metrics for the DNS process) was not collected or reported.
EXHAUSTED HYPOTHESES: None.
NEXT CHECKS: The investigation plans for New Hypothesis 1 and New Hypothesis 2 should be executed. Additionally, the engineer's finding regarding the DNSSEC DS record mismatch is a critical discovery that appears to explain the observed symptoms and should be prioritized for verification and remediation.

HUMAN REVIEW REQUIRED — These findings must be reviewed and approved by a qualified engineer before any remediation is attempted.

---

## Stage 6 — Final Report

CAUSE:
The root cause of the intermittent SERVFAIL errors for `api.novaridge.example` was a mismatch between the Delegation Signer (DS) record published at the domain registrar and the current Key Signing Key (KSK) hash used for `novaridge.example`. A KSK rollover was performed approximately five weeks prior to the incident as part of routine key maintenance. However, the updated DS record corresponding to the new KSK was not submitted to the registrar, leaving the registrar with an outdated DS record pointing to the retired KSK. This broken chain of trust caused validating DNS resolvers to fail DNSSEC validation, resulting in SERVFAIL responses. The intermittency of the issue is explained by the fact that some recursive resolvers might have had valid, cached DNSSEC records from before the KSK rollover, while others were attempting fresh validation against the mismatched DS record.

EVIDENCE TRAIL:
- Customers and remote staff reported intermittent SERVFAIL / 'site can't be reached' errors for `api.novaridge.example`, ongoing for about 4 hours, spread across different, unrelated networks.
- The automated incident classification of "SERVFAIL rate spike" was confirmed.
- Initial checks confirmed that the Zone Signing Key (ZSK) and RRSIGs were valid and within their expiration period, ruling out ZSK issues.
- Authoritative servers reported normal CPU and response times with no traffic spike.
- Engineer confirmed by pulling the DS record from the registrar and comparing it against the current KSK hash, revealing they did not match.
- Further investigation uncovered that a KSK rollover occurred about 5 weeks prior, but the updated DS record was not pushed to the registrar.
- This discrepancy directly explains the intermittent SERVFAIL behavior, depending on resolver cache state and validation frequency.

REMEDIATION STEPS:
1.  **Immediate:** Update the Delegation Signer (DS) record at the domain registrar for `novaridge.example` to accurately reflect the hash of the current Key Signing Key (KSK).
2.  **Medium-term:** Conduct a thorough review of the KSK rollover procedure to identify and correct the process gap that led to the failure in updating the DS record at the registrar. Ensure clear steps for DS record propagation and verification are included.
3.  **Long-term:** Implement automated monitoring and alerting for DNSSEC chain of trust validation (including DS record matching at the parent zone) to proactively detect such inconsistencies after key rollovers or due to misconfiguration.

HUMAN SIGN-OFF: [ ] Reviewed and approved by: ___________ Date: ___________

---

*Generated by DDI Copilot Investigator — MVP v2.*
*Human review required before any remediation is attempted.*
