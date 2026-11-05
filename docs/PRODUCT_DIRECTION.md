# TapeGrade product direction

TapeGrade helps a fantasy basketball manager answer one question: **is there a better move for my roster, and what evidence supports it?** The core path is connect a league → compare players → check film → review a decision → act in Sleeper.

The success criterion is a manager understanding the next action without reading the README or knowing the model names. A report with no supported move is a complete outcome when its reason is clear.

## Design review: scouting workflow

### Summary

The initial interface needed work: it exposed the scouting machinery before explaining the user's task. Empty film, tracking, candidate and card panels competed with the request, while setup failures described requirements without taking users to a fix. This iteration prioritizes the roster decision and gives the technical evidence a supporting role.

This is a React web app for desktop and mobile browsers. Apple's clarity, hierarchy and accessibility principles apply; native macOS navigation conventions do not.

### Improvements implemented

- **High — Unclear starting point.** The landing page now explains the outcome, offers three editable requests and provides a clearly labeled sample scan. No empty analysis panels appear before a report. `writing.md › Best practices`: “Provide clear next steps on any blank screens.”
- **High — Setup dead ends.** The next action uses backend readiness and links to game logs, film or player availability. A report remains available without verified add/drop eligibility. Setup shows one task at a time. `layout.md › Visual hierarchy`: “Use progressive disclosure to make layouts cleaner and easier to interact with.”
- **High — Misleading automation language.** “Autopilot” became “Scouting preferences.” Results explain that a user acts in Sleeper; unavailable schedules cannot be enabled. `writing.md › Best practices`: “Be action oriented.”
- **High — Unlabeled compact navigation.** Mobile now has persistent, labeled navigation rather than an icon-only side rail. Tablet navigation also retains labels. Readiness uses text and checkmarks, not color alone. This is a design judgment applied to the web layout.
- **Medium — Result hierarchy.** The recommendation precedes player verdicts and film. The next request, tracking audit, card download and league summary use disclosure controls.
- **Medium — Upload handoff.** Users explicitly choose a player, search statistics-ready free agents and return to scouting after upload. Successful processing refreshes global readiness rather than leaving the scan disabled with stale state.
- **Medium — Progress and recovery.** Scans have three understandable phases, a labeled progress bar, persistent history and an explicit retry explanation.

### Craft notes

Keep the existing court-green identity and quiet typography. The signature is a concrete add/drop decision with inspectable evidence. Remove decorative edition markers, model advertising beside the main action and the API explorer from primary help. No new ornamental motion is needed.

New workflow color roles reuse the existing dark palette:

| Role | Value | Measured contrast |
| --- | --- | --- |
| Background | `#111410` | Content: 15.36:1 |
| Panel | `#191d17` | Content: 14.14:1 |
| Guided step | `#1d2519` | Secondary text: 8.71:1 |
| Content | `#e7ebe2` | On background: 15.36:1 |
| Secondary text | `#b9c4b1` | On guided step: 8.71:1 |
| Action | `#c0ee8e` | On guided step: 11.92:1 |

Primary button text `#151b10` on the action color is 13.26:1. New explanatory text uses 14px, secondary text 12–13px, headings 20–24px and the page title 28–42px. Compact navigation labels use 11px and 58px-high targets. Existing dense evidence tables are retained; this is not a complete accessibility certification or a light-theme implementation.

Regular layout: context → next step/request → decision + player verdicts → selected film → optional detail.
Compact layout: the same order in one column, with labeled navigation below.

```text
Desktop                         Mobile
League / team                   League / team
Next step + request             Next step + request
Decision | Player verdicts      Decision
Selected player's film          Player verdicts
Optional audit / downloads      Selected player's film
                                Optional audit / downloads
                                Labeled navigation
```

### What works

Keep the distinction between fictional samples, live league data and film diagnostics. Preserve sourced statistics, honest unavailable measurements, backend transaction validation, protected players and explicit live-call limits. These make the decision trustworthy.

### Platform notes

Keyboard focus and a skip link remain visible. Disclosure controls are native HTML, current navigation has an accessible name and state, and the progress bar reports its value. Reduced-motion preferences suppress animation. Mobile no longer loses content width to the side rail. New workflow text meets measured contrast requirements; retained legacy evidence styling still needs a dedicated accessibility pass.

## Remaining work toward “just works”

1. **Reduce footage preparation.** The largest remaining input burden is finding recent, permitted footage with a verifiable player identity. Build a player-specific clip acquisition/preparation flow before promising autonomous real-league scouting. Never substitute a historical or unidentified highlight for current evidence.
2. **Refresh league data with less supervision.** Coordinate roster/rule freshness and bounded game-log refreshes, preserve source timestamps and show one user-facing state. Keep provider failures recoverable without requiring an API explorer.
3. **Bring availability review into the proposed move.** The current manual evidence expires after five minutes. A supported authoritative eligibility source, or a focused candidate/drop review at decision time, would reduce repeated setup. Unknown locks must continue to withhold actionable moves.
4. **Validate real scouting value.** Verify named, recent footage and tracking accuracy in bounded live tests before claiming useful fantasy predictions. The successful sample workflow proves the experience and integrations, not real-world scouting accuracy.
5. **Make local operation reliable.** The current app needs an awake Mac, API and separate worker. A single managed startup experience and clear worker health would close another gap before hosted operation or scheduled scouting is promoted.

Prioritize these input and reliability gaps before adding more models, dashboards, fantasy platforms or autonomous transaction execution.
