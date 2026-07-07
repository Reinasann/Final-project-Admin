import time
import copy
from datetime import datetime, timedelta
from django.shortcuts import render, redirect
from django.http import HttpResponse, HttpResponseForbidden
from django.views.decorators.http import require_POST
from .dummy_data import (
    get_organizations, get_machines, get_users, get_issues, get_topics,
    MOCK_COLLECTION_HISTORY
)

SYSTEM_ADMIN = 'System admin'
ORG_ADMIN = 'Admin'
WASTE_TYPES = ['Plastic', 'Glass', 'Can']


def login_required(view):
    def wrapper(request, *args, **kwargs):
        if not request.session.get('logged_in'):
            return redirect('login')
        return view(request, *args, **kwargs)
    wrapper.__name__ = view.__name__
    return wrapper


def is_system_admin(request):
    return request.session.get('user_role') == SYSTEM_ADMIN


def current_org_id(request):
    return request.session.get('organization_id')


def org_map(session):
    return {org['id']: org for org in get_organizations(session)}


def current_org(request):
    if is_system_admin(request):
        return None
    return org_map(request.session).get(current_org_id(request))


def visible_records(request, records):
    if is_system_admin(request):
        return records
    oid = current_org_id(request)
    return [item for item in records if item.get('organization_id') == oid]


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



def dashboard_chart_payload(machines, history):
    machine_names = [machine['name'] for machine in machines]
    waste_types = WASTE_TYPES
    history_dates = sorted({row['date'] for row in history})
    if history_dates:
        end_date = datetime.strptime(history_dates[-1], '%Y-%m-%d').date()
    else:
        end_date = datetime.today().date()

    date_range = [end_date - timedelta(days=offset) for offset in range(119, -1, -1)]
    dates = [date.isoformat() for date in date_range]
    labels = [date.strftime('%b %d') for date in date_range]
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
            'valuesByType': values_by_type,
        })

    return {
        'dates': dates,
        'labels': labels,
        'wasteTypes': ['All'] + waste_types,
        'series': series,
        'defaultDays': 7,
    }

def render_admin(request, template_name, context):
    context.setdefault('active_tab_page', context.get('active_tab'))
    context.update({
        'is_system_admin': is_system_admin(request),
        'user_role': request.session.get('user_role', ORG_ADMIN),
        'user_email': request.session.get('user_email', ''),
        'organizations': get_organizations(request.session),
        'current_org': current_org(request),
    })
    return render(request, template_name, context)


def deny_org_admin(request):
    request.session['toast'] = {
        'type': 'error',
        'title': 'Permission denied',
        'message': 'Only System admin can manage organizations.',
    }
    return redirect('dashboard')


