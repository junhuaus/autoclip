# ADR-021: Treat ordinary review as selection and make Delivery browsable

Status: accepted

Date: 2026-08-18

## Context

The review board exposed two independent checkbox systems (“批量审核” and “选择导出”), separate approve/reject buttons, a mandatory rejection reason and a later Delivery action. The user clarified that this is unnecessary ceremony: rendered clips only need to be selected or omitted, their score must remain editable, and the selected set must export together in the previously established `index.html` package form.

The durable `ReviewDecision` and `approved` eligibility state are already embedded in Delivery, release and compatibility contracts. Replacing those records would require a broad migration without changing the ordinary keep/discard meaning.

## Decision

The Web presents one “选入交付” control. Selecting writes the compatible `approved` decision; clearing writes `rejected` with a system-owned bounded reason rather than asking the user to justify omission. UI labels describe `approved` as selected and all other current states as unselected. The atomic batch endpoint remains the persistence boundary for one or many selection changes.

Score becomes an allowed field in `ClipPatch`. It creates an immutable human EditPlan revision just like other editorial changes and is bounded to 0–100. Existing revision, render and Delivery fences remain unchanged: the new revision must have its own current clean master before it is deliverable.

New formal Delivery versions add deterministic `index.html` and `checksums.sha256` members. The HTML is file-only, CSP constrained, contains no external resources or executable editorial content, and references only system-generated relative MP4/SRT names. These members participate in the same pinned-file, hash, ZIP and immutable-publication validation as existing media and manifest members. Historical Delivery versions remain byte-for-byte unchanged.

## Consequences

The ordinary path becomes: inspect or edit → select keepers → create webpage Delivery. There is one visible selection state and one export action. Backend compatibility and old API clients continue to work, while the Web no longer exposes approval/rejection terminology for content selection.

Changing only a score currently advances the EditPlan revision and invalidates the old master, even though the clean video pixels are unchanged. This favors one uniform immutable revision fence over an in-place metadata exception; a future separately versioned editorial-ranking model may remove that render cost if real usage justifies the added state.
