from datetime import timedelta
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from accounts.models import User, StudentProfile
from academics.models import Semester, Course, CourseOffering, Enrollment
from academics.services import archive_academic
from grading.models import Assessment
from grading.services import save_grades, publish_final
from core.services import audit


class Command(BaseCommand):
    help = "Create English demonstration data once, without changing existing demo records."

    @transaction.atomic
    def handle(self, *args, **options):
        if User.objects.filter(email="admin@campus.example").exists():
            self.stdout.write("Demo data already exists. Existing records were left unchanged.")
            return
        now = timezone.now()
        today = timezone.localdate()
        admin = User.objects.create_superuser(
            "admin@campus.example",
            "DemoAdmin!2026",
            first_name="Jordan",
            last_name="Ellis",
        )
        teachers = [
            User.objects.create_user(
                email,
                "DemoTeacher!2026",
                first_name=first,
                last_name=last,
                role="TEACHER",
                approval_status="APPROVED",
                approved_at=now,
            )
            for email, first, last in [
                ("teacher@campus.example", "Sarah", "Mitchell"),
                ("teacher2@campus.example", "Daniel", "Hayes"),
            ]
        ]
        names = [
            ("Alex", "Morgan"),
            ("Jamie", "Reed"),
            ("Taylor", "Brooks"),
            ("Casey", "Parker"),
            ("Riley", "Bennett"),
            ("Sam", "Walker"),
            ("Avery", "Cole"),
            ("Quinn", "Foster"),
            ("Charlie", "Lane"),
            ("Drew", "Harper"),
            ("Robin", "Blake"),
            ("Morgan", "Wells"),
        ]
        students = []
        for index, (first, last) in enumerate(names, 1):
            email = "student@campus.example" if index == 1 else f"student{index}@campus.example"
            student = User.objects.create_user(
                email,
                "DemoStudent!2026",
                first_name=first,
                last_name=last,
                approval_status="APPROVED",
                approved_at=now,
            )
            StudentProfile.objects.create(user=student, student_number=f"STU-{student.pk:06d}")
            students.append(student)
        for number in [1, 2]:
            User.objects.create_user(
                f"pending{number}@campus.example",
                "DemoStudent!2026",
                first_name=["Emma", "Oliver"][number - 1],
                last_name="West",
            )
        User.objects.create_user(
            "rejected@campus.example",
            "DemoStudent!2026",
            first_name="Noah",
            last_name="Stone",
            approval_status="REJECTED",
            rejection_reason="Please contact the registrar to confirm your student details.",
        )
        current = Semester.objects.create(
            name="Current semester",
            start_date=today - timedelta(days=60),
            end_date=today + timedelta(days=120),
        )
        previous = Semester.objects.create(
            name="Previous semester",
            start_date=today - timedelta(days=270),
            end_date=today - timedelta(days=90),
        )
        descriptions = [
            (
                "CS101",
                "Introduction to Programming",
                "Build a strong foundation in Python, problem solving, and the everyday practice of writing clear, reliable programs.",
            ),
            (
                "MA201",
                "Applied Mathematics",
                "Explore mathematical ideas through practical problems, logical reasoning, and collaborative exercises.",
            ),
            (
                "DB301",
                "Database Systems",
                "Learn how to model information, write SQL, and design reliable relational databases with PostgreSQL.",
            ),
            (
                "WD101",
                "Web Development Foundations",
                "Discover the building blocks of the web, from accessible HTML and CSS to server-side application design.",
            ),
        ]
        for index, (code, title, description) in enumerate(descriptions):
            course = Course.objects.create(code=code, title=title, description=description)
            semester = previous if index == 3 else current
            offering = CourseOffering.objects.create(
                course=course,
                semester=semester,
                teacher=teachers[index % 2],
                capacity=3 if index == 1 else 30,
                enrollment_start=now - timedelta(days=240 if index == 3 else 30),
                enrollment_end=now + timedelta(days=14)
                if index < 2
                else now - timedelta(days=120 if index == 3 else 2),
                status="ACTIVE",
            )
            selected = students[:3] if index == 1 else students[:6]
            enrollments = [
                Enrollment.objects.create(
                    student=student,
                    offering=offering,
                    enrolled_at=now - timedelta(days=150 if index == 3 else 20),
                )
                for student in selected
            ]
            assessments = [
                Assessment.objects.create(
                    offering=offering,
                    title=title,
                    description=description,
                    display_order=order,
                    due_date=today - timedelta(days=125 if index == 3 else 1)
                    if index > 1
                    else today + timedelta(days=20 + order * 7),
                )
                for order, (title, description) in enumerate(
                    [
                        (
                            "Practical exercises",
                            "Apply the concepts in a set of focused exercises.",
                        ),
                        (
                            "Course project",
                            "Bring your knowledge together in an independent project.",
                        ),
                        (
                            "Final assessment",
                            "Demonstrate your understanding of the course material.",
                        ),
                    ]
                )
            ]
            if index in [2, 3]:
                changes = []
                for student_index, enrollment in enumerate(enrollments):
                    for assessment_index, assessment in enumerate(assessments):
                        if index == 2 and student_index > 0 and assessment_index == 2:
                            continue
                        changes.append(
                            {
                                "enrollment_id": enrollment.pk,
                                "assessment_id": assessment.pk,
                                "value": 6 + (student_index + assessment_index) % 5,
                                "comment": "Good progress. Keep explaining your reasoning clearly.",
                            }
                        )
                save_grades(offering.teacher, offering.pk, changes)
                if index == 2:
                    publish_final(offering.teacher, offering.pk, enrollments[0].pk)
                else:
                    for enrollment in enrollments:
                        publish_final(offering.teacher, offering.pk, enrollment.pk)
                    archive_academic(admin, "offerings", offering.pk)
        archive_academic(admin, "semesters", previous.pk)
        audit(admin, "Demonstration data loaded", admin)
        self.stdout.write(
            self.style.SUCCESS(
                "Demo data created. These credentials are for local educational use only."
            )
        )
        self.stdout.write("Administrator: admin@campus.example / DemoAdmin!2026")
        self.stdout.write("Teacher: teacher@campus.example / DemoTeacher!2026")
        self.stdout.write("Second teacher: teacher2@campus.example / DemoTeacher!2026")
        self.stdout.write("Student: student@campus.example / DemoStudent!2026")
