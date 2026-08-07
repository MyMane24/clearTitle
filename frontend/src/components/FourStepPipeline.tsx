import React from 'react';
import { PIPELINE_STEPS } from '../data/landingData';
import { FileText, Brain, ShieldCheck, Boxes, ArrowRight, Check } from 'lucide-react';

interface PipelineProps {
  onStartAudit: () => void;
}

export const FourStepPipeline: React.FC<PipelineProps> = ({ onStartAudit }) => {
  const getIcon = (iconName: string) => {
    switch (iconName) {
      case 'FileText': return <FileText className="w-6 h-6 text-current" />;
      case 'Brain': return <Brain className="w-6 h-6 text-current" />;
      case 'ShieldCheck': return <ShieldCheck className="w-6 h-6 text-current" />;
      case 'Boxes': return <Boxes className="w-6 h-6 text-current" />;
      default: return <ShieldCheck className="w-6 h-6 text-current" />;
    }
  };

  return (
    <section id="solution" className="py-20 lg:py-28 bg-[#faf8f5] border-b border-stone-200">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        
        {/* Section Header */}
        <div className="text-center max-w-3xl mx-auto mb-16">
          <span className="text-xs font-medium uppercase tracking-widest text-[#ea580c] bg-orange-100/70 border border-orange-200 px-3.5 py-1 rounded-full inline-block mb-3">
            OUR SOLUTION PIPELINE
          </span>
          <h2 className="text-3xl sm:text-5xl font-bold text-stone-900 tracking-tight leading-tight">
            AI verifies the property. <br className="hidden sm:inline" />
            <span className="text-[#ea580c]">Blockchain preserves the trust.</span>
          </h2>
          <p className="mt-4 text-stone-600 text-base sm:text-lg">
            From raw Indian-language land deeds to cryptographic proof of ownership on-chain, clearTitle automates property due diligence end-to-end.
          </p>
        </div>

        {/* 4 Steps Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 relative">
          {PIPELINE_STEPS.map((step, idx) => (
            <div 
              key={step.num}
              className="bg-white rounded-2xl p-6 sm:p-7 border border-stone-200/80 shadow-md hover:shadow-xl hover:border-orange-300 transition-all group flex flex-col justify-between relative"
            >
              <div>
                <div className="flex items-center justify-between mb-6">
                  <div className="w-12 h-12 rounded-xl bg-orange-50 border border-orange-200/60 flex items-center justify-center group-hover:scale-110 group-hover:bg-[#ea580c] group-hover:text-white transition-all text-[#ea580c]">
                    {getIcon(step.icon)}
                  </div>
                  <span className="text-2xl font-bold text-stone-300 font-mono">{step.num}</span>
                </div>

                <h3 className="text-lg font-medium text-stone-900 mb-2 group-hover:text-[#ea580c] transition-colors">
                  {step.title}
                </h3>

                <p className="text-xs sm:text-sm text-stone-600 leading-relaxed">
                  {step.desc}
                </p>
              </div>

              <div className="mt-6 pt-4 border-t border-stone-100 flex items-center justify-between text-xs font-semibold text-[#ea580c]">
                <span>Step {idx + 1} of 4</span>
                <ArrowRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
              </div>
            </div>
          ))}
        </div>

        {/* Summary Banner */}
        <div className="mt-12 bg-white rounded-2xl p-6 border border-stone-200 shadow-xs flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-emerald-100 text-emerald-700 flex items-center justify-center flex-shrink-0">
              <Check className="w-5 h-5" />
            </div>
            <div>
              <h4 className="text-sm font-medium text-stone-900">100% Automated Multi-Document Cross Verification</h4>
              <p className="text-xs text-stone-500">Detects area discrepancies, spelling variations, missing survey numbers, and undisclosed mortgages in under 3 minutes.</p>
            </div>
          </div>
          <button
            onClick={onStartAudit}
            className="px-5 py-2.5 bg-[#ea580c] hover:bg-[#c2410c] text-white text-xs font-medium rounded-xl shadow cursor-pointer whitespace-nowrap"
          >
            Run Sample Document Audit
          </button>
        </div>

      </div>
    </section>
  );
};
