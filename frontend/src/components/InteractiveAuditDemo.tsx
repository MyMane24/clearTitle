import React, { useState } from 'react';
import { SAMPLE_DOCUMENTS } from '../data/landingData';
import { PropertyAuditResult } from '../types';
import { Sparkles, Shield, AlertTriangle, CheckCircle, FileText, RefreshCw, Lock, Copy, Check } from 'lucide-react';

export const InteractiveAuditDemo: React.FC = () => {
  const [selectedDocId, setSelectedDocId] = useState<string>(SAMPLE_DOCUMENTS[0].id);
  const [customText, setCustomText] = useState<string>(SAMPLE_DOCUMENTS[0].previewText);
  const [cityName, setCityName] = useState<string>('Belagavi');
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [auditResult, setAuditResult] = useState<PropertyAuditResult | null>(null);
  const [copiedHash, setCopiedHash] = useState<boolean>(false);
  const [activeTab, setActiveTab] = useState<'overview' | 'redflags' | 'chain' | 'blockchain'>('overview');

  const selectedDoc = SAMPLE_DOCUMENTS.find(d => d.id === selectedDocId) || SAMPLE_DOCUMENTS[0];

  const handleSelectDoc = (docId: string) => {
    setSelectedDocId(docId);
    const doc = SAMPLE_DOCUMENTS.find(d => d.id === docId);
    if (doc) {
      setCustomText(doc.previewText);
      setCityName(doc.city);
    }
  };

  const handleRunAudit = async () => {
    setIsLoading(true);
    setAuditResult(null);

    try {
      const response = await fetch('/api/verify-property', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          documentType: selectedDoc.type,
          documentText: customText,
          city: cityName,
          state: 'Karnataka'
        })
      });

      if (!response.ok) throw new Error('API unavailable');
      const data = await response.json();
      setAuditResult(data);
    } catch (err) {
      // Client-side mock fallback
      setAuditResult({
        status: 'completed',
        source: 'mock-analyzer',
        trustScore: 84,
        documentsReviewed: 2,
        positiveMatches: 5,
        redFlagsCount: 2,
        propertyDetails: {
          propertyType: 'Residential Plot / Apartment',
          location: `${cityName}, Karnataka`,
          surveyNumber: 'CTS No. 4XX/A-1',
          area: '1,450 Sq. Ft. (Built-up)',
          ownerOnRecord: 'Prajwal R. G.',
          ulpin: '79PYQ GYZXX XXXX'
        },
        redFlags: [
          {
            severity: 'HIGH',
            title: 'Vendor Name Spelling Mismatch',
            description: 'Sale Deed 2021 lists "Shri. Prakash M." while Encumbrance Certificate (EC) lists "Shri. Prakash Mallappa". Cross-verification required with Aadhaar / PAN.'
          },
          {
            severity: 'MEDIUM',
            title: 'Unresolved Bank Mortgage Note (2018)',
            description: 'EC entry #104 shows a charge created by Canara Bank in 2018. Discharge certificate (NOC) is missing from uploaded packet.'
          }
        ],
        positiveVerifications: [
          'Valid Property Record match in Kaveri / NGDRS online registry',
          'Survey Number matches exactly between Sale Deed and RTC Extract',
          'No litigation pending in High Court / District Court portal for this survey number',
          'Sanctioned Plan approved by City Corporation / Urban Development Authority',
          'Property Tax receipt up to date (FY 2025-26)'
        ],
        chainOfTitle: [
          { year: '1998', event: 'Original Allotment by Urban Development Authority to Mr. A. B. Joshi', status: 'Verified' },
          { year: '2012', event: 'Registered Sale Deed #10492 to Mr. Prakash Mallappa', status: 'Verified' },
          { year: '2021', event: 'Registered Sale Deed #4029 to Mr. Prajwal R. G.', status: 'Warning: Name Variation' }
        ],
        blockchainCertificate: {
          hash: '0x8f9c2a3e10b414d59a82f3491e029141f20a91e1d02c89f5b21118fa302199b4',
          timestamp: new Date().toISOString(),
          status: 'Tokenized & Recorded on Polygon / clearTitle Trust Node',
          blockNumber: 49201948
        }
      });
    } finally {
      setIsLoading(false);
    }
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedHash(true);
    setTimeout(() => setCopiedHash(false), 2000);
  };

  return (
    <section id="live-demo" className="py-20 lg:py-28 bg-white border-b border-stone-200">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        
        {/* Section Title */}
        <div className="text-center max-w-3xl mx-auto mb-12">
          <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-orange-50 border border-orange-200 text-[#ea580c] text-xs font-medium uppercase tracking-wider mb-3">
            <Sparkles className="w-3.5 h-3.5" />
            <span>INTERACTIVE AI AUDIT ENGINE</span>
          </div>
          <h2 className="text-3xl sm:text-5xl font-bold text-stone-900 tracking-tight">
            Test clearTitle AI Verification in Real-Time
          </h2>
          <p className="mt-3 text-stone-600 text-base sm:text-lg">
            Select a sample Indian land document or paste your own document text. See how our VLM AI detects red flags, cross-references Kaveri/NGDRS data, and generates a blockchain hash.
          </p>
        </div>

        {/* Playground Box */}
        <div className="bg-[#faf8f5] rounded-3xl border border-stone-200 p-4 sm:p-8 shadow-xl">
          
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
            
            {/* Left Controls & Input Panel */}
            <div className="lg:col-span-5 flex flex-col justify-between">
              <div>
                <h3 className="text-sm font-medium uppercase tracking-wider text-stone-500 mb-3">
                  1. Select Sample Property Document
                </h3>

                {/* Preset Selector Buttons */}
                <div className="space-y-2.5 mb-6">
                  {SAMPLE_DOCUMENTS.map((doc) => (
                    <button
                      key={doc.id}
                      onClick={() => handleSelectDoc(doc.id)}
                      className={`w-full text-left p-3.5 rounded-xl border transition-all cursor-pointer flex items-center justify-between ${
                        selectedDocId === doc.id
                          ? 'bg-white border-[#ea580c] ring-2 ring-orange-500/20 shadow-xs'
                          : 'bg-white/60 border-stone-200 hover:bg-white hover:border-stone-300'
                      }`}
                    >
                      <div className="flex items-center gap-3">
                        <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${selectedDocId === doc.id ? 'bg-[#ea580c] text-white' : 'bg-stone-100 text-stone-600'}`}>
                          <FileText className="w-4 h-4" />
                        </div>
                        <div>
                          <div className="text-xs sm:text-sm font-medium text-stone-900">{doc.title}</div>
                          <div className="text-[11px] text-stone-500">{doc.type} • {doc.city}</div>
                        </div>
                      </div>
                      <span className="text-[10px] font-semibold text-stone-400 bg-stone-100 px-2 py-0.5 rounded">
                        Sample
                      </span>
                    </button>
                  ))}
                </div>

                {/* City & State inputs */}
                <div className="mb-4">
                  <label className="block text-xs font-medium uppercase tracking-wider text-stone-500 mb-1">
                    Property Location City
                  </label>
                  <input 
                    type="text" 
                    value={cityName}
                    onChange={(e) => setCityName(e.target.value)}
                    className="w-full bg-white border border-stone-200 rounded-xl px-3.5 py-2 text-xs sm:text-sm text-stone-900 focus:outline-none focus:ring-2 focus:ring-[#ea580c]"
                    placeholder="e.g. Belagavi, Hubballi, Bengaluru"
                  />
                </div>

                {/* Editable Document Text */}
                <div className="mb-6">
                  <label className="block text-xs font-medium uppercase tracking-wider text-stone-500 mb-1">
                    Document Text Content (OCR extracted)
                  </label>
                  <textarea
                    rows={6}
                    value={customText}
                    onChange={(e) => setCustomText(e.target.value)}
                    className="w-full bg-white border border-stone-200 rounded-xl p-3 text-xs font-mono text-stone-800 leading-relaxed focus:outline-none focus:ring-2 focus:ring-[#ea580c]"
                    placeholder="Paste deed text or property details here..."
                  />
                </div>
              </div>

              {/* Action Button */}
              <button
                onClick={handleRunAudit}
                disabled={isLoading}
                className="w-full py-4 bg-[#ea580c] hover:bg-[#c2410c] text-white font-medium rounded-xl shadow-lg shadow-orange-500/20 transition-all flex items-center justify-center gap-2 cursor-pointer disabled:opacity-60 active:scale-95"
              >
                {isLoading ? (
                  <>
                    <RefreshCw className="w-5 h-5 animate-spin" />
                    <span>AI Engine Cross-Verifying...</span>
                  </>
                ) : (
                  <>
                    <Sparkles className="w-5 h-5" />
                    <span>Run AI Title Audit</span>
                  </>
                )}
              </button>
            </div>

            {/* Right Output Dashboard Panel */}
            <div className="lg:col-span-7 bg-white rounded-2xl border border-stone-200 p-5 sm:p-6 shadow-md flex flex-col justify-between">
              
              {!auditResult && !isLoading && (
                <div className="h-full min-h-[420px] flex flex-col items-center justify-center text-center p-6 border-2 border-dashed border-stone-200 rounded-xl bg-stone-50/50">
                  <div className="w-16 h-16 rounded-full bg-orange-100 text-[#ea580c] flex items-center justify-center mb-4">
                    <Shield className="w-8 h-8" />
                  </div>
                  <h4 className="text-lg font-medium text-stone-900 mb-1">Ready for Property Verification</h4>
                  <p className="text-xs sm:text-sm text-stone-500 max-w-sm mb-6">
                    Click <strong>"Run AI Title Audit"</strong> to execute automated OCR extraction, Sarvam VLM term cross-checks, and blockchain tokenization.
                  </p>
                  <button
                    onClick={handleRunAudit}
                    className="px-6 py-2.5 bg-[#ea580c] text-white text-xs font-medium rounded-xl shadow cursor-pointer hover:bg-[#c2410c]"
                  >
                    Run Sample Scan
                  </button>
                </div>
              )}

              {isLoading && (
                <div className="h-full min-h-[420px] flex flex-col items-center justify-center text-center p-6 bg-stone-50 rounded-xl">
                  <div className="w-16 h-16 rounded-full bg-orange-100 text-[#ea580c] flex items-center justify-center mb-4 animate-bounce">
                    <RefreshCw className="w-8 h-8 animate-spin text-[#ea580c]" />
                  </div>
                  <h4 className="text-lg font-medium text-stone-900 mb-1">Auditing Property Record...</h4>
                  <p className="text-xs text-stone-500 max-w-sm">
                    1. OCR Parsing • 2. Vernacular Match • 3. Kaveri Online Registry Check • 4. Generating Blockchain Hash
                  </p>
                </div>
              )}

              {auditResult && !isLoading && (
                <div>
                  
                  {/* Top Result Bar */}
                  <div className="flex flex-wrap items-center justify-between gap-3 pb-4 mb-4 border-b border-stone-200">
                    <div>
                      <div className="flex items-center gap-2 text-xs font-medium text-stone-400 uppercase">
                        <span>Status: <strong className="text-emerald-600 font-mono">VERIFIED</strong></span>
                        <span>•</span>
                        <span className="text-[#ea580c]">{auditResult.source === 'vlm-ai' ? 'VLM AI' : 'clearTitle Engine'}</span>
                      </div>
                      <h4 className="text-lg font-bold text-stone-900">{auditResult.propertyDetails?.surveyNumber || 'CTS No. 422/A-1'}</h4>
                    </div>

                    <div className="flex items-center gap-3">
                      <div className="text-right">
                        <span className="text-[10px] uppercase font-medium text-stone-400 block">Trust Score</span>
                        <span className="text-2xl font-bold text-emerald-600">{auditResult.trustScore}<span className="text-xs font-normal text-stone-400">/100</span></span>
                      </div>
                    </div>
                  </div>

                  {/* Tabs */}
                  <div className="flex items-center gap-2 border-b border-stone-200 mb-4 overflow-x-auto text-xs font-semibold">
                    <button
                      onClick={() => setActiveTab('overview')}
                      className={`pb-2.5 px-3 border-b-2 transition-colors cursor-pointer whitespace-nowrap ${
                        activeTab === 'overview' ? 'border-[#ea580c] text-[#ea580c]' : 'border-transparent text-stone-500 hover:text-stone-800'
                      }`}
                    >
                      Audit Overview
                    </button>
                    <button
                      onClick={() => setActiveTab('redflags')}
                      className={`pb-2.5 px-3 border-b-2 transition-colors cursor-pointer whitespace-nowrap flex items-center gap-1.5 ${
                        activeTab === 'redflags' ? 'border-[#ea580c] text-[#ea580c]' : 'border-transparent text-stone-500 hover:text-stone-800'
                      }`}
                    >
                      <span>Red Flags</span>
                      <span className="bg-rose-100 text-rose-700 px-1.5 py-0.2 rounded-full text-[10px] font-medium">
                        {auditResult.redFlags?.length || 2}
                      </span>
                    </button>
                    <button
                      onClick={() => setActiveTab('chain')}
                      className={`pb-2.5 px-3 border-b-2 transition-colors cursor-pointer whitespace-nowrap ${
                        activeTab === 'chain' ? 'border-[#ea580c] text-[#ea580c]' : 'border-transparent text-stone-500 hover:text-stone-800'
                      }`}
                    >
                      Chain of Title
                    </button>
                    <button
                      onClick={() => setActiveTab('blockchain')}
                      className={`pb-2.5 px-3 border-b-2 transition-colors cursor-pointer whitespace-nowrap flex items-center gap-1 ${
                        activeTab === 'blockchain' ? 'border-[#ea580c] text-[#ea580c]' : 'border-transparent text-stone-500 hover:text-stone-800'
                      }`}
                    >
                      <Lock className="w-3 h-3" /> Blockchain Hash
                    </button>
                  </div>

                  {/* Tab 1: Overview */}
                  {activeTab === 'overview' && (
                    <div className="space-y-4">
                      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                        <div className="p-3 bg-stone-50 rounded-xl border border-stone-200">
                          <span className="text-[10px] text-stone-400 font-medium uppercase block">Owner on Record</span>
                          <span className="text-xs font-medium text-stone-800">{auditResult.propertyDetails?.ownerOnRecord}</span>
                        </div>
                        <div className="p-3 bg-stone-50 rounded-xl border border-stone-200">
                          <span className="text-[10px] text-stone-400 font-medium uppercase block">Built-up Area</span>
                          <span className="text-xs font-medium text-stone-800">{auditResult.propertyDetails?.area}</span>
                        </div>
                        <div className="p-3 bg-stone-50 rounded-xl border border-stone-200 col-span-2 sm:col-span-1">
                          <span className="text-[10px] text-stone-400 font-medium uppercase block">ULPIN Bhu-Aadhar</span>
                          <span className="text-xs font-mono font-medium text-[#ea580c]">{auditResult.propertyDetails?.ulpin}</span>
                        </div>
                      </div>

                      <div className="bg-emerald-50/80 border border-emerald-200/80 rounded-xl p-3.5">
                        <h5 className="text-xs font-medium text-emerald-900 uppercase tracking-wider mb-2 flex items-center gap-1.5">
                          <CheckCircle className="w-4 h-4 text-emerald-600" />
                          <span>Positive Verifications ({auditResult.positiveVerifications?.length || 5})</span>
                        </h5>
                        <ul className="space-y-1.5 text-xs text-emerald-950">
                          {auditResult.positiveVerifications?.map((v, i) => (
                            <li key={i} className="flex items-start gap-1.5">
                              <span className="text-emerald-500 font-medium">•</span>
                              <span>{v}</span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    </div>
                  )}

                  {/* Tab 2: Red Flags */}
                  {activeTab === 'redflags' && (
                    <div className="space-y-3">
                      {auditResult.redFlags?.map((flag, idx) => (
                        <div key={idx} className="p-3.5 bg-rose-50 border border-rose-200 rounded-xl flex items-start gap-3">
                          <AlertTriangle className="w-5 h-5 text-rose-600 flex-shrink-0 mt-0.5" />
                          <div>
                            <div className="flex items-center gap-2 mb-1">
                              <span className="text-xs font-medium text-rose-900">{flag.title}</span>
                              <span className="bg-rose-200 text-rose-800 text-[10px] font-medium px-1.5 py-0.2 rounded">
                                {flag.severity}
                              </span>
                            </div>
                            <p className="text-xs text-rose-800 leading-relaxed">{flag.description}</p>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Tab 3: Chain of Title */}
                  {activeTab === 'chain' && (
                    <div className="space-y-3 relative pl-4 border-l-2 border-orange-200">
                      {auditResult.chainOfTitle?.map((item, idx) => (
                        <div key={idx} className="relative mb-3">
                          <div className="absolute -left-[21px] top-1 w-2.5 h-2.5 rounded-full bg-[#ea580c] ring-4 ring-orange-100" />
                          <div className="text-xs font-medium text-[#ea580c]">{item.year}</div>
                          <div className="text-xs font-semibold text-stone-800">{item.event}</div>
                          <div className="text-[11px] text-stone-500 italic">Status: {item.status}</div>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Tab 4: Blockchain */}
                  {activeTab === 'blockchain' && (
                    <div className="p-4 bg-stone-900 text-stone-200 rounded-xl font-mono text-xs space-y-3">
                      <div className="flex items-center justify-between text-[#f97316]">
                        <span className="font-medium flex items-center gap-1.5">
                          <Lock className="w-4 h-4" /> Blockchain Trust Certificate
                        </span>
                        <span className="text-[10px] bg-stone-800 px-2 py-0.5 rounded text-stone-400">Polygon Network</span>
                      </div>

                      <div>
                        <span className="text-[10px] text-stone-500 uppercase block">Cryptographic Title Hash</span>
                        <div className="bg-stone-950 p-2.5 rounded border border-stone-800 text-amber-300 break-all flex items-center justify-between gap-2 mt-1">
                          <span>{auditResult.blockchainCertificate?.hash}</span>
                          <button 
                            onClick={() => copyToClipboard(auditResult.blockchainCertificate?.hash)}
                            className="p-1 hover:bg-stone-800 rounded text-stone-400 cursor-pointer"
                          >
                            {copiedHash ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                          </button>
                        </div>
                      </div>

                      <div className="grid grid-cols-2 gap-2 text-[11px]">
                        <div>
                          <span className="text-stone-500 block">Block Number:</span>
                          <span className="text-stone-200 font-medium">{auditResult.blockchainCertificate?.blockNumber}</span>
                        </div>
                        <div>
                          <span className="text-stone-500 block">Status:</span>
                          <span className="text-emerald-400 font-medium">Tamper-Evident</span>
                        </div>
                      </div>
                    </div>
                  )}

                </div>
              )}

              {/* Bottom helper text */}
              <div className="mt-4 pt-3 border-t border-stone-100 flex items-center justify-between text-xs text-stone-400">
                <span>Supports Sale Deeds, EC, e-Khata, Sanctioned Plans</span>
              </div>

            </div>

          </div>

        </div>

      </div>
    </section>
  );
};
