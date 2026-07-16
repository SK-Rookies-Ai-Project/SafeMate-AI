import math
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.analyzers.url import features
from src.analyzers.url.constants import LABEL_COLUMN
from src.analyzers.url.datasets import (
    load_feature_csv,
    load_url_csv,
    make_feature_dataset,
    make_tfidf_dataset,
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


if __name__ == "__main__":
    unittest.main()
