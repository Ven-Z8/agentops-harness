# AgentOps Harness Project Rules

- Build a local-first coding-agent harness, not a chatbot.
- Demo mode must work without paid API keys.
- Use the mock provider by default.
- User approved an OpenAI-compatible provider path for OpenRouter/OpenAI. Keep it behind `app/core/llm.py` and keep mock mode as the default.
- Keep CLI and core engine reliable before adding dashboard/UI work.
- Never create real `.env` files or hardcode secrets.
