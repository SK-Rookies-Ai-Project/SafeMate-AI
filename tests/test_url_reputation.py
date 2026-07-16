import pandas as pd

from src.analyzers.url.reputation import build_url_reputation_db, lookup_url_reputation


def test_reputation_db_exact_match_uses_canonical_url(tmp_path):
    csv_path = tmp_path / "urls.csv"
    db_path = tmp_path / "reputation.sqlite3"
    pd.DataFrame(
        {
            "url": [
                "https://www.naver.com/",
                "http://naver.com",
                "https://bad.example/login",
            ],
            "status": ["정상", "정상", "악성"],
        }
    ).to_csv(csv_path, index=False)

    build_url_reputation_db(csv_path=csv_path, db_path=db_path, chunksize=2)

    naver = lookup_url_reputation("www.naver.com", db_path=db_path)
    bad = lookup_url_reputation("bad.example/login", db_path=db_path)
    missing = lookup_url_reputation("missing.example", db_path=db_path)

    assert naver["canonical_url"] == "naver.com"
    assert naver["label"] == "정상"
    assert naver["risk_score"] == 0.0
    assert naver["benign_count"] == 2

    assert bad["label"] == "악성"
    assert bad["risk_score"] == 1.0
    assert missing is None
