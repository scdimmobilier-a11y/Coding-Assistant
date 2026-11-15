"""
Integration layer between the new tools system and modular rollout.
Wraps octotools-style tools for use in staged rollout.
"""

import os
import importlib
from typing import Dict, Any, Optional, List
from openmanus_rl.tools.base import BaseTool


class ToolRegistry:
    """Registry for managing and executing tools."""
    
    def __init__(self):
        self.tools: Dict[str, BaseTool] = {}
        self.tool_instances: Dict[str, Any] = {}
    
    def discover_tools(self, tools_dir: str = "openmanus_rl/tools"):
        """Auto-discover all available tools in the tools directory."""
        tools_found = []
        
        # List all subdirectories in tools
        for item in os.listdir(tools_dir):
            tool_path = os.path.join(tools_dir, item)
            if os.path.isdir(tool_path) and not item.startswith('_'):
                # Check if it has a tool.py file
                tool_module_path = os.path.join(tool_path, 'tool.py')
                if os.path.exists(tool_module_path):
                    tools_found.append(item)
        
        print(f"Discovered tools: {tools_found}")
        return tools_found
    
    def load_tool(self, tool_name: str, model_string: Optional[str] = None) -> Optional[BaseTool]:
        """Load a specific tool by name."""
        try:
            # Import the tool module
            module_path = f"openmanus_rl.tools.{tool_name}.tool"
            module = importlib.import_module(module_path)
            
            # Find the tool class (usually named after the tool)
            # Convert snake_case to CamelCase
            class_name = ''.join(word.capitalize() for word in tool_name.split('_'))
            if hasattr(module, class_name):
                tool_class = getattr(module, class_name)
            else:
                # Try to find any class that inherits from BaseTool
                for name in dir(module):
                    obj = getattr(module, name)
                    if isinstance(obj, type) and issubclass(obj, BaseTool) and obj != BaseTool:
                        tool_class = obj
                        break
                else:
                    print(f"No tool class found in {module_path}")
                    return None
            
            # Instantiate the tool
            if tool_class.require_llm_engine and model_string:
                tool_instance = tool_class(model_string=model_string)
            else:
                tool_instance = tool_class()
            
            self.tools[tool_name] = tool_instance
            return tool_instance
            
        except Exception as e:
            print(f"Failed to load tool {tool_name}: {e}")
            return None
    
    def register_tool(self, name: str, tool: BaseTool):
        """Register a tool instance."""
        self.tools[name] = tool
    
    def execute_tool(self, tool_name: str, params: Dict[str, Any]) -> str:
        """Execute a tool with given parameters."""
        if tool_name not in self.tools:
            # Try to load it
            tool = self.load_tool(tool_name)
            if not tool:
                return f"Error: Tool '{tool_name}' not found"
        else:
            tool = self.tools[tool_name]
        
        try:
            # Execute the tool
            # Map common parameter names
            if 'query' in params and 'text' in tool.input_types:
                params['text'] = params.pop('query')
            elif 'expression' in params and 'code' in tool.input_types:
                params['code'] = params.pop('expression')
            
            result = tool.execute(**params)
            
            # Format result as string
            if isinstance(result, dict):
                return str(result.get('output', result))
            else:
                return str(result)
                
        except Exception as e:
            return f"Error executing {tool_name}: {str(e)}"
    
    def list_tools(self) -> List[str]:
        """List all registered tools."""
        return list(self.tools.keys())
    
    def get_tool_info(self, tool_name: str) -> Dict[str, Any]:
        """Get metadata for a specific tool."""
        if tool_name in self.tools:
            return self.tools[tool_name].get_metadata()
        return {}


def create_tool_wrapper(registry: ToolRegistry):
    """
    Create a wrapper function that matches the simple tool interface.
    This allows octotools to work with our modular system.
    """
    def tool_wrapper(params: Dict[str, Any]) -> str:
        # Extract tool name from params if specified
        tool_name = params.pop('tool', None)
        if not tool_name:
            # Try to infer from params
            if 'image' in params:
                tool_name = 'object_detector'
            elif 'url' in params:
                tool_name = 'url_text_extractor'
            elif 'arxiv' in str(params.get('query', '')).lower():
                tool_name = 'arxiv_paper_searcher'
            else:
                tool_name = 'google_search'  # Default
        
        return registry.execute_tool(tool_name, params)
    
    return tool_wrapper