def login_view(request):
    if request.session.get('logged_in'):
        return redirect('dashboard')

    error = None
    organizations = get_organizations(request.session)
    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '').strip()
        role = request.POST.get('role', ORG_ADMIN)
        organization_id = request.POST.get('organization_id') or organizations[0]['id']

        if email and password:
            request.session['logged_in'] = True
            request.session['user_email'] = email
            request.session['user_role'] = SYSTEM_ADMIN if role == SYSTEM_ADMIN else ORG_ADMIN
            request.session['organization_id'] = None if role == SYSTEM_ADMIN else organization_id
            return redirect('dashboard')
        error = 'Please enter email and password.'

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
    machines = visible_records(request, get_machines(request.session))
    users = visible_records(request, get_users(request.session))
    issues = visible_records(request, get_issues(request.session))
    history = visible_records(request, MOCK_COLLECTION_HISTORY)

    online_count = sum(1 for m in machines if m['status'] == 'Online')
    active_users = sum(1 for u in users if u['status'] == 'Active')
    new_issues = sum(1 for i in issues if i['status'] == 'Waiting')
    today_weight = sum(h['weight'] for h in history if h['date'] == '2023-10-25')

    chart_data = [
        {'label': 'Mon', 'value': 85},
        {'label': 'Tue', 'value': 120},
        {'label': 'Wed', 'value': 95},
        {'label': 'Thu', 'value': 140},
        {'label': 'Fri', 'value': 110},
        {'label': 'Sat', 'value': 60},
        {'label': 'Sun', 'value': 45},
    ]

    return render_admin(request, 'core/dashboard.html', {
        'active_tab': 'dashboard',
        'online_count': online_count,
        'total_machines': len(machines),
        'active_users': active_users,
        'new_issues': new_issues,
        'today_weight': today_weight,
        'chart_data': chart_data,
        'chart_payload': dashboard_chart_payload(machines, history),
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

    toast = request.session.pop('toast', None)
    return render_admin(request, 'core/organizations.html', {
        'active_tab': 'organizations',
        'organizations_list': orgs,
        'toast': toast,
    })


@login_required
@require_POST
def organization_add(request):
    if not is_system_admin(request):
        return deny_org_admin(request)

    organizations = get_organizations(request.session)
    name = request.POST.get('name', '').strip()
    card_color = request.POST.get('card_color', '#2563eb').strip() or '#2563eb'
    if name:
        organizations.append({
            'id': f'org-{int(time.time())}',
            'name': name,
            'card_color': card_color,
        })
        request.session['organizations'] = organizations
        request.session['toast'] = {'type': 'success', 'title': 'Saved', 'message': 'Organization created.'}
    return redirect('organizations')


@login_required
@require_POST
def organization_edit(request):
    if not is_system_admin(request):
        return deny_org_admin(request)

    organizations = get_organizations(request.session)
    oid = request.POST.get('id')
    for org in organizations:
        if org['id'] == oid:
            org['name'] = request.POST.get('name', org['name']).strip() or org['name']
            org['card_color'] = request.POST.get('card_color', org['card_color']).strip() or org['card_color']
            break
    request.session['organizations'] = organizations
    request.session['toast'] = {'type': 'success', 'title': 'Saved', 'message': 'Organization updated.'}
    return redirect('organizations')


@login_required
def machines_view(request):
    machines = enrich_with_org(request.session, visible_records(request, get_machines(request.session)))
    search = request.GET.get('search', '')
    status_filter = request.GET.get('status', 'All')
    organization_filter = request.GET.get('organization', 'All')

    filtered = [
        m for m in machines
        if (search.lower() in m['name'].lower() or search.lower() in m['code'].lower())
        and (status_filter == 'All' or m['status'] == status_filter)
        and (not is_system_admin(request) or organization_filter == 'All' or m['organization_id'] == organization_filter)
    ]

    toast = request.session.pop('toast', None)
    return render_admin(request, 'core/machines.html', {
        'active_tab': 'machines',
        'machines': filtered,
        'search': search,
        'status_filter': status_filter,
        'organization_filter': organization_filter,
        'toast': toast,
    })


@login_required
@require_POST
def machine_add(request):
    machines = get_machines(request.session)
    code = request.POST.get('code', '').strip()
    name = request.POST.get('name', '').strip()
    location = request.POST.get('location', '').strip()
    organization_id = request.POST.get('organization_id') if is_system_admin(request) else current_org_id(request)

    if any(m['code'] == code for m in machines):
        request.session['toast'] = {'type': 'error', 'title': 'Error', 'message': 'Machine code already exists.'}
    elif code and name and organization_id:
        machines.append({
            'id': f'M{int(time.time())}',
            'code': code, 'name': name, 'location': location,
            'status': 'Offline', 'plastic': 0, 'glass': 0, 'can': 0,
            'lastUpdate': 'New', 'capacity': '500kg', 'installDate': 'New',
            'organization_id': organization_id,
        })
        request.session['machines'] = machines
        request.session['toast'] = {'type': 'success', 'title': 'Saved', 'message': 'Machine created.'}
    return redirect('machines')


@login_required
@require_POST
def machine_edit(request):
    machines = get_machines(request.session)
    mid = request.POST.get('id')
    allowed_orgs = None if is_system_admin(request) else {current_org_id(request)}
    for m in machines:
        if m['id'] == mid and (allowed_orgs is None or m.get('organization_id') in allowed_orgs):
            m['name'] = request.POST.get('name', m['name']).strip()
            m['location'] = request.POST.get('location', m['location']).strip()
            m['capacity'] = request.POST.get('capacity', m['capacity']).strip()
            if is_system_admin(request):
                m['organization_id'] = request.POST.get('organization_id', m['organization_id'])
            break
    request.session['machines'] = machines
    request.session['toast'] = {'type': 'success', 'title': 'Saved', 'message': 'Machine updated.'}
    return redirect('machines')


@login_required
def users_view(request):
    users = enrich_with_org(request.session, visible_records(request, get_users(request.session)))
    search = request.GET.get('search', '')
    role_filter = request.GET.get('role', 'All')
    status_filter = request.GET.get('status', 'All')
    pending_search = request.GET.get('pending_search', '')
    organization_filter = request.GET.get('organization', 'All')

    if is_system_admin(request) and organization_filter != 'All':
        users = [u for u in users if u.get('organization_id') == organization_filter]

    pending = [u for u in users if u['status'] == 'Pending'
               and (pending_search.lower() in u['name'].lower() or pending_search.lower() in u['email'].lower())]

    active = [u for u in users if u['status'] != 'Pending'
              and (search.lower() in u['name'].lower() or search.lower() in u['email'].lower())
              and (role_filter == 'All' or u['role'] == role_filter)
              and (status_filter == 'All' or u['status'] == status_filter)]

    toast = request.session.pop('toast', None)
    return render_admin(request, 'core/users.html', {
        'active_tab': 'users',
        'pending_users': pending,
        'active_users': active,
        'search': search,
        'role_filter': role_filter,
        'status_filter': status_filter,
        'pending_search': pending_search,
        'organization_filter': organization_filter,
        'toast': toast,
        'pending_count': len(pending),
    })


@login_required
@require_POST
def user_action(request):
    users = get_users(request.session)
    uid = int(request.POST.get('id'))
    action = request.POST.get('action')
    allowed_orgs = None if is_system_admin(request) else {current_org_id(request)}

    for u in list(users):
        if u['id'] == uid and (allowed_orgs is None or u.get('organization_id') in allowed_orgs):
            if action == 'approve':
                u['status'] = 'Active'
                request.session['toast'] = {'type': 'success', 'title': 'Saved', 'message': 'Member approved.'}
            elif action == 'reject':
                users.remove(u)
                request.session['toast'] = {'type': 'success', 'title': 'Saved', 'message': 'Member rejected.'}
            elif action == 'suspend':
                u['status'] = 'Suspended' if u['status'] == 'Active' else 'Active'
                request.session['toast'] = {'type': 'success', 'title': 'Saved', 'message': 'Member status changed.'}
            elif action == 'role':
                u['role'] = request.POST.get('role', u['role'])
                if is_system_admin(request):
                    u['organization_id'] = request.POST.get('organization_id', u.get('organization_id'))
                request.session['toast'] = {'type': 'success', 'title': 'Saved', 'message': 'Member updated.'}
            break

    request.session['users'] = users
    return redirect('users')


@login_required
def issues_view(request):
    issues = enrich_with_org(request.session, visible_records(request, get_issues(request.session)))
    topics = get_topics(request.session)
    active_tab = request.GET.get('tab', 'Waiting')
    organization_filter = request.GET.get('organization', 'All')

    if is_system_admin(request) and organization_filter != 'All':
        issues = [i for i in issues if i.get('organization_id') == organization_filter]

    filtered = [i for i in issues if i['status'] == active_tab]
    counts = {
        'Waiting': sum(1 for i in issues if i['status'] == 'Waiting'),
        'In Progress': sum(1 for i in issues if i['status'] == 'In Progress'),
        'Completed': sum(1 for i in issues if i['status'] == 'Completed'),
    }

    toast = request.session.pop('toast', None)
    return render_admin(request, 'core/issues.html', {
        'active_tab_page': 'issues',
        'active_tab': active_tab,
        'issues': filtered,
        'topics': topics,
        'counts': counts,
        'toast': toast,
        'organization_filter': organization_filter,
        'tabs': [('Waiting', 'Waiting'), ('In Progress', 'In Progress'), ('Completed', 'Completed')],
    })


@login_required
@require_POST
def issue_next_status(request):
    issues = get_issues(request.session)
    iid = int(request.POST.get('id'))
    tab = request.POST.get('tab', 'Waiting')
    status_map = {'Waiting': 'In Progress', 'In Progress': 'Completed'}
    allowed_orgs = None if is_system_admin(request) else {current_org_id(request)}

    for i in issues:
        if i['id'] == iid and i['status'] in status_map and (allowed_orgs is None or i.get('organization_id') in allowed_orgs):
            i['status'] = status_map[i['status']]
            request.session['toast'] = {'type': 'success', 'title': 'Saved', 'message': f'Status changed to {i["status"]}.'}
            break

    request.session['issues'] = issues
    return redirect(f'/issues/?tab={tab}')


@login_required
@require_POST
def topic_add(request):
    topics = get_topics(request.session)
    new_topic = request.POST.get('topic', '').strip()
    if new_topic and new_topic not in topics:
        topics.append(new_topic)
        request.session['topics'] = topics
        request.session['toast'] = {'type': 'success', 'title': 'Saved', 'message': 'Topic added.'}
    return redirect(f'/issues/?tab={request.POST.get("tab", "Waiting")}&topics=1')


@login_required
@require_POST
def topic_delete(request):
    topics = get_topics(request.session)
    topic = request.POST.get('topic', '')
    if topic in topics:
        topics.remove(topic)
        request.session['topics'] = topics
    return redirect(f'/issues/?tab={request.POST.get("tab", "Waiting")}&topics=1')


@login_required
def statistics_view(request):
    start_date = request.GET.get('start', '')
    end_date = request.GET.get('end', '')
    search = request.GET.get('search', '')
    organization_filter = request.GET.get('organization', 'All')

    history = enrich_with_org(request.session, visible_records(request, MOCK_COLLECTION_HISTORY))
    if is_system_admin(request) and organization_filter != 'All':
        history = [h for h in history if h.get('organization_id') == organization_filter]
    if start_date and end_date:
        history = [h for h in history if start_date <= h['date'] <= end_date]
    elif start_date:
        history = [h for h in history if h['date'] == start_date]
    if search:
        history = [h for h in history if search.lower() in h['staff'].lower() or search.lower() in h['type'].lower() or search.lower() in h['machine'].lower()]

    total_weight = sum(row['weight'] for row in history)
    toast = request.session.pop('toast', None)
    return render_admin(request, 'core/statistics.html', {
        'active_tab': 'statistics',
        'history': history,
        'start_date': start_date,
        'end_date': end_date,
        'search': search,
        'organization_filter': organization_filter,
        'total_weight': total_weight,
        'toast': toast,
    })


@login_required
def statistics_export(request):
    history = enrich_with_org(request.session, visible_records(request, MOCK_COLLECTION_HISTORY))
    lines = ['date,time,organization,machine,type,weight,staff']
    for row in history:
        lines.append(f"{row['date']},{row['time']},{row['organization_name']},{row['machine']},{row['type']},{row['weight']},{row['staff']}")
    response = HttpResponse('\n'.join(lines), content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="organization-report.csv"'
    return response

