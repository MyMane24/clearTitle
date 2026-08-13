import React from 'react';
import { Link } from 'react-router-dom';
import { Mail, Phone, MapPin } from 'lucide-react';
import clearTitleLogo from "../assets/clearTitle.png";

interface CtaFooterProps {
  onStartAudit?: () => void;
}

export const CtaFooter: React.FC<CtaFooterProps> = () => {
  return (
    <footer className="bg-[#FFF8F2] pt-16 pb-12 border-t border-stone-200/80">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        
        {/* Main Footer Content */}
        <div className="grid grid-cols-1 md:grid-cols-12 gap-10 pb-12 border-b border-stone-200/80">
          
          {/* Brand & Address Column (5 cols) */}
          <div className="md:col-span-5 space-y-4">
            <Link to="/" className="inline-block group">
              <img
                src={clearTitleLogo}
                alt="clearTitle"
                className="h-12 sm:h-14 w-auto object-contain group-hover:scale-105 transition-transform"
              />
            </Link>
            <p className="text-stone-600 text-sm leading-relaxed max-w-sm">
              The AI & Blockchain land title due diligence platform built for home buyers, legal consultants, lenders, and developers across India.
            </p>

            <div className="pt-2 space-y-2 text-xs text-stone-600 font-medium">
              <div className="flex items-start gap-2">
                <MapPin className="w-4 h-4 text-[#ea580c] shrink-0 mt-0.5" />
                <span>Vijaya Enclave, Tilakwadi, Belagavi, Karnataka 590006</span>
              </div>
              <div className="flex items-center gap-2">
                <Phone className="w-4 h-4 text-[#ea580c] shrink-0" />
                <span>+91 98454 57463</span>
              </div>
              <div className="flex items-center gap-2">
                <Mail className="w-4 h-4 text-[#ea580c] shrink-0" />
                <span>rgprajwal@mymane.in</span>
              </div>
            </div>
          </div>

          {/* Links Grid (7 cols) */}
          <div className="md:col-span-7 grid grid-cols-2 sm:grid-cols-3 gap-8 pt-1">
            
            {/* Col 1 Platform */}
            <div>
              <h4 className="font-semibold text-stone-900 text-xs uppercase tracking-wider mb-4">
                Platform
              </h4>
              <ul className="space-y-3 text-sm text-stone-600">
                <li><a href="#hero" className="hover:text-[#ea580c] transition-colors">AI Title Audit</a></li>
                <li><a href="#solution" className="hover:text-[#ea580c] transition-colors">Vernacular VLM OCR</a></li>
                <li><a href="#live-demo" className="hover:text-[#ea580c] transition-colors">Blockchain Trust Hash</a></li>
                <li><a href="#pricing" className="hover:text-[#ea580c] transition-colors">Pricing & Plans</a></li>
              </ul>
            </div>

            {/* Col 2 Solutions */}
            <div>
              <h4 className="font-semibold text-stone-900 text-xs uppercase tracking-wider mb-4">
                Solutions
              </h4>
              <ul className="space-y-3 text-sm text-stone-600">
                <li><a href="#pricing" className="hover:text-[#ea580c] transition-colors">Home Buyers</a></li>
                <li><a href="#pricing" className="hover:text-[#ea580c] transition-colors">Legal Consultants</a></li>
                <li><a href="#pricing" className="hover:text-[#ea580c] transition-colors">Banks & NBFCs</a></li>
                <li><a href="#pricing" className="hover:text-[#ea580c] transition-colors">Land Developers</a></li>
              </ul>
            </div>

            {/* Col 3 Resources */}
            <div>
              <h4 className="font-semibold text-stone-900 text-xs uppercase tracking-wider mb-4">
                Free Tools
              </h4>
              <ul className="space-y-3 text-sm text-stone-600">
                <li><a href="#live-demo" className="hover:text-[#ea580c] transition-colors">Sale Deed Scanner</a></li>
                <li><a href="#live-demo" className="hover:text-[#ea580c] transition-colors">ULPIN 14-Digit Lookup</a></li>
                <li><a href="#pricing" className="hover:text-[#ea580c] transition-colors">Title Risk Calculator</a></li>
                <li><Link to="/app" className="hover:text-[#ea580c] transition-colors font-medium text-[#ea580c]">App Portal →</Link></li>
              </ul>
            </div>

          </div>
        </div>

        {/* Bottom Bar */}
        <div className="pt-8 flex flex-col sm:flex-row items-center justify-between gap-4 text-xs text-stone-500">
          <div>
            © {new Date().getFullYear()} clearTitle (MyMane / Zameendeko Tech Ventures). All rights reserved.
          </div>

          <div className="flex items-center gap-6">
            <a href="#pricing" className="hover:text-stone-800 transition-colors">Privacy Policy</a>
            <a href="#pricing" className="hover:text-stone-800 transition-colors">Terms of Service</a>
            <a href="#pricing" className="hover:text-stone-800 transition-colors">Security</a>
          </div>
        </div>

      </div>
    </footer>
  );
};