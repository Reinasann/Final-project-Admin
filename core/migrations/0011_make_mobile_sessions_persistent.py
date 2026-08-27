from django.db import migrations


def remove_api_token_expiry(apps, schema_editor):
    api_token = apps.get_model("core", "ApiToken")
    api_token.objects.filter(expires_at__isnull=False).update(expires_at=None)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0010_machine_created_at_machineinformation_created_at"),
    ]

    operations = [
        migrations.RunPython(remove_api_token_expiry, migrations.RunPython.noop),
    ]
