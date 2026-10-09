# Quick check that the AI key works. Run: python test_key.py   (makes ONE real AI request)
import llm


def main():
    print("provider:", llm.provider())
    if llm.provider() is None:
        print("No key found. Open the .env file next to this script and paste your key "
              "(GEMINI_API_KEY=... or OPENAI_API_KEY=... for Groq)")
        raise SystemExit(1)
    print("model:", llm.model_name())
    ans = llm.ask_json('Return only JSON: {"ok": true, "word": "salam"}')
    print("answer:", ans)
    print("tokens in/out:", llm.stats["in_tokens"], llm.stats["out_tokens"])
    print("KEY WORKS" if ans.get("ok") else "Got a reply but not the expected JSON - send this output to Claude")


if __name__ == "__main__":
    main()
