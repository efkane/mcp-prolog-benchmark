"""
Serveur MCP pour la Résolution de Puzzles Logiques via Prolog
=============================================================

Implémente le protocole MCP (Model Context Protocol) selon la spécification
officielle: https://modelcontextprotocol.io/docs/develop/build-server

Ce serveur expose des outils (tools) permettant à un client MCP de :
  1. Exécuter du code Prolog CLP(FD) via SWI-Prolog
  2. Valider la syntaxe Prolog avant exécution
  3. Corriger automatiquement les erreurs Prolog courantes
  4. Parser la sortie Prolog en solution structurée

Architecture MCP:
  ┌──────────────────┐    stdio (JSON-RPC 2.0)    ┌────────────────────┐
  │   Client MCP     │ ◄─────────────────────────► │   Serveur MCP      │
  │   (mcp_client.py)│   initialize / tools/list   │   (ce fichier)     │
  │                  │   tools/call                │                    │
  └──────────────────┘                              └────────┬───────────┘
                                                             │
                                                    ┌────────▼───────────┐
                                                    │   SWI-Prolog       │
                                                    │   (swipl)          │
                                                    │   CLP(FD) solver   │
                                                    └────────────────────┘

Transport : stdio (entrée/sortie standard) — conforme à la spec MCP
Protocole : JSON-RPC 2.0

Référence : https://modelcontextprotocol.io/docs/concepts/transports
Projet    : Projet Tutoré M1 MIAGE — Résolution de Problèmes Logiques
Objectif  : Battre Logic.py (91.9%) sur ZebraLogicBench
"""

import asyncio
import subprocess
import tempfile
import os
import re
import json
import sys
from typing import Any
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

SWIPL_PATH = os.environ.get("SWIPL_PATH", "swipl")
PROLOG_TIMEOUT = int(os.environ.get("PROLOG_TIMEOUT", "30"))


# ═══════════════════════════════════════════════════════════════════════════════
# APPRENTISSAGE PAR RENFORCEMENT — Tracker central au serveur
# ═══════════════════════════════════════════════════════════════════════════════

class ServerLearning:
    """
    Apprentissage par renforcement au serveur MCP.
    
    Enregistre:
    - Succès/échecs des exécutions Prolog
    - Clés d'apprentissage (patterns qui marchent)
    - Temps d'exécution moyen
    
    Sert à améliorer les futures résolutions (via Claude Desktop ou client Python).
    """
    
    LEARNING_FILE = Path(__file__).parent / "server_learning.json"
    
    def __init__(self):
        self.stats: dict = {}
        self.patterns: dict = {}
        self.load()
    
    def load(self):
        """Charge les stats d'apprentissage du serveur."""
        if self.LEARNING_FILE.exists():
            with open(self.LEARNING_FILE, 'r') as f:
                data = json.load(f)
                self.stats = data.get("stats", {})
                self.patterns = data.get("patterns", {})
    
    def save(self):
        """Sauve les stats et patterns d'apprentissage."""
        with open(self.LEARNING_FILE, 'w') as f:
            json.dump({
                "stats": self.stats,
                "patterns": self.patterns,
                "last_update": str(Path(__file__).stat().st_mtime)
            }, f, indent=2)
    
    def record_execution(self, puzzle_id: str, success: bool, execution_time: float):
        """Enregistre une tentative d'exécution Prolog."""
        if puzzle_id not in self.stats:
            self.stats[puzzle_id] = {"total": 0, "success": 0, "failure": 0, "avg_time": 0.0}
        
        s = self.stats[puzzle_id]
        s["total"] += 1
        if success:
            s["success"] += 1
        else:
            s["failure"] += 1
        
        n = s["total"]
        s["avg_time"] = (s.get("avg_time", 0) * (n - 1) + execution_time) / n
        self.save()
    
    def record_pattern(self, pattern_name: str, success: bool):
        """Enregistre une tentative de pattern (ex: 'clpfd_basic', 'labeling_dfs')."""
        if pattern_name not in self.patterns:
            self.patterns[pattern_name] = {"total": 0, "success": 0, "failure": 0}
        
        p = self.patterns[pattern_name]
        p["total"] += 1
        if success:
            p["success"] += 1
        else:
            p["failure"] += 1
        
        self.save()
    
    def get_success_rate(self, puzzle_id: str = None) -> float:
        """Retourne le taux de succès global ou pour un puzzle."""
        if puzzle_id:
            if puzzle_id not in self.stats:
                return 0.0
            s = self.stats[puzzle_id]
            return (s["success"] / s["total"] * 100) if s["total"] > 0 else 0.0
        else:
            # Global success rate
            total = sum(s["total"] for s in self.stats.values())
            if total == 0:
                return 0.0
            success = sum(s["success"] for s in self.stats.values())
            return (success / total * 100)


# ═══════════════════════════════════════════════════════════════════════════════
# FONCTIONS PROLOG — Le cœur du serveur
# ═══════════════════════════════════════════════════════════════════════════════

