"""
Client MCP pour la Résolution de Puzzles Logiques via Prolog
============================================================

Système INTELLIGENT et AUTONOME avec:
  ✅ Sélection AUTOMATIQUE du meilleur modèle
  ✅ Apprentissage par renforcement (mémorise succès/échecs)
  ✅ Auto-retry avec modèles différents si erreur
  ✅ Pas de configuration manuelle nécessaire

Flux:
  1. Charge les stats d'apprentissage (quels modèles réussissent)
  2. Choisit le meilleur modèle AUTONOMIQUEMENT
  3. Si échec → essaie modèle alternatif
  4. Enregistre le résultat pour améliorations futures

Transport : stdio (conforme spec MCP)
Référence : https://modelcontextprotocol.io/docs/concepts/transports

Projet : Projet Tutoré M1 MIAGE — Résolution de Problèmes Logiques
"""

import asyncio
import json
import sys
import os
import re
import time
from typing import Any, Optional, List, Dict
from dataclasses import dataclass, field
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


# ═══════════════════════════════════════════════════════════════════════════════
# SYSTÈME D'APPRENTISSAGE PAR RENFORCEMENT — Intelligence du système
# ═══════════════════════════════════════════════════════════════════════════════

class ModelLearning:
    """Apprentissage par renforcement: track succès/échecs par modèle."""
    
    # ⚠️ NOUVEAU : Modèles à exclure définitivement
    BLACKLISTED_MODELS = [
        "ollama:llama3.2-3b",
        "ollama:llama3.2-1b",
        "ollama:llama2"
    ]
    
    LEARNING_FILE = Path(__file__).parent / "model_learning.json"
    
    def __init__(self):
        self.stats: Dict[str, Dict] = {}
        self.load()
    
    def load(self):
        """Charge les stats d'apprentissage précédentes."""
        if self.LEARNING_FILE.exists():
            with open(self.LEARNING_FILE, 'r') as f:
                self.stats = json.load(f)
        else:
            self.stats = {}
    
    def save(self):
        """Sauve les stats d'apprentissage."""
        with open(self.LEARNING_FILE, 'w') as f:
            json.dump(self.stats, f, indent=2)
    
    def record_result(self, model_name: str, success: bool, puzzle_id: str = "", time_ms: float = 0):
        """Enregistre le résultat d'une tentative."""
        if model_name not in self.stats:
            self.stats[model_name] = {"total": 0, "success": 0, "failures": 0, "avg_time_ms": 0}
        
        stats = self.stats[model_name]
        stats["total"] += 1
        if success:
            stats["success"] += 1
        else:
            stats["failures"] += 1
        stats["avg_time_ms"] = (stats.get("avg_time_ms", 0) * (stats["total"] - 1) + time_ms) / stats["total"]
        self.save()
    
    def get_success_rate(self, model_name: str) -> float:
        """Retourne le taux de succès d'un modèle."""
        if model_name not in self.stats:
            return 50.0  # Avant tout test: confiance 50/50
        stats = self.stats[model_name]
        if stats["total"] == 0:
            return 50.0
        return 100 * stats["success"] / stats["total"]
    
    def rank_models(self, available_models: List[str]) -> List[str]:
        """Range les modèles par taux de succès (meilleur en premier), EXCLUT la liste noire."""
        import logging  # S'assurer que logging est dispo si utilisé ici, sinon on utilise print ou un logger global
        # ⚠️ NOUVEAU : Filtrer les modèles blacklistés
        filtered_models = [m for m in available_models if m not in self.BLACKLISTED_MODELS]
        
        # ⚠️ NOUVEAU : Log d'avertissement
        blacklisted_used = [m for m in available_models if m in self.BLACKLISTED_MODELS]
        if blacklisted_used:
            try:
                import logging
                logging.warning(f"Modèles ignorés (blacklistés) : {blacklisted_used}")
            except Exception:
                print(f"WARNING: Modèles ignorés (blacklistés) : {blacklisted_used}")
        
        ranked = sorted(filtered_models, key=lambda m: -self.get_success_rate(m))
        return ranked if ranked else available_models  # Fallback si tous blacklistés


# ═══════════════════════════════════════════════════════════════════════════════
# MODÈLES DISPONIBLES — Configuration centralisée des providers
# ═══════════════════════════════════════════════════════════════════════════════

