"""Compatibility adapters that expose SQLite records in the legacy template shape."""

from .models import CollectionHistory, IssueCategory, IssueReport, Machine, Organization, User
from django.utils import timezone


def display_date(value):
    return value.strftime('%d/%m/%Y') if value else '-'


def display_datetime(value):
    if not value:
        return '-'
    if timezone.is_aware(value):
        value = timezone.localtime(value)
    return value.strftime('%d/%m/%Y %H:%M')


def get_organizations(session):
    return [{'id': row.id, 'name': row.name, 'card_color': row.card_color} for row in Organization.objects.order_by('name')]


def get_machines(session):
    result = []
    for row in Machine.objects.select_related('device').prefetch_related('bins').all():
        bins = {bin.waste_type: bin for bin in row.bins.all()}
        level = lambda waste_type: float(bins[waste_type].current_level_percent) if waste_type in bins else 0
        result.append({'id': row.id, 'code': row.code, 'name': row.name, 'location': row.location,
                       'status': row.status, 'plastic': level('plastic'), 'glass': level('glass'),
                       'can': level('can'),
                       'latitude': str(row.latitude) if row.latitude is not None else '',
                       'longitude': str(row.longitude) if row.longitude is not None else '',
                       'serial_number': row.device_id or '',
                       'device_model': row.device.model if row.device else '',
                       'lastUpdate': display_datetime(row.last_updated_at),
                       'installDate': display_date(row.installed_on),
                       'organization_id': row.organization_id})
    return result


def get_users(session):
    return [{'id': row.id, 'name': row.name, 'email': row.email, 'phone': row.phone,
             'role': 'Admin' if row.role == User.Role.ORGANIZATION_ADMIN else ('System admin' if row.role == User.Role.SUPER_ADMIN else 'Collector'),
             'status': row.status, 'organization_id': row.organization_id}
            for row in User.objects.all()]


def get_issues(session):
    return [{'id': row.id, 'title': row.category.name, 'status': row.status,
             'time': row.reported_at.strftime('%H:%M'), 'reporter': row.reporter.name,
             'description': row.description, 'location': row.machine.name,
             'reportDate': row.reported_at.date().isoformat(), 'organization_id': row.machine.organization_id}
            for row in IssueReport.objects.select_related('category', 'reporter', 'machine').all()]


def get_topics(session):
    return list(IssueCategory.objects.filter(is_active=True).values_list('name', flat=True))


def get_collection_history():
    names = {'plastic': 'Plastic', 'glass': 'Glass', 'can': 'Can'}
    return [{'id': row.id, 'date': row.collected_at.date().isoformat(), 'time': row.collected_at.strftime('%H:%M'),
             'machine': row.bin.machine.name, 'type': names[row.bin.waste_type], 'weight': float(row.weight_kg),
             'staff': row.collector.name, 'organization_id': row.bin.machine.organization_id}
            for row in CollectionHistory.objects.select_related('bin__machine', 'collector').all()]


MOCK_COLLECTION_HISTORY = []  # Kept only to avoid imports in older code; views use get_collection_history().
