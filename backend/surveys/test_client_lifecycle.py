"""HTTP-client ownership and cleanup regression tests."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase, TestCase, override_settings

from vendors.models import Client, ClientIntegration

from .integrations import InnovateMRAPIError, InnovateMRClient
from .provider_services import sync_client_integration
from .providers.base import ProviderError, SurveyProvider
from .providers.enligne import EnligneProvider
from .services import sync_surveys


@override_settings(
    INNOVATEMR_API_TOKEN="test-token",
    INNOVATEMR_BASE_URL="https://supplier.example.test/api",
)
class InnovateMRClientLifecycleTests(SimpleTestCase):
    @patch("surveys.integrations.requests.Session")
    def test_owned_session_is_lazy_and_closed_once(self, session_class):
        session = session_class.return_value
        client = InnovateMRClient()

        self.assertEqual(client.endpoint_url("surveys"), "https://supplier.example.test/api/surveys")
        session_class.assert_not_called()

        self.assertIs(client.session, session)
        self.assertIs(client.session, session)
        session_class.assert_called_once_with()
        client.close()
        client.close()
        session.close.assert_called_once_with()
        with self.assertRaisesRegex(InnovateMRAPIError, "already closed"):
            _ = client.session

    @patch("surveys.integrations.requests.Session")
    def test_closing_before_first_request_prevents_late_pool_creation(self, session_class):
        client = InnovateMRClient()

        client.close()

        session_class.assert_not_called()
        with self.assertRaisesRegex(InnovateMRAPIError, "already closed"):
            _ = client.session
        session_class.assert_not_called()

    def test_caller_owned_session_is_never_closed(self):
        session = Mock()

        with InnovateMRClient(session=session) as client:
            pass

        session.close.assert_not_called()
        self.assertIs(client.session, session)


class SurveyProviderLifecycleTests(SimpleTestCase):
    @patch("surveys.providers.base.requests.Session")
    def test_owned_session_is_lazy_and_closed_once(self, session_class):
        session = session_class.return_value
        provider = SurveyProvider(SimpleNamespace())

        session_class.assert_not_called()
        self.assertIs(provider.session, session)
        self.assertIs(provider.session, session)
        session_class.assert_called_once_with()

        provider.close()
        provider.close()

        session.close.assert_called_once_with()
        with self.assertRaisesRegex(ProviderError, "already closed"):
            _ = provider.session

    def test_caller_owned_session_is_never_closed(self):
        session = Mock()

        with SurveyProvider(SimpleNamespace(), session=session) as provider:
            pass

        session.close.assert_not_called()
        self.assertIs(provider.session, session)

    @patch("surveys.providers.base.requests.Session")
    def test_close_failure_does_not_replace_context_result(self, session_class):
        session_class.return_value.close.side_effect = RuntimeError("close failed")

        with SurveyProvider(SimpleNamespace()) as provider:
            self.assertIs(provider.session, session_class.return_value)
            result = "business-result"

        self.assertEqual(result, "business-result")


class EnligneProviderLifecycleTests(SimpleTestCase):
    @staticmethod
    def integration():
        return SimpleNamespace(
            pk=11,
            client_id=7,
            base_url="https://enlignesurvey.com/get/api_feed/feed-id",
            credential_env_key="ENLIGNE_DB_PASSWORD",
            config={
                "db_host": "127.0.0.1",
                "db_port": 3306,
                "db_name": "lakshaya",
                "db_user": "reader",
                "company_filter": "innovatemr",
                "outbound_user_id": "kanik",
            },
        )

    @patch.dict("os.environ", {"ENLIGNE_DB_PASSWORD": "secret"})
    def test_owned_nested_detail_client_is_closed_once(self):
        detail_integration = SimpleNamespace(pk=12)
        queryset = Mock()
        queryset.exclude.return_value = queryset
        queryset.order_by.return_value.first.return_value = detail_integration
        session = Mock()

        with patch(
            "surveys.providers.enligne.ClientIntegration.objects.filter",
            return_value=queryset,
        ), patch("surveys.providers.enligne.InnovateMRClient") as client_class:
            provider = EnligneProvider(self.integration(), session=session)
            self.assertIs(provider._innovate_client(), client_class.return_value)
            provider.close()
            provider.close()

        client_class.assert_called_once_with(integration=detail_integration)
        client_class.return_value.close.assert_called_once_with()
        session.close.assert_not_called()

    @patch.dict("os.environ", {"ENLIGNE_DB_PASSWORD": "secret"})
    def test_caller_supplied_nested_client_and_session_remain_open(self):
        session = Mock()
        detail_client = Mock()

        with EnligneProvider(
            self.integration(),
            session=session,
            detail_client=detail_client,
        ):
            pass

        session.close.assert_not_called()
        detail_client.close.assert_not_called()


class SyncServiceClientLifecycleTests(TestCase):
    def setUp(self):
        client = Client.objects.create(
            code="sync-lifecycle",
            name="Sync Lifecycle",
            provider_code="innovatemr",
        )
        self.integration = ClientIntegration.objects.create(
            client=client,
            name="Sync Lifecycle",
            provider_code="innovatemr",
            base_url="https://supplier.example.test/api",
        )

    @patch("surveys.services.InnovateMRClient")
    def test_service_closes_only_the_client_it_constructs(self, client_class):
        owned_client = Mock()
        owned_client.get_allocated_surveys.return_value = []
        owned_client.get_allocated_surveys_paged.return_value = SimpleNamespace(
            surveys=[],
            pages=0,
        )
        owned_client.close.side_effect = RuntimeError("close failed")
        client_class.return_value = owned_client

        sync_surveys(integration=self.integration)

        owned_client.close.assert_called_once_with()

    def test_service_leaves_a_caller_supplied_batch_client_open(self):
        supplied_client = Mock()
        supplied_client.get_allocated_surveys.return_value = []
        supplied_client.get_allocated_surveys_paged.return_value = SimpleNamespace(
            surveys=[],
            pages=0,
        )

        sync_surveys(client=supplied_client, integration=self.integration)

        supplied_client.close.assert_not_called()

    @patch("surveys.provider_services.get_provider")
    def test_specialized_sync_closes_provider_without_masking_success(self, get_provider):
        provider = get_provider.return_value
        provider.inventory.return_value = []
        provider.close_missing_inventory_items = True
        provider.inventory_failures = []
        provider.close.side_effect = RuntimeError("close failed")

        run = sync_client_integration(self.integration)

        self.assertEqual(run.status, "success")
        provider.close.assert_called_once_with()

    @patch("surveys.provider_services.get_provider")
    def test_specialized_sync_close_failure_does_not_replace_upstream_error(self, get_provider):
        provider = get_provider.return_value
        provider.inventory.side_effect = ProviderError("inventory failed")
        provider.close.side_effect = RuntimeError("close failed")

        with self.assertRaisesRegex(ProviderError, "inventory failed"):
            sync_client_integration(self.integration)

        provider.close.assert_called_once_with()
