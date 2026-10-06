"""Tests for export-output estimation helpers."""

from gifmaker.models.render_estimate import calculate_render_estimate, format_file_size


def test_render_estimate_uses_output_speed_for_duration_and_frame_count() -> None:
    estimate = calculate_render_estimate(
        source_duration_seconds=4.0,
        fps=24,
        playback_speed=2.0,
        width=640,
        height=360,
        output_format="GIF",
        quality_preset="balanced",
    )

    assert estimate.duration_seconds == 2.0
    assert estimate.frame_count == 48
    assert estimate.estimated_bytes > 0
    assert format_file_size(estimate.estimated_bytes).endswith("MB")


def test_small_webp_estimate_is_smaller_than_high_quality_gif() -> None:
    common = {
        "source_duration_seconds": 2.0,
        "fps": 24,
        "playback_speed": 1.0,
        "width": 640,
        "height": 360,
    }
    small_webp = calculate_render_estimate(
        **common, output_format="WebP", quality_preset="small"
    )
    high_gif = calculate_render_estimate(
        **common, output_format="GIF", quality_preset="high"
    )

    assert small_webp.estimated_bytes < high_gif.estimated_bytes
