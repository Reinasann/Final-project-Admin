import time
import copy
import csv
import re
import secrets
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from io import StringIO
from django.db import IntegrityError, transaction
from django.db.models import Count, F, Max, Q
from django.core.paginator import Paginator
from django.shortcuts import render, redirect
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST
from .dummy_data import (
    get_organizations, get_machines, get_users, get_issues, get_topics,
    get_collection_history
)
from . import api
from .models import (
    ApiToken, CollectionHistory, IssueCategory, IssueReport, Machine, MachineBin,
    MachineCommand, MachineInformation, Organization, User,
)

# JSON API handlers are re-exported here to preserve the existing URL module shape.
api_login = api.login
api_logout = api.logout
api_request_password_reset = api.request_password_reset
api_confirm_password_reset = api.confirm_password_reset
api_me = api.me
api_register_push_device = api.register_push_device
api_unregister_push_device = api.unregister_push_device
api_update_profile = api.update_profile
api_change_password = api.change_password
api_machines = api.machines
api_machine_detail = api.machine_detail
api_update_machine_status = api.update_machine_status
api_telemetry_history = api.telemetry_history
api_collections = api.collections
api_create_collection = api.create_collection
api_issues = api.issues
api_issue_categories = api.issue_categories
api_create_issue = api.create_issue
api_notifications = api.notifications
api_mark_notification_read = api.mark_notification_read
api_acknowledge_notification = api.acknowledge_notification
api_ingest_telemetry = api.ingest_telemetry
api_poll_device_command = api.poll_device_command
api_acknowledge_device_command = api.acknowledge_device_command

SYSTEM_ADMIN = 'System admin'
ORG_ADMIN = 'Admin'
WASTE_TYPES = ['Plastic', 'Glass', 'Can']
WASTE_TYPE_LABELS = {
    'Plastic': 'พลาสติก',
    'Glass': 'แก้ว',
    'Can': 'กระป๋อง',
}
ORGANIZATION_COLOR_PALETTE = [
    '#2563eb', '#16a34a', '#f97316', '#9333ea', '#0891b2', '#db2777',
    '#ca8a04', '#4f46e5', '#0f766e', '#dc2626', '#64748b', '#7c3aed',
]
ADMIN_PAGE_SIZE_OPTIONS = (10, 25, 50, 100)


def paginate_admin(request, items, *, page_param='page', size_param='page_size', default_size=10):
    """Paginate an admin dataset while accepting only supported page sizes."""
    try:
        page_size = int(request.GET.get(size_param, default_size))
    except (TypeError, ValueError):
        page_size = default_size
    if page_size not in ADMIN_PAGE_SIZE_OPTIONS:
        page_size = default_size

    paginator = Paginator(items, page_size)
    page_obj = paginator.get_page(request.GET.get(page_param, 1))
    page_range = [
        None if page_number == paginator.ELLIPSIS else page_number
        for page_number in paginator.get_elided_page_range(
            page_obj.number, on_each_side=1, on_ends=1,
        )
    ]
    return {
        'items': list(page_obj.object_list),
        'page_obj': page_obj,
        'page_number': page_obj.number,
        'page_size': page_size,
        'page_size_options': ADMIN_PAGE_SIZE_OPTIONS,
        'page_param': page_param,
        'size_param': size_param,
        'page_range': page_range,
        'start_index': page_obj.start_index() if paginator.count else 0,
        'end_index': page_obj.end_index() if paginator.count else 0,
        'total_count': paginator.count,
        'num_pages': paginator.num_pages,
    }


def normalize_card_color(value):
    """Return a normalized six-digit hex color, or None when invalid."""
    color = (value or '').strip().lower()
    return color if re.fullmatch(r'#[0-9a-f]{6}', color) else None


def safe_csv_text(value):
    """Keep exported text inert when a CSV is opened in spreadsheet software."""
    text = '' if value is None else str(value)
    if text.startswith(('=', '+', '-', '@', '\t', '\r')):
        return f"'{text}"
    return text


def next_available_organization_color():
    used_colors = {
        color.lower() for color in Organization.objects.values_list('card_color', flat=True)
    }
    for color in ORGANIZATION_COLOR_PALETTE:
        if color not in used_colors:
            return color


def next_machine_code(device_serial=''):
    """Generate an internal machine code, preferring the SR suffix of its device."""
    serial_match = re.search(r'(?:^|-)SR-(\d+)$', (device_serial or '').upper())
    if serial_match:
        candidate = f'SR-{int(serial_match.group(1)):03d}'
        if not Machine.objects.filter(code=candidate).exists():
            return candidate

    numbers = []
    for existing_code in Machine.objects.values_list('code', flat=True):
        code_match = re.fullmatch(r'SR-(\d+)', (existing_code or '').upper())
        if code_match:
            numbers.append(int(code_match.group(1)))
    next_number = max(numbers, default=0) + 1
    candidate = f'SR-{next_number:03d}'
    while Machine.objects.filter(code=candidate).exists():
        next_number += 1
        candidate = f'SR-{next_number:03d}'
    return candidate
    while True:
        color = f'#{secrets.randbelow(0x1000000):06x}'
        if color not in used_colors:
            return color


def parse_coordinate(value, minimum, maximum):
    """Parse an optional coordinate and constrain it to six decimal places."""
    if value is None or str(value).strip() == '':
        return None
    try:
        coordinate = Decimal(str(value).strip())
    except InvalidOperation as exc:
        raise ValueError('Invalid coordinate') from exc
    if not coordinate.is_finite() or coordinate < Decimal(str(minimum)) or coordinate > Decimal(str(maximum)):
        raise ValueError('Coordinate is outside the allowed range')
    return coordinate.quantize(Decimal('0.000001'), rounding=ROUND_HALF_UP)


