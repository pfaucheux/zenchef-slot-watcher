import json
import os
import re
from datetime import datetime, timezone

RID = os.getenv("ZEN_RID", "362852")
PAX = int(os.getenv("ZEN_PAX", "2"))
URL = f"https://bookings.zenchef.com/results?rid={RID}"


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


def get_app_state(next_data: dict) -> dict:
    """
    Retourne un dict représentant appStoreState.
    On gère 2 structures possibles pour être robuste.
    """
    initial_state = (
        next_data.get("props", {})
        .get("pageProps", {})
        .get("initialState", {})
    )

    # 1) structure attendue (celle de ton HTML collé)
    app = initial_state.get("appStoreState", {})
    if isinstance(app, dict) and "dailyAvailabilities" in app:
        return app

    # 2) fallback si un niveau s'est glissé (rare mais ça arrive selon les hydrations)
    app2 = app.get("appStoreState", {}) if isinstance(app, dict) else {}
    if isinstance(app2, dict) and "dailyAvailabilities" in app2:
        return app2

    # 3) sinon on renvoie ce qu’on a (diagnostic)
    return app if isinstance(app, dict) else {}


def summarize_shifts(next_data: dict) -> dict:
    app_state = get_app_state(next_data)
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
        "has_dailyAvailabilities_key": "dailyAvailabilities" in app_state,
        "sample_daily_keys": list(daily.keys())[:5],
    }


def main() -> int:
    now = datetime.now(timezone.utc).isoformat()
    print(f"[{now}] Checking {URL} for pax={PAX}")

    status = "UNKNOWN"  # AVAILABLE / NOT_AVAILABLE / UNKNOWN
    reason = ""
    details = {}

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            # Charge la page
            page.goto(URL, wait_until="domcontentloaded", timeout=90_000)

            # Attends que la variable Next soit posée (si jamais)
            try:
                page.wait_for_function("() => typeof window.__NEXT_DATA__ !== 'undefined'", timeout=15_000)
            except Exception:
                pass

            # 1) Essai via JS (souvent le plus fiable)
            next_data = None
            try:
                next_data = page.evaluate("() => window.__NEXT_DATA__")
            except Exception:
                next_data = None

            # 2) Fallback via HTML
            if not isinstance(next_data, dict):
                html = page.content()
                next_data = extract_next_data_from_html(html)

            browser.close()

        details = summarize_shifts(next_data)

        if details["days_seen"] == 0 and not details["has_dailyAvailabilities_key"]:
            status = "UNKNOWN"
            reason = "Could not locate dailyAvailabilities in appStoreState (possible challenge / different payload)."
        elif details["total_shifts"] > 0:
            status = "AVAILABLE"
            reason = f"Found shifts on {len(details['days_with_shifts'])} day(s)."
        else:
            status = "NOT_AVAILABLE"
            reason = f"No shifts found (days seen: {details['days_seen']})."

    except Exception as e:
        status = "UNKNOWN"
        reason = f"{type(e).__name__}: {e}"

    # Outputs
    write_output("status", status)
    write_output("available", "1" if status == "AVAILABLE" else "0")
    write_output("reason", reason)
    write_output("details_json", json.dumps(details, ensure_ascii=False))

    print(f"STATUS={status}")
    print(f"REASON={reason}")
    print(f"DETAILS={details}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
