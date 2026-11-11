from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from gifmaker.gui.preview_controller import PreviewController


def test_preview_controller_delegates_playback_and_owns_artifact_cleanup(tmp_path: Path):
    artifact = tmp_path / "preview.gif"
    artifact.write_bytes(b"preview")
    window = SimpleNamespace(
        _preview_temp_file=artifact,
        _last_preview_settings=object(),
        _last_preview_source="source.mp4",
        _last_preview_spec=object(),
    )
    player = Mock()
    controller = PreviewController(window, player=player)

    controller.load(artifact)
    controller.set_playback_speed(1.5)
    controller.play()
    controller.pause()
    controller.clear(remove_temp_file=True)

    player.load.assert_called_once_with(artifact)
    player.set_playback_speed.assert_called_once_with(1.5)
    player.play.assert_called_once_with()
    player.pause.assert_called_once_with()
    player.clear.assert_called_once_with()
    assert not artifact.exists()
    assert window._preview_temp_file is None
    assert window._last_preview_spec is None


def test_clear_can_leave_artifact_on_disk(tmp_path: Path):
    artifact = tmp_path / "preview.gif"
    artifact.touch()
    window = SimpleNamespace(_preview_temp_file=artifact, _last_preview_settings=None,
                             _last_preview_source=None, _last_preview_spec=None)
    controller = PreviewController(window, player=Mock())
    controller.clear(remove_temp_file=False)
    assert artifact.exists()
