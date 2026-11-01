# -*- coding: utf-8 -*-
"""选项永远有内容：模拟模型各种"不听话"的情况，看窗口里三个按钮是否有字。"""
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import ai_client  # noqa: E402
import desktop_pet as dp  # noqa: E402

ok = True
MODE = {"v": "json"}
PAYLOADS = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n).decode("utf-8"))
        PAYLOADS.append(body)
        mode = MODE["v"]
        if mode == "reject_json_mode" and "response_format" in body:
            out = b'{"error": {"message": "response_format not supported"}}'
            self.send_response(400)
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)
            return
        if mode == "prose":
            text = "今天天气不错，我在看你写代码。"
        elif mode == "short_options":
            text = json.dumps({"reply": "嗯，我在。", "delta": 2, "options": ["你好"]},
                              ensure_ascii=False)
        elif mode == "no_options":
            text = json.dumps({"reply": "嗯，我在。", "delta": 1}, ensure_ascii=False)
        else:
            text = json.dumps({"reply": "嘿，你回来啦。", "delta": 3,
                               "options": ["我也想你", "刚忙完", "在干嘛呢"]},
                              ensure_ascii=False)
        out = json.dumps({"choices": [{"message": {"content": text}}]},
                         ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


server = HTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
base = "http://127.0.0.1:%d/v1" % server.server_address[1]


def check(name, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    print("%-46s %s %s" % (name, "ok" if cond else "FAIL", detail))


def settle(pet, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        pet.root.update()
        time.sleep(0.015)


cfg = dp.CONFIG_PATH
if os.path.exists(cfg):
    os.remove(cfg)
pet = dp.DesktopPet(use_ai=True, topmost=True, bubble=True)
settle(pet, 0.5)
pet.brain.api_key = "test"
pet.brain.base_url = base
pet.open_chat()
settle(pet, 0.4)
win = pet.chat_win

def wait_for(pet, needle, timeout=8.0):
    """等窗口记录里出现某段文字（比固定 sleep 稳：网络/线程快慢都不影响）。"""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            text = pet.chat_win.log.get("1.0", "end")
        except Exception:                       # noqa: BLE001
            text = ""
        if needle in text:
            return True
        pet.root.update()
        time.sleep(0.05)
    return False


for mode, expect in (("json", "嘿，你回来啦。"),
                     ("no_options", "嗯，我在。"),
                     ("short_options", "嗯，我在。"),
                     ("prose", "今天天气不错"),
                     ("reject_json_mode", "嘿，你回来啦。")):
    MODE["v"] = mode
    PAYLOADS.clear()
    win.entry.insert(0, "在吗")
    win.submit()
    wait_for(pet, expect)
    settle(pet, 0.4)
    texts = [b.cget("text") for b in win.option_buttons]
    states = [str(b.cget("state")) for b in win.option_buttons]
    filled = sum(1 for t in texts if t.strip())
    print("  [%-18s] 回复含关键字=%s  选项=%s 状态=%s"
          % (mode, expect in win.log.get("1.0", "end"), texts, states))
    if mode == "prose":
        print("DBG options=%r ai=%r mapped=%r texts=%r"
              % (getattr(win, "_options", None), getattr(win, "_ai_options", None),
                 [b.winfo_ismapped() for b in win.option_buttons], texts))
        # 一条 AI 选项都拿不到时，不再用兜底池凑三句空话：按钮收起来，
        # 输入框照常可用（自己说一句也能聊）
        check("  拿不到选项就收起按钮 (%s)" % mode,
              filled == 0 and not win.option_buttons[0].winfo_ismapped(),
              "filled=%d mapped=%s" % (filled,
                                       win.option_buttons[0].winfo_ismapped()))
        check("  输入框还能用 (%s)" % mode,
              str(win.entry.cget("state")) == "normal",
              "entry=%s" % win.entry.cget("state"))
        continue
    if mode == "short_options":
        # 模型只给到 1 条 AI 选项时就显示 1 条，不再拿兜底池凑数（那是空话）
        check("  有几条显示几条 (%s)" % mode, filled >= 1, "filled=%d" % filled)
        check("  不拿兜底池凑数 (%s)" % mode,
              all(t not in ai_client.FALLBACK_OPTIONS for t in texts if t.strip()),
              str(texts))
        continue
    check("  选项三项都有字 (%s)" % mode, filled == 3, "filled=%d" % filled)
    check("  三项都可点 (%s)" % mode,
          all(s == "normal" for s in states), str(states))
    if mode in ("json", "reject_json_mode"):
        # 注意：启动时的"闲话预热"请求偶尔会排在最前面，所以看"有没有一次"
        # 带 response_format，而不是只盯着第一个
        asked = [p for p in PAYLOADS if "response_format" in p]
        check("  有请求带 response_format (%s)" % mode, bool(asked),
              "共 %d 次请求: %s" % (len(PAYLOADS),
                                  [sorted(p.keys())[-2:] for p in PAYLOADS]))
    if mode == "reject_json_mode":
        check("  400 后自动退回普通请求", len(PAYLOADS) >= 2,
              "请求数=%d" % len(PAYLOADS))

MODE["v"] = "json"
print("=== AI 关掉时不塞空话，输入框照常可用 ===")
pet.ai_enabled = False
win.entry.insert(0, "在吗")
win.submit()
settle(pet, 0.8)
texts = [b.cget("text") for b in win.option_buttons]
check("AI 关掉时不拿兜底池凑数", all(not t.strip() for t in texts), str(texts))
check("AI 关掉时输入框还能用", str(win.entry.cget("state")) == "normal",
      "entry=%s" % win.entry.cget("state"))
pet.ai_enabled = True

print("=== 接口报错时不塞空话 ===")
server.shutdown()
server.server_close()          # 只 shutdown 的话监听套接字还开着，连接会被挂住
win.entry.insert(0, "在吗")
win.submit()
wait_for(pet, "（", timeout=10.0)
settle(pet, 0.4)
texts = [b.cget("text") for b in win.option_buttons]
check("接口挂掉时不拿兜底池凑数", all(not t.strip() for t in texts), str(texts))
log = win.log.get("1.0", "end")
check("窗口里能看到错误说明", "（" in log or "错误" in log or "连不上" in log,
      log.strip().splitlines()[-1][:40] if log.strip() else "")

win.cancel()
settle(pet, 0.2)
pet.quit()
print("RESULT:", "OK" if ok else "FAILED")

