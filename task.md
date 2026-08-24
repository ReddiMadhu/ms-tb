# Task Tracker: Wire Pipeline Agents

## Phase 1: Core Pipeline → Produce .twbx

- `[x]` Step 1.1: Install missing Python packages (`tableauhyperapi`, `tableauserverclient`, `langchain-openai`, `pandas`)
- `[x]` Step 1.2: Wire SemanticAgent (Stage 3)
- `[x]` Step 1.3: Wire IRCompilerAgent + Dedup (Stages 4-5)
- `[x]` Step 1.4: Wire AITranslationAgent (Stage 6)
- `[x]` Step 1.5: Wire VisualizationAgent (Stage 7)
- `[x]` Step 1.6: Wire HyperBuilderAgent (Stage 8)
- `[x]` Step 1.7: Wire TableauEmitterAgent (Stages 9, 10, 15)
- `[x]` Step 1.8: Add download endpoint + UI button

## Phase 2: Validation & Publishing

- `[x]` Step 2.1: Wire ValidationAgent (Stages 12-14)
- `[x]` Step 2.2: Wire PublishAgent (Stages 11, 16, 17)

## Phase 3: Report & Review

- `[x]` Step 3.1: Implement Report generation in orchestrator (Stage 18)
- `[x]` Step 3.2: Verify full test suite (10/10 tests passing) & e2e test


Based on the source code verification of the backend (FastAPI/Python) and frontend (React/Vite), here are the verified answers and technical code descriptions for **Section 9 (API Security)** and **Section 10 (Mobile Security)**.

---

### 9. API Security

