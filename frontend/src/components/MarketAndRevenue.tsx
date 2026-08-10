import React, { useState } from 'react';
import { MARKET_SEGMENTS, PRICING_PLANS, GOVT_INITIATIVES } from '../data/landingData';
import { Check, LandPlot } from 'lucide-react';

interface MarketAndRevenueProps {
  onStartAudit: () => void;
}

export const MarketAndRevenue: React.FC<MarketAndRevenueProps> = ({ onStartAudit }) => {
  const [propertyCount, setPropertyCount] = useState<number>(10);

  // Estimator calculation: Saved ~₹4,500 per property + 40 days time saved per property
  const estimatedSavingsInr = propertyCount * 4500;
  const estimatedDaysSaved = propertyCount * 40;

  return (
    <section id="pricing" className="py-20 lg:py-28 bg-[#faf8f5] border-b border-stone-200">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        
        {/* Header */}
        <div className="text-center max-w-3xl mx-auto mb-16">
          <span className="text-xs font-medium uppercase tracking-widest text-[#ea580c] bg-orange-100 border border-orange-200 px-3.5 py-1 rounded-full inline-block mb-3">
            SIMPLE, HONEST PRICING & MARKET OPPORTUNITY
          </span>
          <h2 className="text-3xl sm:text-5xl font-bold text-stone-900 tracking-tight">
            Transparent Pricing per Property Basis
          </h2>
          <p className="mt-3 text-stone-600 text-base sm:text-lg">
            Pay per property report — no hidden subscriptions. Scale from single home purchases to multi-parcel enterprise acquisitions.
          </p>
        </div>

        {/* Pricing Cards Grid - Matching slide 11 */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-20">
          {PRICING_PLANS.map((plan) => (
            <div
              key={plan.id}
              className={`rounded-2xl p-6 transition-all flex flex-col justify-between relative ${
                plan.isPopular
                  ? 'bg-white border-2 border-[#ea580c] shadow-xl ring-4 ring-orange-500/10'
                  : 'bg-white border border-stone-200 shadow-md hover:border-stone-300'
              }`}
            >
              {plan.badge && (
                <div className="absolute -top-3.5 left-1/2 -translate-x-1/2 bg-[#ea580c] text-white text-[10px] font-semibold uppercase tracking-wider px-3 py-1 rounded-full shadow-sm">
                  {plan.badge}
                </div>
              )}

              <div>
                <div className="text-xs font-medium uppercase tracking-wider text-stone-400 mb-1">
                  {plan.name}
                </div>
                <div className="text-2xl sm:text-3xl font-bold text-stone-900 font-sans my-2">
                  {plan.price}
                </div>
                <div className="text-[11px] font-semibold text-[#ea580c] bg-orange-50 px-2 py-0.5 rounded inline-block mb-3">
                  {plan.unit}
                </div>
                <p className="text-xs text-stone-600 leading-relaxed mb-6">
                  {plan.description}
                </p>

                <div className="border-t border-stone-100 pt-4 mb-6 space-y-2.5">
                  {plan.features.map((feat, i) => (
                    <div key={i} className="flex items-start gap-2 text-xs text-stone-700">
                      <Check className="w-4 h-4 text-[#ea580c] flex-shrink-0 mt-0.5" />
                      <span>{feat}</span>
                    </div>
                  ))}
                </div>
              </div>

              <button
                onClick={onStartAudit}
                className={`w-full py-3 rounded-xl font-medium text-xs sm:text-sm transition-all cursor-pointer ${
                  plan.isPopular
                    ? 'bg-[#ea580c] hover:bg-[#c2410c] text-white shadow-md shadow-orange-500/20'
                    : 'bg-stone-100 hover:bg-stone-200 text-stone-900'
                }`}
              >
                {plan.cta}
              </button>
            </div>
          ))}
        </div>

        {/* Savings Interactive Calculator */}
        <div className="bg-white rounded-3xl border border-stone-200 p-6 sm:p-8 shadow-lg mb-20">
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-center">
            <div className="lg:col-span-6">
              <span className="text-xs font-medium text-[#ea580c] uppercase tracking-wider block mb-1">
                VALUE & TIME SAVED CALCULATOR
              </span>
              <h3 className="text-2xl font-bold text-stone-900 mb-2">
                Estimate Your Due Diligence Savings
              </h3>
              <p className="text-xs sm:text-sm text-stone-600 mb-6">
                Drag the slider to select how many property title checks you perform per month:
              </p>

              <div className="space-y-4">
                <div className="flex justify-between items-center text-sm font-medium text-stone-900">
                  <span>Monthly Property Verifications</span>
                  <span className="text-[#ea580c] font-mono text-lg">{propertyCount} properties</span>
                </div>
                <input
                  type="range"
                  min="1"
                  max="100"
                  value={propertyCount}
                  onChange={(e) => setPropertyCount(parseInt(e.target.value))}
                  className="w-full accent-[#ea580c] h-2 bg-stone-100 rounded-lg cursor-pointer"
                />
              </div>
            </div>

            <div className="lg:col-span-6 bg-[#faf8f5] rounded-2xl p-6 border border-stone-200">
              <div className="grid grid-cols-2 gap-4 text-center">
                <div className="bg-white p-4 rounded-xl border border-stone-200 shadow-xs">
                  <span className="text-[10px] font-medium text-stone-400 uppercase block">Estimated Cost Savings</span>
                  <span className="text-xl sm:text-2xl font-bold text-emerald-600 font-mono">
                    ₹{estimatedSavingsInr.toLocaleString('en-IN')}
                  </span>
                  <span className="text-[10px] text-stone-500 block mt-1">vs traditional legal due diligence</span>
                </div>

                <div className="bg-white p-4 rounded-xl border border-stone-200 shadow-xs">
                  <span className="text-[10px] font-medium text-stone-400 uppercase block">Closure Time Saved</span>
                  <span className="text-xl sm:text-2xl font-bold text-[#ea580c] font-mono">
                    {estimatedDaysSaved} Days
                  </span>
                  <span className="text-[10px] text-stone-500 block mt-1">accelerated deal turnaround</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Customer Segments & Market TAM/SAM/SOM (Slide 10) */}
        <div className="mb-20">
          <div className="text-center max-w-2xl mx-auto mb-10">
            <span className="text-xs font-medium uppercase tracking-widest text-[#ea580c]">
              CUSTOMER SEGMENTS & MARKET SIZE
            </span>
            <h3 className="text-2xl sm:text-4xl font-bold text-stone-900 tracking-tight mt-1">
              Addressing India's Land Vetting TAM
            </h3>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
            {MARKET_SEGMENTS.map((seg) => (
              <div key={seg.id} className="bg-white rounded-2xl border border-stone-200 p-6 shadow-xs hover:shadow-md transition-shadow">
                <div className="text-xs font-medium text-stone-300 font-mono mb-2">{seg.number}</div>
                <h4 className="text-lg font-medium text-stone-900">{seg.title}</h4>
                <div className="text-xs font-semibold text-[#ea580c] mb-2">{seg.subtitle}</div>
                <p className="text-xs text-stone-500 leading-relaxed">{seg.audience}</p>
              </div>
            ))}
          </div>
        </div>

        {/* Government Infrastructure Tailwinds */}
        <div className="bg-gradient-to-br from-stone-900 to-stone-950 text-white rounded-3xl p-6 sm:p-10 shadow-2xl">
          <div className="text-center max-w-2xl mx-auto mb-10">
            <span className="text-xs font-medium uppercase tracking-widest text-[#f97316] bg-orange-950/80 px-3 py-1 rounded-full inline-block mb-3">
              GOVERNMENT INFRASTRUCTURE TAILWINDS
            </span>
            <h3 className="text-2xl sm:text-4xl font-bold text-white tracking-tight">
              Leveraging India's Land Digitization
            </h3>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {GOVT_INITIATIVES.map((govt, i) => (
              <div key={i} className="bg-stone-800/80 border border-stone-700/80 rounded-2xl p-6">
                <div className="w-10 h-10 rounded-xl bg-orange-500/20 border border-orange-500/40 text-[#f97316] flex items-center justify-center mb-4">
                  <LandPlot className="w-5 h-5" />
                </div>
                <h4 className="text-lg font-medium text-white mb-1">{govt.title}</h4>
                <div className="text-xs font-medium text-[#f97316] mb-3">{govt.subtitle}</div>
                <p className="text-xs text-stone-300 leading-relaxed">{govt.desc}</p>
              </div>
            ))}
          </div>
        </div>

      </div>
    </section>
  );
};
