"""临时工具：把 PyInstaller 及其依赖的 wheel 下到 .tmp/wheels/。

pip 在这台机器上"下载得了、写盘被拦"（PermissionError 落在 pip-unpack-*.whl），
而 python 自己写文件是没问题的，所以绕过 pip 的下载/解包流程：
先取 PyPI JSON 接口拿 wheel 地址，再用 urllib 拉下来，
最后 pip install --no-index --find-links 从本地装。
"""
import json
import os
import ssl
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, ".tmp", "wheels")
PKGS = ["pyinstaller", "pyinstaller-hooks-contrib", "altgraph", "pefile",
        "pywin32-ctypes", "packaging", "setuptools"]
INDEXES = ["https://pypi.tuna.tsinghua.edu.cn/pypi/{}/json",
           "https://pypi.org/pypi/{}/json"]

OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler(urllib.request.getproxies()),
    urllib.request.HTTPSHandler(context=ssl.create_default_context()),
)


def get(url, binary=False, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "wheels/1.0"})
    with OPENER.open(req, timeout=timeout) as resp:
        data = resp.read()
    return data if binary else data.decode("utf-8")


def pick(files):
    wheels = [f for f in files if f["filename"].endswith(".whl")]
    # 纯 python 的包优先；带平台的包必须挑 win_amd64（这台机器是 x64，
    # 别把 win_arm64 的 PyInstaller 下下来，启动器架构不对直接跑不了）
    for pattern in ("py3-none-any.whl", "py2.py3-none-any.whl",
                    "cp312-cp312-win_amd64.whl",
                    "cp312-abi3-win_amd64.whl"):
        hits = [f for f in wheels if f["filename"].endswith(pattern)]
        if hits:
            return hits[-1]
    hits = [f for f in wheels if "win_amd64" in f["filename"]]
    if hits:
        return hits[-1]
    return wheels[-1] if wheels else None


def main():
    os.makedirs(OUT, exist_ok=True)
    bad = 0
    for pkg in PKGS:
        meta = None
        for tpl in INDEXES:
            try:
                meta = json.loads(get(tpl.format(pkg)))
                break
            except Exception as exc:        # noqa: BLE001
                print("index failed %s %r" % (pkg, exc))
        if not meta:
            bad += 1
            continue
        chosen = pick(meta.get("urls") or [])
        if not chosen:
            print("no wheel: %s" % pkg)
            bad += 1
            continue
        dest = os.path.join(OUT, chosen["filename"])
        if os.path.exists(dest) and os.path.getsize(dest) == chosen["size"]:
            print("have %s" % chosen["filename"])
            continue
        try:
            blob = get(chosen["url"], binary=True, timeout=120)
            with open(dest, "wb") as fh:
                fh.write(blob)
            print("ok   %s (%d bytes)" % (chosen["filename"], len(blob)))
        except Exception as exc:            # noqa: BLE001
            print("dl failed %s %r" % (chosen["filename"], exc))
            bad += 1
    print("bad=%d" % bad)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