def normalize_date_parameter(value):
    """Accept DD/MM/YYYY from the UI while keeping ISO dates for comparisons."""
    value = (value or '').strip()
    if not value:
        return ''
    for pattern in ('%d/%m/%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(value, pattern).strftime('%Y-%m-%d')
        except ValueError:
            continue
    return ''


def display_date(value):
    if not value:
        return ''
    try:
        return datetime.strptime(value, '%Y-%m-%d').strftime('%d/%m/%Y')
    except ValueError:
        return value


def login_required(view):
    def wrapper(request, *args, **kwargs):
        if not request.session.get('logged_in'):
            return redirect('login')
        user = User.objects.select_related('organization').filter(
            pk=request.session.get('user_id')
        ).first()
        if (
            not user
            or (
                user.role != User.Role.SUPER_ADMIN
                and user.organization
                and user.organization.status == Organization.Status.SUSPENDED
            )
        ):
            request.session.flush()
            return redirect('/?suspended=1')
        return view(request, *args, **kwargs)
    wrapper.__name__ = view.__name__
    return wrapper


def is_system_admin(request):
    return request.session.get('user_role') == SYSTEM_ADMIN


def current_org_id(request):
    return request.session.get('organization_id')


def org_map(session):
    return {
        org.id: {
            'id': org.id, 'name': org.name, 'card_color': org.card_color,
            'status': org.status,
        }
        for org in Organization.objects.all()
    }


def current_org(request):
    if is_system_admin(request):
        return None
    return org_map(request.session).get(current_org_id(request))


def visible_records(request, records):
    if is_system_admin(request):
        return records
    oid = current_org_id(request)
    return [item for item in records if item.get('organization_id') == oid]


def visible_issue_queryset(request):
    queryset = IssueReport.objects.all()
    if is_system_admin(request):
        queryset = queryset.filter(escalated_at__isnull=False)
    else:
        queryset = queryset.filter(machine__organization_id=current_org_id(request))
    return queryset


def issue_nav_counts(request):
    return visible_issue_queryset(request).aggregate(
        waiting=Count('id', filter=Q(status=IssueReport.Status.WAITING)),
        in_progress=Count('id', filter=Q(status=IssueReport.Status.IN_PROGRESS)),
    )


def revision_part(value):
    return value.isoformat() if hasattr(value, 'isoformat') else str(value or '')


def enrich_with_org(session, records):
    organizations = org_map(session)
    enriched = []
    for item in records:
        copied = copy.deepcopy(item)
        org = organizations.get(copied.get('organization_id'), {})
        copied['organization_name'] = org.get('name', '-')
        copied['card_color'] = org.get('card_color', '#2563eb')
        enriched.append(copied)
    return enriched


def thai_role(role):
    return {
        SYSTEM_ADMIN: 'แอดมินสูงสุด',
        ORG_ADMIN: 'แอดมินหน่วยงาน',
        'Collector': 'คนเก็บขยะ',
    }.get(role, role)


def next_user_id(users):
    return max([user.get('id', 0) for user in users] or [0]) + 1


def dashboard_chart_payload(machines, history):
    machine_names = [machine['name'] for machine in machines]
    waste_types = WASTE_TYPES
    history_dates = sorted({row['date'] for row in history})
    if history_dates:
        end_date = datetime.strptime(history_dates[-1], '%Y-%m-%d').date()
    else:
        end_date = datetime.today().date()

    # Keep a leap-year-safe window so the dashboard can show a full trailing year.
    date_range = [end_date - timedelta(days=offset) for offset in range(365, -1, -1)]
    dates = [date.isoformat() for date in date_range]
    labels = [date.strftime('%d/%m/%Y') for date in date_range]
    palette = ['#2dd4bf', '#60a5fa', '#a78bfa', '#f59e0b', '#fb7185', '#34d399']
    series = []

    for index, machine_name in enumerate(machine_names):
        values_by_type = {'All': []}
        for waste_type in waste_types:
            values_by_type[waste_type] = []

        for date in dates:
            daily_rows = [
                row for row in history
                if row['date'] == date and row['machine'] == machine_name
            ]
            values_by_type['All'].append(round(sum(row['weight'] for row in daily_rows), 2))
            for waste_type in waste_types:
                values_by_type[waste_type].append(round(
                    sum(row['weight'] for row in daily_rows if row['type'] == waste_type),
                    2
                ))

        series.append({
            'id': machine_name,
            'name': machine_name,
            'color': palette[index % len(palette)],
            'organizationId': next(
                (m.get('organization_id') for m in machines if m['name'] == machine_name),
                '',
            ),
            'organizationName': next(
                (m.get('organization_name', '-') for m in machines if m['name'] == machine_name),
                '-',
            ),
            'valuesByType': values_by_type,
        })

    return {
        'dates': dates,
        'labels': labels,
        'wasteTypes': ['All'] + waste_types,
        'series': series,
        'defaultRange': '7d',
        'organizations': [
            {'id': org['id'], 'name': org['name']}
            for org in {
                m.get('organization_id'): {
                    'id': m.get('organization_id'),
                    'name': m.get('organization_name', '-'),
                }
                for m in machines if m.get('organization_id')
            }.values()
        ],
    }

def render_admin(request, template_name, context):
    context.setdefault('active_tab_page', context.get('active_tab'))
    nav_issue_counts = issue_nav_counts(request)
    context.update({
        'base_template': (
            'core/base_ajax.html'
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            else 'core/base.html'
        ),
        'is_system_admin': is_system_admin(request),
        'user_role': request.session.get('user_role', ORG_ADMIN),
        'user_role_th': thai_role(request.session.get('user_role', ORG_ADMIN)),
        'user_email': request.session.get('user_email', ''),
        'current_user_id': request.session.get('user_id', ''),
        'organizations': get_organizations(request.session),
        'current_org': current_org(request),
        'issue_waiting_count': nav_issue_counts['waiting'],
        'issue_in_progress_count': nav_issue_counts['in_progress'],
    })
    return render(request, template_name, context)


@login_required
def admin_live_state(request):
    machine_queryset = Machine.objects.all()
    if not is_system_admin(request):
        machine_queryset = machine_queryset.filter(organization_id=current_org_id(request))
    machine_state = machine_queryset.aggregate(
        count=Count('id', distinct=True),
        created=Max('created_at'),
        updated=Max('last_updated_at'),
        measured=Max('bins__last_measured_at'),
    )
    device_revision = ''
    if is_system_admin(request):
        device_state = MachineInformation.objects.aggregate(
            count=Count('serial_number'),
            created=Max('created_at'),
            seen=Max('last_seen_at'),
        )
        device_revision = ':'.join(revision_part(device_state[key]) for key in ('count', 'created', 'seen'))

    issue_queryset = visible_issue_queryset(request)
    issue_state = issue_queryset.aggregate(
        count=Count('id'),
        updated=Max('updated_at'),
        waiting=Count('id', filter=Q(status=IssueReport.Status.WAITING)),
        in_progress=Count('id', filter=Q(status=IssueReport.Status.IN_PROGRESS)),
    )
    return JsonResponse({
        'machines_revision': ':'.join(
            [revision_part(machine_state[key]) for key in ('count', 'created', 'updated', 'measured')]
            + [device_revision]
        ),
        'issues_revision': ':'.join(
            revision_part(issue_state[key]) for key in ('count', 'updated')
        ),
        'issue_counts': {
            'waiting': issue_state['waiting'],
            'in_progress': issue_state['in_progress'],
        },
    })


def deny_org_admin(request):
    request.session['toast'] = {
        'type': 'error',
        'title': 'ไม่มีสิทธิ์',
        'message': 'เฉพาะแอดมินสูงสุดเท่านั้นที่จัดการข้อมูลนี้ได้',
    }
    return redirect('dashboard')


def login_view(request):
    if request.session.get('logged_in'):
        return redirect('dashboard')

    error = 'หน่วยงานนี้ถูกระงับ กรุณาติดต่อผู้ดูแลระบบ' if request.GET.get('suspended') == '1' else None
    organizations = Organization.objects.all().order_by('name')
    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '').strip()
        user = User.objects.select_related('organization').filter(email__iexact=email).first()
        if not user or not user.check_password(password):
            error = 'อีเมลหรือรหัสผ่านไม่ถูกต้อง'
        elif user.status == User.Status.SUSPENDED:
            error = 'บัญชีนี้ถูกระงับ กรุณาติดต่อผู้ดูแลระบบ'
        elif user.status == User.Status.PENDING:
            error = 'บัญชีนี้ยังไม่ได้รับการอนุมัติ'
        elif (
            user.role != User.Role.SUPER_ADMIN
            and user.organization
            and user.organization.status == Organization.Status.SUSPENDED
        ):
            error = 'หน่วยงานนี้ถูกระงับ กรุณาติดต่อผู้ดูแลระบบ'
        elif user.role not in (User.Role.SUPER_ADMIN, User.Role.ORGANIZATION_ADMIN):
            error = 'บัญชีนี้ไม่มีสิทธิ์เข้าสู่ระบบแอดมิน'
        else:
            request.session['logged_in'] = True
            request.session['user_id'] = user.id
            request.session['user_email'] = user.email
            request.session['user_role'] = SYSTEM_ADMIN if user.role == User.Role.SUPER_ADMIN else ORG_ADMIN
            request.session['organization_id'] = user.organization_id
            return redirect('dashboard')

    return render(request, 'core/login.html', {
        'error': error,
        'organizations': organizations,
        'system_role': SYSTEM_ADMIN,
        'admin_role': ORG_ADMIN,
    })


def logout_view(request):
    request.session.flush()
    return redirect('login')


