# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A fork of [aws-samples/bedrock-chat](https://github.com/aws-samples/bedrock-chat) (v3 line) customized by Houndoc/Blend360 and branded **Nadia**. It is a generative-AI chat platform on Amazon Bedrock: chat, custom bots with RAG, a bot store, agents, and per-bot published APIs.

Three deployable pieces live in one repo:

| Dir | Stack | Runs as |
| --- | --- | --- |
| [backend/](backend/) | Python 3.13, FastAPI, Poetry | Lambda container (uvicorn + AWS Lambda Web Adapter), plus separate Lambda handlers |
| [frontend/](frontend/) | React 18, Vite, TypeScript, Tailwind | CloudFront + S3 |
| [cdk/](cdk/) | AWS CDK v2 (TypeScript) | Infrastructure for everything above |

Fork-specific state to be aware of:
- [cdk/config.app.json](cdk/config.app.json) is the single source of deployment params (`pipelineName: "bnddevs"` → stack `bnddevs-BedrockChatStack`, OIDC identity provider `iam-oidc`, brand colors). [cdk/parameter.ts](cdk/parameter.ts) just loads it into the CDK parameter map.
- [version.txt](version.txt) + [CHANGELOG.md](CHANGELOG.md) drive the internal release pipeline ([buildspec.yml](buildspec.yml) publishes the zip and updates `houndoc_component_master`/`houndoc_product_master` DynamoDB tables — only for non-`-dev.N` versions).
- Branching is git-flow: work lands on `develop`, releases merge to `main`. Upstream syncs come through `update/chore/upstream`.
- [DESARROLLO_LOCAL.md](DESARROLLO_LOCAL.md) (Spanish) is the authoritative, verified local-dev guide for this fork; [README.md](README.md) is the upstream-derived doc.

## Commands

### Backend

The system-wide Poetry (1.1.12) is too old for `package-mode = false`. Always use the Poetry/Python inside `backend/.venv`.

```sh
cd backend
source .venv/bin/activate                    # or call .venv/bin/<tool> directly

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000   # Swagger at /docs, health at /health
python -m pytest                                            # all tests (run from backend/)
python -m pytest tests/test_strands_integration/test_chat_strands.py -q   # single file
python -m pytest tests/test_strands_integration/test_chat_strands.py::TestX::test_y  # single test
mypy --config-file mypy.ini .                # CI gate
black .                                      # CI gate (--check in CI)
```

Tests are `unittest`-style classes run under pytest. **Many of them (`tests/test_repositories/*`, `tests/test_bedrock.py`) are integration tests that hit real DynamoDB/Bedrock** and need the env vars below plus valid AWS credentials. `tests/test_strands_integration/*` and `tests/test_utils/*` are mocked and run offline.

### Frontend

```sh
cd frontend
npm ci
npm run dev            # Vite on :5173
npm run build          # tsc && vite build
npm run lint           # eslint, --max-warnings 0 (CI gate)
npm run test           # vitest (watch); `npx vitest run <path>` for a single file
npm run ladle          # component sandbox
```

### CDK

```sh
cd cdk
npm ci
npx cdk deploy --all -c envName=bnddevs     # envName must match config.app.json pipelineName
npx cdk diff --all -c envName=bnddevs
npm run test                                 # jest snapshot/assertion tests in cdk/test
```

### Pre-commit

[lefthook.yml](lefthook.yml) runs `black` + `mypy` on staged backend files and `prettier` + `eslint --fix --max-warnings=0` on staged frontend files.

## Local development model

**There is no offline mode.** DynamoDB, S3, Cognito, OpenSearch and Bedrock are always the real resources of a deployed stack; only the code runs locally. Running the backend locally consumes real Bedrock tokens.

Config values come from CloudFormation outputs of `bnddevs-BedrockChatStack` (output keys carry CDK-generated suffixes, so match by prefix). See [DESARROLLO_LOCAL.md](DESARROLLO_LOCAL.md) §4 for the generator script and §10 for the full env-var table.

Three modes, and the traps in each:

- **Frontend local → deployed backend** (default for UI work): the only mode with real streaming. `VITE_APP_COGNITO_DOMAIN` must be set **without** `https://`. `http://localhost:5173/` must be registered in the Cognito app client callback/logout URLs — the `update-user-pool-client` call *replaces* the whole list, so always include the production URL.
- **Backend local only** (Swagger): with no `Authorization` header, [main.py](backend/app/main.py) injects a mock user `test_user` outside Lambda, so you will not see real users' data. Paste a real JWT into Swagger's *Authorize* instead of editing the mock.
- **Both local**: set `VITE_APP_USE_STREAMING="false"`. Streaming goes over an API Gateway WebSocket that does not exist locally ([usePostMessageStreaming.ts](frontend/src/hooks/usePostMessageStreaming.ts)); with the flag off, [useChat.ts](frontend/src/hooks/useChat.ts) falls back to synchronous `POST /conversation`. Vite reads `.env` only at startup — restart after edits.

Notable backend env flags: `USE_STRANDS` (default `true`), `PUBLISHED_API_ID` (switches the app into published-API mode), `LOCAL_SYNC_MODE=true` (bypass SQS in published-API mode), `CORS_ALLOW_ORIGINS`, `ENABLE_BEDROCK_CROSS_REGION_INFERENCE`.

## Architecture

### Request paths

There are three entry points into the same `usecases/chat.py::chat()`:

