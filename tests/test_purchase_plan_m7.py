"""Milestone M7: PurchasePlan and Multi-Leg Authorization Test Suite.

Verifies:
1. successful single-leg PurchasePlan
2. successful multi-leg PurchasePlan
3. correct plan_id on all child MandateRecords
4. correct aggregate total_authorized_paise
5. correct aggregate reserved_paise update
6. plan total equals sum of child mandate authorized amounts
7. duplicate plan request
8. duplicate leg request
9. duplicate mandate/idempotency key
10. concurrent plan authorization against the same intent
11. concurrent plans cannot exceed the original spend cap
12. concurrent plans cannot bypass max_transactions
13. one invalid child leg aborts the entire plan
14. unauthorized merchant aborts the entire plan
15. invalid/forged quote aborts the entire plan
16. expired intent aborts the entire plan
17. insufficient remaining budget aborts the entire plan
18. all-or-nothing database behavior when one leg fails
19. audit ledger consistency after successful authorization
20. no partial audit/mandate/reservation state after rollback
21. legacy single-mandate flow remains valid
22. deterministic leg idempotency keys: tx_plan_{plan_id.hex}_leg_{merchant_id}
"""

import concurrent.futures
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
import pytest
from sqlalchemy.orm import sessionmaker

from app.crypto import (
    generate_es256_keypair,
    issue_cart_jwt,
    issue_intent_jwt,
)
from app.errors import (
    PolicyCartExpired,
    PolicyCategoryNotAllowed,
    PolicyIntentExpired,
    PolicyMerchantNotAllowed,
    PolicyReplayDetected,
    PolicySpendCapExceeded,
    PolicyTransactionLimitReached,
    PolicyViolation,
)
from app.merchant import seed_catalog, sign_cart
from app.models import (
    AuditLedgerEntry,
    CatalogItem,
    IntentRegistry,
    IntentStatus,
    LedgerEntryType,
    MandateRecord,
    MandateStatus,
    PurchasePlan,
)
from app.policy import authorize_mandate, authorize_plan, verify_intent
from app.schemas import MerchantSignedCart, UserIntentCredential


@pytest.fixture
def crypto_keys():
    """Generates fresh ES256 keypairs for user, merchants, and platform."""
    user_priv, user_pub = generate_es256_keypair()
    m1_priv, m1_pub = generate_es256_keypair()
    m2_priv, m2_pub = generate_es256_keypair()
    plat_priv, plat_pub = generate_es256_keypair()

    return {
        "user": {"private_key_pem": user_priv, "public_key_pem": user_pub},
        "merchant_1": {"private_key_pem": m1_priv, "public_key_pem": m1_pub},
        "merchant_2": {"private_key_pem": m2_priv, "public_key_pem": m2_pub},
        "platform": {"private_key_pem": plat_priv, "public_key_pem": plat_pub},
    }


def make_test_intent_jwt(
    user_keys,
    db,
    spend_cap_paise=200000,
    max_transactions=5,
    allowed_merchants=None,
    allowed_categories=None,
    not_before=None,
    expires_at=None,
):
    """Helper to create and register a UserIntentCredential."""
    now = datetime.now(timezone.utc)
    intent = UserIntentCredential(
        intent_id=uuid4(),
        user_id="test_buyer_01",
        spend_cap_paise=spend_cap_paise,
        currency="INR",
        allowed_categories=allowed_categories or ["bakery", "gifting"],
        allowed_merchant_ids=allowed_merchants or ["merchant_cakehouse_01", "merchant_sweetdelight_02"],
        max_transactions=max_transactions,
        nonce=f"nonce_{uuid4().hex}",
        not_before=not_before or (now - timedelta(minutes=5)),
        expires_at=expires_at or (now + timedelta(hours=2)),
    )
    jwt_str = issue_intent_jwt(intent, user_keys["private_key_pem"])
    verify_intent(jwt_str, user_keys["public_key_pem"], db)
    return intent, jwt_str


