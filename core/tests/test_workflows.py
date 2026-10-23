import csv
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from threading import Barrier
from unittest.mock import patch
from django.conf import settings
from django.contrib.admin.sites import site
from django.core import mail
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.db import IntegrityError, close_old_connections, connections, transaction
from django.http import Http404
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from accounts.models import User, StudentProfile
from accounts.services import review_student, set_user_active, save_user
from academics.forms import OfferingForm
from academics.models import CourseOffering, Enrollment, Course, Semester
from academics.services import enroll, withdraw, save_academic, archive_academic
from core.models import AuditEvent
from grading.models import Assessment, Grade, FinalGrade
from grading.services import (
    save_grades,
    save_assessment,
    grade_summary,
    publish_final,
    unpublish_final,
    clear_grade,
)
from reports.views import safe_cell
from .factories import make_user, make_academics, make_enrollment


class WorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = make_user("admin@example.com", "ADMIN")
        cls.teacher = make_user("teacher@example.com", "TEACHER")
        cls.other_teacher = make_user("otherteacher@example.com", "TEACHER")
        cls.student = make_user("student@example.com")
        cls.other = make_user("other@example.com")
        cls.pending = make_user("pending@example.com", approved=False)
        cls.offering, cls.assessment = make_academics(cls.teacher)
        cls.enrollment = make_enrollment(cls.student, cls.offering)

    def changes(self, value=8, assessment=None, enrollment=None, comment="Well done"):
        return [
            {
                "enrollment_id": (enrollment or self.enrollment).pk,
                "assessment_id": (assessment or self.assessment).pk,
                "value": value,
                "comment": comment,
            }
        ]

    def close_enrollment(self):
        self.offering.enrollment_end = timezone.now() - timedelta(days=1)
        self.offering.save()

    def publish(self):
        self.close_enrollment()
        save_grades(self.teacher, self.offering.pk, self.changes())
        return publish_final(self.teacher, self.offering.pk, self.enrollment.pk)

    def test_registration_and_role_escalation(self):
        data = {
            "first_name": "New",
            "last_name": "Student",
            "email": "NEW@example.com",
            "password1": "StrongTestPassword!62",
            "password2": "StrongTestPassword!62",
        }
        response = self.client.post(reverse("accounts:register"), {**data, "role": "ADMIN"})
        self.assertContains(response, "Account permissions cannot be set")
        self.assertFalse(User.objects.filter(email="new@example.com").exists())
        self.assertRedirects(
            self.client.post(reverse("accounts:register"), data),
            reverse("accounts:status"),
        )
        user = User.objects.get(email="new@example.com")
        self.assertEqual((user.role, user.approval_status), ("STUDENT", "PENDING"))

    def test_duplicate_email_is_case_insensitive(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user("STUDENT@EXAMPLE.COM", "password")

    def test_approval_assigns_stable_student_number(self):
        review_student(self.admin, self.pending.pk, True)
        number = StudentProfile.objects.get(user=self.pending).student_number
        review_student(self.admin, self.pending.pk, True)
        self.assertEqual(StudentProfile.objects.get(user=self.pending).student_number, number)
        self.assertNotEqual(number, self.student.student_profile.student_number)

    def test_rejection_requires_reason_and_can_be_reconsidered(self):
        with self.assertRaises(ValidationError):
            review_student(self.admin, self.pending.pk, False)
        review_student(self.admin, self.pending.pk, False, "Confirm your identity.")
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.approval_status, "REJECTED")
        review_student(self.admin, self.pending.pk, True)
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.approval_status, "APPROVED")

    def test_academic_history_cannot_be_rejected(self):
        with self.assertRaises(ValidationError):
            review_student(self.admin, self.student.pk, False, "A reason")

    def test_pending_access_and_direct_service_denial(self):
        self.client.force_login(self.pending)
        self.assertRedirects(
            self.client.get(reverse("student:catalog")), reverse("accounts:status")
        )
        with self.assertRaises(PermissionDenied):
            enroll(self.pending, self.offering.pk)

    def test_blocking_invalidates_existing_session_and_preserves_enrollment(self):
        self.client.force_login(self.student)
        set_user_active(self.admin, self.student.pk, False, "Account review")
        self.assertEqual(self.client.get(reverse("student:catalog")).status_code, 302)
        self.enrollment.refresh_from_db()
        self.assertEqual(self.enrollment.status, "ENROLLED")
        with self.assertRaises(PermissionDenied):
            enroll(self.student, self.offering.pk)

    def test_administrator_cannot_be_blocked(self):
        with self.assertRaises(ValidationError):
            set_user_active(self.admin, self.admin.pk, False, "A reason")

    def test_teacher_creation_and_profile_edit(self):
        teacher = save_user(
            self.admin,
            {
                "email": "newteacher@example.com",
                "first_name": "New",
                "last_name": "Teacher",
                "password1": "StrongTestPassword!62",
            },
        )
        self.assertEqual((teacher.role, teacher.approval_status), ("TEACHER", "APPROVED"))
        self.assertTrue(teacher.check_password("StrongTestPassword!62"))
        self.client.force_login(self.student)
        self.client.post(
            reverse("accounts:profile"),
            {
                "first_name": "Updated",
                "last_name": "Name",
                "email": "forged@example.com",
            },
        )
        self.student.refresh_from_db()
        self.assertEqual(self.student.email, "student@example.com")

    def test_all_role_dashboards_and_pages_render(self):
        pages = {
            self.admin: [
                "/management/",
                "/management/users/",
                "/management/users/new/",
                "/management/courses/",
                "/management/semesters/",
                "/management/offerings/",
                "/management/audit/",
                f"/management/offerings/{self.offering.pk}/gradebook/",
                "/management/offerings/new/",
            ],
            self.teacher: [
                "/teacher/",
                "/teacher/offerings/",
                f"/teacher/offerings/{self.offering.pk}/",
                f"/teacher/offerings/{self.offering.pk}/assessments/new/",
            ],
            self.student: [
                "/student/",
                "/student/catalog/",
                "/student/courses/",
                f"/student/offerings/{self.offering.pk}/",
                "/student/transcript/",
                "/accounts/profile/",
                "/accounts/password/change/",
            ],
        }
        for user, urls in pages.items():
            self.client.force_login(user)
            for url in urls:
                with self.subTest(role=user.role, url=url):
                    response = self.client.get(url)
                    self.assertEqual(response.status_code, 200)
                    self.assertContains(response, '<html lang="en">')

    def test_other_role_dashboard_is_forbidden(self):
        self.client.force_login(self.student)
        self.assertEqual(self.client.get("/teacher/").status_code, 403)
        self.assertEqual(self.client.get("/management/").status_code, 403)

    def test_teacher_cannot_access_other_offering(self):
        self.client.force_login(self.other_teacher)
        self.assertEqual(
            self.client.get(reverse("teacher:gradebook", args=[self.offering.pk])).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(reverse("teacher:export", args=[self.offering.pk])).status_code,
            404,
        )
        with self.assertRaises(Http404):
            save_grades(self.other_teacher, self.offering.pk, self.changes())

    def test_student_cannot_access_gradebooks_or_other_transcript(self):
        save_grades(self.teacher, self.offering.pk, self.changes(comment="Private feedback"))
        self.client.force_login(self.other)
        response = self.client.get(reverse("student:offering", args=[self.offering.pk]))
        self.assertNotContains(response, "Private feedback")
        self.assertEqual(
            self.client.get(reverse("teacher:gradebook", args=[self.offering.pk])).status_code,
            403,
        )
        response = self.client.get(
            reverse("student:transcript"), {"format": "csv", "student": self.student.pk}
        )
        self.assertNotIn(self.offering.course.title, response.content.decode())

    def test_enrollment_duplicate_and_capacity(self):
        with self.assertRaises(ValidationError):
            enroll(self.student, self.offering.pk)
        self.offering.capacity = 1
        self.offering.save()
        with self.assertRaises(ValidationError):
            enroll(self.other, self.offering.pk)

    def test_enrollment_window_draft_and_archived(self):
        self.close_enrollment()
        with self.assertRaises(ValidationError):
            enroll(self.other, self.offering.pk)
        for status in ["DRAFT", "ARCHIVED"]:
            self.offering.status = status
            self.offering.save()
            with self.assertRaises(ValidationError):
                enroll(self.other, self.offering.pk)

    def test_archived_semester_prevents_enrollment(self):
        Semester.objects.filter(pk=self.offering.semester_id).update(is_archived=True)
        with self.assertRaises(ValidationError):
            enroll(self.other, self.offering.pk)

    def test_withdrawal_and_reenrollment(self):
        withdraw(self.student, self.offering.pk)
        self.assertEqual(self.offering.enrolled_count, 0)
        enrollment = enroll(self.student, self.offering.pk)
        self.assertEqual(enrollment.pk, self.enrollment.pk)
        self.assertEqual(self.offering.enrolled_count, 1)

    def test_withdrawal_after_grading_is_rejected(self):
        save_grades(self.teacher, self.offering.pk, self.changes())
        with self.assertRaises(ValidationError):
            withdraw(self.student, self.offering.pk)

    def test_get_confirmation_does_not_enroll(self):
        self.client.force_login(self.other)
        url = reverse("student:enrollment_action", args=[self.offering.pk, "enroll"])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertFalse(Enrollment.objects.filter(student=self.other).exists())
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertTrue(Enrollment.objects.filter(student=self.other).exists())

    def test_csrf_protection_and_logout_method(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.other)
        url = reverse("student:enrollment_action", args=[self.offering.pk, "enroll"])
        self.assertEqual(client.post(url).status_code, 403)
        self.assertEqual(client.get(reverse("accounts:logout")).status_code, 405)

    def test_grade_bounds_and_fractional_values(self):
        for value in [0, 11, 7.5, True, "8"]:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                save_grades(self.teacher, self.offering.pk, self.changes(value))

    def test_grade_database_constraints(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Grade.objects.create(
                enrollment=self.enrollment,
                assessment=self.assessment,
                value=11,
                last_editor=self.teacher,
            )

    def test_grade_cannot_cross_offerings(self):
        other_offering, other_assessment = make_academics(self.teacher, "OTHER101")
        with self.assertRaises(Http404):
            save_grades(
                self.teacher,
                self.offering.pk,
                self.changes(assessment=other_assessment),
            )
        grade = Grade(
            enrollment=self.enrollment,
            assessment=other_assessment,
            value=8,
            last_editor=self.teacher,
        )
        with self.assertRaises(ValidationError):
            grade.full_clean()

    def test_batch_grade_write_rolls_back_on_any_invalid_cell(self):
        assessment = Assessment.objects.create(offering=self.offering, title="Second assessment")
        with self.assertRaises(ValidationError):
            save_grades(
                self.teacher,
                self.offering.pk,
                self.changes(8) + self.changes(11, assessment=assessment),
            )
        self.assertFalse(Grade.objects.exists())
        self.assertFalse(AuditEvent.objects.exists())

    def test_missing_grades_are_not_zero(self):
        Assessment.objects.create(offering=self.offering, title="Second assessment")
        save_grades(self.teacher, self.offering.pk, self.changes(8))
        summary = grade_summary(self.enrollment)
        self.assertEqual(summary["average"], Decimal("8.00"))
        self.assertEqual(summary["missing"], 1)
        self.close_enrollment()
        with self.assertRaises(ValidationError):
            publish_final(self.teacher, self.offering.pk, self.enrollment.pk)

    def test_final_requires_closed_enrollment_and_assessments(self):
        save_grades(self.teacher, self.offering.pk, self.changes())
        with self.assertRaises(ValidationError):
            publish_final(self.teacher, self.offering.pk, self.enrollment.pk)
        self.close_enrollment()
        Grade.objects.all().delete()
        self.assessment.delete()
        with self.assertRaises(ValidationError):
            publish_final(self.teacher, self.offering.pk, self.enrollment.pk)

    def test_half_up_rounding_and_final_snapshot(self):
        self.close_enrollment()
        assessment = Assessment.objects.create(offering=self.offering, title="Second assessment")
        save_grades(
            self.teacher,
            self.offering.pk,
            self.changes(7) + self.changes(8, assessment=assessment),
        )
        final = publish_final(self.teacher, self.offering.pk, self.enrollment.pk)
        self.assertEqual(final.value, 8)
        self.assertEqual(final.average_snapshot, Decimal("7.5"))

    def test_publication_locks_grades_and_assessments(self):
        self.publish()
        with self.assertRaises(ValidationError):
            save_grades(self.teacher, self.offering.pk, self.changes(9))
        with self.assertRaises(ValidationError):
            publish_final(self.teacher, self.offering.pk, self.enrollment.pk)
        with self.assertRaises(ValidationError):
            save_assessment(
                self.teacher,
                self.offering.pk,
                {
                    "title": "New",
                    "description": "",
                    "due_date": None,
                    "display_order": 2,
                },
            )

    def test_unpublish_correct_and_republish(self):
        final = self.publish()
        with self.assertRaises(PermissionDenied):
            unpublish_final(self.teacher, self.offering.pk, self.enrollment.pk, "A reason")
        with self.assertRaises(ValidationError):
            unpublish_final(self.admin, self.offering.pk, self.enrollment.pk, "")
        unpublish_final(self.admin, self.offering.pk, self.enrollment.pk, "Correct an entry error.")
        save_grades(self.teacher, self.offering.pk, self.changes(9))
        republished = publish_final(self.teacher, self.offering.pk, self.enrollment.pk)
        self.assertEqual(republished.pk, final.pk)
        self.assertEqual(republished.value, 9)
        self.assertTrue(
            AuditEvent.objects.filter(
                action="Final grade unpublished", reason="Correct an entry error."
            ).exists()
        )

    def test_admin_clear_grade_requires_reason_and_unpublished_final(self):
        self.publish()
        grade = Grade.objects.get()
        with self.assertRaises(ValidationError):
            clear_grade(self.admin, self.offering.pk, grade.pk, "Correct an error")
        unpublish_final(self.admin, self.offering.pk, self.enrollment.pk, "Correction")
        with self.assertRaises(ValidationError):
            clear_grade(self.admin, self.offering.pk, grade.pk, "")
        clear_grade(self.admin, self.offering.pk, grade.pk, "Wrong student")
        self.assertFalse(Grade.objects.exists())

    def test_assessment_with_grades_cannot_be_deleted(self):
        save_grades(self.teacher, self.offering.pk, self.changes())
        with self.assertRaises(ValidationError):
            save_assessment(self.teacher, self.offering.pk, {}, self.assessment.pk, delete=True)

    def test_audit_failure_rolls_back_grade_and_approval(self):
        with patch("grading.services.audit", side_effect=RuntimeError("Audit failure")):
            with self.assertRaises(RuntimeError):
                save_grades(self.teacher, self.offering.pk, self.changes())
        self.assertFalse(Grade.objects.exists())
        with patch("accounts.services.audit", side_effect=RuntimeError("Audit failure")):
            with self.assertRaises(RuntimeError):
                review_student(self.admin, self.pending.pk, True)
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.approval_status, "PENDING")
        self.assertFalse(StudentProfile.objects.filter(user=self.pending).exists())

    def test_archiving_requires_finals_and_makes_records_read_only(self):
        self.close_enrollment()
        with self.assertRaises(ValidationError):
            archive_academic(self.admin, "offerings", self.offering.pk)
        self.publish()
        archive_academic(self.admin, "offerings", self.offering.pk)
        for operation in [
            lambda: save_grades(self.teacher, self.offering.pk, self.changes()),
            lambda: unpublish_final(self.admin, self.offering.pk, self.enrollment.pk, "Correction"),
        ]:
            with self.assertRaises(ValidationError):
                operation()
        self.client.force_login(self.student)
        self.assertEqual(
            self.client.get(reverse("student:offering", args=[self.offering.pk])).status_code,
            200,
        )
        self.client.force_login(self.other)
        self.assertEqual(
            self.client.get(reverse("student:offering", args=[self.offering.pk])).status_code,
            404,
        )

    def test_semester_cannot_archive_before_offerings(self):
        with self.assertRaises(ValidationError):
            archive_academic(self.admin, "semesters", self.offering.semester_id)

    def test_offering_edits_reject_capacity_reduction_and_published_finals(self):
        data = {field: getattr(self.offering, field) for field in OfferingForm.Meta.fields}
        make_enrollment(self.other, self.offering)
        data["capacity"] = 1
        with self.assertRaises(ValidationError):
            save_academic(self.admin, "offerings", data, self.offering.pk)
        data["capacity"] = 10
        self.publish()
        with self.assertRaises(ValidationError):
            save_academic(self.admin, "offerings", data, self.offering.pk)

    def test_batch_gradebook_form_and_invalid_post(self):
        self.client.force_login(self.teacher)
        url = reverse("teacher:gradebook", args=[self.offering.pk])
        data = {
            "form-TOTAL_FORMS": "1",
            "form-INITIAL_FORMS": "1",
            "form-MIN_NUM_FORMS": "0",
            "form-MAX_NUM_FORMS": "5000",
            "form-0-enrollment_id": self.enrollment.pk,
            "form-0-assessment_id": self.assessment.pk,
            "form-0-value": "8",
            "form-0-comment": "Clear reasoning",
        }
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertEqual(Grade.objects.get().value, 8)
        data["form-0-value"] = "7.5"
        self.assertContains(self.client.post(url, data), "No changes have been saved")
        self.assertEqual(Grade.objects.get().value, 8)
        data["form-0-assessment_id"] = 999999
        data["form-0-value"] = "9"
        self.assertEqual(self.client.post(url, data).status_code, 404)

    def test_teacher_gradebook_cannot_clear_existing_grade(self):
        save_grades(self.teacher, self.offering.pk, self.changes())
        self.client.force_login(self.teacher)
        data = {
            "form-TOTAL_FORMS": "1",
            "form-INITIAL_FORMS": "1",
            "form-0-enrollment_id": self.enrollment.pk,
            "form-0-assessment_id": self.assessment.pk,
            "form-0-value": "",
            "form-0-comment": "",
        }
        response = self.client.post(reverse("teacher:gradebook", args=[self.offering.pk]), data)
        self.assertContains(response, "Only an administrator can clear")
        self.assertEqual(Grade.objects.count(), 1)

    def test_csv_export_and_formula_neutralization(self):
        for value in [
            "=1+1",
            "+SUM(A1)",
            "-1+2",
            "@SUM(A1)",
            "  =1+1",
            "\ttext",
            "\rtext",
            "\ntext",
        ]:
            self.assertTrue(safe_cell(value).startswith("'"))
        self.student.first_name = "=HYPERLINK(1)"
        self.student.save()
        self.client.force_login(self.teacher)
        response = self.client.get(reverse("teacher:export", args=[self.offering.pk]))
        self.assertEqual(response.status_code, 200)
        rows = list(csv.reader(StringIO(response.content.decode())))
        self.assertTrue(rows[1][1].startswith("'="))

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_password_reset_email_is_english_and_has_working_route(self):
        response = self.client.post(
            reverse("accounts:password_reset"), {"email": self.student.email}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Reset your Campus password", mail.outbox[0].subject)
        self.assertIn("/accounts/password/reset/", mail.outbox[0].body)

    def test_technical_admin_disallows_academic_mutations(self):
        request = type("Request", (), {"user": self.admin})()
        for model in [
            User,
            Course,
            CourseOffering,
            Semester,
            Enrollment,
            Assessment,
            Grade,
            FinalGrade,
            AuditEvent,
        ]:
            model_admin = site._registry[model]
            self.assertFalse(model_admin.has_add_permission(request))
            self.assertFalse(model_admin.has_change_permission(request))
            self.assertFalse(model_admin.has_delete_permission(request))

    def test_health_check(self):
        self.assertEqual(self.client.get("/health/").json(), {"status": "ok"})

    def test_complete_registration_to_final_grade_journey(self):
        password = "StrongJourneyPassword!62"
        self.client.post(
            reverse("accounts:register"),
            {
                "first_name": "Journey",
                "last_name": "Student",
                "email": "journey@example.com",
                "password1": password,
                "password2": password,
            },
        )
        student = User.objects.get(email="journey@example.com")
        self.client.force_login(self.admin)
        self.assertEqual(
            self.client.post(
                reverse("management:user_action", args=[student.pk, "approve"])
            ).status_code,
            302,
        )
        self.client.force_login(student)
        self.assertEqual(
            self.client.post(
                reverse("student:enrollment_action", args=[self.offering.pk, "enroll"])
            ).status_code,
            302,
        )
        enrollment = Enrollment.objects.get(student=student, offering=self.offering)
        self.close_enrollment()
        self.client.force_login(self.teacher)
        response = self.client.get(reverse("teacher:gradebook", args=[self.offering.pk]))
        formset = response.context["formset"]
        data = {
            "form-TOTAL_FORMS": str(len(formset.forms)),
            "form-INITIAL_FORMS": str(len(formset.forms)),
        }
        for index, form in enumerate(formset.forms):
            for key, value in form.initial.items():
                data[f"form-{index}-{key}"] = "" if value is None else value
            if form.initial["enrollment_id"] == enrollment.pk:
                data[f"form-{index}-value"] = "9"
                data[f"form-{index}-comment"] = "Excellent understanding."
        self.assertEqual(
            self.client.post(
                reverse("teacher:gradebook", args=[self.offering.pk]), data
            ).status_code,
            302,
        )
        self.assertEqual(
            self.client.post(
                reverse("teacher:publish", args=[self.offering.pk, enrollment.pk])
            ).status_code,
            302,
        )
        self.client.force_login(student)
        response = self.client.get(reverse("student:offering", args=[self.offering.pk]))
        self.assertContains(response, "Excellent understanding.")
        self.assertContains(response, "Published final grade")
        self.assertEqual(FinalGrade.objects.get(enrollment=enrollment).value, 9)
        export = self.client.get(reverse("student:transcript"), {"format": "csv"})
        self.assertIn(self.offering.course.title, export.content.decode())

    @override_settings(DEBUG=False)
    def test_error_pages_render(self):
        self.client.force_login(self.student)
        self.assertContains(
            self.client.get("/does-not-exist/"),
            "This page could not be found",
            status_code=404,
        )
        self.assertContains(
            self.client.get("/management/users/"),
            "Access is restricted",
            status_code=403,
        )


class ConcurrentEnrollmentTests(TransactionTestCase):
    def test_two_students_compete_for_one_remaining_place(self):
        teacher = make_user("teacher@example.com", "TEACHER")
        students = [make_user("one@example.com"), make_user("two@example.com")]
        offering, _ = make_academics(teacher, capacity=1)
        barrier = Barrier(2)

        def attempt(student):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try:
                    enroll(student, offering.pk)
                    return "enrolled"
                except ValidationError:
                    return "full"
            finally:
                connections["default"].close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(attempt, students))
        self.assertCountEqual(results, ["enrolled", "full"])
        self.assertEqual(Enrollment.objects.filter(offering=offering, status="ENROLLED").count(), 1)


