import React from 'react';
import { PROBLEM_METRICS, OLD_WAY_VS_CLEARTITLE } from '../data/landingData';
import { XCircle, CheckCircle2, AlertCircle, Sparkles } from 'lucide-react';

interface ProblemSolutionProps {
  onStartAudit: () => void;
}

export const ProblemSolutionSection: React.FC<ProblemSolutionProps> = ({ onStartAudit }) => {
  return (
    <section id="problem" className="py-16 lg:py-24 bg-stone-900 text-white relative overflow-hidden">
      {/* Background Gradient Mesh */}
      <div className="absolute inset-0 bg-gradient-to-b from-stone-900 via-stone-900 to-[#ea580c]/20 opacity-80 pointer-events-none" />

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 relative z-10">
        
        {/* Section Header */}
        <div className="text-center max-w-3xl mx-auto mb-12 lg:mb-16">
          <span className="text-xs font-medium uppercase tracking-widest text-[#f97316] bg-orange-950/60 border border-orange-800/60 px-3 py-1 rounded-full inline-block mb-3">
            THE PROPERTY DUE DILIGENCE GAP
          </span>
          <h2 className="text-3xl sm:text-5xl font-bold text-white tracking-tight">
            Property due diligence in India is slow, manual, fragmented.
          </h2>
          <p className="mt-4 text-stone-300 text-base sm:text-lg">
            And property frauds have become common. Existing digital tools only retrieve records — they don't cross-verify them for fraud, and no one offers a blockchain trust layer to guarantee authenticity.
          </p>
        </div>

        {/* Problem Key Metrics */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-16">
          {PROBLEM_METRICS.map((metric, idx) => (
            <div 
              key={idx} 
              className="bg-stone-800/80 border border-stone-700/80 rounded-2xl p-6 sm:p-8 hover:border-orange-500/50 transition-colors shadow-lg"
            >
              <div className="text-4xl sm:text-5xl font-bold text-[#f97316] font-mono tracking-tight mb-2">
                {metric.value}
              </div>
              <h3 className="text-lg font-medium text-white mb-1">{metric.label}</h3>
              <p className="text-xs sm:text-sm text-stone-400 leading-relaxed">{metric.description}</p>
            </div>
          ))}
        </div>

        {/* Feature Comparison Box - Matching reference card in pitch deck / screenshot */}
        <div className="rounded-3xl bg-gradient-to-br from-[#ea580c] to-[#c2410c] p-6 sm:p-10 lg:p-12 shadow-2xl relative overflow-hidden">
          
          <div className="max-w-3xl mb-10">
            <span className="text-xs font-medium uppercase tracking-wider text-orange-200 bg-white/10 px-3 py-1 rounded-full inline-block mb-3">
              ONE PLATFORM INSTEAD OF 6 DISCONNECTED TOOLS
            </span>
            <h3 className="text-2xl sm:text-4xl font-bold text-white leading-tight">
              Land vetting is hard enough. <br className="hidden sm:inline" />
              Your tools shouldn't make it <em className="serif italic font-normal text-amber-200">harder</em>.
            </h3>
            <p className="text-orange-100 text-sm sm:text-base mt-3">
              Most property buyers, lawyers, and banks verify across 6+ disconnected state portals and manual spreadsheets. Here is what changes the day you switch to clearTitle.
            </p>
          </div>

          {/* Side by side boxes */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            
            {/* The Old Way */}
            <div className="bg-stone-900/90 backdrop-blur-md rounded-2xl p-6 border border-white/10 text-stone-300">
              <div className="flex items-center gap-2 mb-4 pb-3 border-b border-stone-800">
                <AlertCircle className="w-5 h-5 text-rose-400" />
                <span className="text-xs font-medium uppercase tracking-wider text-rose-300">THE OLD WAY</span>
              </div>
              <ul className="space-y-3.5 text-xs sm:text-sm">
                {OLD_WAY_VS_CLEARTITLE.oldWay.map((item, index) => (
                  <li key={index} className="flex items-start gap-2.5">
                    <XCircle className="w-4 h-4 text-rose-400 flex-shrink-0 mt-0.5" />
                    <span className="text-stone-300 leading-normal">{item}</span>
                  </li>
                ))}
              </ul>
            </div>

            {/* The clearTitle Way */}
            <div className="bg-white rounded-2xl p-6 border border-orange-200 text-stone-900 shadow-xl">
              <div className="flex items-center gap-2 mb-4 pb-3 border-b border-stone-200">
                <Sparkles className="w-5 h-5 text-[#ea580c]" />
                <span className="text-xs font-medium uppercase tracking-wider text-[#ea580c]">THE CLEARTITLE WAY</span>
              </div>
              <ul className="space-y-3.5 text-xs sm:text-sm">
                {OLD_WAY_VS_CLEARTITLE.clearTitleWay.map((item, index) => (
                  <li key={index} className="flex items-start gap-2.5">
                    <CheckCircle2 className="w-4 h-4 text-emerald-600 flex-shrink-0 mt-0.5" />
                    <span className="text-stone-800 font-medium leading-normal">{item}</span>
                  </li>
                ))}
              </ul>
            </div>

          </div>

          <div className="mt-8 text-center">
            <button
              onClick={onStartAudit}
              className="px-8 py-3.5 bg-white text-[#ea580c] hover:bg-orange-50 font-medium rounded-xl shadow-lg transition-transform active:scale-95 cursor-pointer text-sm sm:text-base inline-flex items-center gap-2"
            >
              <span>Switch to clearTitle Verification</span>
              <CheckCircle2 className="w-4 h-4 text-[#ea580c]" />
            </button>
          </div>

        </div>

      </div>
    </section>
  );
};
