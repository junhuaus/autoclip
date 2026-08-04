from __future__ import annotations

import threading

from liveclip.application.stage_runner import RunOneOutcome
from liveclip.bootstrap import LiveClipRuntime, local_worker_id
from liveclip.config import Settings, get_settings


def run_worker(
    settings: Settings,
    *,
    once: bool = False,
    poll_seconds: float = 0.5,
) -> int:
    if poll_seconds <= 0 or poll_seconds > 5:
        raise ValueError("worker poll interval must be between zero and five seconds")
    worker_id = local_worker_id("worker")
    with LiveClipRuntime.open(settings) as runtime:
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


def main() -> None:
    try:
        raise SystemExit(run_worker(get_settings()))
    except KeyboardInterrupt:
        print("LiveClip worker stopped", flush=True)


if __name__ == "__main__":
    main()