1. **REST** — API Gateway → Lambda container running `app.main:app` (FastAPI). Routers in [backend/app/routes/](backend/app/routes/) are registered without a prefix; each route declares its full path (`/conversation*`, `/bot*`, `/store/*`, `/admin/*`, `/user/*`, `/config/global`, `/health`).
2. **WebSocket streaming** — the frontend chunks the payload (32 KB) with the Cognito ID token and sends it over the API Gateway WebSocket; [backend/app/websocket.py](backend/app/websocket.py) is a **separate Lambda handler** (not FastAPI) that reassembles chunks, verifies the token, calls `chat()` with `on_stream`/`on_thinking` callbacks, and pushes deltas back through a sender thread.
3. **Published API** — when `PUBLISHED_API_ID` is set, [main.py](backend/app/main.py) exposes only `/published_api/*` with no user auth. Requests normally go onto SQS and are drained by [sqs_consumer.py](backend/app/sqs_consumer.py); `LOCAL_SYNC_MODE=true` calls `chat()` inline instead. Each published API is its own CloudFormation stack (`ApiPublishmentStack*`) created at runtime by a CodeBuild project.

### Backend layering

`routes/` (FastAPI + Pydantic schemas) → `usecases/` (orchestration) → `repositories/` (DynamoDB/OpenSearch access) → `repositories/models/` (persistence models).

- API contract is **camelCase**: [routes/schemas/base.py](backend/app/routes/schemas/base.py) applies `humps.camelize` as the Pydantic alias generator. Python code stays snake_case; the frontend `@types` mirror the camelCase shape.
- `routes/schemas/*` (wire format) and `repositories/models/*` (stored format) are deliberately distinct — a field change usually touches both.
- DynamoDB is single-table with composite keys built in [repositories/common.py](backend/app/repositories/common.py) (`{user_id}#CONV#{id}`, `BOT#{bot_id}`, …). The `user_id` prefix exists for **row-level security**: inside Lambda the code assumes `TABLE_ACCESS_ROLE_ARN` with an inline `LeadingKeys` policy. Outside Lambda (`AWS_EXECUTION_ENV` unset) that assume-role is skipped, so local credentials need direct table permissions.

### Agent / LLM layer (Strands)

`chat()` dispatches on `USE_STRANDS` (default `true`) to [strands_integration/chat_strands.py](backend/app/strands_integration/chat_strands.py); `converse_legacy()` in [usecases/chat.py](backend/app/usecases/chat.py) is the deprecated path kept for fallback.

- [strands_integration/agent/factory.py](backend/app/strands_integration/agent/factory.py) builds the `strands.Agent`: it resolves tools **first**, then derives the `BedrockModel` config from the actual tool list (model capability checks must reflect what is really sent to Bedrock).
- `get_strands_tools()` in [strands_integration/utils.py](backend/app/strands_integration/utils.py) filters registered tools by the names in `bot.agent.tools`, then appends the knowledge-base tool if the bot has knowledge.
- **Tools exist twice**: [app/agents/tools/](backend/app/agents/tools/) (legacy) and [app/strands_integration/tools/](backend/app/strands_integration/tools/) (current — `internet_search`, `knowledge_search`, `calculator`, `bedrock_agent`, `simple_list`). New tools go in the Strands directory.
- `converters/` translate between the repo's `SimpleMessageModel`/`MessageModel` and Strands message types; `text_sanitizer.py` strips internal agent tags (e.g. `<thinking>`) before display. `handlers/` carry the streaming callback handler and tool-result capture; `observability.py` composes handlers to feed the Kinesis observability stream configured in `config.app.json`.

### Knowledge bases and bot sync

Bot knowledge changes set `SyncStatus=QUEUED` on the bot item; the Embedding Step Functions state machine ([cdk/lib/constructs/embedding.ts](cdk/lib/constructs/embedding.ts), handlers in [backend/embedding_statemachine/](backend/embedding_statemachine/)) then drives a CodeBuild project that deploys a **per-bot CDK stack** (`BrChatKbStack*`) containing the Bedrock Knowledge Base. Multi-tenant bots instead attach a tenant to a shared KB (`BedrockKnowledgeBase.type='shared'`), filtered by Bot ID metadata. Bot-store search runs on OpenSearch Serverless ([repositories/bot_store.py](backend/app/repositories/bot_store.py), [cdk/lib/constructs/bot-store.ts](cdk/lib/constructs/bot-store.ts)).

### Frontend

- [src/features/](frontend/src/features/) holds upstream feature modules (`agent`, `discover`, `knowledgeBase`, `reasoning`, `helper`), each with its own `components/hooks/types`.
- [src/custom-components/](frontend/src/custom-components/) is **fork-only** code in atoms/molecules/organisms form (`nadia-title`, `logo-container`, `review-answers`, `feedback-dialog`, plus hooks for custom URLs, redirect persistence and storage cleanup). Keep fork customizations here so upstream merges stay clean.
- State: `zustand` stores for cross-cutting state, SWR (via [useHttp.ts](frontend/src/hooks/useHttp.ts), axios with a Cognito ID-token interceptor) for server data, XState ([src/hooks/xstates/](frontend/src/hooks/xstates/)) for the streaming state machine.
- i18n covers 16 locales under [src/i18n/](frontend/src/i18n/); `en` and `es` are the ones that matter for this fork, but a new key missing from a locale falls back rather than failing loudly.

### Adding a Bedrock model

Model identity is duplicated on both sides: `type_model_name` (Literal) in [backend/app/routes/schemas/conversation.py](backend/app/routes/schemas/conversation.py), the ID/pricing/capability maps in [backend/app/bedrock.py](backend/app/bedrock.py), and the model list in [frontend/src/constants/index.ts](frontend/src/constants/index.ts). All three must agree, and the model must be enabled in the Bedrock console for the deployment region.
