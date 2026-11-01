"""Smoke-test the frozen exe: startup, settings window, clean shutdown.

GUI 进程在沙箱里不能用 `&` / Start-Process 等退出码，这里统一走 subprocess。
"""

import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXE = os.path.join(ROOT, "dist", "桌面宠物", "桌面宠物.exe")
LOG = os.path.join(os.path.dirname(EXE), "pet_error.log")


def run(args, limit=90):
    started = time.time()
    proc = subprocess.Popen([EXE] + args,
                            cwd=os.path.dirname(EXE),
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    try:
        out, err = proc.communicate(timeout=limit)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        print("TIMEOUT after %.1fs" % (time.time() - started))
        return 1
    took = time.time() - started
    print("args=%s rc=%s elapsed=%.1fs" % (args, proc.returncode, took))
    if out.strip():
        print("stdout:", out.decode("utf-8", "replace")[-800:])
    if err.strip():
        print("stderr:", err.decode("utf-8", "replace")[-1200:])
    return proc.returncode


def main():
    if not os.path.isfile(EXE):
        print("missing exe:", EXE)
        return 1
    if os.path.isfile(LOG):
        os.remove(LOG)
    ok = True
    ok = run(["--selftest", "5000", "--no-ai"]) == 0 and ok
    ok = run(["--settings", "--selftest", "6000", "--no-ai"]) == 0 and ok
    size = 0
    if os.path.isfile(LOG):
        size = os.path.getsize(LOG)
        if size:
            with open(LOG, encoding="utf-8", errors="replace") as fh:
                print("--- pet_error.log")
                print(fh.read()[-3000:])
    print("pet_error.log bytes:", size)
    ok = ok and size == 0
    print("EXE CHECK OK" if ok else "EXE CHECK FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
