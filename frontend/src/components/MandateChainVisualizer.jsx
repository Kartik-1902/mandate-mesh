import React, { useState } from 'react';
import { Layers, Key, ShieldCheck, Check, ArrowRight, Zap, Terminal } from 'lucide-react';
import { simulateCapture } from '../services/api';

export default function MandateChainVisualizer({ activeMandate, onCaptureSuccess, onLedgerChange }) {
  const [selectedHop, setSelectedHop] = useState('mandate');
  const [capturing, setCapturing] = useState(false);
  const [receiptData, setReceiptData] = useState(null);

  const handleCapture = async () => {
    if (!activeMandate?.razorpay_order_id) return;
    setCapturing(true);
    try {
      const res = await simulateCapture(
        activeMandate.razorpay_order_id,
        activeMandate.authorized_amount_paise || 94000
      );
      setReceiptData(res);
      if (onCaptureSuccess) {
        onCaptureSuccess(res);
      }
      if (onLedgerChange) {
        onLedgerChange();
      }
    } catch (err) {
      alert(`Capture webhook failure: ${err.message}`);
    } finally {
      setCapturing(false);
    }
  };

  const hops = [
    {
      id: 'intent',
      stepNum: '01',
      title: 'USER INTENT CREDENTIAL',
      signer: 'CLIENT NIST P-256',
      status: activeMandate ? 'VERIFIED' : 'STANDBY',
      details: {
        credential_type: 'UserIntentCredential (JWT)',
        signer_key: 'user:client-key-01',
        spend_cap: activeMandate ? `₹${(activeMandate.authorized_amount_paise / 100).toFixed(2)}` : '₹1500.00',
        authorized_merchants: ['merchant_cakehouse_01'],
        intent_sha256: activeMandate?.intent_hash || 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
      },
    },
    {
      id: 'cart',
      stepNum: '02',
      title: 'MERCHANT SIGNED CART',
      signer: 'MERCHANT SECP256K1',
      status: activeMandate ? 'VERIFIED' : 'STANDBY',
      details: {
        credential_type: 'MerchantSignedCart (JWT)',
        signer_key: 'merchant:key-cakehouse-01',
        pricing_engine: 'Authoritative SQLite Catalog (Zero LLM price input)',
        cart_sha256: activeMandate?.cart_hash || 'b7e2a48f0a1c3d9e8b7a6f5e4d3c2b1a0f9e8d7c6b5a4f3e2d1c0b9a8f7e6d5c',
      },
    },
    {
      id: 'mandate',
      stepNum: '03',
      title: 'PAYMENT MANDATE',
      signer: 'PLATFORM PLAT-KEY-01',
      status: activeMandate ? 'AUTHORIZED' : 'STANDBY',
      details: {
        credential_type: 'PaymentMandate (FSM Active)',
        signer_key: 'platform:core-signing-key',
        mandate_id: activeMandate?.mandate_id || 'PENDING_AUTHORIZATION',
        bound_cart_hash: activeMandate?.cart_hash || 'PENDING',
        bound_intent_hash: activeMandate?.intent_hash || 'PENDING',
        authorized_ceiling: activeMandate ? `₹${(activeMandate.authorized_amount_paise / 100).toFixed(2)}` : 'PENDING',
      },
    },
    {
      id: 'order',
      stepNum: '04',
      title: 'RAZORPAY ORDER',
      signer: 'GATEWAY TEST HARNESS',
      status: activeMandate?.razorpay_order_id ? 'CREATED' : 'STANDBY',
      details: {
        gateway_entity: 'Razorpay Orders API (orders.create)',
        razorpay_order_id: activeMandate?.razorpay_order_id || 'PENDING_CREATION',
        receipt_reference: activeMandate?.receipt_reference || `mm_${activeMandate?.mandate_id?.replace(/-/g, '') || ''}`,
        currency_code: 'INR',
      },
    },
    {
      id: 'receipt',
      stepNum: '05',
      title: 'PAYMENT RECEIPT',
      signer: 'PLATFORM AUDIT PROOF',
      status: receiptData ? 'CAPTURED' : (activeMandate?.razorpay_order_id ? 'AWAITING_WEBHOOK' : 'STANDBY'),
      details: {
        proof_type: 'PaymentReceipt (Platform Signed Proof)',
        receipt_id: receiptData?.receipt_id || 'AWAITING_PAYMENT_CAPTURED_EVENT',
        settlement_timestamp: receiptData?.receipt?.captured_at || 'PENDING',
        hash_audit_trace: 'intent_hash -> cart_hash -> mandate_id -> razorpay_payment_id',
      },
    },
  ];

  const currentHopData = hops.find((h) => h.id === selectedHop) || hops[2];

  return (
    <div className="panel-card" style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
      
      {/* Panel Header & Webhook Simulation Trigger */}
      <div className="panel-card-header" style={{ marginBottom: 0 }}>
        <div className="panel-title">
          <Layers size={16} color="var(--text-phosphor)" />
          <span>CRYPTOGRAPHIC MANDATE CHAIN // 5-HOP STATE PIPELINE</span>
        </div>

        {activeMandate?.razorpay_order_id && !receiptData && (
          <button
            className="btn btn-success"
            onClick={handleCapture}
            disabled={capturing}
            style={{ fontSize: '0.72rem', padding: '4px 10px' }}
          >
            {capturing ? 'SETTLING WEBHOOK...' : '[ EMIT: PAYMENT.CAPTURED WEBHOOK ]'}
          </button>
        )}
      </div>

      {/* 5-Hop Hardware Register Sequence */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: '6px' }}>
        {hops.map((hop) => {
          const isSelected = selectedHop === hop.id;
          const isVerified = hop.status === 'VERIFIED' || hop.status === 'AUTHORIZED' || hop.status === 'CREATED' || hop.status === 'CAPTURED';

          return (
            <button
              key={hop.id}
              onClick={() => setSelectedHop(hop.id)}
              style={{
                background: isSelected ? 'var(--bg-surface)' : 'var(--bg-recessed)',
                border: isSelected ? '1px solid var(--text-phosphor)' : '1px solid var(--border-line)',
                borderTop: isVerified ? '3px solid var(--accent-terminal)' : '1px solid var(--border-line)',
                padding: '10px 8px',
                textAlign: 'left',
                display: 'flex',
                flexDirection: 'column',
                gap: '6px',
                cursor: 'pointer',
                transition: 'none',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: '0.65rem', color: 'var(--text-muted)', fontWeight: 800 }}>
                  REGISTER {hop.stepNum}
                </span>
                <span
                  style={{
                    fontSize: '0.62rem',
                    fontWeight: 700,
                    color: isVerified ? 'var(--accent-terminal)' : 'var(--text-dim)',
                  }}
                >
                  [{hop.status}]
                </span>
              </div>

              <div style={{ fontSize: '0.72rem', fontWeight: 800, color: 'var(--text-phosphor)', lineHeight: 1.2 }}>
                {hop.title}
              </div>

              <div style={{ fontSize: '0.62rem', color: 'var(--text-muted)' }}>
                {hop.signer}
              </div>
            </button>
          );
        })}
      </div>

      {/* Register Telemetry Inspection Window */}
      <div style={{
        background: 'var(--bg-recessed)',
        border: '1px solid var(--border-line)',
        padding: '12px',
        display: 'flex',
        flexDirection: 'column',
        gap: '8px',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid var(--border-dim)', paddingBottom: '6px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <Terminal size={14} color="var(--text-muted)" />
            <span style={{ fontSize: '0.72rem', fontWeight: 800, color: 'var(--text-phosphor)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
              REGISTER INSPECTOR // {currentHopData.title}
            </span>
          </div>
          <span className="badge badge-steel" style={{ fontSize: '0.65rem' }}>
            SIGNER: {currentHopData.signer}
          </span>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '8px', fontSize: '0.72rem' }}>
          {Object.entries(currentHopData.details).map(([k, v]) => (
            <div key={k} style={{ display: 'flex', flexDirection: 'column', gap: '2px', background: 'var(--bg-terminal)', padding: '6px 8px', border: '1px solid var(--border-dim)' }}>
              <span style={{ color: 'var(--text-muted)', fontSize: '0.65rem', textTransform: 'uppercase' }}>
                {k.replace(/_/g, ' ')}:
              </span>
              <span style={{
                color: 'var(--text-phosphor)',
                fontWeight: 600,
                wordBreak: 'break-all',
                fontFamily: 'var(--font-mono)',
              }}>
                {Array.isArray(v) ? v.join(', ') : String(v)}
              </span>
            </div>
          ))}
        </div>
      </div>

    </div>
  );
}
