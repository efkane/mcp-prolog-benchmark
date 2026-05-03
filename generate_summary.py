import json
import glob
from pathlib import Path
import os

def main():
    # Répertoire où se trouve ce script
    script_dir = Path(__file__).parent.absolute()
    print(f"Répertoire du script : {script_dir}")
    print(f"Répertoire de travail actuel : {os.getcwd()}")

    # Recherche récursive de TOUS les fichiers benchmark_results_*.json
    # dans n'importe quel sous-dossier de results/
    pattern = script_dir / "results" / "**" / "benchmark_results_*.json"
    result_files = glob.glob(str(pattern), recursive=True)

    if not result_files:
        print("\n❌ Aucun fichier 'benchmark_results_*.json' trouvé.")
        print("Voici le contenu complet de votre dossier 'results' :\n")
        results_dir = script_dir / "results"
        if results_dir.exists():
            for racine, dossiers, fichiers in os.walk(results_dir):
                niveau = racine.replace(str(results_dir), '').count(os.sep)
                indent = '  ' * niveau
                print(f"{indent}{Path(racine).name}/")
                for f in fichiers:
                    if f.endswith('.json'):
                        print(f"  {indent}  - {f}")
        else:
            print(f"  → Le dossier 'results' est introuvable à l'emplacement : {results_dir}")
        return

    print(f"\n✅ {len(result_files)} fichier(s) trouvé(s) :")
    for f in result_files:
        print(f"  - {f}")

    # --- Calcul des statistiques (identique à votre version) ---
    stats = {
        "Small":  {"Total": 0, "Traités": 0, "Résolus": 0},
        "Medium": {"Total": 0, "Traités": 0, "Résolus": 0},
        "Large":  {"Total": 0, "Traités": 0, "Résolus": 0},
        "XL":     {"Total": 0, "Traités": 0, "Résolus": 0}
    }

    def taille_vers_difficulte(taille: str) -> str:
        taille = taille.replace("*", "x")
        if taille.startswith("2"): return "Small"
        if taille.startswith("3"): return "Medium"
        if taille.startswith("4"): return "Large"
        if taille.startswith("5") or taille.startswith("6"): return "XL"
        return "Medium"

    for chemin in result_files:
        try:
            with open(chemin, "r", encoding="utf-8") as f:
                data = json.load(f)
                for res in data.get("results", []):
                    taille = res.get("puzzle_size", "3x3")
                    diff = taille_vers_difficulte(taille)
                    statut = res.get("status", "failed")

                    stats[diff]["Total"] += 1
                    if statut in ["correct", "failed"]:
                        stats[diff]["Traités"] += 1
                    if statut == "correct":
                        stats[diff]["Résolus"] += 1
        except Exception as e:
            print(f"Erreur de lecture de {chemin} : {e}")

    # --- Génération du rapport Markdown et CSV ---
    md = [
        "# Résumé du Benchmark (Dataset Polymath)",
        "",
        "| Difficultés | Nombres de problèmes total | Nombre de problèmes traités | Nombre de problèmes résolus |",
        "|-------------|----------------------------|-----------------------------|-----------------------------|"
    ]
    ordre = ["Small", "Medium", "Large", "XL"]
    for diff in ordre:
        if stats[diff]["Total"] > 0:
            md.append(f"| {diff} | {stats[diff]['Total']} | {stats[diff]['Traités']} | {stats[diff]['Résolus']} |")
    md.append("")
    md.append("## Rapport généré avec succès")

    # Sauvegarde des fichiers
    sortie_dir = script_dir / "results"
    sortie_dir.mkdir(exist_ok=True)

    with open(sortie_dir / "TABLEAU_BENCHMARK.md", "w", encoding="utf-8") as f:
        f.write("\n".join(md))

    csv_lignes = ["Difficultés,Nombres de problèmes total,Nombre de problèmes traités,Nombre de problèmes résolus"]
    for diff in ordre:
        if stats[diff]["Total"] > 0:
            csv_lignes.append(f"{diff},{stats[diff]['Total']},{stats[diff]['Traités']},{stats[diff]['Résolus']}")

    with open(sortie_dir / "TABLEAU_BENCHMARK.csv", "w", encoding="utf-8") as f:
        f.write("\n".join(csv_lignes))

    print("\n================== TABLEAU SYNTHÈSE ==================")
    for ligne in md[2:]:
        print(ligne)
    print("======================================================\n")
    print(f"✅ Fichiers générés : {sortie_dir / 'TABLEAU_BENCHMARK.md'} et {sortie_dir / 'TABLEAU_BENCHMARK.csv'}")

if __name__ == "__main__":
    main()