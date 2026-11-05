# TapeGrade: a focused scouting workspace

## Summary

Initial audit before this redesign: **Needs work**. The previous pass improved legibility and keyboard access, but its presentation still emphasized dashboard furniture over the work. TapeGrade is for a fantasy basketball manager who wants to inspect a player’s film and understand a supported roster decision. Its defining element is the actual annotated film; the application frame should be quiet.

This is a React browser application. Apple's hierarchy, accessibility, interaction, and writing principles apply; native Apple navigation APIs and menu-bar requirements do not.

## Improvements

- **High — Too much interface before the evidence.** The toolbar, page title, slogan, team cards, new-scan card, source line, and report heading precede the film. `design-principles.md › Agency`: “Stay out of the way.” Replace these with a compact page toolbar and one contextual report header.
- **High — A report is fragmented into cards.** Player list, film, global recommendation, tracking audit, and exports have competing boxed headers. `split-views.md › Best practices`: “To support navigation, persistently highlight the current selection in each pane that leads to the detail view.” Give the list a stable leading pane and the selected player a clear detail pane; show the whole-scan move below the film.
- **High — Setup overload.** League setup shows data ingestion, scoring rules, athlete mapping, eligibility evidence, and game logs together. `layout.md › Visual hierarchy`: “Use progressive disclosure to make layouts cleaner and easier to interact with.” Introduce keyboard-accessible section tabs while retaining each task and its state.
- **Medium — Large controls repeat small amounts of information.** Remove rank decorations, initial avatars from candidate navigation, repeated section icons, decorative court imagery, the footer slogan, and sidebar advice. `design-principles.md › Simplicity`: “Include just what’s necessary.” Keep player names, verdicts, confidence, statistics, and explicit provenance.
- **Medium — Form consistency.** Roster, settings, film upload, and league setup need one system for labels, helper text, controls, and actions. `lists-and-tables.md › Content`: “Keep item text succinct so row content is comfortable to read.” Use grouped rows, restrained dividers, and aligned form controls.
- **Medium — Interaction polish.** Retain visible focus, Escape dismissal, focus restoration, and reduced-motion handling; add brief page transitions and clear control press states. `motion.md › Best practices`: “Add motion purposefully, supporting the experience without overshadowing it.”

## What works

Keep the existing workflows and identifiers, backend requests, readiness checks, real/demo provenance, film overlay/timeline/fullscreen, unavailable measurements, critic assessments, watchlist controls, protected players, scheduling, and report downloads. Keep the distinction between the selected athlete and the scan-level move. Keep system appearance and enlarged-text support.

## Design system

Six roles, with contrast computed against the primary surface:

| Role            | Light   | Dark    | Light ratio | Dark ratio |
| --------------- | ------- | ------- | ----------- | ---------- |
| Canvas          | #f5f5f7 | #161617 | —           | —          |
| Surface         | #ffffff | #1c1c1e | —           | —          |
| Content         | #1d1d1f | #f5f5f7 | 16.83:1     | 15.63:1    |
| Secondary       | #6e6e73 | #a1a1a6 | 5.07:1      | 6.61:1     |
| Action/link     | #0071e3 | #64a8ff | 4.70:1      | 6.96:1     |
| Positive signal | #287348 | #85cda0 | 5.78:1      | 9.10:1     |

Filled primary actions use #0071e3 with white labels in both modes. Error and caution roles have separate adaptive tokens and always include a text label. Dividers provide grouping rather than text contrast. The toolbar is solid by default; a restrained translucent enhancement applies only where reduced-transparency preferences permit it.

Typography: platform system sans; 20px toolbar title, 32–40px first-run task heading, 26px selected-player heading, 17px section titles, 15px body, 13px supporting text and 12px metadata. Use rem, tabular numerals for data, and monospace only for timecodes. No imported display face is needed for a working tool.

Spacing: 4/8/12/16/24/32/48px. Controls: 36px minimum on desktop and 44px for coarse pointers or compact screens. Corners: 6px controls, 10px grouped surfaces, 12px media. Surfaces have delicate borders; only temporary layers receive a meaningful shadow.

```text
Regular
+---------------+-------------------------------------------+
| TapeGrade     | Scouting desk                 Connection  |
| League        +-------------------------------------------+
| Scouting desk | Report mission / source        New scan   |
| My roster     +-------------+-----------------------------+
| Film library  | Players     | Selected athlete + verdict  |
| Scan history  | name / team | Film + playback controls    |
| League setup  | result      | Measurements                |
| Guardrails    |             | Scan recommendation         |
|               |             | Tracking audit / downloads  |
+---------------+-------------+-----------------------------+
Compact
+------------------------------------+
| Menu   Scouting desk    Connection  |
| Report / new scan                  |
| Players (compact rows)             |
| Selected film                      |
| Measurements / recommendation      |
| Tracking / downloads               |
+------------------------------------+
```

Plan critique: the subject-specific identity lives in the film, measured observations, and honest scouting decisions. Adding a court illustration or editorial slogan would repeat the subject without helping the manager act, so both are removed. The app should feel like a useful, familiar desktop tool. On compact screens the same navigation is available through a dismissible drawer.

Motion: 140–180ms opacity and surface transitions; a short drawer reveal; determinate progress during scans. No entrance choreography, parallax, animated metrics, or decorative looping effects. Respect reduced motion, reduced transparency, increased contrast, and forced colors.

## Validation

- Production TypeScript/Vite build, Prettier formatting, and strict TypeScript checks with unused-local/parameter detection pass. No ESLint task is configured.
- All 19 frontend interaction tests and all 138 offline backend tests pass. The backend suite reports one existing Starlette/httpx deprecation warning.
- Completed a new scan with the isolated mock API and worker. Selected another athlete, toggled overlays, and confirmed the detail pane returned to its top. Stored measurements and scan-level recommendations remain distinct.
- Visually checked the report at 1440px and 375px; checked compact navigation, grouped settings, upload controls, and first-scan entry at 320px. Light and dark appearances were both inspected.
- At 320px and 200% text, checked settings, upload, report, and first-scan entry. The report's internal scroll width equals its client width after the final reflow fixes. Native text fields retain their expected horizontal editing behavior; roster tables retain an explicit horizontal scroller.
- Used a temporary, clearly labeled fictional fixture to inspect league-rule forms at desktop and 320px widths. Removed the fixture after QA. The live Sleeper service was not called for this visual review.
- Tests cover tab keyboard navigation and form-state preservation, compact drawer focus and dismissal, connection-dialog focus containment/restoration, history/report behavior, guardrails, upload readiness refresh, stored measurements, and honest real/demo provenance.
- Kept setup action feedback visible across all five sections, including after saving rules.
- Replaced the inaccessible game-log import label with a native button that opens the same JSON picker. Updated references to setup actions to name their new sections.
- Reduced motion disables animations and transitions; reduced transparency retains a solid toolbar. Increased contrast and forced-color adaptations are included. A full screen-reader/device-lab audit was not part of this pass.

Final critique: the remaining visual emphasis belongs to the athlete and film. Removed the decorative court illustration, slogans, repeated title/breadcrumbs, summary-card grid, repeated section icons, candidate initials, and export-card framing. Report tools are available where their content is used; the sidebar remains stable while evidence scrolls. Final assessment: **Good**, with a coherent utility-focused point of view and the existing functional surface preserved.
