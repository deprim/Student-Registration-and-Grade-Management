"""Playwright end-to-end scenarios for Campus.

Run (Windows, repository root):
    .venv\\Scripts\\python.exe manage.py test e2e --pattern="e2e_*.py" -v 2

The Django test runner creates and destroys the isolated test database; the browser only talks to
Django's live test server, never to the development database. Starting data is created before
Playwright starts, because Playwright's sync API keeps an asyncio loop running in this thread and
Django refuses database calls while it runs. Test bodies therefore check results through the UI.
"""

import os
import re
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.utils import timezone
from playwright.sync_api import expect, sync_playwright

from academics.models import CourseOffering
from core.tests.factories import make_academics, make_enrollment, make_user
from grading.services import publish_final, save_grades

PASSWORD = "StrongTestPassword!62"  # password used by core.tests.factories.make_user
SCREENSHOTS = Path(settings.BASE_DIR) / "test-results" / "e2e"


def local_input(delta):
    """A datetime-local field value in the application's time zone."""
    return timezone.localtime(timezone.now() + delta).strftime("%Y-%m-%dT%H:%M")


def field(page, label):
    """A form field by its visible label, with or without the required-field asterisk."""
    return page.get_by_label(re.compile(rf"^\s*{re.escape(label)}\s*\*?\s*$"))


class CampusE2ETestCase(StaticLiveServerTestCase):
    """Starts Chromium per test, after the test data has been created."""

    def prepare(self):
        """Create starting data. Runs before Playwright starts."""

    def setUp(self):
        self.prepare()
        self.unexpected_dialogs = []
        self.playwright = sync_playwright().start()
        headed = os.environ.get("E2E_HEADED") == "1"
        self.browser = self.playwright.chromium.launch(
            headless=not headed, slow_mo=250 if headed else 0
        )

    def tearDown(self):
        self.browser.close()
        self.playwright.stop()
        self.assertEqual(self.unexpected_dialogs, [], "Unexpected browser dialogs")

    def on_dialog(self, dialog):
        # The gradebook warns before leaving with unsaved grades; that is the only expected dialog.
        if dialog.type == "beforeunload":
            dialog.accept()
        else:
            self.unexpected_dialogs.append(f"{dialog.type}: {dialog.message}")
            dialog.dismiss()

    def new_page(self):
        page = self.browser.new_context(viewport={"width": 1280, "height": 900}).new_page()
        page.on("dialog", self.on_dialog)
        return page

    def url(self, path):
        return f"{self.live_server_url}{path}"

    def sign_in(self, email):
        page = self.new_page()
        page.goto(self.url("/accounts/login/"))
        field(page, "Email").fill(email)
        field(page, "Password").fill(PASSWORD)
        page.get_by_role("button", name="Sign in to your workspace").click()
        expect(page).not_to_have_url(re.compile(r"/accounts/login/"))
        return page

    def confirm(self, page):
        page.get_by_role("button", name="Confirm action").click()

    def expect_success(self, page, text):
        expect(page.locator(".alert-success").first).to_contain_text(text)

    def shot(self, page, name):
        SCREENSHOTS.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=SCREENSHOTS / f"{name}.png", full_page=True)


