# ADR 034: Offline Runner tokenizer assets and scoped process cleanup

Status: proposed, separately bounded engineering prerequisite, 2026-09-12.

Run20260912T165201Z-1e2ea95c froze unchanged source/dependencies and passed lint,
but tests produced44 failures/1043 passes. The isolated TMP cache lacks tiktoken's
public o200k data, causing forbidden network attempts. Self-only signals prevent
the existing timeout/cancellation handlers from terminating their own groups.

Trusted `make setup` prepares cl100k_base/o200k_base from two static HTTPS URLs.
The SHA-256 pins match the locked tiktoken0.14.0 definitions. Responses are bounded,
redirects rejected, and only verified bytes are published without replacement.
Invalid existing assets are preserved for diagnosis. Readiness only checks bytes;
it cannot fetch, repair or run the SDK loader. `.cache/tiktoken` joins the sealed,
fingerprinted toolchain. Runner sets TIKTOKEN_CACHE_DIR to that frozen directory;
ordinary Make commands default to the project cache. No dependency lock changes.

Seatbelt signals change from target self to target same-sandbox. Descendants
inherit that sandbox, allowing existing group cancellation while unrelated host
processes remain inaccessible. This primitive is also used in the primary
[OpenAI Codex Seatbelt policy](https://github.com/openai/codex/blob/main/codex-rs/sandboxing/src/seatbelt_base_policy.sbpl).
An actual authority probe must demonstrate child and orphaned-group cleanup,
foreign signal denial, and the retained file/QA/credential/network boundaries.
No executable command IDs, Coder authority, role profiles or retry limits change.

Recovery: preserve old runs/snapshots and any corrupt assets; fix trusted setup in
a new bounded task before a new run. No Runner network fallback or broad signal
grant is allowed. Review and deterministic diagnostics are not five-role acceptance.

Scope extension: captured output truncation must produce Runner ERROR even for exit0. The previous million-byte failure tail exposed a missing check in Runner, although role capture already rejected truncation. Add a correlated Runner/Gateway regression; retain the existing cap and schema.


## Browser runtime follow-up

Actual diagnostic Run20260912T170850Z-3fdd7dcf preserves source/toolchain and passes
lint,1095 Python tests and58 Web tests. Browser E2E then fails Chrome startup.
Fixed synthetic probes isolate the following additional necessities:

1. macOS Chromium uses MAC_CHROMIUM_TMPDIR (not TMPDIR) before NSTemporaryDirectory;
   override it to the existing per-command private scratch. The primary source is
   [file_util_apple.mm](https://chromium.googlesource.com/chromium/src/+/refs/tags/146.0.7680.180/base/files/file_util_apple.mm).
2. Chrome's SingletonSocket needs AF_UNIX bind/connect only below that scratch.
   Permit system-socket AF_UNIX and local/remote Unix subpath filters, matching the
   path-scoped primitive in [Codex seatbelt.rs](https://github.com/openai/codex/blob/main/codex-rs/sandboxing/src/seatbelt.rs).
3. Chrome84304's own crash report identifies IONotificationPortGetRunLoopSource;
   permit only RootDomainUserClient for system power notifications, as in the
   [restricted defaults](https://github.com/openai/codex/blob/main/codex-rs/sandboxing/src/restricted_read_only_platform_defaults.sbpl).
   No other IOKit/GPU/device permission is granted.
4. Standard multiprocess Chrome requires bootstrap_check_in. Match only anchored
   `com.google.Chrome.MachPortRendezvousServer.[0-9]+` global service names.
   This is a name-namespace restriction, not caller-PID equality; the fresh reviewer
   must assess this distinction. No blanket registration or browser single-process
   workaround. The implementation is in Chromium's base/apple/mach_port_rendezvous_mac.cc.

Browser probe QA20260912171849Z-52aa actually launches, reads page title/text and
closes Chrome in this sandbox. QA20260912171927Z-5c26 verifies20 real observations:
private Unix exchange succeeds; an actual owned host Unix listener is inaccessible;
unrelated Mach registration returns1100; the probe's own Chrome-form service succeeds;
all prior source/QA/private HOME/credential/network/foreign-signal limits remain.
Personal Chrome Crashpad reads stay denied and were not made a permission exception.

The first review's P3 concurrency test gap is addressed by valid and corrupt winners
created immediately before os.link; winner bytes are preserved and downloads removed.
All failed startup probes remain in parent receipts with exact fixed-script hashes.


## Residual authority and recording dependency

The independent review01a096a3 identified a P3 documentation gap. The anchored Mach
rule permits reserving another PID's currently unregistered Chrome-form service name
in the accessible bootstrap namespace. Untrusted command descendants could squat on
such names and disrupt another Chrome startup. It does not provide caller-PID
isolation. A synthetic non-existent PID-form registration observation is required;
never target a real browser. Same-sandbox signals likewise allow descendants of this
command to interfere with one another. RootDomainUserClient permits that kernel
interface, not only notification methods. These residual capabilities are recorded
explicitly; the bounded reviewer passes them with these limits, not as a claim of
perfect isolation. Arbitrary Mach service names, foreign Unix sockets and unrelated
process signals remain denied. No broad IOKit or Mach registration rule is added.

Actual full dc38 advances through1097 Python,58 Web and1 mock browser E2E pass;
real-backend recording requires Playwright's own ffmpeg1011 helper. Trusted setup
runs the locked project's Playwright CLI to install only that helper in
`.cache/playwright`. Runner reads its sealed, fingerprinted cache using a forced
PLAYWRIGHT_BROWSERS_PATH. Readiness requires the locked macOS helper path to be a
regular executable within the project. Changing Playwright's helper revision in a
future lock update requires reviewing that readiness path. No test recording is
removed, no personal cache is read, and Runner never downloads the helper.

The actual21-observation receipt `sandbox-probe-20260912T172844Z` confirms the synthetic2147483647 Chrome-form name can be registered after a host check verifies no such process exists. Its port is destroyed immediately. This is recorded as an allowed residual capability, not a security denial. Actual recording receipt `video-probe-20260912T172833Z` retains a nonempty hashed WebM. No personal browser or real-media input was used.
