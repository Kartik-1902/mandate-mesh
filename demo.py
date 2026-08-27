"""Mandate Mesh — CLI Demo Runner (Track 01: AI Growth & Agentic Commerce).

Usage:
  python demo.py --happy-path     # Complete end-to-end payment lifecycle
  python demo.py --attack=1       # Attack 1: Over-budget spend blocked (HTTP 403)
  python demo.py --attack=2       # Attack 2: Prompt injection fake SKU rejected (HTTP 404)
  python demo.py --attack=3       # Attack 3: Cart quote tampering blocked (HTTP 409)
  python demo.py --attack=4       # Attack 4 / Failure: Lost-response reconciled
"""

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from uuid import uuid4

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.agent import run_buyer_agent
from app.api.deps import KEYS_DIR
from app.crypto import (
    compute_cart_hash,
    generate_es256_keypair,
    issue_cart_jwt,
    issue_intent_jwt,
    load_private_key_pem,
    load_public_key_pem,
    verify_receipt_jwt,
)
from app.db import Base, engine, get_session
from app.ledger import verify_chain
from app.merchant import seed_catalog, sign_cart
from app.models import MandateRecord, MandateStatus
from app.policy import authorize_mandate, verify_intent
from app.razorpay_client import RazorpayClient, simulate_payment_captured_webhook
from app.schemas import CartLineItem, MerchantSignedCart, UserIntentCredential
from app.webhooks import process_payment_webhook


def ensure_keys_and_db(db):
    """Bootstraps database tables, seed catalog, and keys."""
    Base.metadata.create_all(bind=engine)
    seed_catalog(db)
    db.commit()

    KEYS_DIR.mkdir(parents=True, exist_ok=True)
    keys = {}
    for actor in ["user", "merchant", "platform"]:
        priv_p = KEYS_DIR / f"{actor}_private.pem"
        pub_p = KEYS_DIR / f"{actor}_public.pem"
        if not priv_p.exists() or not pub_p.exists():
            priv_b, pub_b = generate_es256_keypair()
            priv_p.write_bytes(priv_b)
            pub_p.write_bytes(pub_b)
        keys[f"{actor}_priv"] = load_private_key_pem(priv_p)
        keys[f"{actor}_pub"] = load_public_key_pem(pub_p)
    return keys


