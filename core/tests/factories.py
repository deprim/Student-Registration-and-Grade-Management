from datetime import timedelta
from django.utils import timezone
from accounts.models import User, StudentProfile
from academics.models import Semester, Course, CourseOffering, Enrollment
from grading.models import Assessment


def make_user(email, role="STUDENT", approved=True):
    user = User.objects.create_user(
        email,
        "StrongTestPassword!62",
        first_name="Test",
        last_name=email.split("@")[0].capitalize(),
        role=role,
        approval_status="APPROVED" if approved else "PENDING",
    )
    if role == "STUDENT" and approved:
        StudentProfile.objects.create(user=user, student_number=f"STU-{user.pk:06d}")
    return user


def make_academics(teacher, code="TEST101", open_enrollment=True, capacity=10):
    now = timezone.now()
    semester, _ = Semester.objects.get_or_create(
        name="Test semester",
        defaults={
            "start_date": now.date() - timedelta(days=30),
            "end_date": now.date() + timedelta(days=90),
        },
    )
    course = Course.objects.create(
        code=code, title=f"Course {code}", description="A course for integration tests."
    )
    offering = CourseOffering.objects.create(
        course=course,
        semester=semester,
        teacher=teacher,
        capacity=capacity,
        status="ACTIVE",
        enrollment_start=now - timedelta(days=10),
        enrollment_end=now + timedelta(days=10) if open_enrollment else now - timedelta(days=1),
    )
    assessment = Assessment.objects.create(offering=offering, title="Project")
    return offering, assessment


def make_enrollment(student, offering):
    return Enrollment.objects.create(student=student, offering=offering, enrolled_at=timezone.now())
