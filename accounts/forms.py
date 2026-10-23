from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from core.forms import StyledFormMixin
from .models import User


class RegistrationForm(StyledFormMixin, UserCreationForm):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "password1", "password2"]

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def clean(self):
        data = super().clean()
        if any(
            key in self.data
            for key in [
                "role",
                "approval_status",
                "is_staff",
                "is_superuser",
                "is_active",
            ]
        ):
            raise forms.ValidationError("Account permissions cannot be set during registration.")
        return data


class EmailAuthenticationForm(StyledFormMixin, AuthenticationForm):
    username = forms.EmailField(label="Email", widget=forms.EmailInput(attrs={"autofocus": True}))

    def clean_username(self):
        return self.cleaned_data["username"].strip().lower()


class ProfileForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.required = True


class UserEditForm(ProfileForm):
    class Meta(ProfileForm.Meta):
        fields = ["first_name", "last_name", "email"]

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email
