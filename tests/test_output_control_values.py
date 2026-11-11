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
