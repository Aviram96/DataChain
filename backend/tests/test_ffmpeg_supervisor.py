"""Tests for FFmpeg supervisor restart behavior."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.ffmpeg_supervisor import (
    FFmpegRunConfig,
    FFmpegSupervisor,
    resolve_max_restarts,
    resolve_restart_delay_seconds,
)


def test_resolve_restart_settings_defaults(monkeypatch) -> None:
    monkeypatch.delenv("CCTV_FFMPEG_RESTART_DELAY_SECONDS", raising=False)
    monkeypatch.delenv("CCTV_FFMPEG_MAX_RESTARTS", raising=False)
    assert resolve_restart_delay_seconds() == 2.0
    assert resolve_max_restarts() is None


def test_embedded_run_does_not_install_signal_handlers() -> None:
    process = MagicMock(
        wait=MagicMock(return_value=0),
        stderr=None,
        poll=MagicMock(return_value=0),
        pid=1,
    )
    config = FFmpegRunConfig(
        build_command=lambda: ["ffmpeg", "-version"],
        restart_on_crash=False,
        install_signal_handlers=False,
    )
    with (
        patch("app.services.ffmpeg_supervisor.signal.signal") as install,
        patch(
            "app.services.ffmpeg_supervisor.subprocess.Popen",
            return_value=process,
        ),
    ):
        assert FFmpegSupervisor(config).run_until_signal() == 0
    install.assert_not_called()


def test_supervisor_restarts_after_crash() -> None:
    processes = [
        MagicMock(
            wait=MagicMock(return_value=1), stderr=None, poll=MagicMock(return_value=1)
        ),
        MagicMock(
            wait=MagicMock(return_value=0), stderr=None, poll=MagicMock(return_value=0)
        ),
    ]
    build_count = {"n": 0}

    def build_command() -> list[str]:
        build_count["n"] += 1
        return ["ffmpeg", "-version"]

    config = FFmpegRunConfig(
        build_command=build_command,
        restart_on_crash=True,
        restart_delay_seconds=0,
    )
    supervisor = FFmpegSupervisor(config)

    with patch(
        "app.services.ffmpeg_supervisor.subprocess.Popen", side_effect=processes
    ):
        code = supervisor.run_until_signal()

    assert code == 0
    assert supervisor.restart_count == 1
    assert build_count["n"] == 2


def test_supervisor_does_not_restart_on_success() -> None:
    proc = MagicMock(
        wait=MagicMock(return_value=0), stderr=None, poll=MagicMock(return_value=0)
    )
    build_count = {"n": 0}

    def build_command() -> list[str]:
        build_count["n"] += 1
        return ["ffmpeg"]

    config = FFmpegRunConfig(build_command=build_command, restart_on_crash=True)
    supervisor = FFmpegSupervisor(config)

    with patch("app.services.ffmpeg_supervisor.subprocess.Popen", return_value=proc):
        code = supervisor.run_until_signal()

    assert code == 0
    assert supervisor.restart_count == 0
    assert supervisor.gave_up_after_restarts is False
    assert build_count["n"] == 1


def test_supervisor_respects_max_restarts() -> None:
    proc = MagicMock(
        wait=MagicMock(return_value=1), stderr=None, poll=MagicMock(return_value=1)
    )
    config = FFmpegRunConfig(
        build_command=lambda: ["ffmpeg"],
        restart_on_crash=True,
        restart_delay_seconds=0,
        max_restarts=2,
    )
    supervisor = FFmpegSupervisor(config)

    with patch("app.services.ffmpeg_supervisor.subprocess.Popen", return_value=proc):
        code = supervisor.run_until_signal()

    assert code == 1
    assert supervisor.restart_count == 2
    assert supervisor.gave_up_after_restarts is True


def test_signal_handler_does_not_wait_twice() -> None:
    import signal

    handlers = {}
    proc = MagicMock()
    proc.poll.return_value = None
    proc.stderr = None

    def fake_signal(sig, handler):
        handlers[sig] = handler
        return signal.SIG_DFL

    def fake_wait(*args, **kwargs):
        if not getattr(fake_wait, "signal_sent", False):
            fake_wait.signal_sent = True
            handlers[signal.SIGINT](signal.SIGINT, None)
        return 0

    proc.wait.side_effect = fake_wait

    supervisor = FFmpegSupervisor(
        FFmpegRunConfig(
            build_command=lambda: ["ffmpeg"],
            restart_on_crash=True,
        )
    )

    with (
        patch("app.services.ffmpeg_supervisor.subprocess.Popen", return_value=proc),
        patch("app.services.ffmpeg_supervisor.signal.signal", side_effect=fake_signal),
    ):
        supervisor.run_until_signal()

    assert proc.wait.call_count == 1
    assert supervisor.restart_count == 0


def test_supervisor_graceful_stop_sends_q() -> None:
    proc = MagicMock()
    proc.poll.return_value = None
    proc.stdin = MagicMock()
    proc.stderr = None

    supervisor = FFmpegSupervisor(
        FFmpegRunConfig(
            build_command=lambda: ["ffmpeg"],
            graceful_stop=True,
        )
    )

    supervisor._process = proc
    supervisor.stop()

    proc.stdin.write.assert_called_once_with(b"q\n")
    proc.stdin.flush.assert_called_once()


def test_supervisor_forces_termination_after_graceful_timeout() -> None:
    import subprocess

    proc = MagicMock()
    proc.poll.return_value = None
    proc.stderr = None
    proc.stdin = MagicMock()

    wait_calls = {"count": 0}

    def fake_wait(*args, **kwargs):
        wait_calls["count"] += 1

        if wait_calls["count"] == 1:
            raise subprocess.TimeoutExpired(
                cmd=["ffmpeg"],
                timeout=kwargs.get("timeout", 5),
            )

        return 0

    proc.wait.side_effect = fake_wait

    supervisor = FFmpegSupervisor(
        FFmpegRunConfig(
            build_command=lambda: ["ffmpeg"],
            graceful_stop=True,
        )
    )

    supervisor._process = proc
    supervisor.stop()

    proc.stdin.write.assert_called_once_with(b"q\n")
    proc.terminate.assert_called_once()
    assert proc.wait.call_count == 2


def test_supervisor_timeout_after_signal() -> None:
    import signal
    import subprocess
    from unittest.mock import patch

    handlers = {}
    proc = MagicMock()
    proc.poll.return_value = None
    proc.stderr = None
    proc.stdin = MagicMock()

    def fake_signal(sig, handler):
        handlers[sig] = handler
        return signal.SIG_DFL

    calls = {"count": 0}

    def fake_wait(*args, **kwargs):
        calls["count"] += 1

        if calls["count"] == 1:
            handlers[signal.SIGINT](signal.SIGINT, None)

        if proc.terminate.called:
            return -15

        raise subprocess.TimeoutExpired(
            cmd=["ffmpeg"],
            timeout=kwargs.get("timeout", 0.5),
        )

    proc.wait.side_effect = fake_wait

    supervisor = FFmpegSupervisor(
        FFmpegRunConfig(
            build_command=lambda: ["ffmpeg"],
            graceful_stop=True,
        )
    )

    with (
        patch("app.services.ffmpeg_supervisor.subprocess.Popen", return_value=proc),
        patch("app.services.ffmpeg_supervisor.signal.signal", side_effect=fake_signal),
        patch("app.services.ffmpeg_supervisor.time.monotonic", side_effect=[0, 6]),
    ):
        supervisor.run_until_signal()

    proc.stdin.write.assert_called_once_with(b"q\n")
    proc.terminate.assert_called_once()
    assert supervisor.restart_count == 0


def test_exit_hook_runs_once_per_process_after_crash_and_restart() -> None:
    crashed = MagicMock(
        wait=MagicMock(return_value=1),
        stderr=None,
        poll=MagicMock(return_value=1),
    )
    clean = MagicMock(
        wait=MagicMock(return_value=0),
        stderr=None,
        poll=MagicMock(return_value=0),
    )
    processes = [crashed, clean]
    events: list[tuple[str, int | None]] = []
    crashed.pid = 11
    clean.pid = 22

    def build_command() -> list[str]:
        events.append(("build", None))
        return ["ffmpeg", "-version"]

    def on_start(pid: int) -> None:
        events.append(("start", pid))

    def on_exit(code: int) -> None:
        events.append(("exit", code))

    config = FFmpegRunConfig(
        build_command=build_command,
        restart_on_crash=True,
        restart_delay_seconds=0,
        on_process_start=on_start,
        on_process_exit=on_exit,
    )
    supervisor = FFmpegSupervisor(config)

    with patch(
        "app.services.ffmpeg_supervisor.subprocess.Popen",
        side_effect=processes,
    ):
        code = supervisor.run_until_signal()

    assert code == 0
    assert events == [
        ("build", None),
        ("start", 11),
        ("exit", 1),
        ("build", None),
        ("start", 22),
        ("exit", 0),
    ]


def test_exit_hook_failure_does_not_stop_the_supervisor() -> None:
    proc = MagicMock(
        wait=MagicMock(return_value=0),
        stderr=None,
        poll=MagicMock(return_value=0),
    )

    def on_exit(_code: int) -> None:
        raise RuntimeError("marker disk full")

    config = FFmpegRunConfig(
        build_command=lambda: ["ffmpeg"],
        on_process_exit=on_exit,
    )
    supervisor = FFmpegSupervisor(config)

    with patch(
        "app.services.ffmpeg_supervisor.subprocess.Popen",
        return_value=proc,
    ):
        assert supervisor.run_until_signal() == 0


def test_supervisor_reads_stderr_lines(caplog) -> None:
    import io
    import logging

    proc = MagicMock()
    proc.stderr = io.BytesIO(b"First FFmpeg warning\nSecond FFmpeg warning\n")

    with caplog.at_level(logging.WARNING):
        FFmpegSupervisor._log_stderr(proc)

    assert "First FFmpeg warning" in caplog.text
    assert "Second FFmpeg warning" in caplog.text
