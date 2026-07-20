import unittest


class ProjectSmokeTest(unittest.TestCase):
    def test_project_imports(self) -> None:
        import src

        self.assertIsNotNone(src)

    def test_url_package_imports(self) -> None:
        import src.analyzers.url as url_pkg
        import src.analyzers.url_analyzer  # noqa: F401

        for name in url_pkg.__all__:
            self.assertTrue(
                hasattr(url_pkg, name),
                f"__all__에 있지만 없는 심볼: {name}",
            )


if __name__ == "__main__":
    unittest.main()
