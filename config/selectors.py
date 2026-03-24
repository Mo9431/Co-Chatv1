from __future__ import annotations

# Update these with `playwright codegen <url>` after logging into each site.
# Expect selector drift. When one provider changes its DOM, update only that block.
# `streaming_indicator` is optional. If you can identify a reliable "generating"
# element for a provider, add it to reduce partial reply reads even further.

URLS = {
    "gpt": "https://chatgpt.com/",
    "claude": "https://claude.ai/chats",
    "grok": "https://grok.com/",
}

SELECTORS = {
    "gpt": {
        "ready": "textarea, div[contenteditable='true']",
        "input": "textarea, div[contenteditable='true']",
        "send_button": "button[data-testid='send-button'], button[aria-label*='Send']",
        "assistant_messages": "[data-message-author-role='assistant']",
        "streaming_indicator": "",
    },
    "claude": {
        "ready": "textarea, div[contenteditable='true']",
        "input": "textarea, div[contenteditable='true']",
        "send_button": "button[aria-label*='Send'], button:has-text('Send')",
        "assistant_messages": "[data-test-render-count] .font-claude-message, div[data-is-streaming='false']",
        "streaming_indicator": "",
    },
    "grok": {
        "ready": "textarea, div[contenteditable='true']",
        "input": "textarea, div[contenteditable='true']",
        "send_button": "button[aria-label*='Send'], button[type='submit']",
        "assistant_messages": "article, div[data-testid*='message']",
        "streaming_indicator": "",
    },
}
