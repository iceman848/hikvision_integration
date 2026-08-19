from datetime import datetime

import frappe

from .cursor import get_site_timezone


def event_id(device, event):
    """
    Create a unique ERPNext identifier for a Hikvision event.
    """

    serial_no = event.get("serialNo")

    if not serial_no:
        return None

    return f"{device.device_ip}:{serial_no}"


def parse_event_time(event_time_str, site_tz):
    """
    The device sends an offset-aware ISO 8601 string, e.g.
    "2026-08-15T09:55:03+03:00". Parse it explicitly with its own
    offset, convert to the site's configured timezone, then drop the
    tzinfo - matching the naive-local convention Frappe datetimes use
    for storage. This avoids relying on frappe.utils.get_datetime()'s
    undocumented handling of offset-aware strings, which may or may not
    convert correctly depending on the Frappe version.
    """
    aware = datetime.fromisoformat(event_time_str)

    if aware.tzinfo is None:
        # Device didn't send an offset at all - nothing to convert,
        # treat as already being in site time (verify this assumption
        # holds for your device's actual configuration).
        return aware

    converted = aware.astimezone(site_tz)
    return converted.replace(tzinfo=None)


def process_event(device, event):
    """
    Process one Hikvision event.

    The Hikvision Event acts as the concurrency gate.

    If the event already exists, no second Employee Checkin
    is created.

    If Employee Checkin creation fails, the Hikvision Event
    is rolled back so the event can be retried.
    """

    employee_no = (
        event.get("employeeNoString")
        or event.get("employeeNo")
    )

    event_time = event.get("time")

    if not employee_no or not event_time:
        return "skipped_non_personnel"

    status = event.get("attendanceStatus")

    if status not in ("checkIn", "checkOut"):
        return "skipped_no_status"

    serial_no = event.get("serialNo")

    if not serial_no:
        return "skipped_no_serial"

    current_event_id = event_id(
        device,
        event,
    )

    if not current_event_id:
        return "skipped_no_event_id"

    # ---------------------------------------------------------
    # EMPLOYEE MAPPING
    # ---------------------------------------------------------

    employee = frappe.db.get_value(
        "Employee",
        {
            "hikvision_employee_id": employee_no
        },
        "name",
    )

    if not employee:

        frappe.log_error(
            (
                f"Hikvision Employee ID {employee_no} "
                f"was not found in ERPNext."
            ),
            "Hikvision Employee Mapping",
        )

        return "skipped_no_employee"

    # ---------------------------------------------------------
    # EVENT TIME - explicit timezone conversion, not ambient
    # ---------------------------------------------------------

    site_tz = get_site_timezone()
    checkin_time = parse_event_time(event_time, site_tz)

    log_type = (
        "IN"
        if status == "checkIn"
        else "OUT"
    )

    # ---------------------------------------------------------
    # SAVEPOINT
    # ---------------------------------------------------------

    savepoint_name = "hikvision_event"

    frappe.db.savepoint(
        savepoint_name
    )

    # ---------------------------------------------------------
    # CREATE HIKVISION EVENT
    # ---------------------------------------------------------

    try:

        frappe.get_doc(
            {
                "doctype": "Hikvision Event",
                "event_id": current_event_id,
                "device": device.device_ip,
                "employee_hikvision_id": employee_no,
                "employee_name": event.get(
                    "name",
                    "",
                ),
                "event_date": checkin_time.date(),
                "event_time": checkin_time.time(),
                "status": status,
                "serial_no": serial_no,
            }
        ).insert(
            ignore_permissions=True
        )

    except (
        frappe.DuplicateEntryError,
        frappe.UniqueValidationError,
    ):
        # event_id is a unique FIELD (not the document's name/primary
        # key), so Frappe raises UniqueValidationError on a collision
        # here - DuplicateEntryError is what gets raised for a
        # duplicate document *name* instead, which isn't this case.
        # Catching both covers either path correctly.

        frappe.db.rollback(
            save_point=savepoint_name
        )

        return "skipped_duplicate_event"

    except Exception:

        frappe.db.rollback(
            save_point=savepoint_name
        )

        raise

    # ---------------------------------------------------------
    # CREATE EMPLOYEE CHECKIN
    # ---------------------------------------------------------

    try:

        frappe.get_doc(
            {
                "doctype": "Employee Checkin",
                "employee": employee,
                "time": checkin_time,
                "log_type": log_type,
            }
        ).insert(
            ignore_permissions=True
        )

    except Exception:

        frappe.db.rollback(
            save_point=savepoint_name
        )

        raise

    return "processed"