@login_required
def dashboard(request):
    machines = enrich_with_org(request.session, visible_records(request, get_machines(request.session)))
    users = visible_records(request, get_users(request.session))
    issues = visible_records(request, get_issues(request.session))
    if is_system_admin(request):
        issues = [issue for issue in issues if issue.get('escalated')]
    history = visible_records(request, get_collection_history())

    online_count = sum(1 for m in machines if m['status'] == 'Online')
    new_issues = sum(1 for i in issues if i['status'] == 'Waiting')
    today_weight = sum(
        h['weight'] for h in history
        if h['date'] == datetime.today().date().isoformat()
    )

    chart_data = [
        {'label': 'Mon', 'value': 85},
        {'label': 'Tue', 'value': 120},
        {'label': 'Wed', 'value': 95},
        {'label': 'Thu', 'value': 140},
        {'label': 'Fri', 'value': 110},
        {'label': 'Sat', 'value': 60},
        {'label': 'Sun', 'value': 45},
    ]

    # Use the same collection rows as the report page.  The previous chart used
    # current bin weights, so its total represented a different data set and did
    # not match the report summary.
    waste_distribution = []
    for waste_type, thai_name, color in [
        ('Plastic', 'พลาสติก', '#22c55e'), ('Glass', 'แก้ว', '#3b82f6'),
        ('Can', 'กระป๋อง', '#f97316'),
    ]:
        total = sum(row['weight'] for row in history if row['type'] == waste_type)
        waste_distribution.append({'label': thai_name, 'value': round(total, 2), 'color': color})
    return render_admin(request, 'core/dashboard.html', {
        'active_tab': 'dashboard',
        'online_count': online_count,
        'total_machines': len(machines),
        'total_users': len(users),
        'new_issues': new_issues,
        'today_weight': today_weight,
        'chart_data': chart_data,
        'chart_payload': dashboard_chart_payload(machines, history),
        'waste_distribution': waste_distribution,
    })


@login_required
def organizations_view(request):
    if not is_system_admin(request):
        return deny_org_admin(request)

    machines = get_machines(request.session)
    users = get_users(request.session)
    issues = get_issues(request.session)
    orgs = []
    for org in get_organizations(request.session):
        copied = copy.deepcopy(org)
        copied['machine_count'] = sum(1 for m in machines if m.get('organization_id') == org['id'])
        copied['user_count'] = sum(1 for u in users if u.get('organization_id') == org['id'])
        copied['issue_count'] = sum(1 for i in issues if i.get('organization_id') == org['id'])
        orgs.append(copied)
    orgs.sort(
        key=lambda org: (org['created_at'], org['id']),
        reverse=True,
    )
    all_orgs = list(orgs)
    search = request.GET.get('search', '').strip()
    status_filter = request.GET.get('status', 'All')
    if search:
        orgs = [org for org in orgs if search.casefold() in org['name'].casefold()]
    if status_filter != 'All':
        orgs = [org for org in orgs if org.get('status') == status_filter]

    toast = request.session.pop('toast', None)
    organization_colors = [
        {'id': org['id'], 'name': org['name'], 'color': org['card_color'].lower()}
        for org in all_orgs
    ]
    organizations_pagination = paginate_admin(request, orgs)
    return render_admin(request, 'core/organizations.html', {
        'active_tab': 'organizations',
        'organizations_list': organizations_pagination['items'],
        'organizations_pagination': organizations_pagination,
        'organization_colors': organization_colors,
        'suggested_color': next_available_organization_color(),
        'search': search,
        'status_filter': status_filter,
        'toast': toast,
    })


@login_required
@require_POST
def organization_add(request):
    if not is_system_admin(request):
        return deny_org_admin(request)

    name = request.POST.get('name', '').strip()
    card_color = normalize_card_color(request.POST.get('card_color'))
    if not name:
        request.session['toast'] = {'type': 'error', 'title': 'กรอกข้อมูลไม่ครบ', 'message': 'กรุณากรอกชื่อหน่วยงาน'}
    elif not card_color:
        request.session['toast'] = {'type': 'error', 'title': 'สีไม่ถูกต้อง', 'message': 'กรุณาเลือกสีประจำหน่วยงานให้ถูกต้อง'}
    elif Organization.objects.filter(name__iexact=name).exists():
        request.session['toast'] = {'type': 'error', 'title': 'ชื่อซ้ำ', 'message': 'ชื่อหน่วยงานนี้มีอยู่ในระบบแล้ว'}
    elif Organization.objects.filter(card_color__iexact=card_color).exists():
        request.session['toast'] = {'type': 'error', 'title': 'สีซ้ำ', 'message': 'สีนี้ถูกใช้โดยหน่วยงานอื่นแล้ว กรุณาเลือกสีใหม่'}
    else:
        try:
            Organization.objects.create(
                id=f'org-{secrets.token_hex(6)}', name=name, card_color=card_color,
            )
            request.session['toast'] = {'type': 'success', 'title': 'บันทึกแล้ว', 'message': 'เพิ่มหน่วยงานเรียบร้อยแล้ว'}
        except IntegrityError:
            request.session['toast'] = {'type': 'error', 'title': 'ข้อมูลซ้ำ', 'message': 'ชื่อหรือสีประจำหน่วยงานถูกใช้งานแล้ว'}
    return redirect('organizations')


@login_required
@require_POST
def organization_edit(request):
    if not is_system_admin(request):
        return deny_org_admin(request)

    oid = request.POST.get('id')
    org = Organization.objects.filter(pk=oid).first()
    if not org:
        request.session['toast'] = {'type': 'error', 'title': 'ไม่พบข้อมูล', 'message': 'ไม่พบหน่วยงานที่ต้องการแก้ไข'}
        return redirect('organizations')

    name = request.POST.get('name', org.name).strip() or org.name
    card_color = normalize_card_color(request.POST.get('card_color', org.card_color))
    if not card_color:
        request.session['toast'] = {'type': 'error', 'title': 'สีไม่ถูกต้อง', 'message': 'กรุณาเลือกสีประจำหน่วยงานให้ถูกต้อง'}
    elif Organization.objects.exclude(pk=org.pk).filter(name__iexact=name).exists():
        request.session['toast'] = {'type': 'error', 'title': 'ชื่อซ้ำ', 'message': 'ชื่อหน่วยงานนี้มีอยู่ในระบบแล้ว'}
    elif Organization.objects.exclude(pk=org.pk).filter(card_color__iexact=card_color).exists():
        request.session['toast'] = {'type': 'error', 'title': 'สีซ้ำ', 'message': 'สีนี้ถูกใช้โดยหน่วยงานอื่นแล้ว กรุณาเลือกสีใหม่'}
    else:
        try:
            org.name = name
            org.card_color = card_color
            org.save(update_fields=['name', 'card_color'])
            request.session['toast'] = {'type': 'success', 'title': 'บันทึกแล้ว', 'message': 'แก้ไขหน่วยงานเรียบร้อยแล้ว'}
        except IntegrityError:
            request.session['toast'] = {'type': 'error', 'title': 'ข้อมูลซ้ำ', 'message': 'ชื่อหรือสีประจำหน่วยงานถูกใช้งานแล้ว'}
    return redirect('organizations')


@login_required
@require_POST
def organization_toggle_status(request):
    if not is_system_admin(request):
        return deny_org_admin(request)
    organization = Organization.objects.filter(pk=request.POST.get('id')).first()
    if not organization:
        request.session['toast'] = {
            'type': 'error', 'title': 'ไม่พบข้อมูล',
            'message': 'ไม่พบหน่วยงานที่ต้องการเปลี่ยนสถานะ',
        }
        return redirect('organizations')

    if organization.status == Organization.Status.ACTIVE:
        now = timezone.now()
        with transaction.atomic():
            organization.status = Organization.Status.SUSPENDED
            organization.save(update_fields=['status'])
            User.objects.filter(organization=organization).update(
                status=User.Status.SUSPENDED,
            )
            ApiToken.objects.filter(
                user__organization=organization,
                revoked_at__isnull=True,
            ).update(revoked_at=now)
            machines = list(Machine.objects.filter(organization=organization))
            Machine.objects.filter(organization=organization).update(
                status=Machine.Status.SUSPENDED,
                last_updated_at=now,
            )
            for machine in machines:
                api.enqueue_machine_command(machine, MachineCommand.Command.STOP)
        message = 'ระงับหน่วยงาน ผู้ใช้งาน และเครื่องทั้งหมดในหน่วยงานแล้ว'
    else:
        now = timezone.now()
        with transaction.atomic():
            organization.status = Organization.Status.ACTIVE
            organization.save(update_fields=['status'])
            User.objects.filter(organization=organization).update(
                status=User.Status.ACTIVE,
            )
            Machine.objects.filter(organization=organization).update(
                status=Machine.Status.OFFLINE,
                last_updated_at=now,
            )
        message = 'เปิดใช้งานหน่วยงาน ผู้ใช้งาน และเครื่องทั้งหมดแล้ว เครื่องจะอยู่ในสถานะปิดจนกว่าจะสั่งเปิด'
    request.session['toast'] = {
        'type': 'success', 'title': 'บันทึกแล้ว', 'message': message,
    }
    return redirect('organizations')


