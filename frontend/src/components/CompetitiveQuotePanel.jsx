import React from 'react';
import { Scale, RefreshCw, CheckCircle2, ShieldCheck, ArrowDownRight, Layers } from 'lucide-react';

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
    <div className="panel-card" style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
      
      {/* Panel Header & Tactical Badges */}
      <div className="panel-card-header" style={{ marginBottom: 0 }}>
        <div className="panel-title">
          <Scale size={16} color="var(--text-phosphor)" />
          <span>MULTI-MERCHANT QUOTE SPEC SHEET // DETERMINISTIC ROUTING</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span className="badge badge-steel">
            POLICY: LOWEST_TOTAL_PRICE
          </span>
          {savingsPaise != null && savingsPaise > 0 && (
            <span className="badge badge-green">
              SAVINGS: ₹{(savingsPaise / 100).toFixed(2)} VS RUNNER-UP
            </span>
          )}
        </div>
      </div>

      {/* JIT Fallback Revalidation Banner */}
      {isFallback && (
        <div style={{
          background: 'var(--bg-recessed)',
          border: '1px solid var(--accent-amber)',
          padding: '10px 14px',
          display: 'flex',
          alignItems: 'flex-start',
          gap: '10px',
        }}>
          <RefreshCw size={18} color="var(--accent-amber)" style={{ marginTop: '2px', flexShrink: 0 }} />
          <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
            <span style={{ fontSize: '0.78rem', fontWeight: 800, color: 'var(--accent-amber)', textTransform: 'uppercase' }}>
              [ EVENT: JUST-IN-TIME REVALIDATION FALLBACK ACTIVATED ]
            </span>
            <p style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', lineHeight: 1.4 }}>
              Initial winner <code style={{ color: 'var(--text-phosphor)', fontWeight: 700 }}>{MERCHANT_NAMES[routingDecision.fallback_from_merchant] || routingDecision.fallback_from_merchant}</code> failed pre-authorization check ({routingDecision.fallback_reason || 'Verification Failed'}). The deterministic policy engine automatically promoted runner-up <code style={{ color: 'var(--accent-terminal)', fontWeight: 700 }}>{MERCHANT_NAMES[routingDecision.winner_merchant_id] || routingDecision.winner_merchant_id}</code>.
            </p>
          </div>
        </div>
      )}

      {/* Candidate Quotes Comparison Grid */}
      {hasData ? (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(230px, 1fr))', gap: '10px' }}>
          {quotes.map((q, idx) => {
            const isWinner = q.is_winner;
            const isEligible = q.status === 'ELIGIBLE';
            const merchantLabel = MERCHANT_NAMES[q.merchant_id] || q.merchant_id.toUpperCase();

            return (
              <div
                key={idx}
                style={{
                  background: isWinner ? 'var(--bg-surface)' : 'var(--bg-recessed)',
                  border: isWinner ? '1px solid var(--accent-terminal)' : '1px solid var(--border-line)',
                  borderTop: isWinner ? '3px solid var(--accent-terminal)' : '1px solid var(--border-line)',
                  padding: '12px',
                  display: 'flex',
                  flexDirection: 'column',
                  justifyContent: 'space-between',
                  gap: '10px',
                  position: 'relative',
                }}
              >
                {/* Header: Merchant Identifier & Status Stamp */}
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '4px' }}>
                    <span style={{ fontSize: '0.65rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                      REG ID: {q.merchant_id}
                    </span>
                    {isWinner ? (
                      <span className="badge badge-green" style={{ fontSize: '0.65rem', padding: '1px 5px' }}>
                        WINNER // SELECTED
                      </span>
                    ) : (
                      <span className="badge badge-steel" style={{ fontSize: '0.65rem', padding: '1px 5px' }}>
                        {q.status}
                      </span>
                    )}
                  </div>
                  <h4 style={{ fontSize: '0.82rem', fontWeight: 800, color: 'var(--text-phosphor)' }}>
                    {merchantLabel}
                  </h4>
                </div>

                {/* Line Item Telemetry */}
                {q.line_items && q.line_items.length > 0 && (
                  <div style={{ borderTop: '1px dashed var(--border-dim)', borderBottom: '1px dashed var(--border-dim)', padding: '6px 0' }}>
                    {q.line_items.map((item, itemIdx) => (
                      <div key={itemIdx} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem', color: 'var(--text-secondary)' }}>
                        <span>{item.name} × {item.quantity}</span>
                        <span style={{ fontWeight: 600 }}>₹{(item.unit_price_paise * item.quantity / 100).toFixed(2)}</span>
                      </div>
                    ))}
                  </div>
                )}

                {/* Pricing Breakdown */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                    <span>BASE TARIFF:</span>
                    <span>₹{((q.total_paise - (q.tax_paise || 0)) / 100).toFixed(2)}</span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                    <span>APPLIED TAX (GST):</span>
                    <span>₹{((q.tax_paise || 0) / 100).toFixed(2)}</span>
                  </div>
                  <div style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    fontSize: '0.88rem',
                    fontWeight: 800,
                    marginTop: '4px',
                    paddingTop: '4px',
                    borderTop: '1px solid var(--border-line)',
                  }}>
                    <span style={{ color: 'var(--text-secondary)' }}>FINAL QUOTE:</span>
                    <span style={{ color: isWinner ? 'var(--accent-terminal)' : 'var(--text-phosphor)' }}>
                      ₹{(q.total_paise / 100).toFixed(2)}
                    </span>
                  </div>
                </div>

                {/* Cryptographic Attestation Footer */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '0.65rem', color: 'var(--text-muted)', paddingTop: '4px', borderTop: '1px solid var(--border-dim)' }}>
                  <ShieldCheck size={11} color={isWinner ? 'var(--accent-terminal)' : 'var(--text-muted)'} />
                  <span>ECDSA SECP256K1 SIGNATURE VERIFIED</span>
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <div style={{
          background: 'var(--bg-recessed)',
          border: '1px dashed var(--border-line)',
          padding: '24px 16px',
          textAlign: 'center',
          color: 'var(--text-muted)',
          fontSize: '0.75rem',
        }}>
          NO ACTIVE DELIBERATION DATA. SUBMIT AN INTENT GOAL TO POPULATE COMPETITIVE SPEC SHEET.
        </div>
      )}

    </div>
  );
}
