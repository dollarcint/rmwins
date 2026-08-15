from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase
from django.utils import timezone

from .providers.enligne import EnligneProvider


class EnligneProviderTests(SimpleTestCase):
    def integration(self):
        return SimpleNamespace(
            base_url="https://enlignesurvey.com/get/api_feed/feed-id",
            credential_env_key="ENLIGNE_DB_PASSWORD",
            config={
                "db_host": "127.0.0.1",
                "db_port": 3306,
                "db_name": "lakshaya",
                "db_user": "root",
                "company_filter": "innovatemr",
                "outbound_user_id": "kanik",
            },
        )

    @patch.dict("os.environ", {"ENLIGNE_DB_PASSWORD": "secret"})
    def test_inventory_matches_lms_id_and_filters_to_innovatemr(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "status": "Success",
            "data": [
                {
                    "survey_id": "LMS-100",
                    "name": "Enligne Survey",
                    "payout": "1.25",
                    "entry_url": "https://enlignesurvey.com/start_survey?survey_id=LMS-100&user_id={userId}&company=innovatemr",
                    "country": "US",
                },
                {
                    "survey_id": "LMS-200",
                    "name": "Enligne Survey",
                    "payout": "0.50",
                    "entry_url": "https://enlignesurvey.com/start_survey?survey_id=LMS-200&user_id={userId}&company=voqall",
                    "country": "GB",
                },
            ],
        }
        session = Mock()
        session.get.return_value = response
        provider = EnligneProvider(self.integration(), session=session)
        provider._lms_records = Mock(return_value={
            "LMS-100": {
                "lms_survey_id": "LMS-100", "survey_id": "15800967",
                "survey_company": "innovatemr", "survey_name": "Research study",
                "surveyLocalization": "US", "loi": "15", "ir": "80",
            },
            "LMS-200": {
                "lms_survey_id": "LMS-200", "survey_id": "900",
                "survey_company": "voqall", "surveyLocalization": "GB",
            },
        })

        inventory = provider.inventory()
        normalized = provider.normalize_inventory_item(inventory[0], timezone.now())

        self.assertEqual(len(inventory), 1)
        self.assertEqual(normalized.source_key, "15800967")
        self.assertEqual(normalized.numeric_source_id, 15800967)
        self.assertEqual(str(normalized.values["cpi"]), "1.25")
        self.assertEqual(normalized.values["loi"], 15)
        self.assertEqual(str(normalized.values["incidence_rate"]), "80")
        self.assertIn("survey_id=LMS-100", normalized.values["entry_link"])
        self.assertIn("user_id=kanik", normalized.values["entry_link"])

    @patch.dict("os.environ", {"ENLIGNE_DB_PASSWORD": "secret"})
    def test_outbound_link_sends_fixed_user_only_and_never_rid(self):
        provider = EnligneProvider(self.integration(), session=Mock())
        survey = SimpleNamespace(
            entry_link=(
                "https://enlignesurvey.com/start_survey?survey_id=LMS-100"
                "&user_id={userId}&placement_id=abc&company=innovatemr"
            )
        )
        attempt = SimpleNamespace(rid="Aa1Bb2Cc3D")

        outbound = provider.build_outbound_url(survey, attempt, {})

        self.assertIn("user_id=kanik", outbound)
        self.assertIn("survey_id=LMS-100", outbound)
        self.assertNotIn(attempt.rid, outbound)
        self.assertNotIn("PID=", outbound)
        self.assertNotIn("trackId=", outbound)

    @patch.dict("os.environ", {"ENLIGNE_DB_PASSWORD": "secret"})
    def test_lakshaya_lookup_executes_select_only(self):
        executed = []

        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def execute(self, sql, params):
                executed.append(sql.strip())

            def fetchall(self):
                return []

        class Connection:
            def cursor(self):
                return Cursor()

            def close(self):
                pass

        provider = EnligneProvider(
            self.integration(),
            session=Mock(),
            db_connect=lambda **kwargs: Connection(),
        )

        provider._lms_records(["LMS-100"])

        self.assertTrue(executed)
        self.assertTrue(all(statement.upper().startswith("SELECT ") for statement in executed))
