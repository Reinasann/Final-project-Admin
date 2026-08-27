"""JSON API consumed by the Flutter app and ESP32 devices."""

import json
import secrets
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from functools import wraps

from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .models import (
    ApiToken, CollectionHistory, IssueCategory, IssueReport, Machine, MachineBin,
    Notification, NotificationEvent, NotificationType, PasswordResetCode,
    PushDevice, Telemetry, User,
)
from .push import send_notification_deliveries


def response_error(message, status=400):
    return JsonResponse({"detail": message}, status=status)


def json_body(request):
    try:
        return json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def decimal_value(value, field, minimum=None, maximum=None):
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{field} must be a number.")
    if minimum is not None and parsed < minimum:
        raise ValueError(f"{field} must be at least {minimum}.")
    if maximum is not None and parsed > maximum:
        raise ValueError(f"{field} must be at most {maximum}.")
    return parsed


def serialize_machine(machine):
    return {
        "id": machine.id,
        "code": machine.code,
        "serial_number": machine.device_id,
        "name": machine.name,
        "location": machine.location,
        "latitude": str(machine.latitude) if machine.latitude is not None else None,
        "longitude": str(machine.longitude) if machine.longitude is not None else None,
        "status": machine.status,
        "last_updated_at": machine.last_updated_at.isoformat() if machine.last_updated_at else None,
        "bins": [
            {
                "waste_type": item.waste_type,
                "weight_kg": str(item.current_weight_kg),
                "level_percent": str(item.current_level_percent),
                "last_measured_at": item.last_measured_at.isoformat() if item.last_measured_at else None,
            }
            for item in machine.bins.all()
        ],
    }


def serialize_user(user):
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "phone": user.phone,
        "role": user.role,
        "organization_id": user.organization_id,
        "organization_name": (
            user.organization.name if user.organization else "ผู้ดูแลระบบ"
        ),
    }


def inactive_account_message(status):
    if status == User.Status.SUSPENDED:
        return "บัญชีนี้ถูกระงับ กรุณาติดต่อผู้ดูแลหน่วยงาน"
    if status == User.Status.PENDING:
        return "บัญชีนี้ยังไม่ได้รับการอนุมัติ"
    return "บัญชีนี้ไม่พร้อมใช้งาน"


