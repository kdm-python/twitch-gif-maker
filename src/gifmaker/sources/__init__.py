"""Backend source preparation; independent of the GUI session."""

from gifmaker.sources.loader import SourceLoadError, load_source
from gifmaker.sources.model import LoadedSource, SourceFrame, SourceInfo

__all__ = ["LoadedSource", "SourceFrame", "SourceInfo", "SourceLoadError", "load_source"]
