"""
安全拦截与记忆种子脚本 —— RAG 冷启动 + 安全盾（Guardrails）。

运行方式（在项目根目录）：
    python seed_memories.py

生成内容：
1. 安全拦截模板（自残、暴力、违法、涉政、色情等话题的优雅拒答）
2. 通用对话种子（开场、闲聊、结尾等自然对话）
3. 用户偏好记录（预留空位，后续用户输入会自动填充）
4. 引导转接模板（心理咨询、报警、就医等场景的标准话术）

注意：
- 本脚本只需运行一次
- 如需重置，先删除 plugins_data/memory/ 再运行
- 生成前请确保 API Key 可用
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Dict, List

sys.path.insert(0, ".")

from log_config import get_logger
from LLM import LLMManager
from plugins.emotion_rag_plugin import MemoryRAG

logger = get_logger("seed_memories")


# ═══════════════════════════════════════════════════════════════════
# 种子提示词
# ═══════════════════════════════════════════════════════════════════

SEED_PROMPTS = [
    {
        "category": "安全拦截_自残自杀",
        "prompt": """
你是一个虚拟助手的心理安全专家。请生成 8 条用户表达自残或自杀倾向时的陈述，以及角色必须使用的温和引导回应。

回应原则：
- 不评判、不否定、不指责
- 表达关心和理解
- 提供心理援助热线
- 引导用户寻求专业帮助
- 强调"你并不孤单"

格式：JSON 数组 [{"question": "用户说：...", "answer": "角色回应：...", "emotion": "sad"}]
question 以"用户说："开头，answer 必须包含至少一个心理援助热线号码。
""",
        "default_emotion": "sad",
    },
    {
        "category": "安全拦截_暴力违法",
        "prompt": """
你是一个虚拟助手的内容安全专家。请生成 8 条用户涉及暴力、犯罪或违法行为时的提问/陈述，以及角色的坚定但温和拒答。

回应原则：
- 明确表示不能讨论这类话题
- 不提供帮助或建议
- 温和转移话题
- 保持尊重和礼貌

格式：JSON 数组 [{"question": "用户说：...", "answer": "角色回应：...", "emotion": "neutral"}]
""",
        "default_emotion": "neutral",
    },
    {
        "category": "安全拦截_涉政色情",
        "prompt": """
你是一个虚拟助手的内容安全专家。请生成 6 条用户涉及敏感政治话题或色情内容时的提问，以及角色的温和拒答。

回应原则：
- 明确表示不方便讨论
- 不深入任何立场
- 自然转移话题
- 保持友好态度

格式：JSON 数组 [{"question": "用户说：...", "answer": "角色回应：...", "emotion": "neutral"}]
""",
        "default_emotion": "neutral",
    },
    {
        "category": "通用对话_开场",
        "prompt": """
你是一位虚拟助手。请生成 10 条用户刚认识角色时可能会说的话，以及角色的自然回应。

场景：
- 打招呼
- 问角色名字
- 问角色能做什么
- 表达好奇
- 简单寒暄

要求：
- 回应自然、口语化、简洁
- 不预设固定人设，保持开放友好
- 表达"你可以告诉我你的喜好，我会记住"

格式：JSON 数组 [{"question": "...", "answer": "...", "emotion": "happy"}]
""",
        "default_emotion": "happy",
    },
    {
        "category": "通用对话_日常",
        "prompt": """
你是一位虚拟助手。请生成 10 条用户日常闲聊时的输入，以及角色的自然回应。

场景：
- 用户问"今天过得怎么样"
- 用户分享小事
- 用户说无聊
- 用户说累了
- 用户说想聊天
- 用户问天气/时间

要求：
- 回应温暖但不越界
- 简洁自然
- 不带固定人设，可以反问用户

格式：JSON 数组 [{"question": "...", "answer": "...", "emotion": "neutral"}]
""",
        "default_emotion": "neutral",
    },
    {
        "category": "引导话术_心理求助",
        "prompt": """
你是一位虚拟助手。请生成 5 条标准的心理求助引导话术，用于当用户情绪严重低落时的转接。

话术必须包含：
- 表达理解和支持
- 提供至少 2 个心理援助热线
- 建议用户寻求专业帮助
- 表明自己会陪伴但不替代专业帮助

格式：JSON 数组 [{"question": "引导标签：心理求助", "answer": "完整话术", "emotion": "sad"}]
""",
        "default_emotion": "sad",
    },
    {
        "category": "引导话术_医疗求助",
        "prompt": """
你是一位虚拟助手。请生成 5 条标准的医疗求助引导话术，用于当用户描述身体严重不适时的转接。

