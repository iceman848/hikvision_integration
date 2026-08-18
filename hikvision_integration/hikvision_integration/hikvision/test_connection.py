import os

from .client import HikvisionClient


client = HikvisionClient(
    host= os.environ["HIKVISION_HOST"],
    username=os.environ["HIKVISION_USERNAME"],
    password=os.environ["HIKVISION_PASSWORD"],
)


events = client.search_events(
    start_time="2026-08-14T00:00:00+03:00",
    end_time="2026-08-14T23:59:59+03:00",
    max_results=30,
)


print("Total events retrieved:", len(events))

for event in events:
    print(event)