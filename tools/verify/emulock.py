"""The emulator lock: one Lichii at a time, with a lease.

The lock is a directory (`mkdir` is atomic). `owner.json` inside names the owner and says until when the lock is
valid. The owner renews the lease while it makes progress (the harness does so at every step it reports); a lock
whose lease has run out belongs to a holder that hung or forgot, and the next taker evicts it. The lease is a second
line of defence against losing time to a dead holder, after the check for a dead owner pid.

    lease: 30 minutes by default; 5 to 90 with --lock-minutes, a spec's "lock_minutes" or OOT26_LOCK_MINUTES

Standard library only, so the harness and the lock tool share it.
"""
import datetime as dt
import json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

LOCK = Path(os.environ.get("OOT26_LOCK_DIR") or Path.home() / ".local/share/lichii/verify.lock")
LEASE_DEFAULT_MIN, LEASE_MIN_MIN, LEASE_MAX_MIN = 30, 5, 90
OWNER_ENV = "OOT26_LOCK_OWNER_PID"     # set for the command that runs under `with-lock`, so it may renew the lease


def lease_minutes(minutes=None):
    """The lease length to use: the argument, else OOT26_LOCK_MINUTES, else the default; kept within 5 to 90."""
    if minutes is None:
        minutes = os.environ.get("OOT26_LOCK_MINUTES") or LEASE_DEFAULT_MIN
    return max(LEASE_MIN_MIN, min(LEASE_MAX_MIN, float(minutes)))


def pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def lichii_pids():
    """Every running Lichii (any copy). Matches the process name, so shells mentioning lichii don't count."""
    out = subprocess.run(["pgrep", "-x", "lichii"], capture_output=True, text=True).stdout.split()
    return [int(p) for p in out]


def lock_owner():
    try:
        return json.loads((LOCK / "owner.json").read_text())
    except (OSError, ValueError):
        return None


def _write_owner(owner):
    tmp = LOCK / "owner.json.tmp"
    tmp.write_text(json.dumps(owner))
    tmp.replace(LOCK / "owner.json")


def _stamp(owner, minutes):
    now = time.time()
    owner["lease_min"] = minutes
    owner["renewed"] = dt.datetime.fromtimestamp(now).isoformat(timespec="seconds")
    owner["expires_ts"] = now + minutes * 60
    owner["expires"] = dt.datetime.fromtimestamp(owner["expires_ts"]).isoformat(timespec="seconds")
    return owner


def expired(owner):
    """True when the owner's lease has run out. A lock written before leases existed never expires this way."""
    return bool(owner) and owner.get("expires_ts") is not None and time.time() > owner["expires_ts"]


