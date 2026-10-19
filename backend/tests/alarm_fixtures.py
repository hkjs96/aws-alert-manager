"""Fixtures for alarms the engine created (they carry JSON metadata in AlarmDescription).

`identify_alarm()` only claims an alarm when its description carries our metadata, so any
fixture that stands for one of OUR alarms must be built with these helpers. The description is
built with the production builder so the format never drifts.
"""

from common.alarm_naming import _build_alarm_description


def managed_description(resource_type, resource_id, metric_key, severity=""):
    """AlarmDescription exactly as the engine writes it."""
    return _build_alarm_description(
        resource_type, resource_id, metric_key,
        f"Auto-created by AWS Monitoring Engine for {resource_type} {resource_id}",
        severity=severity,
    )


def managed_alarm(name, resource_type, resource_id, metric_key="CPUUtilization", severity="", **extra):
    """describe_alarms-style dict for one of our alarms. `resource_id` is the FULL id (ARN for ALB/NLB/TG)."""
    alarm = {
        "AlarmName": name,
        "AlarmDescription": managed_description(resource_type, resource_id, metric_key, severity),
    }
    alarm.update(extra)
    return alarm


def managed_put_kwargs(name, resource_type, resource_id, metric_key="CPUUtilization", severity="", **kwargs):
    """kwargs for moto `put_metric_alarm` creating one of our alarms."""
    return {
        "AlarmName": name,
        "AlarmDescription": managed_description(resource_type, resource_id, metric_key, severity),
        **kwargs,
    }
