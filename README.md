# Mandate Mesh

**The LLM proposes. Deterministic Python disposes. An unauthorized rupee cannot move.**

Mandate Mesh is a cryptographic policy rail and multi-merchant routing engine for autonomous AI purchasing agents. It solves the hardest problem in agentic commerce: how do you let an AI agent shop on your behalf without giving it unlimited financial authority?

The answer is a fail-closed state machine where the LLM is structurally incapable of authorizing payments. Every authorization flows through deterministic Python: verified cryptographic signatures, integer-paise arithmetic, and an append-only hash-chained audit ledger.

---

## Table of Contents

- [The Problem](#the-problem)
- [Architecture](#architecture)
- [Cryptographic Chain of Custody](#cryptographic-chain-of-custody)
- [The Seven Quote Verification Gates](#the-seven-quote-verification-gates)
- [Multi-Merchant Routing](#multi-merchant-routing)
- [Mandate Finite State Machine](#mandate-finite-state-machine)
- [Adversarial Resilience](#adversarial-resilience)
- [Human-in-the-Loop (HITL) Escalation](#human-in-the-loop-hitl-escalation)
- [Partial Completion](#partial-completion)
- [Audit Ledger](#audit-ledger)
- [Test Suite](#test-suite)
- [Stack](#stack)
- [Setup](#setup)
- [API Reference](#api-reference)
- [Design Decisions](#design-decisions)
- [Project Structure](#project-structure)
- [Core Invariant](#core-invariant)

---

## The Problem

Modern AI agents can browse, decide, and initiate — but payment APIs don't care whether the instruction came from a verified human or a hallucinating model. An agent told to "buy birthday supplies" could silently overspend, authorize merchants you've never heard of, or be manipulated by a prompt-injected product description to bypass your budget entirely.

Mandate Mesh eliminates this attack surface. The agent proposes. A deterministic policy engine disposes. The LLM has zero financial authority.

---

## Architecture

The system is a strict pipeline. Each stage produces a cryptographically signed artifact that the next stage verifies before proceeding.

```
Natural Language Goal
        ↓
┌─────────────────────────────┐
│   LangGraph Buyer Agent     │  Gemini LLM deliberates, browses catalog,
│   (app/agent.py)            │  proposes SKU selections — no prices, no amounts
└─────────────┬───────────────┘
              ↓
┌─────────────────────────────┐
│   UserIntentCredential      │  ES256 JWT signed by user key
│   (app/schemas.py)          │  Contains: spend_cap_paise, allowed_categories,
│                             │  allowed_merchant_ids, TTL, nonce (replay guard)
└─────────────┬───────────────┘
              ↓
┌─────────────────────────────┐
│   Multi-Merchant Quote      │  app/quote_router.py verifies each quote
│   Router (app/quote_router) │  through 7 gates: merchant allowlist, category
│                             │  allowlist, signature validity, cart hash,
│                             │  budget cap, TTL, stock status
└─────────────┬───────────────┘
              ↓
┌─────────────────────────────┐
│   Mixed-Basket Planner      │  app/basket_planner.py allocates each product
│   (app/basket_planner.py)   │  to the cheapest verified merchant.
│                             │  All arithmetic in integer paise (zero float).
└─────────────┬───────────────┘
              ↓
┌─────────────────────────────┐
│   Policy Rail               │  app/policy.py: atomic spend reservation
│   (app/policy.py)           │  under SELECT FOR UPDATE. Issues PaymentMandate
│                             │  JWT signed by platform key. Single DB transaction
│                             │  for reservation + mandate + ledger append.
└─────────────┬───────────────┘
              ↓
┌─────────────────────────────┐
│   HITL + JIT Execution      │  app/hitl_execution.py: re-validates quotes
│   (app/hitl_execution.py)   │  just before payment. Falls back to runner-up
│                             │  on stockout. Executes each merchant leg
│                             │  independently. PARTIAL_COMPLETE on leg failure.
└─────────────┬───────────────┘
              ↓
┌─────────────────────────────┐
│   Razorpay Orders API       │  Per-leg Razorpay order creation and webhook
│   (app/razorpay_client.py)  │  capture. HMAC-verified webhook delivery.
│                             │  Deduplication on razorpay_payment_id.
└─────────────┬───────────────┘
              ↓
┌─────────────────────────────┐
│   SHA-256 Audit Ledger      │  app/ledger.py: append-only, backward hash-
│   (app/ledger.py)           │  chained. Every lifecycle transition sealed.
│                             │  verify_chain() mathematically validates the
│                             │  entire ledger from genesis to head.
└─────────────────────────────┘
```

---

## Cryptographic Chain of Custody

Every artifact in the pipeline is signed and verified. No unsigned data crosses a trust boundary.

| Artifact | Algorithm | Signer | Verified By |
|---|---|---|---|
| `UserIntentCredential` | ES256 (NIST P-256) | User private key | Policy rail at mandate issuance |
| `MerchantSignedCart` | ES256 (NIST P-256) | Merchant private key | Quote router (7-gate verification) |
| `PaymentMandate` | ES256 (NIST P-256) | Platform private key | HITL execution engine |
| `PaymentReceipt` | ES256 (NIST P-256) | Platform private key | Consumer verification |
| Webhook payload | HMAC-SHA256 | Razorpay | `app/webhooks.py` |
| Audit ledger entries | SHA-256 chain | Platform | `verify_chain()` |

Per **ADR-002**: no module other than `app/crypto.py` may directly call `cryptography` or `jwt` primitives. The entire cryptographic boundary is centralized and auditable in a single 632-line file.

### Cart Hash Integrity

Every `MerchantSignedCart` carries a `cart_hash`: a SHA-256 digest of the canonical JSON of its line items, tax, total, and merchant ID (RFC 8785 serialization — sorted keys, no whitespace). The policy rail recomputes this hash independently and rejects any cart where the claimed hash does not match the computed hash. A man-in-the-middle cannot alter a cart line item without breaking the signature and the hash simultaneously.

---

## The Seven Quote Verification Gates

`verify_and_classify_quotes()` in `app/quote_router.py` runs every candidate quote through these gates in order. Any failure is terminal for that quote — it is classified and no further gates are evaluated.

1. **Merchant Allowlist Authorization** — merchant ID must appear in `UserIntentCredential.allowed_merchant_ids`
2. **Category Authorization** — every line item category must be in `UserIntentCredential.allowed_categories`
3. **Cart JWT Signature** — ES256 signature verified against the merchant's registered public key
4. **Cart Hash Integrity** — recomputed SHA-256 cart hash must match the claimed `cart_hash` field
5. **Cart TTL** — `expires_at` must be in the future relative to current UTC
6. **Spend Cap** — `total_paise` must not exceed `UserIntentCredential.spend_cap_paise`
7. **Live Stock Validation** — each SKU must be in-stock in the live database catalog

---

## Multi-Merchant Routing

When a goal requires multiple products (e.g., a birthday cake from one merchant and candles from another), the basket planner allocates each product to the cheapest available verified merchant independently.

**Optimization modes:**
- `LOWEST_TOTAL_PRICE` — greedy per-product allocation. Mathematically optimal under the current commerce model (zero delivery fees, zero minimum order values, no volume tiers). See the explicit warning in `basket_planner.py` about when this stops being optimal.
- `PREFER_SINGLE_MERCHANT` — consolidate to a single merchant when possible.
- `LOWEST_PRICE_SINGLE_MERCHANT` — single-merchant constraint with price optimization.

All routing decisions are deterministic, auditable, and visible in the Control Tower with explicit savings calculations vs. runner-up alternatives.

---

## Mandate Finite State Machine

Every `MandateRecord` follows a formal FSM enforced by `app/mandate_fsm.py`. Direct assignment to `record.status` is forbidden — all transitions must go through `transition()`, which raises `InvalidStateTransition` on illegal moves.

```
RESERVED ──────────────────────────────────── ORDER_CREATING
                                                     │
                           ┌─────────────────────────┤
                           │                         │
                      ORDER_CREATED           RELEASED (terminal)
                           │
           ┌───────────────┼───────────────┐
           │               │               │
   PAYMENT_CAPTURED  PAYMENT_PENDING  PAYMENT_FAILED ──► RELEASED
   (terminal)              │               
                    PAYMENT_CAPTURED  
                    (terminal)        
```

A `RELEASED` mandate returns its reserved paise to the `IntentRegistry` available balance. A `PAYMENT_CAPTURED` mandate is permanent — it can never be mutated.

---

## Adversarial Resilience

Six attack vectors are tested in `tests/test_attacks.py` and `tests/test_backend_hardening.py`. All fail closed with zero side-effects.

| Attack | Response | HTTP Status |
|---|---|---|
| Over-budget spend attempt | `POLICY_SPEND_CAP_EXCEEDED`, zero paise reserved, no mandate created | 403 |
| Prompt injection with fake SKU | `CATALOG_SKU_NOT_FOUND`, cart never signed, LLM proposal rejected | 404 |
| MITM cart tampering | `POLICY_CART_SIGNATURE_INVALID` or `POLICY_CART_HASH_MISMATCH`, `POLICY_REJECTED` ledger entry | 409 |
| Unauthorized merchant in cart | `POLICY_MERCHANT_NOT_ALLOWED`, mandate authorization aborted | 403 |
| Webhook double-capture replay | `deduplicated: true`, second webhook silently absorbed, no double-credit | 200 |
| Cross-merchant signature forgery | Merchant B's key rejects Merchant A's signed cart, quote fails gate 3 | 409 |

Every rejection produces a `POLICY_REJECTED` ledger entry recording the exact breach context (amount attempted, cap in force, merchant ID, reason code). The ledger is mathematically tamper-evident.

---

## Human-in-the-Loop (HITL) Escalation

When a proposed basket exceeds the initial spend cap, the agent halts and presents a structured approval request. On approval, the engine performs **JIT revalidation** — it re-fetches merchant quotes at execution time to confirm prices and stock have not changed since authorization.

If a quote has expired during HITL review, the engine automatically re-quotes from the same merchant for the same SKUs (never substituting alternatives) and validates the fresh quote through the full 7-gate pipeline before proceeding.

---

## Partial Completion

When a multi-merchant plan has one leg captured and another fail (e.g., stockout at execution time), the system reaches `PARTIAL_COMPLETE`:

- The captured leg stays captured. It is never rolled back.
- The failed leg's reservation is released back to the available budget.
- A `POLICY_REJECTED` entry records the failure with the exact leg context.
- The aggregate `PurchasePlan` status reflects the partial state.

Zero reconciliation debt is possible. The 6-field invariant always holds:

```
Total Cap = Captured + Released + Remaining Headroom
```

---

## Audit Ledger

`app/ledger.py` maintains an append-only SHA-256 backward hash chain. Each entry contains:
- `entry_type` — the lifecycle event (INTENT_REGISTERED, CART_SIGNED, MANDATE_ISSUED, PAYMENT_CAPTURED, POLICY_REJECTED, etc.)
- `actor` — the system component that generated the entry
- `payload` — canonical JSON of the event context
- `payload_hash` — SHA-256 of the canonical payload
- `prev_hash` — the hash of the immediately preceding entry
- `entry_hash` — SHA-256 of `prev_hash + payload_hash + created_at_iso`

`verify_chain(db)` re-derives every hash from genesis to head. If any entry has been mutated, deleted, or reordered, the function returns `(False, broken_entry_id)` with the exact position of the break.

PostgreSQL deployments use `pg_advisory_xact_lock(1)` to serialize concurrent appends without table locks. SQLite uses a process-level `threading.RLock`.

---

## Test Suite

**290 tests passing. 6 skipped (concurrency tests excluded on SQLite). 0 failures.**

```
tests/test_attacks.py              8 tests   — 6 adversarial attack vectors + chain integrity
tests/test_backend_hardening.py   12 tests   — Injection, replay, boundary conditions
tests/test_basket_planner.py      14 tests   — Multi-merchant allocation correctness
tests/test_crypto.py              14 tests   — ES256 sign/verify, hash computation, JWT lifecycle
tests/test_integration.py         11 tests   — End-to-end journey: intent → mandate → capture
tests/test_ledger.py               6 tests   — Append, verify, tamper detection
tests/test_ledger_integrity.py     7 tests   — Chain hash correctness, concurrent appends
tests/test_mandate_fsm.py         58 tests   — Every legal and illegal state transition
tests/test_mixed_merchant_hitl_m8.py  19 tests — HITL + JIT revalidation + partial completion
tests/test_multi_merchant_discovery.py  17 tests — Quote routing, 7-gate verification
tests/test_policy.py              11 tests   — Spend cap, category, merchant, replay
tests/test_purchase_plan_m7.py    18 tests   — Purchase plan lifecycle
tests/test_quote_router.py        22 tests   — Router gate-by-gate verification
tests/test_merchant_keys.py       25 tests   — Per-merchant key resolution
```

Run the full suite:
```bash
uv run pytest
```

---

## Stack

| Layer | Technology |
|---|---|
| **Backend** | Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic |
| **AI Agent** | LangGraph, Gemini API (`gemini-3.5-flash-lite`) |
| **Cryptography** | `cryptography` library (NIST P-256 / ES256), PyJWT |
| **Payment Gateway** | Razorpay Orders API (test mode), HMAC-SHA256 webhook verification |
| **Database** | SQLite (development), PostgreSQL 16 (production via Docker) |
| **Frontend** | React 18, Vite, Tailwind CSS |
| **Package Manager** | `uv` |

---

## Setup

### Prerequisites
- Python 3.12+
- Node.js 18+
- `uv` package manager

### Backend

```bash
# Install dependencies
uv sync

# Copy and configure environment
cp .env.example .env
# Set GEMINI_API_KEY and RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET in .env

# Run migrations (SQLite, development)
uv run alembic upgrade head

# Start the API server
uv run uvicorn app.main:app --port 8000 --reload
```

The API documentation is available at `http://localhost:8000/docs`.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The Control Tower UI is available at `http://localhost:5173`.

### PostgreSQL (Optional)

```bash
docker compose up -d
# Update DATABASE_URL in .env to point to the Postgres instance
uv run alembic upgrade head
```

### Environment Variables

| Variable | Description | Required |
|---|---|---|
| `GEMINI_API_KEY` | Gemini API key for LLM deliberation | Yes (for agent) |
| `RAZORPAY_KEY_ID` | Razorpay test mode key ID | Yes |
| `RAZORPAY_KEY_SECRET` | Razorpay test mode secret | Yes |
| `DATABASE_URL` | SQLAlchemy connection string | No (defaults to SQLite) |
| `APP_ENV` | `development` or `production` | No (defaults to development) |

---

## API Reference

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/intent` | Register a `UserIntentCredential` |
| `POST` | `/api/v1/checkout` | Authorize a `PaymentMandate` against a signed cart |
| `POST` | `/api/v1/mandates/{id}/execute` | Execute a mandate leg (create Razorpay order) |
| `POST` | `/api/v1/webhooks/razorpay` | Receive and verify Razorpay payment webhooks |
| `GET`  | `/api/v1/ledger/verify` | Forensically verify the entire audit chain |
| `POST` | `/api/v1/agent/run` | Run the full LangGraph agent journey |
| `POST` | `/api/v1/demo/multi-leg-journey` | Orchestrated demo: intent → multi-merchant → capture |
| `GET`  | `/healthz` | Health check |

---

## Design Decisions

**Why integer paise everywhere?** Floating-point arithmetic on money is undefined behavior. `0.1 + 0.2 ≠ 0.3` in IEEE 754. Every amount in Mandate Mesh is an integer in paise. Division never happens. Rounding never happens.

**Why one cryptographic module?** ADR-002 mandates that `app/crypto.py` is the only file that may import `cryptography` or `jwt` primitives. This makes the cryptographic boundary auditable in a single place and prevents scattered, inconsistent signature logic across the codebase.

**Why a formal FSM for mandate states?** Direct assignment to `record.status` is forbidden. The FSM in `app/mandate_fsm.py` makes illegal state transitions a compile-time error pattern rather than a silent data corruption. Every allowed and forbidden transition is explicitly defined and tested.

**Why `pg_advisory_xact_lock` for the ledger?** The hash chain requires strictly sequential appends. Row-level locks create deadlock risk under concurrent writes. PostgreSQL advisory locks serialize all appends within a transaction without locking the table, giving linear chain integrity without sacrificing concurrent read performance.

**Why greedy per-product basket allocation?** Under the current commerce model (no delivery fees, no minimum order values, no volume tiers), greedy independent per-product allocation is mathematically provably optimal. The code explicitly documents the conditions under which this ceases to be true and what the correct replacement algorithm would be (MILP / branch-and-bound).

---

## Project Structure

```
mandate-mesh/
├── app/
│   ├── agent.py              # LangGraph buyer agent, Gemini LLM integration
│   ├── basket_planner.py     # Deterministic mixed-basket allocation (M6)
│   ├── crypto.py             # Sole cryptographic boundary (ADR-002)
│   ├── errors.py             # Structured PolicyViolation exception hierarchy
│   ├── hitl_execution.py     # HITL + JIT revalidation + partial completion (M8)
│   ├── ledger.py             # Append-only SHA-256 hash-chained audit log
│   ├── main.py               # FastAPI entrypoint, lifespan, route registration
│   ├── mandate_fsm.py        # Formal mandate state machine (ADR-005)
│   ├── merchant.py           # Merchant catalog seeding and cart signing
│   ├── merchant_keys.py      # Per-merchant ES256 key resolution
│   ├── models.py             # SQLAlchemy ORM models
│   ├── policy.py             # Deterministic policy rail, atomic reservation
│   ├── quote_router.py       # 7-gate multi-merchant quote verification (M3)
│   ├── razorpay_client.py    # Razorpay Orders API client (test mode)
│   ├── reconcile.py          # Self-healing reconciliation for stuck orders
│   ├── schemas.py            # Pydantic models: Intent, Cart, Mandate, Receipt
│   ├── schemas_routing.py    # Routing-specific Pydantic models
│   └── webhooks.py           # HMAC-verified Razorpay webhook processor
├── tests/                    # 290 passing tests across 24 test files
├── frontend/                 # React + Vite Control Tower UI
├── alembic/                  # Database migrations
├── docker-compose.yml        # PostgreSQL 16 for production
└── pyproject.toml
```

---

## Core Invariant

> **The LLM proposes; deterministic Python disposes. Zero unauthorized rupees move.**

This is not a marketing claim. It is enforced structurally: the LangGraph agent's tool schema for `propose_cart` accepts only `{items: list[{sku, quantity}]}`. The schema contains no `price`, `amount`, `total`, or `discount` parameters. The agent is architecturally incapable of proposing a price. Prices are retrieved exclusively from the signed merchant catalog at cart-signing time.

---

Built for the **Razorpay Buildathon** · Track 01: Agentic Commerce Guardrails