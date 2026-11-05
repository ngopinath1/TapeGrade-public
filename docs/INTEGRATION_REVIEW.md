# Integration behavior

The workspace combines presentation components with the durable scouting workflow.

The shared frontend now connects those structures to the updated backend:

- Live scan controls use `workflow.can_start`, allowing the worker to refresh statistics and locate film even when cached manual readiness is false. Backend blockers still disable submission when cached readiness is true.
- Failed scans retain retry behavior and open the backend-requested setup tab or connection dialog. Setup destination names map to the design's existing accessible tabs without losing form state.
- The designed mission form retains its compact layout and position shortcuts, with explicit sample/live actions, guided readiness, and progress through the new worker stages.
- The selected-player film panel displays identity proof, observed-player profiles, source attribution and excerpt ranges, automatic clip attempts, and withheld tracking states. Clip-switch events remain in the audit. Player selection remains independent of the scan-wide recommendation.
- Reports without analyzed footage show the explanation and publisher viewing links without suggesting that the footage was analyzed. Empty shortlists retain the backend's reason.
- The film library preserves its upload layout and file-size checks, adds statistics-ready player search and explicit selection, refreshes global readiness after upload, offers a return to scouting, and shows collected highlights before optional uploads.
- Scheduling controls honor server availability. Diagnostic reports are distinguished from roster recommendations, and move summaries explain that the user acts in Sleeper.
- New evidence styles use the design's existing adaptive tokens. Backend navigation and global styling overrides were not layered over the redesigned shell.

## Validation boundaries

Run the offline backend/frontend suites and production build in `handoff.md`.
Contract fixtures validate client behavior, error handling, identity gates,
fallbacks, and persistence without paid model requests. They do not establish
live service access or recommendation accuracy.

Review mock/live labels, evidence downloads, rejected tracking, player switching,
workspace changes, settings persistence, keyboard navigation, and compact layouts
when changing shared workflows. Keep private runtime evidence and account details
outside repository documentation. The local-use boundary is documented in
`SECURITY.md`.
