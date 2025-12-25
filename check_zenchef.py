import json
import os
import re
from datetime import datetime, timezone

RID = os.getenv("ZEN_RID", "362852")
PAX = int(os.getenv("ZEN_PAX", "2"))
URL = f"https://bookings.zenchef.com/results?rid={RID}"

def extract_next_data(html: str) -> dict:
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
    if not m:
        raise RuntimeError("__NEXT_DATA__ introuvable (page non rendue ou challenge)")
    return json.loads(m.group(1))

def has_any_shift(next_data: dict) -> bool:
    # On vise: props.pageProps.initialState.appStoreState.dailyAvailabilities
    state = next_data.get("props", {}).get("pageProps", {}).get("initialState", {}).get("appStoreState", {})
    daily = state.get("dailyAvailabilities", {})
    # On regarde simplement s'il existe au moins un jour avec shifts non vide.
    for day, payload in daily.items():
        shifts = (payload or {}).get("shifts", [])
        if isinstance(shifts, list) and len(shifts) > 0:
            return True
    return False

def main():
    from playwright.sync_api import sync_playwright

    now = datetime.now(timezone.utc).isoformat()
    print(f"[{now}] Checking {URL} for pax={PAX}")

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
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write("available=1\n")
    else:
        print("AVAILABLE=0 No shift found in dailyAvailabilities")
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write("available=0\n")


if __name__ == "__main__":
    main()