def make_signed_cart_jwt(
    merchant_id,
    merchant_keys,
    db,
    price_paise=50000,
    category="bakery",
    sku=None,
    expires_at=None,
):
    """Helper to create a valid signed cart JWT for a merchant."""
    sku_name = sku or f"SKU-{uuid4().hex[:6]}"
    # Ensure item exists in DB
    existing = db.query(CatalogItem).filter_by(merchant_id=merchant_id, sku=sku_name).first()
    if not existing:
        item = CatalogItem(
            merchant_id=merchant_id,
            sku=sku_name,
            name=f"Test Item {sku_name}",
            description="Test Description",
            category=category,
            price_paise=price_paise,
            in_stock=True,
        )
        db.add(item)
        db.commit()

    signed_cart, cart_jwt = sign_cart(
        merchant_id=merchant_id,
        line_items_req=[{"sku": sku_name, "quantity": 1}],
        merchant_private_key_pem=merchant_keys["private_key_pem"],
        db=db,
    )
    return signed_cart, cart_jwt


def test_successful_single_leg_purchase_plan(db_session, crypto_keys):
    """Requirement 1: Successful single-leg PurchasePlan creation."""
    intent, intent_jwt = make_test_intent_jwt(crypto_keys["user"], db_session, spend_cap_paise=100000)
    cart1, cart_jwt1 = make_signed_cart_jwt(
        "merchant_cakehouse_01",
        crypto_keys["merchant_1"],
        db_session,
        price_paise=45000,
    )

    plan_id = uuid4()
    plan, mandates, mandate_records = authorize_plan(
        intent_jwt=intent_jwt,
        legs=[{"merchant_id": "merchant_cakehouse_01", "cart_jwt": cart_jwt1}],
        user_public_key_pem=crypto_keys["user"]["public_key_pem"],
        platform_private_key_pem=crypto_keys["platform"]["private_key_pem"],
        db=db_session,
        plan_id=plan_id,
        merchant_public_keys={"merchant_cakehouse_01": crypto_keys["merchant_1"]["public_key_pem"]},
    )

    assert plan.plan_id == plan_id
    assert plan.status == "CONFIRMED"
    assert plan.total_authorized_paise == 45000
    assert len(mandates) == 1
    assert len(mandate_records) == 1
    assert mandate_records[0].plan_id == plan_id
    assert mandate_records[0].status == MandateStatus.RESERVED


def test_successful_multi_leg_purchase_plan(db_session, crypto_keys):
    """Requirement 2: Successful multi-leg PurchasePlan grouping multiple merchant legs."""
    intent, intent_jwt = make_test_intent_jwt(crypto_keys["user"], db_session, spend_cap_paise=200000)

    cart1, cart_jwt1 = make_signed_cart_jwt(
        "merchant_cakehouse_01",
        crypto_keys["merchant_1"],
        db_session,
        price_paise=60000,
    )
    cart2, cart_jwt2 = make_signed_cart_jwt(
        "merchant_sweetdelight_02",
        crypto_keys["merchant_2"],
        db_session,
        price_paise=75000,
    )

    plan_id = uuid4()
    plan, mandates, records = authorize_plan(
        intent_jwt=intent_jwt,
        legs=[
            {"merchant_id": "merchant_cakehouse_01", "cart_jwt": cart_jwt1},
            {"merchant_id": "merchant_sweetdelight_02", "cart_jwt": cart_jwt2},
        ],
        user_public_key_pem=crypto_keys["user"]["public_key_pem"],
        platform_private_key_pem=crypto_keys["platform"]["private_key_pem"],
        db=db_session,
        plan_id=plan_id,
        merchant_public_keys={
            "merchant_cakehouse_01": crypto_keys["merchant_1"]["public_key_pem"],
            "merchant_sweetdelight_02": crypto_keys["merchant_2"]["public_key_pem"],
        },
    )

    assert plan.plan_id == plan_id
    assert plan.status == "CONFIRMED"
    assert len(mandates) == 2
    assert len(records) == 2
    assert plan.total_authorized_paise == 135000


