"""Performance test TC-Perf-01: emergency allocation <= 3 s for 95% of requests (OT-NF-001 / OTMS-12)."""
import time
from datetime import datetime, timedelta

from app.models.models import PriorityEnum, Surgery, SurgeryStatusEnum, Theatre
from app.schemas.emergency import EmergencyCreate
from app.services.emergency_service import EmergencyService


def test_tc_perf_01_emergency_allocation_p95_under_3_seconds(db_session):
    base = datetime(2026, 11, 20, 8, 0)
    theatres = [Theatre(name=f"Perf-OT-{i}") for i in range(1, 6)]
    db_session.add_all(theatres)
    db_session.flush()

    routines = []
    for t in theatres:
        for k in range(100):
            start = base + timedelta(hours=2 * k)
            routines.append(
                Surgery(
                    patient_name=f"Routine-{t.theatre_id}-{k}",
                    theatre_id=t.theatre_id,
                    start_time=start,
                    end_time=start + timedelta(hours=2),
                    priority=PriorityEnum.routine,
                    status=SurgeryStatusEnum.scheduled,
                )
            )
    db_session.add_all(routines)
    db_session.commit()

    service = EmergencyService(db_session)
    latencies = []
    for i in range(100):
        t_id = theatres[i % 5].theatre_id
        start = base + timedelta(hours=2 * i)
        payload = EmergencyCreate(
            patient_name=f"Emergency-{i}",
            theatre_id=t_id,
            start_time=start,
            end_time=start + timedelta(hours=1),
            priority=PriorityEnum.critical,
        )
        t0 = time.perf_counter()
        service.log_and_process_emergency(payload)
        latencies.append(time.perf_counter() - t0)

    latencies.sort()
    p95 = latencies[int(len(latencies) * 0.95) - 1]
    assert p95 <= 3.0, f"p95 latency {p95:.3f}s exceeded 3.0s limit"
