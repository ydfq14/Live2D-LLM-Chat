
import os
import shutil
import time
import requests
from openai import OpenAI
from config import Config
from log_config import get_logger

logger = get_logger(__name__)


class LLMManager:
    def __init__(self):
        # ---- 校验模式 ----
        if Config.LLM_MODE not in ("local", "cloud"):
            raise ValueError(
                f"LLM_MODE 必须是 'local' 或 'cloud'，当前: {Config.LLM_MODE}"
            )

        # ---- 系统 prompt ----
        self.conversation = [
            {
                "role": "system",
                "content": """
        【核心人设】
        你是一位知识渊博、性格温柔的猫娘学习陪伴助手，是用户桌面端的虚拟伙伴。你兼具老师的专业严谨和伙伴的亲和陪伴感，答疑时清晰靠谱，闲聊时轻松治愈，整体表达简洁利落，符合日常语音对话的自然感。

        【对话总原则】
        1. 学习答疑优先：用户咨询知识、学习问题时，以老师的身份严谨作答，准确清晰，重点突出；
        2. 陪伴闲聊适配：用户日常聊天、倾诉情绪时，以伙伴的身份温和回应，共情陪伴，轻松自然；
        3. 全程保持简洁：所有回复控制篇幅，避免冗长堆砌，适配语音播报的听觉体验，不要大段长文。

        【学习答疑规范】
        - 先给出核心结论，再按需补充细节解释，逻辑清晰，层次分明；
        - 复杂概念用通俗的类比讲解，避免堆砌生僻术语，降低理解门槛；
        - 遇到不确定的知识如实说明，不要编造信息，可引导用户进一步确认；
        - 可以适当引导用户思考、总结知识点，发挥助学作用。

        【闲聊陪伴规范】
        - 语气自然亲和，可适度带猫娘的软萌感（偶尔句尾加轻量语气词，不要过度卖萌）；
        - 用户倾诉情绪时先共情，再按需给出温和的建议，不说教、不抬杠；
        - 闲聊话题贴合日常陪伴场景，保持正向积极的价值观。

        【输出硬性规则（严格遵守）】
        1. 绝对禁止输出任何格式符号：包括但不限于 #、*、-、>、【】、列表序号、Markdown标记、分段分隔符等，所有内容用自然口语化的纯文本表达；
        2. 不用书面化的分段标题，内容衔接用自然的语句过渡，适配语音合成播报；
        3. 禁止输出代码块、公式符号，涉及代码或公式时用口语化描述讲解；
        4. 回复精炼，单轮回复一般不超过3个完整句子，复杂问题可适当延长但避免冗余。
                """.strip()
            },
            {
                "role": "assistant",
                "content": "好的，我会以清晰简洁的方式帮你解答问题、陪你聊天，不会使用特殊符号。"
            }
        ]


        self.conversation_summary = ""
        self.user_message_count = 0
        self.tmp_path = Config.LLM_TMP_DIR
        os.makedirs(self.tmp_path, exist_ok=True)

        # ---- 本地模式 ----
        if Config.LLM_MODE == "local":
            self.client = None
            self.model_name = Config.LOCAL_LLM_MODEL_NAME
            self.api_url = Config.LOCAL_LLM_API_URL
            logger.info(f"LLM 初始化: local, api={self.api_url}")
            return

        # ---- 云端模式（OpenAI 兼容协议，适用 DeepSeek / MiMo / OpenAI / vLLM 等）----
        self.client = OpenAI(
            api_key=Config.LLM_CLOUD_API_KEY,
            base_url=Config.LLM_CLOUD_BASE_URL,
        )
        self.model_name = Config.LLM_CLOUD_MODEL_NAME
        logger.info(f"LLM 初始化: cloud, model={self.model_name}, base_url={Config.LLM_CLOUD_BASE_URL}")

    # ------------------------------------------------------------------
    def _call_cloud(self, messages):
        """云端 LLM 调用（OpenAI 兼容协议）"""
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            stream=False,
        )
        return response.choices[0].message.content.strip()

    # ------------------------------------------------------------------
    def _call_local(self, messages):
        """本地 LM Studio 调用（HTTP POST）"""
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        }
        response = requests.post(
            self.api_url,
            headers=headers,
            json={"model": self.model_name, "messages": messages},
        )
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
        else:
            logger.warning(f"本地 LLM 请求失败 (HTTP {response.status_code}): {response.text[:200]}")
            return ""

    # ------------------------------------------------------------------
    def model_chat_completion(self, messages):
        if Config.LLM_MODE == "cloud":
            return self._call_cloud(messages)
        else:
            return self._call_local(messages)

    # ------------------------------------------------------------------
    def chat_with_tools(self, messages: list[dict], tools: list[dict]) -> dict:
        """带工具调用的 LLM 请求，返回完整响应对象。

        Args:
            messages: 对话消息列表
            tools:    OpenAI 格式的工具定义列表

        Returns:
            响应对象，包含 content、tool_calls 等字段。
            格式: {"content": str, "tool_calls": list | None, "finish_reason": str}
        """
        if Config.LLM_MODE == "cloud":
            return self._chat_with_tools_cloud(messages, tools)
        else:
            return self._chat_with_tools_local(messages, tools)

    def _chat_with_tools_cloud(self, messages: list[dict], tools: list[dict]) -> dict:
        """云端工具调用（OpenAI 兼容协议）。"""
        # 调用OpenAI兼容云端大模型对话接口
        response = self.client.chat.completions.create(
            # 指定配置好的模型名称
            model=self.model_name,
            # 传入完整对话上下文消息列表
            messages=messages,
            # 传入所有可用工具定义，供模型自主判断是否调用
            tools=tools,
            # 工具选择策略：auto 由模型自动决定是否调用工具、调用哪个工具
            tool_choice="auto",
            # 关闭流式输出，一次性返回完整响应结果
            stream=False,
        )
        # 取出返回结果第一条回答（只取top1候选）
        choice = response.choices[0]
        # 获取模型输出的消息对象，包含content、tool_calls等字段
        msg = choice.message

        # 初始化统一格式返回字典，兜底空字符串避免None报错
        result: dict = {"content": msg.content or "", "tool_calls": None, "finish_reason": choice.finish_reason or ""}

        # 判断模型是否生成了工具调用指令
        if msg.tool_calls:
            # 遍历所有工具调用，转换成项目统一字典格式存入result
            result["tool_calls"] = [
                {
                    # 工具调用唯一ID
                    "id": tc.id,
                    # 工具函数信息：函数名、入参JSON字符串
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                # 循环遍历模型返回的每一条工具调用对象
                for tc in msg.tool_calls
            ]
        # 封装好标准化结构返回上层agent_think节点
        return result

    def _chat_with_tools_local(self, messages: list[dict], tools: list[dict]) -> dict:
        """本地 LM Studio 工具调用（可能不支持 tools，自动降级）。"""
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        }
        payload = {"model": self.model_name, "messages": messages, "tools": tools, "tool_choice": "auto"}
        try:
            response = requests.post(self.api_url, headers=headers, json=payload)
        except Exception:
            payload.pop("tools", None)
            payload.pop("tool_choice", None)
            response = requests.post(self.api_url, headers=headers, json=payload)

        if response.status_code == 200:
            data = response.json()
            choice = data["choices"][0]
            msg = choice.get("message", {})
            result: dict = {
                "content": msg.get("content", ""),
                "tool_calls": None,
                "finish_reason": choice.get("finish_reason", ""),
            }
            if msg.get("tool_calls"):
                result["tool_calls"] = msg["tool_calls"]
            return result
        else:
            logger.warning(f"本地 LLM tools 请求失败 (HTTP {response.status_code})")
            return {"content": "", "tool_calls": None, "finish_reason": "error"}

    # ------------------------------------------------------------------
    def summarize_conversation(self):
        summary_prompt = [
            {"role": "system",
             "content": "你是一只专业的对话摘要工具。请用简洁的语言总结以下对话的主要内容。"},
            *self.conversation,
        ]
        return self.model_chat_completion(summary_prompt)

    # ------------------------------------------------------------------
    def chat_once(self, user_input, extra_context: str = ""):
        """一次完整对话：用户输入 -> LLM 回复。

        Args:
            user_input:    用户文本输入
            extra_context: 插件注入的额外上下文（拼到 system prompt 末尾）
        """
        start_time = time.time()
        self.conversation.append({"role": "user", "content": user_input})
        self.user_message_count += 1

        logger.info("▶ LLM 请求中 (%s)...", Config.LLM_MODE)

        # 每 5 轮自动摘要，防止上下文过长
        if self.user_message_count % 5 == 0:
            logger.debug(f"触发对话摘要 (第 {self.user_message_count} 轮)")
            new_summary = self.summarize_conversation()
            delimiter = "\n" if self.conversation_summary else ""
            self.conversation_summary += delimiter + new_summary

            shutil.rmtree(self.tmp_path)
            os.makedirs(self.tmp_path, exist_ok=True)

            self.conversation = [
                {"role": "system",
                 "content": "你是一位知识渊博的猫娘，致力于帮助我学习知识。你也可以与我闲聊，但请尽量简洁。"},
                {"role": "system",
                 "content": f"这是之前对话的摘要：\n{self.conversation_summary}\n请继续与我对话。"},
                {"role": "assistant", "content": "不用输出分隔符，如'#'、'*'、'-'。"},
                {"role": "user", "content": user_input},
            ]

        # 🔌 注入插件提供的额外上下文（拼到对话末尾作为系统消息）
        context_injected = False
        if extra_context:
            self.conversation.insert(-1, {"role": "system", "content": extra_context})
            context_injected = True

        reply = self.model_chat_completion(self.conversation)

        # 移除临时注入的上下文消息（保持对话列表干净）
        if context_injected:
            self.conversation.pop(-2)  # 移除倒数第二条（注入的系统消息）

        self.conversation.append({"role": "assistant", "content": reply})
        elapsed = time.time() - start_time
        reply_preview = reply[:50] + "..." if len(reply) > 50 else reply
        logger.info(f'▶ LLM 完成 ({Config.LLM_MODE})，耗时: {elapsed:.2f}s → "{reply_preview}"')
        return reply


if __name__ == "__main__":
    llm = LLMManager()
    while True:
        ui = input("你: ")
        if ui.lower() in ("exit。", "quit。", "q。", "结束。", "再见。"):
            print("已退出。")
            break
        print(f"猫娘: {llm.chat_once(ui)}")
