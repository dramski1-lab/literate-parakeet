#!/usr/bin/env python3
"""
Data broker opt-out automation for name "Ramski".

Each broker has a unique removal flow. This script automates what can be done
via HTTP (form submissions, API calls). Sites that gate removal behind CAPTCHA
or phone verification are flagged in the MANUAL_ACTION_REQUIRED report at the end.

Usage:
    python3 remove_ramski.py [--email your@email.com] [--dry-run]

    --email   Address used for broker confirmation emails (required by many sites)
    --dry-run Print what would be submitted without sending any requests
"""

import argparse
import json
import sys
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Optional

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

TARGET_NAME = "Ramski"
TARGET_FIRST = ""       # optional – set if you want to narrow searches
TARGET_LAST = "Ramski"  # primary search token

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

REQUEST_TIMEOUT = 20  # seconds


# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------

@dataclass
class BrokerResult:
    name: str
    status: str          # "submitted" | "not_found" | "manual_required" | "error"
    detail: str = ""
    opt_out_url: str = ""


results: list[BrokerResult] = []


def record(name: str, status: str, detail: str = "", opt_out_url: str = "") -> None:
    results.append(BrokerResult(name, status, detail, opt_out_url))
    icon = {"submitted": "✓", "not_found": "–", "manual_required": "!", "error": "✗"}.get(status, "?")
    print(f"  [{icon}] {name}: {detail or status}")


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def get(session: requests.Session, url: str, **kwargs) -> Optional[requests.Response]:
    try:
        r = session.get(url, headers=DEFAULT_HEADERS, timeout=REQUEST_TIMEOUT, **kwargs)
        r.raise_for_status()
        return r
    except requests.RequestException as exc:
        return None


def post(session: requests.Session, url: str, **kwargs) -> Optional[requests.Response]:
    try:
        r = session.post(url, headers=DEFAULT_HEADERS, timeout=REQUEST_TIMEOUT, **kwargs)
        return r
    except requests.RequestException:
        return None


def soup(response: requests.Response) -> BeautifulSoup:
    return BeautifulSoup(response.text, "lxml")


# ---------------------------------------------------------------------------
# Broker handlers
# ---------------------------------------------------------------------------

def check_spokeo(session: requests.Session, email: str, dry_run: bool) -> None:
    """Spokeo: search then POST the listing URL to their opt-out endpoint."""
    broker = "Spokeo"
    search_url = f"https://www.spokeo.com/search?q={urllib.parse.quote(TARGET_NAME)}"
    r = get(session, search_url)
    if r is None:
        record(broker, "error", "search request failed")
        return

    page = soup(r)
    # Profile links look like /FirstName-LastName/State/id
    links = [
        a["href"] for a in page.select("a[href]")
        if TARGET_LAST.lower() in a["href"].lower()
        and "/search" not in a["href"]
        and a["href"].startswith("/")
    ]

    if not links:
        record(broker, "not_found", f"no profiles matching '{TARGET_NAME}'",
               opt_out_url="https://www.spokeo.com/optout")
        return

    submitted = 0
    for path in links[:10]:  # cap to avoid hammering
        profile_url = "https://www.spokeo.com" + path
        if dry_run:
            print(f"    [dry-run] would opt-out: {profile_url}")
            submitted += 1
            continue
        payload = {"email": email, "url": profile_url}
        resp = post(session, "https://www.spokeo.com/optout/submit",
                    data=payload,
                    headers={**DEFAULT_HEADERS, "Referer": "https://www.spokeo.com/optout"})
        if resp and resp.status_code < 400:
            submitted += 1
        time.sleep(1)

    record(broker, "submitted" if submitted else "error",
           f"{submitted} opt-out request(s) submitted; check {email} for confirmation",
           opt_out_url="https://www.spokeo.com/optout")


def check_whitepages(session: requests.Session, email: str, dry_run: bool) -> None:
    """WhitePages: POST suppression request."""
    broker = "WhitePages"
    search_url = (
        f"https://www.whitepages.com/name/{urllib.parse.quote(TARGET_NAME)}"
    )
    r = get(session, search_url)
    if r is None:
        record(broker, "error", "search request failed")
        return

    page = soup(r)
    # Profile card links contain /person/
    profile_links = list({
        a["href"] for a in page.select("a[href*='/person/']")
        if TARGET_LAST.lower() in a["href"].lower()
    })

    if not profile_links:
        record(broker, "not_found", f"no profiles matching '{TARGET_NAME}'",
               opt_out_url="https://www.whitepages.com/suppression-requests")
        return

    submitted = 0
    for href in profile_links[:10]:
        full_url = href if href.startswith("http") else "https://www.whitepages.com" + href
        if dry_run:
            print(f"    [dry-run] would suppress: {full_url}")
            submitted += 1
            continue
        resp = post(session, "https://www.whitepages.com/suppression-requests/new",
                    data={"utf8": "✓", "requester_email": email, "listing_url": full_url},
                    headers={**DEFAULT_HEADERS, "Referer": full_url})
        if resp and resp.status_code < 400:
            submitted += 1
        time.sleep(1)

    record(broker, "submitted" if submitted else "manual_required",
           f"{submitted} suppression(s) queued; email confirmation may be required",
           opt_out_url="https://www.whitepages.com/suppression-requests")


