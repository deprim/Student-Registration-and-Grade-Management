from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from accounts.models import User
from academics.models import Course, CourseOffering, Enrollment, Semester
from grading.models import Grade
from .access import role_required
from .ui import enrollment_window


def plural(count, word):
    return f"{count} {word}{'' if count == 1 else 's'}"


def stat(label, value, url=None, action="", attention=False):
    return {"label": label, "value": value, "url": url, "action": action, "attention": attention}


def admin_overview(offerings):
    users_url = reverse("management:users")
    offerings_url = reverse("management:academic_list", args=["offerings"])
    pending = User.objects.filter(role="STUDENT", approval_status="PENDING").count()
    active = offerings.filter(status="ACTIVE").count()
    stats = [
        stat(
            "Approved students",
            User.objects.filter(role="STUDENT", approval_status="APPROVED").count(),
            f"{users_url}?role=STUDENT&status=APPROVED",
            "View students",
        ),
        stat(
            "Pending applications",
            pending,
            f"{users_url}?status=PENDING",
            "Review applications",
            attention=pending > 0,
        ),
        stat(
            "Teachers",
            User.objects.filter(role="TEACHER").count(),
            f"{users_url}?role=TEACHER",
            "View teachers",
        ),
        stat("Active offerings", active, offerings_url, "Manage offerings"),
    ]
    setup = [
        (
            Semester.objects.filter(is_archived=False).exists(),
            "Start by creating a semester.",
            reverse("management:academic_create", args=["semesters"]),
            "Create semester",
        ),
        (
            Course.objects.filter(is_archived=False).exists(),
            "Add a course to the course library.",
            reverse("management:academic_create", args=["courses"]),
            "Add course to library",
        ),
        (
            User.objects.filter(role="TEACHER", is_active=True).exists(),
            "Create a teacher account.",
            reverse("management:teacher_create"),
            "Create teacher",
        ),
        (
            active > 0,
            "Create a course offering and set it to Active.",
            reverse("management:academic_create", args=["offerings"]),
            "Create course offering",
        ),
    ]
    missing = next((item for item in setup if not item[0]), None)
    if pending:
        next_step = {
            "title": f"{plural(pending, 'student application')} waiting for review.",
            "detail": "Approve students so they can enroll in courses, or reject an "
            "application with a reason the student will see.",
            "url": f"{users_url}?status=PENDING",
            "action": f"Review {plural(pending, 'application')}",
            "attention": True,
        }
    elif missing:
        next_step = {
            "title": missing[1],
            "detail": "Students can enroll once a semester, a library course, a teacher "
            "and an Active course offering exist.",
            "url": missing[2],
            "action": missing[3],
        }
    else:
        next_step = {
            "title": "No applications are waiting for review.",
            "detail": "Keep course offerings up to date: check enrollment windows, "
            "places and gradebooks.",
            "url": offerings_url,
            "action": "Manage course offerings",
        }
    panel = {
        "title": "Active course offerings",
        "description": "Offerings students can see. Open one to view its gradebook.",
        "url": offerings_url,
        "empty": "No course offerings are active yet.",
        "empty_url": reverse("management:academic_create", args=["offerings"]),
        "empty_action": "Create course offering",
    }
    return stats, next_step, panel


def teacher_overview(user, offerings):
    courses_url = reverse("teacher:offerings")
    active = offerings.filter(status="ACTIVE").count()
    awaiting = (
        Enrollment.objects.filter(
            offering__teacher=user,
            offering__status="ACTIVE",
            offering__semester__is_archived=False,
            offering__enrollment_end__lt=timezone.now(),
            status="ENROLLED",
        )
        .exclude(final_grade__is_published=True)
        .count()
    )
    stats = [
        stat("Assigned courses", active, courses_url, "View courses"),
        stat(
            "Enrolled students",
            Enrollment.objects.filter(
                offering__teacher=user, status="ENROLLED", offering__status="ACTIVE"
            ).count(),
        ),
        stat(
            "Published finals",
            Enrollment.objects.filter(
                offering__teacher=user, final_grade__is_published=True
            ).count(),
        ),
        stat(
            "Finals still to publish",
            awaiting,
            courses_url if awaiting else None,
            "Open gradebooks",
            attention=awaiting > 0,
        ),
    ]
    if not active:
        next_step = {
            "title": "You have no active courses yet.",
            "detail": "An administrator assigns course offerings to teachers. They appear "
            "under Assigned courses once they are Active.",
            "url": courses_url,
            "action": "Open assigned courses",
        }
    elif awaiting:
        next_step = {
            "title": f"{plural(awaiting, 'student')} in closed courses still "
            f"need{'s' if awaiting == 1 else ''} a published final grade.",
            "detail": "Enrollment has closed. Grade every assessment, then publish each "
            "student's final grade in the gradebook.",
            "url": courses_url,
            "action": "Open assigned courses",
            "attention": True,
        }
    else:
        next_step = {
            "title": "Open a course to add assessments and enter grades.",
            "detail": "Students see saved grades immediately. Final grades can be published "
            "after enrollment closes.",
            "url": courses_url,
            "action": "Open assigned courses",
        }
    panel = {
        "title": "Your assigned courses",
        "description": "Open a course to manage assessments, grades and final grades.",
        "url": courses_url,
        "empty": "No courses are assigned to you yet.",
    }
    return stats, next_step, panel


