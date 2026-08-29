import React from 'react';
import { Scale, CheckCircle2, AlertTriangle, ArrowDownRight, Award, ShieldCheck, RefreshCw, Zap } from 'lucide-react';

const MERCHANT_NAMES = {
  merchant_cakehouse_01: 'CakeHouse Bakery',
  merchant_sweetdelight_02: 'Sweet Delight Confectionery',
  merchant_artisan_03: 'Artisan Treats Lab',
};

export default function CompetitiveQuotePanel({ routingDecision, candidateQuotes }) {
  const quotes = candidateQuotes || routingDecision?.candidate_quotes || [];
  const hasData = quotes.length > 0;
  const isFallback = routingDecision?.fallback_applied;
  const savingsPaise = routingDecision?.price_savings_paise;

  return (
    <div className="panel-card" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      
      {/* Header & Metrics */}
      <div className="panel-card-header" style={{ marginBottom: 0 }}>
        <div className="panel-title">
          <Scale size={20} className="text-cyan" />
          <span>Multi-Merchant Competitive Quotes</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span className="badge badge-cyan" style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
            <Zap size={12} />
            Lowest Price Policy
          </span>
          {savingsPaise != null && savingsPaise > 0 && (
            <span className="badge badge-green" style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
              <ArrowDownRight size={12} />
              Saved ₹{(savingsPaise / 100).toFixed(2)} vs Runner-Up
            </span>
          )}
        </div>
      </div>

      {/* JIT Fallback Notification Banner */}
      {isFallback && (
        <div
          style={{
            background: 'linear-gradient(135deg, rgba(245, 158, 11, 0.15), rgba(245, 158, 11, 0.05))',
            border: '1px solid var(--accent-amber)',
            borderRadius: 'var(--radius-md)',
            padding: '12px 16px',
            display: 'flex',
            alignItems: 'flex-start',
            gap: '12px',
          }}
        >
          <RefreshCw size={20} className="text-amber" style={{ marginTop: '2px', flexShrink: 0 }} />
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <strong style={{ fontSize: '0.85rem', color: 'var(--accent-amber)' }}>
                Just-In-Time Revalidation Fallback Triggered
              </strong>
              <span className="badge badge-amber" style={{ fontSize: '0.65rem' }}>Auto-Resolved</span>
            </div>
            <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
              Initial winner <code className="font-mono text-cyan">{MERCHANT_NAMES[routingDecision.fallback_from_merchant] || routingDecision.fallback_from_merchant}</code> failed pre-authorization check ({routingDecision.fallback_reason || 'Verification Failed'}). The policy rail automatically promoted the verified runner-up <code className="font-mono text-green">{MERCHANT_NAMES[routingDecision.winner_merchant_id] || routingDecision.winner_merchant_id}</code>.
            </p>
          </div>
        </div>
      )}

      {/* Candidate Quotes Comparison Cards */}
      {hasData ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '12px' }}>
            {quotes.map((q, idx) => {
              const isWinner = q.is_winner;
              const isEligible = q.status === 'ELIGIBLE';
              const merchantLabel = MERCHANT_NAMES[q.merchant_id] || q.merchant_id;
              
              return (
                <div
                  key={idx}
                  style={{
                    background: isWinner
                      ? 'linear-gradient(135deg, rgba(16, 185, 129, 0.12), rgba(16, 185, 129, 0.04))'
                      : 'var(--bg-surface)',
                    border: isWinner
                      ? '1px solid var(--accent-green)'
                      : '1px solid var(--border-subtle)',
                    borderRadius: 'var(--radius-md)',
                    padding: '14px',
                    display: 'flex',
                    flexDirection: 'column',
                    justifyContent: 'space-between',
                    gap: '10px',
                    position: 'relative',
                    transition: 'transform 0.2s ease',
                    boxShadow: isWinner ? '0 0 20px rgba(16, 185, 129, 0.15)' : 'none',
                  }}
                >
                  {/* Top: Merchant Identity & Winner Badge */}
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                    <div>
                      <h4 style={{ fontSize: '0.9rem', fontWeight: 700, color: 'var(--text-primary)' }}>
                        {merchantLabel}
                      </h4>
                      <span className="font-mono text-muted" style={{ fontSize: '0.72rem' }}>
                        {q.merchant_id}
                      </span>
                    </div>
                    {isWinner && (
                      <span className="badge badge-green" style={{ fontSize: '0.7rem' }}>
                        <Award size={12} />
                        Winner
                      </span>
                    )}
                  </div>

                  {/* Middle: Price & Delta */}
                  <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
                    <div>
                      <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Verified Total</span>
                      <p className="font-mono" style={{ fontSize: '1.2rem', fontWeight: 700, color: isWinner ? 'var(--accent-green)' : 'var(--text-primary)' }}>
                        {q.total_paise != null ? `₹${(q.total_paise / 100).toFixed(2)}` : 'N/A'}
                      </p>
                    </div>
                    {q.price_delta_paise != null && q.price_delta_paise > 0 && (
                      <span className="badge badge-amber" style={{ fontSize: '0.7rem' }}>
                        +₹{(q.price_delta_paise / 100).toFixed(2)}
                      </span>
                    )}
                    {isWinner && (
                      <span className="badge badge-cyan" style={{ fontSize: '0.7rem' }}>
                        Best Price
                      </span>
                    )}
                  </div>

                  {/* Bottom: 7-Gate Status */}
                  <div style={{ borderTop: '1px solid rgba(255,255,255,0.06)', paddingTop: '8px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Policy Gate</span>
                    {isEligible ? (
                      <span className="badge badge-green" style={{ fontSize: '0.68rem' }}>
                        <ShieldCheck size={11} />
                        Verified Eligible
                      </span>
                    ) : (
                      <span className="badge badge-red" style={{ fontSize: '0.68rem' }}>
                        <AlertTriangle size={11} />
                        {q.status}
                      </span>
                    )}
                  </div>

                  {/* Rejection Details */}
                  {q.rejection_reason && (
                    <p style={{ fontSize: '0.72rem', color: 'var(--accent-red)', marginTop: '-4px', background: 'rgba(239, 68, 68, 0.08)', padding: '4px 6px', borderRadius: 'var(--radius-sm)' }}>
                      {q.rejection_reason}
                    </p>
                  )}
                </div>
              );
            })}
          </div>

          {/* Decision Rationale */}
          {routingDecision?.decision_rationale && (
            <div style={{ background: 'var(--bg-card-hover)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)', padding: '10px 14px' }}>
              <span style={{ fontSize: '0.72rem', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                Deterministic Routing Rationale
              </span>
              <p className="font-mono text-cyan" style={{ fontSize: '0.8rem', marginTop: '2px' }}>
                {routingDecision.decision_rationale}
              </p>
            </div>
          )}
        </div>
      ) : (
        /* Empty State */
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '36px 16px', color: 'var(--text-muted)', textAlign: 'center', gap: '8px' }}>
          <Scale size={36} style={{ opacity: 0.35 }} />
          <p style={{ fontSize: '0.85rem' }}>
            Awaiting buyer agent goal. The system will query all authorized merchants and select the optimal quote.
          </p>
          <div style={{ display: 'flex', gap: '8px', marginTop: '8px' }}>
            <span className="badge badge-cyan" style={{ fontSize: '0.7rem' }}>CakeHouse Bakery (₹940)</span>
            <span className="badge badge-green" style={{ fontSize: '0.7rem' }}>Sweet Delight (₹890)</span>
            <span className="badge badge-amber" style={{ fontSize: '0.7rem' }}>Artisan Treats (₹1200)</span>
          </div>
        </div>
      )}

    </div>
  );
}
