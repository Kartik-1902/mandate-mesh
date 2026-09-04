import React, { useState, useEffect } from 'react';
import { ShieldCheck, Activity } from 'lucide-react';

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
    <header className="panel-card" style={{ padding: '10px 16px', borderBottom: '1px solid var(--border-line)' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px' }}>
        
        {/* Brand & Mode */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <div style={{
            background: 'var(--text-phosphor)',
            color: 'var(--bg-terminal)',
            padding: '4px 6px',
            fontFamily: 'var(--font-mono)',
            fontWeight: 900,
            fontSize: '11px',
            letterSpacing: '0.05em',
            lineHeight: 1,
          }}>
            MM
          </div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px' }}>
            <h1 style={{
              fontFamily: 'var(--font-macro)',
              fontSize: '1.15rem',
              letterSpacing: '-0.03em',
              lineHeight: 1,
              color: 'var(--text-phosphor)',
            }}>
              MANDATE MESH
            </h1>
            <span style={{ fontSize: '0.68rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase' }}>
              CONTROL TOWER
            </span>
          </div>
        </div>

        {/* Compact Invariant Pill */}
        <div style={{
          background: 'var(--bg-recessed)',
          border: '1px solid var(--border-line)',
          borderLeft: '2px solid var(--accent-red)',
          padding: '4px 10px',
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          fontFamily: 'var(--font-mono)',
          fontSize: '0.7rem',
          color: 'var(--text-secondary)',
        }}>
          <ShieldCheck size={13} color="var(--accent-red)" style={{ flexShrink: 0 }} />
          <span>
            <strong style={{ color: 'var(--accent-red)' }}>INVARIANT:</strong> LLM Proposes · Python Disposes · 0 Unauthorized Rupees
          </span>
        </div>

        {/* Consolidated Telemetry Cluster */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '12px',
          background: 'var(--bg-recessed)',
          border: '1px solid var(--border-line)',
          padding: '4px 10px',
          fontFamily: 'var(--font-mono)',
          fontSize: '0.7rem',
        }}>
          {/* API */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
            <div className="pulse-dot" style={{ width: '5px', height: '5px' }} />
            <span style={{ color: 'var(--text-muted)' }}>API:</span>
            <span style={{ color: 'var(--accent-terminal)', fontWeight: 700 }}>8000</span>
          </div>

          <span style={{ color: 'var(--border-line)' }}>|</span>

          {/* Chain */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
            <Activity size={11} color={chainValid ? 'var(--accent-terminal)' : 'var(--accent-red)'} />
            <span style={{ color: 'var(--text-muted)' }}>CHAIN:</span>
            <span style={{ color: chainValid ? 'var(--accent-terminal)' : 'var(--accent-red)', fontWeight: 700 }}>
              {chainValid ? '100% LINEAR' : 'ALTERED'}
            </span>
          </div>

          <span style={{ color: 'var(--border-line)' }}>|</span>

          {/* Clock */}
          <div style={{ color: 'var(--text-phosphor)', fontWeight: 600 }}>
            {clockIST || 'IST'}
          </div>
        </div>

      </div>
    </header>
  );
}
