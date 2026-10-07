"""Stopping a video's work: the processes each job has running, so the Stop button can end them.

A job's thread sets `current.jid`; whatever it starts (Whisper, the music remover, Claude, ffmpeg)
registers here. stop() ends them all and marks the job, and the job's next step sees it and stops.
"""
import threading

current = threading.local()
_lock = threading.Lock()
_running = {}        # jid -> set of Popen
_stopping = set()


class Stopped(Exception):
    pass


def register(p):
    jid = getattr(current, "jid", None)
    if jid:
        with _lock:
            _running.setdefault(jid, set()).add(p)


def unregister(p):
    jid = getattr(current, "jid", None)
    if jid:
        with _lock:
            _running.get(jid, set()).discard(p)


def stop(jid):
    with _lock:
        _stopping.add(jid)
        procs = list(_running.get(jid, ()))
    for p in procs:
        try:
            p.kill()
        except OSError:
            pass
    return len(procs)


def check(jid=None):
    """Raise Stopped if the Stop button was pressed for this job."""
    jid = jid or getattr(current, "jid", None)
    if jid and jid in _stopping:
        raise Stopped()


def stopped(jid):
    return jid in _stopping


def clear(jid):
    with _lock:
        _stopping.discard(jid)
        _running.pop(jid, None)