AVAILABLE_MODELS = [
    # Groq (cloud) — Très rapide et fiable
    {"name": "groq:llama-3.3-70b", "type": "groq", "model": "llama-3.3-70b-versatile", "priority": 1},
    
    # Qwen 2.5 Coder (7B) — Excellent pour le code et la logique (fallback local)
    {"name": "ollama:qwen2.5-coder", "type": "ollama", "model": "qwen2.5-coder:7b", "priority": 2},
    
    # Llama 3.2 (3B et 1B) — Rapides et efficaces (fallback local)
    {"name": "ollama:llama3.2-3b", "type": "ollama", "model": "llama3.2:3b", "priority": 3},
    {"name": "ollama:llama3.2-1b", "type": "ollama", "model": "llama3.2:1b", "priority": 3},
]




SYSTEM_PROMPT = (
    "You are an expert puzzle solving agent with access to a Prolog logic solver "
    "tool that uses CLP(FD). You generate CORRECT, EXECUTABLE Prolog code. "
    "Your solver tool supports only these 4 operators: #=, #<, #>, #\\= "
    "and only the function abs/1."
)

DATA_STRUCTURE_PROMPT = """Given the following puzzle description, define the data structure for a valid puzzle solution.

### Your task:
1. Create predicate solve/0
2. Extract all entities from the puzzle (names, pets, colors, objects, etc.)
3. Create a single flat list named `Vars` that contains ALL variables.
   **All variable names must begin with an uppercase letter.**
   **For multi-word names, use underscores: e.g. `Samsung_Galaxy_S21`, `Very_Short`, `Pall_Mall`**
4. Add the domain constraint: `Vars ins 1..N` where N is the number of houses/positions.
5. Group them by logical category (Names, Pets, Colors, etc.)
6. For each group, add `all_different(GroupName),`
7. End the last line with a COMMA ',' (not a period)
8. Do NOT translate clues yet — only the data structure.
9. Put your prolog code between ``` ```

Example for a 4-house puzzle:
```prolog
solve :-
    Vars = [Alice, Eric, Arnold, Peter,
        Google_Pixel_6, Iphone_13, Oneplus_9, Samsung_Galaxy_S21],
    Vars ins 1..4,
    Names = [Alice, Eric, Arnold, Peter],
    PhoneModels = [Google_Pixel_6, Iphone_13, Oneplus_9, Samsung_Galaxy_S21],
    all_different(Names),
    all_different(PhoneModels),
    %% CONSTRAINTS START HERE
```

PUZZLE:
{puzzle}

Generate ONLY the data structure. MUST end with a COMMA ',':"""

CONSTRAINTS_PROMPT = """You have already defined the data structure. Now write the logical constraints and the output display.

### Constraints Section:
- Translate EACH clue into a Prolog constraint.
- Add a comment for each: `%% Clue X: <original clue>`
- Use the SAME variable names defined in `Vars`.
- Your solver supports ONLY: #=, #<, #>, #\\= and abs/1.
- Examples:
    %% Clue 1: The person whose child is Fred is somewhere to the left of Eric.
    Fred #< Eric,
    %% Clue 2: There are two houses between Penny and the short person.
    abs(Penny - Short) #= 2,
    %% Clue 3: The person whose favorite color is red is in the second house.
    Red #= 2,
    %% Clue 4: The rabbit owner is directly left of Aniya.
    Rabbit #= Aniya - 1,

- End with:
    labeling([], Vars),
    write(Vars), nl.
  The last line MUST end with a PERIOD '.'

CURRENT CODE (structure only):
```prolog
{data_structure}
```

PUZZLE CLUES:
{clues}

Complete with constraints:"""

ERROR_FIX_PROMPT = """The Prolog code produced an error. Fix it.

CODE:
```prolog
{code}
```

ERROR:
{error}

Fix the code. Common mistakes:
1. Use #= instead of == or =:=
2. Use #\\= instead of \\= or =\\=
3. Every line ends with comma EXCEPT the last (period)
4. Variables must start with uppercase
5. Multi-word names use underscores: Very_Short, not VeryShort
6. labeling([], Vars) must come before write
7. Only use #=, #<, #>, #\\= and abs/1

Return ONLY the corrected complete Prolog code:"""


# ═══════════════════════════════════════════════════════════════════════════════
# LLM PROVIDERS — Groq (cloud) et Ollama (local)
# ═══════════════════════════════════════════════════════════════════════════════

class LLMProvider:
    """Interface pour les providers LLM."""

    async def complete(self, system: str, user: str, temperature: float = 0.1) -> str:
        raise NotImplementedError


