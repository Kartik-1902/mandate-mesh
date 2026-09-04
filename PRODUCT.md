# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **Primary:** Fintech & AI Commerce Developers, Hackathon Judges, and Risk/Security Engineers building or evaluating autonomous purchasing agents.
- **Secondary:** Autonomous buying agent operators and merchant aggregators requiring verifiable human-in-the-loop spending controls.

## Product Purpose

Mandate Mesh is a deterministic constraint enforcement, multi-merchant quote routing, and cryptographic audit engine for autonomous AI purchasing agents. It eliminates financial hallucination by enforcing that an AI agent cannot spend a single unauthorized rupee or bypass user-defined policies.

## Positioning

Unlike conventional AI shopping assistants that directly invoke payment APIs or place orders based on unverified LLM output, Mandate Mesh interposes a fail-closed cryptographic state machine where:
- The LLM proposes candidate goals.
- Deterministic Python validates authoritative merchant catalogs, applies lowest-TCO multi-merchant routing, and verifies ECDSA signatures.
- Razorpay payments only execute against cryptographically bound payment mandates.

## Operating Context

- **Workflow:** Real-time agentic deliberation $\rightarrow$ Multi-merchant quote evaluation $\rightarrow$ Cryptographic mandate authorization $\rightarrow$ Razorpay test payment execution $\rightarrow$ Immutable backward hash-chained audit logging.
- **Environment:** Control Tower desktop browser interface connecting to a local FastAPI backend (`:8000`), SQLite/PostgreSQL state storage, and simulated Razorpay test webhooks.

## Capabilities and Constraints

- **Deterministic Financial Rails:** All price computations are calculated strictly in integer **paise** (zero floating-point math).
- **Cryptographic Zero-Trust Chain:** NIST P-256 (User Intent Credential) $\rightarrow$ ECDSA SECP256K1 (Merchant-Signed Cart) $\rightarrow$ Platform Payment Mandate $\rightarrow$ Razorpay Orders API $\rightarrow$ Platform Signed Payment Receipt.
- **Adversarial Resilience:** Deterministic fail-closed defense against 6 attack vectors: Over-budget spend, Prompt injection SKU bypass, MITM cart tampering, Webhook double-capture replay, Cross-merchant signature forgery, and Expired quote authorization.
- **Human-in-the-Loop (HITL) Escalation:** When candidate catalog pricing exceeds the initial budget ceiling, automated charge is halted, and a structured approval request is presented.
- **Just-in-Time (JIT) Fallback Routing:** If a primary quote winner fails re-validation at authorization time, the policy engine automatically falls back to the verified runner-up without failing the transaction.

## Brand Commitments

- **Name:** Mandate Mesh (Control Tower)
- **Tagline:** Agentic Commerce Guardrails & Multi-Merchant Routing
- **Core Invariant:** *The LLM proposes; deterministic Python disposes. Zero unauthorized rupees move.*
- **Visual Personality:** Restrained, high-precision dark telemetry console (charcoal substrate, soft white phosphor, refined crimson alerts, and emerald verification proofs).

## Evidence on Hand

- `mandate_mesh_spec.md`: Complete architectural and cryptographic specification.
- `user_capabilities.md`: Detailed policy matrix and user guardrail boundaries.
- Full test suite: 259 passing Pytest unit/integration tests and 24 passing adversarial security attack vectors.
- Live Control Tower frontend: React + Vite application running on `http://localhost:5173`.

## Product Principles

1. **Deterministic Authority Outranks Probabilistic Proposals:** An LLM may hallucinate a goal or item, but only database-grounded, merchant-signed prices and user-authorized spend caps can trigger payment.
2. **Fail-Closed by Default:** Any missing signature, expired TTL, budget overrun, or unregistered SKU aborts the transaction with zero side-effects.
3. **Immutable Auditability:** Every lifecycle transition (intent, quote, mandate, rejection, capture, receipt) is appended to a tamper-evident SHA-256 backward hash chain in Indian Standard Time (IST).
4. **Transparent Optimization:** Routing decisions must be deterministic, auditable, and clearly display savings vs runner-up candidates.

## Accessibility & Inclusion

- High-contrast, glare-free dark mode adhering to WCAG 2.1 AA standards.
- Monospace tabular alignment for unambiguous financial numbers and cryptographic digests.
- Clear, jargon-free escalation prompts for human budget approvals.