def token_required(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return response_error("Bearer token is required.", 401)
        raw_token = header[7:].strip()
        now = timezone.now()
        token = ApiToken.objects.select_related("user").filter(
            token_hash=ApiToken.digest_token(raw_token),
            revoked_at__isnull=True,
        ).first()
        if token is None or not token.is_valid(raw_token, now):
            return response_error("Invalid or expired token.", 401)
        if token.user.status != User.Status.ACTIVE:
            return response_error(inactive_account_message(token.user.status), 403)
        request.api_user = token.user
        request.api_token = token
        return view(request, *args, **kwargs)
    return wrapped


def visible_machines(user):
    machines = Machine.objects.select_related("organization").prefetch_related(
        "bins",
    ).order_by("-created_at", "-id")
    if user.role == User.Role.SUPER_ADMIN:
        return machines
    if not user.organization_id:
        return machines.none()
    return machines.filter(organization_id=user.organization_id)


WASTE_TYPE_LABELS = {
    MachineBin.WasteType.PLASTIC: "พลาสติก",
    MachineBin.WasteType.GLASS: "แก้ว",
    MachineBin.WasteType.CAN: "กระป๋อง",
}


def create_full_bin_notification(machine, bin_item, level):
    """Create one active event and deliver it to every active organization user."""
    notification_type, _ = NotificationType.objects.get_or_create(
        name="Bin full",
        defaults={
            "description": "แจ้งเตือนเมื่อระดับขยะถึงค่าที่กำหนด",
            "severity_level": NotificationType.Severity.HIGH,
        },
    )
    waste_label = WASTE_TYPE_LABELS.get(bin_item.waste_type, bin_item.waste_type)
    title = f"ถัง{waste_label}เต็มแล้ว"
    message = (
        f"ถัง{waste_label}ของเครื่อง {machine.name} มีระดับ {format(level, 'f')}% "
        "กรุณากดตอบรับเพื่อดำเนินการเก็บขยะ"
    )
    try:
        with transaction.atomic():
            event, created = NotificationEvent.objects.get_or_create(
                machine=machine,
                waste_type=bin_item.waste_type,
                resolved_at__isnull=True,
                defaults={
                    "notification_type": notification_type,
                    "title": title,
                    "message": message,
                },
            )
    except IntegrityError:
        event = NotificationEvent.objects.filter(
            machine=machine,
            waste_type=bin_item.waste_type,
            resolved_at__isnull=True,
        ).first()
        created = False
    if not created or event is None:
        return event

    recipients = User.objects.filter(
        organization=machine.organization,
        status=User.Status.ACTIVE,
    )
    deliveries = [
        Notification(
            recipient=recipient,
            machine=machine,
            notification_type=notification_type,
            event=event,
            action_required=True,
            title=title,
            message=message,
        )
        for recipient in recipients
    ]
    Notification.objects.bulk_create(deliveries)
    send_notification_deliveries(deliveries)
    return event


def resolve_full_bin_notification(machine, waste_type, resolved_at):
    NotificationEvent.objects.filter(
        machine=machine,
        waste_type=waste_type,
        resolved_at__isnull=True,
    ).update(resolved_at=resolved_at)


@csrf_exempt
@require_POST
def login(request):
    payload = json_body(request)
    if payload is None:
        return response_error("Request body must be valid JSON.")
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", ""))
    user = User.objects.filter(email__iexact=email).first()
    if not user or not user.check_password(password):
        return response_error("Invalid email or password.", 401)
    if user.status != User.Status.ACTIVE:
        return response_error(inactive_account_message(user.status), 403)
    raw_token = secrets.token_urlsafe(32)
    # The mobile app keeps its opaque token in encrypted device storage. The
    # session remains valid until the user explicitly logs out, an admin
    # suspends the account, or the token is revoked server-side.
    token = ApiToken(user=user, expires_at=None)
    token.set_token(raw_token)
    token.save()
    return JsonResponse({
        "access_token": raw_token,
        "token_type": "Bearer",
        "expires_in": None,
        "user": serialize_user(user),
    })


@csrf_exempt
@require_POST
@token_required
def logout(request):
    request.api_token.revoked_at = timezone.now()
    request.api_token.save(update_fields=["revoked_at"])
    return JsonResponse({"detail": "ออกจากระบบเรียบร้อยแล้ว"})


@csrf_exempt
@require_POST
def request_password_reset(request):
    payload = json_body(request)
    if payload is None:
        return response_error("Request body must be valid JSON.")
    email = str(payload.get("email", "")).strip().lower()
    if not email:
        return response_error("กรุณากรอกอีเมล")

    user = User.objects.filter(
        email__iexact=email,
        status=User.Status.ACTIVE,
    ).first()
    response = {
        "detail": "หากอีเมลนี้อยู่ในระบบ เราได้ส่งรหัสยืนยันให้แล้ว",
        "expires_in": 10 * 60,
    }
    if user is None:
        return JsonResponse(response)

    now = timezone.now()
    PasswordResetCode.objects.filter(
        user=user,
        used_at__isnull=True,
    ).update(used_at=now)
    raw_code = f"{secrets.randbelow(1000000):06d}"
    reset_code = PasswordResetCode(
        user=user,
        expires_at=now + timedelta(minutes=10),
    )
    reset_code.set_code(raw_code)
    reset_code.save()
    send_mail(
        subject="รหัสตั้งรหัสผ่านใหม่ Smart Recycle",
        message=(
            f"รหัสยืนยันของคุณคือ {raw_code}\n"
            "รหัสนี้มีอายุ 10 นาที หากคุณไม่ได้ส่งคำขอให้ละเว้นอีเมลนี้"
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )
    if settings.DEBUG:
        response["debug_code"] = raw_code
    return JsonResponse(response)


@csrf_exempt
@require_POST
def confirm_password_reset(request):
    payload = json_body(request)
    if payload is None:
        return response_error("Request body must be valid JSON.")
    email = str(payload.get("email", "")).strip().lower()
    code = str(payload.get("code", "")).strip()
    new_password = str(payload.get("new_password", ""))
    if len(new_password) < 8:
        return response_error("รหัสผ่านใหม่ต้องมีอย่างน้อย 8 ตัวอักษร")

    user = User.objects.filter(
        email__iexact=email,
        status=User.Status.ACTIVE,
    ).first()
    now = timezone.now()
    reset_code = None
    if user is not None:
        reset_code = PasswordResetCode.objects.filter(
            user=user,
            used_at__isnull=True,
            expires_at__gt=now,
        ).first()
    if reset_code is None or not reset_code.is_valid(now):
        return response_error("รหัสยืนยันไม่ถูกต้องหรือหมดอายุแล้ว")

    if not reset_code.check_code(code):
        reset_code.attempts += 1
        if reset_code.attempts >= 5:
            reset_code.used_at = now
            reset_code.save(update_fields=["attempts", "used_at"])
        else:
            reset_code.save(update_fields=["attempts"])
        return response_error("รหัสยืนยันไม่ถูกต้องหรือหมดอายุแล้ว")

    user.set_password(new_password)
    user.save(update_fields=["password"])
    reset_code.used_at = now
    reset_code.save(update_fields=["used_at"])
    ApiToken.objects.filter(user=user, revoked_at__isnull=True).update(
        revoked_at=now,
    )
    return JsonResponse({"detail": "ตั้งรหัสผ่านใหม่เรียบร้อยแล้ว"})


@require_GET
@token_required
def me(request):
    return JsonResponse(serialize_user(request.api_user))


@csrf_exempt
@require_POST
@token_required
def register_push_device(request):
    payload = json_body(request)
    if payload is None:
        return response_error("Request body must be valid JSON.")
    token = str(payload.get("token", "")).strip()
    platform = str(payload.get("platform", "android")).strip().lower()
    if not token or len(token) > 4096:
        return response_error("โทเคนอุปกรณ์ไม่ถูกต้อง")
    device, created = PushDevice.objects.update_or_create(
        token=token,
        defaults={
            "user": request.api_user,
            "platform": platform[:20] or "android",
            "is_active": True,
        },
    )
    return JsonResponse({
        "id": device.id,
        "registered": True,
    }, status=201 if created else 200)


@csrf_exempt
@require_POST
@token_required
def unregister_push_device(request):
    payload = json_body(request)
    if payload is None:
        return response_error("Request body must be valid JSON.")
    token = str(payload.get("token", "")).strip()
    PushDevice.objects.filter(
        user=request.api_user,
        token=token,
    ).update(is_active=False)
    return JsonResponse({"unregistered": True})


@csrf_exempt
@require_http_methods(["PATCH"])
@token_required
def update_profile(request):
    payload = json_body(request)
    if payload is None:
        return response_error("Request body must be valid JSON.")
    user = request.api_user
    user.name = str(payload.get("name", user.name)).strip() or user.name
    user.phone = str(payload.get("phone", user.phone)).strip()
    user.save(update_fields=["name", "phone"])
    return JsonResponse(serialize_user(user))


@csrf_exempt
@require_POST
@token_required
def change_password(request):
    payload = json_body(request)
    if payload is None:
        return response_error("Request body must be valid JSON.")
    old_password = str(payload.get("old_password", ""))
    new_password = str(payload.get("new_password", ""))
    user = request.api_user
    if not user.check_password(old_password):
        return response_error("Current password is incorrect.", 400)
    if len(new_password) < 8:
        return response_error("New password must contain at least 8 characters.")
    user.set_password(new_password)
    user.save(update_fields=["password"])
    return JsonResponse({"detail": "Password updated."})


@require_GET
@token_required
def machines(request):
    return JsonResponse({"results": [serialize_machine(machine) for machine in visible_machines(request.api_user)]})


@require_GET
@token_required
def machine_detail(request, machine_id):
    machine = visible_machines(request.api_user).filter(pk=machine_id).first()
    if machine is None:
        return response_error("Machine not found.", 404)
    return JsonResponse(serialize_machine(machine))


@csrf_exempt
@require_http_methods(["PATCH"])
@token_required
def update_machine_status(request, machine_id):
    payload = json_body(request)
    if payload is None or not isinstance(payload.get("is_on"), bool):
        return response_error("is_on must be a boolean.")
    machine = visible_machines(request.api_user).filter(pk=machine_id).first()
    if machine is None:
        return response_error("Machine not found.", 404)
    machine.status = Machine.Status.ONLINE if payload["is_on"] else Machine.Status.OFFLINE
    machine.last_updated_at = timezone.now()
    machine.save(update_fields=["status", "last_updated_at"])
    return JsonResponse(serialize_machine(machine))


@require_GET
@token_required
def telemetry_history(request, machine_id):
    machine = visible_machines(request.api_user).filter(pk=machine_id).first()
    if machine is None:
        return response_error("Machine not found.", 404)
    limit = min(max(int(request.GET.get("limit", 60)), 1), 500)
    rows = Telemetry.objects.filter(bin__machine=machine).select_related("bin")[:limit]
    return JsonResponse({"results": [
        {
            "waste_type": row.bin.waste_type, "weight_kg": str(row.weight_kg),
            "level_percent": str(row.level_percent), "recorded_at": row.recorded_at.isoformat(),
        } for row in rows
    ]})


@csrf_exempt
@require_POST
@token_required
def create_collection(request):
    payload = json_body(request)
    if payload is None:
        return response_error("Request body must be valid JSON.")
    machine = visible_machines(request.api_user).filter(pk=payload.get("machine_id")).first()
    if machine is None:
        return response_error("Machine not found.", 404)
    waste_type = payload.get("waste_type")
    bin_item = machine.bins.filter(waste_type=waste_type).first()
    if bin_item is None:
        return response_error("Waste type was not found on this machine.", 404)
    try:
        weight = decimal_value(payload.get("weight_kg"), "weight_kg", Decimal("0"))
    except ValueError as error:
        return response_error(str(error))
    item = CollectionHistory.objects.create(
        bin=bin_item, collector=request.api_user, weight_kg=weight, collected_at=timezone.now(),
        label_code=str(payload.get("label_code", ""))[:64],
    )
    bin_item.current_weight_kg = Decimal("0")
    bin_item.current_level_percent = Decimal("0")
    bin_item.last_measured_at = timezone.now()
    bin_item.save(update_fields=[
        "current_weight_kg", "current_level_percent", "last_measured_at",
    ])
    resolve_full_bin_notification(
        machine,
        bin_item.waste_type,
        bin_item.last_measured_at,
    )
    return JsonResponse({
        "id": item.id,
        "label_code": item.label_code,
        "collected_at": item.collected_at.isoformat(),
    }, status=201)


@require_GET
@token_required
def collections(request):
    rows = CollectionHistory.objects.select_related("bin__machine", "collector").filter(
        bin__machine__in=visible_machines(request.api_user)
    )
    if request.GET.get("mine") in {"1", "true", "True"}:
        rows = rows.filter(collector=request.api_user)
    rows = rows[:200]
    return JsonResponse({"results": [
        {
            "id": row.id, "machine_id": row.bin.machine_id, "machine_name": row.bin.machine.name,
            "waste_type": row.bin.waste_type, "weight_kg": str(row.weight_kg),
            "collector": row.collector.name, "collected_at": row.collected_at.isoformat(),
        } for row in rows
    ]})


@require_GET
@token_required
def issues(request):
    rows = IssueReport.objects.select_related("machine", "category", "reporter").filter(
        machine__in=visible_machines(request.api_user)
    )
    if request.GET.get("mine") in {"1", "true", "True"}:
        rows = rows.filter(reporter=request.api_user)
    return JsonResponse({"results": [
        {
            "id": row.id, "machine_id": row.machine_id, "machine_name": row.machine.name,
            "category": row.category.name,
            "description": row.description, "status": row.status,
            "reporter": row.reporter.name, "reported_at": row.reported_at.isoformat(),
        } for row in rows
    ]})


@require_GET
@token_required
def issue_categories(request):
    rows = IssueCategory.objects.filter(is_active=True).order_by("name")
    return JsonResponse({"results": [
        {"id": row.id, "name": row.name} for row in rows
    ]})


@csrf_exempt
@require_POST
@token_required
def create_issue(request):
    payload = json_body(request)
    if payload is None:
        return response_error("Request body must be valid JSON.")
    machine = visible_machines(request.api_user).filter(pk=payload.get("machine_id")).first()
    category = IssueCategory.objects.filter(pk=payload.get("category_id"), is_active=True).first()
    description = str(payload.get("description", "")).strip()
    if machine is None or category is None:
        return response_error("Machine or issue category was not found.", 404)
    if not description:
        return response_error("description is required.")
    item = IssueReport.objects.create(machine=machine, category=category, reporter=request.api_user, description=description)
    return JsonResponse({"id": item.id, "status": item.status, "reported_at": item.reported_at.isoformat()}, status=201)


@require_GET
@token_required
def notifications(request):
    rows = request.api_user.notifications.select_related(
        "machine", "notification_type", "event", "event__acknowledged_by",
    )[:200]
    return JsonResponse({"results": [
        {
            "id": row.id, "machine_id": row.machine_id, "title": row.title, "message": row.message,
            "severity": row.notification_type.severity_level, "is_read": row.is_read,
            "created_at": row.created_at.isoformat(),
            "requires_acknowledgement": bool(
                row.action_required
                and row.event_id
                and row.event.acknowledged_at is None
                and row.event.resolved_at is None
            ),
            "acknowledged_by_name": (
                row.event.acknowledged_by_name if row.event_id else ""
            ),
            "acknowledged_at": (
                row.event.acknowledged_at.isoformat()
                if row.event_id and row.event.acknowledged_at else None
            ),
        } for row in rows
    ]})


@csrf_exempt
@require_POST
@token_required
def mark_notification_read(request, notification_id):
    item = request.api_user.notifications.filter(pk=notification_id).first()
    if item is None:
        return response_error("Notification not found.", 404)
    item.is_read = True
    item.save(update_fields=["is_read"])
    return JsonResponse({"id": item.id, "is_read": True})


@csrf_exempt
@require_POST
@token_required
def acknowledge_notification(request, notification_id):
    delivery = request.api_user.notifications.filter(
        pk=notification_id,
        action_required=True,
        event__isnull=False,
    ).first()
    if delivery is None:
        return response_error("ไม่พบการแจ้งเตือนที่สามารถตอบรับได้", 404)

    now = timezone.now()
    acknowledgement_deliveries = []
    with transaction.atomic():
        event = NotificationEvent.objects.select_for_update().select_related(
            "machine", "notification_type",
        ).get(pk=delivery.event_id)
        if event.resolved_at is not None:
            delivery.is_read = True
            delivery.save(update_fields=["is_read"])
            return response_error("การแจ้งเตือนนี้ได้รับการจัดการแล้ว", 409)
        if event.acknowledged_at is not None:
            delivery.is_read = True
            delivery.save(update_fields=["is_read"])
            return JsonResponse({
                "event_id": event.id,
                "already_acknowledged": True,
                "acknowledged_by_name": event.acknowledged_by_name,
                "acknowledged_at": event.acknowledged_at.isoformat(),
            })

        event.acknowledged_by = request.api_user
        event.acknowledged_by_name = request.api_user.name
        event.acknowledged_at = now
        event.save(update_fields=[
            "acknowledged_by", "acknowledged_by_name", "acknowledged_at",
        ])
        Notification.objects.filter(
            event=event,
            action_required=True,
        ).update(is_read=True)

        title = "มีผู้ตอบรับการแจ้งเตือนแล้ว"
        waste_label = WASTE_TYPE_LABELS.get(event.waste_type, event.waste_type)
        message = (
            f"{request.api_user.name} ตอบรับการเก็บขยะประเภท{waste_label}ที่เครื่อง "
            f"{event.machine.name} แล้ว"
        )
        other_users = User.objects.filter(
            organization=event.machine.organization,
            status=User.Status.ACTIVE,
        ).exclude(pk=request.api_user.pk)
        acknowledgement_deliveries = [
            Notification(
                recipient=user,
                machine=event.machine,
                notification_type=event.notification_type,
                event=event,
                action_required=False,
                title=title,
                message=message,
            )
            for user in other_users
        ]
        Notification.objects.bulk_create(acknowledgement_deliveries)

    send_notification_deliveries(acknowledgement_deliveries)

    return JsonResponse({
        "event_id": event.id,
        "already_acknowledged": False,
        "acknowledged_by_name": event.acknowledged_by_name,
        "acknowledged_at": event.acknowledged_at.isoformat(),
    })


@csrf_exempt
@require_POST
def ingest_telemetry(request):
    """ESP32 endpoint. Device sends calculated weight and fill level every minute."""
    payload = json_body(request)
    if payload is None:
        return response_error("Request body must be valid JSON.")
    device_id = str(payload.get("device_id", ""))
    device_key = request.headers.get("X-Device-Key", "")
    machine = Machine.objects.select_related("device").prefetch_related("bins").filter(device_id=device_id).first()
    if machine is None or not machine.device.check_api_key(device_key):
        return response_error("Invalid device credentials.", 401)
    timestamp = parse_datetime(str(payload.get("recorded_at", ""))) or timezone.now()
    if timezone.is_naive(timestamp):
        timestamp = timezone.make_aware(timestamp, timezone.get_current_timezone())
    readings = payload.get("bins")
    if not isinstance(readings, list) or not readings:
        return response_error("bins must be a non-empty list.")
    bins_by_type = {item.waste_type: item for item in machine.bins.all()}
    created = []
    for reading in readings:
        if not isinstance(reading, dict) or reading.get("waste_type") not in bins_by_type:
            return response_error("Each reading must reference a configured waste_type.")
        try:
            weight = decimal_value(reading.get("weight_kg"), "weight_kg", Decimal("0"))
            level = decimal_value(reading.get("level_percent"), "level_percent", Decimal("0"), Decimal("100"))
        except ValueError as error:
            return response_error(str(error))
        bin_item = bins_by_type[reading["waste_type"]]
        telemetry, created_now = Telemetry.objects.get_or_create(
            bin=bin_item, recorded_at=timestamp,
            defaults={"weight_kg": weight, "level_percent": level, "raw_payload": reading},
        )
        if not created_now:
            telemetry.weight_kg, telemetry.level_percent, telemetry.raw_payload = weight, level, reading
            telemetry.save(update_fields=["weight_kg", "level_percent", "raw_payload"])
        bin_item.current_weight_kg = weight
        bin_item.current_level_percent = level
        bin_item.last_measured_at = timestamp
        bin_item.save(update_fields=["current_weight_kg", "current_level_percent", "last_measured_at"])
        if level >= bin_item.full_threshold_percent:
            create_full_bin_notification(machine, bin_item, level)
        else:
            resolve_full_bin_notification(machine, bin_item.waste_type, timestamp)
        created.append({"waste_type": bin_item.waste_type, "telemetry_id": telemetry.id})
    machine.status = Machine.Status.ONLINE
    machine.last_updated_at = timestamp
    machine.save(update_fields=["status", "last_updated_at"])
    machine.device.last_seen_at = timezone.now()
    machine.device.save(update_fields=["last_seen_at"])
    return JsonResponse({"machine_id": machine.id, "recorded_at": timestamp.isoformat(), "readings": created}, status=201)
