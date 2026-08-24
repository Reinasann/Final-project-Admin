from django.db import migrations


THAI_CATEGORY_NAMES = {
    "Machine not working": "เครื่องไม่ทำงาน",
    "Sensor abnormal": "เซ็นเซอร์ผิดปกติ",
    "Bin damaged": "ถังขยะชำรุด",
    "Electrical issue": "ระบบไฟฟ้าขัดข้อง",
    "Other": "อื่น ๆ",
}


def translate_categories(apps, schema_editor):
    issue_category = apps.get_model("core", "IssueCategory")
    for english_name, thai_name in THAI_CATEGORY_NAMES.items():
        issue_category.objects.filter(name=english_name).update(name=thai_name)


def restore_categories(apps, schema_editor):
    issue_category = apps.get_model("core", "IssueCategory")
    for english_name, thai_name in THAI_CATEGORY_NAMES.items():
        issue_category.objects.filter(name=thai_name).update(name=english_name)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0003_alter_machinebin_waste_type"),
    ]

    operations = [
        migrations.RunPython(translate_categories, restore_categories),
    ]