| Sl. # | Question | Answer | Description & Code Verification |
| :--- | :--- | :--- | :--- |
| **1** | Is rate limiting implemented on each API endpoint? | **Yes** | Global rate limiting is configured via `slowapi` in [`backend/auth/rate_limiter.py`](file:///c:/Users/madhu/Desktop/rsli/backend/auth/rate_limiter.py#L25-L44) with `DEFAULT_RATE_LIMIT = "60/minute"`. Specialized stricter limits are applied across routes: `AUTH_RATE_LIMIT = "5/minute"` ([`/api/auth/login`](file:///c:/Users/madhu/Desktop/rsli/backend/main.py#L341)), `UPLOAD_RATE_LIMIT = "10/minute"` ([`/api/analyze`](file:///c:/Users/madhu/Desktop/rsli/backend/main.py#L758), [`/api/execute`](file:///c:/Users/madhu/Desktop/rsli/backend/main.py#L963)), and `ADMIN_RATE_LIMIT = "30/minute"` ([`/api/admin/...`](file:///c:/Users/madhu/Desktop/rsli/backend/main.py#L432)). |
| **2** | Is user submitted data validated before it is executed by your API functions? | **Yes** | User inputs are strictly validated through allowlist sanitizers in [`backend/auth/input_validator.py`](file:///c:/Users/madhu/Desktop/rsli/backend/auth/input_validator.py) and Pydantic request models in [`backend/main.py`](file:///c:/Users/madhu/Desktop/rsli/backend/main.py#L75-L229). Python scripts undergo AST syntax checks ([`validate_python_code()`](file:///c:/Users/madhu/Desktop/rsli/backend/main.py#L243-L282)) and security inspection via [`RiskClassifier`](file:///c:/Users/madhu/Desktop/rsli/backend/validator/risk_classifier.py#L9-L58) to block unsafe calls (`subprocess`, `os.system`, `eval`, `exec`). |
| **3** | Is size limit implemented for submitted strings and arrays? | **Yes** | Multiple size limits are enforced:<br>• Request body maximum size capped to 10 MB and query strings capped to 2048 chars in [`RequestSizeLimitMiddleware`](file:///c:/Users/madhu/Desktop/rsli/backend/auth/rate_limiter.py#L69-L119).<br>• Source code capped to 500,000 characters (`MAX_CODE_LENGTH`) in [`input_validator.py:52`](file:///c:/Users/madhu/Desktop/rsli/backend/auth/input_validator.py#L52).<br>• Pydantic schemas enforce field bounds (e.g. `username: max_length=50`, `password: max_length=128`, `trace_nodes: max_length=500`).<br>• Upload file size capped to 50 MB in [`_save_uploads()`](file:///c:/Users/madhu/Desktop/rsli/backend/main.py#L875-L909).<br>• Pagination capped to `page_size <= 100` in [`validate_pagination()`](file:///c:/Users/madhu/Desktop/rsli/backend/auth/input_validator.py#L221-L230). |
| **4** | Is default permission for all users for all resources is "deny access"? | **Yes** | Protected routes enforce explicit dependency injection via [`get_current_user`](file:///c:/Users/madhu/Desktop/rsli/backend/auth/middleware.py#L21-L47) (returns HTTP 401 Unauthorized for unauthenticated requests) and [`require_admin`](file:///c:/Users/madhu/Desktop/rsli/backend/auth/middleware.py#L49-L54) (returns HTTP 403 Forbidden for non-admin users). Only onboarding/login endpoints (`/login`, `/register`, `/validate-password`) and `/health` are open. |
| **5** | Is CORS Policy set for APIs that are publicly accessible from browser-based clients? | **Yes** | Strict CORS policy is configured in [`backend/main.py:139-151`](file:///c:/Users/madhu/Desktop/rsli/backend/main.py#L139-L151) using `CORSMiddleware`. Allowed origins default to local dev URLs (`http://localhost:5173`) and are explicitly restricted in production via the `RSLI_CORS_ORIGINS` environment variable with credentials allowed (`allow_credentials=True`). |
| **6** | What Standards are used for the authentication process? For e.g. like OAuth and JWT. | **JWT (RFC 7519)** | Standards-compliant **JSON Web Tokens (JWT - RFC 7519)** signed using `HS256` HMAC-SHA256 with user claims (`sub`, `user_id`, `is_admin`, `iat`, `exp`) generated in [`create_token()`](file:///c:/Users/madhu/Desktop/rsli/backend/auth/service.py#L103-L114) and transmitted via `HttpOnly`, `SameSite=Lax` cookies. |
| **7** | Are all API endpoints authenticated? | **Yes** | All operational, lineage analysis, script execution, file download, audit trail, and user management endpoints require valid authentication (`get_current_user` / `require_admin`). Only public onboarding (`/api/auth/login`, `/api/auth/register`, `/api/auth/validate-password`) and `/api/health` are unauthenticated. |
| **8** | Does your application use a single static API key for authentication across different instances or users, or does it implement a more dynamic, individualized key system for each user or instance? | **Dynamic, individualized key system** | Authentication uses dynamic, user-specific JWT session tokens signed with a server secret (`RSLI_SECRET_KEY`) containing individual user IDs and privilege claims ([`backend/auth/service.py`](file:///c:/Users/madhu/Desktop/rsli/backend/auth/service.py#L103-L122)). No static shared API keys are used. |
| **9** | Is Applications and programming interfaces (APIs) designed, developed, deployed, and tested in accordance with leading industry standards? | **Yes** | Built with OpenAPI (FastAPI), OWASP Secure Headers ([`backend/auth/security_headers.py`](file:///c:/Users/madhu/Desktop/rsli/backend/auth/security_headers.py)), OWASP input allowlisting ([`backend/auth/input_validator.py`](file:///c:/Users/madhu/Desktop/rsli/backend/auth/input_validator.py)), TLS 1.2/1.3 forward secrecy ([`backend/auth/ssl_config.py`](file:///c:/Users/madhu/Desktop/rsli/backend/auth/ssl_config.py)), rate limiting ([`backend/auth/rate_limiter.py`](file:///c:/Users/madhu/Desktop/rsli/backend/auth/rate_limiter.py)), and automated unit/integration test suites. |

---

### 10. Mobile Security

> **Note**: ETLPulse.AI / RSLI is a **web-based SaaS application** (FastAPI + React Vite). It does not distribute a standalone mobile application (iOS/Android). Mobile-specific checklist items are marked **NA (No mobile application)**, with corresponding web security measures described where applicable.

| Sl. # | Question | Answer | Description & Code Verification |
| :--- | :--- | :--- | :--- |
| **1** | If applicable, JavaScript is enabled in WebView's? | **NA** | No mobile application / WebView. Web application runs standard browser JavaScript with CSP restrictions (`Content-Security-Policy: default-src 'self' ...`) in [`backend/auth/security_headers.py:68-80`](file:///c:/Users/madhu/Desktop/rsli/backend/auth/security_headers.py#L68-L80). |
| **2** | If applicable, Any sensitive data is written application logs stored in device? | **NA / No** | No mobile device storage. Server-side logs sanitize PII and exclude sensitive password credentials ([`LLMDataSanitizer`](file:///c:/Users/madhu/Desktop/rsli/backend/validator/pii_masker.py), [`User.to_dict()`](file:///c:/Users/madhu/Desktop/rsli/backend/database/models.py#L31-L44)). |
| **3** | Is keyboard cache disabled on text inputs that process sensitive data? | **NA** | No mobile application. Web forms use `type="password"` input fields. |
| **4** | If Applicable, Does backups include any sensitive data? | **NA** | No mobile backups. Cloud backups are encrypted at rest via Azure Key Vault / Storage Server-Side Encryption. |
| **5** | Are all inputs from external sources and the user are validated and if necessary sanitized including data received via the UI, IPC? | **Yes / NA** | All inputs received by the web API are validated through allowlists in [`input_validator.py`](file:///c:/Users/madhu/Desktop/rsli/backend/auth/input_validator.py) and Pydantic schemas. |
| **6** | If Applicable, Object serialization, if any, is implemented using safe serialization APIs? | **Yes** | API responses and session archives use standard safe JSON serialization (`json.dumps()`) and Pydantic models; no unsafe object deserialization (e.g. `pickle.loads` on user input) is allowed. |
| **7** | If Applicable, Any keys are hardcoded in? | **No** | No API keys, secret keys, or connection strings are hardcoded. All credentials are read from environment variables ([`backend/.env.example`](file:///c:/Users/madhu/Desktop/rsli/backend/.env.example)). |
| **8** | If Applicable, Does a password policy exists and is enforced at the remote endpoint while authenticating username and password? | **Yes** | Remote backend endpoint strictly enforces password complexity rules in [`validate_password_strength()`](file:///c:/Users/madhu/Desktop/rsli/backend/auth/service.py#L50-L75) (min 8 chars, uppercase, lowercase, number, special char, history check). |
| **9** | If Applicable, The app is signed and provisioned with valid certificate? | **NA / Yes** | No mobile binary. Web service is served over TLS 1.2+ with valid SSL/TLS certificates configured in [`backend/auth/ssl_config.py`](file:///c:/Users/madhu/Desktop/rsli/backend/auth/ssl_config.py). |
| **10** | If Applicable, The app catches and handles possible exceptions? | **Yes** | Robust exception handling is implemented across all API endpoints with structured JSON error responses in [`backend/main.py`](file:///c:/Users/madhu/Desktop/rsli/backend/main.py). |
| **11** | If Applicable, The app build is in release mode or debug mode? | **Release (Production)** | Production deployments run in release mode (`RSLI_RELOAD=false` in [`backend/.env.example:70`](file:///c:/Users/madhu/Desktop/rsli/backend/.env.example#L70), Vite production bundle in frontend `dist/`). |
| **12** | Are all inputs from external sources and the user are validated and if necessary sanitized including data received via the UI, IPC? | **Yes** | Centralized sanitization (`sanitize_string`, `strip_control_chars`, `validate_filename`, `validate_code_input`) in [`backend/auth/input_validator.py`](file:///c:/Users/madhu/Desktop/rsli/backend/auth/input_validator.py). |
| **13** | If applicable, Biometric authentication, if any, is not event-bound or Keystore based? | **NA** | No mobile biometric authentication implemented. |
| **14** | Does the app verifies the X.509 certificate of the remote endpoint when the secure channel is established? | **Yes** | Remote HTTPS calls and Azure Blob storage clients verify valid X.509 certificates. Optional mutual TLS client verification is supported via `RSLI_SSL_CA_CERTS` in [`backend/auth/ssl_config.py:132-136`](file:///c:/Users/madhu/Desktop/rsli/backend/auth/ssl_config.py#L132-L136). |
| **15** | If Applicable, Does the app uses MFA? | **NA / No** | No mobile app MFA. Cloud infrastructure and hosting environments require Azure Active Directory / IAM MFA. |
| **16** | If applicable, can the mobile application detect rooted/jailbroken devices? | **NA** | No mobile application. |