from django.test import override_settings
from django.test.runner import DiscoverRunner


class PortalTestRunner(DiscoverRunner):
    """Tests read source assets without requiring a production static manifest."""

    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        self.storage_settings = override_settings(
            STORAGES={
                "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
                "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
            }
        )
        self.storage_settings.enable()

    def teardown_test_environment(self, **kwargs):
        try:
            super().teardown_test_environment(**kwargs)
        finally:
            self.storage_settings.disable()
