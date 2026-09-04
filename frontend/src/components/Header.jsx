import React, { useState, useEffect } from 'react';
import { ShieldCheck, Zap, Activity, Terminal, Lock } from 'lucide-react';

export default function Header({ chainValid, isLive = true }) {
  const [clockIST, setClockIST] = useState('');

  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      setClockIST(
        now.toLocaleTimeString('en-IN', {
          timeZone: 'Asia/Kolkata',
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
          hour12: false,
        }) + ' IST'
      );
    };
    updateTime();
    const timer = setInterval(updateTime, 1000);
    return () => clearInterval(timer);
  }, []);

  return (
    <header className="panel-card" style={{ padding: '14px 18px', borderBottom: '2px solid var(--border-bright)' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '16px' }}>
        
        {/* Masthead: Macro-Typography & Terminal ID */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
          <div style={{
            background: 'var(--text-phosphor)',
            color: 'var(--bg-terminal)',
            padding: '8px 10px',
            fontFamily: 'var(--font-mono)',
            fontWeight: 900,
            fontSize: '14px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            letterSpacing: '0.05em',
          }}>
            [MM]
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: '10px' }}>
              <h1 style={{
                fontFamily: 'var(--font-macro)',
                fontSize: '1.5rem',
                letterSpacing: '-0.04em',
                lineHeight: 1,
                color: 'var(--text-phosphor)',
              }}>
                MANDATE MESH
              </h1>
              <span className="badge badge-steel" style={{ fontSize: '0.68rem', padding: '1px 6px' }}>
                TACTICAL CONTROL TOWER // REV 2.4
              </span>
            </div>
            <p style={{ fontFamily: 'var(--font-mono)', fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '3px', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
              AGENTIC COMMERCE GUARDRAILS & DETERMINISTIC MULTI-MERCHANT ROUTING
            </p>
          </div>
        </div>

        {/* Security Invariant Framing */}
        <div style={{
          background: 'var(--bg-recessed)',
          border: '1px solid var(--border-line)',
          borderLeft: '3px solid var(--accent-red)',
          padding: '8px 14px',
          display: 'flex',
          alignItems: 'center',
          gap: '10px',
          maxWidth: '560px',
        }}>
          <ShieldCheck size={16} color="var(--accent-red)" style={{ flexShrink: 0 }} />
          <p style={{ fontFamily: 'var(--font-mono)', fontSize: '0.72rem', color: 'var(--text-secondary)', lineHeight: 1.3, letterSpacing: '0.02em' }}>
            <span style={{ color: 'var(--accent-red)', fontWeight: 800 }}>[ CORE INVARIANT ]</span>
            <br />
            THE LLM PROPOSES /// DETERMINISTIC PYTHON DISPOSES. ZERO UNAUTHORIZED RUPEES MOVE.
          </p>
        </div>

        {/* Hardware Status & Telemetry Readouts */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
          
          {/* Clock */}
          <div style={{
            background: 'var(--bg-recessed)',
            border: '1px solid var(--border-line)',
            padding: '5px 10px',
            fontFamily: 'var(--font-mono)',
            fontSize: '0.72rem',
            color: 'var(--text-muted)',
            letterSpacing: '0.08em',
          }}>
            <span style={{ color: 'var(--text-secondary)' }}>SYS/TIME: </span>
            <span style={{ color: 'var(--text-phosphor)', fontWeight: 700 }}>{clockIST || 'IST'}</span>
          </div>

          {/* Backend API */}
          <div style={{
            background: 'var(--bg-recessed)',
            border: '1px solid var(--border-line)',
            padding: '5px 10px',
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            fontFamily: 'var(--font-mono)',
            fontSize: '0.72rem',
          }}>
            <div className="pulse-dot" />
            <span style={{ color: 'var(--text-secondary)', fontWeight: 600 }}>API:8000</span>
            <span style={{ color: 'var(--accent-terminal)', fontWeight: 800 }}>[ONLINE]</span>
          </div>

          {/* Ledger Chain */}
          <div style={{
            background: 'var(--bg-recessed)',
            border: '1px solid var(--border-line)',
            padding: '5px 10px',
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            fontFamily: 'var(--font-mono)',
            fontSize: '0.72rem',
          }}>
            <Activity size={12} color={chainValid ? 'var(--accent-terminal)' : 'var(--accent-red)'} />
            <span style={{ color: 'var(--text-secondary)', fontWeight: 600 }}>CHAIN:</span>
            <span style={{ color: chainValid ? 'var(--accent-terminal)' : 'var(--accent-red)', fontWeight: 800 }}>
              {chainValid ? 'SECURE' : 'ALTERED'}
            </span>
          </div>

        </div>

      </div>
    </header>
  );
}
