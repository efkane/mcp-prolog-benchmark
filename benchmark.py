"""
benchmark.py — Benchmark MCP-Prolog (version durable & reproductible)
==============================================================================

DESIGN GOALS:
  - Fonctionne sur TOUTE machine (Linux / macOS / Windows)
  - Séquentiel par défaut → jamais de saturation Groq
  - Backoff exponentiel adaptatif (2→4→8→16→32s) sur 429
  - Fallback automatique Ollama si Groq épuisé
  - Interruption propre (Ctrl+C) : sauvegarde les résultats partiels
  - Résultats reproductibles : seed fixe, ordre stable, JSON horodaté

USAGE:
  python benchmark.py                          # 10 puzzles, mode auto, toutes tailles
  python benchmark.py --size 2x2               # une seule taille
  python benchmark.py --size 2x2,3x3 --max 5  # plusieurs tailles, 5 puzzles chacune
  python benchmark.py --provider groq --max 20 # forcer Groq
  python benchmark.py --sequential             # force séquentiel (défaut)
  python benchmark.py --delay 3.0              # délai minimal entre appels Groq (secondes)

ARCHITECTURE:
  - Un seul slot actif à la fois pour Groq (pas de parallélisme)
  - Chaque puzzle est indépendant, résultat sauvegardé dès terminaison
  - Le fichier benchmark_results_{size}.json est écrit incrémentalement
  - En cas de Ctrl+C : le fichier contient les résultats déjà obtenus

Projet : Projet Tutoré M1 MIAGE — Résolution de Problèmes Logiques
        EUR Digital Systems for Humans (DS4H) — Université Côte d'Azur
"""

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
import time
from pathlib import Path
from datetime import datetime
import traceback

# ── Import des providers ────────────────────────────────────────────────────────
try:
    from client.mcp_client import MCPPrologClient, GroqProvider, OllamaProvider
except ImportError:
    logging.error(
        "ImportError: impossible d'importer mcp_client.\n"
        "Lancez ce script depuis le dossier mcp_prolog/\n"
        "Exemple: python benchmark.py"
    )
    sys.exit(1)

# ── Logging ─────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTES
# ══════════════════════════════════════════════════════════════════════════════

SIZE_TO_DIFFICULTY = {
    "2x2": "small",  "2x3": "small",  "2x4": "small",
    "2x5": "small",  "2x6": "small",  "3x2": "small",
    "3x3": "small",  "4x2": "small",
    "3x4": "medium", "3x5": "medium", "3x6": "medium",
    "4x3": "medium", "4x4": "medium", "5x2": "medium", "6x2": "medium",
    "4x5": "large",  "4x6": "large",  "5x3": "large",  "5x4": "large",
    "6x3": "large",
    "5x5": "xlarge", "5x6": "xlarge", "6x4": "xlarge",
    "6x5": "xlarge", "6x6": "xlarge",
}

ALL_SIZES = ["2x2", "2x3", "3x3", "3x4", "4x4", "4x5", "5x5", "5x6"]

# Délai minimal (en secondes) entre deux appels Groq — ajustable via --delay
DEFAULT_GROQ_DELAY = 4.0  # 4s → ~15 req/min, bien en dessous des limites Groq


# ══════════════════════════════════════════════════════════════════════════════
# GESTION D'INTERRUPTION PROPRE
# ══════════════════════════════════════════════════════════════════════════════

_shutdown_requested = False

def _handle_sigint(sig, frame):
    """Intercepte Ctrl+C et demande un arrêt propre."""
    global _shutdown_requested
    if not _shutdown_requested:
        log.warning("⚠️  Interruption reçue — fin du puzzle courant puis sauvegarde...")
        _shutdown_requested = True
    else:
        log.warning("⚠️  Deuxième interruption — arrêt immédiat.")
        sys.exit(1)

signal.signal(signal.SIGINT, _handle_sigint)


# ══════════════════════════════════════════════════════════════════════════════
# CHARGEMENT DES PUZZLES
# ══════════════════════════════════════════════════════════════════════════════

