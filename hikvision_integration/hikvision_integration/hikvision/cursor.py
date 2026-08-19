from datetime import datetime, timedelta

import frappe
import pytz


CURSOR_OVERLAP_SECONDS = 60

# On a device's very first sync (no Hikvision Event stored yet for it),
# start from this fixed clock time today instead of "now". Without
# this, start_time and end_time both resolve to "now" a few
# milliseconds apart - an effectively zero-width query window that
# misses any scan that happened before you triggered the sync, no
# matter how recent.
FIRST_SYNC_START_HOUR = 7
FIRST_SYNC_START_MINUTE = 0


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
    now_site = now_utc.astimezone(site_tz)

    todays_start = now_site.replace(
        hour=FIRST_SYNC_START_HOUR,
        minute=FIRST_SYNC_START_MINUTE,
        second=0,
        microsecond=0,
    )

    # Safety: if it's currently earlier than 7am (sync runs before the
    # workday starts), don't request a start_time in the future - that
    # would put start_time after end_time and the device would return
    # nothing, or reject the query outright. Fall back to "now" in
    # that edge case only.
    if todays_start > now_site:
        return now_site.isoformat(timespec="seconds")

    return todays_start.isoformat(timespec="seconds")