@login_required
def machines_view(request):
    machines = enrich_with_org(request.session, visible_records(request, get_machines(request.session)))
    search = request.GET.get('search', '')
    status_filter = request.GET.get('status', 'All')
    organization_filter = request.GET.get('organization', 'All')
    show_suspended = is_system_admin(request) and request.GET.get('show_suspended') == '1'
    if not show_suspended:
        machines = [m for m in machines if m['status'] != Machine.Status.SUSPENDED]

    filtered = [
        m for m in machines
        if (search.lower() in m['name'].lower() or search.lower() in m['code'].lower())
        and (status_filter == 'All' or m['status'] == status_filter)
        and (not is_system_admin(request) or organization_filter == 'All' or m['organization_id'] == organization_filter)
    ]

    machine_map_data = [
        {
            'id': machine['id'],
            'code': machine['code'],
            'name': machine['name'],
            'location': machine['location'],
            'status': machine['status'],
            'organization_name': machine['organization_name'],
            'card_color': machine['card_color'],
            'latitude': float(machine['latitude']) if machine['latitude'] else None,
            'longitude': float(machine['longitude']) if machine['longitude'] else None,
        }
        for machine in machines
    ]

    device_rows = []
    available_devices = []
    if is_system_admin(request):
        assigned_by_serial = {
            machine.device_id: machine
            for machine in Machine.objects.exclude(device_id__isnull=True)
        }
        for device in MachineInformation.objects.order_by('-created_at', '-serial_number'):
            assigned_machine = assigned_by_serial.get(device.serial_number)
            row = {
                'serial_number': device.serial_number,
                'model': device.model,
                'firmware_version': device.firmware_version or '-',
                'hardware_status': device.hardware_status,
                'status_th': {
                    MachineInformation.HardwareStatus.AVAILABLE: 'พร้อมใช้งาน',
                    MachineInformation.HardwareStatus.INSTALLED: 'ติดตั้งแล้ว',
                    MachineInformation.HardwareStatus.MAINTENANCE: 'ซ่อมบำรุง',
                    MachineInformation.HardwareStatus.DEFECTIVE: 'ชำรุด',
                }.get(device.hardware_status, device.hardware_status),
                'machine_id': assigned_machine.id if assigned_machine else '',
                'machine_code': assigned_machine.code if assigned_machine else '',
                'machine_name': assigned_machine.name if assigned_machine else '',
                'api_key': device.get_api_key(),
            }
            device_rows.append(row)
            if not assigned_machine and device.hardware_status == MachineInformation.HardwareStatus.AVAILABLE:
                available_devices.append(row)

    caretaker_query = User.objects.select_related('organization').filter(
        status=User.Status.ACTIVE,
    ).exclude(role=User.Role.SUPER_ADMIN)
    if not is_system_admin(request):
        caretaker_query = caretaker_query.filter(organization_id=current_org_id(request))
    caretaker_options = [
        {
            'id': user.id,
            'name': user.name,
            'organization_id': user.organization_id,
            'organization_name': user.organization.name if user.organization else '-',
            'role_th': 'แอดมินหน่วยงาน' if user.role == User.Role.ORGANIZATION_ADMIN else 'ผู้เก็บขยะ',
        }
        for user in caretaker_query.order_by('organization__name', 'name', 'id')
    ]

    machines_pagination = paginate_admin(request, filtered)
    devices_pagination = paginate_admin(
        request,
        device_rows,
        page_param='device_page',
        size_param='device_page_size',
    )
    toast = request.session.pop('toast', None)
    device_credentials = request.session.pop('device_credentials', None)
    return render_admin(request, 'core/machines.html', {
        'active_tab': 'machines',
        'machines': machines_pagination['items'],
        'machines_pagination': machines_pagination,
        'machine_map_data': machine_map_data,
        'search': search,
        'status_filter': status_filter,
        'organization_filter': organization_filter,
        'show_suspended': show_suspended,
        'device_rows': device_rows,
        'device_rows_page': devices_pagination['items'],
        'devices_pagination': devices_pagination,
        'available_devices': available_devices,
        'caretaker_options': caretaker_options,
        'device_credentials': device_credentials,
        'show_devices': request.GET.get('devices') == '1' or bool(device_credentials),
        'toast': toast,
    })


@login_required
@require_POST
def device_add(request):
    if not is_system_admin(request):
        return deny_org_admin(request)

    serial_number = request.POST.get('serial_number', '').strip().upper()
    model = request.POST.get('model', '').strip() or 'ESP32'
    firmware_version = request.POST.get('firmware_version', '').strip()
    provided_api_key = request.POST.get('api_key', '').strip()
    raw_api_key = provided_api_key or secrets.token_urlsafe(24)

    if not re.fullmatch(r'[A-Z0-9._-]{3,30}', serial_number):
        request.session['toast'] = {
            'type': 'error',
            'title': 'Serial Number ไม่ถูกต้อง',
            'message': 'ใช้ตัวอักษร A-Z ตัวเลข จุด ขีดกลาง หรือขีดล่าง จำนวน 3-30 ตัว',
        }
    elif provided_api_key and len(provided_api_key) < 8:
        request.session['toast'] = {
            'type': 'error',
            'title': 'รหัสเชื่อมต่อสั้นเกินไป',
            'message': 'รหัสเชื่อมต่อต้องมีอย่างน้อย 8 ตัวอักษร หรือเว้นว่างเพื่อให้ระบบสร้างอัตโนมัติ',
        }
    elif MachineInformation.objects.filter(pk=serial_number).exists():
        request.session['toast'] = {
            'type': 'error',
            'title': 'Serial Number ซ้ำ',
            'message': 'Serial Number นี้ลงทะเบียนไว้แล้ว',
        }
    else:
        device = MachineInformation(
            serial_number=serial_number,
            model=model[:50],
            firmware_version=firmware_version[:50],
            hardware_status=MachineInformation.HardwareStatus.AVAILABLE,
        )
        device.set_api_key(raw_api_key)
        device.save()
        request.session['device_credentials'] = {
            'serial_number': serial_number,
            'api_key': raw_api_key,
        }
        request.session['toast'] = {
            'type': 'success',
            'title': 'เตรียมอุปกรณ์แล้ว',
            'message': 'ลงทะเบียนหมายเลขประจำอุปกรณ์และสร้างรหัสเชื่อมต่อเรียบร้อยแล้ว',
        }
    return redirect('/machines/?devices=1')


@login_required
@require_POST
def device_regenerate_key(request):
    if not is_system_admin(request):
        return deny_org_admin(request)
    device = MachineInformation.objects.filter(
        pk=request.POST.get('serial_number', '').strip(),
    ).first()
    if device:
        raw_api_key = secrets.token_urlsafe(24)
        device.set_api_key(raw_api_key)
        device.save(update_fields=['api_key_hash', 'api_key_ciphertext'])
        request.session['device_credentials'] = {
            'serial_number': device.serial_number,
            'api_key': raw_api_key,
        }
        request.session['toast'] = {
            'type': 'success',
            'title': 'สร้างรหัสเชื่อมต่อใหม่แล้ว',
            'message': 'รหัสเชื่อมต่อเดิมจะไม่สามารถใช้งานได้อีก',
        }
    return redirect('/machines/?devices=1')


