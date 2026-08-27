import React from 'react';
import { ShieldCheck, Zap, Activity, Lock } from 'lucide-react';

export default function Header({ chainValid, isLive = true }) {
  return (
    <header className="panel-card" style={{ padding: '16px 24px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '16px' }}>
        
        {/* Brand & Invariant */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          <div style={{
            background: 'linear-gradient(135deg, #00f0ff, #0077ff)',
            padding: '10px',
            borderRadius: '12px',
            boxShadow: '0 0 20px rgba(0, 240, 255, 0.4)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}>
            <Lock size={24} color="#050914" />
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <h1 style={{ fontSize: '1.4rem', fontWeight: '800', letterSpacing: '-0.02em', background: 'linear-gradient(to right, #ffffff, #94a3b8)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
                MANDATE MESH
              </h1>
              <span className="badge badge-cyan">CONTROL TOWER</span>
            </div>
            <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
              Track 01: AI Growth & Agentic Commerce · Razorpay Buildathon
            </p>
          </div>
        </div>

        {/* Security Invariant Pill */}
        <div style={{
          background: 'rgba(15, 23, 42, 0.8)',
          border: '1px solid var(--border-glow)',
          borderRadius: 'var(--radius-md)',
          padding: '8px 16px',
          display: 'flex',
          alignItems: 'center',
          gap: '12px',
          maxWidth: '520px',
        }}>
          <ShieldCheck size={18} className="text-cyan" style={{ flexShrink: 0 }} />
          <p style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', lineHeight: 1.3 }}>
            <strong className="text-cyan">Core Invariant:</strong> <em>The LLM proposes; deterministic Python disposes. An unauthorized rupee can never move.</em>
          </p>
        </div>

        {/* Live System Status Badges */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', background: 'var(--bg-surface)', padding: '6px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
            <div className="pulse-dot pulse-dot-green" />
            <span style={{ fontSize: '0.75rem', fontWeight: 600 }}>Backend API :8000</span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', background: 'var(--bg-surface)', padding: '6px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
            <Zap size={14} className="text-amber" />
            <span style={{ fontSize: '0.75rem', fontWeight: 600 }}>Razorpay Test Mode</span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', background: 'var(--bg-surface)', padding: '6px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
            <Activity size={14} className={chainValid ? 'text-green' : 'text-red'} />
            <span style={{ fontSize: '0.75rem', fontWeight: 600 }}>
              Ledger: {chainValid ? '100% Linear' : 'Check Chain'}
            </span>
          </div>
        </div>

      </div>
    </header>
  );
}