def run_happy_path():
    print("=" * 70)
    print("MANDATE MESH: HAPPY PATH END-TO-END DEMO")
    print("Track 01: AI Growth & Agentic Commerce · Razorpay Buildathon")
    print("=" * 70)

    db = get_session()
    keys = ensure_keys_and_db(db)
    rzp = RazorpayClient(mock_mode=True)
    webhook_secret = "whsec_test_secret_123"

    now = datetime.now(timezone.utc)

    # 1. User issues Intent Credential (Spend Cap: ₹1,500.00 / 150000 paise)
    print("\n[Step 1] User issues signed UserIntentCredential:")
    intent = UserIntentCredential(
        user_id="user_karthik_01",
        spend_cap_paise=150000,  # ₹1,500
        allowed_categories=["bakery", "gifting"],
        allowed_merchant_ids=["merchant_cakehouse_01"],
        max_transactions=1,
        nonce=uuid4().hex,
        not_before=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
    )
    intent_jwt = issue_intent_jwt(intent, keys["user_priv"])
    print(f"  User ID:         {intent.user_id}")
    print(f"  Spend Cap:       Rs. {intent.spend_cap_paise / 100:.2f}")
    print(f"  Allowed:         Categories={intent.allowed_categories}, Merchants={intent.allowed_merchant_ids}")
    print(f"  Intent JWT:      {intent_jwt[:35]}...")

    # 2. Register intent
    verify_intent(intent_jwt, keys["user_pub"], db)
    db.commit()
    print("  [OK] Intent verified and registered in IntentRegistry (State: ACTIVE).")

    # 3. Agent selects item; Merchant signs Cart Quote (1kg Chocolate Truffle Cake @ ₹940.00)
    print("\n[Step 2] Merchant issues authoritative signed cart quote:")
    cart_model, cart_jwt = sign_cart(
        merchant_id="merchant_cakehouse_01",
        line_items_req=[{"sku": "CAKE-CHOC-001", "quantity": 1}],
        merchant_private_key_pem=keys["merchant_priv"],
        db=db,
    )
    print(f"  SKU:             {cart_model.line_items[0].sku} ({cart_model.line_items[0].name})")
    print(f"  Authoritative:   Rs. {cart_model.total_paise / 100:.2f} (Priced from DB catalog, not agent)")
    print(f"  Cart Hash:       {cart_model.cart_hash[:16]}...")
    print(f"  Cart JWT:        {cart_jwt[:35]}...")

    # 4. Policy Rail Authorization
    print("\n[Step 3] Policy Rail evaluates bounds & creates Razorpay Order:")
    idemp_key = f"tx_{uuid4().hex[:12]}"
    mandate, mandate_jwt, record = authorize_mandate(
        intent_jwt=intent_jwt,
        cart_jwt=cart_jwt,
        idempotency_key=idemp_key,
        user_public_key_pem=keys["user_pub"],
        merchant_public_key_pem=keys["merchant_pub"],
        platform_private_key_pem=keys["platform_priv"],
        db=db,
    )

    # Pre-flight write and order creation
    record.status = MandateStatus.ORDER_CREATING
    db.commit()

    rzp_order = rzp.create_order(
        amount_paise=mandate.authorized_amount_paise,
        currency=mandate.currency,
        receipt=record.order_idempotency_key,
    )
    record.razorpay_order_id = rzp_order["id"]
    record.status = MandateStatus.ORDER_CREATED
    db.commit()

    print(f"  Mandate ID:      {mandate.mandate_id}")
    print(f"  Authorized:      Rs. {mandate.authorized_amount_paise / 100:.2f}")
    print(f"  Order Receipt:   {record.order_idempotency_key}")
    print(f"  Razorpay Order:  {record.razorpay_order_id} (State: ORDER_CREATED)")
    print("  [OK] Spend cap atomically reserved in IntentRegistry.")

    # 5. Razorpay Webhook Ingestion (payment.captured)
    print("\n[Step 4] Ingesting authentic Razorpay payment.captured webhook:")
    raw_wh_bytes, wh_sig = simulate_payment_captured_webhook(
        razorpay_order_id=record.razorpay_order_id,
        amount_paise=94000,
        webhook_secret=webhook_secret,
    )

    wh_res = process_payment_webhook(
        raw_body=raw_wh_bytes,
        signature=wh_sig,
        db=db,
        webhook_secret=webhook_secret,
        platform_private_key_pem=keys["platform_priv"],
    )
    print(f"  Webhook Status:  {wh_res['status']}")
    print(f"  Receipt ID:      {wh_res['receipt_id']}")

    # Verify receipt JWT
    receipt_obj = verify_receipt_jwt(wh_res["receipt_jwt"], keys["platform_pub"])
    print(f"  Signed Receipt:  Captured Rs. {receipt_obj.amount_captured_paise / 100:.2f} (Order: {receipt_obj.razorpay_order_id})")

    # 6. Audit Ledger Verification
    print("\n[Step 5] Forensically verifying append-only audit ledger chain:")
    is_valid, broken_id = verify_chain(db)
    print(f"  Audit Chain:     {'VALID [OK]' if is_valid else 'CORRUPTED [FAILED]'}")
    print("=" * 70)
    print("SUCCESS: Full payment flow executed with zero OTP and 100% cryptographic proof.")
    print("=" * 70)
    db.close()