async def execute_prolog_code(code: str, goal: str = "solve") -> dict[str, Any]:
    """Exécute du code Prolog via SWI-Prolog en subprocess async."""
    with tempfile.NamedTemporaryFile(
        mode='w', suffix='.pl', delete=False, encoding='utf-8'
    ) as f:
        f.write(code)
        temp_file = f.name

    try:
        process = await asyncio.create_subprocess_exec(
            SWIPL_PATH, '-s', temp_file, '-g', goal, '-t', 'halt',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=PROLOG_TIMEOUT
            )
        except asyncio.TimeoutError:
            process.kill()
            return {"success": False, "output": "", "error": f"Timeout ({PROLOG_TIMEOUT}s)", "code": -1}

        return {
            "success": process.returncode == 0,
            "output": stdout.decode('utf-8', errors='replace').strip(),
            "error": stderr.decode('utf-8', errors='replace').strip(),
            "code": process.returncode
        }
    finally:
        try:
            os.unlink(temp_file)
        except OSError:
            pass


def validate_prolog_syntax(code: str) -> dict[str, Any]:
    """Vérifie la syntaxe du code Prolog. Détecte les erreurs courantes."""
    errors = []
    warnings = []

    # Parenthèses/crochets équilibrées
    stack = []
    matching = {'(': ')', '[': ']', '{': '}'}
    for i, ch in enumerate(code):
        if ch in '([{':
            stack.append((ch, i))
        elif ch in ')]}':
            if not stack:
                errors.append(f"Fermant '{ch}' sans ouverture (pos {i})")
            else:
                opening, _ = stack.pop()
                if ch != matching[opening]:
                    errors.append(f"'{ch}' ne correspond pas à '{opening}'")
    for ch, pos in stack:
        errors.append(f"'{ch}' (pos {pos}) jamais fermé")

    # Module CLP(FD)
    if '#=' in code and 'clpfd' not in code.lower():
        warnings.append("Utilise CLP(FD) sans charger le module. Ajouter: :- use_module(library(clpfd)).")

    # Prédicat solve
    if 'solve :-' not in code and 'solve:-' not in code:
        warnings.append("Prédicat 'solve' non défini")

    # Opérateurs invalides
    for op in ['#<>', '#!=', '#/=', '==']:
        if op in code:
            errors.append(f"Opérateur invalide '{op}'. Utilisez #= ou #\\=")

    # labeling
    if 'labeling' not in code:
        warnings.append("Pas d'appel à labeling/2 — le solveur ne cherchera pas de solution")

    return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}


def auto_fix_prolog(code: str) -> dict[str, Any]:
    """Corrige automatiquement les erreurs Prolog courantes du LLM."""
    original = code
    fixes = []

    # Ajouter use_module si manquant
    if ':- use_module(library(clpfd))' not in code and '#=' in code:
        code = ':- use_module(library(clpfd)).\n' + code
        fixes.append("Ajout de :- use_module(library(clpfd)).")

    # Remplacer == par #=
    if '==' in code:
        code = re.sub(r'(?<![#])={2}', '#=', code)
        fixes.append("Remplacement de == par #=")

    # Remplacer \= par #\= (si pas déjà #\=)
    if re.search(r'(?<!#)\\=', code):
        code = re.sub(r'(?<!#)\\=', r'#\\=', code)
        fixes.append("Remplacement de \\= par #\\=")

    # Assurer que le code finit par un point
    stripped = code.rstrip()
    if stripped and not stripped.endswith('.'):
        lines = code.split('\n')
        for i in range(len(lines) - 1, -1, -1):
            line = lines[i].strip()
            if line:
                if line.endswith(','):
                    lines[i] = lines[i].rstrip()[:-1] + '.'
                else:
                    lines[i] = lines[i].rstrip() + '.'
                fixes.append("Ajout du point final")
                break
        code = '\n'.join(lines)

    return {"code": code, "was_modified": code != original, "fixes": fixes}


def parse_prolog_output(output: str, variables: list[str], n_positions: int) -> dict[str, Any]:
    """Parse la sortie Prolog [1,2,3,...] en solution structurée."""
    match = re.search(r'\[([\d,\s]+)\]', output)
    if not match:
        return {"success": False, "error": f"Format invalide: {output}", "raw_output": output}

    try:
        numbers = [int(x.strip()) for x in match.group(1).split(',')]
    except ValueError as e:
        return {"success": False, "error": f"Parsing: {e}", "raw_output": output}

    if len(numbers) != len(variables):
        return {
            "success": False,
            "error": f"{len(numbers)} valeurs pour {len(variables)} variables",
            "raw_output": output
        }

    assignments = dict(zip(variables, numbers))
    by_position = {}
    for var, pos in assignments.items():
        by_position.setdefault(pos, []).append(var)

    return {
        "success": True,
        "assignments": assignments,
        "by_position": {str(k): v for k, v in sorted(by_position.items())},
        "raw_output": output
    }


# ═══════════════════════════════════════════════════════════════════════════════
# SERVEUR MCP — Définition des outils exposés au client
# ═══════════════════════════════════════════════════════════════════════════════

server = Server("prolog-logic-solver")
learning = ServerLearning()  # Instance global du tracker d'apprentissage


