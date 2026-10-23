# Verification Guide

## Implementation verification results

Verified on October 23, 2026:

- Clean migrations and demonstration seeding on Python 3.13 and PostgreSQL 17.11.
- All 46 automated tests passed locally and inside the built Docker image.
- Django system checks and migration drift checks passed.
- Production static-file packaging, Python linting, and formatting checks passed.
- Chromium checks passed for administrator, teacher, and student pages at 1440 px and 375 px, including the mobile menu and gradebook.
- The same browser checks passed against the Dockerized application.
- A PostgreSQL custom-format backup was restored into a separate database. Source and restored counts matched: 18 users, 21 enrollments, 31 assessment grades, 7 final grades, and 41 audit events.

## Frontend redesign verification

The academic editorial redesign was verified on October 23, 2026 against the local PostgreSQL 17 application. See [Visual Design](visual-design.md) for the page inventory and design tokens.

- All 46 PostgreSQL tests passed after the redesign. System checks and migration drift checks passed.
- Backend Python file hashes matched their pre-redesign values: models, services, views, permissions, and route definitions are unchanged.
- Application Python lint and format checks passed, and all 30 HTML templates passed formatting checks. Lint checks are scoped to application code; installed third-party skill packages are excluded.
- Browser checks cover 1440, 1024, 768, and 375 pixel widths, including public authentication, all three roles, pending and rejected applications, supplementary Django Admin, course details, gradebooks, filters, and forms.
- The complete browser matrix passed with zero automated axe-core violations for WCAG 2 A/AA, 2.1 AA, and 2.2 AA rule tags. Manual review also covers keyboard navigation, reduced motion, SVG icons, readable tables, and useful empty/error states. These checks are not a claim of complete accessibility certification.
- A deliberately invalid grade batch preserved the entered value, focused the invalid control, and left all grade values and comments unchanged.
- Duplicate registration preserved the form input and focused the email error; the error description has a unique identifier.
- Approval, rejection, and blocking confirmation screens passed mobile browser and accessibility checks without applying those actions.
- Teacher gradebook and student transcript CSV downloads passed. The transcript print layout excludes navigation and controls.
- Login, course search, and course-detail navigation also passed with JavaScript disabled.
- Locally hosted fonts and icons are included in the production static-file manifest. No frontend framework or runtime dependency was added.

## Automated checks

Run the PostgreSQL suite, system checks, migration drift check, and static packaging commands described in the README. Concurrency tests use separate database connections and verify that exactly one of two students gets the last available place.

## Full user journey

1. Open a private browser session and register a new student.
2. Confirm that only the application status and account controls are available.
3. Sign in as the demo administrator and approve the new application.
4. Sign in as the student and enroll in CS101.
5. As the administrator, end the CS101 enrollment window by setting its closing time to a past time after its opening time.
6. Sign in as `teacher@campus.example` and record all three assessment grades for the new student. Save the gradebook.
7. Confirm the student's final grade and verify the calculation.
8. Sign in as the student and check the individual grades, comments, average, and published final.
9. Export the personal transcript and verify that it contains only that student's courses.
10. As the administrator, unpublish the final with a reason. As the teacher, correct a grade and republish. Check the audit history.

## Layout and accessibility

Verify all three dashboards at desktop width and at 375 px:

- The mobile Menu button opens and closes navigation.
- All fields have labels, including gradebook cells.
- Keyboard focus is visible and the skip-to-content link works.
- Tables scroll inside their panels instead of widening the whole page.
- The gradebook preserves invalid input and reports errors.
- Empty catalogs, search results, gradebooks, and transcripts show helpful messages.
- Forms, errors, emails, CSV headers, and print views are in English.

Verify CSV downloads and a print-preview of the transcript. The print view excludes navigation and controls.

## Clean installation

Use a separate empty database and follow the README from dependency installation through migrations and seeding. Run `seed_demo` twice and confirm that record counts do not change. Do not reset an existing project database to perform this check.

## Backup verification

Follow `docs/backup.md` to restore into a separate database. Compare user, grade, final-grade, and audit counts, then read a sample transcript through Django's ORM.