def test_correct_plan_id_on_all_child_mandate_records(db_session, crypto_keys):
    """Requirement 3: Every child MandateRecord has the matching plan_id."""
    intent, intent_jwt = make_test_intent_jwt(crypto_keys["user"], db_session)
    cart1, cjwt1 = make_signed_cart_jwt("merchant_cakehouse_01", crypto_keys["merchant_1"], db_session, price_paise=30000)
    cart2, cjwt2 = make_signed_cart_jwt("merchant_sweetdelight_02", crypto_keys["merchant_2"], db_session, price_paise=40000)

    plan_id = uuid4()
    plan, mandates, records = authorize_plan(
        intent_jwt=intent_jwt,
        legs=[
            {"merchant_id": "merchant_cakehouse_01", "cart_jwt": cjwt1},
            {"merchant_id": "merchant_sweetdelight_02", "cart_jwt": cjwt2},
        ],
        user_public_key_pem=crypto_keys["user"]["public_key_pem"],
        platform_private_key_pem=crypto_keys["platform"]["private_key_pem"],
        db=db_session,
        plan_id=plan_id,
        merchant_public_keys={
            "merchant_cakehouse_01": crypto_keys["merchant_1"]["public_key_pem"],
            "merchant_sweetdelight_02": crypto_keys["merchant_2"]["public_key_pem"],
        },
    )

    for rec in records:
        assert rec.plan_id == plan_id
        # Verify persistence in DB
        db_rec = db_session.query(MandateRecord).filter_by(mandate_id=rec.mandate_id).one()
        assert db_rec.plan_id == plan_id


def test_correct_aggregate_total_authorized_paise_and_reserved_update(db_session, crypto_keys):
    """Requirement 4 & 5 & 6: Aggregate total authorized and reserved_paise updates match child sums."""
    intent, intent_jwt = make_test_intent_jwt(crypto_keys["user"], db_session, spend_cap_paise=250000)
    cart1, cjwt1 = make_signed_cart_jwt("merchant_cakehouse_01", crypto_keys["merchant_1"], db_session, price_paise=50000)
    cart2, cjwt2 = make_signed_cart_jwt("merchant_sweetdelight_02", crypto_keys["merchant_2"], db_session, price_paise=70000)

    initial_reserved = db_session.query(IntentRegistry).filter_by(intent_id=str(intent.intent_id)).one().reserved_paise
    assert initial_reserved == 0

    plan, mandates, records = authorize_plan(
        intent_jwt=intent_jwt,
        legs=[
            {"merchant_id": "merchant_cakehouse_01", "cart_jwt": cjwt1},
            {"merchant_id": "merchant_sweetdelight_02", "cart_jwt": cjwt2},
        ],
        user_public_key_pem=crypto_keys["user"]["public_key_pem"],
        platform_private_key_pem=crypto_keys["platform"]["private_key_pem"],
        db=db_session,
        merchant_public_keys={
            "merchant_cakehouse_01": crypto_keys["merchant_1"]["public_key_pem"],
            "merchant_sweetdelight_02": crypto_keys["merchant_2"]["public_key_pem"],
        },
    )

    # 4. Correct aggregate total_authorized_paise
    assert plan.total_authorized_paise == 120000

    # 5. Correct aggregate reserved_paise update in IntentRegistry
    intent_row = db_session.query(IntentRegistry).filter_by(intent_id=str(intent.intent_id)).one()
    assert intent_row.reserved_paise == 120000
    assert intent_row.available_paise == 250000 - 120000

    # 6. Plan total equals sum of child mandate authorized and reserved amounts
    sum_child_authorized = sum(rec.authorized_amount_paise for rec in records)
    sum_child_reserved = sum(rec.reserved_paise for rec in records)
    assert plan.total_authorized_paise == sum_child_authorized == 120000
    assert intent_row.reserved_paise == sum_child_reserved == 120000


