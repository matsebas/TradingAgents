#!/usr/bin/env python3
"""
Quick test to verify TradingAgents works end-to-end with Google Gemini
"""

import os
import sys

def quick_test():
    print("=" * 80)
    print("TradingAgents - Quick End-to-End Test with Google Gemini")
    print("=" * 80)

    # Check environment
    print("\n1. Checking environment...")
    gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not gemini_key:
        print("❌ ERROR: GEMINI_API_KEY or GOOGLE_API_KEY not set")
        return False
    print(f"✅ API Key found: {gemini_key[:20]}...")

    # Check config
    print("\n2. Checking configuration...")
    from tradingagents.default_config import DEFAULT_CONFIG
    print(f"   LLM Provider: {DEFAULT_CONFIG.get('llm_provider')}")
    print(f"   Deep Think LLM: {DEFAULT_CONFIG.get('deep_think_llm')}")
    print(f"   Quick Think LLM: {DEFAULT_CONFIG.get('quick_think_llm')}")

    if DEFAULT_CONFIG.get('llm_provider', '').lower() != 'google':
        print("⚠️  WARNING: llm_provider is not set to 'google'")
        print("   This test expects Google Gemini configuration")

    # Test memory system
    print("\n3. Testing memory system...")
    try:
        from tradingagents.agents.utils.memory import FinancialSituationMemory
        config = DEFAULT_CONFIG.copy()
        config['gemini_api_key'] = gemini_key

        memory = FinancialSituationMemory("quick_test", config)
        print(f"✅ Memory system initialized: {memory.client_type}")
        print(f"   Embedding model: {memory.embedding}")
    except Exception as e:
        print(f"❌ Memory system failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Test graph initialization
    print("\n4. Testing TradingAgentsGraph initialization...")
    try:
        from tradingagents.graph.trading_graph import TradingAgentsGraph

        config = DEFAULT_CONFIG.copy()
        config['gemini_api_key'] = gemini_key

        print("   Initializing graph (this may take a moment)...")
        graph = TradingAgentsGraph(
            selected_analysts=['market'],  # Just one analyst for quick test
            config=config,
            debug=False
        )
        print("✅ Graph initialized successfully")
        print(f"   Deep thinking LLM: {graph.config['deep_think_llm']}")
        print(f"   Quick thinking LLM: {graph.config['quick_think_llm']}")

    except Exception as e:
        print(f"❌ Graph initialization failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    print("\n" + "=" * 80)
    print("✅ All components initialized successfully!")
    print("=" * 80)
    print("\nYou can now run:")
    print("  python -m cli.main          # For interactive CLI")
    print("  python main.py              # For programmatic usage")
    print()

    return True


if __name__ == "__main__":
    success = quick_test()
    sys.exit(0 if success else 1)

