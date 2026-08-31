import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Navbar } from '../components/Navbar';
import { CtaFooter } from '../components/CtaFooter';
import { ScrollToTopButton } from '../components/ScrollToTopButton';
import { Check, Zap, Shield, Building2 } from 'lucide-react';

export function PricingPage() {
  const navigate = useNavigate();
  const goToApp = () => navigate('/app');

  const scrollToSection = (sectionId: string) => {
    const element = document.getElementById(sectionId);
    if (element) {
      element.scrollIntoView({ behavior: 'smooth' });
    }
  };

  const plans = [
    {
      name: 'Basic AI Scan',
      price: '₹499 – ₹1,999',
      subtitle: 'per property report',
      description: 'Instant AI document analysis & red flag summary for retail home buyers.',
      features: [
        'Instant AI document OCR & extraction',
        'Survey number & area match check',
        'PDF Summary download',
        'Standard email support',
      ],
      cta: 'Run Instant Scan',
      icon: <Zap className="w-5 h-5" />,
      popular: false,
    },
    {
      name: 'Standard Check',
      price: '₹3,000 – ₹7,500',
      subtitle: 'per property report',
      description: 'Complex retail & land investigations with deep Vernacular AI analysis.',
      features: [
        'Everything in Basic Scan',
        'Full Chain of Title analysis (13-30 yrs)',
        'Vernacular language AI parsing (Kannada/Hindi)',
        'Red Flag risk alert matrix',
        'Priority verification desk review',
      ],
      cta: 'Start Standard Check',
      icon: <Shield className="w-5 h-5" />,
      popular: true,
    },
    {
      name: 'Premium Diligence',
      price: '₹10,000+',
      subtitle: 'per property report',
      description: 'Deep legal histories, multi-parcel land checks, and court litigation search.',
      features: [
        'Everything in Standard Check',
        'District & High Court litigation scan',
        'Bank mortgage NOC verification',
        'ULPIN 14-digit Bhu-Aadhar geotag audit',
        '1-on-1 Legal Expert consultation call',
        'Custom branded client report',
      ],
      cta: 'Order Premium Check',
      icon: <Building2 className="w-5 h-5" />,
      popular: false,
    },
  ];

  return (
    <div className="min-h-screen bg-[#FFF8F2] text-stone-900 font-sans antialiased selection:bg-orange-200 selection:text-orange-900">
      <Navbar onOpenAudit={goToApp} onNavigate={scrollToSection} />

      <section className="pt-8 pb-24 px-6 bg-[#FAF9F6]">
        <div className="max-w-6xl mx-auto space-y-16">

          {/* Header */}
          <div className="text-center max-w-3xl mx-auto space-y-4">
            <h2 className="text-3xl sm:text-5xl font-extrabold tracking-tight text-slate-950 leading-tight">
              Transparent Pricing per Property Basis
            </h2>
            <p className="text-slate-600 text-sm sm:text-base leading-relaxed max-w-2xl mx-auto">
              Pay per property report — no hidden subscriptions. Scale from single home purchases to multi-parcel enterprise acquisitions.
            </p>
          </div>

          {/* Pricing Cards */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {plans.map((plan) => (
              <div
                key={plan.name}
                className={`relative rounded-3xl p-6 sm:p-8 border transition-all ${
                  plan.popular
                    ? 'bg-white border-orange-300 shadow-xl shadow-orange-500/10 scale-[1.02]'
                    : 'bg-white/80 border-[#e9e1dd] hover:border-orange-200'
                }`}
              >
                {plan.popular && (
                  <div className="absolute -top-3.5 left-1/2 -translate-x-1/2 px-4 py-1 bg-[#ea580c] text-white text-[11px] font-bold font-mono uppercase tracking-wider rounded-full shadow-lg shadow-orange-500/30">
                    MOST POPULAR
                  </div>
                )}

                <div className="flex items-center gap-3 mb-4">
                  <div className={`w-10 h-10 rounded-xl flex items-center justify-center ${
                    plan.popular ? 'bg-orange-100 text-[#ea580c]' : 'bg-stone-100 text-stone-600'
                  }`}>
                    {plan.icon}
                  </div>
                  <h3 className="text-lg font-bold text-slate-900">{plan.name}</h3>
                </div>

                <div className="mb-4">
                  <span className="text-3xl font-black text-slate-950 font-mono">{plan.price}</span>
                  <span className="text-sm text-slate-500 block mt-1">{plan.subtitle}</span>
                </div>

                <p className="text-sm text-slate-600 mb-6 leading-relaxed">{plan.description}</p>

                <ul className="space-y-3 mb-8">
                  {plan.features.map((feature, i) => (
                    <li key={i} className="flex items-start gap-2.5 text-sm text-slate-700">
                      <Check className={`w-4 h-4 mt-0.5 flex-shrink-0 ${plan.popular ? 'text-[#ea580c]' : 'text-emerald-500'}`} />
                      <span>{feature}</span>
                    </li>
                  ))}
                </ul>

                <button
                  onClick={goToApp}
                  className={`w-full py-3 px-4 rounded-xl font-bold text-sm transition-colors cursor-pointer ${
                    plan.popular
                      ? 'bg-[#ea580c] hover:bg-[#dc4a0a] text-white shadow-lg shadow-orange-500/25'
                      : 'bg-stone-900 hover:bg-stone-800 text-white'
                  }`}
                >
                  {plan.cta}
                </button>
              </div>
            ))}
          </div>

          {/* Enterprise Row */}
          <div className="rounded-3xl p-6 sm:p-8 border border-stone-200 bg-white/80">
            <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-6">
              <div className="flex-1">
                <div className="flex items-center gap-3 mb-3">
                  <div className="w-10 h-10 rounded-xl bg-stone-100 flex items-center justify-center text-stone-600">
                    <Building2 className="w-5 h-5" />
                  </div>
                  <h3 className="text-lg font-bold text-slate-900">Enterprise SaaS / API</h3>
                </div>
                <p className="text-sm text-slate-600 mb-4 lg:mb-0">
                  Built for Banks, NBFCs, Housing Finance, and Large Developer Desks.
                </p>
              </div>
              <div className="flex-1">
                <ul className="space-y-2 text-sm text-slate-700">
                  <li className="flex items-center gap-2"><Check className="w-4 h-4 text-emerald-500" /> Bulk automated document processing API</li>
                  <li className="flex items-center gap-2"><Check className="w-4 h-4 text-emerald-500" /> Custom ERP & LOS integration</li>
                  <li className="flex items-center gap-2"><Check className="w-4 h-4 text-emerald-500" /> White-label client verification portal</li>
                  <li className="flex items-center gap-2"><Check className="w-4 h-4 text-emerald-500" /> Dedicated account manager & SLA</li>
                </ul>
              </div>
              <div className="lg:text-right">
                <span className="text-2xl font-black text-slate-950 font-mono block">Custom / API</span>
                <span className="text-sm text-slate-500 block mb-4">per monthly volume</span>
                <button
                  onClick={goToApp}
                  className="px-6 py-3 bg-stone-900 hover:bg-stone-800 text-white font-bold text-sm rounded-xl transition-colors cursor-pointer"
                >
                  Contact Enterprise Desk
                </button>
              </div>
            </div>
          </div>

        </div>
      </section>

      <CtaFooter onStartAudit={goToApp} />
      <ScrollToTopButton />
    </div>
  );
}
