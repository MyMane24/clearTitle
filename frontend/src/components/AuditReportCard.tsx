import React from 'react';
import { Shield, AlertTriangle, ExternalLink } from 'lucide-react';

interface AuditReportCardProps {
  onStartAudit: () => void;
}

export const AuditReportCard: React.FC<AuditReportCardProps> = ({ onStartAudit }) => {
  return (
    <div className="rounded-xl overflow-hidden bg-white border border-stone-200/80 shadow-sm">
      {/* Top Frame Window Bar */}
      <div className="bg-stone-50 px-4 py-3 border-b border-stone-200/80 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="flex gap-1.5">
            <div className="w-3 h-3 rounded-full bg-rose-400/80" />
            <div className="w-3 h-3 rounded-full bg-amber-400/80" />
            <div className="w-3 h-3 rounded-full bg-emerald-400/80" />
          </div>
          <div className="ml-4 px-3 py-1 bg-white border border-stone-200 rounded-md text-xs font-mono text-stone-500 flex items-center gap-1.5">
            <Shield className="w-3 h-3 text-[#ea580c]" />
            <span>app.cleartitle.in/audit/CTS-422-A1</span>
          </div>
        </div>
        <div className="flex items-center gap-3 text-xs font-medium text-stone-500">
          <span className="hidden sm:inline bg-emerald-100 text-emerald-800 px-2 py-0.5 rounded font-semibold text-[11px]">
            ● Live Verification Engine
          </span>
          <span className="text-stone-400">Belagavi, KA</span>
        </div>
      </div>

      {/* Simulated Audit Report Content */}
      <div className="p-4 sm:p-6 bg-[#fcfbf9]">

        {/* Header Status Bar */}
        <div className="bg-white p-4 sm:p-5 rounded-xl border border-stone-200 shadow-xs mb-4 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 text-xs font-medium text-stone-400 uppercase tracking-wider">
              <span>VERIFICATION REPORT #CT-2026-881</span>
              <span>•</span>
              <span className="text-[#ea580c]">KA-BEL-422</span>
            </div>
            <h3 className="text-lg sm:text-xl font-medium text-stone-900 mt-0.5">
              CTS No. 422/A-1, Tilakwadi, Belagavi
            </h3>
            <p className="text-xs text-stone-500">
              Documents Audited: Sale Deed (2021), Encumbrance Certificate (2010-2025), e-Khata Extract
            </p>
          </div>

          <div className="flex items-center gap-3">
            <div className="text-right">
              <span className="text-xs font-semibold text-stone-500 block">Trust Score</span>
              <span className="text-2xl font-bold text-emerald-600">84<span className="text-sm font-normal text-stone-400">/100</span></span>
            </div>
            <div className="px-3 py-1.5 bg-amber-50 border border-amber-200 rounded-lg text-amber-800 text-xs font-medium flex items-center gap-1">
              <AlertTriangle className="w-3.5 h-3.5 text-amber-600" />
              <span>Review Required (2 Flags)</span>
            </div>
          </div>
        </div>

        {/* Grid Metrics & Warnings */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">

          {/* Metric 1 */}
          <div className="bg-white p-4 rounded-xl border border-stone-200 shadow-xs">
            <div className="flex justify-between text-xs text-stone-500 mb-1">
              <span>Doc Validity</span>
              <span className="text-emerald-600 font-medium">100% Match</span>
            </div>
            <div className="text-sm font-medium text-stone-900">Valid Property Record</div>
            <div className="text-[11px] text-stone-500 mt-1">Cross-matched with Kaveri Online Registry</div>
          </div>

          {/* Metric 2 */}
          <div className="bg-white p-4 rounded-xl border border-stone-200 shadow-xs">
            <div className="flex justify-between text-xs text-stone-500 mb-1">
              <span>Survey & ULPIN</span>
              <span className="text-emerald-600 font-medium">79PYQ GYZ30</span>
            </div>
            <div className="text-sm font-medium text-stone-900">14-Digit Bhu-Aadhar Tagged</div>
            <div className="text-[11px] text-stone-500 mt-1">Boundary matches sanctioned layout</div>
          </div>

          {/* Metric 3 */}
          <div className="bg-white p-4 rounded-xl border border-stone-200 shadow-xs">
            <div className="flex justify-between text-xs text-stone-500 mb-1">
              <span>Blockchain Proof</span>
              <span className="text-stone-400 font-mono text-[10px]">Polygon #49201948</span>
            </div>
            <div className="text-sm font-medium text-stone-900 truncate font-mono text-xs">
              0x8f9c2a3e...18fa3021
            </div>
            <div className="text-[11px] text-[#ea580c] font-medium mt-1 flex items-center gap-1">
              <span>Tamper-Proof Ledger</span>
              <ExternalLink className="w-3 h-3" />
            </div>
          </div>

        </div>

        {/* Sample Red Flag Banner */}
        <div className="bg-rose-50 border border-rose-200 rounded-xl p-3 sm:p-4 text-xs sm:text-sm text-rose-900 flex items-start gap-3">
          <AlertTriangle className="w-5 h-5 text-rose-600 flex-shrink-0 mt-0.5" />
          <div className="flex-1">
            <span className="font-medium text-rose-900 block sm:inline">CRITICAL AUDIT ALERT: Vendor Name Variation Detected</span>
            <span className="text-rose-700 ml-0 sm:ml-2">
              Sale Deed lists 'Shri. Prakash M.' while EC entry #104 lists 'Shri. Prakash Mallappa'. Automated identity cross-verification advised.
            </span>
          </div>
          <button
            onClick={onStartAudit}
            className="hidden md:block bg-rose-600 text-white text-xs font-medium px-3 py-1.5 rounded-lg hover:bg-rose-700 transition-colors whitespace-nowrap cursor-pointer"
          >
            Audit Details
          </button>
        </div>

      </div>
    </div>
  );
};
