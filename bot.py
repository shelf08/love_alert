from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib import error, parse, request
from zoneinfo import ZoneInfo


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/{method}"
TELEGRAM_MESSAGE_LIMIT = 4096
OPENROUTER_ATTEMPTS = 3


def load_dotenv(path: str = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


@dataclass(frozen=True)
class Config:
    telegram_bot_token: str
    telegram_chat_id: str
    openrouter_api_key: str
    openrouter_model: str
    timezone: ZoneInfo
    start_hour: int
    end_hour: int
    send_on_start: bool
    recipient_names: tuple[str, ...]

    @classmethod
    def from_env(cls) -> "Config":
        load_dotenv()

        return cls(
            telegram_bot_token=required_env("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=required_env("TELEGRAM_CHAT_ID"),
            openrouter_api_key=required_env("OPENROUTER_API_KEY"),
            openrouter_model=os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini"),
            timezone=ZoneInfo(os.getenv("TIMEZONE", "Europe/Moscow")),
            start_hour=int(os.getenv("SEND_START_HOUR", "8")),
            end_hour=int(os.getenv("SEND_END_HOUR", "22")),
            send_on_start=os.getenv("SEND_ON_START", "false").lower() == "true",
            recipient_names=tuple(
                name.strip()
                for name in os.getenv("RECIPIENT_NAMES", "Даша, Дашуля, Дарья, Данечка").split(",")
                if name.strip()
            ),
        )


class BotError(RuntimeError):
    pass


def post_json(url: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            **(headers or {}),
        },
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=45) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise BotError(f"HTTP {exc.code} from {url}: {details}") from exc
    except error.URLError as exc:
        raise BotError(f"Network error while calling {url}: {exc.reason}") from exc


def normalize_openrouter_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts).strip()

    return ""


def generate_message(config: Config) -> str:
    now = datetime.now(config.timezone)
    last_response: dict[str, Any] | None = None

    for attempt in range(1, OPENROUTER_ATTEMPTS + 1):
        response = post_json(
            OPENROUTER_URL,
            {
                "model": config.openrouter_model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Ты пишешь очень милые, нежные и немного слащавые сообщения для Telegram. "
                            "Тон: заботливый, влюбленный, теплый, без иронии и без канцелярита. "
                            "Добавляй сердечки естественно, чтобы сообщение выглядело ласковым."
                        ),
                    },
                    {"role": "user", "content": build_prompt(now, config)},
                ],
                "temperature": 0.9,
                "max_tokens": 260,
            },
            headers={
                "Authorization": f"Bearer {config.openrouter_api_key}",
                "X-OpenRouter-Title": "Love Alert Telegram Bot",
            },
        )
        last_response = response

        try:
            content = normalize_openrouter_content(response["choices"][0]["message"].get("content"))
        except (KeyError, IndexError, TypeError, AttributeError) as exc:
            raise BotError(f"Unexpected OpenRouter response: {response}") from exc

        if content:
            return content[:TELEGRAM_MESSAGE_LIMIT]

        print(f"OpenRouter returned empty content, retry {attempt}/{OPENROUTER_ATTEMPTS}", flush=True)
        time.sleep(2)

    raise BotError(f"OpenRouter returned empty content after retries: {last_response}")


def build_prompt(now: datetime, config: Config) -> str:
    names = ", ".join(config.recipient_names)

    if now.hour == 8:
        topic = (
            "Утреннее сообщение: пожелай доброго утра и мягко пожелай хорошего дня. "
            "Можно добавить, что она любимая, красивая, самая нежная и что я рядом мысленно."
        )
    elif 9 <= now.hour <= 17:
        topic = (
            "Дневное сообщение: пожелай удачи в работе, легких задач, спокойствия и сил. "
            "Можно добавить маленькое признание в любви или напоминание, что я ею горжусь."
        )
    elif 18 <= now.hour <= 21:
        topic = (
            "Вечернее сообщение: пожелай хорошего отдыха, выдохнуть после дня, вкусного ужина "
            "или уютного вечера. Можно добавить очень нежное признание в любви."
        )
    elif now.hour == 22:
        topic = (
            "Ночное сообщение: пожелай спокойной ночи, сладких снов и мягко скажи, что она очень любима."
        )
    else:
        topic = (
            "Нейтральное милое сообщение: скажи что-то нежное, заботливое и влюбленное."
        )

    return (
        f"Сейчас {now:%H:%M}. Адресат: девушка, к ней можно обращаться так: {names}. "
        f"{topic} "
        "Напиши на русском языке от мужского лица. "
        "Выбери только одно обращение из списка и используй его естественно. "
        "Сделай сообщение очень милым, ласковым и сладким, но живым. "
        "Объем: 4-6 коротких предложений. "
        "Добавь 1-3 сердечка, например ❤️, 💕 или 💖. "
        "Не используй хэштеги, списки, кавычки, подписи, другие эмодзи и markdown."
    )


def send_telegram_message(config: Config, text: str) -> None:
    url = TELEGRAM_API_URL.format(
        token=parse.quote(config.telegram_bot_token, safe=":"),
        method="sendMessage",
    )
    response = post_json(
        url,
        {
            "chat_id": config.telegram_chat_id,
            "text": text,
            "disable_web_page_preview": True,
        },
    )

    if not response.get("ok"):
        raise BotError(f"Telegram rejected message: {response}")


def is_sending_hour(now: datetime, config: Config) -> bool:
    return config.start_hour <= now.hour <= config.end_hour


def next_send_time(now: datetime, config: Config) -> datetime:
    today_start = now.replace(hour=config.start_hour, minute=0, second=0, microsecond=0)
    today_end = now.replace(hour=config.end_hour, minute=0, second=0, microsecond=0)

    if now < today_start:
        return today_start

    if now <= today_end:
        next_hour = (now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))
        if next_hour <= today_end:
            return next_hour

    return today_start + timedelta(days=1)


def create_and_send(config: Config) -> None:
    text = generate_message(config)
    send_telegram_message(config, text)
    sent_at = datetime.now(config.timezone).isoformat(timespec="seconds")
    print(f"[{sent_at}] sent message ({len(text)} chars)", flush=True)


def run() -> None:
    config = Config.from_env()
    print(
        "Love Alert bot started. "
        f"Window: {config.start_hour:02d}:00-{config.end_hour:02d}:00 "
        f"({config.timezone.key}). Model: {config.openrouter_model}",
        flush=True,
    )

    if config.send_on_start and is_sending_hour(datetime.now(config.timezone), config):
        try:
            create_and_send(config)
        except BotError as exc:
            print(f"Startup send failed: {exc}", flush=True)

    while True:
        now = datetime.now(config.timezone)
        target = next_send_time(now, config)
        sleep_seconds = max(1, (target - now).total_seconds())
        print(f"Next message at {target.isoformat(timespec='seconds')}", flush=True)
        time.sleep(sleep_seconds)

        try:
            create_and_send(config)
        except BotError as exc:
            print(f"Send failed: {exc}", flush=True)
            time.sleep(60)


if __name__ == "__main__":
    run()
