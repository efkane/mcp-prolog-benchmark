"""
benchmark_5puzzles.py - Benchmark Indépendant pour les Problèmes CSPLib
======================================================================
Ce script teste 5 problèmes spécifiques (CSPLib) sans altérer les 
résultats existants du benchmark ZebraLogic.
Il évalue automatiquement les 6 critères demandés par les tuteurs.
"""

import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    from client.mcp_client import MCPPrologClient, OllamaProvider
except ImportError:
    print("Veuillez lancer le script depuis le répertoire mcp_prolog/")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

async def run_benchmark():
    # Setup paths
    script_dir = Path(__file__).resolve().parent
    puzzles_file = script_dir / "csplib_puzzles.json"
    
    if not puzzles_file.exists():
        log.error(f"Fichier introuvable: {puzzles_file}")
        sys.exit(1)
        
    with open(puzzles_file, "r", encoding="utf-8") as f:
        puzzles = json.load(f)
        
    # Create isolated output directory
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_dir = script_dir / "results" / "5puzzles" / timestamp
    out_dir.mkdir(parents=True, exist_ok=True)
    
    log.info("═" * 60)
    log.info("  BENCHMARK CSPLib (5 puzzles) - STRICTEMENT ISOLÉ")
    log.info(f"  Dossier de sortie : {out_dir}")
    log.info("═" * 60)

    # Initialize client with Qwen2.5-coder:7b (local, stable)
    provider = OllamaProvider(model="qwen2.5-coder:7b")
    client = MCPPrologClient(llm=provider)
    
    results = []
    
    async with client:
        for i, puzzle in enumerate(puzzles):
            pid = puzzle["id"]
            log.info(f"[{i+1}/5] Résolution de {pid}...")
            
            start_time = time.time()
            try:
                # Solve using the same method as benchmark.py
                res = await client.solve(puzzle["puzzle"], pid)
                elapsed_ms = (time.time() - start_time) * 1000
                
                # Évaluation automatique des 6 critères
                c1_intention_mcp = bool(res.prolog_code.strip())
                c2_utilisation_outils = "Oui" if res.attempts > 0 else "Non"
                c3_succes = "Oui" if res.success else "Non"
                c4_retries = max(0, res.attempts - 1)
                
                # Check for python fallback in raw output
                raw = str(res.raw_output).lower()
                c5_python = "Oui" if ("def " in raw or "import " in raw or "python" in raw) and not res.success else "Non"
                
                # Code generality - simple heuristic
                c6_generalite = "Faible (hardcodé)" if str(res.n_positions) in res.prolog_code and res.n_positions > 0 else "Moyenne/Élevée (à vérifier)"
                if c3_succes == "Non":
                    c6_generalite = "N/A"
                
                results.append({
                    "id": pid,
                    "status": "correct" if res.success else "failed",
                    "time_ms": elapsed_ms,
                    "attempts": res.attempts,
                    "c1_intention": "Oui" if c1_intention_mcp else "Non",
                    "c2_outils": c2_utilisation_outils,
                    "c3_succes": c3_succes,
                    "c4_retries": c4_retries,
                    "c5_python": c5_python,
                    "c6_generalite": c6_generalite,
                    "raw_prolog": res.prolog_code,
                    "raw_output": res.raw_output
                })
                
                log.info(f"  -> Succès: {c3_succes} | Retries: {c4_retries} | Temps: {elapsed_ms:.0f}ms")
                
            except Exception as e:
                log.error(f"  Erreur fatale sur {pid}: {e}")
                results.append({
                    "id": pid,
                    "status": "error",
                    "error_msg": str(e)
                })

    # Generate CSV and Markdown
    csv_file = out_dir / "evaluation_grid.csv"
    md_file = out_dir / "evaluation_grid.md"
    json_file = out_dir / "raw_results.json"
    
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
        
    with open(csv_file, "w", encoding="utf-8") as f:
        f.write("Puzzle,C1: Intention MCP,C2: Utilisation Outils,C3: Succes,C4: Retries,C5: Recours Python,C6: Generalite\n")
        for r in results:
            if r["status"] != "error":
                f.write(f"{r['id']},{r['c1_intention']},{r['c2_outils']},{r['c3_succes']},{r['c4_retries']},{r['c5_python']},{r['c6_generalite']}\n")
                
    with open(md_file, "w", encoding="utf-8") as f:
        f.write("# Grille d'Évaluation CSPLib (5 problèmes)\n\n")
        f.write("| Problème | C1: Intention MCP | C2: Utilisation Outils | C3: Succès | C4: Retries | C5: Recours Python | C6: Généralité |\n")
        f.write("|----------|-------------------|------------------------|------------|-------------|--------------------|----------------|\n")
        for r in results:
            if r["status"] != "error":
                f.write(f"| {r['id']} | {r['c1_intention']} | {r['c2_outils']} | {r['c3_succes']} | {r['c4_retries']} | {r['c5_python']} | {r['c6_generalite']} |\n")
    
    log.info("═" * 60)
    log.info("  TERMINÉ !")
    log.info(f"  Rapports générés dans : {out_dir}")
    log.info("═" * 60)

if __name__ == "__main__":
    asyncio.run(run_benchmark())
