# Telegram

Connects **zerai6Bot** to this project. The cron job uses this package to:

- announce a scan start
- collect the Zerodha app code
- send the finished zone summary and zone details as chat messages

Chart scanning and Kite browser automation stay in `crone-job/`. `live_indicator/` is unchanged.

## Files

| File | Purpose |
|---|---|
| `client.py` | Send a message and read incoming updates |
| `env_file.py` | Read and update the project-root `.env` without dropping other keys |
| `setup.py` | Save the bot token, learn your chat id, send a test message |
| `notify.py` | Scan-start, login status, and scan-complete chat messages |
| `app_code.py` | Wait for a 6-digit app code from the trusted chat |
| `tests/` | Unit tests (no network) |

## Secrets

The bot token and your chat id live only in the project-root `.env` file:

```
TELEGRAM_BOT_TOKEN=123456:your-token
TELEGRAM_CHAT_ID=123456789
```

`.env` is gitignored. Do not paste the token into source files.

## One-time setup

From the project root:

```
python -m pip install -r telegram/requirements.txt
python telegram/setup.py
```

If `.env` has no token yet, the script asks for it (the typing is hidden) and stores it. Then send `/start` to the bot on your phone while the script waits. On success it prints the chat it saved and sends:

```
Project Broker Model: Telegram connected.
```

## Check the connection again later

```
python -c "import sys; sys.path.insert(0, '.'); from telegram.client import send_message; send_message('Project Broker Model: Telegram still connected.')"
```

Run that from the project root after setup has saved `TELEGRAM_CHAT_ID`.
