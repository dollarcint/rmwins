"""Focused regression tests for allocation-cleanup task efficiency."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from .models import AllocationReservation
from .tasks import expire_allocation_reservations_task


class AllocationCleanupTaskEfficiencyTests(SimpleTestCase):
    @patch("vendors.tasks.expire_reservation")
    @patch("vendors.tasks.AllocationReservation.objects.filter")
    def test_cleanup_loads_the_batch_once_without_refetching_each_row(
        self,
        filter_reservations,
        expire_reservation,
    ):
        references = [Mock(pk=1), Mock(pk=2), Mock(pk=3)]
        queryset = filter_reservations.return_value
        queryset.order_by.return_value.only.return_value.__getitem__.return_value = references
        expire_reservation.return_value = SimpleNamespace(
            status=AllocationReservation.Status.EXPIRED,
        )

        result = expire_allocation_reservations_task.run(batch_size=3)

        self.assertEqual(filter_reservations.call_count, 1)
        self.assertEqual(expire_reservation.call_count, 3)
        self.assertEqual(result, {"expired": 3, "examined": 3})

    def test_periodic_cleanup_does_not_persist_a_celery_result(self):
        self.assertTrue(expire_allocation_reservations_task.ignore_result)
