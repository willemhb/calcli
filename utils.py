import requests, time, json, datetime as dt, random as rand
from dateutil.parser import parse as du_parse
from jwt import JWT, jwk_from_pem
from typing import Union, Callable, Optional, Iterable, AnyStr
from dataclasses import dataclass, InitVar, field
from functools import lru_cache, singledispatch, wraps, cached_property
from urllib.parse import urljoin, urlencode


JSONObject = Union[dict,list,tuple,str,int,float,bool,None,dt.datetime]
HTTPObject = JSONObject

"""
General utilities.
"""

def get_time() -> int:
    return int(time.time())


def get_dt(o=None) -> dt.datetime:
    if o is None:
        return dt.datetime.now()

    elif isinstance(o, dt.datetime):
        return o

    else:
        return get_cached_dt(o)


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


class DtJsonDecoder(json.JSONDecoder):
    def decode(self, s: str):
        o = super().decode(s)

        if isinstance(o, str):
            try:
                return du_parse(o)

            except:
                return o

        elif isinstance(o, list):
            return self.traverse_list(o)

        elif isinstance(o, dict):
            return self.traverse_dict(o)

        else:
            return o

    def traverse_dict(self, o):
        for k, v in o.items():
            if isinstance(v, str):
                o[k] = try_dt(v)

            elif isinstance(v, list):
                o[k] = self.traverse_list(v)

            elif isinstance(v, dict):
                o[k] = self.traverse_dict(v)

        return o

    def traverse_list(self, o):
        for i, v in enumerate(o):
            if isinstance(v, str):
                o[i] = try_dt(v)

            elif isinstance(v, list):
                o[i] = self.traverse_list(v)

            elif isinstance(v, dict):
                o[i] = self.traverse_dict(v)

        return o


