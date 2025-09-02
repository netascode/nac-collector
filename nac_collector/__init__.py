try:
    from importlib.metadata import version  # type: ignore

    __version__ = version(__name__)
except Exception:
    __version__ = "development"