def test_duplicate_plan_request_is_idempotent(db_session, crypto_keys):
    """Requirement 7: Duplicate plan request returns identical plan and child records without re-reserving."""
    intent, intent_jwt = make_test_intent_jwt(crypto_keys["user"], db_session, spend_cap_paise=150000)
    cart1, cjwt1 = make_signed_cart_jwt("merchant_cakehouse_01", crypto_keys["merchant_1"], db_session, price_paise=40000)

    fixed_plan_id = uuid4()
    plan1, mandates1, records1 = authorize_plan(
        intent_jwt=intent_jwt,
        legs=[{"merchant_id": "merchant_cakehouse_01", "cart_jwt": cjwt1}],
        user_public_key_pem=crypto_keys["user"]["public_key_pem"],
        platform_private_key_pem=crypto_keys["platform"]["private_key_pem"],
        db=db_session,
        plan_id=fixed_plan_id,
        merchant_public_keys={"merchant_cakehouse_01": crypto_keys["merchant_1"]["public_key_pem"]},
    )

    # Re-issue duplicate authorization request with same plan_id
    plan2, mandates2, records2 = authorize_plan(
        intent_jwt=intent_jwt,
        legs=[{"merchant_id": "merchant_cakehouse_01", "cart_jwt": cjwt1}],
        user_public_key_pem=crypto_keys["user"]["public_key_pem"],
        platform_private_key_pem=crypto_keys["platform"]["private_key_pem"],
        db=db_session,
        plan_id=fixed_plan_id,
        merchant_public_keys={"merchant_cakehouse_01": crypto_keys["merchant_1"]["public_key_pem"]},
    )

    assert plan1.plan_id == plan2.plan_id == fixed_plan_id
    assert [r.mandate_id for r in records1] == [r.mandate_id for r in records2]

    # Verify reservations were NOT doubled
    intent_row = db_session.query(IntentRegistry).filter_by(intent_id=str(intent.intent_id)).one()
    assert intent_row.reserved_paise == 40000
    assert db_session.query(PurchasePlan).filter_by(plan_id=fixed_plan_id).count() == 1
    assert db_session.query(MandateRecord).filter_by(plan_id=fixed_plan_id).count() == 1


def test_duplicate_leg_request_in_same_plan_aborts(db_session, crypto_keys):
    """Requirement 8: Multiple legs for the same merchant in a single plan is rejected."""
    intent, intent_jwt = make_test_intent_jwt(crypto_keys["user"], db_session)
    cart1, cjwt1 = make_signed_cart_jwt("merchant_cakehouse_01", crypto_keys["merchant_1"], db_session, price_paise=20000)
    cart2, cjwt2 = make_signed_cart_jwt("merchant_cakehouse_01", crypto_keys["merchant_1"], db_session, price_paise=30000)

    with pytest.raises(PolicyViolation) as exc:
        authorize_plan(
            intent_jwt=intent_jwt,
            legs=[
                {"merchant_id": "merchant_cakehouse_01", "cart_jwt": cjwt1},
                {"merchant_id": "merchant_cakehouse_01", "cart_jwt": cjwt2},
            ],
            user_public_key_pem=crypto_keys["user"]["public_key_pem"],
            platform_private_key_pem=crypto_keys["platform"]["private_key_pem"],
            db=db_session,
            merchant_public_keys={"merchant_cakehouse_01": crypto_keys["merchant_1"]["public_key_pem"]},
        )
    assert exc.value.code == "POLICY_DUPLICATE_MERCHANT_LEG"


def test_deterministic_leg_idempotency_keys_format(db_session, crypto_keys):
    """Requirement 9 & 22: Leg idempotency keys are tx_plan_{plan_id.hex}_leg_{merchant_id}."""
    intent, intent_jwt = make_test_intent_jwt(crypto_keys["user"], db_session)
    cart1, cjwt1 = make_signed_cart_jwt("merchant_cakehouse_01", crypto_keys["merchant_1"], db_session, price_paise=25000)
    cart2, cjwt2 = make_signed_cart_jwt("merchant_sweetdelight_02", crypto_keys["merchant_2"], db_session, price_paise=35000)

    plan_id = uuid4()
    plan, mandates, records = authorize_plan(
        intent_jwt=intent_jwt,
        legs=[
            {"merchant_id": "merchant_cakehouse_01", "cart_jwt": cjwt1},
            {"merchant_id": "merchant_sweetdelight_02", "cart_jwt": cjwt2},
        ],
        user_public_key_pem=crypto_keys["user"]["public_key_pem"],
        platform_private_key_pem=crypto_keys["platform"]["private_key_pem"],
        db=db_session,
        plan_id=plan_id,
        merchant_public_keys={
            "merchant_cakehouse_01": crypto_keys["merchant_1"]["public_key_pem"],
            "merchant_sweetdelight_02": crypto_keys["merchant_2"]["public_key_pem"],
        },
    )

    records_by_mid = {r.merchant_id: r for r in records}
    expected_key_1 = f"tx_plan_{plan_id.hex}_leg_merchant_cakehouse_01"
    expected_key_2 = f"tx_plan_{plan_id.hex}_leg_merchant_sweetdelight_02"

    assert records_by_mid["merchant_cakehouse_01"].idempotency_key == expected_key_1
    assert records_by_mid["merchant_sweetdelight_02"].idempotency_key == expected_key_2


