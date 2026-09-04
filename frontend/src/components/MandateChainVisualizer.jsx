import React, { useState } from 'react';
import { Layers, Terminal, CheckCircle2, Copy, Check, ShieldCheck, Zap, Lock } from 'lucide-react';
import { simulateCapture } from '../services/api';

export default function MandateChainVisualizer({ activeMandate, onCaptureSuccess, onLedgerChange }) {
  const [selectedHop, setSelectedHop] = useState('mandate');
  const [capturing, setCapturing] = useState(false);
  const [receiptData, setReceiptData] = useState(null);
  const [copiedKey, setCopiedKey] = useState(null);

  const handleCopy = (key, text) => {
    navigator.clipboard.writeText(text);
    setCopiedKey(key);
    setTimeout(() => setCopiedKey(null), 1800);
  };

  const handleCapture = async () => {
    if (!activeMandate?.razorpay_order_id) return;
    setCapturing(true);
    try {
      const res = await simulateCapture(
        activeMandate.razorpay_order_id,
        activeMandate.authorized_amount_paise || 94000
      );
      setReceiptData(res);
      setSelectedHop('receipt');
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
      num: '01',
      title: 'USER INTENT',
      signer: 'NIST P-256 (User)',
      status: activeMandate ? 'VERIFIED' : 'STANDBY',
      summary: activeMandate ? `Cap: ₹${(activeMandate.authorized_amount_paise / 100).toFixed(2)}` : 'Cap: ₹1500',
      details: {
        credential: 'UserIntentCredential (JWT)',
        signer_key: 'user:client-key-01',
        intent_sha256: activeMandate?.intent_hash || 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
      },
    },
    {
      id: 'cart',
      num: '02',
      title: 'SIGNED CART',
      signer: 'SECP256K1 (Merchant)',
      status: activeMandate ? 'VERIFIED' : 'STANDBY',
      summary: activeMandate ? 'Authoritative DB' : 'Catalog Price',
      details: {
        credential: 'MerchantSignedCart (JWT)',
        signer_key: 'merchant:key-cakehouse-01',
        cart_sha256: activeMandate?.cart_hash || 'b7e2a48f0a1c3d9e8b7a6f5e4d3c2b1a0f9e8d7c6b5a4f3e2d1c0b9a8f7e6d5c',
      },
    },
    {
      id: 'mandate',
      num: '03',
      title: 'MANDATE',
      signer: 'PLATFORM (Core)',
      status: activeMandate ? 'AUTHORIZED' : 'STANDBY',
      summary: activeMandate?.mandate_id ? `${activeMandate.mandate_id.substring(0, 8)}...` : 'Pending Auth',
      details: {
        credential: 'PaymentMandate (FSM ACTIVE)',
        mandate_id: activeMandate?.mandate_id || 'PENDING_AUTHORIZATION',
        bound_cart_hash: activeMandate?.cart_hash || 'PENDING',
        bound_intent_hash: activeMandate?.intent_hash || 'PENDING',
      },
    },
    {
      id: 'order',
      num: '04',
      title: 'RAZORPAY',
      signer: 'GATEWAY (Test)',
      status: activeMandate?.razorpay_order_id ? 'CREATED' : 'STANDBY',
      summary: activeMandate?.razorpay_order_id || 'Pending Order',
      details: {
        gateway_order: activeMandate?.razorpay_order_id || 'PENDING_ORDER_CREATION',
        receipt_reference: activeMandate?.receipt_reference || 'PENDING',
        currency: 'INR',
      },
    },
    {
      id: 'receipt',
      num: '05',
      title: 'RECEIPT',
      signer: 'PLATFORM (Proof)',
      status: receiptData ? 'SETTLED' : (activeMandate?.razorpay_order_id ? 'AWAITING' : 'STANDBY'),
      summary: receiptData ? 'Settled & Issued' : 'Awaiting Webhook',
      details: {
        proof_type: 'PaymentReceipt (Platform Signed Proof)',
        receipt_id: receiptData?.receipt_id || 'AWAITING_PAYMENT_CAPTURED_WEBHOOK',
        captured_at: receiptData?.receipt?.captured_at || 'PENDING',
      },
    },
  ];

  const currentHopData = hops.find((h) => h.id === selectedHop) || hops[2];

  return (
    <div className="panel-card" style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
      
      {/* Header with Live Action Trigger */}
      <div className="panel-card-header" style={{ marginBottom: 0, paddingBottom: '6px' }}>
        <div className="panel-title">
          <Layers size={14} color="var(--text-phosphor)" />
          <span>CRYPTOGRAPHIC STATE PIPELINE // 5-HOP ZERO-TRUST CHAIN</span>
        </div>

        {activeMandate?.razorpay_order_id && !receiptData && (
          <button
            className="btn btn-success"
            onClick={handleCapture}
            disabled={capturing}
            style={{ fontSize: '0.68rem', padding: '3px 10px', gap: '6px' }}
          >
            <Zap size={11} className={capturing ? 'animate-spin' : ''} />
            {capturing ? 'SETTLING WEBHOOK...' : '[ EMIT: PAYMENT.CAPTURED WEBHOOK ]'}
          </button>
        )}

        {receiptData && (
          <span className="badge badge-green" style={{ fontSize: '0.65rem', padding: '2px 6px' }}>
            <CheckCircle2 size={11} />
            SETTLEMENT PROOF ISSUED
          </span>
        )}
      </div>

      {/* 5-Hop Step-Through Pipeline Rail */}
      <div style={{ position: 'relative', display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: '4px' }}>
        {hops.map((hop) => {
          const isSelected = selectedHop === hop.id;
          const isVerified = hop.status === 'VERIFIED' || hop.status === 'AUTHORIZED' || hop.status === 'CREATED' || hop.status === 'SETTLED';

          return (
            <button
              key={hop.id}
              onClick={() => setSelectedHop(hop.id)}
              style={{
                background: isSelected ? 'var(--bg-surface)' : 'var(--bg-recessed)',
                border: isSelected ? '1px solid var(--text-phosphor)' : '1px solid var(--border-line)',
                borderTop: isVerified ? '2px solid var(--accent-terminal)' : '1px solid var(--border-line)',
                padding: '6px 8px',
                textAlign: 'left',
                display: 'flex',
                flexDirection: 'column',
                gap: '2px',
                cursor: 'pointer',
                transition: 'all 0.15s ease',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: '0.62rem', color: isSelected ? 'var(--text-phosphor)' : 'var(--text-muted)', fontWeight: 800 }}>
                  {hop.num} {hop.title}
                </span>
                <span
                  style={{
                    fontSize: '0.58rem',
                    fontWeight: 700,
                    color: isVerified ? 'var(--accent-terminal)' : 'var(--text-dim)',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '2px',
                  }}
                >
                  {isVerified && <Check size={9} />}
                  [{hop.status}]
                </span>
              </div>
              <span style={{ fontSize: '0.65rem', color: isVerified ? 'var(--text-phosphor)' : 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}>
                {hop.summary}
              </span>
            </button>
          );
        })}
      </div>

      {/* Interactive Telemetry & Cryptographic Seal Inspector */}
      {currentHopData && (
        <div style={{
          background: 'var(--bg-terminal)',
          border: '1px solid var(--border-line)',
          padding: '8px 10px',
          display: 'flex',
          flexDirection: 'column',
          gap: '6px',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid var(--border-dim)', paddingBottom: '4px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <ShieldCheck size={12} color="var(--accent-terminal)" />
              <span style={{ fontSize: '0.68rem', fontWeight: 700, color: 'var(--text-phosphor)', textTransform: 'uppercase' }}>
                REGISTER {currentHopData.num}: {currentHopData.title}
              </span>
            </div>
            <span style={{ fontSize: '0.62rem', color: 'var(--text-muted)' }}>
              ATTESTED SIGNER: <strong style={{ color: 'var(--text-secondary)' }}>{currentHopData.signer}</strong>
            </span>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '6px' }}>
            {Object.entries(currentHopData.details).map(([k, v]) => (
              <div
                key={k}
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  background: 'var(--bg-recessed)',
                  padding: '4px 8px',
                  border: '1px solid var(--border-dim)',
                  fontSize: '0.68rem',
                }}
              >
                <div style={{ display: 'flex', flexDirection: 'column', overflow: 'hidden', marginRight: '6px' }}>
                  <span style={{ color: 'var(--text-muted)', fontSize: '0.6rem', textTransform: 'uppercase' }}>
                    {k.replace(/_/g, ' ')}
                  </span>
                  <span style={{
                    color: 'var(--text-phosphor)',
                    fontFamily: 'var(--font-mono)',
                    fontWeight: 600,
                    textOverflow: 'ellipsis',
                    overflow: 'hidden',
                    whiteSpace: 'nowrap',
                  }}>
                    {String(v)}
                  </span>
                </div>

                <button
                  className="btn btn-secondary"
                  onClick={() => handleCopy(k, String(v))}
                  style={{
                    padding: '2px 5px',
                    fontSize: '0.58rem',
                    flexShrink: 0,
                    background: copiedKey === k ? 'var(--accent-terminal-dim)' : 'transparent',
                    borderColor: copiedKey === k ? 'var(--accent-terminal)' : 'var(--border-line)',
                    color: copiedKey === k ? 'var(--accent-terminal)' : 'var(--text-muted)',
                  }}
                  title="Copy parameter to clipboard"
                >
                  {copiedKey === k ? <Check size={10} /> : <Copy size={10} />}
                  <span>{copiedKey === k ? 'COPIED' : 'COPY'}</span>
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

    </div>
  );
}
