"""Celery maintenance tasks for abandoned allocation reservations."""

from celery import shared_task
from django.utils import timezone

from .models import AllocationReservation
from .services import expire_reservation


@shared_task(name="vendors.expire_allocation_reservations", ignore_result=True)
def expire_allocation_reservations_task(batch_size=500):
    reservations = list(
        AllocationReservation.objects.filter(
            status=AllocationReservation.Status.RESERVED,
            expires_at__lte=timezone.now(),
        )
        .order_by("expires_at")
        .only("id")[:batch_size]
    )
    expired = 0
    for reservation in reservations:
        locked = expire_reservation(reservation)
        expired += int(locked.status == AllocationReservation.Status.EXPIRED)
    return {"expired": expired, "examined": len(reservations)}
