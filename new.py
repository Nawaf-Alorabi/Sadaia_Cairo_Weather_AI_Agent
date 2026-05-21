"""Cairo Weather AI Agent.

Fetches current weather from Open-Meteo, writes a short notification with
OpenRouter when configured, and sends it through email and/or Telegram.
"""

import argparse
import logging
import os
import smtplib
import sys
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import requests
from dotenv import load_dotenv


# ══════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════

DEFAULT_LATITUDE = 30.0444
DEFAULT_LONGITUDE = 31.2357
DEFAULT_LOCATION_NAME = "Cairo, Egypt"
DEFAULT_SMTP_HOST = "smtp.gmail.com"
DEFAULT_SMTP_PORT = 587
DEFAULT_OPENROUTER_MODEL = "openrouter/free"

AGENT_SYSTEM_PROMPT = """
You are a helpful weather assistant.
When given a temperature reading, write exactly ONE short friendly
message (2-3 sentences) suitable for both email and Telegram.
Be warm and natural. Add a practical tip if relevant.
Return only the message text — no preamble, no sign-off.
""".strip()

logger = logging.getLogger("weather-agent")


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got {value!r}") from exc


def configure_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )


# ══════════════════════════════════════════════════════════════
# STEP 1 — Get current temperature
# ══════════════════════════════════════════════════════════════


def get_current_temperature(latitude: float, longitude: float, location_name: str) -> float:
    """
    Calls Open-Meteo API (free, no key needed).
    Returns the current temperature as a float (°C).
    """
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={latitude}"
        f"&longitude={longitude}"
        "&current=temperature_2m"
    )

    logger.info("[Step 1] Fetching %s temperature...", location_name)
    response = requests.get(url, timeout=20)
    response.raise_for_status()

    temp = response.json()["current"]["temperature_2m"]
    logger.info("Temperature: %s°C", temp)
    return temp


# ══════════════════════════════════════════════════════════════
# STEP 2 — AI agent composes the message
# ══════════════════════════════════════════════════════════════


def fallback_message(temperature: float, location_name: str) -> str:
    return (
        f"Hello! Just a heads-up: it's currently {temperature}°C in {location_name}. "
        "Stay hydrated and dress comfortably for the weather."
    )


def run_ai_agent(temperature: float, location_name: str) -> str:
    """
    Sends the temperature to an AI model via OpenRouter.
    Falls back to a plain message if OpenRouter is not configured or unavailable.
    """
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        logger.warning("OPENROUTER_API_KEY is missing. Using fallback message.")
        return fallback_message(temperature, location_name)

    models = [
        item.strip()
        for item in os.getenv("OPENROUTER_MODELS", DEFAULT_OPENROUTER_MODEL).split(",")
        if item.strip()
    ]
    if not models:
        models = [DEFAULT_OPENROUTER_MODEL]

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": os.getenv("APP_URL", "https://github.com/your-app"),
        "X-Title": os.getenv("APP_NAME", "Cairo Weather Agent"),
    }

    user_message = (
        f"The current temperature in {location_name} is {temperature}°C. "
        f"Write a short friendly notification message I can send to my contacts."
    )

    logger.info("[Step 2] Asking AI agent to write a message...")

    for model in models:
        logger.info("Trying model: %s", model)

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": AGENT_SYSTEM_PROMPT},
                {"role": "user",   "content": user_message},
            ],
            "temperature": 0.7,
            "max_tokens": 200,
        }

        wait = 5

        for attempt in range(1, 3):
            try:
                resp = requests.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=30,
                )
            except requests.RequestException as exc:
                logger.warning("OpenRouter request failed for %s: %s", model, exc)
                break

            if resp.status_code == 200:
                try:
                    data = resp.json()
                except ValueError:
                    logger.warning("OpenRouter returned non-JSON response.")
                    break

                choices = data.get("choices") or []
                if not choices:
                    logger.warning("OpenRouter response had no choices.")
                    break

                message = choices[0].get("message") or {}
                content = message.get("content")
                if isinstance(content, str) and content.strip():
                    ai_message = content.strip()
                    logger.info("AI message created with %s", model)
                    return ai_message

                logger.warning("OpenRouter returned empty/non-text model output.")
                break

            elif resp.status_code == 429:
                if attempt < 2:
                    retry_after = resp.headers.get("Retry-After")
                    if retry_after and retry_after.isdigit():
                        wait = int(retry_after)
                    logger.warning("Rate limited. Waiting %ss before retry...", wait)
                    time.sleep(wait)
                    wait *= 2
                else:
                    logger.warning("Still rate limited. Trying next model.")

            else:
                logger.warning("OpenRouter returned HTTP %s: %s", resp.status_code, resp.text[:200])
                break

    logger.warning("All AI models unavailable. Using fallback message.")
    return fallback_message(temperature, location_name)


# ══════════════════════════════════════════════════════════════
# STEP 3 — Build final message (AI text + factual footer)
# ══════════════════════════════════════════════════════════════


def build_final_message(ai_text: str, temperature: float, location_name: str) -> str:
    """
    Adds a factual footer below the AI message so the
    recipient always sees the exact temperature number.
    """
    footer = f"\n\nLocation: {location_name} temperature: {temperature}°C (via Open-Meteo)"
    return ai_text + footer


