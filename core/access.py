from functools import wraps
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from accounts.models import User
from academics.models import CourseOffering


def require_actor(actor, roles):
    if not actor or not actor.is_authenticated:
        raise PermissionDenied
    current = User.objects.get(pk=actor.pk)
    if (
        not current.is_active
        or current.role not in roles
        or current.approval_status != User.Approval.APPROVED
    ):
        raise PermissionDenied
    return current


def role_required(*roles):
    def decorate(view):
        @login_required
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if (
                request.user.role == User.Role.STUDENT
                and request.user.approval_status != User.Approval.APPROVED
            ):
                return redirect("accounts:status")
            require_actor(request.user, roles)
            return view(request, *args, **kwargs)

        return wrapped

    return decorate


def staff_offering(actor, pk):
    actor = require_actor(actor, [User.Role.ADMIN, User.Role.TEACHER])
    offerings = CourseOffering.objects.select_related("course", "semester", "teacher")
    if actor.role == User.Role.TEACHER:
        offerings = offerings.filter(teacher=actor)
    return get_object_or_404(offerings, pk=pk)