# Quick tool wrappers for common tools
def create_simple_tool_wrappers(registry: ToolRegistry) -> Dict[str, Any]:
    """Create simple wrapper functions for common tools."""
    
    def search_wrapper(params: dict) -> str:
        """Google search wrapper."""
        return registry.execute_tool('google_search', params)
    
    def arxiv_wrapper(params: dict) -> str:
        """ArXiv search wrapper."""
        return registry.execute_tool('arxiv_paper_searcher', params)
    
    def wikipedia_wrapper(params: dict) -> str:
        """Wikipedia search wrapper."""
        return registry.execute_tool('wikipedia_knowledge_searcher', params)
    
    def python_wrapper(params: dict) -> str:
        """Python code generator wrapper."""
        return registry.execute_tool('python_code_generator', params)
    
    def image_caption_wrapper(params: dict) -> str:
        """Image captioner wrapper."""
        return registry.execute_tool('image_captioner', params)
    
    def object_detect_wrapper(params: dict) -> str:
        """Object detector wrapper."""
        return registry.execute_tool('object_detector', params)
    
    def url_extract_wrapper(params: dict) -> str:
        """URL text extractor wrapper."""
        return registry.execute_tool('url_text_extractor', params)
    
    return {
        'search': search_wrapper,
        'arxiv': arxiv_wrapper,
        'wikipedia': wikipedia_wrapper,
        'python': python_wrapper,
        'caption': image_caption_wrapper,
        'detect': object_detect_wrapper,
        'url': url_extract_wrapper,
    }


# Global registry instance
GLOBAL_TOOL_REGISTRY = ToolRegistry()

# Auto-discover tools on import
import os
tools_path = os.path.join(os.path.dirname(__file__), '..', 'tools')
if os.path.exists(tools_path):
    GLOBAL_TOOL_REGISTRY.discover_tools(tools_path)

# ──────────────────────────────────────────────────────────────────────────────
# UNIFIED SYSTEM — SSRF-safe tool registry
# Inherits ToolRegistry and replaces the raw requests.get calls inside tools
# with the crewAI SSRFProtectedAdapter.  Every HTTP fetch made by an
# OpenManus-RL tool (google_search, url_text_extractor, …) is validated
# against a blocklist of private/reserved IP ranges before the socket connects.
# ──────────────────────────────────────────────────────────────────────────────

try:
    from crewai_tools.security.safe_requests import (
        create_safe_session,
        safe_get,
        SSRFProtectedAdapter,
    )
    from crewai_tools.security.safe_path import validate_url
    _CREWAI_SECURITY_AVAILABLE = True
except ImportError:
    _CREWAI_SECURITY_AVAILABLE = False


class SSRFSafeToolRegistry(ToolRegistry):
    """ToolRegistry that injects an SSRF-hardened requests.Session into each tool.

    When the crewAI security module is available, every tool that exposes a
    ``session`` or ``requests_session`` attribute gets a
    :class:`~crewai_tools.security.safe_requests.SSRFProtectedAdapter`-backed
    session injected at load time.

    If crewAI's security module is not installed the registry falls back to the
    base :class:`ToolRegistry` behaviour silently — no crash, just no hardening.

    Usage::

        registry = SSRFSafeToolRegistry()
        registry.discover_tools()
        registry.load_tool("google_search")
        result = registry.execute_tool("google_search", {"query": "OpenManus RL"})
    """

    def __init__(self) -> None:
        super().__init__()
        if _CREWAI_SECURITY_AVAILABLE:
            self._safe_session = create_safe_session()
        else:
            import requests
            self._safe_session = requests.Session()
            print(
                "[SSRFSafeToolRegistry] WARNING: crewai_tools not installed. "
                "HTTP requests from tools will NOT be SSRF-protected."
            )

    # ── Override load_tool to inject the safe session ─────────────────────

    def load_tool(self, tool_name: str, model_string: Optional[str] = None):
        tool_instance = super().load_tool(tool_name, model_string)
        if tool_instance is not None:
            self._inject_safe_session(tool_instance)
        return tool_instance

    def register_tool(self, name: str, tool) -> None:
        super().register_tool(name, tool)
        self._inject_safe_session(tool)

    # ── Internal helpers ───────────────────────────────────────────────────

    def _inject_safe_session(self, tool) -> None:
        """Replace HTTP session attributes on the tool with a safe session."""
        for attr in ("session", "requests_session", "_session", "http_session"):
            if hasattr(tool, attr):
                setattr(tool, attr, self._safe_session)
                return

        # Monkey-patch tools that call requests.get / requests.post directly
        # by replacing the ``requests`` module reference if the tool holds one.
        import types
        for attr in dir(tool):
            try:
                obj = getattr(tool, attr)
            except Exception:
                continue
            if isinstance(obj, types.ModuleType) and obj.__name__ == "requests":
                # Build a minimal proxy that routes .get through safe_get
                proxy = _RequestsProxy(self._safe_session)
                setattr(tool, attr, proxy)
                break

    def validate_url_before_execute(self, url: str) -> None:
        """Explicitly validate a URL before executing a tool.

        Raises:
            ValueError: if the URL targets a private/reserved address.
        """
        if _CREWAI_SECURITY_AVAILABLE:
            validate_url(url)


class _RequestsProxy:
    """Minimal proxy replacing `import requests` in a tool instance.

    Routes .get and .post through the SSRF-protected session.
    """

    def __init__(self, session) -> None:
        self._session = session

    def get(self, url: str, **kwargs):
        return self._session.get(url, **kwargs)

    def post(self, url: str, **kwargs):
        return self._session.post(url, **kwargs)

    def __getattr__(self, name: str):
        return getattr(self._session, name)
