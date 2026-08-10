import React from 'react';
import { COMPETITORS } from '../data/landingData';
import { ShieldCheck, CheckCircle, Zap, Scale, Sparkles } from 'lucide-react';

export const CompetitiveLandscape: React.FC = () => {
  return (
    <section id="competitors" className="py-20 lg:py-28 bg-white border-b border-stone-200">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        
        {/* Header */}
        <div className="text-center max-w-3xl mx-auto mb-16">
          <span className="text-xs font-medium uppercase tracking-widest text-[#ea580c] bg-orange-100 border border-orange-200 px-3.5 py-1 rounded-full inline-block mb-3">
            COMPETITIVE LANDSCAPE & MATRIX
          </span>
          <h2 className="text-3xl sm:text-5xl font-bold text-stone-900 tracking-tight">
            Positioned for Title Depth + Speed
          </h2>
          <p className="mt-3 text-stone-600 text-base sm:text-lg">
            Where others only retrieve basic records, clearTitle delivers full title chain verification, Vernacular AI, and a blockchain trust layer.
          </p>
        </div>

        {/* 2x2 Matrix Box */}
        <div className="bg-[#faf8f5] rounded-3xl border border-stone-200 p-6 sm:p-10 shadow-xl max-w-5xl mx-auto relative overflow-hidden">
          
          <div className="text-center mb-6">
            <span className="text-xs font-medium text-stone-400 uppercase tracking-widest block mb-1">
              FULL TITLE VERIFICATION
            </span>
            <div className="w-px h-6 bg-stone-300 mx-auto" />
          </div>

          <div className="relative min-h-[380px] sm:min-h-[440px] border-2 border-stone-200 rounded-2xl bg-white p-4 sm:p-8 flex items-center justify-center">
            
            {/* Axis Lines */}
            <div className="absolute inset-x-0 top-1/2 h-0.5 bg-stone-200" />
            <div className="absolute inset-y-0 left-1/2 w-0.5 bg-stone-200" />

            {/* Quadrant Labels */}
            <span className="absolute top-3 left-3 text-[10px] font-medium text-stone-400 uppercase tracking-wider">
              INDIRECT COMPETITORS (SLOW + FULL)
            </span>
            <span className="absolute top-3 right-3 text-[10px] font-medium text-[#ea580c] uppercase tracking-wider">
              DIRECT COMPETITORS (FAST + FULL)
            </span>
            <span className="absolute bottom-3 left-3 text-[10px] font-medium text-stone-400 uppercase tracking-wider">
              SLOW + BASIC
            </span>
            <span className="absolute bottom-3 right-3 text-[10px] font-medium text-stone-400 uppercase tracking-wider">
              RECORD RETRIEVERS (FAST + BASIC)
            </span>

            {/* Placed Competitor Badges */}
            {COMPETITORS.map((comp) => (
              <div
                key={comp.name}
                style={{ left: `${comp.x}%`, top: `${100 - comp.y}%` }}
                className={`absolute -translate-x-1/2 -translate-y-1/2 transition-all group cursor-pointer ${
                  comp.isClearTitle ? 'z-30' : 'z-10'
                }`}
              >
                {comp.isClearTitle ? (
                  <div className="bg-gradient-to-r from-[#ea580c] to-[#f97316] text-white px-4 py-2.5 rounded-xl shadow-xl border-2 border-white ring-4 ring-orange-500/20 flex items-center gap-2 animate-bounce">
                    <ShieldCheck className="w-5 h-5 text-white" />
                    <div>
                      <span className="text-sm font-bold tracking-tight block">clearTitle</span>
                      <span className="text-[10px] text-orange-100 font-medium block">AI + Blockchain Trust</span>
                    </div>
                  </div>
                ) : (
                  <div className="bg-stone-100 hover:bg-stone-200 text-stone-700 px-3 py-1.5 rounded-lg border border-stone-200 text-xs font-semibold shadow-xs flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full bg-stone-400" />
                    <span>{comp.name}</span>
                  </div>
                )}
              </div>
            ))}

          </div>

          <div className="flex items-center justify-between mt-6 px-2">
            <span className="text-xs font-medium text-stone-400 uppercase tracking-widest">
              ← SLOW VERIFICATION
            </span>
            <span className="text-xs font-medium text-stone-400 uppercase tracking-widest">
              FAST VERIFICATION →
            </span>
          </div>

          <div className="text-center mt-6">
            <span className="text-xs font-medium text-stone-400 uppercase tracking-widest block mb-1">
              BASIC VERIFICATION
            </span>
          </div>

          {/* Winning Highlights Box */}
          <div className="mt-8 bg-white border border-stone-200 rounded-2xl p-5 shadow-xs flex flex-col sm:flex-row items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-full bg-orange-100 text-[#ea580c] flex items-center justify-center flex-shrink-0">
                <Sparkles className="w-5 h-5" />
              </div>
              <p className="text-xs sm:text-sm text-stone-800">
                <strong className="font-medium text-[#ea580c]">clearTitle Advantage:</strong> Wins on blockchain trust verification, Vernacular Indian AI (Kannada & Hindi support), and dedicated focus on Tier 2 & Tier 3 real estate markets.
              </p>
            </div>
          </div>

        </div>

      </div>
    </section>
  );
};
