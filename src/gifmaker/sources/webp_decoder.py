"""Decode animated WebP with the libwebpdemux animation API."""
from __future__ import annotations

import ctypes
import ctypes.util
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtGui import QImage

from gifmaker.sources.model import LoadedSource, SourceFrame, SourceInfo


class WebPData(ctypes.Structure):
    _fields_ = [("bytes", ctypes.POINTER(ctypes.c_uint8)), ("size", ctypes.c_size_t)]


class WebPAnimInfo(ctypes.Structure):
    _fields_ = [("width", ctypes.c_uint32), ("height", ctypes.c_uint32),
                ("loop", ctypes.c_uint32), ("background", ctypes.c_uint32),
                ("count", ctypes.c_uint32), ("pad", ctypes.c_uint32 * 4)]


def load_reference_webp(path: Path) -> LoadedSource:
    name = ctypes.util.find_library("webpdemux")
    if not name:
        raise RuntimeError("libwebpdemux is unavailable")
    lib = ctypes.CDLL(name)
    lib.WebPAnimDecoderNewInternal.argtypes = [ctypes.POINTER(WebPData), ctypes.c_void_p, ctypes.c_int]
    lib.WebPAnimDecoderNewInternal.restype = ctypes.c_void_p
    lib.WebPAnimDecoderGetInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(WebPAnimInfo)]
    lib.WebPAnimDecoderHasMoreFrames.argtypes = [ctypes.c_void_p]
    lib.WebPAnimDecoderGetNext.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.POINTER(ctypes.c_uint8)), ctypes.POINTER(ctypes.c_int)]
    lib.WebPAnimDecoderDelete.argtypes = [ctypes.c_void_p]
    payload = path.read_bytes()
    data_buffer = (ctypes.c_uint8 * len(payload)).from_buffer_copy(payload)
    data = WebPData(data_buffer, len(payload))
    decoder = lib.WebPAnimDecoderNewInternal(ctypes.byref(data), None, 0x0107)
    if not decoder:
        raise ValueError("libwebp could not decode animation")
    temporary = None
    try:
        info = WebPAnimInfo()
        if not lib.WebPAnimDecoderGetInfo(decoder, ctypes.byref(info)) or info.count < 2:
            raise ValueError("Expected an animation with at least two frames")
        temporary = TemporaryDirectory(prefix="webp-reference-")
        frames = []
        previous = 0
        while lib.WebPAnimDecoderHasMoreFrames(decoder):
            buffer = ctypes.POINTER(ctypes.c_uint8)()
            timestamp = ctypes.c_int()
            if not lib.WebPAnimDecoderGetNext(decoder, ctypes.byref(buffer), ctypes.byref(timestamp)):
                raise ValueError("libwebp failed to decode a frame")
            if timestamp.value <= previous:
                raise ValueError("Frame has unsupported duration")
            raw = ctypes.string_at(buffer, info.width * info.height * 4)
            image = QImage(raw, info.width, info.height, info.width * 4, QImage.Format.Format_RGBA8888)
            frame = Path(temporary.name) / f"frame-{len(frames):08d}.png"
            if not image.save(str(frame), "PNG"):
                raise OSError("Could not save frame")
            frames.append(SourceFrame(frame, previous, timestamp.value - previous))
            previous = timestamp.value
        if len(frames) != info.count:
            raise ValueError("Incomplete animation")
        metadata = SourceInfo(previous / 1000, info.width, info.height, "webp", len(frames) * 1000 / previous)
        result = LoadedSource(path.resolve(), metadata, frames=tuple(frames), temporary_directory=temporary)
        temporary = None
        return result
    finally:
        lib.WebPAnimDecoderDelete(decoder)
        if temporary is not None:
            temporary.cleanup()