class E2E01AcademicLifecycle(CampusE2ETestCase):
    def prepare(self):
        make_user("admin@example.com", "ADMIN")
        make_user("teacher@example.com", "TEACHER")

    def test_complete_academic_lifecycle(self):
        """E2E-01: setup, registration, approval, enrollment, grading, publication, transcript."""
        today = timezone.localdate()
        admin = self.sign_in("admin@example.com")

        admin.goto(self.url("/management/semesters/new/"))
        field(admin, "Name").fill("E2E semester")
        field(admin, "Start date").fill(str(today - timedelta(days=30)))
        field(admin, "End date").fill(str(today + timedelta(days=60)))
        admin.get_by_role("button", name="Save changes").click()
        self.expect_success(admin, "Semester saved.")

        admin.goto(self.url("/management/courses/new/"))
        field(admin, "Code").fill("E2E101")
        field(admin, "Title").fill("End-to-end testing")
        admin.get_by_role("button", name="Save changes").click()
        self.expect_success(admin, "Library course saved.")

        admin.goto(self.url("/management/offerings/new/"))
        field(admin, "Course").select_option(label="E2E101 · End-to-end testing")
        field(admin, "Semester").select_option(label="E2E semester")
        field(admin, "Teacher").select_option(label="Test Teacher")
        field(admin, "Capacity").fill("5")
        field(admin, "Enrollment start").fill(local_input(timedelta(days=-1)))
        field(admin, "Enrollment end").fill(local_input(timedelta(days=1)))
        field(admin, "Status").select_option(label="Active")
        admin.get_by_role("button", name="Save changes").click()
        self.expect_success(admin, "Course offering saved.")
        expect(admin.get_by_role("row", name=re.compile("End-to-end testing"))).to_contain_text(
            "Open"
        )
        self.shot(admin, "e2e01-1-offering-created")

        student = self.new_page()
        student.goto(self.url("/accounts/register/"))
        field(student, "First name").fill("Erin")
        field(student, "Last name").fill("Example")
        field(student, "Email").fill("erin@example.com")
        field(student, "Password").fill(PASSWORD)
        field(student, "Password confirmation").fill(PASSWORD)
        student.get_by_role("button", name="Create student account").click()
        expect(student).to_have_url(re.compile(r"/accounts/status/"))
        expect(student.get_by_text("Pending approval")).to_be_visible()

        admin.goto(self.url("/management/users/?status=PENDING"))
        admin.get_by_role("row", name=re.compile("Erin Example")).get_by_role(
            "link", name="Approve"
        ).click()
        self.confirm(admin)
        self.expect_success(admin, "Erin Example has been approved. Student number: STU-")

        student.goto(self.url("/student/catalog/"))
        student.get_by_role("link", name="View course and enroll").click()
        student.get_by_role("link", name="Enroll in course").click()
        self.confirm(student)
        self.expect_success(student, "You are enrolled in End-to-end testing.")
        self.shot(student, "e2e01-2-student-enrolled")

        teacher = self.sign_in("teacher@example.com")
        teacher.goto(self.url("/teacher/offerings/"))
        teacher.get_by_role("link", name="Open gradebook").click()
        teacher.get_by_role("link", name="Add assessment").click()
        field(teacher, "Title").fill("Final exam")
        teacher.get_by_role("button", name="Save changes").click()
        self.expect_success(teacher, "Assessment Final exam saved.")
        teacher.get_by_label("Erin Example — Final exam grade").fill("9")
        teacher.get_by_label("Erin Example — Final exam comment").fill("Well done.")
        teacher.get_by_role("button", name="Save grades").click()
        self.expect_success(teacher, "Grades saved. Students can see them now.")
        expect(teacher.get_by_text("Available after enrollment closes")).to_be_visible()

        admin.goto(self.url("/management/offerings/"))
        admin.get_by_role("row", name=re.compile("End-to-end testing")).get_by_role(
            "link", name="Edit", exact=True
        ).click()
        field(admin, "Enrollment end").fill(local_input(timedelta(minutes=-2)))
        admin.get_by_role("button", name="Save changes").click()
        self.expect_success(admin, "Course offering saved.")

        teacher.reload()
        teacher.get_by_role("link", name="Publish final grade").click()
        self.confirm(teacher)
        self.expect_success(teacher, "Final grade 9/10 published for Erin Example.")
        self.shot(teacher, "e2e01-3-final-published")

        student.goto(self.url("/student/transcript/"))
        row = student.get_by_role("row", name=re.compile("End-to-end testing"))
        expect(row).to_contain_text("9/10")
        expect(row).not_to_contain_text("Not yet published")
        self.shot(student, "e2e01-4-transcript")


