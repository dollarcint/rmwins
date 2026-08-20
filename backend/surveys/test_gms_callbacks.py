from django.test import TestCase, override_settings
from django.urls import reverse

from vendors.models import Client, ClientIntegration

from .models import Survey, SurveyAttempt


@override_settings(PUBLIC_RESULT_BASE_URL="https://www.rmwinsights.com")
class GMSCallbackTests(TestCase):
    def setUp(self):
        self.gms_client = Client.objects.create(
            code="gms-client",
            name="GMS",
            provider_code="innovatemr",
        )
        integration = ClientIntegration.objects.create(
            client=self.gms_client,
            name="GMS integration",
            provider_code="innovatemr",
            base_url="https://gms.example/api",
        )
        self.survey = Survey.objects.create(
            client=self.gms_client,
            integration=integration,
            source_id=800001,
            name="GMS callback survey",
            status=Survey.Status.LIVE,
            remaining=100,
            entry_link="https://gms.example/start?pid=[%%pid%%]",
        )

    def create_attempt(self, rid):
        return SurveyAttempt.objects.create(
            rid=rid,
            survey=self.survey,
            status=SurveyAttempt.Status.REDIRECTED,
        )

    def test_four_redirects_record_the_expected_verified_outcome(self):
        cases = {
            "1": SurveyAttempt.Status.COMPLETED,
            "2": SurveyAttempt.Status.TERMINATED,
            "3": SurveyAttempt.Status.OVER_QUOTA,
            "4": SurveyAttempt.Status.QUALITY_TERMINATED,
        }
        for index, (status, expected) in enumerate(cases.items(), start=1):
            with self.subTest(status=status):
                rid = f"Gm{index}Aa{index}Bb{index}C"
                attempt = self.create_attempt(rid)

                response = self.client.get(
                    reverse("gms-callback"),
                    {"pid": rid, "status": status},
                )

                self.assertRedirects(
                    response,
                    f"https://www.rmwinsights.com/survey?status={status}&rid={rid}",
                    fetch_redirect_response=False,
                )
                attempt.refresh_from_db()
                self.assertEqual(attempt.status, expected)
                self.assertTrue(attempt.is_verified)
                self.assertEqual(attempt.status_source, "gms_redirect")
                self.assertEqual(attempt.callback_count, 1)
                audit = attempt.upstream_transaction_data["gms_redirect"]
                self.assertEqual(audit, {"upstream_status": status, "duplicate": False})
                self.assertNotIn("termreason", str(attempt.upstream_transaction_data).lower())
                self.assertNotIn("hash", str(attempt.upstream_transaction_data).lower())

    def test_first_gms_result_is_immutable_on_replay(self):
        attempt = self.create_attempt("Gm5Aa5Bb5C")
        self.client.get(reverse("gms-callback"), {"pid": attempt.rid, "status": "1"})

        self.client.get(reverse("gms-callback"), {"pid": attempt.rid, "status": "4"})

        attempt.refresh_from_db()
        self.assertEqual(attempt.status, SurveyAttempt.Status.COMPLETED)
        self.assertTrue(attempt.is_verified)
        self.assertEqual(attempt.callback_count, 2)
        self.assertTrue(attempt.upstream_transaction_data["gms_redirect"]["duplicate"])

    def test_callback_rejects_extra_reason_or_hash_parameters(self):
        attempt = self.create_attempt("Gm6Aa6Bb6C")
        for extra in ({"termreason": "screenout"}, {"hash": "unused"}):
            with self.subTest(extra=extra):
                response = self.client.get(
                    reverse("gms-callback"),
                    {"pid": attempt.rid, "status": "1", **extra},
                )
                self.assertEqual(response.status_code, 400)
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, SurveyAttempt.Status.REDIRECTED)
        self.assertEqual(attempt.callback_count, 0)

    def test_callback_rejects_non_gms_attempt(self):
        other_client = Client.objects.create(
            code="other",
            name="Other",
            provider_code="innovatemr",
        )
        other_survey = Survey.objects.create(
            client=other_client,
            source_id=800002,
            name="Other survey",
            status=Survey.Status.LIVE,
        )
        attempt = SurveyAttempt.objects.create(
            rid="Gm7Aa7Bb7C",
            survey=other_survey,
            status=SurveyAttempt.Status.REDIRECTED,
        )

        response = self.client.get(
            reverse("gms-callback"),
            {"pid": attempt.rid, "status": "1"},
        )

        self.assertEqual(response.status_code, 404)
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, SurveyAttempt.Status.REDIRECTED)