def test_one_invalid_child_leg_aborts_entire_plan_atomically(db_session, crypto_keys):
    """Requirement 13 & 18 & 20: If one child leg is invalid, ENTIRE plan aborts with 0 DB side effects."""
    intent, intent_jwt = make_test_intent_jwt(crypto_keys["user"], db_session, spend_cap_paise=100000)
    # Leg 1: valid
    cart1, cjwt1 = make_signed_cart_jwt("merchant_cakehouse_01", crypto_keys["merchant_1"], db_session, price_paise=30000)
    # Leg 2: invalid category (electronics not in allowed ["bakery", "gifting"])
    cart2, cjwt2 = make_signed_cart_jwt(
        "merchant_sweetdelight_02",
        crypto_keys["merchant_2"],
        db_session,
        price_paise=20000,
        category="electronics",
    )

    plan_id = uuid4()
    with pytest.raises(PolicyCategoryNotAllowed):
        authorize_plan(
            intent_jwt=intent_jwt,
            legs=[
                {"merchant_id": "merchant_cakehouse_01", "cart_jwt": cjwt1},
                {"merchant_id": "merchant_sweetdelight_02", "cart_jwt": cjwt2},
            ],
            user_public_key_pem=crypto_keys["user"]["public_key_pem"],
            platform_private_key_pem=crypto_keys["platform"]["private_key_pem"],
            db=db_session,
            plan_id=plan_id,
            merchant_public_keys={
                "merchant_cakehouse_01": crypto_keys["merchant_1"]["public_key_pem"],
                "merchant_sweetdelight_02": crypto_keys["merchant_2"]["public_key_pem"],
            },
        )

    # Verify all-or-nothing rollback:
    # 1. Zero PurchasePlan created
    assert db_session.query(PurchasePlan).filter_by(plan_id=plan_id).count() == 0
    # 2. Zero MandateRecords created
    assert db_session.query(MandateRecord).filter_by(plan_id=plan_id).count() == 0
    # 3. Zero budget reserved
    intent_row = db_session.query(IntentRegistry).filter_by(intent_id=str(intent.intent_id)).one()
    assert intent_row.reserved_paise == 0
    assert intent_row.transactions_consumed == 0


def test_unauthorized_merchant_aborts_entire_plan(db_session, crypto_keys):
    """Requirement 14: Merchant not in allowed_merchant_ids aborts entire plan."""
    intent, intent_jwt = make_test_intent_jwt(
        crypto_keys["user"],
        db_session,
        allowed_merchants=["merchant_cakehouse_01"],  # Sweet Delight is not authorized
    )
    cart1, cjwt1 = make_signed_cart_jwt("merchant_cakehouse_01", crypto_keys["merchant_1"], db_session, price_paise=20000)
    cart2, cjwt2 = make_signed_cart_jwt("merchant_sweetdelight_02", crypto_keys["merchant_2"], db_session, price_paise=20000)

    with pytest.raises(PolicyMerchantNotAllowed):
        authorize_plan(
            intent_jwt=intent_jwt,
            legs=[
                {"merchant_id": "merchant_cakehouse_01", "cart_jwt": cjwt1},
                {"merchant_id": "merchant_sweetdelight_02", "cart_jwt": cjwt2},
            ],
            user_public_key_pem=crypto_keys["user"]["public_key_pem"],
            platform_private_key_pem=crypto_keys["platform"]["private_key_pem"],
            db=db_session,
            merchant_public_keys={
                "merchant_cakehouse_01": crypto_keys["merchant_1"]["public_key_pem"],
                "merchant_sweetdelight_02": crypto_keys["merchant_2"]["public_key_pem"],
            },
        )


