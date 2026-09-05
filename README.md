# Mandate Mesh

**The LLM proposes. Deterministic Python disposes. An unauthorized rupee cannot move.**

Mandate Mesh is a cryptographic policy rail and multi-merchant routing engine for autonomous AI purchasing agents. It solves a core problem in agentic commerce: how do you let an AI agent shop and initiate payments without giving the model unrestricted financial authority?

The answer is a fail-closed control plane. The LLM proposes products; deterministic Python decides what is financially executable. Every authorization is bounded by a signed user intent, merchant-signed quotes, integer-paise accounting, a formal mandate state machine, Just-In-Time (JIT) revalidation, and an append-only SHA-256 audit ledger.

> **Razorpay is the payment execution rail; Mandate Mesh is the bounded authorization control plane that decides whether an AI-generated purchase is allowed to reach that rail.**

---

## 🚀 Live Demo

The repository includes a judge-facing **Control Tower** for running and observing the transaction engine.

### 90-second walkthrough

1. Open the Control Tower.
2. Enter a natural-language shopping request and spend cap.
3. Run the **Guided Transaction Journey**.
4. Observe the control-plane flow: intent → AI proposal → policy boundary → PurchasePlan → reservation → JIT → independent payment legs → settlement → audit proof.
5. Run the same request in **All Success** and **Leg 2 Stock Exhaustion** scenarios.
6. Inspect the returned intent ID, PurchasePlan ID, mandate IDs, Razorpay order IDs, JIT verdicts, settlement accounting, and run-scoped audit events.
7. Switch to the **Adversarial Threat Bench** to exercise over-budget spend, cart tampering, signature forgery, webhook replay, and stale-quote scenarios.

The Guided Journey is an **observability projection of the backend engine**, not a second business-logic implementation. Values shown in the journey are intended to come from the authoritative backend execution state.

> **Submission note:** add the deployed frontend and backend URLs here before final submission.

---

## 🎯 What It Solves

Modern AI agents can browse, reason, select products, and call tools. Payment systems need stronger guarantees than a model's natural-language intent.

An autonomous buyer should not be able to:

- exceed a user-defined spend cap,
- purchase from an unauthorized merchant,
- alter a merchant quote,
- replay a payment event,
- bypass merchant/product identity,
- continue using an expired intent or quote,
- corrupt a successful payment because a different merchant leg failed.

Mandate Mesh separates **reasoning authority** from **financial authority**:

```text
AI / LLM
  │
  │ proposes products and intent interpretation
  ▼
Deterministic Control Plane
  │
  ├── signed user intent
  ├── merchant allowlists
  ├── quote verification
  ├── deterministic routing
  ├── aggregate budget reservation
  ├── mandate FSM
  ├── JIT inventory / price revalidation
  └── idempotent payment processing
  │
  ▼
Razorpay execution rail
```

---

## 💡 Why Razorpay + Mandate Mesh

Razorpay provides payment primitives for creating and processing payments. Mandate Mesh adds an authorization layer above those primitives.

| Responsibility                           |          Mandate Mesh |        Razorpay |
| ---------------------------------------- | --------------------: | --------------: |
| Interpret natural-language shopping goal |                    ✅ |               — |
| Bound AI authority                       |                    ✅ |               — |
| Authorize merchants/categories           |                    ✅ |               — |
| Validate merchant-signed quotes          |                    ✅ |               — |
| Determine aggregate spend exposure       |                    ✅ |               — |
| Create payment order                     |    Requests execution |              ✅ |
| Process payment                          |                     — |              ✅ |
| Payment lifecycle / status               |       Consumes result |              ✅ |
| Webhook delivery                         | Verifies + reconciles | ✅ sends events |
| Final internal authorization decision    |                    ✅ |               — |
| Immutable internal audit trail           |                    ✅ |               — |

This separation is also relevant to AI-enabled payment tooling. Razorpay's official MCP Server lets compatible AI assistants interact with Razorpay APIs, including payment and order operations. Mandate Mesh addresses the complementary question: **what should an AI agent be authorized to do with those payment capabilities?**

