from datetime import datetime, timezone
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase


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
