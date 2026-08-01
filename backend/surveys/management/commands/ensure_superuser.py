import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create or update the configured deployment superuser."

    def handle(self, *args, **options):
        username = os.environ.get("DJANGO_SUPERUSER_USERNAME")
        email = os.environ.get("DJANGO_SUPERUSER_EMAIL")
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD")
        if not all((username, email, password)):
            self.stdout.write("Superuser environment variables are incomplete; skipping.")
            return

        user, created = get_user_model().objects.get_or_create(username=username)
        user.email = email
        user.is_staff = True
        user.is_superuser = True
        user.set_password(password)
        user.save(update_fields=["email", "is_staff", "is_superuser", "password"])
        action = "Created" if created else "Updated"
        self.stdout.write(self.style.SUCCESS(f"{action} deployment superuser '{username}'."))
