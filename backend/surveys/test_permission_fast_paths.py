"""Fail-closed regressions for cached permission paths."""

from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.test import RequestFactory, TestCase
from django.urls import reverse
from rest_framework.exceptions import PermissionDenied as DRFPermissionDenied

from accounts.models import AccessFunction
from vendors.models import Client, ClientIntegration
from vendors.serializers import ClientSerializer

from .models import Survey
from .serializers import SurveyListSerializer
from .views import _enforce_query_permissions, workspace_home


class InactiveSuperuserFastPathTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="inactive-fast-path-owner",
            password="password-123",
        )
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        self.client_record = Client.objects.create(
            code="inactive-fast-path-client",
            name="Inactive Fast Path Client",
            provider_code="innovatemr",
        )
        ClientIntegration.objects.create(
            client=self.client_record,
            name="Inactive Fast Path Integration",
            provider_code="innovatemr",
            base_url="https://provider.example/api",
        )
        self.survey = Survey.objects.create(
            client=self.client_record,
            source_id=818181,
            name="Inactive permission survey",
            entry_link="https://provider.example/start?pid=[%%pid%%]",
        )
        self.request = RequestFactory().get("/api/v1/surveys/")
        self.request.user = self.user

    def test_survey_serializer_does_not_trust_inactive_superuser_flag(self):
        data = SurveyListSerializer(
            self.survey, context={"request": self.request}
        ).data

        self.assertIsNone(data["start_link"])
        self.assertEqual(data["display_company_name"], "")

    def test_client_serializer_hides_integrations(self):
        data = ClientSerializer(
            self.client_record, context={"request": self.request}
        ).data

        self.assertEqual(data["integrations"], [])

    def test_query_filter_guard_denies_inactive_superuser(self):
        request = SimpleNamespace(
            user=self.user,
            query_params={"min_cpi": "1.00"},
        )

        with self.assertRaises(DRFPermissionDenied):
            _enforce_query_permissions(
                request, {"projects.filter.cpi": ("min_cpi",)}
            )

    def test_workspace_router_denies_inactive_superuser(self):
        with self.assertRaises(DjangoPermissionDenied):
            workspace_home(self.request)

    def test_active_superuser_keeps_catalog_independent_fast_path_access(self):
        active_owner = get_user_model().objects.create_superuser(
            username="active-fast-path-owner",
            password="password-123",
        )
        AccessFunction.objects.filter(
            code__in=(
                "survey_links.copy",
                "clients.integration.view",
                "projects.view",
            )
        ).update(is_active=False)
        request = RequestFactory().get("/api/v1/surveys/")
        request.user = active_owner

        survey_data = SurveyListSerializer(
            self.survey, context={"request": request}
        ).data
        client_data = ClientSerializer(
            self.client_record, context={"request": request}
        ).data
        _enforce_query_permissions(
            SimpleNamespace(
                user=active_owner,
                query_params={"unknown": "value"},
            ),
            {"catalog.code.that.does.not.exist": ("unknown",)},
        )
        home = workspace_home(request)

        self.assertIsNotNone(survey_data["start_link"])
        self.assertEqual(len(client_data["integrations"]), 1)
        self.assertEqual(home.url, reverse("projects"))
