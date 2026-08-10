import React, { useState } from 'react';
import { ArrowRight, Menu, X, Sparkles } from 'lucide-react';
import clearTitleLogo from "../assets/clearTitle.png";

interface NavbarProps {
  onOpenAudit: () => void;
  onNavigate: (sectionId: string) => void;
}

export const Navbar: React.FC<NavbarProps> = ({ onOpenAudit, onNavigate }) => {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  const handleNavClick = (id: string) => {
    setMobileMenuOpen(false);
    onNavigate(id);
  };

  return (
    <header className="sticky top-0 z-50 bg-[#FFF8F2]/90 backdrop-blur-md border-b border-stone-200/60">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16 sm:h-20">
          
          {/* Logo */}
          <div 
            onClick={() => handleNavClick('hero')} 
            className="flex items-center gap-2.5 cursor-pointer group"
          >
            <img 
              src={clearTitleLogo}
              alt="clearTitle"
              className="h-10 sm:h-11 w-auto object-contain group-hover:scale-105 transition-transform"
            />
          </div>

          {/* Desktop Links */}
          <nav className="hidden lg:flex items-center gap-8 text-sm font-medium text-stone-700">
            <button 
              onClick={() => handleNavClick('problem')} 
              className="hover:text-[#ea580c] transition-colors cursor-pointer"
            >
              The Problem
            </button>
            <button 
              onClick={() => handleNavClick('solution')} 
              className="hover:text-[#ea580c] transition-colors cursor-pointer"
            >
              How it Works
            </button>
            <button 
              onClick={() => handleNavClick('live-demo')} 
              className="hover:text-[#ea580c] transition-colors flex items-center gap-1.5 cursor-pointer text-[#ea580c] font-semibold"
            >
              <Sparkles className="w-4 h-4" /> Live AI Audit
            </button>
            <button 
              onClick={() => handleNavClick('pricing')} 
              className="hover:text-[#ea580c] transition-colors cursor-pointer"
            >
              Pricing
            </button>
          </nav>

          {/* Right Action Buttons */}
          <div className="hidden sm:flex items-center gap-3">
            <button 
              onClick={onOpenAudit}
              className="px-5 py-2.5 text-sm font-semibold text-white bg-[#ea580c] hover:bg-[#c2410c] rounded-xl shadow-md shadow-orange-500/20 transition-all flex items-center gap-2 cursor-pointer active:scale-95"
            >
              <span>Run Free Scan</span>
              <ArrowRight className="w-4 h-4" />
            </button>
          </div>

          {/* Mobile Menu Button */}
          <div className="lg:hidden flex items-center gap-2">
            <button 
              onClick={onOpenAudit}
              className="px-3 py-1.5 text-xs font-semibold text-white bg-[#ea580c] rounded-lg cursor-pointer"
            >
              Scan
            </button>
            <button 
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
              className="p-2 text-stone-700 hover:text-stone-900 rounded-lg cursor-pointer"
            >
              {mobileMenuOpen ? <X className="w-6 h-6" /> : <Menu className="w-6 h-6" />}
            </button>
          </div>

        </div>
      </div>

      {/* Mobile Drawer */}
      {mobileMenuOpen && (
        <div className="lg:hidden bg-white border-b border-stone-200 px-4 pt-2 pb-6 space-y-3 shadow-lg">
          <button 
            onClick={() => handleNavClick('problem')} 
            className="block w-full text-left py-2 text-stone-800 font-medium"
          >
            The Problem
          </button>
          <button 
            onClick={() => handleNavClick('solution')} 
            className="block w-full text-left py-2 text-stone-800 font-medium"
          >
            How it Works
          </button>
          <button 
            onClick={() => handleNavClick('live-demo')} 
            className="block w-full text-left py-2 text-[#ea580c] font-semibold flex items-center gap-2"
          >
            <Sparkles className="w-4 h-4" /> Live AI Property Audit
          </button>
          <button 
            onClick={() => handleNavClick('pricing')} 
            className="block w-full text-left py-2 text-stone-800 font-medium"
          >
            Pricing & Plans
          </button>
          <div className="pt-2 border-t border-stone-100 flex flex-col gap-2">
            <button 
              onClick={onOpenAudit}
              className="w-full py-2.5 text-center font-semibold text-white bg-[#ea580c] rounded-xl shadow cursor-pointer"
            >
              Run Free AI Property Scan
            </button>
          </div>
        </div>
      )}
    </header>
  );
};
