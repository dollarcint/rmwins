from datetime import datetime, timezone
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings

from . import services
from .services import FeedError, normalize_innovatemr_survey, normalize_voqall_survey


SAMPLE = [
    {
        "survey_id": "LMS-1",
        "name": "Enligne Survey",
        "payout": 0.75,
        "description": "",
        "entry_url": "https://example.test/start?survey_id=LMS-1&user_id={userId}&company=voqall",
        "country": "US",
        "company": "voqall",
        "placement_id": "abc",
    },
    {
        "survey_id": "LMS-2",
        "name": "Enligne Survey",
        "payout": 1.25,
        "description": "",
        "entry_url": "https://example.test/start?survey_id=LMS-2&user_id={userId}&company=innovatemr",
        "country": "GB",
        "company": "innovatemr",
        "placement_id": "def",
    },
]


class SurveyViewsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="tester", password="test-pass-123")

    def test_dashboard_requires_login(self):
        response = self.client.get("/")
        self.assertRedirects(response, "/login/?next=/")

    def test_branded_login_page_loads(self):
        response = self.client.get("/login/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alessar Research Cloud")

    def test_authenticated_dashboard_loads(self):
        self.client.force_login(self.user)
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Live survey inventory")

    @patch("surveys.views.get_surveys")
    def test_api_filters_by_company_and_country(self, get_surveys):
        self.client.force_login(self.user)
        get_surveys.return_value = (SAMPLE, datetime.now(timezone.utc), False)
        response = self.client.get("/api/surveys/?company=voqall&country=US")
        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["pagination"]["total"], 1)
        self.assertEqual(payload["surveys"][0]["survey_id"], "LMS-1")

    @patch("surveys.views.get_surveys")
    def test_api_paginates_results(self, get_surveys):
        self.client.force_login(self.user)
        get_surveys.return_value = (SAMPLE, datetime.now(timezone.utc), False)
        response = self.client.get("/api/surveys/?page_size=1&page=2")
        payload = response.json()
        self.assertEqual(payload["pagination"]["total_pages"], 2)
        self.assertEqual(len(payload["surveys"]), 1)

    @patch("surveys.views.get_surveys")
    def test_csv_export_contains_all_matching_rows_without_page_limit(self, get_surveys):
        self.client.force_login(self.user)
        get_surveys.return_value = (SAMPLE, datetime.now(timezone.utc), False)
        response = self.client.get("/api/surveys/export/?page_size=1&user_id=omega")
        content = b"".join(response.streaming_content).decode("utf-8-sig")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-Exported-Count"], "2")
        self.assertIn("LMS-1", content)
        self.assertIn("LMS-2", content)
        self.assertIn("user_id=omega", content)
        self.assertNotIn("{userId}", content)

    @patch("surveys.views.get_surveys")
    def test_csv_export_personalizes_supplier_specific_user_ids(self, get_surveys):
        self.client.force_login(self.user)
        rows = [
            {**SAMPLE[0], "entry_url": "https://example.test/start?PID=[%%pid%%]"},
            {**SAMPLE[1], "entry_url": "https://example.test/start?vq_uid=&vq_token=keep-me"},
        ]
        get_surveys.return_value = (rows, datetime.now(timezone.utc), False)

        response = self.client.get("/api/surveys/export/?user_id=omega")
        content = b"".join(response.streaming_content).decode("utf-8-sig")

        self.assertIn("PID=omega", content)
        self.assertIn("vq_uid=omega", content)
        self.assertIn("vq_token=keep-me", content)


class SurveyServicesTests(SimpleTestCase):
    def setUp(self):
        services._cache.update(data=None, fetched_at=None, monotonic=0.0, stale=False)
        services._supplier_cache.update(InnovateMR=None, Voqall=None)
        services._voqall_language_cache = {}

    def tearDown(self):
        services._cache.update(data=None, fetched_at=None, monotonic=0.0, stale=False)
        services._supplier_cache.update(InnovateMR=None, Voqall=None)
        services._voqall_language_cache = {}

    def test_innovatemr_schema_is_normalized(self):
        survey = normalize_innovatemr_survey(
            {
                "surveyId": 12632,
                "surveyName": "Beverage study",
                "CPI": "4.50",
                "CountryCode": "US",
                "entryLink": "https://supplier.test/start?PID=[%%pid%%]",
            }
        )
        self.assertEqual(survey["survey_id"], "12632")
        self.assertEqual(survey["company"], "InnovateMR")
        self.assertEqual(survey["country"], "US")
        self.assertEqual(survey["payout"], 4.5)

    def test_voqall_schema_and_language_market_are_normalized(self):
        survey = normalize_voqall_survey(
            {
                "SurveyId": 77,
                "Name": "Retail study",
                "Revenue": 1.75,
                "LanguageId": 114,
                "SurveyUrl": "https://supplier.test/start?vq_uid=&vq_token=abc",
            },
            {"114": "JM"},
        )
        self.assertEqual(survey["survey_id"], "77")
        self.assertEqual(survey["company"], "Voqall")
        self.assertEqual(survey["country"], "JM")
        self.assertEqual(survey["payout"], 1.75)

    @override_settings(SURVEY_CACHE_SECONDS=0)
    @patch("surveys.services._fetch_voqall_surveys")
    @patch("surveys.services._fetch_innovatemr_surveys")
    def test_one_supplier_failure_does_not_hide_the_other(self, innovate_fetch, voqall_fetch):
        innovate_fetch.return_value = [SAMPLE[1]]
        voqall_fetch.side_effect = FeedError("Voqall unavailable")

        surveys, _, stale = services.get_surveys(force=True)

        self.assertEqual(surveys, [SAMPLE[1]])
        self.assertTrue(stale)
