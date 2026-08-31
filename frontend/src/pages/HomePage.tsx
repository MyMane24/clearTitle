import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Navbar } from '../components/Navbar';
import { HeroSection } from '../components/HeroSection';
import { LiveVerificationSection } from '../components/LiveVerificationSection';
import { ProblemSolutionSection } from '../components/ProblemSolutionSection';
import { FourStepPipeline } from '../components/FourStepPipeline';
import { SavingsCalculator } from '../components/SavingsCalculator';
import { WhoWeEmpower } from '../components/WhoWeEmpower';
import { FaqSection } from '../components/FaqSection';
import { CtaFooter } from '../components/CtaFooter';
import { ScrollToTopButton } from '../components/ScrollToTopButton';

export function HomePage() {
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

      {/* Savings Calculator */}
      <SavingsCalculator />

      {/* Who We Empower */}
      <WhoWeEmpower />

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
