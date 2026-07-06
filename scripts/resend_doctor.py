"""Resend setup doctor — read-only checks that subscriber delivery is ready.

Run in CI (.github/workflows/resend-doctor.yml) or locally:

    RESEND_API_KEY=re_... EMAIL_FROM="dAIly <digest@you.dev>" \
    RESEND_AUDIENCE_ID=... python -m scripts.resend_doctor

Prints a ✅/❌ checklist with the exact next action for every failure. Makes
only GET requests — it never sends email or mutates anything.
"""

from __future__ import annotations

import os
import re
import sys

import requests

API = "https://api.resend.com"


def _get(path: str, api_key: str) -> tuple[int, dict]:
    try:
        r = requests.get(
            f"{API}{path}",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=20,
        )
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, {}
    except requests.RequestException as exc:
        return 0, {"error": str(exc)}


def _from_domain(email_from: str) -> str:
    m = re.search(r"<([^>]+)>", email_from or "")
    addr = m.group(1) if m else (email_from or "").strip()
    return addr.rsplit("@", 1)[-1].lower() if "@" in addr else ""


def run_checks(
    api_key: str, email_from: str, audience_id: str, buttondown_key: str = ""
) -> list[tuple[bool, str]]:
    """Returns (passed, message) rows, in dependency order."""
    rows: list[tuple[bool, str]] = []

    # 1. API key
    if not api_key:
        rows.append((False, "RESEND_API_KEY is not set → add the secret in "
                            "Settings → Secrets and variables → Actions → Secrets."))
        return rows
    code, domains = _get("/domains", api_key)
    if code == 0:
        rows.append((False, f"Could not reach the Resend API ({domains.get('error')}) — "
                            "network issue; re-run."))
        return rows
    if code in (401, 403):
        rows.append((False, "RESEND_API_KEY is invalid or lacks permission → create a "
                            "fresh key with Full access at resend.com → API Keys."))
        return rows
    rows.append((True, "RESEND_API_KEY works."))

    # 2. Verified sending domain
    verified = [d for d in domains.get("data", []) if d.get("status") == "verified"]
    pending = [d for d in domains.get("data", []) if d.get("status") != "verified"]
    if verified:
        names = ", ".join(d["name"] for d in verified)
        rows.append((True, f"Verified sending domain(s): {names}."))
    elif pending:
        names = ", ".join(f"{d['name']} ({d.get('status')})" for d in pending)
        rows.append((False, f"Domain added but NOT verified yet: {names} → finish the "
                            "DNS records shown at resend.com → Domains, then re-run."))
    else:
        rows.append((False, "No sending domain in Resend → add one at resend.com → "
                            "Domains (broadcasts to subscribers cannot use "
                            "onboarding@resend.dev)."))

    # 3. Sender. EMAIL_FROM is optional: when unset (or still on resend.dev) the
    # run auto-sends as digest@<first-verified-domain>.
    fd = _from_domain(email_from)
    verified_names = {d["name"].lower() for d in verified}
    if email_from and fd not in ("", "resend.dev") and fd not in verified_names and verified:
        rows.append((False, f"EMAIL_FROM domain '{fd}' does not match a verified "
                            "domain → use an address on a verified domain."))
    elif email_from and fd in verified_names:
        rows.append((True, f"EMAIL_FROM looks good ({email_from})."))
    elif verified:
        rows.append((True, f"EMAIL_FROM not set to a custom domain — broadcasts "
                           f"auto-send as digest@{verified[0]['name']}."))
    else:
        rows.append((False, "No custom sender possible yet — verify a domain first "
                            "(see above)."))

    # 4. Audience. Optional: the run auto-uses the first audience, or creates
    # 'dAIly subscribers' if none exists.
    code, audiences = _get("/audiences", api_key)
    listing = audiences.get("data", []) if code < 300 else []
    check_id = audience_id
    if not audience_id:
        if listing:
            check_id = listing[0]["id"]
            rows.append((True, f"RESEND_AUDIENCE_ID not set — will auto-use "
                               f"'{listing[0]['name']}' ({check_id})."))
        else:
            rows.append((True, "No audience yet — 'dAIly subscribers' will be "
                               "auto-created on the first send."))
    elif listing and audience_id not in {a["id"] for a in listing}:
        check_id = ""
        rows.append((False, f"RESEND_AUDIENCE_ID '{audience_id}' not found in this "
                            "account → copy the id from: "
                            + ", ".join(f"{a['name']}={a['id']}" for a in listing)))
    else:
        rows.append((True, f"Audience configured ({audience_id})."))

    # 5. Contacts in the audience (Buttondown lists auto-sync in at send time).
    if check_id:
        code, contacts = _get(f"/audiences/{check_id}/contacts", api_key)
        if code < 300:
            data = contacts.get("data", [])
            subscribed = sum(1 for c in data if not c.get("unsubscribed"))
            if data:
                rows.append((True, f"Audience has {len(data)} contact(s), "
                                   f"{subscribed} subscribed."))
            elif buttondown_key:
                rows.append((True, "Audience is empty now — your Buttondown "
                                   "subscribers auto-sync in on the first send."))
            else:
                rows.append((False, "Audience has 0 contacts → add yourself at "
                                    "resend.com → Audience (or keep the Buttondown "
                                    "key set and its list auto-syncs in)."))
    if buttondown_key:
        rows.append((True, "Buttondown detected — its subscribers auto-migrate "
                           "into Resend each run; Buttondown sending stops once "
                           "the broadcast succeeds."))
    return rows


def main() -> int:
    rows = run_checks(
        os.environ.get("RESEND_API_KEY", "").strip(),
        os.environ.get("EMAIL_FROM", "").strip(),
        os.environ.get("RESEND_AUDIENCE_ID", "").strip(),
        os.environ.get("BUTTONDOWN_API_KEY", "").strip(),
    )
    lines = ["# Resend subscriber-delivery checklist", ""]
    ok = True
    for passed, msg in rows:
        ok &= passed
        lines.append(f"{'✅' if passed else '❌'} {msg}")
    lines.append("")
    lines.append("🎉 All checks passed — the next digest run delivers to every subscriber."
                 if ok else "→ Fix the ❌ items above (top to bottom), then re-run this workflow.")
    report = "\n".join(lines)
    print(report)
    # Pretty summary on the Actions run page.
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        try:
            with open(summary, "a", encoding="utf-8") as fh:
                fh.write(report + "\n")
        except OSError:
            pass
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
