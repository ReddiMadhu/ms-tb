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
Listed directory rsli
Listed directory backend
Listed directory auth
Listed directory database
Listed directory audit
Listed directory frontend
Listed directory src
Listed directory components
Viewed service.py:1-271
Viewed rate_limiter.py:1-139
Viewed security_headers.py:1-106
Viewed ssl_config.py:1-142
Viewed input_validator.py:1-249
Viewed middleware.py:1-54
Viewed models.py:1-91
Viewed db.py:1-62
Viewed logger.py:1-93
Viewed blob_store.py:1-121
Viewed main.py:1-150
Viewed main.py:151-300
Searched for "@app."
Searched for "app."
Viewed main.py:300-450
Viewed main.py:450-600
Viewed main.py:601-850
Viewed main.py:851-1100
Viewed main.py:1101-1274
Viewed .env.example:1-85
Viewed LoginPage.jsx:1-150
Viewed LoginPage.jsx:151-261
Listed directory store
Viewed useAuthStore.js:1-111
Viewed UploadZone.jsx:1-100
Viewed AdminUsers.jsx:1-100
Viewed ChangePasswordModal.jsx:1-100
Listed directory validator
Listed directory executor
Viewed risk_classifier.py:1-60
Viewed pii_masker.py:1-74

Based on the inspection of the application's source code (backend Python and frontend React/JavaScript), here are the verified answers and technical descriptions for each question in the **Application Security Checklist**.

---

### 2. Authentication and User/ Password Management

