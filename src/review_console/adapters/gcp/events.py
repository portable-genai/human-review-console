"""GCP EventPublisherPort: Pub/Sub case-lifecycle events (SDK imports lazy).

Publishes a content-free event (the event type, ids and decision attributes, never raw case
content) to the lifecycle topic, so downstream verticals and the console's own queue (on
``case.escalated``) can react. The topic comes from the environment (set by ``infra/terraform``).
The ``google-cloud-pubsub`` import lives inside the method so the offline / onprem profiles import
this module with no GCP SDK installed.
"""

from __future__ import annotations

from hex_service_kit.netdefaults import read_env_setting

from ...config import Settings


class PubSubEventPublisher:
    """Publish content-free case events to a Pub/Sub topic."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def publish(  # pragma: no cover - needs live GCP
        self, *, event_type: str, tenant: str, case_id: str, attributes: dict[str, str]
    ) -> None:
        from google.cloud import pubsub_v1

        project = read_env_setting("REVIEW_GCP_PROJECT")
        topic = read_env_setting("REVIEW_EVENTS_TOPIC")
        if not project.has_value or not topic.has_value:
            raise RuntimeError(
                "REVIEW_GCP_PROJECT and REVIEW_EVENTS_TOPIC must be set for the Pub/Sub publisher"
            )

        publisher = pubsub_v1.PublisherClient()
        topic_path = publisher.topic_path(project.value, topic.value)
        # The message body is content-free (the event type); ids + decision attributes travel as
        # Pub/Sub attributes so a subscriber can filter without parsing a payload.
        publisher.publish(
            topic_path,
            event_type.encode("utf-8"),
            event_type=event_type,
            tenant=tenant,
            case_id=case_id,
            **{k: str(v) for k, v in attributes.items()},
        ).result()
