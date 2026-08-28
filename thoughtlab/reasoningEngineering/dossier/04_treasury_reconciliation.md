# Treasury reconciliation analysis

**Author:** North River Treasury controller and payment analytics unit  
**Evidence base:** settled-payment ledger, reversal ledger, provider reports, and manual review of sampled authorizations  
**Boundary limitation:** identifiers do not map cleanly through every legacy and bypass path  
**Date:** 3 May 2026

Treasury confirmed 1,184 excess provider settlements associated with the April incident window. Each was linked by manual review to an earlier settlement judged to represent the same benefit obligation. The 1,184 excess settlements represent 0.71 percent of the 166,761 provider-settlement instructions initiated during that period. The count excludes suspected repeats blocked before settlement and excludes household payments, which use a different rail.

Of the 1,184 linked excess-settlement pairs, 742 shared a recognizable household, provider, service period, and amount but arrived with different authorization identifiers. Another 318 shared an authorization identifier but arrived as distinct payment instructions. The remaining 124 required manual linkage because one member of the pair came through a provider-adjustment batch feed. The gateway operations team could match at least one visible retry to 959 cases, but Treasury found 225 cases for which the available gateway record showed one event identifier or no gateway path.

The 225 cases weaken a gateway-only account. They do not prove that Treasury generated duplicates independently. In several legacy paths, a regenerated authorization identifier can obscure the relationship to an earlier gateway command. Treasury also found that its own settlement interface treats a changed authorization identifier as a new obligation unless an explicit reversal reference is present. That rule is consistent with the current interface specification but may be unsafe when upstream systems regenerate identifiers during correction.

Duplicate and reconciliation problems predate the Eastbank pilot. During the preceding six months, Treasury identified an average of 37 duplicate or conflicting provider settlements per month, mostly associated with retroactive corrections and the three bypass feeds. The April rate was far higher, but the pre-existing cases show that the mixed transaction model was not sound before migration. Historical counts are incomplete because providers do not always report small duplicate payments promptly and automated matching improved in February.

Treasury’s manual sample overrepresents completed settlements. Reversed and rejected transactions are less likely to appear because the analytics extract is keyed to the settled ledger. The team therefore cannot estimate how often gateway retries were safely absorbed upstream or how many attempted duplicates were prevented. It also cannot determine whether a legacy transaction committed before an acknowledgement timeout.

Treasury requires that any recovery architecture preserve settlement finality, support an explicit correction and reversal chain, and prevent a county workflow from silently redefining an already settled obligation. Treasury can accept delayed authorization during controlled degradation for up to twenty-four hours if emergency cases have a manual route. It cannot accept a design that reconciles duplicates only after providers receive funds as a normal operating pattern.

The controller is open to a temporary reconciliation service or parallel validation, but Treasury will not treat a shadow ledger as authoritative without a Council-approved legal and accounting basis. The unit has four analysts who can support transition work for six months; two are already assigned full time to incident reconciliation. Treasury regards restoration of end-to-end correlation as necessary under every long-term platform choice.
