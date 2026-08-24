"""Persistent SQLite models for the Smart Recycle system."""

import hashlib
import hmac

from django.contrib.auth.hashers import check_password, make_password
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models.functions import Lower


class Organization(models.Model):
    id = models.CharField(max_length=32, primary_key=True)
    name = models.CharField(max_length=150, unique=True)
    card_color = models.CharField(max_length=7, default="#2563eb")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                Lower("card_color"),
                name="uniq_organization_card_color_ci",
            ),
        ]

    def __str__(self):
        return self.name


class User(models.Model):
    class Role(models.TextChoices):
        ORGANIZATION_ADMIN = "OrganizationAdmin", "Organization admin"
        SUPER_ADMIN = "SuperAdmin", "Super admin"
        COLLECTOR = "Collector", "Collector"

    class Status(models.TextChoices):
        ACTIVE = "Active", "Active"
        PENDING = "Pending", "Pending"
        SUSPENDED = "Suspended", "Suspended"

    id = models.CharField(max_length=20, primary_key=True)
    organization = models.ForeignKey(
        Organization, on_delete=models.PROTECT, related_name="users", null=True, blank=True
    )
    name = models.CharField(max_length=100)
    password = models.CharField(max_length=128)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.COLLECTOR)
    email = models.EmailField(max_length=100, unique=True)
    phone = models.CharField(max_length=15, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)

    def set_password(self, raw_password):
        self.password = make_password(raw_password)

    def check_password(self, raw_password):
        return check_password(raw_password, self.password)

    def __str__(self):
        return self.name


class MachineInformation(models.Model):
    class HardwareStatus(models.TextChoices):
        AVAILABLE = "Available", "Available"
        INSTALLED = "Installed", "Installed"
        MAINTENANCE = "Maintenance", "Maintenance"
        DEFECTIVE = "Defective", "Defective"

    serial_number = models.CharField(max_length=30, primary_key=True)
    model = models.CharField(max_length=50)
    hardware_status = models.CharField(
        max_length=20, choices=HardwareStatus.choices, default=HardwareStatus.AVAILABLE
    )
    api_key_hash = models.CharField(max_length=128, blank=True)
    firmware_version = models.CharField(max_length=50, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    def set_api_key(self, raw_key):
        self.api_key_hash = make_password(raw_key)

    def check_api_key(self, raw_key):
        return bool(self.api_key_hash) and check_password(raw_key, self.api_key_hash)

    def __str__(self):
        return self.serial_number


class Machine(models.Model):
    class Status(models.TextChoices):
        ONLINE = "Online", "Online"
        OFFLINE = "Offline", "Offline"
        MAINTENANCE = "Maintenance", "Maintenance"

    id = models.CharField(max_length=20, primary_key=True)
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="machines")
    device = models.OneToOneField(
        MachineInformation, on_delete=models.PROTECT, related_name="machine", null=True, blank=True
    )
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    location = models.CharField(max_length=255)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OFFLINE)
    installed_on = models.DateField(null=True, blank=True)
    last_updated_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.code} - {self.name}"


class MachineBin(models.Model):
    class WasteType(models.TextChoices):
        PLASTIC = "plastic", "Plastic/PET"
        GLASS = "glass", "Glass"
        CAN = "can", "Aluminium can"

    machine = models.ForeignKey(Machine, on_delete=models.CASCADE, related_name="bins")
    waste_type = models.CharField(max_length=10, choices=WasteType.choices)
    capacity_kg = models.DecimalField(max_digits=9, decimal_places=2, null=True, blank=True)
    full_threshold_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=90,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    current_weight_kg = models.DecimalField(max_digits=9, decimal_places=2, default=0)
    current_level_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    last_measured_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["machine", "waste_type"], name="unique_machine_bin_type")]

    def __str__(self):
        return f"{self.machine_id}:{self.waste_type}"


