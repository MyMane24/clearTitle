import React from 'react';
import { ArrowRight, Mail, Phone, MapPin, Heart } from 'lucide-react';
import clearTitleLogo from "../assets/clearTitle.png";

interface CtaFooterProps {
  onStartAudit: () => void;
}

export const CtaFooter: React.FC<CtaFooterProps> = ({ onStartAudit }) => {
  return (
    <footer className="bg-white pt-16 pb-12 border-t border-stone-200">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        
        {/* Bottom CTA Card - Matching reference image */}
        <div className="bg-stone-900 text-white rounded-3xl p-8 sm:p-14 text-center max-w-5xl mx-auto mb-20 shadow-2xl relative overflow-hidden">
          <div className="absolute inset-0 bg-gradient-to-tr from-orange-600/10 via-transparent to-amber-500/10 pointer-events-none" />

          <h2 className="text-3xl sm:text-5xl font-bold text-white tracking-tight leading-tight">
            Start running your property <br className="hidden sm:inline" />
            business the <em className="serif italic font-normal text-amber-200">calm</em> way
          </h2>

          <div className="mt-8 flex flex-col sm:flex-row items-center justify-center gap-4">
            <button
              onClick={onStartAudit}
              className="w-full sm:w-auto px-8 py-4 bg-[#ea580c] hover:bg-[#c2410c] text-white font-medium rounded-xl shadow-lg transition-transform active:scale-95 cursor-pointer text-sm sm:text-base flex items-center justify-center gap-2"
            >
              <span>Run Free Title Scan</span>
              <ArrowRight className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Footer Navigation Columns */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-8 mb-12 text-xs">
          
          {/* Col 1 Brand */}
          <div className="col-span-2 md:col-span-1">
            <div className="flex items-center gap-2 mb-3">
              <img
                src={clearTitleLogo}
                alt="clearTitle"
                className="h-7 w-auto object-contain"
              />
            </div>
            <p className="text-stone-500 leading-relaxed mb-4">
              Run your property business without the chaos. AI + Blockchain property title verification platform built in Belagavi, Karnataka.
            </p>
            <div className="space-y-1.5 text-stone-600 font-medium">
              <div className="flex items-center gap-1.5">
                <MapPin className="w-3.5 h-3.5 text-[#ea580c]" />
                <span>Vijaya Enclave, Tilakwadi, Belagavi</span>
              </div>
              <div className="flex items-center gap-1.5">
                <Phone className="w-3.5 h-3.5 text-[#ea580c]" />
                <span>+91 98454 57463</span>
              </div>
              <div className="flex items-center gap-1.5">
                <Mail className="w-3.5 h-3.5 text-[#ea580c]" />
                <span>rgprajwal@mymane.in</span>
              </div>
            </div>
          </div>

          {/* Col 2 Product */}
          <div>
            <h4 className="font-medium text-stone-900 uppercase tracking-wider mb-3">Product</h4>
            <ul className="space-y-2 text-stone-600 font-medium">
              <li><a href="#hero" className="hover:text-[#ea580c]">AI Title Audit</a></li>
              <li><a href="#solution" className="hover:text-[#ea580c]">Vernacular VLM</a></li>
              <li><a href="#live-demo" className="hover:text-[#ea580c]">Blockchain Trust Hash</a></li>
              <li><a href="#pricing" className="hover:text-[#ea580c]">Pricing & Plans</a></li>
            </ul>
          </div>

          {/* Col 3 Use Cases */}
          <div>
            <h4 className="font-medium text-stone-900 uppercase tracking-wider mb-3">Use Cases</h4>
            <ul className="space-y-2 text-stone-600 font-medium">
              <li><a href="#pricing" className="hover:text-[#ea580c]">Retail Home Buyers</a></li>
              <li><a href="#pricing" className="hover:text-[#ea580c]">Lawyers & Consultants</a></li>
              <li><a href="#pricing" className="hover:text-[#ea580c]">Banks & NBFCs</a></li>
              <li><a href="#pricing" className="hover:text-[#ea580c]">Land Developers</a></li>
            </ul>
          </div>

          {/* Col 4 Free Tools */}
          <div>
            <h4 className="font-medium text-stone-900 uppercase tracking-wider mb-3">Free Tools</h4>
            <ul className="space-y-2 text-stone-600 font-medium">
              <li><a href="#live-demo" className="hover:text-[#ea580c]">Sale Deed OCR Check</a></li>
              <li><a href="#live-demo" className="hover:text-[#ea580c]">ULPIN 14-Digit Lookup</a></li>
              <li><a href="#pricing" className="hover:text-[#ea580c]">Due Diligence Calculator</a></li>
              <li><a href="#live-demo" className="hover:text-[#ea580c]">Red Flag Scanner</a></li>
            </ul>
          </div>

          {/* Col 5 Company */}
          <div>
            <h4 className="font-medium text-stone-900 uppercase tracking-wider mb-3">Company</h4>
            <ul className="space-y-2 text-stone-600 font-medium">
              <li><a href="#team" className="hover:text-[#ea580c]">About MyMane</a></li>
              <li><a href="#team" className="hover:text-[#ea580c]">Team & Leadership</a></li>
              <li><a href="#pricing" className="hover:text-[#ea580c]">Privacy Policy</a></li>
              <li><a href="#pricing" className="hover:text-[#ea580c]">Terms & Conditions</a></li>
            </ul>
          </div>

        </div>

        {/* Bottom copyright line */}
        <div className="pt-6 border-t border-stone-100 flex flex-col sm:flex-row items-center justify-between text-xs text-stone-400 gap-2">
          <span>© 2026 clearTitle (MyMane / Zameendeko Tech Ventures). All rights reserved.</span>
        </div>

      </div>
    </footer>
  );
};