from django.db import models
from .models import AuditEvent


def snapshot(obj, fields):
    result = {}
    for field in fields:
        value = getattr(obj, field)
        if isinstance(value, models.Model):
            value = value.pk
        elif value is not None and not isinstance(value, (str, int, float, bool)):
            value = str(value)
        result[field] = value
    return result


def audit(actor, action, obj, old=None, new=None, reason=""):
    return AuditEvent.objects.create(
        actor=actor,
        action=action,
        target=f"{obj._meta.label}:{obj.pk}",
        old_values=old or {},
        new_values=new or {},
        reason=reason,
    )
