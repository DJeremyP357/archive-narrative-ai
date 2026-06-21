import asyncio
import json
import re
import time
import uuid
from abc import ABC, abstractmethod
from collections import deque
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from core.llm_client import LLMClient, LLMProvider, MultiLLMRouter
from core.tool_registry import ToolRegistry


# -----------------------------------------------------------------------------
# 内置的极简 AgentMemory（替代原 core/memory.py）
# 原实现只 remember 不 recall，且不持久化，简化在 Agent 内部维护
# -----------------------------------------------------------------------------


class _ShortTermMemory:
    """短期记忆 — 记录当前任务的思考/行动/观察序列"""

    def __init__(self):
        self._items: List[Dict] = []

    def add(self, item: Dict) -> None:
        self._items.append(item)

    def clear(self) -> None:
        self._items.clear()

    def get_all(self) -> List[Dict]:
        return list(self._items)


class _AgentMemory:
    """AgentMemory 轻量版：保留 remember/recall 语义，但不依赖外部模块"""

    def __init__(self, name: str):
        self.name = name
        self.short_term = _ShortTermMemory()

    def remember(self, key: str, value: Any, meta: Optional[Dict] = None) -> None:
        self.short_term.add({"key": key, "value": value, "meta": meta or {}, "ts": datetime.now().isoformat()})

    def recall(self, key: str) -> Optional[Any]:
        for item in reversed(self.short_term.get_all()):
            if item["key"] == key:
                return item["value"]
        return None

    def clear_short_term(self) -> None:
        self.short_term.clear()

    def add_user_message(self, content: str) -> None:
        self.remember(f"user_msg_{int(time.time()*1000)}", content, {"role": "user"})

    def add_thought(self, thought: str) -> None:
        self.remember(f"thought_{int(time.time()*1000)}", thought, {"role": "thought"})

    def add_tool_result(self, tool: str, result: str) -> None:
        self.remember(f"tool_{tool}_{int(time.time()*1000)}", result[:500], {"role": "tool"})


# 为兼容外部 from core.memory import AgentMemory 重导出
AgentMemory = _AgentMemory


# -----------------------------------------------------------------------------
# 内置的极简 MessageBus（替代原 core/message_bus.py）
# 原实现注册了 Agent 但不通信，简化为最小 API 兼容
# -----------------------------------------------------------------------------


class _MessageType(str, Enum):
    TASK_REQUEST = "task_request"
    TASK_RESULT = "task_result"
    QUERY = "query"
    QUERY_RESPONSE = "query_response"
    INFO = "info"


class _AgentMessage:
    def __init__(self, sender: str, receiver: str, msg_type: _MessageType,
                 content: Any = None, reply_to: Optional[str] = None):
        self.id = str(uuid.uuid4())
        self.sender = sender
        self.receiver = receiver
        self.msg_type = msg_type
        self.content = content
        self.reply_to = reply_to
        self.timestamp = datetime.now().isoformat()


class _MessageBus:
    def __init__(self):
        self._agents: Dict[str, Callable] = {}
        self._queues: Dict[str, asyncio.Queue] = {}

    def register_agent(self, name: str, handler: Callable) -> None:
        self._agents[name] = handler
        self._queues.setdefault(name, asyncio.Queue())

    async def send(self, message: _AgentMessage) -> None:
        if message.receiver in self._agents:
            await self._queues[message.receiver].put(message)
            handler = self._agents[message.receiver]
            try:
                await handler(message)
            except Exception:
                pass

    async def send_task(self, sender: str, receiver: str, task: str, parameters: Optional[Dict] = None) -> str:
        msg = _AgentMessage(sender, receiver, _MessageType.TASK_REQUEST,
                            content={"task": task, "parameters": parameters or {}})
        await self.send(msg)
        return msg.id

    async def send_result(self, sender: str, receiver: str, result: Any, reply_to: Optional[str] = None) -> None:
        await self.send(_AgentMessage(sender, receiver, _MessageType.TASK_RESULT, content=result, reply_to=reply_to))

    async def receive(self, name: str, timeout: float = 0.0) -> Optional[_AgentMessage]:
        q = self._queues.get(name)
        if not q:
            return None
        try:
            if timeout <= 0:
                return q.get_nowait()
            return await asyncio.wait_for(q.get(), timeout=timeout)
        except (asyncio.QueueEmpty, asyncio.TimeoutError):
            return None


