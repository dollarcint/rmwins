"""Compatibility task names retained after quantity reservations were removed."""

from celery import shared_task


@shared_task(name="vendors.expire_allocation_reservations", ignore_result=True)
def expire_allocation_reservations_task(batch_size=500):
    return {"expired": 0, "examined": 0, "disabled": True}
