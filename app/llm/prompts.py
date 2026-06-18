from app.enums import LLM_CATEGORIES

CATEGORY_LIST = ", ".join(LLM_CATEGORIES)

CLASSIFY_SYSTEM = (
    "You are a precise transaction categorizer. For each transaction item you are "
    "given, choose the single best category from this fixed list and nothing else:\n"
    f"{CATEGORY_LIST}.\n"
    "Respond ONLY with a JSON object mapping each item's \"index\" (as a string) to "
    "one category string from the list. Do not add commentary."
)


def build_classify_prompt(items: list[dict]) -> str:
    """`items`: list of {index, merchant, amount, currency}."""
    lines = ["Classify these transactions:", ""]
    for it in items:
        lines.append(
            f'- index {it["index"]}: merchant="{it["merchant"]}", '
            f'amount={it["amount"]} {it["currency"]}'
        )
    lines.append("")
    lines.append(
        'Return JSON like {"0": "Food", "1": "Travel"} using ONLY these categories: '
        f"{CATEGORY_LIST}."
    )
    return CLASSIFY_SYSTEM + "\n\n" + "\n".join(lines)


SUMMARY_SYSTEM = (
    "You are a financial analyst. Given aggregate statistics about a batch of "
    "transactions, produce a concise JSON summary. The narrative must be 2-3 "
    "sentences. risk_level must be one of: low, medium, high."
)


def build_summary_prompt(aggregates: dict) -> str:
    return (
        SUMMARY_SYSTEM
        + "\n\nAggregates:\n"
        + _format_aggregates(aggregates)
        + "\n\nReturn JSON with exactly these fields: "
        '{"total_spend_inr": number, "total_spend_usd": number, '
        '"top_merchants": [{"merchant": string, "total": number, "count": number}], '
        '"anomaly_count": number, "narrative": string, '
        '"risk_level": "low"|"medium"|"high"}. '
        "Include at most the top 3 merchants."
    )


def _format_aggregates(agg: dict) -> str:
    import json

    return json.dumps(agg, indent=2, default=str)
