from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0006_passwordresetcode"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="machine",
            name="caretaker",
        ),
    ]
