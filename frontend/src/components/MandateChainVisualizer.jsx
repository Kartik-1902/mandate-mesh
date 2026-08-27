import React, { useState } from 'react';
import { Layers, Key, FileCheck, Check, ArrowRight, ExternalLink, ShieldCheck, Zap } from 'lucide-react';
import { simulateCapture } from '../services/api';

export default function MandateChainVisualizer({ activeMandate, onCaptureSuccess, onLedgerChange }) {
  const [selectedHop, setSelectedHop] = useState(null);
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
      alert(`Webhook capture failed: ${err.message}`);
    } finally {
      setCapturing(false);
    }
  };

  const hops = [
    {
      id: 'intent',
      title: '1. User Intent',
      signer: 'User (ES256)',
      status: activeMandate ? 'VERIFIED' : 'PENDING',
      color: '#00f0ff',
      details: {
        type: 'UserIntentCredential (JWT)',
        signer_key: 'user:key-1 (NIST P-256)',
        spend_cap: activeMandate ? `Rs. ${(activeMandate.authorized_amount_paise / 100).toFixed(2)}` : 'Rs. 1500.00',
        allowed_merchants: ['merchant_cakehouse_01'],
        intent_hash: activeMandate?.intent_hash || 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
      },
    },
    {
      id: 'cart',
      title: '2. Signed Cart',
      signer: 'Merchant (ES256)',
      status: activeMandate ? 'VERIFIED' : 'PENDING',
      color: '#a855f7',
      details: {
        type: 'MerchantSignedCart (JWT)',
        signer_key: 'merchant:key-1 (NIST P-256)',
        pricing_source: 'Authoritative Merchant Catalog (Zero LLM price input)',
        cart_hash: activeMandate?.cart_hash || 'b7e2a48f0a1c3d9e8b7a6f5e4d3c2b1a0f9e8d7c6b5a4f3e2d1c0b9a8f7e6d5c',
      },
    },
    {
      id: 'mandate',
      title: '3. Payment Mandate',
      signer: 'Platform (ES256)',
      status: activeMandate ? 'AUTHORIZED' : 'PENDING',
      color: '#10b981',
      details: {
        type: 'PaymentMandate (JWT)',
        signer_key: 'platform:key-1 (NIST P-256)',
        mandate_id: activeMandate?.mandate_id || 'Pending Authorization',
        bound_cart_hash: activeMandate?.cart_hash || 'Pending',
        bound_intent_hash: activeMandate?.intent_hash || 'Pending',
        authorized_amount: activeMandate ? `Rs. ${(activeMandate.authorized_amount_paise / 100).toFixed(2)}` : 'Pending',
      },
    },
    {
      id: 'order',
      title: '4. Razorpay Order',
      signer: 'Gateway (Test Mode)',
      status: activeMandate?.razorpay_order_id ? 'CREATED' : 'PENDING',
      color: '#f59e0b',
      details: {
        type: 'Razorpay Orders API Entity',
        razorpay_order_id: activeMandate?.razorpay_order_id || 'Pending Creation',
        receipt_reference: activeMandate?.receipt_reference || `mm_${activeMandate?.mandate_id?.replace(/-/g, '') || ''}`,
        currency: 'INR',
      },
    },
    {
      id: 'receipt',
      title: '5. Payment Receipt',
      signer: 'Platform (ES256 Proof)',
      status: receiptData ? 'CAPTURED & ISSUED' : (activeMandate?.razorpay_order_id ? 'READY_FOR_WEBHOOK' : 'PENDING'),
      color: receiptData ? '#10b981' : '#64748b',
      details: {
        type: 'PaymentReceipt (Platform Signed Proof)',
        receipt_id: receiptData?.receipt_id || 'Awaiting payment.captured webhook',
        captured_at: receiptData?.receipt?.captured_at || 'Pending',
        hash_chained_trace: 'intent_hash -> cart_hash -> mandate_id -> razorpay_payment_id',
      },
    },
  ];

  return (
    <div className="panel-card" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      
      {/* Header */}
      <div className="panel-card-header">
        <div className="panel-title">
          <Layers size={20} className="text-cyan" />
          <span>Cryptographic Mandate Chain Explorer</span>
        </div>
        <span className="badge badge-green">Dual-Layer ES256 & SHA-256</span>
      </div>

      {/* Visual Pipeline */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '12px' }}>
        {hops.map((hop, idx) => {
          const isActive = hop.status !== 'PENDING';
          return (
            <div
              key={hop.id}
              onClick={() => setSelectedHop(hop)}
              style={{
                background: isActive ? 'var(--bg-surface)' : 'rgba(15, 23, 42, 0.4)',
                border: `1px solid ${isActive ? hop.color : 'var(--border-subtle)'}`,
                borderRadius: 'var(--radius-md)',
                padding: '14px',
                cursor: 'pointer',
                transition: 'all 0.2s ease',
                boxShadow: isActive ? `0 0 16px ${hop.color}22` : 'none',
              }}
              onMouseOver={(e) => (e.currentTarget.style.transform = 'translateY(-2px)')}
              onMouseOut={(e) => (e.currentTarget.style.transform = 'translateY(0)')}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
                <span style={{ fontSize: '0.75rem', fontWeight: 700, color: hop.color, textTransform: 'uppercase' }}>
                  Hop #{idx + 1}
                </span>
                {isActive ? (
                  <Check size={14} color={hop.color} />
                ) : (
                  <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: 'var(--text-muted)' }} />
                )}
              </div>

              <h4 style={{ fontSize: '0.9rem', fontWeight: 700, marginBottom: '4px' }}>{hop.title}</h4>
              <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{hop.signer}</p>
              
              <div style={{ marginTop: '10px' }}>
                <span className={`badge ${isActive ? 'badge-green' : 'badge-amber'}`} style={{ fontSize: '0.65rem' }}>
                  {hop.status}
                </span>
              </div>
            </div>
          );
        })}
      </div>

      {/* Webhook Capture Simulation Trigger */}
      {activeMandate?.razorpay_order_id && !receiptData && (
        <div style={{ background: 'rgba(16, 185, 129, 0.08)', border: '1px solid var(--accent-green)', borderRadius: 'var(--radius-md)', padding: '14px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <span style={{ fontSize: '0.85rem', fontWeight: 700, color: 'var(--accent-green)' }}>
              Order Created on Gateway ({activeMandate.razorpay_order_id})
            </span>
            <p style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
              Simulate Razorpay sending the authentic <code>payment.captured</code> webhook to issue the final cryptographic receipt.
            </p>
          </div>
          <button
            className="btn btn-success"
            onClick={handleCapture}
            disabled={capturing}
          >
            <Zap size={16} />
            {capturing ? 'Capturing...' : 'Simulate Webhook Capture'}
          </button>
        </div>
      )}

      {/* Receipt Completed Confirmation */}
      {receiptData && (
        <div style={{ background: 'rgba(16, 185, 129, 0.12)', border: '1px solid var(--accent-green)', borderRadius: 'var(--radius-md)', padding: '14px', display: 'flex', alignItems: 'center', gap: '12px' }}>
          <ShieldCheck size={24} className="text-green" />
          <div>
            <h4 style={{ fontSize: '0.9rem', fontWeight: 700, color: 'var(--accent-green)' }}>
              Cryptographic Payment Proof Verified
            </h4>
            <p className="font-mono" style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
              Receipt ID: {receiptData.receipt_id} (Captured Rs. {(activeMandate?.authorized_amount_paise / 100).toFixed(2)})
            </p>
          </div>
        </div>
      )}

      {/* Expandable JSON Claims Inspector */}
      {selectedHop && (
        <div style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border-glow)',
          borderRadius: 'var(--radius-md)',
          padding: '16px',
          display: 'flex',
          flexDirection: 'column',
          gap: '10px',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Key size={16} className="text-cyan" />
              <strong style={{ fontSize: '0.9rem' }}>{selectedHop.title} Inspection</strong>
            </div>
            <button
              onClick={() => setSelectedHop(null)}
              style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '0.8rem' }}
            >
              Close ✕
            </button>
          </div>

          <pre className="code-block">
            {JSON.stringify(selectedHop.details, null, 2)}
          </pre>
        </div>
      )}

    </div>
  );
}
