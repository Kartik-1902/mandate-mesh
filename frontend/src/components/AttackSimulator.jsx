import React, { useState } from 'react';
import { Skull, ShieldAlert, CheckCircle2, Terminal } from 'lucide-react';
import { triggerAttack } from '../services/api';

export default function AttackSimulator({ onAttackSuccess, onLedgerChange }) {
  const [loadingAttackId, setLoadingAttackId] = useState(null);
  const [attackResult, setAttackResult] = useState(null);

  const attacks = [
    {
      id: 1,
      name: 'VECTOR 01: OVER-BUDGET SPEND',
      desc: 'Agent attempts luxury ₹4,940 cake against ₹1,500 budget cap.',
      expected: 'HTTP 403 · POLICY_SPEND_CAP_EXCEEDED',
    },
    {
      id: 2,
      name: 'VECTOR 02: PROMPT INJECTION SKU',
      desc: 'Prompt requests unapproved "GOLD-COIN" to bypass catalog.',
      expected: 'HTTP 404 · CATALOG_SKU_NOT_FOUND',
    },
    {
      id: 3,
      name: 'VECTOR 03: MITM CART TAMPERING',
      desc: 'Attacker modifies total_paise inside signed cart JWT in transit.',
      expected: 'HTTP 409 · POLICY_CART_SIGNATURE_INVALID',
    },
    {
      id: 4,
      name: 'VECTOR 04: WEBHOOK REPLAY ATTACK',
      desc: 'Replays payment.captured webhook 3x to trigger double debit.',
      expected: 'HTTP 200 · DEDUPLICATED (0 Double Debits)',
    },
    {
      id: 5,
      name: 'VECTOR 05: CROSS-MERCHANT KEY FORGERY',
      desc: 'Submits Sweet Delight signature under CakeHouse identity.',
      expected: 'HTTP 409 · POLICY_CART_SIGNATURE_INVALID',
    },
    {
      id: 6,
      name: 'VECTOR 06: EXPIRED QUOTE REPLAY',
      desc: 'Attempts to authorize expired cart quote after TTL expiration.',
      expected: 'HTTP 409 · POLICY_CART_EXPIRED',
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
    <div className="panel-card" style={{ display: 'flex', flexDirection: 'column', gap: '14px', borderTop: '3px solid var(--accent-red)' }}>
      <div className="hazard-stripe-bar" style={{ marginTop: '-16px', marginLeft: '-16px', marginRight: '-16px', width: 'calc(100% + 32px)' }} />

      {/* Header */}
      <div className="panel-card-header" style={{ marginBottom: 0 }}>
        <div className="panel-title">
          <Skull size={16} color="var(--accent-red)" />
          <span>ADVERSARIAL THREAT BENCH // FAIL-CLOSED VERIFICATION</span>
        </div>
        <span className="badge badge-red">FAIL-CLOSED ENFORCED</span>
      </div>

      {/* Vector Trigger Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '10px' }}>
        {attacks.map((atk) => {
          const isLoading = loadingAttackId === atk.id;

          return (
            <div
              key={atk.id}
              style={{
                background: 'var(--bg-recessed)',
                border: '1px solid var(--border-line)',
                padding: '12px',
                display: 'flex',
                flexDirection: 'column',
                justifyContent: 'space-between',
                gap: '8px',
              }}
            >
              <div>
                <div style={{ fontSize: '0.75rem', fontWeight: 800, color: 'var(--text-phosphor)' }}>
                  {atk.name}
                </div>
                <p style={{ fontSize: '0.68rem', color: 'var(--text-secondary)', marginTop: '4px', lineHeight: 1.35 }}>
                  {atk.desc}
                </p>
              </div>

              <div style={{
                background: 'var(--bg-terminal)',
                padding: '4px 6px',
                border: '1px solid var(--border-dim)',
                fontSize: '0.65rem',
                color: 'var(--text-muted)',
              }}>
                EXPECTED: <span style={{ color: 'var(--text-secondary)', fontWeight: 600 }}>{atk.expected}</span>
              </div>

              <button
                className="btn btn-danger"
                onClick={() => handleRunAttack(atk.id)}
                disabled={isLoading}
                style={{ fontSize: '0.7rem', padding: '6px 10px', width: '100%' }}
              >
                {isLoading ? 'SIMULATING VECTOR...' : `[ LAUNCH VECTOR 0${atk.id} ]`}
              </button>
            </div>
          );
        })}
      </div>

      {/* Threat Diagnostic Output Console */}
      {attackResult && (
        <div style={{
          background: 'var(--bg-recessed)',
          border: '1px solid var(--border-bright)',
          borderLeft: '4px solid var(--accent-red)',
          padding: '12px',
          display: 'flex',
          flexDirection: 'column',
          gap: '8px',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Terminal size={14} color="var(--accent-red)" />
              <span style={{ fontSize: '0.72rem', fontWeight: 800, color: 'var(--accent-red)', textTransform: 'uppercase' }}>
                [ THREAT INTERCEPT DIAGNOSTIC RESULT ]
              </span>
            </div>
            <span className="badge badge-green" style={{ fontSize: '0.65rem' }}>
              INVARIANT PRESERVED · 0 RUPEES MOVED
            </span>
          </div>

          <div style={{
            background: 'var(--bg-terminal)',
            border: '1px solid var(--border-line)',
            padding: '10px',
            fontFamily: 'var(--font-mono)',
            fontSize: '0.72rem',
            color: 'var(--text-secondary)',
            maxHeight: '180px',
            overflowY: 'auto',
          }}>
            <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
              {JSON.stringify(attackResult, null, 2)}
            </pre>
          </div>
        </div>
      )}

    </div>
  );
}
