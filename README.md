# Co-Chat

Co-Chat is a simple browser-tab hub for running multiple web AI chats from one command surface without provider APIs. It uses Playwright persistent sessions, keeps provider login state in `sessions/`, polls for new replies, and lets you relay messages between providers with loop limits.

## What it does

- Opens ChatGPT, Claude, Grok, DeepSeek, Codex, or any future provider you add
- Uses one persistent Chromium profile per provider instead of official APIs
- Sends messages from one CLI or optional Telegram control surface
- Mirrors new assistant replies back into one place
- Supports controlled AI-to-AI routing with max-round loop protection
- Logs activity to `logs/chat.jsonl`

## Project tree

```text
co-chat/
├── .gitignore
├── README.md
├── main.py
├── requirements.txt
├── router.py
├── browser/
│   ├── __init__.py
│   ├── controller.py
│   └── registry.py
├── config/
│   ├── __init__.py
│   ├── config.py
│   └── selectors.py
├── core/
│   ├── __init__.py
│   ├── logger.py
│   ├── message.py
│   └── state.py
├── interfaces/
│   ├── __init__.py
│   ├── cli.py
│   └── telegram_control.py
├── logs/
└── sessions/
```

## Setup on WSL2 Ubuntu

1. Install Python and base tools:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
```

2. Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

3. Install Python dependencies:

```bash
pip install -r requirements.txt
```

4. Install Playwright Chromium and Linux browser dependencies:

```bash
python -m playwright install --with-deps chromium
```

## Running

Start in headful mode:

```bash
python main.py
```

Optional environment overrides:

```bash
export CO_CHAT_HEADLESS=false
export CO_CHAT_ENABLE_TELEGRAM=false
export CO_CHAT_POLL_INTERVAL=1.0
export CO_CHAT_MAX_AUTO_ROUNDS=3
export CO_CHAT_PROVIDERS=gpt,claude,grok,deepseek,codex
python main.py
```

The first run opens a persistent browser profile stored in `sessions/`. Log in manually to each provider once. Later runs reuse that login state from the same profile directory.

Provider profile layout:

```text
sessions/
├── claude/
├── codex/
├── deepseek/
├── gpt/
└── grok/
```

## CLI commands

```text
gpt <text>
claude <text>
grok <text>
deepseek <text>
codex <text>
all <text>
compare <prompt>
status
probe
routes
relay <source> <target>
stoproute <source> <target>
quit
```

Examples:

```text
gpt summarize this repo
all compare this idea
compare compare these tradeoffs
relay gpt claude
deepseek summarize this discussion
codex outline a fix plan for this bug
stoproute gpt claude
routes
status
probe
```

## Telegram control

Telegram is optional. The project runs fully without it.

To enable it:

```bash
export CO_CHAT_ENABLE_TELEGRAM=true
export CO_CHAT_BOT_TOKEN=your_bot_token
export CO_CHAT_CHAT_ID=123456789
python main.py
```

If `CO_CHAT_CHAT_ID=0`, the bot accepts the first chat that sends a message and mirrors replies there. Set a real chat id if you want the control path locked down.

Recommended Telegram setup:

1. Create a bot with `@BotFather`
2. Copy the bot token into `CO_CHAT_BOT_TOKEN`
3. Start Co-Chat with `CO_CHAT_ENABLE_TELEGRAM=true`
4. Send `/help` to your bot from Telegram
5. If you want to lock access to one chat, capture that numeric chat id and set `CO_CHAT_CHAT_ID`

Telegram accepts the same core commands as CLI. Useful slash forms:

```text
/help
/status
/probe
/routes
/relay gpt deepseek
/stoproute gpt deepseek
```

## Codex local provider

`codex` in Co-Chat is a local provider backed by the installed Codex CLI, not a browser tab.

- It creates its own separate Codex thread under `sessions/codex/thread_id.txt`
- It does not attach to this live Codex desktop conversation unless you explicitly build that bridge later
- The first `codex <text>` creates a fresh Codex session for Co-Chat
- Later `codex <text>` calls resume the same Co-Chat-owned Codex thread

If you want to disable it:

```bash
export CO_CHAT_PROVIDERS=gpt,claude,grok,deepseek
```

## WSL login/browser reliability

Co-Chat now prefers real Chrome for persistent login flows in this order:

1. `channel="chrome"` when Playwright can use the installed Chrome channel
2. Windows Chrome from WSL at `/mnt/c/Program Files/Google/Chrome/Application/chrome.exe`
3. Playwright default Chromium only as a last fallback

Important WSL note:

- `channel="chrome"` expects a Chrome install inside WSL, typically at `/opt/google/chrome/chrome`
- If that channel is missing, Co-Chat tries the Windows `chrome.exe` path next
- Some WSL setups still reject Playwright control of the Windows binary through the remote debugging pipe
- If both real-Chrome attempts fail, Co-Chat falls back to Playwright Chromium and logs that fallback

The browser launch also uses login-friendlier args:

- `--disable-blink-features=AutomationControlled`
- `--disable-infobars`
- `--no-sandbox`
- `--disable-dev-shm-usage`
- `--start-maximized`

If a login gets stuck because a persistent profile is corrupted, stop Co-Chat and reset the saved browser state manually:

```bash
rm -rf sessions/
mkdir -p sessions/gpt sessions/claude sessions/grok
```

That is optional and manual only. Co-Chat does not delete sessions automatically.

## Refreshing selectors with Playwright codegen

These sites change their DOM often. Expect selector drift.

Use Playwright codegen to refresh a provider:

```bash
python -m playwright codegen https://chatgpt.com/
python -m playwright codegen https://claude.ai/chats
python -m playwright codegen https://grok.com/
python -m playwright codegen https://chat.deepseek.com/
```

Then update the matching block in `config/selectors.py`:

- `input`: text box or contenteditable input
- `send_btn`: clickable send button
- `last_assistant`: selector that resolves to the latest assistant reply node
- `streaming_indicator`: selector that is visible only while the provider is still generating

If you do not have a reliable `streaming_indicator`, set it to `None`. Co-Chat will fall back to stricter unchanged-poll detection before emitting a reply.

DeepSeek note:

- `chat.deepseek.com` returned a CloudFront `403` during anonymous headless inspection in this environment
- Co-Chat now includes a selector block validated against a logged-in DeepSeek session, but you should still refresh it if DeepSeek changes its DOM
- If DeepSeek opens but does not send or mirror replies, run `probe`, then refresh only the `deepseek` block in `config/selectors.py`

After editing selectors, rerun:

```bash
python main.py
```

## Session persistence

- Login state, cookies, local storage, and most session data live in `sessions/`
- `sessions/` is ignored by Git
- The persistent profile survives restarts of Co-Chat
- Co-Chat closes the browser on shutdown; persistence is about login state, not leaving Chromium running forever

## Logs

Every user send, assistant reply, route action, and error is appended to:

```text
logs/chat.jsonl
```

Each line includes:

- `timestamp`
- `source`
- `target`
- `content`
- `kind`
- `status`

`status` in the CLI now also shows:

- ready or not ready
- current page URL
- last assistant message timestamp
- last error
- selector health

## First-run notes for WSL2

- Headful browser mode requires a working GUI path from WSL2 into Windows
- WSLg usually works out of the box on current Windows 11 builds
- If login pages keep looping or stalling, install a Chrome build inside WSL for `channel="chrome"` support, then refresh `sessions/` manually if needed
- Keep `CO_CHAT_HEADLESS=false` while tuning selectors so you can see what the browser is doing

## Known limitations

- Web chat UIs change often, so selectors are the main maintenance point
- Some sites stream partial responses; Co-Chat now waits for a stable final reply and uses `streaming_indicator` when available
- Sending with Enter may not work for every provider, so keep `send_btn` selectors current
- DeepSeek is included, but its selectors are more likely to need refresh after login than GPT or Grok
- This is a single-user laptop tool, not a multi-user server
- No conversation history sync beyond what the provider site already stores in the browser

## Simple extension path

To add another provider:

1. Add its name to `CO_CHAT_PROVIDERS` or `ENABLED_PROVIDERS`
2. Add its URL to `config/selectors.py`
3. Add its selector block to `config/selectors.py`
4. Restart Co-Chat
