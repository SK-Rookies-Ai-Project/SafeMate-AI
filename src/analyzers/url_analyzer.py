"""URL model analyzer entry points."""

from src.analyzers.model_loader import LoadedModel, load_model


def load_url_model() -> LoadedModel:
    """Load the manifest-approved URL model and public version."""
    return load_model("url")
