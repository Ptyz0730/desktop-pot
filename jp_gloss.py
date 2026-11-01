#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""日语台词的"下面一行"中文翻译。

郑迪隆（骚话少年）说话中日语混着来，玩家不一定看得懂。这里做两件事：

  1. 模型把翻译写在同一行（「気持ちいい（好舒服啊）」）—— 拆成两行，
     日语在上、中文在下；
  2. 模型忘了翻译 —— 用固定的骚话库补一行。

只认**含假名**的句子（「月色真美」是中文暗号，故意不翻译，翻了就不含蓄了）。
没登记过的日语不硬翻，交给提示词让模型自己补括号，避免瞎猜。

对外：
    jp_gloss.add_gloss(text) -> text   幂等，反复调用不会重复加
    jp_gloss.translate(jp)   -> str|"" 单词/短句的固定译法
"""
import re

# 用户给的骚话库 + 两句暗号（长的放前面：先匹配「好きすぎて困る」再「好き」）
_GLOSS_PAIRS = (
    ("ちょっとドキドキする", "有点心跳加速"),
    ("好きすぎて困る", "喜欢到没办法"),
    ("もっと近くに来て", "再靠近一点"),
    ("君のこと、好きだよ", "喜欢你哦"),
    ("君のこと好きだよ", "喜欢你哦"),
    ("毎日会いたい", "每天都想见你"),
    ("抱きしめたい", "想抱你"),
    ("離さないよ", "不放你走哦"),
    ("君だけだよ", "只有你哦"),
    ("ドキドキする", "心跳加速"),
    ("気持ちいい", "好舒服啊"),
    ("きもちいい", "好舒服啊"),
    ("ずるいよ", "你好狡猾"),
    ("もう一回", "再来一次"),
    ("嘘つき", "骗子"),
    ("寂しい", "好寂寞"),
    ("バカ", "笨蛋"),
    ("好きだよ", "喜欢你哦"),
)

GLOSS = dict(_GLOSS_PAIRS)

# 假名（平假名 + 片假名）：只有含假名的句子才需要翻译
_KANA = re.compile(r"[\u3040-\u309f\u30a0-\u30ff]")
# 句末的「（中文）」：模型自带翻译时会被拆到下一行
_TAIL_PAREN = re.compile(r"[（(]([^（）()]{1,20})[）)]\s*$")
_CN_VALUES = frozenset(cn for _, cn in _GLOSS_PAIRS)


def has_kana(text):
    return bool(_KANA.search(str(text or "")))


def translate(jp):
    """一句日语（可能混着中文/符号）的固定译法；没登记返回空串。"""
    line = str(jp or "")
    for phrase, cn in _GLOSS_PAIRS:
        if phrase in line:
            return cn
    return ""


def _looks_like_translation(inner):
    """括号里是不是中文译文。

    只认骚话库里登记过的译法。之前用"含汉字且不含代词"判断，结果颜文字
    「（＃￣皿￣）」里的「皿」是汉字，被当成译文把翻译吞掉了。
    """
    return inner.strip() in _CN_VALUES


_WHOLE_PAREN = re.compile(r"^[（(]([^（）()]{1,20})[）)]$")


def _paren_cn(line):
    """整行就是「（中文）」时取出括号里的内容，否则空串。"""
    m = _WHOLE_PAREN.match(str(line or "").strip())
    return m.group(1).strip() if m else ""


def add_gloss(text):
    """给日语那句的下面补一行中文；已经有翻译就不动（幂等）。"""
    raw = str(text or "")
    if not raw.strip():
        return raw
    lines = raw.split("\n")
    out = []
    for i, line in enumerate(lines):
        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
        # 下一行已经是登记过的译文，就别再加一遍
        already_below = _paren_cn(nxt) in _CN_VALUES
        if not has_kana(line) or already_below:
            out.append(line)
            continue
        # 1) 同一行末尾自带「（中文）」——拆成上下两行
        m = _TAIL_PAREN.search(line)
        if m and _looks_like_translation(m.group(1)):
            head = line[:m.start()].rstrip()
            if head:
                out.append(head)
                out.append("（%s）" % m.group(1).strip())
                continue
        # 2) 没翻译：查固定译法（同一行已经写了中文就别重复补）
        cn = translate(line)
        out.append(line)
        if cn and cn not in line:
            out.append("（%s）" % cn)
    return "\n".join(out)
