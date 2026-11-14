from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.shortcuts import redirect, render
from django.utils import dateformat, timezone
from .forms import ConfirmForm, ReasonForm

DISPLAY_DATETIME = "M j, Y, H:i"


def paginate(request, queryset):
    return Paginator(queryset, 25).get_page(request.GET.get("page"))


def form_errors(form, error):
    for message in error.messages:
        form.add_error(None, message)


def local_datetime(value):
    return dateformat.format(timezone.localtime(value), DISPLAY_DATETIME)


def enrollment_window(offering):
    """Describe an offering's enrollment window for display only.

    The enrollment and publication rules themselves stay in the service layer.
    """
    now = timezone.now()
    opens = local_datetime(offering.enrollment_start)
    closes = local_datetime(offering.enrollment_end)
    dates = {"opens": opens, "closes": closes}
    if now < offering.enrollment_start:
        return dates | {
            "state": "upcoming",
            "label": "Not open yet",
            "tone": "neutral",
            "detail": f"Opens {opens}",
            "summary": f"Enrollment opens {opens}",
        }
    if now <= offering.enrollment_end:
        return dates | {
            "state": "open",
            "label": "Open",
            "tone": "",
            "detail": f"Closes {closes}",
            "summary": f"Enrollment open until {closes}",
        }
    return dates | {
        "state": "closed",
        "label": "Closed",
        "tone": "neutral",
        "detail": f"Closed {closes}",
        "summary": f"Enrollment closed on {closes}",
    }


def confirmation(
    request,
    title,
    back_url,
    operation,
    reason=False,
    description="",
    consequences=(),
    success_message=None,
    reason_help="",
    danger=False,
):
    form = (ReasonForm if reason else ConfirmForm)(
        request.POST if request.method == "POST" else None
    )
    if reason and reason_help:
        form.fields["reason"].help_text = reason_help
    if request.method == "POST" and form.is_valid():
        try:
            result = operation(form.cleaned_data.get("reason", ""))
        except ValidationError as error:
            form_errors(form, error)
        else:
            if callable(success_message):
                success_message = success_message(result)
            messages.success(request, success_message or "The action was completed successfully.")
            return redirect(back_url)
    return render(
        request,
        "core/confirm.html",
        {
            "title": title,
            "description": description,
            "consequences": consequences,
            "back_url": back_url,
            "form": form,
            "danger": danger,
        },
    )
