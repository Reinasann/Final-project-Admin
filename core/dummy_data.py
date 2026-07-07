import copy

INITIAL_ORGANIZATIONS = [
    {'id': 'org-1', 'name': 'Green Campus', 'card_color': '#2563eb'},
    {'id': 'org-2', 'name': 'City Recycle Center', 'card_color': '#16a34a'},
]

INITIAL_MACHINES = [
    {'id': 'M001', 'code': 'SR-001', 'name': 'Recycle Station A', 'location': 'Central Cafeteria', 'status': 'Online', 'plastic': 45, 'glass': 90, 'can': 20, 'lastUpdate': '10 mins ago', 'capacity': '500kg', 'installDate': '01/01/2023', 'organization_id': 'org-1'},
    {'id': 'M002', 'code': 'SR-002', 'name': 'Recycle Station B', 'location': 'Student Dormitory', 'status': 'Offline', 'plastic': 10, 'glass': 10, 'can': 5, 'lastUpdate': '2 hours ago', 'capacity': '500kg', 'installDate': '15/02/2023', 'organization_id': 'org-1'},
    {'id': 'M003', 'code': 'SR-003', 'name': 'Recycle Station C', 'location': 'Learning Building 5', 'status': 'Online', 'plastic': 80, 'glass': 30, 'can': 60, 'lastUpdate': '5 mins ago', 'capacity': '750kg', 'installDate': '10/03/2023', 'organization_id': 'org-2'},
    {'id': 'M004', 'code': 'SR-004', 'name': 'Recycle Station D', 'location': 'Activity Building Parking', 'status': 'Online', 'plastic': 95, 'glass': 15, 'can': 40, 'lastUpdate': '1 min ago', 'capacity': '500kg', 'installDate': '20/04/2023', 'organization_id': 'org-2'},
]

INITIAL_USERS = [
    {'id': 1, 'name': 'Somchai Rakdee', 'role': 'Collector', 'status': 'Active', 'email': 'somchai@recycle.com', 'phone': '081-111-1111', 'organization_id': 'org-1'},
    {'id': 2, 'name': 'Wilaivan Jaidee', 'role': 'Admin', 'status': 'Active', 'email': 'wilai@recycle.com', 'phone': '089-999-9999', 'organization_id': 'org-1'},
    {'id': 3, 'name': 'New Collector', 'role': 'Collector', 'status': 'Pending', 'email': 'newbie@recycle.com', 'phone': '090-000-0000', 'organization_id': 'org-1'},
    {'id': 4, 'name': 'Mana Odton', 'role': 'Collector', 'status': 'Suspended', 'email': 'mana@recycle.com', 'phone': '082-222-2222', 'organization_id': 'org-2'},
    {'id': 5, 'name': 'Somsri Khayan', 'role': 'Collector', 'status': 'Active', 'email': 'somsri@recycle.com', 'phone': '083-333-3333', 'organization_id': 'org-2'},
]

DEFAULT_TOPICS = ['Machine not working', 'Sensor abnormal', 'Bin damaged', 'Electrical issue', 'Other']

INITIAL_ISSUES = [
    {'id': 1, 'title': 'Sensor abnormal', 'status': 'Waiting', 'time': '11:15', 'reporter': 'Somchai Rakdee (Collector)', 'description': 'Plastic level sensor stays at 100%.', 'location': 'Recycle Station B', 'reportDate': '2023-10-25', 'organization_id': 'org-1'},
    {'id': 2, 'title': 'Bin damaged', 'status': 'Waiting', 'time': '12:00', 'reporter': 'New Collector (Collector)', 'description': 'Glass bin cover is broken and cannot close properly.', 'location': 'Recycle Station A', 'reportDate': '2023-10-25', 'organization_id': 'org-1'},
    {'id': 3, 'title': 'Electrical issue', 'status': 'In Progress', 'time': '09:30', 'reporter': 'Mana Odton (Collector)', 'description': 'Display is off and status lights are not working.', 'location': 'Recycle Station C', 'reportDate': '2023-10-24', 'organization_id': 'org-2'},
    {'id': 4, 'title': 'Machine not working', 'status': 'Completed', 'time': '14:20', 'reporter': 'Somsri Khayan (Collector)', 'description': 'Bottle conveyor was jammed.', 'location': 'Recycle Station D', 'reportDate': '2023-10-23', 'organization_id': 'org-2'},
]

MOCK_COLLECTION_HISTORY = [
    {'id': 1, 'date': '2023-10-25', 'time': '10:30', 'machine': 'Recycle Station A', 'type': 'Plastic', 'weight': 5.5, 'staff': 'Somchai Rakdee', 'organization_id': 'org-1'},
    {'id': 2, 'date': '2023-10-25', 'time': '11:00', 'machine': 'Recycle Station B', 'type': 'Glass', 'weight': 12.0, 'staff': 'Somchai Rakdee', 'organization_id': 'org-1'},
    {'id': 3, 'date': '2023-10-26', 'time': '09:15', 'machine': 'Recycle Station A', 'type': 'Can', 'weight': 3.2, 'staff': 'Wilaivan Jaidee', 'organization_id': 'org-1'},
    {'id': 4, 'date': '2023-10-26', 'time': '14:20', 'machine': 'Recycle Station C', 'type': 'Plastic', 'weight': 8.0, 'staff': 'Mana Odton', 'organization_id': 'org-2'},
    {'id': 5, 'date': '2023-10-27', 'time': '08:45', 'machine': 'Recycle Station B', 'type': 'Plastic', 'weight': 15.0, 'staff': 'Wilaivan Jaidee', 'organization_id': 'org-1'},
    {'id': 6, 'date': '2023-10-27', 'time': '16:00', 'machine': 'Recycle Station D', 'type': 'Glass', 'weight': 6.5, 'staff': 'Somsri Khayan', 'organization_id': 'org-2'},
]


def get_organizations(session):
    if 'organizations' not in session:
        session['organizations'] = copy.deepcopy(INITIAL_ORGANIZATIONS)
    return session['organizations']


def get_machines(session):
    if 'machines' not in session:
        session['machines'] = copy.deepcopy(INITIAL_MACHINES)
    return session['machines']


def get_users(session):
    if 'users' not in session:
        session['users'] = copy.deepcopy(INITIAL_USERS)
    return session['users']


def get_issues(session):
    if 'issues' not in session:
        session['issues'] = copy.deepcopy(INITIAL_ISSUES)
    return session['issues']


def get_topics(session):
    if 'topics' not in session:
        session['topics'] = copy.deepcopy(DEFAULT_TOPICS)
    return session['topics']
