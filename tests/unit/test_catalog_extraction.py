"""Catalog extraction: only real prices and real listings become catalog items.

Regression for a developer portfolio (General mode) whose Catalog panel listed
"Healthcare Revenue Portal · USA — $780" and "Quick answers about the project… — $780":
the case study says a client "recovered $780M+", which was read as a $780 price, and the
first line of each chunk (a hero eyebrow, an FAQ intro) was taken as the product name.
"""
import json

import pytest

from app import verticals
from app.catalog_intelligence import extract_catalog_items_from_chunk, extract_price_and_currency
from app.ingestion import chunk_text, clean_html

# Trimmed copy of the markup on https://qasim-omer.vercel.app/work/revenue-cycle-attorneys/
CASE_STUDY_HTML = """<!doctype html><html><head><title>Revenue Cycle Attorneys — Qasim Omer</title>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"CreativeWork",
"name":"Revenue Cycle Attorneys","author":{"@type":"Person","name":"Qasim Omer"}}</script></head><body>
<main id="main" class="wrap"><article><div class="ph"><p class="eyebrow">Healthcare Revenue Portal · USA</p>
<h1>Revenue Cycle Attorneys</h1><p class="lede">The healthcare revenue recovery arm of GED Lawyers, having
recovered $780M+ for providers, featuring high-stakes claims evaluation funnels.</p></div>
<dl class="facts"><div class="fact"><dt>Role</dt><dd>Full-Stack Web Engineering, Secure Workflow Integrations &amp; QA</dd></div>
<div class="fact"><dt>Tech Stack</dt><dd>Custom Web Architecture, REST APIs, Automated Regression Testing</dd></div></dl>
<div class="frame"><img src="/assets/img/revenue.webp" width="800" height="500" alt="Interface"></div>
<p class="cap">Production application interface, verified <time datetime="2026-10-15">15 October 2026</time>.</p>
</article>
<section aria-labelledby="qa"><div class="sh"><div><p class="eyebrow">Project Q&amp;A</p>
<h2><span id="qa">Revenue Cycle Attorneys, in short.</span></h2></div>
<div class="side"><p>Quick answers about the project, the role, and the technology.</p></div></div>
<div class="faq"><details open><summary><h3>What is Revenue Cycle Attorneys?</h3></summary>
<p>The healthcare revenue recovery arm of GED Lawyers, having recovered $780M+ for providers, featuring
high-stakes claims evaluation funnels. Category: Healthcare Revenue Portal · USA.
Live at https://www.revenuecycleattorneys.com/.</p></details>
<details><summary><h3>What did Qasim Omer do on Revenue Cycle Attorneys?</h3></summary>
<p>Qasim Omer's role was Full-Stack Web Engineering, Secure Workflow Integrations &amp; QA.</p></details></div>
</section></main></body></html>"""

PRODUCT_HTML = """<html><head><title>Leather Wallet</title>
<script type="application/ld+json">%s</script></head><body><main><h1>Leather Wallet</h1>
<p>Hand-stitched full-grain leather.</p></main></body></html>""" % json.dumps({
    "@context": "https://schema.org", "@type": "Product", "name": "Leather Wallet",
    "offers": {"@type": "Offer", "price": "45.00", "priceCurrency": "USD"},
})


def _items_for_page(html: str, url: str):
    page = clean_html(html, base_url=url)
    items = []
    for i, chunk in enumerate(chunk_text(page["content"]), 1):
        items.extend(extract_catalog_items_from_chunk(chunk, i, url=url, title=page["title"]))
    return items


