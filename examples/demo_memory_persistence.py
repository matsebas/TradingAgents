"""
Demo script showing memory persistence in action
Run this script twice to see how data persists between sessions
"""
import os
import sys
from dotenv import load_dotenv

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tradingagents.agents.utils.memory import FinancialSituationMemory

# Load environment variables
load_dotenv()

def main():
    print("=" * 70)
    print("💾 DEMO: Financial Situation Memory Persistence")
    print("=" * 70 + "\n")

    # Configuration
    config = {
        "llm_provider": "google",
        "gemini_api_key": os.getenv("GEMINI_API_KEY", ""),
        "memory_path": "./demo_chroma_db"  # Demo database
    }

    # Create memory instance
    memory = FinancialSituationMemory(name="demo_trading_memory", config=config)

    # Check existing data
    existing_count = memory.situation_collection.count()
    print(f"📊 Current database status:")
    print(f"   Existing situations: {existing_count}\n")

    if existing_count == 0:
        print("🆕 First run detected - Adding initial situations...\n")

        # Add some example situations
        situations = [
            (
                "High inflation rate with rising interest rates and declining consumer spending",
                "Consider defensive sectors like consumer staples and utilities. Review fixed-income portfolio duration."
            ),
            (
                "Tech sector showing high volatility with increasing institutional selling pressure",
                "Reduce exposure to high-growth tech stocks. Look for value opportunities in established tech companies with strong cash flows."
            ),
            (
                "Strong dollar affecting emerging markets with increasing forex volatility",
                "Hedge currency exposure in international positions. Consider reducing allocation to emerging market debt."
            ),
            (
                "Market showing signs of sector rotation with rising yields",
                "Rebalance portfolio to maintain target allocations. Consider increasing exposure to sectors benefiting from higher rates."
            ),
        ]

        memory.add_situations(situations)
        print(f"   ✅ Added {len(situations)} situations to memory")
        print("   💡 Run this script again to see the data persist!\n")

    else:
        print("✨ Data persisted from previous run!\n")

        # Show all existing situations
        all_data = memory.situation_collection.get()
        print(f"📚 Stored situations ({len(all_data['documents'])}):")
        for i, (doc, meta) in enumerate(zip(all_data['documents'], all_data['metadatas']), 1):
            print(f"\n{i}. Situation: {doc[:80]}...")
            print(f"   → Recommendation: {meta['recommendation'][:80]}...")

    # Query example
    print("\n" + "=" * 70)
    print("🔍 Testing similarity search...")
    print("=" * 70 + "\n")

    query = "Market volatility in technology sector with rising rates"
    print(f"Query: {query}\n")

    results = memory.get_memories(query, n_matches=2)

    print(f"Found {len(results)} matches:\n")
    for i, result in enumerate(results, 1):
        print(f"Match {i} (Similarity: {result['similarity_score']:.2%}):")
        print(f"  Situation: {result['matched_situation'][:80]}...")
        print(f"  Recommendation: {result['recommendation'][:80]}...\n")

    print("=" * 70)
    print("✅ Demo completed!")
    print(f"💾 Database location: {config['memory_path']}")
    print("🔄 Run this script again to see persistence in action!")
    print("=" * 70)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
