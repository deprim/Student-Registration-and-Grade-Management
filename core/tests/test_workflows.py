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


class CatalogAvailabilityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.teacher = make_user("teacher@example.com", "TEACHER")
        cls.student = make_user("student@example.com")
        cls.other = make_user("other@example.com")
        cls.open_offering, _ = make_academics(cls.teacher, "OPEN101")
        cls.full_offering, _ = make_academics(cls.teacher, "FULL101", capacity=1)
        cls.closed_offering, _ = make_academics(cls.teacher, "CLOSED101", open_enrollment=False)
        make_enrollment(cls.other, cls.full_offering)

    def labels(self, student):
        self.client.force_login(student)
        response = self.client.get(reverse("student:catalog"))
        return {
            offering.course.code: offering.availability
            for offering in response.context["page_obj"]
        }

    def test_open_offering(self):
        self.assertEqual(self.labels(self.student)["OPEN101"], "Open for enrollment")

    def test_full_offering(self):
        self.assertEqual(self.labels(self.student)["FULL101"], "Enrollment full")

    def test_closed_offering(self):
        self.assertEqual(self.labels(self.student)["CLOSED101"], "Enrollment closed")

    def test_enrolled_status_takes_priority(self):
        make_enrollment(self.student, self.closed_offering)
        self.assertEqual(self.labels(self.student)["CLOSED101"], "You are enrolled")
        self.assertEqual(self.labels(self.other)["FULL101"], "You are enrolled")

    def test_withdrawn_enrollment_is_not_shown_as_enrolled(self):
        enrollment = make_enrollment(self.student, self.open_offering)
        enrollment.status = Enrollment.Status.WITHDRAWN
        enrollment.save()
        self.assertEqual(self.labels(self.student)["OPEN101"], "Open for enrollment")

    def test_catalog_renders_each_status_and_other_pages_keep_status_badge(self):
        make_enrollment(self.student, self.open_offering)
        self.client.force_login(self.student)
        response = self.client.get(reverse("student:catalog"))
        for label in ["You are enrolled", "Enrollment full", "Enrollment closed"]:
            self.assertContains(response, label)
        my_courses = self.client.get(reverse("student:courses"))
        self.assertContains(my_courses, "Active")
        self.assertNotContains(my_courses, "You are enrolled")
        self.client.force_login(self.other)
        self.assertContains(self.client.get(reverse("student:catalog")), "Open for enrollment")