@login_required
@require_POST
def device_delete(request):
    if not is_system_admin(request):
        return deny_org_admin(request)
    device = MachineInformation.objects.filter(
        pk=request.POST.get('serial_number', '').strip(),
    ).first()
    if not device:
        request.session['toast'] = {
            'type': 'error', 'title': 'ไม่พบอุปกรณ์', 'message': 'Serial Number นี้ไม่มีในระบบ',
        }
    elif Machine.objects.filter(device=device).exists():
        request.session['toast'] = {
            'type': 'error', 'title': 'ลบไม่ได้', 'message': 'Serial Number นี้ถูกผูกกับเครื่องแล้ว',
        }
    else:
        device.delete()
        request.session['toast'] = {
            'type': 'success', 'title': 'ลบแล้ว', 'message': 'ลบ Serial Number ที่ยังไม่ใช้งานแล้ว',
        }
    return redirect('/machines/?devices=1')


def valid_machine_caretakers(organization, caretaker_ids):
    selected_ids = list(dict.fromkeys(
        caretaker_id.strip()
        for caretaker_id in caretaker_ids
        if caretaker_id.strip()
    ))
    if not selected_ids:
        return [], True
    caretakers = list(
        User.objects.filter(
            pk__in=selected_ids,
            organization=organization,
            status=User.Status.ACTIVE,
        ).exclude(role=User.Role.SUPER_ADMIN)
    )
    return caretakers, len(caretakers) == len(selected_ids)


@login_required
@require_POST
def machine_add(request):
    system_admin = is_system_admin(request)
    organization_id = request.POST.get('organization_id') if system_admin else current_org_id(request)
    device_serial = request.POST.get('device_serial', '').strip().upper()
    provided_api_key = request.POST.get('api_key', '').strip()
    name = request.POST.get('name', '').strip() or 'ยังไม่ระบุชื่อ'
    location = request.POST.get('location', '').strip()
    caretaker_ids = request.POST.getlist('caretaker_ids')

    organization = Organization.objects.filter(pk=organization_id).first()
    caretakers, caretakers_valid = valid_machine_caretakers(organization, caretaker_ids)
    if not organization:
        request.session['toast'] = {
            'type': 'error', 'title': 'ไม่พบหน่วยงาน', 'message': 'ไม่พบหน่วยงานสำหรับเครื่องที่ต้องการเพิ่ม',
        }
    elif not re.fullmatch(r'[A-Z0-9._-]{3,30}', device_serial):
        request.session['toast'] = {
            'type': 'error',
            'title': 'Serial Number ไม่ถูกต้อง',
            'message': 'กรุณากรอก Serial Number จำนวน 3-30 ตัว โดยใช้ตัวอักษร ตัวเลข จุด ขีดกลาง หรือขีดล่าง',
        }
    elif not system_admin and len(provided_api_key) < 8:
        request.session['toast'] = {
            'type': 'error',
            'title': 'รหัสเชื่อมต่อไม่ถูกต้อง',
            'message': 'กรุณากรอกรหัสเชื่อมต่ออย่างน้อย 8 ตัวอักษรให้ตรงกับรหัสที่ตั้งค่าในอุปกรณ์',
        }
    elif not caretakers_valid:
        request.session['toast'] = {
            'type': 'error',
            'title': 'ผู้ดูแลเครื่องไม่ถูกต้อง',
            'message': 'กรุณาเลือกผู้ดูแลเครื่องที่กำลังใช้งานและอยู่ในหน่วยงานเดียวกับเครื่อง',
        }
    else:
        with transaction.atomic():
            device = MachineInformation.objects.select_for_update().filter(pk=device_serial).first()
            if system_admin and (
                device is None
                or device.hardware_status != MachineInformation.HardwareStatus.AVAILABLE
                or Machine.objects.filter(device_id=device_serial).exists()
            ):
                request.session['toast'] = {
                    'type': 'error',
                    'title': 'Serial Number ไม่พร้อมใช้งาน',
                    'message': 'Serial Number นี้ไม่มีในรายการที่เตรียมไว้ หรือถูกผูกกับเครื่องอื่นแล้ว',
                }
                device = None
            elif not system_admin and device is not None and (
                device.hardware_status != MachineInformation.HardwareStatus.AVAILABLE
                or Machine.objects.filter(device_id=device_serial).exists()
            ):
                request.session['toast'] = {
                    'type': 'error',
                    'title': 'Serial Number ถูกใช้งานแล้ว',
                    'message': 'Serial Number นี้ถูกผูกกับเครื่องอื่นแล้ว กรุณาตรวจสอบหมายเลขบนอุปกรณ์',
                }
                device = None
            elif not system_admin and device is not None and not device.check_api_key(provided_api_key):
                request.session['toast'] = {
                    'type': 'error',
                    'title': 'รหัสเชื่อมต่อไม่ถูกต้อง',
                    'message': 'รหัสเชื่อมต่อไม่ตรงกับ Serial Number นี้ กรุณาตรวจสอบข้อมูลบนอุปกรณ์อีกครั้ง',
                }
                device = None
            else:
                if device is None:
                    device = MachineInformation(
                        serial_number=device_serial,
                        model='ESP32',
                        firmware_version='',
                        hardware_status=MachineInformation.HardwareStatus.AVAILABLE,
                    )
                    device.set_api_key(provided_api_key)
                    device.save()
                code = next_machine_code(device_serial)
                machine = Machine.objects.create(
                    id=f'M{int(time.time() * 1000)}',
                    code=code,
                    name=name,
                    location=location,
                    organization=organization,
                    device=device,
                    status=Machine.Status.OFFLINE,
                    installed_on=timezone.localdate(),
                    last_updated_at=timezone.now(),
                )
                machine.caretakers.set(caretakers)
                MachineBin.objects.bulk_create([
                    MachineBin(machine=machine, waste_type=waste_type)
                    for waste_type in MachineBin.WasteType.values
                ])
                device.hardware_status = MachineInformation.HardwareStatus.INSTALLED
                device.save(update_fields=['hardware_status'])
                request.session['toast'] = {
                    'type': 'success',
                    'title': 'เพิ่มเครื่องแล้ว',
                    'message': f'เพิ่ม {name} (รหัส {code}) และผูกกับ Serial Number {device_serial} แล้ว',
                }
    return redirect('machines')


