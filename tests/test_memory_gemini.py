#!/usr/bin/env python3
"""
Test script to verify that the memory system works with Google Gemini embeddings
"""

import os
import sys

def test_memory_with_gemini():
    print("=" * 80)
    print("Testing Memory System with Google Gemini")
    print("=" * 80)

    # Check environment variables
    print("\n1. Checking environment variables...")
    gemini_key = os.getenv("GEMINI_API_KEY")
    google_key = os.getenv("GOOGLE_API_KEY")

    if not gemini_key and not google_key:
        print("❌ ERROR: Neither GEMINI_API_KEY nor GOOGLE_API_KEY is set")
        print("\nPlease set one of these environment variables:")
        print('  export GEMINI_API_KEY="your-api-key"')
        print('  export GOOGLE_API_KEY="your-api-key"')
        return False

    api_key = gemini_key or google_key
    print(f"✅ API Key found: {api_key[:20]}...")

    # Test imports
    print("\n2. Testing imports...")
    try:
        from tradingagents.agents.utils.memory import FinancialSituationMemory
        print("✅ Successfully imported FinancialSituationMemory")
    except Exception as e:
        print(f"❌ Failed to import FinancialSituationMemory: {e}")
        return False

    try:
        from google import genai
        print("✅ Successfully imported google.genai")
    except Exception as e:
        print(f"❌ Failed to import google.genai: {e}")
        print("   Please install: pip install google-genai")
        return False

    # Test configuration
    print("\n3. Testing memory initialization with Gemini...")
    config = {
        "llm_provider": "google",
        "gemini_api_key": api_key,
        "backend_url": "https://generativelanguage.googleapis.com/v1",
    }

    try:
        memory = FinancialSituationMemory("test_memory", config)
        print(f"✅ Memory initialized with provider: {memory.client_type}")
        print(f"✅ Using embedding model: {memory.embedding}")
    except Exception as e:
        print(f"❌ Failed to initialize memory: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Test embedding
    print("\n4. Testing embedding generation...")
    test_text = "High inflation rate with rising interest rates"

    try:
        embedding = memory.get_embedding(test_text)
        print(f"✅ Generated embedding with {len(embedding)} dimensions")
        print(f"   First 5 values: {embedding[:5]}")
    except Exception as e:
        print(f"❌ Failed to generate embedding: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Test adding and retrieving memories
    print("\n5. Testing memory storage and retrieval...")
    test_data = [
        (
            "High inflation rate with rising interest rates and declining consumer spending",
            "Consider defensive sectors like consumer staples and utilities."
        ),
        (
            "Tech sector showing high volatility with increasing institutional selling pressure",
            "Reduce exposure to high-growth tech stocks."
        ),
    ]

    try:
        memory.add_situations(test_data)
        print(f"✅ Added {len(test_data)} situations to memory")
    except Exception as e:
        print(f"❌ Failed to add situations: {e}")
        import traceback
        traceback.print_exc()
        return False

    try:
        query = "Market showing increased volatility in tech sector"
        results = memory.get_memories(query, n_matches=1)
        print(f"✅ Retrieved {len(results)} matching memories")

        if results:
            print(f"\n   Query: {query}")
            print(f"   Best match: {results[0]['matched_situation'][:80]}...")
            print(f"   Similarity: {results[0]['similarity_score']:.3f}")
            print(f"   Recommendation: {results[0]['recommendation'][:80]}...")
    except Exception as e:
        print(f"❌ Failed to retrieve memories: {e}")
        import traceback
        traceback.print_exc()
        return False

    print("\n" + "=" * 80)
    print("✅ All tests passed! Memory system is working with Google Gemini")
    print("=" * 80)
    return True


if __name__ == "__main__":
    success = test_memory_with_gemini()
    sys.exit(0 if success else 1)

