from datetime import datetime, timedelta

import frappe
import pytz


CURSOR_OVERLAP_SECONDS = 60


def get_site_timezone():
    """
    The single source of truth for what timezone we treat all naive
    datetimes as being in - the Frappe site's configured System
    Settings timezone, NOT whatever the server OS happens to be set to.
    Relying on the OS timezone (via bare .astimezone()) breaks silently
    if the server and the site config ever disagree - common on
    containerized/cloud servers that default to UTC.
    """
    tz_name = frappe.utils.get_system_timezone()
    return pytz.timezone(tz_name)


def get_device_start_time(device):
    """
    Find the latest successfully stored Hikvision event for this device.

    A small overlap is deliberately applied to the cursor so that
    timestamp-boundary events are not missed.

    All conversions here are explicit against the site's configured
    timezone - never the ambient OS timezone.
    """
    site_tz = get_site_timezone()

    latest = frappe.db.get_value(
        "Hikvision Event",
        {"device": device.device_ip},
        ["event_date", "event_time"],
        order_by="event_date desc, event_time desc",
        as_dict=True,
    )

    if latest and latest.event_date and latest.event_time is not None:

        naive_combined = datetime.combine(
            frappe.utils.getdate(latest.event_date),
            (datetime.min + latest.event_time).time(),
        )

        # This naive datetime represents a moment in the site's
        # timezone (that's the convention Employee Checkin/Hikvision
        # Event were written under - see events.py). Localize it
        # explicitly rather than assuming the OS timezone matches.
        localized = site_tz.localize(naive_combined)

        localized -= timedelta(seconds=CURSOR_OVERLAP_SECONDS)

        return localized.isoformat(timespec="seconds")

    now_utc = datetime.now(pytz.utc)
    return now_utc.astimezone(site_tz).isoformat(timespec="seconds")