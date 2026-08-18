import React, { useState, useEffect } from 'react';
import { 
  FileText, 
  ShieldCheck, 
  Building2, 
  Sparkles, 
  Check, 
  Lock, 
  Database,
  Shield,
  CheckCircle2
} from 'lucide-react';

interface PipelineProps {
  onStartAudit?: () => void;
}

interface VerticalInputDoc {
  id: string;
  name: string;
  sub: string;
  code: string;
  icon: 'FileText' | 'ShieldCheck' | 'Building2';
}

interface StreamedResultItem {
  id: string;
  title: string;
  detail: string;
}

const VERTICAL_INPUT_DOCS: VerticalInputDoc[] = [
  {
    id: 'sale-deeds',
    name: 'Sale Deeds',
    sub: 'Registered Deeds & Certified Copies',
    code: 'DOC-DEED-01',
    icon: 'FileText'
  },
  {
    id: 'ec-cert',
    name: 'Encumbrance Certificate (EC)',
    sub: '30-Year Form 15 Search Record',
    code: 'DOC-EC-30YR',
    icon: 'ShieldCheck'
  },
  {
    id: 'khata-ror',
    name: 'e-Khata & ROR Extract',
    sub: 'Property ID & Khatiyan Documents',
    code: 'DOC-KHT-REV',
    icon: 'Building2'
  }
];

const STREAMED_RESULT_ITEMS: StreamedResultItem[] = [
  {
    id: 'vendors-chain',
    title: 'Vendors & Chain of Title',
    detail: '30-Year Unbroken Ownership Chain • 0 Gap Discrepancies'
  },
  {
    id: 'purchasers-owner',
    title: 'Purchasers & Owner Details',
    detail: 'Present Owner & Historical Vendor Identity Matched'
  },
  {
    id: 'property-survey',
    title: 'Property survey/CTS number',
    detail: 'CTS No. 422/A-1 • Extent Area & Boundaries Reconciled'
  },
  {
    id: 'encumbrance-mortgage',
    title: 'Encumbrance & Mortgage Status',
    detail: '0 Undisclosed Mortgages or Active Bank Liens Found'
  }
];

