# TapeGrade design review and implementation

Previous iteration. The current redesign and validation are documented in [apple-workspace.md](apple-workspace.md).

## Summary

Overall rating of the original: **Critical issues**. A React web workspace for fantasy basketball managers gives similar weight to the scan form, four summary metrics, film, all candidate rationales, a model audit, a move, a large export card, and a repeated roster. The screen's job is to help a manager find and assess a supported roster opportunity. Its signature should be the film and its annotated court, rather than interface decoration.

Apple's foundations apply here; native macOS menu-bar or iOS tab-bar requirements do not apply to this browser application.

## Critical

- **Accessibility:** The original navigation caption uses 9px #747e6c on #151912 (4.19:1). Many utility labels use 8–10px. `accessibility.md › Vision`: “Strive to meet color contrast minimum standards.” Replace small utility text with 12px minimum, body text with 15px, and semantic colors that pass 4.5:1 in both appearances. `frontend/src/style.css` originally lines 210–215.
- **Keyboard access:** The league dialog lacks Escape dismissal, a focus trap, and restoration to its trigger. `accessibility.md › Speech`: “Let people use the keyboard alone to navigate and interact with your app.” Add focus management and retain a visible close control. `frontend/src/components/SleeperDialog.tsx` originally lines 39–48.

## Improvements

- **High — hierarchy:** The page repeats the roster and opens with promotional copy, delaying the core task. `layout.md › Visual hierarchy`: “Order content by relative importance.” Use a direct page title, a compact team snapshot, the mission form, and a report organized as candidate → film → move. Remove the repeated roster. `frontend/src/pages/App.tsx` originally lines 211–322 and 494–507.
- **High — progressive disclosure:** Long rationales for every player, an always-open operation log, and a full export image compete with the evidence. `layout.md › Visual hierarchy`: “Use progressive disclosure to make layouts cleaner and easier to interact with.” Show the selected rationale, disclose the tracking audit and card preview, and keep export links easy to reach.
- **Medium — navigation:** A chevron suggests the league card is interactive, but it is a div. Turn it into a connection button; identify the active page with `aria-current`. `buttons.md › Content`: “Ensure that each button clearly communicates its purpose.” Add a hide/show navigation control, following `sidebars.md › Best practices`: “Consider letting people hide the sidebar.”
- **Medium — appearance:** The original workspace forces dark green. `dark-mode.md › Best practices`: “Ensure that your app looks good in both appearance modes.” Follow `prefers-color-scheme`, with an ink-colored film viewport in either appearance.
- **Medium — entry:** The roster has no search or filtering. Add a labeled search field and an explicit protected-player filter. This is a product judgment about the manager's task.

## What works

Keep the persistent league workspace, clear simulated/live provenance, verified/unverified film state, metric limitations, candidate selection, manual recommendation copying, and data-readiness checks. Keep Lucide as a consistent vector icon vocabulary and use native HTML inputs, buttons, disclosures, and tables.

## Design plan

Six core roles, specified before layout work. Ratios are computed from sRGB values against the surface in each appearance.

| Role         | Light   | Dark    | Light contrast | Dark contrast |
| ------------ | ------- | ------- | -------------- | ------------- |
| Canvas       | #f3f5f8 | #111923 | background     | background    |
| Surface      | #ffffff | #182431 | background     | background    |
| Content      | #172b4d | #e6edf5 | 14.10:1        | 13.33:1       |
| Secondary    | #59677b | #aab9cb | 5.75:1         | 7.87:1        |
| Action       | #245bd4 | #93b4ff | 5.96:1         | 7.65:1        |
| Court signal | #a34217 | #ffbd8a | 6.27:1         | 9.66:1        |

Type: system sans for controls and content; a compact 28–36px semibold display title; 20px section titles; 15px body; 13px supporting text; 12px utility labels. Use tabular numerals and a system monospace stack only for timecodes and observed measurements. Sizes use rem and containers grow with text.

Layout: persistent navigation at regular widths, wrapping labeled navigation at compact widths, a candidate list to the leading side of the film on desktop, and candidate/film/move reading order on compact layouts.

```text
Regular
+------------+-------------------------------------------+
| TapeGrade  | Page title                    Connection  |
| League     | Team snapshot                             |
| Navigation | Mission input                  Run scan   |
|            | Candidates     | Player film + metrics    |
|            | Proposed move  |                           |
|            | Tracking details       | Save report      |
+------------+-------------------------------------------+
Compact
+--------------------------------+
| TapeGrade           League     |
| Labeled navigation (wraps)     |
| Page title + team snapshot     |
| Mission / suggested needs      |
| Run scan                       |
| Candidates                     |
| Player film + metrics          |
| Proposed move                  |
| Tracking details / Save report |
+--------------------------------+
```

Signature: basketball court linework in the first-run film guide and the dark video canvas. It connects to film scouting without inventing player evidence. Brand emphasis is spent here; the surrounding workspace stays quiet. Motion: only an activity spinner and determinate progress while a scan runs; reduced motion disables animation. No blur is required.

Plan critique: a generic analytics dashboard would emphasize oversized KPIs and charts. This plan instead gives space to choosing an athlete and inspecting their actual film, preserves evidence provenance, and separates the whole-scan roster move from selected-player tracking. Remove the decorative volume label, avatar profile, repeated slogans, and duplicate roster.

## Validation

Implemented the plan across the desk, roster, library, guardrails, history, and connection dialog. The completed-report state collapses the mission form into “Start another scan.” The whole-scan recommendation explicitly explains that selecting a player changes the film view, not the proposed move. Upload completion refreshes bootstrap readiness so newly permitted footage can enable scanning immediately.

- Production TypeScript/Vite build passes.
- All 16 frontend tests pass, including mission submission, stored measurements, diagnostic provenance, league setup, candidate selection, first-run navigation, roster filtering, dialog focus containment/restoration, and upload readiness refresh.
- Completed a scan in an isolated mock API/worker/browser preview, then switched candidates and checked the selected film.
- Visually inspected desktop at 1440px, an intermediate 805px viewport, and compact layouts at 375px and 320px. Checked both light and dark palettes. The library form and report have no page-level horizontal overflow at 320px.
- Tested 200% root text at 1440px and 320px. Content-driven container queries stack measurements and player controls; the final checks found no overflowing names, measurements, or upload controls. The roster intentionally retains its focusable horizontal table scroller.
- Verified Escape closes the connection dialog and returns focus to the trigger. Automated tests also cover forward/backward focus wrapping. Focus rings, skip navigation, active-page semantics, and status messages are present.
- Reduced motion disables transitions and animation. No backdrop blur or translucent content surface remains, so reduced transparency needs no separate rendering path. Increased contrast and forced-color styles are provided; these two OS modes were inspected in code, not manually emulated. A full VoiceOver audit remains outside this visual/keyboard check.

Final craft critique: removing the decorative volume marker, profile block, repeated roster, and default-open audit/export imagery keeps attention on the athlete and film. The court is the signature; familiar labeled controls carry the workflow. Final rating: **Good**, with device/assistive-technology testing still appropriate before release.
