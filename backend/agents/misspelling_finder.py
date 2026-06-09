import anthropic
import os
import json
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))


def generate_misspellings(query: str) -> list[str]:
    """Use Claude to generate common misspellings of a player/card name."""
    prompt = f"""Generate a list of common misspellings that eBay sellers might use when listing this sports card:

Query: "{query}"

Focus on:
- Swapped letters (e.g. Lebron → Leborn, Lerbron)
- Missing letters (e.g. LeBron → Lebron, Lebon)
- Extra letters (e.g. LeBron → Lebronn, LeBronn)
- Phonetic misspellings (e.g. LeBron → Lebrown, Lebrone)
- Common keyboard typos (adjacent keys)
- Split/joined words

Return ONLY a JSON array of misspelling strings, no explanation. Max 8 misspellings.
Example: ["Leborn James", "Lebron Janes", "LeBrone James", "Lebrown James"]"""

    try:
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        import ai
        text = ai.generate(prompt, max_tokens=200).strip()
        # Extract JSON array from response
        start = text.find("[")
        end = text.rfind("]") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
    except Exception as e:
        print(f"Misspelling generation error: {e}")

    # Fallback: basic misspellings
    words = query.split()
    misspellings = []
    for word in words[:2]:
        if len(word) > 3:
            # Swap two middle letters
            mid = len(word) // 2
            swapped = word[:mid-1] + word[mid] + word[mid-1] + word[mid+1:]
            misspellings.append(query.replace(word, swapped))
    return misspellings
