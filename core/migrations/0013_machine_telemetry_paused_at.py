from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0012_restore_machine_caretaker"),
    ]

    operations = [
        migrations.AddField(
            model_name="machine",
            name="telemetry_paused_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
