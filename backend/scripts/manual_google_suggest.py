"""Optional single-query smoke check against the live Suggest endpoint."""

import argparse
import asyncio

from app.services.google_suggest import GoogleSuggestClient, GoogleSuggestError


async def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch one Google Suggest query")
    parser.add_argument("query", nargs="?", default="age calculator")
    parser.add_argument("--country", default="us")
    parser.add_argument("--language", default="en")
    args = parser.parse_args()

    try:
        async with GoogleSuggestClient() as client:
            suggestions = await client.get_suggestions(
                args.query, country=args.country, language=args.language
            )
    except GoogleSuggestError as exc:
        parser.exit(1, f"Suggest request failed: {exc}\n")

    for suggestion in suggestions:
        print(suggestion)


if __name__ == "__main__":
    asyncio.run(main())
