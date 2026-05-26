from django.db import migrations


def rename_forward(apps, schema_editor):
    HardwareTarget = apps.get_model("catalog", "HardwareTarget")
    # Rename the existing row in place so its images / cache (FK by id) stay
    # attached; skip if a pc-arm64 row already exists.
    if (HardwareTarget.objects.filter(slug="generic-arm64").exists()
            and not HardwareTarget.objects.filter(slug="pc-arm64").exists()):
        HardwareTarget.objects.filter(slug="generic-arm64").update(
            slug="pc-arm64", name="Generic ARM64 PC (UEFI)",
        )


def rename_backward(apps, schema_editor):
    HardwareTarget = apps.get_model("catalog", "HardwareTarget")
    if (HardwareTarget.objects.filter(slug="pc-arm64").exists()
            and not HardwareTarget.objects.filter(slug="generic-arm64").exists()):
        HardwareTarget.objects.filter(slug="pc-arm64").update(
            slug="generic-arm64", name="Generic ARM64 server",
        )


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0008_upstreamimage_extra_targets"),
    ]

    operations = [
        migrations.RunPython(rename_forward, rename_backward),
    ]
