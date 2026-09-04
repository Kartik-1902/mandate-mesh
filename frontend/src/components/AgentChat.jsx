import React, { useState } from 'react';
import { Terminal, Send, AlertTriangle, CheckCircle2, ShieldAlert, Sparkles, Layers } from 'lucide-react';
import { deliberateGoal, escalateAndPay } from '../services/api';

export default function AgentChat({ onDeliberateSuccess, onEscalateSuccess, onLedgerChange }) {
  const [goal, setGoal] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [agentState, setAgentState] = useState(null);
  const [escalating, setEscalating] = useState(false);

  const samplePrompts = [
    { label: '[ EXEC: CAKE_ROUTING < ₹1500 ]', text: 'Order a 1kg chocolate cake under Rs. 1500 comparing all bakeries' },
    { label: '[ EXEC: HITL_ESCALATION < ₹800 ]', text: 'Order a chocolate cake under Rs. 800' },
    { label: '[ EXEC: COMBO_BASKET < ₹2000 ]', text: 'Order a chocolate cake and greeting card under Rs. 2000' },
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
    <div className="panel-card" style={{ height: '100%', minHeight: '660px' }}>
      
      {/* Panel Header */}
      <div className="panel-card-header">
        <div className="panel-title">
          <Terminal size={16} color="var(--text-phosphor)" />
          <span>AUTONOMOUS BUYER AGENT // DELIBERATION CONSOLE</span>
        </div>
        <span className="badge badge-steel">LANGGRAPH ENGINE</span>
      </div>

      {/* Preset Diagnostic Macro Triggers */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginBottom: '14px' }}>
        <span style={{ fontSize: '0.68rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
          PRESET SCENARIO MACROS:
        </span>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
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
                fontSize: '0.7rem',
                padding: '4px 8px',
                border: '1px solid var(--border-line)',
                background: 'var(--bg-recessed)',
              }}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {/* Command Input Bar */}
      <div style={{ display: 'flex', gap: '8px', marginBottom: '16px' }}>
        <div style={{
          flex: 1,
          display: 'flex',
          alignItems: 'center',
          background: 'var(--bg-input)',
          border: '1px solid var(--border-bright)',
          padding: '0 10px',
        }}>
          <span style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontWeight: 700, marginRight: '8px' }}>
            &gt;&gt;&gt;
          </span>
          <input
            type="text"
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            placeholder="ENTER PURCHASING INTENT QUERY..."
            onKeyDown={(e) => e.key === 'Enter' && handleDeliberate()}
            disabled={loading}
            style={{
              flex: 1,
              background: 'transparent',
              border: 'none',
              color: 'var(--text-phosphor)',
              padding: '10px 0',
              fontSize: '0.82rem',
              fontFamily: 'var(--font-mono)',
              outline: 'none',
              textTransform: 'uppercase',
            }}
          />
        </div>
        <button
          className="btn btn-primary"
          onClick={() => handleDeliberate()}
          disabled={loading || !goal.trim()}
          style={{ padding: '0 16px', minWidth: '130px' }}
        >
          {loading ? 'DELIBERATING...' : '[ TRANSMIT ]'}
        </button>
      </div>

      {/* Error Notice */}
      {error && (
        <div style={{
          background: 'var(--accent-red-dim)',
          border: '1px solid var(--accent-red)',
          padding: '10px 14px',
          marginBottom: '14px',
          display: 'flex',
          alignItems: 'center',
          gap: '10px',
        }}>
          <ShieldAlert size={18} color="var(--accent-red)" />
          <span style={{ fontSize: '0.78rem', color: 'var(--accent-red)', fontWeight: 700 }}>
            {error}
          </span>
        </div>
      )}

      {/* Deliberation Transcript Stream */}
      <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '12px' }}>
        {agentState ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            
            {/* Telemetry Record: User Goal */}
            <div style={{ background: 'var(--bg-recessed)', border: '1px solid var(--border-line)', padding: '10px 12px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                <span style={{ fontSize: '0.68rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                  TARGET OBJECTIVE INTENT
                </span>
                <span className="badge badge-steel" style={{ fontSize: '0.65rem' }}>FSM: PARSED</span>
              </div>
              <p style={{ fontSize: '0.85rem', color: 'var(--text-phosphor)', fontWeight: 600 }}>
                "{agentState.goal}"
              </p>
            </div>

            {/* LLM Deliberation Reasoning */}
            {agentState.llm_reasoning && (
              <div style={{ background: 'var(--bg-recessed)', border: '1px solid var(--border-line)', padding: '10px 12px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '6px' }}>
                  <Sparkles size={13} color="var(--accent-steel)" />
                  <span style={{ fontSize: '0.68rem', fontWeight: 700, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                    REASONING MATRIX TELEMETRY
                  </span>
                </div>
                <p style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', lineHeight: 1.45 }}>
                  {agentState.llm_reasoning}
                </p>
              </div>
            )}

            {/* Authoritative Signed Cart Table */}
            {agentState.signed_cart?.line_items && (
              <div style={{ background: 'var(--bg-recessed)', border: '1px solid var(--border-line)' }}>
                <div style={{
                  padding: '8px 12px',
                  borderBottom: '1px solid var(--border-line)',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                }}>
                  <span style={{ fontSize: '0.7rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--text-phosphor)' }}>
                    AUTHORITATIVE MERCHANT CART MANIFEST
                  </span>
                  <span className="badge badge-green" style={{ fontSize: '0.65rem' }}>
                    DB PRICED · ZERO LLM CALC
                  </span>
                </div>

                <div style={{ padding: '8px 12px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  {agentState.signed_cart.line_items.map((item, i) => (
                    <div
                      key={i}
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        fontSize: '0.78rem',
                        padding: '4px 0',
                        borderBottom: '1px dashed var(--border-dim)',
                      }}
                    >
                      <div>
                        <span style={{ color: 'var(--text-phosphor)', fontWeight: 600 }}>{item.name}</span>
                        <span style={{ color: 'var(--text-muted)', marginLeft: '8px' }}>[QTY: {item.quantity}]</span>
                      </div>
                      <span style={{ color: 'var(--text-phosphor)', fontWeight: 700 }}>
                        ₹{(item.unit_price_paise * item.quantity / 100).toFixed(2)}
                      </span>
                    </div>
                  ))}

                  <div style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    marginTop: '8px',
                    paddingTop: '8px',
                    borderTop: '1px solid var(--border-line)',
                    fontWeight: 800,
                    fontSize: '0.85rem',
                  }}>
                    <span style={{ color: 'var(--text-muted)' }}>TOTAL SETTLEMENT SUM:</span>
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
                position: 'relative',
              }}>
                <div className="hazard-stripe-amber" />
                <div style={{ padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <AlertTriangle size={18} color="var(--accent-amber)" />
                    <div>
                      <h4 style={{ fontSize: '0.82rem', fontWeight: 800, color: 'var(--accent-amber)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                        POLICY INTERCEPT // HUMAN-IN-THE-LOOP AUTHORIZATION REQUIRED
                      </h4>
                      <p style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '2px' }}>
                        Catalog pricing exceeds initial budget threshold. Automated execution halted.
                      </p>
                    </div>
                  </div>

                  <div style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(3, 1fr)',
                    gap: '8px',
                    background: 'var(--bg-terminal)',
                    border: '1px solid var(--border-line)',
                    padding: '8px 10px',
                    fontSize: '0.75rem',
                  }}>
                    <div>
                      <span style={{ color: 'var(--text-muted)', fontSize: '0.68rem' }}>INITIAL CEILING:</span>
                      <p style={{ color: 'var(--text-secondary)', fontWeight: 700, marginTop: '2px' }}>
                        ₹{(agentState.escalation_details.current_budget_paise / 100).toFixed(2)}
                      </p>
                    </div>
                    <div>
                      <span style={{ color: 'var(--text-muted)', fontSize: '0.68rem' }}>MERCHANT QUOTE:</span>
                      <p style={{ color: 'var(--accent-amber)', fontWeight: 800, marginTop: '2px' }}>
                        ₹{(agentState.escalation_details.suggested_total_paise / 100).toFixed(2)}
                      </p>
                    </div>
                    <div>
                      <span style={{ color: 'var(--text-muted)', fontSize: '0.68rem' }}>OVERSPEND DELTA:</span>
                      <p style={{ color: 'var(--accent-red)', fontWeight: 800, marginTop: '2px' }}>
                        +₹{(agentState.escalation_details.overspend_paise / 100).toFixed(2)}
                      </p>
                    </div>
                  </div>

                  <div style={{ display: 'flex', gap: '8px' }}>
                    <button
                      className="btn btn-success"
                      onClick={handleEscalateApproval}
                      disabled={escalating}
                      style={{ flex: 1, fontSize: '0.75rem' }}
                    >
                      {escalating ? 'AUTHORIZING MANDATE...' : `[ AUTHORIZE & SIGN ₹${(agentState.escalation_details.suggested_total_paise / 100).toFixed(2)} ]`}
                    </button>
                    <button
                      className="btn btn-secondary"
                      onClick={handleDecline}
                      disabled={escalating}
                      style={{ fontSize: '0.75rem' }}
                    >
                      [ DECLINE ]
                    </button>
                  </div>
                </div>
              </div>
            )}

            {/* No Candidate Match Banner */}
            {agentState.status === 'NO_CANDIDATE_MATCH' && (
              <div style={{
                background: 'var(--bg-recessed)',
                border: '1px solid var(--border-bright)',
                borderLeft: '3px solid var(--accent-amber)',
                padding: '10px 12px',
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
              }}>
                <AlertTriangle size={16} color="var(--accent-amber)" />
                <span style={{ fontSize: '0.78rem', color: 'var(--text-phosphor)', fontWeight: 600 }}>
                  [ OUTCOME: NO_CANDIDATE_MATCH ] · ZERO RUPEES COMMITTED
                </span>
              </div>
            )}

            {/* Completed Outcome */}
            {agentState.status === 'COMPLETED' && (
              <div style={{
                background: 'var(--bg-recessed)',
                border: '1px solid var(--border-bright)',
                borderLeft: '3px solid var(--accent-terminal)',
                padding: '10px 12px',
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
              }}>
                <CheckCircle2 size={16} color="var(--accent-terminal)" />
                <span style={{ fontSize: '0.78rem', color: 'var(--accent-terminal)', fontWeight: 700 }}>
                  [ OUTCOME: MANDATE_ISSUED & ORDER_CREATED ] · CRYPTOGRAPHICALLY BOUND
                </span>
              </div>
            )}

            {/* Declined Outcome */}
            {agentState.status === 'USER_REJECTED' && (
              <div style={{
                background: 'var(--bg-recessed)',
                border: '1px solid var(--border-bright)',
                borderLeft: '3px solid var(--accent-red)',
                padding: '10px 12px',
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
              }}>
                <ShieldAlert size={16} color="var(--accent-red)" />
                <span style={{ fontSize: '0.78rem', color: 'var(--accent-red)', fontWeight: 700 }}>
                  [ OUTCOME: TRANSACTION_ABORTED_BY_USER ] · ZERO RUPEES MOVED
                </span>
              </div>
            )}

          </div>
        ) : (
          <div style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            height: '100%',
            color: 'var(--text-muted)',
            textAlign: 'center',
            gap: '8px',
            border: '1px dashed var(--border-line)',
            padding: '32px 16px',
          }}>
            <Terminal size={32} color="var(--border-bright)" />
            <p style={{ fontSize: '0.78rem', maxWidth: '300px', letterSpacing: '0.04em' }}>
              SELECT A PRESET SCENARIO OR TRANSMIT NATURAL LANGUAGE INTENT TO COMMENCE AGENTIC DELIBERATION.
            </p>
          </div>
        )}
      </div>

    </div>
  );
}
