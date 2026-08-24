import csv
import json
from datetime import timedelta
from io import StringIO

from django.test import TestCase, override_settings
from django.utils import timezone

from .models import (
    ApiToken, CollectionHistory, IssueCategory, IssueReport, Machine, MachineBin,
    MachineInformation, Notification, NotificationEvent, Organization,
    PasswordResetCode, PushDevice, Telemetry, User,
)
from .templatetags.core_extras import ddmmyy
from .views import display_date, normalize_date_parameter


class DateFormattingTests(TestCase):
    def test_formats_dates_as_day_month_four_digit_year(self):
        self.assertEqual(ddmmyy("2026-08-05"), "05/08/2026")
        self.assertEqual(ddmmyy("2026-08-05T12:28:00+07:00"), "05/08/2026")
        self.assertEqual(ddmmyy("05/08/2026"), "05/08/2026")

    def test_accepts_display_date_for_internal_filters(self):
        self.assertEqual(normalize_date_parameter("05/08/2026"), "2026-08-05")
        self.assertEqual(display_date("2026-08-05"), "05/08/2026")


class UserManagementPermissionTests(TestCase):
    def setUp(self):
        self.organization_a = Organization.objects.create(
            id="org-a", name="Organization A", card_color="#2563eb",
        )
        self.organization_b = Organization.objects.create(
            id="org-b", name="Organization B", card_color="#16a34a",
        )
        self.super_admin = self.create_user(
            "SA100", None, "Super Admin", "super@example.com", User.Role.SUPER_ADMIN,
        )
        self.organization_admin_a = self.create_user(
            "OA100", self.organization_a, "Admin A", "admin-a@example.com",
            User.Role.ORGANIZATION_ADMIN,
        )
        self.organization_admin_b = self.create_user(
            "OA200", self.organization_b, "Admin B", "admin-b@example.com",
            User.Role.ORGANIZATION_ADMIN,
        )
        self.collector_a = self.create_user(
            "UC100", self.organization_a, "Collector A", "collector-a@example.com",
            User.Role.COLLECTOR,
        )
        self.collector_b = self.create_user(
            "UC200", self.organization_b, "Collector B", "collector-b@example.com",
            User.Role.COLLECTOR,
        )

    @staticmethod
    def create_user(user_id, organization, name, email, role):
        user = User(
            id=user_id, organization=organization, name=name, email=email,
            role=role, status=User.Status.ACTIVE,
        )
        user.set_password("password123")
        user.save()
        return user

    def login(self, email):
        response = self.client.post("/", data={"email": email, "password": "password123"})
        self.assertRedirects(response, "/dashboard/")

    def test_super_admin_sees_organization_admins_by_default_and_can_view_all(self):
        self.login(self.super_admin.email)

        response = self.client.get("/users/")
        visible_emails = {user["email"] for user in response.context["active_users"]}
        self.assertEqual(visible_emails, {
            self.organization_admin_a.email,
            self.organization_admin_b.email,
        })

        response = self.client.get("/users/?view=all")
        visible_emails = {user["email"] for user in response.context["active_users"]}
        self.assertEqual(visible_emails, {
            self.organization_admin_a.email,
            self.organization_admin_b.email,
            self.collector_a.email,
            self.collector_b.email,
        })

    def test_super_admin_adds_only_an_organization_admin(self):
        self.login(self.super_admin.email)
        response = self.client.post("/users/add/", data={
            "name": "New Organization Admin",
            "email": "new-admin@example.com",
            "password": "new-password",
            "organization_id": self.organization_b.id,
            "role": "Collector",
        })
        self.assertRedirects(response, "/users/")
        created = User.objects.get(email="new-admin@example.com")
        self.assertEqual(created.role, User.Role.ORGANIZATION_ADMIN)
        self.assertEqual(created.organization, self.organization_b)

    def test_organization_admin_sees_and_adds_collectors_only_in_own_organization(self):
        self.login(self.organization_admin_a.email)

        response = self.client.get("/users/")
        visible_emails = {user["email"] for user in response.context["active_users"]}
        self.assertEqual(visible_emails, {self.collector_a.email})

        response = self.client.post("/users/add/", data={
            "name": "New Collector A",
            "email": "new-collector@example.com",
            "password": "new-password",
            "organization_id": self.organization_b.id,
            "role": "Admin",
        })
        self.assertRedirects(response, "/users/")
        created = User.objects.get(email="new-collector@example.com")
        self.assertEqual(created.role, User.Role.COLLECTOR)
        self.assertEqual(created.organization, self.organization_a)

    def test_admin_levels_cannot_manage_users_outside_their_scope(self):
        self.login(self.organization_admin_a.email)
        response = self.client.post("/users/action/", data={
            "id": self.collector_a.id,
            "action": "role",
            "role": "Admin",
            "organization_id": self.organization_b.id,
        })
        self.assertRedirects(response, "/users/")
        self.collector_a.refresh_from_db()
        self.assertEqual(self.collector_a.role, User.Role.COLLECTOR)
        self.assertEqual(self.collector_a.organization, self.organization_a)

        response = self.client.post("/users/action/", data={
            "id": self.collector_b.id,
            "action": "suspend",
        })
        self.assertRedirects(response, "/users/")
        self.collector_b.refresh_from_db()
        self.assertEqual(self.collector_b.status, User.Status.ACTIVE)

        self.client.get("/logout/")
        self.login(self.super_admin.email)
        response = self.client.post("/users/action/", data={
            "id": self.collector_a.id,
            "action": "suspend",
            "return_view": "all",
        })
        self.assertRedirects(response, "/users/?view=all")
        self.collector_a.refresh_from_db()
        self.assertEqual(self.collector_a.status, User.Status.ACTIVE)


