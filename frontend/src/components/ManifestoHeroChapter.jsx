import React from 'react';
import { ArrowDown, Shield, Lock, Terminal } from 'lucide-react';

export default function ManifestoHeroChapter({ onAdvance }) {
  return (
    <section
      id="scene-00"
      className="snap-scene min-h-[calc(100vh-3.5rem)] flex flex-col justify-center py-8 px-4 sm:px-6 max-w-6xl mx-auto w-full"
    >
      {/* Structural Framing Header */}
      <div className="flex items-center justify-between border-b-2 border-black pb-3 mb-8 font-mono text-xs text-black">
        <span className="font-bold flex items-center gap-2">
          <span className="w-3 h-3 bg-[#E61919]" />
          SECTION // 00.0 : ARCHITECTURAL MANIFESTO
        </span>
        <span className="hidden sm:inline-block font-bold tracking-wider text-black/70">
          SPECIFICATION // NIST P-256 · DETERMINISTIC POLICY · ATOMIC CONTAINMENT
        </span>
      </div>

      {/* Blueprint Main Card */}
      <div className="blueprint-border-thick bg-[#F4F4F0] p-8 sm:p-12 relative shadow-[6px_6px_0px_0px_#050505]">
        {/* Top Identification Badge */}
        <div className="flex items-center justify-between border-b border-black pb-4 mb-8 font-mono text-xs">
          <div className="flex items-center gap-2">
            <span className="bg-black text-white px-2 py-0.5 font-bold text-[11px]">
              CORE THESIS
            </span>
            <span className="text-black/60 hidden sm:inline">
              MANDATE MESH SPECIFICATION v1.0
            </span>
          </div>
          <span className="text-[#E61919] font-bold">
            [ BOUNDED AUTONOMOUS COMMERCE ]
          </span>
        </div>

        {/* Massive Swiss Macro-Headline */}
        <h1 className="font-macro text-4xl sm:text-6xl md:text-7xl lg:text-8xl tracking-tighter text-black mb-8 leading-[0.88]">
          YOU PROMPT THE AI.
          <br />
          <span className="text-[#E61919]">
            POLICY COMMANDS THE MONEY.
          </span>
        </h1>

        {/* Core Architectural Manifesto Paragraph */}
        <p className="max-w-3xl text-black font-sans font-medium text-lg sm:text-xl mb-10 leading-relaxed border-l-4 border-black pl-6 py-1">
          Autonomous commerce requires mathematical containment. A natural-language shopping request is interpreted by machine intelligence, stamped by asymmetric cryptographic policy, decomposed across independent merchant rails, and reconciled without atomic loss.
        </p>

        {/* Advance Trigger CTA Bar */}
        <div className="pt-6 border-t-2 border-black flex flex-col sm:flex-row items-center justify-between gap-4 font-mono">
          <button
            onClick={onAdvance}
            className="w-full sm:w-auto px-8 py-4 bg-black hover:bg-[#E61919] text-white font-bold text-sm flex items-center justify-center gap-3 transition-colors cursor-pointer uppercase tracking-wider shadow-[4px_4px_0px_0px_#E61919]"
          >
            <span>[ INITIALIZE PROTAGONIST INTENT STREAM ↓ ]</span>
            <ArrowDown className="w-4 h-4 animate-bounce" />
          </button>

          <span className="text-xs text-black/60 font-bold hidden md:inline-block">
            STAGE 01 OF 08 FOLLOWS DIRECTLY ↓
          </span>
        </div>
      </div>
    </section>
  );
}