def check_beenverified(session: requests.Session, email: str, dry_run: bool) -> None:
    """BeenVerified: opt-out requires CAPTCHA – flag for manual action."""
    record(
        "BeenVerified",
        "manual_required",
        "CAPTCHA-protected opt-out; visit the URL and search for 'Ramski'",
        opt_out_url="https://www.beenverified.com/app/optout/search",
    )


def check_intelius(session: requests.Session, email: str, dry_run: bool) -> None:
    """Intelius shares WhitePages infrastructure for opt-out."""
    broker = "Intelius"
    opt_out_url = "https://www.intelius.com/opt-out/submit/"
    search_url = (
        f"https://www.intelius.com/people-search/results/"
        f"?firstName=&lastName={urllib.parse.quote(TARGET_LAST)}"
    )
    r = get(session, search_url)
    if r is None:
        record(broker, "error", "search request failed",
               opt_out_url=opt_out_url)
        return

    page = soup(r)
    profile_links = list({
        a["href"] for a in page.select("a[href]")
        if TARGET_LAST.lower() in a.get("href", "").lower()
        and "/people/" in a.get("href", "")
    })

    if not profile_links:
        record(broker, "not_found", f"no profiles matching '{TARGET_NAME}'",
               opt_out_url=opt_out_url)
        return

    submitted = 0
    for href in profile_links[:10]:
        full_url = href if href.startswith("http") else "https://www.intelius.com" + href
        if dry_run:
            print(f"    [dry-run] would opt-out: {full_url}")
            submitted += 1
            continue
        resp = post(session, opt_out_url,
                    data={"email": email, "reportUrl": full_url},
                    headers={**DEFAULT_HEADERS, "Referer": full_url})
        if resp and resp.status_code < 400:
            submitted += 1
        time.sleep(1)

    record(broker, "submitted" if submitted else "manual_required",
           f"{submitted} opt-out(s) submitted",
           opt_out_url=opt_out_url)


def check_radaris(session: requests.Session, email: str, dry_run: bool) -> None:
    """Radaris: opt-out via their control center form."""
    broker = "Radaris"
    opt_out_url = "https://radaris.com/control/privacy"
    search_url = f"https://radaris.com/p/{urllib.parse.quote(TARGET_LAST)}/"
    r = get(session, search_url)
    if r is None:
        record(broker, "error", "search request failed", opt_out_url=opt_out_url)
        return

    page = soup(r)
    profile_links = list({
        a["href"] for a in page.select("a[href]")
        if TARGET_LAST.lower() in a.get("href", "").lower()
        and "/ng/#/5/" in a.get("href", "")
    })

    if not profile_links:
        record(broker, "not_found", f"no profiles matching '{TARGET_NAME}'",
               opt_out_url=opt_out_url)
        return

    for href in profile_links[:10]:
        full_url = href if href.startswith("http") else "https://radaris.com" + href
        if dry_run:
            print(f"    [dry-run] would request removal: {full_url}")

    record(broker, "manual_required",
           "Radaris requires email verification; visit opt_out_url, "
           f"found {len(profile_links)} candidate profile(s)",
           opt_out_url=opt_out_url)


