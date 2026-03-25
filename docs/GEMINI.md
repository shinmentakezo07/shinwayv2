# Shin Proxy — Project Context

Shin Proxy is a high-performance reverse proxy built with FastAPI that exposes Cursor's internal chat API as standard OpenAI and Anthropic compatible interfaces. It is designed to enable third-party autonomous agents (like Roo Code, Kilo Code, and Cline) to leverage Cursor's backend while bypassing native restrictions on tools, paths, and AI persona.

## Project Overview

*   **Purpose:** Bridge the gap between Cursor's internal API and standard LLM interfaces, specifically optimized for coding agent workflows.
*   **Core Architecture:** Follows a structured pipeline: `Unified Router` -> `LiteLLM Normalization` -> `Format Conversion` -> `Request Pipeline` -> `Cursor API` -> `Response Conversion`.
*   **Key Features:**
    *   **Unified Routing:** Single entry point for both OpenAI (`/v1/chat/completions`) and Anthropic (`/v1/messages`) formats.
    *   **Stealth Bypass:** Uses natural language role-play strategies to override Cursor's "Support Assistant" persona and restricted path scoping.
    *   **Massive Context Support:** Optimized for 200K+ token payloads with dynamic timeout management.
    *   **Credential Management:** Round-robin cookie pool with health monitoring and auto-recovery.
    *   **Advanced Observability:** Structured logging with `structlog` and Vercel telemetry spoofing.

## Tech Stack

*   **Framework:** FastAPI (Python 3.12+)
*   **API Normalization:** LiteLLM
*   **HTTP Client:** httpx (Async)
*   **Data Validation:** Pydantic / Pydantic-Settings
*   **Logging:** structlog
*   **Caching:** cachetools (L1), Redis (Optional L2)
*   **Token Management:** tiktoken

## Building and Running

### Setup
1.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
2.  **Environment Configuration:**
    ```bash
    cp .env.example .env
    # Fill in required fields, especially CURSOR_COOKIE or CURSOR_COOKIES
    ```

### Execution
*   **Run Server:**
    ```bash
    python run.py
    ```
    *Note: The server defaults to port 4000.*
*   **Start with Optimizations (Production-like):**
    ```bash
    export GATEWAY_FIRST_TOKEN_TIMEOUT=180 && python run.py
    ```

### Testing
*   **Run Automated Tests:**
    ```bash
    PYTHONPATH=. pytest tests/
    ```
*   **Manual Verification:** Use the included test scripts (e.g., `test_all_tools.py`, `test_massive.py`) to verify specific capabilities.

## Development Conventions

*   **Architecture Consistency:** Maintain the established pipeline flow when adding new features or endpoints.
*   **Type Safety:** Strict use of type hints for all functions and variable declarations.
*   **Exception Handling:** Use the custom exception hierarchy in `handlers.py` (inheriting from `ProxyError`).
*   **Logging:** Always use structured logging with context. Avoid raw `print` statements in production code.
*   **Configuration:** All settings must be declared in `config.py` and loaded via the `settings` object.
*   **Formatters:** Response formatting logic should reside in `converters/` to keep routers lean.