Official references:

- [Razorpay Standard Checkout](https://razorpay.com/docs/payments/payment-gateway/web-integration/standard/)
- [Razorpay Integration Steps](https://razorpay.com/docs/payments/payment-gateway/web-integration/standard/integration-steps/)
- [Razorpay Webhooks — Validate & Test](https://razorpay.com/docs/webhooks/validate-test/)
- [Razorpay MCP Server](https://razorpay.com/docs/mcp-server/)
- [Razorpay MCP Tools Reference](https://razorpay.com/docs/mcp-server/tools-reference/)

---

## 🏗 Architecture

The system is a strict pipeline. AI-generated proposals are converted into cryptographically bounded artifacts before any payment execution is allowed.

```text
Natural Language Goal
        ↓
┌─────────────────────────────┐
│   LangGraph Buyer Agent     │  Gemini LLM deliberates and proposes
│   (app/agent.py)            │  product/SKU selections only
│                             │  no payment credentials or price authority
└─────────────┬───────────────┘
              ↓
┌─────────────────────────────┐
│   UserIntentCredential      │  ES256 JWT signed by user key
│   (app/schemas.py)          │  spend cap, categories, merchants, TTL, nonce
└─────────────┬───────────────┘
              ↓
┌─────────────────────────────┐
│   Quote Verification        │  7 deterministic verification gates
│   (app/quote_router.py)     │  merchant, category, signature, hash,
│                             │  TTL, spend cap, live stock
└─────────────┬───────────────┘
              ↓
┌─────────────────────────────┐
│   Mixed-Basket Planner      │  deterministic merchant allocation
│   (app/basket_planner.py)   │  integer-paise arithmetic
└─────────────┬───────────────┘
              ↓
┌─────────────────────────────┐
│   Policy + PurchasePlan     │  aggregate authorization and reservation
│   (app/policy.py)           │  row-locked budget evaluation
│                             │  one intent → one plan → N mandates
└─────────────┬───────────────┘
              ↓
┌─────────────────────────────┐
│   HITL + JIT Execution      │  exact-basket revalidation, independent legs
│   (app/hitl_execution.py)   │  price/stock fail-closed handling
│                             │  PARTIAL_COMPLETE support
└─────────────┬───────────────┘
              ↓
┌─────────────────────────────┐
│   Razorpay                  │  per-leg order execution + payment lifecycle
│   (app/razorpay_client.py)  │  test-mode / mock demo support
└─────────────┬───────────────┘
              ↓
┌─────────────────────────────┐
│   Webhooks + Reconciliation │  HMAC verification, deduplication,
│   (app/webhooks.py)         │  state transitions and accounting
└─────────────┬───────────────┘
              ↓
┌─────────────────────────────┐
│   SHA-256 Audit Ledger      │  append-only backward hash chain
│   (app/ledger.py)           │  verify_chain() validates genesis → head
└─────────────────────────────┘
```

---

## 💳 Razorpay Payment Flow

Mandate Mesh deliberately keeps gateway execution downstream of deterministic authorization.

```text
User Goal
   ↓
AI Proposal
   ↓
Signed Intent + Policy Validation
   ↓
Deterministic PurchasePlan
   ↓
Aggregate Reservation
   ↓
Per-Leg JIT Validation
   ↓
Razorpay Order Creation
   ↓
Razorpay Checkout / Payment
   ↓
Payment Verification / Webhook
   ↓
Mandate State Transition
   ↓
IntentRegistry Accounting
   ↓
PaymentReceipt + Audit Ledger
```

Razorpay's Standard Checkout documentation requires server-side order creation and server-side verification of the returned payment signature before fulfillment. Successful payment data includes the Razorpay payment ID, order ID, and signature; the signature is verified on the server using the server-known order ID and account secret. See the [official integration steps](https://razorpay.com/docs/payments/payment-gateway/web-integration/standard/integration-steps/).

For asynchronous events, Razorpay webhooks use an `X-Razorpay-Signature` generated from the configured webhook secret. Razorpay also documents duplicate webhook delivery and recommends idempotent handling. See [Validate and Test Webhooks](https://razorpay.com/docs/webhooks/validate-test/).

Mandate Mesh applies those gateway events to its own mandate FSM and financial-control state rather than allowing a payment callback to directly mutate arbitrary application state.

---

## 🧪 Razorpay Test Mode & Demo Reality

The project is designed for a hackathon-safe environment. **No real customer money is required for the repository's demonstration flows.** Razorpay Test Mode uses test credentials and simulated payment behavior instead of real monetary movement.

Be explicit about the current demo boundary:

| Component                   | Status in the demo architecture                                          |
| --------------------------- | ------------------------------------------------------------------------ |
| LLM deliberation            | Real Gemini/LangGraph path where enabled                                 |
| Intent credential           | Real signed application artifact                                         |
| Quote validation            | Real deterministic code                                                  |
| PurchasePlan                | Real database state                                                      |
| Reservation accounting      | Real database state                                                      |
| Cryptographic signing       | Real application cryptography                                            |
| JIT validation              | Real deterministic engine                                                |
| Partial-failure handling    | Real M8 engine                                                           |
| Audit ledger                | Real append-only application ledger                                      |
| Razorpay credentials        | Server-side only; use Test Mode for submission                           |
| Guided demo payment capture | Controlled simulated webhook / mock Razorpay path where used by the demo |
| Real money                  | **Never required**                                                       |

Do not describe a simulated webhook as a live customer payment. The repository distinguishes **real control-plane execution** from **simulated/test gateway settlement**.

---

## 🤖 AI vs Financial Authority

The core security property is structural rather than prompt-based.

```text
┌───────────────────────┐
│       LLM / Agent     │
│                       │
│  Can propose:         │
│  • products           │
│  • SKUs               │
│  • quantities         │
│  • natural-language   │
│    interpretation     │
│                       │
│  Cannot authorize:    │
│  • financial amount   │
│  • merchant authority │
│  • payment credentials│
│  • final execution    │
└───────────┬───────────┘
            ↓
┌───────────────────────┐
│ Deterministic Policy  │
│        Rail           │
│                       │
│  • verifies intent    │
│  • verifies quotes    │
│  • checks budgets     │
│  • reserves exposure  │
│  • authorizes plans   │
│  • controls execution │
└───────────────────────┘
```

The agent proposal interface is intentionally narrower than the financial policy interface. Merchant-signed catalog data supplies authoritative prices used by deterministic code.

---

## 🔐 Cryptographic Chain of Custody

Every trust-boundary artifact is signed or verified before it is used.

| Artifact               | Algorithm          | Signer               | Verified By                 |
| ---------------------- | ------------------ | -------------------- | --------------------------- |
| `UserIntentCredential` | ES256 (NIST P-256) | User private key     | Policy rail                 |
| `MerchantSignedCart`   | ES256 (NIST P-256) | Merchant private key | Quote / policy verification |
| `PaymentMandate`       | ES256 (NIST P-256) | Platform private key | Execution engine            |
| `PaymentReceipt`       | ES256 (NIST P-256) | Platform private key | Consumer verification       |
| Razorpay webhook       | HMAC-SHA256        | Razorpay             | `app/webhooks.py`           |
| Audit ledger entries   | SHA-256 chain      | Platform             | `verify_chain()`            |

Per **ADR-002**, cryptographic primitives are centralized in `app/crypto.py` so signature and JWT handling remain auditable and consistent across trust boundaries.

### Cart Hash Integrity

Every `MerchantSignedCart` carries a SHA-256 `cart_hash` over canonical cart content. The policy rail recomputes the hash independently and rejects a cart when the claimed hash does not match the computed representation.

---

## ✅ The Seven Quote Verification Gates

`verify_and_classify_quotes()` in `app/quote_router.py` evaluates every candidate quote through deterministic gates:

1. **Merchant Allowlist Authorization** — merchant must be permitted by the user intent.
2. **Category Authorization** — every line item category must be allowed.
3. **Cart JWT Signature** — merchant signature must verify against its registered public key.
4. **Cart Hash Integrity** — recomputed hash must match the signed cart.
5. **Cart TTL** — quote must still be valid.
6. **Spend Cap** — quote total must fit the authorized cap.
7. **Live Stock Validation** — required SKUs must be in stock in the authoritative catalog.

Any failed gate rejects the quote rather than passing an uncertain artifact downstream.

---

## 🧩 PurchasePlan + Multi-Merchant Execution

A key abstraction is the aggregate `PurchasePlan`:

```text
1 UserIntent
      ↓
1 PurchasePlan
      ↓
N Merchant Mandates
      ↓
N Razorpay Orders
```

A PurchasePlan represents one coherent user purchase intent while keeping each merchant leg independently executable.

Authorization is aggregate: the plan is validated and reserved before gateway execution. Execution is independent: one merchant leg may succeed while another fails. The plan therefore models physical-commerce reality without pretending that separate payments are transactionally atomic.

Possible aggregate outcomes include:

- `CONFIRMED` — authorized and awaiting execution.
- `IN_PROGRESS` — one or more legs are actively executing.
- `COMPLETE` — every leg is captured.
- `PARTIAL_COMPLETE` — at least one leg is captured and another leg is failed, released, or pending.
- `FAILED` — all legs reached unsuccessful terminal states.

---

## 💰 Financial Reservation & Invariants

All monetary arithmetic uses integer paise.

The authoritative `IntentRegistry` balance model is:

```text
SPEND CAP = CAPTURED + RESERVED + AVAILABLE

AVAILABLE = SPEND CAP - RESERVED - CAPTURED
```

Before gateway execution, the aggregate PurchasePlan exposure is reserved. After execution, captured funds remain captured and failed-leg reservations are released.

For a partial plan, the observable accounting is:

```text
Authorized Plan
      ├── Captured amount
      └── Released amount

IntentRegistry
      ├── Captured
      ├── Remaining reserved
      └── Available
```

This distinction matters because **reserved exposure** and **captured money** are not the same state.

---

## ⚡ Just-In-Time Revalidation

Execution-time freshness is intentionally separate from initial planning.

For each leg, the M8 execution engine can revalidate:

- exact originally authorized SKU(s),
- merchant identity,
- category allowlist,
- merchant signature,
- cart hash,
- quote TTL,
- price against the authorized amount,
- live stock.

A fresh quote that differs from the authorized amount requires re-authorization rather than silently charging a new price. An unavailable originally authorized SKU fails closed rather than substituting an arbitrary product.

---

## 🧯 Partial Completion

Independent merchant rails deliberately do not pretend to be one atomic payment.

Example:

```text
PurchasePlan
   │
   ├── Leg A → PAYMENT_CAPTURED   ₹X
   │
   └── Leg B → RELEASED           ₹Y
                         │
                         └── reservation returned

Plan → PARTIAL_COMPLETE
```

The successful leg is never rolled back because another merchant failed. The failed leg's reserved amount is released through the financial control plane, and the aggregate plan records the partial outcome.

This models a real commerce property: once a merchant has fulfilled one independently paid item, the system cannot truthfully pretend that item was never purchased merely because another merchant became unavailable.

---

## 🛡 Adversarial Threat Bench

The Control Tower exposes six adversarial scenarios:

| Attack                                 | Expected result                          |
| -------------------------------------- | ---------------------------------------- |
| Over-budget runaway spend              | Blocked by policy / spend cap            |
| Prompt injection / fake SKU            | Rejected by catalog/identity boundary    |
| MITM cart tampering                    | Signature/hash verification fails        |
| Webhook replay                         | Duplicate event is absorbed idempotently |
| Cross-merchant key confusion / forgery | Wrong merchant signature fails           |
| Stale quote / TTL replay               | Expired quote rejected                   |

The important property is not merely that an error is returned. Each attack is designed around the same control plane used by legitimate transactions, so the security boundary is exercised against adversarial input rather than demonstrated only by prose.

---

## 🔔 Razorpay Webhooks & Idempotency

Razorpay webhook processing is treated as an external, asynchronous input to the mandate state machine.

```text
Razorpay Webhook
      ↓
Raw-body HMAC verification
      ↓
Event identity / deduplication
      ↓
Mandate state validation
      ↓
Serialized financial accounting
      ↓
Audit ledger append
```

The runtime webhook model maintains a uniqueness boundary around Razorpay event identity and event type. Razorpay documents duplicate webhook delivery and the need for idempotent handling.

For customer-facing production deployments, the webhook endpoint should be public HTTPS and the webhook secret must remain private. Test-mode webhook traffic can be used to validate the integration before live mode.

---

## 📜 Audit Ledger

`app/ledger.py` maintains an append-only backward SHA-256 hash chain. Each entry contains:

- `entry_type` — lifecycle event type
- `actor` — component that emitted the event
- `payload` — structured event context
- `payload_hash` — SHA-256 of the canonical payload
- `prev_hash` — immediately preceding entry hash
- `entry_hash` — hash linking the current entry to its predecessor

`verify_chain(db)` re-derives the chain from genesis to head and identifies the location of a break if the chain is invalid.

PostgreSQL deployments serialize ledger appends with transaction-scoped advisory locking; SQLite uses a process-level lock for local development.

The Control Tower can display audit events associated with a transaction run, making the ledger observable rather than merely stored.

---

## 🖥 Guided Transaction Journey

The Guided Transaction Journey is the visual debugger / narrator for one backend execution.

```text
01  HUMAN INTENT
    ↓
02  AI DELIBERATION
    ↓
03  INTENT BOUNDARY
    ↓
04  PURCHASE PLAN
    ↓
05  RESERVATION
    ↓
06  JIT REVALIDATION
    ↓
07  INDEPENDENT EXECUTION
    ↓
08  SETTLEMENT
    ↓
09  AUDIT PROOF
```

A completed run should expose authoritative values rather than scenario-derived placeholders:

- intent / plan / mandate identifiers,
- merchant and SKU information,
- authorization amounts,
- pre- and post-execution reservation balances,
- JIT verdicts,
- Razorpay order IDs,
- capture/release outcomes,
- aggregate PurchasePlan status,
- run-scoped ledger events and chain verification.

The journey supports controlled **All Success** and **Leg 2 Stock Exhaustion** scenarios so a judge can observe the difference between `COMPLETE` and `PARTIAL_COMPLETE` without changing the core execution semantics.

---

## 🧪 Test Suite

The repository contains unit, integration, adversarial, concurrency, planner, policy, PurchasePlan, JIT/HITL, ledger, and cryptographic tests.

Run the current suite with:

```bash
uv run pytest -q
```

The test suite is the source of truth for the current test count; avoid keeping a manually maintained total in this README after adding new tests.

Useful test areas include:

```text
tests/test_attacks.py
tests/test_backend_hardening.py
tests/test_basket_planner.py
tests/test_crypto.py
tests/test_integration.py
tests/test_ledger.py
tests/test_ledger_integrity.py
tests/test_mandate_fsm.py
tests/test_mixed_merchant_hitl_m8.py
tests/test_multi_merchant_discovery.py
tests/test_policy.py
tests/test_purchase_plan_m7.py
tests/test_quote_router.py
tests/test_merchant_keys.py
```

---

## 🚀 Deployment

For a judge-accessible deployment, use a public frontend, public HTTPS backend, managed PostgreSQL, and Razorpay Test Mode.

A typical layout is:

```text
Vercel / Static Host
        │
        ▼
React Control Tower
        │
        ▼
Public HTTPS FastAPI Backend
        │
        ├── Managed PostgreSQL
        ├── Gemini API
        └── Razorpay Test Mode
```

Deployment requirements:

- Set `VITE_API_BASE` to the public backend URL rather than `localhost`.
- Restrict backend CORS to the deployed frontend origin(s).
- Inject PostgreSQL connection strings through platform secrets.
- Inject Gemini and Razorpay credentials through platform secrets.
- Persist application cryptographic keys securely; do not rely on development-time auto-generation in production.
- Configure a public HTTPS Razorpay webhook endpoint in Test Mode.

Razorpay's webhook documentation provides a Test Mode workflow for validating webhook integrations and requires the webhook secret used to verify signatures to remain private. See [Validate and Test Webhooks](https://razorpay.com/docs/webhooks/validate-test/).

### Environment variables

| Variable              | Purpose                                  | Required                              |
| --------------------- | ---------------------------------------- | ------------------------------------- |
| `GEMINI_API_KEY`      | Gemini API key for agent deliberation    | For AI path                           |
| `RAZORPAY_KEY_ID`     | Razorpay Test Mode key ID                | For Razorpay integration              |
| `RAZORPAY_KEY_SECRET` | Razorpay Test Mode secret                | For Razorpay integration              |
| `DATABASE_URL`        | SQLAlchemy database URL                  | No; SQLite is the development default |
| `APP_ENV`             | `development` or `production`            | No                                    |
| `VITE_API_BASE`       | Public FastAPI base URL for the frontend | Required for deployed frontend        |

---

## ⚙️ Local Setup

### Prerequisites

- Python 3.12+
- Node.js 18+
- `uv` package manager

### Backend

```bash
uv sync
cp .env.example .env

# Configure the required development/test secrets in .env.
uv run alembic upgrade head
uv run uvicorn app.main:app --port 8000 --reload
```

API documentation:

```text
http://localhost:8000/docs
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

### PostgreSQL development environment

```bash
docker compose up -d
uv run alembic upgrade head
```

---

## 🔌 API Reference

Core routes currently exposed by the application include:

| Method | Path                                     | Description                                        |
| ------ | ---------------------------------------- | -------------------------------------------------- |
| `POST` | `/api/v1/intent/authorize`               | Authorize/register a `UserIntentCredential`        |
| `GET`  | `/api/v1/checkout/catalog.json`          | Read merchant catalog data used by checkout flows  |
| `POST` | `/api/v1/checkout/checkout/sign-cart`    | Create a merchant-signed cart                      |
| `POST` | `/api/v1/mandate/authorize`              | Authorize a `PaymentMandate` against a signed cart |
| `POST` | `/api/v1/mandate/reconcile/{mandate_id}` | Reconcile a mandate stuck during order creation    |
| `POST` | `/api/v1/webhooks/razorpay`              | Receive and verify Razorpay webhooks               |
| `GET`  | `/api/v1/ledger/entries`                 | Inspect audit ledger entries                       |
| `GET`  | `/api/v1/ledger/verify-chain`            | Verify the full SHA-256 audit chain                |
| `POST` | `/api/v1/agent/deliberate`               | Run the agent deliberation / shopping path         |
| `POST` | `/api/v1/agent/escalate-and-pay`         | Escalated HITL authorization flow                  |
| `POST` | `/api/v1/demo/multi-leg-journey`         | Controlled multi-merchant Guided Journey execution |
| `POST` | `/api/v1/demo/attack/{attack_id}`        | Run one adversarial attack scenario                |
| `POST` | `/api/v1/demo/simulate-capture`          | Controlled payment-capture webhook simulation      |
| `GET`  | `/healthz`                               | Health check                                       |

For complete request/response schemas, use the FastAPI OpenAPI documentation exposed by the running backend.

---

## ⚠️ Known Limitations & Honest Demo Boundaries

This project is intentionally explicit about what is and is not production-complete:

- Razorpay integration is designed for Test Mode in the hackathon submission.
- Some Control Tower demo flows use a controlled mock Razorpay client or simulated webhook to demonstrate the downstream state machine safely.
- The merchant inventory is a controlled application catalog rather than a production merchant-network integration.
- The current greedy mixed-basket planner assumes no delivery fees, minimum-order constraints, volume pricing, or cross-item pricing interactions; the repository documents when a more complex optimizer would be required.
- SQLite is intended for development; PostgreSQL is the concurrency-oriented deployment database.
- Production deployment requires secure persistence/injection of application cryptographic keys and restrictive CORS configuration.

These limitations do not change the central control-plane thesis: the AI proposal is not itself authorized to move money.

---

## 🧠 Design Decisions

**Why integer paise everywhere?** All financial state is represented as integer paise, eliminating floating-point rounding from authorization and reconciliation logic.

**Why one cryptographic module?** Cryptographic primitives are centralized so signature and JWT handling remain auditable and consistent across trust boundaries.

**Why a formal FSM?** `MandateRecord` transitions are explicitly constrained; illegal state changes are rejected rather than silently mutating financial state.

**Why a PurchasePlan?** A user request can require multiple independent merchant payments. PurchasePlan separates aggregate authorization from per-leg execution while preserving a single financial boundary.

**Why aggregate reservation before gateway execution?** The system reserves the authorized exposure before calling an external payment gateway so concurrent agents cannot oversubscribe the same intent budget.

**Why JIT revalidation?** Agent deliberation and payment execution happen at different times. Inventory and quotes can change during that interval, so the execution rail revalidates exact authorized products immediately before order creation.

**Why partial completion instead of forced rollback?** Independent merchant payments are not one atomic external transaction. Preserving already-captured payments while releasing failed-leg reservations reflects the actual physical and financial state.

**Why the Razorpay boundary?** The payment gateway executes an already-authorized action. Mandate Mesh decides whether an AI-originated proposal is allowed to become that action.

---

## 📁 Project Structure

```text
mandate-mesh/
├── app/
│   ├── agent.py              # LangGraph buyer agent, Gemini integration
│   ├── basket_planner.py     # Deterministic mixed-basket allocation
│   ├── crypto.py             # Central cryptographic boundary
│   ├── errors.py             # Structured policy exception hierarchy
│   ├── hitl_execution.py     # HITL + JIT + partial completion engine
│   ├── ledger.py             # Append-only SHA-256 audit ledger
│   ├── main.py               # FastAPI application entrypoint
│   ├── mandate_fsm.py        # Formal mandate state machine
│   ├── merchant.py            # Merchant catalog and cart signing
│   ├── merchant_keys.py      # Per-merchant key resolution
│   ├── models.py             # SQLAlchemy ORM models
│   ├── policy.py             # Deterministic policy rail + reservation
│   ├── quote_router.py       # 7-gate quote verification
│   ├── razorpay_client.py    # Razorpay integration / mock adapter
│   ├── reconcile.py          # Stuck-order reconciliation
│   ├── schemas.py            # Pydantic domain schemas
│   ├── schemas_routing.py    # Routing-specific schemas
│   └── webhooks.py           # Razorpay webhook processor
├── tests/                    # Unit, integration and adversarial tests
├── frontend/                 # React 19 + Vite Control Tower UI
├── alembic/                  # Database migrations
├── docker-compose.yml        # PostgreSQL development environment
└── pyproject.toml
```

---

## 🧱 Core Invariant

> **The LLM proposes; deterministic Python disposes. Zero unauthorized rupees move.**

This is enforced structurally. The agent proposal interface is intentionally narrower than the financial policy interface: the model can propose item identities and quantities, but authoritative prices, merchant identity, policy constraints, spend limits, reservation state, and payment execution are resolved outside the LLM.

The core security boundary therefore does not depend on a single prompt being perfectly followed. It depends on what the model is **architecturally unable to authorize**.

---

Built for the **Razorpay Buildathon · Track 01: AI Growth & Agentic Commerce / Agentic Commerce Guardrails**.
