# PostgreSQL Backup and Restoration

Run commands from the project root. Keep backup files outside version control and store real institutional backups in access-controlled storage.

## Docker Compose backup

Create the destination directory and a PostgreSQL custom-format backup:

```sh
mkdir -p backups
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > backups/campus.dump
```

Check that the command succeeded and the file is nonempty. Inspect its table of contents:

```sh
docker compose exec -T db pg_restore --list < backups/campus.dump
```

## Verify restoration into a separate database

Create a new database without modifying the application database:

```sh
docker compose exec db sh -c 'createdb -U "$POSTGRES_USER" campus_restore_check'
docker compose exec -T db sh -c 'pg_restore --exit-on-error --no-owner -U "$POSTGRES_USER" -d campus_restore_check' < backups/campus.dump
```

Inspect restored records:

```sh
docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d campus_restore_check -c "SELECT COUNT(*) AS users FROM accounts_user; SELECT COUNT(*) AS grades FROM grading_grade; SELECT COUNT(*) AS audit_events FROM core_auditevent;"'
```

For an application-level check, run the web image temporarily against the restored database:

```sh
docker compose run --rm -e POSTGRES_DB=campus_restore_check web python manage.py check
docker compose run --rm -e POSTGRES_DB=campus_restore_check web python manage.py shell -c 'from accounts.models import User; from grading.models import Grade; print("Users:", User.objects.count(), "Grades:", Grade.objects.count())'
```

Keep the verification database until counts and sample academic records are checked. Remove it only after it is no longer needed:

```sh
docker compose exec db sh -c 'dropdb -U "$POSTGRES_USER" campus_restore_check'
```

## Manual PostgreSQL installation

Use the connection settings from `.env`; PostgreSQL tools do not automatically load this file. Supply credentials through your PostgreSQL password file or interactive password prompt.

```sh
pg_dump -h 127.0.0.1 -U student_portal -d student_portal -Fc -f campus.dump
createdb -h 127.0.0.1 -U student_portal campus_restore_check
pg_restore -h 127.0.0.1 -U student_portal -d campus_restore_check --no-owner --exit-on-error campus.dump
```

Restore into an empty database. A custom-format dump from PostgreSQL 17 should be restored using a compatible PostgreSQL 17 or newer toolchain and server. Back up configuration and secrets separately; database dumps do not include `.env` or Docker configuration.
