# Agent Conversationnel pour Problèmes Logiques (MCP + Prolog)

**Projet Tutoré M1 MIAGE** — EUR Digital Systems for Humans (DS4H) — Université Côte d'Azur  
**Auteur :** El Hadji Fodé KANE  
**Tuteurs :** Etienne Lozes & Pascal Urso (Laboratoire I3S, Sophia Antipolis)

---

## Présentation

Ce projet implémente un agent conversationnel pour résoudre des problèmes logiques en langage naturel. Il fonctionne en trois étapes :

1. Un LLM (Ollama localement ou Groq dans le cloud) qui traduit les énoncés en code Prolog.
2. Le protocole MCP (Model Context Protocol) qui orchestre la communication entre le LLM et le solveur.
3. SWI-Prolog avec CLP(FD) qui valide et exécute le code Prolog pour trouver les solutions.

L'architecture est modulaire, robuste avec une boucle d'auto-correction, et elle fonctionne entièrement en local sans GPU dédié.

---

## Architecture

```
Énoncé (langage naturel)
        │
        ▼
  ┌─────────────┐
  │    LLM      │  (Ollama local ou Groq cloud)
  │  qwen2.5    │
  └──────┬──────┘
         │  génère du code Prolog
         ▼
  ┌─────────────────────────────────────┐
  │           Client MCP                │
  │   (benchmark.py / mcp_client.py)    │
  └──────────────┬──────────────────────┘
                 │ protocole MCP / JSON-RPC
                 ▼
  ┌─────────────────────────────────────┐
  │           Serveur MCP               │
  │   Outils : validate / fix /         │
  │            execute / parse          │
  └──────────────┬──────────────────────┘
                 │ subprocess
                 ▼
         ┌──────────────┐
         │  SWI-Prolog  │
         │   CLP(FD)    │
         └──────────────┘
```

---

## Résultats

Benchmark sur ZebraLogic (dataset Polymath) avec Qwen2.5-Coder:7b en local (température=0.0, seed=42) :

| Difficulté | Total | Résolis | Taux réussite |
|------------|-------|---------|---------------------|
| Small      | 40    | 38      | 95,0 %      |
| Medium     | 40    | 31      | 77,5 %      |
| Large      | 30    | 21      | 70,0 %      |
| XL         | 30    | 19      | 63,3 %      |
| **Total**  | **140**| **109** | **77,8 %**     |

Les résultats détaillés sont disponibles dans le dossier `results/ollama/` de ce dépôt. Vous pouvez les consulter directement sans relancer les benchmarks. Si vous voulez régénérer vos propres résultats :

```bash
python benchmark.py
```

---

## Installation

### Prérequis

Vous aurez besoin de :
- Python 3.10 ou plus récent
- [SWI-Prolog](https://www.swi-prolog.org/Download.html) (accessible depuis le PATH)
- [Ollama](https://ollama.com/) avec le modèle `qwen2.5-coder:7b`

### Installation

```bash
# Cloner le dépôt
git clone https://github.com/VOTRE_COMPTE/VOTRE_REPO.git
cd mcp_prolog

# Créer un environnement virtuel
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/macOS

# Installer les dépendances
pip install -r requirements.txt

# Optionnel : configurer les clés Groq
cp .env.example .env
# Éditez .env avec vos clés si vous comptez utiliser Groq
```

### Fichiers locaux vs GitHub

Ces fichiers ne sont **pas versionnés** sur GitHub (voir `.gitignore`) :

- `.env` — vos clés API personnelles
- `.venv/` — votre environnement virtuel
- Fichiers de log

Les résultats de benchmarks (`results/ollama/`) **sont** inclus sur GitHub pour permettre à vos tuteurs et aux autres de les consulter sans relancer les tests.

---

## Utilisation

### Benchmark complet ZebraLogic

```bash
# Mode local avec Ollama (recommandé)
python benchmark.py --provider ollama --model qwen2.5-coder:7b

# Mode cloud avec Groq
python benchmark.py --provider groq --size 2x2,3x3 --max 10
```

### Benchmark CSPLib (5 problèmes)

```bash
python benchmark_5puzzles.py
```

Les résultats sont enregistrés dans `results/5puzzles/` avec un timestamp.

---

## Structure du projet

```
mcp_prolog/
├── benchmark.py            # Script principal de benchmark ZebraLogic
├── benchmark_5puzzles.py   # Script de test sur les 5 problèmes CSPLib
├── csplib_puzzles.json     # Énoncés des 5 problèmes CSPLib
├── generate_summary.py     # Génération des tableaux récapitulatifs
├── requirements.txt        # Dépendances Python
├── .env.example            # Template de configuration des clés API

│
├── client/
│   ├── mcp_client.py       # Client MCP + Providers LLM + Prompts
│   └── __init__.py
│
├── server/
│   ├── mcp_server.py       # Serveur MCP (outils Prolog)
│   └── __init__.py
│
└── results/
    ├── ollama/             # Résultats du benchmark ZebraLogic
    └── 5puzzles/           # Résultats du benchmark CSPLib
```

---

## Comparaison avec l'état de l'art

| Système | Taux réussite | Environnement LLM |
|---------|-----------------|-------------------|
| logic.py | 91,9 % | API Cloud (GPT-4) |
| Polymath | 84,0 % | API Cloud |
| Notre système | 77,8 % | 100 % Local (Qwen 7B) |

Notre système atteint 77,8 % entièrement en local, à coût zéro et sans GPU dédié. Sur un serveur dédié avec un modèle plus grand, ce score devrait être largement supérieur à 90 %.

---

## Sécurité

Ne jamais committer de fichier `.env` ou de clés API dans ce dépôt. Les clés Groq sont chargées depuis les variables d'environnement (voir `.env.example`).

---

## Licence

Usage académique — Projet Tutoré M1 MIAGE, Université Côte d'Azur, 2025-2026.
