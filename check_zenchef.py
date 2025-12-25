import json
import os
import re
from datetime import datetime, timezone

RID = os.getenv("ZEN_RID", "362852")
PAX = int(os.getenv("ZEN_PAX", "2"))
URL = f"https://bookings.zenchef.com/results?rid={RID}"


def write_output(name: str, value: str) -> None:
    """
    Ecrit un output GitHub Actions (si on est dans Actions).
    En local, GITHUB_OUTPUT est généralement absent => on ne fait rien.
    """
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
        raise RuntimeError("__NEXT_DATA__ introuvable (page non rendue ou challenge)")
    return json.loads(m.group(1))


def has_any_shift(next_data: dict) -> bool:
    """
    Inspecte initialState.appStoreState.dailyAvailabilities[*].shifts
    et renvoie True si au moins un jour a une liste de shifts non vide.
    """
    state = (
        next_data.get("props", {})
        .get("pageProps", {})
        .get("initialState", {})
        .get("appStoreState", {})
    )
    daily = state.get("dailyAvailabilities", {}) or {}

    for _, payload in daily.items():
        shifts = (payload or {}).get("shifts", [])
        if isinstance(shifts, list) and len(shifts) > 0:
            return True
    return False


def main() -> int:
    now = datetime.now(timezone.utc).isoformat()
    print(f"[{now}] Checking {URL} for pax={PAX}")

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(URL, wait_until="networkidle", timeout=90_000)
            html = page.content()
            browser.close()

        next_data = extract_next_data(html)
        available = has_any_shift(next_data)

        if available:
            print("AVAILABLE=1 Found at least one shift in dailyAvailabilities")
            write_output("available", "1")
        else:
            print("AVAILABLE=0 No shift found in dailyAvailabilities")
            write_output("available", "0")

        return 0

    except Exception as e:
        # Important: ne pas faire échouer le job Actions,
        # sinon "Create issue if available" est skipped.
        print(f"ERROR: {type(e).__name__}: {e}")
        print("AVAILABLE=0 (forced because of error)")
        write_output("available", "0")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
