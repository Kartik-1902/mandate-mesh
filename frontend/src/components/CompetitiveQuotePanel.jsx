import React from 'react';
import { Scale, RefreshCw, CheckCircle2, ShieldCheck, ArrowDownRight } from 'lucide-react';

const MERCHANT_NAMES = {
  merchant_cakehouse_01: 'CAKEHOUSE BAKERY',
  merchant_sweetdelight_02: 'SWEET DELIGHT CONFECTIONERY',
  merchant_artisan_03: 'ARTISAN TREATS LAB',
};

export default function CompetitiveQuotePanel({ routingDecision, candidateQuotes }) {
  const quotes = candidateQuotes || routingDecision?.candidate_quotes || [];
  const hasData = quotes.length > 0;
  const isFallback = routingDecision?.fallback_applied;
  const savingsPaise = routingDecision?.price_savings_paise;

  return (
    <div className="panel-card" style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
      
      {/* Header */}
      <div className="panel-card-header" style={{ marginBottom: 0, paddingBottom: '6px' }}>
        <div className="panel-title">
          <Scale size={14} color="var(--text-phosphor)" />
          <span>MULTI-MERCHANT ROUTING</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span className="badge badge-steel" style={{ fontSize: '0.65rem' }}>
            LOWEST PRICE POLICY
          </span>
          {savingsPaise != null && savingsPaise > 0 && (
            <span className="badge badge-green" style={{ fontSize: '0.65rem' }}>
              SAVED ₹{(savingsPaise / 100).toFixed(2)}
            </span>
          )}
        </div>
      </div>

      {/* JIT Fallback Notice */}
      {isFallback && (
        <div style={{
          background: 'var(--bg-recessed)',
          border: '1px solid var(--accent-amber)',
          padding: '8px 10px',
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          fontSize: '0.72rem',
        }}>
          <RefreshCw size={14} color="var(--accent-amber)" style={{ flexShrink: 0 }} />
          <p style={{ color: 'var(--text-secondary)', margin: 0 }}>
            <strong style={{ color: 'var(--accent-amber)' }}>FALLBACK TRIGGERED: </strong>
            Promoted runner-up <code style={{ color: 'var(--accent-terminal)', fontWeight: 700 }}>{MERCHANT_NAMES[routingDecision.winner_merchant_id] || routingDecision.winner_merchant_id}</code> after pre-auth check failed on initial winner.
          </p>
        </div>
      )}

      {/* Candidate Quotes Comparison Grid */}
      {hasData ? (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '8px' }}>
          {quotes.map((q, idx) => {
            const isWinner = q.is_winner;
            const merchantLabel = MERCHANT_NAMES[q.merchant_id] || q.merchant_id.toUpperCase();

            return (
              <div
                key={idx}
                style={{
                  background: isWinner ? 'var(--bg-surface)' : 'var(--bg-recessed)',
                  border: isWinner ? '1px solid var(--accent-terminal)' : '1px solid var(--border-line)',
                  borderTop: isWinner ? '2px solid var(--accent-terminal)' : '1px solid var(--border-line)',
                  padding: '10px',
                  display: 'flex',
                  flexDirection: 'column',
                  justifyContent: 'space-between',
                  gap: '8px',
                }}
              >
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '2px' }}>
                    <span style={{ fontSize: '0.62rem', color: 'var(--text-muted)' }}>
                      {q.merchant_id.replace('merchant_', '')}
                    </span>
                    {isWinner ? (
                      <span className="badge badge-green" style={{ fontSize: '0.6rem', padding: '1px 4px' }}>
                        SELECTED
                      </span>
                    ) : (
                      <span className="badge badge-steel" style={{ fontSize: '0.6rem', padding: '1px 4px' }}>
                        {q.status}
                      </span>
                    )}
                  </div>
                  <h4 style={{ fontSize: '0.78rem', fontWeight: 800, color: 'var(--text-phosphor)' }}>
                    {merchantLabel}
                  </h4>
                </div>

                {/* Line Items Brief */}
                {q.line_items && q.line_items.length > 0 && (
                  <div style={{ fontSize: '0.68rem', color: 'var(--text-secondary)' }}>
                    {q.line_items.map((item, itemIdx) => (
                      <div key={itemIdx} style={{ display: 'flex', justifyContent: 'space-between' }}>
                        <span>{item.name}</span>
                        <span>₹{(item.unit_price_paise * item.quantity / 100).toFixed(2)}</span>
                      </div>
                    ))}
                  </div>
                )}

                {/* Total */}
                <div style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'baseline',
                  borderTop: '1px solid var(--border-line)',
                  paddingTop: '4px',
                  fontWeight: 800,
                  fontSize: '0.85rem',
                }}>
                  <span style={{ fontSize: '0.68rem', color: 'var(--text-muted)' }}>QUOTE:</span>
                  <span style={{ color: isWinner ? 'var(--accent-terminal)' : 'var(--text-phosphor)' }}>
                    ₹{(q.total_paise / 100).toFixed(2)}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <div style={{
          background: 'var(--bg-recessed)',
          border: '1px dashed var(--border-line)',
          padding: '16px',
          textAlign: 'center',
          color: 'var(--text-muted)',
          fontSize: '0.72rem',
        }}>
          DELIBERATE AN INTENT TO POPULATE MULTI-MERCHANT QUOTES.
        </div>
      )}

    </div>
  );
}
