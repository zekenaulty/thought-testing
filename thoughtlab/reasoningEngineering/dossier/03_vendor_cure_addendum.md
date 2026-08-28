# Root-cause and remediation addendum

**Author:** Tern Systems engineering and account leadership  
**Contractual context:** submitted under the program’s cure process; disputed liability may affect fees and milestone payments  
**Date:** 30 April 2026

Tern Systems reproduced the April retry sequence against the contracted New Case Platform configuration. When a stable business-occurrence identifier is supplied, the platform retains it across ordinary submission, correction, timeout recovery, and user refresh. Its supported gateway connector also retains the identifier. Under those conditions, repeated deliveries are distinguishable and the replacement rules service produces the same determination for the same occurrence and rule version.

The Eastbank tenant included a locally commissioned workflow extension that creates a fresh correction event when a caseworker reopens a queued task after an external status timeout. Tern did not approve this extension as part of the production baseline. In a sample of 12,640 Eastbank correction events from 1–14 April, 8.6 percent lacked the original business-occurrence identifier after passing through that extension. The extension was visible in an integration inventory, but no acceptance test exercised a timeout followed by reopen and correction.

Tern also identified an error in its supported connector defaults. The default backoff for a missing application-level acknowledgement was shorter than the deployment guide specified and allowed two additional attempts during the legacy core’s degraded response window. Tern has supplied a patch and will waive the related connector support charge. The company does not agree that this defect alone explains the duplicate settlements: most affected commands still carried a stable gateway correlation identifier, and Treasury reported duplicates for cases where Tern saw only one platform event.

The vendor’s position is that the present partial architecture preserves incompatible transaction semantics. The New Case Platform describes intent and correction history; the legacy core collapses some revisions into new authorizations; Treasury reasons over settlements. The gateway is being asked to infer equivalence after information has already been lost. Adding more retry rules at that boundary can reduce recurrence but cannot establish exactly-once business behavior.

Tern proposes accelerating the Replacement Rules and Payments Service so the New Case Platform and replacement service share occurrence, determination, and payment semantics. It estimates that core contracted rule coverage can be production-ready within seven months if rule clarification, test data, and Benefits Authority subject-matter experts are available on schedule. That estimate excludes several low-volume exception rules, provider recoupments, and two court-ordered manual processes. Those could remain on the legacy core temporarily or be handled through controlled operations.

The company notes that Eastbank’s pilot improved intake throughput and captured corrections that the old workflow often represented as free-text notes. It argues that the 3.7-fold event increase reflects previously hidden work as well as campaign volume, not merely inefficient software. A rollback would therefore reduce event volume partly by losing structured information.

Under the current agreement, Tern receives milestone fees for production cohorts and may negotiate a price adjustment if the mixed architecture continues beyond the contracted transition period. It will support data export and termination assistance if the Council chooses another course, subject to the limits described in the contract extracts.
