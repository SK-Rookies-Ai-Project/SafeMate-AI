import unittest


class ProjectSmokeTest(unittest.TestCase):
    def test_project_imports(self) -> None:
        import src  # noqa: F401

        self.assertIsNotNone(src)


if __name__ == "__main__":
    unittest.main()
