# Limited independent assurance review

**Author:** Halden & Rowe Assurance  
**Commissioned by:** Joint Recovery Council  
**Scope:** six weeks; architecture and control review, 240 sampled cases, 17 interviews, and available telemetry  
**Date:** 28 May 2026

The review found no evidence sufficient to assign the program’s failure to one component or organization. It identified several cross-boundary weaknesses: transaction meaning changes between systems, correlation is incomplete, acceptance evidence omits important production sequences, and decision rights for semantic changes are unresolved. These weaknesses could amplify or misclassify more than one possible initiating failure; the available evidence does not show that they all contributed equally to the April incident.

The April duplicates could plausibly originate or become irreversible at at least three boundaries. A gateway retry can repeat a command when the legacy commit state is unknown. The legacy core can create a fresh authorization identifier during a correction path. Treasury can settle a changed identifier as a new obligation when it lacks a reversal reference. Available records cannot apportion the 1,184 confirmed duplicates among these mechanisms. The mechanisms are not mutually exclusive.

The reviewers traced 240 sampled Eastbank cases selected across ordinary intake, document correction, household change, timeout, and provider adjustment. End-to-end linkage was complete for 142 cases. Of the remainder, 61 lost the platform occurrence identifier at or before the legacy boundary, 23 used a bypass feed, and 14 had inconsistent timestamps that prevented confident ordering. The sample was intentionally enriched for complex corrections and therefore cannot estimate network-wide incidence.

Acceptance testing was strong for ordinary final determinations and weak for temporal and semantic behavior. The contracted scenario list reports high passage, but it underrepresents delayed acknowledgements, multiple corrections before settlement, reversal followed by reauthorization, and concurrency between a caseworker edit and a policy-table change. Several tests assert identical final amounts while ignoring whether two payment obligations were created on the way to that amount.

The governance model distinguishes program policy, local workflow, shared interfaces, and settlement control, but the modernization program repeatedly made decisions that crossed those categories. The Council approved an “event standard” without deciding whether it governed county occurrence identity. Eastbank approved a workflow extension without recognizing its effect on shared retry semantics. Tern accepted an interface while reserving exclusions for local customizations. No standing body owned the combined semantic consequence.

The replacement service showed promising determination agreement in the shadow evidence reviewed, but production exception coverage and payment behavior remain incomplete. The legacy core remains operationally indispensable but contains undocumented transaction behavior and approaching support risks. The review therefore does not certify replacement readiness, recommend rollback, or endorse indefinite continuation of the current mixed design.

The Council should require proposed recovery courses to explain how transaction state will become observable across relevant boundaries, how corrections and reversals will be represented, how production-like sequences will be tested, and who may authorize changes whose effects cross organizations. Proposals should also explain how unresolved causation will be reduced or safely bounded during transition. The assurance work did not compare complete recovery courses or determine a long-term product arrangement.

Limitations are material. Legacy transaction logs were unavailable for two of the three relevant code paths. Treasury reversal sampling was incomplete. The review did not render a legal opinion, independently price alternatives, or test the replacement service under peak production mix. Findings should be used to construct and test a recovery course, not treated as a complete root-cause verdict.
