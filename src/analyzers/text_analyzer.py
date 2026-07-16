"""Message model analyzer entry points."""

from src.analyzers.model_loader import LoadedModel, load_model


def load_message_model() -> LoadedModel:
    """Load the manifest-approved message model and public version."""
    return load_model("message")
