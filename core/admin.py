from django.contrib import admin
from accounts.models import User, StudentProfile
from academics.models import Semester, Course, CourseOffering, Enrollment
from grading.models import Assessment, Grade, FinalGrade
from .models import AuditEvent


class ReadOnlyAdmin(admin.ModelAdmin):
    """Academic changes must pass through the application's audited services."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(User)
class UserAdmin(ReadOnlyAdmin):
    fields = [
        "email",
        "first_name",
        "last_name",
        "role",
        "approval_status",
        "is_active",
        "date_joined",
    ]
    list_display = [
        "email",
        "first_name",
        "last_name",
        "role",
        "approval_status",
        "is_active",
    ]
    search_fields = ["email", "first_name", "last_name"]
    list_filter = ["role", "approval_status", "is_active"]


for model in [
    StudentProfile,
    Semester,
    Course,
    CourseOffering,
    Enrollment,
    Assessment,
    Grade,
    FinalGrade,
    AuditEvent,
]:
    admin.site.register(model, ReadOnlyAdmin)

admin.site.site_header = "Campus technical administration"
admin.site.site_title = "Campus administration"
admin.site.index_title = "Read-only academic records"