class TestPriceNeedsACurrencyAndIsNotAStatistic:
    @pytest.mark.parametrize("text", [
        "having recovered $780M+ for providers",
        "a $2B market",
        "raised $1.5 million in seed funding",
        "AED 5bn of transactions",
        "served 10,000+ customers",
        "over $50+ integrations",
    ])
    def test_statistics_are_not_prices(self, text):
        assert extract_price_and_currency(text) == (None, None, None)

    @pytest.mark.parametrize("text", [
        "800x500 hero image, 2026, 15 October",
        "Role: Full-Stack Web Engineering",
    ])
    def test_bare_numbers_are_not_prices(self, text):
        assert extract_price_and_currency(text, require_currency=True)[0] is None

    def test_labelled_number_without_currency_needs_structured_context(self):
        assert extract_price_and_currency("Price: 450", require_currency=True)[0] is None
        assert extract_price_and_currency("Price: 450")[0] == 450.0

    @pytest.mark.parametrize("text,expected", [
        ("$89.99", (89.99, "USD", "")),
        ("Price: 4,500 AED / month", (4500.0, "AED", "month")),
        ("USD 450", (450.0, "USD", "")),
        ("€ 120", (120.0, "EUR", "")),
        ("Only £35 this week", (35.0, "GBP", "")),
        ("Maple Desk $350 Made of maple", (350.0, "USD", "")),
    ])
    def test_real_prices_still_parse(self, text, expected):
        assert extract_price_and_currency(text, require_currency=True) == expected

    def test_skips_a_statistic_and_finds_the_real_price(self):
        assert extract_price_and_currency("Trusted by $5M+ brands. Now $49.") == (49.0, "USD", "")


class TestFaqAndHeadingsAreNotProducts:
    def test_portfolio_case_study_yields_no_catalog_items(self):
        assert _items_for_page(CASE_STUDY_HTML, "https://qasim-omer.vercel.app/work/revenue-cycle-attorneys/") == []

    def test_faq_block_with_a_real_price_is_still_not_a_product(self):
        block = ("Quick answers about the project, the role, and the technology.\n"
                 "How much does a build cost?\nProjects start from $500.")
        assert extract_catalog_items_from_chunk(block) == []

    def test_question_list_is_not_a_product(self):
        block = "Pricing\nIs there a free plan?\nYes.\nWhat does Pro cost?\nPro is $29 per month."
        assert extract_catalog_items_from_chunk(block) == []

    def test_prose_item_with_a_currency_price_still_works(self):
        items = extract_catalog_items_from_chunk("Classic Leather Wallet\nHand-stitched, full grain.\nOnly $45 today.")
        assert [(it["name"], it["price_num"], it["currency"], it["structured"]) for it in items] == [
            ("Classic Leather Wallet", 45.0, "USD", False)]

    def test_schema_org_product_is_extracted(self):
        items = _items_for_page(PRODUCT_HTML, "https://shop.example.com/wallet")
        assert [(it["name"], it["price_num"], it["currency"], it["structured"]) for it in items] == [
            ("Leather Wallet", 45.0, "USD", True)]

    def test_structured_block_without_currency_keeps_its_labelled_price(self):
        block = "🏷️ STRUCTURED PRODUCT SPECIFICATION:\n• Item Name: Oud Perfume\n• Price: 450"
        items = extract_catalog_items_from_chunk(block)
        assert [(it["name"], it["price_num"]) for it in items] == [("Oud Perfume", 450.0)]


class _FakeIndex:
    def __init__(self, items_per_chunk):
        self.chunks = [{} for _ in items_per_chunk]
        self._items = items_per_chunk

    def catalog_items(self, i):
        return self._items[i]


def _prose(name):
    return {"name": name, "url": f"https://site.example/{name}", "structured": False, "entity_type": "product"}


@pytest.fixture()
def fake_index(monkeypatch):
    def install(*items):
        index = _FakeIndex([[it] for it in items])
        monkeypatch.setattr(verticals, "_get_index", lambda _aid: index)
    return install


class TestGeneralModeIsConservative:
    def test_general_mode_hides_prose_items(self, fake_index):
        fake_index(_prose("a"), _prose("b"), _prose("c"))
        assert verticals.all_catalog_items("asst", "general") == []

    def test_auto_mode_ignores_a_couple_of_stray_prose_prices(self, fake_index):
        fake_index(_prose("a"), _prose("b"))
        assert verticals.all_catalog_items("asst") == []
        assert verticals.resolve_industry({"industry": "auto", "name": "Qasim Omer"}, "asst") == "general"

    def test_ecommerce_mode_keeps_prose_items(self, fake_index):
        fake_index(_prose("a"))
        assert [it["name"] for it in verticals.all_catalog_items("asst", "ecommerce")] == ["a"]

    def test_structured_items_win_in_every_mode(self, fake_index):
        fake_index(_prose("a"), {**_prose("b"), "structured": True})
        for industry in ("auto", "general", "ecommerce"):
            assert [it["name"] for it in verticals.all_catalog_items("asst", industry)] == ["b"]
