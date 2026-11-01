# -*- coding: utf-8 -*-
"""选项必须是 AI 生成的、回复不许一字不差地重复。

假服务器区分三类请求：
  * 主请求        -> 返回 {"reply","delta","options"}（可按 mode 缺 options / 空内容）
  * 只要选项      -> 返回 {"options": [...]}（带轮次编号，便于检查是不是新生成的）
  * 带"别重复"提示 -> 返回另一句话（检查查重重试是否生效）
"""
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import ai_client as ac  # noqa: E402

ok = True
MODE = {"v": "no_options"}
H = {}
CALLS = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n).decode("utf-8"))
        sys_text = " ".join(m.get("content") or "" for m in body["messages"]
                            if m.get("role") == "system")
        asks_options = "接下来可以" in sys_text
        asks_norepeat = "换一句完全不同" in sys_text
        CALLS.append("options" if asks_options else
                     ("norepeat" if asks_norepeat else "main"))

        if asks_options:
            opts = ["想吃点什么吗", "那我们去走走", "你先忙你的"]
            text = json.dumps({"options": opts}, ensure_ascii=False)
        elif asks_norepeat:
            text = json.dumps({"reply": "嗯……那你先忙吧，我不打扰。", "delta": 1,
                               "options": ["好", "bye", "等你"]}, ensure_ascii=False)
        elif MODE["v"] == "no_options":
            H["n"] = H.get("n", 0) + 1
            text = json.dumps({"reply": "第%d句，花还喜欢吗？" % H["n"],
                               "delta": 1}, ensure_ascii=False)
        elif MODE["v"] == "repeat":
            text = json.dumps({"reply": "同一句话，我又说了一遍。",
                               "delta": 1}, ensure_ascii=False)
        elif MODE["v"] == "empty":
            text = ""
        else:
            text = json.dumps({"reply": "嗯。", "delta": 1,
                               "options": ["a", "b", "c"]}, ensure_ascii=False)
        out = json.dumps({"choices": [{"finish_reason": "stop",
                                       "message": {"content": text}}]},
                         ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


def check(name, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    print("%-52s %s %s" % (name, "ok" if cond else "FAIL", detail))


server = HTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
brain = ac.PetBrain(api_key="test",
                    base_url="http://127.0.0.1:%d/v1" % server.server_address[1])
brain.system_prompt = ac.persona_prompt("闷骚少年")

print("=== 主请求不给 options：应该再单独要一次（AI 生成的选项）===")
CALLS.clear()
reply, delta, options, err = brain.chat_with_options("你还在吗", 21)
print("   调用序列:", CALLS)
print("   回复:", reply)
print("   选项:", options)
check("确实又发了一次「只要选项」的请求", CALLS.count("options") == 1, str(CALLS))
check("选项来自 AI（假服务器那三句）",
      options == ["想吃点什么吗", "那我们去走走", "你先忙你的"], str(options))
check("回复正常", "花还喜欢吗" in reply, reply)

print("=== 第二轮的选项也不一样（每轮都是新生成的）===")
CALLS.clear()
reply2, _d, options2, _e = brain.chat_with_options("嗯嗯，然后呢？", 21)
check("第二轮同样单独要了选项", CALLS.count("options") == 1, str(CALLS))
check("第二轮选项仍是 AI 生成的那三句",
      options2 == ["想吃点什么吗", "那我们去走走", "你先忙你的"], str(options2))

print("=== 回复和上一条一字不差：应该带「别重复」再要一次 ===")
MODE["v"] = "repeat"
brain.history.append({"role": "assistant", "content": "同一句话，我又说了一遍。"})
CALLS.clear()
reply3, _d, options3, _e = brain.chat_with_options("嗯嗯，然后呢？", 21)
print("   调用序列:", CALLS)
check("检测到重复并重试了", "norepeat" in CALLS, str(CALLS))
check("回复换成新的一句", reply3 == "嗯……那你先忙吧，我不打扰。", reply3)

print("=== 接口彻底空内容：仍然有人话 + 三条选项 ===")
MODE["v"] = "empty"
CALLS.clear()
reply4, _d, options4, err4 = brain.chat_with_options("在吗", 21)
check("回复不是「模型没说话」", "模型没说话" not in reply4, reply4)
check("选项还是 AI 生成的", options4 == ["想吃点什么吗", "那我们去走走", "你先忙你的"],
      str(options4))

server.shutdown()
server.server_close()
print("RESULT:", "OK" if ok else "FAILED")
