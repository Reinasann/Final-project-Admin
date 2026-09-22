from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0014_machine_multiple_caretakers"),
    ]

    operations = [
        migrations.CreateModel(
            name="MachineCommand",
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
                    "command",
                    models.CharField(
                        choices=[
                            ("START", "Start machine"),
                            ("STOP", "Stop machine"),
                            ("RESET_BIN", "Reset bin weight"),
                        ],
                        max_length=20,
                    ),
                ),
                ("payload", models.JSONField(blank=True, default=dict)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("PENDING", "Pending"),
                            ("DELIVERED", "Delivered"),
                            ("ACKNOWLEDGED", "Acknowledged"),
                            ("FAILED", "Failed"),
                        ],
                        default="PENDING",
                        max_length=20,
                    ),
                ),
                ("attempts", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("delivered_at", models.DateTimeField(blank=True, null=True)),
                ("acknowledged_at", models.DateTimeField(blank=True, null=True)),
                ("result_message", models.CharField(blank=True, max_length=255)),
                (
                    "machine",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="device_commands",
                        to="core.machine",
                    ),
                ),
            ],
            options={
                "ordering": ["created_at", "id"],
            },
        ),
        migrations.AddIndex(
            model_name="machinecommand",
            index=models.Index(
                fields=["machine", "status", "created_at"],
                name="core_cmd_machine_status_idx",
            ),
        ),
    ]
