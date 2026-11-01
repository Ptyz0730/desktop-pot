# -*- coding: utf-8 -*-
"""用真接口看三档人设的实际口吻（好感 10 / 50 / 95），结果写到 _persona_probe.txt。"""
import io
import sys
import time

sys.path.insert(0, ".")
import ai_client as ac  # noqa: E402
import desktop_pet as dp  # noqa: E402

LINES = {
    10: "在吗",
    50: "今天训练累不累啊",
    95: "今天有人说你打球帅",
}

out = []
for aff, user_line in LINES.items():
    brain = ac.PetBrain(api_key=getattr(dp, "BUILTIN_API_KEY", "") or None)
    brain.system_prompt = ac.persona_prompt("闷骚少年", romance=(aff >= 95))
    brain.persona = "闷骚少年"
    t0 = time.time()
    reply, delta, options, err = brain.chat_with_options(user_line, aff)
    took = time.time() - t0
    out.append("=== 好感度 %d（%.1fs）===" % (aff, took))
    out.append("玩家: " + user_line)
    out.append("chm : " + (reply or "（空）"))
    out.append("delta=%s options=%s err=%s" % (delta, options, err))
    out.append("")

io.open("_persona_probe.txt", "w", encoding="utf-8").write("\n".join(out))
print("written _persona_probe.txt")
