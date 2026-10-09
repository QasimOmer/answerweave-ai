/**
 * WeaveFlow AI - Universal Embedded Chatbot Widget
 * Engineered for 100% Host-Website Isolation via Shadow DOM & Scoped CSS Resets.
 * - Prevents WordPress, Elementor, Kadence, Astra theme CSS leaks
 * - Dynamic Assistant Branding (EcomAlign Assistant default)
 * - Auto-detects Host API endpoint from script src
 * - Grounded Source Citations & In-Chat Lead Capture
 */

(function () {
    if (window.WeaveFlowWidgetInitialized) return;
    window.WeaveFlowWidgetInitialized = true;

    // Resolve current script tag accurately
    const currentScript = document.currentScript || (function () {
        const scripts = document.getElementsByTagName('script');
        for (let i = scripts.length - 1; i >= 0; i--) {
            if (scripts[i].src && scripts[i].src.indexOf('widget.js') !== -1) {
                return scripts[i];
            }
        }
        return scripts[scripts.length - 1];
    })();

    let detectedApiBase = 'https://answerweave-ai.vercel.app';
    if (currentScript && currentScript.src) {
        try {
            const scriptUrl = new URL(currentScript.src);
            if (scriptUrl.origin && scriptUrl.origin !== 'null' && scriptUrl.origin !== 'file://') {
                detectedApiBase = scriptUrl.origin;
            }
        } catch (e) {}
    }

    const API_BASE = (currentScript && currentScript.getAttribute('data-api-url')) || detectedApiBase;
    const ASSISTANT_ID = (currentScript && currentScript.getAttribute('data-assistant-id')) || "asst_default";

    let botConfig = {
        name: "EcomAlign Assistant",
        primary_color: "#0f172a",
        welcome_message: "Hi there! 👋 Welcome to EcomAlign. How can we help grow your e-commerce brand across Amazon, eBay, TikTok Shop, or other marketplaces today?",
        bot_avatar: "⚡",
        position: "bottom-right",
        widget_subtitle: "Online • Marketplace Growth AI",
        suggested_questions: "How does EcomAlign help scale sales across Amazon, eBay & TikTok Shop?\nWhat full-service store management & listing optimization do you provide?\nHow can I book a call or start a project with your growth team?",
        lead_capture_enabled: 1,
        voice_enabled: 1,
        launcher_style: "circle",
        teaser_message: "👋 Need help growing on marketplaces?",
        show_branding: 1
    };

    let conversationId = sessionStorage.getItem(`wf_conv_${ASSISTANT_ID}`) || (`wf_${ASSISTANT_ID}_${Math.random().toString(36).substring(2, 10)}`);
    sessionStorage.setItem(`wf_conv_${ASSISTANT_ID}`, conversationId);

    let isOpen = false;
    let isRecording = false;
    let recognition = null;

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (SpeechRecognition) {
        try {
            recognition = new SpeechRecognition();
            recognition.continuous = false;
            recognition.interimResults = false;
            recognition.lang = 'en-US';
        } catch (e) {}
    }

    // Host Container with Shadow DOM for total CSS isolation against WordPress / Elementor
    const hostContainer = document.createElement('div');
    hostContainer.id = 'wf-chat-widget-container';
    hostContainer.style.cssText = 'all: initial !important; position: fixed !important; bottom: 0 !important; right: 0 !important; z-index: 2147483647 !important; pointer-events: none !important; width: 0 !important; height: 0 !important; overflow: visible !important;';

    const shadow = hostContainer.attachShadow ? hostContainer.attachShadow({ mode: 'open' }) : hostContainer;

    // Scoped CSS styles
    const style = document.createElement('style');
    style.textContent = `
        @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');

        :host, .wf-root {
            all: initial;
            font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
            -webkit-font-smoothing: antialiased !important;
            box-sizing: border-box !important;
            color: #0f172a !important;
        }

        *, *::before, *::after {
            box-sizing: border-box !important;
            margin: 0;
            padding: 0;
        }

        .wf-root {
            position: fixed !important;
            bottom: 24px !important;
            right: 24px !important;
            z-index: 2147483647 !important;
            pointer-events: none !important;
        }
        .wf-position-left {
            right: auto !important;
            left: 24px !important;
        }

        /* Launcher Floating Button Wrap */
        .wf-launcher-wrap {
            position: relative !important;
            display: flex !important;
            align-items: center !important;
            justify-content: flex-end !important;
            pointer-events: auto !important;
        }
        .wf-position-left .wf-launcher-wrap {
            justify-content: flex-start !important;
        }

        .wf-teaser-bubble {
            position: absolute !important;
            bottom: 72px !important;
            right: 0 !important;
            background: #ffffff !important;
            color: #0f172a !important;
            padding: 10px 16px !important;
            border-radius: 18px 18px 4px 18px !important;
            box-shadow: 0 10px 25px -4px rgba(0, 0, 0, 0.15), 0 2px 6px rgba(0, 0, 0, 0.05) !important;
            border: 1px solid rgba(226, 232, 240, 0.9) !important;
            font-size: 13px !important;
            font-weight: 600 !important;
            white-space: nowrap !important;
            cursor: pointer !important;
            transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1) !important;
            animation: wfFadeUp 0.3s ease-out !important;
            display: flex !important;
            align-items: center !important;
            gap: 8px !important;
            pointer-events: auto !important;
        }
        .wf-position-left .wf-teaser-bubble {
            right: auto !important;
            left: 0 !important;
            border-radius: 18px 18px 18px 4px !important;
        }
        .wf-teaser-bubble:hover {
            transform: translateY(-2px) !important;
            box-shadow: 0 14px 30px -4px rgba(0, 0, 0, 0.2) !important;
        }
        .wf-teaser-close {
            color: #94a3b8 !important;
            font-size: 14px !important;
            padding: 2px !important;
            cursor: pointer !important;
        }
        .wf-teaser-close:hover { color: #475569 !important; }

        button.wf-launcher {
            all: unset !important;
            width: 60px !important;
            height: 60px !important;
            min-width: 60px !important;
            min-height: 60px !important;
            border-radius: 50% !important;
            background: #0f172a !important;
            box-shadow: 0 10px 30px -4px rgba(15, 23, 42, 0.4), 0 4px 8px rgba(0,0,0,0.1) !important;
            border: 1px solid rgba(255, 255, 255, 0.18) !important;
            cursor: pointer !important;
            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
            color: #ffffff !important;
            padding: 0 !important;
            margin: 0 !important;
            box-sizing: border-box !important;
            transition: transform 0.25s cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 0.25s ease !important;
            outline: none !important;
            pointer-events: auto !important;
        }
        button.wf-launcher:hover {
            transform: scale(1.08) !important;
            box-shadow: 0 14px 36px -4px rgba(15, 23, 42, 0.5), 0 6px 12px rgba(0,0,0,0.15) !important;
        }
        button.wf-launcher svg {
            width: 24px !important;
            height: 24px !important;
            stroke: currentColor !important;
            fill: none !important;
            display: block !important;
            pointer-events: none !important;
        }

        /* Widget Container Window */
        .wf-window {
            position: fixed !important;
            bottom: 96px !important;
            right: 24px !important;
            width: 395px !important;
            height: 630px !important;
            max-width: calc(100vw - 36px) !important;
            max-height: calc(100dvh - 120px) !important;
            background: #ffffff !important;
            border-radius: 22px !important;
            box-shadow: 0 25px 60px -12px rgba(15, 23, 42, 0.28), 0 4px 16px rgba(0, 0, 0, 0.08) !important;
            display: flex !important;
            flex-direction: column !important;
            overflow: hidden !important;
            opacity: 0 !important;
            pointer-events: none !important;
            transform: translateY(20px) scale(0.96) !important;
            transition: opacity 0.28s cubic-bezier(0.16, 1, 0.3, 1), transform 0.28s cubic-bezier(0.16, 1, 0.3, 1) !important;
            z-index: 2147483647 !important;
            border: 1px solid rgba(226, 232, 240, 0.85) !important;
        }
        .wf-position-left .wf-window {
            right: auto !important;
            left: 24px !important;
        }
        .wf-window.wf-open {
            opacity: 1 !important;
            pointer-events: auto !important;
            transform: translateY(0) scale(1) !important;
        }

        /* Header Bar */
        .wf-header {
            background: #0f172a !important;
            color: #ffffff !important;
            padding: 16px 20px !important;
            display: flex !important;
            align-items: center !important;
            justify-content: space-between !important;
            border-bottom: 1px solid rgba(255, 255, 255, 0.08) !important;
            user-select: none !important;
            flex-shrink: 0 !important;
        }
        .wf-header-left {
            display: flex !important;
            align-items: center !important;
            gap: 12px !important;
        }
        .wf-avatar-circle {
            width: 42px !important;
            height: 42px !important;
            min-width: 42px !important;
            border-radius: 50% !important;
            background: #ffffff !important;
            color: #0f172a !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            font-size: 20px !important;
            font-weight: 800 !important;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15) !important;
            overflow: hidden !important;
            flex-shrink: 0 !important;
        }
        .wf-avatar-circle img {
            width: 100% !important;
            height: 100% !important;
            object-fit: cover !important;
        }
        .wf-header-info {
            display: flex !important;
            flex-direction: column !important;
        }
        .wf-header-title {
            font-weight: 700 !important;
            font-size: 15px !important;
            color: #ffffff !important;
            line-height: 1.2 !important;
            letter-spacing: -0.01em !important;
        }
        .wf-status-row {
            display: flex !important;
            align-items: center !important;
            gap: 6px !important;
            margin-top: 3px !important;
            font-size: 11.5px !important;
            color: #94a3b8 !important;
            font-weight: 500 !important;
        }
        .wf-status-dot {
            width: 7px !important;
            height: 7px !important;
            min-width: 7px !important;
            border-radius: 50% !important;
            background: #10b981 !important;
            box-shadow: 0 0 10px #10b981 !important;
            display: inline-block !important;
        }

        /* Top Header Action Buttons */
        .wf-header-actions {
            display: flex !important;
            align-items: center !important;
            gap: 8px !important;
        }
        .wf-header-divider {
            width: 1px !important;
            height: 20px !important;
            background: rgba(255, 255, 255, 0.15) !important;
            margin: 0 4px !important;
        }
        button.wf-icon-btn {
            all: unset !important;
            background: rgba(255, 255, 255, 0.08) !important;
            border: 1px solid rgba(255, 255, 255, 0.12) !important;
            color: #cbd5e1 !important;
            width: 32px !important;
            height: 32px !important;
            min-width: 32px !important;
            min-height: 32px !important;
            border-radius: 8px !important;
            cursor: pointer !important;
            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
            padding: 0 !important;
            margin: 0 !important;
            box-sizing: border-box !important;
            transition: all 0.15s ease !important;
            outline: none !important;
        }
        button.wf-icon-btn:hover {
            color: #ffffff !important;
            background: rgba(255, 255, 255, 0.22) !important;
            border-color: rgba(255, 255, 255, 0.3) !important;
        }
        button.wf-icon-btn svg {
            width: 17px !important;
            height: 17px !important;
            stroke: currentColor !important;
            fill: none !important;
            display: block !important;
            pointer-events: none !important;
            flex-shrink: 0 !important;
        }

        /* Chat Body Canvas with Dotted Pattern */
        .wf-chat-body {
            flex: 1 !important;
            padding: 18px !important;
            overflow-y: auto !important;
            background-color: #f8fafc !important;
            background-image: radial-gradient(#cbd5e1 1.2px, transparent 1.2px) !important;
            background-size: 16px 16px !important;
            display: flex !important;
            flex-direction: column !important;
            gap: 14px !important;
            scroll-behavior: smooth !important;
        }

        /* Message Bubbles */
        .wf-bubble {
            display: flex !important;
            flex-direction: column !important;
            max-width: 88% !important;
            font-size: 13.5px !important;
            line-height: 1.55 !important;
            animation: wfFadeUp 0.25s cubic-bezier(0.16, 1, 0.3, 1) !important;
            word-break: break-word !important;
            overflow-wrap: anywhere !important;
        }
        .wf-msg-p {
            margin: 0 0 6px 0 !important;
            line-height: 1.5 !important;
        }
        .wf-msg-p:last-child {
            margin-bottom: 0 !important;
        }
        .wf-msg-list {
            margin: 6px 0 6px 18px !important;
            padding: 0 !important;
            list-style-type: disc !important;
        }
        .wf-msg-list li {
            margin-bottom: 5px !important;
            line-height: 1.45 !important;
        }
        .wf-msg-list li:last-child {
            margin-bottom: 0 !important;
        }
        .wf-citation-inline {
            display: inline-block !important;
            background: rgba(99, 102, 241, 0.12) !important;
            color: #4338ca !important;
            font-weight: 700 !important;
            font-size: 11px !important;
            padding: 1px 5px !important;
            border-radius: 5px !important;
            margin: 0 2px !important;
            vertical-align: middle !important;
        }
        @keyframes wfFadeUp {
            from { opacity: 0; transform: translateY(8px); }
            to { opacity: 1; transform: translateY(0); }
        }

        /* Welcome Message Bubble */
        .wf-welcome-bubble {
            align-self: flex-start !important;
            background: #ffffff !important;
            color: #0f172a !important;
            padding: 13px 18px !important;
            border-radius: 18px 18px 18px 6px !important;
            border: 1px solid #e2e8f0 !important;
            box-shadow: 0 2px 10px rgba(0, 0, 0, 0.04) !important;
            font-size: 13.5px !important;
            font-weight: 500 !important;
            line-height: 1.5 !important;
        }

        /* Popular Questions Section */
        .wf-popular-section {
            margin-top: 6px !important;
            margin-bottom: 2px !important;
        }
        .wf-popular-head {
            display: flex !important;
            align-items: flex-start !important;
            gap: 10px !important;
            margin-bottom: 12px !important;
        }
        .wf-popular-bar {
            width: 3.5px !important;
            height: 24px !important;
            background: #f59e0b !important;
            border-radius: 4px !important;
            flex-shrink: 0 !important;
            margin-top: 1px !important;
        }
        .wf-popular-title {
            font-size: 14.5px !important;
            font-weight: 700 !important;
            color: #0f172a !important;
            line-height: 1.2 !important;
            letter-spacing: -0.01em !important;
        }
        .wf-popular-sub {
            font-size: 12px !important;
            color: #64748b !important;
            margin-top: 3px !important;
        }

        /* Popular Question Cards */
        .wf-popular-cards {
            display: flex !important;
            flex-direction: column !important;
            gap: 9px !important;
        }
        button.wf-question-card {
            all: unset !important;
            background: #ffffff !important;
            border: 1px solid #e2e8f0 !important;
            border-radius: 16px !important;
            padding: 12px 16px !important;
            display: flex !important;
            align-items: center !important;
            justify-content: space-between !important;
            gap: 10px !important;
            cursor: pointer !important;
            box-shadow: 0 2px 6px rgba(0, 0, 0, 0.03) !important;
            transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1) !important;
            text-align: left !important;
            width: 100% !important;
            box-sizing: border-box !important;
        }
        button.wf-question-card:hover {
            transform: translateY(-2px) !important;
            border-color: #f59e0b !important;
            box-shadow: 0 6px 16px rgba(245, 158, 11, 0.12) !important;
            background: #fffbeb !important;
        }
        .wf-question-left {
            display: flex !important;
            align-items: center !important;
            gap: 10px !important;
            flex: 1 !important;
        }
        .wf-question-dot {
            width: 6px !important;
            height: 6px !important;
            min-width: 6px !important;
            border-radius: 50% !important;
            background: #f59e0b !important;
            flex-shrink: 0 !important;
            display: inline-block !important;
        }
        .wf-question-text {
            font-size: 13px !important;
            font-weight: 600 !important;
            color: #0f172a !important;
            line-height: 1.35 !important;
            flex: 1 !important;
        }
        .wf-question-arrow {
            color: #94a3b8 !important;
            font-size: 14px !important;
            font-weight: 700 !important;
            flex-shrink: 0 !important;
            transition: transform 0.15s ease, color 0.15s ease !important;
        }
        button.wf-question-card:hover .wf-question-arrow {
            color: #d97706 !important;
            transform: translateX(3px) !important;
        }

        /* User Message Bubble */
        .wf-bubble-user {
            align-self: flex-end !important;
            background: #0f172a !important;
            color: #ffffff !important;
            padding: 11px 16px !important;
            border-radius: 18px 18px 4px 18px !important;
            box-shadow: 0 3px 10px rgba(15, 23, 42, 0.18) !important;
            font-weight: 500 !important;
        }

        /* Assistant Grounded Bubble */
        .wf-bubble-bot {
            align-self: flex-start !important;
            background: #ffffff !important;
            color: #0f172a !important;
            padding: 13px 16px !important;
            border-radius: 18px 18px 18px 4px !important;
            border: 1px solid #e2e8f0 !important;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.03) !important;
        }

        /* Citations list inside message */
        .wf-citations {
            margin-top: 10px !important;
            padding-top: 8px !important;
            border-top: 1px solid #f1f5f9 !important;
            display: flex !important;
            flex-wrap: wrap !important;
            gap: 6px !important;
        }
        .wf-citation-pill {
            display: inline-flex !important;
            align-items: center !important;
            gap: 4px !important;
            background: #f8fafc !important;
            border: 1px solid #cbd5e1 !important;
            border-radius: 6px !important;
            padding: 3px 8px !important;
            font-size: 11px !important;
            font-weight: 600 !important;
            color: #2563eb !important;
            text-decoration: none !important;
            transition: all 0.15s !important;
        }
        .wf-citation-pill:hover {
            background: #eff6ff !important;
            border-color: #93c5fd !important;
            color: #1d4ed8 !important;
        }

        /* In-chat Lead Capture Card */
        .wf-lead-card {
            background: #ffffff !important;
            border: 1px solid #cbd5e1 !important;
            border-radius: 16px !important;
            padding: 16px !important;
            box-shadow: 0 4px 14px rgba(0, 0, 0, 0.05) !important;
            margin-top: 6px !important;
            align-self: flex-start !important;
            width: 100% !important;
            max-width: 90% !important;
            box-sizing: border-box !important;
        }
        .wf-lead-card h4 {
            margin: 0 0 4px 0 !important;
            font-size: 13.5px !important;
            font-weight: 700 !important;
            color: #0f172a !important;
        }
        .wf-lead-card p {
            margin: 0 0 10px 0 !important;
            font-size: 11.5px !important;
            color: #64748b !important;
        }
        input.wf-lead-input {
            all: unset !important;
            width: 100% !important;
            padding: 9px 12px !important;
            border: 1px solid #cbd5e1 !important;
            border-radius: 10px !important;
            font-size: 12px !important;
            margin-bottom: 8px !important;
            box-sizing: border-box !important;
            outline: none !important;
            background: #f8fafc !important;
            transition: all 0.15s !important;
            font-family: inherit !important;
            color: #0f172a !important;
        }
        input.wf-lead-input:focus {
            border-color: #0f172a !important;
            background: #ffffff !important;
            box-shadow: 0 0 0 2px rgba(15, 23, 42, 0.08) !important;
        }
        button.wf-lead-btn {
            all: unset !important;
            width: 100% !important;
            background: #0f172a !important;
            color: #ffffff !important;
            border: none !important;
            padding: 10px !important;
            border-radius: 10px !important;
            font-weight: 700 !important;
            font-size: 12.5px !important;
            cursor: pointer !important;
            transition: opacity 0.15s !important;
            text-align: center !important;
            box-sizing: border-box !important;
            display: block !important;
        }
        button.wf-lead-btn:hover { opacity: 0.92 !important; }

        /* Slide-over Drawer for Contact Form */
        .wf-drawer {
            position: absolute !important;
            inset: 0 !important;
            background: #ffffff !important;
            z-index: 50 !important;
            transform: translateX(100%) !important;
            transition: transform 0.28s cubic-bezier(0.16, 1, 0.3, 1) !important;
            display: flex !important;
            flex-direction: column !important;
        }
        .wf-drawer.wf-drawer-open {
            transform: translateX(0) !important;
        }
        .wf-drawer-header {
            padding: 16px 20px !important;
            border-bottom: 1px solid #e2e8f0 !important;
            display: flex !important;
            align-items: center !important;
            justify-content: space-between !important;
            background: #f8fafc !important;
        }
        .wf-drawer-title {
            font-weight: 700 !important;
            font-size: 14px !important;
            color: #0f172a !important;
        }
        .wf-drawer-body {
            padding: 20px !important;
            flex: 1 !important;
            overflow-y: auto !important;
        }

        /* Bottom Input Bar */
        form.wf-input-wrap {
            all: unset !important;
            padding: 14px 18px !important;
            background: #ffffff !important;
            border-top: 1px solid #e2e8f0 !important;
            display: flex !important;
            gap: 10px !important;
            align-items: center !important;
            flex-shrink: 0 !important;
            box-sizing: border-box !important;
        }
        .wf-field-container {
            flex: 1 !important;
            background: #f1f5f9 !important;
            border: 1px solid #e2e8f0 !important;
            border-radius: 24px !important;
            display: flex !important;
            align-items: center !important;
            padding: 3px 6px 3px 14px !important;
            transition: all 0.2s !important;
            box-sizing: border-box !important;
        }
        .wf-field-container:focus-within {
            background: #ffffff !important;
            border-color: #cbd5e1 !important;
            box-shadow: 0 0 0 3px rgba(15, 23, 42, 0.05) !important;
        }
        input.wf-field {
            all: unset !important;
            flex: 1 !important;
            border: none !important;
            background: transparent !important;
            font-size: 13.5px !important;
            outline: none !important;
            font-family: inherit !important;
            color: #0f172a !important;
            padding: 8px 4px !important;
            box-sizing: border-box !important;
        }
        input.wf-field::placeholder { color: #94a3b8 !important; }

        button.wf-mic-btn {
            all: unset !important;
            background: transparent !important;
            border: none !important;
            color: #64748b !important;
            width: 32px !important;
            height: 32px !important;
            min-width: 32px !important;
            min-height: 32px !important;
            border-radius: 50% !important;
            cursor: pointer !important;
            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
            padding: 0 !important;
            margin: 0 !important;
            box-sizing: border-box !important;
            transition: all 0.2s ease !important;
        }
        button.wf-mic-btn:hover {
            color: #0f172a !important;
            background: rgba(0, 0, 0, 0.05) !important;
        }
        button.wf-mic-btn svg {
            width: 17px !important;
            height: 17px !important;
            stroke: currentColor !important;
            fill: none !important;
            display: block !important;
        }
        .wf-mic-active {
            color: #ef4444 !important;
            animation: wfPulseMic 1.2s infinite !important;
        }
        @keyframes wfPulseMic {
            0% { transform: scale(1); }
            50% { transform: scale(1.2); }
            100% { transform: scale(1); }
        }

        button.wf-send-btn {
            all: unset !important;
            background: #e2e8f0 !important;
            border: 1px solid #cbd5e1 !important;
            color: #64748b !important;
            width: 38px !important;
            height: 38px !important;
            min-width: 38px !important;
            min-height: 38px !important;
            border-radius: 50% !important;
            cursor: pointer !important;
            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
            padding: 0 !important;
            margin: 0 !important;
            box-sizing: border-box !important;
            transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1) !important;
            flex-shrink: 0 !important;
        }
        button.wf-send-btn svg {
            width: 16px !important;
            height: 16px !important;
            stroke: currentColor !important;
            fill: none !important;
            display: block !important;
        }
        button.wf-send-btn.wf-send-active {
            background: #0f172a !important;
            border-color: #0f172a !important;
            color: #ffffff !important;
            box-shadow: 0 3px 10px rgba(15, 23, 42, 0.25) !important;
        }
        button.wf-send-btn.wf-send-active:hover {
            transform: scale(1.06) !important;
            background: #1e293b !important;
        }

        /* Footer Branding */
        .wf-footer {
            text-align: center !important;
            font-size: 10.5px !important;
            color: #94a3b8 !important;
            padding: 5px !important;
            background: #ffffff !important;
            font-weight: 500 !important;
            border-top: 1px solid #f1f5f9 !important;
        }

        /* Typing Dots Indicator */
        .wf-typing-bubble {
            align-self: flex-start !important;
            background: #ffffff !important;
            border: 1px solid #e2e8f0 !important;
            border-radius: 16px 16px 16px 4px !important;
            padding: 10px 14px !important;
            display: flex !important;
            gap: 4px !important;
            align-items: center !important;
        }
        .wf-dot-pulse {
            width: 5px !important;
            height: 5px !important;
            min-width: 5px !important;
            border-radius: 50% !important;
            background: #94a3b8 !important;
            display: inline-block !important;
            animation: wfBounceDot 1.4s infinite ease-in-out both !important;
        }
        .wf-dot-pulse:nth-child(1) { animation-delay: -0.32s !important; }
        .wf-dot-pulse:nth-child(2) { animation-delay: -0.16s !important; }
        @keyframes wfBounceDot {
            0%, 80%, 100% { transform: scale(0); }
            40% { transform: scale(1); }
        }

        /* ================= RESPONSIVE STYLES FOR ALL SCREEN SIZES ================= */

        /* Tablets & Foldables (481px to 768px) */
        @media (max-width: 768px) and (min-width: 641px) {
            .wf-window {
                width: 375px !important;
                max-width: calc(100vw - 28px) !important;
                height: 580px !important;
                max-height: calc(100dvh - 100px) !important;
                bottom: 84px !important;
                right: 18px !important;
                border-radius: 20px !important;
            }
            .wf-position-left .wf-window {
                left: 18px !important;
                right: auto !important;
            }
        }

        /* Mobile Phones & Small Handhelds (<= 640px) */
        @media (max-width: 640px) {
            .wf-root {
                bottom: max(16px, env(safe-area-inset-bottom, 16px)) !important;
                right: max(16px, env(safe-area-inset-right, 16px)) !important;
            }
            .wf-position-left {
                left: max(16px, env(safe-area-inset-left, 16px)) !important;
                right: auto !important;
            }

            button.wf-launcher {
                width: 56px !important;
                height: 56px !important;
                min-width: 56px !important;
                min-height: 56px !important;
            }

            .wf-teaser-bubble {
                bottom: 68px !important;
                max-width: calc(100vw - 90px) !important;
                white-space: normal !important;
                font-size: 12px !important;
                line-height: 1.35 !important;
                padding: 8px 14px !important;
            }

            /* Hide launcher button when modal window is active on mobile */
            .wf-is-open .wf-launcher-wrap {
                display: none !important;
            }

            /* Fullscreen Mobile Viewport */
            .wf-window {
                position: fixed !important;
                inset: 0 !important;
                top: 0 !important;
                left: 0 !important;
                right: 0 !important;
                bottom: 0 !important;
                width: 100vw !important;
                max-width: 100vw !important;
                height: 100% !important;
                height: 100dvh !important;
                max-height: 100dvh !important;
                border-radius: 0 !important;
                border: none !important;
                box-shadow: none !important;
                margin: 0 !important;
                transform: translateY(100%) !important;
                transition: transform 0.28s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.25s ease !important;
                z-index: 2147483647 !important;
            }
            .wf-position-left .wf-window {
                left: 0 !important;
                right: 0 !important;
            }
            .wf-window.wf-open {
                transform: translateY(0) !important;
                opacity: 1 !important;
            }

            .wf-header {
                padding: max(14px, env(safe-area-inset-top, 14px)) 16px 14px 16px !important;
                border-radius: 0 !important;
            }
            .wf-header-title {
                font-size: 15px !important;
            }
            .wf-status-row {
                font-size: 11px !important;
            }

            .wf-chat-body {
                padding: 14px !important;
                gap: 12px !important;
                -webkit-overflow-scrolling: touch !important;
            }
            .wf-bubble {
                max-width: 92% !important;
                font-size: 13.5px !important;
            }
            .wf-welcome-bubble {
                font-size: 13.5px !important;
                padding: 12px 15px !important;
            }
            .wf-popular-cards {
                gap: 8px !important;
            }
            button.wf-question-card {
                padding: 10px 14px !important;
                border-radius: 14px !important;
            }
            .wf-question-text {
                font-size: 12.5px !important;
            }

            .wf-lead-card {
                max-width: 100% !important;
            }

            /* Bottom input bar with mobile safe area */
            form.wf-input-wrap {
                padding: 10px 14px max(14px, env(safe-area-inset-bottom, 14px)) 14px !important;
                gap: 8px !important;
            }
            /* Crucial: 16px font size prevents iOS Safari from auto-zooming page on input focus */
            input.wf-field {
                font-size: 16px !important;
                padding: 7px 4px !important;
            }
            input.wf-lead-input {
                font-size: 16px !important;
                padding: 10px 12px !important;
            }

            .wf-drawer {
                inset: 0 !important;
                height: 100dvh !important;
            }
            .wf-drawer-header {
                padding: max(16px, env(safe-area-inset-top, 16px)) 18px 14px 18px !important;
            }
        }

        /* Landscape Mobile Devices (Height <= 520px) */
        @media (max-height: 520px) {
            .wf-window {
                position: fixed !important;
                inset: 0 !important;
                top: 0 !important;
                bottom: 0 !important;
                left: 0 !important;
                right: 0 !important;
                width: 100vw !important;
                height: 100dvh !important;
                max-height: 100dvh !important;
                border-radius: 0 !important;
                transform: translateY(100%) !important;
            }
            .wf-window.wf-open {
                transform: translateY(0) !important;
            }
            .wf-header {
                padding: 8px 14px !important;
            }
            .wf-avatar-circle {
                width: 32px !important;
                height: 32px !important;
                min-width: 32px !important;
                font-size: 15px !important;
            }
            form.wf-input-wrap {
                padding: 6px 12px !important;
            }
            .wf-chat-body {
                padding: 10px !important;
                gap: 8px !important;
            }
            .wf-popular-section {
                display: none !important;
            }
        }
    `;
    shadow.appendChild(style);

    // Root DOM
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
                    <button type="button" class="wf-icon-btn" id="wf-email-btn" title="Leave Contact Info">
                        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <rect width="20" height="16" x="2" y="4" rx="2"/><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/>
                        </svg>
                    </button>
                    <button type="button" class="wf-icon-btn" id="wf-reset-btn" title="Start New Conversation">
                        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/>
                        </svg>
                    </button>
                    <div class="wf-header-divider"></div>
                    <button type="button" class="wf-icon-btn" id="wf-close-btn" title="Close">
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
                    <div class="wf-drawer-title" id="wf-drawer-title">Start Your Project with ${escapeHtml(botConfig.name)}</div>
                    <button type="button" class="wf-icon-btn" id="wf-drawer-close">&times;</button>
                </div>
                <div class="wf-drawer-body">
                    <p style="font-size: 12px; color: #64748b; margin-top: 0; margin-bottom: 14px; line-height: 1.5;">
                        Leave your information and an e-commerce growth specialist will follow up with you within 24 hours.
                    </p>
                    <form id="wf-drawer-form">
                        <input type="text" class="wf-lead-input" id="wf-drawer-name" placeholder="Your full name" required />
                        <input type="email" class="wf-lead-input" id="wf-drawer-email" placeholder="Work email address" required />
                        <input type="tel" class="wf-lead-input" id="wf-drawer-phone" placeholder="Phone number (required for follow-up)" required />
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
                <span id="wf-teaser-text">${botConfig.teaser_message}</span>
                <span class="wf-teaser-close" id="wf-teaser-close">&times;</span>
            </div>

            <button type="button" class="wf-launcher" id="wf-trigger-btn" aria-label="Open AI Assistant">
                <span id="wf-btn-icon">
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/>
                    </svg>
                </span>
            </button>
        </div>
    `;
    shadow.appendChild(root);
    document.body.appendChild(hostContainer);

    // Helpers to query elements inside Shadow DOM
    const $ = (id) => shadow.getElementById(id);

    const win = $('wf-window');
    const triggerBtn = $('wf-trigger-btn');
    const closeBtn = $('wf-close-btn');
    const resetBtn = $('wf-reset-btn');
    const emailBtn = $('wf-email-btn');
    const bodyEl = $('wf-body');
    const popularCardsEl = $('wf-popular-cards');
    const formEl = $('wf-form');
    const inputEl = $('wf-input');
    const sendBtn = $('wf-send-btn');
    const micBtn = $('wf-mic-btn');
    const teaserBubble = $('wf-teaser-bubble');
    const teaserClose = $('wf-teaser-close');
    const drawerEl = $('wf-drawer');
    const drawerClose = $('wf-drawer-close');

    // Initial render of cards
    renderPopularCards();

    // Input activate state
    inputEl.addEventListener('input', () => {
        if (inputEl.value.trim().length > 0) {
            sendBtn.classList.add('wf-send-active');
        } else {
            sendBtn.classList.remove('wf-send-active');
        }
    });

    // Fetch dynamic assistant configuration from API
    fetch(`${API_BASE}/api/assistants/${ASSISTANT_ID}`)
        .then(r => {
            if (!r.ok) throw new Error("Assistant fetch status " + r.status);
            return r.json();
        })
        .then(asst => {
            botConfig = { ...botConfig, ...asst };
            applyConfig();
        })
        .catch(() => {
            applyConfig();
        });

    function applyConfig() {
        const nameEl = $('wf-header-name');
        if (nameEl) nameEl.innerText = botConfig.name || "AI Assistant";

        const drawerTitle = $('wf-drawer-title');
        if (drawerTitle) drawerTitle.innerText = `Start Your Project with ${botConfig.name || 'Us'}`;

        const statusEl = $('wf-header-status');
        if (statusEl) statusEl.innerText = botConfig.widget_subtitle || "Online";

        // Avatar
        const avatarBox = $('wf-avatar-box');
        if (avatarBox) {
            if (botConfig.bot_avatar && (botConfig.bot_avatar.startsWith('http') || botConfig.bot_avatar.startsWith('data:image'))) {
                avatarBox.innerHTML = `<img src="${botConfig.bot_avatar}" alt="Avatar" style="width:100% !important; height:100% !important; object-fit:cover !important; border-radius:50% !important; display:block !important;" />`;
            } else {
                avatarBox.innerText = botConfig.bot_avatar || "⚡";
            }
        }

        // Color Accents
        const primaryColor = botConfig.primary_color || "#0f172a";
        const headerEl = $('wf-header');
        if (headerEl) headerEl.style.backgroundColor = primaryColor;
        if (triggerBtn) triggerBtn.style.backgroundColor = primaryColor;

        if (botConfig.position === 'bottom-left') {
            root.classList.add('wf-position-left');
        }

        if (botConfig.voice_enabled === 0 || botConfig.voice_enabled === false) {
            if (micBtn) micBtn.style.display = 'none';
        }

        if (botConfig.teaser_message) {
            const teaserText = $('wf-teaser-text');
            if (teaserText) teaserText.innerText = botConfig.teaser_message;
        } else {
            if (teaserBubble) teaserBubble.style.display = 'none';
        }

        if (botConfig.show_branding === 0 || botConfig.show_branding === false) {
            const footerEl = $('wf-footer');
            if (footerEl) footerEl.style.display = 'none';
        }

        const welcomeEl = $('wf-welcome-msg');
        if (welcomeEl) welcomeEl.innerText = botConfig.welcome_message || "Hi! How can I help you today?";
        renderPopularCards();
    }

    function renderPopularCards() {
        if (!popularCardsEl) return;
        popularCardsEl.innerHTML = '';
        const questions = typeof botConfig.suggested_questions === 'string'
            ? botConfig.suggested_questions.split('\n').filter(q => q.trim())
            : (botConfig.suggested_questions || []);

        questions.slice(0, 4).forEach(q => {
            const card = document.createElement('button');
            card.type = 'button';
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
            root.classList.add('wf-is-open');
            if (window.innerWidth <= 640) {
                hostContainer.style.width = '100vw';
                hostContainer.style.height = '100vh';
                hostContainer.style.pointerEvents = 'auto';
            }
            if (teaserBubble) teaserBubble.style.display = 'none';
            const iconEl = $('wf-btn-icon');
            if (iconEl) {
                iconEl.innerHTML = `
                    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M18 6 6 18"/><path d="m6 6 12 12"/>
                    </svg>
                `;
            }
            setTimeout(() => inputEl.focus(), 200);
        } else {
            win.classList.remove('wf-open');
            root.classList.remove('wf-is-open');
            hostContainer.style.width = '0';
            hostContainer.style.height = '0';
            hostContainer.style.pointerEvents = 'none';
            const iconEl = $('wf-btn-icon');
            if (iconEl) {
                iconEl.innerHTML = `
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/>
                    </svg>
                `;
            }
        }
    }

    window.addEventListener('resize', () => {
        if (isOpen && window.innerWidth <= 640) {
            hostContainer.style.width = '100vw';
            hostContainer.style.height = '100vh';
            hostContainer.style.pointerEvents = 'auto';
        } else if (!isOpen) {
            hostContainer.style.width = '0';
            hostContainer.style.height = '0';
            hostContainer.style.pointerEvents = 'none';
        }
    });

    triggerBtn.addEventListener('click', toggleChat);
    closeBtn.addEventListener('click', toggleChat);
    if (teaserBubble) {
        teaserBubble.addEventListener('click', (e) => {
            if (e.target !== teaserClose) toggleChat();
        });
    }
    if (teaserClose) {
        teaserClose.addEventListener('click', (e) => {
            e.stopPropagation();
            teaserBubble.style.display = 'none';
        });
    }

    // Reset Chat action
    resetBtn.addEventListener('click', () => {
        conversationId = `wf_${ASSISTANT_ID}_${Math.random().toString(36).substring(2, 10)}`;
        sessionStorage.setItem(`wf_conv_${ASSISTANT_ID}`, conversationId);
        
        const userBubbles = bodyEl.querySelectorAll('.wf-bubble, .wf-lead-card');
        userBubbles.forEach(b => b.remove());
        const popSec = $('wf-popular-section');
        if (popSec) popSec.style.display = 'block';
    });

    // Lead drawer actions
    emailBtn.addEventListener('click', () => {
        drawerEl.classList.add('wf-drawer-open');
    });
    drawerClose.addEventListener('click', () => {
        drawerEl.classList.remove('wf-drawer-open');
    });

    $('wf-drawer-form').onsubmit = async (e) => {
        e.preventDefault();
        const submitBtn = $('wf-drawer-submit');
        submitBtn.disabled = true;
        submitBtn.innerText = "Submitting...";

        const payload = {
            assistant_id: ASSISTANT_ID,
            conversation_id: conversationId,
            name: $('wf-drawer-name').value.trim(),
            email: $('wf-drawer-email').value.trim(),
            phone: $('wf-drawer-phone').value.trim()
        };

        try {
            const res = await fetch(`${API_BASE}/api/leads`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            if (!res.ok) throw new Error("Status " + res.status);
            $('wf-drawer-status').style.display = 'block';
            setTimeout(() => {
                drawerEl.classList.remove('wf-drawer-open');
                $('wf-drawer-status').style.display = 'none';
                submitBtn.disabled = false;
                submitBtn.innerText = "Send Information →";
            }, 2000);
        } catch (err) {
            alert("Error submitting details. Please try again.");
            submitBtn.disabled = false;
            submitBtn.innerText = "Send Information →";
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
        if (micBtn) micBtn.style.display = 'none';
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
        const popSec = $('wf-popular-section');
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

            if (data.lead_prompted && botConfig.lead_capture_enabled) {
                renderInChatLeadCard();
            }

        } catch (err) {
            typingEl.remove();
            appendMsg('bot', "I apologize, but I am having trouble connecting to the service right now. Please try again in a moment.");
        }
    }

    function formatMessageText(text) {
        if (!text) return '';
        let escaped = escapeHtml(text);
        // Bold: **text**
        escaped = escaped.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
        // Italic: *text*
        escaped = escaped.replace(/\*(.+?)\*/g, '<em>$1</em>');
        // Inline Citations: [1], [2]
        escaped = escaped.replace(/\[(\d+)\]/g, '<span class="wf-citation-inline">[$1]</span>');
        
        // Lists with bullet points
        const lines = escaped.split(/\n+/);
        let inList = false;
        let formatted = '';
        for (let line of lines) {
            line = line.trim();
            if (line.startsWith('• ') || line.startsWith('- ')) {
                if (!inList) {
                    formatted += '<ul class="wf-msg-list">';
                    inList = true;
                }
                formatted += `<li>${line.substring(2)}</li>`;
            } else {
                if (inList) {
                    formatted += '</ul>';
                    inList = false;
                }
                if (line) {
                    formatted += `<p class="wf-msg-p">${line}</p>`;
                }
            }
        }
        if (inList) formatted += '</ul>';
        return formatted || escaped;
    }

    function appendMsg(role, text, sources = []) {
        const bubble = document.createElement('div');
        bubble.className = `wf-bubble ${role === 'user' ? 'wf-bubble-user' : 'wf-bubble-bot'}`;

        let html = role === 'user'
            ? `<div>${escapeHtml(text || '').replace(/\n/g, '<br>')}</div>`
            : `<div>${formatMessageText(text)}</div>`;

        if (sources && sources.length > 0) {
            html += `<div class="wf-citations">`;
            sources.forEach(s => {
                html += `
                    <a href="${s.url}" target="_blank" class="wf-citation-pill" title="${escapeHtml(s.snippet || '')}">
                        <span>📚</span>
                        <span>[${s.index}] ${escapeHtml(s.title || 'Source')} ↗</span>
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
            <h4>Connect with ${escapeHtml(botConfig.name || 'Our Team')}</h4>
            <p>Leave your phone number and email below so our specialist can call or text you directly!</p>
            <input type="text" placeholder="Your full name..." class="wf-lead-input" id="wf-inline-name" />
            <input type="email" placeholder="Work email address..." class="wf-lead-input" id="wf-inline-email" required />
            <input type="tel" placeholder="Phone number (required)..." class="wf-lead-input" id="wf-inline-phone" required />
            <button type="button" class="wf-lead-btn" id="wf-inline-submit">Request Call / Follow-up &rarr;</button>
        `;

        card.querySelector('#wf-inline-submit').onclick = async (e) => {
            e.preventDefault();
            const emailInput = card.querySelector('#wf-inline-email');
            const phoneInput = card.querySelector('#wf-inline-phone');
            const nameInput = card.querySelector('#wf-inline-name');
            const email = emailInput ? emailInput.value.trim() : '';
            const phone = phoneInput ? phoneInput.value.trim() : '';
            const name = nameInput ? nameInput.value.trim() : '';

            if (!email) {
                alert("Please enter a valid email address.");
                return;
            }
            if (!phone) {
                alert("Please enter your phone number so our team can follow up with you.");
                return;
            }

            const btn = card.querySelector('#wf-inline-submit');
            btn.disabled = true;
            btn.innerText = "Submitting...";

            try {
                const res = await fetch(`${API_BASE}/api/leads`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        assistant_id: ASSISTANT_ID,
                        conversation_id: conversationId,
                        email: email,
                        phone: phone,
                        name: name
                    })
                });
                if (!res.ok) throw new Error("Status " + res.status);
                card.innerHTML = `<div style="color: #16a34a; font-weight: 700; text-align: center; padding: 10px; font-size: 13px;">🎉 Thank you${name ? ', ' + escapeHtml(name) : ''}! We have received your phone number and email. Our team will contact you shortly.</div>`;
            } catch (err) {
                btn.disabled = false;
                btn.innerText = "Request Call / Follow-up →";
                alert("Error submitting details. Please try again.");
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
