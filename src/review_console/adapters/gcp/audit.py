"""GCP AuditSinkPort: Cloud Logging WORM bucket for sign-off events (SDK imports lazy).

The bucket is locked when the deployment states ``worm_locked = true`` (``infra/terraform``);
the variable has no default, so the lock is always a stated decision.
"""

from __future__ import annotations

from hex_service_kit.serialization import to_jsonable

from ...config import Settings
from ...ports.audit import AuditEvent


class CloudAuditAdapter:
    """Write already-redacted sign-off events to a Cloud Logging WORM sink.

    The ``google-cloud-logging`` import lives inside the method so the ``local`` / ``onprem``
    profiles import this module with no GCP SDK installed.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def record(self, event: AuditEvent) -> None:  # pragma: no cover - needs live GCP
        from google.cloud import logging as cloud_logging

        client = cloud_logging.Client()
        logger = client.logger("review-console-signoff")
        logger.log_struct(to_jsonable(event), severity="NOTICE")