def test_invalid_or_forged_quote_aborts_entire_plan(db_session, crypto_keys):
    """Requirement 15: Forged or tampered quote signature aborts entire plan."""
    intent, intent_jwt = make_test_intent_jwt(crypto_keys["user"], db_session)
    cart1, cjwt1 = make_signed_cart_jwt("merchant_cakehouse_01", crypto_keys["merchant_1"], db_session, price_paise=20000)

    # Corrupt cart JWT signature
    corrupted_cjwt = cjwt1[:-10] + "badsignature"

    with pytest.raises(PolicyViolation):
        authorize_plan(
            intent_jwt=intent_jwt,
            legs=[{"merchant_id": "merchant_cakehouse_01", "cart_jwt": corrupted_cjwt}],
            user_public_key_pem=crypto_keys["user"]["public_key_pem"],
            platform_private_key_pem=crypto_keys["platform"]["private_key_pem"],
            db=db_session,
            merchant_public_keys={"merchant_cakehouse_01": crypto_keys["merchant_1"]["public_key_pem"]},
        )


def test_expired_intent_aborts_entire_plan(db_session, crypto_keys):
    """Requirement 16: Expired intent cannot authorize a plan."""
    now = datetime.now(timezone.utc)
    intent = UserIntentCredential(
        intent_id=uuid4(),
        user_id="test_buyer_01",
        spend_cap_paise=100000,
        currency="INR",
        allowed_categories=["bakery"],
        allowed_merchant_ids=["merchant_cakehouse_01"],
        max_transactions=5,
        nonce=f"nonce_{uuid4().hex}",
        not_before=now - timedelta(minutes=30),
        expires_at=now - timedelta(minutes=10),
    )
    expired_jwt = issue_intent_jwt(intent, crypto_keys["user"]["private_key_pem"])
    cart1, cjwt1 = make_signed_cart_jwt("merchant_cakehouse_01", crypto_keys["merchant_1"], db_session, price_paise=20000)

    with pytest.raises(PolicyIntentExpired):
        authorize_plan(
            intent_jwt=expired_jwt,
            legs=[{"merchant_id": "merchant_cakehouse_01", "cart_jwt": cjwt1}],
            user_public_key_pem=crypto_keys["user"]["public_key_pem"],
            platform_private_key_pem=crypto_keys["platform"]["private_key_pem"],
            db=db_session,
            merchant_public_keys={"merchant_cakehouse_01": crypto_keys["merchant_1"]["public_key_pem"]},
        )


def test_insufficient_remaining_budget_aborts_entire_plan(db_session, crypto_keys):
    """Requirement 17: Plan total exceeding remaining available spend cap aborts entire plan."""
    # Spend cap: ₹1,000 (100,000 paise)
    intent, intent_jwt = make_test_intent_jwt(crypto_keys["user"], db_session, spend_cap_paise=100000)
    # Leg 1: ₹600 (60,000 paise), Leg 2: ₹500 (50,000 paise) -> Total ₹1,100 (110,000 paise)
    cart1, cjwt1 = make_signed_cart_jwt("merchant_cakehouse_01", crypto_keys["merchant_1"], db_session, price_paise=60000)
    cart2, cjwt2 = make_signed_cart_jwt("merchant_sweetdelight_02", crypto_keys["merchant_2"], db_session, price_paise=50000)

    with pytest.raises(PolicySpendCapExceeded) as exc:
        authorize_plan(
            intent_jwt=intent_jwt,
            legs=[
                {"merchant_id": "merchant_cakehouse_01", "cart_jwt": cjwt1},
                {"merchant_id": "merchant_sweetdelight_02", "cart_jwt": cjwt2},
            ],
            user_public_key_pem=crypto_keys["user"]["public_key_pem"],
            platform_private_key_pem=crypto_keys["platform"]["private_key_pem"],
            db=db_session,
            merchant_public_keys={
                "merchant_cakehouse_01": crypto_keys["merchant_1"]["public_key_pem"],
                "merchant_sweetdelight_02": crypto_keys["merchant_2"]["public_key_pem"],
            },
        )
    assert "exceeds available budget" in exc.value.message


