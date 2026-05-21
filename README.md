# Cairo Weather AI Agent

A simple Python project that:

1. Gets the current temperature in Cairo using Open-Meteo.
2. Uses AI to write a short weather message, if an OpenRouter key is provided.
3. Sends the message by email and/or Telegram.

Telegram is the easiest free replacement for WhatsApp/Twilio.

## Files

```text
new.py              Main Python app
requirements.txt    Python packages
.env.example        Example environment variables
.gitignore          Keeps secrets and temporary files out of Git
.github/workflows/  GitHub Actions deployment
```

## Local Setup

Create a virtual environment:

```bash
python -m venv .venv
```

Activate it on Windows:

```bash
.venv\Scripts\activate
```

Install packages:

```bash
pip install -r requirements.txt
```

Create your environment file:

```bash
copy .env.example .env
```

Then edit `.env` and fill these values:

```text
SENDER_EMAIL=your-gmail@gmail.com
EMAIL_APP_PASSWORD=your-gmail-app-password
RECEIVER_EMAIL=receiver@gmail.com
```

Test without sending anything:

```bash
python new.py --dry-run
```

Send the message:

```bash
python new.py
```

## Deployment

This project is best deployed with GitHub Actions because it is a scheduled script, not a website.

Steps:

1. Upload the project to GitHub.
2. Go to `Settings > Secrets and variables > Actions`.
3. Add these secrets:

```text
SENDER_EMAIL
EMAIL_APP_PASSWORD
RECEIVER_EMAIL
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
```

4. Add these variables:

```text
ENABLE_EMAIL=true
ENABLE_TELEGRAM=true
LOCATION_NAME=Cairo, Egypt
LATITUDE=30.0444
LONGITUDE=31.2357
EMAIL_SUBJECT=Cairo Weather Update
```

5. Go to `Actions > Weather Agent > Run workflow`.

The workflow runs once per day.

## Optional AI

If you want the message to be AI-generated, add this GitHub secret and the same value in your local `.env`:

```text
OPENROUTER_API_KEY
```

Without it, the app still works using a normal fallback message.

## Telegram Setup

1. Open Telegram and search for `BotFather`.
2. Send `/newbot`.
3. Copy the bot token into `TELEGRAM_BOT_TOKEN`.
4. Send any message to your new bot.
5. Open this URL in your browser, replacing `<TOKEN>`:

```text
https://api.telegram.org/bot<TOKEN>/getUpdates
```

6. Find `"chat":{"id":...}` and copy that number into `TELEGRAM_CHAT_ID`.

## Important Notes

- Do not upload `.env` to GitHub.
- Gmail needs an App Password, not your normal password.
- Telegram is easier than WhatsApp for this kind of project.
