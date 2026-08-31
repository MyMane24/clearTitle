import React, { useState } from 'react';
import { Link } from 'react-router-dom';
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
        <div className="text-center mb-14">
          <h2 className="text-3xl sm:text-5xl font-bold text-stone-900 tracking-tight">
            Everything you need to know
          </h2>
          <p className="mt-3 text-stone-600 text-base sm:text-lg">
            Got questions about clearTitle? We've got answers.
          </p>
        </div>

        {/* Open Q&A list — hairline separated, no cards */}
        <div className="divide-y divide-stone-200/60">
          {FAQ_ITEMS.map((item, idx) => {
            const isOpen = openIdx === idx;
            const num = String(idx + 1).padStart(2, '0');

            return (
              <div key={idx}>
                <button
                  onClick={() => toggle(idx)}
                  aria-expanded={isOpen}
                  className="w-full py-7 flex items-center gap-4 sm:gap-6 text-left cursor-pointer group"
                >
                  <span className="w-8 shrink-0 font-mono text-xs font-bold text-[#ea580c]/70">
                    {num}
                  </span>
                  <span
                    className={`flex-1 text-lg sm:text-xl font-medium transition-colors ${
                      isOpen ? 'text-[#ea580c]' : 'text-stone-900 group-hover:text-[#ea580c]'
                    }`}
                  >
                    {item.question}
                  </span>
                  <span
                    className={`w-6 h-6 shrink-0 flex items-center justify-center text-stone-400 transition-transform duration-300 ${
                      isOpen ? 'rotate-180 text-[#ea580c]' : 'group-hover:text-stone-600'
                    }`}
                  >
                    <ChevronDown className="w-5 h-5" />
                  </span>
                </button>

                <div
                  className={`grid transition-all duration-300 ${
                    isOpen ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0'
                  }`}
                >
                  <div className="overflow-hidden">
                    <div className="pl-12 sm:pl-14 pb-8">
                      <p className="text-stone-600 text-base leading-relaxed">{item.answer}</p>
                      {item.link && (
                        <Link
                          to={item.link.to}
                          className="inline-flex items-center gap-1.5 mt-3 text-[#ea580c] font-semibold hover:underline"
                        >
                          {item.link.label} <span aria-hidden>→</span>
                        </Link>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>

      </div>
    </section>
  );
};