export const FourStepPipeline: React.FC<PipelineProps> = () => {
  const [activeDocIdx, setActiveDocIdx] = useState<number>(0);
  const [revealedCount, setRevealedCount] = useState<number>(1);
  const [isScanning, setIsScanning] = useState<boolean>(true);

  // Continuous loop for document stream
  useEffect(() => {
    const timer = setInterval(() => {
      setActiveDocIdx((prev) => (prev + 1) % VERTICAL_INPUT_DOCS.length);
    }, 4000);

    return () => clearInterval(timer);
  }, []);

  // Update animation state when active document changes
  useEffect(() => {
    setIsScanning(true);
    setRevealedCount(activeDocIdx + 1);

    const scanDoneTimer = setTimeout(() => {
      setIsScanning(false);
    }, 1300);

    return () => clearTimeout(scanDoneTimer);
  }, [activeDocIdx]);

  const activeDoc = VERTICAL_INPUT_DOCS[activeDocIdx];

  const getDocIcon = (iconName: string) => {
    switch (iconName) {
      case 'FileText': return <FileText className="w-5 h-5 text-[#ea580c]" />;
      case 'ShieldCheck': return <ShieldCheck className="w-5 h-5 text-[#ea580c]" />;
      case 'Building2': return <Building2 className="w-5 h-5 text-[#ea580c]" />;
      default: return <FileText className="w-5 h-5 text-[#ea580c]" />;
    }
  };

  return (
    <section id="solution" className="py-20 lg:py-28 bg-[#faf8f5] border-b border-stone-200 relative overflow-hidden">
      
      {/* Ambient background glows */}
      <div className="absolute top-1/4 left-1/3 w-[500px] h-[500px] bg-orange-200/20 rounded-full blur-3xl pointer-events-none"></div>
      <div className="absolute bottom-10 right-1/4 w-[450px] h-[450px] bg-emerald-200/20 rounded-full blur-3xl pointer-events-none"></div>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 relative z-10">
        
        {/* Section Header */}
        <div className="text-center max-w-3xl mx-auto mb-16">
          <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-orange-100/90 border border-orange-200 text-[#ea580c] text-xs font-semibold uppercase tracking-widest mb-4 shadow-xs">
            <Sparkles className="w-3.5 h-3.5 text-[#ea580c]" />
            <span>OUR SOLUTION PIPELINE • SYSTEM ARCHITECTURE</span>
          </div>
          <h2 className="text-3xl sm:text-5xl font-bold text-stone-900 tracking-tight leading-tight">
            AI verifies the property. <br className="hidden sm:inline" />
            <span className="text-[#ea580c]">Blockchain preserves the trust.</span>
          </h2>
          <p className="mt-4 text-stone-600 text-base sm:text-lg leading-relaxed">
            From raw Indian-language land deeds to cryptographic proof of ownership on-chain, clearTitle automates property due diligence end-to-end.
          </p>
        </div>


        {/* SYSTEM DESIGN ARCHITECTURE CANVAS (GRAPH NODES, EDGES, ARROWHEADS & MOVING PACKETS) */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-center relative">

          {/* SVG SYSTEM DESIGN EDGES OVERLAY WITH ARROWHEADS & ANIMATED DATA PACKETS */}
          <svg className="absolute inset-0 w-full h-full pointer-events-none hidden lg:block z-0" viewBox="0 0 100 100" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">
            <defs>
              {/* Arrowhead Markers for System Design Edges */}
              <marker id="arrowOrange" viewBox="0 0 10 10" refX="6" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                <path d="M 0 0 L 10 5 L 0 10 z" fill="#ea580c" />
              </marker>

              <marker id="arrowEmerald" viewBox="0 0 10 10" refX="6" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                <path d="M 0 0 L 10 5 L 0 10 z" fill="#059669" />
              </marker>

              <linearGradient id="edgeGradOrange" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stopColor="#ea580c" stopOpacity="0.9" />
                <stop offset="100%" stopColor="#fbbf24" stopOpacity="1" />
              </linearGradient>

              <linearGradient id="edgeGradEmerald" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stopColor="#10b981" stopOpacity="0.9" />
                <stop offset="100%" stopColor="#059669" stopOpacity="1" />
              </linearGradient>
            </defs>

            {/* Edge 1: Sale Deeds Node ➔ Verification Engine (with Arrowhead & Moving Packet) */}
            <path 
              id="path-edge-1"
              d="M 27 22 C 32 22, 34 50, 39 50" 
              stroke="url(#edgeGradOrange)" 
              strokeWidth={activeDocIdx === 0 ? "3.5" : "2"} 
              fill="none" 
              markerEnd="url(#arrowOrange)"
              className={activeDocIdx === 0 ? "animate-electric-flow-fast" : "opacity-40"} 
            />
            {activeDocIdx === 0 && (
              <circle r="5" fill="#ea580c" className="shadow-lg">
                <animateMotion path="M 27 22 C 32 22, 34 50, 39 50" dur="1.4s" repeatCount="indefinite" />
              </circle>
            )}

            {/* Edge 2: Encumbrance Cert Node ➔ Verification Engine (with Arrowhead & Moving Packet) */}
            <path 
              id="path-edge-2"
              d="M 27 50 L 39 50" 
              stroke="url(#edgeGradOrange)" 
              strokeWidth={activeDocIdx === 1 ? "3.5" : "2"} 
              fill="none" 
              markerEnd="url(#arrowOrange)"
              className={activeDocIdx === 1 ? "animate-electric-flow-fast" : "opacity-40"} 
            />
            {activeDocIdx === 1 && (
              <circle r="5" fill="#ea580c" className="shadow-lg">
                <animateMotion path="M 27 50 L 39 50" dur="1.4s" repeatCount="indefinite" />
              </circle>
            )}

            {/* Edge 3: e-Khata Node ➔ Verification Engine (with Arrowhead & Moving Packet) */}
            <path 
              id="path-edge-3"
              d="M 27 78 C 32 78, 34 50, 39 50" 
              stroke="url(#edgeGradOrange)" 
              strokeWidth={activeDocIdx === 2 ? "3.5" : "2"} 
              fill="none" 
              markerEnd="url(#arrowOrange)"
              className={activeDocIdx === 2 ? "animate-electric-flow-fast" : "opacity-40"} 
            />
            {activeDocIdx === 2 && (
              <circle r="5" fill="#ea580c" className="shadow-lg">
                <animateMotion path="M 27 78 C 32 78, 34 50, 39 50" dur="1.4s" repeatCount="indefinite" />
              </circle>
            )}

            {/* Edge 4: Verification Engine ➔ Top Box (Blockchain Storage) */}
            <path 
              d="M 61 45 C 66 45, 68 18, 72 18" 
              stroke="url(#edgeGradEmerald)" 
              strokeWidth="2.5" 
              fill="none" 
              markerEnd="url(#arrowEmerald)"
              className="animate-electric-flow" 
            />
            <circle r="4" fill="#059669">
              <animateMotion path="M 61 45 C 66 45, 68 18, 72 18" dur="1.8s" repeatCount="indefinite" />
            </circle>

            {/* Edge 5: Verification Engine ➔ Bottom Box (Streamed Results) */}
            <path 
              d="M 61 55 C 66 55, 68 62, 72 62" 
              stroke="url(#edgeGradEmerald)" 
              strokeWidth="2.5" 
              fill="none" 
              markerEnd="url(#arrowEmerald)"
              className="animate-electric-flow-fast" 
            />
            <circle r="4" fill="#059669">
              <animateMotion path="M 61 55 C 66 55, 68 62, 72 62" dur="1.6s" repeatCount="indefinite" />
            </circle>
          </svg>


          {/* 1. LEFT COLUMN: 3 VERTICAL INPUT CARDS (SYSTEM DESIGN INPUT NODES) */}
          <div className="lg:col-span-3 space-y-4 z-10 flex flex-col justify-between">
            <div className="flex items-center justify-between mb-1 px-1">
              <span className="text-xs font-bold text-stone-900 uppercase tracking-wider">Input Documents</span>
              <span className="text-[10px] font-semibold text-emerald-800 bg-emerald-50 border border-emerald-200 px-2 py-0.5 rounded-full flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-600 animate-ping"></span>
                In Stream
              </span>
            </div>

            {/* 3 Vertically Stacked Input Cards */}
            <div className="space-y-4">
              {VERTICAL_INPUT_DOCS.map((doc, idx) => {
                const isActive = idx === activeDocIdx;
                return (
                  <div
                    key={doc.id}
                    onClick={() => setActiveDocIdx(idx)}
                    className={`bg-white rounded-2xl border transition-all cursor-pointer p-4 shadow-xs relative flex items-center gap-4 ${
                      isActive
                        ? 'border-[#ea580c] ring-4 ring-orange-500/20 shadow-xl scale-[1.03] z-20'
                        : 'border-stone-200 hover:border-stone-300 opacity-85 hover:opacity-100'
                    }`}
                  >
                    {/* Icon Box */}
                    <div className={`w-12 h-12 rounded-xl flex items-center justify-center flex-shrink-0 transition-all ${
                      isActive ? 'bg-orange-50 shadow-xs scale-110' : 'bg-stone-100'
                    }`}>
                      {getDocIcon(doc.icon)}
                    </div>

                    {/* Text Details */}
                    <div>
                      <h4 className="text-xs font-bold text-stone-900 leading-tight">
                        {doc.name}
                      </h4>
                      <p className="text-[10.5px] text-stone-500 font-medium mt-0.5">
                        {doc.sub}
                      </p>
                    </div>

                    {/* Right System Design Anchor Node Port */}
                    <div className={`ml-auto w-3.5 h-3.5 rounded-full border-2 transition-all flex items-center justify-center ${
                      isActive ? 'bg-orange-500 border-white ring-4 ring-orange-400/30 scale-125' : 'bg-stone-300 border-white'
                    }`}>
                      <div className="w-1 h-1 rounded-full bg-white"></div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>


          {/* 2. CENTER COLUMN: clearTitle VERIFICATION ENGINE CORE NODE */}
          <div className="lg:col-span-5 flex flex-col items-center justify-center z-10 px-1">
            <div className="w-full bg-[#090d16] text-white rounded-3xl p-6 border border-stone-800 shadow-2xl relative overflow-hidden flex flex-col items-center justify-center ring-1 ring-orange-500/30">
              
              {/* Radial Core Glow */}
              <div className="absolute inset-0 bg-[radial-gradient(circle_at_center,rgba(234,88,12,0.18)_0%,transparent_75%)] pointer-events-none"></div>

              {/* Vertical Laser Light Beam */}
              <div className="absolute inset-x-0 h-0.5 bg-gradient-to-r from-transparent via-amber-400 to-transparent shadow-[0_0_15px_#fbbf24] animate-scan-laser z-20"></div>

              {/* Left & Right Anchor Ports for System Design Connections */}
              <div className="absolute left-2 top-1/2 -translate-y-1/2 w-3 h-3 rounded-full bg-orange-500 border-2 border-white ring-4 ring-orange-500/40 z-30"></div>
              <div className="absolute right-2 top-1/2 -translate-y-1/2 w-3 h-3 rounded-full bg-emerald-500 border-2 border-white ring-4 ring-emerald-500/40 z-30"></div>

              {/* ROTATING ENGINE CORE */}
              <div className="relative my-4 flex items-center justify-center">
                <div className="w-36 h-36 rounded-full border-2 border-dashed border-orange-500/40 animate-scanner-spin flex items-center justify-center pointer-events-none"></div>
                <div className="absolute w-28 h-28 rounded-full border border-emerald-500/40 animate-pulse pointer-events-none"></div>

                {/* Central Diamond Core Branded with clearTitle */}
                <div className="absolute w-22 h-22 rounded-2xl bg-gradient-to-br from-[#ea580c] via-orange-600 to-amber-700 shadow-[0_0_35px_rgba(234,88,12,0.85)] flex flex-col items-center justify-center text-white text-center p-2 border border-white/30 transform rotate-45">
                  <div className="transform -rotate-45 flex flex-col items-center justify-center">
                    <span className="text-[13px] font-extrabold tracking-wider text-white font-mono drop-shadow-sm">
                      clearTitle
                    </span>
                    <span className="text-[8px] text-amber-200 uppercase tracking-widest font-mono mt-0.5">
                      Core Engine
                    </span>
                  </div>
                </div>
              </div>

              {/* Engine Status Banner */}
              <div className="bg-stone-900/90 rounded-2xl p-3 border border-stone-800 text-center relative z-10 w-full">
                <p className="text-xs font-semibold text-stone-200">
                  Auditing: <span className="text-orange-400 font-mono font-bold">{activeDoc.name}</span>
                </p>
                <p className="text-[10px] text-stone-400 mt-0.5">
                  Cross-matching legal clauses & generating cryptographic proof...
                </p>
              </div>

            </div>
          </div>


          {/* 3. RIGHT COLUMN: 2 OUTLET BOXES (BOX 1: BLOCKCHAIN STORAGE, BOX 2: STREAMED RESULTS) */}
          <div className="lg:col-span-4 space-y-4 z-10">
            
            {/* OUTLET BOX 1: BLOCKCHAIN STORAGE */}
            <div className="bg-white rounded-2xl border border-stone-200 shadow-md p-4 space-y-2 relative">
              {/* System Design Left Input Anchor Port */}
              <div className="absolute -left-1.5 top-1/2 -translate-y-1/2 w-3 h-3 rounded-full bg-emerald-500 border-2 border-white ring-2 ring-emerald-400/50"></div>

              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Database className="w-4.5 h-4.5 text-emerald-700" />
                  <h4 className="text-xs font-bold text-stone-900 uppercase tracking-wider">
                    Blockchain Storage
                  </h4>
                </div>
                <span className="text-[10px] font-extrabold text-emerald-800 bg-emerald-50 border border-emerald-200 px-2 py-0.5 rounded-md flex items-center gap-1">
                  <Lock className="w-3 h-3 text-emerald-700" />
                  TAMPER-PROOF
                </span>
              </div>

              <p className="text-[11px] text-stone-500 leading-tight">
                Document copy vaulted with cryptographic proof hash on-chain.
              </p>

              <div className="bg-stone-900 text-amber-300 rounded-xl p-2 font-mono text-[10px] flex items-center justify-between border border-stone-800">
                <span>Hash: 0x8f3b9c2d...4a21e91a</span>
                <Check className="w-3.5 h-3.5 text-emerald-400" />
              </div>
            </div>

            {/* OUTLET BOX 2: STREAMED RESULTS (MOTION STREAMED OUTPUT CARDS) */}
            <div className="bg-white rounded-2xl border border-stone-200 shadow-md p-4 space-y-3 relative">
              {/* System Design Left Input Anchor Port */}
              <div className="absolute -left-1.5 top-1/2 -translate-y-1/2 w-3 h-3 rounded-full bg-emerald-500 border-2 border-white ring-2 ring-emerald-400/50"></div>

              <div className="flex items-center justify-between">
                <span className="text-xs font-bold text-stone-900 uppercase tracking-wider">
                  Streamed Results
                </span>
                <span className="text-[10px] font-bold text-emerald-800 bg-emerald-50 border border-emerald-200 px-2 py-0.5 rounded-full flex items-center gap-1">
                  <CheckCircle2 className="w-3 h-3 text-emerald-600" />
                  Live Output
                </span>
              </div>

              {/* Streamed Result Cards List with Motion Animation */}
              <div className="space-y-2.5">
                {STREAMED_RESULT_ITEMS.map((res, idx) => {
                  const isRevealed = idx < revealedCount;
                  return (
                    <div
                      key={res.id}
                      className={`rounded-2xl p-3.5 border transition-all duration-500 flex items-center justify-between gap-3 ${
                        isRevealed
                          ? 'bg-white border-stone-200 shadow-xs animate-result-pop scale-100 opacity-100'
                          : 'bg-stone-50 border-stone-200 opacity-30 scale-95'
                      }`}
                    >
                      {/* Left: Green Circular Checkmark + Title & Subtitle */}
                      <div className="flex items-start gap-3">
                        <div className={`w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 mt-0.5 ${
                          isRevealed ? 'bg-emerald-50 border border-emerald-500 text-emerald-600' : 'bg-stone-100 text-stone-400'
                        }`}>
                          <Check className="w-3.5 h-3.5 stroke-[2.5]" />
                        </div>
                        <div>
                          <h5 className={`text-xs font-bold leading-tight ${isRevealed ? 'text-stone-900' : 'text-stone-400'}`}>
                            {res.title}
                          </h5>
                          <p className={`text-[10.5px] mt-0.5 leading-snug ${isRevealed ? 'text-stone-600 font-medium' : 'text-stone-400'}`}>
                            {res.detail}
                          </p>
                        </div>
                      </div>

                      {/* Right: Rounded Pill VERIFIED Badge */}
                      {isRevealed ? (
                        <span className="text-[10px] font-extrabold bg-emerald-100 text-[#064e3b] px-3 py-1 rounded-full whitespace-nowrap tracking-wider flex-shrink-0 animate-pulse">
                          VERIFIED
                        </span>
                      ) : (
                        <span className="text-[9px] font-medium text-stone-400 whitespace-nowrap">
                          PENDING
                        </span>
                      )}
                    </div>
                  );
                })}
              </div>

              {/* Overall Verification Banner */}
              <div className="bg-gradient-to-r from-emerald-700 to-teal-800 text-white rounded-xl p-3 shadow-sm flex items-center justify-between mt-1">
                <div>
                  <span className="text-[8px] font-bold uppercase tracking-wider text-emerald-200">Overall Due Diligence</span>
                  <h5 className="text-xs font-extrabold">100% TITLE CLEARANCE VERIFIED</h5>
                </div>
                <Shield className="w-6 h-6 text-emerald-100" />
              </div>
            </div>

          </div>

        </div>

      </div>
    </section>
  );
};
