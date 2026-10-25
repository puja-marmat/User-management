"""
Client details written to `LogUserLogins` at login, as legacy computes them
[Code `CrystalPower.Utilities/Helpers/Security.cs`]:

* `GetIPAddress`: first entry of `X-Forwarded-For` (not trimmed), else the socket address.
* `GetWebRequestIdentification`:
  ``Machine Name=<reverse DNS of the socket address or "">;IP Address=<ip>;Logon User=<…>;``
  ``Browser Name=<…>;Browser Version=<…>``. "Logon User" is the IIS Windows-auth user,
  always empty for this anonymous form login. Browser name/version come from .NET
  browser capabilities; here a small User-Agent parser gives the same style of values
  (e.g. ``Chrome`` / ``118.0``) [Inferred].

Columns are `IP` nvarchar(50) and `WebRequestIdentification` nvarchar(500); values are
cut to fit (legacy EF would fail the insert instead).
"""

import asyncio
import re
import socket

from fastapi import Request


IP_MAX = 50
IDENTIFICATION_MAX = 500
_DNS_TIMEOUT_SECONDS = 0.5

_BROWSERS = (
    ("Edge", re.compile(r"Edg(?:e|A|iOS)?/(\d+)(?:\.(\d+))?")),
    ("Opera", re.compile(r"OPR/(\d+)(?:\.(\d+))?")),
    ("Firefox", re.compile(r"Firefox/(\d+)(?:\.(\d+))?")),
    ("Chrome", re.compile(r"Chrome/(\d+)(?:\.(\d+))?")),
    ("Safari", re.compile(r"Version/(\d+)(?:\.(\d+))?.*Safari/")),
    ("InternetExplorer", re.compile(r"MSIE (\d+)(?:\.(\d+))?")),
    ("InternetExplorer", re.compile(r"Trident/.*rv:(\d+)(?:\.(\d+))?")),
)


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0][:IP_MAX]
    return (request.client.host if request.client else "")[:IP_MAX]


def browser(user_agent: str | None) -> tuple[str, str]:
    ua = user_agent or ""
    for name, pattern in _BROWSERS:
        m = pattern.search(ua)
        if m:
            return name, f"{m.group(1)}.{m.group(2) or 0}"
    return "Unknown", "0.0"


async def _reverse_dns(address: str) -> str:
    if not address:
        return ""
    loop = asyncio.get_running_loop()
    try:
        host, _ = await asyncio.wait_for(
            loop.getnameinfo((address, 0), socket.NI_NAMEREQD), _DNS_TIMEOUT_SECONDS
        )
    except (OSError, TimeoutError, ValueError):
        return ""
    return host


async def web_request_identification(request: Request) -> str:
    socket_address = request.client.host if request.client else ""
    name, version = browser(request.headers.get("user-agent"))
    text = (
        f"Machine Name={await _reverse_dns(socket_address)};"
        f"IP Address={client_ip(request)};"
        "Logon User=;"
        f"Browser Name={name};"
        f"Browser Version={version}"
    )
    return text[:IDENTIFICATION_MAX]
