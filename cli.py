import sys, os, re, time, requests, jwt, json, datetime as dt, random as rand, argparse as ap, pprint as pp
from dateutil.parser import parse as du_parse
from typing import Union, Callable, Optional, Iterable, AnyStr
from functools import lru_cache, singledispatch, wraps, cached_property
from urllib.parse import urljoin, urlencode


JSONObject = Union[dict,list,tuple,str,int,float,bool,None,dt.datetime]
HTTPObject = JSONObject

"""
General utilities.
"""


def get_ts() -> int:
    return int(time.time())


def get_dt(o=None,/) -> dt.datetime:
    if o is None:
        return dt.datetime.now()

    elif isinstance(o, dt.datetime):
        return o

    else:
        return get_cached_dt(o,fmt)


def wrt_dt(d, fmt: Optional[str] = None) -> str:
    if fmt is None:
        return d.isoformat(sep="T", timespec="seconds")

    else:
        return d.strftime(fmt)


def try_dt(d):
    try:
        return get_dt(d)

    except:
        return d


@lru_cache
def get_cached_dt(o) -> dt.datetime:
    if isinstance(o, float):
        return dt.datetime.fromtimestamp(int(o))

    elif isinstance(o, int):
        return dt.datetime.fromtimestamp(o)

    else:
        return du_parse(o)


@singledispatch
def mk_route(base, *args):
    raise NotImplementedError


@mk_route.register
def _(base: bytes, *args):
    return urljoin(base, b"/".join(args))


@mk_route.register
def _(base: str, *args):
    return urljoin(base, "/".join(args))


def simple_dt_reader(o: dict) -> dict:
    for k, v in o.items():
        if isinstance(v, str):
            try:
                x = du_parse(v)
                o[k] = x

            except:
                pass

        elif isinstance(v, dict):
            o[k] = simple_dt_reader(v)

    return o


def load_conf(fnm: str) -> dict:
    with open(fnm) as conf:
        conf_d = json.load(conf, object_hook=simple_dt_reader)

    return conf_d


def save_conf(conf: dict, fnm: str):
    with open(fnm, "w") as conf_file:
        json.dump(conf, conf_file, default=wrt_dt)

    return


def an_api_call(fun):
    @wraps(fun)
    def wrapper(conf: dict, *args, **kwargs):
        local_conf = {"headers": {"OSDI-API-Token": conf["an-key"]}} | conf
        return fun(local_conf, *args, **kwargs)

    return wrapper


def google_api_call(fun):
    @wraps(fun)
    def wrapper(conf: dict, *args, **kwargs):
        """
        Like the an_api_call wrapper this wrapper adds default headers and parameters
        to the config dictionary, but it also ensures the google authorization token is up
        to date.
        """
        # breakpoint()
        if get_dt() > conf["google-token-expires"]:
            with open(conf["google-pem-file"]) as pf:
                contents = json.load(pf)
                pem = contents["private_key"].encode('utf8')

            # bunch of bullshit to put together the jwt
            ts      = get_ts()
            aud     = "https://oauth2.googleapis.com/token"
            headers = { "typ": "JWT", "alg": "RS256"}
            payload = { "iss": conf["google-service-email"],
                        "scope": conf["google-auth-scope"],
                        "aud": aud,
                        "iat": ts,
                        "exp": ts + 3600,
                       }

            enc = jwt.encode(payload, pem, algorithm="RS256", headers=headers)

            # making the request
            params = {"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": enc}
            rslt = requests.post(aud, params=params)

            # raise an error if it failed
            rslt.raise_for_status()

            rslt = rslt.json()
            conf["google-access-token"] = rslt["access_token"]
            conf["google-token-expires"] = get_dt() + dt.timedelta(seconds=rslt["expires_in"])

        local_conf = conf | {"headers": {"Authorization": f"Bearer {conf['google-access-token']}"},
                             "params": {"scope": conf["google-auth-scope"]}}

        return fun(local_conf, *args, **kwargs)

    return wrapper


