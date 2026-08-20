"""Regression coverage for explicit nullable timestamp ordering on PostgreSQL."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from .models import Survey, SurveyAttempt
from .provider_services import refresh_client_integration_details
from .tasks import _stale_surveys
from .views import (
    NullsLastOrderingFilter,
    SurveyAttemptViewSet,
    SurveyViewSet,
    _latest_callback_first,
)


class PostgreSQLNullOrderingTests(SimpleTestCase):
    def test_survey_api_default_places_unknown_modified_dates_last(self):
        model_modified, model_created = Survey._meta.ordering
        modified_order, created_order = SurveyViewSet.ordering

        self.assertTrue(model_modified.descending)
        self.assertTrue(model_modified.nulls_last)
        self.assertTrue(model_created.descending)
        self.assertTrue(modified_order.descending)
        self.assertTrue(modified_order.nulls_last)
        self.assertTrue(created_order.descending)

    def test_termination_report_places_unknown_callback_dates_last(self):
        queryset = _latest_callback_first(SurveyAttempt.objects.all())
        callback_order, initiated_order = queryset.query.order_by

        self.assertTrue(callback_order.descending)
        self.assertTrue(callback_order.nulls_last)
        self.assertTrue(initiated_order.descending)

    def test_interactive_attempt_sort_places_nullable_values_last(self):
        request = SimpleNamespace(query_params={"ordering": "-callback_at"})
        queryset = NullsLastOrderingFilter().filter_queryset(
            request,
            SurveyAttempt.objects.all(),
            SurveyAttemptViewSet(),
        )

        (callback_order,) = queryset.query.order_by
        self.assertTrue(callback_order.descending)
        self.assertTrue(callback_order.nulls_last)

    def test_interactive_survey_created_sort_places_unknown_dates_last(self):
        request = SimpleNamespace(query_params={"ordering": "source_created_at"})
        queryset = NullsLastOrderingFilter().filter_queryset(
            request,
            Survey.objects.all(),
            SurveyViewSet(),
        )

        (created_order,) = queryset.query.order_by
        self.assertFalse(created_order.descending)
        self.assertTrue(created_order.nulls_last)

    @patch("surveys.tasks.Survey.objects.filter")
    def test_periodic_detail_queue_has_explicit_null_ordering(self, filter_surveys):
        live = filter_surveys.return_value
        stale = live.filter.return_value
        stale.order_by.return_value.__getitem__.return_value = []

        self.assertEqual(_stale_surveys(SimpleNamespace(), 10), [])

        detail_order, modified_order = stale.order_by.call_args.args
        self.assertTrue(detail_order.nulls_first)
        self.assertFalse(detail_order.descending)
        self.assertTrue(modified_order.nulls_last)
        self.assertTrue(modified_order.descending)

    @patch("surveys.provider_services.get_provider")
    @patch("surveys.provider_services.Survey.objects.filter")
    def test_enligne_detail_queue_places_never_synced_rows_first(
        self,
        filter_surveys,
        get_provider,
    ):
        ordered = filter_surveys.return_value.order_by.return_value
        ordered.__getitem__.return_value = []
        integration = SimpleNamespace(
            is_active=True,
            provider_code="enligne",
            config={},
            detail_refresh_batch=10,
        )

        result = refresh_client_integration_details(integration)

        detail_order, primary_key_order = filter_surveys.return_value.order_by.call_args.args
        self.assertTrue(detail_order.nulls_first)
        self.assertFalse(detail_order.descending)
        self.assertEqual(primary_key_order, "pk")
        self.assertEqual(result, {"refreshed": 0, "failures": 0})
        get_provider.return_value.close.assert_called_once_with()

    @patch("surveys.provider_services.get_provider")
    @patch("surveys.provider_services.Survey.objects.filter")
    def test_other_detail_queue_places_unknown_modified_dates_last(
        self,
        filter_surveys,
        get_provider,
    ):
        unsynced = Mock()
        filter_surveys.return_value.filter.return_value = unsynced
        unsynced.order_by.return_value = []
        integration = SimpleNamespace(
            is_active=True,
            provider_code="rfg",
            config={},
            detail_refresh_batch=10,
        )

        result = refresh_client_integration_details(integration)

        modified_order, primary_key_order = unsynced.order_by.call_args.args
        self.assertTrue(modified_order.descending)
        self.assertTrue(modified_order.nulls_last)
        self.assertEqual(primary_key_order, "pk")
        self.assertEqual(result, {"refreshed": 0, "failures": 0})
        get_provider.return_value.close.assert_called_once_with()