class DemonstrationTests(TestCase):
    def test_seeding_is_repeatable_and_contains_required_scenarios(self):
        output = StringIO()
        call_command("seed_demo", stdout=output)
        counts = (
            User.objects.count(),
            Enrollment.objects.count(),
            Grade.objects.count(),
            AuditEvent.objects.count(),
        )
        call_command("seed_demo", stdout=output)
        self.assertEqual(
            counts,
            (
                User.objects.count(),
                Enrollment.objects.count(),
                Grade.objects.count(),
                AuditEvent.objects.count(),
            ),
        )
        self.assertEqual(
            User.objects.filter(role="STUDENT", approval_status="APPROVED").count(), 12
        )
        self.assertEqual(User.objects.filter(approval_status="PENDING").count(), 2)
        self.assertEqual(User.objects.filter(approval_status="REJECTED").count(), 1)
        self.assertEqual(CourseOffering.objects.count(), 4)
        self.assertEqual(CourseOffering.objects.filter(status="ARCHIVED").count(), 1)
        full = CourseOffering.objects.get(course__code="MA201")
        self.assertEqual(full.available_places, 0)

    def test_project_authored_content_is_english(self):
        self.assertEqual(settings.LANGUAGE_CODE, "en-us")
        roots = [
            "accounts",
            "academics",
            "grading",
            "reports",
            "core",
            "config",
            "templates",
        ]
        paths = [
            path
            for root in roots
            for path in (settings.BASE_DIR / root).rglob("*")
            if path.suffix in [".py", ".html", ".txt"]
        ]
        paths.extend((settings.BASE_DIR / "docs").glob("*.md"))
        paths.append(settings.BASE_DIR / "README.md")
        for path in paths:
            if not path.exists():
                continue
            text = path.read_text()
            self.assertFalse(
                any("\u0400" <= character <= "\u04ff" for character in text),
                str(path.relative_to(settings.BASE_DIR)),
            )
