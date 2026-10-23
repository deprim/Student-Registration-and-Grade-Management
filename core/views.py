from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import redirect, render
from accounts.models import User
from academics.models import CourseOffering, Enrollment
from grading.models import Grade
from .access import role_required


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
        stats = [
            (
                "Approved students",
                User.objects.filter(role="STUDENT", approval_status="APPROVED").count(),
            ),
            (
                "Pending applications",
                User.objects.filter(role="STUDENT", approval_status="PENDING").count(),
            ),
            ("Teachers", User.objects.filter(role="TEACHER").count()),
            ("Active offerings", offerings.filter(status="ACTIVE").count()),
        ]
        offerings = offerings.filter(status="ACTIVE")
    elif user.role == "TEACHER":
        offerings = offerings.filter(teacher=user)
        stats = [
            ("Assigned courses", offerings.filter(status="ACTIVE").count()),
            (
                "Enrolled students",
                Enrollment.objects.filter(
                    offering__teacher=user, status="ENROLLED", offering__status="ACTIVE"
                ).count(),
            ),
            (
                "Published finals",
                Enrollment.objects.filter(
                    offering__teacher=user, final_grade__is_published=True
                ).count(),
            ),
        ]
    else:
        offerings = offerings.filter(enrollments__student=user, enrollments__status="ENROLLED")
        stats = [
            ("Current courses", offerings.filter(status="ACTIVE").count()),
            ("Recorded grades", Grade.objects.filter(enrollment__student=user).count()),
            (
                "Published finals",
                Enrollment.objects.filter(student=user, final_grade__is_published=True).count(),
            ),
        ]
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
        {"stats": stats, "offerings": offerings[:6], "recent_grades": recent_grades},
    )


def health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok"})
