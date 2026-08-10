import React from 'react';
import { AlertTriangle, FileText, CheckCircle } from 'lucide-react';

export const ProductSnapshots: React.FC = () => {
  return (
    <section className="py-20 lg:py-24 bg-[#faf8f5] border-b border-stone-200">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">

        {/* Snapshots Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
          
          {/* Snapshot 1 */}
          <div className="bg-white rounded-2xl border border-stone-200 overflow-hidden shadow-lg hover:shadow-xl transition-shadow">
            <div className="bg-stone-900 text-white px-5 py-3 flex items-center justify-between text-xs font-semibold">
              <span>SNAPSHOT 01 • DOCUMENT AUDIT OVERVIEW</span>
              <span className="bg-amber-500/20 text-amber-300 px-2 py-0.5 rounded text-[10px] font-medium">Review Required</span>
            </div>
            <div className="p-6 bg-[#faf8f5]">
              <div className="bg-white rounded-xl border border-stone-200 p-4 shadow-xs mb-4">
                <div className="text-xs font-medium text-stone-400 uppercase mb-1">Documents Reviewed: 02</div>
                <div className="grid grid-cols-2 gap-3 mt-2">
                  <div className="bg-emerald-50 border border-emerald-200 rounded-lg p-3 text-center">
                    <span className="text-2xl font-bold text-emerald-700">04</span>
                    <span className="block text-[11px] font-medium text-emerald-800 uppercase">Positive Matches</span>
                  </div>
                  <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-center">
                    <span className="text-2xl font-bold text-amber-700">03</span>
                    <span className="block text-[11px] font-medium text-amber-800 uppercase">Red Flags</span>
                  </div>
                </div>
              </div>

              <div className="bg-white rounded-xl border border-stone-200 p-4 text-xs space-y-2">
                <div className="font-medium text-stone-800 flex items-center gap-1.5">
                  <FileText className="w-4 h-4 text-[#ea580c]" />
                  <span>Reference Document: Sale Deed (NewSaleDeed.pdf)</span>
                </div>
                <div className="text-stone-600 pl-5">
                  Valid Property Record • Area: 422 Sq. Fts. • Survey No: CTS No. 422/A-1
                </div>
              </div>
            </div>
          </div>

          {/* Snapshot 2 */}
          <div className="bg-white rounded-2xl border border-stone-200 overflow-hidden shadow-lg hover:shadow-xl transition-shadow">
            <div className="bg-stone-900 text-white px-5 py-3 flex items-center justify-between text-xs font-semibold">
              <span>SNAPSHOT 02 • RED FLAG AUDIT MATRIX</span>
              <span className="bg-rose-500/20 text-rose-300 px-2 py-0.5 rounded text-[10px] font-medium">3 Findings</span>
            </div>
            <div className="p-6 bg-[#faf8f5] space-y-3">
              
              <div className="bg-white border border-rose-200 rounded-xl p-3.5 text-xs">
                <div className="flex items-center gap-2 font-medium text-rose-900 mb-1">
                  <AlertTriangle className="w-4 h-4 text-rose-600" />
                  <span>CRITICAL FLAG: Vendors Name Mismatch</span>
                </div>
                <p className="text-stone-600 text-[11px]">
                  NewSaleDeed.pdf shows "M/s Constructions" vs EC.png shows "M/s Prakash Constructions". Partner names require verification.
                </p>
              </div>

              <div className="bg-white border border-amber-200 rounded-xl p-3.5 text-xs">
                <div className="flex items-center gap-2 font-medium text-amber-900 mb-1">
                  <AlertTriangle className="w-4 h-4 text-amber-600" />
                  <span>WARNING: Purchasers Spelling Difference</span>
                </div>
                <p className="text-stone-600 text-[11px]">
                  NewSaleDeed.pdf shows "Shri. Prakash M." while EC.png shows "Shri. Prakash Mallappa".
                </p>
              </div>

              <div className="bg-white border border-emerald-200 rounded-xl p-3.5 text-xs">
                <div className="flex items-center gap-2 font-medium text-emerald-900 mb-1">
                  <CheckCircle className="w-4 h-4 text-emerald-600" />
                  <span>VERIFIED: Document Schedule & Plot Area</span>
                </div>
                <p className="text-stone-600 text-[11px]">
                  Super built-up area matches EC.png exactly at 422 Sq. Fts.
                </p>
              </div>

            </div>
          </div>

        </div>

      </div>
    </section>
  );
};
