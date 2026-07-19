import math
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.analyzers.url import features
from src.analyzers.url.constants import LABEL_COLUMN
from src.analyzers.url.datasets import (
    dedup_group_split,
    load_feature_csv,
    load_url_csv,
    make_feature_dataset,
    make_tfidf_dataset,
    registered_domain,
)
from src.analyzers.url.schemas import DataSet


class DataSetLoadingTests(unittest.TestCase):
    def test_load_feature_csv_returns_clean_dataset(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "sample_features.csv"
            row = {name: 1.0 for name in features.FEATURE_NAMES}
            row["Querylength"] = math.inf
            row["avgpathtokenlen"] = math.nan
            row[LABEL_COLUMN] = "benign"
            pd.DataFrame([row]).to_csv(csv_path, index=False)

            dataset = load_feature_csv(csv_path, random_state=7)

        self.assertIsInstance(dataset, DataSet)
        self.assertEqual(dataset.name, "sample_features")
        self.assertEqual(dataset.random_state, 7)
        self.assertEqual(dataset.y, ["benign"])
        self.assertEqual(list(dataset.x.columns), features.FEATURE_NAMES)
        self.assertEqual(dataset.x.loc[0, "Querylength"], -1.0)
        self.assertEqual(dataset.x.loc[0, "avgpathtokenlen"], -1.0)

    def test_load_feature_csv_rejects_missing_feature_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "missing_feature.csv"
            row = {name: 1.0 for name in features.FEATURE_NAMES}
            row.pop("Querylength")
            row[LABEL_COLUMN] = "benign"
            pd.DataFrame([row]).to_csv(csv_path, index=False)

            with self.assertRaisesRegex(ValueError, "Querylength"):
                load_feature_csv(csv_path)

    def test_load_feature_csv_rejects_missing_label_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "missing_label.csv"
            row = {name: 1.0 for name in features.FEATURE_NAMES}
            pd.DataFrame([row]).to_csv(csv_path, index=False)

            with self.assertRaisesRegex(ValueError, LABEL_COLUMN):
                load_feature_csv(csv_path)

    def test_load_url_csv_returns_clean_urls_and_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "urls.csv"
            pd.DataFrame(
                [
                    {"url": " 'https://example.com/login' ", "label": "benign"},
                    {"url": '"http://bad.test/pay"', "label": "phishing"},
                ],
            ).to_csv(csv_path, index=False)

            urls, labels = load_url_csv(csv_path)

        self.assertEqual(
            urls,
            ["https://example.com/login", "http://bad.test/pay"],
        )
        self.assertEqual(labels, ["benign", "phishing"])

    def test_load_url_csv_rejects_single_column_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "one_column.csv"
            pd.DataFrame([["https://example.com"]]).to_csv(
                csv_path,
                index=False,
                header=False,
            )

            with self.assertRaisesRegex(ValueError, "URL CSV"):
                load_url_csv(csv_path)


class DataSetFactoryTests(unittest.TestCase):
    def test_make_feature_dataset_builds_training_shape(self):
        dataset = make_feature_dataset(
            ["https://example.com/a", "http://bad.test/login?id=1"],
            labels=("benign", "phishing"),
            name="custom-features",
            random_state=13,
        )

        self.assertIsInstance(dataset, DataSet)
        self.assertEqual(dataset.name, "custom-features")
        self.assertEqual(dataset.random_state, 13)
        self.assertEqual(dataset.y, ["benign", "phishing"])
        self.assertEqual(len(dataset), 2)
        self.assertEqual(dataset.n_features, len(features.FEATURE_NAMES))
        self.assertEqual(list(dataset.x.columns), features.FEATURE_NAMES)
        self.assertFalse(dataset.x.isna().any().any())

    def test_make_feature_dataset_allows_prediction_without_labels(self):
        dataset = make_feature_dataset(["https://example.com"])

        self.assertIsNone(dataset.y)
        self.assertEqual(len(dataset), 1)

    def test_make_tfidf_dataset_fits_and_reuses_vectorizer(self):
        train_dataset, vectorizer = make_tfidf_dataset(
            ["https://example.com/login", "http://bad.test/pay"],
            labels=["benign", "phishing"],
            min_df=1,
            ngram_range=(3, 3),
        )
        predict_dataset, same_vectorizer = make_tfidf_dataset(
            [" 'https://example.com/login' "],
            vectorizer=vectorizer,
        )

        self.assertIs(same_vectorizer, vectorizer)
        self.assertEqual(train_dataset.y, ["benign", "phishing"])
        self.assertIsNone(predict_dataset.y)
        self.assertEqual(predict_dataset.n_features, train_dataset.n_features)


class DedupGroupSplitTests(unittest.TestCase):
    def test_registered_domain_uses_public_suffix(self):
        self.assertEqual(registered_domain("a.b.example.co.uk"), "example.co.uk")
        # IP·localhost처럼 PSL 밖 host는 그대로 그룹이 된다
        self.assertEqual(registered_domain("211.239.150.212"), "211.239.150.212")

    def test_dedup_removes_canonical_duplicates(self):
        # 세 표기 모두 canonical 'a.com/x' — 한 행만 남아야 한다
        urls = ["http://a.com/x", "https://www.a.com/x", "a.com/x/", "b.com/1"]
        y = [0, 0, 0, 1]

        urls_train, urls_test, y_train, y_test = dedup_group_split(
            urls, y, test_size=0.0, split="group",
        )

        merged = urls_train + urls_test
        self.assertEqual(len(merged), 2)
        self.assertIn("http://a.com/x", merged)  # 첫 표기 유지
        self.assertIn("b.com/1", merged)

    def test_dedup_drops_label_conflict_groups(self):
        urls = ["conflict.com/p", "http://conflict.com/p", "ok.com/1"]
        y = [0, 1, 1]

        urls_train, urls_test, _, _ = dedup_group_split(
            urls, y, test_size=0.0, split="group",
        )

        self.assertEqual(urls_train + urls_test, ["ok.com/1"])

    def test_group_split_keeps_domains_disjoint(self):
        urls = [f"d{i}.com/page{j}" for i in range(60) for j in range(3)]
        urls.append("sub.d0.com/extra")  # 서브도메인도 같은 그룹이어야 한다
        y = [i % 2 for i in range(len(urls))]

        urls_train, urls_test, y_train, y_test = dedup_group_split(
            urls, y, test_size=0.3, split="group",
        )

        self.assertEqual(len(urls_train) + len(urls_test), len(urls))
        self.assertTrue(urls_train and urls_test)
        train_domains = {registered_domain(u.split("/")[0]) for u in urls_train}
        test_domains = {registered_domain(u.split("/")[0]) for u in urls_test}
        self.assertFalse(train_domains & test_domains)
        d0_side = [u for u in urls_train if "d0.com" in u]
        if d0_side:
            self.assertEqual(len(d0_side), 4)  # page 3개 + sub.d0.com
        else:
            self.assertEqual(sum("d0.com" in u for u in urls_test), 4)

    def test_group_split_is_stable_across_subsets(self):
        urls = [f"d{i}.com/p" for i in range(40)]
        y = [i % 2 for i in range(40)]

        _, test_full, _, _ = dedup_group_split(
            urls, y, test_size=0.3, split="group",
        )
        _, test_half, _, _ = dedup_group_split(
            urls[:20], y[:20], test_size=0.3, split="group",
        )

        # 같은 random_state면 표본이 줄어도 도메인의 train/test 소속은 불변
        self.assertEqual(set(test_half), set(test_full) & set(urls[:20]))

    def test_random_split_fallback(self):
        urls = [f"d{i}.com/p" for i in range(100)]
        y = [i % 2 for i in range(100)]

        urls_train, urls_test, y_train, y_test = dedup_group_split(
            urls, y, test_size=0.2, split="random",
        )

        self.assertEqual(len(urls_test), 20)
        self.assertEqual(len(urls_train), 80)
        self.assertEqual(sorted(urls_train + urls_test), sorted(urls))

    def test_rejects_unknown_split(self):
        with self.assertRaises(ValueError):
            dedup_group_split(["a.com"], [0], split="stratified")


if __name__ == "__main__":
    unittest.main()