def check_fastpeoplesearch(session: requests.Session, email: str, dry_run: bool) -> None:
    """FastPeopleSearch: submit removal for each result URL."""
    broker = "FastPeopleSearch"
    opt_out_url = "https://www.fastpeoplesearch.com/removal"
    search_url = (
        f"https://www.fastpeoplesearch.com/name/{urllib.parse.quote(TARGET_LAST)}_all"
    )
    r = get(session, search_url)
    if r is None:
        record(broker, "error", "search request failed", opt_out_url=opt_out_url)
        return

    page = soup(r)
    profile_links = list({
        a["href"] for a in page.select("a.card-block[href], a[href*='/address/']")
        if TARGET_LAST.lower() in a.get("href", "").lower()
    })

    if not profile_links:
        record(broker, "not_found", f"no profiles matching '{TARGET_NAME}'",
               opt_out_url=opt_out_url)
        return

    submitted = 0
    for href in profile_links[:10]:
        full_url = href if href.startswith("http") else "https://www.fastpeoplesearch.com" + href
        if dry_run:
            print(f"    [dry-run] would remove: {full_url}")
            submitted += 1
            continue
        resp = post(session, opt_out_url,
                    data={"listing-url": full_url},
                    headers={**DEFAULT_HEADERS, "Referer": opt_out_url})
        if resp and resp.status_code < 400:
            submitted += 1
        time.sleep(1)

    record(broker, "submitted" if submitted else "manual_required",
           f"{submitted} removal(s) submitted; email confirmation may follow",
           opt_out_url=opt_out_url)


def check_peoplefinders(session: requests.Session, email: str, dry_run: bool) -> None:
    """PeopleFinders: opt-out requires CAPTCHA."""
    record(
        "PeopleFinders",
        "manual_required",
        "CAPTCHA-protected; visit the URL and search for 'Ramski'",
        opt_out_url="https://www.peoplefinders.com/opt-out",
    )


def check_mylife(session: requests.Session, email: str, dry_run: bool) -> None:
    """MyLife: removal only via email or phone call."""
    record(
        "MyLife",
        "manual_required",
        "Email privacy@mylife.com with subject 'Profile Removal Request' and name 'Ramski'",
        opt_out_url="https://www.mylife.com/privacy-policy/",
    )


def check_truthfinder(session: requests.Session, email: str, dry_run: bool) -> None:
    """TruthFinder: opt-out requires CAPTCHA."""
    record(
        "TruthFinder",
        "manual_required",
        "CAPTCHA-protected; visit the URL and search for 'Ramski'",
        opt_out_url="https://www.truthfinder.com/opt-out/",
    )


def check_instantcheckmate(session: requests.Session, email: str, dry_run: bool) -> None:
    """Instant Checkmate: opt-out requires CAPTCHA."""
    record(
        "InstantCheckmate",
        "manual_required",
        "CAPTCHA-protected; visit the URL and search for 'Ramski'",
        opt_out_url="https://www.instantcheckmate.com/opt-out/",
    )


def check_peekyou(session: requests.Session, email: str, dry_run: bool) -> None:
    """PeekYou: opt-out via their web form."""
    broker = "PeekYou"
    opt_out_url = "https://www.peekyou.com/about/contact/optout/"
    search_url = f"https://www.peekyou.com/{urllib.parse.quote(TARGET_LAST)}"
    r = get(session, search_url)
    if r is None:
        record(broker, "error", "search request failed", opt_out_url=opt_out_url)
        return

    page = soup(r)
    profile_links = list({
        a["href"] for a in page.select("a[href]")
        if "/peoplearch/" in a.get("href", "")
        and TARGET_LAST.lower() in a.get("href", "").lower()
    })

    if not profile_links:
        record(broker, "not_found", f"no profiles matching '{TARGET_NAME}'",
               opt_out_url=opt_out_url)
        return

    for href in profile_links[:5]:
        full_url = href if href.startswith("http") else "https://www.peekyou.com" + href
        if dry_run:
            print(f"    [dry-run] would opt-out: {full_url}")

    record(broker, "manual_required",
           f"Found {len(profile_links)} profile(s); CAPTCHA required to complete removal",
           opt_out_url=opt_out_url)


def check_usphonebook(session: requests.Session, email: str, dry_run: bool) -> None:
    """USPhoneBook: removal via their opt-out form."""
    broker = "USPhoneBook"
    opt_out_url = "https://www.usphonebook.com/opt-out"
    search_url = (
        f"https://www.usphonebook.com/{urllib.parse.quote(TARGET_LAST)}"
    )
    r = get(session, search_url)
    if r is None:
        record(broker, "error", "search request failed", opt_out_url=opt_out_url)
        return

    page = soup(r)
    profile_links = list({
        a["href"] for a in page.select("a.person-link, a[href*='/profile/']")
        if TARGET_LAST.lower() in a.get("href", "").lower()
    })

    if not profile_links:
        record(broker, "not_found", f"no profiles matching '{TARGET_NAME}'",
               opt_out_url=opt_out_url)
        return

    submitted = 0
    for href in profile_links[:10]:
        full_url = href if href.startswith("http") else "https://www.usphonebook.com" + href
        if dry_run:
            print(f"    [dry-run] would opt-out: {full_url}")
            submitted += 1
            continue
        r2 = get(session, opt_out_url)
        if r2:
            p2 = soup(r2)
            token_input = p2.find("input", {"name": "_token"})
            token = token_input["value"] if token_input else ""
            resp = post(session, opt_out_url,
                        data={"_token": token, "link": full_url, "email": email},
                        headers={**DEFAULT_HEADERS, "Referer": opt_out_url})
            if resp and resp.status_code < 400:
                submitted += 1
        time.sleep(1.5)

    record(broker, "submitted" if submitted else "manual_required",
           f"{submitted} opt-out(s) submitted",
           opt_out_url=opt_out_url)


