import React, { useState, useEffect } from 'react';
import { Database, RefreshCw, ShieldCheck, CheckCircle2, ShieldAlert, Terminal } from 'lucide-react';
import { getLedgerEntries, verifyLedgerChain } from '../services/api';

export default function AuditLedgerTable({ refreshTrigger }) {
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(false);
  const [verifyStatus, setVerifyStatus] = useState(null);
  const [verifying, setVerifying] = useState(false);
  const [expandedPayloadIndex, setExpandedPayloadIndex] = useState(null);

  const fetchEntries = async () => {
    setLoading(true);
    try {
      const data = await getLedgerEntries(20);
      if (Array.isArray(data)) {
        setEntries(data);
      } else if (data && Array.isArray(data.entries)) {
        setEntries(data.entries);
      } else {
        setEntries([]);
      }
    } catch (err) {
      console.error('Failed to load ledger entries:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleVerify = async () => {
    setVerifying(true);
    try {
      const res = await verifyLedgerChain();
      setVerifyStatus(res);
    } catch (err) {
      console.error('Ledger verification failed:', err);
    } finally {
      setVerifying(false);
    }
  };

  useEffect(() => {
    fetchEntries();
    handleVerify();
  }, [refreshTrigger]);

  const getEntryBadge = (type) => {
    const badgeStyle = {
      display: 'inline-flex',
      alignItems: 'center',
      justifyContent: 'center',
      width: '124px',
      padding: '2px 6px',
      fontSize: '0.68rem',
      letterSpacing: '0.04em',
      textTransform: 'uppercase',
    };
    switch (type) {
      case 'INTENT_ISSUED':
        return <span className="badge badge-steel" style={badgeStyle}>[INTENT]</span>;
      case 'CART_SIGNED':
        return <span className="badge badge-steel" style={badgeStyle}>[CART_SIG]</span>;
      case 'MANDATE_CREATED':
        return <span className="badge badge-green" style={badgeStyle}>[MANDATE_ACTIVE]</span>;
      case 'POLICY_REJECTED':
        return <span className="badge badge-red" style={badgeStyle}>[POLICY_REJECT]</span>;
      case 'ORDER_CREATED':
        return <span className="badge badge-amber" style={badgeStyle}>[ORDER_CREATED]</span>;
      case 'WEBHOOK_RECEIVED':
        return <span className="badge badge-steel" style={badgeStyle}>[WEBHOOK]</span>;
      case 'PAYMENT_CAPTURED':
      case 'RECEIPT_ISSUED':
        return <span className="badge badge-green" style={badgeStyle}>[CAPTURED_PROOF]</span>;
      default:
        return <span className="badge badge-steel" style={badgeStyle}>[{type || 'LOG'}]</span>;
    }
  };

  const formatIST = (dateStr) => {
    if (!dateStr) return '—';
    const normalizedStr = dateStr.endsWith('Z') || dateStr.includes('+') ? dateStr : `${dateStr}Z`;
    const date = new Date(normalizedStr);
    if (isNaN(date.getTime())) return dateStr;
    return date.toLocaleString('en-IN', {
      timeZone: 'Asia/Kolkata',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: true,
    }) + ' IST';
  };

  return (
    <div className="panel-card" style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
      
      {/* Header */}
      <div className="panel-card-header" style={{ marginBottom: 0, display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px' }}>
        <div className="panel-title" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Database size={16} color="var(--text-phosphor)" />
          <span>APPEND-ONLY HASH-CHAINED AUDIT LEDGER // MAINFRAME LOG</span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: '8px' }}>
          {verifyStatus && (
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              fontFamily: 'var(--font-mono)',
              fontSize: '0.72rem',
              fontWeight: 700,
              color: verifyStatus.valid ? 'var(--accent-terminal)' : 'var(--accent-red)',
              background: 'var(--bg-recessed)',
              padding: '4px 8px',
              border: `1px solid ${verifyStatus.valid ? 'var(--accent-terminal)' : 'var(--accent-red)'}`,
              whiteSpace: 'nowrap',
            }}>
              {verifyStatus.valid ? <CheckCircle2 size={13} /> : <ShieldAlert size={13} />}
              <span>{verifyStatus.valid ? `CHAIN INTEGRITY: 100% LINEAR (${verifyStatus.total_entries || 0} BLOCKS)` : 'INTEGRITY ALERT: BROKEN CHAIN'}</span>
            </div>
          )}

          <button
            className="btn btn-secondary"
            onClick={handleVerify}
            disabled={verifying}
            style={{ padding: '4px 8px', fontSize: '0.7rem', whiteSpace: 'nowrap' }}
          >
            <ShieldCheck size={13} />
            {verifying ? 'AUDITING...' : '[ AUDIT CHAIN ]'}
          </button>

          <button
            className="btn btn-secondary"
            onClick={fetchEntries}
            disabled={loading}
            style={{ padding: '4px 8px', fontSize: '0.7rem', whiteSpace: 'nowrap' }}
          >
            <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
            [ RELOAD ]
          </button>
        </div>
      </div>

      {/* Mainframe Tabular Ledger View */}
      <div style={{ overflowX: 'auto', border: '1px solid var(--border-line)' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontFamily: 'var(--font-mono)', fontSize: '0.72rem' }}>
          <thead>
            <tr style={{ background: 'var(--bg-recessed)', borderBottom: '1px solid var(--border-bright)', color: 'var(--text-muted)' }}>
              <th style={{ padding: '8px 10px', width: '65px', whiteSpace: 'nowrap' }}>BLK #</th>
              <th style={{ padding: '8px 10px', width: '135px', whiteSpace: 'nowrap' }}>TIMESTAMP (IST)</th>
              <th style={{ padding: '8px 10px', width: '140px', whiteSpace: 'nowrap', textAlign: 'center' }}>EVENT TYPE</th>
              <th style={{ padding: '8px 10px', width: '130px', whiteSpace: 'nowrap' }}>ACTOR</th>
              <th style={{ padding: '8px 10px', minWidth: '175px' }}>SHA-256 BLOCK HASH</th>
              <th style={{ padding: '8px 10px', minWidth: '175px' }}>PREV HASH LINK</th>
              <th style={{ padding: '8px 10px', width: '85px', textAlign: 'center', whiteSpace: 'nowrap' }}>PAYLOAD</th>
            </tr>
          </thead>
          <tbody>
            {entries.length > 0 ? (
              entries.map((entry, idx) => {
                const blockSeq = entry.sequence_number || entry.id || idx + 1;
                const timestampVal = entry.created_at || entry.timestamp;
                const eventTypeVal = entry.entry_type || entry.event_type;
                const actorVal = entry.actor || entry.actor_id || 'system:core';
                const currentHashVal = entry.entry_hash || entry.current_hash;
                const prevHashVal = entry.prev_hash || entry.previous_hash;

                return (
                  <React.Fragment key={entry.id || idx}>
                    <tr
                      style={{
                        borderBottom: '1px solid var(--border-line)',
                        background: idx % 2 === 0 ? 'var(--bg-panel)' : 'var(--bg-recessed)',
                      }}
                    >
                      <td style={{ padding: '6px 10px', color: 'var(--text-muted)', fontWeight: 700, fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap' }}>
                        #{String(blockSeq).padStart(4, '0')}
                      </td>
                      <td style={{ padding: '6px 10px', color: 'var(--text-secondary)', fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap' }}>
                        {formatIST(timestampVal)}
                      </td>
                      <td style={{ padding: '6px 10px', textAlign: 'center' }}>
                        {getEntryBadge(eventTypeVal)}
                      </td>
                      <td style={{ padding: '6px 10px', color: 'var(--text-phosphor)', whiteSpace: 'nowrap' }}>
                        {actorVal}
                      </td>
                      <td style={{ padding: '6px 10px' }}>
                        <div style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: '6px',
                          background: 'var(--bg-recessed)',
                          padding: '2px 6px',
                          border: '1px solid var(--border-line)',
                          color: 'var(--accent-steel)',
                          fontFamily: 'var(--font-mono)',
                          fontSize: '0.7rem',
                          letterSpacing: '0.02em',
                        }} title={currentHashVal || ''}>
                          <span>{currentHashVal ? `${currentHashVal.substring(0, 18)}...` : '—'}</span>
                        </div>
                      </td>
                      <td style={{ padding: '6px 10px' }}>
                        <div style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: '6px',
                          background: 'var(--bg-recessed)',
                          padding: '2px 6px',
                          border: '1px solid var(--border-line)',
                          color: 'var(--text-muted)',
                          fontFamily: 'var(--font-mono)',
                          fontSize: '0.7rem',
                          letterSpacing: '0.02em',
                        }} title={prevHashVal || ''}>
                          <span>{prevHashVal ? `${prevHashVal.substring(0, 18)}...` : '000000000000000000...'}</span>
                        </div>
                      </td>
                      <td style={{ padding: '6px 10px', textAlign: 'center', whiteSpace: 'nowrap' }}>
                        <button
                          className="btn btn-secondary"
                          onClick={() => setExpandedPayloadIndex(expandedPayloadIndex === idx ? null : idx)}
                          style={{ padding: '2px 8px', fontSize: '0.65rem' }}
                        >
                          {expandedPayloadIndex === idx ? '[ HIDE ]' : '[ VIEW ]'}
                        </button>
                      </td>
                    </tr>

                  {expandedPayloadIndex === idx && (
                    <tr style={{ background: 'var(--bg-terminal)', borderBottom: '1px solid var(--border-bright)' }}>
                      <td colSpan="7" style={{ padding: '10px 14px' }}>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <span style={{ fontSize: '0.65rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                              RAW BLOCK RECORD TELEMETRY // FULL SIGNED PAYLOAD:
                            </span>
                            <span style={{ fontSize: '0.65rem', color: 'var(--accent-steel)', fontFamily: 'var(--font-mono)' }}>
                              BLOCK #{String(blockSeq).padStart(4, '0')} // {eventTypeVal}
                            </span>
                          </div>
                          <pre style={{
                            margin: 0,
                            padding: '8px 12px',
                            background: 'var(--bg-recessed)',
                            border: '1px solid var(--border-line)',
                            color: 'var(--text-phosphor)',
                            fontFamily: 'var(--font-mono)',
                            fontSize: '0.7rem',
                            lineHeight: 1.45,
                            maxHeight: '180px',
                            overflowY: 'auto',
                            whiteSpace: 'pre-wrap',
                            wordBreak: 'break-all',
                          }}>
                            {JSON.stringify(entry.payload || entry, null, 2)}
                          </pre>
                        </div>
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              );
            })
          ) : (
              <tr>
                <td colSpan="7" style={{ padding: '24px', textAlign: 'center', color: 'var(--text-muted)' }}>
                  NO LEDGER BLOCKS DISCOVERED. DELIBERATE AN INTENT TO GENERATE IMMUTABLE AUDIT RECORDS.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

    </div>
  );
}
