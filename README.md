# Agent Conversationnel pour Problèmes Logiques (MCP + Prolog)

**Projet Tutoré M1 MIAGE** — EUR Digital Systems for Humans (DS4H) — Université Côte d'Azur  
**Auteur :** El Hadji Fodé KANE  
**Tuteurs :** Etienne Lozes & Pascal Urso (Laboratoire I3S, Sophia Antipolis)

---

## Présentation

Ce projet implémente un agent conversationnel capable de résoudre des problèmes logiques formulés en langage naturel. Il combine :

- 🧠 **Un LLM** (local via Ollama ou cloud via Groq) pour traduire le langage naturel en code Prolog.
- ⚙️ **Le protocole MCP** (Model Context Protocol) comme couche d'orchestration entre le LLM et le solveur.
- 🔬 **SWI-Prolog avec CLP(FD)** pour garantir des solutions mathématiquement correctes.

L'architecture est conçue pour être **modulaire**, **robuste** (boucle d'auto-correction), et **frugale** (fonctionne entièrement en local sans GPU dédié).

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

## Résultats (Benchmark ZebraLogic — Polymath Dataset)

Modèle : **Qwen2.5-Coder:7b** (Ollama local, température=0.0, seed=42)

| Difficulté | Total | Résolus | Taux de réussite |
|------------|-------|---------|-----------------|
| Small      | 40    | 38      | **95,0 %**      |
| Medium     | 40    | 31      | **77,5 %**      |
| Large      | 30    | 21      | **70,0 %**      |
| XL         | 30    | 19      | **63,3 %**      |
| **Total**  | **140**| **109** | **77,8 %**     |

---

## Installation

### Prérequis
- Python 3.10+
- [SWI-Prolog](https://www.swi-prolog.org/Download.html) (variable `swipl` dans le PATH)
- [Ollama](https://ollama.com/) (pour le mode local) avec le modèle `qwen2.5-coder:7b`

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

# (Optionnel) Configurer les clés API Groq
cp .env.example .env
# Editez .env avec vos clés
```

---

## Utilisation

### Benchmark ZebraLogic complet
```bash
# Mode local (Ollama — recommandé, reproducible)
python benchmark.py --provider ollama --model qwen2.5-coder:7b

# Mode cloud (Groq)
python benchmark.py --provider groq --size 2x2,3x3 --max 10
```

### Benchmark CSPLib (5 problèmes)
```bash
python benchmark_5puzzles.py
```
Les résultats sont sauvegardés dans `results/5puzzles/YYYY-MM-DD_HHMMSS/`.

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
├── rapport_final.tex       # Rapport LaTeX du projet
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

| Système | Taux de réussite | Environnement LLM |
|---------|-----------------|-------------------|
| logic.py | 91,9 % | API Cloud (GPT-4) |
| Polymath | 84,0 % | API Cloud |
| **Notre système** | **77,8 %** | **100 % Local (Qwen 7B)** |

Notre système atteint 77,8 % *entièrement en local*, à coût zéro, sans GPU dédié. Sur serveur dédié avec modèle plus large, ce score est estimé largement supérieur à 90 %.

---

## Sécurité

> ⚠️ **Ne jamais committer de fichier `.env`** ou de clés API dans ce dépôt.  
> Les clés Groq sont chargées depuis les variables d'environnement (voir `.env.example`).

---

## Licence

Usage académique — Projet Tutoré M1 MIAGE, Université Côte d'Azur, 2025-2026.
