# Telegram

Connects **zerai6Bot** to this project on your Windows PC.

- Announce scan start / collect Zerodha app code / send zone results  
- Always-on commands: `/scan`, `/status`, `/help`  
- Nightly 9:00 PM via Windows Task Scheduler  

Chart scanning stays in `crone-job/`. `live_indicator/` is unchanged.

## Files

| File | Purpose |
|---|---|
| `setup.py` | One-time bot token + chat id binding |
| `bot.py` | Always-on command listener (`/scan`, `/status`, `/help`) |
| `nightly.py` | Entry point for the 9:00 PM scheduled task |
| `install_nightly_task.ps1` | Registers that scheduled task once |
| `scan_control.py` | Shared lock + start/status for bot and nightly |
| `scan_worker.py` | Detached child that runs `run_nifty100.py` with a log file |
| `client.py` / `notify.py` / `app_code.py` | Messaging and TOTP wait |
| `app_code_bridge.py` | Hands app codes from the bot to the scanner if both overlap |
| `format_zones.py` | Readable HTML zone messages |

## Secrets

Project-root `.env` (gitignored):

```
TELEGRAM_BOT_TOKEN=123456:your-token
TELEGRAM_CHAT_ID=123456789
```

`.env` must never be committed. Do not put the bot token or Kite passwords in
`app.json` or any project JSON file. Zerodha passwords stay in Windows
Credential Manager via `crone-job` (not in `.env`).

## One-time setup

```
python -m pip install -r telegram/requirements.txt
python telegram/setup.py
```

## Daily use

### 1. Keep the command bot running

From the project root (leave this terminal open, or add it to Windows Startup):

```
python telegram/bot.py
```

On your phone:

- `/scan` — full NIFTY 100 scan  
- `/scan 3` — short test (first 3 symbols)  
- `/status` — is a scan running?  
- `/help` — command list  

While a scan runs, the bot pauses command polling so app-code replies reach the scanner.

### 2. Install the nightly 9:00 PM task (once)

In PowerShell from the project root:

```
powershell -ExecutionPolicy Bypass -File telegram\install_nightly_task.ps1
```

That registers `ProjectBrokerModelNightlyScan` for daily 9:00 PM local time.

Check:

```
schtasks /Query /TN ProjectBrokerModelNightlyScan /V /FO LIST
```

Remove:

```
schtasks /Delete /TN ProjectBrokerModelNightlyScan /F
```

### 3. PC checklist for unattended nights

- PC on (or awake) at 9:00 PM  
- Internet working  
- Brave debug profile able to open Kite (logged in if possible)  
- Telegram bot optional for nightly start, but useful for `/scan` and TOTP replies  

## Logs

Scan child logs are written under `telegram/logs/` (gitignored).