class GroqProvider(LLMProvider):
    """Provider Groq (cloud) — rapide, gratuit pour les petits volumes."""

    # Gestion de multiples clés API pour éviter les Rate Limits (429) et interruptions
    # Les clés sont chargées depuis les variables d'environnement (jamais en dur dans le code)
    # Définissez GROQ_API_KEY_1, GROQ_API_KEY_2, ... dans un fichier .env (voir .env.example)
    API_KEYS = [
        key for key in [
            os.environ.get("GROQ_API_KEY_1"),
            os.environ.get("GROQ_API_KEY_2"),
            os.environ.get("GROQ_API_KEY_3"),
            os.environ.get("GROQ_API_KEY_4"),
            os.environ.get("GROQ_API_KEY_5"),
            os.environ.get("GROQ_API_KEY_6"),
            os.environ.get("GROQ_API_KEY"),  # Clé unique alternative
        ] if key  # Filtre les None (variables non définies)
    ]
    _key_index = 0
    _last_request_time: Optional[float] = None
    _request_throttle_s = 2.0  # Throttle réduit grâce à la rotation de 3 clés
    _first_request_done = False
    # Semaphore global pour limiter les requêtes concurrentes vers Groq
    _global_concurrency_semaphore: Optional[asyncio.Semaphore] = None

    def __init__(self, api_key: str = None, model: str = "llama-3.3-70b-versatile"):
        self.api_keys = GroqProvider.API_KEYS if api_key is None or api_key.lower() == "auto" else [api_key]
        if api_key and api_key not in self.api_keys and api_key.lower() != "auto":
            # Si une clé explicite est fournie et n'est pas dans la liste
            self.api_keys = [api_key] + GroqProvider.API_KEYS
        self.model = model
        self.base_url = "https://api.groq.com/openai/v1/chat/completions"

    def _get_current_key(self):
        return self.api_keys[GroqProvider._key_index]
        
    def _rotate_key(self):
        GroqProvider._key_index = (GroqProvider._key_index + 1) % len(self.api_keys)
        import logging
        logging.info(f"Rotation de clé Groq effectuée (index: {GroqProvider._key_index})")

    async def complete(self, system: str, user: str, temperature: float = 0.1) -> str:
        import httpx
        import time
        import logging

        # Petit délai initial
        if not GroqProvider._first_request_done:
            await asyncio.sleep(0.5)
            GroqProvider._first_request_done = True

        # Respecter le rate limit global entre requêtes
        if GroqProvider._last_request_time is not None:
            elapsed = time.time() - GroqProvider._last_request_time
            if elapsed < GroqProvider._request_throttle_s:
                await asyncio.sleep(GroqProvider._request_throttle_s - elapsed)

        max_retries = 10
        backoff_seconds = 2

        # Init global semaphore lazily
        if GroqProvider._global_concurrency_semaphore is None:
            GroqProvider._global_concurrency_semaphore = asyncio.Semaphore(2)

        for attempt in range(max_retries):
            current_key = self._get_current_key()
            GroqProvider._last_request_time = time.time()
            self._rotate_key()

            sem = GroqProvider._global_concurrency_semaphore
            await sem.acquire()
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    resp = await client.post(
                        self.base_url,
                        headers={"Authorization": f"Bearer {current_key}", "Content-Type": "application/json"},
                        json={
                            "model": self.model,
                            "messages": [
                                {"role": "system", "content": system},
                                {"role": "user", "content": user}
                            ],
                            "temperature": temperature,
                            "max_tokens": 1500
                        }
                    )

                    if resp.status_code == 429:
                        logging.warning(f"[GROQ] Rate limit (429) avec la clé ...{current_key[-4:]}.")
                        if attempt >= len(self.api_keys):
                            logging.warning("[GROQ] Toutes les clés sont saturées (TPM/RPM). Mise en pause de 20 secondes...")
                            await asyncio.sleep(20)
                        else:
                            await asyncio.sleep(2)
                        continue

                    if resp.status_code in (401, 403):
                        logging.warning(f"[GROQ] Erreur Auth {resp.status_code} avec la clé ...{current_key[-4:]}. Passage à l'autre clé.")
                        await asyncio.sleep(1)
                        continue

                    resp.raise_for_status()
                    return resp.json()["choices"][0]["message"]["content"]

            except httpx.HTTPStatusError as e:
                if attempt < max_retries - 1:
                    logging.warning(f"[GROQ] Erreur HTTP {e}. Retry avec une autre clé...")
                    await asyncio.sleep(backoff_seconds)
                    continue
                else:
                    raise e
            except Exception as e:
                if attempt < max_retries - 1:
                    logging.warning(f"[GROQ] Erreur réseau {e}. Retry...")
                    await asyncio.sleep(backoff_seconds)
                    continue
                else:
                    raise e
            finally:
                try:
                    sem.release()
                except Exception:
                    pass

        raise Exception("Echec de la complétion via Groq API après rotation complète des clés.")

