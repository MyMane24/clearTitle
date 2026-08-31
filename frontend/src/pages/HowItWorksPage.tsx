import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Navbar } from '../components/Navbar';
import { CtaFooter } from '../components/CtaFooter';
import { ScrollToTopButton } from '../components/ScrollToTopButton';
import { PROBLEM_METRICS, OLD_WAY_VS_CLEARTITLE } from '../data/landingData';
import { XCircle, CheckCircle2, AlertCircle, Sparkles, ArrowRight } from 'lucide-react';

export function HowItWorksPage() {
  const navigate = useNavigate();
  const goToApp = () => navigate('/app');

  const scrollToSection = (sectionId: string) => {
    const element = document.getElementById(sectionId);
    if (element) {
      element.scrollIntoView({ behavior: 'smooth' });
    }
  };

  return (
    <div className="min-h-screen bg-[#FFF8F2] text-stone-900 font-sans antialiased selection:bg-orange-200 selection:text-orange-900">
      <Navbar onOpenAudit={goToApp} onNavigate={scrollToSection} />

      {/* THE PROPERTY DUE DILIGENCE GAP */}
      <section className="pt-8 pb-24 px-6 bg-[#FAF9F6]">
        <div className="max-w-6xl mx-auto space-y-16">

          {/* Header */}
          <div className="text-center max-w-3xl mx-auto space-y-4">
            <h2 className="text-3xl sm:text-5xl font-extrabold tracking-tight text-slate-950 leading-tight">
              Property due diligence in India is slow, manual, fragmented.
            </h2>
            <p className="text-slate-600 text-sm sm:text-base leading-relaxed max-w-2xl mx-auto">
              clearTitle brings AI-powered cross-verification, regional language parsing, and a blockchain trust layer into one unified platform.
            </p>
          </div>

          {/* Problem Metrics */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {PROBLEM_METRICS.map((metric, idx) => (
              <div
                key={idx}
                className="soft-inner-card border border-[#e9e1dd] rounded-2xl p-6 sm:p-8 hover:border-orange-300 transition-colors shadow-md shadow-orange-500/5"
              >
                <div className="text-4xl sm:text-5xl font-bold text-[#f97316] font-mono tracking-tight mb-2">
                  {metric.value}
                </div>
                <h3 className="text-lg font-bold text-slate-900 mb-1">{metric.label}</h3>
                <p className="text-xs sm:text-sm text-slate-500 leading-relaxed">{metric.description}</p>
              </div>
            ))}
          </div>

          {/* Old Way vs clearTitle Way */}
          <div className="rounded-3xl bg-gradient-to-br from-[#ea580c] to-[#c2410c] p-6 sm:p-10 lg:p-12 shadow-2xl relative overflow-hidden">

            <div className="max-w-3xl mb-10">
              <span className="text-xs font-medium uppercase tracking-wider text-orange-200 bg-white/10 px-3 py-1 rounded-full inline-block mb-3">
                ONE PLATFORM INSTEAD OF 6 DISCONNECTED TOOLS
              </span>
              <h3 className="text-2xl sm:text-4xl font-bold text-white leading-tight">
                Land vetting is hard enough. <br className="hidden sm:inline" />
                Your tools shouldn't make it <em className="font-serif font-normal text-amber-200">harder</em>.
              </h3>
              <p className="text-orange-100 text-sm sm:text-base mt-3">
                Most property buyers, lawyers, and banks verify across 6+ disconnected state portals and manual spreadsheets. Here is what changes the day you switch to clearTitle.
              </p>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

              {/* The Old Way */}
              <div className="bg-stone-900/90 backdrop-blur-md rounded-2xl p-6 border border-white/10 text-stone-300">
                <div className="flex items-center gap-2 mb-4 pb-3 border-b border-stone-800">
                  <AlertCircle className="w-5 h-5 text-rose-400" />
                  <span className="text-xs font-medium uppercase tracking-wider text-rose-300">THE OLD WAY</span>
                </div>
                <ul className="space-y-3.5 text-xs sm:text-sm">
                  {OLD_WAY_VS_CLEARTITLE.oldWay.map((item, index) => (
                    <li key={index} className="flex items-start gap-2.5">
                      <XCircle className="w-4 h-4 text-rose-400 flex-shrink-0 mt-0.5" />
                      <span className="text-stone-300 leading-normal">{item}</span>
                    </li>
                  ))}
                </ul>
              </div>

              {/* The clearTitle Way */}
              <div className="bg-white rounded-2xl p-6 border border-orange-200 text-stone-900 shadow-xl">
                <div className="flex items-center gap-2 mb-4 pb-3 border-b border-stone-200">
                  <Sparkles className="w-5 h-5 text-[#ea580c]" />
                  <span className="text-xs font-medium uppercase tracking-wider text-[#ea580c]">THE CLEARTITLE WAY</span>
                </div>
                <ul className="space-y-3.5 text-xs sm:text-sm">
                  {OLD_WAY_VS_CLEARTITLE.clearTitleWay.map((item, index) => (
                    <li key={index} className="flex items-start gap-2.5">
                      <CheckCircle2 className="w-4 h-4 text-emerald-600 flex-shrink-0 mt-0.5" />
                      <span className="text-stone-800 font-medium leading-normal">{item}</span>
                    </li>
                  ))}
                </ul>
              </div>

            </div>

            <div className="mt-8 text-center">
              <button
                onClick={goToApp}
                className="px-8 py-3.5 bg-white text-[#ea580c] hover:bg-orange-50 font-bold rounded-xl shadow-lg transition-transform active:scale-95 cursor-pointer text-sm sm:text-base inline-flex items-center gap-2"
              >
                <span>Switch to clearTitle Verification</span>
                <ArrowRight className="w-4 h-4" />
              </button>
            </div>

          </div>

        </div>
      </section>

      <CtaFooter onStartAudit={goToApp} />
      <ScrollToTopButton />
    </div>
  );
}
