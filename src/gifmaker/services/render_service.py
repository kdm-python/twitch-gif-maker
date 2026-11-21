"""Format-neutral rendering facade used by GUI controllers."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from gifmaker.models.render_settings import RenderSpec
from gifmaker.services.gif_export import _run_export
from gifmaker.services.output_formats import get_output_format


class RenderService:
    """Resolve a format renderer and run its immutable recipe."""

    def export(self, spec: RenderSpec, destination: str | Path) -> None:
        """Run the same validated command used by asynchronous rendering."""
        workspace, command = self.prepare_job(spec, destination)
        try:
            _run_export(command)
            if workspace is not None:
                destination = Path(destination)
                descriptor, name = tempfile.mkstemp(prefix=".gifmaker-", suffix=destination.suffix,
                                                    dir=destination.parent)
                os.close(descriptor)
                try:
                    shutil.copyfile(Path(workspace.name) / f"result{destination.suffix.lower()}", name)
                    os.replace(name, destination)
                finally:
                    Path(name).unlink(missing_ok=True)
        finally:
            if workspace is not None:
                workspace.cleanup()

    def prepare_job(self, spec: RenderSpec, destination: str | Path):
        """Return command plus caller-owned workspace for a direct video source."""
        if spec.subtitles.captions:
            from gifmaker.services.subtitle_render import prepare_job

            get_output_format(spec.output_format).build_command(spec, destination)
            source, destination = Path(spec.source_path), Path(destination)
            if destination.resolve() == source.resolve() or (destination.exists() and os.path.samefile(source, destination)):
                raise ValueError("Choose an output file different from the original source.")
            return prepare_job(spec)
        return None, self.build_command(spec, destination)

    def build_command(self, spec: RenderSpec, destination: str | Path) -> list[str]:
        """Return a validated command for a non-blocking render process."""
        if spec.subtitles.captions:
            raise ValueError("Caption rendering requires a prepared job; use prepare_job() or export().")
        return get_output_format(spec.output_format).build_command(spec, destination)
