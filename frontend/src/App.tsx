import React, { useEffect, useState } from 'react';
import { Navbar } from './components/Navbar';
import { HeroSection } from './components/HeroSection';
import { LiveVerificationSection } from './components/LiveVerificationSection';
import { ProblemSolutionSection } from './components/ProblemSolutionSection';
import { FourStepPipeline } from './components/FourStepPipeline';
import { InteractiveAuditDemo } from './components/InteractiveAuditDemo';
import { ProductSnapshots } from './components/ProductSnapshots';
import { MarketAndRevenue } from './components/MarketAndRevenue';
import { FaqSection } from './components/FaqSection';
import { CtaFooter } from './components/CtaFooter';
import { ScrollToTopButton } from './components/ScrollToTopButton';
import { VerificationDashboard } from './dashboard/VerificationDashboard';

type View = 'home' | 'app';

const viewFromHash = (): View => (window.location.hash === '#/app' ? 'app' : 'home');

export default function App() {
  const [view, setView] = useState<View>(viewFromHash);

  useEffect(() => {
    const onHash = () => {
      setView(viewFromHash());
      window.scrollTo(0, 0);
    };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  const goToApp = () => {
    window.location.hash = '#/app';
  };

  const scrollToSection = (sectionId: string) => {
    const element = document.getElementById(sectionId);
    if (element) {
      element.scrollIntoView({ behavior: 'smooth' });
    }
  };

  if (view === 'app') {
    return <VerificationDashboard />;
  }

  return (
    <div className="min-h-screen bg-[#FFF8F2] text-stone-900 font-sans antialiased selection:bg-orange-200 selection:text-orange-900">

      {/* Top Navbar */}
      <Navbar
        onOpenAudit={goToApp}
        onNavigate={scrollToSection}
      />

      {/* Hero Section */}
      <HeroSection
        onStartAudit={goToApp}
        onSeeDemo={() => scrollToSection('solution')}
      />

      {/* Live Verification Report Card — just below the Hero */}
      <LiveVerificationSection
        onStartAudit={goToApp}
      />

      {/* Problem vs Solution (The Old Way vs clearTitle Way) */}
      <ProblemSolutionSection
        onStartAudit={goToApp}
      />

      {/* 4-Step Verification Pipeline */}
      <FourStepPipeline
        onStartAudit={goToApp}
      />

      {/* Interactive AI Audit Playground & Scanner */}
      <InteractiveAuditDemo />

      {/* Product Readiness & Snapshots */}
      <ProductSnapshots />

      {/* Market Segments, Pricing & Financial Projections */}
      <MarketAndRevenue
        onStartAudit={goToApp}
      />

      {/* FAQs */}
      <FaqSection />

      {/* CTA Banner & Footer */}
      <CtaFooter
        onStartAudit={goToApp}
      />

      {/* Scroll to top */}
      <ScrollToTopButton />

    </div>
  );
}
