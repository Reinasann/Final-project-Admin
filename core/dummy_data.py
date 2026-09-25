"""Compatibility adapters that expose SQLite records in the legacy template shape."""

from datetime import datetime

from .models import CollectionHistory, IssueCategory, IssueReport, Machine, Organization, User
from django.utils import timezone


def local_datetime(value):
    if isinstance(value, datetime) and timezone.is_aware(value):
        return timezone.localtime(value)
    return value


def display_date(value):
    value = local_datetime(value)
    return value.strftime('%d/%m/%Y') if value else '-'


def display_datetime(value):
    if not value:
        return '-'
    value = local_datetime(value)
    return value.strftime('%d/%m/%Y %H:%M')


def get_organizations(session):
    return [
        {
            'id': row.id,
            'name': row.name,
            'card_color': row.card_color,
            'status': row.status,
            'created_at': row.created_at,
        }
        for row in Organization.objects.order_by('name')
    ]


def get_machines(session):
    result = []
    rows = Machine.objects.select_related('device').prefetch_related('bins', 'caretakers').order_by(
        '-created_at', '-id',
    )
    for row in rows:
        bins = {bin.waste_type: bin for bin in row.bins.all()}
        caretakers = sorted(
            row.caretakers.all(),
            key=lambda caretaker: (caretaker.name.casefold(), caretaker.id),
        )
        level = lambda waste_type: float(bins[waste_type].current_level_percent) if waste_type in bins else 0
        result.append({'id': row.id, 'code': row.code, 'name': row.name, 'location': row.location,
                       'status': row.status, 'plastic': level('plastic'), 'glass': level('glass'),
                       'can': level('can'),
                       'latitude': str(row.latitude) if row.latitude is not None else '',
                       'longitude': str(row.longitude) if row.longitude is not None else '',
                       'serial_number': row.device_id or '',
                       'device_model': row.device.model if row.device else '',
                       'caretaker_ids': [caretaker.id for caretaker in caretakers],
                       'caretaker_ids_csv': ','.join(caretaker.id for caretaker in caretakers),
                       'caretaker_names': ', '.join(caretaker.name for caretaker in caretakers),
                       'lastUpdate': display_datetime(row.last_updated_at),
                       'installDate': display_date(row.installed_on),
                       'organization_id': row.organization_id})
    return result


def get_users(session):
    return [{'id': row.id, 'name': row.name, 'email': row.email, 'phone': row.phone,
             'role': 'Admin' if row.role == User.Role.ORGANIZATION_ADMIN else ('System admin' if row.role == User.Role.SUPER_ADMIN else 'Collector'),
             'status': row.status, 'organization_id': row.organization_id}
            for row in User.objects.order_by('-created_at', '-id')]


def get_issues(session):
    result = []
    for row in IssueReport.objects.select_related('category', 'reporter', 'machine').all():
        reported_at = local_datetime(row.reported_at)
        result.append({
            'id': row.id, 'title': row.category.name, 'status': row.status,
            'time': reported_at.strftime('%H:%M'), 'reporter': row.reporter.name,
            'description': row.description, 'location': row.machine.name,
            'reportDate': reported_at.date().isoformat(),
            'organization_id': row.machine.organization_id,
            'escalated': bool(row.escalated_at),
            'escalated_at': display_datetime(row.escalated_at) if row.escalated_at else '',
            'escalated_by': row.escalated_by.name if row.escalated_by else '',
        })
    return result


def get_topics(session):
    return list(IssueCategory.objects.filter(is_active=True).values_list('name', flat=True))


def get_collection_history():
    names = {'plastic': 'Plastic', 'glass': 'Glass', 'can': 'Can'}
    result = []
    for row in CollectionHistory.objects.select_related('bin__machine', 'collector').all():
        collected_at = local_datetime(row.collected_at)
        result.append({
            'id': row.id, 'date': collected_at.date().isoformat(),
            'time': collected_at.strftime('%H:%M'), 'machine': row.bin.machine.name,
            'type': names[row.bin.waste_type], 'weight': float(row.weight_kg),
            'staff': row.collector.name,
            'organization_id': row.bin.machine.organization_id,
        })
    return result


MOCK_COLLECTION_HISTORY = []  # Kept only to avoid imports in older code; views use get_collection_history().
