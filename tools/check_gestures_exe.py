"""Check gestures in the packaged exe.

exe 是 GUI 进程：在沙箱里不能直接 `& exe` 等退出码，要用 subprocess.Popen。
`--gesture-selftest` 会用真光标划一遍宠物（约两秒里光标被借走），把命中
结果写进 exe 目录的 pet_gesture_check.log，这里读回来逐项断言。
"""

import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXE = os.path.join(ROOT, "dist", "桌面宠物", "桌面宠物.exe")
LOG = os.path.join(ROOT, "dist", "桌面宠物", "pet_gesture_check.log")


def main():
    if not os.path.exists(EXE):
        print("missing exe:", EXE)
        return 1
    if os.path.exists(LOG):
        os.remove(LOG)
    t0 = time.time()
    proc = subprocess.Popen([EXE, "--gesture-selftest", "--no-ai", "--no-bubble"],
                            cwd=os.path.dirname(EXE))
    rc = proc.wait(timeout=60)
    print("exe rc=%s elapsed=%.1fs" % (rc, time.time() - t0))
    if not os.path.exists(LOG):
        print("no gesture log written")
        return 1
    with open(LOG, encoding="utf-8") as fh:
        text = fh.read()
    print(text.strip())
    hits = {}
    for line in text.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            try:
                hits[key] = int(value)
            except ValueError:
                hits[key] = value
    ok = (rc == 0
          and hits.get("squash", 0) >= 1
          and hits.get("jump", 0) >= 1
          and "error" not in hits)
    print("EXE GESTURE OK" if ok else "EXE GESTURE FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
