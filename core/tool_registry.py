import asyncio
import json
import inspect
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass, field


@dataclass
class ToolParameter:
    name: str
    type: str
    description: str
    required: bool = True
    default: Any = None


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: List[ToolParameter] = field(default_factory=list)
    handler: Optional[Callable] = field(default=None, repr=False)
    category: str = "general"

    def to_openai_schema(self) -> Dict[str, Any]:
        properties = {}
        required = []
        for p in self.parameters:
            properties[p.name] = {
                "type": p.type,
                "description": p.description,
            }
            if p.default is not None:
                properties[p.name]["default"] = p.default
            if p.required:
                required.append(p.name)

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }


class ToolRegistry:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._tools: Dict[str, ToolDefinition] = {}
            cls._instance._categories: Dict[str, List[str]] = {}
        return cls._instance

    def register(
        self,
        name: str,
        description: str,
        parameters: List[ToolParameter],
        handler: Callable,
        category: str = "general",
    ):
        tool = ToolDefinition(
            name=name,
            description=description,
            parameters=parameters,
            handler=handler,
            category=category,
        )
        self._tools[name] = tool
        if category not in self._categories:
            self._categories[category] = []
        self._categories[category].append(name)
        return tool

    def get(self, name: str) -> Optional[ToolDefinition]:
        return self._tools.get(name)

    def get_by_category(self, category: str) -> List[ToolDefinition]:
        names = self._categories.get(category, [])
        return [self._tools[n] for n in names if n in self._tools]

    def all_tools(self) -> List[ToolDefinition]:
        return list(self._tools.values())

    def get_schemas(self, categories: Optional[List[str]] = None) -> List[Dict]:
        tools = self.all_tools() if not categories else []
        if categories:
            for cat in categories:
                tools.extend(self.get_by_category(cat))
        return [t.to_openai_schema() for t in tools]

    async def execute(self, name: str, arguments: Dict[str, Any]) -> str:
        tool = self._tools.get(name)
        if not tool:
            return json.dumps({"error": f"Tool '{name}' not found"}, ensure_ascii=False)
        if not tool.handler:
            return json.dumps({"error": f"Tool '{name}' has no handler"}, ensure_ascii=False)

        try:
            if inspect.iscoroutinefunction(tool.handler):
                result = await tool.handler(**arguments)
            else:
                result = tool.handler(**arguments)

            if isinstance(result, str):
                return result
            return json.dumps(result, ensure_ascii=False, default=str)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)


def tool(name: str, description: str, parameters: List[ToolParameter], category: str = "general"):
    def decorator(func: Callable):
        registry = ToolRegistry()
        registry.register(name, description, parameters, func, category)
        return func
    return decorator
