# Hi Bot - Multi-Website Grounded Chatbot & Lead Capture SaaS

[![Tests](https://github.com/QasimOmer/answerweave-ai/actions/workflows/tests.yml/badge.svg)](https://github.com/QasimOmer/answerweave-ai/actions/workflows/tests.yml)

**Hi Bot** is a complete, production-ready SaaS platform powered by **Grounded RAG**, **Zero Hallucination Guardrails**, **AI Call-Prep Briefs**, and **Multi-Website Tenancy**.

---

## 🌟 Key SaaS Capabilities

1. **Multi-Website / Multi-Assistant Management:**
   - Manage multiple client websites or separate brands from a single SaaS dashboard.
   - Each website assistant has an isolated knowledge base, custom branding, domain whitelist, and dedicated lead pipeline.

2. **1-Line Embeddable Chat Widget (`widget.js`):**
   - Drop into **any website** (WordPress, Shopify, Webflow, React, HTML) using a single script tag:
     ```html
     <script src="http://localhost:8000/static/widget.js" data-assistant-id="asst_default"></script>
     ```
   - Includes **Voice Question Support (Microphone 🎤)** via browser speech recognition.

3. **Strict Zero-Hallucination Grounding:**
   - Adheres exclusively to your verified website pages, PDFs, and FAQs.
   - Refuses to invent facts when answers are not documented, stating the limitation and prompting for contact info.
   - Displays verifiable inline source citations (`[1]`, `[2]`).

4. **Lead Capture & Signature AI Call-Prep Briefs:**
   - Captures visitor leads directly in the chat stream.
   - Automatically generates an **Executive AI Call-Prep Brief** for every lead (intent level, pain points, and recommended talking points for the sales rep).
   - Export leads to CSV with 1 click or send real-time webhooks.

5. **Multi-Engine AI Support:**
   - **SiliconFlow (Free Chinese DeepSeek-V3 & Qwen 2.5):** Free credits on registration, high-speed OpenAI-compatible API.
   - **DeepSeek Official:** DeepSeek-V3 and DeepSeek-R1.
   - **Alibaba Qwen:** DashScope Qwen-plus / Qwen-turbo.
   - **Groq (Free Llama 3.3):** Instant setup with zero credit card required.
   - **Google Gemini (Free tier):** Gemini 2.5 / 1.5 Flash.
   - **OpenAI:** GPT-4o-mini.
   - **Zero-API-Key Local Engine (Active out-of-the-box):** 100% free, runs offline without any API key.

---

## 🧪 Testing

78 automated tests in three layers, run by GitHub Actions on every push and daily against production:

| Layer | Tool | What it covers |
|---|---|---|
| Unit (`tests/unit`) | PyTest | SSRF guard (private IPs, cloud metadata, DNS errors), PBKDF2 password hashing and legacy-hash upgrade, the no-invented-links filter, prompt-injection deflection, human hand-off detection, same-site crawl rules |
| API (`tests/api`) | PyTest + FastAPI TestClient | Sign-up/sign-in, token tampering, sessions revoked on password change, no account enumeration, every private route rejects anonymous calls, widget caching and chat input limits |
| Browser (`tests/e2e`) | Playwright | Landing page, sign-in errors, dashboard access control, no horizontal scroll at phone/tablet/desktop widths, no JavaScript errors on the widget demo |

Unit and API tests run offline against a throwaway SQLite database (the suite refuses to start if it can see any other database) and finish in about 4 seconds.

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest                                   # unit + API
python -m playwright install chromium
pytest tests/e2e --base-url https://answerweave-ai.vercel.app   # browser tests
```

Several tests are regression tests for real production bugs, e.g. Vercel raising `OSError: [Errno 16]` instead of a DNS error, and an off-site sitemap entry breaking a crawl.

---

## ⚡ Deploying to Vercel via GitHub

This repository is pre-configured for **instant serverless deployment on Vercel**:
- `api/index.py`: Serverless ASGI entry point.
- `vercel.json`: Automated URL rewrites for all REST routes and static assets.
- `requirements.txt`: Python package specification.

### Step 1: Push Code to GitHub
```bash
git init
git add .
git commit -m "Initial commit of Hi Bot"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPOSITORY.git
git push -u origin main
```

### Step 2: Import into Vercel
1. Go to [vercel.com/new](https://vercel.com/new) and log in with your GitHub account.
2. Select your newly pushed repository and click **Import**.
3. Leave Framework Preset as **Other** (Vercel automatically detects Python serverless functions via `api/index.py` and `vercel.json`).
4. (Optional) In **Environment Variables**, add:
   - `SILICONFLOW_API_KEY`: *(Optional free Chinese model key)*
   - `GEMINI_API_KEY`: *(Optional Google Gemini key)*
   - `GROQ_API_KEY`: *(Optional Groq key)*
5. Click **Deploy**!

Within ~60 seconds, your Hi Bot platform will be live at `https://your-project.vercel.app` with free SSL!

---

## 🚀 Local Development

Run the server locally using Python 3:
```powershell
py -3 run.py
```

### Accessing the SaaS Applications
- **SaaS Admin Console & Multi-Site Manager:** [http://127.0.0.1:8000](http://127.0.0.1:8000)
- **Live Multi-Website Simulator:** [http://127.0.0.1:8000/demo](http://127.0.0.1:8000/demo)
- **Interactive OpenAPI Documentation:** [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
