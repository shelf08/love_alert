from __future__ import annotations

import json
import os
import random
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
INVALID_MESSAGE_PREFIXES = (
    "user safety:",
    "assistant safety:",
    "safety:",
    "safe",
    "unsafe",
)
HEARTS = ("❤️", "💕", "💖", "💗", "💘", "💞")
DEFAULT_RECIPIENT_NAMES = ("Даша", "Дашуля", "Дарья", "Данечка")
LOCAL_SHORT_MESSAGES = (
    "{name}, я тебя люблю {heart}",
    "{name}, ты мое самое нежное счастье {heart}",
    "{name}, просто обнимаю тебя мысленно {heart}",
    "{name}, ты у меня самая любимая {heart}",
    "{name}, пусть у тебя сейчас станет чуть теплее на душе {heart}",
    "{name}, я рядом мыслями и очень тебя люблю {heart}",
    "{name}, ты моя нежность {heart}",
    "{heart}",
    "{heart}{heart}",
)
MESSAGE_SHAPES = (
    "одно очень короткое сообщение в 1 предложение",
    "2 коротких предложения, почти как быстрый поцелуй в переписке",
    "3 предложения: нежность, маленькое пожелание, признание",
    "4-5 коротких предложений без длинных оборотов",
    "одно сообщение в стиле тихой записки",
    "сообщение как внезапное признание посреди дня",
)
STYLE_DIRECTIONS = (
    "очень простыми словами, без литературности",
    "чуть игриво и очень ласково",
    "тихо, бережно и спокойно",
    "сладко, почти приторно, но не шаблонно",
    "как будто я только что подумал о ней и сразу написал",
    "с ощущением теплых объятий",
    "с маленькой бытовой деталью, но не про ужин каждый раз",
)
FORBIDDEN_CLICHES = (
    "выдохни",
    "дневная суета",
    "оставь заботы позади",
    "пусть ужин будет вкусным",
    "уютный вечер",
    "я всегда рядом, даже если не могу обнять",
)


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


def parse_recipient_names() -> tuple[str, ...]:
    raw_names = os.getenv("RECIPIENT_NAMES", ", ".join(DEFAULT_RECIPIENT_NAMES))
    names = tuple(name.strip() for name in raw_names.split(",") if name.strip())
    return names or DEFAULT_RECIPIENT_NAMES


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
    local_message_chance: float
    heart_only_chance: float

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
            recipient_names=parse_recipient_names(),
            local_message_chance=float(os.getenv("LOCAL_MESSAGE_CHANCE", "0.25")),
            heart_only_chance=float(os.getenv("HEART_ONLY_CHANCE", "0.08")),
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


def is_invalid_generated_message(text: str) -> bool:
    normalized = text.strip().lower()
    if not normalized:
        return True

    return any(normalized.startswith(prefix) for prefix in INVALID_MESSAGE_PREFIXES)


def generate_message(config: Config) -> str:
    now = datetime.now(config.timezone)
    last_response: dict[str, Any] | None = None

    if can_use_local_message(now) and random.random() < config.heart_only_chance:
        return random.choice((random.choice(HEARTS), random.choice(HEARTS) * 2))

    if can_use_local_message(now) and random.random() < config.local_message_chance:
        return build_local_message(config)

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

        if content and not is_invalid_generated_message(content):
            return content[:TELEGRAM_MESSAGE_LIMIT]

        print(f"OpenRouter returned unusable content, retry {attempt}/{OPENROUTER_ATTEMPTS}", flush=True)
        time.sleep(2)

    raise BotError(f"OpenRouter returned unusable content after retries: {last_response}")


def can_use_local_message(now: datetime) -> bool:
    return now.hour not in (8, 22)


def build_local_message(config: Config) -> str:
    name = random.choice(config.recipient_names)
    heart = random.choice(HEARTS)
    template = random.choice(LOCAL_SHORT_MESSAGES)
    return template.format(name=name, heart=heart)


def period_topics(hour: int) -> tuple[str, ...]:
    if hour == 8:
        return (
            "доброе утро, мягкое начало дня, ощущение что она самая любимая",
            "утренний лучик, нежное пожелание сил и легкости",
            "короткое сонное признание и пожелание хорошего дня",
            "пожелание проснуться спокойно и почувствовать себя любимой",
            "ласковое утро без пафоса, как сообщение сразу после пробуждения",
        )

    if 9 <= hour <= 17:
        return (
            "удачи в работе, спокойных задач и маленьких побед",
            "поддержка в середине рабочего дня и признание, что я ею горжусь",
            "короткое напоминание, что она умничка и у нее все получится",
            "пожелание легких звонков, понятных задач и добрых людей рядом",
            "нежное сообщение без конкретного повода, просто потому что я люблю",
            "маленькая пауза с любовью посреди рабочего дня",
        )

    if 18 <= hour <= 21:
        return (
            "вечернее тепло после дня, без обязательного упоминания ужина",
            "пожелание мягкого отдыха и приятных мелочей",
            "признание в любви вечером, будто я очень соскучился",
            "ласковое сообщение про то, что она заслужила спокойствие и заботу",
            "теплая мысль о ней, без советов и без повторяющихся фраз",
            "что-то сладкое и влюбленное, будто хочется прижать ее к себе",
        )

    if hour == 22:
        return (
            "спокойной ночи, сладких снов и нежное признание",
            "короткое ночное сообщение, как поцелуй перед сном",
            "пожелание уснуть спокойно и почувствовать себя любимой",
            "очень мягкое сообщение перед сном, без длинных объяснений",
            "сонное признание в любви и пара сердечек",
        )

    return (
        "внезапные милые слова",
        "короткое признание в любви",
        "нежное сообщение без повода",
    )


def build_prompt(now: datetime, config: Config) -> str:
    names = ", ".join(config.recipient_names)
    topic = random.choice(period_topics(now.hour))
    shape = random.choice(MESSAGE_SHAPES)
    style = random.choice(STYLE_DIRECTIONS)
    hearts_count = random.choice(("0", "1", "1-2", "2-3"))
    forbidden = ", ".join(random.sample(FORBIDDEN_CLICHES, k=3))

    return (
        f"Сейчас {now:%H:%M}. Адресат: девушка, к ней можно обращаться так: {names}. "
        f"Тема: {topic}. "
        f"Форма: {shape}. "
        f"Стиль: {style}. "
        "Напиши на русском языке от мужского лица. "
        "Выбери только одно обращение из списка или вообще не используй обращение, если так звучит естественнее. "
        "Сообщение должно быть цельным, теплым и понятным, не набором красивых слов. "
        f"Сердечки: {hearts_count}, только из вариантов ❤️, 💕, 💖, 💗, 💘, 💞. "
        f"Сегодня избегай этих фраз и близких к ним шаблонов: {forbidden}. "
        "Не повторяй структуру типичного пожелания из пяти предложений. "
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
