# Editor handoff and short-video platform research

Checked: 2026-08-13

This research constrains LiveClip v0.2 export design. Only primary vendor documentation is used for normative compatibility claims.

## Jianying / CapCut subtitle handoff

CapCut's current help states that Desktop and Web can import external subtitle files. Desktop accepts SRT or timecoded TXT; Web accepts SRT. Imported cues become synchronized editable text layers. It recommends UTF-8 for multilingual text. The mobile app does not directly import SRT/TXT; the documented workaround is importing on Desktop/Web and syncing the Project to mobile.

Source: [CapCut — How Do I Import Subtitles?](https://www.capcut.com/help/how-to-import-subtitles)

Another current CapCut help article recommends SRT/TXT for caption export, UTF-8 without BOM and conservative English/ASCII paths when troubleshooting path/encoding failures.

Source: [CapCut — Why Do the Captions Fail to Export?](https://www.capcut.com/help/captions-fail-to-export)

Decision: LiveClip's first Jianying-compatible contract is a clean H.264/AAC MP4 paired with a basename-matched, clip-relative, plain UTF-8 SRT, plus a short Chinese import guide and optional ASCII aliases. We do not claim direct mobile import. We do not generate undocumented Jianying native draft data.

## General upload master

YouTube recommends MP4, H.264 High Profile progressive video with 4:2:0 chroma, AAC-LC/Opus audio, native frame rate, BT.709 for SDR, and a front-loaded `moov` atom (“Fast Start”). For 1080p SDR at ordinary frame rate it lists 8 Mbps as a reference video bitrate, not a strict maximum.

Source: [YouTube — Recommended upload encoding settings](https://support.google.com/youtube/answer/1722171)

Decision: the generic/platform export validator checks MP4/H.264/AAC, progressive portrait dimensions, yuv420p-compatible pixel format, audio sample rate, duration, full decode and fast-start. Exact bitrate is a versioned preset rather than a global hardcoded truth.

## YouTube Shorts and captions

YouTube currently categorizes square or vertical uploads up to three minutes as Shorts for standard channels under its published eligibility rules. A Short over one minute with an active Content ID claim is globally blocked. YouTube recommends plain UTF-8 SRT as a basic caption format and supports timed caption-file upload.

Sources: [YouTube — Understand three-minute Shorts](https://support.google.com/youtube/answer/15424877), [YouTube — Supported subtitle files](https://support.google.com/youtube/answer/2734698), [YouTube — Add subtitles and captions](https://support.google.com/youtube/answer/2734796)

Decision: the Shorts preset permits at most 180 seconds but adds a visible music/rights warning above 60 seconds. Separate SRT remains useful even when an optional delivery master burns captions.

## TikTok developer transfer constraints

TikTok's official Content Posting API transfer guide recommends MP4/H.264, accepts 23–60 fps, requires both dimensions at least 360 pixels, permits up to 4096 pixels per dimension, documents a 4 GB maximum, and says the API initialize endpoint accepts up to 10 minutes while actual creator entitlement can be shorter.

Source: [TikTok for Developers — Media Transfer Guide](https://developers.tiktok.com/doc/content-posting-api-media-transfer-guide)

Decision: a TikTok export preset can validate conservative file properties, but LiveClip must not promise an account-specific maximum without querying an authorized account. Direct posting remains a later integration with explicit user authorization.

## Professional interchange beyond Jianying

Apple documents FCPXML as an interchange format for describing media assets, editing decisions and metadata exchanged with Final Cut Pro. Current documentation describes FCPXML documents/bundles and the resources/event/project structure.

Sources: [Apple — FCPXML reference](https://developer.apple.com/documentation/professional-video-applications/fcpxml-reference), [Apple — FCPXML root element](https://developer.apple.com/documentation/professional-video-applications/fcpxml)

Decision: FCPXML is a credible later professional interchange target after the simple MP4/SRT handoff, but it is not used as a substitute for Jianying compatibility and is deferred until its generated timeline can be imported and visually verified in Final Cut Pro.

## Unverified or intentionally excluded

- No stable public Jianying native draft/project interchange schema was found in primary documentation used for this decision.
- Instagram/Reels and China-specific platform limits must be rechecked against accessible primary documentation immediately before implementing those presets; v0.2 planning names them but does not freeze unverified numeric limits.
- Automatic posting, browser upload automation and storage of social-platform credentials are excluded from the first v0.2 release.
