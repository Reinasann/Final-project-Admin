"""Optional Firebase Cloud Messaging delivery for saved notifications."""

import logging
from pathlib import Path

from django.conf import settings

from .models import PushDevice


logger = logging.getLogger(__name__)


def _firebase_app():
    credential_path = str(getattr(settings, "FIREBASE_CREDENTIALS", "")).strip()
    if not credential_path or not Path(credential_path).is_file():
        return None
    try:
        import firebase_admin
        from firebase_admin import credentials

        try:
            return firebase_admin.get_app()
        except ValueError:
            return firebase_admin.initialize_app(
                credentials.Certificate(credential_path),
            )
    except Exception:
        logger.exception("Unable to initialize Firebase Admin SDK")
        return None


def send_notification_deliveries(deliveries):
    """Send each saved notification to every active device of its recipient."""
    deliveries = list(deliveries)
    app = _firebase_app()
    if app is None or not deliveries:
        return 0
    try:
        from firebase_admin import messaging

        devices_by_user = {}
        for device in PushDevice.objects.filter(
            user_id__in={item.recipient_id for item in deliveries},
            is_active=True,
        ):
            devices_by_user.setdefault(device.user_id, []).append(device.token)

        messages = []
        for delivery in deliveries:
            for token in devices_by_user.get(delivery.recipient_id, []):
                messages.append(messaging.Message(
                    token=token,
                    notification=messaging.Notification(
                        title=delivery.title,
                        body=delivery.message,
                    ),
                    data={
                        "notification_id": str(delivery.id or ""),
                        "machine_id": delivery.machine_id,
                        "action_required": (
                            "true" if delivery.action_required else "false"
                        ),
                    },
                    android=messaging.AndroidConfig(
                        priority="high",
                        notification=messaging.AndroidNotification(
                            channel_id="smart_recycle_alerts",
                            sound="default",
                        ),
                    ),
                ))
        if not messages:
            return 0
        response = messaging.send_each(messages, app=app)
        if response.failure_count:
            logger.warning(
                "FCM delivered %s of %s messages",
                response.success_count,
                len(messages),
            )
        return response.success_count
    except Exception:
        logger.exception("Unable to send Firebase push notifications")
        return 0