def student_overview(user, offerings):
    courses_url = reverse("student:courses")
    transcript_url = reverse("student:transcript")
    catalog_url = reverse("student:catalog")
    current = offerings.filter(status="ACTIVE").count()
    stats = [
        stat("Current courses", current, courses_url, "View my courses"),
        stat(
            "Recorded grades",
            Grade.objects.filter(enrollment__student=user).count(),
            transcript_url,
            "View transcript",
        ),
        stat(
            "Published finals",
            Enrollment.objects.filter(student=user, final_grade__is_published=True).count(),
            transcript_url,
            "View transcript",
        ),
    ]
    if current:
        next_step = {
            "title": f"You are enrolled in {plural(current, 'current course')}.",
            "detail": "Follow your grades and teacher comments in My courses. Final grades "
            "appear on your academic transcript once your teacher publishes them.",
            "url": courses_url,
            "action": "Open my courses",
        }
    else:
        next_step = {
            "title": "You are not enrolled in any course yet.",
            "detail": "Browse the course catalog and enroll in a course while its "
            "enrollment is open.",
            "url": catalog_url,
            "action": "Browse course catalog",
        }
    panel = {
        "title": "Your courses",
        "description": "Courses you are enrolled in, including past semesters.",
        "url": courses_url,
        "empty": "You are not enrolled in any course yet.",
        "empty_url": catalog_url,
        "empty_action": "Browse course catalog",
    }
    return stats, next_step, panel


@login_required
def home(request):
    if (
        request.user.role == User.Role.STUDENT
        and request.user.approval_status != User.Approval.APPROVED
    ):
        return redirect("accounts:status")
    return redirect(
        {
            "ADMIN": "management:dashboard",
            "TEACHER": "teacher:dashboard",
            "STUDENT": "student:dashboard",
        }[request.user.role]
    )


@role_required("ADMIN", "TEACHER", "STUDENT")
def dashboard(request):
    user = request.user
    from django.core.exceptions import PermissionDenied

    expected = {"management": "ADMIN", "teacher": "TEACHER", "student": "STUDENT"}.get(
        request.resolver_match.namespace
    )
    if user.role != expected:
        raise PermissionDenied
    offerings = CourseOffering.objects.select_related("course", "semester", "teacher")
    if user.role == "ADMIN":
        stats, next_step, panel = admin_overview(offerings)
        offerings = offerings.filter(status="ACTIVE")
    elif user.role == "TEACHER":
        offerings = offerings.filter(teacher=user)
        stats, next_step, panel = teacher_overview(user, offerings)
    else:
        offerings = offerings.filter(enrollments__student=user, enrollments__status="ENROLLED")
        stats, next_step, panel = student_overview(user, offerings)
    listed = list(offerings[:6])
    for offering in listed:
        offering.window = enrollment_window(offering)
    recent_grades = (
        Grade.objects.filter(enrollment__student=user)
        .select_related("assessment", "enrollment__offering__course")
        .order_by("-updated_at")[:5]
        if user.role == "STUDENT"
        else []
    )
    return render(
        request,
        "core/dashboard.html",
        {
            "stats": stats,
            "next_step": next_step,
            "panel": panel,
            "offerings": listed,
            "recent_grades": recent_grades,
        },
    )


def health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok"})