@server.list_tools()
async def list_tools() -> list[Tool]:
    """Expose les 4 outils du serveur au client MCP."""
    return [
        Tool(
            name="execute_prolog",
            description=(
                "Exécute du code Prolog CLP(FD) via SWI-Prolog. "
                "Le code doit définir un prédicat solve/0 qui utilise "
                "labeling/2 pour résoudre les contraintes et write/1 pour afficher le résultat. "
                "Opérateurs supportés: #=, #\\=, #<, #>, ins, all_different, abs/1."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Code Prolog CLP(FD) complet"},
                    "goal": {"type": "string", "description": "Prédicat à appeler", "default": "solve"}
                },
                "required": ["code"]
            }
        ),
        Tool(
            name="validate_prolog",
            description=(
                "Valide la syntaxe du code Prolog avant exécution. "
                "Détecte: parenthèses déséquilibrées, opérateurs invalides, "
                "module clpfd manquant, absence de solve/0 ou labeling."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Code Prolog à valider"}
                },
                "required": ["code"]
            }
        ),
        Tool(
            name="auto_fix_prolog",
            description=(
                "Corrige automatiquement les erreurs Prolog courantes générées par les LLMs: "
                "== → #=, \\= → #\\=, ajout du module clpfd, ajout du point final."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Code Prolog à corriger"}
                },
                "required": ["code"]
            }
        ),
        Tool(
            name="parse_prolog_output",
            description=(
                "Parse la sortie brute de Prolog [1,2,3,...] en solution structurée. "
                "Associe chaque position à ses variables correspondantes."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "output": {"type": "string", "description": "Sortie brute de Prolog"},
                    "variables": {
                        "type": "array", "items": {"type": "string"},
                        "description": "Noms des variables dans l'ordre de Vars = [...]"
                    },
                    "n_positions": {"type": "integer", "description": "Nombre de positions (N dans ins 1..N)"}
                },
                "required": ["output", "variables", "n_positions"]
            }
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Route les appels d'outils du client vers les fonctions correspondantes.
    
    Enregistre aussi les résultats dans le système d'apprentissage pour 
    améliorer les futures résolutions (via Claude Desktop ou client Python).
    """
    import time
    
    start_time = time.time()

    if name == "execute_prolog":
        code = arguments.get("code", "")
        goal = arguments.get("goal", "solve")
        result = await execute_prolog_code(code, goal)
        
        # Enregistrement apprentissage
        execution_time = time.time() - start_time
        puzzle_id = f"puzzle_{hash(code) % 10000}"  # ID basé sur le code
        success = result.get("success", False)
        learning.record_execution(puzzle_id, success, execution_time)
        
        # Détecte les patterns utilisés
        if "use_module(library(clpfd))" in code:
            learning.record_pattern("clpfd_basic", success)
        if "labeling(" in code:
            learning.record_pattern("labeling_used", success)
        if "all_different" in code:
            learning.record_pattern("all_different", success)
        if "#=" in code:
            learning.record_pattern("constraint_arithmetic", success)
        
    elif name == "validate_prolog":
        result = validate_prolog_syntax(arguments.get("code", ""))
    elif name == "auto_fix_prolog":
        code = arguments.get("code", "")
        result = auto_fix_prolog(code)
        # Enregistrement apprentissage des fixes
        if result.get("fixes"):
            learning.record_pattern("auto_fix_applied", True)
    elif name == "parse_prolog_output":
        result = parse_prolog_output(
            arguments.get("output", ""),
            arguments.get("variables", []),
            arguments.get("n_positions", 3)
        )
    else:
        result = {"error": f"Outil inconnu: {name}"}

    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]


# ═══════════════════════════════════════════════════════════════════════════════
# POINT D'ENTRÉE
# ═══════════════════════════════════════════════════════════════════════════════

async def main():
    """Démarre le serveur MCP sur stdio (conforme à la spec MCP)."""
    print("[MCP Server] ═══════════════════════════════════════════════════════════", file=sys.stderr)
    print("[MCP Server] Démarrage du serveur prolog-logic-solver...", file=sys.stderr)
    print(f"[MCP Server] SWI-Prolog: {SWIPL_PATH}", file=sys.stderr)
    print(f"[MCP Server] Timeout: {PROLOG_TIMEOUT}s", file=sys.stderr)
    
    # Affiche les stats d'apprentissage
    global_success = learning.get_success_rate()
    print(f"[MCP Server] Apprentissage: {global_success:.1f}% réussite globale", file=sys.stderr)
    print(f"[MCP Server] Puzzles suivis: {len(learning.stats)}", file=sys.stderr)
    print(f"[MCP Server] Patterns appris: {len(learning.patterns)}", file=sys.stderr)
    print("[MCP Server] ═══════════════════════════════════════════════════════════", file=sys.stderr)
    print("[MCP Server] 🚀 Serveur prêt pour Claude Desktop !", file=sys.stderr)

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, write_stream,
            server.create_initialization_options()
        )

if __name__ == "__main__":
    asyncio.run(main())
