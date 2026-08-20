import React from 'react';
import { Sparkles } from 'lucide-react';
import clearTitleVideo from '../assets/clearTitle.mp4';

interface PipelineProps {
  onStartAudit?: () => void;
}

export const FourStepPipeline: React.FC<PipelineProps> = () => {
  return (
    <section id="solution" className="py-20 lg:py-28 bg-[#faf8f5] border-b border-stone-200 relative overflow-hidden">
      
      {/* Ambient background glows */}
      <div className="absolute top-1/4 left-1/3 w-[500px] h-[500px] bg-orange-200/20 rounded-full blur-3xl pointer-events-none"></div>
      <div className="absolute bottom-10 right-1/4 w-[450px] h-[450px] bg-emerald-200/20 rounded-full blur-3xl pointer-events-none"></div>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 relative z-10">
        
        {/* Section Header */}
        <div className="text-center max-w-3xl mx-auto mb-16">
          <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-orange-100/90 border border-orange-200 text-[#ea580c] text-xs font-semibold uppercase tracking-widest mb-4 shadow-xs">
            <Sparkles className="w-3.5 h-3.5 text-[#ea580c]" />
            <span>OUR SOLUTION PIPELINE • SYSTEM ARCHITECTURE</span>
          </div>
          <h2 className="text-3xl sm:text-5xl font-bold text-stone-900 tracking-tight leading-tight">
            AI verifies the property. <br className="hidden sm:inline" />
            <span className="text-[#ea580c]">Blockchain preserves the trust.</span>
          </h2>
          <p className="mt-4 text-stone-600 text-base sm:text-lg leading-relaxed">
            From raw Indian-language land deeds to cryptographic proof of ownership on-chain, clearTitle automates property due diligence end-to-end.
          </p>
        </div>

        {/* Video Container */}
        <div className="relative max-w-5xl mx-auto rounded-3xl overflow-hidden shadow-2xl shadow-stone-900/10 bg-transparent">
          <video
            src={clearTitleVideo}
            autoPlay
            loop
            muted
            playsInline
            className="w-full h-auto block object-cover rounded-3xl"
          />
        </div>

      </div>
    </section>
  );
};
