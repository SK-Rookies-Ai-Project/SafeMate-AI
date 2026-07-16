import math
import unittest

from src.pipeline import calculate_overall_risk


class OverallRiskPolicyTest(unittest.TestCase):
    def test_uses_message_score_when_it_is_the_only_score(self) -> None:
        self.assertEqual(
            calculate_overall_risk({"phishing_probability": 0.2}, []),
            {"score": 0.2, "level": "low"},
        )

    def test_uses_maximum_valid_message_and_url_score(self) -> None:
        self.assertEqual(
            calculate_overall_risk(
                {"phishing_probability": 0.65},
                [{"risk_score": 0.3}, {"risk_score": 0.91}],
            ),
            {"score": 0.91, "level": "high"},
        )

    def test_applies_threshold_boundaries(self) -> None:
        self.assertEqual(
            calculate_overall_risk(None, [{"risk_score": 0.4}])["level"],
            "medium",
        )
        self.assertEqual(
            calculate_overall_risk(None, [{"risk_score": 0.7}])["level"],
            "high",
        )

    def test_returns_unknown_when_no_valid_score_exists(self) -> None:
        invalid_values = [-0.1, 1.1, math.nan, math.inf, "0.8", True, None]
        self.assertEqual(
            calculate_overall_risk(
                {"phishing_probability": invalid_values[0]},
                [{"risk_score": value} for value in invalid_values[1:]],
            ),
            {"score": None, "level": "unknown"},
        )

    def test_ignores_invalid_values_when_a_valid_score_exists(self) -> None:
        self.assertEqual(
            calculate_overall_risk(
                {"phishing_probability": math.nan},
                [{"risk_score": "0.9"}, {"risk_score": 0.55}],
            ),
            {"score": 0.55, "level": "medium"},
        )


if __name__ == "__main__":
    unittest.main()
