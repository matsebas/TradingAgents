"""
Test for FinancialSituationMemory persistence functionality
"""
import os
import sys
import tempfile
import shutil

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tradingagents.agents.utils.memory import FinancialSituationMemory


def test_memory_persistence():
    """Test that ChromaDB persists data between sessions"""

    # Create a temporary directory for the test
    temp_dir = tempfile.mkdtemp()

    try:
        print(f"🧪 Testing memory persistence in: {temp_dir}\n")

        # Configuration - use Google/Gemini as configured in the project
        config = {
            "llm_provider": "google",
            "gemini_api_key": os.getenv("GEMINI_API_KEY", ""),
            "memory_path": temp_dir
        }

        # Test data
        test_data = [
            (
                "High inflation with rising interest rates",
                "Consider defensive sectors and review fixed-income duration"
            ),
            (
                "Tech sector showing high volatility",
                "Reduce exposure to high-growth tech stocks"
            ),
            (
                "Strong dollar affecting emerging markets",
                "Hedge currency exposure in international positions"
            )
        ]

        # === PHASE 1: Create memory and add data ===
        print("📝 Phase 1: Creating memory and adding situations...")
        memory1 = FinancialSituationMemory(name="test_trading_memory", config=config)
        memory1.add_situations(test_data)

        initial_count = memory1.situation_collection.count()
        print(f"   ✅ Added {initial_count} situations")

        # Query to verify data was added
        query = "Market volatility in technology sector"
        results1 = memory1.get_memories(query, n_matches=2)
        print(f"   ✅ Query returned {len(results1)} results")
        print(f"   Top match: {results1[0]['matched_situation'][:60]}...")

        # Clean up first instance
        del memory1
        print("   🔄 Closed first memory instance\n")

        # === PHASE 2: Create new memory instance and verify data persisted ===
        print("📖 Phase 2: Creating new memory instance...")
        memory2 = FinancialSituationMemory(name="test_trading_memory", config=config)

        persisted_count = memory2.situation_collection.count()
        print(f"   ✅ Found {persisted_count} persisted situations")

        # Verify count matches
        assert persisted_count == initial_count, \
            f"Count mismatch! Expected {initial_count}, got {persisted_count}"
        print("   ✅ Count matches!")

        # Query again to verify data integrity
        results2 = memory2.get_memories(query, n_matches=2)
        print(f"   ✅ Query returned {len(results2)} results")

        # Verify same situation is retrieved
        assert results1[0]['matched_situation'] == results2[0]['matched_situation'], \
            "Retrieved different situation after persistence!"
        print("   ✅ Same situation retrieved!")

        # Verify similarity scores are consistent
        score_diff = abs(results1[0]['similarity_score'] - results2[0]['similarity_score'])
        assert score_diff < 0.01, f"Similarity scores differ by {score_diff}"
        print(f"   ✅ Similarity scores consistent: {results2[0]['similarity_score']:.3f}")

        # === PHASE 3: Add more data and verify accumulation ===
        print("\n📚 Phase 3: Testing data accumulation...")
        new_data = [
            (
                "Market showing sector rotation signals",
                "Rebalance portfolio to maintain target allocations"
            )
        ]
        memory2.add_situations(new_data)

        final_count = memory2.situation_collection.count()
        expected_count = initial_count + len(new_data)
        assert final_count == expected_count, \
            f"Expected {expected_count} situations, got {final_count}"
        print(f"   ✅ Data accumulated correctly: {final_count} total situations")

        # Clean up
        del memory2

        # === PHASE 4: Final verification ===
        print("\n🔍 Phase 4: Final verification...")
        memory3 = FinancialSituationMemory(name="test_trading_memory", config=config)
        verify_count = memory3.situation_collection.count()
        assert verify_count == expected_count, \
            f"Final count mismatch! Expected {expected_count}, got {verify_count}"
        print(f"   ✅ Final verification passed: {verify_count} situations persisted")

        # Verify we can still query
        results3 = memory3.get_memories(query, n_matches=1)
        print(f"   ✅ Final query successful")

        print("\n" + "="*60)
        print("✨ ALL TESTS PASSED! Memory persistence is working correctly.")
        print("="*60)
        print(f"\n📊 Summary:")
        print(f"   - Initial situations: {initial_count}")
        print(f"   - Added situations: {len(new_data)}")
        print(f"   - Final total: {verify_count}")
        print(f"   - Data persisted across {3} instances")
        print(f"   - Storage location: {temp_dir}")

        return True

    except Exception as e:
        print(f"\n❌ TEST FAILED: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        # Clean up temporary directory
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
            print(f"\n🧹 Cleaned up test directory")


def test_multiple_collections():
    """Test that multiple collections can be persisted independently"""

    temp_dir = tempfile.mkdtemp()

    try:
        print("\n" + "="*60)
        print("🧪 Testing multiple independent collections...")
        print("="*60 + "\n")

        config = {
            "llm_provider": "google",
            "gemini_api_key": os.getenv("GEMINI_API_KEY", ""),
            "memory_path": temp_dir
        }

        # Create two different memories
        memory_stocks = FinancialSituationMemory(name="stocks_memory", config=config)
        memory_crypto = FinancialSituationMemory(name="crypto_memory", config=config)

        # Add different data to each
        memory_stocks.add_situations([
            ("Bull market in tech stocks", "Increase growth allocation")
        ])
        memory_crypto.add_situations([
            ("Bitcoin hitting new highs", "Consider taking profits")
        ])

        stock_count = memory_stocks.situation_collection.count()
        crypto_count = memory_crypto.situation_collection.count()

        print(f"   ✅ Created 2 collections:")
        print(f"      - stocks_memory: {stock_count} situations")
        print(f"      - crypto_memory: {crypto_count} situations")

        del memory_stocks
        del memory_crypto

        # Recreate and verify
        memory_stocks2 = FinancialSituationMemory(name="stocks_memory", config=config)
        memory_crypto2 = FinancialSituationMemory(name="crypto_memory", config=config)

        assert memory_stocks2.situation_collection.count() == stock_count
        assert memory_crypto2.situation_collection.count() == crypto_count

        print("   ✅ Both collections persisted independently!")
        print("\n✨ Multiple collections test PASSED!")

        return True

    except Exception as e:
        print(f"\n❌ TEST FAILED: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)


if __name__ == "__main__":
    print("="*60)
    print("🚀 FINANCIAL SITUATION MEMORY PERSISTENCE TESTS")
    print("="*60 + "\n")

    # Run tests
    test1_passed = test_memory_persistence()
    test2_passed = test_multiple_collections()

    print("\n" + "="*60)
    print("📋 TEST RESULTS SUMMARY")
    print("="*60)
    print(f"Memory Persistence Test: {'✅ PASSED' if test1_passed else '❌ FAILED'}")
    print(f"Multiple Collections Test: {'✅ PASSED' if test2_passed else '❌ FAILED'}")

    if test1_passed and test2_passed:
        print("\n🎉 All tests passed successfully!")
        sys.exit(0)
    else:
        print("\n⚠️  Some tests failed. Please review the output above.")
        sys.exit(1)