# 兼容外部 from core.message_bus import ... 的重导出
MessageBus = _MessageBus
AgentMessage = _AgentMessage
MessageType = _MessageType


class ReActAgentStatus(str, Enum):
    IDLE = "idle"
    THINKING = "thinking"
    ACTING = "acting"
    OBSERVING = "observing"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"


class ReActAgent(ABC):
    def __init__(
        self,
        name: str,
        description: str,
        llm_router: MultiLLMRouter,
        tool_categories: Optional[List[str]] = None,
        max_iterations: int = 15,
    ):
        self.name = name
        self.description = description
        self.llm_router = llm_router
        self.tool_registry = ToolRegistry()
        self.tool_categories = tool_categories or []
        self.max_iterations = max_iterations
        self.status = ReActAgentStatus.IDLE
        self.memory = AgentMemory(name)
        self.message_bus = MessageBus()
        self.message_bus.register_agent(name, self._handle_message)
        self._task_history: List[Dict] = []
        self._current_iteration = 0

    def _build_system_prompt(self) -> str:
        tools_desc = ""
        schemas = self.tool_registry.get_schemas(self.tool_categories or None)
        if schemas:
            tools_desc = "\n\n你可以使用以下工具：\n"
            for schema in schemas:
                func = schema["function"]
                tools_desc += f"- {func['name']}: {func['description']}\n"
                params = func.get("parameters", {}).get("properties", {})
                if params:
                    for pname, pinfo in params.items():
                        tools_desc += f"    - {pname}: {pinfo.get('description', '')}\n"
            tools_desc += "\n"

        return (
            f"你是 {self.name}，{self.description}。\n"
            f"{tools_desc}"
            "你必须严格按照 ReAct 模式工作：\n"
            "1. 思考(Thought): 分析当前情况，决定下一步行动\n"
            "2. 行动(Action): 选择一个工具并调用，或者直接给出回答\n"
            "3. 观察(Observation): 查看行动的结果\n"
            "4. 重复以上步骤直到任务完成\n\n"
            "输出格式：\n"
            "思考: <你的推理过程>\n"
            "行动: <工具名称>|<JSON参数> 或 回答: <最终答案>\n\n"
            "重要规则：\n"
            "- 每次只执行一个行动\n"
            "- 如果已有足够信息，直接用「回答:」给出最终答案\n"
            "- 如果工具调用失败，尝试其他方法\n"
            "- 最多进行15轮思考-行动循环"
        )

    def _parse_response(self, response_text: str) -> Dict[str, Any]:
        thought = ""
        action = None
        answer = None

        thought_match = re.search(
            r"思考[：:]\s*(.+?)(?=\n行动[：:]|\n回答[：:]|$)",
            response_text,
            re.DOTALL,
        )
        if thought_match:
            thought = thought_match.group(1).strip()

        action_match = re.search(
            r"行动[：:]\s*(.+?)(?=\n思考[：:]|\n回答[：:]|$)",
            response_text,
            re.DOTALL,
        )
        if action_match:
            action_text = action_match.group(1).strip()
            if "|" in action_text:
                parts = action_text.split("|", 1)
                tool_name = parts[0].strip()
                try:
                    tool_args = json.loads(parts[1].strip())
                except json.JSONDecodeError:
                    tool_args = {"input": parts[1].strip()}
                action = {"tool": tool_name, "args": tool_args}
            else:
                action = {"tool": action_text, "args": {}}

        answer_match = re.search(r"回答[：:]\s*(.+?)$", response_text, re.DOTALL)
        if answer_match:
            answer = answer_match.group(1).strip()

        return {"thought": thought, "action": action, "answer": answer}

    async def _think_and_act(self, task: str, context: Dict = None) -> Dict[str, Any]:
        self.status = ReActAgentStatus.THINKING
        self.memory.clear_short_term()
        self.memory.add_user_message(task)
        self._current_iteration = 0

        messages = [
            {"role": "system", "content": self._build_system_prompt()},
            {"role": "user", "content": task},
        ]

        if context:
            context_str = json.dumps(context, ensure_ascii=False, default=str)
            messages.append(
                {"role": "user", "content": f"上下文信息：\n{context_str}"}
            )

        while self._current_iteration < self.max_iterations:
            self._current_iteration += 1

            self.status = ReActAgentStatus.THINKING
            try:
                response = await self.llm_router.chat_with_fallback(messages)
                response_text = response["choices"][0]["message"]["content"]
            except Exception as e:
                self.status = ReActAgentStatus.FAILED
                return {
                    "success": False,
                    "error": f"LLM调用失败: {str(e)}",
                    "iterations": self._current_iteration,
                }

            parsed = self._parse_response(response_text)

            if parsed["thought"]:
                self.memory.add_thought(parsed["thought"])
                messages.append({"role": "assistant", "content": response_text})

            if parsed["answer"]:
                self.status = ReActAgentStatus.COMPLETED
                return {
                    "success": True,
                    "answer": parsed["answer"],
                    "thought": parsed["thought"],
                    "iterations": self._current_iteration,
                }

            if parsed["action"]:
                self.status = ReActAgentStatus.ACTING
                tool_name = parsed["action"]["tool"]
                tool_args = parsed["action"]["args"]

                tool_result = await self.tool_registry.execute(tool_name, tool_args)

                self.status = ReActAgentStatus.OBSERVING
                self.memory.add_tool_result(tool_name, tool_result)

                observation = f"观察: 工具 [{tool_name}] 返回结果：\n{tool_result[:2000]}"
                messages.append({"role": "user", "content": observation})

                self.memory.remember(
                    f"tool_call_{self._current_iteration}",
                    tool_result[:500],
                    {"tool": tool_name, "args": tool_args},
                )
            else:
                messages.append(
                    {
                        "role": "user",
                        "content": "请按照格式输出：先写「思考:」，再写「行动:」或「回答:」",
                    }
                )

        self.status = ReActAgentStatus.FAILED
        return {
            "success": False,
            "error": "达到最大迭代次数，未能完成任务",
            "iterations": self._current_iteration,
        }

    async def _handle_message(self, message: AgentMessage):
        if message.msg_type == MessageType.TASK_REQUEST:
            task = message.content.get("task", "")
            params = message.content.get("parameters", {})
            result = await self._think_and_act(task, params)
            await self.message_bus.send_result(
                sender=self.name,
                receiver=message.sender,
                result=result,
                reply_to=message.id,
            )
        elif message.msg_type == MessageType.QUERY:
            answer = await self.answer_query(message.content)
            response = AgentMessage(
                sender=self.name,
                receiver=message.sender,
                msg_type=MessageType.QUERY_RESPONSE,
                content=answer,
                reply_to=message.id,
            )
            await self.message_bus.send(response)

    @abstractmethod
    async def answer_query(self, question: str) -> str:
        pass

    async def delegate_to(self, agent_name: str, task: str, params: Dict = None) -> Optional[Dict]:
        task_id = await self.message_bus.send_task(
            sender=self.name, receiver=agent_name, task=task, parameters=params
        )
        timeout = 120.0
        start = time.time()
        while time.time() - start < timeout:
            msg = await self.message_bus.receive(self.name, timeout=2.0)
            if msg and msg.msg_type == MessageType.TASK_RESULT and msg.reply_to == task_id:
                return msg.content
        return None

    async def run(self, task: str, context: Dict = None) -> Dict[str, Any]:
        start_time = time.time()
        result = await self._think_and_act(task, context)
        elapsed = time.time() - start_time

        self._task_history.append(
            {
                "task": task[:200],
                "result": result,
                "iterations": self._current_iteration,
                "elapsed": round(elapsed, 2),
                "timestamp": datetime.now().isoformat(),
            }
        )

        return result

    def get_status(self) -> Dict:
        return {
            "name": self.name,
            "status": self.status.value,
            "iteration": self._current_iteration,
            "task_count": len(self._task_history),
            "memory_items": len(self.memory.short_term.get_all()),
        }
