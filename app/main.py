"""FastAPI application entrypoint for Mandate Mesh.

Core Invariant:
  The LLM proposes; deterministic Python disposes.
  An unauthorized rupee can never move because of an LLM decision.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.agent_routes import router as agent_router
from app.api.checkout import router as checkout_router
from app.api.demo_routes import router as demo_router
from app.api.deps import KEYS_DIR
from app.api.intent import router as intent_router
from app.api.ledger_routes import router as ledger_router
from app.api.mandates import router as mandates_router
from app.api.webhooks import router as webhooks_router
from app.crypto import generate_es256_keypair
from app.db import Base, engine, get_session
from app.errors import PolicyViolation
from app.merchant import seed_catalog
from app.razorpay_client import RazorpayClient
from app.reconcile import reconcile_stuck_orders


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application startup & shutdown events."""
    try:
        # 1. Ensure database tables exist
        Base.metadata.create_all(bind=engine)

        # 2. Seed merchant catalog
        session = get_session()
        try:
            seed_catalog(session)
            session.commit()
        except Exception:
            session.rollback()
        finally:
            session.close()

        # 3. Self-healing reconciliation of stuck ORDER_CREATING mandates (ADR-005)
        rec_session = get_session()
        try:
            rzp_client = RazorpayClient(mock_mode=True)
            reconcile_stuck_orders(rec_session, rzp_client)
        except Exception:
            rec_session.rollback()
        finally:
            rec_session.close()
    except Exception:
        pass

    # 4. Ensure local keys exist for user, platform, and all demo merchants
    try:
        from app.merchant_keys import KNOWN_DEMO_MERCHANTS, MERCHANT_KEYS_DIR

        KEYS_DIR.mkdir(parents=True, exist_ok=True)
        MERCHANT_KEYS_DIR.mkdir(parents=True, exist_ok=True)

        for actor in ["user", "platform"]:
            priv_p = KEYS_DIR / f"{actor}_private.pem"
            pub_p = KEYS_DIR / f"{actor}_public.pem"
            if not priv_p.exists() or not pub_p.exists():
                priv_b, pub_b = generate_es256_keypair()
                priv_p.write_bytes(priv_b)
                pub_p.write_bytes(pub_b)

        # Generate per-merchant keys
        for mid in KNOWN_DEMO_MERCHANTS:
            m_dir = MERCHANT_KEYS_DIR / mid
            m_dir.mkdir(parents=True, exist_ok=True)
            priv_p = m_dir / "private.pem"
            pub_p = m_dir / "public.pem"
            if not priv_p.exists() or not pub_p.exists():
                priv_b, pub_b = generate_es256_keypair()
                priv_p.write_bytes(priv_b)
                pub_p.write_bytes(pub_b)

        # Mirror CakeHouse keys to legacy flat files for backward compatibility
        cake_priv = MERCHANT_KEYS_DIR / "merchant_cakehouse_01" / "private.pem"
        cake_pub = MERCHANT_KEYS_DIR / "merchant_cakehouse_01" / "public.pem"
        flat_priv = KEYS_DIR / "merchant_private.pem"
        flat_pub = KEYS_DIR / "merchant_public.pem"
        if cake_priv.exists() and not flat_priv.exists():
            flat_priv.write_bytes(cake_priv.read_bytes())
        if cake_pub.exists() and not flat_pub.exists():
            flat_pub.write_bytes(cake_pub.read_bytes())
    except Exception:
        pass

    yield


app = FastAPI(
    title="Mandate Mesh — Deterministic Policy Rail",
    description="Cryptographically-bound policy rail for autonomous AI agentic commerce (Razorpay Buildathon Track 01).",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware for Next.js Control Tower UI (Phase 6)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(PolicyViolation)
async def policy_violation_handler(request: Request, exc: PolicyViolation) -> JSONResponse:
    """Standardized exception handler for all deterministic policy violations."""
    return JSONResponse(
        status_code=exc.http_status,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            }
        },
    )


# Register API Routers
app.include_router(intent_router)
app.include_router(checkout_router)
app.include_router(mandates_router)
app.include_router(webhooks_router)
app.include_router(ledger_router)
app.include_router(agent_router)
app.include_router(demo_router)


@app.get("/healthz", tags=["System"])
def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "mandate-mesh"}