def load_puzzles(size: str, max_puzzles: int) -> list:
    """
    Charge les puzzles Polymath filtrés par taille.
    Retourne une liste stable (triée par ID pour reproductibilité).
    """
    difficulty = SIZE_TO_DIFFICULTY.get(size)
    if difficulty is None:
        log.error(f"Taille inconnue: {size}. Tailles disponibles: {list(SIZE_TO_DIFFICULTY.keys())}")
        return []

    json_size = size.replace("x", "*")  # "2x2" → "2*2" (format Polymath)
    script_dir = Path(__file__).resolve().parent
    dataset_path = (
        script_dir.parent
        / "polymath" / "agent" / "logic" / "dataset"
        / f"test-00000-of-00001-{difficulty}.json"
    )

    if not dataset_path.exists():
        log.error(f"Dataset introuvable: {dataset_path}")
        log.error(f"  → Vérifiez que le dossier polymath/ est bien présent à côté de mcp_prolog/")
        return []

    with open(dataset_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    puzzles = sorted(
        [p for p in data if p.get("size", "") == json_size],
        key=lambda p: p["id"]  # Tri stable pour reproductibilité
    )

    if not puzzles:
        log.warning(f"Aucun puzzle trouvé pour la taille {size} (format: {json_size})")
        return []

    selected = puzzles[:max_puzzles]
    log.info(f"Taille {size} ({difficulty}): {len(selected)}/{len(puzzles)} puzzles chargés")
    return selected


# ══════════════════════════════════════════════════════════════════════════════
# RÉSOLUTION D'UN PUZZLE AVEC BACKOFF ROBUSTE
# ══════════════════════════════════════════════════════════════════════════════

async def solve_one(client: MCPPrologClient, puzzle: dict, provider_name: str,
                    groq_delay: float, last_groq_call: list) -> dict:
    """
    Résout un puzzle unique.
    - Respecte le délai Groq entre appels
    - Capture toutes les exceptions → résultat "error" (jamais de crash global)
    - Retourne un dict serialisable JSON
    """
    puzzle_id = puzzle["id"]

    # ── Throttling Groq ───────────────────────────────────────────────────────
    if provider_name in ("groq", "auto") and last_groq_call[0] is not None:
        elapsed = time.time() - last_groq_call[0]
        wait = groq_delay - elapsed
        if wait > 0:
            log.debug(f"  Throttle Groq: attente {wait:.1f}s...")
            await asyncio.sleep(wait)

    start = time.time()
    last_groq_call[0] = time.time()

    try:
        if provider_name == "auto":
            res = await client.solve_with_model_selection(puzzle["puzzle"], puzzle_id)
        else:
            res = await client.solve(puzzle["puzzle"], puzzle_id)

        elapsed_ms = (time.time() - start) * 1000

        return {
            "puzzle_id": puzzle_id,
            "puzzle_size": puzzle["size"],
            "status": "correct" if res.success else "failed",
            "expected_solution": puzzle.get("solution", {}),
            "parsed_solution": getattr(res, "parsed_solution", {}),
            "prolog_code_generated": getattr(res, "prolog_code", ""),
            "errors": getattr(res, "errors", []),
            "attempts": getattr(res, "attempts", 1),
            "time_ms": round(elapsed_ms, 1),
            "model_used": getattr(res, "model_used", "unknown"),
            "models_tried": getattr(res, "models_tried", []),
            "fixes_applied": getattr(res, "fixes_applied", []),
        }

    except asyncio.CancelledError:
        raise

    except Exception as e:
        elapsed_ms = (time.time() - start) * 1000
        log.error(f"  Exception pour {puzzle_id}: {e}")
        return {
            "puzzle_id": puzzle_id,
            "puzzle_size": puzzle["size"],
            "status": "error",
            "errors": [str(e)],
            "time_ms": round(elapsed_ms, 1),
        }


# ══════════════════════════════════════════════════════════════════════════════
# BENCHMARK POUR UNE TAILLE
# ══════════════════════════════════════════════════════════════════════════════

async def benchmark_size(
    provider_name: str,
    model_name: str,
    size: str,
    max_puzzles: int,
    groq_delay: float,
    out_dir: Path,
) -> dict:
    """
    Lance le benchmark pour une taille de puzzle, de façon entièrement séquentielle.
    Sauvegarde les résultats partiels en cas d'interruption.
    """
    global _shutdown_requested

    puzzles = load_puzzles(size, max_puzzles)
    if not puzzles:
        return {}

    # ── Construction du client ────────────────────────────────────────────────
    if provider_name == "groq":
        provider = GroqProvider(model=model_name)
        client = MCPPrologClient(llm=provider)
    elif provider_name == "ollama":
        provider = OllamaProvider(model=model_name)
        client = MCPPrologClient(llm=provider)
    else:  # auto
        client = MCPPrologClient(llm=None)

    out_file = out_dir / f"benchmark_results_{size}.json"
    results = []
    correct = 0
    completed_ids = set()

    if out_file.exists():
        try:
            with open(out_file, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
                if "results" in existing_data:
                    results = existing_data["results"]
                    correct = existing_data.get("metadata", {}).get("correct", 0)
                    completed_ids = {r["puzzle_id"] for r in results}
                    log.info(f"  Reprise : {len(completed_ids)} puzzles déjà résolus.")
        except Exception as e:
            log.warning(f"  Impossible de lire le fichier existant: {e}")

    last_groq_call = [None]  # liste mutable pour le partager entre appels
    start_time = datetime.now()

    log.info(f"\n{'─'*60}")
    log.info(f"  Taille {size} — {len(puzzles)} puzzles — provider: {provider_name.upper()}")
    log.info(f"{'─'*60}")

    async with client:
        for i, puzzle in enumerate(puzzles):
            if puzzle['id'] in completed_ids:
                log.info(f"  [{i+1:02d}/{len(puzzles):02d}] {puzzle['id']} (déjà résolu, ignoré)")
                continue

            if _shutdown_requested:
                log.warning(f"  Arrêt demandé après {i}/{len(puzzles)} puzzles.")
                break

            log.info(f"  [{i+1:02d}/{len(puzzles):02d}] {puzzle['id']}")

            result = await solve_one(
                client, puzzle, provider_name, groq_delay, last_groq_call
            )
            results.append(result)

            is_correct = result.get("status") == "correct"
            if is_correct:
                correct += 1

            status_icon = "✓" if is_correct else ("⚠" if result["status"] == "error" else "✗")
            log.info(
                f"         {status_icon} {result['status']:7s} | "
                f"{result.get('time_ms', 0):.0f}ms | "
                f"modèle: {result.get('model_used', 'N/A')}"
            )

            # Sauvegarde incrémentale après chaque puzzle
            _save_partial(results, size, provider_name, model_name, start_time, out_dir)

    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    total = len(results)

    summary = {
        "metadata": {
            "timestamp": start_time.isoformat(),
            "size": size,
            "provider": provider_name,
            "model": model_name,
            "total_puzzles": total,
            "correct": correct,
            "failed": total - correct,
            "success_rate_percent": round(100 * correct / total, 2) if total > 0 else 0,
            "total_time_seconds": round(duration, 2),
            "avg_time_per_puzzle_seconds": round(duration / total, 2) if total > 0 else 0,
            "groq_min_delay_s": groq_delay,
            "interrupted": _shutdown_requested,
        },
        "results": results,
    }

    out_file = out_dir / f"benchmark_results_{size}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    log.info(f"\n  → {size}: {correct}/{total} ({summary['metadata']['success_rate_percent']}%)")
    log.info(f"  → Fichier: {out_file}")
    return summary


def _save_partial(results, size, provider_name, model_name, start_time, out_dir):
    """Sauvegarde les résultats partiels (appelé après chaque puzzle)."""
    total = len(results)
    correct = sum(1 for r in results if r.get("status") == "correct")
    out_file = out_dir / f"benchmark_results_{size}.json"
    partial = {
        "metadata": {
            "timestamp": start_time.isoformat(),
            "size": size,
            "provider": provider_name,
            "model": model_name,
            "total_puzzles": total,
            "correct": correct,
            "success_rate_percent": round(100 * correct / total, 2) if total > 0 else 0,
            "partial": True,
        },
        "results": results,
    }
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(partial, f, indent=2, ensure_ascii=False)


# ══════════════════════════════════════════════════════════════════════════════
# SYNTHÈSE FINALE
# ══════════════════════════════════════════════════════════════════════════════

def print_summary(all_summaries: dict):
    """Affiche un tableau récapitulatif en console."""
    print("\n" + "═" * 70)
    print("  RÉSULTATS FINAUX DU BENCHMARK")
    print("═" * 70)
    print(f"  {'Taille':<8} {'Réussis':<10} {'Total':<8} {'Taux':<8} {'Temps moy.'}")
    print("  " + "─" * 60)

    total_correct = 0
    total_puzzles = 0

    for size, summary in sorted(all_summaries.items()):
        if not summary:
            continue
        m = summary.get("metadata", {})
        correct = m.get("correct", 0)
        total = m.get("total_puzzles", 0)
        rate = m.get("success_rate_percent", 0)
        avg = m.get("avg_time_per_puzzle_seconds", 0)
        total_correct += correct
        total_puzzles += total
        flag = " ⚠ (interrompu)" if m.get("interrupted") else ""
        print(f"  {size:<8} {correct:<10} {total:<8} {rate:>5.1f}%  {avg:.1f}s/puzzle{flag}")

    if total_puzzles > 0:
        global_rate = 100 * total_correct / total_puzzles
        print("  " + "─" * 60)
        print(f"  {'TOTAL':<8} {total_correct:<10} {total_puzzles:<8} {global_rate:>5.1f}%")

    print("═" * 70)
    print()


def generate_summary_json(all_summaries: dict, out_dir: Path):
    """Génère un fichier JSON de synthèse globale."""
    total_correct = sum(
        s.get("metadata", {}).get("correct", 0)
        for s in all_summaries.values() if s
    )
    total_puzzles = sum(
        s.get("metadata", {}).get("total_puzzles", 0)
        for s in all_summaries.values() if s
    )

    global_summary = {
        "generated_at": datetime.now().isoformat(),
        "global": {
            "total_puzzles": total_puzzles,
            "correct": total_correct,
            "success_rate_percent": round(100 * total_correct / total_puzzles, 2) if total_puzzles > 0 else 0,
        },
        "by_size": {
            size: s.get("metadata", {})
            for size, s in sorted(all_summaries.items()) if s
        },
    }

    out_file = out_dir / "benchmark_global_summary.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(global_summary, f, indent=2, ensure_ascii=False)
    log.info(f"Synthèse globale: {out_file}")
    return global_summary


# ══════════════════════════════════════════════════════════════════════════════
# POINT D'ENTRÉE
# ══════════════════════════════════════════════════════════════════════════════

async def main(args):
    """Orchestration principale — séquentielle et robuste."""
    global _shutdown_requested

    # ── Détermination des tailles à traiter ───────────────────────────────────
    if args.size.lower() == "all":
        sizes = ALL_SIZES
    else:
        sizes = [s.strip() for s in args.size.split(",")]

    out_dir = Path(__file__).resolve().parent
    provider = args.provider.lower()
    model = args.model
    groq_delay = args.delay

    log.info("═" * 60)
    log.info("  BENCHMARK MCP-PROLOG — VERSION ROBUSTE")
    log.info("═" * 60)
    log.info(f"  Tailles      : {sizes}")
    log.info(f"  Max puzzles  : {args.max}")
    log.info(f"  Provider     : {provider.upper()}")
    log.info(f"  Modèle       : {model}")
    log.info(f"  Délai Groq   : {groq_delay}s entre appels")
    log.info(f"  Mode         : SÉQUENTIEL (stable, reproductible)")
    log.info("═" * 60)

    model_safe_name = model.replace(':', '_').replace('/', '_')
    model_dir = out_dir / "results" / provider / model_safe_name
    model_dir.mkdir(parents=True, exist_ok=True)
    log.info(f"  Dossier      : {model_dir}")

    # ── Exécution séquentielle par taille ─────────────────────────────────────
    all_summaries = {}

    for size in sizes:
        if _shutdown_requested:
            log.warning("Arrêt global demandé — benchmark interrompu.")
            break

        summary = await benchmark_size(
            provider_name=provider,
            model_name=model,
            size=size,
            max_puzzles=args.max,
            groq_delay=groq_delay,
            out_dir=model_dir,
        )
        all_summaries[size] = summary

    # ── Résumé ────────────────────────────────────────────────────────────────
    print_summary(all_summaries)
    global_summary = generate_summary_json(all_summaries, model_dir)

    if _shutdown_requested:
        log.warning("Benchmark interrompu — résultats partiels sauvegardés.")
    else:
        log.info("Benchmark terminé avec succès.")

    return global_summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Benchmark MCP-Prolog — robuste et reproductible",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples:
  python benchmark.py
  python benchmark.py --size 2x2 --max 10
  python benchmark.py --size 2x2,2x3,3x3 --max 20
  python benchmark.py --provider groq --delay 5
  python benchmark.py --provider ollama --model qwen2.5-coder
        """
    )
    parser.add_argument(
        "--provider", default="ollama",
        choices=["auto", "groq", "ollama"],
        help="Provider LLM (défaut: ollama — pour reproductibilité scientifique sans limites)"
    )
    parser.add_argument(
        "--model", default="qwen2.5-coder:7b",
        help="Modèle à utiliser si provider est 'groq' ou 'ollama'"
    )
    parser.add_argument(
        "--size", default="all",
        help="Taille(s) ex: 2x2 | 2x2,3x3 | all (défaut: all)"
    )
    parser.add_argument(
        "--max", type=int, default=10,
        help="Nombre max de puzzles par taille (défaut: 10)"
    )
    parser.add_argument(
        "--delay", type=float, default=DEFAULT_GROQ_DELAY,
        help=f"Délai minimal en secondes entre appels Groq (défaut: {DEFAULT_GROQ_DELAY})"
    )
    parser.add_argument(
        "--sequential", action="store_true", default=True,
        help="Mode séquentiel (défaut, toujours actif — option conservée pour compatibilité)"
    )

    args = parser.parse_args()
    asyncio.run(main(args))