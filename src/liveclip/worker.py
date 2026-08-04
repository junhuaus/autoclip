from __future__ import annotations

import signal
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from types import FrameType

from liveclip.application.stage_runner import RunOneOutcome
from liveclip.bootstrap import LiveClipRuntime, local_worker_id
from liveclip.config import Settings, get_settings


class WorkerShutdown(KeyboardInterrupt):
    """Interrupt durable work so owned subprocess groups can unwind safely."""

    def __init__(self, signal_number: int):
        super().__init__(f"worker received signal {signal_number}")
        self.signal_number = signal_number


def _raise_worker_shutdown(signal_number: int, _frame: FrameType | None) -> None:
    raise WorkerShutdown(signal_number)


@contextmanager
def worker_signal_handlers() -> Iterator[None]:
    """Install explicit handlers even when a background shell ignored SIGINT."""

    if threading.current_thread() is not threading.main_thread():
        yield
        return
    watched = (signal.SIGINT, signal.SIGTERM)
    previous = {value: signal.getsignal(value) for value in watched}
    try:
        for value in watched:
            signal.signal(value, _raise_worker_shutdown)
        yield
    finally:
        for value, handler in previous.items():
            signal.signal(value, handler)


def run_worker(
    settings: Settings,
    *,
    once: bool = False,
    poll_seconds: float = 0.5,
) -> int:
    if poll_seconds <= 0 or poll_seconds > 5:
        raise ValueError("worker poll interval must be between zero and five seconds")
    worker_id = local_worker_id("worker")
    try:
        with worker_signal_handlers(), LiveClipRuntime.open(settings) as runtime:
            print(f"LiveClip worker started: {worker_id}", flush=True)
            while True:
                outcome = runtime.stage_runner.run_one(worker_id=worker_id)
                if outcome == RunOneOutcome.BUSY:
                    handled = False
                elif outcome == RunOneOutcome.IDLE:
                    render_outcome = runtime.render_runner.run_one(worker_id=worker_id)
                    if render_outcome.value == RunOneOutcome.BUSY.value:
                        handled = False
                    elif render_outcome.value == RunOneOutcome.IDLE.value:
                        delivery_outcome = runtime.delivery_runner.run_one(worker_id=worker_id)
                        handled = delivery_outcome.value not in {
                            RunOneOutcome.IDLE.value,
                            RunOneOutcome.BUSY.value,
                        }
                    else:
                        handled = True
                else:
                    handled = True
                if once:
                    return 0
                if not handled:
                    threading.Event().wait(poll_seconds)
    except WorkerShutdown as exc:
        print("LiveClip worker stopped", flush=True)
        return 128 + exc.signal_number


def main() -> None:
    raise SystemExit(run_worker(get_settings()))


if __name__ == "__main__":
    main()
