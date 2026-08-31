import React, { useEffect, useRef, useState } from 'react';
import { Minus, Plus } from 'lucide-react';

const PRESETS = [1, 5, 10, 25, 50, 100];

const formatIndian = (num: number) => {
  const s = String(num);
  const last3 = s.slice(-3);
  const rest = s.slice(0, -3);
  if (!rest) return last3;
  return rest.replace(/\B(?=(\d{2})+(?!\d))/g, ',') + ',' + last3;
};

function useAnimatedNumber(target: number, duration = 400) {
  const [value, setValue] = useState(target);
  const previous = useRef(target);

  useEffect(() => {
    const from = previous.current;
    const start = performance.now();
    let raf: number;

    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      setValue(from + (target - from) * eased);
      if (t < 1) raf = requestAnimationFrame(tick);
    };

    raf = requestAnimationFrame(tick);
    previous.current = target;
    return () => cancelAnimationFrame(raf);
  }, [target, duration]);

  return Math.round(value);
}

const clamp = (n: number) => Math.min(100, Math.max(1, n));

export const SavingsCalculator: React.FC = () => {
  const [volume, setVolume] = useState(10);
  const cost = useAnimatedNumber(7500 * volume);
  const days = useAnimatedNumber(12 * volume);
  const pct = ((volume - 1) / 99) * 100;

  const setVolumeFromInput = (raw: string) => {
    const n = parseInt(raw, 10);
    if (!Number.isNaN(n) && n >= 1 && n <= 100) setVolume(n);
  };

  return (
    <section className="py-20 lg:py-28 bg-[#FAF9F6] relative overflow-hidden">
      {/* Ambient glow */}
      <div className="absolute -top-24 left-1/3 w-[600px] h-[400px] bg-orange-200/25 rounded-full blur-3xl pointer-events-none" />

      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 relative">

        {/* Header */}
        <div className="max-w-2xl">
          <h2 className="text-3xl sm:text-4xl font-bold text-stone-900 tracking-tight leading-[1.15]">
            What <span className="text-[#ea580c]">clearTitle</span> keeps in{' '}
            <em className="font-serif-display text-[1.1em] font-normal not-italic text-stone-950">your pocket.</em>
          </h2>
          <p className="mt-3 text-stone-600 text-sm sm:text-base leading-relaxed">
            Adjust how many property checks you run a month — the savings read out live.
          </p>
        </div>

        {/* Split console */}
        <div className="mt-12 grid grid-cols-1 lg:grid-cols-12 gap-y-10 lg:gap-x-16 items-center">

          {/* Controls */}
          <div className="lg:col-span-5 flex flex-col gap-7">
            <div className="flex items-center justify-between gap-4">
              <span className="text-sm font-semibold text-stone-700">Checks per month</span>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setVolume(clamp(volume - 1))}
                  disabled={volume <= 1}
                  aria-label="Decrease"
                  className="w-9 h-9 rounded-full border border-stone-300 text-stone-600 flex items-center justify-center hover:border-[#ea580c] hover:text-[#ea580c] active:scale-90 transition-all disabled:opacity-30 cursor-pointer"
                >
                  <Minus className="w-4 h-4" />
                </button>
                <input
                  type="number"
                  min={1}
                  max={100}
                  value={volume}
                  onChange={(e) => setVolumeFromInput(e.target.value)}
                  aria-label="Property checks per month"
                  className="num-input-hide-spin w-14 h-9 text-center text-lg font-black font-mono tabular-nums text-stone-900 bg-transparent outline-none rounded-lg focus:ring-2 focus:ring-[#ea580c]/30 hover:border hover:border-stone-300 transition-colors"
                />
                <button
                  onClick={() => setVolume(clamp(volume + 1))}
                  disabled={volume >= 100}
                  aria-label="Increase"
                  className="w-9 h-9 rounded-full border border-stone-300 text-stone-600 flex items-center justify-center hover:border-[#ea580c] hover:text-[#ea580c] active:scale-90 transition-all disabled:opacity-30 cursor-pointer"
                >
                  <Plus className="w-4 h-4" />
                </button>
              </div>
            </div>

            <input
              type="range"
              min="1"
              max="100"
              step="1"
              value={volume}
              onChange={(e) => setVolume(Number(e.target.value))}
              aria-label="Monthly property check volume"
              className="slider-thumb w-full"
              style={{ background: `linear-gradient(to right, #ea580c ${pct}%, #e7e5e4 ${pct}%)` }}
            />

            <div className="flex flex-wrap gap-2">
              {PRESETS.map((p) => (
                <button
                  key={p}
                  onClick={() => setVolume(p)}
                  className={`px-3.5 py-1.5 rounded-full text-xs font-mono font-bold border transition-colors active:scale-95 cursor-pointer ${
                    volume === p
                      ? 'bg-[#ea580c] text-white border-[#ea580c]'
                      : 'bg-transparent text-stone-500 border-stone-300 hover:border-[#ea580c] hover:text-[#ea580c]'
                  }`}
                >
                  {p}
                </button>
              ))}
            </div>
          </div>

          {/* Readouts */}
          <div className="lg:col-span-7 lg:border-l lg:border-stone-300/60 lg:pl-12 xl:pl-16">
            <div className="grid grid-cols-2 divide-x divide-stone-300/60">
              <div className="pr-3 sm:pr-10 py-2 flex flex-col gap-2 sm:gap-3">
                <p className="text-[10px] sm:text-[11px] font-bold uppercase tracking-[0.12em] sm:tracking-[0.14em] text-stone-400">Estimated cost savings</p>
                <p className="text-2xl sm:text-5xl font-black font-mono tabular-nums tracking-tighter text-stone-900 leading-none">
                  <span className="text-lg sm:text-3xl text-[#ea580c] align-top mr-1">₹</span>
                  {formatIndian(cost)}
                </p>
                <p className="text-[11px] sm:text-xs text-stone-500 leading-snug">vs traditional legal due diligence</p>
              </div>

              <div className="pl-3 sm:pl-10 py-2 flex flex-col gap-2 sm:gap-3">
                <p className="text-[10px] sm:text-[11px] font-bold uppercase tracking-[0.12em] sm:tracking-[0.14em] text-stone-400">Closure time saved</p>
                <p className="text-2xl sm:text-5xl font-black font-mono tabular-nums tracking-tighter text-stone-900 leading-none">
                  {days}
                  <span className="text-sm sm:text-lg font-bold text-stone-400 ml-1 sm:ml-2">days</span>
                </p>
                <p className="text-[11px] sm:text-xs text-stone-500 leading-snug">accelerated deal turnaround</p>
              </div>
            </div>
          </div>
        </div>

      </div>
    </section>
  );
};