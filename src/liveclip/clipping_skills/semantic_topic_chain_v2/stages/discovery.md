# Discovery

Return a V5 Discovery batch with unchanged batch context, ownership and logical windows.
Record a proposal only when its start cue belongs to the half-open ownership interval.
Preserve fragment, topic, window and boundary references. Evidence must cite known cues.
Open boundaries identify related fragments/candidates and the unfinished objective.

Propose all potentially valuable material, including risky topics and originals whose
possible_profiles do not include mini_lesson. No score threshold, Top-N, duration gate
or publication-risk rejection belongs in Discovery. Use typed risks instead of a free
string risk_flags channel: each risk has a unique local risk_id within its proposal,
an existing RiskFlagV4 flag, a nonempty reason and nonempty known evidence_cue_ids.
Several independently evidenced risk IDs may have the same flag. Preserve them all.
The trusted namespacer/attributor owns global provenance; do not invent attributed IDs.
