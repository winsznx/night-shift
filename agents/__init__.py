"""The Night Shift operational agent fleet.

Six specialists, each owning a distinct reasoning domain and a distinct authority
boundary. None of them writes the datastore; all of them go through the tool broker.
"""

from agents.fleet import AGENT_DESCRIPTIONS, build_agent, build_fleet
from agents.prompts import build_prompt
from agents.toolsets import build_toolset

__all__ = [
    "AGENT_DESCRIPTIONS",
    "build_agent",
    "build_fleet",
    "build_prompt",
    "build_toolset",
]
