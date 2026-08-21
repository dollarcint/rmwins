from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import AccessFunction, EmployeeProfile, Role, UserFunctionOverride
from surveys.models import Survey, SurveyAttempt, TargetingQuestion

from .models import (
    AllocationReservation,
    Client,
    ClientIntegration,
    OrganizationClientAccess,
    OrganizationUnit,
    VendorAPIKey,
    VendorClientAllocation,
    VendorCommercialProfile,
    VendorSurveyAllocation,
)
from .services import (
    AllocationUnavailable,
    finalize_attempt_capacity,
    payable_cpi,
    reserve_attempt_capacity,
    resolve_vendor_survey_context,
    survey_pricing_for_user,
)
from .serializers import OrganizationUnitSerializer
from .tasks import expire_allocation_reservations_task
from .views import OrganizationUnitViewSet
from .supplier_delivery import supplier_outcome_redirect, supplier_outcome_signature


class VendorFoundationTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_superuser("vendor-owner", "owner@example.test", "test-password")
        self.internal = User.objects.create_user("internal-vendor", first_name="Internal")
        self.external = User.objects.create_user("external-vendor", first_name="External")
        self.employee = User.objects.create_user("ordinary-employee")
        EmployeeProfile.objects.filter(user=self.internal).update(
            account_type=EmployeeProfile.AccountType.INTERNAL_VENDOR,
            role=Role.objects.get(slug="admin"),
            created_by=self.owner,
        )
        EmployeeProfile.objects.filter(user=self.external).update(
            account_type=EmployeeProfile.AccountType.EXTERNAL_VENDOR,
            role=Role.objects.get(slug="external-vendor"),
            created_by=self.owner,
        )
        self.client_record = Client.objects.create(
            code="uat-client",
            name="UAT Client",
            provider_code="innovatemr",
            created_by=self.owner,
        )
        self.survey = Survey.objects.create(
            client=self.client_record,
            source_id=88001,
            name="Allocation test survey",
            status=Survey.Status.LIVE,
            remaining=20,
            cpi=Decimal("10.00"),
        )
        self.external_policy = VendorCommercialProfile.objects.create(
            vendor=self.external,
            default_cpi_cut_percent=Decimal("30.00"),
            created_by=self.owner,
        )
        self.external_client_allocation = VendorClientAllocation.objects.create(
            vendor=self.external,
            client=self.client_record,
            quantity_limit=5,
            created_by=self.owner,
        )
        self.external_survey_allocation = VendorSurveyAllocation.objects.create(
            client_allocation=self.external_client_allocation,
            survey=self.survey,
            quantity_limit=2,
            created_by=self.owner,
        )

    def attempt(self, rid, status=SurveyAttempt.Status.INITIATED):
        return SurveyAttempt.objects.create(
            rid=rid,
            survey=self.survey,
            platform_user=self.external,
            user_id=str(self.external.pk),
            status=status,
        )

    def test_hidden_biobrain_client_is_not_published_before_inventory(self):
        hidden = Client.objects.create(
            code="catalog-hidden-biobrain", name="BioBrain", provider_code="biobrain", is_active=False
        )
        integration = ClientIntegration.objects.create(
            client=hidden,
            name="Hidden BioBrain",
            provider_code="biobrain",
            base_url="https://partner-api.voqall.com/api/v1/surveys",
            credential_env_key="BIOBRAIN_API_KEY",
        )
        api = APIClient()
        api.force_authenticate(self.owner)
        response = api.get(reverse("vendor-client-list"))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(hidden.pk, [row["id"] for row in response.data["results"]])
        response = api.get(reverse("client-integration-list"))
        self.assertNotIn(integration.pk, [row["id"] for row in response.data["results"]])
        response = api.get(reverse("client-integration-providers"))
        self.assertNotIn("biobrain", [row["code"] for row in response.data])
        hidden.is_active = True
        hidden.save(update_fields=["is_active", "updated_at"])
        response = api.get(reverse("vendor-client-list"))
        self.assertIn(hidden.pk, [row["id"] for row in response.data["results"]])
        response = api.get(reverse("client-integration-list"))
        self.assertIn(integration.pk, [row["id"] for row in response.data["results"]])
        response = api.get(reverse("client-integration-providers"))
        self.assertIn("biobrain", [row["code"] for row in response.data])

    def test_external_cut_and_internal_full_cpi_rules(self):
        self.assertEqual(payable_cpi(Decimal("10.00"), Decimal("30.00")), Decimal("7.00"))
        self.assertEqual(self.external_survey_allocation.effective_cpi_cut_percent, Decimal("30.00"))

        internal_policy = VendorCommercialProfile(
            vendor=self.internal,
            default_cpi_cut_percent=Decimal("1.00"),
            created_by=self.owner,
        )
        with self.assertRaises(ValidationError):
            internal_policy.full_clean()

    def test_employee_role_can_show_a_configured_cpi_percentage(self):
        role = Role.objects.get(slug="team-lead")
        role.cpi_visibility_percent = Decimal("70.00")
        role.save(update_fields=["cpi_visibility_percent"])
        EmployeeProfile.objects.filter(user=self.employee).update(role=role)
        self.employee.employee_profile.refresh_from_db()

        visible_cpi, applied_cut = survey_pricing_for_user(self.employee, self.survey)

        self.assertEqual(visible_cpi, Decimal("7.00"))
        self.assertEqual(applied_cut, Decimal("30.00"))

    def test_manager_role_percentage_and_five_dollar_cap_use_one_policy(self):
        role = Role.objects.get(slug="manager")
        role.cpi_visibility_percent = Decimal("60.00")
        role.save(update_fields=["cpi_visibility_percent"])
        EmployeeProfile.objects.filter(user=self.employee).update(role=role)
        self.employee.employee_profile.refresh_from_db()

        visible_cpi, applied_cut = survey_pricing_for_user(self.employee, self.survey)

        self.assertEqual(visible_cpi, Decimal("5.00"))
        self.assertEqual(applied_cut, Decimal("50.00"))
        self.survey.cpi = Decimal("4.25")
        self.survey.save(update_fields=["cpi"])
        visible_cpi, applied_cut = survey_pricing_for_user(self.employee, self.survey)
        self.assertEqual(visible_cpi, Decimal("2.55"))
        self.assertEqual(applied_cut, Decimal("40.00"))

    def test_attempt_freezes_cpi_without_quantity_reservations(self):
        attempt = self.attempt("Ua1Bb2Cc3D")
        attributed = reserve_attempt_capacity(attempt, self.external_survey_allocation)
        self.assertEqual(attributed.pk, attempt.pk)
        attempt.refresh_from_db()
        self.assertEqual(attempt.vendor, self.external)
        self.assertEqual(attempt.client, self.client_record)
        self.assertEqual(attempt.source_cpi_snapshot, Decimal("10.00"))
        self.assertEqual(attempt.cpi_cut_percent_snapshot, Decimal("30.00"))
        self.assertEqual(attempt.payable_cpi_snapshot, Decimal("7.00"))

        self.survey.cpi = Decimal("6.00")
        self.survey.save(update_fields=["cpi"])
        attempt.status = SurveyAttempt.Status.COMPLETED
        attempt.save(update_fields=["status"])
        self.assertIsNone(finalize_attempt_capacity(attempt))
        attempt.refresh_from_db()
        self.assertEqual(attempt.payable_cpi_snapshot, Decimal("7.00"))
        self.external_client_allocation.refresh_from_db()
        self.external_survey_allocation.refresh_from_db()
        self.assertEqual(self.external_client_allocation.consumed_quantity, 0)
        self.assertEqual(self.external_survey_allocation.consumed_quantity, 0)
        self.assertIsNone(finalize_attempt_capacity(attempt))

        new_attempt = self.attempt("Ua9Mm8Nn7P")
        reserve_attempt_capacity(new_attempt, self.external_survey_allocation)
        new_attempt.refresh_from_db()
        attempt.refresh_from_db()
        self.assertEqual(attempt.payable_cpi_snapshot, Decimal("7.00"))
        self.assertEqual(new_attempt.source_cpi_snapshot, Decimal("6.00"))
        self.assertEqual(new_attempt.payable_cpi_snapshot, Decimal("4.20"))

    def test_supplier_quantity_fields_do_not_limit_delivery(self):
        attempt = self.attempt("Ua4Ee5Ff6G")
        reserve_attempt_capacity(attempt, self.external_survey_allocation)
        attempt.status = SurveyAttempt.Status.TERMINATED
        attempt.save(update_fields=["status"])
        self.assertIsNone(finalize_attempt_capacity(attempt))
        self.external_survey_allocation.refresh_from_db()
        self.assertEqual(self.external_survey_allocation.reserved_quantity, 0)

        self.external_survey_allocation.quantity_limit = 0
        self.external_survey_allocation.save(update_fields=["quantity_limit"])
        self.assertEqual(
            reserve_attempt_capacity(self.attempt("Ua7Hh8Ii9J"), self.external_survey_allocation).status,
            SurveyAttempt.Status.INITIATED,
        )

    def test_client_grant_exposes_all_projects_and_uses_shared_capacity(self):
        unallocated_survey = Survey.objects.create(
            client=self.client_record,
            source_id=88002,
            name="Client-level survey",
            status=Survey.Status.LIVE,
            remaining=10,
            cpi=Decimal("10.00"),
            entry_link="https://edgeapi.innovatemr.net/startSurvey?survNum=uat&supCode=1150&PID=[%%pid%%]",
            targeting_synced_at=timezone.now(),
        )
        hidden_client = Client.objects.create(code="hidden", name="Hidden client", created_by=self.owner)
        Survey.objects.create(
            client=hidden_client,
            source_id=88003,
            name="Hidden survey",
            status=Survey.Status.LIVE,
            remaining=10,
            cpi=Decimal("20.00"),
        )
        for code in ["projects.view", "survey_links.copy", "attempts.view"]:
            UserFunctionOverride.objects.create(
                user=self.external,
                function=AccessFunction.objects.get(code=code),
                effect=UserFunctionOverride.Effect.ALLOW,
            )

        api = APIClient()
        api.force_authenticate(self.external)
        listing = api.get(reverse("survey-list"))
        self.assertEqual(listing.status_code, 200)
        rows = {item["source_id"]: item for item in listing.data["results"]}
        self.assertEqual(set(rows), {88001, 88002})

        start = self.client.get(
            reverse("survey-start"),
            {
                "surveyId": unallocated_survey.source_id,
                "supplierCode": "1000",
                "userId": self.external.pk,
                "code": unallocated_survey.local_id,
            },
        )
        self.assertEqual(start.status_code, 302)
        created_attempt = SurveyAttempt.objects.get(survey=unallocated_survey)
        self.assertEqual(created_attempt.client_allocation, self.external_client_allocation)
        self.assertIsNone(created_attempt.survey_allocation)

        created_attempt.status = SurveyAttempt.Status.COMPLETED
        created_attempt.save(update_fields=["status"])
        finalize_attempt_capacity(created_attempt)
        self.external_client_allocation.refresh_from_db()
        self.assertEqual(self.external_client_allocation.consumed_quantity, 0)

    def test_superuser_can_manage_foundation_api_and_employee_cannot(self):
        owner_api = APIClient()
        owner_api.force_authenticate(self.owner)
        response = owner_api.post(reverse("vendor-client-list"), {
            "code": "second-client",
            "name": "Second Client",
            "provider_code": "custom",
        })
        self.assertEqual(response.status_code, 201)
        directory = owner_api.get(reverse("vendor-directory-list"))
        self.assertEqual(directory.status_code, 200)
        self.assertEqual(directory.data["count"], 1)

        employee_api = APIClient()
        employee_api.force_authenticate(self.employee)
        self.assertEqual(employee_api.get(reverse("vendor-client-list")).status_code, 403)

    def test_vendor_api_is_read_only_and_scoped_to_its_own_allocations(self):
        sibling = get_user_model().objects.create_user("sibling-vendor")
        EmployeeProfile.objects.filter(user=sibling).update(
            account_type=EmployeeProfile.AccountType.EXTERNAL_VENDOR,
            created_by=self.owner,
        )
        sibling_allocation = VendorClientAllocation.objects.create(
            vendor=sibling,
            client=self.client_record,
            quantity_limit=3,
            created_by=self.owner,
        )
        for code in ["clients.view", "vendors.view", "vendors.tab.clients"]:
            UserFunctionOverride.objects.create(
                user=self.external,
                function=AccessFunction.objects.get(code=code),
                effect=UserFunctionOverride.Effect.ALLOW,
            )

        api = APIClient()
        api.force_authenticate(self.external)
        listing = api.get(reverse("vendor-client-allocation-list"))
        self.assertEqual(listing.status_code, 200)
        self.assertEqual([item["id"] for item in listing.data["results"]], [self.external_client_allocation.id])
        self.assertEqual(
            api.get(reverse("vendor-client-allocation-detail", kwargs={"pk": sibling_allocation.pk})).status_code,
            404,
        )
        self.assertEqual(
            api.patch(
                reverse("vendor-client-allocation-detail", kwargs={"pk": self.external_client_allocation.pk}),
                {"quantity_limit": 99},
                format="json",
            ).status_code,
            403,
        )

    def test_legacy_reservation_cleanup_task_is_disabled(self):
        result = expire_allocation_reservations_task.run()
        self.assertEqual(result, {"expired": 0, "examined": 0, "disabled": True})

    def test_active_project_exclusion_hides_only_that_project(self):
        second = Survey.objects.create(
            client=self.client_record,
            source_id=88004,
            name="Client fallback survey",
            status=Survey.Status.LIVE,
            remaining=4,
            cpi=Decimal("4.00"),
        )
        self.external_survey_allocation.is_excluded = True
        self.external_survey_allocation.is_active = True
        self.external_survey_allocation.save(update_fields=["is_excluded", "is_active"])
        UserFunctionOverride.objects.create(
            user=self.external,
            function=AccessFunction.objects.get(code="projects.view"),
            effect=UserFunctionOverride.Effect.ALLOW,
        )
        api = APIClient()
        api.force_authenticate(self.external)
        ids = {row["source_id"] for row in api.get(reverse("survey-list")).data["results"]}
        self.assertEqual(ids, {88004})

    def test_external_client_cpi_range_filters_list_and_direct_start(self):
        self.external_client_allocation.min_cpi = Decimal("11.00")
        self.external_client_allocation.max_cpi = Decimal("20.00")
        self.external_client_allocation.save(update_fields=["min_cpi", "max_cpi"])
        UserFunctionOverride.objects.create(
            user=self.external,
            function=AccessFunction.objects.get(code="projects.view"),
            effect=UserFunctionOverride.Effect.ALLOW,
        )
        api = APIClient()
        api.force_authenticate(self.external)
        self.assertEqual(api.get(reverse("survey-list")).data["count"], 0)
        with self.assertRaisesMessage(AllocationUnavailable, "outside"):
            resolve_vendor_survey_context(self.external, self.survey)

    def test_allocation_manager_can_open_workspace_and_use_safe_options(self):
        for code in ("allocations.view", "vendors.tab.clients", "vendors.column.client.client"):
            UserFunctionOverride.objects.create(
                user=self.employee,
                function=AccessFunction.objects.get(code=code),
                effect=UserFunctionOverride.Effect.ALLOW,
            )
        self.client.force_login(self.employee)
        page = self.client.get(reverse("vendor-management"))
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, "Commercial policies")
        self.assertContains(page, "Client allocations")
        self.assertNotContains(page, "Project allocations")
        options = self.client.get(reverse("vendor-management-options"))
        self.assertEqual(options.status_code, 200)
        self.assertEqual(len(options.json()["vendors"]), 1)
        self.assertIn(self.client_record.pk, {item["id"] for item in options.json()["clients"]})
        self.assertEqual(self.client.get(reverse("vendor-survey-allocation-list")).status_code, 403)

    def test_vendor_management_uses_separate_task_modals(self):
        self.client.force_login(self.owner)
        page = self.client.get(reverse("vendor-management"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'id="vendorPolicyModal"')
        self.assertContains(page, 'id="clientAllocationModal"')
        self.assertContains(page, 'id="surveyAllocationModal"')
        self.assertContains(page, 'id="vendorApiKeyModal"')
        self.assertNotContains(page, 'id="vendorManagementForm"')
        script = (Path(settings.BASE_DIR) / "static" / "vendors" / "management.js").read_text(encoding="utf-8")
        self.assertIn("closest('button[data-edit-policy]')", script)
        self.assertNotIn("closest('[data-edit-policy]')", script)
        self.assertIn("closest('button[data-revoke-api-key]')", script)
        self.assertNotIn("closest('[data-revoke-api-key]')", script)

    def test_supplier_directory_hides_profiles_without_the_required_role(self):
        EmployeeProfile.objects.filter(user=self.internal).update(role=None)
        api = APIClient()
        api.force_authenticate(self.owner)

        directory = api.get(reverse("vendor-directory-list"))
        self.assertEqual(directory.status_code, 200)
        self.assertNotIn(self.internal.pk, [row["id"] for row in directory.data["results"]])
        options = api.get(reverse("vendor-management-options"))
        self.assertNotIn(self.internal.pk, [row["id"] for row in options.data["vendors"]])

    def test_directory_reports_average_effective_client_cut(self):
        second_client = Client.objects.create(
            code="average-cut-client", name="Average Cut Client", created_by=self.owner,
        )
        VendorClientAllocation.objects.create(
            vendor=self.external,
            client=second_client,
            quantity_limit=10,
            cpi_cut_override_percent=Decimal("50.00"),
            created_by=self.owner,
        )
        api = APIClient()
        api.force_authenticate(self.owner)
        response = api.get(reverse("vendor-directory-list"))
        row = next(item for item in response.data["results"] if item["id"] == self.external.pk)
        self.assertEqual(row["active_client_allocation_count"], 2)
        self.assertEqual(Decimal(row["average_client_cpi_cut_percent"]), Decimal("40.00"))

    def test_api_key_can_be_scoped_to_one_selected_client(self):
        self.external_policy.delivery_mode = VendorCommercialProfile.DeliveryMode.BOTH
        self.external_policy.save(update_fields=["delivery_mode", "updated_at"])
        second_client = Client.objects.create(
            code="key-scope-client", name="Key Scope Client", created_by=self.owner,
        )
        second_survey = Survey.objects.create(
            client=second_client,
            source_id=88007,
            name="Key scoped survey",
            status=Survey.Status.LIVE,
            remaining=5,
            cpi=Decimal("8.00"),
        )
        second_allocation = VendorClientAllocation.objects.create(
            vendor=self.external,
            client=second_client,
            quantity_limit=5,
            created_by=self.owner,
        )
        owner_api = APIClient()
        owner_api.force_authenticate(self.owner)
        issued = owner_api.post(reverse("vendor-api-key-list"), {
            "vendor": self.external.pk,
            "name": "One client only",
            "client_allocations": [second_allocation.pk],
        }, format="json")
        self.assertEqual(issued.status_code, 201)
        self.assertEqual(issued.data["client_names"], [second_client.name])

        listing = APIClient().get(reverse("survey-list"), HTTP_X_API_KEY=issued.data["api_key"])
        self.assertEqual(listing.status_code, 200)
        self.assertEqual([row["source_id"] for row in listing.data["results"]], [second_survey.source_id])

        allocation_detail = owner_api.get(
            reverse("vendor-client-allocation-detail", kwargs={"pk": second_allocation.pk})
        )
        self.assertEqual(allocation_detail.data["api_key_scopes"][0]["name"], "One client only")

    def test_api_key_inherits_live_client_scope_and_different_client_cuts(self):
        self.external_policy.delivery_mode = VendorCommercialProfile.DeliveryMode.BOTH
        self.external_policy.save(update_fields=["delivery_mode", "updated_at"])
        second_client = Client.objects.create(
            code="second-cut-client", name="Second Cut Client", provider_code="custom", created_by=self.owner,
        )
        second_survey = Survey.objects.create(
            client=second_client,
            source_id=88005,
            name="Fifty percent survey",
            status=Survey.Status.LIVE,
            remaining=9,
            cpi=Decimal("10.00"),
        )
        second_client_allocation = VendorClientAllocation.objects.create(
            vendor=self.external,
            client=second_client,
            quantity_limit=4,
            cpi_cut_override_percent=Decimal("50.00"),
            created_by=self.owner,
        )
        VendorSurveyAllocation.objects.create(
            client_allocation=second_client_allocation,
            survey=second_survey,
            quantity_limit=4,
            created_by=self.owner,
        )
        hidden_client = Client.objects.create(code="api-hidden", name="API Hidden", created_by=self.owner)
        Survey.objects.create(
            client=hidden_client,
            source_id=88006,
            name="Not allocated",
            status=Survey.Status.LIVE,
            remaining=5,
            cpi=Decimal("99.00"),
        )

        owner_api = APIClient()
        owner_api.force_authenticate(self.owner)
        issued = owner_api.post(reverse("vendor-api-key-list"), {
            "vendor": self.external.pk,
            "name": "UAT integration",
            "client_allocations": [self.external_client_allocation.pk, second_client_allocation.pk],
        }, format="json")
        self.assertEqual(issued.status_code, 201)
        raw_key = issued.data["api_key"]
        self.assertTrue(raw_key.startswith("exh_"))
        self.assertFalse(VendorAPIKey.objects.get(pk=issued.data["id"]).key_hash == raw_key)

        vendor_api = APIClient()
        listing = vendor_api.get(reverse("survey-list"), HTTP_X_API_KEY=raw_key)
        self.assertEqual(listing.status_code, 200)
        rows = {item["source_id"]: item for item in listing.data["results"]}
        self.assertEqual(set(rows), {self.survey.source_id, second_survey.source_id})
        self.assertEqual(Decimal(rows[self.survey.source_id]["cpi"]), Decimal("7.00"))
        self.assertEqual(Decimal(rows[self.survey.source_id]["cpi_cut_percent"]), Decimal("30.00"))
        self.assertEqual(Decimal(rows[second_survey.source_id]["cpi"]), Decimal("5.00"))
        self.assertEqual(Decimal(rows[second_survey.source_id]["cpi_cut_percent"]), Decimal("50.00"))
        self.assertEqual(rows[second_survey.source_id]["display_company_name"], second_client.name)
        client_catalog = vendor_api.get(reverse("supplier-client-catalog"), HTTP_X_API_KEY=raw_key)
        self.assertEqual(client_catalog.status_code, 200)
        self.assertEqual(client_catalog.data["supplier_id"], self.external_policy.supplier_code)
        self.assertEqual(
            {row["name"] for row in client_catalog.data["clients"]},
            {self.client_record.name, second_client.name},
        )
        self.assertEqual(rows[self.survey.source_id]["survey_id"], self.survey.local_id)
        self.assertEqual(rows[self.survey.source_id]["supplier_id"], self.external_policy.supplier_code)
        self.assertEqual(rows[second_survey.source_id]["supplier_id"], self.external_policy.supplier_code)
        self.assertIn("/supplier/start?", rows[self.survey.source_id]["entry_link"])
        self.assertNotIn("edgeapi.innovatemr.net", rows[self.survey.source_id]["entry_link"])

        self.external_policy.survey_id_mode = VendorCommercialProfile.SurveyIdMode.SOURCE_ID
        self.external_policy.save(update_fields=["survey_id_mode", "updated_at"])
        source_mode = vendor_api.get(reverse("survey-list"), HTTP_X_API_KEY=raw_key)
        source_rows = {item["source_id"]: item for item in source_mode.data["results"]}
        self.assertEqual(source_rows[self.survey.source_id]["survey_id"], str(self.survey.source_identifier))

        filtered = vendor_api.get(reverse("survey-list"), {"client_name": second_client.name}, HTTP_X_API_KEY=raw_key)
        self.assertEqual([row["source_id"] for row in filtered.data["results"]], [second_survey.source_id])
        UserFunctionOverride.objects.create(
            user=self.external,
            function=AccessFunction.objects.get(code="projects.filter.cpi"),
            effect=UserFunctionOverride.Effect.ALLOW,
        )
        visible_cpi_filtered = vendor_api.get(
            reverse("survey-list"),
            {"min_cpi": "5.50", "max_cpi": "7.50", "ordering": "-cpi"},
            HTTP_X_API_KEY=raw_key,
        )
        self.assertEqual(visible_cpi_filtered.status_code, 200)
        self.assertEqual(
            [row["source_id"] for row in visible_cpi_filtered.data["results"]],
            [self.survey.source_id],
        )
        key_record = VendorAPIKey.objects.get(pk=issued.data["id"])
        self.assertIsNotNone(key_record.last_used_at)

        key_list = owner_api.get(reverse("vendor-api-key-list"))
        self.assertEqual(key_list.status_code, 200)
        self.assertNotIn("api_key", key_list.data["results"][0])
        self.assertEqual(
            owner_api.delete(reverse("vendor-api-key-detail", kwargs={"pk": key_record.pk})).status_code,
            204,
        )
        self.assertIn(
            vendor_api.get(reverse("survey-list"), HTTP_X_API_KEY=raw_key).status_code,
            {401, 403},
        )

    def test_supplier_entry_and_signed_outcome_redirect_forward_term_reason(self):
        self.external_policy.delivery_mode = VendorCommercialProfile.DeliveryMode.BOTH
        self.external_policy.save(update_fields=["delivery_mode", "updated_at"])
        self.survey.entry_link = "https://edgeapi.innovatemr.net/startSurvey?PID=[%%pid%%]"
        self.survey.save(update_fields=["entry_link"])
        self.external_client_allocation.complete_redirect_url = "https://supplier.example/complete?campaign=alpha"
        self.external_client_allocation.terminate_redirect_url = (
            "https://supplier.example/terminate?status=legacy&rid=[%%pid%%]"
            "&survey=[%%survey_id%%]&reason=[%%termreason%%]"
        )
        self.external_client_allocation.save(update_fields=["complete_redirect_url", "terminate_redirect_url"])

        owner_api = APIClient()
        owner_api.force_authenticate(self.owner)
        policy = owner_api.patch(
            reverse("vendor-commercial-profile-detail", kwargs={"pk": self.external_policy.pk}),
            {"callback_hash_enabled": True, "generate_callback_hash_secret": True},
            format="json",
        )
        self.assertEqual(policy.status_code, 200)
        raw_hash_key = policy.data["callback_hash_secret"]
        issued = owner_api.post(reverse("vendor-api-key-list"), {
            "vendor": self.external.pk,
            "name": "Supplier delivery",
            "client_allocations": [self.external_client_allocation.pk],
        }, format="json")
        self.assertEqual(issued.status_code, 201)
        catalog = APIClient().get(reverse("survey-list"), HTTP_X_API_KEY=issued.data["api_key"])
        entry_link = catalog.data["results"][0]["supplier_entry_link"]
        parts = urlsplit(entry_link.replace("[%%pid%%]", "SUPPLIER-RID-42"))
        started = self.client.get(f"{parts.path}?{parts.query}")
        self.assertEqual(started.status_code, 302)
        attempt = SurveyAttempt.objects.get(supplier_respondent_id="SUPPLIER-RID-42")
        self.assertEqual(attempt.vendor, self.external)
        self.assertEqual(attempt.client_allocation, self.external_client_allocation)

        attempt.status = SurveyAttempt.Status.TERMINATED
        attempt.status_source = "innovatemr_redirect_hash"
        attempt.is_verified = True
        attempt.upstream_transaction_data = {"transaction": {"termReason": "Age quota closed"}}
        attempt.save(update_fields=["status", "status_source", "is_verified", "upstream_transaction_data"])
        redirect_url = supplier_outcome_redirect(attempt)
        query = parse_qs(urlsplit(redirect_url).query)
        self.assertEqual(query["pid"], ["SUPPLIER-RID-42"])
        self.assertEqual(query["status"], [SurveyAttempt.Status.TERMINATED])
        self.assertEqual(query["rid"], ["SUPPLIER-RID-42"])
        self.assertEqual(query["survey"], [self.survey.local_id])
        self.assertEqual(query["reason"], ["Age quota closed"])
        self.assertEqual(query["survey_id"], [self.survey.local_id])
        self.assertEqual(query["term_reason"], ["Age quota closed"])
        self.assertEqual(query["hash"], [supplier_outcome_signature(
            raw_hash_key,
            pid="SUPPLIER-RID-42",
            status=SurveyAttempt.Status.TERMINATED,
            survey_id=self.survey.local_id,
            term_reason="Age quota closed",
        )])

    def test_supplier_entry_hydrates_pending_targeting_before_creating_attempt(self):
        integration = ClientIntegration.objects.create(
            client=self.client_record,
            name="Supplier targeting sync",
            provider_code="innovatemr",
            base_url="https://example.test",
        )
        self.survey.integration = integration
        self.survey.entry_link = "https://edgeapi.innovatemr.net/startSurvey?PID=[%%pid%%]"
        self.survey.targeting_synced_at = None
        self.survey.save(update_fields=["integration", "entry_link", "targeting_synced_at"])
        self.external_policy.delivery_mode = VendorCommercialProfile.DeliveryMode.BOTH
        self.external_policy.save(update_fields=["delivery_mode", "updated_at"])

        owner_api = APIClient()
        owner_api.force_authenticate(self.owner)
        issued = owner_api.post(reverse("vendor-api-key-list"), {
            "vendor": self.external.pk,
            "name": "Pending targeting delivery",
            "client_allocations": [self.external_client_allocation.pk],
        }, format="json")
        catalog = APIClient().get(
            reverse("survey-list"), HTTP_X_API_KEY=issued.data["api_key"]
        )
        entry_link = catalog.data["results"][0]["supplier_entry_link"]
        parts = urlsplit(entry_link.replace("[%%pid%%]", "PENDING-TARGETING-1"))

        def hydrate(_client, survey):
            TargetingQuestion.objects.create(
                survey=survey,
                question_id=1,
                key="AGE",
                text="What is your age?",
                question_type="Numeric",
            )
            survey.targeting_synced_at = timezone.now()
            survey.save(update_fields=["targeting_synced_at", "updated_at"])

        client = Mock()
        with (
            patch("surveys.views.InnovateMRClient", return_value=client),
            patch("surveys.views.replace_survey_targeting", side_effect=hydrate) as refresh,
        ):
            started = self.client.get(f"{parts.path}?{parts.query}")

        self.assertEqual(started.status_code, 302)
        refresh.assert_called_once()
        attempt = SurveyAttempt.objects.get(
            supplier_respondent_id="PENDING-TARGETING-1"
        )
        form = self.client.get(started["Location"])
        self.assertContains(form, "What is your age?")
        self.assertEqual(attempt.survey.targeting_questions.count(), 1)

    def test_delivery_mode_blocks_wrong_channel(self):
        owner_api = APIClient()
        owner_api.force_authenticate(self.owner)
        panel_only_key = owner_api.post(reverse("vendor-api-key-list"), {
            "vendor": self.external.pk,
            "name": "Blocked panel-only key",
        }, format="json")
        self.assertEqual(panel_only_key.status_code, 400)

        self.external_policy.delivery_mode = VendorCommercialProfile.DeliveryMode.API
        self.external_policy.save(update_fields=["delivery_mode", "updated_at"])
        self.external.set_password("password-123")
        self.external.save(update_fields=["password"])
        login = self.client.post(reverse("login"), {
            "username": self.external.username,
            "password": "password-123",
        })
        self.assertEqual(login.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(login, "Username or password is incorrect")

        issued = owner_api.post(reverse("vendor-api-key-list"), {
            "vendor": self.external.pk,
            "name": "API-only integration",
            "client_allocations": [self.external_client_allocation.pk],
        }, format="json")
        self.assertEqual(issued.status_code, 201)
        self.assertEqual(
            APIClient().get(reverse("survey-list"), HTTP_X_API_KEY=issued.data["api_key"]).status_code,
            200,
        )

    def test_vendor_scoped_admin_cannot_manage_owner_api_keys(self):
        for code in ("vendors.tab.api_keys", "vendors.action.create_api_key"):
            UserFunctionOverride.objects.create(
                user=self.internal,
                function=AccessFunction.objects.get(code=code),
                effect=UserFunctionOverride.Effect.ALLOW,
            )
        internal_api = APIClient()
        internal_api.force_authenticate(self.internal)
        listing = internal_api.get(reverse("vendor-api-key-list"))
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.data["count"], 0)
        response = internal_api.post(reverse("vendor-api-key-list"), {
            "vendor": self.external.pk,
            "name": "Forbidden delegated key",
        }, format="json")
        self.assertEqual(response.status_code, 403)


class OrganizationHierarchyTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_superuser("organization-owner", "org-owner@example.test", "test-password")
        self.internal = User.objects.create_user("organization-internal", first_name="Internal", last_name="Vendor")
        EmployeeProfile.objects.filter(user=self.internal).update(
            account_type=EmployeeProfile.AccountType.INTERNAL_VENDOR,
            role=Role.objects.get(slug="admin"),
            created_by=self.owner,
        )
        VendorCommercialProfile.objects.create(vendor=self.internal, created_by=self.owner)
        self.client_a = Client.objects.create(code="client-a", name="Client A", created_by=self.owner)
        self.client_b = Client.objects.create(code="client-b", name="Client B", created_by=self.owner)
        self.survey_a = Survey.objects.create(
            client=self.client_a, source_id=99001, name="Client A survey", status=Survey.Status.LIVE,
            remaining=10, cpi=Decimal("3.00"),
        )
        self.survey_b = Survey.objects.create(
            client=self.client_b, source_id=99002, name="Client B survey", status=Survey.Status.LIVE,
            remaining=10, cpi=Decimal("4.00"),
        )
        self.owner_api = APIClient()
        self.owner_api.force_authenticate(self.owner)

    def create_tree(self, owner, prefix):
        branch = OrganizationUnit.objects.create(
            workspace_owner=owner, unit_type=OrganizationUnit.UnitType.BRANCH,
            name=f"{prefix} Branch", code=f"{prefix}-branch", created_by=self.owner,
        )
        sub_branch = OrganizationUnit.objects.create(
            workspace_owner=owner, parent=branch, unit_type=OrganizationUnit.UnitType.SUB_BRANCH,
            name="Operations", code="operations", created_by=self.owner,
        )
        shift = OrganizationUnit.objects.create(
            workspace_owner=owner, parent=sub_branch, unit_type=OrganizationUnit.UnitType.SHIFT,
            name="Morning", code="morning", created_by=self.owner,
        )
        return branch, sub_branch, shift

    def test_view_queryset_prefetches_complete_unit_paths(self):
        self.create_tree(self.owner, "query-path")
        view = OrganizationUnitViewSet()
        view.request = SimpleNamespace(user=self.owner)
        units = list(view.get_queryset().order_by("pk"))

        with CaptureQueriesContext(connection) as queries:
            data = OrganizationUnitSerializer(
                units,
                many=True,
                context={"organization_rollup_counts": {}},
            ).data

        self.assertEqual(len(data), 3)
        self.assertEqual(len(queries), 0)

    def test_owner_can_build_strict_tree_and_internal_vendor_is_scoped(self):
        branch = self.owner_api.post(reverse("organization-unit-list"), {
            "workspace_owner": self.internal.pk,
            "unit_type": "branch",
            "name": "Gurgaon",
            "code": "gurgaon",
            "is_active": True,
        }, format="json")
        self.assertEqual(branch.status_code, 201)
        sub_branch = self.owner_api.post(reverse("organization-unit-list"), {
            "workspace_owner": self.internal.pk,
            "parent": branch.data["id"],
            "unit_type": "sub_branch",
            "name": "Operations",
            "code": "operations",
            "is_active": True,
        }, format="json")
        self.assertEqual(sub_branch.status_code, 201)
        invalid_shift = self.owner_api.post(reverse("organization-unit-list"), {
            "workspace_owner": self.internal.pk,
            "parent": branch.data["id"],
            "unit_type": "shift",
            "name": "Invalid",
            "code": "invalid",
        }, format="json")
        self.assertEqual(invalid_shift.status_code, 400)
        shift = self.owner_api.post(reverse("organization-unit-list"), {
            "workspace_owner": self.internal.pk,
            "parent": sub_branch.data["id"],
            "unit_type": "shift",
            "name": "Morning",
            "code": "morning",
        }, format="json")
        self.assertEqual(shift.status_code, 201)

        internal_api = APIClient()
        internal_api.force_authenticate(self.internal)
        listing = internal_api.get(reverse("organization-unit-list"))
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.data["count"], 3)
        self.assertTrue(all(row["workspace_owner"] == self.internal.pk for row in listing.data["results"]))
        self.client.force_login(self.internal)
        page = self.client.get(reverse("organization-management"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Organization hierarchy")

    def test_unit_client_grants_filter_main_office_projects(self):
        branch, _, shift = self.create_tree(self.owner, "main")
        OrganizationClientAccess.objects.create(
            organization_unit=branch, client=self.client_a, created_by=self.owner,
        )
        employee = get_user_model().objects.create_user("main-shift-employee")
        EmployeeProfile.objects.filter(user=employee).update(
            organization_unit=shift,
            created_by=self.owner,
            role=Role.objects.get(slug="employee"),
        )
        api = APIClient()
        api.force_authenticate(employee)
        response = api.get(reverse("survey-list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual({row["source_id"] for row in response.data["results"]}, {self.survey_a.source_id})
        with self.assertRaisesMessage(AllocationUnavailable, "not assigned"):
            resolve_vendor_survey_context(employee, self.survey_b)

    def test_superuser_remains_unscoped_when_assigned_to_an_organization_unit(self):
        branch, _, _ = self.create_tree(self.owner, "owner")
        EmployeeProfile.objects.filter(user=self.owner).update(organization_unit=branch)

        response = self.owner_api.get(reverse("survey-list"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {row["source_id"] for row in response.data["results"]},
            {self.survey_a.source_id, self.survey_b.source_id},
        )

    def test_shift_client_grants_override_broader_branch_grants(self):
        branch, _, shift = self.create_tree(self.owner, "shift-override")
        OrganizationClientAccess.objects.bulk_create([
            OrganizationClientAccess(
                organization_unit=branch, client=self.client_a, created_by=self.owner,
            ),
            OrganizationClientAccess(
                organization_unit=branch, client=self.client_b, created_by=self.owner,
            ),
            OrganizationClientAccess(
                organization_unit=shift, client=self.client_b, is_active=False, created_by=self.owner,
            ),
        ])
        employee = get_user_model().objects.create_user("shift-override-employee")
        EmployeeProfile.objects.filter(user=employee).update(
            organization_unit=shift,
            created_by=self.owner,
            role=Role.objects.get(slug="employee"),
        )
        api = APIClient()
        api.force_authenticate(employee)

        response = api.get(reverse("survey-list"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {row["source_id"] for row in response.data["results"]},
            {self.survey_a.source_id},
        )
        with self.assertRaisesMessage(AllocationUnavailable, "not assigned"):
            resolve_vendor_survey_context(employee, self.survey_b)

    def test_child_inherits_parent_cpi_range_and_can_override_it(self):
        branch, sub_branch, shift = self.create_tree(self.owner, "cpi-policy")
        OrganizationClientAccess.objects.create(
            organization_unit=branch,
            client=self.client_a,
            min_cpi=Decimal("2.00"),
            max_cpi=Decimal("3.50"),
            created_by=self.owner,
        )
        employee = get_user_model().objects.create_user("cpi-policy-employee")
        EmployeeProfile.objects.filter(user=employee).update(
            organization_unit=shift,
            created_by=self.owner,
            role=Role.objects.get(slug="employee"),
        )
        api = APIClient()
        api.force_authenticate(employee)
        self.assertEqual(
            {row["source_id"] for row in api.get(reverse("survey-list")).data["results"]},
            {self.survey_a.source_id},
        )

        sub_policy = OrganizationClientAccess.objects.create(
            organization_unit=sub_branch,
            client=self.client_a,
            created_by=self.owner,
        )
        OrganizationClientAccess.objects.create(
            organization_unit=shift,
            client=self.client_a,
            created_by=self.owner,
        )
        employee = get_user_model().objects.get(pk=employee.pk)
        api.force_authenticate(employee)
        self.assertEqual(
            {row["source_id"] for row in api.get(reverse("survey-list")).data["results"]},
            {self.survey_a.source_id},
        )

        sub_policy.min_cpi = Decimal("4.00")
        sub_policy.max_cpi = Decimal("8.00")
        sub_policy.inherit_cpi_range = False
        sub_policy.save(update_fields=["min_cpi", "max_cpi", "inherit_cpi_range", "updated_at"])
        employee = get_user_model().objects.get(pk=employee.pk)
        api.force_authenticate(employee)
        self.assertEqual(api.get(reverse("survey-list")).data["count"], 0)
        with self.assertRaisesMessage(AllocationUnavailable, "outside"):
            resolve_vendor_survey_context(employee, self.survey_a)

    def test_shift_members_and_clients_roll_up_to_parent_totals(self):
        branch, sub_branch, shift = self.create_tree(self.owner, "rollup")
        OrganizationClientAccess.objects.create(
            organization_unit=shift, client=self.client_a, created_by=self.owner,
        )
        for index in range(2):
            employee = get_user_model().objects.create_user(f"rollup-employee-{index}")
            EmployeeProfile.objects.filter(user=employee).update(
                organization_unit=shift,
                created_by=self.owner,
                role=Role.objects.get(slug="employee"),
            )

        response = self.owner_api.get(reverse("organization-unit-list"))

        self.assertEqual(response.status_code, 200)
        units = {row["id"]: row for row in response.data["results"]}
        for unit in (branch, sub_branch, shift):
            self.assertEqual(units[unit.pk]["member_count"], 2)
            self.assertEqual(units[unit.pk]["client_count"], 1)
        self.assertEqual(units[branch.pk]["direct_member_count"], 0)
        self.assertEqual(units[branch.pk]["direct_client_count"], 0)
        self.assertEqual(units[shift.pk]["direct_member_count"], 2)
        self.assertEqual(units[shift.pk]["direct_client_count"], 1)

    def test_branch_client_is_counted_as_inherited_for_every_child(self):
        branch, sub_branch, shift = self.create_tree(self.owner, "inherited-count")
        OrganizationClientAccess.objects.create(
            organization_unit=branch, client=self.client_a, created_by=self.owner,
        )
        response = self.owner_api.get(reverse("organization-unit-list"))
        units = {row["id"]: row for row in response.data["results"]}
        for unit in (branch, sub_branch, shift):
            self.assertEqual(units[unit.pk]["client_count"], 1)
        self.assertEqual(units[branch.pk]["direct_client_count"], 1)
        self.assertEqual(units[sub_branch.pk]["direct_client_count"], 0)
        self.assertEqual(units[shift.pk]["direct_client_count"], 0)

    def test_user_creation_assigns_team_leads_and_employees_to_shifts(self):
        branch, _, shift = self.create_tree(self.owner, "people")
        invalid = self.owner_api.post(reverse("access-user-list"), {
            "first_name": "Invalid", "last_name": "Lead", "email": "invalid-lead@example.test",
            "password": "password-123", "role": "team-lead", "account_type": "employee",
            "organization_unit": branch.pk, "allow_codes": [], "deny_codes": [],
        }, format="json")
        self.assertEqual(invalid.status_code, 400)
        created = self.owner_api.post(reverse("access-user-list"), {
            "first_name": "Morning", "last_name": "Lead", "email": "morning-lead@example.test",
            "password": "password-123", "role": "team-lead", "account_type": "employee",
            "organization_unit": shift.pk, "allow_codes": [], "deny_codes": [],
        }, format="json")
        self.assertEqual(created.status_code, 201)
        lead = get_user_model().objects.get(email="morning-lead@example.test")
        self.assertEqual(lead.employee_profile.organization_unit, shift)
        self.assertEqual(created.data["organization_unit_details"]["path"], "people Branch / Operations / Morning")

    def test_internal_vendor_unit_grants_intersect_vendor_allocations(self):
        allocation_a = VendorClientAllocation.objects.create(
            vendor=self.internal, client=self.client_a, quantity_limit=10, created_by=self.owner,
        )
        allocation_b = VendorClientAllocation.objects.create(
            vendor=self.internal, client=self.client_b, quantity_limit=10, created_by=self.owner,
        )
        VendorSurveyAllocation.objects.create(
            client_allocation=allocation_a, survey=self.survey_a, quantity_limit=10, created_by=self.owner,
        )
        VendorSurveyAllocation.objects.create(
            client_allocation=allocation_b, survey=self.survey_b, quantity_limit=10, created_by=self.owner,
        )
        branch, _, shift = self.create_tree(self.internal, "internal")
        OrganizationClientAccess.objects.create(
            organization_unit=branch, client=self.client_a, created_by=self.owner,
        )
        employee = get_user_model().objects.create_user("internal-shift-employee")
        EmployeeProfile.objects.filter(user=employee).update(
            organization_unit=shift,
            created_by=self.owner,
            role=Role.objects.get(slug="employee"),
        )
        api = APIClient()
        api.force_authenticate(employee)
        response = api.get(reverse("survey-list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual({row["source_id"] for row in response.data["results"]}, {self.survey_a.source_id})

        unallocated_client = Client.objects.create(code="not-allocated", name="Not Allocated", created_by=self.owner)
        rejected = self.owner_api.post(reverse("organization-client-access-list"), {
            "organization_unit": branch.pk,
            "client": unallocated_client.pk,
            "is_active": True,
        }, format="json")
        self.assertEqual(rejected.status_code, 400)

    def test_existing_tree_cannot_be_reparented_into_a_cycle(self):
        branch, sub_branch, _ = self.create_tree(self.owner, "cycle")
        response = self.owner_api.patch(reverse("organization-unit-detail", args=[branch.pk]), {
            "unit_type": OrganizationUnit.UnitType.SHIFT,
            "parent": sub_branch.pk,
        }, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("parent", response.data)

    def test_existing_branch_can_be_corrected_to_sub_branch_under_another_branch(self):
        destination = OrganizationUnit.objects.create(
            workspace_owner=self.owner, unit_type=OrganizationUnit.UnitType.BRANCH,
            name="Destination", code="destination", created_by=self.owner,
        )
        mistaken = OrganizationUnit.objects.create(
            workspace_owner=self.owner, unit_type=OrganizationUnit.UnitType.BRANCH,
            name="Mistaken Branch", code="mistaken-branch", created_by=self.owner,
        )
        response = self.owner_api.patch(reverse("organization-unit-detail", args=[mistaken.pk]), {
            "unit_type": OrganizationUnit.UnitType.SUB_BRANCH,
            "parent": destination.pk,
            "name": "Corrected Sub-branch",
        }, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        mistaken.refresh_from_db()
        self.assertEqual(mistaken.unit_type, OrganizationUnit.UnitType.SUB_BRANCH)
        self.assertEqual(mistaken.parent, destination)
        self.assertEqual(mistaken.name, "Corrected Sub-branch")

    def test_unused_unit_deletes_and_parent_with_children_returns_conflict(self):
        unused = OrganizationUnit.objects.create(
            workspace_owner=self.owner, unit_type=OrganizationUnit.UnitType.BRANCH,
            name="Unused", code="unused", created_by=self.owner,
        )
        deleted = self.owner_api.delete(reverse("organization-unit-detail", args=[unused.pk]))
        self.assertEqual(deleted.status_code, 204)
        self.assertFalse(OrganizationUnit.objects.filter(pk=unused.pk).exists())

        branch, _, _ = self.create_tree(self.owner, "protected")
        protected = self.owner_api.delete(reverse("organization-unit-detail", args=[branch.pk]))
        self.assertEqual(protected.status_code, 409)
        self.assertIn("child units", protected.data["detail"])

    def test_client_access_can_be_removed_before_deleting_unit(self):
        branch = OrganizationUnit.objects.create(
            workspace_owner=self.owner, unit_type=OrganizationUnit.UnitType.BRANCH,
            name="Client Branch", code="client-branch", created_by=self.owner,
        )
        grant = OrganizationClientAccess.objects.create(
            organization_unit=branch, client=self.client_a, created_by=self.owner,
        )
        blocked = self.owner_api.delete(reverse("organization-unit-detail", args=[branch.pk]))
        self.assertEqual(blocked.status_code, 409)
        removed = self.owner_api.delete(reverse("organization-client-access-detail", args=[grant.pk]))
        self.assertEqual(removed.status_code, 204)
        self.assertFalse(OrganizationClientAccess.objects.filter(pk=grant.pk).exists())
        deleted = self.owner_api.delete(reverse("organization-unit-detail", args=[branch.pk]))
        self.assertEqual(deleted.status_code, 204)

    def test_user_cannot_be_assigned_below_an_inactive_ancestor(self):
        branch, _, shift = self.create_tree(self.owner, "inactive")
        branch.is_active = False
        branch.save(update_fields=["is_active", "updated_at"])
        response = self.owner_api.post(reverse("access-user-list"), {
            "first_name": "Blocked", "last_name": "Employee", "email": "blocked@example.test",
            "password": "password-123", "role": "employee", "account_type": "employee",
            "organization_unit": shift.pk, "allow_codes": [], "deny_codes": [],
        }, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("organization_unit", response.data)

    def test_external_vendor_cannot_receive_organization_access_by_override(self):
        external = get_user_model().objects.create_user("organization-external")
        EmployeeProfile.objects.filter(user=external).update(
            account_type=EmployeeProfile.AccountType.EXTERNAL_VENDOR,
            role=Role.objects.get(slug="external-vendor"),
            created_by=self.owner,
        )
        function = AccessFunction.objects.get(code="organization.view")
        UserFunctionOverride.objects.create(
            user=external,
            function=function,
            effect=UserFunctionOverride.Effect.ALLOW,
        )
        external_api = APIClient()
        external_api.force_authenticate(external)
        response = external_api.get(reverse("organization-unit-list"))
        self.assertEqual(response.status_code, 403)

    def test_internal_vendor_organization_options_do_not_expose_unallocated_clients(self):
        VendorClientAllocation.objects.create(
            vendor=self.internal,
            client=self.client_a,
            quantity_limit=10,
            created_by=self.owner,
        )
        internal_api = APIClient()
        internal_api.force_authenticate(self.internal)
        response = internal_api.get(reverse("organization-options"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual({row["id"] for row in response.data["clients"]}, {self.client_a.pk})
        self.assertEqual(response.data["client_eligibility"][str(self.internal.pk)], [self.client_a.pk])
