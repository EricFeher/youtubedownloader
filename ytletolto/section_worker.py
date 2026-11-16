"""Részletletöltés külön folyamatban, az ffmpeg-gyerekfolyamat megszakításával."""

from __future__ import annotations

import multiprocessing
import os
import queue
import signal
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path

from .downloader import DownloadRequest, Downloader, Event, Finished, Tools, _download_workspace


def _run(request: DownloadRequest, tools: Tools, events, temp_dir: Path) -> None:
    if os.name != "nt":
        os.setsid()
    try:
        Downloader(events.put, tools, _inline_sections=True, _temp_dir=temp_dir).run(request)
    except Exception as exc:
        events.put(Finished(False, f"Nem sikerült letölteni a részletet: {exc}"))


def _stop(process) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, check=False)
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            if process.is_alive():
                process.terminate()  # a worker még nem érte el a setsid-et
    process.join(timeout=2)
    if os.name != "nt":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.is_alive():
        process.kill()
        process.join(timeout=2)


def download_section(request: DownloadRequest, tools: Tools, emit: Callable[[Event], None], cancel: threading.Event) -> Finished:
    if cancel.is_set():
        return Finished(False, "Letöltés megszakítva.")
    request.output_dir.mkdir(parents=True, exist_ok=True)
    # A szülő takarít, miután a worker és az ffmpeg is leállt, kényszerített megszakításkor is.
    with _download_workspace(request) as temp_dir:
        return _download_section(request, tools, emit, cancel, Path(temp_dir).resolve())


def _download_section(request: DownloadRequest, tools: Tools, emit: Callable[[Event], None],
                      cancel: threading.Event, temp_dir: Path) -> Finished:
    context = multiprocessing.get_context("spawn")
    events = context.Queue()
    process = context.Process(target=_run, args=(request, tools, events, temp_dir))
    try:
        if cancel.is_set():
            return Finished(False, "Letöltés megszakítva.")
        process.start()
        while True:
            if cancel.is_set():
                _stop(process)
                return Finished(False, "Letöltés megszakítva.")
            try:
                event = events.get(timeout=0.1)
            except queue.Empty:
                if process.is_alive():
                    continue
                return Finished(False, "A részletletöltés váratlanul leállt.")
            if isinstance(event, Finished):
                return event
            emit(event)
    finally:
        if process.pid is not None:
            process.join(timeout=2)
            if process.is_alive():
                _stop(process)
            process.close()
        events.close()
        events.join_thread()
