import hashlib
import re

from django.db import migrations, models
from django.db.models.functions import Lower


COLOR_PALETTE = [
    "#2563eb", "#16a34a", "#f97316", "#9333ea", "#0891b2", "#db2777",
    "#ca8a04", "#4f46e5", "#0f766e", "#dc2626", "#64748b", "#7c3aed",
]


def make_unique_organization_colors(apps, schema_editor):
    organization = apps.get_model("core", "Organization")
    seen = set()

    for org in organization.objects.order_by("created_at", "id"):
        color = (org.card_color or "").strip().lower()
        if not re.fullmatch(r"#[0-9a-f]{6}", color) or color in seen:
            color = next((item for item in COLOR_PALETTE if item not in seen), None)
            salt = 0
            while color is None or color in seen:
                digest = hashlib.sha256(f"{org.pk}:{salt}".encode()).hexdigest()[:6]
                color = f"#{digest}"
                salt += 1
        if org.card_color != color:
            organization.objects.filter(pk=org.pk).update(card_color=color)
        seen.add(color)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0004_translate_issue_categories"),
    ]

    operations = [
        migrations.RunPython(make_unique_organization_colors, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="organization",
            constraint=models.UniqueConstraint(
                Lower("card_color"),
                name="uniq_organization_card_color_ci",
            ),
        ),
    ]