@an_api_call
def get_an_events(conf: dict, **query) -> list[dict]:
    """
    Query the action network API.
    """
    endpt = mk_route(conf["an-base"], "events", "")
    rslt = requests.get(endpt, params=query, headers=conf["headers"])

    rslt.raise_for_status()

    rslt = rslt.json(object_hook=simple_dt_reader)
    return rslt["_embedded"]["osdi:events"]


def prepare_an_event(event: dict) -> dict:
    """
    Prepare a raw result from the action network API to be sent to the
    google api.
    """
    out = dict()
    out["start"] = { "dateTime": event["start_date"], "timeZone": "US/Eastern" }
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


# add a single google event
@google_api_call
def add_google_event(conf: dict, event: dict) -> dict:
    endpt = mk_route(conf["google-base"], "calendars", conf["google-cal-id"], "events")
    headers = conf["headers"]
    params = conf["params"] | { "sendUpdates": "none" }
    event = {k:v for k,v in event.items() if k != "id"}
    event["start"]["dateTime"] = wrt_dt(event["start"]["dateTime"], fmt="%Y-%m-%dT%H:%M:%S")
    event["end"]["dateTime"] = wrt_dt(event["end"]["dateTime"], fmt="%Y-%m-%dT%H:%M:%S")
    rslt = requests.post(endpt, headers=headers, params=params, json=event)

    rslt.raise_for_status()

    return rslt.json()

"""
The command line interface.
"""

mode_choices = ("manual", "auto")
filter_type = lambda s: s if re.match(r"(?:lt|gt|eq) created_date \d{4}-\d{2}-\d{2}", s) else "created_date gt '1970-01-01'"

# valid script names
parser = ap.ArgumentParser(description="CLI for coordinating Google Calendar and Action Network.")
parser.add_argument("-t", "--test", action="store_true",
                    help="Whether to use test or production configuration.")
parser.add_argument("-v", "--verbose", action="store_true",
                    help="Whether to display verbose output.")
parser.add_argument("-f", "--filter", nargs = "?", type=filter_type,
                    help="Filter to apply to the Action Network fetch.")
parser.add_argument("-m", "--mode", nargs="?", const="manual", choices=mode_choices,
                    help="Whether to merge automatically or manually.")


if __name__ == "__main__":
    status = 0
    args = parser.parse_args()

    if args.test:
        conf = load_conf(".env.test.json")

    else:
        conf = load_conf(".env.json")

    try:
        an_events = get_an_events(conf, filter=args.filter)

    except requests.HTTPError as e:
        print(f"Request failed with status code {e.response.status_code} : {e.response.reason}.")

        if args.verbose:
            print(f"\n\nRequest object: --------------------------------\n\n")
            pp.pprint(vars(e.request))
            print(f"\n\nResponse object: -------------------------------\n\n")
            pp.pprint(vars(e.response))

        print("\n\n")
        status = 1

    except Exception as e:
        print(f"Request failed. Reason {repr(e)}.")
        status = 1

    else:
        prepped_an_events = sorted([prepare_an_event(e) for e in an_events], key=lambda e:e["start"]["dateTime"])

        print(f"Fetched {len(prepped_an_events)} events from Action Network.")

        if args.verbose:
            pp.pprint(prepped_an_events)

        count = 0

        for evt in prepped_an_events:
            if args.mode == "manual":
                print("About to add new event: ---------------------------------\n\n")
                pp.pprint(evt)

                if input("\n\n Add this event [y/N] ? ").lower() in {"", "n", "no"}:
                    continue

            try:
                add_google_event(conf, evt)


            except requests.HTTPError as e:
                print(f"Request failed with status code {e.response.status_code} : {e.response.reason}.")

                if args.verbose:
                    print(f"\n\nRequest object: --------------------------------\n\n")
                    pp.pprint(vars(e.request))
                    print(f"\n\nResponse object: -------------------------------\n\n")
                    pp.pprint(vars(e.response))

                print("\n\n")
                status = 1

            except Exception as e:
                print(f"Request failed. Reason {repr(e)}.")
                status = 1

            else:
                count += 1

            finally:
                if status:
                    print(f"Exiting due to failure. Successfully added {count} events before failure occurred.")
                    break

        else:
            print(f"Adding Google events completed. Added {count} events.")

    exit(status)
