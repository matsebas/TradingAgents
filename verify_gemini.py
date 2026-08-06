#!/usr/bin/env python3
"""
Script de verificación para la configuración de Gemini
"""

import os
import sys

def check_env_vars():
    """Verifica que las variables de entorno estén configuradas"""
    print("🔍 Verificando variables de entorno...\n")

    gemini_key = os.getenv("GEMINI_API_KEY")

    if not gemini_key or gemini_key == "gemini_api_key_placeholder":
        print("❌ GEMINI_API_KEY no está configurada o usa el placeholder")
        print("   Configúrala con: export GEMINI_API_KEY='tu-api-key'\n")
        return False
    else:
        print(f"✅ GEMINI_API_KEY configurada: {gemini_key[:10]}...")


    print()
    return True

def check_config():
    """Verifica la configuración del proyecto"""
    print("🔍 Verificando configuración del proyecto...\n")

    try:
        from tradingagents.default_config import DEFAULT_CONFIG

        llm_provider = DEFAULT_CONFIG.get("llm_provider")
        deep_think = DEFAULT_CONFIG.get("deep_think_llm")
        quick_think = DEFAULT_CONFIG.get("quick_think_llm")
        gemini_model = DEFAULT_CONFIG.get("gemini_model")

        fund_vendor = DEFAULT_CONFIG.get("data_vendors", {}).get("fundamental_data")
        news_vendor = DEFAULT_CONFIG.get("data_vendors", {}).get("news_data")

        print(f"LLM Provider: {llm_provider}")
        print(f"  Deep thinking model: {deep_think}")
        print(f"  Quick thinking model: {quick_think}")
        print(f"  Data vendor model: {gemini_model}")
        print()
        print(f"Data Vendors:")
        print(f"  Fundamental data: {fund_vendor}")
        print(f"  News data: {news_vendor}")
        print()

        if llm_provider != "google":
            print("❌ LLM provider no es 'google'")
            return False

        if fund_vendor != "gemini" or news_vendor != "gemini":
            print("⚠️  Data vendors no están configurados a 'gemini'")
            print("    (Esto está bien si prefieres usar otros vendors)")

        print("✅ Configuración correcta\n")
        return True

    except Exception as e:
        print(f"❌ Error al cargar configuración: {e}\n")
        return False

def test_gemini_connection():
    """Prueba la conexión con Gemini"""
    print("🔍 Probando conexión con Gemini (google.genai)...\n")

    try:
        from google import genai
        from google.genai import types
        from tradingagents.dataflows.config import get_config

        config = get_config()
        api_key = config.get("gemini_api_key")

        if not api_key:
            print("❌ API key no encontrada en config")
            return False

        client = genai.Client(api_key=api_key)

        response = client.models.generate_content(
            model=config.get("gemini_model", "gemini-3.6-flash"),
            contents="Hello! Reply with just 'OK' if you can hear me.",
            config=types.GenerateContentConfig(
                temperature=1.0,
                max_output_tokens=100,
            )
        )

        print(f"✅ Conexión exitosa! Respuesta: {response.text[:50]}...")
        print("   ✅ Usando google.genai (biblioteca actualizada)\n")
        return True

    except Exception as e:
        print(f"❌ Error al conectar con Gemini: {e}\n")
        return False

def test_langchain_gemini():
    """Prueba ChatGoogleGenerativeAI de langchain"""
    print("🔍 Probando ChatGoogleGenerativeAI (langchain)...\n")

    try:
        from langchain_google_genai import ChatGoogleGenerativeAI

        llm = ChatGoogleGenerativeAI(model="gemini-3.6-flash")
        response = llm.invoke("Say 'OK' if you work")

        # Handle different response formats
        if hasattr(response, 'content'):
            content = str(response.content)
        else:
            content = str(response)

        # Truncate if too long
        display_content = content[:100] if len(content) > 100 else content
        print(f"✅ Langchain Gemini funciona! Respuesta: {display_content}...\n")
        return True

    except Exception as e:
        print(f"❌ Error con ChatGoogleGenerativeAI: {e}\n")
        return False

def main():
    print("=" * 60)
    print("   VERIFICACIÓN DE CONFIGURACIÓN DE GEMINI")
    print("=" * 60)
    print()

    checks = [
        ("Variables de entorno", check_env_vars),
        ("Configuración del proyecto", check_config),
        ("Conexión con Gemini (vendor)", test_gemini_connection),
        ("ChatGoogleGenerativeAI (langchain)", test_langchain_gemini),
    ]

    results = []
    for name, check_func in checks:
        try:
            result = check_func()
            results.append((name, result))
        except Exception as e:
            print(f"❌ Error en '{name}': {e}\n")
            results.append((name, False))

    print("=" * 60)
    print("   RESUMEN")
    print("=" * 60)
    print()

    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {name}")

    print()

    all_passed = all(result for _, result in results)
    if all_passed:
        print("🎉 ¡Todo configurado correctamente! Gemini está listo para usar.")
        return 0
    else:
        print("⚠️  Hay problemas con la configuración. Revisa los errores arriba.")
        return 1

if __name__ == "__main__":
    sys.exit(main())