class DtJsonEncoder(json.JSONEncoder):
    def __init__(self, fmt=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fmt = fmt

    def encode_dt(self, d):
        if self.fmt is not None:
            return d.strftime(self.fmt)

        else:
            return d.isoformat(sep="T", timespec="seconds")

    def default(self, o):
        if isinstance(o, dt.datetime):
            return self.encode_dt(o)

        elif isinstance(o, (list, tuple)):
            return [self.defaut(v) for v in o]

        elif isinstance(o, dict):
            return {k: self.default(v) for k,v in o.items()}

        else:
            return super().default(o)

    def prepare(self, o):
        if isinstance(o, dt.datetime):
            return self.encode_dt(o)

        elif isinstance(o, (list, tuple)):
            return [self.prepare(v) for v in o]

        elif isinstance(o, dict):
            return {k: self.prepare(v) for k,v in o.items()}

        else:
            return o

"""
config class.
"""

class Config(dict):
    def __new__(cls, ini: Optional[str]=None, it={}, **kwargs):
        return super().__new__(cls, it, **kwargs)

    def __init__(self, ini: Optional[str]=None, it={}, **kwargs):
        super().__init__(it, **kwargs)
        self.backing = ini

        if ini is not None:
            with open(ini) as js:
                env = json.load(js, cls=DtJsonDecoder)
                self.update(env)

    def __missing__(self, name):
        if name in {"google-token", "google-headers", "google-params", "an-headers"}:
            return getattr(self, name.replace("-", "_"))

        else:
            return super().__missing__(name)

    def save(self, backing: Optional[str] = None):
        env = backing or self.backing

        if env is None:
            raise ValueError("No save target.")

        with open(env, "w+") as out:
            json.dump(self, out, cls=DtJsonEncoder)

        return

    def refresh_google_token(self):
        with open(self["google-pem-file"]) as pf:
            contents = json.load(pf)
            pem = contents["private_key"].encode('utf8')

        # bunch of bullshit to put together the jwt
        ts = get_time()
        aud = "https://oauth2.googleapis.com/token"
        jwt_headers = {"typ": "JWT", "alg": "RS256"}
        jwt_body = {"iss": self["google-service-email"],
                    "scope": self["google-auth-scope"],
                    "aud": aud,
                    "iat": ts,
                    "exp": ts + 3600,
                    }

        jwt_pk = jwk_from_pem(pem)
        instance = JWT()
        enc = instance.encode(jwt_body, jwt_pk, alg="RS256", optional_headers=jwt_headers)

        # making the request
        params = {"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": enc}
        rslt = requests.post(aud, params=params)

        # raise an error if it failed
        rslt.raise_for_status()

        rslt = rslt.json()
        self["google-access-token"] = rslt["access_token"]
        self["google-token-expires"] = get_dt() + dt.timedelta(seconds=rslt["expires_in"])
        return

    @property
    def google_token(self):
        if get_dt() > self["google-token-expires"]:
            self.refresh_google_token()

        return self["google-access-token"]

    @cached_property
    def an_headers(self):
        return {"OSDI-API-Token": self["an-key"]}

    @property
    def google_headers(self):
        return {"Authorization": f"Bearer {self.google_token}"}

    @cached_property
    def google_params(self):
        return {"scope": self["google-auth-scope"]}

"""
Simple wrappers for requests that handle datetime aware JSON.
"""


def get(url, **kwargs):
    if (d := kwargs.get("json", None)) is not None:
        kwargs["json"] = None
        kwargs.setdefault("headers", dict())["Content-Type"] = 'application/json'
        kwargs["data"] = json.dumps(d, cls=DtJsonEncoder)

    return requests.get(url, **kwargs)


def post(url, **kwargs):
    if (d := kwargs.get("json", None)) is not None:
        kwargs["json"] = None
        kwargs.setdefault("headers", dict())["Content-Type"] = 'application/json'
        kwargs["data"] = json.dumps(d, cls=DtJsonEncoder)

    return requests.post(url, **kwargs)


def put(url, **kwargs):
    if (d := kwargs.get("json", None)) is not None:
        kwargs["json"] = None
        kwargs.setdefault("headers", dict())["Content-Type"] = 'application/json'
        kwargs["data"] = json.dumps(d, cls=DtJsonEncoder)

    return requests.put(url, **kwargs)



def patch(url, **kwargs):
    if (d := kwargs.get("json", None)) is not None:
        kwargs["json"] = None
        kwargs.setdefault("headers", dict())["Content-Type"] = 'application/json'
        kwargs["data"] = json.dumps(d, cls=DtJsonEncoder)

    return requests.patch(url, **kwargs)


def delete(url, **kwargs):
    if (d := kwargs.get("json", None)) is not None:
        kwargs["json"] = None
        kwargs.setdefault("headers", dict())["Content-Type"] = 'application/json'
        kwargs["data"] = json.dumps(d, cls=DtJsonEncoder)

    return requests.delete(url, **kwargs)


def head(url, **kwargs):
    if (d := kwargs.get("json", None)) is not None:
        kwargs["json"] = None
        kwargs.setdefault("headers", dict())["Content-Type"] = 'application/json'
        kwargs["data"] = json.dumps(d, cls=DtJsonEncoder)

    return requests.head(url, **kwargs)


"""
Helpers for managing integration using a local cache.
"""


def intern_results(resp: list[dict], k: str, fnm: str) -> dict:
    """
    filter from responses those that have already been received.

    return a list of the keys that were added to the 'database'.
    """
    with open(fnm) as dbf:
        db = json.load(dbf, cls=DtJsonDecoder)

    for r in resp:
        db.setdefault(r[k], r)

    with open(fnm, "w") as dbf:
        json.dump(db, dbf, cls=DtJsonEncoder)

    return db


def mark_resolved(k: str, fnm: str) -> dict:
    """
    Mark an event as successfully added to the Google calendar.
    """
    with open(fnm) as dbf:
        db = json.load(dbf, cls=DtJsonDecoder)

    rslt = db[k]
    db[k] = None

    with open(fnm) as dbf:
        json.dump(db, dbf, cls=DtJsonEncoder)

    return rslt


def dump_database(dbnm: str, show_old: bool = False):
    with open(dbnm) as dbf:
        db = json.load(dbf, cls=DtJsonDecoder)

        if show_old:
            return db

        else:
            return {k:v for k in db if isinstance((v := db[k]), dict)}


def get_cached_event(dbnm: str):
    """
    Fetch an event from the database.
    """
    with open(dbnm) as dbf:
        db = json.load(dbf, cls=DtJsonDecoder)

    k = rand.choice(list(db))
    return db[k]
