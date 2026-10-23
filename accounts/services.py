from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from core.access import require_actor
from core.services import audit, snapshot
from .models import User, StudentProfile


@transaction.atomic
def review_student(actor, student_id, approved, reason=""):
    actor = require_actor(actor, [User.Role.ADMIN])
    student = User.objects.select_for_update().get(pk=student_id, role=User.Role.STUDENT)
    if not approved and not reason.strip():
        raise ValidationError("A rejection reason is required.")
    old = snapshot(student, ["approval_status", "rejection_reason"])
    if not approved and student.enrollments.exists():
        raise ValidationError(
            "A student with academic history must be blocked instead of rejected."
        )
    student.approval_status = User.Approval.APPROVED if approved else User.Approval.REJECTED
    student.rejection_reason = "" if approved else reason.strip()
    student.approved_at = timezone.now() if approved else None
    student.save()
    if approved:
        StudentProfile.objects.get_or_create(
            user=student, defaults={"student_number": f"STU-{student.pk:06d}"}
        )
    audit(
        actor,
        "Student approved" if approved else "Student rejected",
        student,
        old,
        snapshot(student, ["approval_status"]),
        reason,
    )
    return student


@transaction.atomic
def set_user_active(actor, user_id, active, reason):
    actor = require_actor(actor, [User.Role.ADMIN])
    user = User.objects.select_for_update().get(pk=user_id)
    if actor.pk == user.pk or user.role == User.Role.ADMIN:
        raise ValidationError("Administrator accounts cannot be blocked here.")
    if not reason.strip():
        raise ValidationError("A reason is required.")
    old = {"is_active": user.is_active}
    user.is_active = active
    user.save()
    audit(
        actor,
        "User unblocked" if active else "User blocked",
        user,
        old,
        {"is_active": active},
        reason,
    )


@transaction.atomic
def save_user(actor, data, user_id=None):
    actor = require_actor(actor, [User.Role.ADMIN])
    user = (
        User.objects.select_for_update().get(pk=user_id)
        if user_id
        else User(role=User.Role.TEACHER, approval_status=User.Approval.APPROVED)
    )
    old = snapshot(user, ["email", "first_name", "last_name"]) if user.pk else {}
    for field in ["email", "first_name", "last_name"]:
        setattr(user, field, data[field])
    if not user.pk:
        from django.contrib.auth.password_validation import validate_password

        validate_password(data["password1"], user)
        user.set_password(data["password1"])
    user.full_clean(exclude=["password"])
    user.save()
    audit(
        actor,
        "User profile saved",
        user,
        old,
        snapshot(user, ["email", "first_name", "last_name"]),
    )
    return user