@login_required
@require_POST
def machine_edit(request):
    mid = request.POST.get('id')
    allowed_orgs = None if is_system_admin(request) else {current_org_id(request)}
    machine = Machine.objects.filter(pk=mid).first()
    if machine and (allowed_orgs is None or machine.organization_id in allowed_orgs):
        machine_saved = False
        target_organization = machine.organization
        if is_system_admin(request):
            target_organization = Organization.objects.filter(
                pk=request.POST.get('organization_id', machine.organization_id),
            ).first()
            if target_organization is None:
                request.session['toast'] = {
                    'type': 'error', 'title': 'ไม่พบหน่วยงาน', 'message': 'กรุณาเลือกหน่วยงานที่ถูกต้อง',
                }
                return redirect('machines')

        caretakers_submitted = 'caretakers_submitted' in request.POST
        caretakers = None
        if caretakers_submitted:
            caretakers, caretakers_valid = valid_machine_caretakers(
                target_organization,
                request.POST.getlist('caretaker_ids'),
            )
            if not caretakers_valid:
                request.session['toast'] = {
                    'type': 'error',
                    'title': 'ผู้ดูแลเครื่องไม่ถูกต้อง',
                    'message': 'กรุณาเลือกผู้ดูแลเครื่องที่กำลังใช้งานและอยู่ในหน่วยงานเดียวกับเครื่อง',
                }
                return redirect('machines')

        coordinates_submitted = 'latitude' in request.POST or 'longitude' in request.POST
        try:
            latitude = parse_coordinate(request.POST.get('latitude'), -90, 90)
            longitude = parse_coordinate(request.POST.get('longitude'), -180, 180)
            if coordinates_submitted and ((latitude is None) != (longitude is None)):
                raise ValueError('Both coordinates are required')
        except ValueError:
            request.session['toast'] = {
                'type': 'error',
                'title': 'พิกัดไม่ถูกต้อง',
                'message': 'กรุณาระบุละติจูดและลองจิจูดให้ครบและอยู่ในช่วงที่ถูกต้อง',
            }
            return redirect('machines')

        machine.name = (
            request.POST.get('name', machine.name).strip()
            or machine.name
            or 'ยังไม่ระบุชื่อ'
        )
        machine.location = request.POST.get('location', machine.location).strip()
        machine.last_updated_at = timezone.now()
        if coordinates_submitted:
            machine.latitude = latitude
            machine.longitude = longitude
        if is_system_admin(request):
            code = request.POST.get('code', machine.code).strip()
            if code and not Machine.objects.filter(code=code).exclude(pk=machine.pk).exists(): machine.code = code
            machine.organization = target_organization
            device_serial = request.POST.get('device_serial', machine.device_id or '').strip().upper()
            if device_serial and device_serial != machine.device_id:
                with transaction.atomic():
                    new_device = MachineInformation.objects.select_for_update().filter(
                        pk=device_serial,
                        hardware_status=MachineInformation.HardwareStatus.AVAILABLE,
                    ).first()
                    if new_device is None or Machine.objects.filter(device=new_device).exclude(pk=machine.pk).exists():
                        request.session['toast'] = {
                            'type': 'error',
                            'title': 'เปลี่ยน Serial Number ไม่ได้',
                            'message': 'Serial Number ที่เลือกไม่พร้อมใช้งานหรือถูกใช้โดยเครื่องอื่นแล้ว',
                        }
                        return redirect('machines')
                    old_device = machine.device
                    machine.device = new_device
                    new_device.hardware_status = MachineInformation.HardwareStatus.INSTALLED
                    new_device.save(update_fields=['hardware_status'])
                    if old_device:
                        old_device.hardware_status = MachineInformation.HardwareStatus.AVAILABLE
                        old_device.save(update_fields=['hardware_status'])
                    machine.save()
                    machine_saved = True
        if not machine_saved:
            machine.save()
        if caretakers_submitted:
            machine.caretakers.set(caretakers)
    request.session['toast'] = {'type': 'success', 'title': 'บันทึกแล้ว', 'message': 'แก้ไขข้อมูลเครื่องเรียบร้อยแล้ว'}
    return redirect('machines')


@login_required
@require_POST
def machine_toggle(request):
    mid = request.POST.get('id')
    allowed_orgs = None if is_system_admin(request) else {current_org_id(request)}
    with transaction.atomic():
        machine = Machine.objects.select_for_update().filter(pk=mid).first()
        if machine and (allowed_orgs is None or machine.organization_id in allowed_orgs):
            if machine.status == Machine.Status.SUSPENDED:
                request.session['toast'] = {
                    'type': 'error', 'title': 'เครื่องถูกระงับ',
                    'message': 'กรุณาเปิดใช้งานเครื่องก่อนส่งคำสั่งเปิดหรือปิด',
                }
                return redirect('machines')
            if (
                machine.status != Machine.Status.ONLINE
                and machine.bins.filter(
                    current_level_percent__gte=F('full_threshold_percent'),
                ).exists()
            ):
                request.session['toast'] = {
                    'type': 'error',
                    'title': 'ยังเปิดเครื่องไม่ได้',
                    'message': 'มีถังเต็มอยู่ กรุณาเก็บขยะและรีเซ็ตถังก่อนเปิดเครื่อง',
                }
                return redirect('machines')
            machine.status = Machine.Status.OFFLINE if machine.status == Machine.Status.ONLINE else Machine.Status.ONLINE
            changed_at = timezone.now()
            machine.telemetry_paused_at = None
            machine.last_updated_at = changed_at
            machine.save(update_fields=[
                'status', 'telemetry_paused_at', 'last_updated_at',
            ])
            api.enqueue_machine_command(
                machine,
                (
                    MachineCommand.Command.START
                    if machine.status == Machine.Status.ONLINE
                    else MachineCommand.Command.STOP
                ),
            )
            action_text = 'ส่งคำสั่งเปิดเครื่อง' if machine.status == Machine.Status.ONLINE else 'ส่งคำสั่งหยุดเครื่อง'
            request.session['toast'] = {
                'type': 'success',
                'title': 'ส่งคำสั่งแล้ว',
                'message': f'{action_text} {machine.code} แล้ว รออุปกรณ์ตอบรับคำสั่ง',
            }
    return redirect('machines')


@login_required
@require_POST
def machine_toggle_suspension(request):
    if not is_system_admin(request):
        return deny_org_admin(request)
    with transaction.atomic():
        machine = Machine.objects.select_for_update().filter(pk=request.POST.get('id')).first()
        if not machine:
            request.session['toast'] = {
                'type': 'error', 'title': 'ไม่พบข้อมูล', 'message': 'ไม่พบเครื่องที่เลือก',
            }
            return redirect('machines')
        if machine.status == Machine.Status.SUSPENDED:
            machine.status = Machine.Status.OFFLINE
            message = 'เปิดใช้งานเครื่องแล้ว เครื่องจะอยู่ในสถานะออฟไลน์เพื่อความปลอดภัย'
        else:
            machine.status = Machine.Status.SUSPENDED
            api.enqueue_machine_command(machine, MachineCommand.Command.STOP)
            message = 'ระงับการใช้งานเครื่องแล้ว'
        machine.telemetry_paused_at = None
        machine.last_updated_at = timezone.now()
        machine.save(update_fields=['status', 'telemetry_paused_at', 'last_updated_at'])
    request.session['toast'] = {
        'type': 'success', 'title': 'บันทึกแล้ว', 'message': message,
    }
    return redirect('/machines/?show_suspended=1')


@login_required
def users_view(request):
    users = User.objects.select_related('organization').exclude(
        role=User.Role.SUPER_ADMIN,
    ).order_by('-created_at', '-id')
    search = request.GET.get('search', '')
    role_filter = request.GET.get('role', 'All')
    status_filter = request.GET.get('status', 'All')
    organization_filter = request.GET.get('organization', 'All')
    view_scope = request.GET.get('view', 'admins') if is_system_admin(request) else 'collectors'

    if is_system_admin(request):
        if view_scope != 'all':
            view_scope = 'admins'
            users = users.filter(role=User.Role.ORGANIZATION_ADMIN)
            role_filter = 'Admin'
        elif role_filter != 'All':
            role_value = User.Role.ORGANIZATION_ADMIN if role_filter == 'Admin' else User.Role.COLLECTOR
            users = users.filter(role=role_value)
        if organization_filter != 'All':
            users = users.filter(organization_id=organization_filter)
    else:
        users = users.filter(
            organization_id=current_org_id(request),
            role=User.Role.COLLECTOR,
        )
        role_filter = 'Collector'
        organization_filter = current_org_id(request)
    if search:
        from django.db.models import Q
        users = users.filter(Q(name__icontains=search) | Q(email__icontains=search))
    if status_filter != 'All':
        users = users.filter(status=status_filter)
    active = [{
        'id': u.id, 'name': u.name, 'email': u.email,
        'role': 'Admin' if u.role == User.Role.ORGANIZATION_ADMIN else u.role,
        'status': u.status, 'organization_id': u.organization_id,
        'organization_name': u.organization.name if u.organization else '-',
        'can_manage': (
            (is_system_admin(request) and u.role == User.Role.ORGANIZATION_ADMIN)
            or (
                not is_system_admin(request)
                and u.role == User.Role.COLLECTOR
                and u.organization_id == current_org_id(request)
            )
        ),
    } for u in users]

    users_pagination = paginate_admin(request, active)
    organization_admin_by_org = dict(
        User.objects.filter(
            role=User.Role.ORGANIZATION_ADMIN,
            organization_id__isnull=False,
        ).values_list('organization_id', 'id')
    )
    admin_organizations = [
        {
            **organization,
            'admin_id': organization_admin_by_org.get(organization['id'], ''),
        }
        for organization in get_organizations(request.session)
    ]
    toast = request.session.pop('toast', None)
    return render_admin(request, 'core/users.html', {
        'active_tab': 'users',
        'active_users': users_pagination['items'],
        'users_pagination': users_pagination,
        'search': search,
        'role_filter': role_filter,
        'status_filter': status_filter,
        'organization_filter': organization_filter,
        'view_scope': view_scope,
        'admin_organizations': admin_organizations,
        'has_available_admin_organization': any(
            not organization['admin_id'] for organization in admin_organizations
        ),
        'toast': toast,
    })


