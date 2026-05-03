#!/usr/bin/env python3
"""
Script de test: Vérifie que le serveur MCP Prolog peut démarrer
"""
import sys
import subprocess
import time

# Chemin du serveur
SERVER_PATH = r"C:\Users\Admin\Desktop\EFKANE\Master1MIAGE\Cours\ProjetTutoré\S2\Test\mcp_prolog\server\mcp_server.py"
VENV_PYTHON = r"C:\Users\Admin\Desktop\EFKANE\Master1MIAGE\Cours\ProjetTutoré\S2\Test\mcp_prolog\.venv\Scripts\python.exe"

def test_server_startup():
    """Lance le serveur pendant 3 secondes pour vérifier qu'il démarre"""
    print("[TEST] 🔍 Test de démarrage du serveur MCP Prolog...")
    
    try:
        # Lance le serveur
        proc = subprocess.Popen(
            [VENV_PYTHON, SERVER_PATH],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        # Attends 2 secondes
        time.sleep(2)
        
        # Si le serveur est encore en vie, c'est bon
        if proc.poll() is None:
            print("[TEST] ✅ Serveur démarre correctement!")
            print("[TEST] 📋 Le serveur est prêt pour Claude Desktop")
            
            # Tue le serveur proprement
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
            
            return True
        else:
            # Le serveur s'est arrêté
            stdout, stderr = proc.communicate()
            print("[TEST] ❌ Serveur s'est arrêté inopinément")
            if stderr:
                print("[TEST] Erreur:", stderr)
            return False
            
    except Exception as e:
        print(f"[TEST] ❌ Erreur au démarrage: {e}")
        return False

if __name__ == "__main__":
    success = test_server_startup()
    sys.exit(0 if success else 1)