class UserGuidanceTests(TestCase):
    """Presentation guidance: labels, next steps and explanations. Rules stay in services."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = make_user("admin@example.com", "ADMIN")
        cls.teacher = make_user("teacher@example.com", "TEACHER")
        cls.student = make_user("student@example.com")
        cls.other = make_user("other@example.com")
        cls.pending = make_user("pending@example.com", approved=False)
        cls.offering, cls.assessment = make_academics(cls.teacher)
        cls.enrollment = make_enrollment(cls.student, cls.offering)

    def get(self, user, url, **params):
        self.client.force_login(user)
        return self.client.get(url, params)

    def grade(self, value=8, assessment=None):
        save_grades(
            self.teacher,
            self.offering.pk,
            [
                {
                    "enrollment_id": self.enrollment.pk,
                    "assessment_id": (assessment or self.assessment).pk,
                    "value": value,
                    "comment": "",
                }
            ],
        )

    def close_enrollment(self):
        self.offering.enrollment_end = timezone.now() - timedelta(days=1)
        self.offering.save()

    def test_dashboard_title_is_well_formed(self):
        content = self.get(self.admin, "/management/").content.decode()
        title = content.split("<title>")[1].split("</title>")[0]
        self.assertNotIn("</div>", title)
        self.assertIn("Overview", title)

    def test_admin_dashboard_links_to_pending_applications(self):
        response = self.get(self.admin, "/management/")
        pending_url = f"{reverse('management:users')}?status=PENDING"
        self.assertContains(response, f'href="{pending_url}"')
        self.assertContains(response, "Review 1 application")
        self.assertContains(response, "1 student application waiting for review.")
        self.assertContains(response, f'href="{reverse("management:users")}?role=TEACHER"')

    def test_dashboard_next_steps_are_role_specific(self):
        self.assertContains(
            self.get(self.teacher, "/teacher/"),
            "Open a course to add assessments and enter grades.",
        )
        self.assertContains(
            self.get(self.student, "/student/"), "You are enrolled in 1 current course."
        )
        response = self.get(self.other, "/student/")
        self.assertContains(response, "You are not enrolled in any course yet.")
        self.assertContains(response, reverse("student:catalog"))
        self.assertContains(response, "Courses you are enrolled in, including past semesters.")

    def test_teacher_dashboard_counts_finals_still_to_publish(self):
        self.close_enrollment()
        response = self.get(self.teacher, "/teacher/")
        self.assertContains(
            response, "1 student in closed courses still needs a published final grade."
        )
        self.assertContains(response, "Finals still to publish")

    def test_admin_navigation_follows_setup_order(self):
        content = self.get(self.admin, reverse("management:users")).content.decode()
        labels = ["Semesters</a>", "Course library</a>", "Course offerings</a>"]
        positions = [content.index(label) for label in labels]
        self.assertEqual(positions, sorted(positions))

    def test_academic_pages_explain_the_structure(self):
        expectations = {
            "semesters": ("Semesters", "named teaching period"),
            "courses": ("Course library", "permanent course descriptions"),
            "offerings": ("Course offerings", "taught in one semester by one teacher"),
        }
        for kind, (title, phrase) in expectations.items():
            with self.subTest(kind=kind):
                response = self.get(self.admin, reverse("management:academic_list", args=[kind]))
                self.assertContains(response, f"<h1>{title}</h1>", html=True)
                self.assertContains(response, phrase)
                self.assertContains(response, 'aria-current="page"')
        response = self.get(self.admin, reverse("management:academic_list", args=["offerings"]))
        self.assertContains(response, "Enrollment")
        self.assertContains(response, "Closes ")
        self.assertNotContains(response, "Before you create a course offering")

    def test_offering_form_has_sections_and_help_text(self):
        response = self.get(self.admin, reverse("management:academic_create", args=["offerings"]))
        self.assertContains(response, "<legend")
        self.assertContains(response, "Draft offerings are hidden from students")
        self.assertContains(response, "Teachers can publish final grades only after enrollment")
        self.assertContains(response, "Create course offering")

    def test_assessment_form_explains_display_order(self):
        response = self.get(
            self.teacher, reverse("teacher:assessment_create", args=[self.offering.pk])
        )
        self.assertContains(response, "Lower numbers appear first")

    def test_action_specific_success_messages(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("management:user_action", args=[self.pending.pk, "approve"]), follow=True
        )
        self.assertContains(response, "has been approved. Student number: STU-")
        self.client.force_login(self.other)
        response = self.client.post(
            reverse("student:enrollment_action", args=[self.offering.pk, "enroll"]), follow=True
        )
        self.assertContains(response, f"You are enrolled in {self.offering.course.title}.")

    def test_confirmation_pages_explain_consequences(self):
        expectations = {
            (self.pending, "approve"): "A permanent student number is assigned.",
            (self.pending, "reject"): "Shown to the student.",
            (self.student, "block"): "The user is signed out immediately",
        }
        for (person, action), text in expectations.items():
            with self.subTest(action=action):
                response = self.get(
                    self.admin, reverse("management:user_action", args=[person.pk, action])
                )
                self.assertContains(response, text)
        archive_url = reverse("management:academic_archive", args=["offerings", self.offering.pk])
        response = self.get(self.admin, archive_url)
        self.assertContains(response, "every enrolled student has a published final grade")

    def test_course_detail_back_link_and_withdrawal_explanation(self):
        url = reverse("student:offering", args=[self.offering.pk])
        response = self.get(self.other, url)
        self.assertContains(response, "Back to course catalog")
        self.assertContains(response, "Enrollment is open")
        response = self.get(self.student, url)
        self.assertContains(response, "Back to my courses")
        self.assertContains(response, "Withdraw from course")
        self.grade()
        response = self.get(self.student, url)
        self.assertNotContains(response, "Withdraw from course")
        self.assertContains(response, "grades have already been recorded")
        self.assertContains(response, "Not yet published")

    def test_catalog_filter_hides_archived_semesters_only(self):
        Semester.objects.create(
            name="Old semester",
            start_date=timezone.localdate() - timedelta(days=400),
            end_date=timezone.localdate() - timedelta(days=300),
            is_archived=True,
        )
        self.assertNotContains(self.get(self.student, reverse("student:catalog")), "Old semester")
        self.assertContains(self.get(self.student, reverse("student:courses")), "Old semester")
        self.assertContains(self.get(self.student, reverse("student:transcript")), "Old semester")

    def test_rejected_applicant_sees_next_steps(self):
        review_student(self.admin, self.pending.pk, False, "Confirm your identity.")
        response = self.get(self.pending, reverse("accounts:status"))
        self.assertContains(response, "Confirm your identity.")
        self.assertContains(response, "You do not need to register again.")

    def test_gradebook_explains_why_a_final_cannot_be_published(self):
        url = reverse("teacher:gradebook", args=[self.offering.pk])
        publish_url = reverse("teacher:publish", args=[self.offering.pk, self.enrollment.pk])
        self.grade()
        response = self.get(self.teacher, url)
        self.assertContains(response, "Available after enrollment closes on")
        self.assertNotContains(response, publish_url)
        self.assertNotContains(response, "Proposed:")
        self.close_enrollment()
        second = Assessment.objects.create(offering=self.offering, title="Exam")
        response = self.get(self.teacher, url)
        self.assertContains(response, "1 grade not yet entered.")
        self.assertNotContains(response, publish_url)
        self.grade(9, assessment=second)
        response = self.get(self.teacher, url)
        self.assertContains(response, publish_url)
        self.assertContains(response, "Publish final grade")

    def test_gradebook_locks_assessment_actions_after_publication(self):
        self.close_enrollment()
        self.grade()
        publish_final(self.teacher, self.offering.pk, self.enrollment.pk)
        response = self.get(self.teacher, reverse("teacher:gradebook", args=[self.offering.pk]))
        self.assertContains(response, "Assessments are locked")
        self.assertNotContains(
            response, reverse("teacher:assessment_create", args=[self.offering.pk])
        )
        response = self.get(self.admin, reverse("management:gradebook", args=[self.offering.pk]))
        self.assertContains(response, "Only the assigned teacher can enter grades")
        self.assertContains(response, "Unpublish")

    def test_transcript_uses_clear_wording(self):
        response = self.get(self.student, reverse("student:transcript"))
        self.assertContains(response, "Not yet graded")
        self.assertContains(response, "Not yet published")
        self.assertContains(response, "When do final grades appear?")
        self.assertNotContains(response, "Missing grades")


class EmptySystemGuidanceTests(TestCase):
    def test_offering_pages_list_missing_prerequisites(self):
        admin = make_user("admin@example.com", "ADMIN")
        self.client.force_login(admin)
        for url in [
            reverse("management:academic_list", args=["offerings"]),
            reverse("management:academic_create", args=["offerings"]),
        ]:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertContains(response, "Before you create a course offering")
                self.assertContains(response, "Create semester →")
                self.assertContains(response, "Create teacher →")
        response = self.client.get("/management/")
        self.assertContains(response, "Start by creating a semester.")


class VisualRefreshTests(TestCase):
    """The TSI-inspired refresh: project notice and no decorative numbering."""

    @classmethod
    def setUpTestData(cls):
        cls.student = make_user("student@example.com")
        cls.offering, _ = make_academics(make_user("teacher@example.com", "TEACHER"))

    def test_footer_states_this_is_a_student_project(self):
        notice = "Campus is a student group project, not an official TSI service."
        self.assertContains(self.client.get(reverse("accounts:login")), notice)
        self.client.force_login(self.student)
        self.assertContains(self.client.get(reverse("student:dashboard")), notice)

    def test_catalog_and_dashboard_have_no_decorative_numbering(self):
        self.client.force_login(self.student)
        catalog = self.client.get(reverse("student:catalog"))
        self.assertContains(catalog, self.offering.course.title)
        self.assertNotContains(catalog, "course-index")
        self.assertNotContains(self.client.get(reverse("student:dashboard")), "stat-index")


class FunctionalQATests(TestCase):
    """Access matrix, real sign-in, enrollment boundaries, audit actors and CSV routes."""

    password = "StrongTestPassword!62"

    @classmethod
    def setUpTestData(cls):
        cls.admin = make_user("admin@example.com", "ADMIN")
        cls.teacher = make_user("teacher@example.com", "TEACHER")
        cls.student = make_user("student@example.com")
        cls.pending = make_user("pending@example.com", approved=False)
        cls.offering, cls.assessment = make_academics(cls.teacher)
        cls.enrollment = make_enrollment(cls.student, cls.offering)

    def set_window(self, start_days, end_days):
        now = timezone.now()
        CourseOffering.objects.filter(pk=self.offering.pk).update(
            enrollment_start=now + timedelta(days=start_days),
            enrollment_end=now + timedelta(days=end_days),
        )

    def sign_in(self, email):
        self.client.logout()
        return self.client.post(
            reverse("accounts:login"),
            {"username": email, "password": self.password},
            follow=True,
        )

    def test_anonymous_users_are_sent_to_login(self):
        pk = self.offering.pk
        for url in [
            "/",
            "/student/",
            "/student/catalog/",
            "/student/transcript/",
            "/teacher/",
            f"/teacher/offerings/{pk}/",
            "/management/",
            "/management/users/",
            "/management/audit/",
            f"/management/offerings/{pk}/gradebook/",
        ]:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response.url.startswith(reverse("accounts:login")))

    def test_cross_role_pages_are_forbidden(self):
        pk = self.offering.pk
        matrix = {
            self.teacher: [
                reverse("management:dashboard"),
                reverse("management:users"),
                reverse("management:audit"),
                reverse("management:academic_list", args=["semesters"]),
                reverse("management:gradebook", args=[pk]),
                reverse("management:export", args=[pk]),
            ],
            self.admin: [
                reverse("teacher:dashboard"),
                reverse("teacher:gradebook", args=[pk]),
                reverse("teacher:assessment_create", args=[pk]),
                reverse("teacher:export", args=[pk]),
            ],
        }
        for user, urls in matrix.items():
            self.client.force_login(user)
            for url in urls:
                with self.subTest(role=user.role, url=url):
                    self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.admin)
        response = self.client.post(reverse("management:gradebook", args=[pk]), {})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Grade.objects.exists())

    def test_sign_in_with_uppercase_email_reaches_dashboard(self):
        response = self.sign_in("STUDENT@EXAMPLE.COM")
        self.assertEqual(response.redirect_chain[-1][0], reverse("student:dashboard"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.student.pk)

    def test_pending_rejected_and_blocked_sign_in_outcomes(self):
        response = self.sign_in("pending@example.com")
        self.assertEqual(response.redirect_chain[-1][0], reverse("accounts:status"))
        self.assertContains(response, "Pending approval")

        rejected = make_user("rejected@example.com", approved=False)
        review_student(self.admin, rejected.pk, False, "Confirm your identity.")
        response = self.sign_in("rejected@example.com")
        self.assertEqual(response.redirect_chain[-1][0], reverse("accounts:status"))
        self.assertContains(response, "Confirm your identity.")

        set_user_active(self.admin, self.student.pk, False, "Account review")
        response = self.sign_in("student@example.com")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_enrollment_window_boundaries(self):
        other = make_user("other@example.com")
        self.set_window(1, 5)
        with self.assertRaises(ValidationError):
            enroll(other, self.offering.pk)
        self.assertFalse(Enrollment.objects.filter(student=other).exists())
        self.set_window(-10, -1)
        with self.assertRaises(ValidationError):
            withdraw(self.student, self.offering.pk)
        self.enrollment.refresh_from_db()
        self.assertEqual(self.enrollment.status, "ENROLLED")

    def test_main_journey_records_audit_actor_and_action(self):
        review_student(self.admin, self.pending.pk, True)
        enrollment = enroll(self.pending, self.offering.pk)
        change = {
            "enrollment_id": enrollment.pk,
            "assessment_id": self.assessment.pk,
            "value": 8,
            "comment": "",
        }
        save_grades(self.teacher, self.offering.pk, [change])
        self.set_window(-10, -1)
        final = publish_final(self.teacher, self.offering.pk, enrollment.pk)
        grade = Grade.objects.get(enrollment=enrollment)
        expected = [
            ("Student approved", self.admin, f"accounts.User:{self.pending.pk}"),
            ("Student enrolled", self.pending, f"academics.Enrollment:{enrollment.pk}"),
            ("Assessment grade saved", self.teacher, f"grading.Grade:{grade.pk}"),
            ("Final grade published", self.teacher, f"grading.FinalGrade:{final.pk}"),
        ]
        for action, actor, target in expected:
            with self.subTest(action=action):
                event = AuditEvent.objects.get(action=action, target=target)
                self.assertEqual(event.actor_id, actor.pk)

    def test_admin_gradebook_csv_and_transcript_semester_filter(self):
        save_grades(
            self.teacher,
            self.offering.pk,
            [
                {
                    "enrollment_id": self.enrollment.pk,
                    "assessment_id": self.assessment.pk,
                    "value": 8,
                    "comment": "",
                }
            ],
        )
        self.client.force_login(self.admin)
        response = self.client.get(reverse("management:export", args=[self.offering.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Type"].startswith("text/csv"))
        rows = list(csv.reader(StringIO(response.content.decode())))
        self.assertEqual(rows[0][0], "Student number")
        self.assertEqual(rows[1][0], self.student.student_profile.student_number)
        self.assertIn("8", rows[1])

        now = timezone.now()
        spring = Semester.objects.create(
            name="Spring term",
            start_date=now.date() - timedelta(days=30),
            end_date=now.date() + timedelta(days=90),
        )
        other = CourseOffering.objects.create(
            course=Course.objects.create(code="OTHER201", title="Other course"),
            semester=spring,
            teacher=self.teacher,
            capacity=5,
            status="ACTIVE",
            enrollment_start=now - timedelta(days=10),
            enrollment_end=now + timedelta(days=10),
        )
        make_enrollment(self.student, other)
        self.client.force_login(self.student)
        response = self.client.get(
            reverse("student:transcript"), {"format": "csv", "semester": spring.pk}
        )
        content = response.content.decode()
        self.assertIn("Other course", content)
        self.assertNotIn(self.offering.course.title, content)


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
            text = path.read_text(encoding="utf-8")
            self.assertFalse(
                any("\u0400" <= character <= "\u04ff" for character in text),
                str(path.relative_to(settings.BASE_DIR)),
            )
