import requests, json, datetime as dt
from utils import Config, mk_route, get_dt, wrt_dt, get, post, head, DtJsonDecoder, DtJsonEncoder, intern_results


def get_an_events(conf: Config, params: dict = {}) -> list[dict]:
    """
    Query the action network API.
    """
    endpt = mk_route(conf["an-base"], "events", "")
    rslt = get(endpt, params=params, headers=conf["an-headers"])

    rslt.raise_for_status()

    conf.last_an_fetch = dt.datetime.now()

    rslt = rslt.json(cls=DtJsonDecoder)
    return rslt["_embedded"]["osdi:events"]


def prepare_an_event(event: dict) -> dict:
    """
    Prepare a raw result from the action network API to be sent to the
    google api.
    """
    out = dict()
    out["id"] = event["identifiers"][0].removeprefix("action_network:").replace("-", "")
    out["start"] = { "dateTime": event["start_date"],
                     "timeZone": "US/Eastern" }
    out["end"]   = { "dateTime": event["start_date"] + dt.timedelta(hours=2),
                     "timeZone": "US/Eastern" }
    out["summary"] = event["title"]
    out["description"] = event["description"]
    out["extendedProperties"] = {}
    out["extendedProperties"]["private"] = {"action-network-id": event["identifiers"][0]}
    out["extendedProperties"]["shared"] = {}

    if (loc := ', '.join(event.get("address_lines", []))):
        out["location"] = loc

    return out


def save_an_events(conf: Config, events: list[dict]) -> list[str]:
    """
    Commit an Action Network query to the database.
    """
    prepared = [prepare_an_event(e) for e in events]
    return intern_results(prepared, "id", conf["db-file"])


# use a head request to check whether an event with that id already exists
def check_id_collision(conf: Config, e_id: str) -> bool:
    endpt = mk_route(conf["google-base"], "calendars", conf["google-cal-id"], "events", c_id)
    resp = head(endpt, headers=conf.g_headers, params=conf.g_params)

    return not resp.ok


# add a single google event
def add_google_event(conf: Config, event: dict) -> dict:
    endpt = mk_route(conf["google-base"], "calendars", conf["google-cal-id"], "events")
    headers = conf["google-headers"]
    params = conf["google-params"] | { "sendUpdates": "none" }
    event = DtJsonEncoder(fmt="%Y-%m-%dT%H:%M:%S").prepare(event)
    event = {k:v for k,v in event.items() if k != "id"}
    rslt = requests.post(endpt, headers=headers, params=params, json=event)

    rslt.raise_for_status()

    return rslt.json(cls=DtJsonDecoder)
