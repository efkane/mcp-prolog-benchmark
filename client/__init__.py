"""
Module client MCP pour la résolution de puzzles logiques via Prolog.
"""

from .mcp_client import MCPPrologClient, GroqProvider, OllamaProvider, SolveResult

__all__ = ['MCPPrologClient', 'GroqProvider', 'OllamaProvider', 'SolveResult']
