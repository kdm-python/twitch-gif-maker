"""Exercise source playback using exact fixture frame times and a fake clock."""
import os
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from gifmaker.sources import load_source
from gifmaker.sources.animation_player import AnimationSourcePlayer

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
FIXTURE = Path(__file__).parent / "fixtures/webp_input/variable_delays.webp"


@pytest.fixture
def setup_player():
    app = QApplication.instance() or QApplication([])
    now = [10.0]
    source = load_source(FIXTURE)
    player = AnimationSourcePlayer(clock=lambda: now[0])
    colors, positions, states, errors = [], [], [], []
    player.frameChanged.connect(lambda image: colors.append(image.pixelColor(0, 0).name()))
    player.positionChanged.connect(positions.append)
    player.playingChanged.connect(states.append)
    player.errorOccurred.connect(errors.append)
    player.set_source(source)
    yield player, source, now, colors, positions, states, errors
    player.clear()
    source.close()
    app.processEvents()


def test_seek_frame_boundaries_and_endpoint(setup_player):
    player, _, _, colors, positions, _, _ = setup_player
    assert player.duration_ms == 750
    for time in (99, 100, 349, 350, 750):
        player.seek(time)
    assert colors == ["#ff0000", "#00ff00", "#0000ff"]
    assert positions == [0, 99, 100, 349, 350, 750]
    player.seek(-1)
    assert player.position_ms == 0
    player.seek(9999)
    assert player.position_ms == 750


def test_play_pause_resume_and_late_timer(setup_player):
    player, _, now, colors, positions, states, _ = setup_player
    player.play()
    now[0] += 0.15
    player._tick()
    assert player.position_ms == 150
    assert colors[-1] == "#00ff00"
    player.pause()
    now[0] += 2
    assert player.position_ms == 150
    player.play()
    now[0] += 0.7
    player._tick()
    assert player.position_ms == 750
    assert colors[-1] == "#0000ff"
    assert states == [True, False, True, False]
    assert positions[-1] == 750
    player.play()
    assert player.position_ms == 0
    assert colors[-1] == "#ff0000"


def test_seek_and_rate_while_playing(setup_player):
    player, _, now, colors, _, _, _ = setup_player
    player.play()
    player.seek(100)
    player.set_playback_rate(2)
    now[0] += 0.15
    player._tick()
    assert 399 <= player.position_ms <= 400
    assert colors[-1] == "#0000ff"
    player.seek(750)
    assert not player.playing
    with pytest.raises(ValueError):
        player.set_playback_rate(float("nan"))


def test_source_lifetime_and_failed_replacement(setup_player, tmp_path):
    player, source, _, _, _, _, errors = setup_player
    player.play()
    source.close()
    player._tick()
    assert not player.playing
    assert errors == ["Source is closed"]
    with pytest.raises(ValueError):
        player.set_source(source)
    assert player.duration_ms == 750


def test_real_qt_timer_advances_and_stops():
    from PySide6.QtCore import QEventLoop, QTimer

    app = QApplication.instance() or QApplication([])
    with load_source(FIXTURE) as source:
        player = AnimationSourcePlayer()
        loop = QEventLoop()
        positions = []
        player.positionChanged.connect(positions.append)
        player.playingChanged.connect(lambda active: loop.quit() if not active else None)
        player.set_source(source)
        player.play()
        QTimer.singleShot(2500, loop.quit)
        loop.exec()
        assert not player.playing
        assert positions[-1] == 750
        assert any(100 <= position < 350 for position in positions)
        player.clear()
    app.processEvents()


def test_missing_frame_stops_playback_with_error(setup_player):
    player, source, now, _, _, _, errors = setup_player
    source.frames[1].path.unlink()
    player.play()
    now[0] += 0.2
    player._tick()
    assert not player.playing
    assert errors == ["Source frame could not be read"]
