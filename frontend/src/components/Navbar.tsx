import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, Menu, X, Sparkles } from 'lucide-react';
import clearTitleLogo from "../assets/clearTitle.png";

interface NavbarProps {
  onOpenAudit: () => void;
  onNavigate: (sectionId: string) => void;
}

export const Navbar: React.FC<NavbarProps> = ({ onOpenAudit, onNavigate }) => {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    let ticking = false;
    const handleScroll = () => {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(() => {
        setScrolled(window.scrollY > 20);
        ticking = false;
      });
    };
    window.addEventListener('scroll', handleScroll, { passive: true });
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

  const handleNavClick = (id: string) => {
    setMobileMenuOpen(false);
    onNavigate(id);
  };

  return (
    <header className={`sticky top-0 z-50 w-full transition-all duration-300 ${
      scrolled ? 'bg-white/95 backdrop-blur-md border-b border-stone-200/80 shadow-[0_8px_30px_rgb(0,0,0,0.07)]' : 'bg-[#FFF8F2] border-b border-stone-200/30'
    }`}>
      <div className="w-full max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-3 flex items-center justify-between">
        
        {/* Logo */}
        <Link
          to="/"
          onClick={() => setMobileMenuOpen(false)}
          className="flex items-center gap-2.5 cursor-pointer group"
        >
          <img
            src={clearTitleLogo}
            alt="clearTitle"
            className="h-10 sm:h-12 w-auto object-contain group-hover:scale-105 transition-transform"
          />
        </Link>

        {/* Desktop Nav Links */}
        <nav className="hidden lg:flex items-center gap-8 text-[14px] font-medium text-stone-600">
          <button 
            onClick={() => handleNavClick('problem')} 
            className="hover:text-stone-900 transition-colors cursor-pointer"
          >
            The Problem
          </button>
          <Link
            to="/how-it-works"
            onClick={() => setMobileMenuOpen(false)}
            className="hover:text-stone-900 transition-colors cursor-pointer"
          >
            How it Works
          </Link>
          <button 
            onClick={() => handleNavClick('live-demo')} 
            className="hover:text-stone-900 transition-colors flex items-center gap-1.5 cursor-pointer text-[#ea580c] font-semibold"
          >
            <Sparkles className="w-3.5 h-3.5 text-[#ea580c]" /> Live AI Audit
          </button>
          <Link
            to="/pricing"
            onClick={() => setMobileMenuOpen(false)}
            className="hover:text-stone-900 transition-colors cursor-pointer"
          >
            Pricing
          </Link>
        </nav>

        {/* Right Actions */}
        <div className="hidden sm:flex items-center gap-4">
          <Link
            to="/login"
            className="text-[14px] font-medium text-stone-700 hover:text-stone-900 transition-colors px-2 py-1 cursor-pointer"
          >
            Sign in
          </Link>
          <button 
            onClick={onOpenAudit}
            className="px-5 py-2.5 text-[14px] font-medium text-white bg-[#0F172A] hover:bg-slate-800 rounded-full shadow-sm transition-all flex items-center gap-2 cursor-pointer group active:scale-95"
          >
            <span>Run Free Scan</span>
            <ArrowRight className="w-4 h-4 text-stone-300 group-hover:translate-x-0.5 transition-transform" />
          </button>
        </div>

        {/* Mobile Menu Toggle Button */}
        <div className="sm:hidden flex items-center gap-2">
          <button 
            onClick={onOpenAudit}
            className="px-3 py-1.5 text-xs font-semibold text-white bg-[#0F172A] rounded-full cursor-pointer flex items-center gap-1"
          >
            <span>Scan</span>
            <ArrowRight className="w-3 h-3" />
          </button>
          <button 
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            className="p-1.5 text-stone-700 hover:text-stone-900 rounded-lg cursor-pointer"
            aria-label="Toggle menu"
          >
            {mobileMenuOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
          </button>
        </div>

      </div>

      {/* Mobile Drawer */}
      {mobileMenuOpen && (
        <div className={`sm:hidden mt-2 bg-white/95 backdrop-blur-xl border border-stone-200/90 rounded-2xl p-4 space-y-3 shadow-xl ${
          scrolled ? '' : 'mx-2'
        }`}>
          <button 
            onClick={() => handleNavClick('problem')} 
            className="block w-full text-left py-2 text-stone-700 font-medium text-sm hover:text-stone-900"
          >
            The Problem
          </button>
          <Link
            to="/how-it-works"
            onClick={() => setMobileMenuOpen(false)}
            className="block w-full text-left py-2 text-stone-700 font-medium text-sm hover:text-stone-900"
          >
            How it Works
          </Link>
          <button 
            onClick={() => handleNavClick('live-demo')} 
            className="block w-full text-left py-2 text-[#ea580c] font-semibold text-sm flex items-center gap-2"
          >
            <Sparkles className="w-4 h-4 text-[#ea580c]" /> Live AI Audit
          </button>
          <Link
            to="/pricing"
            onClick={() => setMobileMenuOpen(false)}
            className="block w-full text-left py-2 text-stone-700 font-medium text-sm hover:text-stone-900"
          >
            Pricing & Plans
          </Link>
          <div className="pt-2 border-t border-stone-100 flex flex-col gap-2">
            <Link
              to="/login"
              onClick={() => setMobileMenuOpen(false)}
              className="w-full py-2 text-center text-sm font-medium text-stone-700 hover:text-stone-900 block"
            >
              Sign in
            </Link>
            <button 
              onClick={() => {
                setMobileMenuOpen(false);
                onOpenAudit();
              }}
              className="w-full py-2.5 text-center text-sm font-medium text-white bg-[#0F172A] rounded-full shadow cursor-pointer flex items-center justify-center gap-2"
            >
              <span>Run Free Scan</span>
              <ArrowRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}
    </header>
  );
};

