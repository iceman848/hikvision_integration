import os
import json
import time
from datetime import datetime

import requests
from requests.auth import HTTPDigestAuth


# ---------------------------------------------------------------------------
# DEVICES - add one entry per Hikvision terminal
# ---------------------------------------------------------------------------
DEVICES = [
    {
        "host": os.environ["HIKVISION_1_HOST"],
        "username": os.environ["HIKVISION_1_USERNAME"],
        "password": os.environ["HIKVISION_1_PASSWORD"],
    },
    {
        "host": os.environ["HIKVISION_2_HOST"],
        "username": os.environ["HIKVISION_2_USERNAME"],
        "password": os.environ["HIKVISION_2_PASSWORD"],
    },
]

POLL_INTERVAL_SECONDS = 5
MAX_RESULTS = 30
SEEN_ID_CACHE_SIZE = 500   # per device, how many recent event IDs to remember
LOG_FILE = "checkins_log.json"  # array of objects, rewritten after every loop

checkin_log = []  # in-memory array of objects, mirrored to LOG_FILE


def create_session(dev):
    session = requests.Session()
    session.auth = HTTPDigestAuth(dev["username"], dev["password"])
    session.headers.update({"Connection": "close"})
    return session


def fetch_events(session, host, start_time, end_time):
    url = f"{host}/ISAPI/AccessControl/AcsEvent?format=json"
    position = 0
    events = []

    while True:
        body = {
            "AcsEventCond": {
                "searchID": str(int(time.time() * 1000)),
                "searchResultPosition": position,
                "maxResults": MAX_RESULTS,
                "major": 0,
                "minor": 0,
                "startTime": start_time,
                "endTime": end_time,
            }
        }
        response = session.post(url, json=body, timeout=10)
        response.raise_for_status()
        data = response.json()

        info = data.get("AcsEvent", {})
        batch = info.get("InfoList", [])
        events.extend(batch)

        num_matches = info.get("numOfMatches", 0)
        total = info.get("totalMatches", 0)
        position += num_matches

        if num_matches < MAX_RESULTS or position >= total:
            break

    return events


def build_device_state():
    """One session + one polling cursor + one dedup cache per device."""
    start_time = datetime.now().astimezone().isoformat(timespec="seconds")

    state = {}
    for dev in DEVICES:
        session = create_session(dev)
        dev_id = dev["host"].replace("http://", "").replace("https://", "")
        state[dev_id] = {
            "config": dev,
            "session": session,
            "last_time": start_time,
            "seen_ids": [],
        }
    return state


device_state = build_device_state()

print(f"Polling {len(DEVICES)} device(s) every {POLL_INTERVAL_SECONDS}s")

while True:
    loop_start = datetime.now().astimezone()
    end_time = loop_start.isoformat(timespec="seconds")

    for dev_id, st in device_state.items():
        dev = st["config"]

        try:
            events = fetch_events(st["session"], dev["host"], st["last_time"], end_time)
        except requests.RequestException as e:
            print(f"[{dev_id}] Poll failed:", e)
            st["session"] = create_session(dev)  # drop the stale connection, start fresh next loop
            continue  # leave last_time as-is, retry this window next loop

        for ev in events:
            emp_no = ev.get("employeeNoString") or ev.get("employeeNo")
            ev_time = ev.get("time")
            name = ev.get("name", "")

            if not emp_no or not ev_time:
                continue  # non-personnel event (door alarm, tamper, etc.)

            # Compound key: serialNo alone is only unique WITHIN one device,
            # so prefix it with the device id to keep cross-device events distinct.
            raw_serial = ev.get("serialNo") or (emp_no + ev_time)
            event_id = f"{dev_id}:{raw_serial}"

            if event_id in st["seen_ids"]:
                continue

            # ev_time comes back like "2026-08-15T09:55:03+03:00" - split
            # it into separate date and time fields.
            parsed = datetime.fromisoformat(ev_time)
            # Only populated if the device's Time & Attendance mode is
            # configured with status rules (checkIn/checkOut/breakOut/etc).
            # Common raw values: "checkIn", "checkOut", "breakOut", "breakIn",
            # "overtimeIn", "overtimeOut". Falls back to "unknown" if the
            # device isn't sending it.
            status = ev.get("attendanceStatus", "unknown")

            record = {
                "device": dev_id,
                "employee": emp_no,
                "name": name,
                "date": parsed.date().isoformat(),   # "2026-08-15"
                "time": parsed.time().isoformat(),   # "09:55:03"
                "status": status,
                "serial_no": raw_serial,              # device's own event serial number
                "event_id": event_id,                
            }

            print(json.dumps(record))
            checkin_log.append(record)
            st["seen_ids"].append(event_id)

        st["seen_ids"][:] = st["seen_ids"][-SEEN_ID_CACHE_SIZE:]
        st["last_time"] = end_time

    if checkin_log:
        with open(LOG_FILE, "w") as f:
            json.dump(checkin_log, f, indent=2)

    elapsed = (datetime.now().astimezone() - loop_start).total_seconds()
    time.sleep(max(0, POLL_INTERVAL_SECONDS - elapsed))