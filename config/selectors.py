from __future__ import annotations

# Update these with `playwright codegen <url>` after logging into each site.
# Expect selector drift. When one provider changes its DOM, update only that block.
# `streaming_indicator` can be `None` when you do not have a reliable selector yet.
# In that case Co-Chat falls back to stricter stability polling before emit.

URLS = {
    "gpt": "https://chatgpt.com/",
    "claude": "https://claude.ai/chats",
    "grok": "https://grok.com/",
    "deepseek": "https://chat.deepseek.com/",
}

SELECTORS = {
    "gpt": {
        "input": "#prompt-textarea, textarea, div[contenteditable='true']",
        "send_btn": "button[data-testid='send-button'], button[aria-label*='Send']",
        "last_assistant": "[data-message-author-role='assistant']",
        "streaming_indicator": "button[data-testid='stop-button']",
    },
    "claude": {
        "input": "textarea, div[contenteditable='true']",
        "send_btn": "button[aria-label*='Send'], button:has-text('Send')",
        "last_assistant": "[data-test-render-count] .font-claude-message:last-child, div[data-is-streaming='false']:last-child",
        "streaming_indicator": None,
    },
    "grok": {
        "input": "textarea, div[contenteditable='true']",
        "send_btn": "button[aria-label*='Send'], button[type='submit']",
        "last_assistant": "main div.message-bubble.max-w-none",
        "streaming_indicator": None,
    },
    "deepseek": {
        # Validated against a logged-in DeepSeek session on 2026-03-24.
        "input": "textarea",
        "send_btn": "button[type='submit'], button[aria-label*='Send']",
        "last_assistant": "div.ds-markdown",
        "streaming_indicator": None,
    },
}
