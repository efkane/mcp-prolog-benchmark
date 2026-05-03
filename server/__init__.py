"""
Module serveur MCP pour la résolution de puzzles logiques via Prolog.
"""

from .mcp_server import server, execute_prolog_code, validate_prolog_syntax

__all__ = ['server', 'execute_prolog_code', 'validate_prolog_syntax']
