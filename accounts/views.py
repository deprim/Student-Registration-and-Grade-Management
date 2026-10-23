from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.shortcuts import redirect, render
from core.services import audit, snapshot
from .forms import RegistrationForm, ProfileForm


def register(request):
    if request.user.is_authenticated:
        return redirect("home")
    form = RegistrationForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                user = form.save()
                audit(
                    user,
                    "Student registered",
                    user,
                    new={"approval_status": user.approval_status},
                )
        except IntegrityError:
            form.add_error("email", "An account with this email already exists.")
        else:
            login(request, user)
            return redirect("accounts:status")
    return render(request, "accounts/register.html", {"form": form})


@login_required
def status(request):
    return render(request, "accounts/status.html")


@login_required
def profile(request):
    old = snapshot(request.user, ["first_name", "last_name"])
    form = ProfileForm(request.POST if request.method == "POST" else None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            user = form.save()
            audit(
                user,
                "Personal profile updated",
                user,
                old,
                snapshot(user, ["first_name", "last_name"]),
            )
        messages.success(request, "Your profile has been updated.")
        return redirect("accounts:profile")
    return render(
        request,
        "core/form.html",
        {
            "form": form,
            "title": "Your profile",
            "description": f"Account email: {request.user.email}",
            "back_url": "/",
        },
    )
