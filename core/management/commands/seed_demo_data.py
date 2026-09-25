from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from core.models import (
    CollectionHistory, IssueCategory, Machine, MachineBin, MachineInformation, NotificationType,
    Organization, User,
)


class Command(BaseCommand):
    help = "Create a local demo organization, collector, machine, bins, and ESP32 device."

    def handle(self, *args, **options):
        organization, _ = Organization.objects.get_or_create(
            id="org-1", defaults={"name": "Green Campus", "card_color": "#2563eb"}
        )
        user, _ = User.objects.get_or_create(
            id="U001",
            defaults={
                "organization": organization, "name": "Recycle Collector",
                "email": "staff@recycle.com", "role": User.Role.COLLECTOR,
                "status": User.Status.ACTIVE,
            },
        )
        user.organization = organization
        user.name = "Recycle Collector"
        user.email = "staff@recycle.com"
        user.role = User.Role.COLLECTOR
        user.status = User.Status.ACTIVE
        user.set_password("12345678")
        user.save()
        for user_id, name, email, role, org in [
            ("A001", "ผู้ดูแล Green Campus", "admin@recycle.com", User.Role.ORGANIZATION_ADMIN, organization),
            ("SA001", "ผู้ดูแลระบบสูงสุด", "superadmin@recycle.com", User.Role.SUPER_ADMIN, None),
        ]:
            admin, _ = User.objects.get_or_create(
                id=user_id,
                defaults={"name": name, "email": email, "role": role, "status": User.Status.ACTIVE},
            )
            admin.name = name
            admin.email = email
            admin.role = role
            admin.organization = org
            admin.status = User.Status.ACTIVE
            admin.set_password("12345678")
            admin.save()
        device, _ = MachineInformation.objects.get_or_create(
            serial_number="ESP32-SR-001", defaults={"model": "ESP32"}
        )
        device.model = "ESP32"
        device.hardware_status = MachineInformation.HardwareStatus.INSTALLED
        device.set_api_key("change-this-device-key")
        device.save()
        machine, _ = Machine.objects.get_or_create(
            id="M001",
            defaults={
                "organization": organization, "device": device,
                "code": "SR-001", "name": "Recycle Station A", "location": "Central Cafeteria",
            },
        )
        machine.organization = organization
        machine.device = device
        machine.save()
        CollectionHistory.objects.filter(bin__waste_type='unsorted').delete()
        MachineBin.objects.filter(waste_type='unsorted').delete()
        for waste_type in MachineBin.WasteType.values:
            MachineBin.objects.get_or_create(machine=machine, waste_type=waste_type)
        demo_organizations = []
        for organization_id, name, color in [
            ("org-2", "เทศบาลเมืองสีเขียว", "#16a34a"),
            ("org-3", "มหาวิทยาลัยรักษ์โลก", "#9333ea"),
        ]:
            demo_organization, _ = Organization.objects.get_or_create(
                id=organization_id,
                defaults={"name": name, "card_color": color},
            )
            demo_organization.name = name
            demo_organization.card_color = color
            demo_organization.status = Organization.Status.ACTIVE
            demo_organization.save(update_fields=["name", "card_color", "status"])
            demo_organizations.append(demo_organization)
        for machine_id, code, name, location, org in [
            ("M002", "SR-002", "สถานีรีไซเคิล B", "หอพักนักศึกษา", organization),
            ("M003", "SR-003", "สถานีรีไซเคิล C", "อาคารเรียน 5", organization),
            ("M004", "SR-004", "สถานีรีไซเคิล D", "ลานกิจกรรม", organization),
        ]:
            extra_device, _ = MachineInformation.objects.get_or_create(
                serial_number=f"ESP32-{code}",
                defaults={"model": "ESP32"},
            )
            extra_device.model = "ESP32"
            extra_device.hardware_status = MachineInformation.HardwareStatus.INSTALLED
            if not extra_device.api_key_hash:
                extra_device.set_api_key(f"change-this-device-key-{code[-3:]}")
            extra_device.save()
            extra, _ = Machine.objects.get_or_create(
                id=machine_id, defaults={"organization": org, "device": extra_device, "code": code, "name": name, "location": location, "status": Machine.Status.ONLINE}
            )
            extra.organization, extra.device, extra.code, extra.name, extra.location, extra.status = org, extra_device, code, name, location, Machine.Status.ONLINE
            extra.save()
            for waste_type in MachineBin.WasteType.values:
                bin_row, _ = MachineBin.objects.get_or_create(machine=extra, waste_type=waste_type)
                bin_row.current_weight_kg = {"plastic": 4.5, "glass": 9.2, "can": 2.8}[waste_type]
                bin_row.current_level_percent = {"plastic": 35, "glass": 72, "can": 20}[waste_type]
                bin_row.last_measured_at = timezone.now()
                bin_row.save()

        # Two active organizations with users, online machines, bin readings,
        # and recent collection history make the admin views realistic while
        # remaining deterministic and safe to seed more than once.
        for index, demo_organization in enumerate(demo_organizations, start=1):
            collector_id = f"U10{index}"
            admin_id = f"A10{index}"
            collector_email = f"collector{index}@demo.recycle.local"
            admin_email = f"admin{index}@demo.recycle.local"
            collector, _ = User.objects.get_or_create(
                id=collector_id,
                defaults={
                    "organization": demo_organization,
                    "name": f"เจ้าหน้าที่เก็บขยะ {demo_organization.name}",
                    "email": collector_email,
                    "role": User.Role.COLLECTOR,
                    "status": User.Status.ACTIVE,
                },
            )
            collector.organization = demo_organization
            collector.name = f"เจ้าหน้าที่เก็บขยะ {demo_organization.name}"
            collector.email = collector_email
            collector.role = User.Role.COLLECTOR
            collector.status = User.Status.ACTIVE
            collector.set_password("12345678")
            collector.save()

            organization_admin, _ = User.objects.get_or_create(
                id=admin_id,
                defaults={
                    "organization": demo_organization,
                    "name": f"ผู้ดูแล {demo_organization.name}",
                    "email": admin_email,
                    "role": User.Role.ORGANIZATION_ADMIN,
                    "status": User.Status.ACTIVE,
                },
            )
            organization_admin.organization = demo_organization
            organization_admin.name = f"ผู้ดูแล {demo_organization.name}"
            organization_admin.email = admin_email
            organization_admin.role = User.Role.ORGANIZATION_ADMIN
            organization_admin.status = User.Status.ACTIVE
            organization_admin.set_password("12345678")
            organization_admin.save()

            serial_number = f"ESP32-SIM-{index:03d}"
            machine_id = f"MSIM{index:03d}"
            machine_code = f"SIM-{index:03d}"
            demo_device, _ = MachineInformation.objects.get_or_create(
                serial_number=serial_number,
                defaults={"model": "ESP32-WROOM-32"},
            )
            demo_device.model = "ESP32-WROOM-32"
            demo_device.hardware_status = MachineInformation.HardwareStatus.INSTALLED
            if not demo_device.api_key_hash:
                demo_device.set_api_key(f"demo-device-key-{index:03d}")
            demo_device.save()

            demo_machine, _ = Machine.objects.get_or_create(
                id=machine_id,
                defaults={
                    "organization": demo_organization,
                    "device": demo_device,
                    "code": machine_code,
                    "name": f"จุดคัดแยก {demo_organization.name}",
                    "location": "อาคารบริการส่วนกลาง",
                    "status": Machine.Status.ONLINE,
                    "installed_on": timezone.localdate() - timedelta(days=90 * index),
                },
            )
            demo_machine.organization = demo_organization
            demo_machine.device = demo_device
            demo_machine.code = machine_code
            demo_machine.name = f"จุดคัดแยก {demo_organization.name}"
            demo_machine.location = "อาคารบริการส่วนกลาง"
            demo_machine.status = Machine.Status.ONLINE
            demo_machine.last_updated_at = timezone.now()
            demo_machine.save()
            demo_machine.caretakers.set([collector])

            bin_settings = {
                "plastic": (6.5 + index, 48 + index * 4),
                "glass": (8.0 + index, 55 + index * 3),
                "can": (3.0 + index, 34 + index * 2),
            }
            demo_bins = {}
            for waste_type in MachineBin.WasteType.values:
                bin_row, _ = MachineBin.objects.get_or_create(
                    machine=demo_machine,
                    waste_type=waste_type,
                )
                weight, level = bin_settings[waste_type]
                bin_row.current_weight_kg = weight
                bin_row.current_level_percent = level
                bin_row.last_measured_at = timezone.now()
                bin_row.save()
                demo_bins[waste_type] = bin_row

            for offset, waste_type, weight in [
                (index, "plastic", 2.5 + index),
                (index + 2, "glass", 4.0 + index),
                (index + 4, "can", 1.5 + index),
            ]:
                label_code = f"DEMO-{machine_id}-{waste_type.upper()}"
                collected_at = timezone.now() - timedelta(days=offset)
                history_row = CollectionHistory.objects.filter(
                    label_code=label_code,
                ).order_by("id").first()
                if history_row is None:
                    CollectionHistory.objects.create(
                        bin=demo_bins[waste_type],
                        collector=collector,
                        weight_kg=weight,
                        collected_at=collected_at,
                        label_code=label_code,
                    )
                else:
                    history_row.bin = demo_bins[waste_type]
                    history_row.collector = collector
                    history_row.weight_kg = weight
                    history_row.collected_at = collected_at
                    history_row.save(update_fields=[
                        "bin", "collector", "weight_kg", "collected_at",
                    ])
        prepared_device, _ = MachineInformation.objects.get_or_create(
            serial_number="ESP32-SR-005",
            defaults={
                "model": "ESP32-S3",
                "hardware_status": MachineInformation.HardwareStatus.AVAILABLE,
                "firmware_version": "1.0.0",
            },
        )
        if not prepared_device.api_key_hash:
            prepared_device.set_api_key("change-this-device-key-005")
        if not Machine.objects.filter(device=prepared_device).exists():
            prepared_device.hardware_status = MachineInformation.HardwareStatus.AVAILABLE
        prepared_device.save()
        for name, priority in [
            ("เครื่องไม่ทำงาน", "High"), ("เซ็นเซอร์ผิดปกติ", "High"),
            ("ถังขยะชำรุด", "Medium"), ("ระบบไฟฟ้าขัดข้อง", "Critical"),
            ("อื่น ๆ", "Low"),
        ]:
            IssueCategory.objects.get_or_create(name=name, defaults={"priority_level": priority})
        NotificationType.objects.get_or_create(
            name="Bin full", defaults={"severity_level": NotificationType.Severity.HIGH}
        )
        # Current-year collection rows for charts, history, and reports.
        CollectionHistory.objects.filter(collected_at__year__lt=timezone.now().year).delete()
        for offset, waste_type, weight in [(0, 'plastic', 3.4), (1, 'glass', 5.8), (2, 'can', 1.7)]:
            bin_row = MachineBin.objects.get(machine=machine, waste_type=waste_type)
            CollectionHistory.objects.get_or_create(
                bin=bin_row, collector=user, collected_at=timezone.now() - timedelta(days=offset),
                defaults={"weight_kg": weight},
            )
        self.stdout.write(self.style.SUCCESS(
            "Demo data is ready. ESP32 key: change-this-device-key"
        ))
