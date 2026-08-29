from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0011_make_mobile_sessions_persistent"),
    ]

    operations = [
        migrations.AddField(
            model_name="machine",
            name="caretaker",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="assigned_machines",
                to="core.user",
            ),
        ),
    ]
