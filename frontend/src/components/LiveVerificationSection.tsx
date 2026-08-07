import React from 'react';
import { AuditReportCard } from './AuditReportCard';

interface LiveVerificationSectionProps {
  onStartAudit: () => void;
}

export const LiveVerificationSection: React.FC<LiveVerificationSectionProps> = ({ onStartAudit }) => {
  return (
    <section id="live-verification" className="py-24 lg:py-32 bg-[#FFF8F2]">
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="text-center max-w-3xl mx-auto mb-10">
          <span className="text-xs font-medium uppercase tracking-widest text-[#f97316] bg-orange-100 border border-orange-200 px-3 py-1 rounded-full inline-block mb-3">
            LIVE TITLE VERIFICATION
          </span>
          <h3 className="text-2xl sm:text-4xl font-bold text-stone-900 tracking-tight">
            See the verification engine in action.
          </h3>
          <p className="mt-4 text-sm sm:text-base text-stone-600 leading-relaxed">
            A real audit of a Belagavi property — every deed, EC, and e-Khata cross-checked
            against government registries in seconds, with blockchain proof anchored on Polygon.
          </p>
        </div>

        <div className="relative rounded-2xl bg-white/70 p-2 sm:p-3 ring-1 ring-stone-200/70 shadow-xl shadow-orange-500/5 backdrop-blur-sm">
          <AuditReportCard onStartAudit={onStartAudit} />
        </div>
      </div>
    </section>
  );
};
