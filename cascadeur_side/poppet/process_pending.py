"""Cascadeur command: Poppet -> Process Pending.

Drains all pending request files in the requests directory:
  - For each <uuid>.json: load JSON, dispatch via _dispatchers.dispatch(),
    write response to responses/<uuid>.json, delete the request file.
  - Log a summary to dispatcher.log + Cascadeur's event log.

This is the manual-drain heart of the file-sync architecture (since Cascadeur
2025.3.3 has no usable in-process scheduler: PySide isn't bundled, csc has
no main-thread event-post API, and background Python threads only get one
GIL slice at creation).

The MCP server writes request files and polls response files. The user (or
an auto-nudge mechanism) clicks this command to drain the queue.
"""

import json
import os
import time
import traceback

from . import _paths
from ._dispatchers import dispatch


def command_name():
    return "Poppet.Process Pending"


def run(scene):
    req_dir = _paths.requests_dir()
    resp_dir = _paths.responses_dir()
    log_path = _paths.dispatcher_log_path()

    def log(msg):
        line = "{} {}".format(time.strftime("%H:%M:%S"), msg)
        print("[poppet] " + line)
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

    pending = sorted(f for f in os.listdir(req_dir) if f.endswith(".json"))
    if not pending:
        log("Process Pending: no requests")
        return

    log(f"Process Pending: draining {len(pending)} request(s)")
    ok = 0
    err = 0

    for fname in pending:
        req_path = os.path.join(req_dir, fname)
        uuid = fname[:-5]  # strip .json
        try:
            with open(req_path, encoding="utf-8") as f:
                message = json.load(f)
        except Exception as e:
            response = {
                "status": "error",
                "message": f"could not read request {fname}: {e}",
            }
            err += 1
        else:
            try:
                response = dispatch(message, scene)
                if response.get("status") == "success":
                    ok += 1
                else:
                    err += 1
            except Exception as e:
                response = {
                    "status": "error",
                    "message": f"dispatch crashed: {type(e).__name__}: {e}",
                    "traceback": traceback.format_exc(),
                }
                err += 1

        resp_path = os.path.join(resp_dir, uuid + ".json")
        try:
            # Write to .tmp then rename — atomic on Windows + POSIX.
            tmp_path = resp_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(response, f, ensure_ascii=False)
            os.replace(tmp_path, resp_path)
        except Exception as e:
            log(f"failed writing response {uuid}: {e}")

        try:
            os.remove(req_path)
        except Exception as e:
            log(f"failed removing request {fname}: {e}")

    log(f"Process Pending: done — ok={ok} err={err}")
