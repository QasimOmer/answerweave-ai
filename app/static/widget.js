/**
 * WeaveFlow AI - Premium Embedded Chatbot Widget
 * Crafted to match senior UI/UX standards (Inspired by Fin / HazenTech Reference):
 * - Dark Obsidian / Navy Header with Status Indicator & Top Quick Actions
 * - Dotted Matrix Pattern Canvas Background
 * - "Popular questions" Interactive Prompts with Bullet Points & Arrow Transitions
 * - Rounded Bubble Dialogues & Grounded Source Citations
 * - In-Chat & Drawer Lead Capture Forms
 * - Speech-to-Text Microphone Voice Input
 * - Multi-Website Tenancy & Dynamic Branding
 */

(function () {
    if (window.WeaveFlowWidgetInitialized) return;
    window.WeaveFlowWidgetInitialized = true;

    const currentScript = document.currentScript || (function () {
        const scripts = document.getElementsByTagName('script');
        return scripts[scripts.length - 1];
    })();

    const API_BASE = currentScript.getAttribute('data-api-url') || window.location.origin;
    const ASSISTANT_ID = currentScript.getAttribute('data-assistant-id') || "asst_default";

    let botConfig = {
        name: "HazenTech Assistant",
        primary_color: "#081726",
        welcome_message: "Hi! How can I help you today?",
        bot_avatar: "⚡",
        position: "bottom-right",
        widget_subtitle: "Online",
        suggested_questions: "What legal process outsourcing services do you offer?\nCan you build a custom AI solution for my business?\nHow does HazenTech save firms 50% on back-office costs?",
        lead_capture_enabled: 1,
        voice_enabled: 1,
        launcher_style: "circle",
        teaser_message: "👋 Hi! Need quick answers?",
        show_branding: 1
    };

    let conversationId = sessionStorage.getItem(`wf_conv_${ASSISTANT_ID}`) || (`wf_${ASSISTANT_ID}_${Math.random().toString(36).substring(2, 10)}`);
    sessionStorage.setItem(`wf_conv_${ASSISTANT_ID}`, conversationId);

    let isOpen = false;
    let isRecording = false;
    let recognition = null;
    let isLeadDrawerOpen = false;

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (SpeechRecognition) {
        recognition = new SpeechRecognition();
        recognition.continuous = false;
        recognition.interimResults = false;
        recognition.lang = 'en-US';
    }

    // Inject Styles
    const style = document.createElement('style');
    style.id = 'wf-widget-styles';
    style.innerHTML = `
        @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');

        .wf-root {
            position: fixed;
            bottom: 24px;
            right: 24px;
            z-index: 2147483647;
            font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
            -webkit-font-smoothing: antialiased;
            color: #0f172a;
        }
        .wf-position-left {
            right: auto !important;
            left: 24px !important;
        }

        /* Launcher Floating Action Button */
        .wf-launcher-wrap {
            position: relative;
            display: flex;
            align-items: center;
            justify-content: flex-end;
        }
        .wf-position-left .wf-launcher-wrap {
            justify-content: flex-start;
        }

        .wf-teaser-bubble {
            position: absolute;
            bottom: 72px;
            right: 0;
            background: #ffffff;
            color: #0f172a;
            padding: 10px 16px;
            border-radius: 18px 18px 4px 18px;
            box-shadow: 0 10px 25px -4px rgba(0, 0, 0, 0.15), 0 2px 6px rgba(0, 0, 0, 0.05);
            border: 1px solid rgba(226, 232, 240, 0.9);
            font-size: 13px;
            font-weight: 600;
            white-space: nowrap;
            cursor: pointer;
            transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
            animation: wfFadeUp 0.3s ease-out;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .wf-position-left .wf-teaser-bubble {
            right: auto;
            left: 0;
            border-radius: 18px 18px 18px 4px;
        }
        .wf-teaser-bubble:hover {
            transform: translateY(-2px);
            box-shadow: 0 14px 30px -4px rgba(0, 0, 0, 0.2);
        }
        .wf-teaser-close {
            color: #94a3b8;
            font-size: 14px;
            padding: 2px;
            cursor: pointer;
        }
        .wf-teaser-close:hover { color: #475569; }

        .wf-launcher {
            width: 60px;
            height: 60px;
            border-radius: 50%;
            background: #081726;
            box-shadow: 0 10px 30px -4px rgba(8, 23, 38, 0.4), 0 4px 8px rgba(0,0,0,0.1);
            border: 1px solid rgba(255, 255, 255, 0.15);
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            color: #ffffff;
            transition: transform 0.25s cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 0.25s ease;
            outline: none;
            user-select: none;
        }
        .wf-launcher:hover {
            transform: scale(1.08);
            box-shadow: 0 14px 36px -4px rgba(8, 23, 38, 0.5), 0 6px 12px rgba(0,0,0,0.15);
        }

        /* Widget Container Window */
        .wf-window {
            position: fixed;
            bottom: 96px;
            right: 24px;
            width: 390px;
            height: 620px;
            max-width: calc(100vw - 32px);
            max-height: calc(100vh - 120px);
            background: #ffffff;
            border-radius: 26px;
            box-shadow: 0 25px 60px -12px rgba(15, 23, 42, 0.28), 0 4px 16px rgba(0, 0, 0, 0.06);
            display: flex;
            flex-direction: column;
            overflow: hidden;
            opacity: 0;
            pointer-events: none;
            transform: translateY(20px) scale(0.95);
            transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
            z-index: 2147483647;
            border: 1px solid rgba(226, 232, 240, 0.8);
        }
        .wf-position-left .wf-window {
            right: auto;
            left: 24px;
        }
        .wf-window.wf-open {
            opacity: 1;
            pointer-events: auto;
            transform: translateY(0) scale(1);
        }

        /* Header Bar (Matches HazenTech dark aesthetic) */
        .wf-header {
            background: #081726;
            color: #ffffff;
            padding: 16px 20px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            border-bottom: 1px solid rgba(255, 255, 255, 0.08);
            user-select: none;
            shrink: 0;
        }
        .wf-header-left {
            display: flex;
            align-items: center;
            gap: 12px;
        }
        .wf-avatar-circle {
            width: 42px;
            height: 42px;
            border-radius: 50%;
            background: #ffffff;
            color: #081726;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 20px;
            font-weight: 800;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
            overflow: hidden;
            shrink: 0;
        }
        .wf-avatar-circle img {
            width: 100%;
            height: 100%;
            object-fit: cover;
        }
        .wf-header-info {
            display: flex;
            flex-direction: column;
        }
        .wf-header-title {
            font-weight: 700;
            font-size: 15px;
            color: #ffffff;
            line-height: 1.2;
            letter-spacing: -0.01em;
        }
        .wf-status-row {
            display: flex;
            align-items: center;
            gap: 6px;
            margin-top: 3px;
            font-size: 11.5px;
            color: #94a3b8;
            font-weight: 500;
        }
        .wf-status-dot {
            width: 7px;
            height: 7px;
            border-radius: 50%;
            background: #10b981;
            box-shadow: 0 0 10px #10b981;
        }

        /* Top Header Action Buttons */
        .wf-header-actions {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .wf-header-divider {
            width: 1px;
            height: 20px;
            background: rgba(255, 255, 255, 0.15);
            margin: 0 4px;
        }
        .wf-icon-btn {
            background: transparent;
            border: none;
            color: #94a3b8;
            width: 32px;
            height: 32px;
            border-radius: 8px;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: all 0.15s ease;
            outline: none;
        }
        .wf-icon-btn:hover {
            color: #ffffff;
            background: rgba(255, 255, 255, 0.1);
        }

        /* Chat Body Canvas with Dotted Pattern */
        .wf-chat-body {
            flex: 1;
            padding: 18px;
            overflow-y: auto;
            background-color: #f8fafc;
            background-image: radial-gradient(#cbd5e1 1.2px, transparent 1.2px);
            background-size: 16px 16px;
            display: flex;
            flex-direction: column;
            gap: 14px;
            scroll-behavior: smooth;
        }

        /* Message Bubbles */
        .wf-bubble {
            display: flex;
            flex-direction: column;
            max-width: 88%;
            font-size: 13.5px;
            line-height: 1.55;
            animation: wfFadeUp 0.25s cubic-bezier(0.16, 1, 0.3, 1);
        }
        @keyframes wfFadeUp {
            from { opacity: 0; transform: translateY(8px); }
            to { opacity: 1; transform: translateY(0); }
        }

        /* Welcome Message Bubble */
        .wf-welcome-bubble {
            align-self: flex-start;
            background: #ffffff;
            color: #0f172a;
            padding: 12px 18px;
            border-radius: 18px 18px 18px 6px;
            border: 1px solid #e2e8f0;
            box-shadow: 0 2px 10px rgba(0, 0, 0, 0.04);
            font-size: 13.5px;
            font-weight: 500;
        }

        /* Popular Questions Header (Vertical Accent Bar) */
        .wf-popular-section {
            margin-top: 6px;
            margin-bottom: 2px;
        }
        .wf-popular-head {
            display: flex;
            align-items: flex-start;
            gap: 10px;
            margin-bottom: 12px;
        }
        .wf-popular-bar {
            width: 3.5px;
            height: 24px;
            background: #081726;
            border-radius: 4px;
            shrink: 0;
            margin-top: 1px;
        }
        .wf-popular-title {
            font-size: 14.5px;
            font-weight: 700;
            color: #0f172a;
            line-height: 1.2;
            letter-spacing: -0.01em;
        }
        .wf-popular-sub {
            font-size: 12px;
            color: #64748b;
            margin-top: 3px;
        }

        /* Popular Question Cards (Full-Width Pill with Dot & Arrow) */
        .wf-popular-cards {
            display: flex;
            flex-direction: column;
            gap: 9px;
        }
        .wf-question-card {
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 20px;
            padding: 13px 18px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            cursor: pointer;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.03);
            transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
            text-align: left;
            width: 100%;
            outline: none;
        }
        .wf-question-card:hover {
            transform: translateY(-2px);
            border-color: #cbd5e1;
            box-shadow: 0 6px 16px rgba(0, 0, 0, 0.06);
            background: #fdfdfd;
        }
        .wf-question-left {
            display: flex;
            align-items: center;
            gap: 10px;
            flex: 1;
        }
        .wf-question-dot {
            width: 6px;
            height: 6px;
            border-radius: 50%;
            background: #94a3b8;
            shrink: 0;
        }
        .wf-question-text {
            font-size: 13px;
            font-weight: 600;
            color: #1e293b;
            line-height: 1.35;
        }
        .wf-question-arrow {
            color: #94a3b8;
            font-size: 14px;
            font-weight: 600;
            shrink: 0;
            transition: transform 0.15s ease, color 0.15s ease;
        }
        .wf-question-card:hover .wf-question-arrow {
            color: #081726;
            transform: translateX(3px);
        }

        /* User Message Bubble */
        .wf-bubble-user {
            align-self: flex-end;
            background: #081726;
            color: #ffffff;
            padding: 11px 16px;
            border-radius: 18px 18px 4px 18px;
            box-shadow: 0 3px 10px rgba(8, 23, 38, 0.18);
            font-weight: 500;
        }

        /* Assistant Grounded Bubble */
        .wf-bubble-bot {
            align-self: flex-start;
            background: #ffffff;
            color: #0f172a;
            padding: 13px 16px;
            border-radius: 18px 18px 18px 4px;
            border: 1px solid #e2e8f0;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.03);
        }

        /* Citations list inside message */
        .wf-citations {
            margin-top: 10px;
            padding-top: 8px;
            border-top: 1px solid #f1f5f9;
            display: flex;
            flex-wrap: wrap;
            gap: 5px;
        }
        .wf-citation-pill {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            background: #f1f5f9;
            border: 1px solid #cbd5e1;
            border-radius: 6px;
            padding: 3px 8px;
            font-size: 11px;
            font-weight: 600;
            color: #2563eb;
            text-decoration: none;
            transition: all 0.15s;
        }
        .wf-citation-pill:hover {
            background: #eff6ff;
            border-color: #93c5fd;
            color: #1d4ed8;
        }

        /* Lead Capture Card inside chat */
        .wf-lead-card {
            background: #ffffff;
            border: 1px solid #cbd5e1;
            border-radius: 16px;
            padding: 16px;
            box-shadow: 0 4px 14px rgba(0, 0, 0, 0.05);
            margin-top: 6px;
            align-self: flex-start;
            width: 100%;
            max-width: 90%;
            box-sizing: border-box;
        }
        .wf-lead-card h4 {
            margin: 0 0 4px 0;
            font-size: 13.5px;
            font-weight: 700;
            color: #0f172a;
        }
        .wf-lead-card p {
            margin: 0 0 10px 0;
            font-size: 11.5px;
            color: #64748b;
        }
        .wf-lead-input {
            width: 100%;
            padding: 9px 12px;
            border: 1px solid #cbd5e1;
            border-radius: 10px;
            font-size: 12px;
            margin-bottom: 8px;
            box-sizing: border-box;
            outline: none;
            background: #f8fafc;
            transition: all 0.15s;
            font-family: inherit;
        }
        .wf-lead-input:focus {
            border-color: #081726;
            background: #ffffff;
            box-shadow: 0 0 0 2px rgba(8, 23, 38, 0.08);
        }
        .wf-lead-btn {
            width: 100%;
            background: #081726;
            color: #ffffff;
            border: none;
            padding: 10px;
            border-radius: 10px;
            font-weight: 700;
            font-size: 12.5px;
            cursor: pointer;
            transition: opacity 0.15s;
            outline: none;
        }
        .wf-lead-btn:hover { opacity: 0.92; }

        /* Slide-over Lead Contact Drawer */
        .wf-drawer {
            position: absolute;
            inset: 0;
            background: #ffffff;
            z-index: 50;
            transform: translateX(100%);
            transition: transform 0.28s cubic-bezier(0.16, 1, 0.3, 1);
            display: flex;
            flex-direction: column;
        }
        .wf-drawer.wf-drawer-open {
            transform: translateX(0);
        }
        .wf-drawer-header {
            padding: 16px 20px;
            border-bottom: 1px solid #e2e8f0;
            display: flex;
            align-items: center;
            justify-content: space-between;
            background: #f8fafc;
        }
        .wf-drawer-title {
            font-weight: 700;
            font-size: 14px;
            color: #0f172a;
        }
        .wf-drawer-body {
            padding: 20px;
            flex: 1;
            overflow-y: auto;
        }

        /* Bottom Chat Input Bar */
        .wf-input-wrap {
            padding: 14px 18px;
            background: #ffffff;
            border-top: 1px solid #e2e8f0;
            display: flex;
            gap: 10px;
            align-items: center;
            shrink: 0;
        }
        .wf-field-container {
            flex: 1;
            background: #f1f5f9;
            border: 1px solid #e2e8f0;
            border-radius: 24px;
            display: flex;
            align-items: center;
            padding: 3px 6px 3px 14px;
            transition: all 0.2s;
        }
        .wf-field-container:focus-within {
            background: #ffffff;
            border-color: #cbd5e1;
            box-shadow: 0 0 0 3px rgba(8, 23, 38, 0.05);
        }
        .wf-field {
            flex: 1;
            border: none;
            background: transparent;
            font-size: 13px;
            outline: none;
            font-family: inherit;
            color: #0f172a;
        }
        .wf-field::placeholder { color: #94a3b8; }

        .wf-mic-btn {
            background: transparent;
            border: none;
            color: #64748b;
            width: 32px;
            height: 32px;
            border-radius: 50%;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 15px;
            transition: all 0.2s;
            outline: none;
        }
        .wf-mic-btn:hover { color: #0f172a; }
        .wf-mic-active {
            color: #ef4444 !important;
            animation: wfPulseMic 1.2s infinite;
        }
        @keyframes wfPulseMic {
            0% { transform: scale(1); }
            50% { transform: scale(1.2); }
            100% { transform: scale(1); }
        }

        .wf-send-btn {
            background: #f1f5f9;
            border: 1px solid #e2e8f0;
            color: #64748b;
            width: 38px;
            height: 38px;
            border-radius: 50%;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
            outline: none;
            shrink: 0;
        }
        .wf-send-btn.wf-send-active {
            background: #081726;
            color: #ffffff;
            border-color: #081726;
            box-shadow: 0 2px 8px rgba(8, 23, 38, 0.2);
        }
        .wf-send-btn.wf-send-active:hover {
            transform: scale(1.05);
        }

        /* Footer Branding */
        .wf-footer {
            text-align: center;
            font-size: 10px;
            color: #94a3b8;
            padding: 4px;
            background: #ffffff;
            font-weight: 500;
        }

        /* Typing Dots Indicator */
        .wf-typing-bubble {
            align-self: flex-start;
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 16px 16px 16px 4px;
            padding: 10px 14px;
            display: flex;
            gap: 4px;
            align-items: center;
        }
        .wf-dot-pulse {
            width: 5px;
            height: 5px;
            border-radius: 50%;
            background: #94a3b8;
            animation: wfBounceDot 1.4s infinite ease-in-out both;
        }
        .wf-dot-pulse:nth-child(1) { animation-delay: -0.32s; }
        .wf-dot-pulse:nth-child(2) { animation-delay: -0.16s; }
        @keyframes wfBounceDot {
            0%, 80%, 100% { transform: scale(0); }
            40% { transform: scale(1); }
        }
    `;
    document.head.appendChild(style);

    // Build DOM
    const root = document.createElement('div');
    root.className = 'wf-root';
    root.id = 'wf-widget-root';
    root.innerHTML = `
        <!-- Main Chat Window -->
        <div class="wf-window" id="wf-window">
            <!-- Header Bar -->
            <div class="wf-header" id="wf-header">
                <div class="wf-header-left">
                    <div class="wf-avatar-circle" id="wf-avatar-box">⚡</div>
                    <div class="wf-header-info">
                        <div class="wf-header-title" id="wf-header-name">${botConfig.name}</div>
                        <div class="wf-status-row">
                            <span class="wf-status-dot"></span>
                            <span id="wf-header-status">${botConfig.widget_subtitle || 'Online'}</span>
                        </div>
                    </div>
                </div>

                <div class="wf-header-actions">
                    <button class="wf-icon-btn" id="wf-email-btn" title="Leave Contact Info">
                        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <rect width="20" height="16" x="2" y="4" rx="2"/><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/>
                        </svg>
                    </button>
                    <button class="wf-icon-btn" id="wf-reset-btn" title="Start New Conversation">
                        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/>
                        </svg>
                    </button>
                    <div class="wf-header-divider"></div>
                    <button class="wf-icon-btn" id="wf-close-btn" title="Close">
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M18 6 6 18"/><path d="m6 6 12 12"/>
                        </svg>
                    </button>
                </div>
            </div>

            <!-- Chat Canvas Body -->
            <div class="wf-chat-body" id="wf-body">
                <!-- Welcome Bubble -->
                <div class="wf-welcome-bubble" id="wf-welcome-msg">
                    ${botConfig.welcome_message}
                </div>

                <!-- Popular Questions Section -->
                <div class="wf-popular-section" id="wf-popular-section">
                    <div class="wf-popular-head">
                        <div class="wf-popular-bar" id="wf-popular-bar"></div>
                        <div>
                            <div class="wf-popular-title">Popular questions</div>
                            <div class="wf-popular-sub">Tap one to get started, or type your own.</div>
                        </div>
                    </div>
                    <div class="wf-popular-cards" id="wf-popular-cards"></div>
                </div>
            </div>

            <!-- Slide-over Drawer for Contact / Lead Capture -->
            <div class="wf-drawer" id="wf-drawer">
                <div class="wf-drawer-header">
                    <div class="wf-drawer-title">Contact Our Team</div>
                    <button class="wf-icon-btn" id="wf-drawer-close">&times;</button>
                </div>
                <div class="wf-drawer-body">
                    <p style="font-size: 12px; color: #64748b; margin-top: 0; margin-bottom: 14px;">
                        Leave your information and an enterprise specialist will follow up with you within 24 hours.
                    </p>
                    <form id="wf-drawer-form">
                        <input type="text" class="wf-lead-input" id="wf-drawer-name" placeholder="Your full name" required />
                        <input type="email" class="wf-lead-input" id="wf-drawer-email" placeholder="Work email address" required />
                        <input type="tel" class="wf-lead-input" id="wf-drawer-phone" placeholder="Phone number (optional)" />
                        <button type="submit" class="wf-lead-btn" id="wf-drawer-submit">Send Information &rarr;</button>
                    </form>
                    <div id="wf-drawer-status" style="display:none; font-size: 12px; margin-top: 12px; font-weight: 600; color: #16a34a; text-align: center;">
                        🎉 Thank you! Your request has been received.
                    </div>
                </div>
            </div>

            <!-- Input Bar -->
            <form class="wf-input-wrap" id="wf-form">
                <div class="wf-field-container">
                    <input type="text" class="wf-field" id="wf-input" placeholder="Ask a question..." autocomplete="off" />
                    <button type="button" class="wf-mic-btn" id="wf-mic-btn" title="Speak question">
                        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" x2="12" y1="19" y2="22"/>
                        </svg>
                    </button>
                </div>
                <button type="submit" class="wf-send-btn" id="wf-send-btn" aria-label="Send">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/>
                    </svg>
                </button>
            </form>
            <div class="wf-footer" id="wf-footer">Powered by WeaveFlow AI</div>
        </div>

        <!-- Floating Launcher Button Wrap -->
        <div class="wf-launcher-wrap">
            <div class="wf-teaser-bubble" id="wf-teaser-bubble">
                <span id="wf-teaser-text">👋 Hi! Need quick answers?</span>
                <span class="wf-teaser-close" id="wf-teaser-close">&times;</span>
            </div>

            <button class="wf-launcher" id="wf-trigger-btn" aria-label="Open AI Assistant">
                <span id="wf-btn-icon">
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/>
                    </svg>
                </span>
            </button>
        </div>
    `;
    document.body.appendChild(root);

    // Element Refs
    const win = document.getElementById('wf-window');
    const triggerBtn = document.getElementById('wf-trigger-btn');
    const closeBtn = document.getElementById('wf-close-btn');
    const resetBtn = document.getElementById('wf-reset-btn');
    const emailBtn = document.getElementById('wf-email-btn');
    const bodyEl = document.getElementById('wf-body');
    const popularCardsEl = document.getElementById('wf-popular-cards');
    const formEl = document.getElementById('wf-form');
    const inputEl = document.getElementById('wf-input');
    const sendBtn = document.getElementById('wf-send-btn');
    const micBtn = document.getElementById('wf-mic-btn');
    const teaserBubble = document.getElementById('wf-teaser-bubble');
    const teaserClose = document.getElementById('wf-teaser-close');
    const drawerEl = document.getElementById('wf-drawer');
    const drawerClose = document.getElementById('wf-drawer-close');

    // Input activate state
    inputEl.addEventListener('input', () => {
        if (inputEl.value.trim().length > 0) {
            sendBtn.classList.add('wf-send-active');
        } else {
            sendBtn.classList.remove('wf-send-active');
        }
    });

    // Fetch dynamic assistant configuration
    fetch(`${API_BASE}/api/assistants/${ASSISTANT_ID}`)
        .then(r => r.json())
        .then(asst => {
            botConfig = { ...botConfig, ...asst };
            applyConfig();
        })
        .catch(() => {
            applyConfig();
        });

    function applyConfig() {
        document.getElementById('wf-header-name').innerText = botConfig.name || "AI Assistant";
        document.getElementById('wf-header-status').innerText = botConfig.widget_subtitle || "Online";

        // Avatar
        const avatarBox = document.getElementById('wf-avatar-box');
        if (botConfig.bot_avatar && botConfig.bot_avatar.startsWith('http')) {
            avatarBox.innerHTML = `<img src="${botConfig.bot_avatar}" alt="Avatar" />`;
        } else {
            avatarBox.innerText = botConfig.bot_avatar || "⚡";
        }

        // Color Accents
        const primaryColor = botConfig.primary_color || "#081726";
        document.getElementById('wf-header').style.backgroundColor = primaryColor;
        document.getElementById('wf-popular-bar').style.backgroundColor = primaryColor;
        triggerBtn.style.backgroundColor = primaryColor;

        if (botConfig.position === 'bottom-left') {
            root.classList.add('wf-position-left');
        }

        if (botConfig.voice_enabled === 0 || botConfig.voice_enabled === false) {
            micBtn.style.display = 'none';
        }

        if (botConfig.teaser_message) {
            document.getElementById('wf-teaser-text').innerText = botConfig.teaser_message;
        } else {
            teaserBubble.style.display = 'none';
        }

        if (botConfig.show_branding === 0 || botConfig.show_branding === false) {
            document.getElementById('wf-footer').style.display = 'none';
        }

        document.getElementById('wf-welcome-msg').innerText = botConfig.welcome_message || "Hi! How can I help you today?";
        renderPopularCards();
    }

    function renderPopularCards() {
        popularCardsEl.innerHTML = '';
        const questions = typeof botConfig.suggested_questions === 'string'
            ? botConfig.suggested_questions.split('\n').filter(q => q.trim())
            : (botConfig.suggested_questions || []);

        questions.slice(0, 4).forEach(q => {
            const card = document.createElement('button');
            card.className = 'wf-question-card';
            card.innerHTML = `
                <div class="wf-question-left">
                    <span class="wf-question-dot"></span>
                    <span class="wf-question-text">${escapeHtml(q)}</span>
                </div>
                <span class="wf-question-arrow">→</span>
            `;
            card.onclick = () => {
                inputEl.value = q;
                sendBtn.classList.add('wf-send-active');
                submitQuery();
            };
            popularCardsEl.appendChild(card);
        });
    }

    function toggleChat() {
        isOpen = !isOpen;
        if (isOpen) {
            win.classList.add('wf-open');
            teaserBubble.style.display = 'none';
            document.getElementById('wf-btn-icon').innerHTML = `
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M18 6 6 18"/><path d="m6 6 12 12"/>
                </svg>
            `;
            setTimeout(() => inputEl.focus(), 200);
        } else {
            win.classList.remove('wf-open');
            document.getElementById('wf-btn-icon').innerHTML = `
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/>
                </svg>
            `;
        }
    }

    triggerBtn.addEventListener('click', toggleChat);
    closeBtn.addEventListener('click', toggleChat);
    teaserBubble.addEventListener('click', (e) => {
        if (e.target !== teaserClose) toggleChat();
    });
    teaserClose.addEventListener('click', (e) => {
        e.stopPropagation();
        teaserBubble.style.display = 'none';
    });

    // Reset Chat action
    resetBtn.addEventListener('click', () => {
        conversationId = `wf_${ASSISTANT_ID}_${Math.random().toString(36).substring(2, 10)}`;
        sessionStorage.setItem(`wf_conv_${ASSISTANT_ID}`, conversationId);
        
        // Remove all user and bot replies, keep welcome and popular questions
        const userBubbles = bodyEl.querySelectorAll('.wf-bubble, .wf-lead-card');
        userBubbles.forEach(b => b.remove());
        const popSec = document.getElementById('wf-popular-section');
        if (popSec) popSec.style.display = 'block';
    });

    // Lead drawer actions
    emailBtn.addEventListener('click', () => {
        drawerEl.classList.add('wf-drawer-open');
    });
    drawerClose.addEventListener('click', () => {
        drawerEl.classList.remove('wf-drawer-open');
    });

    document.getElementById('wf-drawer-form').onsubmit = async (e) => {
        e.preventDefault();
        const submitBtn = document.getElementById('wf-drawer-submit');
        submitBtn.disabled = true;
        submitBtn.innerText = "Submitting...";

        const payload = {
            assistant_id: ASSISTANT_ID,
            conversation_id: conversationId,
            name: document.getElementById('wf-drawer-name').value.trim(),
            email: document.getElementById('wf-drawer-email').value.trim(),
            phone: document.getElementById('wf-drawer-phone').value.trim()
        };

        try {
            await fetch(`${API_BASE}/api/lead`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            document.getElementById('wf-drawer-status').style.display = 'block';
            setTimeout(() => {
                drawerEl.classList.remove('wf-drawer-open');
                document.getElementById('wf-drawer-status').style.display = 'none';
                submitBtn.disabled = false;
                submitBtn.innerText = "Send Information →";
            }, 2000);
        } catch (err) {
            alert("Error submitting details.");
            submitBtn.disabled = false;
        }
    };

    // Voice recognition
    if (recognition) {
        recognition.onstart = () => {
            isRecording = true;
            micBtn.classList.add('wf-mic-active');
            inputEl.placeholder = "Listening... Speak now";
        };
        recognition.onresult = (e) => {
            const transcript = e.results[0][0].transcript;
            inputEl.value = transcript;
            sendBtn.classList.add('wf-send-active');
            isRecording = false;
            micBtn.classList.remove('wf-mic-active');
            inputEl.placeholder = "Ask a question...";
            submitQuery();
        };
        recognition.onerror = () => {
            isRecording = false;
            micBtn.classList.remove('wf-mic-active');
            inputEl.placeholder = "Ask a question...";
        };
        recognition.onend = () => {
            isRecording = false;
            micBtn.classList.remove('wf-mic-active');
            inputEl.placeholder = "Ask a question...";
        };

        micBtn.onclick = () => {
            if (!isRecording) recognition.start();
            else recognition.stop();
        };
    } else {
        micBtn.style.display = 'none';
    }

    // Submit Query
    formEl.addEventListener('submit', (e) => {
        e.preventDefault();
        submitQuery();
    });

    async function submitQuery() {
        const query = inputEl.value.trim();
        if (!query) return;

        inputEl.value = '';
        sendBtn.classList.remove('wf-send-active');

        // Hide popular questions once chat starts
        const popSec = document.getElementById('wf-popular-section');
        if (popSec) popSec.style.display = 'none';

        appendMsg('user', query);

        // Typing indicator
        const typingEl = document.createElement('div');
        typingEl.className = 'wf-typing-bubble';
        typingEl.innerHTML = `
            <span class="wf-dot-pulse"></span>
            <span class="wf-dot-pulse"></span>
            <span class="wf-dot-pulse"></span>
        `;
        bodyEl.appendChild(typingEl);
        bodyEl.scrollTop = bodyEl.scrollHeight;

        try {
            const res = await fetch(`${API_BASE}/api/chat`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    assistant_id: ASSISTANT_ID,
                    conversation_id: conversationId,
                    message: query
                })
            });

            const data = await res.json();
            typingEl.remove();

            appendMsg('bot', data.answer, data.sources);

            // Trigger in-chat lead card if prompted
            if (data.lead_prompted && botConfig.lead_capture_enabled) {
                renderInChatLeadCard();
            }

        } catch (err) {
            typingEl.remove();
            appendMsg('bot', "I apologize, but I am having trouble connecting to the service right now. Please try again in a moment.");
        }
    }

    function appendMsg(role, text, sources = []) {
        const bubble = document.createElement('div');
        bubble.className = `wf-bubble ${role === 'user' ? 'wf-bubble-user' : 'wf-bubble-bot'}`;

        let html = `<div>${text.replace(/\n/g, '<br>')}</div>`;

        if (sources && sources.length > 0) {
            html += `<div class="wf-citations">`;
            sources.forEach(s => {
                html += `
                    <a href="${s.url}" target="_blank" class="wf-citation-pill" title="${escapeHtml(s.snippet || '')}">
                        <span>📚</span>
                        <span>[${s.index}] ${escapeHtml(s.title || 'Documentation')} ↗</span>
                    </a>
                `;
            });
            html += `</div>`;
        }

        bubble.innerHTML = html;
        bodyEl.appendChild(bubble);
        bodyEl.scrollTop = bodyEl.scrollHeight;
    }

    function renderInChatLeadCard() {
        const card = document.createElement('div');
        card.className = 'wf-lead-card';
        card.innerHTML = `
            <h4>Connect with our team</h4>
            <p>Leave your contact details and our team will be glad to follow up with you directly!</p>
            <input type="email" placeholder="Your work email..." class="wf-lead-input" id="wf-inline-email" required />
            <input type="text" placeholder="Your name (optional)..." class="wf-lead-input" id="wf-inline-name" />
            <button class="wf-lead-btn" id="wf-inline-submit">Request Follow-up &rarr;</button>
        `;

        card.querySelector('#wf-inline-submit').onclick = async (e) => {
            e.preventDefault();
            const email = card.querySelector('#wf-inline-email').value.trim();
            const name = card.querySelector('#wf-inline-name').value.trim();
            if (!email) {
                alert("Please enter a valid email address.");
                return;
            }

            const btn = card.querySelector('#wf-inline-submit');
            btn.disabled = true;
            btn.innerText = "Submitting...";

            try {
                await fetch(`${API_BASE}/api/lead`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        assistant_id: ASSISTANT_ID,
                        conversation_id: conversationId,
                        email: email,
                        name: name
                    })
                });
                card.innerHTML = `<div style="color: #16a34a; font-weight: 700; text-align: center; padding: 6px;">🎉 Thank you! We have received your information.</div>`;
            } catch (err) {
                btn.disabled = false;
                btn.innerText = "Request Follow-up →";
            }
        };

        bodyEl.appendChild(card);
        bodyEl.scrollTop = bodyEl.scrollHeight;
    }

    function escapeHtml(text) {
        if (!text) return '';
        return text
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }
})();
