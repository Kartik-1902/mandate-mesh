/**
 * Mandate Mesh API Service
 * Connects Control Tower UI to FastAPI backend endpoints.
 */

const API_BASE = "http://localhost:8000/api/v1";

export async function deliberateGoal(goal, initialBudgetPaise = null, allowedMerchantIds = null) {
  const payload = {
    goal,
    initial_budget_paise: initialBudgetPaise,
  };
  if (allowedMerchantIds && allowedMerchantIds.length > 0) {
    payload.allowed_merchant_ids = allowedMerchantIds;
  }

  const res = await fetch(`${API_BASE}/agent/deliberate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.error?.message || err.detail || "Agent deliberation failed");
  }
  return res.json();
}

export async function escalateAndPay(cartJwt, approvedBudgetPaise, userId = "user_control_tower_01", merchantId = null) {
  const payload = {
    cart_jwt: cartJwt,
    approved_budget_paise: approvedBudgetPaise,
    user_id: userId,
  };
  if (merchantId) {
    payload.merchant_id = merchantId;
  }
  const res = await fetch(`${API_BASE}/agent/escalate-and-pay`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.error?.message || err.detail || "Budget escalation authorization failed");
  }
  return res.json();
}

export async function triggerAttack(attackId) {
  const res = await fetch(`${API_BASE}/demo/attack/${attackId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.error?.message || err.detail || `Attack ${attackId} execution failed`);
  }
  return res.json();
}

export async function simulateCapture(razorpayOrderId, amountPaise) {
  const res = await fetch(`${API_BASE}/demo/simulate-capture`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      razorpay_order_id: razorpayOrderId,
      amount_paise: amountPaise,
      webhook_secret: "whsec_demo_secret",
    }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.error?.message || err.detail || "Webhook capture simulation failed");
  }
  return res.json();
}

export async function getLedgerEntries(limit = 20) {
  const res = await fetch(`${API_BASE}/ledger/entries?limit=${limit}`);
  if (!res.ok) throw new Error("Failed to fetch audit ledger entries");
  return res.json();
}

export async function verifyLedgerChain() {
  const res = await fetch(`${API_BASE}/ledger/verify-chain`);
  if (!res.ok) throw new Error("Failed to verify audit ledger chain");
  return res.json();
}

export async function getCatalog(merchantId = "merchant_cakehouse_01") {
  const res = await fetch(`${API_BASE}/merchant/catalog?merchant_id=${merchantId}`);
  if (!res.ok) throw new Error("Failed to fetch merchant catalog");
  return res.json();
}
