import React from 'react';
import { AuditReportCard } from './AuditReportCard';

interface LiveVerificationSectionProps {
  onStartAudit: () => void;
}

export const LiveVerificationSection: React.FC<LiveVerificationSectionProps> = ({ onStartAudit }) => {
  return (
    <section id="live-verification" className="relative py-14 sm:py-24 px-4 sm:px-6 bg-[#FAF9F6] text-slate-900 overflow-hidden">
      <div className="absolute inset-0 bg-dot-pattern opacity-60 pointer-events-none" />
      <div className="absolute top-1/4 -left-32 w-96 h-96 bg-orange-400/10 rounded-full blur-[110px] pointer-events-none" />
      <div className="absolute bottom-10 -right-32 w-96 h-96 bg-amber-300/10 rounded-full blur-[110px] pointer-events-none" />

      <div className="max-w-5xl mx-auto relative z-10 space-y-12">
        <div className="text-center max-w-3xl mx-auto space-y-3">
          <h2 className="text-2xl sm:text-3xl md:text-5xl font-extrabold tracking-tight text-slate-950 leading-tight">
            See the verification engine in action.
          </h2>

          <p className="text-slate-600 text-sm sm:text-base leading-relaxed max-w-2xl mx-auto">
            A real audit of a Belagavi property — every deed, EC, and e-Khata cross-checked against government registries in seconds.
          </p>
        </div>

        <AuditReportCard onStartAudit={onStartAudit} />
      </div>
    </section>
  );
};
