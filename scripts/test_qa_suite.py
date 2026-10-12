import sys, os
sys.path.insert(0, os.path.abspath("."))
from app.rag import generate_grounded_response

test_cases = [
    # EcomAlign
    ("asst_0ea55267", "EcomAlign", [
        "What services do you provide?",
        "what are your services",
        "Who is the founder?",
        "Who is the owner?",
        "Who runs this company?",
        "Where are you located?",
        "What is your address?",
        "How can I contact you?",
        "What is your phone number?",
        "What are your timings",
        "Tell me about EcomAlign",
        "What is your pricing?",
        "How much does it cost?",
        "Do you manage Amazon stores?",
        "What is your return policy?"
    ]),
    # Ideal Homes
    ("asst_8667289e", "Ideal Homes", [
        "What services do you provide?",
        "i need your contact number to discuss renewal",
        "How can I contact you?",
        "Where is your office located?",
        "Who is the founder?",
        "Who is the CEO?",
        "Tell me about Ideal Homes",
        "What are your property management services?",
        "Do you have properties for rent?",
        "Do you have properties for sale?"
    ]),
    # Prep
    ("asst_f38450f1", "Prep", [
        "What services do you provide?",
        "How much is the membership?",
        "What is your pricing?",
        "How do you handle warehouse stock?",
        "How can I contact you?",
        "What is your refund policy?"
    ]),
    # Logic Leap
    ("asst_c7461166", "Logic Leap", [
        "What services do you provide?",
        "type of projects u do",
        "How can I speak to someone?",
        "Do you offer AI chatbot development?",
        "Where are you located?",
        "How can I contact you?"
    ])
]

print("=== STARTING COMPREHENSIVE QA EVALUATION ===", flush=True)
total_tests = 0
failed_tests = 0

for asst_id, asst_name, questions in test_cases:
    print(f"\n==========================================", flush=True)
    print(f"EVALUATING: {asst_name} ({asst_id})", flush=True)
    print(f"==========================================", flush=True)
    for q in questions:
        total_tests += 1
        res = generate_grounded_response(q, assistant_id=asst_id)
        ans = res.get("answer", "").strip()
        is_apology = "I apologize, but I do not have enough details" in ans
        has_real_estate_in_ecom = "real estate" in ans.lower() and asst_name != "Ideal Homes"
        has_catalog_price_in_founder = "USD 25.00" in ans and "founder" in q.lower()
        
        failed = is_apology or has_real_estate_in_ecom or has_catalog_price_in_founder or len(ans) < 25
        if failed:
            failed_tests += 1
            print(f"❌ FAIL: Q: {q}", flush=True)
            print(f"   Reason: {'Apology fallback' if is_apology else ('Real estate hallucination' if has_real_estate_in_ecom else ('Catalog pricing in founder' if has_catalog_price_in_founder else 'Too short/empty'))}", flush=True)
            print(f"   Output: {ans[:180].replace(chr(10), ' ')}...", flush=True)
        else:
            print(f"✅ PASS: Q: {q}", flush=True)
            print(f"   Output: {ans[:140].replace(chr(10), ' ')}...", flush=True)

print(f"\n==========================================", flush=True)
print(f"TOTAL: {total_tests} | PASSED: {total_tests - failed_tests} | FAILED: {failed_tests}", flush=True)
print(f"FAILURE RATE: {(failed_tests / total_tests) * 100:.1f}%", flush=True)