class OllamaProvider(LLMProvider):
    """Provider Ollama (local) — pour Llama 3.3 en local."""

    def __init__(self, model: str = "qwen2.5-coder:7b", base_url: str = "http://localhost:11434"):
        self.model = model
        self.base_url = base_url

    async def complete(self, system: str, user: str, temperature: float = 0.0) -> str:
        import httpx
        # Force strict zero temperature for scientific reproducibility
        strict_temp = 0.0
        async with httpx.AsyncClient(timeout=1800.0) as client:
            resp = await client.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user}
                    ],
                    "stream": False,
                    "options": {
                        "temperature": strict_temp,
                        "num_predict": 4096,
                        "num_ctx": 8192,
                        "seed": 42
                    }
                }
            )
            resp.raise_for_status()
            return resp.json()["message"]["content"]


class AnthropicProvider(LLMProvider):
    """Provider Anthropic (cloud) — Claude 3.5 Sonnet avec API key."""

    def __init__(self, api_key: str, model: str = "claude-3-5-sonnet-20241022"):
        self.api_key = api_key
        self.model = model
        self.base_url = "https://api.anthropic.com/v1/messages"

    async def complete(self, system: str, user: str, temperature: float = 0.1) -> str:
        import httpx
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                self.base_url,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                },
                json={
                    "model": self.model,
                    "max_tokens": 2048,
                    "temperature": temperature,
                    "system": system,
                    "messages": [
                        {"role": "user", "content": user}
                    ]
                }
            )
            if resp.status_code != 200:
                error_info = resp.text
                raise Exception(f"Anthropic API error {resp.status_code}: {error_info}")
            return resp.json()["content"][0]["text"]


class GoogleProvider(LLMProvider):
    """Provider Google (cloud) — Gemini 2.0 Flash avec API key."""

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash"):
        self.api_key = api_key
        self.model = model
        self.base_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    async def complete(self, system: str, user: str, temperature: float = 0.1) -> str:
        import httpx
        
        # Gemini v1beta : fusionner système et utilisateur dans les messages
        combined_prompt = f"{system}\n\n{user}"
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                self.base_url,
                params={"key": self.api_key},
                json={
                    "contents": [
                        {
                            "role": "user",
                            "parts": [{"text": combined_prompt}]
                        }
                    ],
                    "generationConfig": {
                        "temperature": temperature,
                        "maxOutputTokens": 2048,
                        "topP": 1.0,
                        "topK": 32
                    },
                    "safetySettings": []
                }
            )
            if resp.status_code != 200:
                error_info = resp.text
                raise Exception(f"Google API error {resp.status_code}: {error_info}")
            data = resp.json()
            if "candidates" in data and len(data["candidates"]) > 0:
                candidate = data["candidates"][0]
                if "content" in candidate and "parts" in candidate["content"]:
                    return candidate["content"]["parts"][0]["text"]
            raise Exception(f"Unexpected Google API response: {data}")


# ═══════════════════════════════════════════════════════════════════════════════
# DATA CLASSES — Résultats structurés
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class SolveResult:
    """Résultat complet de la résolution d'un puzzle.
    
    Enrichi avec les critères d'évaluation du tuteur:
    - Syntaxe Prolog correcte
    - Résultat correct
    - Nombre de tentatives
    - Langage utilisé
    - Capacité à réessayer/s'améliorer
    """
    success: bool
    puzzle_id: str = ""
    raw_output: str = ""
    parsed_solution: dict = field(default_factory=dict)
    prolog_code: str = ""
    variables: list = field(default_factory=list)
    n_positions: int = 0
    attempts: int = 0
    fixes_applied: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    time_ms: float = 0.0
    model_used: str = ""
    models_tried: list = field(default_factory=list)
    
    # ── Critères d'évaluation stricte (tuteur) ──
    syntax_valid: bool = False  # Le Prolog généré est-il syntaxiquement correct?
    result_correct: bool = False  # La solution satisfait-elle les contraintes?
    language_used: str = "prolog"  # Prolog / Python / autre
    retried: bool = False  # A-t-il réessayé après une erreur?
    self_improved: bool = False  # A-t-il changé de stratégie entre tentatives?
    error_types: list = field(default_factory=list)  # Types d'erreurs: syntax, constraint, timeout...

    def to_dict(self) -> dict:
        return {
            "success": self.success, "puzzle_id": self.puzzle_id,
            "raw_output": self.raw_output, "parsed_solution": self.parsed_solution,
            "prolog_code": self.prolog_code, "variables": self.variables,
            "n_positions": self.n_positions, "attempts": self.attempts,
            "fixes_applied": self.fixes_applied, "errors": self.errors,
            "time_ms": self.time_ms, "model_used": self.model_used,
            "models_tried": self.models_tried,
            # Critères d'évaluation
            "syntax_valid": self.syntax_valid,
            "result_correct": self.result_correct,
            "language_used": self.language_used,
            "retried": self.retried,
            "self_improved": self.self_improved,
            "error_types": self.error_types
        }


