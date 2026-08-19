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


def process_device(
    device,
    end_time,
):
    """
    Synchronize one Hikvision device.

    The end_time is supplied by sync_all_devices()
    so that all devices use the same synchronization
    boundary.
    """

    start_time = get_device_start_time(
        device
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

    # Always commit at the end of this device's run.
    #
    # This ensures that if a later device fails and
    # sync_all_devices() rolls back, this device's
    # successfully processed events are already saved.
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


def update_last_sync_of_checkin(sync_end_time):
    """
    Update Last Sync of Checkin for all Shift Types
    that have Auto Attendance enabled.

    This is called only after all configured Hikvision
    devices have synchronized successfully.
    """

    frappe.db.sql(
        """
        UPDATE `tabShift Type`
        SET last_sync_of_checkin = %s
        WHERE enable_auto_attendance = 1
        """,
        sync_end_time,
    )


def sync_all_devices():
    """
    Synchronize all configured Hikvision devices.

    All devices use the same sync_end_time.

    Last Sync of Checkin is updated only when every
    configured device completes successfully.
    """

    settings = get_hikvision_settings()

    results = {}

    # Create ONE synchronization boundary for all devices.
    #
    # This means Device 1 and Device 2 are both queried
    # up to exactly the same point in time.
    site_tz = get_site_timezone()

    now_utc = datetime.now(timezone.utc)

    sync_end_time = now_utc.astimezone(
        site_tz
    ).strftime("%Y-%m-%d %H:%M:%S")


    all_devices_successful = True

    for device in settings.devices:

        try:

            results[device.device_ip] = process_device(
                device,
                sync_end_time,
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

            all_devices_successful = False

            # Safe because process_device() commits its
            # completed work before returning or raising.
            frappe.db.rollback()

    # Only advance Last Sync of Checkin if ALL devices
    # completed successfully.
    #
    # This prevents Auto Attendance from believing that
    # all biometric devices have been synchronized when
    # one of them actually failed.
    if all_devices_successful and settings.devices:

        update_last_sync_of_checkin(
            sync_end_time
        )

    frappe.db.commit()

    return results
