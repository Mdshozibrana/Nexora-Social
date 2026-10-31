"""Approximate country lookup from the visitor's IP (Phase 19).

Telegram tells us a member's language, never their country, so the
admin dashboard's country figures come from a free IP geolocation
lookup (ipapi.co) done once, when the member first appears without a
stored country. Only the country name is kept — never the IP itself.
Private/reserved addresses are skipped and every failure is silent:
country is a nice-to-have statistic, never a login blocker.
"""
import ipaddress

import httpx


def _public_ip(raw):
    """First public IP from an X-Forwarded-For chain / client host."""
    for part in (raw or "").split(","):
        ip = part.strip()
        if not ip:
            continue
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if addr.is_global:
            return ip
    return None


async def lookup_country(raw_ip):
    """Country name for a public IP, or None (best-effort, ~3s cap)."""
    ip = _public_ip(raw_ip)
    if not ip:
        return None
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(f"https://ipapi.co/{ip}/json/")
        if resp.status_code != 200:
            return None
        data = resp.json()
        if data.get("error"):
            return None
        return data.get("country_name") or data.get("country_code") or None
    except Exception:
        return None
