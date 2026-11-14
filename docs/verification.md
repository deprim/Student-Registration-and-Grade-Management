# Verification Guide

## Current verified state

Verified on November 9, 2026 at commit `760c652` (branch `review-and-improvement`).

### Environment

| Component | Version |
|---|---|
| Operating system | Windows 11 |
| Python | 3.13.7 (virtual environment in `.venv`) |
| Django | 5.2.18 |
| PostgreSQL | 18.6, local service (README and `compose.yaml` target PostgreSQL 17) |
| psycopg | 3.3.3 |
| Playwright | 1.58.0 with the Chromium headless shell (build 1208) |

### Results

| Check | Command | Result |
|---|---|---|
| Django tests | `manage.py test` | 78 passed |
| Playwright end-to-end scenarios | `manage.py test e2e --pattern="e2e_*.py" -v 2` | 3 passed (E2E-01, E2E-02, E2E-03) |
| System checks | `manage.py check` | No issues |
| Migration drift | `manage.py makemigrations --check --dry-run` | No changes detected |

All automated checks ran on the isolated test database that Django creates and destroys; the development
database was not used. The end-to-end scenarios are described in [End-to-End Tests](e2e-testing.md).

The Django tests cover registration and approval, real sign-in (including blocked, pending and rejected
users), the role-based access matrix, object ownership, CSRF, enrollment windows and capacity (including a
concurrent last place), withdrawal, grade ranges and all-or-nothing grade batches, final-grade calculation,
publication, unpublication and correction, archiving, audit actors and rollback, CSV safety and exports,
password reset, the read-only technical admin, demonstration seeding and the English-content requirement.

### Browser checks of the current interface

- The three Playwright scenarios exercise the main workflows in Chromium at 1280 × 900 and save seven
  screenshots to `test-results/e2e/`.
- After the visual refresh (commit `20ef22a`), 25 pages were rendered from the isolated test database and
  measured at 1440 px and a true 390 px width: no horizontal overflow, no on-screen text below 12 px, no
  text below WCAG AA contrast in a browser script that compares computed colours, and visible focus rings.
  This was a measurement script, not an axe-core scan.

### Not verified at this commit

- Docker Compose build and startup: Docker is not installed on the verification machine.
- PostgreSQL 17, the version targeted by the README and `compose.yaml`; only PostgreSQL 18.6 was used.
- Deployment and HTTPS settings: `manage.py check --deploy` reports the expected warnings for a local setup
  (`DEBUG`, HSTS, SSL redirect and secure cookies). Public hosting is out of scope.
- An axe-core accessibility scan, browsers other than Chromium, and screen-reader testing.
- The printed transcript layout (manual print preview only).
- Email delivery over SMTP; local configuration prints emails to the console.
- Ruff, djlint and static-file packaging checks were not repeated after the UI changes.

## Commands

From the repository root on Windows:

```powershell
.venv\Scripts\python.exe manage.py test
.venv\Scripts\python.exe manage.py test e2e --pattern="e2e_*.py" -v 2
.venv\Scripts\python.exe manage.py check
.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
```

The test database user needs permission to create databases. The end-to-end scenarios need the one-time
setup in [End-to-End Tests](e2e-testing.md). The Docker Compose equivalents are listed in the README.

## Full user journey (manual)

1. Open a private browser session, select **Create a student account** and register a new student.
2. Confirm that only **Application status** and account controls are available, showing **Pending approval**.
3. Sign in as the demo administrator. On **Overview**, select the **Review … applications** button (it shows
   the number of pending applications), then **Approve** the new student and **Confirm action**. The message
   shows the new student number.
4. Sign in as the student, open **Course catalog**, select **View course and enroll** for CS101, then
   **Enroll in course** and **Confirm action**.
5. As the administrator, open **Course offerings**, select **Edit** for CS101 and set **Enrollment end** to a
   time in the past after **Enrollment start**. Select **Save changes**.
6. Sign in as `teacher@campus.example`, open **Assigned courses**, then **Open gradebook** for CS101. Enter all
   three assessment grades for the new student and select **Save grades**.
7. Select **Publish final grade** for the new student, check the calculated value and **Confirm action**.
8. Sign in as the student and check the individual grades, comments, average and the published final grade on
   the course page and the **Academic transcript**.
9. On the transcript, select **Export CSV** and verify that it contains only that student's courses.
10. As the administrator, open **Course offerings**, then **Gradebook** for CS101, select **Unpublish** and give a
    reason. As the teacher, correct a grade, **Save grades** and **Publish final grade** again. Check the
    entries in **Audit history**.

Steps 5 and 10 change the database permanently. Use a database that may be reseeded.

## Layout and accessibility (manual)

Verify all three dashboards at desktop width and at 390 px:

- The mobile **Menu** button opens and closes navigation.
- All fields have labels, including gradebook cells.
- Keyboard focus is visible and the skip-to-content link works.
- Tables scroll inside their panels instead of widening the whole page.
- The gradebook preserves invalid input and reports errors.
- Empty catalogs, search results, gradebooks and transcripts show helpful messages.
- Forms, errors, emails, CSV headers and print views are in English.

Verify CSV downloads and a print preview of the transcript. The print view excludes navigation and controls.

## Clean installation

Use a separate empty database and follow the README from dependency installation through migrations and
seeding. Run `seed_demo` twice and confirm that record counts do not change. Do not reset an existing project
database to perform this check.

## Backup verification

Follow `docs/backup.md` to restore into a separate database. Compare user, grade, final-grade and audit counts,
then read a sample transcript through Django's ORM.

## History: October 23, 2026 verification

Recorded before the UI/UX improvements and the visual refresh; kept for reference.

- Clean migrations and demonstration seeding on Python 3.13 and PostgreSQL 17.11, locally and in Docker.
- 46 automated tests passed locally and inside the built Docker image; system and migration drift checks passed.
- Production static-file packaging, Python linting and formatting checks passed; 30 HTML templates passed
  formatting checks.
- Chromium checks passed at 1440, 1024, 768 and 375 px with zero automated axe-core violations for the enabled
  WCAG 2 A/AA, 2.1 AA and 2.2 AA rule tags, including JavaScript-disabled navigation.
- A frontend audit (the published web-design-guidelines skill, the installed ui-ux-pro-max guidance, Chromium
  inspection and axe-core 4.10.3) led to these corrections: higher contrast for course numbers and control
  borders, explicit SVG icon fill and stroke, field errors linked to unique description IDs with input kept,
  readable gradebook errors beside each control, focus moved to the first invalid control, visible scrolling
  guidance and keyboard access for overflowing tables, and larger filter targets in the technical admin.
- A PostgreSQL custom-format backup was restored into a separate database with matching record counts.
