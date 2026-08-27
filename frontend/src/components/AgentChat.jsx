import React, { useState } from 'react';
import { Bot, Send, AlertTriangle, CheckCircle2, ShoppingBag, ArrowRight, ShieldAlert, Sparkles } from 'lucide-react';
import { deliberateGoal, escalateAndPay } from '../services/api';

export default function AgentChat({ onDeliberateSuccess, onEscalateSuccess, onLedgerChange }) {
  const [goal, setGoal] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [agentState, setAgentState] = useState(null);
  const [escalating, setEscalating] = useState(false);

  const samplePrompts = [
    { label: '🎂 Birthday Cake < Rs. 1500', text: 'Order me a birthday cake under Rs. 1500' },
    { label: '🍫 Choc Cake < Rs. 800 (HITL Escalation)', text: 'Order a chocolate cake under Rs. 800' },
    { label: '🎁 Card + Cake Combo < Rs. 2000', text: 'Order a chocolate cake and greeting card under Rs. 2000' },
  ];

  const handleDeliberate = async (targetGoal) => {
    const activeGoal = targetGoal || goal;
    if (!activeGoal.trim()) return;

    setLoading(true);
    setError(null);
    try {
      const res = await deliberateGoal(activeGoal);
      setAgentState(res);
      if (onDeliberateSuccess) {
        onDeliberateSuccess(res);
      }
      if (onLedgerChange) {
        onLedgerChange();
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleEscalateApproval = async () => {
    if (!agentState?.cart_jwt || !agentState?.escalation_details) return;

    setEscalating(true);
    setError(null);
    try {
      const res = await escalateAndPay(
        agentState.cart_jwt,
        agentState.escalation_details.suggested_total_paise
      );
      setAgentState((prev) => ({
        ...prev,
        status: 'COMPLETED',
        escalation_resolved: true,
        mandate: {
          mandate_id: res.mandate_id,
          authorized_amount_paise: res.authorized_amount_paise,
          status: res.status,
          mandate_jwt: res.mandate_jwt,
        },
        razorpay_order_id: res.razorpay_order_id,
      }));
      if (onEscalateSuccess) {
        onEscalateSuccess(res);
      }
      if (onLedgerChange) {
        onLedgerChange();
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setEscalating(false);
    }
  };

  const handleDecline = () => {
    setAgentState((prev) => ({
      ...prev,
      status: 'USER_REJECTED',
    }));
  };

  return (
    <div className="panel-card" style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: '620px' }}>
      
      {/* Header */}
      <div className="panel-card-header">
        <div className="panel-title">
          <Bot size={20} className="text-cyan" />
          <span>Autonomous Buyer Agent</span>
        </div>
        <span className="badge badge-cyan">LangGraph + Gemini</span>
      </div>

      {/* Suggestion Chips */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginBottom: '16px' }}>
        {samplePrompts.map((p, idx) => (
          <button
            key={idx}
            onClick={() => {
              setGoal(p.text);
              handleDeliberate(p.text);
            }}
            disabled={loading}
            style={{
              background: 'var(--bg-surface)',
              border: '1px solid var(--border-subtle)',
              color: 'var(--text-secondary)',
              borderRadius: 'var(--radius-md)',
              padding: '6px 12px',
              fontSize: '0.75rem',
              cursor: 'pointer',
              transition: 'all 0.2s ease',
            }}
            onMouseOver={(e) => (e.currentTarget.style.borderColor = 'var(--accent-cyan)')}
            onMouseOut={(e) => (e.currentTarget.style.borderColor = 'var(--border-subtle)')}
          >
            {p.label}
          </button>
        ))}
      </div>

      {/* Input Box */}
      <div style={{ display: 'flex', gap: '10px', marginBottom: '20px' }}>
        <input
          type="text"
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          placeholder="e.g. Order me a chocolate cake under Rs. 1500"
          onKeyDown={(e) => e.key === 'Enter' && handleDeliberate()}
          disabled={loading}
          style={{
            flex: 1,
            background: 'var(--bg-input)',
            border: '1px solid var(--border-glow)',
            color: 'var(--text-primary)',
            padding: '12px 16px',
            borderRadius: 'var(--radius-md)',
            fontSize: '0.9rem',
            fontFamily: 'var(--font-sans)',
            outline: 'none',
          }}
        />
        <button
          className="btn btn-primary"
          onClick={() => handleDeliberate()}
          disabled={loading || !goal.trim()}
          style={{ padding: '0 20px' }}
        >
          {loading ? 'Thinking...' : <Send size={18} />}
        </button>
      </div>

      {/* Error Banner */}
      {error && (
        <div style={{ background: 'var(--accent-red-dim)', border: '1px solid var(--accent-red)', borderRadius: 'var(--radius-md)', padding: '12px', marginBottom: '16px', display: 'flex', alignItems: 'center', gap: '10px' }}>
          <ShieldAlert size={20} className="text-red" />
          <p style={{ fontSize: '0.85rem', color: 'var(--text-primary)' }}>{error}</p>
        </div>
      )}

      {/* Deliberation Transcript / Results Container */}
      <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '16px' }}>
        {agentState ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
            
            {/* User Goal */}
            <div style={{ background: 'var(--bg-surface)', padding: '12px 16px', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
              <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 600 }}>Goal</span>
              <p style={{ fontSize: '0.95rem', fontWeight: 500, marginTop: '2px' }}>"{agentState.goal}"</p>
            </div>

            {/* LLM Reasoning */}
            {agentState.llm_reasoning && (
              <div style={{ background: 'rgba(0, 240, 255, 0.04)', border: '1px solid rgba(0, 240, 255, 0.2)', padding: '12px 16px', borderRadius: 'var(--radius-md)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '4px' }}>
                  <Sparkles size={14} className="text-cyan" />
                  <span style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--accent-cyan)', textTransform: 'uppercase' }}>LLM Deliberation Reasoning</span>
                </div>
                <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>{agentState.llm_reasoning}</p>
              </div>
            )}

            {/* Proposed Items Breakdown */}
            {agentState.signed_cart?.line_items && (
              <div style={{ background: 'var(--bg-surface)', padding: '14px', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }}>
                  <span style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase' }}>Authoritative Merchant Cart</span>
                  <span className="badge badge-cyan">DB Priced</span>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {agentState.signed_cart.line_items.map((item, i) => (
                    <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.85rem', paddingBottom: '6px', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                      <div>
                        <strong>{item.name}</strong>
                        <span style={{ color: 'var(--text-muted)', marginLeft: '6px' }}>× {item.quantity}</span>
                      </div>
                      <span className="font-mono text-cyan">Rs. {(item.unit_price_paise * item.quantity / 100).toFixed(2)}</span>
                    </div>
                  ))}
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '6px', paddingTop: '6px', fontWeight: 700, fontSize: '0.95rem' }}>
                    <span>Total Sum:</span>
                    <span className="font-mono text-green">Rs. {(agentState.signed_cart.total_paise / 100).toFixed(2)}</span>
                  </div>
                </div>
              </div>
            )}

            {/* ADR-007: Human-in-the-Loop Budget Escalation Review Modal */}
            {agentState.status === 'REQUIRES_USER_APPROVAL' && agentState.escalation_details && (
              <div style={{
                background: 'linear-gradient(135deg, rgba(245, 158, 11, 0.12), rgba(245, 158, 11, 0.05))',
                border: '1px solid var(--accent-amber)',
                borderRadius: 'var(--radius-lg)',
                padding: '18px',
                boxShadow: '0 0 24px rgba(245, 158, 11, 0.2)',
                display: 'flex',
                flexDirection: 'column',
                gap: '12px',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <AlertTriangle size={24} className="text-amber" />
                  <div>
                    <h4 style={{ fontSize: '0.95rem', fontWeight: 700, color: 'var(--accent-amber)' }}>
                      Human-in-the-Loop Budget Escalation Required
                    </h4>
                    <p style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
                      Policy Rail blocked auto-charge: Catalog pricing exceeds initial budget ceiling.
                    </p>
                  </div>
                </div>

                <div style={{ background: 'rgba(0,0,0,0.3)', padding: '12px', borderRadius: 'var(--radius-md)', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', fontSize: '0.8rem' }}>
                  <div>
                    <span style={{ color: 'var(--text-muted)' }}>Initial Budget Cap:</span>
                    <p className="font-mono text-muted">Rs. {(agentState.escalation_details.current_budget_paise / 100).toFixed(2)}</p>
                  </div>
                  <div>
                    <span style={{ color: 'var(--text-muted)' }}>Merchant Required:</span>
                    <p className="font-mono text-amber" style={{ fontWeight: 700 }}>Rs. {(agentState.escalation_details.suggested_total_paise / 100).toFixed(2)}</p>
                  </div>
                  <div style={{ gridColumn: 'span 2', paddingTop: '4px', borderTop: '1px solid rgba(255,255,255,0.08)' }}>
                    <span style={{ color: 'var(--text-muted)' }}>Overspend Delta:</span>
                    <p className="font-mono text-red" style={{ fontWeight: 700 }}>+Rs. {(agentState.escalation_details.overspend_paise / 100).toFixed(2)}</p>
                  </div>
                </div>

                <div style={{ display: 'flex', gap: '10px', marginTop: '4px' }}>
                  <button
                    className="btn btn-success"
                    onClick={handleEscalateApproval}
                    disabled={escalating}
                    style={{ flex: 1 }}
                  >
                    {escalating ? 'Authorizing...' : `Approve & Sign (Rs. ${(agentState.escalation_details.suggested_total_paise / 100).toFixed(2)})`}
                  </button>
                  <button
                    className="btn btn-secondary"
                    onClick={handleDecline}
                    disabled={escalating}
                  >
                    Decline
                  </button>
                </div>
              </div>
            )}

            {/* Resolved / Completed Confirmation */}
            {agentState.status === 'COMPLETED' && (
              <div style={{ background: 'var(--accent-green-dim)', border: '1px solid var(--accent-green)', borderRadius: 'var(--radius-md)', padding: '12px', display: 'flex', alignItems: 'center', gap: '10px' }}>
                <CheckCircle2 size={20} className="text-green" />
                <p style={{ fontSize: '0.85rem', color: 'var(--accent-green)', fontWeight: 600 }}>
                  Payment Mandate Authorized & Order Created!
                </p>
              </div>
            )}

            {/* Declined Status */}
            {agentState.status === 'USER_REJECTED' && (
              <div style={{ background: 'var(--accent-red-dim)', border: '1px solid var(--accent-red)', borderRadius: 'var(--radius-md)', padding: '12px', display: 'flex', alignItems: 'center', gap: '10px' }}>
                <ShieldAlert size={20} className="text-red" />
                <p style={{ fontSize: '0.85rem', color: 'var(--accent-red)', fontWeight: 600 }}>
                  Transaction Aborted by User. Zero rupees moved.
                </p>
              </div>
            )}

          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--text-muted)', textAlign: 'center', gap: '8px' }}>
            <ShoppingBag size={36} style={{ opacity: 0.4 }} />
            <p style={{ fontSize: '0.85rem' }}>Select a prompt above or type a natural language goal to watch the AI buyer deliberate.</p>
          </div>
        )}
      </div>

    </div>
  );
}
