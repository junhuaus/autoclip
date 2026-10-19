## Subtitle calibration behavior

Subtitle correction is audio-grounded. When audio transcription/alignment tools
are available, inspect the candidate audio, compare the second-pass result with
the original cues, correct homophones, names, vocal terminology and sentence
breaks, and preserve the source timeline. Use `inspect_candidate_audio` first,
then `save_subtitle_revision`; the latter preserves cue IDs/times and computes
the explicit original-to-corrected diff.

Never rewrite for style, invent inaudible words or silently replace uncertain
audio. Keep an unresolved token unchanged and mark its local confidence when
the audio observation cannot support a correction. If no audio-grounded tool is
available, do not claim calibration; finish the clip candidate without a fake
subtitle revision. Evidence marked `mock_fixture` is test evidence and must
never be described as a real correction.
