import json
import os
import sys
from datetime import date, datetime, timezone
from calendar import monthrange

import requests

RID = os.getenv("ZEN_RID", "362852")
PAX = int(os.getenv("ZEN_PAX", "2"))
MONTHS_AHEAD = int(os.getenv("ZEN_MONTHS_AHEAD", "3"))  # ex: 3 => mois courant + 2
DEBUG = os.getenv("DEBUG", "0") == "1"

BASE = "https://bookings-middleware.zenchef.com"
SUMMARY_ENDPOINT = f"{BASE}/getAvailabilitiesSummary"


def write_output(name: str, value: str) -> None:
    path = os.getenv("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{name}={value}\n")


def month_start(d: date) -> date:
    return date(d.year, d.month, 1)


def add_months(d: date, months: int) -> date:
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    day = min(d.day, monthrange(y, m)[1])
    return date(y, m, day)


def month_end(d: date) -> date:
    last = monthrange(d.year, d.month)[1]
    return date(d.year, d.month, last)


def fetch_month_summary(session: requests.Session, restaurant_id: str, d: date) -> list:
    begin = month_start(d).isoformat()
    end = month_end(d).isoformat()

    params = {
        "restaurantId": restaurant_id,
        "date_begin": begin,
        "date_end": end,
    }

    # On reproduit les headers essentiels du navigateur (Origin/Referer/UA),
    # c’est souvent ce qui fait la différence sur des endpoints protégés. [attached_file:1]
    headers = {
        "accept": "application/json, text/plain, */*",
        "origin": "https://bookings.zenchef.com",
        "referer": "https://bookings.zenchef.com/",
        "user-agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
    }

    r = session.get(SUMMARY_ENDPOINT, params=params, headers=headers, timeout=30)
    r.raise_for_status()
    data = r.json()

    if not isinstance(data, list):
        raise RuntimeError(f"Unexpected JSON type from summary: {type(data)}")

    return data


def day_has_pax(day_obj: dict, pax: int) -> bool:
    # Exemple que tu as fourni : isOpen + shifts[] + possible_guests[] [attached_file:1]
    if not isinstance(day_obj, dict):
        return False

    shifts = day_obj.get("shifts", [])
    if not isinstance(shifts, list) or len(shifts) == 0:
        return False

    for s in shifts:
        if not isinstance(s, dict):
            continue
        possible = s.get("possible_guests", [])
        # Certains shifts peuvent avoir possible_guests=[] mais d'autres OK (cf ton exemple). [attached_file:1]
        if isinstance(possible, list) and pax in possible:
            return True

    return False


def main() -> int:
    now = datetime.now(timezone.utc).isoformat()
    print(f"[{now}] Checking middleware {SUMMARY_ENDPOINT} for restaurantId={RID}, pax={PAX}, months_ahead={MONTHS_AHEAD}, DEBUG={int(DEBUG)}")

    debug = {
        "restaurantId": RID,
        "pax": PAX,
        "months_ahead": MONTHS_AHEAD,
        "months_checked": [],
        "days_total": 0,
        "days_open": 0,
        "days_with_shifts": 0,
        "days_with_pax": [],
        "sample_open_days": [],
    }

    status = "UNKNOWN"
    reason = ""
    details = {}

    try:
        session = requests.Session()

        start = month_start(date.today())
        months = [add_months(start, i) for i in range(max(1, MONTHS_AHEAD))]

        days_with_pax = []

        for m in months:
            ym = f"{m.year:04d}-{m.month:02d}"
            debug["months_checked"].append(ym)

            data = fetch_month_summary(session, RID, m)
            debug["days_total"] += len(data)

            for d in data:
                is_open = bool(d.get("isOpen"))
                shifts = d.get("shifts", [])
                has_shifts = isinstance(shifts, list) and len(shifts) > 0

                if is_open:
                    debug["days_open"] += 1
                    if len(debug["sample_open_days"]) < 5:
                        debug["sample_open_days"].append(d.get("date"))

                if has_shifts:
                    debug["days_with_shifts"] += 1

                if day_has_pax(d, PAX):
                    days_with_pax.append(d.get("date"))

        debug["days_with_pax"] = days_with_pax[:30]  # on limite la taille
        details = {
            "days_with_pax_count": len(days_with_pax),
            "days_with_pax_sample": days_with_pax[:10],
            "months_checked": debug["months_checked"],
        }

        if len(days_with_pax) > 0:
            status = "AVAILABLE"
            reason = f"Found at least one open shift that accepts pax={PAX}."
        else:
            status = "NOT_AVAILABLE"
            reason = f"No shifts accept pax={PAX} in checked months."

    except Exception as e:
        status = "UNKNOWN"
        reason = f"{type(e).__name__}: {e}"
        details = {}

    write_output("status", status)
    write_output("available", "1" if status == "AVAILABLE" else "0")
    write_output("reason", reason)
    write_output("details_json", json.dumps(details, ensure_ascii=False))
    write_output("debug_json", json.dumps(debug, ensure_ascii=False))

    print(f"STATUS={status}")
    print(f"REASON={reason}")
    print(f"DETAILS={details}")
    if DEBUG:
        print(f"DEBUG={debug}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
