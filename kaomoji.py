# -*- coding: utf-8 -*-
"""颜文字系统：按心情挑一个，贴在它自己说的话后面。

设计上刻意做成"代码决定、模型不掺和"：
  * 模型只负责说话的内容，颜文字由这里按时机/心情补上 —— 稳定、可控，
    不会被模型偶尔一大串 emoji 或是忘掉；
  * 已经有颜文字的句子不再补第二个（decorate 是幂等的）；
  * 心情主要看好感度（低好感装酷、高好感害羞），另外留了手势用的映射。
"""
import random
import re

# 每个心情一组，句子都短，气泡里放得下
# 注意：气泡是 PIL 画字，没有字体回退 —— 字体里没有的符号会变成方块 ▯。
# 所以这里只用 tools/probe_glyphs_ok.py 验证过"一定能画"的字符
# （()（）￣ _ ^ v V ω ° ▽ △ ≧ ≦ ☆ ★ · ・ ！？ … ー ヽ ヾ ノ ﾉ ミ ゞ 〃 ＊ ※ 等）。
GROUPS = {
    "开心": ["(^▽^)", "(≧▽≦)", "(☆▽☆)", "(´▽`)", "(*^▽^*)", "ヽ(°▽°)ノ",
             "ヾ(≧▽≦)ノ", "(*^ω^*)", "(≧ω≦)", "(ノ^▽^)ノ"],
    "害羞": ["(*^_^*)", "(〃▽〃)", "(〃ω〃)", "(///ω///)", "(´ω`)", "(≧///≦)",
             "(〃_〃)", "(ノωヽ)"],
    "得意": ["(￣▽￣)", "(￣▽￣)~*", "(￣ω￣)", "(￣ー￣)", "(￣▽￣)ノ", "(－▽－)",
             "(￣ε￣)", "(☆ω☆)"],
    "无语": ["(￣_￣)", "(－_－)", "(-_-)", "(=_=)", "(°_°)", "(・_・)",
             "(￣_￣|||)", "(￣o￣)"],
    "生气": ["(￣^￣)", "(￣皿￣)", "(｀Д´)", "(#`Д´)", "(￣ヘ￣)", "(＃￣皿￣)",
             "(ー_ー)!!"],
    "难过": ["(T_T)", "(T▽T)", "(;_ ;)", "(ノ_・。)", "(´・ω・`)", "(￣ω￣)"],
    "困": ["(￣o￣) zzZ", "(－_－) zzZ", "(＿ ＿*) Z z z", "(-_-) zzZ",
           "(=_=) zzZ"],
    "疑问": ["(・_・?)", "(°_°?)", "(￣_￣?)", "(・ω・?)", "(⊙_⊙)?"],
}

# 好感度 → 默认心情（chm 是傲娇：越熟越软）
def mood_for_affection(value):
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = 50
    if value <= 20:
        return "生气"
    if value <= 40:
        return "无语"
    if value <= 60:
        return "得意"
    if value <= 80:
        return "开心"
    return "害羞"


# 手势 → 心情
GESTURE_MOODS = {
    "head": "害羞",
    "jump": "开心",
    "squash": "无语",
    "spin": "困",
    "dodge": "生气",
    "shoot": "得意",
}

# 句尾已经像颜文字的形态（括号里没有汉字）
_TAIL_RE = re.compile(r"[（(][^（）()\u4e00-\u9fff]{1,24}[）)][^\u4e00-\u9fff]{0,3}$")
_SYMBOLS = "ヽﾉ∀ωФД∇≧≦▽△☆★≧╯╰°✧♡♥ミ◡ω"


def all_kaomoji():
    out = []
    for group in GROUPS.values():
        out.extend(group)
    return out


def pick(mood="开心", rng=None):
    """按心情取一个（心情没有就用"开心"）。"""
    group = GROUPS.get(mood) or GROUPS["开心"]
    return (rng or random).choice(group)


def mood_for_gesture(kind, affection=None):
    if kind in GESTURE_MOODS:
        return GESTURE_MOODS[kind]
    return mood_for_affection(affection if affection is not None else 50)


def has_kaomoji(text):
    """句尾是不是已经有颜文字了。"""
    tail = (text or "").rstrip()
    if not tail:
        return False
    if _TAIL_RE.search(tail):
        return True
    # 没有括号但带一堆颜文字符号的（比如 zzZ、°▽°）
    return any(ch in _SYMBOLS for ch in tail[-4:])


def decorate(text, mood="开心", rate=1.0, rng=None):
    """在句子后面贴一个颜文字。已经有就不贴；rate<1 时按概率贴。"""
    text = (text or "").rstrip()
    if not text or has_kaomoji(text):
        return text
    rng = rng or random
    if rate < 1.0 and rng.random() > rate:
        return text
    return text + " " + pick(mood, rng)
