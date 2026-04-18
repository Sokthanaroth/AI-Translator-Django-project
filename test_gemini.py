import os
import sys
from google import genai

# Fix windows console unicode issues
sys.stdout.reconfigure(encoding='utf-8')

# Setup your API key here (get one at https://aistudio.google.com/app/apikey)
# IMPORTANT: Never commit real API keys to version control!
GEMINI_API_KEY = os.environ.get("GOOGLE_API_KEY", "YOUR_NEW_API_KEY_HERE")

client = genai.Client(api_key=GEMINI_API_KEY)
model_name = 'gemini-2.0-flash'


def test_translation(text, target_language="English"):
    print(f"Original: {text}")
    print(f"Translating to {target_language}...\n")
    
    prompt = f"Translate the following text to {target_language}. Just provide the translation and nothing else:\n\n{text}"
    
    response = client.models.generate_content(model=model_name, contents=prompt)
    print(f"Translation: {response.text}")
    print("-" * 40)


def test_grammar_fix(text):
    print(f"Original: {text}")
    print(f"Fixing Grammar...\n")
    
    prompt = f"""You are a grammar expert. Fix the following text and explain your corrections.
Format your response as:
Fixed: [The fixed text]
Explanation: [Why you made the changes]

Text to fix:
{text}
"""
    
    response = client.models.generate_content(model=model_name, contents=prompt)
    print(response.text)
    print("-" * 40)


if __name__ == "__main__":
    if GEMINI_API_KEY == "YOUR_API_KEY_HERE":
        print("Please replace 'YOUR_API_KEY_HERE' in test_gemini.py with your real Google Gemini API Key.")
        print("You can get one for free at: https://aistudio.google.com/app/apikey")
    else:
        # Example tests
        test_translation("សួស្តី តើអ្នកមានឈ្មោះអ្វី?", "English")
        test_translation("Hello, how are you today?", "Khmer")
        
        test_grammar_fix("He do not likes to eating apple.")