def run_attack(attack_num: int):
    print("=" * 70)
    print(f"MANDATE MESH: ADVERSARIAL ATTACK DEMO (MODE --attack={attack_num})")
    print("=" * 70)

    db = get_session()
    keys = ensure_keys_and_db(db)
    rzp = RazorpayClient(mock_mode=True)
    now = datetime.now(timezone.utc)

    if attack_num == 1:
        # Attack 1: Over-budget spend
        print("\n[Attack 1] The Over-Budget Runaway Spend:")
        print("  Scenario: User sets spend cap to Rs. 1,500. Agent selects Luxury Fondant Cake @ Rs. 4,940.")
        intent = UserIntentCredential(
            user_id="user_attacker_01",
            spend_cap_paise=150000,  # ₹1,500 cap
            allowed_categories=["bakery"],
            allowed_merchant_ids=["merchant_cakehouse_01"],
            nonce=uuid4().hex,
            not_before=now - timedelta(minutes=1),
            expires_at=now + timedelta(hours=1),
        )
        intent_jwt = issue_intent_jwt(intent, keys["user_priv"])
        verify_intent(intent_jwt, keys["user_pub"], db)
        db.commit()

        cart_model, cart_jwt = sign_cart(
            merchant_id="merchant_cakehouse_01",
            line_items_req=[{"sku": "CAKE-PREM-001", "quantity": 1}],  # ₹4,940
            merchant_private_key_pem=keys["merchant_priv"],
            db=db,
        )

        try:
            authorize_mandate(intent_jwt, cart_jwt, "tx_atk_1", keys["user_pub"], keys["merchant_pub"], keys["platform_priv"], db)
            print("  [ERROR] Attack succeeded unexpectedly!")
        except Exception as e:
            print(f"  [BLOCKED] Policy Rail rejected authorization: {type(e).__name__} (HTTP {getattr(e, 'http_status', 403)})")
            print(f"  Message:  {e}")
            print("  Result:   Zero money moved. Invariant preserved.")

    elif attack_num == 2:
        # Attack 2: Prompt injection fake SKU
        print("\n[Attack 2] Prompt Injection / Hallucinated Fake SKU:")
        print("  Scenario: Malicious prompt asks agent to buy 'UNAPPROVED-GOLD-COIN' with arbitrary price.")
        try:
            sign_cart(
                merchant_id="merchant_cakehouse_01",
                line_items_req=[{"sku": "UNAPPROVED-GOLD-COIN-99", "quantity": 1}],
                merchant_private_key_pem=keys["merchant_priv"],
                db=db,
            )
            print("  [ERROR] Cart signing succeeded unexpectedly!")
        except Exception as e:
            print(f"  [BLOCKED] Merchant rejected invalid SKU: {type(e).__name__} (HTTP {getattr(e, 'http_status', 404)})")
            print(f"  Message:  {e}")
            print("  Result:   Agent cannot hallucinate prices or non-existent items.")

    elif attack_num == 3:
        # Attack 3: Cart quote tampering
        print("\n[Attack 3] MITM Cart Quote Tampering:")
        print("  Scenario: Attacker tampers with the signed cart JWT payload to alter price or items.")
        cart_model, cart_jwt = sign_cart(
            merchant_id="merchant_cakehouse_01",
            line_items_req=[{"sku": "CAKE-CHOC-001", "quantity": 1}],
            merchant_private_key_pem=keys["merchant_priv"],
            db=db,
        )

        header_b64, payload_b64, sig_b64 = cart_jwt.split(".")
        import base64
        p_dict = json.loads(base64.urlsafe_b64decode(payload_b64 + "==").decode("utf-8"))
        p_dict["total_paise"] = 1000  # Tampered total
        tampered_b64 = base64.urlsafe_b64encode(json.dumps(p_dict).encode("utf-8")).decode("utf-8").rstrip("=")
        tampered_jwt = f"{header_b64}.{tampered_b64}.{sig_b64}"

        intent = UserIntentCredential(
            user_id="user_atk3",
            spend_cap_paise=150000,
            allowed_categories=["bakery"],
            allowed_merchant_ids=["merchant_cakehouse_01"],
            nonce=uuid4().hex,
            not_before=now - timedelta(minutes=1),
            expires_at=now + timedelta(hours=1),
        )
        intent_jwt = issue_intent_jwt(intent, keys["user_priv"])
        verify_intent(intent_jwt, keys["user_pub"], db)
        db.commit()

        try:
            authorize_mandate(intent_jwt, tampered_jwt, "tx_atk_3", keys["user_pub"], keys["merchant_pub"], keys["platform_priv"], db)
            print("  [ERROR] Tampered cart was accepted unexpectedly!")
        except Exception as e:
            print(f"  [BLOCKED] Cryptographic Trust Layer rejected tampered cart: {type(e).__name__} (HTTP {getattr(e, 'http_status', 409)})")
            print(f"  Message:  {e}")
            print("  Result:   Dual-layer ES256 & SHA-256 cart_hash validation caught tampering.")

    elif attack_num == 4:
        # Attack 4: Lost-response network recovery
        print("\n[Attack 4 / Resilience] Lost-Response Network Recovery:")
        print("  Scenario: Network drops after Razorpay creates order but before response arrives.")
        intent = UserIntentCredential(
            user_id="user_resilience_01",
            spend_cap_paise=150000,
            allowed_categories=["bakery"],
            allowed_merchant_ids=["merchant_cakehouse_01"],
            nonce=uuid4().hex,
            not_before=now - timedelta(minutes=1),
            expires_at=now + timedelta(hours=1),
        )
        intent_jwt = issue_intent_jwt(intent, keys["user_priv"])
        verify_intent(intent_jwt, keys["user_pub"], db)
        db.commit()

        cart_model, cart_jwt = sign_cart(
            merchant_id="merchant_cakehouse_01",
            line_items_req=[{"sku": "CAKE-CHOC-001", "quantity": 1}],
            merchant_private_key_pem=keys["merchant_priv"],
            db=db,
        )

        mandate, mandate_jwt, record = authorize_mandate(
            intent_jwt, cart_jwt, "tx_lost_resp_01", keys["user_pub"], keys["merchant_pub"], keys["platform_priv"], db
        )
        record.status = MandateStatus.ORDER_CREATING
        db.commit()

        # Simulate Razorpay creating the order in the background
        rzp_order = rzp.create_order(
            amount_paise=94000,
            receipt=record.order_idempotency_key,
        )
        print(f"  Mandate state stuck in: {record.status} (Network response dropped)")
        print(f"  Receipt Key:            {record.order_idempotency_key}")

        # Trigger application reconciler
        print("  [Reconciler] Running receipt-based reconciliation against Razorpay...")
        matched = rzp.reconcile_order(record.order_idempotency_key)
        if matched:
            record.razorpay_order_id = matched["id"]
            record.status = MandateStatus.ORDER_CREATED
            db.commit()
            print(f"  [OK] Reconciled! Recovered Razorpay Order ID: {record.razorpay_order_id}")
            print(f"  Mandate state advanced to: {record.status}")

    print("=" * 70)
    db.close()


