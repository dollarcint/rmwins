from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import EmployeeProfile, Role
from vendors.models import Client, VendorClientAllocation, VendorCommercialProfile
from vendors.services import reserve_attempt_capacity, resolve_vendor_survey_context

from .forms import ManualSurveyForm, prepare_manual_entry_link
from .models import Survey, SurveyAttempt
from .survey_flow import build_outbound_url, create_attempt


class ManualSurveyFormTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_superuser(
            "manual-owner", "owner@example.test", "test-password"
        )
        self.client_record = Client.objects.create(
            code="manual-buyer",
            name="Manual Buyer",
            provider_code="custom",
            created_by=self.owner,
        )
        self.payload = {
            "client": self.client_record.pk,
            "source_key": "BUYER-9001",
            "name": "Manual consumer survey",
            "entry_link": "https://client.example/start?campaign=summer&pid=old",
            "rid_parameter": "respondent_id",
            "cpi": "10.00",
            "sample_size": "125",
            "loi": "12",
            "incidence_rate": "35.50",
            "country": "United States",
            "country_code": "us",
            "language": "English",
            "language_code": "en",
            "buyer_id": "BRAND-42",
            "survey_type": "B2C",
            "device_type": "All",
        }

    def test_form_creates_manual_inventory_and_canonical_rid_template(self):
        form = ManualSurveyForm(self.payload)
        self.assertTrue(form.is_valid(), form.errors)

        survey = form.save(created_by=self.owner)

        self.assertEqual(survey.inventory_source, Survey.InventorySource.MANUAL)
        self.assertIsNone(survey.integration)
        self.assertIsNone(survey.source_id)
        self.assertEqual(survey.source_key, "BUYER-9001")
        self.assertEqual(survey.company_name, "Manual Buyer")
        self.assertEqual(survey.manual_rid_parameter, "respondent_id")
        self.assertEqual(survey.remaining, 125)
        self.assertEqual(survey.sample_size, 125)
        self.assertEqual(survey.country_code, "US")
        self.assertEqual(survey.language_code, "EN")
        self.assertEqual(len(survey.local_id), 14)
        params = parse_qs(urlsplit(survey.entry_link).query)
        self.assertEqual(params["campaign"], ["summer"])
        self.assertEqual(params["respondent_id"], ["[%%rid%%]"])
        self.assertEqual(params["pid"], ["old"])

    def test_form_rejects_duplicate_client_survey_id_and_non_https_link(self):
        first = ManualSurveyForm(self.payload)
        self.assertTrue(first.is_valid(), first.errors)
        first.save(created_by=self.owner)

        duplicate = ManualSurveyForm(self.payload)
        self.assertFalse(duplicate.is_valid())
        self.assertIn("already exists", duplicate.errors["source_key"][0])

        invalid_payload = {**self.payload, "source_key": "BUYER-9002", "entry_link": "http://client.example/start"}
        invalid = ManualSurveyForm(invalid_payload)
        self.assertFalse(invalid.is_valid())
        self.assertIn("HTTPS", invalid.errors["entry_link"][0])

    def test_prepare_link_replaces_duplicate_target_parameter_once(self):
        prepared = prepare_manual_entry_link(
            "https://client.example/start?rid=one&campaign=9&RID=two", "rid"
        )
        params = parse_qs(urlsplit(prepared).query)
        self.assertEqual(params["campaign"], ["9"])
        self.assertEqual(params["rid"], ["[%%rid%%]"])


class ManualSurveyPageTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_superuser(
            "manual-admin", "admin@example.test", "test-password"
        )
        self.employee = get_user_model().objects.create_user(
            "manual-employee", password="test-password"
        )
        self.client_record = Client.objects.create(
            code="page-manual", name="Page Manual Client", provider_code="custom"
        )
        self.payload = {
            "client": self.client_record.pk,
            "source_key": "PAGE-100",
            "name": "Page-created survey",
            "entry_link": "https://client.example/fieldwork?campaign=page",
            "rid_parameter": "pid",
            "cpi": "4.75",
            "sample_size": "80",
            "loi": "8",
            "incidence_rate": "55",
            "country": "India",
            "country_code": "IN",
            "language": "English",
            "language_code": "EN",
            "buyer_id": "",
            "survey_type": "B2C",
            "device_type": "All",
        }

    def test_admin_can_create_from_sidebar_page_and_get_internal_link(self):
        self.client.force_login(self.owner)
        page = self.client.get(reverse("manual-survey-create"))
        self.assertContains(page, "Add Manual Survey")
        self.assertContains(page, 'name="rid_parameter"')

        response = self.client.post(reverse("manual-survey-create"), self.payload)
        survey = Survey.objects.get(source_key="PAGE-100")
        self.assertRedirects(
            response,
            f"{reverse('manual-survey-create')}?created={survey.local_id}",
        )
        success = self.client.get(response["Location"])
        self.assertContains(success, survey.local_id)
        self.assertContains(success, "RM Wins start link")
        projects = self.client.get(reverse("projects"))
        self.assertContains(projects, "Add Manual Survey")

    def test_employee_without_manual_permission_is_denied_and_button_hidden(self):
        self.client.force_login(self.employee)
        self.assertEqual(self.client.get(reverse("manual-survey-create")).status_code, 403)
        self.assertNotContains(self.client.get(reverse("projects")), "Add Manual Survey")


class ManualSurveyDeliveryTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_superuser(
            "delivery-owner", "delivery@example.test", "test-password"
        )
        self.client_record = Client.objects.create(
            code="delivery-manual", name="Delivery Client", provider_code="custom"
        )
        form = ManualSurveyForm({
            "client": self.client_record.pk,
            "source_key": "DELIVERY-1",
            "name": "Manual delivery survey",
            "entry_link": "https://client.example/launch?campaign=alpha&respondent_id=placeholder",
            "rid_parameter": "respondent_id",
            "cpi": "12.00",
            "sample_size": "100",
            "loi": "10",
            "incidence_rate": "40",
            "country": "United States",
            "country_code": "US",
            "language": "English",
            "language_code": "EN",
            "buyer_id": "",
            "survey_type": "B2C",
            "device_type": "All",
        })
        self.assertTrue(form.is_valid(), form.errors)
        self.survey = form.save(created_by=self.owner)

    def test_manual_outbound_uses_configured_parameter_without_api_routing_parameters(self):
        outbound = build_outbound_url(
            self.survey.entry_link,
            "Aa1Bb2Cc3D",
            {},
            rid_parameter=self.survey.manual_rid_parameter,
        )
        params = parse_qs(urlsplit(outbound).query)
        self.assertEqual(params["respondent_id"], ["Aa1Bb2Cc3D"])
        self.assertEqual(params["campaign"], ["alpha"])
        self.assertNotIn("PID", params)
        self.assertNotIn("trackId", params)

    @override_settings(PRESCREENER_VAULT_ENABLED=False, PUBLIC_SUPPLIER_CODE="1000")
    def test_manual_project_uses_normal_attempt_and_redirect_flow(self):
        start = self.client.get(reverse("survey-start"), {
            "surveyId": self.survey.source_key,
            "supplierCode": "1000",
            "userId": self.owner.pk,
            "code": self.survey.local_id,
        })
        self.assertEqual(start.status_code, 302)
        rid = parse_qs(urlsplit(start["Location"]).query)["rid"][0]

        form_page = self.client.get(start["Location"])
        self.assertEqual(form_page.status_code, 200)
        submit = self.client.post(reverse("survey-start"), {"rid": rid})

        self.assertEqual(submit.status_code, 302)
        params = parse_qs(urlsplit(submit["Location"]).query)
        self.assertEqual(params["respondent_id"], [rid])
        attempt = SurveyAttempt.objects.get(rid=rid)
        self.assertEqual(attempt.source_cpi_snapshot, Decimal("12.00"))
        self.assertEqual(attempt.payable_cpi_snapshot, Decimal("12.00"))

    def test_manual_survey_uses_existing_supplier_cpi_cut_policy(self):
        supplier = get_user_model().objects.create_user("manual-supplier")
        EmployeeProfile.objects.filter(user=supplier).update(
            account_type=EmployeeProfile.AccountType.EXTERNAL_VENDOR,
            role=Role.objects.get(slug="external-vendor"),
            created_by=self.owner,
        )
        VendorCommercialProfile.objects.create(
            vendor=supplier,
            default_cpi_cut_percent=Decimal("25.00"),
            created_by=self.owner,
        )
        allocation = VendorClientAllocation.objects.create(
            vendor=supplier,
            client=self.client_record,
            created_by=self.owner,
        )
        attempt = create_attempt(self.survey, supplier, None)
        context = resolve_vendor_survey_context(
            supplier, self.survey, require_capacity=True
        )

        reserve_attempt_capacity(
            attempt,
            context.survey_allocation,
            client_allocation=allocation,
        )

        attempt.refresh_from_db()
        self.assertEqual(attempt.source_cpi_snapshot, Decimal("12.00"))
        self.assertEqual(attempt.cpi_cut_percent_snapshot, Decimal("25.00"))
        self.assertEqual(attempt.payable_cpi_snapshot, Decimal("9.00"))
