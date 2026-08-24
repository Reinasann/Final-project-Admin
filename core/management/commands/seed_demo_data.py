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
        city, _ = Organization.objects.get_or_create(id="org-2", defaults={"name": "ศูนย์รีไซเคิลเมือง", "card_color": "#16a34a"})
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
