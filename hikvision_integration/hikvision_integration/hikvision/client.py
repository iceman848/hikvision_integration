import uuid

import requests
from requests.auth import HTTPDigestAuth


class HikvisionClient:
    def __init__(self, host, username, password):
        self.host = host.rstrip("/")
        self.auth = HTTPDigestAuth(username, password)

    def get(self, endpoint):
        url = f"{self.host}{endpoint}"

        response = requests.get(
            url,
            auth=self.auth,
            timeout=15,
        )

        response.raise_for_status()

        return response.json()

    def search_events(self, start_time, end_time, max_results=30):

        url = f"{self.host}/ISAPI/AccessControl/AcsEvent?format=json"

        # Each synchronization/search operation gets its own search ID.
        # This prevents two overlapping synchronizations from sharing
        # the same Hikvision search session.
        search_id = str(uuid.uuid4())

        position = 0
        events = []

        while True:
            payload = {
                "AcsEventCond": {
                    "searchID": search_id,
                    "searchResultPosition": position,
                    "maxResults": max_results,
                    "major": 0,
                    "minor": 0,
                    "startTime": start_time,
                    "endTime": end_time,
                }
            }

            response = requests.post(
                url,
                json=payload,
                auth=self.auth,
                timeout=15,
            )

            response.raise_for_status()

            data = response.json()

            info = data.get("AcsEvent", {})

            batch = info.get("InfoList") or []

            num_matches = int(
                info.get("numOfMatches") or 0
            )

            total_matches = int(
                info.get("totalMatches") or 0
            )

            # Add this page to the complete result set.
            events.extend(batch)

            # Nothing was returned - definitely done.
            if num_matches == 0:
                break

            # Move to the next page.
            position += num_matches

            # responseStatusStrg is deliberately NOT used to decide
            # whether to stop paginating - its per-page meaning isn't
            # reliably documented across firmware versions, and relying
            # on it caused a real bug (stopping after page 1 on "OK"
            # even when more pages existed). These two checks below are
            # the actual documented completion signals: either we've
            # reached the reported total, or this page came back short
            # (fewer than we asked for, meaning it was the last one).
            if total_matches and position >= total_matches:
                break

            if num_matches < max_results:
                break

        return events