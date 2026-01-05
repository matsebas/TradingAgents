#!/usr/bin/env python3
"""
Test script to verify that extract_content_string properly cleans Gemini format responses
"""

def extract_content_string(content):
    """Extract clean text content from various message formats."""
    if isinstance(content, str):
        return content
    elif isinstance(content, list):
        # Handle list format (Anthropic/Gemini)
        text_parts = []
        for item in content:
            if isinstance(item, dict):
                # Extract text, ignoring extras like signatures
                if item.get('type') == 'text' and 'text' in item:
                    text_parts.append(item['text'])
                elif item.get('type') == 'tool_use':
                    text_parts.append(f"[Tool: {item.get('name', 'unknown')}]")
                elif 'text' in item:  # Fallback: just extract 'text' key
                    text_parts.append(item['text'])
            elif isinstance(item, str):
                text_parts.append(item)
        return '\n\n'.join(text_parts) if text_parts else str(content)
    else:
        return str(content)


# Test case 1: Simple string
test1 = "Simple string content"
result1 = extract_content_string(test1)
print("Test 1 (Simple string):")
print(f"Input: {test1[:50]}...")
print(f"Output: {result1[:50]}...")
print(f"Pass: {result1 == test1}\n")

# Test 2: Gemini format with extras (like the one in the issue)
test2 = [
    {
        'type': 'text',
        'text': 'This is the actual analysis text that should be extracted.',
        'extras': {
            'signature': 'Very long signature string that should be ignored...'
        }
    }
]
result2 = extract_content_string(test2)
print("Test 2 (Gemini with extras):")
print(f"Input: List with 'type', 'text', and 'extras' keys")
print(f"Output: {result2}")
print(f"Pass: {result2 == 'This is the actual analysis text that should be extracted.' and 'extras' not in result2 and 'signature' not in result2}\n")

# Test 3: List of strings
test3 = ["First part", "Second part", "Third part"]
result3 = extract_content_string(test3)
print("Test 3 (List of strings):")
print(f"Input: {test3}")
print(f"Output: {result3}")
print(f"Pass: {result3 == 'First part\\n\\nSecond part\\n\\nThird part'}\n")

# Test 4: Mixed list (strings and dicts)
test4 = [
    "Some text",
    {'type': 'text', 'text': 'More text'},
    {'type': 'tool_use', 'name': 'get_data'}
]
result4 = extract_content_string(test4)
print("Test 4 (Mixed list):")
print(f"Input: Mixed list with strings and dicts")
print(f"Output: {result4}")
print(f"Pass: {('[Tool: get_data]' in result4 and 'Some text' in result4 and 'More text' in result4)}\n")

# Test 5: Real-world Gemini format (simplified)
test5 = [
    {
        'type': 'text',
        'text': 'Look, I hear the cautious whispers and the wait and see approach coming from the more conservative corners.',
        'extras': {
            'signature': 'EqIdCp8dAXLI2nwrq60D8dPk0YGbVJzggTcDPNtRClu+wnA35MAFeATZa...'
        }
    }
]
result5 = extract_content_string(test5)
print("Test 5 (Real Gemini format):")
print(f"Input: Gemini format with long signature in extras")
print(f"Output length: {len(result5)} characters")
print(f"Output (truncated): {result5[:100]}...")
print(f"Pass: {'EqIdCp8dAXLI2nwrq60D8dPk0YGbVJzggTcDPNtRClu' not in result5 and 'extras' not in result5}\n")

print("="*80)
print("All tests completed!")
print("="*80)

