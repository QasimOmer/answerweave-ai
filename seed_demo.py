"""
Seeds multiple sample websites and assistants into the database.
Showcases multi-website isolation and AI Call-Prep briefs.
"""

from app.db import (
    init_db,
    create_assistant,
    get_assistant,
    add_source,
    add_chunk,
    update_source_chunk_count,
    add_lead
)
from app.ingestion import chunk_text
from app.embeddings import generate_embeddings_batch

ACME_DOCS = [
    {
        "title": "AcmeCloud Products & Platform Overview",
        "url": "https://acmecloud.io/products",
        "content": """AcmeCloud provides next-generation cloud infrastructure for engineering teams.
Key features include:
1. Serverless Functions: Instant cold starts under 15ms, auto-scaling to 100,000 requests per second.
2. Edge CDN: Global distribution across 120+ edge points of presence with automated SSL certificates.
3. Managed Microservices: Deploy containerized services with automated health checks, blue-green deployments, and canary testing.
4. Database Replication: Multi-region active-active PostgreSQL and SQLite edge replication with sub-5ms read latency.
All services operate with a 99.99% uptime Service Level Agreement."""
    },
    {
        "title": "Pricing & Subscription Plans",
        "url": "https://acmecloud.io/pricing",
        "content": """AcmeCloud offers flexible pricing tiers:
- Starter Tier: $29 per month. Includes 5 team members, 100GB fast edge bandwidth, and community Discord support.
- Growth Tier: $99 per month. Includes unlimited team members, 1TB edge bandwidth, custom domains, and standard email support (response within 12 hours).
- Enterprise Tier: Custom pricing starting at $499 per month. Includes dedicated VPC peering, SOC2 Type II compliance guarantees, 99.99% uptime SLA, and 24/7 dedicated phone & Slack support.
Discounts: Annual subscriptions receive a 20% discount across all tiers. Non-profit and open-source projects can apply for free sponsored tier access."""
    },
    {
        "title": "Customer Support & Contact Methods",
        "url": "https://acmecloud.io/support",
        "content": """How to reach AcmeCloud support:
- Email Support: Available for all customers at support@acmecloud.io.
- Sales & Enterprise Solutions: Contact sales@acmecloud.io for custom migration quotes, enterprise security questionnaires, or custom contracts.
- Office Locations: AcmeCloud headquarters is located at 500 Cloud Way, San Francisco, CA 94107.
- Working Hours: Support is available Monday through Friday, 8am to 8pm EST. Enterprise tier customers have access to 24/7 on-call emergency paging."""
    }
]

URBANKICKS_DOCS = [
    {
        "title": "Shipping & Delivery Policy",
        "url": "https://urbankicks.shop/shipping",
        "content": """UrbanKicks ships worldwide!
- Standard US Shipping: 3-5 business days ($5.99, or FREE on orders over $75).
- Express 2-Day Air: 2 business days ($14.99).
- International Shipping: 7-12 business days with full customs tracking.
All orders receive a tracking number via email within 24 hours of fulfillment."""
    },
    {
        "title": "30-Day Return & Size Exchange Guarantee",
        "url": "https://urbankicks.shop/returns",
        "content": """UrbanKicks offers a 30-day hassle-free return and exchange guarantee.
Shoes must be in unworn condition with original packaging and tags attached.
To initiate a return: Visit urbankicks.shop/returns, enter your order number, and print the pre-paid return shipping label. Exchanges for alternate shoe sizes are completely free."""
    }
]

def seed():
    init_db()
    print("🌱 Seeding Multi-Site SaaS Database...")

    # 1. Seed AcmeCloud Assistant
    print("  Adding AcmeCloud sources...")
    for doc in ACME_DOCS:
        source_id = add_source("asst_default", "text", doc["title"], doc["url"], doc["content"])
        chunks = chunk_text(doc["content"])
        embeddings = generate_embeddings_batch(chunks)
        for idx, (c_text, emb) in enumerate(zip(chunks, embeddings)):
            add_chunk("asst_default", source_id, idx, c_text, doc["title"], doc["url"], emb)
        update_source_chunk_count(source_id, len(chunks))

    # Add sample lead with AI Call-Prep Brief
    add_lead(
        assistant_id="asst_default",
        email="alex.turner@vanguard.io",
        name="Alex Turner",
        phone="+1 (415) 890-1234",
        note="Requested quote for 40 developer seats",
        conversation_summary="Prospect inquired about Growth vs Enterprise tiers and SOC2 compliance.",
        ai_call_prep_brief="""• Primary Inquiries: Enterprise tier pricing, dedicated VPC peering, and SOC2 certification timeline.
• Detected Intent & Urgency: HIGH (Evaluating migration from AWS within current quarter).
• Potential Objections: Migration complexity from existing ECS clusters.
• Recommended Next Steps for Sales Rep:
  1. Confirm SOC2 Type II audit report availability under NDA.
  2. Offer a free sandbox migration environment with solutions engineer assistance.
  3. Propose a follow-up call with enterprise architecture team."""
    )

    # 2. Seed UrbanKicks Assistant
    asst_store = get_assistant("asst_store")
    if not asst_store:
        from app.db import get_db
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO assistants (
                id, name, domain, primary_color, welcome_message, bot_avatar,
                position, suggested_questions, lead_capture_enabled, voice_enabled
            ) VALUES (
                'asst_store', 'UrbanKicks Concierge', 'urbankicks.shop', '#059669',
                'Hey there! 👟 Need help with shoe sizes, shipping, or returns?', '👟',
                'bottom-right', 'How long does shipping take?\nWhat is your return policy?\nDo you offer size exchanges?', 1, 1
            );
        """)
        conn.commit()
        conn.close()

    print("  Adding UrbanKicks sources...")
    for doc in URBANKICKS_DOCS:
        source_id = add_source("asst_store", "text", doc["title"], doc["url"], doc["content"])
        chunks = chunk_text(doc["content"])
        embeddings = generate_embeddings_batch(chunks)
        for idx, (c_text, emb) in enumerate(zip(chunks, embeddings)):
            add_chunk("asst_store", source_id, idx, c_text, doc["title"], doc["url"], emb)
        update_source_chunk_count(source_id, len(chunks))

    add_lead(
        assistant_id="asst_store",
        email="sarah.m@gmail.com",
        name="Sarah Miller",
        note="Looking for wide-width running sneakers",
        conversation_summary="Inquired about return policy if size doesn't fit properly.",
        ai_call_prep_brief="""• Primary Inquiries: Return policy on shoe sizing.
• Detected Intent & Urgency: High buying intent (worried about sizing fit).
• Recommended Next Steps:
  1. Highlight 30-day free size exchanges.
  2. Send link to UrbanKicks printable size guide."""
    )

    print("✨ Multi-Site SaaS Database Seeded Successfully!")

if __name__ == "__main__":
    seed()
