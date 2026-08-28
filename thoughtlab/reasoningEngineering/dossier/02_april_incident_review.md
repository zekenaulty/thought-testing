# April service incident review

**Author:** County Services Cooperative site-reliability and incident-management team  
**Evidence base:** gateway telemetry, deployment records, incident bridge transcript, and sampled request logs  
**System visibility limitation:** no access to Legacy Benefits Core transaction internals or Treasury settlement internals  
**Date:** 22 April 2026

On 14 April, benefit authorization latency rose for six hours and fourteen minutes. Eastbank caseworkers saw repeated “pending” states, several county call centers retried work manually, and Treasury later identified duplicate provider payments. No complete end-to-end correlation exists, so this review describes the gateway boundary and does not apportion all downstream effects.

Between 08:00 and 14:30, Eastbank generated 3.7 times its ordinary hourly event volume. Much of the increase consisted of correction events following a policy-table update and a county workflow campaign to clear held cases. Gateway CPU remained below 61 percent and queue storage below 38 percent. Median gateway transform time stayed within its service objective. The queue of commands awaiting legacy acknowledgement, however, grew from an ordinary range of 1,100–2,400 to a peak of 46,280.

Legacy acknowledgement latency began degrading eighteen minutes before the Eastbank campaign reached its highest event rate. At 09:11, the 95th percentile crossed 90 seconds. At 09:24, the retry controller began treating a subset of timed-out legacy acknowledgements as transport failures. Of 8,412 automatically retried commands during the incident, 7,906 retained their gateway correlation identifier. The remaining 506 entered an older adapter that recreated the command after schema normalization and generated a new correlation identifier. That adapter had been enabled two weeks earlier to support a legacy correction path.

The review matched 81 percent of later duplicate-payment reports to commands that experienced at least one retry at the gateway. This association does not establish that the retry created the duplicate. A retried command could also be a consequence of a legacy transaction that committed before its acknowledgement was lost. For 19 percent of reported duplicates, no retry was visible under the gateway identifiers available to the team. Some may have traversed bypass feeds, used regenerated identifiers, or been caused downstream.

At 10:02, operators increased the legacy timeout to reduce retry pressure. Queue growth slowed but caseworker-visible latency increased. At 11:17, the Benefits Authority disabled one correction adapter. At 12:05, Eastbank paused its case campaign. The queue returned to its normal band at 14:14. It is not possible to isolate the effect of any one action because all three occurred while legacy response time was recovering.

The team found one gateway defect: the timeout-classification deployment allowed an ambiguous application acknowledgement to enter a retryable category. A corrected rule is ready. The team also found two architectural gaps outside its unilateral control: occurrence identifiers are not stable across every correction path, and gateway operations cannot determine whether an unacknowledged legacy command committed. The gateway can suppress exact transport duplicates when the same correlation identifier returns, but it cannot safely infer that two semantically similar commands are the same business occurrence.

The Cooperative recommends immediate correction of the timeout rule, end-to-end correlation, and a defined idempotency boundary. It does not recommend that the gateway become the authoritative eligibility or settlement ledger. It believes the incident can be contained without abandoning the Eastbank workflow, provided the other systems expose enough transaction state to distinguish safe retry from duplicate execution.