class OrganizationColorUniquenessTests(TestCase):
    def setUp(self):
        self.organization_a = Organization.objects.create(
            id="org-color-a", name="Color Organization A", card_color="#2563eb",
        )
        self.organization_b = Organization.objects.create(
            id="org-color-b", name="Color Organization B", card_color="#16a34a",
        )
        self.super_admin = User(
            id="SA-COLOR", name="Color Admin", email="color-admin@example.com",
            role=User.Role.SUPER_ADMIN, status=User.Status.ACTIVE,
        )
        self.super_admin.set_password("password123")
        self.super_admin.save()
        response = self.client.post("/", data={
            "email": self.super_admin.email,
            "password": "password123",
        })
        self.assertRedirects(response, "/dashboard/")

    def test_add_rejects_used_color_and_normalizes_available_color(self):
        response = self.client.post("/organizations/add/", data={
            "name": "Duplicate Color Organization",
            "card_color": "#2563EB",
        })
        self.assertRedirects(response, "/organizations/")
        self.assertFalse(Organization.objects.filter(name="Duplicate Color Organization").exists())

        response = self.client.post("/organizations/add/", data={
            "name": "Unique Color Organization",
            "card_color": "#F97316",
        })
        self.assertRedirects(response, "/organizations/")
        created = Organization.objects.get(name="Unique Color Organization")
        self.assertEqual(created.card_color, "#f97316")

    def test_edit_rejects_color_used_by_another_organization(self):
        response = self.client.post("/organizations/edit/", data={
            "id": self.organization_b.id,
            "name": self.organization_b.name,
            "card_color": self.organization_a.card_color.upper(),
        })
        self.assertRedirects(response, "/organizations/")
        self.organization_b.refresh_from_db()
        self.assertEqual(self.organization_b.card_color, "#16a34a")

    def test_page_suggests_an_unused_color(self):
        response = self.client.get("/organizations/")
        self.assertEqual(response.status_code, 200)
        used_colors = {
            self.organization_a.card_color,
            self.organization_b.card_color,
        }
        self.assertNotIn(response.context["suggested_color"], used_colors)
        self.assertContains(response, 'data-color-hex type="text"', count=3)
        self.assertContains(
            response,
            f'value="{response.context["suggested_color"].upper()}"',
        )


class ApiTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(id="org-1", name="Green Campus")
        self.user = User(
            id="U001", organization=self.organization, name="Collector", email="staff@recycle.com",
            role=User.Role.COLLECTOR, status=User.Status.ACTIVE,
        )
        self.user.set_password("password123")
        self.user.save()
        self.admin = User(
            id="SA001", name="System Admin", email="admin@recycle.com",
            role=User.Role.SUPER_ADMIN, status=User.Status.ACTIVE,
        )
        self.admin.set_password("admin-password")
        self.admin.save()
        self.device = MachineInformation(
            serial_number="ESP32-SR-001",
            model="ESP32",
            hardware_status=MachineInformation.HardwareStatus.INSTALLED,
        )
        self.device.set_api_key("device-secret")
        self.device.save()
        self.machine = Machine.objects.create(
            id="M001", organization=self.organization, device=self.device,
            code="SR-001", name="Station A", location="Cafeteria",
        )
        for waste_type in MachineBin.WasteType.values:
            MachineBin.objects.create(machine=self.machine, waste_type=waste_type)

    def login_token(
        self,
        email="staff@recycle.com",
        password="password123",
    ):
        response = self.client.post(
            "/api/v1/auth/login/",
            data=json.dumps({
                "email": email,
                "password": password,
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        return response.json()["access_token"]

    def test_logout_revokes_current_api_token(self):
        token = self.login_token()
        auth = {"HTTP_AUTHORIZATION": f"Bearer {token}"}

        response = self.client.post("/api/v1/auth/logout/", **auth)

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(ApiToken.objects.get(user=self.user).revoked_at)
        self.assertEqual(self.client.get("/api/v1/me/", **auth).status_code, 401)

    def test_api_token_uses_direct_digest_lookup(self):
        token = self.login_token()
        stored_token = ApiToken.objects.get(user=self.user)

        self.assertEqual(
            stored_token.token_hash,
            ApiToken.digest_token(token),
        )
        self.assertNotEqual(stored_token.token_hash, token)
        self.assertEqual(len(stored_token.token_hash), 64)
        self.assertEqual(
            self.client.get(
                "/api/v1/me/",
                HTTP_AUTHORIZATION=f"Bearer {token}",
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(
                "/api/v1/me/",
                HTTP_AUTHORIZATION="Bearer invalid-token",
            ).status_code,
            401,
        )

    def test_mobile_device_can_register_and_unregister_push_token(self):
        token = self.login_token()
        auth = {"HTTP_AUTHORIZATION": f"Bearer {token}"}

        response = self.client.post(
            "/api/v1/me/push-devices/register/",
            data=json.dumps({
                "token": "test-fcm-registration-token",
                "platform": "android",
            }),
            content_type="application/json",
            **auth,
        )

        self.assertEqual(response.status_code, 201)
        device = PushDevice.objects.get(token="test-fcm-registration-token")
        self.assertEqual(device.user, self.user)
        self.assertTrue(device.is_active)

        response = self.client.post(
            "/api/v1/me/push-devices/unregister/",
            data=json.dumps({"token": device.token}),
            content_type="application/json",
            **auth,
        )
        self.assertEqual(response.status_code, 200)
        device.refresh_from_db()
        self.assertFalse(device.is_active)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEBUG=True,
    )
    def test_password_reset_changes_password_and_revokes_existing_tokens(self):
        old_token = self.login_token()
        response = self.client.post(
            "/api/v1/auth/password-reset/request/",
            data=json.dumps({"email": self.user.email}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        code = response.json()["debug_code"]
        self.assertEqual(len(code), 6)
        self.assertEqual(PasswordResetCode.objects.filter(user=self.user).count(), 1)

        response = self.client.post(
            "/api/v1/auth/password-reset/confirm/",
            data=json.dumps({
                "email": self.user.email,
                "code": code,
                "new_password": "new-password-123",
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("new-password-123"))
        self.assertIsNotNone(
            PasswordResetCode.objects.get(user=self.user).used_at,
        )
        self.assertEqual(
            self.client.get(
                "/api/v1/me/",
                HTTP_AUTHORIZATION=f"Bearer {old_token}",
            ).status_code,
            401,
        )
        login_response = self.client.post(
            "/api/v1/auth/login/",
            data=json.dumps({
                "email": self.user.email,
                "password": "new-password-123",
            }),
            content_type="application/json",
        )
        self.assertEqual(login_response.status_code, 200)

    def test_machine_status_api_persists_status(self):
        token = self.login_token()
        auth = {"HTTP_AUTHORIZATION": f"Bearer {token}"}

        response = self.client.patch(
            f"/api/v1/machines/{self.machine.id}/status/",
            data=json.dumps({"is_on": False}),
            content_type="application/json",
            **auth,
        )

        self.assertEqual(response.status_code, 200)
        self.machine.refresh_from_db()
        self.assertEqual(self.machine.status, Machine.Status.OFFLINE)
        self.assertEqual(response.json()["status"], Machine.Status.OFFLINE)

    def test_collector_sees_all_machines_in_own_organization_only(self):
        same_organization_machine = Machine.objects.create(
            id="M002",
            organization=self.organization,
            code="SR-002",
            name="Unassigned machine",
            location="Building B",
        )
        other_organization = Organization.objects.create(
            id="org-2",
            name="Another Campus",
            card_color="#16a34a",
        )
        other_machine = Machine.objects.create(
            id="M003",
            organization=other_organization,
            code="SR-003",
            name="Other organization machine",
            location="Building C",
        )
        token = self.login_token()
        auth = {"HTTP_AUTHORIZATION": f"Bearer {token}"}

        response = self.client.get("/api/v1/machines/", **auth)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {machine["id"] for machine in response.json()["results"]},
            {self.machine.id, same_organization_machine.id},
        )
        self.assertEqual(
            self.client.get(
                f"/api/v1/machines/{other_machine.id}/",
                **auth,
            ).status_code,
            404,
        )

    def test_login_page_contains_skeleton_loading(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="login-page-skeleton"')
        self.assertContains(response, 'aria-label="กำลังโหลดหน้าเข้าสู่ระบบ"')

    def test_admin_date_fields_include_calendar_pickers(self):
        login_response = self.client.post("/", data={
            "email": self.admin.email,
            "password": "admin-password",
        })
        self.assertRedirects(login_response, "/dashboard/")

        dashboard_response = self.client.get("/dashboard/")
        self.assertContains(dashboard_response, 'id="admin-page-skeleton"')
        self.assertContains(
            dashboard_response,
            'id="admin-page-skeleton" class="fixed inset-y-0 right-0 left-64',
        )
        self.assertContains(dashboard_response, 'aria-label="กำลังโหลดข้อมูล"')
        self.assertContains(dashboard_response, 'id="chart-start-date-picker" type="date"')
        self.assertContains(dashboard_response, 'id="chart-end-date-picker" type="date"')
        self.assertContains(dashboard_response, 'aria-label="เปิดปฏิทินวันที่เริ่มต้น"')
        self.assertEqual(len(dashboard_response.context["chart_payload"]["dates"]), 366)
        self.assertEqual(
            dashboard_response.context["chart_payload"]["defaultRange"],
            "7d",
        )
        for label in ("7 วัน", "30 วัน", "3 เดือน", "6 เดือน", "1 ปี", "กำหนดเอง"):
            self.assertContains(dashboard_response, label)

        statistics_response = self.client.get("/statistics/")
        self.assertContains(statistics_response, 'id="filter-start-picker" type="date"')
        self.assertContains(statistics_response, 'id="filter-end-picker" type="date"')
        self.assertContains(statistics_response, 'aria-label="เปิดปฏิทินวันที่สิ้นสุด"')
        self.assertContains(statistics_response, 'onclick="printStatisticsReport()"')
        self.assertContains(statistics_response, 'report-table')
        self.assertContains(statistics_response, 'table-header-group')
        self.assertContains(statistics_response, 'A4 landscape')

    def test_admin_data_pages_offer_page_size_controls(self):
        login_response = self.client.post("/", data={
            "email": self.admin.email,
            "password": "admin-password",
        })
        self.assertRedirects(login_response, "/dashboard/")

        for path in (
            "/organizations/",
            "/machines/",
            "/users/?view=all",
            "/issues/",
            "/statistics/",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'data-admin-pagination')
                self.assertContains(response, 'aria-label="จำนวนรายการต่อหน้า"')
                for page_size in (10, 25, 50, 100):
                    self.assertContains(response, f'<option value="{page_size}"')

    def test_statistics_paginates_screen_rows_but_keeps_full_print_report(self):
        collection_bin = self.machine.bins.get(
            waste_type=MachineBin.WasteType.PLASTIC,
        )
        for index in range(12):
            CollectionHistory.objects.create(
                bin=collection_bin,
                collector=self.user,
                weight_kg="1.00",
                collected_at=timezone.now() - timedelta(minutes=index),
                label_code=f"PAGE-{index:02d}",
            )

        login_response = self.client.post("/", data={
            "email": self.admin.email,
            "password": "admin-password",
        })
        self.assertRedirects(login_response, "/dashboard/")
        response = self.client.get("/statistics/?page=2&page_size=10")

        self.assertEqual(len(response.context["history"]), 2)
        self.assertEqual(len(response.context["history_all"]), 12)
        pagination = response.context["statistics_pagination"]
        self.assertEqual(pagination["page_number"], 2)
        self.assertEqual(pagination["total_count"], 12)
        self.assertContains(response, 'aria-current="page">2</span>')
        self.assertContains(response, '<tbody class="print-only">')

    def test_statistics_csv_is_excel_compatible_localized_and_safely_quoted(self):
        self.machine.name = "Station, A"
        self.machine.save(update_fields=["name"])
        self.user.name = "=2+2"
        self.user.save(update_fields=["name"])
        CollectionHistory.objects.create(
            bin=self.machine.bins.get(waste_type=MachineBin.WasteType.PLASTIC),
            collector=self.user,
            weight_kg="12.50",
            collected_at=timezone.now(),
        )
        login_response = self.client.post("/", data={
            "email": self.admin.email,
            "password": "admin-password",
        })
        self.assertRedirects(login_response, "/dashboard/")

        response = self.client.get("/statistics/export/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        self.assertTrue(response.content.startswith(b"\xef\xbb\xbf"))
        self.assertRegex(
            response["Content-Disposition"],
            r'attachment; filename="RecycleAdmin-report-\d{4}-\d{2}-\d{2}\.csv"',
        )
        rows = list(csv.reader(StringIO(response.content.decode("utf-8-sig"))))
        self.assertEqual(rows[0], [
            "ลำดับ", "วันที่", "เวลา", "หน่วยงาน", "เครื่อง",
            "ประเภทขยะ", "น้ำหนัก (กก.)", "ผู้ใช้งาน",
        ])
        self.assertEqual(rows[1][4], "Station, A")
        self.assertEqual(rows[1][5], "พลาสติก")
        self.assertEqual(rows[1][6], "12.50")
        self.assertEqual(rows[1][7], "'=2+2")

    def test_login_and_machine_list(self):
        token = self.login_token()
        response = self.client.get("/api/v1/machines/", HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"][0]["id"], "M001")
        self.assertEqual(
            response.json()["results"][0]["serial_number"],
            "ESP32-SR-001",
        )

    def test_super_admin_prepares_serial_before_adding_machine(self):
        login_response = self.client.post("/", data={
            "email": self.admin.email,
            "password": "admin-password",
        })
        self.assertRedirects(login_response, "/dashboard/")

        response = self.client.post("/machines/devices/add/", data={
            "serial_number": "esp32-sr-005",
            "model": "ESP32-S3",
            "firmware_version": "1.2.0",
            "api_key": "device-secret-005",
        })
        self.assertRedirects(
            response,
            "/machines/?devices=1",
            fetch_redirect_response=False,
        )
        prepared_device = MachineInformation.objects.get(pk="ESP32-SR-005")
        self.assertEqual(
            prepared_device.hardware_status,
            MachineInformation.HardwareStatus.AVAILABLE,
        )
        self.assertTrue(prepared_device.check_api_key("device-secret-005"))

        response = self.client.get("/machines/?devices=1")
        self.assertContains(response, "ESP32-SR-005")
        self.assertContains(response, "device-secret-005")
        self.assertContains(response, "พร้อมเลือกตอนเพิ่มเครื่อง")

        response = self.client.post("/machines/add/", data={
            "code": "SHOULD-BE-IGNORED",
            "organization_id": self.organization.id,
            "device_serial": "ESP32-SR-005",
            "name": "Station 5",
            "location": "Building 5",
        })
        self.assertRedirects(response, "/machines/")
        machine = Machine.objects.get(code="SR-005")
        self.assertEqual(machine.name, "Station 5")
        self.assertEqual(machine.device_id, "ESP32-SR-005")
        self.assertEqual(machine.bins.count(), 3)
        self.assertIsNotNone(machine.installed_on)
        prepared_device.refresh_from_db()
        self.assertEqual(
            prepared_device.hardware_status,
            MachineInformation.HardwareStatus.INSTALLED,
        )

        duplicate_response = self.client.post("/machines/add/", data={
            "code": "SR-006",
            "organization_id": self.organization.id,
            "device_serial": "ESP32-SR-005",
        })
        self.assertRedirects(duplicate_response, "/machines/")
        self.assertFalse(Machine.objects.filter(code="SR-006").exists())

        telemetry_response = self.client.post(
            "/api/v1/iot/telemetry/",
            data=json.dumps({
                "device_id": "ESP32-SR-005",
                "recorded_at": "2026-08-15T10:30:00+07:00",
                "bins": [
                    {"waste_type": "plastic", "weight_kg": 2.5, "level_percent": 30},
                    {"waste_type": "glass", "weight_kg": 4.0, "level_percent": 45},
                    {"waste_type": "can", "weight_kg": 1.5, "level_percent": 20},
                ],
            }),
            content_type="application/json",
            HTTP_X_DEVICE_KEY="device-secret-005",
        )
        self.assertEqual(telemetry_response.status_code, 201)

    def test_admin_can_choose_and_save_machine_coordinates(self):
        login_response = self.client.post("/", data={
            "email": self.admin.email,
            "password": "admin-password",
        })
        self.assertRedirects(login_response, "/dashboard/")

        response = self.client.get("/machines/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ใช้ตำแหน่งปัจจุบัน")
        self.assertContains(response, 'id="machine-map"')
        self.assertContains(response, 'id="machine-overview-map"')
        self.assertContains(response, 'onclick="openOverviewMapModal()"')
        self.assertContains(response, 'id="overview-map-modal"')
        self.assertContains(response, 'aria-label="ปิดแผนที่"')
        self.assertEqual(response.context["machine_map_data"][0]["id"], self.machine.id)
        self.assertIsNone(response.context["machine_map_data"][0]["latitude"])

        response = self.client.post("/machines/edit/", data={
            "id": self.machine.id,
            "code": self.machine.code,
            "name": self.machine.name,
            "location": "อาคารทดสอบ ชั้น 1",
            "organization_id": self.organization.id,
            "latitude": "13.7563004",
            "longitude": "100.5018004",
        })
        self.assertRedirects(response, "/machines/")
        self.machine.refresh_from_db()
        self.assertEqual(str(self.machine.latitude), "13.756300")
        self.assertEqual(str(self.machine.longitude), "100.501800")

        response = self.client.get("/machines/")
        map_machine = response.context["machine_map_data"][0]
        self.assertEqual(map_machine["latitude"], 13.7563)
        self.assertEqual(map_machine["longitude"], 100.5018)

    def test_user_app_can_update_profile_collect_waste_and_report_issue(self):
        token = self.login_token()
        auth = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
        category = IssueCategory.objects.create(name="Sensor problem")
        plastic = MachineBin.objects.get(
            machine=self.machine,
            waste_type=MachineBin.WasteType.PLASTIC,
        )
        plastic.current_weight_kg = 4.75
        plastic.current_level_percent = 80
        plastic.save()

        response = self.client.patch(
            "/api/v1/me/profile/",
            data=json.dumps({"name": "Updated Collector", "phone": "0812345678"}),
            content_type="application/json",
            **auth,
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.name, "Updated Collector")

        response = self.client.get("/api/v1/issue-categories/", **auth)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"][0]["id"], category.id)

        response = self.client.post(
            "/api/v1/issues/create/",
            data=json.dumps({
                "machine_id": self.machine.id,
                "category_id": category.id,
                "description": "Ultrasonic sensor does not respond.",
            }),
            content_type="application/json",
            **auth,
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(IssueReport.objects.count(), 1)
        other_user = User.objects.create(
            id="U002", organization=self.organization, name="Other Collector",
            email="other@recycle.com", role=User.Role.COLLECTOR,
            status=User.Status.ACTIVE,
        )
        IssueReport.objects.create(
            machine=self.machine, category=category, reporter=other_user,
            description="Issue reported by another collector.",
        )
        response = self.client.get("/api/v1/issues/?mine=1", **auth)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(response.json()["results"][0]["machine_name"], "Station A")

        response = self.client.post(
            "/api/v1/collections/create/",
            data=json.dumps({
                "machine_id": self.machine.id,
                "waste_type": "plastic",
                "weight_kg": 4.75,
                "label_code": "LBL-M001-TEST",
            }),
            content_type="application/json",
            **auth,
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["label_code"], "LBL-M001-TEST")
        self.assertEqual(
            CollectionHistory.objects.get(collector=self.user).label_code,
            "LBL-M001-TEST",
        )
        CollectionHistory.objects.create(
            bin=plastic, collector=other_user, weight_kg=9.25,
            collected_at=timezone.now(),
        )
        self.assertEqual(CollectionHistory.objects.count(), 2)
        response = self.client.get("/api/v1/collections/?mine=1", **auth)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(response.json()["results"][0]["collector"], "Updated Collector")
        plastic.refresh_from_db()
        self.assertEqual(plastic.current_weight_kg, 0)
        self.assertEqual(plastic.current_level_percent, 0)

    def test_esp32_telemetry_updates_latest_state_and_history(self):
        response = self.client.post(
            "/api/v1/iot/telemetry/",
            data=json.dumps({
                "device_id": "ESP32-SR-001",
                "recorded_at": "2026-07-21T10:30:00+07:00",
                "bins": [
                    {"waste_type": "plastic", "weight_kg": 4.25, "level_percent": 36.5},
                    {"waste_type": "glass", "weight_kg": 12.4, "level_percent": 81},
                    {"waste_type": "can", "weight_kg": 2.1, "level_percent": 20},
                ],
            }),
            content_type="application/json",
            HTTP_X_DEVICE_KEY="device-secret",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Telemetry.objects.count(), 3)
        plastic = MachineBin.objects.get(machine=self.machine, waste_type="plastic")
        self.assertEqual(str(plastic.current_weight_kg), "4.25")
        self.assertEqual(str(plastic.current_level_percent), "36.50")

    def test_full_bin_alert_is_broadcast_and_first_acknowledgement_wins(self):
        colleague = User(
            id="U002",
            organization=self.organization,
            name="Second Collector",
            email="second@recycle.com",
            role=User.Role.COLLECTOR,
            status=User.Status.ACTIVE,
        )
        colleague.set_password("password123")
        colleague.save()
        other_organization = Organization.objects.create(
            id="org-other",
            name="Other Organization",
            card_color="#16a34a",
        )
        outsider = User.objects.create(
            id="U003",
            organization=other_organization,
            name="Outside Collector",
            email="outside@recycle.com",
            role=User.Role.COLLECTOR,
            status=User.Status.ACTIVE,
        )

        def send_telemetry(recorded_at, plastic_level):
            return self.client.post(
                "/api/v1/iot/telemetry/",
                data=json.dumps({
                    "device_id": "ESP32-SR-001",
                    "recorded_at": recorded_at,
                    "bins": [
                        {
                            "waste_type": "plastic",
                            "weight_kg": 8.5,
                            "level_percent": plastic_level,
                        },
                        {
                            "waste_type": "glass",
                            "weight_kg": 1,
                            "level_percent": 10,
                        },
                        {
                            "waste_type": "can",
                            "weight_kg": 1,
                            "level_percent": 10,
                        },
                    ],
                }),
                content_type="application/json",
                HTTP_X_DEVICE_KEY="device-secret",
            )

        self.assertEqual(
            send_telemetry("2026-08-24T10:00:00+07:00", 95).status_code,
            201,
        )
        event = NotificationEvent.objects.get(
            machine=self.machine,
            waste_type=MachineBin.WasteType.PLASTIC,
        )
        self.assertEqual(
            set(event.deliveries.filter(action_required=True).values_list(
                "recipient_id",
                flat=True,
            )),
            {self.user.id, colleague.id},
        )
        self.assertFalse(Notification.objects.filter(recipient=outsider).exists())

        self.assertEqual(
            send_telemetry("2026-08-24T10:01:00+07:00", 96).status_code,
            201,
        )
        self.assertEqual(NotificationEvent.objects.count(), 1)
        self.assertEqual(Notification.objects.filter(action_required=True).count(), 2)

        token = self.login_token()
        auth = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
        response = self.client.get("/api/v1/notifications/", **auth)
        self.assertEqual(response.status_code, 200)
        alert = response.json()["results"][0]
        self.assertTrue(alert["requires_acknowledgement"])

        response = self.client.post(
            f"/api/v1/notifications/{alert['id']}/acknowledge/",
            **auth,
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["already_acknowledged"])
        event.refresh_from_db()
        self.assertEqual(event.acknowledged_by, self.user)
        self.assertEqual(event.acknowledged_by_name, self.user.name)
        self.assertFalse(
            Notification.objects.filter(event=event, action_required=True, is_read=False).exists()
        )
        accepted_notice = Notification.objects.get(
            recipient=colleague,
            event=event,
            action_required=False,
        )
        self.assertIn(self.user.name, accepted_notice.message)

        colleague_token = self.login_token(colleague.email, "password123")
        colleague_delivery = event.deliveries.get(
            recipient=colleague,
            action_required=True,
        )
        response = self.client.post(
            f"/api/v1/notifications/{colleague_delivery.id}/acknowledge/",
            HTTP_AUTHORIZATION=f"Bearer {colleague_token}",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["already_acknowledged"])
        self.assertEqual(
            Notification.objects.filter(event=event, action_required=False).count(),
            1,
        )

        self.assertEqual(
            send_telemetry("2026-08-24T10:02:00+07:00", 20).status_code,
            201,
        )
        event.refresh_from_db()
        self.assertIsNotNone(event.resolved_at)
        self.assertEqual(
            send_telemetry("2026-08-24T10:03:00+07:00", 95).status_code,
            201,
        )
        self.assertEqual(NotificationEvent.objects.count(), 2)