@login_required
@require_POST
def user_add(request):
    name = request.POST.get('name', '').strip()
    email = request.POST.get('email', '').strip().lower()
    password = request.POST.get('password', '').strip()
    system_admin = is_system_admin(request)
    organization_id = request.POST.get('organization_id') if system_admin else current_org_id(request)
    role = User.Role.ORGANIZATION_ADMIN if system_admin else User.Role.COLLECTOR
    organization_exists = Organization.objects.filter(pk=organization_id).exists()

    if not name or not email or not password or not organization_id or not organization_exists:
        request.session['toast'] = {
            'type': 'error', 'title': 'กรอกข้อมูลไม่ครบ',
            'message': 'กรุณากรอกชื่อ อีเมล รหัสผ่าน และเลือกหน่วยงานให้ถูกต้อง',
        }
    elif User.objects.filter(email__iexact=email).exists():
        request.session['toast'] = {'type': 'error', 'title': 'ผิดพลาด', 'message': 'อีเมลนี้มีอยู่ในระบบแล้ว'}
    elif system_admin and User.objects.filter(
        organization_id=organization_id,
        role=User.Role.ORGANIZATION_ADMIN,
    ).exists():
        request.session['toast'] = {
            'type': 'error',
            'title': 'หน่วยงานนี้มีแอดมินแล้ว',
            'message': 'หนึ่งหน่วยงานมีแอดมินหน่วยงานได้เพียง 1 คน กรุณาเลือกหน่วยงานอื่น',
        }
    else:
        user = User(
            id=f'U{secrets.token_hex(6).upper()}', name=name, email=email, phone='-',
            role=role, status=User.Status.ACTIVE, organization_id=organization_id,
        )
        user.set_password(password)
        user.save()
        role_name = 'แอดมินหน่วยงาน' if system_admin else 'ผู้เก็บขยะ'
        request.session['toast'] = {
            'type': 'success', 'title': 'บันทึกแล้ว',
            'message': f'เพิ่ม{role_name}เรียบร้อยแล้ว',
        }
    return redirect('users')


@login_required
@require_POST
def user_action(request):
    uid = request.POST.get('id')
    action = request.POST.get('action')
    system_admin = is_system_admin(request)
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    return_view = request.POST.get('return_view')
    redirect_url = '/users/?view=all' if system_admin and return_view == 'all' else '/users/'

    user = User.objects.filter(pk=uid).first()
    can_manage = bool(user) and (
        (system_admin and user.role == User.Role.ORGANIZATION_ADMIN)
        or (
            not system_admin
            and user.role == User.Role.COLLECTOR
            and user.organization_id == current_org_id(request)
        )
    )
    if not can_manage:
        if is_ajax:
            return JsonResponse({
                'success': False,
                'message': 'คุณไม่มีสิทธิ์จัดการผู้ใช้งานรายการนี้',
            }, status=403)
        request.session['toast'] = {
            'type': 'error', 'title': 'ไม่มีสิทธิ์',
            'message': 'คุณไม่มีสิทธิ์จัดการผู้ใช้งานรายการนี้',
        }
        return redirect(redirect_url)

    if user:
        if action == 'approve':
            user.status = User.Status.ACTIVE
            user.save(update_fields=['status'])
            request.session['toast'] = {'type': 'success', 'title': 'บันทึกแล้ว', 'message': 'อนุมัติผู้ใช้งานแล้ว'}
        elif action == 'reject':
            user.delete()
            request.session['toast'] = {'type': 'success', 'title': 'บันทึกแล้ว', 'message': 'ปฏิเสธผู้ใช้งานแล้ว'}
        elif action == 'suspend':
            user.status = User.Status.SUSPENDED if user.status == User.Status.ACTIVE else User.Status.ACTIVE
            user.save(update_fields=['status'])
            status_label = 'ใช้งาน' if user.status == User.Status.ACTIVE else 'ระงับ'
            message = f'เปลี่ยนสถานะบัญชีเป็น {status_label} แล้ว'
            if is_ajax:
                return JsonResponse({
                    'success': True,
                    'status': user.status,
                    'status_label': status_label,
                    'message': message,
                })
            request.session['toast'] = {
                'type': 'success', 'title': 'บันทึกแล้ว', 'message': message,
            }
        elif action == 'role':
            if system_admin:
                organization_id = request.POST.get('organization_id', user.organization_id)
                if not Organization.objects.filter(pk=organization_id).exists():
                    request.session['toast'] = {
                        'type': 'error', 'title': 'ข้อมูลไม่ถูกต้อง',
                        'message': 'ไม่พบหน่วยงานที่เลือก',
                    }
                    return redirect(redirect_url)
                if User.objects.filter(
                    organization_id=organization_id,
                    role=User.Role.ORGANIZATION_ADMIN,
                ).exclude(pk=user.pk).exists():
                    request.session['toast'] = {
                        'type': 'error',
                        'title': 'ย้ายหน่วยงานไม่ได้',
                        'message': 'หน่วยงานที่เลือกมีแอดมินหน่วยงานอยู่แล้ว หนึ่งหน่วยงานมีแอดมินได้เพียง 1 คน',
                    }
                    return redirect(redirect_url)
                user.role = User.Role.ORGANIZATION_ADMIN
                user.organization_id = organization_id
            else:
                user.role = User.Role.COLLECTOR
            user.save(update_fields=['role', 'organization'])
            request.session['toast'] = {'type': 'success', 'title': 'บันทึกแล้ว', 'message': 'แก้ไขผู้ใช้งานแล้ว'}
    return redirect(redirect_url)


@login_required
def issues_view(request):
    issues = enrich_with_org(request.session, visible_records(request, get_issues(request.session)))
    topics = get_topics(request.session)
    active_tab = request.GET.get('tab', 'Waiting')
    organization_filter = request.GET.get('organization', 'All')

    if is_system_admin(request):
        issues = [issue for issue in issues if issue.get('escalated')]

    if is_system_admin(request) and organization_filter != 'All':
        issues = [i for i in issues if i.get('organization_id') == organization_filter]

    filtered = [i for i in issues if i['status'] == active_tab]
    counts = {
        'Waiting': sum(1 for i in issues if i['status'] == 'Waiting'),
        'In Progress': sum(1 for i in issues if i['status'] == 'In Progress'),
        'Completed': sum(1 for i in issues if i['status'] == 'Completed'),
    }

    issues_pagination = paginate_admin(request, filtered)
    toast = request.session.pop('toast', None)
    return render_admin(request, 'core/issues.html', {
        'active_tab_page': 'issues',
        'active_tab': active_tab,
        'issues': issues_pagination['items'],
        'issues_pagination': issues_pagination,
        'topics': topics,
        'counts': counts,
        'toast': toast,
        'organization_filter': organization_filter,
        'tabs': [('Waiting', 'Waiting'), ('In Progress', 'In Progress'), ('Completed', 'Completed')],
    })


