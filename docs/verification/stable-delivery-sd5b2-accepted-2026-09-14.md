# SD-5 B2 accepted: durable CLI and Web observation

Status: **accepted for the bounded synthetic engineering contract** on
2026-09-14. The short-highlight and mini-lesson presets remain experimental;
this record does not establish SD-6 real Chinese content/audio, cloud or
distinct 2h/4h performance acceptance.

`liveclip auto VIDEO` now saves one idempotent versioned-preset Completion
goal and observes it while an independent `liveclip-worker` processes media.
It prints the caller/request key before create, supports `--no-watch`, and a
terminal interrupt only stops observation. `liveclip resume PROJECT_ID`
requires an exact intent when the Project has several goals, leaves manual
selection and exhausted retry history parked, and explicitly wakes only an
eligible `needs_action` through the version-fenced service. CLI and Web read
the same attempt-bound progress. Web reload recovers the confirmed goal
under current authority and does not show a ZIP until its bound Delivery
Asset commits. An unauthorized reader gets no goal or ZIP bytes.

Formal isolated successor `20260914T224719Z-804eeb92` reached `DONE` from
the 2309-path Main owner freeze. Its sole recorded Coder session
`01a0a21e-c01e-73c2-9a93-d6ffcac2fec3` changed only
`apps/web/e2e-real/completion-goal-real.spec.ts`, repairing a browser
navigation race while retaining final authorized UI and cookie-only download
assertions. Fresh Reviewer PASS had zero findings, Tester READY selected
only the checked-in fixed Runner IDs, and read-only Gateway PASS followed
the deterministic evidence precheck. Runner lint `20260914T225742Z-efa9`,
early e2e `20260914T225948Z-160c`, and full test
`20260914T230500Z-a9b9` all PASS. Full test ran **2425 Python tests**,
**78 Web tests**, Mock Chrome and two real-service Chrome scenarios.
The previous successor-11 full-test browser navigation failure remains
terminal BLOCKED and was not relabeled or published.

Independent source/Gateway/QA audit matched all 2309 candidate and sealed
assurance paths at fingerprint
`bc66adcd0e6853b4105e6719281526330aa9e6260f0e49d235dc3e1eea837aa4`.
For both early e2e and full test, an independent retained-artifact audit
verified the legacy Completion and B2 browser fixtures separately. The B2
fixture showed browser-visible Delivery work counts 1/4 and 2/4 across
reload/navigation, then one signed ZIP; each B2 run retained 22 Assets and
28 evidence files. The legacy fixture retained 16 Assets and 21 files.
SQLite/Asset producer lineage, unchanged source, ZIP/member hashes,
credential-free retained text, full MP4 decode, removed disposable fixture
and rejection of a wrong existing producer attempt all passed. The current
synthetic MP4 is byte-identical to previously opened 360×640 high-contrast
color-pattern frames; it is not real content/audio review. Local ignored
audit receipts are under `.loop/development/sd5b2-observation-20260914/`:
`sd5b2-successor12-independent-done-source-receipt.json`,
`sd5b2-successor12-current-artifacts-audit.json` and
`sd5b2-successor12-synthetic-visual-inspection.json`.

Trusted CAS publication matched the original 503-path accepted B1 code
map, then atomically published exactly **22** reviewed code/test paths
(**7** new). The resulting 510-path original code map matched the accepted
sealed source. The three formal QA requests/results were appended to the
original append-only logs. Separate document CAS published README, Product
Spec, Solution, API, MLX/recovery guides and ADR048. Original postpublication
lint `20260914233622Z-09a1` PASS, 133 focused Python tests
`20260914233646Z-33bf` PASS, 18 Web tests `20260914234328Z-306d` PASS,
product Doctor `20260914234349Z-3478` READY with the known FFmpeg text-filter
fallback, Demo `20260914234410Z-3c86` PASS and loop Doctor
`20260914234523Z-7e5f` READY. Demo generated three candidates, an
independently decoded 1080×1920 H.264/AAC master, inspected synthetic
contact sheet and ZIP with valid CRC/four member checksums. Original QA now
has 1030 unique request IDs and matching reports plus one historical
supplemental report section.

The supplied read-only `input/8-30.ts` is about 110m34s and cannot satisfy
the distinct 2h or 4h cases. A current local ASR sample, bounded real Codex
editorial check, human labels/listening, real source-to-delivery trials and
long-input performance remain SD-6 work. The old OpenRouter key exposed in
chat is excluded even if local Doctor sees an OpenRouter configuration.