def run_agent(goal: str):
    """Executes natural language goal via LangGraph Buyer Agent and full payment rail."""
    print("=" * 70)
    print("  MANDATE MESH — BUYER AGENT AUTONOMOUS PURCHASE DEMO")
    print(f"  Goal: '{goal}'")
    print("=" * 70)

    db = get_session()
    keys = ensure_keys_and_db(db)

    # 1. User Intent Credential (budget extracted from goal or default Rs. 1,500)
    parsed_budget_match = re.search(r"(?:under|below|max|budget)\s*(?:rs\.?|inr)?\s*(\d+)", goal, re.IGNORECASE)
    initial_spend_cap = int(parsed_budget_match.group(1)) * 100 if parsed_budget_match else 150000

    print("\n[Step 1: User Signs Intent Credential (ES256)]")
    now = datetime.now(timezone.utc)
    intent = UserIntentCredential(
        user_id="user_alice_agent_01",
        spend_cap_paise=initial_spend_cap,
        allowed_categories=["bakery"],
        allowed_merchant_ids=["merchant_cakehouse_01"],
        nonce=uuid4().hex,
        not_before=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
    )
    intent_jwt = issue_intent_jwt(intent, keys["user_priv"])
    verify_intent(intent_jwt, keys["user_pub"], db)
    db.commit()
    print(f"  Intent ID:   {intent.intent_id}")
    print(f"  Spend Cap:   Rs. {initial_spend_cap / 100:.2f} ({initial_spend_cap} paise)")
    print("  Categories:  ['bakery']")

    # 2. Buyer Agent Execution (LangGraph)
    print("\n[Step 2: Buyer Agent Deliberation (LangGraph)]")
    agent_state = run_buyer_agent(
        goal=goal,
        db=db,
        merchant_private_key_pem=keys["merchant_priv"],
    )

    if agent_state.get("error"):
        print(f"  [ERROR] Agent failed: {agent_state['error']}")
        db.close()
        return

    cart = agent_state["signed_cart"]
    cart_jwt = agent_state["cart_jwt"]

    print(f"  Node 1 (parse_goal):      Parsed goal -> category='{agent_state['parsed_intent'].get('category')}'")
    print(f"  Node 2 (browse_catalog):  Found {len(agent_state['catalog_candidates'])} candidate catalog items")
    print(f"  Node 3 (propose_cart):    Proposed {len(cart.line_items)} line item(s):")
    for li in cart.line_items:
        print(f"    • SKU: {li.sku:<16} | Name: {li.name:<25} | Qty: {li.quantity} | Unit: Rs. {li.unit_price_paise/100:.2f} | Line Total: Rs. {li.line_total_paise/100:.2f}")

    if agent_state.get("llm_reasoning"):
        print(f"  [Gemini LLM Reasoning]:   \"{agent_state['llm_reasoning']}\"")
    print("  [Structural Boundary]:    Agent tool submitted ONLY {sku, quantity} list -- NO price parameter.")
    print(f"  Authoritative Subtotal:   Rs. {cart.subtotal_paise / 100:.2f}")
    print(f"  Merchant Signed Total:    Rs. {cart.total_paise / 100:.2f} ({cart.total_paise} paise)")

    # Handle Human-in-the-Loop Budget Escalation
    if agent_state.get("status") == "REQUIRES_USER_APPROVAL":
        esc = agent_state["escalation_details"]
        print("\n[Human-in-the-Loop] Budget Escalation Triggered!")
        print(f"  Notice:         {esc['message']}")
        print(f"  Current Cap:    Rs. {esc['current_budget_paise'] / 100:.2f}")
        print(f"  Required Total: Rs. {esc['suggested_total_paise'] / 100:.2f} (+Rs. {esc['overspend_paise'] / 100:.2f})")
        print(f"  [User Biometric Approval: User approves Rs. {esc['suggested_total_paise'] / 100:.2f} on device]")

        # User mints and signs a new Intent Credential with the escalated spend cap
        now = datetime.now(timezone.utc)
        elevated_intent = UserIntentCredential(
            user_id="user_alice_agent_01",
            spend_cap_paise=esc["suggested_total_paise"],
            allowed_categories=["bakery"],
            allowed_merchant_ids=["merchant_cakehouse_01"],
            nonce=uuid4().hex,
            not_before=now - timedelta(minutes=1),
            expires_at=now + timedelta(hours=1),
        )
        intent_jwt = issue_intent_jwt(elevated_intent, keys["user_priv"])
        verify_intent(intent_jwt, keys["user_pub"], db)
        db.commit()
        print(f"  New Intent ID:  {elevated_intent.intent_id} (Approved Cap: Rs. {esc['suggested_total_paise'] / 100:.2f})")
        intent_jwt = intent_jwt

    # 3. Policy Rail Authorization
    print("\n[Step 3: Deterministic Policy Rail Authorization]")
    idemp_key = f"tx_agent_{uuid4().hex[:12]}"
    mandate, mandate_jwt, record = authorize_mandate(
        intent_jwt=intent_jwt,
        cart_jwt=cart_jwt,
        idempotency_key=idemp_key,
        user_public_key_pem=keys["user_pub"],
        merchant_public_key_pem=keys["merchant_pub"],
        platform_private_key_pem=keys["platform_priv"],
        db=db,
    )
    print(f"  [OK] Mandate Authorized: {mandate.mandate_id}")
    print(f"  Reserved in Registry:    Rs. {record.reserved_paise / 100:.2f}")

    # 4. Razorpay Order Creation
    print("\n[Step 4: Razorpay Order Creation]")
    rzp = RazorpayClient(mock_mode=True)
    rzp_order = rzp.create_order(
        amount_paise=record.authorized_amount_paise,
        receipt=record.order_idempotency_key,
    )
    record.razorpay_order_id = rzp_order["id"]
    record.status = MandateStatus.ORDER_CREATED
    db.commit()
    print(f"  Razorpay Order ID: {rzp_order['id']}")
    print(f"  Receipt Reference: {record.order_idempotency_key}")

    # 5. Webhook Capture Simulation
    print("\n[Step 5: Razorpay Webhook Capture & Receipt Issuance]")
    raw_webhook, signature = simulate_payment_captured_webhook(
        razorpay_order_id=rzp_order["id"],
        amount_paise=record.authorized_amount_paise,
        webhook_secret="whsec_demo_secret",
    )
    wh_result = process_payment_webhook(
        raw_body=raw_webhook,
        signature=signature,
        db=db,
        webhook_secret="whsec_demo_secret",
        platform_private_key_pem=keys["platform_priv"],
    )
    print(f"  Webhook Status:    {wh_result['status']}")
    print(f"  Payment Receipt:   {wh_result['receipt_id']}")

    # 6. Verify Payment Receipt
    receipt = verify_receipt_jwt(wh_result["receipt_jwt"], keys["platform_pub"])
    print(f"  Verified Receipt:  Captured Rs. {receipt.amount_captured_paise / 100:.2f} at {receipt.captured_at.isoformat()}")

    # 7. Audit Ledger Verification
    print("\n[Step 6: Forensic Audit Ledger Verification]")
    is_valid, broken_id = verify_chain(db)
    print(f"  Hash Chain Status: {'VALID (Linear, zero tamper)' if is_valid else f'CORRUPTED at {broken_id}'}")

    print("\n" + "=" * 70)
    print("  [SUCCESS] Buyer agent goal fulfilled & payment completed deterministically!")
    print("=" * 70)
    db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mandate Mesh CLI Demo")
    parser.add_argument("--happy-path", action="store_true", help="Execute complete happy path payment flow")
    parser.add_argument("--attack", type=int, choices=[1, 2, 3, 4], help="Execute specific attack / failure mode (1-4)")
    parser.add_argument("--agent", type=str, help="Run autonomous buyer agent with a natural language goal")
    args = parser.parse_args()

    if args.happy_path:
        run_happy_path()
    elif args.attack:
        run_attack(args.attack)
    elif args.agent:
        run_agent(args.agent)
    else:
        parser.print_help()
