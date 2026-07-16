import unittest

from src.ui.visualizations import (
    create_message_feature_chart,
    create_message_probability_chart,
    create_url_contribution_chart,
    create_url_feature_chart,
    create_url_risk_chart,
)
from matplotlib.figure import Figure


class VisualizationTest(unittest.TestCase):
    def test_creates_message_probability_chart(self) -> None:
        figure = create_message_probability_chart(
            {"phishing_probability": 0.84}
        )

        self.assertIsInstance(figure, Figure)
        self.assertEqual(len(figure.axes[0].patches), 2)

    def test_omits_message_probability_chart_without_valid_score(self) -> None:
        self.assertIsNone(
            create_message_probability_chart({"phishing_probability": None})
        )
        self.assertIsNone(
            create_message_probability_chart({"phishing_probability": 1.5})
        )

    def test_creates_message_feature_chart_from_contributions(self) -> None:
        figure = create_message_feature_chart(
            [
                {"name": "비밀번호", "contribution": 0.31},
                {"name": "인증", "contribution": 0.26},
                {"name": "계산 불가", "contribution": None},
            ]
        )

        self.assertIsInstance(figure, Figure)
        self.assertEqual(len(figure.axes[0].patches), 2)

    def test_creates_url_risk_and_feature_charts(self) -> None:
        risk_figure = create_url_risk_chart(
            [
                {"url": "https://one.example/login", "risk_score": 0.78},
                {"url": "https://two.example", "risk_score": None},
            ]
        )
        features = [
            {
                "name": "URL 길이",
                "normalized_value": 0.72,
                "contribution": 0.18,
            }
        ]

        self.assertIsInstance(risk_figure, Figure)
        self.assertIsInstance(create_url_feature_chart(features), Figure)
        self.assertIsInstance(create_url_contribution_chart(features), Figure)

    def test_does_not_invent_missing_feature_contributions(self) -> None:
        features = [
            {
                "name": "URL 길이",
                "normalized_value": 0.72,
                "contribution": None,
            }
        ]

        self.assertIsNone(create_url_contribution_chart(features))


if __name__ == "__main__":
    unittest.main()
