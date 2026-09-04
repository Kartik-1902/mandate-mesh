import React, { useState } from 'react';
import { Skull, ShieldAlert, CheckCircle2, Terminal } from 'lucide-react';
import { triggerAttack } from '../services/api';

export default function AttackSimulator({ onAttackSuccess, onLedgerChange }) {
  const [loadingAttackId, setLoadingAttackId] = useState(null);
  const [attackResult, setAttackResult] = useState(null);
  const [activeHoverId, setActiveHoverId] = useState(null);

  const attacks = [
    {
      id: 1,
      tag: '01: OVER-BUDGET',
      name: 'Over-Budget Spend (₹4,940 vs ₹1,500)',
      expected: 'HTTP 403 · POLICY_SPEND_CAP_EXCEEDED',
    },
    {
      id: 2,
      tag: '02: INJECTION SKU',
      name: 'Prompt Injection Fake SKU (GOLD-COIN)',
      expected: 'HTTP 404 · CATALOG_SKU_NOT_FOUND',
    },
    {
      id: 3,
      tag: '03: MITM TAMPER',
      name: 'MITM Cart Total Tampering',
      expected: 'HTTP 409 · POLICY_CART_SIGNATURE_INVALID',
    },
    {
      id: 4,
      tag: '04: WEBHOOK REPLAY',
      name: 'Idempotent Webhook Replay (3x)',
      expected: 'HTTP 200 · DEDUPLICATED (0 Double Debits)',
    },
    {
      id: 5,
      tag: '05: KEY FORGERY',
      name: 'Cross-Merchant Key Forgery',
      expected: 'HTTP 409 · POLICY_CART_SIGNATURE_INVALID',
    },
    {
      id: 6,
      tag: '06: EXPIRED QUOTE',
      name: 'Expired Quote Replay (Post-TTL)',
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

  const hoveredAttack = attacks.find((a) => a.id === activeHoverId);

  return (
    <div className="panel-card" style={{ display: 'flex', flexDirection: 'column', gap: '10px', borderTop: '2px solid var(--accent-red)' }}>
      
      {/* Header */}
      <div className="panel-card-header" style={{ marginBottom: 0, paddingBottom: '6px' }}>
        <div className="panel-title">
          <Skull size={14} color="var(--accent-red)" />
          <span>ADVERSARIAL THREAT BENCH</span>
        </div>
        <span className="badge badge-red" style={{ fontSize: '0.65rem' }}>
          FAIL-CLOSED ENFORCED
        </span>
      </div>

      {/* Compact Vector Action Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '6px' }}>
        {attacks.map((atk) => {
          const isLoading = loadingAttackId === atk.id;

          return (
            <button
              key={atk.id}
              onClick={() => handleRunAttack(atk.id)}
              onMouseEnter={() => setActiveHoverId(atk.id)}
              onMouseLeave={() => setActiveHoverId(null)}
              disabled={isLoading}
              className="btn btn-danger"
              style={{
                padding: '6px 8px',
                fontSize: '0.68rem',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                textAlign: 'left',
              }}
            >
              <span>[ {atk.tag} ]</span>
              <span style={{ fontSize: '0.62rem', opacity: 0.85 }}>{isLoading ? '...' : 'EXEC'}</span>
            </button>
          );
        })}
      </div>

      {/* Vector Description / Expected Outcome Strip */}
      <div style={{
        background: 'var(--bg-recessed)',
        border: '1px solid var(--border-line)',
        padding: '4px 8px',
        fontSize: '0.68rem',
        color: 'var(--text-muted)',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        minHeight: '24px',
      }}>
        {hoveredAttack ? (
          <>
            <span style={{ color: 'var(--text-phosphor)', fontWeight: 600 }}>{hoveredAttack.name}</span>
            <span style={{ color: 'var(--text-secondary)' }}>{hoveredAttack.expected}</span>
          </>
        ) : (
          <span style={{ color: 'var(--text-dim)' }}>
            HOVER OVER A THREAT VECTOR TO INSPECT TARGET INVARIANT · CLICK TO EXECUTE
          </span>
        )}
      </div>

      {/* Threat Diagnostic Output Console */}
      {attackResult && (
        <div style={{
          background: 'var(--bg-recessed)',
          border: '1px solid var(--border-bright)',
          borderLeft: '3px solid var(--accent-red)',
          padding: '8px 10px',
          display: 'flex',
          flexDirection: 'column',
          gap: '6px',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Terminal size={12} color="var(--accent-red)" />
              <span style={{ fontSize: '0.68rem', fontWeight: 800, color: 'var(--accent-red)', textTransform: 'uppercase' }}>
                INTERCEPT DIAGNOSTIC RESULT
              </span>
            </div>
            <span className="badge badge-green" style={{ fontSize: '0.62rem' }}>
              0 RUPEES MOVED
            </span>
          </div>

          <pre style={{
            margin: 0,
            padding: '6px 8px',
            background: 'var(--bg-terminal)',
            border: '1px solid var(--border-line)',
            fontFamily: 'var(--font-mono)',
            fontSize: '0.68rem',
            color: 'var(--text-secondary)',
            maxHeight: '120px',
            overflowY: 'auto',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
          }}>
            {JSON.stringify(attackResult, null, 2)}
          </pre>
        </div>
      )}

    </div>
  );
}