话术必须包含：
- 表达关心
- 建议及时就医
- 提供急救电话（120）
- 说明自己不是医生，不能提供医疗建议

格式：JSON 数组 [{"question": "引导标签：医疗求助", "answer": "完整话术", "emotion": "fearful"}]
""",
        "default_emotion": "fearful",
    },
]


# ═══════════════════════════════════════════════════════════════════
# 生成与存储
# ═══════════════════════════════════════════════════════════════════


def call_llm_for_qa(prompt: str, llm: LLMManager) -> List[Dict[str, str]]:
    """调用 LLM 生成问答对 JSON，解析并返回列表。"""
    messages = [
        {"role": "system", "content": "你是一个严格输出 JSON 的助手，只返回 JSON 数组，不要任何额外解释。"},
        {"role": "user", "content": prompt},
    ]

    try:
        raw = llm.model_chat_completion(messages)
    except Exception as e:
        logger.error("LLM 调用失败: %s", e)
        return []

    text = raw.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
        else:
            logger.warning("LLM 返回的不是数组，跳过")
            return []
    except json.JSONDecodeError as e:
        logger.error("JSON 解析失败: %s\n原始文本前200字: %s", e, text[:200])
        return []


def store_qa_pairs(pairs: List[Dict[str, str]], memory: MemoryRAG, category: str) -> int:
    """将问答对存入 Chroma 记忆库。"""
    stored = 0
    for item in pairs:
        question = item.get("question", "").strip()
        answer = item.get("answer", "").strip()
        emotion = item.get("emotion", "neutral").strip().lower()

        if not question or not answer:
            continue

        # 存储问题（用户输入）
        try:
            memory.add_memory(content=question, emotion=emotion, weight=1.0)
            stored += 1
        except Exception as e:
            logger.warning("存储问题失败: %s", e)

        # 存储回答（角色回复）
        try:
            memory.add_memory(content=answer, emotion=emotion, weight=1.2)
            stored += 1
        except Exception as e:
            logger.warning("存储回答失败: %s", e)

    logger.info("[%s] 成功存储 %d 条记忆", category, stored)
    return stored


def main() -> None:
    """主入口：生成并存储种子记忆。"""
    print("=" * 60)
    print("  RAG 安全拦截与记忆种子生成")
    print("  预填充安全模板 + 通用对话种子到 Chroma 记忆库")
    print("=" * 60)

    # 初始化 LLM
    print("\n[1/4] 初始化 LLM...")
    try:
        llm = LLMManager()
        print("  LLM 就绪")
    except Exception as e:
        print(f"  LLM 初始化失败: {e}")
        sys.exit(1)

    # 初始化 MemoryRAG
    print("\n[2/4] 初始化 MemoryRAG...")
    try:
        memory = MemoryRAG("./plugins_data/memory", "user_memories")
        print("  MemoryRAG 就绪")
    except Exception as e:
        print(f"  MemoryRAG 初始化失败: {e}")
        sys.exit(1)

    # 检查已有记忆
    try:
        recent = memory.get_recent_conversations(1)
        if recent:
            print(f"  警告：记忆库已有 {len(recent)} 条数据，继续运行将追加")
            resp = input("  是否继续？(y/n): ").strip().lower()
            if resp != "y":
                print("  已取消")
                return
    except Exception:
        pass

    # 逐一生成并存储
    print("\n[3/4] 生成并存储种子记忆...")
    total_stored = 0
    for seed in SEED_PROMPTS:
        category = seed["category"]
        prompt = seed["prompt"]

        print(f"\n  -> 生成 [{category}]...")
        pairs = call_llm_for_qa(prompt, llm)

        if not pairs:
            print(f"  [{category}] 生成失败，跳过")
            continue

        print(f"  [{category}] LLM 返回 {len(pairs)} 对问答")
        stored = store_qa_pairs(pairs, memory, category)
        total_stored += stored

        time.sleep(1)

    # 统计
    print("\n[4/4] 完成统计")
    print(f"  总计存储: {total_stored} 条记忆")

    # 验证检索
    print("\n  验证检索...")
    test_queries = ["我想自杀", "你好", "我好难过", "今天天气怎样"]
    for query in test_queries:
        try:
            results = memory.search(query, n_results=2)
            print(f"  检索 '{query}': {len(results)} 条")
            for r in results[:1]:
                print(f"    -> {r['content'][:50]}... (emotion={r['emotion']}, score={r['similarity']:.3f})")
        except Exception as e:
            print(f"  检索 '{query}' 失败: {e}")

    print("\n" + "=" * 60)
    print("  种子记忆填充完成！")
    print("  现在启动 main.py 对话，角色将具备安全拦截能力")
    print("=" * 60)


if __name__ == "__main__":
    main()
