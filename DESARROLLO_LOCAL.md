# Guía de Ejecución Local — Nadia

Guía práctica para levantar el proyecto en tu máquina y desarrollar contra el stack ya desplegado en AWS.

> Esta guía es el camino corto y verificado contra el código actual (v4.5.3).

---

## Índice

- [1. Cómo funciona el "local"](#1-cómo-funciona-el-local)
- [2. Requisitos](#2-requisitos)
- [3. Credenciales AWS](#3-credenciales-aws)
- [4. Obtener la configuración del stack](#4-obtener-la-configuración-del-stack)
- [5. Modo A — Solo frontend (el más simple)](#5-modo-a--solo-frontend-el-más-simple)
- [6. Modo B — Solo backend (Swagger)](#6-modo-b--solo-backend-swagger)
- [7. Modo C — Frontend + backend local](#7-modo-c--frontend--backend-local)
- [8. Autenticación en local](#8-autenticación-en-local)
- [9. Modo API publicada](#9-modo-api-publicada)
- [10. Referencia de variables de entorno](#10-referencia-de-variables-de-entorno)
- [11. Troubleshooting](#11-troubleshooting)
- [12. Higiene antes de commitear](#12-higiene-antes-de-commitear)

---

## 1. Cómo funciona el "local"

**No existe un modo 100% offline.** No se emula AWS: DynamoDB, S3, Cognito, OpenSearch y Bedrock siempre son los recursos **reales** del stack desplegado (`bnddevs-BedrockChatStack` u otro ambiente). Lo que corres en local es únicamente el código:

```
┌─────────────────────┐        ┌──────────────────────┐
│ Frontend (Vite)     │        │  AWS (stack CDK)     │
│ localhost:5173      │───────▶│  DynamoDB, S3,       │
│                     │        │  Cognito, Bedrock,   │
│ Backend (FastAPI)   │───────▶│  OpenSearch, SFN     │
│ localhost:8000      │        └──────────────────────┘
└─────────────────────┘
```

Hay tres modos de trabajo según lo que estés tocando:

| Modo | Frontend | Backend | Cuándo usarlo |
| --- | --- | --- | --- |
| **A** | local | AWS (API Gateway) | Cambios solo de UI. Es el modo con menos fricción y el único con streaming real. |
| **B** | — | local | Cambios solo de backend. Se prueba desde Swagger (`/docs`). |
| **C** | local | local | Cambios que tocan ambos lados. Requiere desactivar streaming. |

**Ojo con Bedrock:** cualquier modo que ejecute el backend en local consume tokens reales de Bedrock con tus credenciales.

---

## 2. Requisitos

Estado verificado en esta máquina (29/07/2026):

| Herramienta | Requerido | Detectado | Nota |
| --- | --- | --- | --- |
| Node.js | 18+ | v22.22.0 ✅ | |
| npm | — | 10.9.4 ✅ | |
| Python | 3.13 (`pyproject.toml`) | `/usr/bin/python3.13` ✅ | |
| AWS CLI | v2 | 2.29.0 ✅ | |
| Poetry (sistema) | 1.8+ | **1.1.12 ⚠️** | Demasiado antiguo: no entiende `package-mode = false`. Usa el Poetry del venv (ver abajo). |

El `backend/.venv` que ya existe corre **Python 3.12.0** con las dependencias instaladas y funcionando, e incluye su propio `poetry` y `uvicorn`. Mientras uses ese venv **no necesitas tocar `pyproject.toml`** (el viejo consejo de bajar `^3.13.0` → `^3.12.0` ya no aplica).

### Si necesitas recrear el venv desde cero

```bash
cd backend/
rm -rf .venv
/usr/bin/python3.13 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip poetry     # instala Poetry moderno DENTRO del venv
poetry install
```

A partir de aquí, en el backend siempre usa `.venv/bin/poetry` o activa el venv primero — nunca el `poetry` global 1.1.12.

---

## 3. Credenciales AWS

En local, el backend **no asume el rol `TABLE_ACCESS_ROLE_ARN`**: ese `sts:AssumeRole` solo ocurre dentro de Lambda ([common.py:86](backend/app/repositories/common.py#L86)). Fuera de Lambda, boto3 usa tus credenciales tal cual, así que **tu usuario/rol necesita permisos directos** sobre DynamoDB, S3, Bedrock, Cognito y OpenSearch.

Opciones, de mejor a peor:

```bash
# Recomendado: SSO (se renueva solo con un comando)
aws sso login --profile <tu-perfil>
export AWS_PROFILE=<tu-perfil>

# Alternativa: credenciales temporales exportadas a mano (expiran en ~1-12h)
export AWS_ACCESS_KEY_ID="..."
export AWS_SECRET_ACCESS_KEY="..."
export AWS_SESSION_TOKEN="..."
```

Verifica siempre antes de arrancar:

```bash
aws sts get-caller-identity
```

> ⚠️ **Nunca pegues credenciales en `launch.json`, en archivos versionados, ni las compartas por chat.** Si lo hiciste, invalida la sesión y renueva. Prefiere `AWS_PROFILE` para que el proceso local herede las credenciales sin escribirlas en ningún archivo.

---

## 4. Obtener la configuración del stack

Todos los valores salen de los **Outputs de CloudFormation**. El ambiente actual está definido en [cdk/config.app.json](cdk/config.app.json) → `pipelineName: "bnddevs"`, por lo que el stack es `bnddevs-BedrockChatStack`.

### Ver los outputs

```bash
aws cloudformation describe-stacks \
  --stack-name bnddevs-BedrockChatStack \
  --query 'Stacks[0].Outputs' --output table
```

### Generar los archivos de entorno automáticamente

Este script lee los outputs y escribe `backend/.env.backend` y `frontend/.env.local`. Guárdalo como `scripts/gen-local-env.sh` y ejecútalo desde la raíz:

```bash
#!/usr/bin/env bash
set -euo pipefail

STACK="${1:-bnddevs-BedrockChatStack}"
REGION="${AWS_REGION:-us-east-1}"

get() {
  aws cloudformation describe-stacks --stack-name "$STACK" --region "$REGION" \
    --query "Stacks[0].Outputs[?starts_with(OutputKey,'$1')].OutputValue | [0]" \
    --output text
}

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
CONV_TABLE=$(get ConversationTableNameV3)
BOT_TABLE=$(get BotTableNameV3)
USER_POOL_ID=$(get AuthUserPoolId)
CLIENT_ID=$(get AuthUserPoolClientId)
DOC_BUCKET=$(get DocumentBucketName)
LARGE_BUCKET=$(get LargeMessageBucketName)
ROLE_ARN=$(get TableAccessRoleArn)
OS_ENDPOINT=$(get BotStoreOpenSearchEndpoint)
SFN_ARN=$(get EmbeddingStateMachineArn)
API_URL=$(get BackendApiBackendApiUrl)
WS_URL=$(get WebSocketWebSocketEndpoint)
COGNITO_DOMAIN=$(get FrontendCognitoDomain)

cat > backend/.env.backend <<EOF
export CONVERSATION_TABLE_NAME="${CONV_TABLE}"
export BOT_TABLE_NAME="${BOT_TABLE}"
export ACCOUNT="${ACCOUNT_ID}"
export REGION="${REGION}"
export BEDROCK_REGION="${REGION}"
export USER_POOL_ID="${USER_POOL_ID}"
export CLIENT_ID="${CLIENT_ID}"
export DOCUMENT_BUCKET="${DOC_BUCKET}"
export LARGE_MESSAGE_BUCKET="${LARGE_BUCKET}"
export TABLE_ACCESS_ROLE_ARN="${ROLE_ARN}"
export OPENSEARCH_DOMAIN_ENDPOINT="${OS_ENDPOINT}"
export EMBEDDING_STATE_MACHINE_ARN="${SFN_ARN}"
export CORS_ALLOW_ORIGINS="http://localhost:5173"
export ENABLE_BEDROCK_CROSS_REGION_INFERENCE="true"
export USE_STRANDS="true"
EOF

cat > frontend/.env.local <<EOF
VITE_APP_API_ENDPOINT="${API_URL}"
VITE_APP_WS_ENDPOINT="${WS_URL}"
VITE_APP_USER_POOL_ID="${USER_POOL_ID}"
VITE_APP_USER_POOL_CLIENT_ID="${CLIENT_ID}"
VITE_APP_REGION="${REGION}"
VITE_APP_REDIRECT_SIGNIN_URL="http://localhost:5173/"
VITE_APP_REDIRECT_SIGNOUT_URL="http://localhost:5173/"
VITE_APP_COGNITO_DOMAIN="${COGNITO_DOMAIN#https://}"
VITE_APP_USE_STREAMING="true"
VITE_APP_SOCIAL_PROVIDERS=""
VITE_APP_CUSTOM_PROVIDER_ENABLED="true"
VITE_APP_CUSTOM_PROVIDER_NAME="iam-oidc"
EOF

echo "OK -> backend/.env.backend y frontend/.env.local"
```

```bash
chmod +x scripts/gen-local-env.sh
./scripts/gen-local-env.sh bnddevs-BedrockChatStack
```

Los nombres de output llevan sufijos autogenerados por CDK (p. ej. `AuthUserPoolIdC0605E59`), por eso el script busca por prefijo con `starts_with`.

---

## 5. Modo A — Solo frontend (el más simple)

El frontend local apunta al backend ya desplegado. Es el modo recomendado para trabajar UI.

### 5.1 Instalar

```bash
cd frontend/
npm install
```

### 5.2 Configurar

Usa el `frontend/.env.local` generado en el paso 4 (o copia `frontend/.env.template`). Punto crítico: **`VITE_APP_COGNITO_DOMAIN` va sin `https://`** — solo el dominio.

### 5.3 Registrar localhost en Cognito (solo la primera vez)

Cognito rechaza redirecciones a URLs no registradas. Añade `http://localhost:5173/` **conservando** las URLs de producción:

```bash
aws cognito-idp update-user-pool-client \
  --user-pool-id <USER_POOL_ID> \
  --client-id <CLIENT_ID> \
  --callback-urls "https://nadia.devs.ia.blend360.com/" "http://localhost:5173/" \
  --logout-urls "https://nadia.devs.ia.blend360.com/" "http://localhost:5173/" \
  --supported-identity-providers "iam-oidc" "COGNITO" \
  --allowed-o-auth-flows code \
  --allowed-o-auth-scopes openid email \
  --allowed-o-auth-flows-user-pool-client \
  --region us-east-1
```

> Este comando **reemplaza** las listas completas: si omites la URL de producción, rompes el login del ambiente desplegado para todos. Lista primero las actuales con `aws cognito-idp describe-user-pool-client`.

En Keycloak, añade además el `ApprovedRedirectURI` del stack a **Valid redirect URIs** del cliente.

### 5.4 Arrancar

```bash
npm run dev
```

→ http://localhost:5173/

---

## 6. Modo B — Solo backend (Swagger)

### 6.1 Arrancar

```bash
cd backend/
source .venv/bin/activate
source .env.backend          # el generado en el paso 4
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

→ Swagger en http://localhost:8000/docs · health en http://localhost:8000/health

### 6.2 Depurar desde VSCode

`.vscode/launch.json` (ya está en `.gitignore`):

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Backend: FastAPI Local",
      "type": "debugpy",
      "request": "launch",
      "module": "uvicorn",
      "args": ["app.main:app", "--reload", "--host", "0.0.0.0", "--port", "8000"],
      "envFile": "${workspaceFolder}/backend/.env.debug",
      "env": { "AWS_PROFILE": "<tu-perfil-sso>" },
      "console": "integratedTerminal",
      "python": "${workspaceFolder}/backend/.venv/bin/python",
      "cwd": "${workspaceFolder}/backend"
    }
  ]
}
```

`envFile` usa formato `CLAVE=valor` **sin** `export`, así que crea `backend/.env.debug` a partir de `.env.backend`:

```bash
sed 's/^export //' backend/.env.backend > backend/.env.debug
```

Usar `AWS_PROFILE` en lugar de pegar las tres variables `AWS_*` evita dejar credenciales escritas en disco.

---

## 7. Modo C — Frontend + backend local

### Terminal 1 — backend

```bash
cd backend/
source .venv/bin/activate
source .env.backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Terminal 2 — frontend

Ajusta `frontend/.env.local`:

```bash
VITE_APP_API_ENDPOINT="http://localhost:8000"
VITE_APP_USE_STREAMING="false"     # ← obligatorio
VITE_APP_WS_ENDPOINT=""
```

```bash
cd frontend/
npm run dev
```

**Por qué `VITE_APP_USE_STREAMING="false"`:** el streaming del frontend viaja por WebSocket de API Gateway ([usePostMessageStreaming.ts:8](frontend/src/hooks/usePostMessageStreaming.ts#L8)), y ese WebSocket **no existe en local** — el handler de [backend/app/websocket.py](backend/app/websocket.py) solo corre como Lambda. Con la bandera en `false`, [useChat.ts:477](frontend/src/hooks/useChat.ts#L477) cae al `POST /conversation` síncrono, que sí sirve el backend local. La respuesta llega completa de una vez, sin efecto de escritura progresiva.

Vite no recarga los `.env` en caliente: reinicia `npm run dev` tras cada cambio.

---

## 8. Autenticación en local

El middleware [main.py:105-133](backend/app/main.py#L105-L133) se comporta distinto fuera de Lambda:

- **Con** header `Authorization: Bearer <jwt>` → valida el token real contra Cognito (esto pasa en Modo C, porque el frontend sí envía el JWT).
- **Sin** header → inyecta un usuario mock:

```python
request.state.current_user = User(
    id="test_user", name="test_user", email="user@example.com", groups=[]
)
```

Consecuencia práctica: llamando a Swagger sin token, todo se guarda bajo el usuario `test_user` y **no verás las conversaciones de tu usuario real**. Para trabajar con datos reales desde Swagger tienes dos caminos:

1. **Pegar un JWT real** en el botón *Authorize* de Swagger (cópialo del `localStorage` / DevTools con el frontend logueado). Es lo recomendado: no toca código.
2. **Cambiar el `id` mock** en [main.py:127](backend/app/main.py#L127) por tu `sub` de Cognito (p. ej. `64b8f498-6031-7002-7574-2683f4532c2a`), que sacas de la consola de Cognito o de la tabla de conversaciones en DynamoDB. **Revierte este cambio antes de commitear.**

---

## 9. Modo API publicada

Si defines `PUBLISHED_API_ID`, el backend arranca en modo API publicada ([main.py:33-35](backend/app/main.py#L33-L35)): expone solo `/published_api/*`, sin autenticación de usuario, y asocia todo al bot publicado.

```bash
export PUBLISHED_API_ID="01K25C9XD3227C3SYTMF5NJE6N"
export LOCAL_SYNC_MODE="true"
```

`LOCAL_SYNC_MODE=true` ([published_api.py:24-33](backend/app/routes/published_api.py#L24-L33)) es clave en local: sin ella el endpoint publica el mensaje en **SQS** y espera a que un consumidor lo procese (algo que en local no ocurre, y además exige `QUEUE_URL`). Con la bandera activa se salta SQS y llama a `chat()` directamente, de forma síncrona.

El ID del bot lo obtienes en **Admin → Gestión de API** en la UI, o en DynamoDB buscando items con `SK` que empiece por `BOT#`.

---

## 10. Referencia de variables de entorno

### Backend

| Variable | Obligatoria | Origen / valor |
| --- | --- | --- |
| `CONVERSATION_TABLE_NAME` | ✅ | Output `ConversationTableNameV3` |
| `BOT_TABLE_NAME` | ✅ | Output `BotTableNameV3` |
| `ACCOUNT` | ✅ | `aws sts get-caller-identity --query Account` |
| `REGION` | ✅ | `us-east-1` (por defecto sería `ap-northeast-1`) |
| `BEDROCK_REGION` | ✅ | `us-east-1` |
| `USER_POOL_ID` | ✅ | Output `AuthUserPoolId…` |
| `CLIENT_ID` | ✅ | Output `AuthUserPoolClientId…` |
| `DOCUMENT_BUCKET` | ✅ | Output `DocumentBucketName` |
| `LARGE_MESSAGE_BUCKET` | ✅ | Output `LargeMessageBucketName` |
| `OPENSEARCH_DOMAIN_ENDPOINT` | ✅ | Output `BotStoreOpenSearchEndpoint…` |
| `CORS_ALLOW_ORIGINS` | ✅ (modo C) | `http://localhost:5173` |
| `TABLE_ACCESS_ROLE_ARN` | ➖ | Output `TableAccessRoleArn`. **Ignorado en local**, solo se usa en Lambda. |
| `EMBEDDING_STATE_MACHINE_ARN` | ➖ | Necesaria solo para indexar knowledge bases |
| `ENABLE_BEDROCK_CROSS_REGION_INFERENCE` | ➖ | `true` |
| `ENABLE_BEDROCK_GLOBAL_INFERENCE` | ➖ | Perfiles de inferencia global |
| `USE_STRANDS` | ➖ | Por defecto `true`; `false` usa la implementación legacy (en desuso) |
| `PUBLISHED_API_ID` | ➖ | Activa el modo API publicada (§9) |
| `LOCAL_SYNC_MODE` | ➖ | `true` para saltar SQS en local (§9) |
| `QUEUE_URL` | ➖ | Solo si `LOCAL_SYNC_MODE=false` |
| `DEFAULT_MODEL` / `TITLE_MODEL` | ➖ | Fallback: `claude-v3.7-sonnet` / `claude-v3-haiku` |
| `GLOBAL_AVAILABLE_MODELS` | ➖ | Array JSON de modelos habilitados |
| `USAGE_ANALYSIS_TABLE` | ➖ | Solo para el dashboard de uso (Athena) |
| `ENV_NAME` / `ENV_PREFIX` | ➖ | Prefijo de índices en OpenSearch |
| `DDB_ENDPOINT_URL` | ➖ | Apunta a un DynamoDB Local si algún día lo montas |

### Frontend (`frontend/.env.local`)

| Variable | Nota |
| --- | --- |
| `VITE_APP_API_ENDPOINT` | URL de API Gateway, o `http://localhost:8000` en modo C |
| `VITE_APP_WS_ENDPOINT` | WebSocket del stack; vacío en modo C |
| `VITE_APP_USER_POOL_ID` / `VITE_APP_USER_POOL_CLIENT_ID` | Cognito |
| `VITE_APP_REGION` | `us-east-1` |
| `VITE_APP_REDIRECT_SIGNIN_URL` / `_SIGNOUT_URL` | `http://localhost:5173/` (con `/` final) |
| `VITE_APP_COGNITO_DOMAIN` | **sin** `https://` |
| `VITE_APP_USE_STREAMING` | `true` con backend AWS, `false` con backend local |
| `VITE_APP_CUSTOM_PROVIDER_ENABLED` / `_NAME` | `true` / `iam-oidc` |
| `VITE_APP_SOCIAL_PROVIDERS` | vacío |

---

## 11. Troubleshooting

| Síntoma | Causa | Solución |
| --- | --- | --- |
| URL con `https://https//...` | `VITE_APP_COGNITO_DOMAIN` incluye el protocolo | Deja solo el dominio |
| `redirect_mismatch` | `http://localhost:5173/` no registrado en Cognito | §5.3 |
| `RedirectUri not registered` (Keycloak) | Falta el redirect URI en el cliente | Añade `.../oauth2/idpresponse` |
| El chat se queda "pensando" para siempre en modo C | Streaming activo sin WebSocket local | `VITE_APP_USE_STREAMING="false"` y reinicia Vite |
| Error de CORS desde el navegador | Falta `CORS_ALLOW_ORIGINS` en el backend | `export CORS_ALLOW_ORIGINS="http://localhost:5173"` |
| `InvalidClientTokenId` / `ExpiredToken` | Credenciales expiradas | `aws sso login`, o reexporta las temporales |
| `AccessDeniedException` en DynamoDB | En local no se asume `TABLE_ACCESS_ROLE_ARN` | Tu rol necesita permisos directos sobre las tablas |
| `ResourceNotFoundException: Table not found` | Nombre de tabla mal copiado o región errónea | Revisa `REGION` y los outputs |
| No aparecen tus conversaciones en Swagger | Estás como `test_user` | Envía un JWT real (§8) |
| `poetry install` falla con `package-mode` | Poetry 1.1.12 del sistema | Usa `.venv/bin/poetry` (§2) |
| Cambios en `.env.local` sin efecto | Vite lee los `.env` solo al arrancar | Reinicia `npm run dev` |

---

## 12. Higiene antes de commitear

- `frontend/.env.local` y `.vscode/` ya están ignorados por git — verifícalo igualmente con `git status`.
- Añade `backend/.env.backend` y `backend/.env.debug` a `.gitignore` si los creas (**no** están ignorados hoy).
- Revierte cualquier cambio temporal en [backend/app/main.py](backend/app/main.py) (usuario mock) y en `pyproject.toml`.
- Nunca commitees credenciales AWS, ni siquiera temporales.

---

## Comandos rápidos

```bash
# Frontend
cd frontend/ && npm install && npm run dev              # → :5173

# Backend
cd backend/ && source .venv/bin/activate \
  && source .env.backend \
  && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000   # → :8000/docs

# Regenerar configuración desde CloudFormation
./scripts/gen-local-env.sh bnddevs-BedrockChatStack
```
