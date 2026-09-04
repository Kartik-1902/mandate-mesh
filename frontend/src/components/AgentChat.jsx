import React, { useState } from 'react';
import { Terminal, Send, AlertTriangle, CheckCircle2, ShieldAlert, Sparkles } from 'lucide-react';
import { deliberateGoal, escalateAndPay } from '../services/api';

export default function AgentChat({ onDeliberateSuccess, onEscalateSuccess, onLedgerChange }) {
  const [goal, setGoal] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [agentState, setAgentState] = useState(null);
  const [escalating, setEscalating] = useState(false);

  const samplePrompts = [
    { label: 'Cake Routing (< ₹1500)', text: 'Order a 1kg chocolate cake under Rs. 1500 comparing all bakeries' },
    { label: 'HITL Escalation (< ₹800)', text: 'Order a chocolate cake under Rs. 800' },
    { label: 'Combo Basket (< ₹2000)', text: 'Order a chocolate cake and greeting card under Rs. 2000' },
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
        agentState.escalation_details.suggested_total_paise,
        "user_control_tower_01",
        agentState.escalation_details.suggested_merchant_id || null
      );
      setAgentState((prev) => ({
        ...prev,
        status: 'COMPLETED',
        escalation_resolved: true,
        mandate: res.mandate || {
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
    <div className="panel-card" style={{ height: '100%', minHeight: '560px', display: 'flex', flexDirection: 'column' }}>
      
      {/* Header */}
      <div className="panel-card-header" style={{ marginBottom: 0, paddingBottom: '6px' }}>
        <div className="panel-title">
          <Terminal size={14} color="var(--text-phosphor)" />
          <span>AUTONOMOUS BUYER AGENT</span>
        </div>
        <span className="badge badge-steel" style={{ fontSize: '0.65rem' }}>
          LANGGRAPH DELIBERATION
        </span>
      </div>

      {/* Preset Macro Buttons */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', margin: '10px 0 8px' }}>
        {samplePrompts.map((p, idx) => (
          <button
            key={idx}
            onClick={() => {
              setGoal(p.text);
              handleDeliberate(p.text);
            }}
            disabled={loading}
            className="btn btn-secondary"
            style={{
              fontSize: '0.68rem',
              padding: '3px 8px',
              border: '1px solid var(--border-line)',
              background: 'var(--bg-recessed)',
            }}
          >
            [ {p.label} ]
          </button>
        ))}
      </div>

      {/* Command Input Bar */}
      <div style={{ display: 'flex', gap: '6px', marginBottom: '12px' }}>
        <div style={{
          flex: 1,
          display: 'flex',
          alignItems: 'center',
          background: 'var(--bg-input)',
          border: '1px solid var(--border-bright)',
          padding: '0 8px',
        }}>
          <span style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontWeight: 700, marginRight: '6px' }}>
            &gt;&gt;&gt;
          </span>
          <input
            type="text"
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            placeholder="ENTER PURCHASING GOAL..."
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                handleDeliberate();
              }
            }}
            disabled={loading}
            style={{
              flex: 1,
              background: 'transparent',
              border: 'none',
              color: 'var(--text-phosphor)',
              padding: '8px 0',
              fontSize: '0.78rem',
              fontFamily: 'var(--font-mono)',
              outline: 'none',
              textTransform: 'uppercase',
            }}
          />
          <span style={{
            fontSize: '0.62rem',
            color: 'var(--text-dim)',
            fontFamily: 'var(--font-mono)',
            padding: '2px 4px',
            border: '1px solid var(--border-line)',
            background: 'var(--bg-recessed)',
          }}>
            ↵
          </span>
        </div>
        <button
          className="btn btn-primary"
          onClick={() => handleDeliberate()}
          disabled={loading || !goal.trim()}
          style={{ padding: '0 12px', minWidth: '110px', fontSize: '0.72rem' }}
        >
          {loading ? 'RUNNING...' : '[ DELIBERATE ↵ ]'}
        </button>
      </div>

      {/* Error Banner */}
      {error && (
        <div style={{
          background: 'var(--accent-red-dim)',
          border: '1px solid var(--accent-red)',
          padding: '8px 10px',
          marginBottom: '10px',
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
        }}>
          <ShieldAlert size={14} color="var(--accent-red)" />
          <span style={{ fontSize: '0.72rem', color: 'var(--accent-red)', fontWeight: 700 }}>
            {error}
          </span>
        </div>
      )}

      {/* Results Container */}
      <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '8px' }}>
        {agentState ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            
            {/* User Goal */}
            <div style={{ background: 'var(--bg-recessed)', border: '1px solid var(--border-line)', padding: '8px 10px' }}>
              <span style={{ fontSize: '0.62rem', color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                GOAL:
              </span>
              <p style={{ fontSize: '0.8rem', color: 'var(--text-phosphor)', fontWeight: 600, marginTop: '2px' }}>
                "{agentState.goal}"
              </p>
            </div>

            {/* LLM Deliberation Reasoning */}
            {agentState.llm_reasoning && (
              <div style={{ background: 'var(--bg-recessed)', border: '1px solid var(--border-line)', padding: '8px 10px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '5px', marginBottom: '4px' }}>
                  <Sparkles size={12} color="var(--accent-steel)" />
                  <span style={{ fontSize: '0.65rem', fontWeight: 700, color: 'var(--text-secondary)', textTransform: 'uppercase' }}>
                    REASONING
                  </span>
                </div>
                <p style={{ fontSize: '0.74rem', color: 'var(--text-secondary)', lineHeight: 1.4 }}>
                  {agentState.llm_reasoning}
                </p>
              </div>
            )}

            {/* Authoritative Signed Cart Table */}
            {agentState.signed_cart?.line_items && (
              <div style={{ background: 'var(--bg-recessed)', border: '1px solid var(--border-line)' }}>
                <div style={{
                  padding: '6px 10px',
                  borderBottom: '1px solid var(--border-line)',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                }}>
                  <span style={{ fontSize: '0.68rem', fontWeight: 700, textTransform: 'uppercase', color: 'var(--text-phosphor)' }}>
                    MERCHANT CART
                  </span>
                  <span className="badge badge-green" style={{ fontSize: '0.6rem' }}>
                    DB PRICED
                  </span>
                </div>

                <div style={{ padding: '6px 10px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                  {agentState.signed_cart.line_items.map((item, i) => (
                    <div
                      key={i}
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        fontSize: '0.74rem',
                        padding: '2px 0',
                      }}
                    >
                      <span>{item.name} × {item.quantity}</span>
                      <span style={{ color: 'var(--text-phosphor)', fontWeight: 700 }}>
                        ₹{(item.unit_price_paise * item.quantity / 100).toFixed(2)}
                      </span>
                    </div>
                  ))}

                  <div style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    marginTop: '4px',
                    paddingTop: '4px',
                    borderTop: '1px solid var(--border-line)',
                    fontWeight: 800,
                    fontSize: '0.82rem',
                  }}>
                    <span style={{ color: 'var(--text-muted)' }}>TOTAL:</span>
                    <span style={{ color: 'var(--accent-terminal)' }}>
                      ₹{(agentState.signed_cart.total_paise / 100).toFixed(2)}
                    </span>
                  </div>
                </div>
              </div>
            )}

            {/* ADR-007: Human-in-the-Loop Budget Escalation Warning Module */}
            {agentState.status === 'REQUIRES_USER_APPROVAL' && agentState.escalation_details && agentState.escalation_details.suggested_total_paise > 0 && (
              <div style={{
                background: 'var(--bg-recessed)',
                border: '1px solid var(--accent-amber)',
                padding: '10px 12px',
                display: 'flex',
                flexDirection: 'column',
                gap: '8px',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <AlertTriangle size={15} color="var(--accent-amber)" />
                  <span style={{ fontSize: '0.74rem', fontWeight: 800, color: 'var(--accent-amber)', textTransform: 'uppercase' }}>
                    BUDGET ESCALATION REQUIRED
                  </span>
                </div>

                <div style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(3, 1fr)',
                  gap: '6px',
                  background: 'var(--bg-terminal)',
                  border: '1px solid var(--border-line)',
                  padding: '6px 8px',
                  fontSize: '0.72rem',
                }}>
                  <div>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.62rem' }}>CAP:</span>
                    <p style={{ fontWeight: 700 }}>₹{(agentState.escalation_details.current_budget_paise / 100).toFixed(2)}</p>
                  </div>
                  <div>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.62rem' }}>REQUIRED:</span>
                    <p style={{ color: 'var(--accent-amber)', fontWeight: 800 }}>₹{(agentState.escalation_details.suggested_total_paise / 100).toFixed(2)}</p>
                  </div>
                  <div>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.62rem' }}>DELTA:</span>
                    <p style={{ color: 'var(--accent-red)', fontWeight: 800 }}>+₹{(agentState.escalation_details.overspend_paise / 100).toFixed(2)}</p>
                  </div>
                </div>

                <div style={{ display: 'flex', gap: '6px' }}>
                  <button
                    className="btn btn-success"
                    onClick={handleEscalateApproval}
                    disabled={escalating}
                    style={{ flex: 1, fontSize: '0.7rem', padding: '6px 8px' }}
                  >
                    {escalating ? 'AUTHORIZING...' : `[ APPROVE & SIGN ₹${(agentState.escalation_details.suggested_total_paise / 100).toFixed(2)} ]`}
                  </button>
                  <button
                    className="btn btn-secondary"
                    onClick={handleDecline}
                    disabled={escalating}
                    style={{ fontSize: '0.7rem', padding: '6px 8px' }}
                  >
                    [ DECLINE ]
                  </button>
                </div>
              </div>
            )}

            {/* Outcomes */}
            {agentState.status === 'NO_CANDIDATE_MATCH' && (
              <div style={{
                background: 'var(--bg-recessed)',
                border: '1px solid var(--border-bright)',
                padding: '6px 10px',
                fontSize: '0.72rem',
                color: 'var(--text-phosphor)',
              }}>
                [ NO CANDIDATE MATCH ] · ZERO RUPEES COMMITTED
              </div>
            )}

            {agentState.status === 'COMPLETED' && (
              <div style={{
                background: 'var(--bg-recessed)',
                border: '1px solid var(--accent-terminal)',
                padding: '6px 10px',
                fontSize: '0.72rem',
                color: 'var(--accent-terminal)',
                fontWeight: 700,
              }}>
                [ MANDATE ISSUED & ORDER CREATED ]
              </div>
            )}

            {agentState.status === 'USER_REJECTED' && (
              <div style={{
                background: 'var(--bg-recessed)',
                border: '1px solid var(--accent-red)',
                padding: '6px 10px',
                fontSize: '0.72rem',
                color: 'var(--accent-red)',
                fontWeight: 700,
              }}>
                [ TRANSACTION ABORTED BY USER ] · ZERO RUPEES MOVED
              </div>
            )}

          </div>
        ) : (
          <div style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            height: '100%',
            color: 'var(--text-muted)',
            textAlign: 'center',
            fontSize: '0.72rem',
            padding: '24px 12px',
          }}>
            TRANSMIT AN INTENT OR SELECT A PRESET MACRO TO COMMENCE DELIBERATION.
          </div>
        )}
      </div>

    </div>
  );
}
