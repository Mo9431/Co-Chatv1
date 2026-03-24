# Co-Chat

Co-Chat is a simple browser-tab hub for running multiple web AI chats from one command surface without provider APIs. It uses Playwright persistent sessions, keeps provider login state in `sessions/`, polls for new replies, and lets you relay messages between providers with loop limits.

## What it does

- Opens ChatGPT, Claude, Grok, or any future provider you add
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
export CO_CHAT_PROVIDERS=gpt,claude,grok
python main.py
```

The first run opens Chromium with a persistent profile stored in `sessions/`. Log in manually to each provider once. Later runs reuse that login state from the same profile directory.

Provider profile layout:

```text
sessions/
├── claude/
├── gpt/
└── grok/
```

## CLI commands

```text
gpt <text>
claude <text>
grok <text>
all <text>
compare <prompt>
status
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
stoproute gpt claude
routes
status
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

## Selector updates

These sites change their DOM often. Expect selector drift.

Use Playwright codegen to refresh a provider:

```bash
python -m playwright codegen https://chatgpt.com/
python -m playwright codegen https://claude.ai/chats
python -m playwright codegen https://grok.com/
```

Then update the matching block in `config/selectors.py`:

- `ready`: element that proves the page is usable
- `input`: text box or contenteditable input
- `send_button`: clickable send button if Enter alone is unreliable
- `assistant_messages`: selector that matches assistant reply containers

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
- If Chromium fails to open a window, verify your WSL GUI support before debugging Co-Chat itself
- Keep `CO_CHAT_HEADLESS=false` while tuning selectors so you can see what the browser is doing

## Known limitations

- Web chat UIs change often, so selectors are the main maintenance point
- Some sites stream partial responses; Co-Chat currently captures the latest stable visible message text
- Sending with Enter may not work for every provider, so use `send_button` selectors when needed
- This is a single-user laptop tool, not a multi-user server
- No conversation history sync beyond what the provider site already stores in the browser

## Simple extension path

To add another provider:

1. Add its name to `CO_CHAT_PROVIDERS` or `ENABLED_PROVIDERS`
2. Add its URL to `config/selectors.py`
3. Add its selector block to `config/selectors.py`
4. Restart Co-Chat
