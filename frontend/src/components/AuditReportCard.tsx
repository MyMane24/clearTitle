import React from 'react';
import { Shield, AlertTriangle, FileWarning, CheckCircle, HelpCircle } from 'lucide-react';

interface AuditReportCardProps {
  onStartAudit: () => void;
}

export const AuditReportCard: React.FC<AuditReportCardProps> = ({ onStartAudit }) => {
  return (
    <div className="space-y-6">

      {/* Main Audit Card — AUDIT REPORT // CASE-CT-881 */}
      <div className="premium-glass-card rounded-3xl border border-[#e9e1dd] overflow-hidden">
        <div className="bg-[#FAF2EE]/80 px-6 py-3.5 border-b border-[#e9e1dd] flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full bg-orange-400" />
              <span className="w-2.5 h-2.5 rounded-full bg-amber-400" />
              <span className="w-2.5 h-2.5 rounded-full bg-emerald-400" />
            </div>
            <span className="text-slate-300">|</span>
            <div className="flex items-center gap-2 font-mono text-xs text-slate-700">
              <Shield className="w-4 h-4 text-orange-600" />
              <span className="font-bold tracking-wide">AUDIT REPORT // CASE-CT-881</span>
            </div>
          </div>
          <div className="flex items-center gap-2 font-mono text-xs">
            <span className="bg-emerald-50 text-emerald-700 font-bold px-3 py-1 rounded-full border border-emerald-200 flex items-center gap-1.5 shadow-xs">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-ping" /> Live Engine Active
            </span>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-12 divide-y lg:divide-y-0 lg:divide-x divide-[#e9e1dd]">

          {/* Left Side: Property Identifiers & Verification Pills */}
          <div className="lg:col-span-7 p-6 sm:p-8 space-y-6">
            <div className="space-y-1.5">
              <div className="flex items-center gap-2 font-mono text-xs">
                <span className="text-orange-700 bg-orange-50 font-bold px-2 py-0.5 rounded border border-orange-200">KA-BEL-4XX</span>
                <span className="text-slate-400 font-medium">Registered Deed (2021)</span>
              </div>
              <h3 className="text-2xl sm:text-3xl font-black text-slate-900 tracking-tight">
                CTS No. 4XX/A-1, Tilakwadi, Belagavi
              </h3>
              <p className="text-xs text-slate-500 font-mono">
                Audited: Sale Deed (2021), EC (2010–2025), e-Khata Extract
              </p>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5 font-mono text-xs">
              <div className="soft-inner-card p-4 rounded-2xl border border-[#e9e1dd] space-y-1.5 hover:border-orange-300 transition-colors">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] text-slate-400 font-bold uppercase tracking-wider">DOC VALIDITY</span>
                  <span className="text-emerald-700 bg-emerald-50 text-[10px] font-bold px-2 py-0.5 rounded border border-emerald-200">100% MATCH</span>
                </div>
                <p className="font-bold text-slate-900 text-sm">Valid Property Record</p>
                <p className="text-[11px] text-slate-500 leading-relaxed">All details consistent across documents</p>
              </div>

              <div className="soft-inner-card p-4 rounded-2xl border border-[#e9e1dd] space-y-1.5 hover:border-orange-300 transition-colors">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] text-slate-400 font-bold uppercase tracking-wider">TITLE CHAIN AUDIT</span>
                  <span className="text-emerald-700 bg-emerald-50 text-[10px] font-bold px-2 py-0.5 rounded border border-emerald-200">3 LINKS</span>
                </div>
                <p className="font-bold text-slate-900 text-sm">Chain Traced &amp; Verified</p>
                <p className="text-[11px] text-slate-500 leading-relaxed">Ownership linked back to the sanctioned layout</p>
              </div>
            </div>
          </div>

          {/* Right Side: Trust Score & Critical Red Flag */}
          <div className="lg:col-span-5 p-6 sm:p-8 bg-[#FAF2EE]/40 flex flex-col justify-between space-y-6">
            <div className="shimmer-effect relative bg-gradient-to-br from-emerald-50 via-white to-emerald-50/70 p-5 rounded-2xl border border-emerald-200 shadow-md shadow-emerald-600/10 flex items-center justify-between overflow-hidden">
              <div className="flex items-center gap-3.5 relative z-10">
                <div className="shield-pulse w-11 h-11 rounded-2xl bg-emerald-600 text-white flex items-center justify-center shadow-lg shadow-emerald-600/30 flex-shrink-0">
                  <Shield className="w-5 h-5" />
                </div>
                <div className="space-y-0.5">
                  <span className="text-[10px] font-mono font-bold text-emerald-800 uppercase tracking-wider block">TRUST SCORE</span>
                  <span className="text-xs text-slate-500">Title Confidence Index</span>
                </div>
              </div>
              <div className="text-right relative z-10">
                <span className="text-3xl font-black text-emerald-600 font-mono tracking-tight">84<span className="text-xs font-semibold text-emerald-700/60">/100</span></span>
                <span className="text-[10px] font-mono font-bold text-amber-700 bg-amber-50 px-2 py-0.5 rounded border border-amber-200 block mt-0.5">Review Required</span>
              </div>
            </div>

            <div className="bg-rose-50/90 border border-rose-200/90 rounded-2xl p-4 text-rose-950 space-y-2 shadow-xs">
              <div className="flex items-center gap-2">
                <AlertTriangle className="w-5 h-5 text-rose-600" />
                <span className="font-mono text-xs font-bold text-rose-900 uppercase tracking-wide">Critical Survey Alert</span>
              </div>
              <p className="text-xs text-rose-800 leading-relaxed">
                Deed cites parent <strong className="font-mono font-bold text-rose-950">Sy No. 6XX/1 paiki</strong>, but 2018 Mutation records sub-divided parcel <strong className="font-mono font-bold text-rose-950">Sy No. 6XX/1-A/2</strong>. Boundary mismatch flagged.
              </p>
              <button
                onClick={onStartAudit}
                className="w-full mt-2 py-2.5 px-3 rounded-xl bg-rose-600 hover:bg-rose-700 text-white font-bold text-xs font-mono transition-colors shadow-xs flex items-center justify-center gap-1.5 cursor-pointer"
              >
                <span>Inspect Survey Conflict</span>
                <AlertTriangle className="w-4 h-4" />
              </button>
            </div>

          </div>

        </div>
      </div>

      {/* Snapshots Side by Side */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

        {/* SNAPSHOT 01 • DOCUMENT AUDIT OVERVIEW */}
        <div className="rounded-2xl border border-[#e9e1dd] overflow-hidden bg-white/95 shadow-md shadow-orange-500/5">
          <div className="bg-[#FAF2EE]/80 px-4 py-2.5 border-b border-[#e9e1dd] flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2 font-mono text-[11px] text-slate-700">
              <Shield className="w-3.5 h-3.5 text-orange-600" />
              <span className="font-bold tracking-wide">SNAPSHOT 01 • DOCUMENT AUDIT OVERVIEW</span>
            </div>
            <span className="bg-amber-50 text-amber-700 font-bold px-2 py-0.5 rounded-full border border-amber-200 text-[10px] font-mono shadow-xs">
              Review Required
            </span>
          </div>
          <div className="p-4 space-y-3">
            <div className="grid grid-cols-3 gap-2.5">
              <div className="soft-inner-card p-3 rounded-xl border border-[#e9e1dd] text-center">
                <span className="text-[9px] text-slate-400 font-bold uppercase tracking-wider block font-mono">Docs Reviewed</span>
                <span className="text-2xl font-black text-slate-900 font-mono">02</span>
              </div>
              <div className="soft-inner-card p-3 rounded-xl border border-[#e9e1dd] text-center">
                <span className="text-[9px] text-slate-400 font-bold uppercase tracking-wider block font-mono">Positive</span>
                <span className="text-2xl font-black text-emerald-600 font-mono">04</span>
              </div>
              <div className="soft-inner-card p-3 rounded-xl border border-[#e9e1dd] text-center">
                <span className="text-[9px] text-slate-400 font-bold uppercase tracking-wider block font-mono">Red Flags</span>
                <span className="text-2xl font-black text-rose-600 font-mono">02</span>
              </div>
            </div>
            <div className="soft-inner-card p-3 rounded-xl border border-[#e9e1dd]">
              <p className="text-xs text-slate-700 font-medium leading-relaxed">
                Reference Document: Sale Deed (2021)
              </p>
              <p className="text-[11px] text-slate-500 font-mono mt-0.5">
                Valid Property Record • Area: 1200 Sq. Fts. • Survey No: CTS No. 4XX/A-1
              </p>
            </div>
          </div>
        </div>

        {/* SNAPSHOT 02 • RED FLAG AUDIT MATRIX */}
        <div className="rounded-2xl border border-[#e9e1dd] overflow-hidden bg-white/95 shadow-md shadow-orange-500/5">
          <div className="bg-[#FAF2EE]/80 px-4 py-2.5 border-b border-[#e9e1dd] flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2 font-mono text-[11px] text-slate-700">
              <AlertTriangle className="w-3.5 h-3.5 text-orange-600" />
              <span className="font-bold tracking-wide">SNAPSHOT 02 • RED FLAG AUDIT MATRIX</span>
            </div>
            <span className="bg-rose-50 text-rose-700 font-bold px-2 py-0.5 rounded-full border border-rose-200 text-[10px] font-mono shadow-xs">
              3 Findings
            </span>
          </div>
          <div className="p-4 space-y-2.5">
            <div className="bg-rose-50/90 border border-rose-200/90 rounded-xl p-3 text-rose-950 space-y-1">
              <div className="flex items-center gap-1.5">
                <FileWarning className="w-4 h-4 text-rose-600" />
                <span className="font-mono text-[10px] font-bold text-rose-900 uppercase tracking-wide">CRITICAL FLAG: Survey Boundary Inconsistency</span>
              </div>
              <p className="text-[11px] text-rose-800 leading-relaxed">
                Deed cites parent <strong className="font-mono font-bold text-rose-950">Sy No. 6XX/1 paiki</strong>, but mutation records sub-divided parcel <strong className="font-mono font-bold text-rose-950">Sy No. 6XX/1-A/2</strong>.
              </p>
            </div>
            <div className="bg-amber-50/90 border border-amber-200/90 rounded-xl p-3 text-amber-950 space-y-1">
              <div className="flex items-center gap-1.5">
                <HelpCircle className="w-4 h-4 text-amber-600" />
                <span className="font-mono text-[10px] font-bold text-amber-900 uppercase tracking-wide">WARNING: Prior Share Exposure</span>
              </div>
              <p className="text-[11px] text-amber-800 leading-relaxed">
                2008 ledger indicates vendor conveyed an undivided 1/2 share before the 2009 transfer.
              </p>
            </div>
            <div className="bg-emerald-50/90 border border-emerald-200/90 rounded-xl p-3 text-emerald-950 space-y-1">
              <div className="flex items-center gap-1.5">
                <CheckCircle className="w-4 h-4 text-emerald-600" />
                <span className="font-mono text-[10px] font-bold text-emerald-900 uppercase tracking-wide">VERIFIED: Document Schedule & Plot Area</span>
              </div>
              <p className="text-[11px] text-emerald-800 leading-relaxed">
                Super built-up area matches Encumbrance Certificate exactly at 1200 Sq. Fts.
              </p>
            </div>
          </div>
        </div>

      </div>

    </div>
  );
};
