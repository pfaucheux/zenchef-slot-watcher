import json
import os
import re
from datetime import datetime, timezone

RID = os.getenv("ZEN_RID", "362852")
PAX = int(os.getenv("ZEN_PAX", "2"))
URL = f"https://bookings.zenchef.com/results?rid={RID}"
DEBUG = os.getenv("DEBUG", "0") == "1"


def write_output(name: str, value: str) -> None:
    path = os.getenv("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{name}={value}\n")


def extract_next_data_from_html(html: str) -> dict:
    m = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html,
        re.S,
    )
    if not m:
        raise RuntimeError("__NEXT_DATA__ introuvable dans le HTML")
    return json.loads(m.group(1))


def safe_keys(obj) -> list:
    return sorted(list(obj.keys())) if isinstance(obj, dict) else []


def get_initial_state(next_data: dict) -> dict:
    return (
        next_data.get("props", {})
        .get("pageProps", {})
        .get("initialState", {})
    )


def get_app_state(initial_state: dict) -> dict:
    app = initial_state.get("appStoreState", {})
    if isinstance(app, dict) and "dailyAvailabilities" in app:
        return app
    app2 = app.get("appStoreState", {}) if isinstance(app, dict) else {}
    if isinstance(app2, dict) and "dailyAvailabilities" in app2:
        return app2
    return app if isinstance(app, dict) else {}


def summarize_shifts(app_state: dict) -> dict:
    daily = app_state.get("dailyAvailabilities", {}) or {}

    days_with_shifts = []
    total_shifts = 0

    for day, payload in daily.items():
        shifts = (payload or {}).get("shifts", [])
        if isinstance(shifts, list) and len(shifts) > 0:
            days_with_shifts.append(day)
            total_shifts += len(shifts)

    return {
        "days_seen": len(daily),
        "days_with_shifts": days_with_shifts,
        "total_shifts": total_shifts,
        "sample_daily_keys": list(daily.keys())[:5],
    }


def main() -> int:
    now = datetime.now(timezone.utc).isoformat()
    print(f"[{now}] Checking {URL} for pax={PAX} DEBUG={int(DEBUG)}")

    status = "UNKNOWN"  # AVAILABLE / NOT_AVAILABLE / UNKNOWN
    reason = ""
    details = {}

    debug_info = {
        "url": URL,
        "pax": PAX,
        "final_url": None,
        "main_response_status": None,
        "has_next_data_js": False,
        "has_next_data_html": False,
        "initial_state_keys": [],
        "app_state_keys": [],
        "dailyAvailabilities_present": False,
    }

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            main_response = page.goto(URL, wait_until="domcontentloaded", timeout=90_000)
            debug_info["final_url"] = page.url
            if main_response:
                debug_info["main_response_status"] = main_response.status

            # On attend un peu que Next hydrate / pose __NEXT_DATA__ global
            try:
                page.wait_for_function("() => typeof window.__NEXT_DATA__ !== 'undefined'", timeout=15_000)
            except Exception:
                pass

            next_data = None

            # 1) Tenter via JS (le plus fiable quand la page est réellement exécutée)
            try:
                next_data = page.evaluate("() => window.__NEXT_DATA__")
                debug_info["has_next_data_js"] = isinstance(next_data, dict)
            except Exception:
                next_data = None

            # 2) Fallback via HTML
            html = page.content()
            debug_info["has_next_data_html"] = ('id="__NEXT_DATA__"' in html)

            if not isinstance(next_data, dict):
                next_data = extract_next_data_from_html(html)

            browser.close()

        initial_state = get_initial_state(next_data)
        app_state = get_app_state(initial_state)

        debug_info["initial_state_keys"] = safe_keys(initial_state)
        debug_info["app_state_keys"] = safe_keys(app_state)
        debug_info["dailyAvailabilities_present"] = (
            isinstance(app_state, dict) and "dailyAvailabilities" in app_state
        )

        if not debug_info["dailyAvailabilities_present"]:
            status = "UNKNOWN"
            reason = "dailyAvailabilities absent (payload différent / challenge possible)"
            details = {
                "days_seen": 0,
                "days_with_shifts": [],
                "total_shifts": 0,
            }
        else:
            details = summarize_shifts(app_state)
            if details["total_shifts"] > 0:
                status = "AVAILABLE"
                reason = f"Found shifts on {len(details['days_with_shifts'])} day(s)."
            else:
                status = "NOT_AVAILABLE"
                reason = f"No shifts found (days seen: {details['days_seen']})."

    except Exception as e:
        status = "UNKNOWN"
        reason = f"{type(e).__name__}: {e}"
        details = {
            "days_seen": 0,
            "days_with_shifts": [],
            "total_shifts": 0,
        }

    # Outputs pour le workflow
    write_output("status", status)
    write_output("available", "1" if status == "AVAILABLE" else "0")
    write_output("reason", reason)
    write_output("details_json", json.dumps(details, ensure_ascii=False))
    write_output("debug_json", json.dumps(debug_info, ensure_ascii=False))

    # Logs
    print(f"STATUS={status}")
    print(f"REASON={reason}")
    print(f"DETAILS={details}")
    if DEBUG:
        print(f"DEBUG={debug_info}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
