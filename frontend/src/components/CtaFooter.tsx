import React from 'react';
import { Link } from 'react-router-dom';
import { Mail, Phone, MapPin, ArrowRight } from 'lucide-react';

interface CtaFooterProps {
  onStartAudit?: () => void;
}

export const CtaFooter: React.FC<CtaFooterProps> = () => {
  return (
    <footer className="bg-[#FAF9F6] text-slate-800 pt-12 pb-12 px-6 sm:px-12 border-t border-[#e9e1dd] selection:bg-orange-100 selection:text-orange-950">
      <div className="max-w-7xl mx-auto space-y-16">

        {/* All Columns Top-Aligned in a Single Row */}
        <div className="grid grid-cols-1 md:grid-cols-12 gap-10 lg:gap-14 items-start">

          {/* Brand & Direct Contacts (5 Cols) */}
          <div className="md:col-span-5 space-y-5">
            <Link to="/" className="inline-block">
              <span className="text-4xl font-black tracking-tight block" style={{ background: 'linear-gradient(135deg, #ea580c 0%, #f59e0b 100%)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
                clearTitle
              </span>
            </Link>

            <p className="text-xs sm:text-sm text-slate-600 leading-relaxed max-w-sm">
              The AI & Blockchain land title due diligence platform built for home buyers, legal consultants, lenders, and developers across India.
            </p>

            {/* Structured Contact Details */}
            <div className="space-y-2.5 text-xs font-mono text-slate-600 pt-1">
              <div className="flex items-start gap-2">
                <MapPin className="w-4 h-4 text-orange-600 shrink-0 mt-0.5" />
                <span>Vijaya Enclave, Tilakwadi, Belagavi, Karnataka 590006</span>
              </div>
              <div className="flex items-center gap-2">
                <Phone className="w-4 h-4 text-orange-600 shrink-0" />
                <a href="tel:+919845457463" className="hover:text-orange-600 transition-colors">+91 98454 57463</a>
              </div>
              <div className="flex items-center gap-2">
                <Mail className="w-4 h-4 text-orange-600 shrink-0" />
                <a href="mailto:rgprajwal@mymane.in" className="hover:text-orange-600 transition-colors">rgprajwal@mymane.in</a>
              </div>
            </div>
          </div>

          {/* Column 1: Platform (2 Cols) */}
          <div className="md:col-span-2 md:pt-14 space-y-4">
            <span className="font-mono text-xs font-bold text-slate-900 tracking-wider uppercase block">
              PLATFORM
            </span>
            <ul className="space-y-3 text-xs font-medium text-slate-600">
              <li><a href="#hero" className="hover:text-orange-600 transition-colors">AI Title Audit</a></li>
              <li><a href="#solution" className="hover:text-orange-600 transition-colors">Vernacular OCR</a></li>
              <li><a href="#live-demo" className="hover:text-orange-600 transition-colors">Blockchain Trust Hash</a></li>
              <li><a href="/pricing" className="hover:text-orange-600 transition-colors">Pricing & Plans</a></li>
            </ul>
          </div>

          {/* Column 2: Solutions (3 Cols) */}
          <div className="md:col-span-3 md:pt-14 space-y-4">
            <span className="font-mono text-xs font-bold text-slate-900 tracking-wider uppercase block">
              SOLUTIONS
            </span>
            <ul className="space-y-3 text-xs font-medium text-slate-600">
              <li><a href="#segments" className="hover:text-orange-600 transition-colors">Home Buyers</a></li>
              <li><a href="#segments" className="hover:text-orange-600 transition-colors">Legal Consultants</a></li>
              <li><a href="#segments" className="hover:text-orange-600 transition-colors">Banks & NBFCs</a></li>
              <li><a href="#segments" className="hover:text-orange-600 transition-colors">Land Developers</a></li>
            </ul>
          </div>

          {/* Column 3: Free Tools (2 Cols) */}
          <div className="md:col-span-2 md:pt-14 space-y-4">
            <span className="font-mono text-xs font-bold text-slate-900 tracking-wider uppercase block">
              FREE TOOLS
            </span>
            <ul className="space-y-3 text-xs font-medium text-slate-600">
              <li><a href="#live-demo" className="hover:text-orange-600 transition-colors">Sale Deed Scanner</a></li>
              <li><a href="#live-demo" className="hover:text-orange-600 transition-colors">ULPIN 14-Digit Lookup</a></li>
              <li><a href="#pricing" className="hover:text-orange-600 transition-colors">Title Risk Calculator</a></li>
              <li className="pt-1">
                <Link to="/app" className="inline-flex items-center gap-1 text-[#ea580c] hover:text-orange-700 font-mono font-bold text-xs transition-colors">
                  <span>App Portal</span>
                  <ArrowRight className="w-3.5 h-3.5" />
                </Link>
              </li>
            </ul>
          </div>

        </div>

        {/* Bottom Bar */}
        <div className="pt-8 border-t border-[#e9e1dd] flex flex-col sm:flex-row items-center justify-between gap-4 text-xs font-mono text-slate-500">
          <p className="text-center sm:text-left">
            &copy; 2026 clearTitle (MyMane / Zameendeko Tech Ventures). All rights reserved.
          </p>

          <div className="flex items-center gap-6">
            <a href="#pricing" className="hover:text-orange-600 transition-colors">Privacy Policy</a>
            <a href="#pricing" className="hover:text-orange-600 transition-colors">Terms of Service</a>
            <a href="#pricing" className="hover:text-orange-600 transition-colors">Security</a>
          </div>
        </div>

      </div>
    </footer>
  );
};
