"""Format-neutral rendering facade used by GUI controllers."""

from __future__ import annotations

from pathlib import Path

from gifmaker.models.render_settings import RenderSpec
from gifmaker.services.gif_export import _run_export
from gifmaker.services.output_formats import get_output_format


class RenderService:
    """Resolve a format renderer and run its immutable recipe."""

    def export(self, spec: RenderSpec, destination: str | Path) -> None:
        """Run the same validated command used by asynchronous rendering."""
        _run_export(self.build_command(spec, destination))

    def build_command(self, spec: RenderSpec, destination: str | Path) -> list[str]:
        """Return a validated command for a non-blocking render process."""
        return get_output_format(spec.output_format).build_command(spec, destination)