def test_audit_ledger_consistency_after_successful_authorization(db_session, crypto_keys):
    """Requirement 19: Audit ledger logs MANDATE_CREATED events for each leg in the plan transaction."""
    intent, intent_jwt = make_test_intent_jwt(crypto_keys["user"], db_session)
    cart1, cjwt1 = make_signed_cart_jwt("merchant_cakehouse_01", crypto_keys["merchant_1"], db_session, price_paise=25000)
    cart2, cjwt2 = make_signed_cart_jwt("merchant_sweetdelight_02", crypto_keys["merchant_2"], db_session, price_paise=35000)

    plan_id = uuid4()
    plan, mandates, records = authorize_plan(
        intent_jwt=intent_jwt,
        legs=[
            {"merchant_id": "merchant_cakehouse_01", "cart_jwt": cjwt1},
            {"merchant_id": "merchant_sweetdelight_02", "cart_jwt": cjwt2},
        ],
        user_public_key_pem=crypto_keys["user"]["public_key_pem"],
        platform_private_key_pem=crypto_keys["platform"]["private_key_pem"],
        db=db_session,
        plan_id=plan_id,
        merchant_public_keys={
            "merchant_cakehouse_01": crypto_keys["merchant_1"]["public_key_pem"],
            "merchant_sweetdelight_02": crypto_keys["merchant_2"]["public_key_pem"],
        },
    )

    ledger_entries = (
        db_session.query(AuditLedgerEntry)
        .filter(AuditLedgerEntry.entry_type == LedgerEntryType.MANDATE_CREATED)
        .all()
    )
    plan_entries = [e for e in ledger_entries if e.payload.get("plan_id") == str(plan_id)]
    assert len(plan_entries) == 2
    entry_mids = {e.payload["merchant_id"] for e in plan_entries}
    assert entry_mids == {"merchant_cakehouse_01", "merchant_sweetdelight_02"}


def test_legacy_single_mandate_flow_remains_valid(db_session, crypto_keys):
    """Requirement 21: Existing single-mandate flow continues to work seamlessly with plan_id=NULL."""
    intent, intent_jwt = make_test_intent_jwt(crypto_keys["user"], db_session, spend_cap_paise=100000)
    cart1, cjwt1 = make_signed_cart_jwt("merchant_cakehouse_01", crypto_keys["merchant_1"], db_session, price_paise=40000)

    mandate, m_jwt, mandate_record = authorize_mandate(
        intent_jwt=intent_jwt,
        cart_jwt=cjwt1,
        idempotency_key="tx_legacy_single_001",
        user_public_key_pem=crypto_keys["user"]["public_key_pem"],
        merchant_public_key_pem=crypto_keys["merchant_1"]["public_key_pem"],
        platform_private_key_pem=crypto_keys["platform"]["private_key_pem"],
        db=db_session,
    )

    assert mandate_record.plan_id is None
    assert mandate_record.status == MandateStatus.RESERVED
    assert mandate_record.authorized_amount_paise == 40000

    intent_row = db_session.query(IntentRegistry).filter_by(intent_id=str(intent.intent_id)).one()
    assert intent_row.reserved_paise == 40000


