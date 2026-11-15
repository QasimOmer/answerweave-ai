"""SSRF guard: crawls and webhooks must never reach private networks in production."""
import socket

import pytest

from app import netsafe


@pytest.fixture()
def production(monkeypatch):
    monkeypatch.setenv("AW_BLOCK_PRIVATE_URLS", "1")
    monkeypatch.delenv("AW_ALLOW_PRIVATE_URLS", raising=False)


def fake_dns(monkeypatch, ip):
    def resolver(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]
    monkeypatch.setattr(netsafe.socket, "getaddrinfo", resolver)


@pytest.mark.parametrize("url", ["ftp://example.com", "javascript:alert(1)", "file:///etc/passwd", "", "example.com"])
def test_rejects_non_http_urls(url, production):
    ok, reason = netsafe.check_public_url(url)
    assert not ok
    assert "http" in reason


@pytest.mark.parametrize("ip", [
    "127.0.0.1",        # loopback
    "10.0.0.5",         # private range
    "192.168.1.1",      # private range
    "169.254.169.254",  # cloud metadata endpoint
    "0.0.0.0",
])
def test_blocks_private_addresses_in_production(ip, production, monkeypatch):
    fake_dns(monkeypatch, ip)
    ok, reason = netsafe.check_public_url("https://internal.example.com/")
    assert not ok
    assert "private network" in reason


def test_blocks_ipv4_mapped_ipv6_loopback(production, monkeypatch):
    def resolver(host, port, *a, **k):
        return [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::ffff:127.0.0.1", port, 0, 0))]
    monkeypatch.setattr(netsafe.socket, "getaddrinfo", resolver)
    assert not netsafe.is_public_url("https://sneaky.example.com/")


def test_allows_public_address(production, monkeypatch):
    fake_dns(monkeypatch, "93.184.216.34")
    assert netsafe.check_public_url("https://example.com/") == (True, "")


def test_dns_failure_gives_friendly_message(production, monkeypatch):
    """Regression: Vercel raised OSError(EBUSY) instead of gaierror and the crawl crashed."""
    def resolver(*a, **k):
        raise OSError(16, "Device or resource busy")
    monkeypatch.setattr(netsafe.socket, "getaddrinfo", resolver)
    ok, reason = netsafe.check_public_url("https://no-such-site.example/")
    assert not ok
    assert "couldn't find the website" in reason


def test_local_development_allows_localhost(monkeypatch):
    monkeypatch.delenv("AW_BLOCK_PRIVATE_URLS", raising=False)
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
    assert netsafe.is_public_url("http://localhost:8000/")


def test_serverless_blocks_private_by_default(monkeypatch):
    monkeypatch.delenv("AW_BLOCK_PRIVATE_URLS", raising=False)
    monkeypatch.delenv("AW_ALLOW_PRIVATE_URLS", raising=False)
    monkeypatch.setenv("VERCEL", "1")
    assert not netsafe.private_urls_allowed()
