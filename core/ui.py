from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.shortcuts import redirect, render
from .forms import ConfirmForm, ReasonForm


def paginate(request, queryset):
    return Paginator(queryset, 25).get_page(request.GET.get("page"))


def form_errors(form, error):
    for message in error.messages:
        form.add_error(None, message)


def confirmation(request, title, back_url, operation, reason=False, description=""):
    form = (ReasonForm if reason else ConfirmForm)(
        request.POST if request.method == "POST" else None
    )
    if request.method == "POST" and form.is_valid():
        try:
            operation(form.cleaned_data.get("reason", ""))
        except ValidationError as error:
            form_errors(form, error)
        else:
            messages.success(request, "The action was completed successfully.")
            return redirect(back_url)
    return render(
        request,
        "core/confirm.html",
        {
            "title": title,
            "description": description,
            "back_url": back_url,
            "form": form,
        },
    )
