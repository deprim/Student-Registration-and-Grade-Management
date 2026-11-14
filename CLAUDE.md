# Campus: project guide for Claude Code

Campus is a four-person TSI university group project: a server-rendered Django application for student
registration, administrator approval, course enrollment, assessment grading and final-grade publication.
Roles: Administrator, Teacher, Student.

**Start every session by reading [docs/current-state.md](docs/current-state.md)** (checkpoint, decisions,
limitations and future work).

## Stack

Python 3.13, Django 5.2, PostgreSQL (psycopg 3), Django templates, locally bundled Bootstrap 5.3, vanilla
JavaScript and CSS, WhiteNoise, Gunicorn. Do not add a frontend framework.

## Architecture

| App | Responsibility |
|---|---|
| `accounts` | Email-based custom user, registration, approval, profiles, blocking |
| `academics` | Semesters, course library, course offerings, enrollment and withdrawal, admin list pages |
| `grading` | Assessments, grades, gradebook, final-grade publication, unpublish, clear grade |
| `reports` | Student transcript and CSV exports |
| `core` | Access helpers (`access.py`), `ActiveUserMiddleware`, audit log, dashboards, display helpers (`ui.py`), `seed_demo`, test runner, tests |

`config/` holds settings, WSGI and the routes (`config/urls.py`; account routes in `accounts/urls.py`).

## Business-logic boundaries

- Rules live only in `*/services.py` (transactions, row locks, audit writes) and in model/database constraints.
- Views and templates present and explain rules; they never replace server-side checks. A UI hint that
  mirrors a rule must match the service condition, and the service stays authoritative.
- `core/ui.py` contains presentation helpers only (`enrollment_window`, `confirmation`).

## Commands (Windows, repository root)

```
.venv\Scripts\python.exe manage.py test
.venv\Scripts\python.exe manage.py check
.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
```

Tests create and destroy a separate `test_<POSTGRES_DB>` database (the database user needs CREATEDB).
Focused run: `manage.py test core.tests.test_workflows.UserGuidanceTests`.
Playwright E2E (separate, about 25 s): `manage.py test e2e --pattern="e2e_*.py" -v 2`; see `docs/e2e-testing.md`.
E2E tests create data before starting Playwright and check results only through the browser.

## Database and migration safety

- Never write to the development database without explicit approval: no `migrate`, `seed_demo`, `flush`,
  `createsuperuser`, shell writes, or signing in to the running app (sign-in updates `last_login`).
- Never change models, create migrations, or edit/delete historical migrations without explicit approval.
- Never print `.env` values, passwords, tokens or personal configuration.

## Git safety

- Work on `review-and-improvement`; `main` is the release branch.
- No commits, pushes, merges, rebases, resets, stashes, tags, force operations or branch deletion without
  explicit approval.
- Stage by explicit path (never `git add -A`) and review `git diff --cached --stat` before proposing a commit.
- Never commit `.env`, `.venv/`, `.claude/`, screenshots or scratch files.
- Claude Code configuration: this root `CLAUDE.md` is tracked; `.claude/` (including `settings.local.json`)
  stays local. A shared `.claude/settings.json` has been deferred.

## Conventions

- Python follows the ruff settings in `pyproject.toml` (line length 100); templates follow djlint (2-space indent).
- All code, user-facing text and docs are English (a test enforces this); read and write files as UTF-8.
- Reuse the CSS tokens in `:root` of `static/css/app.css` and existing components (`panel`, `badge-soft`,
  `badge-state`, `callout`, `form-section`, `confirm-summary`). Avoid new literal colors.
- Accessibility: labeled fields, visible focus, 44 px targets, states shown with text and not color alone,
  tables scroll inside panels, no page-wide horizontal overflow at 390 px.
- Every presentation change gets a focused test in `core/tests/test_workflows.py`. Do not weaken or delete
  business-rule tests.
- Keep changes small and scoped. No unrelated refactoring. Do not claim verification that was not run.

## Session checklist

1. Read `docs/current-state.md`.
2. Run `git status --short` and `git log --oneline -3`; confirm the branch and a clean tree.
3. Confirm the task scope, including whether it is read-only.
4. After changes, run the three commands above and report the results honestly.
5. Update `docs/current-state.md` at each approved checkpoint.

## Documentation

- [README.md](README.md): setup, demo accounts, grading rules, tests, hosting
- [docs/application-workflows.md](docs/application-workflows.md): role workflows, rules, demo walkthrough
- [docs/current-state.md](docs/current-state.md): internal status, decisions, limitations, future work
- [docs/verification.md](docs/verification.md) and [docs/e2e-testing.md](docs/e2e-testing.md): test evidence
- [docs/visual-design.md](docs/visual-design.md), [docs/backup.md](docs/backup.md)
