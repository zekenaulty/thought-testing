# Shared-service current-state architecture, revision 4

**Author:** cross-organization architecture working group  
**Sign-off:** accepted by County Services Cooperative and North River Treasury; North River Benefits Authority and Eastbank Human Services accepted the topology but left semantic annotations unresolved  
**Date:** 6 May 2026

The North River Benefits Network does not have one system of record for every stage of a case. Participating counties create and steward household facts, evidence, and caseworker annotations. The Benefits Authority determines eligibility under statewide rules. Treasury owns the settled-payment ledger. The phrase “system of record” has nevertheless been used in program material as if it referred to one product, producing disputes that are partly technical and partly institutional.

For non-pilot counties, case actions enter the Legacy Benefits Core directly. The core applies eligibility rules, assigns or reuses a household identifier, creates an authorization, and places an outbound record into an internal queue. The Shared Integration Gateway transforms that record into a payment instruction for Treasury and sends status events back to county systems. Three older batch feeds bypass the gateway for provider adjustments, retroactive corrections, and end-of-month reconciliation.

Eastbank caseworkers work in the New Case Platform. The platform sends case changes and correction events to the gateway. The gateway transforms them into commands understood by the Legacy Benefits Core, which remains the production eligibility engine. The resulting authorization then returns through the gateway to Treasury. A replacement rules and payments service exists in test environments but is not authoritative in production. During limited shadow periods it has evaluated copied case data without initiating payments.

The modernization design assumed that every business occurrence would have one stable occurrence identifier across the New Case Platform, gateway, legacy core, and Treasury. In practice, the platform always assigns an event identifier, but some correction workflows create a new event for what an operator regards as the same business occurrence. The gateway creates a correlation identifier for each received event. The legacy core does not persist either identifier in every transaction path. Treasury retains the gateway correlation identifier when it is present but also assigns a settlement identifier. The bypass feeds use different keys.

Acknowledgement meaning is also inconsistent. To the New Case Platform, an accepted gateway request means that the gateway has durably received it. To the gateway operations team, an accepted legacy response means that the legacy core has accepted a command. In two legacy paths, that response can precede final database commit. Treasury acknowledgement means that a payment instruction passed syntactic and account checks, not that it settled exactly once. Program documentation sometimes calls all three states “processed.”

The intended correction lifecycle is contested. Eastbank treats a caseworker correction as a revision of an earlier occurrence until the eligibility result changes. The Benefits Authority treats any rule re-evaluation that changes an authorization as a new determination. Treasury treats a changed amount after settlement as a reversal plus a new settlement. No cross-system specification states where a revision must stop being a revision and become a new authorization.

The gateway has configurable retry policies. Network failures are retried with the original gateway correlation identifier. Legacy timeouts are retried with that identifier but may reach a legacy path that generates a fresh internal transaction key. Application rejections are not supposed to be retried automatically. Before the incident, a deployment changed one timeout classification so that an ambiguous legacy response entered the network-failure path.

Unresolved annotations remain on four diagrams: the authoritative boundary for a corrected eligibility decision; the owner of the occurrence identifier; whether the gateway may suppress a command when it suspects a duplicate; and whether Treasury or the Benefits Authority has final authority to classify a payment as a correction rather than a new obligation.

