#!/usr/bin/env python3
"""
Test básico de las funciones de gemini.py usando google.genai
"""

import os
import sys
from datetime import datetime, timedelta

# Asegurar que se puede importar el módulo
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_imports():
    """Verifica que los imports funcionen correctamente"""
    print("🔍 Probando imports...\n")
    try:
        from tradingagents.dataflows.gemini import (
            get_stock_news_gemini,
            get_global_news_gemini,
            get_fundamentals_gemini
        )
        print("✅ Imports exitosos\n")
        return True
    except Exception as e:
        print(f"❌ Error en imports: {e}\n")
        return False

def test_config():
    """Verifica que la configuración esté correcta"""
    print("🔍 Probando configuración...\n")
    try:
        from tradingagents.dataflows.config import get_config
        config = get_config()

        if config.get("gemini_api_key"):
            print(f"✅ API key configurada: {config.get('gemini_api_key')[:10]}...")
        else:
            print("❌ API key no configurada")
            return False

        if config.get("gemini_model"):
            print(f"✅ Modelo configurado: {config.get('gemini_model')}")
        else:
            print("❌ Modelo no configurado")
            return False

        print()
        return True
    except Exception as e:
        print(f"❌ Error en configuración: {e}\n")
        return False

def test_client_creation():
    """Verifica que se pueda crear un cliente de Gemini"""
    print("🔍 Probando creación de cliente...\n")
    try:
        from google import genai
        from google.genai import types
        from tradingagents.dataflows.config import get_config

        config = get_config()
        client = genai.Client(api_key=config.get("gemini_api_key"))

        print("✅ Cliente creado exitosamente")
        print(f"   Usando modelo: {config.get('gemini_model', 'gemini-3.6-flash')}\n")
        return True
    except Exception as e:
        print(f"❌ Error creando cliente: {e}\n")
        return False

def main():
    print("=" * 60)
    print("   TEST DE FUNCIONES GEMINI (google.genai)")
    print("=" * 60)
    print()

    results = {
        "imports": test_imports(),
        "config": test_config(),
        "client": test_client_creation(),
    }

    print("=" * 60)
    print("   RESUMEN")
    print("=" * 60)
    print()

    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {test_name}")

    print()

    if all(results.values()):
        print("🎉 Todas las funciones de gemini.py están correctamente configuradas!")
        print("   Usando google.genai (biblioteca actualizada)")
        return 0
    else:
        print("⚠️  Algunos tests fallaron. Revisa los errores arriba.")
        return 1

if __name__ == "__main__":
    sys.exit(main())

