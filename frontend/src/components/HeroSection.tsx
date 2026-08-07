import React from 'react';
import { ArrowRight, Play, Lock, FileCheck, Cpu } from 'lucide-react';
import DuneFieldBackground from './DuneFieldBackground';

interface HeroSectionProps {
  onStartAudit: () => void;
  onSeeDemo: () => void;
}

export const HeroSection: React.FC<HeroSectionProps> = ({ onStartAudit, onSeeDemo }) => {
  return (
    <section id="hero" className="relative min-h-screen flex flex-col pt-12 pb-20 lg:pt-16 lg:pb-25 overflow-hidden bg-[#FFF8F2]">
      {/* Floating dot-grid dunes */}
      <DuneFieldBackground />
      <div
        className="absolute inset-0 pointer-events-none"
        style={{ background: 'radial-gradient(ellipse 88% 78% at 50% -10%, rgba(249,115,22,0.10), transparent 60%)' }}
      />
      <div className="absolute -top-24 right-[-8%] w-[420px] h-[420px] rounded-full bg-gradient-to-tr from-orange-300/25 to-amber-200/15 blur-3xl pointer-events-none animate-float-slow" />
      <div className="absolute bottom-[-10%] left-[-6%] w-[360px] h-[360px] rounded-full bg-gradient-to-tr from-amber-200/20 to-orange-300/15 blur-3xl pointer-events-none animate-float-slow" />
      <div className="absolute bottom-0 left-0 right-0 h-24 bg-gradient-to-b from-transparent to-[#FFF8F2] pointer-events-none" />

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 relative z-10 flex-1 flex flex-col w-full">

        {/* Centered Headline + CTAs */}
        <div className="flex-1 flex flex-col justify-center">

          {/* Headline */}
          <div className="text-center mx-auto mb-8">
          <h1 className="text-4xl sm:text-5xl lg:text-7xl font-extrabold text-stone-900 tracking-tight leading-[1.1] font-display">
            Verify property documents
            <br />
            without the{' '}
            <span className="font-serif-display text-[1.14em] font-normal italic text-gradient-brand relative inline-block drop-shadow-[0_4px_14px_rgba(249,115,22,0.25)]">
              chaos
            </span>
          </h1>
          <p className="mt-6 text-sm sm:text-base text-stone-700 max-w-xl mx-auto font-bold leading-relaxed">
            <strong className="text-stone-900 font-semibold">clearTitle</strong> — deeds, ECs, e-Khatas &amp; audits, one tamper-proof place.
          </p>
        </div>

        {/* Action Buttons */}
        <div className="flex flex-col sm:flex-row items-center justify-center gap-4 mb-10">
          <button
            onClick={onStartAudit}
            className="group relative w-full sm:w-auto px-8 py-4 rounded-full bg-stone-900 text-white font-semibold text-base transition-all duration-300 flex items-center justify-center gap-3 cursor-pointer active:scale-95 overflow-hidden"
          >
            <span className="absolute inset-0 -translate-x-[130%] skew-x-[-20deg] bg-gradient-to-r from-transparent via-white/30 to-transparent transition-transform duration-700 ease-out group-hover:translate-x-[130%] pointer-events-none" />
            <span className="relative">Run Free Title Scan</span>
            <ArrowRight className="w-5 h-5 group-hover:translate-x-1.5 group-hover:scale-110 transition-transform duration-300 relative" />
          </button>

          <button
            onClick={onSeeDemo}
            className="group relative w-full sm:w-auto px-7 py-4 rounded-full bg-white/10 backdrop-blur-xl border border-white/40 text-stone-800 font-semibold text-base transition-all duration-300 flex items-center justify-center gap-2.5 cursor-pointer overflow-hidden active:scale-95"
          >
            <span className="absolute inset-0 -translate-x-[130%] skew-x-[-20deg] bg-gradient-to-r from-transparent via-white/40 to-transparent transition-transform duration-700 ease-out group-hover:translate-x-[130%] pointer-events-none" />
            <div className="w-7 h-7 rounded-full bg-orange-100 flex items-center justify-center text-orange-600 group-hover:bg-orange-500 group-hover:text-white group-hover:scale-110 group-hover:shadow-[0_0_18px_rgba(249,115,22,0.7)] transition-all duration-300">
              <Play className="w-3.5 h-3.5 fill-current ml-0.5 group-hover:rotate-6 transition-transform duration-300" />
            </div>
            <span>See how it works</span>
          </button>
        </div>

        </div>

        {/* Feature Badges Line — pinned at bottom */}
        <div className="flex flex-wrap items-center justify-center gap-6 sm:gap-8 text-xs sm:text-sm font-bold text-stone-700">
          <div className="flex items-center gap-1.5">
            <Lock className="w-4 h-4 text-orange-500" />
            <span>Encrypted &amp; On-chain</span>
          </div>
          <div className="flex items-center gap-1.5">
            <Cpu className="w-4 h-4 text-orange-500" />
            <span>Vernacular VLM AI (Kannada / Hindi)</span>
          </div>
          <div className="flex items-center gap-1.5">
            <FileCheck className="w-4 h-4 text-orange-500" />
            <span>ULPIN (14-Digit Bhu-Aadhar)</span>
          </div>
        </div>

      </div>
    </section>
  );
};
