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

    let conversationId = sessionStorage.getItem(`wf_conv_${ASSISTANT_ID}`) || (`wf_${ASSISTANT_ID}_${Math.random().toString(36).substring(2, 10)}`);
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
        input.wf-field {
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
        input.wf-field::placeholder { color: var(--wf-text-subtle, #94a3b8) !important; }

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
            input.wf-field {
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
                    <button type="button" class="wf-icon-btn" id="wf-sound-toggle-btn" title="Toggle audio chime">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
                            <path d="M15.54 8.46a5 5 0 0 1 0 7.07"/>
                            <path d="M19.07 4.93a10 10 0 0 1 0 14.14"/>
                        </svg>
                    </button>
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
            <div class="wf-footer" id="wf-footer">Powered by AnswerWeave</div>
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

    // Input activate state
    inputEl.addEventListener('input', () => {
        if (inputEl.value.trim().length > 0) {
            sendBtn.classList.add('wf-send-active');
        } else {
            sendBtn.classList.remove('wf-send-active');
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
        copyBtn.title = 'Copy response';
        copyBtn.innerHTML = `
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <rect width="14" height="14" x="8" y="8" rx="2" ry="2"/>
                <path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>
            </svg>
            <span>Copy</span>
        `;
        copyBtn.onclick = async (e) => {
            e.stopPropagation();
            try {
                const clean = rawText.replace(/<[^>]+>/g, '').replace(/(?:📸\s*)?!\[.*?\]\(.*?\)/g, '').trim();
                await navigator.clipboard.writeText(clean);
                copyBtn.innerHTML = `
                    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                        <polyline points="20 6 9 17 4 12"/>
                    </svg>
                    <span style="color:#10b981;">Copied!</span>
                `;
                setTimeout(() => {
                    copyBtn.innerHTML = `
                        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <rect width="14" height="14" x="8" y="8" rx="2" ry="2"/>
                            <path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>
                        </svg>
                        <span>Copy</span>
                    `;
                }, 1800);
            } catch (err) {}
        };
        bubbleEl.appendChild(copyBtn);
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
        const avatarBox = $('wf-avatar-box');
        if (avatarBox) {
            if (botConfig.bot_avatar && (botConfig.bot_avatar.startsWith('http') || botConfig.bot_avatar.startsWith('data:image'))) {
                avatarBox.innerHTML = `<img src="${botConfig.bot_avatar}" alt="Avatar" style="width:100% !important; height:100% !important; object-fit:cover !important; border-radius:50% !important; display:block !important;" />`;
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
                soundBtn.title = on ? "Mute audio chime" : "Unmute audio chime";
                soundBtn.innerHTML = on ? `
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
                        <path d="M15.54 8.46a5 5 0 0 1 0 7.07"/>
                        <path d="M19.07 4.93a10 10 0 0 1 0 14.14"/>
                    </svg>
                ` : `
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
                        <line x1="23" x2="1" y1="1" y2="23"/>
                    </svg>
                `;
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
            const waNum = botConfig.whatsapp_number || (botConfig.name && botConfig.name.toLowerCase().includes('ideal homes') ? '+971505594888' : '');
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

    // Live Operator Polling
    let knownMessageCount = 0;
    async function checkOperatorMessages() {
        if (!isOpen) return;
        try {
            const res = await fetch(`${API_BASE}/api/conversations/${conversationId}/transcript`, {
                headers: { 'X-Host-Domain': currentHost }
            });
            if (!res.ok) return;
            const data = await res.json();
            const msgs = data.messages || [];

            // Update operator live badge
            const statusEl = $('wf-header-status');
            if (data.status === 'human') {
                if (statusEl) {
                    statusEl.innerText = `${data.operator_name || 'Agent'} (Live)`;
                    statusEl.style.color = '#10b981';
                }
            } else if (statusEl && statusEl.innerText.includes('(Live)')) {
                statusEl.innerText = botConfig.widget_subtitle || 'Online';
                statusEl.style.color = '';
            }

            // Sync new operator messages into the chat
            if (knownMessageCount > 0 && msgs.length > knownMessageCount) {
                const newMsgs = msgs.slice(knownMessageCount);
                for (const m of newMsgs) {
                    if (m.role === 'assistant') {
                        const existing = Array.from(bodyEl.querySelectorAll('.wf-bubble-assistant'));
                        const alreadyThere = existing.some(b => b.innerText.trim() === m.content.trim());
                        if (!alreadyThere) {
                            renderMessage('assistant', m.content, m.sources || []);
                            playChime();
                        }
                    }
                }
            }
            knownMessageCount = msgs.length;
        } catch (e) {}
    }

    setInterval(() => {
        if (isOpen) {
            checkOperatorMessages();
        }
    }, 4000);

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
        const btnLabel = $('wf-btn-label');
        if (isOpen) {
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
                    'X-Host-Domain': currentHost
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

            typingEl.remove();

            // Create streaming bot bubble
            botBubble = document.createElement('div');
            botBubble.className = 'wf-bubble wf-bubble-bot';
            contentDiv = document.createElement('div');
            botBubble.appendChild(contentDiv);
            bodyEl.appendChild(botBubble);

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
                            accumulatedText += jsonPayload.token;
                            contentDiv.innerHTML = formatMessageText(accumulatedText) + '<span class="wf-cursor-beam"></span>';
                            bodyEl.scrollTop = bodyEl.scrollHeight;
                        } else if (jsonPayload.type === 'done') {
                            finalData = jsonPayload;
                        }
                    } catch (e) {}
                }
            }

            contentDiv.innerHTML = formatMessageText(accumulatedText);
            attachCopyButton(botBubble, accumulatedText);
            playChime();

            // Finalize with formatted citations & lead card
            if (finalData) {
                if (finalData.sources && finalData.sources.length > 0) {
                    let citeHtml = `<div class="wf-citations">`;
                    finalData.sources.forEach(s => {
                        citeHtml += `
                            <a href="${s.url}" target="_blank" class="wf-citation-pill" title="${escapeHtml(s.snippet || '')}">
                                <span>📚</span>
                                <span>[${s.index}] ${escapeHtml(s.title || 'Source')} ↗</span>
                            </a>
                        `;
                    });
                    citeHtml += `</div>`;
                    botBubble.insertAdjacentHTML('beforeend', citeHtml);
                }

                if (finalData.lead_prompted && botConfig.lead_capture_enabled) {
                    renderInChatLeadCard();
                }
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
                        'X-Host-Domain': currentHost
                    },
                    body: JSON.stringify({
                        assistant_id: ASSISTANT_ID,
                        conversation_id: conversationId,
                        message: query
                    })
                });
                const data = await res.json();
                appendMsg('bot', data.answer, data.sources);
                if (data.lead_prompted && botConfig.lead_capture_enabled) {
                    renderInChatLeadCard();
                }
            } catch (fallbackErr) {
                appendMsg('bot', "I apologize, but I am having trouble connecting to the service right now. Please try again in a moment.");
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
        if (role !== 'user') {
            attachCopyButton(bubble, text);
            playChime();
        }
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
                    headers: { 
                        'Content-Type': 'application/json',
                        'X-Host-Domain': currentHost
                    },
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
