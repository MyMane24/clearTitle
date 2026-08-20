import React, { useState } from 'react';
import { CheckCircle, Clock } from 'lucide-react';

export const SavingsCalculator: React.FC = () => {
  const [sliderValue, setSliderValue] = useState(10);

  const savingsData: Record<number, { cost: string; days: string }> = {
    1: { cost: '₹7,500', days: '12 Days' },
    5: { cost: '₹37,500', days: '60 Days' },
    10: { cost: '₹75,000', days: '120 Days' },
    25: { cost: '₹1,87,500', days: '300 Days' },
    50: { cost: '₹3,75,000', days: '600 Days' },
    100: { cost: '₹7,50,000', days: '1200 Days' },
  };

  const closest = Object.keys(savingsData)
    .map(Number)
    .reduce((prev, curr) =>
      Math.abs(curr - sliderValue) < Math.abs(prev - sliderValue) ? curr : prev
    );
  const currentSavings = savingsData[closest];

  return (
    <section className="py-16 lg:py-24 bg-[#FAF9F6]">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="rounded-3xl p-6 sm:p-10 border border-[#e9e1dd] bg-white/90 shadow-lg shadow-orange-500/5">
          <div className="text-center mb-10">
            <h3 className="text-2xl sm:text-3xl font-extrabold text-slate-950 tracking-tight">
              VALUE & TIME SAVED CALCULATOR
            </h3>
            <p className="text-slate-600 text-sm mt-2">Estimate Your Due Diligence Savings</p>
          </div>

          <p className="text-sm text-slate-600 text-center mb-6">
            Drag the slider to select how many property title checks you perform per month:
          </p>

          <div className="max-w-xl mx-auto space-y-8">
            <div>
              <div className="flex justify-between text-sm font-mono font-bold text-slate-700 mb-3">
                <span>Monthly Property Verifications</span>
                <span className="text-[#ea580c]">{sliderValue} properties</span>
              </div>
              <input
                type="range"
                min="1"
                max="100"
                step="1"
                value={sliderValue}
                onChange={(e) => setSliderValue(Number(e.target.value))}
                className="w-full h-2 bg-stone-200 rounded-full appearance-none cursor-pointer accent-[#ea580c]"
              />
              <div className="flex justify-between text-[11px] text-slate-400 font-mono mt-1">
                <span>1</span>
                <span>25</span>
                <span>50</span>
                <span>75</span>
                <span>100</span>
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className="rounded-2xl p-5 bg-gradient-to-br from-emerald-50 to-white border border-emerald-200 text-center">
                <div className="flex items-center justify-center gap-2 mb-1">
                  <CheckCircle className="w-4 h-4 text-emerald-600" />
                  <span className="text-[10px] font-mono font-bold text-emerald-800 uppercase tracking-wider">
                    Estimated Cost Savings
                  </span>
                </div>
                <span className="text-3xl font-black text-emerald-600 font-mono">{currentSavings.cost}</span>
                <span className="text-xs text-slate-500 block mt-1">vs traditional legal due diligence</span>
              </div>
              <div className="rounded-2xl p-5 bg-gradient-to-br from-orange-50 to-white border border-orange-200 text-center">
                <div className="flex items-center justify-center gap-2 mb-1">
                  <Clock className="w-4 h-4 text-[#ea580c]" />
                  <span className="text-[10px] font-mono font-bold text-orange-800 uppercase tracking-wider">
                    Closure Time Saved
                  </span>
                </div>
                <span className="text-3xl font-black text-[#ea580c] font-mono">{currentSavings.days}</span>
                <span className="text-xs text-slate-500 block mt-1">accelerated deal turnaround</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
};
