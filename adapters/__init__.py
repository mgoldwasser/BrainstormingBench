"""Adapters wrap a brainstorming system behind a uniform interface.

The benchmark treats each system as a black box: problem text in, a list of
ideas out. See `adapters/base.py` for the contract every adapter must meet.
"""

from adapters.base import Adapter, Idea, Response, parse_ideas

__all__ = ["Adapter", "Idea", "Response", "parse_ideas"]
