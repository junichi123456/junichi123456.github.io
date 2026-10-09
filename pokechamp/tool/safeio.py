"""File writes that survive Windows file locking.

On Windows os.replace fails with PermissionError while another process (a reader such as wait_event.py or
Claude, an antivirus scan, a cloud-sync client) has the destination open. These helpers retry for a while and
then fall back to writing the destination directly instead of crashing the caller.
"""
import json, os, time


def replace(tmp, dst, tries=40, wait=0.05):
    """os.replace with retries. Returns True on success."""
    for _ in range(tries):
        try:
            os.replace(tmp, dst)
            return True
        except PermissionError:
            time.sleep(wait)
    return False


def write_json(path, obj, **dump_kw):
    """Atomically write JSON when possible; returns True if the file was written."""
    dump_kw.setdefault('ensure_ascii', False)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, **dump_kw)
    if replace(tmp, path):
        return True
    try:  # still locked for renaming: overwrite in place
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(obj, f, **dump_kw)
        return True
    except OSError:
        return False
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
