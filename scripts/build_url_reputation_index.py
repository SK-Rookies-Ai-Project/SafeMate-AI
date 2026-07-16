"""Build a local exact-match URL reputation index from url_binary_dataset.csv."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.analyzers.url.constants import URL_BINARY_CSV, URL_REPUTATION_DB
from src.analyzers.url.reputation import build_url_reputation_db


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", default=URL_BINARY_CSV, type=Path)
    parser.add_argument("--db", default=URL_REPUTATION_DB, type=Path)
    parser.add_argument("--chunksize", default=200_000, type=int)
    parser.add_argument("--nrows", default=None, type=int)
    args = parser.parse_args()

    path = build_url_reputation_db(
        csv_path=args.csv,
        db_path=args.db,
        chunksize=args.chunksize,
        nrows=args.nrows,
    )
    print(path)


if __name__ == "__main__":
    main()
