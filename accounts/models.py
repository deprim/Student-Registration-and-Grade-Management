from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.db.models.functions import Lower
from core.models import TimestampedModel


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("An email address is required.")
        user = self.model(email=email.strip().lower(), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.update(role="ADMIN", approval_status="APPROVED")
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if not extra_fields["is_staff"] or not extra_fields["is_superuser"]:
            raise ValueError("Superusers must have staff and superuser permissions.")
        return self.create_user(email, password, **extra_fields)


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Administrator"
        TEACHER = "TEACHER", "Teacher"
        STUDENT = "STUDENT", "Student"

    class Approval(models.TextChoices):
        PENDING = "PENDING", "Pending approval"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    username = None
    email = models.EmailField(unique=True)
    role = models.CharField(max_length=10, choices=Role, default=Role.STUDENT, db_index=True)
    approval_status = models.CharField(
        max_length=10, choices=Approval, default=Approval.PENDING, db_index=True
    )
    rejection_reason = models.TextField(blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    objects = UserManager()
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    class Meta:
        ordering = ["last_name", "first_name", "pk"]
        constraints = [models.UniqueConstraint(Lower("email"), name="user_email_case_insensitive")]

    def save(self, *args, **kwargs):
        self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.get_full_name() or self.email


class StudentProfile(TimestampedModel):
    user = models.OneToOneField(User, on_delete=models.PROTECT, related_name="student_profile")
    student_number = models.CharField(max_length=30, unique=True)

    def __str__(self):
        return self.student_number
