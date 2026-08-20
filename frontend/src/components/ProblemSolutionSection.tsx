import React from 'react';
import { ArrowRight } from 'lucide-react';

interface ProblemSolutionProps {
  onStartAudit: () => void;
}

export const ProblemSolutionSection: React.FC<ProblemSolutionProps> = ({ onStartAudit }) => {
  return (
    <section id="problem" className="py-16 lg:py-24 bg-stone-900 text-white relative overflow-hidden">
      <div className="absolute inset-0 bg-gradient-to-b from-stone-900 via-stone-900 to-[#ea580c]/20 opacity-80 pointer-events-none" />

      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 relative z-10 text-center">
        <span className="text-xs font-medium uppercase tracking-widest text-[#f97316] bg-orange-950/60 border border-orange-800/60 px-3 py-1 rounded-full inline-block mb-3">
          THE PROPERTY DUE DILIGENCE GAP
        </span>
        <h2 className="text-3xl sm:text-5xl font-bold text-white tracking-tight mb-4">
          Property due diligence in India is slow, manual, fragmented.
        </h2>
        <p className="text-stone-300 text-sm sm:text-base max-w-2xl mx-auto mb-8 leading-relaxed">
          clearTitle brings everything together — AI-powered verification, blockchain trust layer, and cross-document fraud detection in one place.
        </p>
        <button
          onClick={() => window.location.href = '/how-it-works'}
          className="px-8 py-3.5 bg-[#ea580c] hover:bg-[#dc4a0a] text-white font-bold rounded-xl shadow-lg shadow-orange-500/25 transition-all active:scale-95 cursor-pointer text-sm inline-flex items-center gap-2"
        >
          <span>Learn How It Works</span>
          <ArrowRight className="w-4 h-4" />
        </button>
      </div>
    </section>
  );
};
