import csv
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import render
from academics.models import Enrollment, Semester
from core.access import role_required, staff_offering
from core.ui import paginate
from grading.services import grade_summary


def safe_cell(value):
    text = str(value) if value is not None else ""
    if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
        return "'" + text
    return text


def csv_response(filename, headers, rows):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    writer = csv.writer(response)
    writer.writerow([safe_cell(value) for value in headers])
    for row in rows:
        writer.writerow([safe_cell(value) for value in row])
    return response


@role_required("STUDENT")
def transcript(request):
    enrollments = (
        Enrollment.objects.filter(student=request.user, status="ENROLLED")
        .select_related("offering__course", "offering__semester")
        .order_by("-offering__semester__start_date", "offering__course__code")
    )
    semester = request.GET.get("semester", "")
    query = request.GET.get("q", "").strip()
    if query:
        enrollments = enrollments.filter(
            Q(offering__course__title__icontains=query) | Q(offering__course__code__icontains=query)
        )
    if semester.isdigit():
        enrollments = enrollments.filter(offering__semester_id=semester)
    if request.GET.get("format") == "csv":
        rows = []
        for enrollment in enrollments:
            summary = grade_summary(enrollment)
            rows.append(
                [
                    enrollment.offering.semester,
                    enrollment.offering.course.code,
                    enrollment.offering.course.title,
                    summary["average"],
                    summary["missing"],
                    summary["final"].value if summary["final"] else "Not published",
                ]
            )
        return csv_response(
            "my-transcript.csv",
            [
                "Semester",
                "Course code",
                "Course",
                "Current average",
                "Missing grades",
                "Final grade",
            ],
            rows,
        )
    page = paginate(request, enrollments)
    return render(
        request,
        "reports/transcript.html",
        {
            "title": "Academic transcript",
            "rows": [(enrollment, grade_summary(enrollment)) for enrollment in page],
            "semesters": Semester.objects.all(),
            "page_obj": page,
        },
    )


@role_required("ADMIN", "TEACHER")
def gradebook_csv(request, pk):
    offering = staff_offering(request.user, pk)
    assessments = list(offering.assessments.all())
    rows = []
    for enrollment in offering.enrollments.filter(status="ENROLLED").select_related(
        "student", "student__student_profile"
    ):
        grades = {g.assessment_id: g.value for g in enrollment.grades.all()}
        summary = grade_summary(enrollment, len(assessments))
        rows.append(
            [
                enrollment.student.student_profile.student_number,
                enrollment.student.get_full_name(),
                enrollment.student.email,
                *[grades.get(a.pk, "Not graded") for a in assessments],
                summary["average"],
                summary["missing"],
                summary["final"].value if summary["final"] else "Not published",
            ]
        )
    return csv_response(
        f"gradebook-{offering.pk}.csv",
        [
            "Student number",
            "Student",
            "Email",
            *[a.title for a in assessments],
            "Current average",
            "Missing grades",
            "Final grade",
        ],
        rows,
    )


@role_required("ADMIN")
def management_csv(request, pk):
    return gradebook_csv(request, pk)


@role_required("TEACHER")
def teacher_csv(request, pk):
    return gradebook_csv(request, pk)
