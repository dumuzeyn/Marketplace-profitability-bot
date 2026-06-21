from __future__ import annotations

import logging
import os
from pathlib import Path

import telebot
from dotenv import load_dotenv
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

from marketplace_bot.analysis import (
    BusinessCosts,
    analyze_product,
    build_price_chart,
    build_price_history,
    cluster_products,
    forecast_prices,
    parse_costs,
)
from marketplace_bot.marketplace import get_marketplace_products, is_url
from marketplace_bot.storage import init_db, save_analysis, save_price_history, save_products

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "outputs"
DB_PATH = DATA_DIR / "market_data.sqlite"
MARKETPLACES = {
    "ozon": "Ozon",
    "wildberries": "Wildberries",
    "yandex_market": "Yandex Market",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def ru(text: str) -> str:
    try:
        return text.encode("ascii").decode("unicode_escape")
    except UnicodeEncodeError:
        return text


load_dotenv(ROOT / ".env")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is missing. Fill .env before starting the bot.")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
user_data: dict[int, dict[str, object]] = {}


def marketplace_keyboard() -> InlineKeyboardMarkup:
    markup = InlineKeyboardMarkup(row_width=1)
    for key, label in MARKETPLACES.items():
        markup.add(InlineKeyboardButton(label, callback_data=f"marketplace:{key}"))
    return markup


def categories_keyboard(categories: list[str]) -> InlineKeyboardMarkup:
    markup = InlineKeyboardMarkup(row_width=1)
    for index, category in enumerate(categories):
        markup.add(InlineKeyboardButton(category[:60], callback_data=f"category:{index}"))
    return markup


def infer_marketplace_from_link(link: str, current: str) -> str:
    value = link.lower()
    if "wildberries" in value or "wb.ru" in value:
        return "wildberries"
    if "ozon" in value:
        return "ozon"
    if "market.yandex" in value or "market.yandex.ru" in value:
        return "yandex_market"
    return current


def uses_approximate_data(products: object) -> bool:
    try:
        sources = set(products.get("data_source", []).astype(str).tolist())
    except Exception:
        return False
    return bool(sources) and sources <= {"synthetic_fallback"}


def approximate_notice() -> str:
    return ru(r"\u0412\u043d\u0438\u043c\u0430\u043d\u0438\u0435: \u0440\u0435\u0430\u043b\u044c\u043d\u044b\u0435 \u0434\u0430\u043d\u043d\u044b\u0435 \u043d\u0435 \u043f\u043e\u043b\u0443\u0447\u0438\u043b\u0438\u0441\u044c, \u043f\u043e\u044d\u0442\u043e\u043c\u0443 \u044d\u0442\u043e \u043f\u0440\u0438\u043c\u0435\u0440\u043d\u0430\u044f \u043e\u0446\u0435\u043d\u043a\u0430 \u0440\u044b\u043d\u043a\u0430.\n")

def choose_best_category(clustered: object, categories: list[str]) -> str:
    try:
        grouped = clustered.groupby("cluster_name")["reviews"].sum().sort_values(ascending=False)
        if not grouped.empty:
            return str(grouped.index[0])
    except Exception:
        pass
    return str(categories[0])


def estimate_costs_from_price(price: float) -> BusinessCosts:
    purchase = price * 0.52
    logistics = max(70.0, min(450.0, price * 0.07))
    packaging = max(25.0, min(120.0, price * 0.025))
    ads = max(60.0, min(350.0, price * 0.08))
    other = max(20.0, min(120.0, price * 0.02))
    return BusinessCosts(purchase, logistics, packaging, ads, other)


@bot.message_handler(commands=["start", "help"])
def handle_start(message: telebot.types.Message) -> None:
    user_data.pop(message.chat.id, None)
    text = ru(
        "\u041f\u0440\u0438\u0432\u0435\u0442! \u042f \u0431\u043e\u0442 \u0434\u043b\u044f \u0430\u043d\u0430\u043b\u0438\u0437\u0430 \u0440\u0435\u043d\u0442\u0430\u0431\u0435\u043b\u044c\u043d\u043e\u0441\u0442\u0438 \u0442\u043e\u0432\u0430\u0440\u043e\u0432 \u043d\u0430 \u043c\u0430\u0440\u043a\u0435\u0442\u043f\u043b\u0435\u0439\u0441\u0430\u0445.\n\n"
        "\u0412\u044b\u0431\u0435\u0440\u0438 \u043f\u043b\u043e\u0449\u0430\u0434\u043a\u0443, \u043f\u043e\u0442\u043e\u043c \u043e\u0442\u043f\u0440\u0430\u0432\u044c \u043d\u0430\u0437\u0432\u0430\u043d\u0438\u0435 \u0442\u043e\u0432\u0430\u0440\u0430 \u0438\u043b\u0438 \u0441\u0441\u044b\u043b\u043a\u0443. "
        "\u042f \u0441\u043e\u0431\u0435\u0440\u0443 \u0432\u044b\u0431\u043e\u0440\u043a\u0443, \u0440\u0430\u0437\u043e\u0431\u044c\u044e \u0442\u043e\u0432\u0430\u0440\u044b \u043d\u0430 \u043a\u0430\u0442\u0435\u0433\u043e\u0440\u0438\u0438, \u043f\u043e\u0441\u0442\u0440\u043e\u044e \u043f\u0440\u043e\u0433\u043d\u043e\u0437 \u0446\u0435\u043d\u044b \u043d\u0430 30 \u0434\u043d\u0435\u0439 "
        "\u0438 \u0434\u0430\u043c \u0440\u0435\u043a\u043e\u043c\u0435\u043d\u0434\u0430\u0446\u0438\u044e \u043f\u043e \u043f\u0440\u043e\u0434\u0430\u0436\u0435."
    )
    bot.send_message(message.chat.id, text, reply_markup=marketplace_keyboard())


@bot.callback_query_handler(func=lambda call: call.data.startswith("marketplace:"))
def choose_marketplace(call: telebot.types.CallbackQuery) -> None:
    marketplace_key = call.data.split(":", 1)[1]
    user_data[call.from_user.id] = {"marketplace": marketplace_key}
    bot.answer_callback_query(call.id)
    bot.send_message(
        call.message.chat.id,
        ru(r"\u041f\u043b\u043e\u0449\u0430\u0434\u043a\u0430: ") + f"<b>{MARKETPLACES[marketplace_key]}</b>\n" + ru(r"\u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u043d\u0430\u0437\u0432\u0430\u043d\u0438\u0435 \u0442\u043e\u0432\u0430\u0440\u0430 \u0438\u043b\u0438 \u0441\u0441\u044b\u043b\u043a\u0443:"),
    )


@bot.message_handler(func=lambda message: message.chat.id in user_data and "product" not in user_data[message.chat.id])
def receive_product(message: telebot.types.Message) -> None:
    state = user_data[message.chat.id]
    query = message.text.strip()
    link_mode = is_url(query)
    marketplace_key = str(state["marketplace"])
    if link_mode:
        marketplace_key = infer_marketplace_from_link(query, marketplace_key)
        state["marketplace"] = marketplace_key
    state["product"] = query

    bot.send_message(message.chat.id, ru(r"\u0421\u043e\u0431\u0438\u0440\u0430\u044e \u0434\u0430\u043d\u043d\u044b\u0435 \u0438 \u0433\u043e\u0442\u043e\u0432\u043b\u044e \u043f\u0440\u043e\u0433\u043d\u043e\u0437, \u043f\u043e\u0434\u043e\u0436\u0434\u0438\u0442\u0435..."))
    try:
        products = get_marketplace_products(marketplace_key, query, count=48, allow_fallback=True)
        save_products(DB_PATH, message.chat.id, marketplace_key, query, products)
        clustered, categories, silhouette = cluster_products(products)
    except Exception:
        logger.exception("Product analysis failed")
        user_data.pop(message.chat.id, None)
        bot.send_message(message.chat.id, ru(r"\u041d\u0435 \u043f\u043e\u043b\u0443\u0447\u0438\u043b\u043e\u0441\u044c \u043e\u0431\u0440\u0430\u0431\u043e\u0442\u0430\u0442\u044c \u0442\u043e\u0432\u0430\u0440. \u041f\u043e\u043f\u0440\u043e\u0431\u0443\u0439\u0442\u0435 \u0434\u0440\u0443\u0433\u043e\u0439 \u0437\u0430\u043f\u0440\u043e\u0441."))
        return

    state["products"] = products
    state["clustered"] = clustered
    state["categories"] = categories
    state["is_approximate"] = uses_approximate_data(products)

    if link_mode:
        category = choose_best_category(clustered, categories)
        state["selected_category"] = category
        state["awaiting_costs"] = True
        subset = clustered[clustered["cluster_name"] == category]
        base_price = float(subset["price"].mean() if not subset.empty else clustered["price"].mean())
        costs = estimate_costs_from_price(base_price)
        message_text = ru(r"\u0421\u0441\u044b\u043b\u043a\u0443 \u043f\u0440\u0438\u043d\u044f\u043b. \u041a\u0430\u0442\u0435\u0433\u043e\u0440\u0438\u044e \u0438 \u0440\u0430\u0441\u0445\u043e\u0434\u044b \u043e\u0446\u0435\u043d\u044e \u0441\u0430\u043c, \u0441\u0440\u0430\u0437\u0443 \u0441\u0442\u0440\u043e\u044e \u0430\u043d\u0430\u043b\u0438\u0437.")
        if state.get("is_approximate"):
            message_text = approximate_notice() + message_text
            state["warned_approx"] = True
        bot.send_message(message.chat.id, message_text)
        run_full_analysis(message.chat.id, costs, auto_costs=True)
        return

    category_text = ""
    if state.get("is_approximate"):
        category_text += approximate_notice()
        state["warned_approx"] = True
    category_text += (
        ru(r"\u041d\u0430\u0448\u0435\u043b ")
        + f"{len(products)} "
        + ru(r"\u0442\u043e\u0432\u0430\u0440\u043e\u0432.\n")
        + ru(r"\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u043a\u0430\u0442\u0435\u0433\u043e\u0440\u0438\u044e:")
    )
    bot.send_message(
        message.chat.id,
        category_text,
        reply_markup=categories_keyboard(categories),
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("category:"))
def choose_category(call: telebot.types.CallbackQuery) -> None:
    state = user_data.get(call.from_user.id)
    if not state:
        bot.answer_callback_query(call.id, ru(r"\u0421\u043d\u0430\u0447\u0430\u043b\u0430 \u043d\u0430\u0436\u043c\u0438\u0442\u0435 /start"))
        return

    try:
        category_index = int(call.data.split(":", 1)[1])
        categories = list(state["categories"])
        category = categories[category_index]
        clustered = state["clustered"]
        marketplace_key = str(state["marketplace"])
    except Exception:
        bot.answer_callback_query(call.id, ru(r"\u041a\u0430\u0442\u0435\u0433\u043e\u0440\u0438\u044f \u0443\u0441\u0442\u0430\u0440\u0435\u043b\u0430, \u043d\u0430\u0436\u043c\u0438\u0442\u0435 /start"))
        return

    state["selected_category"] = category
    state["awaiting_costs"] = True
    bot.answer_callback_query(call.id)
    bot.send_message(
        call.message.chat.id,
        ru(r"\u0412\u0432\u0435\u0434\u0438 \u0440\u0430\u0441\u0445\u043e\u0434\u044b \u043d\u0430 1 \u0442\u043e\u0432\u0430\u0440: \u0437\u0430\u043a\u0443\u043f\u043a\u0430 \u043b\u043e\u0433\u0438\u0441\u0442\u0438\u043a\u0430 \u0443\u043f\u0430\u043a\u043e\u0432\u043a\u0430 \u0440\u0435\u043a\u043b\u0430\u043c\u0430 \u043f\u0440\u043e\u0447\u0435\u0435.\n\u041f\u0440\u0438\u043c\u0435\u0440: 500 80 30 120 0\n\u0418\u043b\u0438 \u043e\u0442\u043f\u0440\u0430\u0432\u044c 0, \u0447\u0442\u043e\u0431\u044b \u0431\u043e\u0442 \u043e\u0446\u0435\u043d\u0438\u043b \u0441\u0435\u0431\u0435\u0441\u0442\u043e\u0438\u043c\u043e\u0441\u0442\u044c \u0430\u0432\u0442\u043e\u043c\u0430\u0442\u0438\u0447\u0435\u0441\u043a\u0438.")
    )


def run_full_analysis(chat_id: int, costs_text: str | BusinessCosts, auto_costs: bool = False) -> None:
    state = user_data.get(chat_id)
    if not state or not state.get("awaiting_costs"):
        bot.send_message(chat_id, ru(r"\u041d\u0430\u0436\u043c\u0438\u0442\u0435 /start, \u0447\u0442\u043e\u0431\u044b \u043d\u0430\u0447\u0430\u0442\u044c \u0430\u043d\u0430\u043b\u0438\u0437 \u0442\u043e\u0432\u0430\u0440\u0430."))
        return

    category = str(state["selected_category"])
    marketplace_key = str(state["marketplace"])
    query = str(state.get("product", ""))
    clustered = state["clustered"]
    products = state["products"]
    costs = costs_text if isinstance(costs_text, BusinessCosts) else parse_costs(costs_text)

    bot.send_message(chat_id, ru(r"\u0421\u0447\u0438\u0442\u0430\u044e \u0440\u044b\u043d\u043e\u043a, \u0440\u0430\u0441\u0445\u043e\u0434\u044b, \u043f\u0440\u0438\u0431\u044b\u043b\u044c \u0438 \u043f\u0440\u043e\u0433\u043d\u043e\u0437..."))

    subset = clustered[clustered["cluster_name"] == category]
    base_price = float(subset["price"].mean() if not subset.empty else clustered["price"].mean())
    history = build_price_history(category, marketplace_key, base_price, days=180)
    forecast = forecast_prices(history, horizon=30)
    analysis_text, fin, market, alerts = analyze_product(clustered, category, marketplace_key, forecast, costs)
    chart_path = build_price_chart(forecast, OUTPUT_DIR / f"{chat_id}_forecast.png")
    save_price_history(DB_PATH, chat_id, marketplace_key, category, history)
    save_analysis(DB_PATH, chat_id, marketplace_key, query, category, fin.score, forecast.risk_level, fin.roi, fin.break_even_price, forecast.monthly_change_pct)

    if state.get("is_approximate") and not state.get("warned_approx"):
        analysis_text = approximate_notice() + analysis_text
    if auto_costs:
        analysis_text += "\n\n" + ru(r"\u0420\u0430\u0441\u0445\u043e\u0434\u044b \u043f\u043e\u0441\u0442\u0430\u0432\u043b\u0435\u043d\u044b \u0430\u0432\u0442\u043e\u043c\u0430\u0442\u0438\u0447\u0435\u0441\u043a\u0438: \u043e\u0442 \u0441\u0440\u0435\u0434\u043d\u0435\u0439 \u0446\u0435\u043d\u044b \u0442\u043e\u0432\u0430\u0440\u0430 \u0438 \u0442\u0438\u043f\u043e\u0432\u044b\u0445 \u0437\u0430\u0442\u0440\u0430\u0442 \u043d\u0430 \u043b\u043e\u0433\u0438\u0441\u0442\u0438\u043a\u0443, \u0443\u043f\u0430\u043a\u043e\u0432\u043a\u0443 \u0438 \u0440\u0435\u043a\u043b\u0430\u043c\u0443.")
    bot.send_message(chat_id, analysis_text[:3900])
    with chart_path.open("rb") as chart:
        bot.send_photo(chat_id, chart)
    state.pop("awaiting_costs", None)
    for key in ("product", "products", "clustered", "categories", "selected_category", "is_approximate", "warned_approx"):
        state.pop(key, None)
    bot.send_message(
        chat_id,
        ru(r"\u0413\u043e\u0442\u043e\u0432\u043e. \u041c\u043e\u0436\u0435\u0442\u0435 \u0432\u0432\u0435\u0441\u0442\u0438 \u0441\u043b\u0435\u0434\u0443\u044e\u0449\u0438\u0439 \u0442\u043e\u0432\u0430\u0440 \u0434\u043b\u044f \u044d\u0442\u043e\u0439 \u0436\u0435 \u043f\u043b\u043e\u0449\u0430\u0434\u043a\u0438 \u0438\u043b\u0438 \u0432\u044b\u0431\u0440\u0430\u0442\u044c \u0434\u0440\u0443\u0433\u0443\u044e:"),
        reply_markup=marketplace_keyboard(),
    )


@bot.message_handler(func=lambda message: message.chat.id in user_data and user_data[message.chat.id].get("awaiting_costs"))
def receive_costs(message: telebot.types.Message) -> None:
    run_full_analysis(message.chat.id, message.text.strip())


@bot.message_handler(func=lambda message: True)
def fallback(message: telebot.types.Message) -> None:
    bot.send_message(message.chat.id, ru(r"\u041d\u0430\u0436\u043c\u0438\u0442\u0435 /start, \u0447\u0442\u043e\u0431\u044b \u043d\u0430\u0447\u0430\u0442\u044c \u0430\u043d\u0430\u043b\u0438\u0437 \u0442\u043e\u0432\u0430\u0440\u0430."))


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    OUTPUT_DIR.mkdir(exist_ok=True)
    init_db(DB_PATH)
    logger.info("Bot started")
    bot.infinity_polling(skip_pending=True, timeout=30)


if __name__ == "__main__":
    main()
