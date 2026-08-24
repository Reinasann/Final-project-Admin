import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0007_remove_machine_caretaker"),
    ]

    operations = [
        migrations.CreateModel(
            name="NotificationEvent",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "waste_type",
                    models.CharField(
                        choices=[
                            ("plastic", "Plastic/PET"),
                            ("glass", "Glass"),
                            ("can", "Aluminium can"),
                        ],
                        max_length=10,
                    ),
                ),
                ("title", models.CharField(max_length=150)),
                ("message", models.CharField(max_length=500)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("acknowledged_by_name", models.CharField(blank=True, max_length=150)),
                ("acknowledged_at", models.DateTimeField(blank=True, null=True)),
                ("resolved_at", models.DateTimeField(blank=True, null=True)),
                (
                    "acknowledged_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="acknowledged_notification_events",
                        to="core.user",
                    ),
                ),
                (
                    "machine",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="notification_events",
                        to="core.machine",
                    ),
                ),
                (
                    "notification_type",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        to="core.notificationtype",
                    ),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddField(
            model_name="notification",
            name="action_required",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="notification",
            name="event",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="deliveries",
                to="core.notificationevent",
            ),
        ),
        migrations.AddIndex(
            model_name="notificationevent",
            index=models.Index(
                fields=["machine", "waste_type", "-created_at"],
                name="core_notif_machine_waste_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="notificationevent",
            constraint=models.UniqueConstraint(
                condition=models.Q(("resolved_at__isnull", True)),
                fields=("machine", "waste_type"),
                name="unique_active_bin_notification",
            ),
        ),
    ]
