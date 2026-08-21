import hashlib
import hmac

from django.test import TestCase, override_settings
from django.urls import reverse

from vendors.models import Client, ClientIntegration

from .models import Survey, SurveyAttempt


CALLBACK_SECRET = "test-only-innovatemr-callback-secret"
CALLBACK_URL = "https://rmwinsights.com/imr_callback"


@override_settings(
    INNOVATEMR_CALLBACK_HASH_SECRET=CALLBACK_SECRET,
    INNOVATEMR_CALLBACK_PUBLIC_URL=CALLBACK_URL,
    PUBLIC_RESULT_BASE_URL="https://www.rmwinsights.com",
)
class InnovateMRCallbackTests(TestCase):
    def setUp(self):
        client = Client.objects.create(
            code="innovate-callback",
            name="Innovate callback",
            provider_code="innovatemr",
        )
        integration = ClientIntegration.objects.create(
            client=client,
            name="Innovate callback integration",
            provider_code="innovatemr",
            base_url="https://supplier.innovatemr.net/api/v2",
        )
        self.survey = Survey.objects.create(
            client=client,
            integration=integration,
            source_id=987654321,
            name="Signed callback survey",
            status=Survey.Status.LIVE,
            remaining=100,
            entry_link="https://edgeapi.innovatemr.net/startSurvey?PID=[%%pid%%]",
        )

    def create_attempt(self, rid="Aa1Bb2Cc3D"):
        return SurveyAttempt.objects.create(
            rid=rid,
            survey=self.survey,
            status=SurveyAttempt.Status.REDIRECTED,
        )

    def callback_url(self, rid, status, *, extra="", secret=CALLBACK_SECRET):
        unsigned = f"{CALLBACK_URL}?pid={rid}&status={status}{extra}&hash="
        digest = hmac.new(
            secret.encode("utf-8"),
            unsigned.encode("utf-8"),
            hashlib.sha1,
        ).hexdigest()
        return f"{reverse('innovatemr-callback')}?pid={rid}&status={status}{extra}&hash={digest}"

    def test_valid_sha1_callback_verifies_and_credits_only_complete_status(self):
        attempt = self.create_attempt()

        response = self.client.get(self.callback_url(attempt.rid, "1"))

        self.assertRedirects(
            response,
            f"https://www.rmwinsights.com/survey?status=1&rid={attempt.rid}",
            fetch_redirect_response=False,
        )
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, SurveyAttempt.Status.COMPLETED)
        self.assertTrue(attempt.is_verified)
        self.assertEqual(attempt.status_source, "innovatemr_redirect_hash")
        self.assertEqual(attempt.callback_count, 1)
        self.assertTrue(attempt.upstream_transaction_data["innovatemr_redirect"]["hash_valid"])

    def test_all_documented_upstream_statuses_map_to_non_credit_outcomes(self):
        cases = {
            "2": SurveyAttempt.Status.TERMINATED,
            "3": SurveyAttempt.Status.OVER_QUOTA,
            "4": SurveyAttempt.Status.QUALITY_TERMINATED,
            "5": SurveyAttempt.Status.TERMINATED,
            "7": SurveyAttempt.Status.OVER_QUOTA,
            "8": SurveyAttempt.Status.QUALITY_TERMINATED,
        }
        for index, (upstream_status, expected) in enumerate(cases.items(), start=1):
            rid = f"Zz{index}Yy{index}Xx{index}W"[:10]
            attempt = self.create_attempt(rid)
            response = self.client.get(self.callback_url(rid, upstream_status))
            self.assertEqual(response.status_code, 302)
            attempt.refresh_from_db()
            self.assertEqual(attempt.status, expected)
            self.assertTrue(attempt.is_verified)

    def test_invalid_hash_security_terminates_without_persisting_hash(self):
        attempt = self.create_attempt()
        supplied_hash = "0" * 40

        response = self.client.get(
            reverse("innovatemr-callback"),
            {"pid": attempt.rid, "status": "1", "hash": supplied_hash},
        )

        self.assertEqual(response.status_code, 302)
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, SurveyAttempt.Status.QUALITY_TERMINATED)
        self.assertFalse(attempt.is_verified)
        self.assertEqual(attempt.status_source, "innovatemr_hash_rejected")
        self.assertNotIn(supplied_hash, str(attempt.upstream_transaction_data))

    def test_first_security_decision_cannot_be_upgraded_by_later_valid_hash(self):
        attempt = self.create_attempt()
        self.client.get(
            reverse("innovatemr-callback"),
            {"pid": attempt.rid, "status": "1", "hash": "0" * 40},
        )

        self.client.get(self.callback_url(attempt.rid, "1"))

        attempt.refresh_from_db()
        self.assertEqual(attempt.status, SurveyAttempt.Status.QUALITY_TERMINATED)
        self.assertFalse(attempt.is_verified)
        self.assertEqual(attempt.status_source, "innovatemr_hash_rejected")
        self.assertEqual(attempt.callback_count, 2)

    def test_invalid_replay_cannot_downgrade_verified_completion(self):
        attempt = self.create_attempt()
        self.client.get(self.callback_url(attempt.rid, "1"))

        self.client.get(
            reverse("innovatemr-callback"),
            {"pid": attempt.rid, "status": "4", "hash": "0" * 40},
        )

        attempt.refresh_from_db()
        self.assertEqual(attempt.status, SurveyAttempt.Status.COMPLETED)
        self.assertTrue(attempt.is_verified)
        self.assertEqual(attempt.status_source, "innovatemr_redirect_hash")

    def test_complete_url_with_additional_signed_data_verifies_byte_for_byte(self):
        attempt = self.create_attempt()

        response = self.client.get(self.callback_url(attempt.rid, "1", extra="&surveyId=99"))

        self.assertEqual(response.status_code, 302)
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, SurveyAttempt.Status.COMPLETED)
        self.assertTrue(attempt.is_verified)

    def test_signed_term_reason_is_persisted_for_supplier_forwarding(self):
        attempt = self.create_attempt()

        response = self.client.get(
            self.callback_url(
                attempt.rid,
                "5",
                extra="&termReason=Qualifications%20did%20not%20match",
            )
        )

        self.assertEqual(response.status_code, 302)
        attempt.refresh_from_db()
        self.assertTrue(attempt.is_verified)
        self.assertEqual(
            attempt.upstream_transaction_data["innovatemr_redirect"]["termReason"],
            "Qualifications did not match",
        )

    def test_unsigned_legacy_callback_cannot_credit_innovatemr_attempt(self):
        attempt = self.create_attempt()

        response = self.client.get(
            reverse("survey-status"),
            {"status": "1", "rid": attempt.rid},
        )

        self.assertEqual(response.status_code, 302)
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, SurveyAttempt.Status.QUALITY_TERMINATED)
        self.assertFalse(attempt.is_verified)
        self.assertEqual(attempt.status_source, "innovatemr_hash_rejected")

    @override_settings(INNOVATEMR_CALLBACK_HASH_SECRET="")
    def test_missing_server_secret_fails_without_mutating_attempt(self):
        attempt = self.create_attempt()

        response = self.client.get(self.callback_url(attempt.rid, "1"))

        self.assertEqual(response.status_code, 503)
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, SurveyAttempt.Status.REDIRECTED)
        self.assertEqual(attempt.callback_count, 0)

    def test_unknown_pid_returns_404(self):
        response = self.client.get(self.callback_url("Qq1Ww2Ee3R", "1"))

        self.assertEqual(response.status_code, 404)
