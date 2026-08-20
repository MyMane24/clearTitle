import React, { useState } from 'react';
import { FAQ_ITEMS } from '../data/landingData';
import { ChevronDown } from 'lucide-react';

export const FaqSection: React.FC = () => {
  const [openIdx, setOpenIdx] = useState<number | null>(0);

  const toggle = (idx: number) => {
    setOpenIdx(openIdx === idx ? null : idx);
  };

  return (
    <section className="py-20 lg:py-28 bg-[#faf8f5] border-b border-stone-200">
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8">
        
        {/* Header */}
        <div className="text-center mb-16">
          <span className="text-xs font-medium uppercase tracking-widest text-[#ea580c] bg-orange-100 border border-orange-200 px-3.5 py-1 rounded-full inline-block mb-3">
            FREQUENTLY ASKED QUESTIONS
          </span>
          <h2 className="text-3xl sm:text-5xl font-bold text-stone-900 tracking-tight">
            Everything you need to know
          </h2>
          <p className="mt-3 text-stone-600 text-base sm:text-lg">
            Got questions about clearTitle? We've got answers.
          </p>
        </div>

        {/* Accordion List */}
        <div className="space-y-4">
          {FAQ_ITEMS.map((item, idx) => {
            const isOpen = openIdx === idx;
            return (
              <div 
                key={idx} 
                className="bg-white rounded-2xl border border-stone-200 overflow-hidden shadow-xs hover:border-orange-300 transition-colors"
              >
                <button
                  onClick={() => toggle(idx)}
                  className="w-full text-left p-5 sm:p-6 flex items-center justify-between gap-4 cursor-pointer focus:outline-none"
                >
                  <span className="text-base sm:text-lg font-medium text-stone-900">
                    {item.question}
                  </span>
                  <div className={`w-8 h-8 rounded-full bg-stone-100 flex items-center justify-center flex-shrink-0 transition-transform ${isOpen ? 'rotate-180 bg-orange-100 text-[#ea580c]' : 'text-stone-500'}`}>
                    <ChevronDown className="w-5 h-5" />
                  </div>
                </button>

                {isOpen && (
                  <div className="px-5 sm:px-6 pb-6 pt-0 text-stone-600 text-xs sm:text-sm leading-relaxed border-t border-stone-100 mt-1">
                    {item.answer}
                  </div>
                )}
              </div>
            );
          })}
        </div>

      </div>
    </section>
  );
};