@login_required
@require_POST
def issue_next_status(request):
    iid = int(request.POST.get('id'))
    tab = request.POST.get('tab', 'Waiting')
    status_map = {'Waiting': 'In Progress', 'In Progress': 'Completed'}

    issue = IssueReport.objects.select_related('machine').filter(pk=iid).first()
    can_manage = bool(issue) and (
        (is_system_admin(request) and issue.escalated_at is not None)
        or (
            not is_system_admin(request)
            and issue.machine.organization_id == current_org_id(request)
            and issue.escalated_at is None
        )
    )
    if issue and issue.status in status_map and can_manage:
        issue.status = status_map[issue.status]
        issue.save(update_fields=['status', 'updated_at'])
        request.session['toast'] = {'type': 'success', 'title': 'บันทึกแล้ว', 'message': 'เปลี่ยนสถานะแจ้งซ่อมแล้ว'}
    elif issue and not can_manage:
        request.session['toast'] = {
            'type': 'error',
            'title': 'ไม่สามารถดำเนินการได้',
            'message': 'รายการนี้ส่งให้แอดมินสูงสุดแล้ว แอดมินหน่วยงานไม่สามารถรับเรื่องหรือปิดงานได้',
        }
    return redirect(f'/issues/?tab={tab}')


@login_required
@require_POST
def issue_escalate(request):
    if is_system_admin(request):
        return deny_org_admin(request)
    issue = IssueReport.objects.select_related('machine').filter(
        pk=request.POST.get('id'),
        machine__organization_id=current_org_id(request),
    ).first()
    if not issue or issue.status == IssueReport.Status.COMPLETED:
        request.session['toast'] = {
            'type': 'error', 'title': 'ส่งเรื่องไม่ได้',
            'message': 'ไม่พบรายการหรือรายการนี้ดำเนินการเสร็จแล้ว',
        }
    else:
        issue.status = IssueReport.Status.WAITING
        issue.escalated_at = timezone.now()
        issue.escalated_by_id = request.session.get('user_id')
        issue.save(update_fields=['status', 'escalated_at', 'escalated_by', 'updated_at'])
        request.session['toast'] = {
            'type': 'success', 'title': 'ส่งเรื่องแล้ว',
            'message': 'ส่งเรื่องให้แอดมินสูงสุดแล้ว และปรับสถานะเป็นรอดำเนินการ',
        }
    return redirect('/issues/?tab=Waiting')


@login_required
@require_POST
def topic_add(request):
    new_topic = request.POST.get('topic', '').strip()
    if new_topic and not IssueCategory.objects.filter(name__iexact=new_topic).exists():
        IssueCategory.objects.create(name=new_topic)
        request.session['toast'] = {'type': 'success', 'title': 'บันทึกแล้ว', 'message': 'เพิ่มหัวข้อปัญหาแล้ว'}
    return redirect(f'/issues/?tab={request.POST.get("tab", "Waiting")}&topics=1')


@login_required
@require_POST
def topic_delete(request):
    topic = request.POST.get('topic', '')
    IssueCategory.objects.filter(name=topic).update(is_active=False)
    return redirect(f'/issues/?tab={request.POST.get("tab", "Waiting")}&topics=1')


@login_required
def statistics_view(request):
    start_date = normalize_date_parameter(request.GET.get('start', ''))
    end_date = normalize_date_parameter(request.GET.get('end', ''))
    search = request.GET.get('search', '')
    organization_filter = request.GET.get('organization', 'All')
    machine_filter = request.GET.get('machine', 'All')
    type_filter = request.GET.get('type', 'All')
    staff_filter = request.GET.get('staff', 'All')

    history = enrich_with_org(request.session, visible_records(request, get_collection_history()))
    if is_system_admin(request) and organization_filter != 'All':
        history = [h for h in history if h.get('organization_id') == organization_filter]
    machine_options = sorted({h['machine'] for h in history})
    type_options = sorted({h['type'] for h in history})
    staff_options = sorted({h['staff'] for h in history})
    if start_date and end_date:
        history = [h for h in history if start_date <= h['date'] <= end_date]
    elif start_date:
        history = [h for h in history if h['date'] == start_date]
    if machine_filter != 'All':
        history = [h for h in history if h['machine'] == machine_filter]
    if type_filter != 'All':
        history = [h for h in history if h['type'] == type_filter]
    if staff_filter != 'All':
        history = [h for h in history if h['staff'] == staff_filter]
    if search:
        history = [h for h in history if search.lower() in h['staff'].lower() or search.lower() in h['type'].lower() or search.lower() in h['machine'].lower()]

    history_all = history
    total_weight = sum(row['weight'] for row in history_all)
    statistics_pagination = paginate_admin(request, history_all)
    toast = request.session.pop('toast', None)
    report_color = '#2563eb'
    current_org_info = current_org(request)
    report_scope = 'ทุกหน่วยงาน'
    if current_org_info:
        report_color = current_org_info.get('card_color', report_color)
        report_scope = current_org_info.get('name', report_scope)
    elif organization_filter != 'All':
        selected_org = org_map(request.session).get(organization_filter, {})
        report_color = selected_org.get('card_color', report_color)
        report_scope = selected_org.get('name', report_scope)
    if start_date and end_date:
        report_period = f'{display_date(start_date)} - {display_date(end_date)}'
    elif start_date:
        report_period = display_date(start_date)
    elif end_date:
        report_period = f'ถึง {display_date(end_date)}'
    else:
        report_period = 'ทุกช่วงเวลา'
    return render_admin(request, 'core/statistics.html', {
        'active_tab': 'statistics',
        'history': statistics_pagination['items'],
        'history_all': history_all,
        'statistics_pagination': statistics_pagination,
        'start_date': start_date,
        'end_date': end_date,
        'start_date_display': display_date(start_date),
        'end_date_display': display_date(end_date),
        'search': search,
        'organization_filter': organization_filter,
        'machine_filter': machine_filter,
        'type_filter': type_filter,
        'staff_filter': staff_filter,
        'machine_options': machine_options,
        'type_options': type_options,
        'staff_options': staff_options,
        'total_weight': total_weight,
        'report_color': report_color,
        'report_scope': report_scope,
        'report_period': report_period,
        'generated_at': timezone.localtime(),
        'toast': toast,
    })


@login_required
def statistics_export(request):
    history = enrich_with_org(request.session, visible_records(request, get_collection_history()))
    organization_filter = request.GET.get('organization', 'All')
    start_date = normalize_date_parameter(request.GET.get('start', ''))
    end_date = normalize_date_parameter(request.GET.get('end', ''))
    machine_filter = request.GET.get('machine', 'All')
    type_filter = request.GET.get('type', 'All')
    staff_filter = request.GET.get('staff', 'All')
    search = request.GET.get('search', '')

    if is_system_admin(request) and organization_filter != 'All':
        history = [h for h in history if h.get('organization_id') == organization_filter]
    if start_date and end_date:
        history = [h for h in history if start_date <= h['date'] <= end_date]
    elif start_date:
        history = [h for h in history if h['date'] == start_date]
    if machine_filter != 'All':
        history = [h for h in history if h['machine'] == machine_filter]
    if type_filter != 'All':
        history = [h for h in history if h['type'] == type_filter]
    if staff_filter != 'All':
        history = [h for h in history if h['staff'] == staff_filter]
    if search:
        history = [h for h in history if search.lower() in h['staff'].lower() or search.lower() in h['type'].lower() or search.lower() in h['machine'].lower()]

    output = StringIO(newline='')
    writer = csv.writer(output, lineterminator='\r\n')
    writer.writerow([
        'ลำดับ', 'วันที่', 'เวลา', 'หน่วยงาน', 'เครื่อง',
        'ประเภทขยะ', 'น้ำหนัก (กก.)', 'ผู้ใช้งาน',
    ])
    for index, row in enumerate(history, 1):
        writer.writerow([
            index,
            display_date(row['date']),
            safe_csv_text(row['time']),
            safe_csv_text(row['organization_name']),
            safe_csv_text(row['machine']),
            safe_csv_text(WASTE_TYPE_LABELS.get(row['type'], row['type'])),
            f"{row['weight']:.2f}",
            safe_csv_text(row['staff']),
        ])
    response = HttpResponse(
        output.getvalue().encode('utf-8-sig'),
        content_type='text/csv; charset=utf-8',
    )
    filename = f"RecycleAdmin-report-{timezone.localdate().isoformat()}.csv"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response