class E2E02AccessAndValidation(CampusE2ETestCase):
    def prepare(self):
        teacher = make_user("teacher@example.com", "TEACHER")
        other_teacher = make_user("other@example.com", "TEACHER")
        self.offering, _ = make_academics(teacher, "OWN101")
        self.other_offering, _ = make_academics(other_teacher, "OTHER101")
        make_enrollment(make_user("student@example.com"), self.offering)

    def test_role_based_access_and_validation(self):
        """E2E-02: forbidden pages for students and teachers, and invalid grades are rejected."""
        student = self.sign_in("student@example.com")
        for path in ["/management/users/", f"/teacher/offerings/{self.offering.pk}/"]:
            response = student.goto(self.url(path))
            self.assertEqual(response.status, 403, path)
            expect(student.get_by_role("heading", name="Access is restricted")).to_be_visible()
        self.shot(student, "e2e02-1-access-denied")

        teacher = self.sign_in("teacher@example.com")
        response = teacher.goto(self.url("/management/"))
        self.assertEqual(response.status, 403)
        response = teacher.goto(self.url(f"/teacher/offerings/{self.other_offering.pk}/"))
        self.assertEqual(response.status, 404)
        expect(teacher.get_by_text("This page could not be found")).to_be_visible()

        teacher.goto(self.url(f"/teacher/offerings/{self.offering.pk}/"))
        grade = teacher.get_by_label("Test Student — Project grade")
        grade.fill("11")
        self.assertTrue(grade.evaluate("field => field.validity.rangeOverflow"))
        teacher.get_by_role("button", name="Save grades").click()
        expect(teacher.locator(".alert-success")).to_have_count(0)

        grade.fill("")
        teacher.get_by_label("Test Student — Project comment").fill("Comment without a grade")
        teacher.get_by_role("button", name="Save grades").click()
        expect(teacher.locator(".alert-danger").first).to_contain_text(
            "No changes have been saved."
        )
        expect(teacher.get_by_text("Enter a grade before adding a comment.")).to_be_visible()
        self.shot(teacher, "e2e02-2-invalid-grade-rejected")

        student.goto(self.url(f"/student/offerings/{self.offering.pk}/"))
        expect(student.get_by_role("row", name=re.compile("Project"))).to_contain_text(
            "Not yet graded"
        )


class E2E03GradeCorrection(CampusE2ETestCase):
    def prepare(self):
        make_user("admin@example.com", "ADMIN")
        teacher = make_user("teacher@example.com", "TEACHER")
        self.offering, assessment = make_academics(teacher, "FIX101")
        enrollment = make_enrollment(make_user("student@example.com"), self.offering)
        change = {
            "enrollment_id": enrollment.pk,
            "assessment_id": assessment.pk,
            "value": 6,
            "comment": "",
        }
        save_grades(teacher, self.offering.pk, [change])
        CourseOffering.objects.filter(pk=self.offering.pk).update(
            enrollment_end=timezone.now() - timedelta(days=1)
        )
        publish_final(teacher, self.offering.pk, enrollment.pk)

    def test_grade_correction_lifecycle(self):
        """E2E-03: admin unpublishes with a reason, teacher corrects and republishes."""
        pk = self.offering.pk
        admin = self.sign_in("admin@example.com")
        admin.goto(self.url(f"/management/offerings/{pk}/gradebook/"))
        admin.get_by_role("link", name="Unpublish", exact=True).click()
        field(admin, "Reason").fill("Final assessment was graded incorrectly.")
        self.confirm(admin)
        self.expect_success(admin, "Final grade for Test Student unpublished.")

        teacher = self.sign_in("teacher@example.com")
        teacher.goto(self.url(f"/teacher/offerings/{pk}/"))
        teacher.get_by_label("Test Student — Project grade").fill("9")
        teacher.get_by_role("button", name="Save grades").click()
        self.expect_success(teacher, "Grades saved.")
        teacher.get_by_role("link", name="Publish final grade").click()
        self.confirm(teacher)
        self.expect_success(teacher, "Final grade 9/10 published for Test Student.")

        student = self.sign_in("student@example.com")
        student.goto(self.url("/student/transcript/"))
        row = student.get_by_role("row", name=re.compile("Course FIX101"))
        expect(row).to_contain_text("9/10")

        admin.goto(self.url("/management/audit/?q=Final+grade"))
        expect(admin.get_by_text("Final grade unpublished")).to_have_count(1)
        expect(admin.get_by_text("Final grade published")).to_have_count(2)
        unpublished = admin.get_by_role("row", name=re.compile("Final grade unpublished"))
        unpublished.get_by_text("View changes").click()
        expect(unpublished).to_contain_text("Final assessment was graded incorrectly.")
        self.shot(admin, "e2e03-1-audit-history")
