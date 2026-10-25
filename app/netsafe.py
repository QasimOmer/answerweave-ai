"""
Outbound-request safety: stops crawls, install checks and webhooks from being
pointed at private networks (cloud metadata endpoints, internal services).

Private addresses are blocked on serverless/production hosts (Vercel, Lambda)
or when AW_BLOCK_PRIVATE_URLS=1. Local development can crawl localhost sites;
set AW_ALLOW_PRIVATE_URLS=1 to allow them anywhere.
"""

import ipaddress
import os
import socket
import urllib.parse
from typing import Tuple


def private_urls_allowed() -> bool:
    if os.environ.get("AW_ALLOW_PRIVATE_URLS") == "1":
        return True
    if os.environ.get("AW_BLOCK_PRIVATE_URLS") == "1":
        return False
    return not (os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))


def _is_private_ip(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return (addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved
            or addr.is_multicast or addr.is_unspecified)


def check_public_url(url: str) -> Tuple[bool, str]:
    """(ok, reason). Only http(s) URLs, and only public hosts unless private ones are allowed."""
    try:
        parsed = urllib.parse.urlparse((url or "").strip())
    except ValueError:
        return False, "That address isn't a valid URL."
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False, "Only http:// and https:// addresses are supported."
    if private_urls_allowed():
        return True, ""
    host = parsed.hostname
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return False, f"We couldn't find the website {host}. Check the address."
    for info in infos:
        if _is_private_ip(info[4][0]):
            return False, "That address points to a private network, which isn't allowed."
    return True, ""


def is_public_url(url: str) -> bool:
    return check_public_url(url)[0]
