def test_project_imports() -> None:
    import src  # noqa: F401


def test_url_package_imports() -> None:
    # __init__의 재수출 전부가 깨지지 않는지 (누락 모듈 등) 확인
    import src.analyzers.url as url_pkg
    import src.analyzers.url_analyzer  # noqa: F401

    for name in url_pkg.__all__:
        assert hasattr(url_pkg, name), f"__all__에 있지만 없는 심볼: {name}"