# ══════════════════════════════════════════════════════════════
# STEP 4 — Send Email via Gmail SMTP
# ══════════════════════════════════════════════════════════════

def send_email(subject: str, body: str) -> bool:
    """
    Sends a plain-text email using Gmail SMTP + TLS.

    Reads from .env:
        SENDER_EMAIL       — your Gmail address
        EMAIL_APP_PASSWORD — Gmail App Password (16 chars)
                             Get one at: myaccount.google.com/apppasswords
                             (requires 2-Step Verification to be ON)
        RECEIVER_EMAIL     — destination address
    """
    sender   = os.getenv("SENDER_EMAIL")
    password = os.getenv("EMAIL_APP_PASSWORD")
    receiver = os.getenv("RECEIVER_EMAIL")

    # Validate all three are present
    missing = [n for n, v in [
        ("SENDER_EMAIL", sender),
        ("EMAIL_APP_PASSWORD", password),
        ("RECEIVER_EMAIL", receiver),
    ] if not v]
    if missing:
        raise EnvironmentError(
            f"Missing from .env: {', '.join(missing)}"
        )

    # Strip spaces — Gmail App Passwords are often copied with spaces
    password = password.replace(" ", "")
    smtp_host = os.getenv("SMTP_HOST", DEFAULT_SMTP_HOST)
    smtp_port = int(os.getenv("SMTP_PORT", str(DEFAULT_SMTP_PORT)))

    msg = MIMEMultipart()
    msg["From"]    = sender
    msg["To"]      = receiver
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    logger.info("[Step 4] Sending email...")
    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(sender, password)
            server.sendmail(sender, receiver, msg.as_string())
        logger.info("Email sent to %s", receiver)
        return True

    except smtplib.SMTPAuthenticationError:
        logger.error(
            "Gmail rejected the login. Create a Gmail App Password and set "
            "EMAIL_APP_PASSWORD without spaces."
        )
        return False
    except (OSError, smtplib.SMTPException) as exc:
        logger.error("Email send failed: %s", exc)
        return False


# ══════════════════════════════════════════════════════════════
# STEP 5 — Send Telegram message
# ══════════════════════════════════════════════════════════════


def send_telegram(message: str) -> bool:
    """
    Sends a Telegram message using the Telegram Bot API.

    Required .env values:
        TELEGRAM_BOT_TOKEN — token from BotFather
        TELEGRAM_CHAT_ID   — your chat ID or group/channel ID
    """
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    missing = [n for n, v in [
        ("TELEGRAM_BOT_TOKEN", bot_token),
        ("TELEGRAM_CHAT_ID", chat_id),
    ] if not v]
    if missing:
        raise EnvironmentError(
            f"Missing from .env: {', '.join(missing)}"
        )

    logger.info("[Step 5] Sending Telegram message...")
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": message,
                "disable_web_page_preview": True,
            },
            timeout=30,
        )
        response.raise_for_status()
        logger.info("Telegram message sent.")
        return True
    except requests.RequestException as exc:
        logger.error("Telegram send failed: %s", exc)
        return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send an AI-written weather notification.")
    parser.add_argument("--dry-run", action="store_true", help="Print the message without sending it.")
    parser.add_argument("--skip-email", action="store_true", help="Do not send email.")
    parser.add_argument("--skip-telegram", action="store_true", help="Do not send Telegram.")
    parser.add_argument("--verbose", action="store_true", help="Show debug logs.")
    return parser.parse_args()


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════


def main() -> int:
    load_dotenv()
    args = parse_args()
    configure_logging(args.verbose)

    location_name = os.getenv("LOCATION_NAME", DEFAULT_LOCATION_NAME)
    latitude = env_float("LATITUDE", DEFAULT_LATITUDE)
    longitude = env_float("LONGITUDE", DEFAULT_LONGITUDE)

    # Step 1 — temperature
    temperature = get_current_temperature(latitude, longitude, location_name)

    # Step 2 — AI writes the message
    ai_text = run_ai_agent(temperature, location_name)

    # Step 3 — attach factual footer
    final_message = build_final_message(ai_text, temperature, location_name)

    print(f"\n[Step 3] Final message:\n{'-' * 40}")
    print(final_message)
    print(f"{'-' * 40}\n")

    if args.dry_run or env_bool("DRY_RUN", default=False):
        logger.info("Dry run enabled. No messages were sent.")
        return 0

    sent_any = False

    if not args.skip_email and env_bool("ENABLE_EMAIL", default=True):
        sent_any = send_email(
            subject=os.getenv("EMAIL_SUBJECT", f"{location_name} Weather Update"),
            body=final_message,
        ) or sent_any
    else:
        logger.info("Email disabled.")

    if not args.skip_telegram and env_bool("ENABLE_TELEGRAM", default=True):
        sent_any = send_telegram(final_message) or sent_any
    else:
        logger.info("Telegram disabled.")

    if not sent_any:
        logger.error("No notification channel succeeded.")
        return 1

    logger.info("All done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