# ═══════════════════════════════════════════════════════════════════════════════
# CLIENT MCP — Le cœur du système
# ═══════════════════════════════════════════════════════════════════════════════

class MCPPrologClient:
    """
    Client MCP qui orchestre la résolution de puzzles logiques.

    Combine :
    - Un LLM (Groq ou Ollama) pour générer du code Prolog
    - Le serveur MCP pour exécuter, valider et corriger le Prolog
    - Un système de retry avec feedback d'erreur
    - NOUVEAU: Système intelligent de sélection multi-modèles
    """

    def __init__(self, llm: Optional[LLMProvider] = None, server_script: Optional[str] = None,
                 max_retries: int = 3):
        self.llm = llm
        self.max_retries = max_retries
        self.learning = ModelLearning()  # Apprentissage par renforcement
        if server_script is None:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            server_script = os.path.join(current_dir, '..', 'server', 'mcp_server.py')
        self.server_script = os.path.abspath(server_script)
        self.session: Optional[ClientSession] = None
        self._stdio_ctx = None
        self._session_ctx = None

    def _create_llm_provider(self, model_config: Dict) -> LLMProvider:
        """Crée un provider LLM basé sur la configuration."""
        if model_config["type"] == "groq":
            # On passe 'auto' pour activer la rotation automatique des 3 clés Groq
            api_key = os.environ.get("GROQ_API_KEY", "auto")
            return GroqProvider(api_key, model_config["model"])
        else:  # ollama
            return OllamaProvider(model_config["model"])

    def _get_available_models(self) -> List[Dict]:
        """Retourne la liste des modèles disponibles et testables."""
        available = []
        for model_cfg in AVAILABLE_MODELS:
            if model_cfg["type"] == "groq":
                # Toujours disponible grâce à nos 3 clés intégrées (rotation)
                available.append(model_cfg)
            else:  # ollama - toujours disponible (local)
                available.append(model_cfg)
        return available

    async def solve_with_model_selection(self, puzzle: str, puzzle_id: str = "") -> SolveResult:
        """
        Résout un puzzle en sélectionnant AUTOMATIQUEMENT le meilleur modèle.
        
        Stratégie:
          1. Range les modèles par taux de succès (basé sur l'apprentissage)
          2. Essaie le meilleur modèle en premier
          3. Si échec → essaie modèle suivant
          4. Enregistre le résultat pour apprentissage futur
          5. Retourne succès avec meilleur modèle qui a réussi
        """
        available_models = self._get_available_models()
        if not available_models:
            raise ValueError("Aucun modèle LLM disponible")
        
        # Ranger par taux de succès (meilleur en premier)
        ranked_models = self.learning.rank_models([m["name"] for m in available_models])
        ranked_configs = [cfg for cfg in available_models if cfg["name"] in ranked_models]
        
        result = SolveResult(success=False, puzzle_id=puzzle_id)
        start = time.time()
        models_tried = []
        
        # Essayer chaque modèle jusqu'à succès
        for model_config in ranked_configs:
            model_name = model_config["name"]
            models_tried.append(model_name)
            print(f"    [Tentative avec {model_name}]", flush=True)
            
            try:
                # Créer un provider pour ce modèle
                provider = self._create_llm_provider(model_config)
                self.llm = provider
                
                # Résoudre avec ce modèle (utiliser le contexte async existant)
                result_attempt = await self.solve(puzzle, puzzle_id)
                
                # Enregistrer le résultat pour apprentissage
                self.learning.record_result(
                    model_name,
                    result_attempt.success,
                    puzzle_id,
                    result_attempt.time_ms
                )
                
                if result_attempt.success:
                    # Succès! Retourner avec ce modèle
                    result_attempt.model_used = model_name
                    result_attempt.models_tried = models_tried
                    result_attempt.time_ms = (time.time() - start) * 1000
                    return result_attempt
                    
            except Exception as e:
                print(f"      Erreur: {str(e)[:50]}", flush=True)
                self.learning.record_result(model_name, False, puzzle_id, (time.time() - start) * 1000)
                continue
        
        # Tous les modèles ont échoué
        result.models_tried = models_tried
        result.time_ms = (time.time() - start) * 1000
        return result


    async def connect(self):
        """Ouvre la connexion stdio vers le serveur MCP."""
        server_params = StdioServerParameters(
            command=sys.executable,
            args=[self.server_script],
            env=None
        )
        self._stdio_ctx = stdio_client(server_params)
        read, write = await self._stdio_ctx.__aenter__()
        self._session_ctx = ClientSession(read, write)
        self.session = await self._session_ctx.__aenter__()
        await self.session.initialize()
        return self

    async def disconnect(self):
        """Ferme la connexion."""
        if self._session_ctx:
            await self._session_ctx.__aexit__(None, None, None)
        if self._stdio_ctx:
            await self._stdio_ctx.__aexit__(None, None, None)

    async def __aenter__(self):
        return await self.connect()

    async def __aexit__(self, *args):
        await self.disconnect()

    # ─── Appels MCP (outils du serveur) ──────────────────────────────────

    async def _call_tool(self, name: str, arguments: dict) -> dict:
        """Appelle un outil sur le serveur MCP et retourne le résultat JSON."""
        result = await self.session.call_tool(name, arguments)
        if result.content and len(result.content) > 0:
            return json.loads(result.content[0].text)
        return {}

    async def mcp_execute(self, code: str, goal: str = "solve") -> dict:
        return await self._call_tool("execute_prolog", {"code": code, "goal": goal})

    async def mcp_validate(self, code: str) -> dict:
        return await self._call_tool("validate_prolog", {"code": code})

    async def mcp_fix(self, code: str) -> dict:
        return await self._call_tool("auto_fix_prolog", {"code": code})

    async def mcp_parse(self, output: str, variables: list, n_positions: int) -> dict:
        return await self._call_tool("parse_prolog_output", {
            "output": output, "variables": variables, "n_positions": n_positions
        })

    async def list_tools(self) -> list[dict]:
        result = await self.session.list_tools()
        return [{"name": t.name, "description": t.description} for t in result.tools]

    # ─── Extraction de code Prolog ───────────────────────────────────────

    @staticmethod
    def _extract_prolog(text: str) -> str:
        """Extrait le code Prolog d'une réponse LLM (markdown ou brut)."""
        match = re.search(r'```(?:prolog)?\s*\n(.*?)```', text, re.DOTALL)
        if match:
            return match.group(1).strip()
        if ':- use_module' in text or 'solve :-' in text:
            lines = []
            capturing = False
            for line in text.split('\n'):
                if ':- use_module' in line or 'solve :-' in line:
                    capturing = True
                if capturing:
                    lines.append(line)
                    if line.strip().endswith('nl.'):
                        break
            if lines:
                return '\n'.join(lines)
        return text.strip()

    @staticmethod
    def _extract_variables(code: str) -> list[str]:
        """Extrait les variables de Vars = [...]."""
        match = re.search(r'Vars\s*=\s*\[(.*?)\]', code, re.DOTALL)
        if not match:
            return []
        return [v.strip() for v in match.group(1).replace('\n', ',').split(',')
                if v.strip() and v.strip()[0].isupper()]

    @staticmethod
    def _extract_n(code: str) -> int:
        """Extrait N de Vars ins 1..N."""
        match = re.search(r'ins\s+1\.\.(\d+)', code)
        return int(match.group(1)) if match else 0

    @staticmethod
    def _extract_clues(puzzle: str) -> str:
        """Extrait les indices du puzzle (section après ## Clues:)."""
        # Try to find clues section
        clues_idx = puzzle.lower().find("clue")
        if clues_idx > 0:
            # Return everything from clues section onward
            return puzzle[clues_idx:]
        # Fallback: return numbered/bulleted lines
        clues = []
        for line in puzzle.split('\n'):
            stripped = line.strip()
            if stripped and (stripped[0].isdigit() or stripped.startswith('-') or stripped.startswith('*')):
                clues.append(stripped)
        return '\n'.join(clues) if clues else puzzle

    # ─── Résolution complète d'un puzzle ─────────────────────────────────

    async def solve(self, puzzle: str, puzzle_id: str = "") -> SolveResult:
        """
        Résout un puzzle logique complet via LLM + MCP.

        Pipeline :
          1. LLM génère la structure Prolog (variables, domaines, groupes)
          2. LLM génère les contraintes CLP(FD)
          3. Serveur MCP corrige automatiquement le code
          4. Serveur MCP valide la syntaxe
          5. Serveur MCP exécute via SWI-Prolog
          6. Serveur MCP parse le résultat
          7. Si erreur → LLM corrige → retry
        """
        start = time.time()
        result = SolveResult(success=False, puzzle_id=puzzle_id)
        result.model_used = getattr(self.llm, "model", "unknown")
        result.models_tried = [result.model_used]
        clues = self._extract_clues(puzzle)

        try:
            # ÉTAPE 1 : Génération de la structure
            struct_response = await self.llm.complete(
                SYSTEM_PROMPT,
                DATA_STRUCTURE_PROMPT.format(puzzle=puzzle)
            )
            data_structure = self._extract_prolog(struct_response)

            # ÉTAPE 2 : Génération des contraintes
            constraints_response = await self.llm.complete(
                SYSTEM_PROMPT,
                CONSTRAINTS_PROMPT.format(data_structure=data_structure, clues=clues)
            )
            full_code = self._extract_prolog(constraints_response)

            # S'assurer que le code est complet
            if ':- use_module' not in full_code:
                full_code = ':- use_module(library(clpfd)).\n' + full_code
            if 'solve :-' not in full_code and data_structure:
                # Nettoyer la structure : enlever le point final s'il existe et s'assurer d'une virgule
                struct_clean = data_structure.strip()
                if struct_clean.endswith('.'):
                    struct_clean = struct_clean[:-1]
                if not struct_clean.endswith(','):
                    struct_clean += ','
                full_code = struct_clean + '\n' + full_code

            result.variables = self._extract_variables(full_code)
            result.n_positions = self._extract_n(full_code)

            # BOUCLE DE RETRY avec feedback d'erreur
            temperature = 0.1
            for attempt in range(self.max_retries):
                result.attempts = attempt + 1

                # Étape 3 : Correction automatique via MCP
                fix_result = await self.mcp_fix(full_code)
                if fix_result.get("was_modified"):
                    full_code = fix_result["code"]
                    result.fixes_applied.extend(fix_result.get("fixes", []))

                result.prolog_code = full_code

                # Étape 4 : Validation via MCP
                validation = await self.mcp_validate(full_code)
                if not validation.get("valid"):
                    result.errors.append(f"Validation: {validation.get('errors', [])}")
                    # On essaie quand même d'exécuter

                # Étape 5 : Exécution via MCP → SWI-Prolog
                exec_result = await self.mcp_execute(full_code)

                if exec_result.get("success") and exec_result.get("output"):
                    output = exec_result["output"]
                    # Vérifier qu'on a bien une liste de nombres
                    if re.search(r'\[\d', output):
                        result.raw_output = output
                        result.success = True

                        # Étape 6 : Parsing via MCP
                        if result.variables and result.n_positions:
                            parsed = await self.mcp_parse(
                                output, result.variables, result.n_positions
                            )
                            result.parsed_solution = parsed
                        break

                # RETRY : Demander au LLM de corriger
                error_msg = exec_result.get("error", "No output")
                if not error_msg and not exec_result.get("output"):
                    error_msg = "No solution found (empty output)"
                result.errors.append(f"Attempt {attempt+1}: {error_msg[:200]}")

                if attempt < self.max_retries - 1:
                    temperature = min(0.7, temperature + 0.2)
                    fix_response = await self.llm.complete(
                        SYSTEM_PROMPT,
                        ERROR_FIX_PROMPT.format(code=full_code, error=error_msg),
                        temperature=temperature
                    )
                    full_code = self._extract_prolog(fix_response)
                    # Re-extraire les variables au cas où elles changent
                    new_vars = self._extract_variables(full_code)
                    if new_vars:
                        result.variables = new_vars
                    new_n = self._extract_n(full_code)
                    if new_n:
                        result.n_positions = new_n

        except Exception as e:
            result.errors.append(f"Exception: {str(e)}")

        result.time_ms = (time.time() - start) * 1000
        return result


