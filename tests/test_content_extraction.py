#!/usr/bin/env python3
"""Test script to verify content extraction handles nested JSON structures."""

def extract_content_string(content):
    """Extract clean text content from various message formats."""
    if isinstance(content, str):
        return content
    elif isinstance(content, list):
        # Handle list format (Anthropic/Gemini)
        text_parts = []
        for item in content:
            if isinstance(item, dict):
                # Handle nested text structure (e.g., {'type': 'text', 'text': '...', 'extras': {...}})
                if item.get('type') == 'text' and 'text' in item:
                    nested_text = item['text']
                    if isinstance(nested_text, str):
                        text_parts.append(nested_text)
                    elif isinstance(nested_text, (list, dict)):
                        # Recursively extract if text itself is a structure
                        text_parts.append(extract_content_string(nested_text))
                elif item.get('type') == 'tool_use':
                    text_parts.append(f"[Tool: {item.get('name', 'unknown')}]")
                elif 'text' in item:  # Fallback: just extract 'text' key
                    nested_text = item['text']
                    if isinstance(nested_text, str):
                        text_parts.append(nested_text)
                    elif isinstance(nested_text, (list, dict)):
                        text_parts.append(extract_content_string(nested_text))
            elif isinstance(item, str):
                text_parts.append(item)
        return '\n\n'.join(text_parts) if text_parts else str(content)
    else:
        return str(content)


# Test case 1: Simple nested structure
test_data_1 = [
    {
        'type': 'text',
        'text': 'Based on the intense debate between the analysts and the provided market context, here is the Risk Management decision.\n\n### **The Decision: BUY**\n\n**Recommendation:** Proceed with a **Buy**...',
        'extras': {'signature': 'Risk_Mgmt_Judge'}
    }
]

print("Test 1: Simple nested structure")
print("=" * 80)
result_1 = extract_content_string(test_data_1)
print(result_1)
print("\n" + "=" * 80)

if result_1.startswith("Based on the intense debate"):
    print("✅ Test 1 PASSED: Content extracted correctly as clean text!")
else:
    print("❌ Test 1 FAILED: Content not extracted properly")
    print(f"Got: {result_1[:100]}...")

print("\n\n")

# Test case 2: The deeply nested structure that was causing the issue
test_data_2 = [
    {
        'type': 'text',
        'text': [
            {
                'type': 'text',
                'text': 'All right, let\'s cut through the noise and get to work. The debate has clarified that while the macro-political risk is real, the market positioning (55% Puts) suggests a "squeeze" is the more probable outcome than a crash.\n\n### The Investment Plan\n\n**The Rationale**\nWe are executing a **Buy**, but we are treating the 690 level as a "Tactical Probe" rather than a conviction bottom.',
                'extras': {'signature': 'Risk_Mgmt_Judge'}
            }
        ],
        'extras': {'signature': 'Risk_Mgmt_Judge'}
    }
]

print("Test 2: Deeply nested structure (the problematic case)")
print("=" * 80)
result_2 = extract_content_string(test_data_2)
print(result_2)
print("\n" + "=" * 80)

if result_2.startswith("All right, let's cut through"):
    print("✅ Test 2 PASSED: Deeply nested content extracted correctly!")
else:
    print("❌ Test 2 FAILED: Deeply nested content not extracted properly")
    print(f"Got: {result_2[:100]}...")

print("\n\n")

# Test case 3: Mixed content types
test_data_3 = [
    "Simple string content",
    {
        'type': 'text',
        'text': 'Dictionary text content'
    },
    {
        'type': 'tool_use',
        'name': 'some_tool'
    }
]

print("Test 3: Mixed content types")
print("=" * 80)
result_3 = extract_content_string(test_data_3)
print(result_3)
print("\n" + "=" * 80)

if "Simple string content" in result_3 and "Dictionary text content" in result_3 and "[Tool: some_tool]" in result_3:
    print("✅ Test 3 PASSED: Mixed content handled correctly!")
else:
    print("❌ Test 3 FAILED: Mixed content not handled properly")
    print(f"Got: {result_3}")

