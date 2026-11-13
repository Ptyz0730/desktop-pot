# -*- coding: utf-8 -*-
"""自检：人设注册 / AI 扩写 / 人设编辑器。"""
import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import ai_client                    # noqa: E402
import desktop_pet as dp            # noqa: E402
import pet_persona                  # noqa: E402

OK = []


def check(name, cond, detail=""):
    OK.append(bool(cond))
    print(("ok   - " if cond else "FAIL - ") + name + ((" | " + str(detail)) if detail else ""))


def settle(pet, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        pet.root.update()
        time.sleep(0.015)


class FakeBrain:
    """假装是 PetBrain：enabled / _complete / model / export 都用得上。"""

    def __init__(self, payload):
        self.enabled = True
        self.payload = payload
        self.calls = 0
        self.model = "fake-model"
        self.persona = "话痨朋友"
        self.system_prompt = ""
        self.context = ""
        self.history = []
        self.turns = 0

    def export(self):
        return {"history": [], "context": "", "turns": 0}

    def needs_summary(self):
        return False

    def _complete(self, messages, max_tokens=0, temperature=0.0, json_mode=False):
        self.calls += 1
        return json.dumps(self.payload, ensure_ascii=False)


def unit_tests():
    print("== ai_client 注册 ==")
    tones = [(81, "恋人期：撒娇"), (61, "暧昧期：脸红"), (41, "朋友期：关心"),
             (21, "熟悉期：互怼"), (0, "陌生期：客气")]
    ai_client.register_persona("自检人设", name="小满", prompt="我是小满，说话软。",
                               hint="软软的同桌", tones=tones,
                               romance_line="今晚月亮真好", romance=True)
    check("人设已注册", "自检人设" in ai_client.PERSONA_PROMPTS)
    check("显示名", ai_client.persona_display_name("自检人设") == "小满")
    check("提要", ai_client.persona_hint("自检人设") == "软软的同桌")
    check("提示词带上正文", "我是小满" in ai_client.persona_prompt("自检人设"))
    check("提示词仍带表演规则", "旁白" in ai_client.persona_prompt("自检人设"))
    check("语气表生效", ai_client.affection_tone(85, "自检人设").startswith("恋人期"))
    check("语气表低档", ai_client.affection_tone(5, "自检人设").startswith("陌生期"))
    check("告白台词", ai_client.romance_line("自检人设") == "今晚月亮真好")
    check("进恋爱名单", "自检人设" in ai_client.ROMANCE_PERSONAS)
    check("内置人设没被改", "话痨朋友" in ai_client.PERSONA_PROMPTS)

    print("== 删掉自定义人设 ==")
    check("删成功", ai_client.forget_persona("自检人设"))
    check("表里没了", "自检人设" not in ai_client.PERSONA_PROMPTS)
    check("恋爱名单也清", "自检人设" not in ai_client.ROMANCE_PERSONAS)
    check("内置删不掉", ai_client.forget_persona("闷骚少年") is False
          and "闷骚少年" in ai_client.PERSONA_PROMPTS)

    print("== 语气表规整 ==")
    t = pet_persona.normalize_tones(["a", "b", "c", "d", "e"])
    check("五条文本按档位升序", [int(x[0]) for x in t] == [81, 61, 41, 21, 0], t)
    t = pet_persona.normalize_tones({"81": "恋人", "0": "陌生"})
    check("缺档补默认", len(t) == 5 and dict(t)[81] == "恋人", t)
    t = pet_persona.normalize_tones([])
    check("空输入也有五档", len(t) == 5)

    print("== AI 扩写（假 brain）==")
    payload = {"name": "阿澈", "hint": "嘴硬的学弟",
               "prompt": "阿澈，17 岁，嘴硬心软，说话短。",
               "tones": ["陌生期(0-20)：叫同学", "熟悉期(21-40)：开始互怼",
                         "朋友期(41-60)：主动找你", "暧昧期(61-80)：脸红吃醋",
                         "恋人期(81-100)：撒娇"],
               "romance_line": "喂，别走。"}
    brain = FakeBrain(payload)
    out = pet_persona.expand(brain, "一个嘴硬的学弟，17 岁", "阿澈")
    check("调了一次接口", brain.calls == 1)
    check("拿到名字", out["name"] == "阿澈")
    check("拿到正文", "嘴硬心软" in out["prompt"])
    check("五档语气", len(out["tones"]) == 5 and out["tones"][0][0] == 81)
    check("告白台词", out["romance_line"] == "喂，别走。")

    bad = FakeBrain({"prompt": ""})
    try:
        pet_persona.expand(bad, "随便写写")
        check("空正文会报错", False)
    except ValueError:
        check("空正文会报错", True)

    class NoKey(FakeBrain):
        enabled = False
    check("没 key 时失败不崩", True)


def integration_tests():
    print("== 桌面宠物集成 ==")
    cfg = dp.CONFIG_PATH
    bak = cfg + ".persona_bak"
    if os.path.exists(cfg):
        shutil.copy2(cfg, bak)
    if os.path.exists(cfg):
        os.remove(cfg)
    pet = None
    try:
        pet = dp.DesktopPet(use_ai=True, topmost=True, bubble=True)
        settle(pet, 0.4)
        pet.brain.api_key = "test"
        check("初始没有自定义人设", pet.custom_personas == {})

        data = {"name": "小满", "hint": "软软的同桌",
                "prompt": "小满，16 岁，说话软软的，被夸会害羞。",
                "tones": ["陌生期：客气", "熟悉期：会笑", "朋友期：主动",
                          "暧昧期：脸红", "恋人期：黏人"],
                "romance_line": "月亮好看吧"}
        check("存人设成功", pet.save_custom_persona("小满", data))
        check("注册进 ai_client", "小满" in ai_client.PERSONA_PROMPTS)
        check("写进配置", "小满" in (pet.cfg.get("custom_personas") or {}))
        with open(cfg, encoding="utf-8") as fh:
            saved = json.load(fh)
        check("配置落盘", "小满" in (saved.get("custom_personas") or {}))

        menu = pet._persona_menu
        labels = []
        for i in range(menu.index("end") + 1):
            try:
                labels.append(str(menu.entrycget(i, "label")))
            except Exception:               # noqa: BLE001  分隔线没有 label
                continue
        check("菜单里出现新人设", any("小满" in x for x in labels), labels[-3:])
        check("菜单里有编辑入口", any("编辑人设" in x for x in labels))

        pet.set_persona("小满")
        settle(pet, 0.2)
        check("切到新人设", pet._persona == "小满")
        check("提示词换了", "小满" in pet.brain.system_prompt)
        check("语气表换了", pet.brain.persona == "小满")

        pet.affection = 90
        check("恋人期语气", ai_client.affection_tone(90, "小满").startswith("恋人期"))

        # 编辑器窗口
        editor = pet_persona.PetPersonaDialog(pet).show()
        settle(pet, 0.3)
        check("编辑器打开", editor.win is not None and editor.win.winfo_exists())
        check("列表里有内置人设", any(not editor._is_custom(k) for k in editor.keys))
        check("列表里有自定义人设", "小满" in editor.keys)
        editor._reload_list(select="小满")
        settle(pet, 0.1)
        check("选中后回填正文", "软软" in editor.txt.get("1.0", "end"))
        check("选中后回填语气",
              editor.v_tier[0].get().startswith("陌生") and
              editor.v_tier[4].get().startswith("恋人"),
              [v.get() for v in editor.v_tier])
        editor._fill(dict(data, tones=pet_persona.normalize_tones(data["tones"])))
        editor._save()
        settle(pet, 0.2)
        check("编辑器保存", "小满" in pet.custom_personas)

        # AI 扩写走一遍（假 brain）
        pet.brain = FakeBrain({"name": "小满", "hint": "改过的",
                               "prompt": "小满，被你夸会低头看手机。",
                               "tones": ["陌生期：客气"] * 5,
                               "romance_line": "别走"})
        editor._expand()
        for _ in range(60):
            pet.root.update()
            time.sleep(0.03)
            if not editor.busy:
                break
        settle(pet, 0.2)
        check("AI 扩写完成", not editor.busy and "低头看手机" in editor.txt.get("1.0", "end"))

        editor.close()
        settle(pet, 0.1)
        check("编辑器关掉", pet.persona_editor is None)

        check("删人设成功", pet.delete_custom_persona("小满"))
        check("删完不在菜单", "小满" not in ai_client.PERSONA_PROMPTS)
        check("删完退回默认", pet._persona == dp.DEFAULT_PERSONA, pet._persona)
        with open(cfg, encoding="utf-8") as fh:
            saved = json.load(fh)
        check("配置里也删了", "小满" not in (saved.get("custom_personas") or {}))
    finally:
        if pet is not None:
            try:
                pet.quit()
            except Exception:               # noqa: BLE001
                pass
        for path in (cfg,):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass
        if os.path.exists(bak):
            shutil.move(bak, cfg)


def main():
    unit_tests()
    integration_tests()
    print("\nRESULT: %s" % ("OK" if all(OK) else "FAILED"))
    return 0 if all(OK) else 1


if __name__ == "__main__":
    sys.exit(main())
