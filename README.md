# Jigyasa (जिज्ञासा)

> You can copy an answer. You can't copy understanding.

A voice-first learning app: students explain a school concept out loud to **Kyun-Kyun**, a curious AI younger sibling, who keeps asking "why" until it is clear whether they really understand.

Built for **India Runs on Voice** (Scaler × Wispr Flow), Education theme.

## Run it

```bash
docker compose up
```

Open http://localhost:3000. You don't need a `.env` file or any API keys: without a key, Jigyasa uses its offline brain.

To use the AI brain (optional), copy `.env.example` to `.env` and set `GEMINI_API_KEY`.

_Full documentation will be added in a later milestone._
