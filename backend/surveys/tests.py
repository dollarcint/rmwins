import json
import re
from datetime import datetime, timezone
from unittest.mock import patch
from urllib.parse import urlsplit

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings

from . import services
from .models import SurveySession
from .services import FeedError, normalize_innovatemr_question, normalize_innovatemr_survey, normalize_voqall_survey


SAMPLE = [
    {
        "survey_id": "LMS-1",
        "name": "Hidden survey name",
        "payout": 0.79,
        "description": "",
        "entry_url": "https://rf.voqall.test/l?vq_sid=LMS-1&vq_vid=vendor-1&vq_token=[#vq_tid#]&vq_uid=[#vq_tuid#]",
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
        "entry_url": "https://edgeapi.innovatemr.test/startSurvey?PID=[%%pid%%]",
        "country": "United Kingdom",
        "company": "InnovateMR",
        "language_id": "EN",
        "updated_at": "2026-08-02T10:00:00+00:00",
        "placement_id": "def",
    },
]

BIOBRAIN_QUESTIONS = {
    "company": "BioBrain",
    "survey_id": "LMS-1",
    "questions": [
        {
            "id": "59",
            "code": "GENDER",
            "text": "What is your gender?",
            "type": "Single select",
            "category": "Demographic",
            "options": [{"id": "1", "text": "Male"}, {"id": "2", "text": "Female"}],
        }
    ],
    "fetched_at": datetime.now(timezone.utc).isoformat(),
}


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
    def test_launch_link_requires_login(self, get_surveys):
        get_surveys.return_value = (SAMPLE, datetime.now(timezone.utc), False)
        response = self.client.post(
            "/api/surveys/launch-link/",
            data=json.dumps({"company": "BioBrain", "survey_id": "LMS-1"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 302)

    @patch("surveys.views.get_surveys")
    def test_biobrain_copy_link_returns_direct_url_with_two_unique_ids(self, get_surveys):
        self.client.force_login(self.user)
        get_surveys.return_value = (SAMPLE, datetime.now(timezone.utc), False)
        response = self.client.post(
            "/api/surveys/launch-link/",
            data=json.dumps({"company": "BioBrain", "survey_id": "LMS-1"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        launch_url = payload["launch_url"]
        generated = re.findall(r"(?:vq_token|vq_uid)=([A-Za-z0-9]{24})", launch_url)
        self.assertFalse(payload["tracked"])
        self.assertIn("rf.voqall", launch_url)
        self.assertEqual(len(generated), 2)
        self.assertEqual(len(set(generated)), 2)
        self.assertNotIn("[#vq_", launch_url)

    def test_tracked_start_and_return_pages_are_disabled_by_default(self):
        self.assertEqual(self.client.get("/survey/start/not-a-live-token/").status_code, 404)
        self.assertEqual(self.client.get("/survey/return/s1/?token=x&vendor_user_id=y").status_code, 404)

    @override_settings(SURVEY_TRACKED_FLOW_ENABLED=True)
    @patch("surveys.views.get_survey_questions")
    @patch("surveys.views.get_surveys")
    def test_public_start_page_creates_unique_tracked_session_and_hands_off(self, get_surveys, get_questions):
        self.client.force_login(self.user)
        get_surveys.return_value = (SAMPLE, datetime.now(timezone.utc), False)
        get_questions.return_value = BIOBRAIN_QUESTIONS
        launch_response = self.client.post(
            "/api/surveys/launch-link/",
            data=json.dumps({"company": "BioBrain", "survey_id": "LMS-1"}),
            content_type="application/json",
        )
        launch_path = urlsplit(launch_response.json()["launch_url"]).path
        self.client.logout()

        page = self.client.get(launch_path)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "What is your gender?")
        response = self.client.post(launch_path, {"question_59": "1", "consent": "yes"})
        self.assertEqual(response.status_code, 303)
        location = response["Location"]
        generated = re.findall(r"(?:vq_token|vq_uid)=([A-Za-z0-9]{24})", location)
        self.assertEqual(len(generated), 2)
        self.assertEqual(len(set(generated)), 2)
        self.assertNotIn("[#vq_", location)
        session = SurveySession.objects.get()
        self.assertEqual(session.status, SurveySession.Status.HANDED_OFF)
        self.assertEqual(session.prescreener_answers["59"]["values"], ["1"])
        self.assertIn("gender=1", location)

    @override_settings(SURVEY_TRACKED_FLOW_ENABLED=True)
    def test_all_four_return_urls_record_the_exact_status(self):
        status_map = {
            "s1": SurveySession.Status.COMPLETE,
            "s2": SurveySession.Status.TERMINATE,
            "s3": SurveySession.Status.QUOTA_FULL,
            "s4": SurveySession.Status.SECURITY_TERMINATE,
        }
        for index, (code, expected_status) in enumerate(status_map.items(), start=1):
            with self.subTest(code=code):
                session = SurveySession.objects.create(
                    client="BioBrain",
                    survey_id=f"LMS-{index}",
                    transaction_id=f"Token{index:019d}",
                    respondent_id=f"User{index:020d}",
                    entry_url="https://rf.voqall.test/l",
                    status=SurveySession.Status.HANDED_OFF,
                )
                response = self.client.get(
                    f"/survey/return/{code}/?token={session.transaction_id}&vendor_user_id={session.respondent_id}&status=88"
                )
                self.assertEqual(response.status_code, 200)
                session.refresh_from_db()
                self.assertEqual(session.status, expected_status)
                self.assertEqual(session.supplier_status_id, "88")
                self.assertIsNotNone(session.returned_at)

    @override_settings(SURVEY_TRACKED_FLOW_ENABLED=True)
    def test_return_url_requires_the_exact_token_and_user_pair(self):
        first = SurveySession.objects.create(
            client="BioBrain", survey_id="LMS-A", transaction_id="A" * 24, respondent_id="B" * 24,
            entry_url="https://rf.voqall.test/l", status=SurveySession.Status.HANDED_OFF,
        )
        second = SurveySession.objects.create(
            client="BioBrain", survey_id="LMS-B", transaction_id="C" * 24, respondent_id="D" * 24,
            entry_url="https://rf.voqall.test/l", status=SurveySession.Status.HANDED_OFF,
        )
        response = self.client.get(f"/survey/return/s1/?token={first.transaction_id}&vendor_user_id={second.respondent_id}")
        self.assertEqual(response.status_code, 404)
        first.refresh_from_db()
        self.assertEqual(first.status, SurveySession.Status.HANDED_OFF)

    @patch("surveys.views.get_surveys")
    def test_csv_export_contains_all_direct_urls_with_distinct_random_ids(self, get_surveys):
        self.client.force_login(self.user)
        get_surveys.return_value = (SAMPLE, datetime.now(timezone.utc), False)
        response = self.client.get("/api/surveys/export/?page_size=1")
        content = b"".join(response.streaming_content).decode("utf-8-sig")
        generated = re.findall(r"(?:PID|vq_token|vq_uid)=([A-Za-z0-9]{24})", content)
        self.assertEqual(response["X-Exported-Count"], "2")
        self.assertIn("Client,Country,CPI,Updated", content)
        self.assertIn(",0.79,", content)
        self.assertNotIn("/survey/start/", content)
        self.assertEqual(len(generated), 3)
        self.assertEqual(len(set(generated)), 3)
        self.assertNotIn("[#vq_", content)
        self.assertNotIn("[%%pid%%]", content)
        self.assertNotIn("Survey name", content)


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