# ═══════════════════════════════════════════════════════════════════════════════
# DÉMONSTRATION
# ═══════════════════════════════════════════════════════════════════════════════

async def demo():
    """Démo du client MCP avec un puzzle simple."""
    print("=" * 70)
    print("  CLIENT MCP PROLOG — DÉMONSTRATION")
    print("=" * 70)

    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        print("Configurez GROQ_API_KEY pour utiliser Groq.")
        print("Utilisation d'Ollama par défaut.")
        llm = OllamaProvider()
    else:
        llm = GroqProvider(api_key)

    async with MCPPrologClient(llm) as client:
        # Lister les outils MCP disponibles
        tools = await client.list_tools()
        print(f"\n  Outils MCP disponibles ({len(tools)}):")
        for t in tools:
            print(f"    - {t['name']}: {t['description'][:60]}...")

        # Résoudre un puzzle
        puzzle = """There are 3 houses, numbered 1 to 3 from left to right.
Each house has a unique name and a unique color.
Names: Alice, Bob, Charlie
Colors: Red, Blue, Green

## Clues:
1. Alice lives in the red house.
2. The blue house is in position 2.
3. Charlie does not live in the green house."""

        print(f"\n  Puzzle:")
        for line in puzzle.strip().split('\n'):
            print(f"    {line}")

        print(f"\n  Résolution en cours...")
        result = await client.solve(puzzle, puzzle_id="demo-1")

        print(f"\n  Résultat:")
        print(f"    Succès: {'OUI' if result.success else 'NON'}")
        print(f"    Sortie: {result.raw_output}")
        print(f"    Tentatives: {result.attempts}")
        print(f"    Temps: {result.time_ms:.0f}ms")
        if result.fixes_applied:
            print(f"    Corrections: {', '.join(result.fixes_applied)}")
        if result.errors:
            print(f"    Erreurs: {'; '.join(result.errors)}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    import glob
    
    async def main():
        """Lance le client pour tester sur TOUS les CSPLib instances."""
        files = sorted(glob.glob('datasets/csplib_prob069/*/*/*.txt'))
        
        print(f"\n{'╔' + '═'*80 + '╗'}")
        print(f"{'║ Tests CSPLib Problem 069 (Balanced Nursing Workload)':^82}║")
        print(f"{'║ ' + f'{len(files)} instances trouvées':^80}║")
        print(f"{'╚' + '═'*80 + '╝'}")
        
        print(f"\n{'Instance':<35} {'Résultat':<10} {'Modèle':<20} {'Temps (ms)':<12} {'Tentatives'}")
        print("="*90)
        
        results = {
            "success": 0,
            "failure": 0,
            "error": 0,
            "total_time_ms": 0,
            "total_attempts": 0,
        }
        
        for idx, fpath in enumerate(files, 1):
            puzzle = Path(fpath).read_text()
            fname = Path(fpath).name
            try:
                async with MCPPrologClient() as client:
                    result = await client.solve_with_model_selection(puzzle, fname)
                    
                    status = "✓ OUI" if result.success else "✗ NON"
                    if result.success:
                        results["success"] += 1
                    else:
                        results["failure"] += 1
                    
                    results["total_time_ms"] += result.time_ms
                    results["total_attempts"] += result.attempts
                    
                    print(f"{fname:<35} {status:<10} {result.model_used:<20} {result.time_ms:>10.0f}ms {result.attempts:>3}")
            except Exception as e:
                results["error"] += 1
                error_msg = str(e)[:30].replace('\n', ' ')
                print(f"{fname:<35} {'✗ ERROR':<10} {error_msg:<20} {'N/A':>10} {'?':>3}")
            
            # Affiche la progression tous les 10 puzzles
            if idx % 10 == 0:
                print(f"  ℹ Progression: {idx}/{len(files)}")
        
        # Résumé final
        print("\n" + "="*90)
        success_rate = 100*results['success']/(results['success']+results['failure']+results['error']) if (results['success']+results['failure']+results['error']) > 0 else 0
        total_time_s = results['total_time_ms']/1000
        avg_attempts = results['total_attempts'] / (results['success'] + results['failure'] + results['error']) if (results['success'] + results['failure'] + results['error']) > 0 else 0
        
        print("╔" + "═"*88 + "╗")
        print(f"{'║ RÉSUMÉ FINAL':^90}║")
        
        success_line = f"║ Réussis: {results['success']}"
        print(f"{success_line:<90}║")
        
        failure_line = f"║ Échoués: {results['failure']}"
        print(f"{failure_line:<90}║")
        
        error_line = f"║ Erreurs: {results['error']}"
        print(f"{error_line:<90}║")
        
        total_line = f"║ Total: {results['success'] + results['failure'] + results['error']} instances"
        print(f"{total_line:<90}║")
        
        rate_line = f"║ Taux de réussite: {success_rate:.1f}%"
        print(f"{rate_line:<90}║")
        
        time_line = f"║ Temps total: {total_time_s:.1f}s"
        print(f"{time_line:<90}║")
        
        attempts_line = f"║ Tentatives totales: {results['total_attempts']}"
        print(f"{attempts_line:<90}║")
        
        if avg_attempts > 0:
            avg_line = f"║ Tentatives moyennes par puzzle: {avg_attempts:.2f}"
            print(f"{avg_line:<90}║")
    
    asyncio.run(main())
