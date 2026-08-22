"""GCP AuditSinkPort: Cloud Logging locked WORM bucket for sign-off events (SDK imports lazy)."""

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
