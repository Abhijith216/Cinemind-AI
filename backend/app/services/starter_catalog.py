"""Import the public TMDb 5000 CSV without overwriting existing movie records.

Source: https://github.com/vamshi121/TMDB-5000-Movie-Dataset
Expected SHA256: 1e0584a8dd374120e4ed4f2b81f0d2bd0eb95a554708e4a350d00ed5c46d2825
This historical snapshot has no poster paths or embeddings. Ratings are snapshot
values, not live ratings. Use the TMDb ingestion service for ongoing updates.
"""

import argparse
import asyncio
import csv
import json
from pathlib import Path
from typing import Any

from sqlalchemy.dialects.postgresql import insert

from app.core.db import dispose_engine, get_sessionmaker
from app.models import Movie


def parse_starter_row(row: dict[str, str]) -> dict[str, Any]:
    """Keep source metadata; never invent missing posters or personality traits."""
    title = row["title"].strip()
    if not title:
        raise ValueError("Missing movie title")
    return {
        "tmdb_id": int(row["id"]),
        "title": title,
        "overview": row.get("overview") or None,
        "release_year": int(row["release_date"][:4]) if row.get("release_date") else None,
        "runtime": int(float(row["runtime"])) if row.get("runtime") else None,
        "genres": [value["name"] for value in json.loads(row.get("genres") or "[]")],
        "keywords": [value["name"] for value in json.loads(row.get("keywords") or "[]")],
        "language": row.get("original_language") or None,
        "vote_average": float(row["vote_average"]) if row.get("vote_average") else None,
        "vote_count": int(row["vote_count"]) if row.get("vote_count") else None,
        "popularity": float(row["popularity"]) if row.get("popularity") else None,
    }


async def import_catalog(path: Path) -> None:
    rows = []
    skipped = 0
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            try:
                rows.append(parse_starter_row(row))
            except (KeyError, TypeError, ValueError):
                skipped += 1
    try:
        async with get_sessionmaker()() as session:
            for start in range(0, len(rows), 250):
                statement = insert(Movie).values(rows[start : start + 250])
                await session.execute(statement.on_conflict_do_nothing(index_elements=["tmdb_id"]))
            await session.commit()
        print(
            f"Processed {len(rows)} movies; {skipped} invalid rows skipped. "
            "Existing movies preserved."
        )
    finally:
        await dispose_engine()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(import_catalog(args.csv))
