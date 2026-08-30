from django.db import migrations, models


def copy_existing_caretakers(apps, schema_editor):
    Machine = apps.get_model("core", "Machine")
    through_model = Machine.caretakers.through
    rows = [
        through_model(machine_id=machine.id, user_id=machine.caretaker_id)
        for machine in Machine.objects.exclude(caretaker_id__isnull=True).iterator()
    ]
    through_model.objects.bulk_create(rows, ignore_conflicts=True)


def restore_single_caretakers(apps, schema_editor):
    Machine = apps.get_model("core", "Machine")
    through_model = Machine.caretakers.through
    for machine in Machine.objects.all().iterator():
        caretaker_id = (
            through_model.objects.filter(machine_id=machine.id)
            .values_list("user_id", flat=True)
            .first()
        )
        if caretaker_id:
            Machine.objects.filter(pk=machine.pk).update(caretaker_id=caretaker_id)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0013_machine_telemetry_paused_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="machine",
            name="caretakers",
            field=models.ManyToManyField(
                blank=True,
                related_name="assigned_machines",
                to="core.user",
            ),
        ),
        migrations.RunPython(copy_existing_caretakers, restore_single_caretakers),
        migrations.RemoveField(
            model_name="machine",
            name="caretaker",
        ),
    ]