def _log(text):
    line = f"{dt.datetime.now().isoformat(timespec='seconds')} pid {os.getpid()}: {text}"
    print("lock: " + text, flush=True)
    try:
        with open(LOCK.parent / (LOCK.name + ".log"), "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def _evict(owner, why):
    """Take the emulator from a holder: ask it to stop (SIGTERM, so it kills its Lichii and puts the config back),
    wait, then kill what is left (its command's process group and the Lichii it recorded) and remove the lock."""
    _log(f"evicting pid {owner.get('pid')} ({owner.get('label')}): {why}")
    pid, pgid, lichii = owner.get("pid"), owner.get("child_pgid"), owner.get("lichii_pid")
    for target, group in ((pgid, True), (pid, False)):
        if target:
            try:
                (os.killpg if group else os.kill)(target, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
    end = time.time() + 25
    while time.time() < end and LOCK.exists() and (lock_owner() or {}).get("pid") == pid and pid_alive(pid or 0):
        time.sleep(1)
    forced = []
    if pgid:
        try:
            os.killpg(pgid, signal.SIGKILL); forced.append(f"process group {pgid}")
        except (ProcessLookupError, PermissionError):
            pass
    if pid and pid_alive(pid):
        try:
            os.kill(pid, signal.SIGKILL); forced.append(f"pid {pid}")
        except (ProcessLookupError, PermissionError):
            pass
    if lichii and lichii in lichii_pids():
        try:
            os.kill(lichii, signal.SIGKILL); forced.append(f"its Lichii {lichii}")
        except (ProcessLookupError, PermissionError):
            pass
    cur = lock_owner()
    if LOCK.exists() and (cur is None or cur.get("pid") == pid):
        shutil.rmtree(LOCK, ignore_errors=True)
    _log("evicted" + (f"; had to kill {', '.join(forced)}: the emulator config may hold that run's settings until "
                      f"the next harness run restores it" if forced else " cleanly"))


def take_lock(label, app, wait_s, minutes=None):
    """Whoever creates LOCK owns the emulator, for `minutes` (see lease_minutes) unless it renews. Waits up to
    wait_s for the lock and for any Lichii this tool did not start to go away. It removes a lock whose owner is dead
    and evicts an owner whose lease has run out; it never touches a Lichii that holds no lock."""
    minutes = lease_minutes(minutes)
    deadline = time.time() + wait_s
    said = None
    while True:
        try:
            LOCK.mkdir(parents=False)
        except FileExistsError:
            owner = lock_owner()
            if owner is None:
                # Created but owner not written yet, or a crash between the two: stale after 60 s.
                age = time.time() - LOCK.stat().st_mtime if LOCK.exists() else 0
                if age > 60:
                    _log(f"removing stale lock with no owner ({age:.0f} s old)")
                    shutil.rmtree(LOCK, ignore_errors=True)
                    continue
                why = "lock being taken by someone"
            elif not pid_alive(owner["pid"]):
                _log(f"removing stale lock of dead pid {owner['pid']} ({owner.get('label')})")
                shutil.rmtree(LOCK, ignore_errors=True)
                continue
            elif expired(owner):
                _evict(owner, f"its lease ran out at {owner.get('expires')} ({owner.get('lease_min'):g} min "
                              f"after its last sign of progress at {owner.get('renewed')})")
                continue
            else:
                why = (f"lock held by pid {owner['pid']} ({owner.get('label')}, since {owner.get('started')}, "
                       f"lease until {owner.get('expires', 'unset')})")
        else:
            _write_owner(_stamp({"pid": os.getpid(), "label": label, "app": str(app),
                                 "started": dt.datetime.now().isoformat(timespec="seconds"),
                                 "lichii_pid": None, "child_pgid": None}, minutes))
            foreign = lichii_pids()
            if not foreign:
                return
            release_lock()
            why = f"a Lichii this tool did not start is running (pid {', '.join(map(str, foreign))})"
        if time.time() > deadline:
            raise SystemExit(f"lock: gave up after {wait_s} s: {why}")
        if why != said:
            print(f"lock: waiting ({why})", flush=True)
            said = why
        time.sleep(10)


def _mine(owner):
    return owner is not None and owner.get("pid") in (os.getpid(), int(os.environ.get(OWNER_ENV) or 0))


def release_lock():
    owner = lock_owner()
    if owner is None or owner["pid"] == os.getpid():
        shutil.rmtree(LOCK, ignore_errors=True)


def update_lock(**fields):
    """Set fields of owner.json (lichii_pid, child_pgid). Only for the owner or the command it runs."""
    owner = lock_owner()
    if _mine(owner):
        owner.update(fields)
        _write_owner(owner)
        return True
    return False


def set_lock_lichii(pid):
    update_lock(lichii_pid=pid)


_last_renew = 0.0


def renew_lock(minutes=None, every_s=20):
    """Push the lease out from now: call it at every sign of progress. `minutes` changes the lease length (5 to 90);
    without it the length the lock was taken with stays. Does nothing for a process that does not hold the lock, and
    writes at most once per every_s seconds. Returns True when the lease was written."""
    global _last_renew
    if time.time() - _last_renew < every_s:
        return False
    owner = lock_owner()
    if not _mine(owner):
        return False
    _stamp(owner, lease_minutes(minutes if minutes is not None else owner.get("lease_min")))
    _write_owner(owner)
    _last_renew = time.time()
    return True


def break_lock(reason):
    """Evict the holder now, whatever its lease says. For a holder that is plainly stuck or wrong; the reason goes to
    the log beside the lock."""
    owner = lock_owner()
    if owner is None:
        if LOCK.exists():
            _log(f"removing lock with no owner file: {reason}")
            shutil.rmtree(LOCK, ignore_errors=True)
            return True
        print("lock: free, nothing to break")
        return False
    _evict(owner, f"broken by hand: {reason}")
    return True


def status():
    """One line for people, and a code: 0 free, 1 held, 2 held but the lease has run out or the owner is dead."""
    owner = lock_owner()
    running = lichii_pids()
    tail = f"; running Lichii pids: {running or 'none'}"
    if owner is None:
        return (f"lock {LOCK}: " + ("held, no owner file" if LOCK.exists() else "free") + tail, 1 if LOCK.exists() else 0)
    if not pid_alive(owner["pid"]):
        return (f"lock {LOCK}: stale, owner pid {owner['pid']} is dead ({owner.get('label')}); the next taker "
                f"removes it" + tail, 2)
    left = (owner["expires_ts"] - time.time()) / 60 if owner.get("expires_ts") is not None else None
    lease = ("no lease recorded" if left is None else
             f"lease ran out {-left:.0f} min ago; the next taker evicts it" if left < 0 else
             f"lease until {owner.get('expires')} ({left:.0f} min left, {owner.get('lease_min'):g} min from each "
             f"sign of progress)")
    return (f"lock {LOCK}: held by pid {owner['pid']} ({owner.get('label')}) since {owner.get('started')}; {lease}; "
            f"its Lichii: {owner.get('lichii_pid') or 'none recorded'}" + tail, 2 if left is not None and left < 0 else 1)
