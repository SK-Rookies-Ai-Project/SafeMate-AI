import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.ui.visualizations import (
    _configure_korean_font,
    create_message_feature_chart,
    create_message_probability_chart,
    create_url_contribution_chart,
    create_url_feature_chart,
    create_url_risk_chart,
)
from matplotlib.figure import Figure


class VisualizationTest(unittest.TestCase):
    def test_prefers_installed_malgun_gothic_font(self) -> None:
        installed_fonts = [SimpleNamespace(name="Malgun Gothic")]
        with patch(
            "src.ui.visualizations.font_manager.fontManager.ttflist",
            installed_fonts,
        ):
            self.assertEqual(_configure_korean_font(), "Malgun Gothic")

    def test_creates_message_probability_chart(self) -> None:
        figure = create_message_probability_chart(
            {
                "phishing_probability": 0.82,
                "label": "normal",
            }
        )

        self.assertIsInstance(figure, Figure)
        self.assertEqual(len(figure.axes[0].patches), 1)
        self.assertEqual(figure.axes[0].get_title(), "문자 모델 반환값")
        self.assertEqual(
            figure.axes[0].get_yticklabels()[0].get_text(),
            "스팸·사기 통합 점수",
        )
        self.assertEqual(
            figure.axes[0].patches[0].get_facecolor()[:3],
            (0.9372549019607843, 0.26666666666666666, 0.26666666666666666),
        )

    def test_labels_email_probability_chart_as_email(self) -> None:
        figure = create_message_probability_chart(
            {"phishing_probability": 0.65},
            input_type="email",
        )

        self.assertIsInstance(figure, Figure)
        self.assertEqual(figure.axes[0].get_title(), "이메일 모델 반환값")

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
        self.assertLessEqual(risk_figure.get_size_inches()[1], 2.0)
        self.assertLessEqual(risk_figure.axes[0].patches[0].get_height(), 0.4)
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
