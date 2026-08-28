# Eastbank pilot outcomes memorandum

**Author:** Eastbank Human Services transformation office  
**Co-signed by:** Eastbank caseworker operations council  
**Evidence base:** pilot service metrics, staff survey, case audit, and post-incident recovery log  
**Date:** 9 May 2026

Eastbank moved approximately 28 percent of network caseload onto the New Case Platform over three cohorts. The pilot changed the caseworker workflow while leaving production eligibility and payment authorization in the Legacy Benefits Core. It therefore demonstrates that the new casework product can operate at meaningful scale, but it is not evidence that the replacement rules and payments service is production-ready.

Across the twelve weeks before the April incident, median intake handling time fell by 31 percent relative to Eastbank’s prior workflow. Abandoned applications fell from 8.4 to 5.9 percent, and the share of corrections represented as structured events rather than free-text notes rose from 46 to 88 percent. Staff survey results favored the new workflow for ordinary cases, especially when applicants changed documents or household composition before determination.

The same structured correction behavior increased event volume. A case that previously accumulated three notes and one final legacy update may now create several explicit events. Eastbank considers that increased visibility a benefit, but the program never established which events should remain revisions and which should become new business occurrences downstream. The pilot acceptance suite evaluated correct final eligibility results more often than repeated delivery, delayed acknowledgement, or long correction chains.

During the April incident, caseworkers saw “pending” states after saving corrections. Some reopened the task, made a harmless edit, and submitted again because the operating guide did not explain whether the first action was durable. The locally commissioned workflow extension created a new event in that sequence. Eastbank accepts that the extension was not included in the contracted acceptance baseline. It notes that the extension appeared in two architecture inventories and was built to compensate for an unresolved status-design issue raised during pilot testing.

Technical export tests recovered 99.1 percent of required structured case fields from the New Case Platform into a format that the legacy intake loader could ingest. That result has sometimes been described as “rollback readiness.” The export did not preserve work-queue ordering, local annotations, document-review state, every event relationship, or the exact staff assignment history. Restoring Eastbank to the former workflow would therefore require manual triage and would lose operational context even if case facts were transferred successfully.

After the incident, thirty-eight staff members spent nine working days reconciling pending and repeated actions. Twelve of them remain assigned to manual comparison between platform, legacy, and Treasury states. This labor helped stabilize service and may partly explain favorable post-incident accuracy. It is not a sustainable substitute for defined transaction semantics.

Eastbank opposes an immediate broad migration while the correction boundary remains unresolved. It also opposes treating pilot rollback as a costless safety action. It would support continued containment of its current cohort, interface correction, or controlled shadow evaluation. It would consider additional migration only if the operating status shown to caseworkers corresponds to an end-to-end state and if correction, retry, and reversal behavior are tested under production-like sequences.