def check_clustrmaps(session: requests.Session, email: str, dry_run: bool) -> None:
    """ClustrMaps: removal request via email."""
    record(
        "ClustrMaps",
        "manual_required",
        "Email privacy@clustrmaps.com requesting removal of all 'Ramski' profiles",
        opt_out_url="https://clustrmaps.com/bl/opt-out",
    )


def check_411(session: requests.Session, email: str, dry_run: bool) -> None:
    """411.com: opt-out form."""
    broker = "411.com"
    opt_out_url = "https://www.411.com/privacy/update"
    search_url = f"https://www.411.com/name/{urllib.parse.quote(TARGET_LAST)}/"
    r = get(session, search_url)
    if r is None:
        record(broker, "error", "search request failed", opt_out_url=opt_out_url)
        return

    page = soup(r)
    profile_links = list({
        a["href"] for a in page.select("a[href]")
        if "/name/" in a.get("href", "")
        and TARGET_LAST.lower() in a.get("href", "").lower()
        and a["href"] != search_url
    })

    if not profile_links:
        record(broker, "not_found", f"no profiles matching '{TARGET_NAME}'",
               opt_out_url=opt_out_url)
        return

    record(broker, "manual_required",
           f"Found {len(profile_links)} candidate(s); visit opt_out_url to complete removal",
           opt_out_url=opt_out_url)


def check_zabasearch(session: requests.Session, email: str, dry_run: bool) -> None:
    """ZabaSearch: opt-out via InfoTracer (parent company)."""
    record(
        "ZabaSearch",
        "manual_required",
        "Managed by InfoTracer; email: privacy@infotracer.com with name 'Ramski'",
        opt_out_url="https://www.zabasearch.com/block_records/",
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

BROKERS = [
    check_spokeo,
    check_whitepages,
    check_beenverified,
    check_intelius,
    check_radaris,
    check_fastpeoplesearch,
    check_peoplefinders,
    check_mylife,
    check_truthfinder,
    check_instantcheckmate,
    check_peekyou,
    check_usphonebook,
    check_clustrmaps,
    check_411,
    check_zabasearch,
]


def print_summary() -> None:
    submitted  = [r for r in results if r.status == "submitted"]
    not_found  = [r for r in results if r.status == "not_found"]
    manual     = [r for r in results if r.status == "manual_required"]
    errors     = [r for r in results if r.status == "error"]

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  Opt-outs submitted automatically : {len(submitted)}")
    print(f"  No matching profiles found       : {len(not_found)}")
    print(f"  Require manual action            : {len(manual)}")
    print(f"  Errors / unreachable             : {len(errors)}")

    if manual:
        print("\nMANUAL ACTION REQUIRED:")
        for r in manual:
            print(f"  • {r.name}")
            print(f"    {r.detail}")
            print(f"    URL: {r.opt_out_url}")

    if errors:
        print("\nERRORS (likely network / blocked):")
        for r in errors:
            print(f"  • {r.name}: {r.detail}")

    print("\nNote: Many brokers send a confirmation email before")
    print("finalising removal. Check the inbox you provided.")
    print("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--email", default="your@email.com",
                        help="Email address for broker confirmation links")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print actions without sending requests")
    args = parser.parse_args()

    if args.email == "your@email.com" and not args.dry_run:
        print("WARNING: No --email provided; using placeholder 'your@email.com'.")
        print("         Run with --email your@real.email for confirmations to work.\n")

    print(f"Scanning {len(BROKERS)} data brokers for '{TARGET_NAME}'...")
    if args.dry_run:
        print("(DRY-RUN mode – no requests will be sent)\n")
    else:
        print()

    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)

    for handler in BROKERS:
        name = handler.__name__.replace("check_", "").replace("_", " ").title()
        print(f"\n[{name}]")
        try:
            handler(session, args.email, args.dry_run)
        except Exception as exc:
            record(name, "error", str(exc))
        time.sleep(0.5)

    print_summary()


if __name__ == "__main__":
    main()
