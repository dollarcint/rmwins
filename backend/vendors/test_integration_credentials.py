from unittest.mock import patch

from django.test import TestCase, override_settings

from surveys.models import Survey
from vendors.credentials import (
    reconcile_all_integration_credentials,
    resolve_integration_token,
    set_integration_env_key,
    set_integration_token,
)
from vendors.models import Client, ClientIntegration
from vendors.serializers import ClientIntegrationSerializer


@override_settings(INTEGRATION_CREDENTIAL_ENCRYPTION_KEY="test-encryption-key")
class ClientIntegrationCredentialTests(TestCase):
    def setUp(self):
        self.client_a = Client.objects.create(code="client-a", name="Client A")
        self.client_b = Client.objects.create(code="client-b", name="Client B")
        self.integration_a = ClientIntegration.objects.create(client=self.client_a, name="API A", base_url="https://example.test/api")
        self.integration_b = ClientIntegration.objects.create(client=self.client_b, name="API B", base_url="https://example.test/api")

    def test_secret_is_encrypted_and_never_serialized(self):
        set_integration_token(self.integration_a, "plain-secret-1234")
        self.integration_a.refresh_from_db()
        self.assertNotIn("plain-secret", self.integration_a.encrypted_api_token)
        self.assertEqual(resolve_integration_token(self.integration_a), "plain-secret-1234")
        payload = ClientIntegrationSerializer(self.integration_a).data
        self.assertNotIn("api_token", payload)
        self.assertNotIn("encrypted_api_token", payload)
        self.assertEqual(payload["masked_credential"], "••••1234")

    def test_changed_key_clears_only_its_own_links(self):
        set_integration_token(self.integration_a, "token-one")
        set_integration_token(self.integration_b, "token-two")
        survey_a = Survey.objects.create(integration=self.integration_a, client=self.client_a, source_id=42, entry_link="https://a.test/start", raw_data={"a": 1})
        survey_b = Survey.objects.create(integration=self.integration_b, client=self.client_b, source_id=42, entry_link="https://b.test/start", raw_data={"b": 1})
        changed, cleared = set_integration_token(self.integration_a, "token-one")
        self.assertFalse(changed)
        self.assertEqual(cleared, 0)
        survey_a.refresh_from_db()
        self.assertTrue(survey_a.entry_link)
        changed, cleared = set_integration_token(self.integration_a, "replacement-token")
        self.assertTrue(changed)
        self.assertEqual(cleared, 1)
        survey_a.refresh_from_db(); survey_b.refresh_from_db()
        self.assertEqual(survey_a.entry_link, "")
        self.assertEqual(survey_a.raw_data, {})
        self.assertEqual(survey_b.entry_link, "https://b.test/start")

    def test_switching_to_same_environment_token_preserves_data(self):
        set_integration_token(self.integration_a, "token-one")
        survey = Survey.objects.create(
            integration=self.integration_a,
            client=self.client_a,
            source_id=42,
            entry_link="https://a.test/start",
            raw_data={"a": 1},
        )
        with patch.dict("os.environ", {"CLIENT_A_API_KEY": "token-one"}):
            changed, cleared = set_integration_env_key(self.integration_a, "CLIENT_A_API_KEY")
            self.integration_a.refresh_from_db()
            self.assertFalse(changed)
            self.assertEqual(cleared, 0)
            self.assertFalse(self.integration_a.encrypted_api_token)
            self.assertEqual(self.integration_a.credential_env_key, "CLIENT_A_API_KEY")
            self.assertEqual(resolve_integration_token(self.integration_a), "token-one")
        survey.refresh_from_db()
        self.assertEqual(survey.entry_link, "https://a.test/start")

    def test_changed_environment_token_stays_environment_backed(self):
        with patch.dict("os.environ", {"CLIENT_A_API_KEY": "token-one"}):
            set_integration_env_key(self.integration_a, "CLIENT_A_API_KEY")
        survey = Survey.objects.create(
            integration=self.integration_a,
            client=self.client_a,
            source_id=42,
            entry_link="https://a.test/start",
            raw_data={"a": 1},
        )
        with patch.dict("os.environ", {"CLIENT_A_API_KEY": "replacement-token"}):
            result = reconcile_all_integration_credentials()
            self.integration_a.refresh_from_db()
            self.assertEqual(result, {"checked": 1, "changed": 1, "cleared": 1})
            self.assertFalse(self.integration_a.encrypted_api_token)
            self.assertEqual(self.integration_a.credential_env_key, "CLIENT_A_API_KEY")
            self.assertEqual(resolve_integration_token(self.integration_a), "replacement-token")
        survey.refresh_from_db()
        self.assertEqual(survey.entry_link, "")
        self.assertEqual(survey.raw_data, {})

    def test_saving_database_token_disables_environment_source(self):
        self.integration_a.credential_env_key = "CLIENT_A_API_KEY"
        self.integration_a.save(update_fields=["credential_env_key"])
        set_integration_token(self.integration_a, "token-one")
        self.integration_a.refresh_from_db()
        self.assertEqual(self.integration_a.credential_env_key, "")
        self.assertTrue(self.integration_a.encrypted_api_token)

    def test_same_provider_source_id_is_unique_per_integration(self):
        Survey.objects.create(integration=self.integration_a, client=self.client_a, source_id=508)
        Survey.objects.create(integration=self.integration_b, client=self.client_b, source_id=508)
        self.assertEqual(Survey.objects.filter(source_id=508).count(), 2)
