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

URBANKICKS_PRODUCTS = {
    "title": "UrbanKicks Footwear Catalog",
    "url": "https://urbankicks.shop/products",
    "content": """# UrbanKicks Official Product Catalog
==================================================
🏷️ PRODUCT SPECIFICATION: CloudStride Daily Runner
• Price: 249 AED
• Category / Type: Running Shoes
• Key Specs & Features: Breathable Mesh • CloudFoam Cushioning • Available in Sizes 38-46
• Direct URL: https://urbankicks.shop/products/cloudstride
==================================================
🏷️ PRODUCT SPECIFICATION: StreetGlide Retro Low Sneaker
• Price: 389 AED
• Category / Type: Casual Sneakers
• Key Specs & Features: Premium Leather • Vintage Gum Sole • Unisex Design
• Direct URL: https://urbankicks.shop/products/streetglide-retro
==================================================
🏷️ PRODUCT SPECIFICATION: AeroSpeed Carbon Marathon Racer
• Price: 479 AED
• Category / Type: Performance Running
• Key Specs & Features: Carbon Fiber Plate • Ultra-light 185g • Energy Return Foam
• Direct URL: https://urbankicks.shop/products/aerospeed-carbon
==================================================
🏷️ PRODUCT SPECIFICATION: UrbanHiker Waterproof Trail Boot
• Price: 699 AED
• Category / Type: Outdoor & Hiking
• Key Specs & Features: Gore-Tex Waterproof • Vibram Traction Lug Sole
• Direct URL: https://urbankicks.shop/products/urbanhiker-boot
=================================================="""
}

IDEALHOMES_PROPERTIES = {
    "title": "Ideal Homes Dubai Properties & Rental Catalog",
    "url": "https://idealhomes.ae/listings",
    "content": """# Ideal Homes Dubai Featured Rental & Sale Properties
==================================================
🏠 PROPERTY LISTING (FOR RENT): Furnished Studio in Dubai Silicon Oasis
• Price: 950 AED / month
• Deal Type: Rental
• Category / Type: Studio Apartment
• Location / Neighborhood: Dubai Silicon Oasis (DSO), Dubai
• Key Specs & Features: Studio • 1 Bath • 420 sqft • High-speed WiFi & DEWA included • Balcony
• Direct URL: https://idealhomes.ae/rent/dso-studio-950
==================================================
🏠 PROPERTY LISTING (FOR RENT): Cozy Studio in Jumeirah Village Circle
• Price: $850 / month
• Deal Type: Rental
• Category / Type: Studio Apartment
• Location / Neighborhood: Jumeirah Village Circle (JVC), Dubai
• Key Specs & Features: Studio • 1 Bath • 460 sqft • Pool & Gym Access • Near Circle Mall
• Direct URL: https://idealhomes.ae/rent/jvc-studio-850
==================================================
🏠 PROPERTY LISTING (FOR RENT): 1-Bedroom Apartment in Al Barsha 1
• Price: 3,800 AED / month
• Deal Type: Rental
• Category / Type: 1-Bedroom Apartment
• Location / Neighborhood: Al Barsha 1, Dubai
• Key Specs & Features: 1 Bed • 2 Baths • 780 sqft • Near Mall of the Emirates & Metro
• Direct URL: https://idealhomes.ae/rent/barsha-1bed
==================================================
🏠 PROPERTY LISTING (FOR RENT): 2-Bedroom Modern Apartment in Dubai Marina
• Price: 7,500 AED / month
• Deal Type: Rental
• Category / Type: 2-Bedroom Apartment
• Location / Neighborhood: Dubai Marina, Dubai
• Key Specs & Features: 2 Beds • 2 Baths • 1,200 sqft • Full Marina View • Chiller Free
• Direct URL: https://idealhomes.ae/rent/marina-2bed
==================================================
🏠 PROPERTY LISTING (FOR SALE): 3-Bedroom Villa in Arabian Ranches
• Price: 3,250,000 AED
• Deal Type: For Sale
• Category / Type: Villa
• Location / Neighborhood: Arabian Ranches, Dubai
• Key Specs & Features: 3 Beds • 4 Baths • 3,100 sqft • Private Garden • Near Community Park
• Direct URL: https://idealhomes.ae/buy/ranches-villa
=================================================="""
}

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
                'Hey there! 👟 Need help finding shoes under your budget, shipping, or returns?', '👟',
                'bottom-right', 'Do you have running shoes under 500 AED?\nWhat is your return policy?\nHow long does shipping take?', 1, 1
            );
        """)
        conn.commit()
        conn.close()

    print("  Adding UrbanKicks sources & product catalog...")
    for doc in URBANKICKS_DOCS + [URBANKICKS_PRODUCTS]:
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

    # 3. Seed Ideal Homes Real Estate Properties Catalog
    print("  Adding Ideal Homes real estate rental & sale catalog...")
    asst_re = get_assistant("asst_8667289e")
    re_id = "asst_8667289e" if asst_re else "asst_realestate"
    if not asst_re:
        from app.db import get_db
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO assistants (
                id, name, domain, primary_color, welcome_message, bot_avatar,
                position, suggested_questions, lead_capture_enabled, voice_enabled
            ) VALUES (
                'asst_realestate', 'Ideal Homes Real Estate', 'idealhomes.ae', '#1e3a8a',
                'Hello! 🏡 Welcome to Ideal Homes. Looking for properties to rent or buy in Dubai?', '🏡',
                'bottom-right', 'Any rental property under 1000 aed or $?\nShow me apartments in JVC or Downtown\nHow can I speak to a leasing agent?', 1, 1
            );
        """)
        conn.commit()
        conn.close()

    doc = IDEALHOMES_PROPERTIES
    source_id = add_source(re_id, "text", doc["title"], doc["url"], doc["content"])
    chunks = chunk_text(doc["content"])
    embeddings = generate_embeddings_batch(chunks)
    for idx, (c_text, emb) in enumerate(zip(chunks, embeddings)):
        add_chunk(re_id, source_id, idx, c_text, doc["title"], doc["url"], emb)
    update_source_chunk_count(source_id, len(chunks))

    print("✨ Multi-Site SaaS Database Seeded Successfully!")

if __name__ == "__main__":
    seed()
