from pathlib import Path

import pytest

from gifmaker.models.render_settings import RenderSettings, RenderSpec
from gifmaker.services.gif_export import (
    GifExportError,
    build_gif_command,
    build_webp_command,
)
from gifmaker.services.output_formats import get_output_format
from gifmaker.services.render_service import RenderService


@pytest.mark.parametrize("name,suffix,builder", [
    ("GIF", ".gif", build_gif_command),
    ("WebP", ".webp", build_webp_command),
])
def test_registered_renderer_preserves_existing_command(tmp_path: Path, name, suffix, builder):
    source = tmp_path / "input.mp4"
    source.touch()
    destination = tmp_path / f"output{suffix}"
    settings = RenderSettings(0.5, 2.0, fps=15, width=320, height=180,
                              playback_speed=1.5, crop=(2, 4, 100, 80))
    spec = RenderSpec(str(source), name, settings)
    expected = builder(source, destination, start_seconds=0.5, end_seconds=2.0,
                       fps=15, width=320, height=180, playback_speed=1.5,
                       quality_preset="balanced", sharpness_preset="mild",
                       crop=(2, 4, 100, 80))
    assert get_output_format(name).suffix == suffix
    assert RenderService().build_command(spec, destination) == expected


def test_unknown_format_has_clear_error():
    with pytest.raises(GifExportError, match="Unsupported output format: unknown"):
        get_output_format("unknown")