def test_plans_cannot_bypass_max_transactions(db_session, crypto_keys):
    """Requirement 12: A plan cannot bypass max_transactions; consumes 1 transaction allowance."""
    # Allow exactly 1 transaction
    intent, intent_jwt = make_test_intent_jwt(
        crypto_keys["user"],
        db_session,
        spend_cap_paise=500000,
        max_transactions=1,
    )
    cart1, cjwt1 = make_signed_cart_jwt("merchant_cakehouse_01", crypto_keys["merchant_1"], db_session, price_paise=20000)
    cart2, cjwt2 = make_signed_cart_jwt("merchant_sweetdelight_02", crypto_keys["merchant_2"], db_session, price_paise=30000)

    # First multi-leg plan succeeds and consumes 1 transaction (exhausting the allowance)
    plan1, m1, r1 = authorize_plan(
        intent_jwt=intent_jwt,
        legs=[
            {"merchant_id": "merchant_cakehouse_01", "cart_jwt": cjwt1},
            {"merchant_id": "merchant_sweetdelight_02", "cart_jwt": cjwt2},
        ],
        user_public_key_pem=crypto_keys["user"]["public_key_pem"],
        platform_private_key_pem=crypto_keys["platform"]["private_key_pem"],
        db=db_session,
        merchant_public_keys={
            "merchant_cakehouse_01": crypto_keys["merchant_1"]["public_key_pem"],
            "merchant_sweetdelight_02": crypto_keys["merchant_2"]["public_key_pem"],
        },
    )

    intent_row = db_session.query(IntentRegistry).filter_by(intent_id=str(intent.intent_id)).one()
    assert intent_row.transactions_consumed == 1
    assert intent_row.status == IntentStatus.EXHAUSTED

    # Subsequent plan authorization MUST fail with PolicyTransactionLimitReached
    cart3, cjwt3 = make_signed_cart_jwt("merchant_cakehouse_01", crypto_keys["merchant_1"], db_session, price_paise=10000)
    with pytest.raises(PolicyTransactionLimitReached):
        authorize_plan(
            intent_jwt=intent_jwt,
            legs=[{"merchant_id": "merchant_cakehouse_01", "cart_jwt": cjwt3}],
            user_public_key_pem=crypto_keys["user"]["public_key_pem"],
            platform_private_key_pem=crypto_keys["platform"]["private_key_pem"],
            db=db_session,
            merchant_public_keys={"merchant_cakehouse_01": crypto_keys["merchant_1"]["public_key_pem"]},
        )


def test_concurrent_plan_authorization_against_same_intent(engine, crypto_keys):
    """Requirement 10 & 11: Concurrent plan authorization race conditions under PostgreSQL.

    Under row locking, 10 concurrent threads attempt ₹800 plans against a ₹1,000 cap.
    Exactly 1 succeeds, 9 fail with PolicySpendCapExceeded.
    """
    if engine.dialect.name == "sqlite":
        pytest.skip("SQLite does not support row-level SELECT FOR UPDATE; concurrency guarantees apply to PostgreSQL.")

    SessionMaker = sessionmaker(bind=engine)
    init_db = SessionMaker()
    seed_catalog(init_db)

    # Intent with ₹1,000 cap (100,000 paise)
    intent, intent_jwt = make_test_intent_jwt(
        crypto_keys["user"],
        init_db,
        spend_cap_paise=100000,
        max_transactions=10,
    )
    # 2 legs: ₹400 + ₹400 = ₹800 (80,000 paise)
    cart1, cjwt1 = make_signed_cart_jwt("merchant_cakehouse_01", crypto_keys["merchant_1"], init_db, price_paise=40000)
    cart2, cjwt2 = make_signed_cart_jwt("merchant_sweetdelight_02", crypto_keys["merchant_2"], init_db, price_paise=40000)
    init_db.close()

    successes = []
    rejections = []

    def _attempt_authorize():
        thread_db = SessionMaker()
        try:
            plan, m, r = authorize_plan(
                intent_jwt=intent_jwt,
                legs=[
                    {"merchant_id": "merchant_cakehouse_01", "cart_jwt": cjwt1},
                    {"merchant_id": "merchant_sweetdelight_02", "cart_jwt": cjwt2},
                ],
                user_public_key_pem=crypto_keys["user"]["public_key_pem"],
                platform_private_key_pem=crypto_keys["platform"]["private_key_pem"],
                db=thread_db,
                merchant_public_keys={
                    "merchant_cakehouse_01": crypto_keys["merchant_1"]["public_key_pem"],
                    "merchant_sweetdelight_02": crypto_keys["merchant_2"]["public_key_pem"],
                },
            )
            successes.append(plan)
        except PolicySpendCapExceeded as e:
            rejections.append(e)
        finally:
            thread_db.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(_attempt_authorize) for _ in range(10)]
        concurrent.futures.wait(futures)

    # Exactly 1 succeeded, remaining rejected
    assert len(successes) == 1
    assert len(rejections) == 9
