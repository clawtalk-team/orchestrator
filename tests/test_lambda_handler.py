"""Tests for lambda_handler event routing."""

from unittest.mock import MagicMock, patch


def test_scheduled_event_calls_k8s_poller():
    """Scheduled EventBridge events route to poll_k8s_container_statuses."""
    event = {"source": "aws.events", "detail-type": "Scheduled Event"}
    context = MagicMock()

    with patch("lambda_handler.poll_k8s_container_statuses", return_value={"processed": 3, "errors": 0}) as mock_poll:
        from lambda_handler import handler
        result = handler(event, context)

    mock_poll.assert_called_once()
    assert result["statusCode"] == 200
    assert "k8s poll complete" in result["body"]


def test_ecs_event_calls_handle_task_event():
    """ECS task state change events route to handle_task_event."""
    event = {"source": "aws.ecs", "detail-type": "ECS Task State Change", "detail": {}}
    context = MagicMock()

    with patch("lambda_handler.handle_task_event") as mock_handle:
        from lambda_handler import handler
        result = handler(event, context)

    mock_handle.assert_called_once_with(event)
    assert result["statusCode"] == 200


def test_k8s_provision_event_calls_provision_pod():
    """Async k8s provision self-invocation events route to provision_pod."""
    from app.services.kubernetes import PROVISION_EVENT_SOURCE, PROVISION_EVENT_TYPE

    detail = {"container_id": "oc-test", "user_id": "user-1"}
    event = {"source": PROVISION_EVENT_SOURCE, "detail-type": PROVISION_EVENT_TYPE, "detail": detail}
    context = MagicMock()

    with patch("lambda_handler.provision_pod") as mock_provision:
        from lambda_handler import handler
        result = handler(event, context)

    mock_provision.assert_called_once_with(detail)
    assert result["statusCode"] == 200
