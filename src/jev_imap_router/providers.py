"""IMAP settings for common providers, so `init` only needs an email address."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Provider:
    name: str
    host: str
    port: int = 993
    password_help: str = ""


GMAIL = Provider(
    "Gmail / Google Workspace", "imap.gmail.com",
    password_help="Use an app password: turn on 2-Step Verification, then create one at "
                  "https://myaccount.google.com/apppasswords. IMAP must be enabled in Gmail settings.")
ICLOUD = Provider(
    "iCloud Mail", "imap.mail.me.com",
    password_help="Use an app-specific password from https://account.apple.com (Sign-In and Security).")
OUTLOOK = Provider(
    "Outlook.com / Microsoft 365", "outlook.office365.com",
    password_help="Personal Outlook.com accounts need an app password (https://account.live.com/proofs/AppPassword). "
                  "Many Microsoft 365 work accounts block password IMAP; ask your admin.")
YAHOO = Provider(
    "Yahoo Mail", "imap.mail.yahoo.com",
    password_help="Generate an app password in Yahoo Account Security.")
FASTMAIL = Provider(
    "Fastmail", "imap.fastmail.com",
    password_help="Create an app password in Settings > Privacy & Security > Integrations.")
AOL = Provider("AOL Mail", "imap.aol.com", password_help="Generate an app password in AOL Account Security.")
ZOHO = Provider("Zoho Mail", "imap.zoho.com", password_help="Use an app-specific password if 2FA is on.")
PROTON = Provider(
    "Proton Mail (via Proton Mail Bridge)", "127.0.0.1", 1143,
    password_help="Proton needs the Proton Mail Bridge app running; use the IMAP password Bridge shows. "
                  "Bridge uses plain IMAP on localhost, so set port to 1143.")
NAMECHEAP = Provider(
    "Namecheap Private Email", "mail.privateemail.com",
    password_help="Your mailbox password, or an application password from Private Email settings.")

BY_DOMAIN = {
    "gmail.com": GMAIL, "googlemail.com": GMAIL,
    "icloud.com": ICLOUD, "me.com": ICLOUD, "mac.com": ICLOUD,
    "outlook.com": OUTLOOK, "hotmail.com": OUTLOOK, "live.com": OUTLOOK, "msn.com": OUTLOOK,
    "yahoo.com": YAHOO, "ymail.com": YAHOO,
    "fastmail.com": FASTMAIL, "fastmail.fm": FASTMAIL,
    "aol.com": AOL,
    "zoho.com": ZOHO, "zohomail.com": ZOHO,
    "proton.me": PROTON, "protonmail.com": PROTON, "pm.me": PROTON,
}

# Custom domains: the MX record usually reveals the provider.
BY_MX = {
    "google.com": GMAIL, "googlemail.com": GMAIL,
    "outlook.com": OUTLOOK, "protection.outlook.com": OUTLOOK,
    "icloud.com": ICLOUD, "messagingengine.com": FASTMAIL,
    "zoho.com": ZOHO, "privateemail.com": NAMECHEAP, "jellyfish.systems": NAMECHEAP,
    "protonmail.ch": PROTON, "yahoodns.net": YAHOO,
}


def guess(address: str) -> Provider | None:
    """Provider for an email address: by domain, else by the domain's MX record (needs dnspython)."""
    domain = address.rsplit("@", 1)[-1].lower().strip()
    if domain in BY_DOMAIN:
        return BY_DOMAIN[domain]
    try:
        import dns.resolver  # optional dependency
        for rr in dns.resolver.resolve(domain, "MX", lifetime=5):
            mx = str(rr.exchange).rstrip(".").lower()
            for suffix, provider in BY_MX.items():
                if mx == suffix or mx.endswith("." + suffix):
                    return provider
    except Exception:
        pass
    return None
