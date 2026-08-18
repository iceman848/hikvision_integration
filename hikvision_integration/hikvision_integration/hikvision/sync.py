import frappe

from datetime import datetime, timezone

from .client import HikvisionClient
from .cursor import get_device_start_time, get_site_timezone
from .events import process_event


MAX_RESULTS = 30


def get_hikvision_settings():
    return frappe.get_single(
        "Hikvision Settings"
    )


def fetch_device_events(
    device,
    start_time,
    end_time,
):
    protocol = (
        device.protocol or "HTTP"
    ).lower()

    host = (
        f"{protocol}://{device.device_ip}"
    )

    client = HikvisionClient(
        host=host,
        username=device.username,
        password=device.get_password(
            "password"
        ),
    )

    return client.search_events(
        start_time=start_time,
        end_time=end_time,
        max_results=MAX_RESULTS,
    )


def process_device(device):
    """
    Synchronize one Hikvision device.
    """

    start_time = get_device_start_time(
        device
    )

    # Get an unambiguous current instant (UTC, timezone-aware by
    # construction), then convert it explicitly to the site's
    # configured timezone. This carries no assumption about what
    # frappe.utils.now_datetime() returns in any given version/config -
    # datetime.now(timezone.utc) is unambiguous on its own.
    site_tz = get_site_timezone()
    now_utc = datetime.now(timezone.utc)
    end_time = now_utc.astimezone(site_tz).isoformat(
        timespec="seconds"
    )

    events = fetch_device_events(
        device=device,
        start_time=start_time,
        end_time=end_time,
    )

    summary = {}

    for i, event in enumerate(
        events,
        start=1,
    ):

        try:

            result = process_event(
                device,
                event,
            )

        except Exception:

            frappe.log_error(
                frappe.get_traceback(),
                (
                    f"Hikvision event processing failed - "
                    f"{device.device_ip}"
                ),
            )

            result = "error"

        summary[result] = (
            summary.get(result, 0) + 1
        )

        if i % 20 == 0:
            frappe.db.commit()

    # Always commit at the end of this device's run - not just every 20
    # events mid-run. Without this, a LATER device failing in
    # sync_all_devices below would call frappe.db.rollback(), which is
    # NOT scoped to just that failing device - it would wipe out this
    # device's leftover uncommitted work too (anything processed since
    # the last i % 20 checkpoint).
    frappe.db.commit()

    skipped_no_status = summary.get(
        "skipped_no_status",
        0,
    )

    if skipped_no_status:

        frappe.log_error(
            (
                f"{skipped_no_status} event(s) from "
                f"{device.device_ip} had no attendanceStatus. "
                f"Check that Time & Attendance mode is "
                f"configured correctly on the Hikvision device."
            ),
            "Hikvision Sync - Missing Status",
        )

    return summary


def sync_all_devices():
    """
    Synchronize all configured Hikvision devices.
    """

    settings = get_hikvision_settings()

    results = {}

    for device in settings.devices:

        try:

            results[device.device_ip] = process_device(
                device
            )

        except Exception:

            frappe.log_error(
                frappe.get_traceback(),
                (
                    f"Hikvision sync failed: "
                    f"{device.device_ip}"
                ),
            )

            results[device.device_ip] = "Error"

            # Safe now: process_device always commits its own completed
            # work before returning or raising, so this rollback can
            # only ever discard this device's own not-yet-committed
            # attempt - never a previous device's already-saved data.
            frappe.db.rollback()

    frappe.db.commit()

    return results