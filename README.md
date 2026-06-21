# Telegram-бот для анализа товаров на маркетплейсах

[English version](#engG)

Этот проект - Telegram-бот для примерной оценки товара перед продажей на маркетплейсах. Бот помогает быстро понять рынок: какие цены у конкурентов, есть ли спрос, какой может быть прогноз цены на месяц и какая минимальная цена нужна, чтобы не работать в убыток.

Бот рассчитан на учебный и демонстрационный сценарий, но пытается работать с реальными данными там, где маркетплейс их отдает.

## Что умеет бот

- Работает с Ozon, Wildberries и Yandex Market.
- Принимает название товара или ссылку на товар.
- Пытается собрать реальные данные с маркетплейса.
- Если реальные данные получить не удалось, использует примерные данные и предупреждает об этом пользователя.
- Не показывает пользователю технические ошибки вроде `403`, `Client error`, `captcha`.
- Делит найденные товары на категории.
- Строит историю цены за 6 месяцев.
- Делает прогноз цены на 30 дней.
- Показывает возможный коридор цены, то есть примерный диапазон будущей цены.
- Считает расходы, прибыль, окупаемость и минимальную цену без убытка.
- Отправляет PNG-график прогноза.
- После анализа продолжает диалог: пользователь может сразу ввести следующий товар без `/start`.

## Как работает сценарий

### Если пользователь вводит название товара

1. Пользователь нажимает `/start`.
2. Выбирает маркетплейс.
3. Вводит название товара, например `фонарь`.
4. Бот собирает данные и предлагает категории.
5. Пользователь выбирает категорию.
6. Пользователь вводит расходы на 1 товар.
7. Бот отправляет анализ и график.
8. Можно сразу ввести следующий товар.

Пример ввода расходов:

```text
500 80 30 120 0
```

Порядок чисел:

```text
закупка логистика упаковка реклама прочее
```

Если отправить `0`, бот оценит расходы автоматически.

### Если пользователь вводит ссылку

Если пользователь отправляет ссылку на товар, бот работает быстрее:

1. Сам определяет маркетплейс по ссылке.
2. Пытается открыть именно эту ссылку.
3. Сам выбирает подходящую категорию товара.
4. Сам примерно считает расходы.
5. Сразу отправляет анализ и график.

Это удобно, когда нужно быстро проверить конкретный товар.

## Реальные и примерные данные

Бот всегда сначала пытается получить реальные данные.

Если маркетплейс не отдал данные, бот использует примерные данные и пишет:

```text
Внимание: реальные данные не получились, поэтому это примерная оценка рынка.
```

Причину ошибки бот пользователю не показывает. Это сделано специально, чтобы диалог был понятным и без технического мусора.

Примерные данные не являются полностью случайными. Они строятся с опорой на тип товара: для фонаря, телефона, наушников, ноутбука, инструмента и других товаров используются разные реалистичные диапазоны цен, отзывов и рейтинга.

## Что показывает анализ

В ответе бот показывает несколько понятных блоков:

- `Коротко` - итоговая оценка товара и решение.
- `Рынок сейчас` - средняя цена, диапазон цен, отзывы и рейтинг.
- `Прогноз на месяц` - куда может пойти цена.
- `Деньги` - расходы, прибыль, минимальная цена без убытка.
- `На что смотреть` - главные риски.
- `Что сделать` - практические советы.

## Файлы проекта

```text
bot.py                         основной Telegram-бот
cli_demo.py                    консольная версия без Telegram
marketplace_bot/marketplace.py сбор данных и примерные данные
marketplace_bot/analysis.py    анализ, прогноз, график
marketplace_bot/storage.py     сохранение данных в SQLite
.env                           настройки и токен бота
requirements.txt               зависимости проекта
README.md                      гайд по проекту
```

## Установка

Открой PowerShell в папке проекта:

```powershell
cd "path\to\marketplace-telegram-bot"
```

Создай виртуальное окружение, если его еще нет:

```powershell
py -m venv .venv
```

Установи зависимости:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Если команда `python` не работает и Windows пишет, что Python не найден, запускай проект через:

```powershell
.\.venv\Scripts\python.exe
```

## Настройка `.env`

В файле `.env` должен быть токен Telegram-бота:

```env
TELEGRAM_BOT_TOKEN=ваш_токен_бота
```

Дополнительные настройки:

```env
MARKETPLACE_DEMO_ONLY=1
```

Эта настройка принудительно включает примерные данные. Ее можно использовать для проверки бота без ожидания ответа маркетплейсов.

```env
MARKETPLACE_BROWSER_VISIBLE=1
MARKETPLACE_BROWSER_WAIT=8
```

Эти настройки включают видимое окно браузера для Selenium-парсинга. Обычно они не нужны для обычного запуска.

## Запуск Telegram-бота

```powershell
.\.venv\Scripts\python.exe bot.py
```

После запуска в консоли должно появиться:

```text
Bot started
```

Дальше открой Telegram, найди своего бота и напиши `/start`.

## Запуск консольной версии

Если нужно проверить логику без Telegram:

```powershell
.\.venv\Scripts\python.exe cli_demo.py
```

Консольная версия работает как черновик: выбираешь маркетплейс, вводишь товар, категорию и расходы. Excel-отчет не создается.

## Частые проблемы

### Python was not found

Запускай не через `python bot.py`, а так:

```powershell
.\.venv\Scripts\python.exe bot.py
```

### Бот не отвечает

Проверь:

- запущен ли `bot.py`;
- правильно ли указан токен в `.env`;
- нет ли второго запущенного процесса этого же бота;
- есть ли интернет.

### Маркетплейс не отдает реальные данные

Это нормально. Маркетплейсы могут менять страницы, ограничивать частые запросы или показывать защиту. В этом случае бот использует примерные данные и предупреждает пользователя.

## Важное замечание

Бот не гарантирует точный финансовый результат. Он помогает быстро оценить ситуацию на рынке и принять предварительное решение. Перед реальной закупкой товара лучше дополнительно проверить цены, отзывы, комиссии, логистику и спрос вручную.

>**Автор проекта: Зейналов У.Р.о.**

---

<h1 id = engG>Marketplace Product Profitability Telegram Bot</h1>

This project is a Telegram bot for quick product analysis before selling on marketplaces. The bot helps estimate the market situation: competitor prices, demand signals, monthly price forecast, expenses, profit, and the minimum price needed to avoid losses.

The project is designed mainly for educational and demonstration purposes, but it still tries to collect real marketplace data whenever possible.

## Features

- Supports Ozon, Wildberries, and Yandex Market.
- Accepts a product name or a product link.
- Tries to collect real marketplace data first.
- If real data is unavailable, uses approximate data and warns the user.
- Does not show technical errors such as `403`, `Client error`, or `captcha` to the user.
- Groups similar products into categories.
- Builds a 6-month price history.
- Forecasts the price for the next 30 days.
- Shows an approximate future price range.
- Calculates expenses, profit, ROI, and break-even price.
- Sends a PNG forecast chart.
- Continues the dialog after analysis, so the user can enter the next product without sending `/start` again.

## Bot Flow

### Product Name Flow

1. The user sends `/start`.
2. The user selects a marketplace.
3. The user enters a product name, for example `flashlight`.
4. The bot collects data and suggests product categories.
5. The user selects a category.
6. The user enters expenses per item.
7. The bot sends the analysis and chart.
8. The user can immediately enter the next product.

Expense input example:

```text
500 80 30 120 0
```

Input order:

```text
purchase logistics packaging ads other
```

If the user sends `0`, the bot estimates expenses automatically.

### Product Link Flow

If the user sends a product link, the bot uses a faster flow:

1. Detects the marketplace from the link.
2. Tries to open the exact product link.
3. Selects the most suitable category automatically.
4. Estimates expenses automatically.
5. Sends the analysis and chart immediately.

This is useful for quickly checking a specific product.

## Real and Approximate Data

The bot always tries to collect real data first.

If the marketplace does not provide the data, the bot uses approximate data and shows this warning:

```text
Внимание: реальные данные не получились, поэтому это примерная оценка рынка.
```

The bot does not show the technical reason to the user. This keeps the dialog simple and readable.

Approximate data is not purely random. It is based on product type: flashlights, phones, headphones, laptops, tools, clothes, cosmetics, and other product groups use different realistic price, review, and rating ranges.

## Analysis Output

The bot response is divided into readable blocks:

- `Коротко` - product score and short decision.
- `Рынок сейчас` - current market price, price range, reviews, and rating.
- `Прогноз на месяц` - expected monthly price direction.
- `Деньги` - expenses, profit, and break-even price.
- `На что смотреть` - key risks.
- `Что сделать` - practical suggestions.

## Project Files

```text
bot.py                         main Telegram bot
cli_demo.py                    console demo without Telegram
marketplace_bot/marketplace.py data collection and approximate fallback data
marketplace_bot/analysis.py    analysis, forecast, chart generation
marketplace_bot/storage.py     SQLite storage
.env                           settings and bot token
requirements.txt               project dependencies
README.md                      project guide
```

## Installation

Open PowerShell in the project folder:

```powershell
cd "path\to\marketplace-telegram-bot"
```

Create a virtual environment if it does not exist yet:

```powershell
py -m venv .venv
```

Install dependencies:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

If the `python` command does not work and Windows says Python was not found, run the project through:

```powershell
.\.venv\Scripts\python.exe
```

## `.env` Setup

The `.env` file must contain the Telegram bot token:

```env
TELEGRAM_BOT_TOKEN=your_bot_token
```

Optional settings:

```env
MARKETPLACE_DEMO_ONLY=1
```

This forces approximate data mode. It is useful for testing the bot without waiting for marketplace responses.

```env
MARKETPLACE_BROWSER_VISIBLE=1
MARKETPLACE_BROWSER_WAIT=8
```

These settings enable a visible browser window for Selenium parsing. They are usually not needed for normal use.

## Run the Telegram Bot

```powershell
.\.venv\Scripts\python.exe bot.py
```

After startup, the console should show:

```text
Bot started
```

Then open Telegram, find your bot, and send `/start`.

## Run the Console Demo

To test the logic without Telegram:

```powershell
.\.venv\Scripts\python.exe cli_demo.py
```

The console version works as a draft interface: select a marketplace, enter a product, select a category, and enter expenses. No Excel report is generated.

## Common Problems

### Python was not found

Run the bot like this instead of `python bot.py`:

```powershell
.\.venv\Scripts\python.exe bot.py
```

### The bot does not respond

Check that:

- `bot.py` is running;
- the token in `.env` is correct;
- another instance of the same bot is not already running;
- internet connection is available.

### Marketplace data is unavailable

This can happen. Marketplaces may change page structure, limit frequent requests, or show protection pages. In this case, the bot uses approximate data and warns the user.

## Important Note

The bot does not guarantee exact financial results. It helps estimate the market situation and make a preliminary decision. Before purchasing real stock, it is better to manually check prices, reviews, commissions, logistics, and demand.

>**Author of project: Zeynalov U.R.o.**
