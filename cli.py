import sys, os, requests, dateutil as du, argparse as ap, pprint as pp
from utils import get_dt, Config, mark_resolved, get_cached_event
from api import get_an_events, save_an_events, add_google_event

# valid script names
scripts = ("show-db", "an-fetch", "pop-event", "show-args")

parser = ap.ArgumentParser(description="CLI for coordinating Google Calendar and Action Network.")
parser.add_argument("-t", "--test", action="store_true")
parser.add_argument("-v", "--verbose", action="store_true")
parser.add_argument("-s", "--start", type=get_dt)
parser.add_argument("command", choices=scripts)


if __name__ == "__main__":
    status = 0
    args = parser.parse_args()

    if args.test:
        conf = Config(".env.test.json")

    else:
        conf = Config(".env.json")

    if args.command == "show-db":
        db_values = dump_database(conf["db-file"])
        pp.pprint(db_values)

    elif args.command == "an-fetch":
        if (d := args.start) is not None:
            rslt = get_an_events(conf, params={"filter": f"created_date gt '{d.strftime('%Y-%m-%d')}'"})

        else:
            rslt = get_an_events(conf)

        n_fetch = len(rslt)
        interned = save_an_events(conf, rslt)
        n_interned = len(interned)

        print(f"{n_fetch} events fetched, {n_interned} objects interned.")

        if args.verbose:
            pp.pprint(interned)

        print("Fetch completed.")

    elif args.command == "pop-event":
        e = get_cached_event(conf["db-file"])
        rsp = {"id": None}
        pp.pprint(e)

        if input("Add this event to the google calendar? [y/N] ").lower() in "yes":
            try:
                rsp = add_google_event(conf, e)

            except requests.HTTPError as e:
                if (r := e.response) is not None:
                    print(f"Failed to add google event. Reason {r.status_code}: {r.reason}.")
                    print("\n\nResponse object: ------------\n\n")
                    pp.pprint(vars(r))
                    print("\n\nRequest object: -------------\n\n")
                    pp.pprint(vars(e.request))
                    print("\n\nGoogle response: ------------\n\n")
                    pp.pprint(r.json())

                else:
                    print(f"Failed to add google event. Reason: {repr(e)}.")

                status = 1

            except Exception as e:
                print(f"Failed to add google event. Reason: {repr(e)}.")
                status = 1

            else:
                print(f"Event successfully added.")
                pp.pprint(rsp)

        if status != 1 and input("Mark it resolved? [y/N] ").lower() in "yes":
            mark_resolved(e["id"], conf["db-file"])

    elif args.command == "show-args":
        pp.pprint(vars(args))

    exit(status)
