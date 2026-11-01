#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""桌宠的情绪机制：日常 / 吃醋 / 冷战（优先级：冷战 > 吃醋 > 日常）。

规则是玩家给的：吃醋时话变短、阴阳怪气、死不承认；冷战只回「嗯」「哦」
「随你」，问就是「没事」「你想多了」；被哄好了嘴上还硬。

如果只把这些写进提示词，模型会时灵时不灵 —— 同一句话有时吃醋有时不。所以
"现在是哪种情绪"由这里决定：玩家说了什么、隔了多久没说话，都是可数的信号；
模型只负责把那个状态下的话说得像。这样行为稳定，也能离线自检
（tools/check_mood.py 用假时钟跑，不联网）。

状态跟着人设槽存（desktop_pet._stash_persona 的 "mood" 键），换形象各气各的。

对外只干这几件事：
    engine.observe(text)    -> event        这一句让情绪怎么变
    engine.prompt(event)    -> str|""       塞给模型的"你现在什么状态"
    engine.options_hint()   -> str|""       写选项时的状态提要（玩家视角）
    engine.shape(reply)     -> str          把模型的话按状态剪短
    engine.clamp_delta(x)   -> int          冷战期不涨好感度
    engine.allow_initiative()-> bool        冷战期不主动找话
"""

import random
import re
import time

NORMAL = "normal"
JEALOUS = "jealous"
COLD = "cold"

STATE_LABELS = {NORMAL: "日常", JEALOUS: "吃醋", COLD: "冷战"}

# 空一行、标点、括号都去掉再判断"敷衍"：模型/用户都可能打「哦。」「嗯…」
_SEP = re.compile(r"[\s，。！？、；：,.!?;:~～…（）()「」『』“”\"'‘’/\\|]+")

# 敷衍的短回复（和 ai_client._LUKEWARM_REPLIES 保持一致；这里去标点后再比）
_LUKEWARM = frozenset((
    "哦", "哦哦", "哦哦哦", "噢", "噢噢", "嗯", "嗯嗯", "嗯嗯嗯",
    "额", "呃", "呵呵", "随便", "都行", "不知道", "还行", "哦好", "嗯好",
))

# 一进就冷战的话（比起吃醋，这是真的伤了）
_COLD_HARD = (
    ("嫌烦", re.compile(
        r"烦不烦|别烦我|你(真|好|太)烦|烦死|烦人|别吵|闭嘴|滚开|走开|别来烦|"
        r"嘴碎|话太多|话真多|别念了|少说两句|"
        r"(^|[\s，。！？,.!?])滚($|[\s，。！？,.!?])")),
    ("贬低", re.compile(
        r"比不上|不如(他|她|人家|别人)|比不过(他|她|人家|别人)|"
        r"(他|她|人家|别人)[^，。！？,.!?]{0,6}比(你)?(强|好|厉害|帅|牛)|"
        r"你(算|是)什么东西|就你(也|还)|你也配|你(真|太)?没用|没出息")),
    ("骗人", re.compile(r"骗(你|我)|骗人|撒谎|忽悠我?|耍我|放我鸽子")),
    ("放鸽子", re.compile(
        r"放(我)?鸽子|鸽了(我)?|爽约|"
        r"我(今天|明天|今晚|这周)?(不|没)(来|去)了|我去不了")),
    # 当众拆穿嘴硬：他嘴上说不在乎，被点破就挂不住脸（用户设定里算冷战）
    ("拆穿", re.compile(
        r"拆穿|别装了|装什么装|装什么蒜|你就是嘴硬|就嘴硬|嘴硬什么|别硬撑|"
        r"明明(就|是)?(很|在)?(开心|喜欢|在意|吃醋|想)")),
)

# 吃醋的话：提到别的男生、夸别人、跟别人玩、拿人比、说「随便你」
_JEALOUS = (
    ("随便你", re.compile(r"随便你|随你便|你随意|都随你|随你怎么想")),
    ("别人", re.compile(
        r"(别的|其他|另一个|其它|隔壁)(男生|男人|男的|人|同学|朋友|队友|学长|小哥)|"
        r"有个(男生|男的|人|同学)")),
    ("夸别人", re.compile(
        r"(他|她|人家|别人|男生|男的|小哥|队友|学长|同学|同桌|哥们|兄弟|室友)"
        r"[^，。！？,.!?]{0,8}(帅|厉害|强|牛|棒|优秀|可爱|好|酷|猛|顶|nb|NB)"
        r"(?!烦|讨厌|丑|烂|差|菜|吗|久|像|多)")),
    ("跟别人玩", re.compile(
        r"(跟|和|同|陪)(?!你|你们)(他|她|人家|别人|同学|朋友|队友|男生|男的|哥们|兄弟|同桌|室友)"
        r"[^，。！？,.!?]{0,6}(聊|玩|吃|打球|出去|看|逛|约|走)")),
    ("比较", re.compile(
        r"(不如|比不上|比不过)(他|她|人家|别人)|"
        r"(他|她|人家|别人)(都|可|就)?(比|强过|胜过)你|"
        r"人家(都|多|那么)(好|强|厉害|帅)")),
)

# 哄人：道歉、服软、想它、夸它、来看它、给台阶
_COAX = re.compile(
    r"对不起|我错了|抱歉|原谅|别生气|别气了|不气了|消消气|哄哄|哄一下|哄你|"
    r"陪你|我陪你|来找你|来看你|过去找你|在楼下|等你|接你|"
    r"想你了|想你|喜欢你|爱你|只喜欢你|最爱你|离不开你|"
    r"你最(好|棒|帅|厉害|强|牛)|你(真|超|最|好|挺)(帅|厉害|强|棒|可爱|好看|酷)|"
    r"乖|抱抱|亲亲|么么|摸摸头|摸头|贴贴|理理我|别不理我|"
    r"goat|mvp|基操", re.IGNORECASE)

# 玩家在问"你怎么了"：冷战时只准回「没事」「你想多了」
_ASKING = re.compile(r"怎么了|咋了|为什么|为啥|生气了|不开心|不高兴|是不是我|谁惹")

# 冷战期的固定短句（模型话多了就换成这些）
COLD_LINES = ("嗯。", "哦。", "随你。", "……")
COLD_ASK = ("没事。", "你想多了。", "GOAT 能有什么事。")
COLD_SOFT = ("我没生气。", "谁要你哄。", "……嗯。", "行了。",
             "……明天有训练，爱来不来。")
COLD_IDLE = ("嗯。", "……", "干嘛。")
# 冷战拖久了才会漏出来的那两句（不主动，但也没真放下）
COLD_TIRED = ("行吧，你忙你的。GOAT 自己练。", "行吧。GOAT 不缺观众。")

# 玩家夸"你比他强"：句子里有"他"，但这是夸你，不能算吃醋
_PRAISE_PET = re.compile(
    r"你(都|才|可|还是|本来就)?(比|强过|胜过|厉害过|牛过)(他|她|人家|别人)")

_END_PUNCT = "。！？!?～~…"


def _squash(text):
    return _SEP.sub("", str(text or "")).strip().lower()


def _is_lukewarm(text):
    """「哦」「嗯」「随便」这类敷衍：整句只有一两个字的才算法。"""
    body = _squash(text)
    return bool(body) and len(body) <= 4 and body in _LUKEWARM


def _cold_hit(text):
    for reason, pattern in _COLD_HARD:
        if pattern.search(text):
            return reason
    return ""


def _jealous_hit(text):
    for reason, pattern in _JEALOUS:
        if not pattern.search(text):
            continue
        if reason == "夸别人" and _PRAISE_PET.search(text):
            continue
        return reason
    return ""


def _cut(text, limit):
    """把一句话剪到 limit 字以内，尽量断在标点上。"""
    if len(text) <= limit:
        return text
    head = text[:limit]
    for i in range(len(head) - 1, 1, -1):
        if head[i] in _END_PUNCT:
            return head[:i + 1]
    return head.rstrip("，、,;；：: ") + "…"


class MoodEngine(object):
    """情绪状态机。只认玩家的话和时间，不看模型怎么想。"""

    JEALOUS_TO_COLD = 2.0     # 吃醋后连着一两次不哄，就转冷战
    SLOW_MINUTES = 10.0       # 隔这么久才回一句 = 回消息慢（吃醋）
    SLOW_RESET_MINUTES = 180.0  # 隔太久（三小时以上）不算"回得慢"，算新的一段
    THAW_HOURS = 24.0         # 一天没说话，气自己消了（不是被哄好的）

    def __init__(self, state=NORMAL, turns=0, reason="", last_seen=0.0):
        self.state = state if state in (NORMAL, JEALOUS, COLD) else NORMAL
        try:
            self.turns = max(0, int(turns or 0))
        except (TypeError, ValueError):
            self.turns = 0
        self.reason = str(reason or "")
        try:
            self.last_seen = max(0.0, float(last_seen or 0.0))
        except (TypeError, ValueError):
            self.last_seen = 0.0
        self._theater_turn = 0

    # ------------------------------------------------------------ 存档
    def dump(self):
        return {
            "state": self.state,
            "turns": self.turns,
            "reason": self.reason,
            "last_seen": round(self.last_seen, 3),
        }

    @classmethod
    def load(cls, data):
        """从配置里恢复（坏数据/老配置就当日常，绝不抛异常）。"""
        if isinstance(data, cls):
            return data
        if not isinstance(data, dict):
            return cls()
        return cls(state=data.get("state"),
                   turns=data.get("turns"),
                   reason=data.get("reason"),
                   last_seen=data.get("last_seen"))

    def reset(self):
        self.state = NORMAL
        self.turns = 0
        self.reason = ""
        self.last_seen = 0.0
        self._theater_turn = 0

    # ------------------------------------------------------------ 判断
    def is_cold(self):
        return self.state == COLD

    def is_jealous(self):
        return self.state == JEALOUS

    def allow_initiative(self):
        """冷战期不主动找话题、不主动冒泡。"""
        return self.state != COLD

    def allows_kaomoji(self):
        """冷战期连颜文字都不要：一两个字的回复才够冷。"""
        return self.state != COLD

    def label(self):
        return STATE_LABELS.get(self.state, STATE_LABELS[NORMAL])

    # ------------------------------------------------------------ 主循环
    def observe(self, text, now=None):
        """喂一句玩家说的话，返回这一轮的情绪事件（dict）。

        event = {
            "kind":   enter_jealous / enter_cold / stay_jealous / stay_cold /
                      resolve_jealous / resolve_cold / calm / daily,
            "before"/"state": 变化前 / 后的状态,
            "reason": 触发原因（供日志和自检看，不给模型）,
            "coaxed": 这句是不是在哄,
            "asking": 是不是在问"你怎么了",
            "gap_min": 距上一句多少分钟（第一句是 None）,
        }
        """
        now = time.time() if now is None else float(now)
        body = str(text or "").strip()
        gap = None
        if self.last_seen:
            gap = max(0.0, (now - self.last_seen) / 60.0)
        self.last_seen = now

        coaxed = bool(_COAX.search(body))
        asking = bool(_ASKING.search(body))
        hard = _cold_hit(body)
        jealous_why = _jealous_hit(body)
        lukewarm = _is_lukewarm(body)

        before = self.state
        event = {"kind": "daily", "before": before, "state": before,
                 "reason": "", "coaxed": coaxed, "asking": asking,
                 "gap_min": gap}

        # 1) 隔太久：人不在，生气也没用 —— 先气消，再看这一句
        calmed = False
        if before != NORMAL and gap is not None and gap >= self.THAW_HOURS * 60.0:
            self.state, self.turns, self.reason = NORMAL, 0, ""
            event.update(kind="calm", reason="time")
            calmed = True

        # 2) 这一句本身就够冷战（优先级最高，哄也没用）
        if hard:
            if self.state == COLD:
                self.turns += 1
                event.update(kind="stay_cold", reason=hard)
            else:
                self.state, self.turns, self.reason = COLD, 0, hard
                event.update(kind="enter_cold", reason=hard)
            event["state"] = self.state
            return event

        # 3) 敷衍（哦/嗯/随便）：不管在哪个状态，直接转冷战
        if lukewarm and self.state != COLD:
            self.state, self.turns, self.reason = COLD, 0, "lukewarm"
            event.update(kind="enter_cold", reason="lukewarm", state=COLD)
            return event

        if self.state == COLD:
            if coaxed:
                self.state, self.turns, self.reason = NORMAL, 0, ""
                event.update(kind="resolve_cold", reason="coax", state=NORMAL)
            else:
                self.turns += 1
                event.update(kind="stay_cold", reason="waiting", state=COLD)
            return event

        if self.state == JEALOUS:
            if jealous_why:
                # 还在提别人：不是"不哄"，但一样往冷战上推
                self.turns += 1
                if self.turns >= self.JEALOUS_TO_COLD:
                    self.state, self.turns, self.reason = COLD, 0, "ignored"
                    event.update(kind="enter_cold", reason="ignored", state=COLD)
                else:
                    event.update(kind="stay_jealous", reason=jealous_why,
                                 state=JEALOUS)
                return event
            if coaxed:
                self.state, self.turns, self.reason = NORMAL, 0, ""
                event.update(kind="resolve_jealous", reason="coax", state=NORMAL)
                return event
            # 不哄、也不提别人：晾着。两轮就进冷战
            self.turns += 1
            if self.turns >= self.JEALOUS_TO_COLD:
                self.state, self.turns, self.reason = COLD, 0, "ignored"
                event.update(kind="enter_cold", reason="ignored", state=COLD)
            else:
                event.update(kind="stay_jealous", reason="waiting", state=JEALOUS)
            return event

        # 4) 日常：吃醋的入口
        if jealous_why:
            self.state, self.turns, self.reason = JEALOUS, 0, jealous_why
            event.update(kind="enter_jealous", reason=jealous_why, state=JEALOUS)
            return event
        if gap is not None and self.SLOW_MINUTES <= gap <= self.SLOW_RESET_MINUTES:
            self.state, self.turns, self.reason = JEALOUS, 0, "slow"
            event.update(kind="enter_jealous", reason="slow", state=JEALOUS)
            return event
        event.update(kind="calm" if calmed else "daily", state=NORMAL)
        return event

    # ------------------------------------------------------------ 给模型的话
    def prompt(self, event=None):
        """当前状态对应的表演要求（塞进 system 消息；日常返回空串）。"""
        kind = (event or {}).get("kind", "")
        if self.state == COLD:
            if kind == "resolve_cold":
                return ("【情绪：刚好一点（冷战尾巴）】对方刚哄你。你嘴上还说"
                        "「我没生气」「谁要你哄」，但可以给一个小台阶，"
                        "比如「明天有训练，爱来不来」。只回一句、不超过 20 字，"
                        "别直接说「我原谅你」，别马上变得很热络。")
            return ("【情绪：冷战（最高优先级）】你正在跟对方冷战。"
                    "只回一两个字：「嗯」「哦」「随你」；对方问你怎么了，只回「没事」"
                    "「你想多了」。不主动找话题，不用口头禅「I'm goat」，"
                    "不解释原因，不长篇控诉，不彻底消失，不说「我原谅你」。"
                    "语气平，句尾别加波浪号，不用感叹号。")
        if self.state == JEALOUS:
            if kind == "resolve_jealous":
                return ("【情绪：刚被哄】对方刚哄了你。你语气软下来，但嘴上还是硬："
                        "「谁要你哄」「……哦」。不承认刚才在吃醋，也别一下子变得特别热情。"
                        "只回一句、不超过 15 字。")
            return ("【情绪：吃醋】你在吃醋，但绝不承认。回复要短（不超过 15 字），"
                    "语气变冷、阴阳怪气，可以反复问「然后呢」「他谁啊」「他很好？」。"
                    "禁止说「我吃醋了」「我不开心」，禁止长篇大论，禁止立刻原谅。"
                    "对方哄你时语气软一点，但嘴上说「谁要你哄」。")
        if kind == "calm":
            return ("【情绪：气消了】隔了很久没说话，你已经没那么气了，但不想承认。"
                    "只回一句、不超过 15 字，像「……你还知道回来」「我以为你不来了」，"
                    "语气平淡，别热络，别说「我原谅你」。")
        if kind in ("resolve_cold", "resolve_jealous"):
            return ("【情绪：刚被哄好】你语气还有点别扭，嘴上说「谁要你哄」「我没生气」，"
                    "给一个小台阶，别直接说「我原谅你」。")
        return ""

    def options_hint(self):
        """给"玩家可以怎么回"这三个选项的状态提要。"""
        if self.state == COLD:
            return ("（当前状态）它正在跟玩家冷战，只会回一两个字。"
                    "三个选项要能破冰：一句认真哄它或道歉、一句解释或服软、"
                    "一句嘴硬逗它；别都是「嗯」「哦」这种。")
        if self.state == JEALOUS:
            return ("（当前状态）它在吃醋但不承认，说话阴阳怪气。"
                    "三个选项：一句哄它或夸它、一句装傻「他谁啊」、一句嘴硬怼回去。")
        return ""

    # ------------------------------------------------------------ 剪回复
    def max_reply_chars(self, event=None):
        if self.state == COLD:
            # 被哄好的那一下可以给个台阶（「明天有训练，爱来不爱」），其余只准一两个字
            if (event or {}).get("kind") == "resolve_cold":
                return 20
            return 8
        if self.state == JEALOUS:
            return 20
        return 0

    def shape(self, reply, event=None, rng=None):
        """按状态剪模型的话：冷战话多了直接换成短句，吃醋只留半句。"""
        text = str(reply or "").strip()
        if not text:
            return text
        if self.state == COLD:
            if len(text) <= self.max_reply_chars(event):
                return text
            return self.cold_line(event, rng)
        limit = self.max_reply_chars(event)
        if limit and len(text) > limit:
            return _cut(text, limit)
        return text

    def cold_line(self, event=None, rng=None):
        rng = rng or random
        kind = (event or {}).get("kind", "")
        if kind == "resolve_cold":
            return rng.choice(COLD_SOFT)
        if (event or {}).get("asking"):
            return rng.choice(COLD_ASK)
        # 冷战拖久了（第四句以后）偶尔漏一句「你自己练去吧」
        if kind == "stay_cold" and self.turns >= 4 and rng.random() < 0.35:
            return rng.choice(COLD_TIRED)
        return rng.choice(COLD_LINES)

    def idle_line(self, rng=None):
        """冷战期被点一下时说的话。"""
        return (rng or random).choice(COLD_IDLE)

    def clamp_delta(self, delta):
        """冷战期不涨好感度（最多 0），吃醋期最多 +1。"""
        try:
            delta = int(delta)
        except (TypeError, ValueError):
            delta = 0
        if self.state == COLD:
            return min(delta, 0)
        if self.state == JEALOUS:
            return min(delta, 1)
        return delta

    # ------------------------------------------------------------ 小动作
    def theater(self, event=None, rng=None):
        """冷战期的"发一条又撤回 / 手滑点赞"：返回 "withdraw" / "like" / None。

        每三次冷战发言才有一次机会，再掷 50% —— 太频繁就不像闹别扭，像抽风。
        """
        if self.state != COLD:
            return None
        if (event or {}).get("kind") not in ("enter_cold", "stay_cold"):
            return None
        self._theater_turn += 1
        if self._theater_turn % 3 != 1:
            return None
        rng = rng or random
        roll = rng.random()
        if roll < 0.25:
            return "withdraw"
        if roll < 0.50:
            return "like"
        return None
