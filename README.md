# Love Alert Telegram Bot

Простой бот, который каждый час генерирует милое сообщение через OpenRouter и отправляет его в Telegram-чат с 08:00 до 22:00.

Логика сообщений:

- `08:00` - доброе утро и пожелание хорошего дня.
- `09:00-17:00` - удачи в работе, легких задач и теплые слова.
- `18:00-21:00` - хорошего отдыха, уютного вечера или признание в любви.
- `22:00` - спокойной ночи и сладких снов.

## Настройка

1. Создай бота через `@BotFather` и получи `TELEGRAM_BOT_TOKEN`.
2. Добавь бота в нужный чат.
3. Узнай `TELEGRAM_CHAT_ID`.
   - Для личного чата можно написать боту любое сообщение и открыть:
     `https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/getUpdates`
   - Для группы добавь бота в группу, напиши сообщение в группу и проверь тот же `getUpdates`.
4. Скопируй `.env.example` в `.env` и заполни значения.

## Запуск локально

```bash
python bot.py
```

Бот использует только стандартную библиотеку Python, дополнительные пакеты не нужны.

## Запуск на VPS

На сервере нужен Python 3.11+.

```bash
git clone https://github.com/shelf08/love_alert.git
cd love_alert
cp .env.example .env
nano .env
python3 bot.py
```

Чтобы бот жил после закрытия SSH, удобнее запустить его через `systemd`.

Можно взять шаблон из `deploy/love-alert.service.example`:

```bash
sudo cp deploy/love-alert.service.example /etc/systemd/system/love-alert.service
sudo nano /etc/systemd/system/love-alert.service
```

Если проект лежит не в `/opt/love_alert`, поменяй `WorkingDirectory` и `ExecStart`.

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now love-alert
sudo systemctl status love-alert
```

## Переменные окружения

- `TELEGRAM_BOT_TOKEN` - токен Telegram-бота.
- `TELEGRAM_CHAT_ID` - id чата, куда отправлять сообщения.
- `OPENROUTER_API_KEY` - ключ OpenRouter.
- `OPENROUTER_MODEL` - модель OpenRouter, по умолчанию `openai/gpt-4o-mini`.
- `TIMEZONE` - часовой пояс, по умолчанию `Europe/Moscow`.
- `SEND_START_HOUR` - первый час отправки, по умолчанию `8`.
- `SEND_END_HOUR` - последний час отправки, по умолчанию `22`.
- `SEND_ON_START` - отправить сразу при запуске, если сейчас разрешенное время.
- `RECIPIENT_NAMES` - варианты обращения, по умолчанию `Даша, Дашуля, Дарья, Данечка`.

На немецком VPS системный часовой пояс может отличаться. Бот ориентируется на `TIMEZONE` из `.env`, поэтому оставь `Europe/Moscow`, если сообщения должны приходить по московскому времени, или поставь `Europe/Berlin`, если по немецкому.