class Telemetry(models.Model):
    """An immutable measurement submitted by ESP32; one row per bin and minute."""

    bin = models.ForeignKey(MachineBin, on_delete=models.CASCADE, related_name="telemetry")
    recorded_at = models.DateTimeField()
    weight_kg = models.DecimalField(max_digits=9, decimal_places=2)
    level_percent = models.DecimalField(
        max_digits=5, decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    raw_payload = models.JSONField(default=dict, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-recorded_at"]
        constraints = [models.UniqueConstraint(fields=["bin", "recorded_at"], name="unique_bin_measurement_time")]
        indexes = [models.Index(fields=["bin", "-recorded_at"])]


class NotificationType(models.Model):
    class Severity(models.TextChoices):
        LOW = "Low", "Low"
        MEDIUM = "Medium", "Medium"
        HIGH = "High", "High"
        CRITICAL = "Critical", "Critical"

    name = models.CharField(max_length=150, unique=True)
    description = models.CharField(max_length=500, blank=True)
    severity_level = models.CharField(max_length=20, choices=Severity.choices, default=Severity.MEDIUM)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class NotificationEvent(models.Model):
    """One organization-wide alert with at most one accepting user."""

    machine = models.ForeignKey(
        Machine,
        on_delete=models.CASCADE,
        related_name="notification_events",
    )
    notification_type = models.ForeignKey(NotificationType, on_delete=models.PROTECT)
    waste_type = models.CharField(max_length=10, choices=MachineBin.WasteType.choices)
    title = models.CharField(max_length=150)
    message = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)
    acknowledged_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name="acknowledged_notification_events",
        null=True,
        blank=True,
    )
    acknowledged_by_name = models.CharField(max_length=150, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["machine", "waste_type"],
                condition=models.Q(resolved_at__isnull=True),
                name="unique_active_bin_notification",
            ),
        ]
        indexes = [
            models.Index(
                fields=["machine", "waste_type", "-created_at"],
                name="core_notif_machine_waste_idx",
            ),
        ]


class Notification(models.Model):
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    machine = models.ForeignKey(Machine, on_delete=models.CASCADE, related_name="notifications")
    notification_type = models.ForeignKey(NotificationType, on_delete=models.PROTECT)
    event = models.ForeignKey(
        NotificationEvent,
        on_delete=models.CASCADE,
        related_name="deliveries",
        null=True,
        blank=True,
    )
    action_required = models.BooleanField(default=False)
    title = models.CharField(max_length=150)
    message = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]


class CollectionHistory(models.Model):
    bin = models.ForeignKey(MachineBin, on_delete=models.PROTECT, related_name="collections")
    collector = models.ForeignKey(User, on_delete=models.PROTECT, related_name="collections")
    weight_kg = models.DecimalField(max_digits=9, decimal_places=2)
    collected_at = models.DateTimeField()
    label_code = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["-collected_at"]
        indexes = [models.Index(fields=["collector", "-collected_at"])]


class IssueCategory(models.Model):
    class Priority(models.TextChoices):
        LOW = "Low", "Low"
        MEDIUM = "Medium", "Medium"
        HIGH = "High", "High"
        CRITICAL = "Critical", "Critical"

    name = models.CharField(max_length=150, unique=True)
    description = models.CharField(max_length=255, blank=True)
    priority_level = models.CharField(max_length=20, choices=Priority.choices, default=Priority.MEDIUM)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class IssueReport(models.Model):
    class Status(models.TextChoices):
        WAITING = "Waiting", "Waiting"
        IN_PROGRESS = "In Progress", "In progress"
        COMPLETED = "Completed", "Completed"

    machine = models.ForeignKey(Machine, on_delete=models.PROTECT, related_name="issue_reports")
    category = models.ForeignKey(IssueCategory, on_delete=models.PROTECT, related_name="reports")
    reporter = models.ForeignKey(User, on_delete=models.PROTECT, related_name="issue_reports")
    description = models.CharField(max_length=500)
    reported_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.WAITING)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-reported_at"]


class ApiToken(models.Model):
    """Opaque Bearer token for Flutter clients, stored only as a hash."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="api_tokens")
    token_hash = models.CharField(max_length=128, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    @staticmethod
    def digest_token(raw_token):
        return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    def set_token(self, raw_token):
        self.token_hash = self.digest_token(raw_token)

    def is_valid(self, raw_token, now):
        return (
            self.revoked_at is None
            and (self.expires_at is None or self.expires_at > now)
            and hmac.compare_digest(
                self.token_hash,
                self.digest_token(raw_token),
            )
        )


class PushDevice(models.Model):
    """FCM registration token belonging to a signed-in mobile device."""

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="push_devices",
    )
    token = models.TextField(unique=True)
    platform = models.CharField(max_length=20, default="android")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["user", "is_active"],
                name="core_push_user_active_idx",
            ),
        ]


class PasswordResetCode(models.Model):
    """Short-lived one-time code used by the Flutter password reset flow."""

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="password_reset_codes",
    )
    code_hash = models.CharField(max_length=128)
    attempts = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["user", "-created_at"],
                name="core_pwd_user_created_idx",
            ),
        ]

    def set_code(self, raw_code):
        self.code_hash = make_password(raw_code)

    def check_code(self, raw_code):
        return check_password(raw_code, self.code_hash)

    def is_valid(self, now):
        return self.used_at is None and self.expires_at > now and self.attempts < 5
