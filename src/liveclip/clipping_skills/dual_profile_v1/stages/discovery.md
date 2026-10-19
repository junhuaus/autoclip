# Stage: Discovery

Scan every supplied cue in the window for high recall. Emit zero or more potential candidates whose
start cue begins inside the half-open `ownership_interval`; the end may extend through the rest of the
context. Do not score, Top-N, semantically deduplicate or reject by risk. Give the natural continuous
boundary, evidence cues, boundary continuation facts, quality observations and risk evidence. If an
otherwise valuable topic touches a context edge or is unfinished, report that fact; never silently
truncate it or manufacture closure.

Boundary cues carry meaning. Include the initiating question, numbered-step marker or explicit premise
when it is needed to understand the answer. Include the final comparison, conclusion, acknowledgement
or brief “OK” when it closes the unit. Conversely, exclude earlier setup once the first direct method
statement is independently understandable. Brief microphone/distance words that directly enable an
immediate vocal demonstration are part of that demonstration, not unrelated duration padding.

For a live diagnosis, include the first meaningful evaluated singing/example cue, the diagnosis and
correction loop, the before/after evidence, the final actionable recommendation and its natural closing
exchange. Exclude invitations and setup before the evaluated sample. For a risk enumeration, include
the opening that states the list and the full analyzed claim chain, rather than discovering only one
safer subclaim.
