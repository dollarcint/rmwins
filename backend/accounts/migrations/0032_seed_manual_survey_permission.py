from django.db import migrations


CODE = "projects.manual.create"


def seed_permission(apps, schema_editor):
    AccessFunction = apps.get_model("accounts", "AccessFunction")
    Role = apps.get_model("accounts", "Role")
    RoleFunctionPermission = apps.get_model("accounts", "RoleFunctionPermission")

    function, _ = AccessFunction.objects.update_or_create(
        code=CODE,
        defaults={
            "name": "Add manual surveys",
            "module": "Projects - Actions",
            "description": (
                "Create survey inventory from a client-supplied entry link when "
                "no API feed is available."
            ),
            "is_active": True,
        },
    )
    for role in Role.objects.filter(slug__in=("admin", "super-admin"), is_active=True):
        RoleFunctionPermission.objects.update_or_create(
            role=role,
            function=function,
            defaults={"allowed": True},
        )


class Migration(migrations.Migration):
    dependencies = [("accounts", "0031_seed_studies_pid_column_permission")]

    operations = [migrations.RunPython(seed_permission, migrations.RunPython.noop)]
