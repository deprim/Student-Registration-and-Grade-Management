# Campus — Student Registration and Grade Management

A complete server-rendered Django application for student approval, course enrollment, assessment grading, and final-grade publication.

## Technology

- Python 3.13 and Django 5.2 LTS
- PostgreSQL 17 and psycopg 3
- Django Templates, locally bundled Bootstrap 5.3.8, and vanilla JavaScript
- Gunicorn, WhiteNoise, and Docker Compose

## Start with Docker Compose

Install Docker Engine with the Compose plugin, or Docker Desktop. Run commands from the project directory.

```sh
cp .env.example .env
```

Edit `.env`: set a random `SECRET_KEY` and choose a local `POSTGRES_PASSWORD`. The Compose configuration supplies the database hostname automatically. Keep the example `localhost` host settings for local use.

```sh
docker compose build
docker compose up -d db
docker compose run --rm web python manage.py migrate
docker compose run --rm web python manage.py seed_demo
docker compose up -d web
```

Open [http://localhost:8000](http://localhost:8000). Database contents persist in the `postgres_data` volume. Migrations and demo seeding are explicit; starting the application never resets data.

To start without demonstration data, replace the `seed_demo` command with:

```sh
docker compose run --rm web python manage.py createsuperuser
```

Useful commands:

```sh
docker compose ps
docker compose logs -f web
docker compose exec web python manage.py check
docker compose stop
```

If you change `POSTGRES_USER`, `POSTGRES_DB`, or `POSTGRES_PASSWORD` after initializing the volume, update the actual PostgreSQL role/database too. PostgreSQL initialization variables do not modify existing volumes.

## Demonstration accounts

These credentials are exclusively for local educational use. Do not expose demonstration accounts publicly.

| Role | Email | Password |
|---|---|---|
| Administrator | `admin@campus.example` | `DemoAdmin!2026` |
| Teacher | `teacher@campus.example` | `DemoTeacher!2026` |
| Second teacher | `teacher2@campus.example` | `DemoTeacher!2026` |
| Student | `student@campus.example` | `DemoStudent!2026` |
| Pending student | `pending1@campus.example` | `DemoStudent!2026` |

Additional approved students use `student2@campus.example` through `student12@campus.example`, with the same student demo password. There are two pending applications and one rejected application.

Demo scenarios:

- **CS101:** enrollment is open and places are available.
- **MA201:** enrollment is open but the course is full.
- **DB301:** enrollment is closed, grades are recorded, one final is published, and other students still have a missing assessment grade. The first teacher manages this course.
- **WD101:** an archived course with published finals in the previous semester.

Demo dates are relative to the initial seed date. Running `seed_demo` again leaves existing demo data unchanged; it does not move dates or reset changes. Seeding is transactional. If the demonstration administrator already exists, the command exits without changing records.

## Manual setup

Install Python 3.13 and PostgreSQL 17. Create a PostgreSQL role and database using your local PostgreSQL administrator account:

```sql
CREATE ROLE student_portal WITH LOGIN PASSWORD 'choose-a-local-password' CREATEDB;
CREATE DATABASE student_portal OWNER student_portal;
```

`CREATEDB` is needed for Django's separate test database; a production application role should not have it.

```sh
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Set `SECRET_KEY` and the `POSTGRES_*` values in `.env` to match your local database, then run:

```sh
python manage.py migrate
python manage.py seed_demo
python manage.py runserver
```

On Windows, activate with `.venv\Scripts\activate` and use `py -3.13` when creating the virtual environment.

For a local production-style server:

```sh
python manage.py collectstatic --noinput
gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 3
```

## Workflows

### Administrator

Open **People & applications** to approve or reject students, create teachers, update user details, or block accounts. Rejections and blocks require reasons. Approved students receive permanent student numbers. Students with academic history are blocked rather than rejected.

Create semesters and course-library entries, then create a course offering with an active teacher, capacity, and enrollment dates. Draft offerings are hidden from students; select **Active** to publish. Capacity cannot be reduced below current enrollment.

Open an offering's gradebook to inspect results. Unpublish a final grade with a reason before a teacher corrects that student's grades. Administrators can clear erroneous assessment grades with a reason, but cannot bypass final-grade locks.

Archive offerings only after enrollment closes and all enrolled students have published finals. Archive semesters and course-library entries after all related offerings are archived. The technical `/admin/` interface is read-only for academic records; normal management uses `/management/`.

### Teacher

Open **Assigned courses**, select a course, and add assessments. Enter grades and optional comments in the gradebook and select **Save grades**. One invalid entry rejects the whole batch. Students see saved grades immediately.

Once enrollment closes and every assessment has a grade for a student, select **Confirm final**. Review the calculated result and confirm. Final publication locks that student's grades. If any final is published, the assessment structure and offering configuration are locked. Ask an administrator to unpublish the relevant finals before corrections.

### Student

Register and wait for administrator approval. Then browse the catalog, open a course, and confirm enrollment. Enrollment is immediate if the window is open and a place remains. Withdrawal is possible during that window only before grades exist; re-enrollment restores the original record.

Use **My courses** for assessment results and comments, or **Academic transcript** for semester filtering, CSV export, and printing. Printing covers the visible page; CSV includes all filtered courses.

## Grading rules

- Assessment grades are whole numbers from 1 to 10, with equal weights.
- Missing grades display as **Not graded** and never count as zero.
- The current average uses only recorded grades and is displayed to two decimal places.
- A final requires at least one assessment, no missing grades, and a closed enrollment window.
- The final rounds the original arithmetic mean to an integer using decimal `ROUND_HALF_UP`: `7.5` becomes `8`.
- Teachers cannot manually override the calculated final.
- The final stores its average snapshot, publisher, and timestamp. Every publication, correction, and unpublication is audited.
- Archived records are read-only. Blocked students retain grades, enrollments, and occupied places.

## Tests and checks

The test runner uses PostgreSQL and creates a separate `test_<POSTGRES_DB>` database. Never point test commands at a production service. The database user needs permission to create test databases.

```sh
docker compose run --rm web python manage.py test --verbosity 2
docker compose run --rm web python manage.py check
docker compose run --rm web python manage.py makemigrations --check --dry-run
```

Or, in the activated manual environment:

```sh
python manage.py test --verbosity 2
python manage.py check
python manage.py makemigrations --check --dry-run
```

Tests cover account approval, permissions, CSRF, object ownership, capacity races, grade ranges, transactional batches, audit rollback, final publication, archival, CSV safety, password reset, demonstration seeding, and the English-content requirement.

Browser verification and database restore instructions are in `docs/verification.md` and `docs/backup.md`.

Optional development tools and browser checks:

```sh
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
python scripts/browser_check.py
ruff check accounts academics config core grading reports scripts manage.py
ruff format --check accounts academics config core grading reports scripts manage.py
```

Run browser checks against a running locally seeded app. Screenshots are saved in the ignored `test-results/` directory. Set `BROWSER_BASE_URL` to use a different address, or `BROWSER_EXECUTABLE` to use an existing Chromium installation. The checks cover desktop, tablet, and mobile at 1440, 1024, 768, and 375 pixels. Optionally set `BROWSER_AXE_SCRIPT` to the absolute path of a local axe-core script to include accessibility checks.

The frontend design system, page inventory, component guidance, and audit approach are documented in [Visual Design](docs/visual-design.md). Fonts, icons, Bootstrap, and application assets are served locally.

## Configuration and hosting

Configuration is read from environment variables; a local `.env` fills only variables not already set in the environment. All `POSTGRES_*`, mail, host, and cookie settings are listed in `.env.example`. Dates and times use `Europe/Riga` by default, with timezone-aware storage.

Password reset emails are printed to the console locally. For email delivery, set `EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend` and the SMTP settings. The reset response does not reveal whether an account exists.

Before public hosting, use unique secrets and credentials, remove demo accounts, set `DEBUG=False`, set exact `ALLOWED_HOSTS` and HTTPS `CSRF_TRUSTED_ORIGINS`, and configure TLS termination. Enable `COOKIE_SECURE=True` and `SECURE_SSL_REDIRECT=True` when requests reach Django over HTTPS. When using a trusted reverse proxy, configure Django's proxy HTTPS handling for that deployment before enabling redirects; do not blindly trust arbitrary forwarded headers. Provide login rate limiting at the reverse proxy. Run `python manage.py check --deploy` and address deployment-specific findings. Actual hosting is outside this delivery.

The default Compose port is bound to loopback. Its health check uses HTTP for local operation; adapt the check to your TLS setup for deployment. `/health/` returns only readiness status and never configuration details.

## Architecture and boundaries

The project uses a single Django deployment. Views handle forms and rendering; service functions enforce permissions, state transitions, transactions, and audit writes. Database constraints reinforce uniqueness and grade ranges. Semester and offering row locks serialize enrollment and grading changes.

Applications:

- `accounts`: custom email-based users, approval, authentication, profiles.
- `academics`: semesters, courses, offerings, enrollments.
- `grading`: assessments, assessment grades, final grades.
- `reports`: permission-scoped CSV and printable transcripts.
- `core`: layouts, dashboards, access helpers, audit, health checks, demonstration data.

Main routes: `/accounts/`, `/student/`, `/teacher/`, `/management/`, `/admin/`, and `/health/`.

The first version supports one institution, one teacher per offering, and one offering per course per semester. It intentionally excludes attendance, scheduling, payments, assignment uploads, chat, admissions, retakes, external integrations, and a separate API.

Bootstrap is included under its MIT license in `static/vendor/BOOTSTRAP-LICENSE.txt`.
