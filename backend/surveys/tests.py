import re
from datetime import datetime, timezone
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings

from . import services
from .services import FeedError, normalize_innovatemr_question, normalize_innovatemr_survey, normalize_voqall_survey


SAMPLE = [
    {
        "survey_id": "LMS-1",
        "name": "Hidden survey name",
        "payout": 0.79,
        "description": "",
        "entry_url": "https://example.test/start?PID=[%%pid%%]",
        "country": "United States",
        "company": "BioBrain",
        "language_id": "1",
        "updated_at": "2026-08-01T10:00:00+00:00",
        "placement_id": "abc",
    },
    {
        "survey_id": "LMS-2",
        "name": "Another hidden name",
        "payout": 1.25,
        "description": "",
        "entry_url": "https://example.test/start?PID=[%%pid%%]",
        "country": "United Kingdom",
        "company": "InnovateMR",
        "language_id": "EN",
        "updated_at": "2026-08-02T10:00:00+00:00",
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

    def test_dashboard_uses_client_cpi_and_date_labels_without_survey_name(self):
        self.client.force_login(self.user)
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "CPI order")
        self.assertContains(response, "From date")
        self.assertContains(response, "Client")
        self.assertNotContains(response, "Survey name")
        self.assertNotContains(response, "Unique random IDs")
        self.assertNotContains(response, "Open ↗")

    def test_questions_endpoint_requires_login(self):
        response = self.client.get("/api/surveys/questions/?company=InnovateMR&survey_id=LMS-2")
        self.assertEqual(response.status_code, 302)

    @patch("surveys.views.get_survey_questions")
    @patch("surveys.views.get_surveys")
    def test_questions_endpoint_returns_current_survey_questions(self, get_surveys, get_questions):
        self.client.force_login(self.user)
        get_surveys.return_value = (SAMPLE, datetime.now(timezone.utc), False)
        get_questions.return_value = {
            "company": "InnovateMR",
            "survey_id": "LMS-2",
            "questions": [{"id": "2", "code": "GENDER", "text": "What is your gender?", "type": "Single Punch", "category": "Demographic", "options": []}],
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        response = self.client.get("/api/surveys/questions/?company=InnovateMR&survey_id=LMS-2")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["questions"][0]["code"], "GENDER")

    @patch("surveys.views.get_surveys")
    def test_api_filters_by_client_and_full_country_name(self, get_surveys):
        self.client.force_login(self.user)
        get_surveys.return_value = (SAMPLE, datetime.now(timezone.utc), False)
        response = self.client.get("/api/surveys/?company=BioBrain&country=United%20States")
        payload = response.json()
        self.assertEqual(payload["pagination"]["total"], 1)
        self.assertEqual(payload["surveys"][0]["survey_id"], "LMS-1")
        self.assertEqual(payload["filters"]["clients"], ["BioBrain", "InnovateMR"])

    @patch("surveys.views.get_surveys")
    def test_api_defaults_to_latest_updated_first(self, get_surveys):
        self.client.force_login(self.user)
        get_surveys.return_value = (SAMPLE, datetime.now(timezone.utc), False)
        response = self.client.get("/api/surveys/")
        self.assertEqual(response.json()["surveys"][0]["survey_id"], "LMS-2")

    @patch("surveys.views.get_surveys")
    def test_api_sorts_cpi_both_directions(self, get_surveys):
        self.client.force_login(self.user)
        get_surveys.return_value = (SAMPLE, datetime.now(timezone.utc), False)
        high = self.client.get("/api/surveys/?sort=payout&direction=desc").json()["surveys"]
        low = self.client.get("/api/surveys/?sort=payout&direction=asc").json()["surveys"]
        self.assertEqual([row["payout"] for row in high], [1.25, 0.79])
        self.assertEqual([row["payout"] for row in low], [0.79, 1.25])

    @patch("surveys.views.get_surveys")
    def test_api_filters_updated_date_range(self, get_surveys):
        self.client.force_login(self.user)
        get_surveys.return_value = (SAMPLE, datetime.now(timezone.utc), False)
        payload = self.client.get("/api/surveys/?from_date=2026-08-02&to_date=2026-08-02").json()
        self.assertEqual(payload["pagination"]["total"], 1)
        self.assertEqual(payload["surveys"][0]["survey_id"], "LMS-2")

    @patch("surveys.views.get_surveys")
    def test_csv_export_contains_all_rows_and_trimmed_cpi(self, get_surveys):
        self.client.force_login(self.user)
        get_surveys.return_value = (SAMPLE, datetime.now(timezone.utc), False)
        response = self.client.get("/api/surveys/export/?page_size=1")
        content = b"".join(response.streaming_content).decode("utf-8-sig")
        self.assertEqual(response["X-Exported-Count"], "2")
        self.assertIn("Client,Country,CPI,Updated", content)
        self.assertIn(",0.79,", content)
        self.assertNotIn("Survey name", content)

    @patch("surveys.views.get_surveys")
    def test_csv_export_generates_distinct_alphanumeric_supplier_ids(self, get_surveys):
        self.client.force_login(self.user)
        rows = [
            SAMPLE[0],
            {**SAMPLE[1], "entry_url": "https://example.test/start?vq_token=[#vq_tid#]&vq_uid=[#vq_tuid#]"},
        ]
        get_surveys.return_value = (rows, datetime.now(timezone.utc), False)
        response = self.client.get("/api/surveys/export/")
        content = b"".join(response.streaming_content).decode("utf-8-sig")
        generated = re.findall(r"(?:PID|vq_token|vq_uid)=([A-Za-z0-9]{24})", content)
        self.assertEqual(len(generated), 3)
        self.assertEqual(len(set(generated)), 3)


class SurveyServicesTests(SimpleTestCase):
    def setUp(self):
        services._cache.update(data=None, fetched_at=None, monotonic=0.0, stale=False)
        services._supplier_cache.update(InnovateMR=None, BioBrain=None)
        services._voqall_language_cache = {}
        services._voqall_qualification_catalog_cache = {}
        services._voqall_question_detail_cache.clear()
        services._question_cache.clear()

    tearDown = setUp

    def test_innovatemr_schema_is_normalized(self):
        survey = normalize_innovatemr_survey(
            {
                "surveyId": 12632,
                "surveyName": "Hidden name",
                "CPI": "0.790",
                "CountryCode": "US",
                "Country": "United States",
                "modifiedDate": "08/02/2026, 03:30:00 pm PST",
                "entryLink": "https://supplier.test/start?PID=[%%pid%%]",
            }
        )
        self.assertEqual(survey["company"], "InnovateMR")
        self.assertEqual(survey["country"], "United States")
        self.assertEqual(survey["payout"], 0.79)
        self.assertEqual(survey["updated_at"], "2026-08-02T23:30:00+00:00")

    def test_voqall_schema_uses_biobrain_full_country_and_updated_date(self):
        survey = normalize_voqall_survey(
            {
                "SurveyId": 77,
                "Name": "VoqQ_7855498",
                "Revenue": 1.75,
                "LanguageId": 114,
                "LastUpdatedOnUTC": "2026-08-02T12:15:22Z",
                "SurveyUrl": "https://supplier.test/start?vq_uid=[#vq_tuid#]&vq_token=[#vq_tid#]",
            },
            {"114": "JM"},
        )
        self.assertEqual(survey["company"], "BioBrain")
        self.assertEqual(survey["country"], "Jamaica")
        self.assertEqual(survey["updated_at"], "2026-08-02T12:15:22+00:00")

    def test_innovatemr_question_schema_is_normalized(self):
        question = normalize_innovatemr_question(
            {"QuestionId": 2, "QuestionKey": "GENDER", "QuestionText": "What is your gender?", "QuestionType": "Single Punch", "QuestionCategory": "Demographic", "Options": [{"OptionId": 1, "OptionText": "Male"}]}
        )
        self.assertEqual(question["options"], [{"id": "1", "text": "Male"}])

    def test_voqall_question_uses_language_detail_and_allowed_options(self):
        question = services._normalize_voqall_question(
            {"QualificationId": 59, "OptionIds": [1]},
            {"Id": 59, "Code": "GENDER", "QuestionText": "What is your gender?", "TypeName": "Single select", "Options": [{"OptionCode": 1, "OptionText": "Male"}, {"OptionCode": 2, "OptionText": "Female"}]},
            {},
        )
        self.assertEqual(question["options"], [{"id": "1", "text": "Male"}])

    @override_settings(SURVEY_CACHE_SECONDS=0)
    @patch("surveys.services._fetch_voqall_surveys")
    @patch("surveys.services._fetch_innovatemr_surveys")
    def test_one_supplier_failure_does_not_hide_the_other(self, innovate_fetch, voqall_fetch):
        innovate_fetch.return_value = [SAMPLE[1]]
        voqall_fetch.side_effect = FeedError("BioBrain unavailable")
        surveys, _, stale = services.get_surveys(force=True)
        self.assertEqual(surveys, [SAMPLE[1]])
        self.assertTrue(stale)
