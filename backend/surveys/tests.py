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


    def test_questions_endpoint_requires_login(self):
        response = self.client.get("/api/surveys/questions/?company=InnovateMR&survey_id=LMS-2")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith("/login/?next="))

    @patch("surveys.views.get_survey_questions")
    @patch("surveys.views.get_surveys")
    def test_questions_endpoint_returns_current_survey_questions(self, get_surveys, get_questions):
        self.client.force_login(self.user)
        get_surveys.return_value = (SAMPLE, datetime.now(timezone.utc), False)
        get_questions.return_value = {
            "company": "innovatemr",
            "survey_id": "LMS-2",
            "survey_name": "Enligne Survey",
            "questions": [{"id": "2", "code": "GENDER", "text": "What is your gender?", "type": "Single Punch", "category": "Demographic", "options": []}],
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }

        response = self.client.get("/api/surveys/questions/?company=innovatemr&survey_id=LMS-2")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["questions"][0]["code"], "GENDER")
        get_questions.assert_called_once_with(SAMPLE[1], force=False)


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
        response = self.client.get("/api/surveys/export/?page_size=1")
        content = b"".join(response.streaming_content).decode("utf-8-sig")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-Exported-Count"], "2")
        self.assertIn("LMS-1", content)
        self.assertIn("LMS-2", content)
        self.assertIn("user_id={userId}", content)

    @patch("surveys.views.get_surveys")
    def test_csv_export_generates_distinct_alphanumeric_supplier_ids(self, get_surveys):
        self.client.force_login(self.user)
        rows = [
            {**SAMPLE[0], "entry_url": "https://example.test/start?PID=[%%pid%%]"},
            {**SAMPLE[1], "entry_url": "https://example.test/start?vq_token=[#vq_tid#]&vq_uid=[#vq_tuid#]"},
        ]
        get_surveys.return_value = (rows, datetime.now(timezone.utc), False)

        response = self.client.get("/api/surveys/export/")
        content = b"".join(response.streaming_content).decode("utf-8-sig")

        self.assertNotIn("[%%pid%%]", content)
        self.assertNotIn("[#vq_tid#]", content)
        self.assertNotIn("[#vq_tuid#]", content)
        generated = re.findall(r"(?:PID|vq_token|vq_uid)=([A-Za-z0-9]{24})", content)
        self.assertEqual(len(generated), 3)
        self.assertEqual(len(set(generated)), 3)
        self.assertNotIn("omega", content)


class SurveyServicesTests(SimpleTestCase):
    def setUp(self):
        services._cache.update(data=None, fetched_at=None, monotonic=0.0, stale=False)
        services._supplier_cache.update(InnovateMR=None, Voqall=None)
        services._voqall_language_cache = {}
        services._voqall_qualification_catalog_cache = {}
        services._voqall_question_detail_cache.clear()
        services._question_cache.clear()

    def tearDown(self):
        services._cache.update(data=None, fetched_at=None, monotonic=0.0, stale=False)
        services._supplier_cache.update(InnovateMR=None, Voqall=None)
        services._voqall_language_cache = {}
        services._voqall_qualification_catalog_cache = {}
        services._voqall_question_detail_cache.clear()
        services._question_cache.clear()

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


    def test_innovatemr_question_schema_is_normalized(self):
        question = normalize_innovatemr_question(
            {
                "QuestionId": 2,
                "QuestionKey": "GENDER",
                "QuestionText": "What is your gender?",
                "QuestionType": "Single Punch",
                "QuestionCategory": "Demographic",
                "Options": [{"OptionId": 1, "OptionText": "Male"}],
            }
        )
        self.assertEqual(question["code"], "GENDER")
        self.assertEqual(question["options"], [{"id": "1", "text": "Male"}])

    def test_voqall_question_uses_language_detail_and_allowed_options(self):
        question = services._normalize_voqall_question(
            {"QualificationId": 59, "OptionIds": [1]},
            {
                "Id": 59,
                "Code": "GENDER",
                "QuestionText": "What is your gender?",
                "TypeName": "Single select",
                "Options": [
                    {"OptionCode": 1, "OptionText": "Male"},
                    {"OptionCode": 2, "OptionText": "Female"},
                ],
            },
            {},
        )
        self.assertEqual(question["text"], "What is your gender?")
        self.assertEqual(question["options"], [{"id": "1", "text": "Male"}])


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
