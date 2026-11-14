# End-to-End Tests (Playwright)

Three browser scenarios check the main Campus workflows the way users perform them: real sign-in, real forms
and real buttons in Chromium. They complement the Django tests in `core/tests/test_workflows.py`, which check
business rules directly.

## Scenarios

| ID | Scenario | What it proves |
|---|---|---|
| E2E-01 | Complete academic lifecycle | An administrator creates a semester, a library course and an Active offering with a teacher. A student registers and is approved, then enrolls. The teacher adds an assessment and saves a grade. The administrator closes the enrollment window, the teacher publishes the final grade, and the student sees 9/10 on the transcript. |
| E2E-02 | Role-based access and validation | A student gets "Access is restricted" (403) on administrator and teacher pages. A teacher gets 403 on an administrator page and 404 on another teacher's gradebook. A grade of 11 is blocked by the browser, a comment without a grade is rejected by the server ("No changes have been saved."), and the student still sees "Not yet graded". |
| E2E-03 | Grade correction lifecycle | Starting from a published final grade of 6, the administrator unpublishes it with a reason, the teacher corrects the grade to 9 and publishes again, the student sees 9/10, and Audit history shows the unpublish (with its reason) and both publications. |

## One-time setup

From the repository root, in the project's virtual environment:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m playwright install chromium
```

The database user needs permission to create databases, exactly as for the Django tests.

## Run

```powershell
.venv\Scripts\python.exe manage.py test e2e --pattern="e2e_*.py" -v 2
```

To watch the browser, set `E2E_HEADED=1` first (PowerShell: `$env:E2E_HEADED = "1"`).

The normal command `manage.py test` does **not** run these scenarios, because their file names start with
`e2e_` instead of `test`. The Django tests therefore stay fast and do not need Playwright.

## Reading the result

Each scenario prints one line, followed by a summary:

```
E2E-01: setup, registration, approval, enrollment, grading, publication, transcript. ... ok
E2E-02: forbidden pages for students and teachers, and invalid grades are rejected. ... ok
E2E-03: admin unpublishes with a reason, teacher corrects and republishes. ... ok
Ran 3 tests in 24s
OK
```

`ok` means PASS. A failing step prints `FAIL` or `ERROR` with the Playwright call log, which names the locator
or assertion that did not match. The whole run takes about 25 seconds.

## Screenshots

Seven full-page screenshots are saved to `test-results/e2e/` (ignored by Git) for the project report:

| File | Shows |
|---|---|
| `e2e01-1-offering-created.png` | Course offerings list with the new offering open for enrollment |
| `e2e01-2-student-enrolled.png` | Student course page after enrolling |
| `e2e01-3-final-published.png` | Teacher gradebook with the published final grade |
| `e2e01-4-transcript.png` | Student transcript with the final grade |
| `e2e02-1-access-denied.png` | The 403 page shown to a student |
| `e2e02-2-invalid-grade-rejected.png` | Gradebook error after an invalid grade entry |
| `e2e03-1-audit-history.png` | Audit history with the unpublish reason expanded |

## How the development database is protected

- The scenarios run inside Django's test runner, which creates a separate `test_<POSTGRES_DB>` database and
  destroys it afterwards. The development database is never opened.
- The browser talks only to Django's live test server on `127.0.0.1` with a random port. No URL points at a
  running development server.
- Each scenario starts from an empty database; Django clears it after every scenario, so the three are
  independent and can run in any order.

## Design notes

- Plain Django `StaticLiveServerTestCase` classes and Playwright's sync API; no extra test framework.
- Starting data (accounts, and for E2E-02 and E2E-03 an existing offering) is created before Playwright
  starts. Playwright's sync API keeps an event loop running while it is active, and Django refuses database
  calls during that time, so test bodies check results through the user interface.
- Locators use visible labels, roles and button text, which also checks that forms stay accessible.
- Only the gradebook's "unsaved changes" warning is accepted automatically; any other browser dialog fails
  the scenario.
- The enrollment window is closed through the administrator's offering form, as a real administrator would.

## Limitations

- Chromium only, at one desktop viewport (1280 × 900).
- No accessibility scan; `scripts/browser_check.py` remains the separate smoke and axe check for a running,
  seeded server.
- Times are entered in the application's time zone (`TIME_ZONE`, Europe/Riga by default).
