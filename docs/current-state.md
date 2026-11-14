# Current State

Internal project status. Last updated: November 9, 2026. Update this file at every approved checkpoint.

## Checkpoint

| Item | Value |
|---|---|
| Branch | `review-and-improvement` (`main` is the release branch); not pushed |
| Latest application commit | `760c652` Add Playwright end-to-end scenarios for core workflows |
| Release readiness | READY WITH LIMITATIONS; application code frozen for the university report |
| Automated tests | 78 Django tests and 3 Playwright E2E scenarios, all passing; system check clean, no migration drift |

Evidence and unverified scenarios: [verification.md](verification.md). Workflows and rules:
[application-workflows.md](application-workflows.md).

## Release readiness

The final readiness review at commit `760c652` found no critical (P0) findings and no confirmed code defects.
Only documentation changes are planned.

**Demo database expiration risk.** `seed_demo` sets enrollment windows relative to the seeding date: CS101 and
MA201 stay open for 14 days after seeding. A demo database seeded on November 9, 2026 can no longer show
enrollment after about November 23, 2026. The demonstration walkthrough also expects Oliver West to be pending
and Taylor Brooks to have no published final, so every rehearsal changes the outcome. Before the presentation,
seed a fresh database shortly beforehand (or adjust the offering dates through the administrator's offering
form), and do not rehearse on that database.

## Delivered on this branch

| Commit | Change |
|---|---|
| `9f10495` | Clearer guidance for all roles: next-step dashboards, catalog availability, gradebook publication reasons, explained confirmations |
| `8942a44` | Shared `CLAUDE.md` project guide and project status documents |
| `20ef22a` | Minimal TSI-inspired visual refresh (see [visual-design.md](visual-design.md)) |
| `852deaf` | Tests for the access matrix, real sign-in, enrollment windows, audit actors and CSV routes |
| `760c652` | Three Playwright end-to-end scenarios (see [e2e-testing.md](e2e-testing.md)) |

## Decisions

- Optional features are retained: audit history, archiving, block/unblock, clear grade, unpublish, CSV export
  and print.
- Blocked users still see the generic login error; an explicit message (audit item R7) was deferred.
- The catalog uses four availability statuses, so an offering whose enrollment has not opened yet shows
  "Enrollment closed"; its course page states when enrollment opens.
- Confirmation buttons keep the generic "Confirm action" label.
- CSV headers read "Not yet graded" and "Not yet published".

## Known limitations

- No notifications or emails for approval, grades or finals (password reset email only).
- The gradebook scrolls horizontally on phones.
- The Django technical admin (`static/css/admin.css`) still uses the previous green palette.
- `static/fonts/source-serif-*` files are no longer referenced.
- QA findings recorded but not changed (P2): a Draft offering blocks archiving of its semester and offerings
  cannot be deleted; `withdraw()` can raise an unhandled error in a rare concurrent double withdrawal; the
  reject service accepts an already approved student without enrollments (reachable only by URL); course
  codes are unique case-sensitively.

## Future work

- Accessibility: an axe-core scan through `scripts/browser_check.py`, a manual keyboard pass for every role,
  and screen-reader spot checks of the gradebook, catalog badges and confirmation pages.
- Tooling: repeat the ruff, djlint and static-packaging checks listed in the README.
- Decisions for the team: whether to hide or remove any optional feature, implement R7, use more specific
  confirmation labels, add a separate catalog status for enrollment that has not opened yet, or fix the P2
  findings.
- Visual identity: use TSI branding beyond the current palette only with official guidance and permission.
- Release: a security and code review of the branch, a teammate walkthrough with the demo in
  application-workflows.md, then a pull request to `main` with team approval. Before any public hosting,
  follow the README hosting checklist.
- Agree on Docker or local PostgreSQL, and on PostgreSQL 17 or 18, for the whole team.

## Environment notes (development machine)

- Windows 11, Python 3.13.7 in `.venv`, local PostgreSQL 18.6. Docker is not installed on this machine.
- `requirements-dev.txt` (Playwright 1.58.0, ruff, djlint) and Playwright's Chromium headless shell are installed.
- During tests, WhiteNoise warns that `staticfiles/` does not exist; this is expected without `collectstatic`.
