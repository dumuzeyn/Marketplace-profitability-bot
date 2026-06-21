from __future__ import annotations

from pathlib import Path
import re

from marketplace_bot.analysis import (
    analyze_product,
    build_price_chart,
    build_price_history,
    cluster_products,
    forecast_prices,
    parse_costs,
)
from marketplace_bot.marketplace import get_marketplace_products


MARKETPLACES = {
    "1": ("wildberries", "Wildberries"),
    "2": ("ozon", "Ozon"),
    "3": ("yandex_market", "Yandex Market"),
}


def choose_marketplace() -> str:
    print("Выберите маркетплейс:")
    for number, (_, title) in MARKETPLACES.items():
        print(f"{number}. {title}")

    while True:
        choice = input("Номер: ").strip()
        if choice in MARKETPLACES:
            return MARKETPLACES[choice][0]
        print("Введите 1, 2 или 3.")


def choose_category(categories: list[str]) -> str:
    print("\nВыберите категорию:")
    for index, category in enumerate(categories, start=1):
        print(f"{index}. {category}")

    while True:
        raw = input("Номер категории: ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(categories):
            return categories[int(raw) - 1]
        print("Введите номер из списка.")


def main() -> None:
    output_dir = Path("outputs")
    output_dir.mkdir(exist_ok=True)

    marketplace = choose_marketplace()
    query = input("\nВведите товар или ссылку: ").strip()
    if not query:
        print("Товар не введен.")
        return

    print("\n" + "\u0421\u043e\u0431\u0438\u0440\u0430\u044e \u0434\u0430\u043d\u043d\u044b\u0435...")
    try:
        products = get_marketplace_products(marketplace, query, count=48, allow_fallback=True)
    except Exception:
        print("\n" + "\u041d\u0435 \u043f\u043e\u043b\u0443\u0447\u0438\u043b\u043e\u0441\u044c \u0441\u043e\u0431\u0440\u0430\u0442\u044c \u0434\u0430\u043d\u043d\u044b\u0435. \u041f\u043e\u043f\u0440\u043e\u0431\u0443\u0439\u0442\u0435 \u0434\u0440\u0443\u0433\u043e\u0439 \u0437\u0430\u043f\u0440\u043e\u0441.")
        return

    print(f"\u041d\u0430\u0439\u0434\u0435\u043d\u043e \u0442\u043e\u0432\u0430\u0440\u043e\u0432: {len(products)}")

    clustered, categories, silhouette = cluster_products(products)
    print(f"Качество группировки: {silhouette:.3f}")
    category = choose_category(categories)

    print(
        "\nВведите расходы на 1 товар через пробел:\n"
        "закупка логистика упаковка реклама прочее\n"
        "Пример: 500 80 30 120 0\n"
        "Или 0, чтобы оценить себестоимость автоматически."
    )
    costs = parse_costs(input("Расходы: ").strip())

    subset = clustered[clustered["cluster_name"] == category]
    base_price = float(subset["price"].mean() if not subset.empty else clustered["price"].mean())
    history = build_price_history(category, marketplace, base_price, days=180)
    forecast = forecast_prices(history, horizon=30)
    analysis_text, _, _, _ = analyze_product(clustered, category, marketplace, forecast, costs)
    chart_path = build_price_chart(forecast, output_dir / "cli_forecast.png")

    plain_text = re.sub(r"</?b>", "", analysis_text)
    print("\n" + "=" * 60)
    print(plain_text)
    print("=" * 60)
    print(f"\nГрафик сохранен: {chart_path.resolve()}")


if __name__ == "__main__":
    main()
