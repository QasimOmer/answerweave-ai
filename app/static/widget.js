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
    const ASSISTANT_ID = currentScript && currentScript.getAttribute('data-assistant-id');

    if (!ASSISTANT_ID) {
        console.warn("[AnswerWeave] Chatbot widget initialization skipped: Missing 'data-assistant-id' attribute on widget script tag.");
        return;
    }

    let botConfig = {
        name: "AI Assistant",
        primary_color: "#0f172a",
        welcome_message: "Hi there! 👋 How can I assist you today?",
        bot_avatar: "⚡",
        position: "bottom-right",
        widget_subtitle: "Online • AI Assistant",
        suggested_questions: "",
        lead_capture_enabled: 1,
        voice_enabled: 1,
        launcher_style: "circle",
        launcher_text: "Chat with us",
        launcher_pulse: 1,
        teaser_message: "",
        show_branding: 1,
        whatsapp_number: "",
        theme_mode: "light",
        border_radius: "22px",
        input_placeholder: "Ask a question...",
        sound_enabled: 1
    };

    // The conversation id is the visitor's key to their own transcript, so make it unguessable.
    function newConversationId() {
        let rand = '';
        try {
            rand = (crypto.randomUUID ? crypto.randomUUID() : Array.from(crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2, '0')).join('')).replace(/-/g, '');
        } catch (e) {
            rand = Math.random().toString(36).slice(2) + Date.now().toString(36);
        }
        return `wf_${ASSISTANT_ID}_${rand}`;
    }
    let conversationId = sessionStorage.getItem(`wf_conv_${ASSISTANT_ID}`) || newConversationId();
    sessionStorage.setItem(`wf_conv_${ASSISTANT_ID}`, conversationId);

    const LAUNCHER_ICONS = {
        chat: '<path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/>',
        sparkles: '<path d="m12 3 1.9 5.8L20 11l-6.1 2.2L12 19l-1.9-5.8L4 11l6.1-2.2Z"/>',
        help: '<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><path d="M12 17h.01"/>',
    };

    function launcherIconHtml() {
        const icon = botConfig.launcher_icon || 'chat';
        const av = botConfig.bot_avatar || '';
        if (icon === 'avatar' && av) {
            if (av.startsWith('http') || av.startsWith('data:image')) {
                return `<img src="${escapeHtml(av)}" alt="" style="width:34px !important;height:34px !important;border-radius:50% !important;object-fit:cover !important;display:block !important;" />`;
            }
            return `<span style="font-size:24px !important;line-height:1 !important;">${escapeHtml(av)}</span>`;
        }
        const paths = LAUNCHER_ICONS[icon] || LAUNCHER_ICONS.chat;
        return `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${paths}</svg>`;
    }

    function isLightColor(hex) {
        const m = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec((hex || '').trim());
        if (!m) return false;
        let h = m[1];
        if (h.length === 3) h = h.split('').map(c => c + c).join('');
        const [r, g, b] = [0, 2, 4].map(i => parseInt(h.substr(i, 2), 16) / 255)
            .map(c => c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4));
        // Relative luminance; above ~0.45, white text drops below 3:1 contrast.
        return (0.2126 * r + 0.7152 * g + 0.0722 * b) > 0.45;
    }

    const FONT_STACKS = {
        jakarta: { css: "'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" },
        inter: { css: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif", href: 'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap' },
        system: { css: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif" },
        serif: { css: "Georgia, 'Times New Roman', serif" },
    };

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
    hostContainer.style.cssText = 'display: none !important; all: initial !important; position: fixed !important; bottom: 0 !important; right: 0 !important; z-index: 2147483647 !important; pointer-events: none !important; width: 0 !important; height: 0 !important; overflow: visible !important;';

    const shadow = hostContainer.attachShadow ? hostContainer.attachShadow({ mode: 'open' }) : hostContainer;

    // Scoped CSS styles
    const style = document.createElement('style');
    style.textContent = `
        @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');

        :host, .wf-root {
            all: initial;
            font-family: var(--wf-font, 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif) !important;
            -webkit-font-smoothing: antialiased !important;
            box-sizing: border-box !important;
            color: var(--wf-text, #0f172a) !important;
            --wf-primary: #0f172a;
            --wf-radius: 22px;
            --wf-bg: #ffffff;
            --wf-surface: #f8fafc;
            --wf-surface-hover: #f1f5f9;
            --wf-card-bg: #ffffff;
            --wf-card-border: rgba(226, 232, 240, 0.9);
            --wf-card-border-hover: rgba(203, 213, 225, 1);
            --wf-text: #0f172a;
            --wf-text-muted: #64748b;
            --wf-text-subtle: #94a3b8;
            --wf-bot-bubble-bg: #ffffff;
            --wf-bot-bubble-border: #e2e8f0;
            --wf-bot-bubble-text: #0f172a;
            --wf-bot-bubble-shadow: 0 2px 10px rgba(0, 0, 0, 0.04);
            --wf-input-wrap-bg: #ffffff;
            --wf-input-field-bg: #f1f5f9;
            --wf-input-field-border: #e2e8f0;
            --wf-footer-bg: #ffffff;
            --wf-window-shadow: 0 25px 70px -12px rgba(15, 23, 42, 0.24), 0 4px 16px rgba(0, 0, 0, 0.05);
            --wf-window-border: rgba(226, 232, 240, 0.9);
        }

        .wf-dark {
            --wf-bg: #0b0f17 !important;
            --wf-surface: #07090e !important;
            --wf-surface-hover: #141b2a !important;
            --wf-card-bg: #0f1624 !important;
            --wf-card-border: rgba(255, 255, 255, 0.08) !important;
            --wf-card-border-hover: rgba(255, 255, 255, 0.18) !important;
            --wf-text: #f8fafc !important;
            --wf-text-muted: #94a3b8 !important;
            --wf-text-subtle: #64748b !important;
            --wf-bot-bubble-bg: #0f1624 !important;
            --wf-bot-bubble-border: rgba(255, 255, 255, 0.08) !important;
            --wf-bot-bubble-text: #f8fafc !important;
            --wf-bot-bubble-shadow: 0 4px 16px rgba(0, 0, 0, 0.4) !important;
            --wf-input-wrap-bg: #0b0f17 !important;
            --wf-input-field-bg: #111827 !important;
            --wf-input-field-border: rgba(255, 255, 255, 0.09) !important;
            --wf-footer-bg: #0b0f17 !important;
            --wf-window-shadow: 0 25px 70px -15px rgba(0, 0, 0, 0.8), 0 0 0 1px rgba(255, 255, 255, 0.08), inset 0 1px 0 rgba(255, 255, 255, 0.1) !important;
            --wf-window-border: rgba(255, 255, 255, 0.1) !important;
        }

        *, *::before, *::after {
            box-sizing: border-box !important;
            margin: 0;
            padding: 0;
        }

        .wf-root {
            position: fixed !important;
            bottom: var(--wf-offset-y, 24px) !important;
            right: var(--wf-offset-x, 24px) !important;
            z-index: 2147483647 !important;
            pointer-events: none !important;
        }
        .wf-position-left {
            right: auto !important;
            left: var(--wf-offset-x, 24px) !important;
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
            background: var(--wf-card-bg, #ffffff) !important;
            color: var(--wf-text, #0f172a) !important;
            padding: 10px 16px !important;
            border-radius: 18px 18px 4px 18px !important;
            box-shadow: 0 10px 25px -4px rgba(0, 0, 0, 0.18), 0 2px 6px rgba(0, 0, 0, 0.05) !important;
            border: 1px solid var(--wf-card-border, rgba(226, 232, 240, 0.9)) !important;
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
            box-shadow: 0 14px 30px -4px rgba(0, 0, 0, 0.25) !important;
        }
        .wf-teaser-close {
            color: var(--wf-text-subtle, #94a3b8) !important;
            font-size: 14px !important;
            padding: 2px !important;
            cursor: pointer !important;
        }
        .wf-teaser-close:hover { color: var(--wf-text, #0f172a) !important; }

        /* Floating Launcher Button */
        button.wf-launcher {
            all: unset !important;
            width: 56px !important;
            height: 56px !important;
            min-width: 56px !important;
            min-height: 56px !important;
            border-radius: 50% !important;
            background: var(--wf-primary, #0f172a) !important;
            box-shadow: 0 10px 30px -4px rgba(15, 23, 42, 0.45), 0 4px 10px rgba(0,0,0,0.15) !important;
            border: 1px solid rgba(255, 255, 255, 0.2) !important;
            cursor: pointer !important;
            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
            color: #ffffff !important;
            padding: 0 !important;
            margin: 0 !important;
            box-sizing: border-box !important;
            transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1) !important;
            outline: none !important;
            pointer-events: auto !important;
            position: relative !important;
        }
        button.wf-launcher:hover {
            transform: scale(1.06) translateY(-2px) !important;
            box-shadow: 0 16px 36px -4px rgba(15, 23, 42, 0.5), 0 6px 12px rgba(0,0,0,0.2) !important;
        }
        button.wf-launcher.wf-launcher-pill {
            width: auto !important;
            min-width: unset !important;
            height: 50px !important;
            min-height: 50px !important;
            padding: 0 18px !important;
            border-radius: 9999px !important;
            gap: 9px !important;
            font-size: 13.5px !important;
            font-weight: 700 !important;
            letter-spacing: -0.01em !important;
        }
        .wf-is-open button.wf-launcher {
            width: 48px !important;
            min-width: 48px !important;
            height: 48px !important;
            min-height: 48px !important;
            padding: 0 !important;
            border-radius: 50% !important;
            gap: 0 !important;
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35) !important;
        }
        .wf-is-open button.wf-launcher:hover {
            transform: scale(1.06) !important;
        }
        .wf-is-open button.wf-launcher #wf-btn-label {
            display: none !important;
        }
        .wf-is-open .wf-has-pulse::before {
            display: none !important;
        }
        .wf-is-open .wf-teaser-bubble {
            display: none !important;
        }
        .wf-has-pulse::before {
            content: '' !important;
            position: absolute !important;
            inset: -5px !important;
            border-radius: inherit !important;
            background: inherit !important;
            opacity: 0.45 !important;
            z-index: -1 !important;
            animation: wfPulseRing 2.4s cubic-bezier(0.24, 0, 0.38, 1) infinite !important;
            pointer-events: none !important;
        }
        @keyframes wfPulseRing {
            0% { transform: scale(1); opacity: 0.45; }
            60% { transform: scale(1.22); opacity: 0; }
            100% { transform: scale(1.22); opacity: 0; }
        }
        button.wf-launcher svg {
            width: 22px !important;
            height: 22px !important;
            stroke: currentColor !important;
            fill: none !important;
            display: block !important;
            pointer-events: none !important;
            transition: transform 0.25s cubic-bezier(0.16, 1, 0.3, 1) !important;
        }

        /* Widget Container Window */
        .wf-window {
            position: fixed !important;
            bottom: calc(var(--wf-offset-y, 24px) + 62px) !important;
            right: var(--wf-offset-x, 24px) !important;
            width: var(--wf-width, 395px) !important;
            height: 620px !important;
            max-width: calc(100vw - 36px) !important;
            max-height: calc(100dvh - 110px) !important;
            background: var(--wf-bg, #ffffff) !important;
            border-radius: var(--wf-radius, 22px) !important;
            box-shadow: var(--wf-window-shadow) !important;
            display: flex !important;
            flex-direction: column !important;
            overflow: hidden !important;
            opacity: 0 !important;
            pointer-events: none !important;
            transform: translateY(16px) scale(0.97) !important;
            transition: opacity 0.25s cubic-bezier(0.16, 1, 0.3, 1), transform 0.25s cubic-bezier(0.16, 1, 0.3, 1), border-radius 0.2s !important;
            z-index: 2147483647 !important;
            border: 1px solid var(--wf-window-border, rgba(226, 232, 240, 0.85)) !important;
            backdrop-filter: blur(20px) !important;
        }
        .wf-position-left .wf-window {
            right: auto !important;
            left: var(--wf-offset-x, 24px) !important;
        }
        .wf-window.wf-open {
            opacity: 1 !important;
            pointer-events: auto !important;
            transform: translateY(0) scale(1) !important;
        }

        /* Header Bar */
        .wf-header {
            background: var(--wf-primary, #0f172a) !important;
            color: #ffffff !important;
            padding: 16px 20px !important;
            display: flex !important;
            align-items: center !important;
            justify-content: space-between !important;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1) !important;
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
        .wf-title-row {
            display: flex !important;
            align-items: center !important;
            gap: 6px !important;
        }
        .wf-header-title {
            font-weight: 700 !important;
            font-size: 15px !important;
            color: #ffffff !important;
            line-height: 1.2 !important;
            letter-spacing: -0.01em !important;
        }
        .wf-verified-badge {
            display: inline-flex !important;
            align-items: center !important;
            gap: 3px !important;
            background: rgba(255, 255, 255, 0.14) !important;
            border: 1px solid rgba(255, 255, 255, 0.22) !important;
            color: #ffffff !important;
            font-size: 10px !important;
            font-weight: 700 !important;
            padding: 1px 6px !important;
            border-radius: 9999px !important;
            letter-spacing: 0.02em !important;
            backdrop-filter: blur(8px) !important;
        }
        .wf-status-row {
            display: flex !important;
            align-items: center !important;
            gap: 6px !important;
            margin-top: 3px !important;
            font-size: 11.5px !important;
            color: rgba(255, 255, 255, 0.75) !important;
            font-weight: 500 !important;
        }
        .wf-status-pulse-wrap {
            position: relative !important;
            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
            width: 8px !important;
            height: 8px !important;
        }
        .wf-status-pulse-ring {
            position: absolute !important;
            width: 10px !important;
            height: 10px !important;
            border-radius: 50% !important;
            background: #10b981 !important;
            opacity: 0.25 !important;
            animation: wfStatusHeartbeat 3.2s infinite ease-out !important;
        }
        .wf-status-dot {
            width: 6.5px !important;
            height: 6.5px !important;
            border-radius: 50% !important;
            background: #10b981 !important;
            box-shadow: 0 0 4px rgba(16, 185, 129, 0.45) !important;
            display: inline-block !important;
        }
        @keyframes wfStatusHeartbeat {
            0% { transform: scale(0.9); opacity: 0.35; }
            55% { transform: scale(1.3); opacity: 0; }
            100% { transform: scale(1.3); opacity: 0; }
        }

        /* Top Header Action Buttons (Sleek Ghost Toolbar) */
        .wf-header-actions {
            display: flex !important;
            align-items: center !important;
            gap: 2px !important;
        }
        .wf-header-divider {
            width: 1px !important;
            height: 16px !important;
            background: rgba(255, 255, 255, 0.16) !important;
            margin: 0 3px !important;
        }
        button.wf-icon-btn {
            all: unset !important;
            background: transparent !important;
            border: none !important;
            color: rgba(255, 255, 255, 0.72) !important;
            width: 28px !important;
            height: 28px !important;
            min-width: 28px !important;
            min-height: 28px !important;
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
            background: rgba(255, 255, 255, 0.15) !important;
        }
        button.wf-icon-btn svg {
            width: 16px !important;
            height: 16px !important;
            stroke: currentColor !important;
            fill: none !important;
            display: block !important;
            pointer-events: none !important;
            flex-shrink: 0 !important;
        }
        .wf-header-wa-btn {
            color: #25D366 !important;
        }
        button.wf-header-wa-btn:hover {
            color: #ffffff !important;
            background: rgba(37, 211, 102, 0.25) !important;
        }

        /* Chat Body Canvas with Dotted Pattern */
        .wf-chat-body {
            flex: 1 !important;
            padding: 18px !important;
            overflow-y: auto !important;
            background-color: var(--wf-surface, #f8fafc) !important;
            background-image: radial-gradient(var(--wf-card-border, #cbd5e1) 1px, transparent 1px) !important;
            background-size: 18px 18px !important;
            display: flex !important;
            flex-direction: column !important;
            gap: 14px !important;
            scroll-behavior: smooth !important;
        }
        .wf-dark .wf-chat-body {
            background-color: #07090e !important;
            background-image: radial-gradient(rgba(255, 255, 255, 0.04) 1px, transparent 1px) !important;
            background-size: 18px 18px !important;
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
            position: relative !important;
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
        .wf-dark .wf-citation-inline {
            background: rgba(99, 102, 241, 0.25) !important;
            color: #a5b4fc !important;
        }
        @keyframes wfFadeUp {
            from { opacity: 0; transform: translateY(8px); }
            to { opacity: 1; transform: translateY(0); }
        }

        /* Welcome Message Bubble */
        .wf-welcome-bubble {
            align-self: flex-start !important;
            background: var(--wf-bot-bubble-bg, #ffffff) !important;
            color: var(--wf-bot-bubble-text, #0f172a) !important;
            padding: 14px 18px !important;
            border-radius: 18px 18px 18px 6px !important;
            border: 1px solid var(--wf-bot-bubble-border, #e2e8f0) !important;
            box-shadow: var(--wf-bot-bubble-shadow) !important;
            font-size: 13.5px !important;
            font-weight: 500 !important;
            line-height: 1.55 !important;
            letter-spacing: -0.01em !important;
        }
        .wf-dark .wf-welcome-bubble {
            background: linear-gradient(145deg, #101726, #090e17) !important;
            border: 1px solid rgba(255, 255, 255, 0.08) !important;
        }

        /* Popular Questions Section */
        .wf-popular-section {
            margin-top: 4px !important;
            margin-bottom: 2px !important;
        }
        .wf-popular-head {
            display: flex !important;
            align-items: flex-start !important;
            gap: 10px !important;
            margin-bottom: 12px !important;
        }
        .wf-popular-bar {
            width: 3px !important;
            height: 20px !important;
            background: linear-gradient(180deg, var(--wf-primary, #6366f1), #818cf8) !important;
            border-radius: 4px !important;
            flex-shrink: 0 !important;
            margin-top: 1px !important;
        }
        .wf-dark .wf-popular-bar {
            background: linear-gradient(180deg, #818cf8, #c084fc) !important;
        }
        .wf-popular-title {
            font-size: 13.5px !important;
            font-weight: 700 !important;
            color: var(--wf-text, #0f172a) !important;
            line-height: 1.2 !important;
            letter-spacing: -0.01em !important;
        }
        .wf-popular-sub {
            font-size: 11.5px !important;
            color: var(--wf-text-muted, #64748b) !important;
            margin-top: 2px !important;
        }

        /* Popular Question Cards */
        .wf-popular-cards {
            display: flex !important;
            flex-direction: column !important;
            gap: 8px !important;
        }
        button.wf-question-card {
            all: unset !important;
            background: var(--wf-card-bg, #ffffff) !important;
            border: 1px solid var(--wf-card-border, #e2e8f0) !important;
            border-radius: 14px !important;
            padding: 12px 16px !important;
            display: flex !important;
            align-items: center !important;
            justify-content: space-between !important;
            gap: 10px !important;
            cursor: pointer !important;
            box-shadow: 0 2px 6px rgba(0, 0, 0, 0.03) !important;
            transition: all 0.22s cubic-bezier(0.16, 1, 0.3, 1) !important;
            text-align: left !important;
            width: 100% !important;
            box-sizing: border-box !important;
            color: var(--wf-text, #0f172a) !important;
        }
        .wf-dark button.wf-question-card {
            background: rgba(255, 255, 255, 0.03) !important;
            border: 1px solid rgba(255, 255, 255, 0.07) !important;
            backdrop-filter: blur(8px) !important;
        }
        button.wf-question-card:hover {
            transform: translateY(-2px) translateX(2px) !important;
            border-color: var(--wf-primary, #6366f1) !important;
            box-shadow: 0 6px 20px rgba(0, 0, 0, 0.15) !important;
            background: var(--wf-surface-hover, #f8fafc) !important;
        }
        .wf-dark button.wf-question-card:hover {
            background: rgba(255, 255, 255, 0.07) !important;
            border-color: rgba(255, 255, 255, 0.2) !important;
        }
        .wf-question-left {
            display: flex !important;
            align-items: center !important;
            gap: 10px !important;
            flex: 1 !important;
        }
        .wf-question-sparkle {
            width: 20px !important;
            height: 20px !important;
            min-width: 20px !important;
            border-radius: 6px !important;
            background: rgba(99, 102, 241, 0.09) !important;
            color: #6366f1 !important;
            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
            flex-shrink: 0 !important;
            transition: all 0.2s ease !important;
        }
        .wf-dark .wf-question-sparkle {
            background: rgba(129, 140, 248, 0.15) !important;
            color: #a5b4fc !important;
        }
        button.wf-question-card:hover .wf-question-sparkle {
            transform: scale(1.08) !important;
            background: #6366f1 !important;
            color: #ffffff !important;
        }
        .wf-dark button.wf-question-card:hover .wf-question-sparkle {
            background: #818cf8 !important;
            color: #0f172a !important;
        }
        .wf-question-text {
            font-size: 13px !important;
            font-weight: 600 !important;
            color: var(--wf-text, #0f172a) !important;
            line-height: 1.35 !important;
            flex: 1 !important;
        }
        .wf-question-arrow-icon {
            color: var(--wf-text-subtle, #94a3b8) !important;
            flex-shrink: 0 !important;
            transition: transform 0.2s ease, color 0.2s ease !important;
            display: block !important;
        }
        button.wf-question-card:hover .wf-question-arrow-icon {
            color: var(--wf-primary, #818cf8) !important;
            transform: translateX(3px) !important;
        }

        /* User Message Bubble */
        .wf-bubble-user {
            align-self: flex-end !important;
            background: var(--wf-primary, #0f172a) !important;
            color: #ffffff !important;
            padding: 11px 16px !important;
            border-radius: 18px 18px 4px 18px !important;
            box-shadow: 0 3px 10px rgba(15, 23, 42, 0.2) !important;
            font-weight: 500 !important;
        }

        /* Assistant Grounded Bubble */
        .wf-bubble-bot {
            align-self: flex-start !important;
            background: var(--wf-bot-bubble-bg, #ffffff) !important;
            color: var(--wf-bot-bubble-text, #0f172a) !important;
            padding: 13px 16px !important;
            border-radius: 18px 18px 18px 4px !important;
            border: 1px solid var(--wf-bot-bubble-border, #e2e8f0) !important;
            box-shadow: var(--wf-bot-bubble-shadow) !important;
            position: relative !important;
        }

        /* 1-Click Copy Button on Bot Bubbles */
        .wf-copy-btn {
            all: unset !important;
            position: absolute !important;
            bottom: 6px !important;
            right: 8px !important;
            opacity: 0 !important;
            background: var(--wf-card-bg, #ffffff) !important;
            border: 1px solid var(--wf-card-border, #e2e8f0) !important;
            border-radius: 6px !important;
            padding: 2px 7px !important;
            font-size: 10.5px !important;
            font-weight: 600 !important;
            color: var(--wf-text-muted, #64748b) !important;
            cursor: pointer !important;
            display: inline-flex !important;
            align-items: center !important;
            gap: 4px !important;
            transition: opacity 0.2s, color 0.15s, background 0.15s !important;
            box-shadow: 0 1px 4px rgba(0,0,0,0.06) !important;
            z-index: 2 !important;
        }
        .wf-bubble-bot:hover .wf-copy-btn {
            opacity: 1 !important;
        }
        .wf-copy-btn:hover {
            color: var(--wf-text, #0f172a) !important;
            background: var(--wf-surface-hover, #f1f5f9) !important;
        }

        /* Was this helpful? 👍 / 👎 on bot replies */
        .wf-feedback {
            display: flex !important;
            align-items: center !important;
            gap: 2px !important;
            margin-top: 6px !important;
            min-height: 22px !important;
        }
        .wf-feedback-btn {
            all: unset !important;
            cursor: pointer !important;
            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
            width: 24px !important;
            height: 22px !important;
            border-radius: 6px !important;
            color: var(--wf-text-muted, #64748b) !important;
            opacity: 0.55 !important;
            transition: opacity 0.15s, background 0.15s, color 0.15s !important;
        }
        .wf-bubble-bot:hover .wf-feedback-btn { opacity: 0.9 !important; }
        .wf-feedback-btn:hover { background: var(--wf-surface-hover, #f1f5f9) !important; opacity: 1 !important; }
        .wf-feedback-btn:focus-visible { outline: 2px solid var(--wf-primary, #4f46e5) !important; }
        .wf-feedback-btn[aria-pressed="true"] { opacity: 1 !important; color: var(--wf-primary, #4f46e5) !important; }
        .wf-feedback-btn[aria-pressed="true"] svg { fill: currentColor !important; fill-opacity: 0.18 !important; }
        .wf-feedback-thanks {
            font-size: 10.5px !important;
            color: var(--wf-text-muted, #64748b) !important;
            margin-left: 4px !important;
        }

        /* Real-Time Typewriter Cursor Beam */
        .wf-cursor-beam {
            display: inline-block !important;
            width: 2px !important;
            height: 14px !important;
            background: var(--wf-primary, #4f46e5) !important;
            margin-left: 3px !important;
            vertical-align: text-bottom !important;
            animation: wfBlinkCursor 0.8s infinite !important;
        }
        @keyframes wfBlinkCursor {
            0%, 100% { opacity: 1; }
            50% { opacity: 0; }
        }

        .wf-link-inline {
            color: #2563eb !important;
            text-decoration: underline !important;
            font-weight: 600 !important;
            transition: color 0.15s ease !important;
        }
        .wf-link-inline:hover {
            color: #1d4ed8 !important;
        }

        /* Action Buttons & Rich Product / Property Cards */
        .wf-action-btn {
            display: inline-flex !important;
            align-items: center !important;
            gap: 6px !important;
            background: var(--wf-card-bg, #f8fafc) !important;
            color: var(--wf-text, #0f172a) !important;
            border: 1px solid var(--wf-card-border, #cbd5e1) !important;
            border-radius: 8px !important;
            padding: 5px 12px !important;
            font-size: 12px !important;
            font-weight: 700 !important;
            text-decoration: none !important;
            margin: 4px 2px !important;
            transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1) !important;
            box-shadow: 0 1px 3px rgba(0,0,0,0.04) !important;
            cursor: pointer !important;
        }
        .wf-action-btn:hover {
            background: var(--wf-primary, #0f172a) !important;
            color: #ffffff !important;
            border-color: var(--wf-primary, #0f172a) !important;
            transform: translateY(-1px) !important;
            box-shadow: 0 3px 8px rgba(15, 23, 42, 0.15) !important;
        }
        .wf-action-arrow {
            font-size: 11px !important;
            opacity: 0.7 !important;
        }
        /* WhatsApp Action Buttons & Card Media */
        .wf-whatsapp-btn {
            background: linear-gradient(135deg, #25D366, #128C7E) !important;
            color: #ffffff !important;
            border: 1px solid rgba(255, 255, 255, 0.25) !important;
            box-shadow: 0 2px 6px rgba(37, 211, 102, 0.25) !important;
        }
        .wf-whatsapp-btn:hover {
            background: linear-gradient(135deg, #1ebe5d, #075E54) !important;
            color: #ffffff !important;
            transform: translateY(-1px) !important;
            box-shadow: 0 4px 12px rgba(37, 211, 102, 0.4) !important;
        }
        .wf-header-wa-btn {
            color: #25D366 !important;
        }
        .wf-header-wa-btn:hover {
            color: #ffffff !important;
            background: rgba(37, 211, 102, 0.25) !important;
        }
        .wf-card-media {
            margin: 6px 0 8px 0 !important;
            border-radius: 10px !important;
            overflow: hidden !important;
            background: var(--wf-surface-hover, #f1f5f9) !important;
            border: 1px solid var(--wf-card-border, rgba(0, 0, 0, 0.08)) !important;
            box-shadow: 0 2px 6px rgba(0, 0, 0, 0.05) !important;
            max-width: 280px !important;
        }
        .wf-card-img {
            width: 100% !important;
            height: 140px !important;
            object-fit: cover !important;
            display: block !important;
            transition: transform 0.3s ease !important;
        }
        .wf-card-img:hover {
            transform: scale(1.03) !important;
        }
        .wf-price-badge {
            display: inline-block !important;
            background: rgba(16, 185, 129, 0.12) !important;
            color: #059669 !important;
            border: 1px solid rgba(16, 185, 129, 0.25) !important;
            border-radius: 6px !important;
            padding: 1px 6px !important;
            font-weight: 700 !important;
            font-size: 12px !important;
        }

        /* Citations list inside message */
        .wf-citations {
            margin-top: 10px !important;
            padding-top: 8px !important;
            border-top: 1px solid var(--wf-card-border, #f1f5f9) !important;
            display: flex !important;
            flex-wrap: wrap !important;
            gap: 6px !important;
        }
        .wf-citation-pill {
            display: inline-flex !important;
            align-items: center !important;
            gap: 4px !important;
            background: var(--wf-input-field-bg, #f8fafc) !important;
            border: 1px solid var(--wf-card-border, #cbd5e1) !important;
            border-radius: 6px !important;
            padding: 3px 8px !important;
            font-size: 11px !important;
            font-weight: 600 !important;
            color: #2563eb !important;
            text-decoration: none !important;
            transition: all 0.15s !important;
        }
        .wf-citation-pill:hover {
            background: var(--wf-surface-hover, #eff6ff) !important;
            border-color: #93c5fd !important;
            color: #1d4ed8 !important;
        }
        /* FAQs and documents: informative, not clickable */
        .wf-citation-pill.wf-citation-static,
        .wf-citation-pill.wf-citation-static:hover {
            color: var(--wf-text-muted, #64748b) !important;
            background: var(--wf-input-field-bg, #f8fafc) !important;
            border-color: var(--wf-card-border, #cbd5e1) !important;
            cursor: default !important;
        }

        /* In-chat Lead Capture Card */
        .wf-lead-card {
            background: var(--wf-card-bg, #ffffff) !important;
            border: 1px solid var(--wf-card-border, #cbd5e1) !important;
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
            color: var(--wf-text, #0f172a) !important;
        }
        .wf-lead-card p {
            margin: 0 0 10px 0 !important;
            font-size: 11.5px !important;
            color: var(--wf-text-muted, #64748b) !important;
        }
        input.wf-lead-input {
            all: unset !important;
            width: 100% !important;
            padding: 9px 12px !important;
            border: 1px solid var(--wf-input-field-border, #cbd5e1) !important;
            border-radius: 10px !important;
            font-size: 12px !important;
            margin-bottom: 8px !important;
            box-sizing: border-box !important;
            outline: none !important;
            background: var(--wf-input-field-bg, #f8fafc) !important;
            transition: all 0.15s !important;
            font-family: inherit !important;
            color: var(--wf-text, #0f172a) !important;
        }
        input.wf-lead-input:focus {
            border-color: var(--wf-primary, #0f172a) !important;
            background: var(--wf-card-bg, #ffffff) !important;
            box-shadow: 0 0 0 2px rgba(15, 23, 42, 0.1) !important;
        }
        button.wf-lead-btn {
            all: unset !important;
            width: 100% !important;
            background: var(--wf-primary, #0f172a) !important;
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
            background: var(--wf-bg, #ffffff) !important;
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
            border-bottom: 1px solid var(--wf-card-border, #e2e8f0) !important;
            display: flex !important;
            align-items: center !important;
            justify-content: space-between !important;
            background: var(--wf-surface, #f8fafc) !important;
        }
        .wf-drawer-title {
            font-weight: 700 !important;
            font-size: 14px !important;
            color: var(--wf-text, #0f172a) !important;
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
            background: var(--wf-input-wrap-bg, #ffffff) !important;
            border-top: 1px solid var(--wf-card-border, #e2e8f0) !important;
            display: flex !important;
            gap: 10px !important;
            align-items: center !important;
            flex-shrink: 0 !important;
            box-sizing: border-box !important;
        }
        .wf-field-container {
            flex: 1 !important;
            background: var(--wf-input-field-bg, #f1f5f9) !important;
            border: 1px solid var(--wf-input-field-border, #e2e8f0) !important;
            border-radius: 24px !important;
            display: flex !important;
            align-items: center !important;
            padding: 3px 6px 3px 14px !important;
            transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1) !important;
            box-sizing: border-box !important;
        }
        .wf-dark .wf-field-container {
            background: rgba(255, 255, 255, 0.04) !important;
            border: 1px solid rgba(255, 255, 255, 0.09) !important;
        }
        .wf-field-container:focus-within {
            background: var(--wf-card-bg, #ffffff) !important;
            border-color: var(--wf-primary, #6366f1) !important;
            box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.15) !important;
        }
        .wf-dark .wf-field-container:focus-within {
            background: rgba(255, 255, 255, 0.07) !important;
            border-color: var(--wf-primary, #818cf8) !important;
            box-shadow: 0 0 0 3px rgba(129, 140, 248, 0.25) !important;
        }
        .wf-field {
            all: unset !important;
            flex: 1 !important;
            border: none !important;
            background: transparent !important;
            font-size: 13.5px !important;
            outline: none !important;
            font-family: inherit !important;
            color: var(--wf-text, #0f172a) !important;
            padding: 8px 4px !important;
            box-sizing: border-box !important;
        }
        .wf-field::placeholder { color: var(--wf-text-subtle, #94a3b8) !important; }

        button.wf-mic-btn {
            all: unset !important;
            background: transparent !important;
            border: none !important;
            color: var(--wf-text-muted, #64748b) !important;
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
            color: var(--wf-text, #0f172a) !important;
            background: rgba(0, 0, 0, 0.05) !important;
        }
        .wf-dark button.wf-mic-btn:hover {
            color: #ffffff !important;
            background: rgba(255, 255, 255, 0.1) !important;
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
            background: var(--wf-surface-hover, #e2e8f0) !important;
            border: 1px solid var(--wf-card-border, #cbd5e1) !important;
            color: var(--wf-text-muted, #64748b) !important;
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
        .wf-dark button.wf-send-btn {
            background: rgba(255, 255, 255, 0.05) !important;
            border: 1px solid rgba(255, 255, 255, 0.1) !important;
            color: rgba(255, 255, 255, 0.45) !important;
        }
        button.wf-send-btn svg {
            width: 16px !important;
            height: 16px !important;
            stroke: currentColor !important;
            fill: none !important;
            display: block !important;
        }
        button.wf-send-btn.wf-send-active {
            background: var(--wf-primary, #0f172a) !important;
            border-color: var(--wf-primary, #0f172a) !important;
            color: #ffffff !important;
            box-shadow: 0 4px 14px rgba(15, 23, 42, 0.25) !important;
        }
        button.wf-send-btn.wf-send-active:hover {
            transform: scale(1.06) !important;
        }

        /* Footer Branding */
        .wf-footer {
            text-align: center !important;
            font-size: 10.5px !important;
            color: var(--wf-text-subtle, #94a3b8) !important;
            padding: 6px !important;
            background: var(--wf-footer-bg, #ffffff) !important;
            font-weight: 500 !important;
            border-top: 1px solid var(--wf-card-border, #f1f5f9) !important;
        }

        /* Typing Dots Indicator */
        .wf-typing-bubble {
            align-self: flex-start !important;
            background: var(--wf-bot-bubble-bg, #ffffff) !important;
            border: 1px solid var(--wf-bot-bubble-border, #e2e8f0) !important;
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
            background: var(--wf-text-subtle, #94a3b8) !important;
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
        /* Live operator messages, system notes and unread badge */
        .wf-bubble-operator {
            border: 1px solid rgba(16, 185, 129, 0.35) !important;
        }
        .wf-operator-label {
            display: flex !important;
            align-items: center !important;
            gap: 6px !important;
            font-size: 11.5px !important;
            font-weight: 600 !important;
            color: #059669 !important;
            margin-bottom: 4px !important;
        }
        .wf-operator-dot {
            width: 7px !important;
            height: 7px !important;
            border-radius: 50% !important;
            background: #10b981 !important;
            display: inline-block !important;
        }
        .wf-system-note {
            display: block !important;
            align-self: center !important;
            width: fit-content !important;
            max-width: 90% !important;
            margin: 6px auto !important;
            padding: 4px 12px !important;
            border-radius: 999px !important;
            background: var(--wf-surface, #f1f5f9) !important;
            color: var(--wf-text-muted, #64748b) !important;
            font-size: 11.5px !important;
            text-align: center !important;
        }
        .wf-unread-badge {
            position: absolute !important;
            top: -4px !important;
            right: -4px !important;
            min-width: 20px !important;
            height: 20px !important;
            padding: 0 6px !important;
            border-radius: 999px !important;
            background: #ef4444 !important;
            color: #ffffff !important;
            font-size: 11px !important;
            font-weight: 700 !important;
            line-height: 20px !important;
            text-align: center !important;
            border: 2px solid #ffffff !important;
            box-sizing: content-box !important;
            pointer-events: none !important;
            z-index: 2 !important;
        }
        .wf-position-left .wf-unread-badge { right: auto !important; left: 40px !important; }
        .wf-is-open .wf-unread-badge { display: none !important; }

        /* Light brand colors: switch on-primary text to dark for readable contrast. */
        .wf-light-primary .wf-header,
        .wf-light-primary .wf-header *:not(.wf-avatar-box):not(.wf-avatar-box *),
        .wf-light-primary button.wf-launcher,
        .wf-light-primary .wf-bubble-user,
        .wf-light-primary .wf-bubble-user *,
        .wf-light-primary button.wf-lead-btn,
        .wf-light-primary button.wf-send-btn.wf-send-active,
        .wf-light-primary .wf-action-btn:hover {
            color: #0f172a !important;
        }
        @media (max-width: 640px) {
            .wf-hide-mobile { display: none !important; }
        }

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
            .wf-is-open .wf-launcher-wrap {
                display: none !important;
            }
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
            .wf-chat-body {
                padding: 14px !important;
                gap: 12px !important;
                -webkit-overflow-scrolling: touch !important;
            }
            .wf-bubble {
                max-width: 92% !important;
                font-size: 13.5px !important;
            }
            form.wf-input-wrap {
                padding: 10px 14px max(14px, env(safe-area-inset-bottom, 14px)) 14px !important;
                gap: 8px !important;
            }
            .wf-field {
                font-size: 16px !important;
                padding: 7px 4px !important;
            }
            input.wf-lead-input {
                font-size: 16px !important;
                padding: 10px 12px !important;
            }
        }

        /* RTL & Arabic Localization */
        .wf-rtl {
            direction: rtl !important;
            text-align: right !important;
        }
        .wf-rtl .wf-header-title {
            text-align: right !important;
        }
        .wf-rtl .wf-question-arrow-icon {
            transform: rotate(180deg) !important;
        }
        .wf-rtl .wf-send-btn svg {
            transform: scaleX(-1) !important;
        }
        .wf-rtl .wf-welcome-bubble {
            border-bottom-left-radius: 18px !important;
            border-bottom-right-radius: 4px !important;
            text-align: right !important;
        }
        .wf-pulse-once {
            animation: wf-pulse 0.8s ease 2 !important;
        }

        /* ================= Header menu, contact card, message formatting ================= */
        .wf-header-left { min-width: 0 !important; flex: 1 !important; }
        .wf-header-info { min-width: 0 !important; }
        .wf-title-row { min-width: 0 !important; }
        .wf-header-title { white-space: nowrap !important; overflow: hidden !important; text-overflow: ellipsis !important; min-width: 0 !important; }
        .wf-header-actions { flex-shrink: 0 !important; }
        .wf-menu-wrap { position: relative !important; display: inline-flex !important; }
        .wf-menu {
            position: absolute !important;
            top: 36px !important;
            right: 0 !important;
            min-width: 220px !important;
            background: var(--wf-card-bg, #ffffff) !important;
            border: 1px solid var(--wf-card-border, #e2e8f0) !important;
            border-radius: 14px !important;
            box-shadow: 0 18px 40px -12px rgba(15, 23, 42, 0.35) !important;
            padding: 6px !important;
            display: none !important;
            z-index: 20 !important;
            transform-origin: top right !important;
        }
        .wf-menu.wf-menu-open { display: block !important; animation: wfMenuIn 0.16s ease-out both !important; }
        @keyframes wfMenuIn { from { opacity: 0; transform: scale(0.96) translateY(-4px); } to { opacity: 1; transform: none; } }
        button.wf-menu-item {
            all: unset !important;
            box-sizing: border-box !important;
            width: 100% !important;
            display: flex !important;
            align-items: center !important;
            gap: 10px !important;
            padding: 9px 10px !important;
            border-radius: 9px !important;
            font-size: 13px !important;
            font-weight: 500 !important;
            color: var(--wf-text, #0f172a) !important;
            cursor: pointer !important;
        }
        button.wf-menu-item:hover, button.wf-menu-item:focus-visible { background: var(--wf-surface-hover, #f1f5f9) !important; }
        button.wf-menu-item svg { width: 16px !important; height: 16px !important; stroke: var(--wf-text-muted, #64748b) !important; flex-shrink: 0 !important; }
        button.wf-icon-btn:focus-visible { outline: 2px solid rgba(255, 255, 255, 0.7) !important; outline-offset: 1px !important; }

        .wf-lead-card { animation: wfBotIn 0.35s cubic-bezier(0.2, 0.8, 0.2, 1) both !important; }
        .wf-lead-card.wf-lead-leaving { opacity: 0 !important; transform: translateY(6px) !important; transition: all 0.2s ease !important; }
        .wf-lead-head { display: flex !important; align-items: flex-start !important; justify-content: space-between !important; gap: 8px !important; }
        button.wf-lead-dismiss {
            all: unset !important;
            font-size: 11.5px !important;
            font-weight: 600 !important;
            color: var(--wf-text-muted, #64748b) !important;
            cursor: pointer !important;
            padding: 2px 6px !important;
            border-radius: 6px !important;
            white-space: nowrap !important;
        }
        button.wf-lead-dismiss:hover { background: var(--wf-surface-hover, #f1f5f9) !important; color: var(--wf-text, #0f172a) !important; }
        .wf-lead-error { display: none; color: #dc2626 !important; font-size: 11.5px !important; margin: -2px 0 8px 0 !important; }
        button.wf-lead-btn:disabled { opacity: 0.6 !important; cursor: default !important; }
        .wf-lead-success { display: flex !important; align-items: center !important; gap: 10px !important; font-size: 13px !important; color: var(--wf-text, #0f172a) !important; font-weight: 500 !important; }
        .wf-lead-check {
            width: 28px !important; height: 28px !important; border-radius: 999px !important; flex-shrink: 0 !important;
            background: rgba(16, 185, 129, 0.14) !important; color: #059669 !important;
            display: inline-flex !important; align-items: center !important; justify-content: center !important;
            animation: wfPop 0.45s cubic-bezier(0.2, 0.9, 0.3, 1.4) both !important;
        }
        .wf-lead-check svg { width: 15px !important; height: 15px !important; }
        @keyframes wfPop { from { transform: scale(0.4); opacity: 0; } to { transform: scale(1); opacity: 1; } }
        .wf-msg-heading { font-weight: 700 !important; margin-top: 4px !important; }
        ol.wf-msg-list { list-style: decimal !important; }

        /* ================= PREMIUM LAYER: depth, motion and listing cards ================= */
        .wf-header {
            background: linear-gradient(135deg, var(--wf-primary, #0f172a) 0%, color-mix(in srgb, var(--wf-primary, #0f172a) 70%, #6366f1) 100%) !important;
            position: relative !important;
            /* Visible so the "more" menu can drop below the header; the window itself clips the sheen. */
            overflow: visible !important;
            z-index: 5 !important;
        }
        .wf-header::after {
            content: '' !important;
            position: absolute !important;
            inset: 0 !important;
            background: linear-gradient(110deg, transparent 35%, rgba(255, 255, 255, 0.16) 50%, transparent 65%) !important;
            transform: translateX(-120%) !important;
            pointer-events: none !important;
        }
        .wf-window.wf-open .wf-header::after {
            animation: wfSheen 1.6s 0.25s cubic-bezier(0.4, 0, 0.2, 1) 1 !important;
        }
        @keyframes wfSheen {
            from { transform: translateX(-120%); }
            to { transform: translateX(120%); }
        }
        .wf-window.wf-open {
            animation: wfWindowIn 0.42s cubic-bezier(0.2, 0.9, 0.25, 1.12) !important;
        }
        @keyframes wfWindowIn {
            from { opacity: 0; transform: translateY(18px) scale(0.96); }
            to { opacity: 1; transform: translateY(0) scale(1); }
        }
        .wf-bubble-bot { animation: wfBotIn 0.38s cubic-bezier(0.2, 0.8, 0.2, 1) both !important; }
        .wf-bubble-user { animation: wfUserIn 0.32s cubic-bezier(0.2, 0.8, 0.2, 1) both !important; }
        @keyframes wfBotIn {
            from { opacity: 0; transform: translate(-6px, 10px) scale(0.98); }
            to { opacity: 1; transform: none; }
        }
        @keyframes wfUserIn {
            from { opacity: 0; transform: translate(6px, 10px) scale(0.98); }
            to { opacity: 1; transform: none; }
        }
        button.wf-question-card { animation: wfFadeUp 0.45s cubic-bezier(0.2, 0.8, 0.2, 1) both !important; }
        button.wf-question-card:nth-child(2) { animation-delay: 0.07s !important; }
        button.wf-question-card:nth-child(3) { animation-delay: 0.14s !important; }
        button.wf-question-card:nth-child(4) { animation-delay: 0.21s !important; }
        .wf-dot-pulse { background: var(--wf-primary, #6366f1) !important; opacity: 0.7 !important; }
        .wf-typing-bubble { box-shadow: var(--wf-bot-bubble-shadow) !important; animation: wfBotIn 0.3s ease both !important; }
        button.wf-send-btn { transition: transform 0.15s ease, background 0.2s ease, box-shadow 0.2s ease !important; }
        button.wf-send-btn:active { transform: scale(0.9) !important; }
        button.wf-launcher { transition: transform 0.3s cubic-bezier(0.2, 0.9, 0.25, 1.2), box-shadow 0.3s ease !important; }
        button.wf-launcher:hover { box-shadow: 0 14px 34px -8px color-mix(in srgb, var(--wf-primary, #0f172a) 70%, transparent) !important; }

        /* Property & product cards */
        .wf-cards {
            display: flex !important;
            gap: 10px !important;
            overflow-x: auto !important;
            scroll-snap-type: x mandatory !important;
            padding: 4px 2px 8px !important;
            margin: 10px -2px 0 !important;
            scrollbar-width: none !important;
            -webkit-mask-image: linear-gradient(to right, #000 86%, transparent) !important;
            mask-image: linear-gradient(to right, #000 86%, transparent) !important;
        }
        .wf-cards.wf-cards-end { -webkit-mask-image: none !important; mask-image: none !important; }
        .wf-cards::-webkit-scrollbar { display: none !important; }
        .wf-lcard {
            flex: 0 0 212px !important;
            scroll-snap-align: start !important;
            background: var(--wf-card-bg, #ffffff) !important;
            border: 1px solid var(--wf-card-border, #e2e8f0) !important;
            border-radius: 16px !important;
            overflow: hidden !important;
            display: flex !important;
            flex-direction: column !important;
            box-shadow: 0 4px 14px rgba(15, 23, 42, 0.06) !important;
            transition: transform 0.25s cubic-bezier(0.2, 0.8, 0.2, 1), box-shadow 0.25s ease, border-color 0.25s ease !important;
            animation: wfCardIn 0.5s cubic-bezier(0.2, 0.8, 0.2, 1) both !important;
            animation-delay: calc(var(--wf-i, 0) * 80ms) !important;
        }
        .wf-lcard:hover {
            transform: translateY(-3px) !important;
            box-shadow: 0 14px 30px -6px rgba(15, 23, 42, 0.18) !important;
            border-color: var(--wf-card-border-hover, #cbd5e1) !important;
        }
        @keyframes wfCardIn {
            from { opacity: 0; transform: translateX(14px) scale(0.97); }
            to { opacity: 1; transform: none; }
        }
        .wf-lcard-media {
            position: relative !important;
            height: 120px !important;
            overflow: hidden !important;
            background: linear-gradient(135deg, color-mix(in srgb, var(--wf-primary, #6366f1) 22%, #e2e8f0), #f8fafc) !important;
        }
        .wf-dark .wf-lcard-media { background: linear-gradient(135deg, color-mix(in srgb, var(--wf-primary, #6366f1) 35%, #0f1624), #0b0f17) !important; }
        .wf-lcard-media img {
            width: 100% !important;
            height: 100% !important;
            object-fit: cover !important;
            display: block !important;
            transition: transform 0.6s cubic-bezier(0.2, 0.8, 0.2, 1), opacity 0.4s ease !important;
            opacity: 0 !important;
        }
        .wf-lcard-media img.wf-loaded { opacity: 1 !important; }
        .wf-lcard:hover .wf-lcard-media img { transform: scale(1.07) !important; }
        .wf-lcard-ph {
            position: absolute !important;
            inset: 0 !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            color: color-mix(in srgb, var(--wf-primary, #6366f1) 55%, #94a3b8) !important;
        }
        .wf-lcard-ph svg { width: 34px !important; height: 34px !important; stroke: currentColor !important; fill: none !important; opacity: 0.8 !important; }
        .wf-lcard-tag {
            position: absolute !important;
            top: 8px !important;
            left: 8px !important;
            background: rgba(15, 23, 42, 0.62) !important;
            backdrop-filter: blur(8px) !important;
            color: #ffffff !important;
            font-size: 10px !important;
            font-weight: 700 !important;
            letter-spacing: 0.04em !important;
            text-transform: uppercase !important;
            padding: 3px 8px !important;
            border-radius: 999px !important;
        }
        .wf-lcard-price {
            position: absolute !important;
            bottom: 8px !important;
            left: 8px !important;
            background: rgba(255, 255, 255, 0.95) !important;
            color: #0f172a !important;
            font-size: 12.5px !important;
            font-weight: 800 !important;
            padding: 4px 10px !important;
            border-radius: 999px !important;
            box-shadow: 0 4px 12px rgba(15, 23, 42, 0.18) !important;
            max-width: calc(100% - 16px) !important;
            white-space: nowrap !important;
            overflow: hidden !important;
            text-overflow: ellipsis !important;
        }
        .wf-lcard-price small { font-weight: 600 !important; color: #64748b !important; font-size: 10.5px !important; }
        .wf-lcard-body { padding: 10px 12px 12px !important; display: flex !important; flex-direction: column !important; flex: 1 !important; }
        .wf-lcard-title {
            font-size: 13px !important;
            font-weight: 700 !important;
            line-height: 1.35 !important;
            color: var(--wf-text, #0f172a) !important;
            display: -webkit-box !important;
            -webkit-line-clamp: 2 !important;
            -webkit-box-orient: vertical !important;
            overflow: hidden !important;
        }
        .wf-lcard-meta {
            font-size: 11.5px !important;
            color: var(--wf-text-muted, #64748b) !important;
            margin-top: 3px !important;
            white-space: nowrap !important;
            overflow: hidden !important;
            text-overflow: ellipsis !important;
        }
        .wf-lcard-chips { display: flex !important; flex-wrap: wrap !important; gap: 4px !important; margin-top: 8px !important; }
        .wf-chip {
            font-size: 10.5px !important;
            font-weight: 600 !important;
            padding: 2px 7px !important;
            border-radius: 999px !important;
            background: var(--wf-surface-hover, #f1f5f9) !important;
            color: var(--wf-text-muted, #64748b) !important;
            border: 1px solid var(--wf-card-border, #e2e8f0) !important;
        }
        .wf-chip-ok { color: #059669 !important; background: rgba(16, 185, 129, 0.1) !important; border-color: rgba(16, 185, 129, 0.25) !important; }
        .wf-chip-warn { color: #b45309 !important; background: rgba(245, 158, 11, 0.1) !important; border-color: rgba(245, 158, 11, 0.28) !important; }
        .wf-lcard-actions { display: grid !important; grid-template-columns: 1fr 1fr !important; gap: 6px !important; margin-top: auto !important; padding-top: 10px !important; }
        .wf-lcard-actions > :only-child { grid-column: 1 / -1 !important; }
        .wf-lcard-btn {
            all: unset !important;
            box-sizing: border-box !important;
            text-align: center !important;
            font-size: 11.5px !important;
            font-weight: 700 !important;
            padding: 7px 4px !important;
            border-radius: 10px !important;
            cursor: pointer !important;
            transition: filter 0.2s ease, background 0.2s ease, transform 0.15s ease !important;
            white-space: nowrap !important;
        }
        .wf-lcard-btn:active { transform: scale(0.96) !important; }
        .wf-lcard-btn:focus-visible { outline: 2px solid var(--wf-primary, #6366f1) !important; outline-offset: 2px !important; }
        .wf-lcard-btn-primary { background: var(--wf-primary, #0f172a) !important; color: #ffffff !important; }
        .wf-lcard-btn-primary:hover { filter: brightness(1.15) !important; }
        .wf-lcard-btn-ghost { border: 1px solid var(--wf-card-border, #e2e8f0) !important; color: var(--wf-text, #0f172a) !important; }
        .wf-lcard-btn-ghost:hover { background: var(--wf-surface-hover, #f1f5f9) !important; }

        /* ================= DESIGN SYSTEM LAYER ================= */
        .wf-sr-only { position: absolute !important; width: 1px !important; height: 1px !important; overflow: hidden !important; clip: rect(0 0 0 0) !important; white-space: nowrap !important; }

        /* Messages: readable type, avatar beside replies, grouped rhythm */
        .wf-chat-body { gap: 10px !important; padding: 18px 16px 12px !important; }
        .wf-bubble { font-size: 14px !important; line-height: 1.6 !important; }
        .wf-msg-p { margin: 0 0 8px 0 !important; line-height: 1.6 !important; }
        .wf-bubble-user + .wf-bubble-bot, .wf-bubble-bot + .wf-bubble-user { margin-top: 6px !important; }
        .wf-bubble-user {
            max-width: 82% !important;
            padding: 10px 14px !important;
            border-radius: 18px 18px 6px 18px !important;
            box-shadow: 0 2px 8px rgba(15, 23, 42, 0.12) !important;
        }
        .wf-bubble-bot:not(.wf-bubble-operator) {
            margin-left: 34px !important;
            max-width: calc(100% - 40px) !important;
            padding: 12px 15px !important;
            border-radius: 6px 18px 18px 18px !important;
            box-shadow: 0 1px 2px rgba(15, 23, 42, 0.05) !important;
            overflow: visible !important;
        }
        .wf-bubble-bot:not(.wf-bubble-operator)::before {
            content: var(--wf-bot-avatar-text, "") !important;
            position: absolute !important;
            left: -34px !important;
            top: 0 !important;
            width: 26px !important;
            height: 26px !important;
            border-radius: 999px !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            font-size: 13px !important;
            line-height: 1 !important;
            background: color-mix(in srgb, var(--wf-primary, #6366f1) 14%, var(--wf-card-bg, #fff)) !important;
            background-image: var(--wf-bot-avatar-img, none) !important;
            background-size: cover !important;
            background-position: center !important;
            border: 1px solid var(--wf-card-border, #e2e8f0) !important;
        }
        /* Only the first reply in a run shows the avatar */
        .wf-bubble-bot:not(.wf-bubble-operator) + .wf-bubble-bot:not(.wf-bubble-operator)::before { visibility: hidden !important; }
        .wf-bubble-error { border-color: rgba(239, 68, 68, 0.35) !important; }
        button.wf-retry-btn {
            all: unset !important;
            display: inline-flex !important; align-items: center !important; gap: 6px !important;
            margin-top: 8px !important; padding: 6px 10px !important; border-radius: 8px !important;
            font-size: 12.5px !important; font-weight: 600 !important; cursor: pointer !important;
            color: var(--wf-text, #0f172a) !important; border: 1px solid var(--wf-card-border, #e2e8f0) !important;
        }
        button.wf-retry-btn:hover { background: var(--wf-surface-hover, #f1f5f9) !important; }
        button.wf-retry-btn svg { width: 14px !important; height: 14px !important; }

        /* Inline citation badges */
        .wf-citation-inline {
            display: inline-flex !important; align-items: center !important; justify-content: center !important;
            min-width: 16px !important; height: 16px !important; padding: 0 4px !important; margin: 0 1px 0 2px !important;
            border-radius: 999px !important; font-size: 10px !important; font-weight: 700 !important; line-height: 1 !important;
            vertical-align: 2px !important; cursor: help !important;
            background: color-mix(in srgb, var(--wf-primary, #6366f1) 12%, transparent) !important;
            color: color-mix(in srgb, var(--wf-primary, #4338ca) 85%, var(--wf-text, #0f172a)) !important;
        }
        .wf-dark .wf-citation-inline { background: rgba(255, 255, 255, 0.10) !important; color: #c7d2fe !important; }

        /* Sources row */
        .wf-citations {
            display: flex !important; flex-wrap: wrap !important; align-items: center !important; gap: 6px !important;
            margin-top: 10px !important; padding: 10px 0 0 0 !important; background: transparent !important;
            border-top: 1px solid var(--wf-card-border, #eef2f7) !important;
        }
        .wf-src-label { font-size: 11px !important; font-weight: 600 !important; letter-spacing: 0.02em !important; color: var(--wf-text-subtle, #94a3b8) !important; margin-right: 2px !important; }
        .wf-citation-pill, .wf-citation-pill:hover {
            display: inline-flex !important; align-items: center !important; gap: 5px !important;
            max-width: 100% !important; padding: 3px 9px 3px 4px !important; border-radius: 999px !important;
            font-size: 11.5px !important; font-weight: 500 !important; text-decoration: none !important;
            background: var(--wf-surface, #f8fafc) !important; border: 1px solid var(--wf-card-border, #e2e8f0) !important;
            color: var(--wf-text, #0f172a) !important; transition: border-color 0.15s, background 0.15s !important;
        }
        a.wf-citation-pill:hover { border-color: color-mix(in srgb, var(--wf-primary, #6366f1) 45%, transparent) !important; background: var(--wf-card-bg, #fff) !important; }
        .wf-citation-pill.wf-citation-static, .wf-citation-pill.wf-citation-static:hover { color: var(--wf-text-muted, #64748b) !important; cursor: default !important; }
        .wf-citation-pill svg { width: 11px !important; height: 11px !important; flex-shrink: 0 !important; opacity: 0.6 !important; }
        .wf-src-num {
            display: inline-flex !important; align-items: center !important; justify-content: center !important;
            min-width: 16px !important; height: 16px !important; border-radius: 999px !important; font-size: 10px !important; font-weight: 700 !important;
            background: color-mix(in srgb, var(--wf-primary, #6366f1) 12%, transparent) !important;
            color: color-mix(in srgb, var(--wf-primary, #4338ca) 85%, var(--wf-text, #0f172a)) !important;
        }
        .wf-src-title { overflow: hidden !important; text-overflow: ellipsis !important; white-space: nowrap !important; max-width: 160px !important; }
        .wf-src-extra { display: none !important; }
        .wf-src-expanded .wf-src-extra { display: inline-flex !important; }
        button.wf-src-more {
            all: unset !important; font-size: 11.5px !important; font-weight: 600 !important; cursor: pointer !important;
            padding: 3px 8px !important; border-radius: 999px !important; color: var(--wf-text-muted, #64748b) !important;
        }
        button.wf-src-more:hover { background: var(--wf-surface-hover, #f1f5f9) !important; color: var(--wf-text, #0f172a) !important; }
        .wf-dark .wf-citation-pill, .wf-dark .wf-citation-pill:hover { background: rgba(255, 255, 255, 0.04) !important; border-color: rgba(255, 255, 255, 0.10) !important; color: #e2e8f0 !important; }
        .wf-dark .wf-src-num { background: rgba(255, 255, 255, 0.10) !important; color: #c7d2fe !important; }
        .wf-dark .wf-citations { border-top-color: rgba(255, 255, 255, 0.08) !important; }

        /* Action row: helpful / not helpful / copy */
        .wf-feedback { margin-top: 8px !important; gap: 2px !important; }
        .wf-feedback button.wf-copy-btn {
            all: unset !important; cursor: pointer !important;
            display: inline-flex !important; align-items: center !important; justify-content: center !important;
            width: 26px !important; height: 24px !important; border-radius: 7px !important;
            color: var(--wf-text-muted, #64748b) !important; opacity: 0.55 !important;
            transition: opacity 0.15s, background 0.15s, color 0.15s !important;
        }
        .wf-feedback button.wf-copy-btn svg { width: 13px !important; height: 13px !important; }
        .wf-bubble-bot:hover .wf-feedback button.wf-copy-btn { opacity: 0.9 !important; }
        .wf-feedback button.wf-copy-btn:hover { background: var(--wf-surface-hover, #f1f5f9) !important; opacity: 1 !important; }
        .wf-feedback button.wf-copy-btn.wf-copied { color: #059669 !important; opacity: 1 !important; }
        .wf-feedback button.wf-copy-btn:focus-visible, .wf-feedback-btn:focus-visible { outline: 2px solid var(--wf-primary, #6366f1) !important; outline-offset: 1px !important; }
        button.wf-copy-btn:not(.wf-feedback *) svg { width: 11px !important; height: 11px !important; }
        @media (hover: none) {
            .wf-feedback-btn, .wf-feedback button.wf-copy-btn { opacity: 0.8 !important; }
        }

        /* Composer */
        .wf-field-container { align-items: flex-end !important; border-radius: 22px !important; padding: 4px 6px 4px 14px !important; position: relative !important; }
        textarea.wf-field {
            resize: none !important; display: block !important; width: 100% !important;
            min-height: 22px !important; max-height: 120px !important; overflow-y: auto !important;
            line-height: 1.45 !important; padding: 8px 4px !important; white-space: pre-wrap !important;
            scrollbar-width: thin !important;
        }
        button.wf-mic-btn { margin-bottom: 3px !important; }
        form.wf-input-wrap { align-items: flex-end !important; }
        button.wf-send-btn { margin-bottom: 2px !important; }
        .wf-char-count {
            position: absolute !important; right: 46px !important; top: -18px !important;
            font-size: 10.5px !important; font-weight: 600 !important; color: var(--wf-text-subtle, #94a3b8) !important;
        }
        .wf-char-count.wf-char-limit { color: #dc2626 !important; }

        /* Jump to latest */
        button.wf-jump-btn {
            all: unset !important; position: absolute !important; left: 50% !important; bottom: 92px !important;
            width: 34px !important; height: 34px !important; border-radius: 999px !important; cursor: pointer !important;
            display: flex !important; align-items: center !important; justify-content: center !important;
            background: var(--wf-card-bg, #fff) !important; color: var(--wf-text, #0f172a) !important;
            border: 1px solid var(--wf-card-border, #e2e8f0) !important; box-shadow: 0 8px 22px -6px rgba(15, 23, 42, 0.3) !important;
            opacity: 0 !important; pointer-events: none !important; transform: translate(-50%, 8px) !important;
            transition: opacity 0.2s, transform 0.2s !important; z-index: 6 !important;
        }
        button.wf-jump-btn.wf-jump-visible { opacity: 1 !important; pointer-events: auto !important; transform: translate(-50%, 0) !important; }
        button.wf-jump-btn svg { width: 16px !important; height: 16px !important; }

        /* Focus rings for keyboard users */
        button.wf-launcher:focus-visible, button.wf-send-btn:focus-visible, button.wf-question-card:focus-visible, .wf-citation-pill:focus-visible {
            outline: 2px solid var(--wf-primary, #6366f1) !important; outline-offset: 2px !important;
        }

        @media (prefers-reduced-motion: reduce) {
            .wf-root *, .wf-root *::before, .wf-root *::after {
                animation-duration: 0.01ms !important;
                animation-delay: 0s !important;
                transition-duration: 0.01ms !important;
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
        <div class="wf-window" id="wf-window" role="dialog" aria-modal="false" aria-label="Chat with our assistant">
            <!-- Header Bar -->
            <div class="wf-header" id="wf-header">
                <div class="wf-header-left">
                    <div class="wf-avatar-circle" id="wf-avatar-box">⚡</div>
                    <div class="wf-header-info">
                        <div class="wf-title-row">
                            <span class="wf-header-title" id="wf-header-name">${botConfig.name}</span>
                            <span class="wf-verified-badge" title="Official Verified AI Assistant">
                                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                                    <polyline points="20 6 9 17 4 12"/>
                                </svg>
                                <span>AI</span>
                            </span>
                        </div>
                        <div class="wf-status-row">
                            <span class="wf-status-pulse-wrap">
                                <span class="wf-status-pulse-ring"></span>
                                <span class="wf-status-dot"></span>
                            </span>
                            <span id="wf-header-status">${botConfig.widget_subtitle || 'Online'}</span>
                        </div>
                    </div>
                </div>

                <div class="wf-header-actions">
                    <button type="button" class="wf-icon-btn wf-header-wa-btn" id="wf-whatsapp-header-btn" title="Chat on WhatsApp" style="display: none;">
                        <svg width="17" height="17" viewBox="0 0 24 24" fill="currentColor">
                            <path d="M.057 24l1.687-6.163c-1.041-1.804-1.588-3.849-1.587-5.946.003-6.556 5.338-11.891 11.893-11.891 3.181.001 6.167 1.24 8.413 3.488 2.245 2.248 3.481 5.236 3.48 8.414-.003 6.557-5.338 11.892-11.893 11.892-1.99-.001-3.951-.5-5.688-1.448l-6.305 1.654zm6.597-3.807c1.676.995 3.276 1.591 5.392 1.592 5.448 0 9.886-4.434 9.889-9.885.002-5.462-4.415-9.89-9.881-9.892-5.452 0-9.887 4.434-9.889 9.884-.001 2.225.651 3.891 1.746 5.634l-.999 3.648 3.742-.981zm11.387-5.464c-.074-.124-.272-.198-.57-.347-.297-.149-1.758-.868-2.031-.967-.272-.099-.47-.149-.669.149-.198.297-.768.967-.941 1.165-.173.198-.347.223-.644.074-.297-.149-1.255-.462-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.297-.347.446-.521.151-.172.2-.296.3-.495.099-.198.05-.372-.025-.521-.075-.148-.669-1.611-.916-2.206-.242-.579-.487-.501-.669-.51l-.57-.01c-.198 0-.52.074-.792.372s-1.04 1.016-1.04 2.479 1.065 2.876 1.213 3.074c.149.198 2.095 3.2 5.076 4.487.709.306 1.263.489 1.694.626.712.226 1.36.194 1.872.118.571-.085 1.758-.719 2.006-1.413.248-.695.248-1.29.173-1.414z"/>
                        </svg>
                    </button>
                    <div class="wf-menu-wrap">
                        <button type="button" class="wf-icon-btn" id="wf-more-btn" title="More options" aria-label="More options" aria-haspopup="menu" aria-expanded="false">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
                                <circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>
                            </svg>
                        </button>
                        <div class="wf-menu" id="wf-menu" role="menu">
                            <button type="button" class="wf-menu-item" id="wf-reset-btn" role="menuitem">
                                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>
                                <span>Start a new chat</span>
                            </button>
                            <button type="button" class="wf-menu-item" id="wf-email-btn" role="menuitem">
                                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="20" height="16" x="2" y="4" rx="2"/><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/></svg>
                                <span>Leave my contact details</span>
                            </button>
                            <button type="button" class="wf-menu-item" id="wf-sound-toggle-btn" role="menuitem">
                                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/></svg>
                                <span>Mute sounds</span>
                            </button>
                        </div>
                    </div>
                    <div class="wf-header-divider"></div>
                    <button type="button" class="wf-icon-btn" id="wf-close-btn" title="Close">
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M18 6 6 18"/><path d="m6 6 12 12"/>
                        </svg>
                    </button>
                </div>
            </div>

            <!-- Chat Canvas Body -->
            <div class="wf-chat-body" id="wf-body" role="log" aria-label="Conversation">
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
                    <p style="font-size: 12px; color: var(--wf-text-muted, #64748b); margin-top: 0; margin-bottom: 14px; line-height: 1.5;">
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
                    <textarea class="wf-field" id="wf-input" rows="1" placeholder="Ask a question..." autocomplete="off" maxlength="4000" aria-label="Type your message"></textarea>
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
            <div class="wf-footer" id="wf-footer">Powered by AnswerWeave</div>
            <button type="button" class="wf-jump-btn" id="wf-jump-btn" aria-label="Jump to latest message" tabindex="-1">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14"/><path d="m19 12-7 7-7-7"/></svg>
            </button>
            <div class="wf-sr-only" id="wf-announcer" aria-live="polite" aria-atomic="true"></div>
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
                <span id="wf-btn-label" style="display:none;"></span>
            </button>
            <span class="wf-unread-badge" id="wf-unread-badge" style="display:none;"></span>
        </div>
    `;
    shadow.appendChild(root);

    function mountWidget() {
        if (!document.body) {
            if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', mountWidget);
            } else {
                window.addEventListener('load', mountWidget);
            }
            return;
        }
        hostContainer.style.display = 'block';
        if (!document.body.contains(hostContainer)) {
            document.body.appendChild(hostContainer);
        }
    }

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

    // Follow new text only while the visitor is at the bottom; otherwise offer a jump button.
    const jumpBtn = $('wf-jump-btn');
    let atBottom = true;
    const nearBottom = () => bodyEl.scrollHeight - bodyEl.scrollTop - bodyEl.clientHeight < 80;
    function followLatest() {
        if (atBottom) bodyEl.scrollTop = bodyEl.scrollHeight;
        else jumpBtn.classList.add('wf-jump-visible');
    }
    bodyEl.addEventListener('scroll', () => {
        atBottom = nearBottom();
        if (atBottom) jumpBtn.classList.remove('wf-jump-visible');
    }, { passive: true });
    jumpBtn.addEventListener('click', () => {
        bodyEl.scrollTo({ top: bodyEl.scrollHeight, behavior: 'smooth' });
        jumpBtn.classList.remove('wf-jump-visible');
        atBottom = true;
    });

    // Screen readers hear each finished reply once (not every streamed word).
    const announcer = $('wf-announcer');
    function announce(text) {
        if (!announcer || !text) return;
        announcer.textContent = '';
        setTimeout(() => { announcer.textContent = String(text).replace(/\[(\d+)\]/g, '').replace(/[*#_`]/g, '').slice(0, 600); }, 60);
    }

    // Escape closes the chat (the menu handler closes an open menu first).
    shadow.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && isOpen && !(menuEl && menuEl.classList.contains('wf-menu-open'))) {
            toggleChat();
            triggerBtn.focus();
        }
    });

    // Composer: grows with the text (up to ~5 lines), Enter sends, Shift+Enter adds a line.
    const MAX_CHARS = 4000;
    function resizeInput() {
        // The widget's reset uses `all: unset !important`, so inline sizes need !important too.
        inputEl.style.setProperty('height', 'auto', 'important');
        inputEl.style.setProperty('height', Math.min(inputEl.scrollHeight, 120) + 'px', 'important');
        const len = inputEl.value.length;
        sendBtn.classList.toggle('wf-send-active', inputEl.value.trim().length > 0);
        let counter = formEl.querySelector('.wf-char-count');
        if (len > MAX_CHARS - 500) {
            if (!counter) {
                counter = document.createElement('span');
                counter.className = 'wf-char-count';
                formEl.querySelector('.wf-field-container').appendChild(counter);
            }
            counter.textContent = `${len}/${MAX_CHARS}`;
            counter.classList.toggle('wf-char-limit', len >= MAX_CHARS);
        } else if (counter) {
            counter.remove();
        }
    }
    inputEl.addEventListener('input', resizeInput);
    inputEl.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
            e.preventDefault();
            formEl.requestSubmit ? formEl.requestSubmit() : submitQuery();
        }
    });

    function isHostAllowed(allowedPattern, host) {
        if (!allowedPattern || allowedPattern.trim() === '*' || allowedPattern.trim() === '') {
            return true;
        }
        if (!host) return true;
        host = host.toLowerCase().split(':')[0].trim();
        if (host === 'localhost' || host === '127.0.0.1' || host.endsWith('.vercel.app') || host === 'vercel.app') {
            return true;
        }
        // Previews inside the AnswerWeave app itself (dashboard, onboarding) are always allowed.
        try { if (host === new URL(API_BASE).hostname.toLowerCase()) return true; } catch (e) {}
        const patterns = allowedPattern.split(',').map(p => p.trim().toLowerCase()).filter(Boolean);
        for (let pat of patterns) {
            if (pat === '*') return true;
            pat = pat.replace(/^https?:\/\//i, '').split('/')[0].split(':')[0].trim();
            if (!pat) continue;
            if (pat.startsWith('*.')) {
                const base = pat.slice(2);
                if (host === base || (typeof host.endsWith === 'function' && host.endsWith('.' + base))) return true;
            } else {
                if (host === pat || host === 'www.' + pat || pat === 'www.' + host) return true;
                if (typeof host.endsWith === 'function' && host.endsWith('.' + pat)) return true;
            }
        }
        return false;
    }

    const currentHost = (window.location && window.location.hostname) ? window.location.hostname : '';
    const configUrl = `${API_BASE}/api/assistants/${encodeURIComponent(ASSISTANT_ID)}?host=${encodeURIComponent(currentHost)}`;

    // Fetch dynamic assistant configuration with strict domain whitelist gating
    fetch(configUrl, {
        headers: {
            'Accept': 'application/json',
            'X-Host-Domain': currentHost
        }
    })
    .then(async r => {
        if (r.status === 403) {
            throw new Error(`Domain authorization failed: Host '${currentHost}' is not allowed to use assistant '${ASSISTANT_ID}'.`);
        }
        if (r.status === 404) {
            throw new Error(`Assistant '${ASSISTANT_ID}' not found on server.`);
        }
        if (!r.ok) {
            throw new Error(`API returned HTTP ${r.status}`);
        }
        return r.json();
    })
    .then(asst => {
        // Enforce strict client-side domain authorization check
        if (!isHostAllowed(asst.domain, currentHost)) {
            throw new Error(`Domain restriction: Assistant '${asst.name}' is restricted to domain '${asst.domain}', but current website is '${currentHost}'. Chatbot blocked.`);
        }

        // Domain verification passed! Configure and display widget
        botConfig = { ...botConfig, ...asst };
        applyConfig();
        mountWidget();
        restoreConversation();
        // data-open="true" opens the chat on load (used by the onboarding preview).
        if (currentScript && currentScript.getAttribute('data-open') === 'true' && !isOpen) {
            setTimeout(() => { if (!isOpen) toggleChat(); }, 350);
        }
    })
    .catch(err => {
        console.warn(`[AnswerWeave] Widget blocked: ${err.message}`);
        // Ensure widget is completely hidden and detached from DOM
        if (hostContainer && hostContainer.parentNode) {
            hostContainer.parentNode.removeChild(hostContainer);
        }
    });

    function updateThemeMode() {
        const mode = botConfig.theme_mode || 'light';
        let isDark = false;
        if (mode === 'dark') {
            isDark = true;
        } else if (mode === 'auto') {
            isDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
        }
        if (isDark) {
            root.classList.add('wf-dark');
        } else {
            root.classList.remove('wf-dark');
        }
    }

    if (window.matchMedia) {
        try {
            window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', updateThemeMode);
        } catch (e) {}
    }

    function playChime() {
        if (botConfig.sound_enabled === 0 || botConfig.sound_enabled === false) return;
        try {
            const AudioContext = window.AudioContext || window.webkitAudioContext;
            if (!AudioContext) return;
            const ctx = new AudioContext();
            const now = ctx.currentTime;
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.type = 'sine';
            osc.frequency.setValueAtTime(587.33, now); // D5
            osc.frequency.exponentialRampToValueAtTime(880, now + 0.12); // A5
            gain.gain.setValueAtTime(0.05, now);
            gain.gain.exponentialRampToValueAtTime(0.001, now + 0.3);
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.start(now);
            osc.stop(now + 0.32);
        } catch (e) {}
    }

    function attachCopyButton(bubbleEl, rawText) {
        if (!bubbleEl || !rawText) return;
        const copyBtn = document.createElement('button');
        copyBtn.type = 'button';
        copyBtn.className = 'wf-copy-btn';
        copyBtn.title = 'Copy';
        copyBtn.setAttribute('aria-label', 'Copy reply');
        const COPY_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>`;
        copyBtn.innerHTML = COPY_ICON;
        copyBtn.onclick = async (e) => {
            e.stopPropagation();
            try {
                const clean = rawText.replace(/<[^>]+>/g, '').replace(/(?:📸\s*)?!\[.*?\]\(.*?\)/g, '').trim();
                await navigator.clipboard.writeText(clean.replace(/\s?\[\d+\]/g, ''));
                copyBtn.classList.add('wf-copied');
                copyBtn.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>`;
                copyBtn.title = 'Copied';
                setTimeout(() => {
                    copyBtn.classList.remove('wf-copied');
                    copyBtn.innerHTML = COPY_ICON;
                    copyBtn.title = 'Copy';
                }, 1600);
            } catch (err) {}
        };
        bubbleEl.appendChild(copyBtn);
    }

    // Visitor rating on a bot reply; the team sees it in the dashboard, and 👎 flags the question as a knowledge gap.
    function attachFeedback(bubbleEl, messageId, current = 0) {
        if (!bubbleEl || !messageId || bubbleEl.querySelector('.wf-feedback')) return;
        const thumb = (down) => `
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"${down ? ' style="transform:rotate(180deg)"' : ''}>
                <path d="M7 10v12"/><path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88Z"/>
            </svg>`;
        const row = document.createElement('div');
        row.className = 'wf-feedback';
        row.innerHTML = `
            <button type="button" class="wf-feedback-btn" data-rating="1" aria-label="Helpful" title="Helpful">${thumb(false)}</button>
            <button type="button" class="wf-feedback-btn" data-rating="-1" aria-label="Not helpful" title="Not helpful">${thumb(true)}</button>
            <span class="wf-feedback-thanks" aria-live="polite"></span>
        `;
        let rating = current;
        const thanks = row.querySelector('.wf-feedback-thanks');
        const paint = () => row.querySelectorAll('.wf-feedback-btn').forEach(b => {
            b.setAttribute('aria-pressed', String(Number(b.dataset.rating) === rating));
        });
        paint();
        row.querySelectorAll('.wf-feedback-btn').forEach(btn => {
            btn.onclick = async (e) => {
                e.stopPropagation();
                const clicked = Number(btn.dataset.rating);
                const next = rating === clicked ? 0 : clicked; // clicking the active thumb clears it
                const previous = rating;
                rating = next;
                paint();
                thanks.textContent = next === 1 ? 'Thanks!' : (next === -1 ? "Thanks, we'll use this to improve." : '');
                try {
                    const res = await fetch(`${API_BASE}/api/conversations/${encodeURIComponent(conversationId)}/messages/${messageId}/feedback`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', 'X-Host-Domain': currentHost },
                        body: JSON.stringify({ rating: next })
                    });
                    if (!res.ok) throw new Error('Feedback ' + res.status);
                } catch (err) {
                    rating = previous;
                    paint();
                    thanks.textContent = '';
                }
            };
        });
        const citations = bubbleEl.querySelector('.wf-citations');
        if (citations) citations.insertAdjacentElement('afterend', row);
        else bubbleEl.appendChild(row);
        // One quiet action row: helpful, not helpful, copy.
        const copyBtn = bubbleEl.querySelector(':scope > .wf-copy-btn');
        if (copyBtn) row.insertBefore(copyBtn, thanks);
    }

    // Property / product cards under a reply: photo, price, key facts and one-tap next steps.
    const CARD_ICONS = {
        property: '<svg viewBox="0 0 24 24" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h14V9.5"/><path d="M10 21v-6h4v6"/></svg>',
        product: '<svg viewBox="0 0 24 24" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M6 7h12l-1 13H7L6 7Z"/><path d="M9 7a3 3 0 0 1 6 0"/></svg>',
    };

    function sendSuggested(text) {
        inputEl.value = text;
        submitQuery();
    }

    function renderCards(bubbleEl, cards) {
        if (!bubbleEl || !Array.isArray(cards) || !cards.length || bubbleEl.querySelector('.wf-cards')) return;
        const safeUrl = (u) => /^https?:\/\//i.test(u || '') ? u : '';
        const row = document.createElement('div');
        row.className = 'wf-cards';
        row.setAttribute('role', 'list');
        cards.slice(0, 6).forEach((c, i) => {
            const isProperty = c.kind === 'property';
            const card = document.createElement('div');
            card.className = 'wf-lcard';
            card.setAttribute('role', 'listitem');
            card.style.setProperty('--wf-i', String(i));

            const tag = isProperty ? (c.deal === 'rent' ? 'For rent' : (c.deal === 'sale' ? 'For sale' : 'Property')) : (c.category || c.brand || '');
            const freq = c.frequency ? ` <small>/ ${escapeHtml(c.frequency)}</small>` : '';
            const price = c.price && !/inquire/i.test(c.price) ? `<span class="wf-lcard-price">${escapeHtml(c.price.replace(/\s*\/\s*(month|year|day)\s*$/i, ''))}${freq}</span>` : '';
            const meta = isProperty ? (c.location || '') : (tag === c.brand ? '' : (c.brand || ''));

            const chips = [];
            if (isProperty) {
                if (c.bedrooms) chips.push(c.bedrooms === 'Studio' ? 'Studio' : `${c.bedrooms} bed`);
                if (c.bathrooms) chips.push(`${c.bathrooms} bath`);
                if (c.size) chips.push(c.size);
            } else if (c.availability) {
                const inStock = /instock|in stock|available/i.test(c.availability.replace(/\s/g, ''));
                const out = /out ?of ?stock|soldout|sold out/i.test(c.availability);
                chips.push({ text: out ? 'Out of stock' : (inStock ? 'In stock' : c.availability), cls: out ? 'wf-chip-warn' : (inStock ? 'wf-chip-ok' : '') });
            }
            if (c.within_budget === false) chips.push({ text: 'Over budget', cls: 'wf-chip-warn' });

            const url = safeUrl(c.url);
            const askText = isProperty ? `I'd like to book a viewing for "${c.name}"` : `Tell me more about "${c.name}"`;
            card.innerHTML = `
                <div class="wf-lcard-media">
                    <div class="wf-lcard-ph" aria-hidden="true">${CARD_ICONS[isProperty ? 'property' : 'product']}</div>
                    ${tag ? `<span class="wf-lcard-tag">${escapeHtml(tag)}</span>` : ''}
                    ${price}
                </div>
                <div class="wf-lcard-body">
                    <div class="wf-lcard-title">${escapeHtml(c.name || 'Listing')}</div>
                    ${meta ? `<div class="wf-lcard-meta">${escapeHtml(meta)}</div>` : ''}
                    ${chips.length ? `<div class="wf-lcard-chips">${chips.map(ch => typeof ch === 'string'
                        ? `<span class="wf-chip">${escapeHtml(ch)}</span>`
                        : `<span class="wf-chip ${ch.cls}">${escapeHtml(ch.text)}</span>`).join('')}</div>` : ''}
                    <div class="wf-lcard-actions">
                        ${url ? `<a class="wf-lcard-btn wf-lcard-btn-ghost" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">View</a>` : ''}
                        <button type="button" class="wf-lcard-btn wf-lcard-btn-primary">${isProperty ? 'Book viewing' : 'Ask about it'}</button>
                    </div>
                </div>`;

            const imgUrl = safeUrl(c.image);
            if (imgUrl) {
                const img = document.createElement('img');
                img.alt = '';
                img.loading = 'lazy';
                img.decoding = 'async';
                img.referrerPolicy = 'no-referrer';
                img.onload = () => { img.classList.add('wf-loaded'); const ph = card.querySelector('.wf-lcard-ph'); if (ph) ph.remove(); };
                img.onerror = () => img.remove();
                img.src = imgUrl;
                card.querySelector('.wf-lcard-media').prepend(img);
            }
            card.querySelector('.wf-lcard-btn-primary').onclick = (e) => { e.stopPropagation(); sendSuggested(askText); };
            row.appendChild(card);
        });
        // Drop the edge fade once the visitor scrolls to the last card.
        const updateFade = () => row.classList.toggle('wf-cards-end', row.scrollLeft + row.clientWidth >= row.scrollWidth - 4);
        row.addEventListener('scroll', updateFade, { passive: true });
        const anchor = bubbleEl.querySelector('.wf-citations') || bubbleEl.querySelector('.wf-feedback');
        if (anchor) anchor.insertAdjacentElement('beforebegin', row);
        else bubbleEl.appendChild(row);
        requestAnimationFrame(updateFade);
        bodyEl.scrollTop = bodyEl.scrollHeight;
    }

    function applyConfig() {
        updateThemeMode();

        const nameEl = $('wf-header-name');
        if (nameEl) nameEl.innerText = botConfig.name || "AI Assistant";

        const drawerTitle = $('wf-drawer-title');
        if (drawerTitle) drawerTitle.innerText = botConfig.lead_title || `Get in touch with ${botConfig.name || 'us'}`;

        const statusEl = $('wf-header-status');
        if (statusEl) statusEl.innerText = botConfig.widget_subtitle || "Online";

        // Avatar
        // Small avatar beside every bot message (emoji or image).
        const av = String(botConfig.bot_avatar || '⚡');
        if (/^(https?:|data:image)/i.test(av)) {
            root.style.setProperty('--wf-bot-avatar-img', `url("${av.replace(/["\\\n]/g, '')}")`);
            root.style.setProperty('--wf-bot-avatar-text', '""');
        } else {
            root.style.setProperty('--wf-bot-avatar-img', 'none');
            root.style.setProperty('--wf-bot-avatar-text', `"${Array.from(av).slice(0, 2).join('').replace(/["\\]/g, '')}"`);
        }
        const avatarBox = $('wf-avatar-box');
        if (avatarBox) {
            if (botConfig.bot_avatar && (botConfig.bot_avatar.startsWith('http') || botConfig.bot_avatar.startsWith('data:image'))) {
                avatarBox.innerHTML = `<img src="${escapeHtml(botConfig.bot_avatar)}" alt="" style="width:100% !important; height:100% !important; object-fit:cover !important; border-radius:50% !important; display:block !important;" />`;
            } else {
                avatarBox.innerText = botConfig.bot_avatar || "⚡";
            }
        }

        // Color Accents & Radius
        const primaryColor = botConfig.primary_color || "#0f172a";
        root.style.setProperty('--wf-primary', primaryColor);
        const rad = botConfig.border_radius || "22px";
        root.style.setProperty('--wf-radius', rad);
        if (win) win.style.borderRadius = rad;

        const headerEl = $('wf-header');
        if (headerEl) headerEl.style.backgroundColor = primaryColor;
        if (triggerBtn) triggerBtn.style.backgroundColor = primaryColor;
        root.classList.toggle('wf-light-primary', isLightColor(primaryColor));

        // Layout: edge offsets & panel width
        const clampPx = (v, d) => { const n = parseInt(v, 10); return `${isNaN(n) ? d : Math.max(0, Math.min(200, n))}px`; };
        root.style.setProperty('--wf-offset-x', clampPx(botConfig.offset_x, 24));
        root.style.setProperty('--wf-offset-y', clampPx(botConfig.offset_y, 24));
        const widths = { compact: '360px', standard: '395px', wide: '440px' };
        root.style.setProperty('--wf-width', widths[botConfig.widget_width] || widths.standard);

        // Typography
        const fontKey = botConfig.font_family || 'jakarta';
        if (fontKey === 'inherit') {
            try {
                root.style.setProperty('--wf-font', getComputedStyle(document.body).fontFamily || FONT_STACKS.jakarta.css);
            } catch (e) {}
        } else {
            const font = FONT_STACKS[fontKey] || FONT_STACKS.jakarta;
            root.style.setProperty('--wf-font', font.css);
            if (font.href && !document.querySelector(`link[data-wf-font="${fontKey}"]`)) {
                const link = document.createElement('link');
                link.rel = 'stylesheet';
                link.href = font.href;
                link.setAttribute('data-wf-font', fontKey);
                document.head.appendChild(link);
            }
        }

        // Launcher icon
        const launcherIconEl = $('wf-btn-icon');
        if (launcherIconEl && !isOpen) launcherIconEl.innerHTML = launcherIconHtml();

        // Visibility on small screens
        root.classList.toggle('wf-hide-mobile', botConfig.hide_on_mobile === 1 || botConfig.hide_on_mobile === true);

        // Custom CSS, scoped to the widget's shadow root. External @imports are stripped.
        let customStyle = shadow.querySelector ? shadow.querySelector('#wf-custom-css') : null;
        const css = String(botConfig.custom_css || '').slice(0, 8000).replace(/@import[^;]*;?/gi, '').replace(/<\/?style/gi, '');
        if (css.trim()) {
            if (!customStyle) {
                customStyle = document.createElement('style');
                customStyle.id = 'wf-custom-css';
                shadow.appendChild(customStyle);
            }
            customStyle.textContent = css;
        } else if (customStyle) {
            customStyle.remove();
        }

        // Launcher Button Style & Pulse
        const btnLabel = $('wf-btn-label');
        if (botConfig.launcher_style === 'pill') {
            triggerBtn.classList.add('wf-launcher-pill');
            if (btnLabel) {
                btnLabel.innerText = botConfig.launcher_text || "Chat with us";
                btnLabel.style.display = isOpen ? 'none' : 'inline';
            }
        } else {
            triggerBtn.classList.remove('wf-launcher-pill');
            if (btnLabel) btnLabel.style.display = 'none';
        }

        if (botConfig.launcher_pulse !== 0 && botConfig.launcher_pulse !== false) {
            triggerBtn.classList.add('wf-has-pulse');
        } else {
            triggerBtn.classList.remove('wf-has-pulse');
        }

        // Input Placeholder
        if (inputEl) {
            inputEl.placeholder = botConfig.input_placeholder || "Ask a question...";
        }

        // Header Sound Toggle
        const soundBtn = $('wf-sound-toggle-btn');
        if (soundBtn) {
            const updateSoundBtnState = () => {
                const on = botConfig.sound_enabled !== 0 && botConfig.sound_enabled !== false;
                soundBtn.title = on ? "Mute sounds" : "Turn sounds on";
                soundBtn.innerHTML = (on ? `
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
                        <path d="M15.54 8.46a5 5 0 0 1 0 7.07"/>
                    </svg>
                ` : `
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
                        <line x1="23" x2="15" y1="9" y2="15"/><line x1="15" x2="23" y1="9" y2="15"/>
                    </svg>
                `) + `<span>${on ? 'Mute sounds' : 'Turn sounds on'}</span>`;
            };
            updateSoundBtnState();
            soundBtn.onclick = () => {
                botConfig.sound_enabled = (botConfig.sound_enabled !== 0 && botConfig.sound_enabled !== false) ? 0 : 1;
                updateSoundBtnState();
                if (botConfig.sound_enabled) playChime();
            };
        }

        // WhatsApp Direct Quick-Connect in Header
        const waHeaderBtn = $('wf-whatsapp-header-btn');
        if (waHeaderBtn) {
            const waNum = botConfig.whatsapp_number || '';
            if (waNum) {
                const clean = waNum.replace(/[^0-9]/g, '');
                waHeaderBtn.style.display = 'inline-flex';
                waHeaderBtn.onclick = () => {
                    const msg = encodeURIComponent(`Hi ${botConfig.name || ''}, I have an inquiry.`);
                    window.open(`https://wa.me/${clean}?text=${msg}`, '_blank');
                };
            } else {
                waHeaderBtn.style.display = 'none';
            }
        }

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
        applyLocalization();
        initProactiveTriggers();
    }

    function applyLocalization() {
        const isArabicBrowser = (navigator.language && navigator.language.startsWith('ar')) ||
                                (navigator.languages && navigator.languages.some(l => l.startsWith('ar')));
        const hasArabicText = /[\u0600-\u06FF]/.test(botConfig.welcome_message || '') ||
                              /[\u0600-\u06FF]/.test(botConfig.name || '');

        if (isArabicBrowser || hasArabicText) {
            root.setAttribute('dir', 'rtl');
            root.classList.add('wf-rtl');
            if (inputEl) inputEl.setAttribute('dir', 'rtl');
        }
    }

    let exitIntentTriggered = false;
    let timeTriggerFired = false;

    function initProactiveTriggers() {
        // 1. Time-on-page trigger (configurable; 0 disables)
        const delaySec = botConfig.teaser_delay === undefined || botConfig.teaser_delay === null ? 12 : Number(botConfig.teaser_delay);
        if (delaySec > 0 && botConfig.teaser_message) setTimeout(() => {
            if (!isOpen && !timeTriggerFired && !sessionStorage.getItem(`wf_teaser_dismissed_${ASSISTANT_ID}`)) {
                timeTriggerFired = true;
                if (teaserBubble) {
                    teaserBubble.style.display = 'block';
                    triggerBtn.classList.add('wf-pulse-once');
                }
            }
        }, delaySec * 1000);

        // 2. Desktop Exit Intent trigger
        if (botConfig.exit_intent === 0 || botConfig.exit_intent === false) return;
        document.addEventListener('mouseleave', (e) => {
            if (e.clientY <= 10 && !isOpen && !exitIntentTriggered && !sessionStorage.getItem(`wf_teaser_dismissed_${ASSISTANT_ID}`)) {
                exitIntentTriggered = true;
                if (teaserBubble) {
                    const teaserText = $('wf-teaser-text');
                    if (teaserText && !botConfig.teaser_message) {
                        teaserText.innerText = "Have a quick question before you go?";
                    }
                    teaserBubble.style.display = 'block';
                    triggerBtn.classList.add('wf-pulse-once');
                }
            }
        });
    }

    // ---------------------------------------------------------------------------
    // Live conversation sync (operator replies, join/leave notes, history restore)
    // ---------------------------------------------------------------------------
    const LAST_ID_KEY = `wf_last_${ASSISTANT_ID}`;
    const STARTED_KEY = `wf_started_${ASSISTANT_ID}`;
    let lastMessageId = parseInt(sessionStorage.getItem(LAST_ID_KEY) || '0', 10) || 0;
    let conversationStarted = sessionStorage.getItem(STARTED_KEY) === '1';
    let unreadCount = 0;
    let syncInFlight = false;

    function setLastMessageId(id) {
        if (id && id > lastMessageId) {
            lastMessageId = id;
            sessionStorage.setItem(LAST_ID_KEY, String(id));
        }
    }

    function markConversationStarted() {
        if (!conversationStarted) {
            conversationStarted = true;
            sessionStorage.setItem(STARTED_KEY, '1');
        }
    }

    function updateUnreadBadge() {
        const badge = $('wf-unread-badge');
        if (!badge) return;
        if (unreadCount > 0 && !isOpen) {
            badge.textContent = unreadCount > 9 ? '9+' : String(unreadCount);
            badge.style.display = 'block';
        } else {
            badge.style.display = 'none';
        }
    }

    // If the visitor asked for a person while the team is online but nobody joins
    // within 2 minutes, offer to leave contact details instead of waiting.
    let liveStatus = 'bot';
    let humanWaitTimer = null;
    const HUMAN_WAIT_MS = 120000;
    function startHumanWaitTimer() {
        clearTimeout(humanWaitTimer);
        humanWaitTimer = setTimeout(() => {
            if (liveStatus === 'human') return;
            appendSystemNote("No one has picked up yet — leave your email and the team will get back to you.");
            if (botConfig.lead_capture_enabled !== 0 && botConfig.lead_capture_enabled !== false) renderInChatLeadCard();
        }, HUMAN_WAIT_MS);
    }
    function handleHumanRequestResult(data) {
        if (data && data.human_requested && data.operators_online) startHumanWaitTimer();
    }

    function applyLiveStatus(status, operatorName) {
        liveStatus = status || 'bot';
        if (liveStatus === 'human') clearTimeout(humanWaitTimer);
        const statusEl = $('wf-header-status');
        if (!statusEl) return;
        if (status === 'human') {
            statusEl.innerText = `${operatorName || 'Support team'} · Live`;
            statusEl.style.color = '#10b981';
        } else if (statusEl.innerText.endsWith('· Live')) {
            statusEl.innerText = botConfig.widget_subtitle || 'Online';
            statusEl.style.color = '';
        }
    }

    function appendOperatorMsg(text, operatorName, opts = {}) {
        const bubble = document.createElement('div');
        bubble.className = 'wf-bubble wf-bubble-bot wf-bubble-operator';
        bubble.innerHTML = `
            <div class="wf-operator-label"><span class="wf-operator-dot"></span>${escapeHtml(operatorName || 'Support team')}</div>
            <div>${formatMessageText(text)}</div>
        `;
        bodyEl.appendChild(bubble);
        bodyEl.scrollTop = bodyEl.scrollHeight;
        if (!opts.silent) playChime();
    }

    function appendSystemNote(text) {
        const note = document.createElement('div');
        note.className = 'wf-system-note';
        note.textContent = text;
        bodyEl.appendChild(note);
        bodyEl.scrollTop = bodyEl.scrollHeight;
    }

    async function fetchTranscript(afterId) {
        const qs = afterId ? `?after_id=${encodeURIComponent(afterId)}` : '';
        const res = await fetch(`${API_BASE}/api/conversations/${encodeURIComponent(conversationId)}/transcript${qs}`, {
            headers: { 'X-Host-Domain': currentHost }
        });
        if (!res.ok) return null;
        return res.json();
    }

    // Re-renders the conversation after a page navigation so nothing is lost.
    async function restoreConversation() {
        if (!conversationStarted) return;
        try {
            const data = await fetchTranscript(0);
            if (!data) return;
            const msgs = data.messages || [];
            if (msgs.length) {
                const popSec = $('wf-popular-section');
                if (popSec) popSec.style.display = 'none';
            }
            for (const m of msgs) {
                if (m.role === 'user') appendMsg('user', m.content);
                else if (m.role === 'assistant') appendMsg('bot', m.content, m.sources || [], { silent: true, messageId: m.id, feedback: m.feedback || 0, cards: m.cards || [] });
                else if (m.role === 'operator') appendOperatorMsg(m.content, data.operator_name, { silent: true });
                else if (m.role === 'system') appendSystemNote(m.content);
                setLastMessageId(m.id);
            }
            applyLiveStatus(data.status, data.operator_name);
        } catch (e) {}
    }

    // Picks up messages the visitor didn't send themselves: operator replies and
    // join/leave notes. The visitor's own messages and bot replies are already on screen.
    async function syncConversation() {
        if (!conversationStarted || syncInFlight) return;
        syncInFlight = true;
        try {
            const data = await fetchTranscript(lastMessageId);
            if (!data) return;
            for (const m of (data.messages || [])) {
                if (m.role === 'operator') {
                    appendOperatorMsg(m.content, data.operator_name);
                    if (!isOpen) {
                        unreadCount += 1;
                        const teaserText = $('wf-teaser-text');
                        if (teaserBubble && teaserText) {
                            teaserText.innerText = `${data.operator_name || 'Support'}: ${m.content.slice(0, 80)}${m.content.length > 80 ? '…' : ''}`;
                            teaserBubble.style.display = 'block';
                        }
                    }
                } else if (m.role === 'system') {
                    appendSystemNote(m.content);
                }
                setLastMessageId(m.id);
            }
            applyLiveStatus(data.status, data.operator_name);
            updateUnreadBadge();
        } catch (e) {
        } finally {
            syncInFlight = false;
        }
    }

    // Poll every 3s while the chat is open, every 12s while minimised.
    let syncTick = 0;
    setInterval(() => {
        syncTick += 1;
        if (isOpen || syncTick % 4 === 0) syncConversation();
    }, 3000);

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
                    <span class="wf-question-sparkle">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3z"/>
                        </svg>
                    </span>
                    <span class="wf-question-text">${escapeHtml(q)}</span>
                </div>
                <svg class="wf-question-arrow-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>
                </svg>
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
        triggerBtn.setAttribute('aria-expanded', String(isOpen));
        triggerBtn.setAttribute('aria-label', isOpen ? 'Close chat' : 'Open chat');
        const btnLabel = $('wf-btn-label');
        if (isOpen) {
            unreadCount = 0;
            updateUnreadBadge();
            syncConversation();
            win.classList.add('wf-open');
            root.classList.add('wf-is-open');
            if (btnLabel) btnLabel.style.display = 'none';
            if (window.innerWidth <= 640) {
                hostContainer.style.width = '100vw';
                hostContainer.style.height = '100vh';
                hostContainer.style.pointerEvents = 'auto';
            }
            if (teaserBubble) teaserBubble.style.display = 'none';
            const iconEl = $('wf-btn-icon');
            if (iconEl) {
                iconEl.innerHTML = `
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
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
            if (btnLabel && botConfig.launcher_style === 'pill') {
                btnLabel.style.display = 'inline';
            }
            const iconEl = $('wf-btn-icon');
            if (iconEl) iconEl.innerHTML = launcherIconHtml();
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

    bodyEl.addEventListener('click', (e) => {
        const more = e.target.closest && e.target.closest('.wf-src-more');
        if (!more) return;
        const row = more.closest('.wf-citations');
        row.classList.add('wf-src-expanded');
        more.remove();
    });

    // Header "more" menu
    const moreBtn = $('wf-more-btn');
    const menuEl = $('wf-menu');
    const setMenu = (open) => {
        menuEl.classList.toggle('wf-menu-open', open);
        moreBtn.setAttribute('aria-expanded', String(open));
    };
    moreBtn.addEventListener('click', (e) => { e.stopPropagation(); setMenu(!menuEl.classList.contains('wf-menu-open')); });
    menuEl.addEventListener('click', (e) => { if (e.target.closest('.wf-menu-item')) setMenu(false); });
    shadow.addEventListener('click', (e) => { if (!e.target.closest || !e.target.closest('.wf-menu-wrap')) setMenu(false); });
    // Clicks on the host page (outside the widget) close it too.
    document.addEventListener('click', (e) => { if (!hostContainer.contains(e.target)) setMenu(false); });
    shadow.addEventListener('keydown', (e) => { if (e.key === 'Escape') setMenu(false); });

    // Reset Chat action
    resetBtn.addEventListener('click', () => {
        leadCardShown = false;
        conversationId = newConversationId();
        sessionStorage.setItem(`wf_conv_${ASSISTANT_ID}`, conversationId);
        lastMessageId = 0;
        conversationStarted = false;
        sessionStorage.removeItem(LAST_ID_KEY);
        sessionStorage.removeItem(STARTED_KEY);
        applyLiveStatus('bot');

        const userBubbles = bodyEl.querySelectorAll('.wf-bubble, .wf-lead-card, .wf-system-note');
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
                headers: { 
                    'Content-Type': 'application/json',
                    'X-Host-Domain': currentHost
                },
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
            submitBtn.disabled = false;
            submitBtn.innerText = "Couldn't send. Try again →";
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
            resizeInput();
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
        resizeInput();

        // Hide popular questions once chat starts
        const popSec = $('wf-popular-section');
        if (popSec) popSec.style.display = 'none';

        appendMsg('user', query);
        markConversationStarted();

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

        let botBubble = null;
        let contentDiv = null;
        let accumulatedText = "";
        let finalData = null;

        try {
            // Attempt SSE Streaming for real-time typewriter experience
            const res = await fetch(`${API_BASE}/api/chat/stream`, {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/json',
                    'X-Host-Domain': currentHost,
                    'X-AW-Widget': '2'
                },
                body: JSON.stringify({
                    assistant_id: ASSISTANT_ID,
                    conversation_id: conversationId,
                    message: query
                })
            });

            if (!res.ok) throw new Error("Stream status " + res.status);

            const reader = res.body.getReader();
            const decoder = new TextDecoder('utf-8');
            let buffer = '';

            // Keep the typing dots up while the assistant looks things up; swap to a bubble on the first token.
            const ensureBubble = () => {
                if (botBubble) return;
                if (typingEl.parentNode) typingEl.remove();
                botBubble = document.createElement('div');
                botBubble.className = 'wf-bubble wf-bubble-bot';
                contentDiv = document.createElement('div');
                botBubble.appendChild(contentDiv);
                bodyEl.appendChild(botBubble);
            };

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop();

                for (const line of lines) {
                    const trimmed = line.trim();
                    if (!trimmed || !trimmed.startsWith('data:')) continue;
                    try {
                        const jsonPayload = JSON.parse(trimmed.substring(5).trim());
                        if (jsonPayload.type === 'token') {
                            ensureBubble();
                            accumulatedText += jsonPayload.token;
                            contentDiv.innerHTML = formatMessageText(accumulatedText) + '<span class="wf-cursor-beam"></span>';
                            followLatest();
                        } else if (jsonPayload.type === 'done') {
                            finalData = jsonPayload;
                        }
                    } catch (e) {}
                }
            }

            // A person has taken over: there's no bot reply, the operator answers live.
            if (finalData && finalData.operator_active && !accumulatedText.trim()) {
                if (typingEl.parentNode) typingEl.remove();
                if (botBubble) botBubble.remove();
                applyLiveStatus('human', finalData.operator_name);
                syncConversation();
                return;
            }

            // The server's final answer is authoritative (links checked, internal tags removed).
            if (finalData && typeof finalData.answer === 'string' && finalData.answer.trim()) {
                accumulatedText = finalData.answer;
            }
            if (!accumulatedText.trim()) {
                // The message already reached the server, so don't resend it through the fallback.
                accumulatedText = "Sorry, I lost my train of thought there. Could you send that again?";
            }
            ensureBubble();
            contentDiv.innerHTML = formatMessageText(accumulatedText);
            attachCopyButton(botBubble, accumulatedText);
            playChime();
            syncConversation();

            // Finalize with formatted citations & lead card
            if (finalData) {
                if (finalData.sources && finalData.sources.length > 0) {
                    botBubble.insertAdjacentHTML('beforeend', citationsHtml(finalData.sources));
                    decorateCitations(botBubble, finalData.sources);
                }
                announce(accumulatedText);
                if (finalData.message_id) attachFeedback(botBubble, finalData.message_id);
                if (finalData.cards && finalData.cards.length) renderCards(botBubble, finalData.cards);

                if (finalData.lead_prompted && botConfig.lead_capture_enabled) {
                    renderInChatLeadCard();
                }
                handleHumanRequestResult(finalData);
            }

        } catch (streamErr) {
            // Graceful fallback to standard /api/chat
            if (typingEl.parentNode) typingEl.remove();
            if (botBubble && botBubble.parentNode) botBubble.remove();

            try {
                const res = await fetch(`${API_BASE}/api/chat`, {
                    method: 'POST',
                    headers: { 
                        'Content-Type': 'application/json',
                        'X-Host-Domain': currentHost,
                        'X-AW-Widget': '2'
                    },
                    body: JSON.stringify({
                        assistant_id: ASSISTANT_ID,
                        conversation_id: conversationId,
                        message: query
                    })
                });
                const data = await res.json();
                if (data.operator_active && !(data.answer || '').trim()) {
                    applyLiveStatus('human', data.operator_name);
                    syncConversation();
                    return;
                }
                appendMsg('bot', data.answer, data.sources, { messageId: data.message_id, cards: data.cards || [] });
                if (data.lead_prompted && botConfig.lead_capture_enabled) {
                    renderInChatLeadCard();
                }
                handleHumanRequestResult(data);
            } catch (fallbackErr) {
                appendMsg('bot', "Sorry, I couldn't reach the server just now.");
                const errBubble = bodyEl.lastElementChild;
                errBubble.classList.add('wf-bubble-error');
                const retry = document.createElement('button');
                retry.type = 'button';
                retry.className = 'wf-retry-btn';
                retry.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/></svg><span>Try again</span>';
                retry.onclick = () => {
                    const userBubble = errBubble.previousElementSibling;
                    errBubble.remove();
                    if (userBubble && userBubble.classList.contains('wf-bubble-user')) userBubble.remove();
                    sendSuggested(query);
                };
                errBubble.appendChild(retry);
                announce("Sorry, I couldn't reach the server just now.");
            }
        }
    }

    function formatMessageText(text) {
        if (!text) return '';
        let escaped = escapeHtml(text);

        // Images: 📸 ![Alt](URL) or ![Alt](URL)
        escaped = escaped.replace(/(?:📸\s*)?!\[([^\]]*)\]\((https?:\/\/[^\s)]+)\)/g, '<div class="wf-card-media"><img src="$2" alt="$1" class="wf-card-img" loading="lazy" onerror="this.parentElement.style.display=\'none\';" /></div>');

        // Convert WhatsApp links with 🟢 to styled WhatsApp action buttons
        escaped = escaped.replace(/🟢\s*\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer" class="wf-action-btn wf-whatsapp-btn"><svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor" style="display:inline-block; vertical-align:middle; margin-right:2px;"><path d="M.057 24l1.687-6.163c-1.041-1.804-1.588-3.849-1.587-5.946.003-6.556 5.338-11.891 11.893-11.891 3.181.001 6.167 1.24 8.413 3.488 2.245 2.248 3.481 5.236 3.48 8.414-.003 6.557-5.338 11.892-11.893 11.892-1.99-.001-3.951-.5-5.688-1.448l-6.305 1.654zm6.597-3.807c1.676.995 3.276 1.591 5.392 1.592 5.448 0 9.886-4.434 9.889-9.885.002-5.462-4.415-9.89-9.881-9.892-5.452 0-9.887 4.434-9.889 9.884-.001 2.225.651 3.891 1.746 5.634l-.999 3.648 3.742-.981zm11.387-5.464c-.074-.124-.272-.198-.57-.347-.297-.149-1.758-.868-2.031-.967-.272-.099-.47-.149-.669.149-.198.297-.768.967-.941 1.165-.173.198-.347.223-.644.074-.297-.149-1.255-.462-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.297-.347.446-.521.151-.172.2-.296.3-.495.099-.198.05-.372-.025-.521-.075-.148-.669-1.611-.916-2.206-.242-.579-.487-.501-.669-.51l-.57-.01c-.198 0-.52.074-.792.372s-1.04 1.016-1.04 2.479 1.065 2.876 1.213 3.074c.149.198 2.095 3.2 5.076 4.487.709.306 1.263.489 1.694.626.712.226 1.36.194 1.872.118.571-.085 1.758-.719 2.006-1.413.248-.695.248-1.29.173-1.414z"/></svg><span>$1</span><span class="wf-action-arrow">↗</span></a>');

        // Convert links with 🔗 to styled action buttons
        escaped = escaped.replace(/🔗\s*\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer" class="wf-action-btn"><span>🔗</span><span>$1</span><span class="wf-action-arrow">↗</span></a>');
        // Standard markdown links
        escaped = escaped.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer" class="wf-link-inline">$1 ↗</a>');

        // Bold: **text**
        escaped = escaped.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
        // Italic: *text*
        escaped = escaped.replace(/\*(.+?)\*/g, '<em>$1</em>');
        // Inline Citations: [1], [2]
        escaped = escaped.replace(/\[(\d+)\]/g, '<span class="wf-citation-inline">[$1]</span>');
        
        // Lists (•, -, * and 1.) and headings
        const lines = escaped.split(/\n+/);
        let listTag = '';
        let formatted = '';
        const closeList = () => { if (listTag) { formatted += `</${listTag}>`; listTag = ''; } };
        for (let line of lines) {
            line = line.trim();
            const bullet = line.match(/^(?:•|-|\*)\s+(.*)$/);
            const numbered = line.match(/^\d{1,2}[.)]\s+(.*)$/);
            const heading = line.match(/^#{1,4}\s+(.*)$/);
            if (bullet || numbered) {
                const tag = bullet ? 'ul' : 'ol';
                if (listTag !== tag) { closeList(); formatted += `<${tag} class="wf-msg-list">`; listTag = tag; }
                formatted += `<li>${(bullet || numbered)[1]}</li>`;
            } else {
                closeList();
                if (heading) formatted += `<p class="wf-msg-p wf-msg-heading">${heading[1]}</p>`;
                else if (line) formatted += `<p class="wf-msg-p">${line}</p>`;
            }
        }
        closeList();
        return formatted || escaped;
    }

    // Sources under a reply: a quiet row with up to three chips and "+N more". Web pages open in a new
    // tab; FAQs and uploaded documents have no address, so they're plain labels (never links to "#").
    const SOURCE_ICONS = {
        link: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>',
        doc: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></svg>',
    };
    function cleanSourceTitle(title) {
        // "Services - Ecomalign" -> "Services": the site name repeats on every chip.
        const t = String(title || 'Source').trim();
        const parts = t.split(/\s+[-|–—]\s+/);
        return (parts.length > 1 && parts[0].length >= 3 ? parts[0] : t).slice(0, 80);
    }
    function citationsHtml(sources) {
        const seen = new Set();
        const unique = sources.filter(s => {
            const key = (/^https?:\/\//i.test(s.url || '') ? s.url : s.title || '').toLowerCase();
            if (seen.has(key)) return false;
            seen.add(key);
            return true;
        });
        const chip = (s, hidden) => {
            const isLink = /^https?:\/\//i.test(s.url || '');
            const inner = `<span class="wf-src-num">${escapeHtml(String(s.index))}</span>${isLink ? SOURCE_ICONS.link : SOURCE_ICONS.doc}<span class="wf-src-title">${escapeHtml(cleanSourceTitle(s.title))}</span>`;
            const tip = escapeHtml(`${s.title || 'Source'}${s.snippet ? ' — ' + s.snippet : ''}`);
            const cls = `wf-citation-pill${isLink ? '' : ' wf-citation-static'}${hidden ? ' wf-src-extra' : ''}`;
            return isLink
                ? `<a href="${escapeHtml(s.url)}" target="_blank" rel="noopener noreferrer" class="${cls}" title="${tip}">${inner}</a>`
                : `<span class="${cls}" title="${tip}">${inner}</span>`;
        };
        const shown = unique.slice(0, 3).map(s => chip(s, false)).join('');
        const extra = unique.slice(3).map(s => chip(s, true)).join('');
        const more = unique.length > 3 ? `<button type="button" class="wf-src-more" aria-expanded="false">+${unique.length - 3} more</button>` : '';
        return `<div class="wf-citations"><span class="wf-src-label">Sources</span>${shown}${extra}${more}</div>`;
    }
    // Inline [n] markers become small badges that name their source on hover.
    function decorateCitations(bubbleEl, sources) {
        const byIndex = {};
        sources.forEach(s => { byIndex[String(s.index)] = s; });
        bubbleEl.querySelectorAll('.wf-citation-inline').forEach(el => {
            const n = el.textContent.replace(/[\[\]]/g, '');
            const src = byIndex[n];
            el.textContent = n;
            if (src) el.title = src.title || 'Source';
        });
    }

    function appendMsg(role, text, sources = [], opts = {}) {
        const bubble = document.createElement('div');
        bubble.className = `wf-bubble ${role === 'user' ? 'wf-bubble-user' : 'wf-bubble-bot'}`;

        let html = role === 'user'
            ? `<div>${escapeHtml(text || '').replace(/\n/g, '<br>')}</div>`
            : `<div>${formatMessageText(text)}</div>`;

        if (sources && sources.length > 0) {
            html += citationsHtml(sources);
        }

        bubble.innerHTML = html;
        if (role !== 'user' && sources && sources.length) decorateCitations(bubble, sources);
        if (role !== 'user') {
            attachCopyButton(bubble, text);
            if (opts.messageId) attachFeedback(bubble, opts.messageId, opts.feedback || 0);
            if (opts.cards && opts.cards.length) renderCards(bubble, opts.cards);
            if (!opts.silent) playChime();
        }
        bodyEl.appendChild(bubble);
        bodyEl.scrollTop = bodyEl.scrollHeight;
    }

    // One contact card per conversation; it never stacks and disappears once sent or dismissed.
    let leadCardShown = false;
    const LEAD_DONE_KEY = `wf_lead_done_${ASSISTANT_ID}`;

    function renderInChatLeadCard() {
        if (leadCardShown || bodyEl.querySelector('.wf-lead-card')) return;
        try { if (sessionStorage.getItem(LEAD_DONE_KEY) === conversationId) return; } catch (e) {}
        leadCardShown = true;
        const fields = String(botConfig.lead_fields || 'name_email');
        const phoneRequired = fields.includes('phone');
        const card = document.createElement('form');
        card.className = 'wf-lead-card';
        card.noValidate = true;
        card.innerHTML = `
            <div class="wf-lead-head">
                <h4>${escapeHtml(botConfig.lead_title || 'Get in touch with our team')}</h4>
                <button type="button" class="wf-lead-dismiss" aria-label="Not now">Not now</button>
            </div>
            <p>Leave your details and someone from ${escapeHtml(String(botConfig.name || 'our team').replace(/\s+(ai\s+)?(assistant|chatbot|bot)$/i, '')) || 'the team'} will get back to you.</p>
            <input type="text" placeholder="Your name" class="wf-lead-input" name="name" autocomplete="name" maxlength="120" />
            <input type="email" placeholder="Email address" class="wf-lead-input" name="email" autocomplete="email" maxlength="254" required />
            <input type="tel" placeholder="${phoneRequired ? 'Phone number' : 'Phone number (optional)'}" class="wf-lead-input" name="phone" autocomplete="tel" maxlength="40" ${phoneRequired ? 'required' : ''} />
            <p class="wf-lead-error" role="alert"></p>
            <button type="submit" class="wf-lead-btn">Send my details</button>
        `;
        const errorEl = card.querySelector('.wf-lead-error');
        const showError = (msg, input) => {
            errorEl.textContent = msg;
            errorEl.style.display = msg ? 'block' : 'none';
            if (input) input.focus();
        };
        card.querySelector('.wf-lead-dismiss').onclick = () => {
            card.classList.add('wf-lead-leaving');
            setTimeout(() => card.remove(), 220);
        };
        card.onsubmit = async (e) => {
            e.preventDefault();
            const name = card.elements.name.value.trim();
            const email = card.elements.email.value.trim();
            const phone = card.elements.phone.value.trim();
            if (!/^[^@\s]+@[^@\s]+\.[^@\s]{2,}$/.test(email)) return showError('Please enter a valid email address.', card.elements.email);
            if (phoneRequired && phone.replace(/\D/g, '').length < 6) return showError('Please enter a phone number we can reach you on.', card.elements.phone);
            showError('');
            const btn = card.querySelector('.wf-lead-btn');
            btn.disabled = true;
            btn.textContent = 'Sending…';
            try {
                const res = await fetch(`${API_BASE}/api/leads`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-Host-Domain': currentHost },
                    body: JSON.stringify({ assistant_id: ASSISTANT_ID, conversation_id: conversationId, email, phone, name })
                });
                if (!res.ok) {
                    const data = await res.json().catch(() => ({}));
                    throw new Error(typeof data.detail === 'string' ? data.detail : 'Something went wrong. Please try again.');
                }
                try { sessionStorage.setItem(LEAD_DONE_KEY, conversationId); } catch (err) {}
                card.innerHTML = `<div class="wf-lead-success">
                    <span class="wf-lead-check" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg></span>
                    <span>Thanks${name ? ', ' + escapeHtml(name) : ''}! We've got your details and will be in touch soon.</span>
                </div>`;
            } catch (err) {
                btn.disabled = false;
                btn.textContent = 'Send my details';
                showError(err.message || 'Something went wrong. Please try again.');
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
