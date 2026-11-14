import pytest

from gifmaker.models.render_settings import OutputControlValues, resolve_visual_settings


def test_visual_settings_ignore_hidden_quality_for_gif():
    controls = OutputControlValues(1.5, 30, 640, 360, "high", "mild")
    gif = resolve_visual_settings(1, 2, controls, None, uses_quality=False)
    webp = resolve_visual_settings(1, 2, controls, None, uses_quality=True)
    assert gif.quality_preset == "balanced"
    assert webp.quality_preset == "high"
    assert gif.playback_speed == webp.playback_speed == 1.5


@pytest.mark.parametrize("start,end", [(None, 1), (0, None), (1, 1), (2, 1)])
def test_visual_settings_reject_missing_or_invalid_selection(start, end):
    controls = OutputControlValues(1, 24, 640, 360, "balanced", "mild")
    with pytest.raises(ValueError):
        resolve_visual_settings(start, end, controls, None, uses_quality=True)


def test_render_settings_are_composed_and_immutable():
    from dataclasses import FrozenInstanceError

    from gifmaker.models.render_settings import RenderSettings

    settings = RenderSettings(1, 3, fps=30, playback_speed=1.5, quality_preset="high")
    assert (settings.shared.start_seconds, settings.shared.end_seconds, settings.shared.playback_speed) == (1, 3, 1.5)
    assert settings.visual.fps == 30
    assert settings.format_settings.quality_preset == "high"
    with pytest.raises(FrozenInstanceError):
        settings.shared.playback_speed = 2
    assert settings == RenderSettings(1, 3, fps=30, playback_speed=1.5, quality_preset="high")
    assert settings != RenderSettings(1, 3, fps=30, playback_speed=1.5, quality_preset="small")


def test_format_specific_settings_are_resolved_independently():
    from gifmaker.models.render_settings import GIFSettings, WebPSettings

    controls = OutputControlValues(1, 24, 640, 360, "high", "mild")
    gif = resolve_visual_settings(0, 1, controls, None, uses_quality=False)
    webp = resolve_visual_settings(0, 1, controls, None, uses_quality=True)
    assert isinstance(gif.format_settings, GIFSettings)
    assert webp.format_settings == WebPSettings("high")
    assert gif.quality_preset == "balanced"
