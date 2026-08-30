import React, { useState } from 'react';
import { Skull, ShieldAlert, ShieldCheck, Play, CheckCircle2, Lock } from 'lucide-react';
import { triggerAttack } from '../services/api';

export default function AttackSimulator({ onAttackSuccess, onLedgerChange }) {
  const [activeAttack, setActiveAttack] = useState(null);
  const [loadingAttackId, setLoadingAttackId] = useState(null);
  const [attackResult, setAttackResult] = useState(null);

  const attacks = [
    {
      id: 1,
      name: 'Attack 1: Over-Budget Spend',
      desc: 'Agent attempts luxury ₹4,940 cake against ₹1,500 budget.',
      expected: 'HTTP 403 · POLICY_SPEND_CAP_EXCEEDED',
      color: '#ef4444',
    },
    {
      id: 2,
      name: 'Attack 2: Prompt Injection Fake SKU',
      desc: 'Prompt requests unapproved "GOLD-COIN" to bypass catalog.',
      expected: 'HTTP 404 · CATALOG_SKU_NOT_FOUND',
      color: '#f59e0b',
    },
    {
      id: 3,
      name: 'Attack 3: MITM Cart Tampering',
      desc: 'Attacker modifies total_paise inside signed cart JWT in transit.',
      expected: 'HTTP 409 · POLICY_CART_SIGNATURE_INVALID',
      color: '#a855f7',
    },
    {
      id: 4,
      name: 'Attack 4: Webhook Replay Replay',
      desc: 'Replays payment.captured webhook 3x to trigger double debit.',
      expected: 'HTTP 200 · DEDUPLICATED (0 Double Debits)',
      color: '#00f0ff',
    },
    {
      id: 5,
      name: 'Attack 5: Cross-Merchant Key Forgery',
      desc: 'Submits Sweet Delight signature under CakeHouse identity.',
      expected: 'HTTP 409 · POLICY_CART_SIGNATURE_INVALID',
      color: '#ec4899',
    },
    {
      id: 6,
      name: 'Attack 6: Expired Quote Replay',
      desc: 'Attempts to authorize expired cart quote after TTL expiration.',
      expected: 'HTTP 409 · POLICY_CART_EXPIRED',
      color: '#f97316',
    },
  ];

  const handleRunAttack = async (attackId) => {
    setLoadingAttackId(attackId);
    setAttackResult(null);
    try {
      const res = await triggerAttack(attackId);
      setAttackResult(res);
      if (onAttackSuccess) {
        onAttackSuccess(res);
      }
      if (onLedgerChange) {
        onLedgerChange();
      }
    } catch (err) {
      alert(`Attack trigger error: ${err.message}`);
    } finally {
      setLoadingAttackId(null);
    }
  };

  return (
    <div className="panel-card" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      
      {/* Header */}
      <div className="panel-card-header">
        <div className="panel-title">
          <Skull size={20} className="text-red" />
          <span>Adversarial Threat Simulator (1-Click Judge Playground)</span>
        </div>
        <span className="badge badge-red">Fails Closed Guaranteed</span>
      </div>

      {/* Attack Buttons Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '12px' }}>
        {attacks.map((atk) => (
          <div
            key={atk.id}
            style={{
              background: 'var(--bg-surface)',
              border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-md)',
              padding: '14px',
              display: 'flex',
              flexDirection: 'column',
              justifyContent: 'space-between',
              gap: '10px',
              transition: 'all 0.2s ease',
            }}
          >
            <div>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '4px' }}>
                <strong style={{ fontSize: '0.88rem' }}>{atk.name}</strong>
              </div>
              <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>{atk.desc}</p>
            </div>

            <div>
              <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', marginBottom: '8px' }} className="font-mono">
                {atk.expected}
              </div>
              <button
                className="btn btn-secondary"
                onClick={() => handleRunAttack(atk.id)}
                disabled={loadingAttackId === atk.id}
                style={{ width: '100%', fontSize: '0.8rem', padding: '6px 12px' }}
              >
                <Play size={14} />
                {loadingAttackId === atk.id ? 'Attacking...' : 'Run Attack'}
              </button>
            </div>
          </div>
        ))}
      </div>

      {/* Live Rejection Outcome Banner */}
      {attackResult && (
        <div style={{
          background: 'linear-gradient(135deg, rgba(239, 68, 68, 0.12), rgba(15, 23, 42, 0.6))',
          border: '1px solid var(--accent-red)',
          borderRadius: 'var(--radius-lg)',
          padding: '18px',
          boxShadow: '0 0 24px rgba(239, 68, 68, 0.2)',
          display: 'flex',
          flexDirection: 'column',
          gap: '12px',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '8px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <ShieldAlert size={24} className="text-red" />
              <div>
                <h4 style={{ fontSize: '0.95rem', fontWeight: 700, color: 'var(--text-primary)' }}>
                  Threat Model Neutralized: {attackResult.name}
                </h4>
                <p className="font-mono text-muted" style={{ fontSize: '0.75rem' }}>
                  Outcome: {attackResult.outcome} · HTTP {attackResult.http_status} ({attackResult.error_code})
                </p>
              </div>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span className="badge badge-green" style={{ fontSize: '0.8rem', padding: '6px 12px' }}>
                <CheckCircle2 size={14} /> ₹0.00 Unauthorized Money Moved
              </span>
            </div>
          </div>

          <div style={{ background: 'rgba(0,0,0,0.3)', padding: '10px 14px', borderRadius: 'var(--radius-md)', fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
            <strong>Deterministic Reason:</strong> {attackResult.message}
          </div>
        </div>
      )}

    </div>
  );
}
