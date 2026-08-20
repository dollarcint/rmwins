"""Compatibility coverage after supplier quantity cleanup was retired."""

from django.test import SimpleTestCase

from .tasks import expire_allocation_reservations_task


class AllocationCleanupTaskEfficiencyTests(SimpleTestCase):
    def test_cleanup_is_a_database_free_compatibility_noop(self):
        self.assertEqual(
            expire_allocation_reservations_task.run(batch_size=3),
            {"expired": 0, "examined": 0, "disabled": True},
        )

    def test_periodic_cleanup_does_not_persist_a_celery_result(self):
        self.assertTrue(expire_allocation_reservations_task.ignore_result)
