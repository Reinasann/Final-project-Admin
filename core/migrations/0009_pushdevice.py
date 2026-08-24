from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0008_notificationevent_notification_action_required_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="PushDevice",
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
                ("token", models.TextField(unique=True)),
                ("platform", models.CharField(default="android", max_length=20)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="push_devices",
                        to="core.user",
                    ),
                ),
            ],
        ),
        migrations.AddIndex(
            model_name="pushdevice",
            index=models.Index(
                fields=["user", "is_active"],
                name="core_push_user_active_idx",
            ),
        ),
    ]
