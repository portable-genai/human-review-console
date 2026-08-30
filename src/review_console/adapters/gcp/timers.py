"""GCP TimerPort: Cloud Tasks deadline timers (SDK imports lazy).

Schedules an HTTP task that fires at the clock's deadline and calls the service back to
re-evaluate the case, so a breach is acted on even if nothing polls. The queue, the callback URL
and the invoker service account come from the environment (set on the Cloud Run service by
``infra/terraform``); the task name is deterministic (derived from tenant + case + clock) so a
reschedule REPLACES rather than duplicates. The ``google-cloud-tasks`` import lives inside each
method so the offline / onprem profiles import this module with no GCP SDK installed.
"""

from __future__ import annotations

import contextlib
import re
from datetime import datetime
from typing import Any

from hex_service_kit.netdefaults import read_env_setting

from ...config import Settings


def _env(name: str) -> str:
    """A required Cloud Tasks setting. Unset and EMPTIED both refuse, which is one direction.

    Both states are closed here, so a single branch is honest: there is no default for this read
    to inherit, and an adapter that cannot name its queue must not run.
    """
    setting = read_env_setting(name)
    if not setting.has_value:  # pragma: no cover - needs live GCP config
        raise RuntimeError(f"{name} must be set for the Cloud Tasks timer adapter")
    return setting.value


def _task_id(tenant: str, case_id: str, clock: str) -> str:
    """A deterministic, Cloud-Tasks-safe task id (so a reschedule replaces the same task)."""
    raw = f"{tenant}--{case_id}--{clock}"
    return re.sub(r"[^A-Za-z0-9_-]", "-", raw)[:500]


class CloudTasksTimerAdapter:
    """Schedule deadline timers as Cloud Tasks (asia-southeast1)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _task_name(
        self, client: Any, tenant: str, case_id: str, clock: str
    ) -> str:  # pragma: no cover
        parent: str = client.queue_path(
            _env("REVIEW_GCP_PROJECT"), self._settings.region, _env("REVIEW_TASKS_QUEUE")
        )
        return f"{parent}/tasks/{_task_id(tenant, case_id, clock)}"

    def schedule(  # pragma: no cover - needs live GCP
        self, *, tenant: str, case_id: str, clock: str, fire_at: datetime
    ) -> None:
        from google.cloud import tasks_v2
        from google.protobuf import timestamp_pb2

        client = tasks_v2.CloudTasksClient()
        name = self._task_name(client, tenant, case_id, clock)
        parent = name.rsplit("/tasks/", 1)[0]

        schedule_time = timestamp_pb2.Timestamp()
        schedule_time.FromDatetime(fire_at)

        callback = _env("REVIEW_TIMER_CALLBACK_URL").rstrip("/")
        task = {
            "name": name,
            "schedule_time": schedule_time,
            "http_request": {
                "http_method": tasks_v2.HttpMethod.POST,
                "url": f"{callback}/v1/cases/{case_id}/evaluate",
                "headers": {"X-Case-Tenant": tenant, "X-Case-Clock": clock},
                "oidc_token": {"service_account_email": _env("REVIEW_TASKS_INVOKER_SA")},
            },
        }
        # An existing task with this name means the clock was already scheduled: replace it.
        # A not-found on delete is fine; we are (re)creating it next.
        with contextlib.suppress(Exception):
            client.delete_task(name=name)
        # The client accepts a mapping at runtime through protobuf-plus, and its own signature
        # says Task. Constructing the message is the honest reading of that signature, and it
        # also means a key this API does not define fails HERE rather than at the far end of a
        # call nothing in the offline gate can make.
        client.create_task(parent=parent, task=tasks_v2.Task(task))

    def cancel(  # pragma: no cover - needs live GCP
        self, *, tenant: str, case_id: str, clock: str
    ) -> None:
        from google.cloud import tasks_v2

        client = tasks_v2.CloudTasksClient()
        name = self._task_name(client, tenant, case_id, clock)
        # A timer that already fired or never existed is fine to "cancel".
        with contextlib.suppress(Exception):
            client.delete_task(name=name)
