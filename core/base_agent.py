"""
BaseAgent — 所有 Agent 的抽象基类

当前系统使用 SmartOrchestrator (V2) 作为唯一编排入口。
BaseAgent 提供 Agent 生命周期管理（状态、任务历史）。
"""

from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid


class AgentStatus(Enum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    WAITING = "waiting"


class TaskResult:
    """Agent 任务执行结果"""

    def __init__(self, success: bool, data: Any = None,
                 error: str = None, metadata: Dict = None):
        self.id = str(uuid.uuid4())
        self.success = success
        self.data = data
        self.error = error
        self.metadata = metadata or {}
        self.timestamp = datetime.now()

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat(),
        }


class BaseAgent(ABC):
    """Agent 抽象基类 — 所有 Agent 继承此类"""

    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
        self.status = AgentStatus.IDLE
        self.task_history: List[Dict] = []
        self.current_task: Optional[str] = None

    @abstractmethod
    async def execute(self, task_input: Dict[str, Any]) -> TaskResult:
        """子类必须实现此方法"""

    async def run(self, task_input: Dict[str, Any]) -> TaskResult:
        self.status = AgentStatus.RUNNING
        self.current_task = str(uuid.uuid4())
        try:
            result = await self.execute(task_input)
            self.status = AgentStatus.COMPLETED if result.success else AgentStatus.FAILED
            self.task_history.append({
                "task_id": self.current_task,
                "status": self.status.value,
                "result": result.to_dict(),
            })
            return result
        except Exception as e:
            self.status = AgentStatus.FAILED
            error_result = TaskResult(success=False, error=str(e))
            self.task_history.append({
                "task_id": self.current_task,
                "status": self.status.value,
                "result": error_result.to_dict(),
            })
            return error_result
        finally:
            self.current_task = None

    def get_status(self) -> Dict:
        return {
            "name": self.name,
            "status": self.status.value,
            "current_task": self.current_task,
            "task_count": len(self.task_history),
        }
