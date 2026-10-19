# Structured repair

Repair only schema or explicitly reported deterministic validation errors. Preserve every candidate and
all valid source evidence. Do not invent cue IDs, alter the requested Profile, hide risky candidates,
weaken quality flags, change a valid final boundary, or add candidates merely to reach a count. Return
only one complete replacement JSON object matching the requested strict schema.