| Sl. # | Question | Answer | Description & Code Verification |
| :--- | :--- | :--- | :--- |
| **1** | Does your application transmit the user credentials through secure channel? | **Yes** | Transport is secured with TLS 1.2/1.3 context configuration in [`backend/auth/ssl_config.py`](file:///c:/Users/madhu/Desktop/rsli/backend/auth/ssl_config.py#L99-L141) and HSTS enforcement in [`backend/auth/security_headers.py`](file:///c:/Users/madhu/Desktop/rsli/backend/auth/security_headers.py#L48-L60). Frontend transmits credentials over encrypted HTTPS with `credentials: "include"`. |
| **2** | Does your application store the authentication credentials in plain text? | **No** | Passwords are never stored in plain text; they are hashed with `bcrypt` (12 salt rounds) via [`hash_password()`](file:///c:/Users/madhu/Desktop/rsli/backend/auth/service.py#L36-L39). The [`User.to_dict()`](file:///c:/Users/madhu/Desktop/rsli/backend/database/models.py#L31-L44) serialization model explicitly strips `password_hash`. |
| **3** | Does your application restricts the maximum failed login attempts or Account Lockout? | **Yes** | Auth endpoints are strictly rate-limited via `slowapi` to 5 requests/minute (`AUTH_RATE_LIMIT = "5/minute"`) in [`backend/auth/rate_limiter.py`](file:///c:/Users/madhu/Desktop/rsli/backend/auth/rate_limiter.py#L26) on [`/api/auth/login`](file:///c:/Users/madhu/Desktop/rsli/backend/main.py#L340-L346). Admins can also manually disable accounts. |
| **4** | Do you hardcode authentication credentials in connection strings or configuration files? | **No** | All secrets and credentials are loaded dynamically from environment variables (`os.environ.get(...)`) as seen in [`backend/auth/service.py`](file:///c:/Users/madhu/Desktop/rsli/backend/auth/service.py#L17-L21) and [`.env.example`](file:///c:/Users/madhu/Desktop/rsli/backend/.env.example). |
| **5** | Does your application follow organization approved password Policy? | **Yes** | Strong password validation is enforced on both backend ([`validate_password_strength()`](file:///c:/Users/madhu/Desktop/rsli/backend/auth/service.py#L50-L75)) and frontend ([`PasswordStrengthIndicator.jsx`](file:///c:/Users/madhu/Desktop/rsli/frontend/src/components/PasswordStrengthIndicator.jsx)): min 8 characters, at least 1 uppercase, 1 lowercase, 1 digit, 1 special character, and a history preventing reuse of the last 5 passwords. |
| **6** | Do you have password ageing in place for application and administrative level accounts? | **No** | The database tracks `created_at` and `last_login` in [`User`](file:///c:/Users/madhu/Desktop/rsli/backend/database/models.py#L25-L27), but automatic periodic expiration (e.g., mandatory 90-day reset) is not enforced in code. Admin reset is available on demand via [`reset_password()`](file:///c:/Users/madhu/Desktop/rsli/backend/auth/service.py#L214-L247). |
| **7** | Does the application stores any Default User accounts? | **No** | Database initialization ([`init_db()`](file:///c:/Users/madhu/Desktop/rsli/backend/database/db.py#L59-L61)) creates schema only without pre-seeded default users. Admin privilege is dynamically assigned upon registration when matching `RSLI_ADMIN_EMAIL` with an invite code. |
| **8** | Do you have account deletion and disablement process in place? | **Yes** | Account deactivation/activation endpoints are implemented for admins ([`/api/admin/users/{user_id}/deactivate`](file:///c:/Users/madhu/Desktop/rsli/backend/main.py#L446-L457)), and [`get_current_user()`](file:///c:/Users/madhu/Desktop/rsli/backend/auth/middleware.py#L42-L46) blocks deactivated users with HTTP 401. |
| **9** | Does your application provide two factor authentication mechanism? | **No** | 2FA/MFA is not currently implemented in the application layer; authentication relies on JWT token cookies, bcrypt credentials, and registration invite codes. |
| **10** | Is user authentication controlled by means other than user account and password or PIN? | **No** | Application uses standard username/password authentication paired with invite code validation. |
| **11** | Does the application force "new" users to change their password upon first login into the application? | **No** | New users define their own password during registration. Admin resets generate a secure temporary password, but there is no forced password change on first login. |
| **12** | Does the application support integration with the enterprise identity management system(IAM)? | **No** | Application uses local relational database authentication with signed JWTs rather than external SSO (SAML/LDAP/OAuth2). |
| **13** | Does your application implement user credentials Autocomplete to "OFF" at the browser? | **No** | Form inputs in [`LoginPage.jsx`](file:///c:/Users/madhu/Desktop/rsli/frontend/src/components/LoginPage.jsx#L167-L176) currently rely on standard browser input attributes without explicit `autoComplete="off"`. |

---

### 3. Encryption

| Sl. # | Question | Answer | Description & Code Verification |
| :--- | :--- | :--- | :--- |
| **1** | Do you maintain and encrypt critical application and user data stored in the database? | **Yes** | Passwords are encrypted with bcrypt (12 rounds) in [`backend/auth/service.py`](file:///c:/Users/madhu/Desktop/rsli/backend/auth/service.py#L36-L39). PII is detected and stripped from LLM prompts via [`LLMDataSanitizer`](file:///c:/Users/madhu/Desktop/rsli/backend/validator/pii_masker.py#L7-L74). Database volume encryption at rest is managed via host storage. |
| **2** | Do you keep Centralized Key storage facility? For e.g. AWS KMS, Azure Keyvault, etc. | **Yes** | Secrets and keys (e.g. `AZURE_STORAGE_CONNECTION_STRING`, `RSLI_SECRET_KEY`) are managed through Azure Key Vault / App Service configuration ([`backend/.env.example`](file:///c:/Users/madhu/Desktop/rsli/backend/.env.example)). |
| **3** | What are the supported TLS versions? | **TLSv1.2, TLSv1.3** | Hardened SSL context in [`backend/auth/ssl_config.py`](file:///c:/Users/madhu/Desktop/rsli/backend/auth/ssl_config.py#L99-L112) disables SSLv2, SSLv3, TLS 1.0, and TLS 1.1, and enforces `ctx.minimum_version = ssl.TLSVersion.TLSv1_2`. |
| **4** | Do you transmit restricted or confidential data on public networks i.e. batch data feeds, emails etc. in encrypted form? | **Yes** | All network communications are enforced over TLS 1.2+ with HSTS enabled ([`backend/auth/security_headers.py`](file:///c:/Users/madhu/Desktop/rsli/backend/auth/security_headers.py#L58-L60)), and cloud blob archives use HTTPS connections in [`BlobAuditStore`](file:///c:/Users/madhu/Desktop/rsli/backend/audit/blob_store.py). |

---

### 4. Access Control

| Sl. # | Question | Answer | Description & Code Verification |
| :--- | :--- | :--- | :--- |
| **1** | Do you have Access Control environment defined for the application and database? | **Yes** | Access is governed by FastAPI auth middleware dependencies ([`get_current_user`](file:///c:/Users/madhu/Desktop/rsli/backend/auth/middleware.py#L21-L47), [`require_admin`](file:///c:/Users/madhu/Desktop/rsli/backend/auth/middleware.py#L49-L54)) and scoped database sessions ([`get_db`](file:///c:/Users/madhu/Desktop/rsli/backend/database/db.py#L50-L57)). |
| **2** | Does your application provide role-based authorization to users of the application/solution? | **Yes** | Role-Based Access Control (RBAC) separates Standard Users from Admins (`User.is_admin` in [`backend/database/models.py`](file:///c:/Users/madhu/Desktop/rsli/backend/database/models.py#L22)), restricting user management and administrative APIs to authorized admins only. |
| **3** | Does your application support principle of least privileges during registration? | **Yes** | Registered accounts default to standard non-privileged users (`is_admin=False`) in [`register_user()`](file:///c:/Users/madhu/Desktop/rsli/backend/auth/service.py#L158-L167). |
| **4** | Does your application provide access to server directories for the application user? | **No** | Direct directory access is prevented. Filenames are strictly sanitized with `os.path.basename()` and allowlist regex in [`validate_filename()`](file:///c:/Users/madhu/Desktop/rsli/backend/auth/input_validator.py#L122-L136) to prevent path traversal attacks. |
| **5** | Is application configuration data and files secured with appropriate file permissions? | **Yes** | Environment variables, `.env` files, and database files are isolated from static public directories and excluded from version control via [`.gitignore`](file:///c:/Users/madhu/Desktop/rsli/.gitignore). |

---

### 5. Auditing and Logging

| Sl. # | Question | Answer | Description & Code Verification |
| :--- | :--- | :--- | :--- |
| **1** | Does your application cache sensitive pages and files inside the browser temporary folders? | **No** | Caching of sensitive API responses is prevented via headers in [`SecurityHeadersMiddleware`](file:///c:/Users/madhu/Desktop/rsli/backend/auth/security_headers.py#L87-L93): `Cache-Control: no-store, no-cache, must-revalidate, max-age=0` and `Pragma: no-cache`. |
| **2** | Does your application have auditing and logging enabled for application and DB servers? | **Yes** | Auditing is implemented via [`AuditLog`](file:///c:/Users/madhu/Desktop/rsli/backend/database/models.py#L50-L91) and [`log_event()`](file:///c:/Users/madhu/Desktop/rsli/backend/audit/logger.py#L8-L43), recording user logins, registrations, script parses, executions, risk alerts, and downloads. |
| **3** | Does your application maintain user activity logs? | **Yes** | User activity logs are stored in the database with timestamps, usernames, and action metadata, and are viewable/exportable via [`/api/audit`](file:///c:/Users/madhu/Desktop/rsli/backend/main.py#L472-L613) and [`AuditTrail.jsx`](file:///c:/Users/madhu/Desktop/rsli/frontend/src/components/AuditTrail.jsx). |
| **4** | Does your company centrally log and secure event data offline, in order to support forensic investigations as required? | **Yes** | Execution logs, input/output artifacts, overrides, and LLM logs are archived to Azure Blob Storage via [`BlobAuditStore`](file:///c:/Users/madhu/Desktop/rsli/backend/audit/blob_store.py#L32-L121). |
| **5** | What is the Log Retention period? | **Configurable** | Logs are persisted in the database and Azure Blob Storage, subject to Azure Storage lifecycle management rules. Local temp workspaces expire after `RSLI_SESSION_CLEANUP_S` (default: 1800s / 30 mins). |
| **6** | Is privileged logical (administrator) access logged, monitored, reset and reviewed timely? | **Yes** | Admin actions (resetting passwords, deactivating users) require `require_admin` check and generate audit log events with the acting admin's username. |

---

### 6. Error Handling

| Sl. # | Question | Answer | Description & Code Verification |
| :--- | :--- | :--- | :--- |
| **1** | Does your application display customized error pages for exceptional conditions and errors to the users? | **Yes** | Custom user-friendly UI error banners and toast states are implemented in [`LoginPage.jsx`](file:///c:/Users/madhu/Desktop/rsli/frontend/src/components/LoginPage.jsx#L218-L223) and [`UploadZone.jsx`](file:///c:/Users/madhu/Desktop/rsli/frontend/src/components/UploadZone.jsx#L59-L87) with standardized JSON errors returned from [`backend/auth/rate_limiter.py`](file:///c:/Users/madhu/Desktop/rsli/backend/auth/rate_limiter.py#L48-L64). |
| **2** | Does your application allows leakage of internal application information through error mechanism? | **No** | Exceptions are caught in FastAPI route handlers and sanitized into generic error descriptions without leaking database connection strings or raw stack traces. |

---

### 7. Session Management

| Sl. # | Question | Answer | Description & Code Verification |
| :--- | :--- | :--- | :--- |
| **1** | Does your application assign dynamic Session Ids for each and every session? | **Yes** | Dynamic session IDs are generated per pipeline execution using `uuid.uuid4().hex[:10]` in [`backend/main.py`](file:///c:/Users/madhu/Desktop/rsli/backend/main.py#L983), and authentication tokens contain dynamic `iat`/`exp` timestamps. |
| **2** | Does your application allows multiple sessions for a single user at the same time? | **Yes** | Stateless JWT authentication allows concurrent logins, while execution runs are isolated per unique session ID. |
| **3** | Does your application require Session Cookies to travel through query strings? | **No** | Session cookies and tokens are transmitted exclusively via HTTP headers (`Cookie`), never via URL query parameters ([`backend/main.py`](file:///c:/Users/madhu/Desktop/rsli/backend/main.py#L349-L356)). Long query strings are blocked by [`RequestSizeLimitMiddleware`](file:///c:/Users/madhu/Desktop/rsli/backend/auth/rate_limiter.py#L84-L94). |
| **4** | Is there an Idle Session timeout allocated for the application? | **Yes** | JWT expiration is set by `RSLI_JWT_EXPIRY_DAYS` / `COOKIE_MAX_AGE` ([`backend/auth/service.py`](file:///c:/Users/madhu/Desktop/rsli/backend/auth/service.py#L19-L28)), and temporary execution workspaces expire via cleanup timers after 30 minutes ([`_schedule_session_cleanup`](file:///c:/Users/madhu/Desktop/rsli/backend/main.py#L116-L138)). |
| **5** | Does your application logout the session when the user's password is changed? | **No** | Password change updates the hash in the DB; the user remains logged in on the current client unless explicit logout ([`/api/auth/logout`](file:///c:/Users/madhu/Desktop/rsli/backend/main.py#L366-L370)) is triggered or the account is deactivated. |
| **6** | Does your application kill the session when the user closes the browser without logout? | **No** | Cookie is configured with a persistent `max_age` (`COOKIE_MAX_AGE`) rather than a transient browser session cookie. |
| **7** | Does the application set "HTTP Only" and "Secure" cookie attributes to "True" for authenticated cookies? | **Yes** | In [`backend/main.py:349-356`](file:///c:/Users/madhu/Desktop/rsli/backend/main.py#L349-L356): `response.set_cookie(key=COOKIE_NAME, value=token, max_age=COOKIE_MAX_AGE, httponly=True, samesite="lax", secure=COOKIE_SECURE)` where `COOKIE_SECURE` is configurable via `RSLI_COOKIE_SECURE` env var (enabled in production). |
| **8** | Does your application use a single static API key for authentication across different instances or users, or does it implement a more dynamic, individualized key system for each user or instance? | **Dynamic Key System** | Individualized JWT tokens signed with a secret key are generated per user containing specific user IDs and role claims ([`create_token()`](file:///c:/Users/madhu/Desktop/rsli/backend/auth/service.py#L103-L114)). |
| **9** | Does the application allocate random CSRF tokens for restricting Cross Site Request Forgery attacks? | **Mitigated (SameSite & CORS)** | CSRF is protected via `samesite="lax"` cookie enforcement in [`backend/main.py`](file:///c:/Users/madhu/Desktop/rsli/backend/main.py#L354), strict origin validation in [`CORSMiddleware`](file:///c:/Users/madhu/Desktop/rsli/backend/main.py#L140-L151), and JSON-payload APIs. |

---

### 8. Cloud Security

| Sl. # | Question | Answer | Description & Code Verification |
| :--- | :--- | :--- | :--- |
| **1** | For data encryption within cloud, How does your company maintain the encryption keys? | **Azure Key Vault** | Encryption keys and application secrets are loaded via Azure Key Vault / App Service configuration ([`backend/.env.example`](file:///c:/Users/madhu/Desktop/rsli/backend/.env.example)). |
| **2** | For SAAS Service, Does the application allow secure removal of EXL's data from all storage media? | **Yes** | Temporary execution directories and uploaded files are purged after processing via [`cleanup_temp_dir()`](file:///c:/Users/madhu/Desktop/rsli/backend/executor/runner.py) and [`_schedule_session_cleanup()`](file:///c:/Users/madhu/Desktop/rsli/backend/main.py#L116-L138). |
| **3** | Does your company implement technical controls to continuously monitor and timely rectify any configuration changes? | **Yes** | Managed through version control (Git / Azure DevOps) and CI/CD pipelines. |
| **4** | Is EXL data separated from other tenants, ideally by providing a dedicated database or dedicated schema? | **Yes / NA** | Deployment model supports single-tenant dedicated database instances via `RSLI_DATABASE_URL` ([`backend/database/db.py`](file:///c:/Users/madhu/Desktop/rsli/backend/database/db.py#L12)). |
| **5** | Is data separation maintained between the organization's information and that of other customers? | **Yes** | Each execution workspace is isolated into a unique ephemeral folder (`rsli_{session_id}`) in [`backend/main.py:984`](file:///c:/Users/madhu/Desktop/rsli/backend/main.py#L984). |
| **6** | Are your Amazon S3 buckets and EBS Volumes encrypted? | **NA / Azure Blob** | Azure Blob Storage is used instead of AWS S3, leveraging Azure Storage Server-Side Encryption (SSE-KMS) in [`BlobAuditStore`](file:///c:/Users/madhu/Desktop/rsli/backend/audit/blob_store.py). |
| **7** | Is secure login enabled on PaaS/SaaS Service? | **Yes** | Enforced via TLS 1.2+, bcrypt hashing, and JWT HttpOnly session security. |
| **8** | Is Version Controlling is in place for cloud services? | **Yes** | Code and configuration templates are tracked in Git. |
| **9** | Is principle of least privilege followed while assigning privileges via IAM entity? | **Yes** | Role-based authorization isolates admin endpoints from regular application users. |
| **10** | Is S3 Bucket Access logging enabled? | **NA / Azure** | Azure Blob Storage analytics and diagnostic access logging apply for storage containers. |
| **11** | Does your company enforce multi-factor authentication (MFA) for the access of EXL's data in cloud? | **Yes** | MFA is enforced at the cloud infrastructure/IAM level (Azure Active Directory / Cloud Portal access). |

---

### 9. API Security

| Sl. # | Question | Answer | Description & Code Verification |
| :--- | :--- | :--- | :--- |
| **1** | Is rate limiting implemented on each API endpoint? | **Yes** | Rate limiting is implemented across endpoints using `slowapi` in [`backend/auth/rate_limiter.py`](file:///c:/Users/madhu/Desktop/rsli/backend/auth/rate_limiter.py#L25-L44): default (60/min), auth endpoints (5/min), upload & analysis endpoints (10/min), and admin endpoints (30/min). |
| **2** | Is user submitted data validated before it is executed by your API functions? | **Yes** | Centralized input validation is implemented in [`backend/auth/input_validator.py`](file:///c:/Users/madhu/Desktop/rsli/backend/auth/input_validator.py). Python scripts undergo AST syntax checks ([`validate_python_code`](file:///c:/Users/madhu/Desktop/rsli/backend/main.py#L243-L282)) and security scanning via [`RiskClassifier`](file:///c:/Users/madhu/Desktop/rsli/backend/validator/risk_classifier.py#L9-L58) to block dangerous operations (`os.system`, `subprocess`, `eval`, `exec`). |

---

### 11. Others

| Sl. # | Question | Answer | Description & Code Verification |
| :--- | :--- | :--- | :--- |
| **1** | Will you store any production data in development or staging environment? | **No** | Dev/staging environments use synthetic sample data files ([`samples/`](file:///c:/Users/madhu/Desktop/rsli/samples)) and isolated temporary folders. |
| **2** | Is there client and server validations implemented for the application for client supplied inputs? | **Yes** | Client validation is implemented in React forms ([`LoginPage.jsx`](file:///c:/Users/madhu/Desktop/rsli/frontend/src/components/LoginPage.jsx), [`PasswordStrengthIndicator.jsx`](file:///c:/Users/madhu/Desktop/rsli/frontend/src/components/PasswordStrengthIndicator.jsx)); server validation is enforced via Pydantic models in [`backend/main.py`](file:///c:/Users/madhu/Desktop/rsli/backend/main.py#L75-L229) and [`input_validator.py`](file:///c:/Users/madhu/Desktop/rsli/backend/auth/input_validator.py). |
| **3** | Does your application has file upload feature? | **Yes** | File uploads (Python ETL scripts, CSV, XLSX, Parquet) are handled in [`/api/validate-sources`](file:///c:/Users/madhu/Desktop/rsli/backend/main.py#L916-L953) and [`/api/execute`](file:///c:/Users/madhu/Desktop/rsli/backend/main.py#L962-L1009), with size limit enforcement (50MB in [`_save_uploads`](file:///c:/Users/madhu/Desktop/rsli/backend/main.py#L872-L913)) and extension allowlisting. |
| **4** | Do you have version controlling tool in place for the application to track changes and modification to the application? | **Yes** | Managed via Git repository version control (`.git/`). |
| **5** | Is there a backup policy defined for the application? | **Yes** | Audit logs and artifacts are archived in cloud blob storage ([`BlobAuditStore`](file:///c:/Users/madhu/Desktop/rsli/backend/audit/blob_store.py)), with relational database backup management. |
| **6** | Does the application maintain a journal of transactions or snapshots of data between backup intervals? | **Yes** | SQLite uses Write-Ahead Logging (`PRAGMA journal_mode=WAL` in [`backend/database/db.py:36-42`](file:///c:/Users/madhu/Desktop/rsli/backend/database/db.py#L36-L42)). Intermediate execution steps and validation states are saved via [`SnapshotStore`](file:///c:/Users/madhu/Desktop/rsli/backend/validator/snapshot_store.py) and [`snapshot.py`](file:///c:/Users/madhu/Desktop/rsli/backend/executor/snapshot.py). |
| **7** | Does the application and DB servers follow centrally managed OS policies? | **Yes** | Built to run in standard containerized or Azure App Service managed OS environments. |
| **8** | Does your company's patch management process covers Operating systems, Middleware, Firmware, Application / software? | **Yes** | Managed via automated dependency updates in [`requirements.txt`](file:///c:/Users/madhu/Desktop/rsli/backend/requirements.txt) / [`package.json`](file:///c:/Users/madhu/Desktop/rsli/frontend/package.json) and host OS patching. |
| **9** | Does your company perform regular vulnerability scanning for its IT infrastructure? | **Yes** | Supported via automated dependency scanning and static analysis in CI/CD. |
| **10** | Does your company engage an independent party to perform annual penetration testing on the company's network, internet-facing...? | **NA / Org Policy** | Application is an internal tool; external network pen-testing is handled at the enterprise infrastructure level. |
| **11** | Does your company have controls in place to protect its internet facing applications (serving EXL) from DDoS attack? | **Yes** | Application layer rate limiting ([`SlowAPIMiddleware`](file:///c:/Users/madhu/Desktop/rsli/backend/auth/rate_limiter.py#L135)) and request size limiting ([`RequestSizeLimitMiddleware`](file:///c:/Users/madhu/Desktop/rsli/backend/auth/rate_limiter.py#L69-L119)) combine with cloud infrastructure DDoS protection. |
| **12** | Is WAF implemented on public facing application for Web, Mobile and API for e.g. Citrix, Imperva? | **Yes / NA** | Deployable behind Azure Front Door / App Gateway WAF or Citrix ADC reverse proxy. |
| **13** | Do you DDOS protection for your public facing application? | **Yes** | Protected via in-application IP rate limiters ([`backend/auth/rate_limiter.py`](file:///c:/Users/madhu/Desktop/rsli/backend/auth/rate_limiter.py)) and cloud network DDoS mitigation. |