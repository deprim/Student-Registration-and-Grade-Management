from django.contrib import admin
from django.urls import include, path
from core import views as core
from academics import views as academic
from grading import views as grading
from reports import views as reports

student_patterns = [
    path("", core.dashboard, name="dashboard"),
    path("catalog/", academic.catalog, name="catalog"),
    path("courses/", academic.my_courses, name="courses"),
    path("offerings/<int:pk>/", academic.offering_detail, name="offering"),
    path(
        "offerings/<int:pk>/<str:action>/",
        academic.enrollment_action,
        name="enrollment_action",
    ),
    path("transcript/", reports.transcript, name="transcript"),
]
teacher_patterns = [
    path("", core.dashboard, name="dashboard"),
    path("offerings/", academic.teacher_offerings, name="offerings"),
    path("offerings/<int:pk>/", grading.teacher_gradebook, name="gradebook"),
    path("offerings/<int:pk>/export/", reports.teacher_csv, name="export"),
    path(
        "offerings/<int:pk>/assessments/new/",
        grading.assessment_edit,
        name="assessment_create",
    ),
    path(
        "offerings/<int:pk>/assessments/<int:assessment_id>/edit/",
        grading.assessment_edit,
        name="assessment_edit",
    ),
    path(
        "offerings/<int:pk>/assessments/<int:assessment_id>/delete/",
        grading.assessment_delete,
        name="assessment_delete",
    ),
    path(
        "offerings/<int:pk>/final/<int:enrollment_id>/publish/",
        grading.final_publish,
        name="publish",
    ),
]
management_patterns = [
    path("", core.dashboard, name="dashboard"),
    path("users/", academic.users, name="users"),
    path("users/new/", academic.user_edit, name="teacher_create"),
    path("users/<int:pk>/edit/", academic.user_edit, name="user_edit"),
    path("users/<int:pk>/<str:action>/", academic.user_action, name="user_action"),
    path("audit/", academic.audit_history, name="audit"),
    path("offerings/<int:pk>/gradebook/", grading.management_gradebook, name="gradebook"),
    path("offerings/<int:pk>/export/", reports.management_csv, name="export"),
    path(
        "offerings/<int:pk>/final/<int:enrollment_id>/unpublish/",
        grading.final_unpublish,
        name="unpublish",
    ),
    path(
        "offerings/<int:pk>/grades/<int:grade_id>/clear/",
        grading.grade_clear,
        name="grade_clear",
    ),
    path("<str:kind>/", academic.academic_list, name="academic_list"),
    path("<str:kind>/new/", academic.academic_edit, name="academic_create"),
    path("<str:kind>/<int:pk>/edit/", academic.academic_edit, name="academic_edit"),
    path(
        "<str:kind>/<int:pk>/archive/",
        academic.academic_archive,
        name="academic_archive",
    ),
]
urlpatterns = [
    path("", core.home, name="home"),
    path("accounts/", include("accounts.urls")),
    path("student/", include((student_patterns, "student"))),
    path("teacher/", include((teacher_patterns, "teacher"))),
    path("management/", include((management_patterns, "management"))),
    path("admin/", admin.site.urls),
    path("health/", core.health, name="health"),
]
