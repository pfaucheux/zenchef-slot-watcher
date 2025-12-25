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


def extract_next_data(html: str) -> dict:
    m = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html,
        re.S,
    )
    if not m:
        raise RuntimeError("__NEXT_DATA__ introuvable (page non rendue / challenge possible)")
    return json.loads(m.group(1))


def summarize_shifts(next_data: dict) -> dict:
    state = (
        next_data.get("props", {})
        .get("pageProps", {})
        .get("initialState", {})
        .get("appStoreState", {})
    )
    daily = state.get("dailyAvailabilities", {}) or {}

    days_with_shifts = []
    total_shifts = 0

    for day, payload in daily.items():
        shifts = (payload or {}).get("shifts", [])
        if isinstance(shifts, list):
            if len(shifts) > 0:
                days_with_shifts.append(day)
                total_shifts += len(shifts)

    return {
        "days_seen": len(daily),
        "days_with_shifts": days_with_shifts,
        "total_shifts": total_shifts,
    }


def main() -> int:
    now = datetime.now(timezone.utc).isoformat()
    print(f"[{now}] Checking {URL} for pax={PAX}")

    # Valeurs par défaut (UNKNOWN)
    status = "UNKNOWN"  # AVAILABLE / NOT_AVAILABLE / UNKNOWN
    reason = ""
    details = {}

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(URL, wait_until="networkidle", timeout=90_000)
            html = page.content()
            browser.close()

        next_data = extract_next_data(html)
        details = summarize_shifts(next_data)

        if details["total_shifts"] > 0:
            status = "AVAILABLE"
            reason = f"Found shifts on {len(details['days_with_shifts'])} day(s)."
        else:
            status = "NOT_AVAILABLE"
            reason = f"No shifts found (days seen: {details['days_seen']})."

    except Exception as e:
        status = "UNKNOWN"
        reason = f"{type(e).__name__}: {e}"

    # Outputs pour le workflow
    write_output("status", status)
    write_output("available", "1" if status == "AVAILABLE" else "0")
    write_output("reason", reason)

    # Détails (JSON compact) pour debug dans la summary
    try:
        write_output("details_json", json.dumps(details, ensure_ascii=False))
    except Exception:
        write_output("details_json", "{}")

    # Logs lisibles
    print(f"STATUS={status}")
    print(f"REASON={reason}")
    print(f"DETAILS={details}")

    # On ne casse pas le workflow: succès technique
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
