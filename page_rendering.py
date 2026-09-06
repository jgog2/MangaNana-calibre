"""Bounded ordered rendering. No providers, Qt, layout decisions or ZIP writes."""
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import os
from threading import Event, Lock
from time import perf_counter
try:
    from . import native_dithering
except ImportError:
    import native_dithering


def worker_count(cpu_count=None):
    count = os.cpu_count() if cpu_count is None else cpu_count
    return min(4, max(1, (count or 2)//2))


def final_workers(settings):
    if (settings.output_depth and settings.dithering != 'off' and settings.dither_strength > 0
            and native_dithering.get_backend() is not None):
        return worker_count()
    return 1


def ordered_render(jobs, render, workers=1, check_cancel=lambda: None,
                   completed=lambda count: None, metrics=None, fallback_active=None):
    """Yield (index,result) in order; completed counts finished, not submitted jobs.

    Submitted + completed-but-not-written is bounded to workers*2. Callbacks and
    consumption happen on the owner thread. Running work cooperatively stops on
    error/cancel. If native fails mid-batch, callback gates portable loops serially.
    """
    if not 1 <= workers <= 4: raise ValueError('Expected 1–4 render workers')
    metrics = metrics if metrics is not None else {}
    metrics.update(workers=workers, peak_outstanding=0, completed=0, render_seconds=0.0)
    stopped = Event(); portable = Lock(); failure_lock = Lock(); failures = []

    def check_failure():
        with failure_lock:
            if failures: raise failures[0]

    def execute(job):
        owns_portable = False
        def check():
            nonlocal owns_portable
            check_cancel()
            if stopped.is_set(): raise InterruptedError('Rendering stopped')
            if workers > 1 and fallback_active and fallback_active() and not owns_portable:
                while not portable.acquire(timeout=.05):
                    check_cancel()
                    if stopped.is_set(): raise InterruptedError('Rendering stopped')
                owns_portable = True
        try:
            check()
            return render(job, check)
        except BaseException as exc:
            with failure_lock:
                if not failures: failures.append(exc)
            stopped.set()
            raise
        finally:
            if owns_portable: portable.release()

    if workers == 1:
        for index, job in enumerate(jobs):
            check_cancel(); start = perf_counter()
            result = execute(job)
            metrics['render_seconds'] += perf_counter()-start
            metrics['peak_outstanding'] = 1
            metrics['completed'] += 1; completed(metrics['completed'])
            yield index, result
        return

    pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix='MangaNana-render')
    pending = {}; ready = {}; source = iter(enumerate(jobs)); exhausted = False; next_index = 0
    start = perf_counter()
    try:
        while True:
            check_failure()
            check_cancel()
            while not exhausted and len(pending)+len(ready) < workers*2:
                check_failure()
                try: index, job = next(source)
                except StopIteration: exhausted = True; break
                pending[pool.submit(execute, job)] = index
                metrics['peak_outstanding'] = max(metrics['peak_outstanding'], len(pending)+len(ready))
            if not pending and not ready: break
            if pending:
                done, _ = wait(pending, timeout=.05, return_when=FIRST_COMPLETED)
                check_failure()
                # Inspect all finished jobs before scheduling any more work.
                for future in done:
                    ready[pending.pop(future)] = future.result()
                    metrics['completed'] += 1; completed(metrics['completed'])
                    metrics['render_seconds'] = perf_counter()-start
            while next_index in ready:
                check_cancel()
                yield next_index, ready.pop(next_index)
                next_index += 1
    finally:
        stopped.set()
        for future in pending: future.cancel()
        pool.shutdown(wait=True, cancel_futures=True)
