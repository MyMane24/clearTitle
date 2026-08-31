import React from 'react';
import { Verified, Landmark, Gavel, Building } from 'lucide-react';

const segments = [
  {
    number: '01',
    title: 'Retail',
    subtitle: 'Buyers, Sellers, NRIs',
    description: 'Retail property buyers requiring fast title verification before token advance.',
    footer: 'Token Advance Vetting',
    icon: <Verified className="w-4 h-4 text-orange-500" />,
  },
  {
    number: '02',
    title: 'Institutional',
    subtitle: 'Banks, NBFCs, Housing Finance',
    description: 'Loan processing desks needing automated title search reports & mortgage checks.',
    footer: 'Collateral Due Diligence',
    icon: <Landmark className="w-4 h-4 text-orange-500" />,
  },
  {
    number: '03',
    title: 'Professional',
    subtitle: 'Brokers, Consultants, Law Firms',
    description: 'Legal consultants accelerating due diligence throughput 10x per attorney.',
    footer: '10x Title Throughput',
    icon: <Gavel className="w-4 h-4 text-orange-500" />,
  },
  {
    number: '04',
    title: 'Enterprise',
    subtitle: 'Developers & Real-Estate Teams',
    description: 'Land acquisition teams evaluating multi-acre land parcels in Tier 2/3 markets.',
    footer: 'Multi-Acre Assembly',
    icon: <Building className="w-4 h-4 text-orange-500" />,
  },
];

export const WhoWeEmpower: React.FC = () => {
  return (
    <section className="relative py-24 px-6 bg-[#FAF9F6] text-slate-900 border-y border-[#e9e1dd] overflow-hidden selection:bg-orange-100 selection:text-orange-950">
      {/* Subtle Ambient Glow */}
      <div className="absolute inset-0 bg-dot-pattern opacity-60 pointer-events-none"></div>
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[700px] h-[350px] bg-orange-400/10 rounded-full blur-[140px] pointer-events-none"></div>

      <div className="max-w-7xl mx-auto relative z-10 space-y-12">
        {/* Section Header */}
        <div className="text-center max-w-3xl mx-auto space-y-3">
          <h2 className="text-3xl sm:text-4xl md:text-5xl font-extrabold tracking-tight text-slate-950 leading-[1.15]">
            Built for every stakeholder across Indian real estate.
          </h2>
        </div>

        {/* 4-Column Card Grid */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
          {segments.map((seg) => (
            <div
              key={seg.number}
              className="rounded-3xl p-6 sm:p-7 flex flex-col justify-between space-y-6 bg-gradient-to-b from-white to-[#FAF6F2] border border-[#e9e1dd] shadow-[0_4px_20px_-2px_rgba(28,25,23,0.03),inset_0_1px_0_rgba(255,255,255,0.9)] transition-all duration-300 hover:-translate-y-1 hover:border-orange-300 hover:shadow-[0_16px_32px_-8px_rgba(234,88,12,0.12),inset_0_1px_0_rgba(255,255,255,1)]"
            >
              <div className="space-y-4">
                <span className="font-mono text-xs font-bold text-slate-400 block">{seg.number}</span>

                <div className="space-y-1">
                  <h3 className="text-xl font-bold text-slate-950 tracking-tight">{seg.title}</h3>
                  <p className="text-xs font-mono font-bold text-[#ea580c]">{seg.subtitle}</p>
                </div>

                <p className="text-xs text-slate-600 font-sans leading-relaxed">
                  {seg.description}
                </p>
              </div>

              <div className="pt-2 border-t border-slate-100 flex items-center justify-between text-[11px] font-mono text-slate-400">
                <span>{seg.footer}</span>
                {seg.icon}
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
};
