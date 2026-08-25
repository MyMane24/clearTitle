export const PROBLEM_METRICS = [
  {
    value: '47%',
    label: 'Title disputes in Indian courts',
    description: 'Nearly half of all civil litigation in India stems from unclear or disputed property titles.',
  },
  {
    value: '6+',
    label: 'Portals checked per verification',
    description: 'Buyers and lawyers manually cross-check Kaveri, NCAL, sub-registrar, and municipal portals.',
  },
  {
    value: '14 days',
    label: 'Average manual verification time',
    description: 'Traditional due diligence takes weeks of site visits, document collection, and manual comparison.',
  },
];

export const OLD_WAY_VS_CLEARTITLE = {
  oldWay: [
    'Visit sub-registrar office physically for EC printout',
    'Manually compare Sale Deed and EC fields in separate PDFs',
    'Hire a lawyer to read Kannada documents line by line',
    'Cross-check property tax records on a different municipal portal',
    'Track title chain across 20+ years of encumbrance entries by hand',
    'No audit trail — trust the advocate\'s verbal assurance',
  ],
  clearTitleWay: [
    'Upload PDFs once — AI extracts and cross-verifies every field in seconds',
    'Title chain built automatically from EC ledger entries',
    'Kannada + English OCR with regional document understanding',
    'Property identifiers matched across Sale Deed, EC, and Tax records',
    'Red flags surfaced with severity scores and plain-language explanations',
    'Full audit report with timestamps, hashes, and case history',
  ],
};

export const SAMPLE_DOCUMENTS = [
  {
    id: 'sale-deed',
    title: 'Sale Deed — Residential Plot',
    type: 'SALE_DEED',
    city: 'Belagavi',
    previewText:
      'Registered Sale Deed No. 4029 of 2021. This Deed of Sale is made on this 15th day of March, 2021 at Belagavi. Between: Smt. Kamalabai W/o Shri Ramesh M. G., aged about 58 years, occupier of property bearing CTS No. 4XX/A-1, situated at Sadashiv Nagar, Belagavi (hereinafter called the VENDOR) of the ONE PART... Property measuring 1,450 sq. ft. built-up area, residential apartment on 2nd floor of "Ganesh Enclave", bearing CTS No. 4XX/A-1, Survey No. 663/1, Block No. 12, Unit No. 7, Sadashiv Nagar, Belagavi 590001. Consideration of Rs. 45,00,000 (Rupees Forty-Five Lakhs Only) paid by cheque.',
  },
  {
    id: 'ec',
    title: 'Encumbrance Certificate',
    type: 'ENCUMBRANCE_CERTIFICATE',
    city: 'Belagavi',
    previewText:
      'Encumbrance Certificate for Property bearing CTS No. 4XX/A-1, Survey No. 663/1, Block 12, Sadashiv Nagar, Belagavi. Period of search: 01/01/2000 to 31/12/2024. Transaction 1: Registered Sale Deed No. 10492 dated 22/06/2012 between Shri Prakash Mallappa and Smt. Kamalabai. Transaction 2: Registered Sale Deed No. 4029 dated 15/03/2021 between Smt. Kamalabai and Shri Prajwal R. G. Transaction 3: Home Loan Mortgage with Canara Bank, Charge Created 10/08/2018, Rs. 35,00,000. Total Transactions Found: 3.',
  },
  {
    id: 'rtc',
    title: 'RTC Extract (Pahani)',
    type: 'RTC_PAHANI',
    city: 'Belagavi',
    previewText:
      'Rights, Tenancy and Crops (RTC) Extract — Khata No. 12/45, Survey No. 663/1, Village: Sadashiv Nagar, Hobli: Belagavi, Taluk: Belagavi, District: Belagavi. Land Type: Non-Agricultural (NA). Classification: Residential. Extent: 1,450 sq. ft. (0.033 acres). Owner of Record: Smt. Kamalabai w/o Shri Ramesh M. G. Land is in single possession. No encumbrance noted in revenue records. Latest Property Tax paid: FY 2025-26, Receipt No. PT/2025/44821.',
  },
  {
    id: 'khata',
    title: 'Khata Certificate',
    type: 'KHATA',
    city: 'Belagavi',
    previewText:
      'Municipal Khata Certificate — BBMP/Belagavi City Corporation. Khata No. 12/45, Ward No. 32, Property Address: No. 7, Ganesh Enclave, Sadashiv Nagar, Belagavi 590001. CTS No. 4XX/A-1, Survey No. 663/1. Owner: Prajwal R. G. (Transferred from Kamalabai w/o Ramesh M. G. on 15/03/2021). Property Type: Residential Apartment. Built-up Area: 1,450 sq. ft. Annual Value: Rs. 1,80,000. Tax Paid Up To: 2025-26. Outstanding: Nil.',
  },
];

export const FAQ_ITEMS = [
  {
    question: 'What is clearTitle?',
    answer:
      'clearTitle is an AI-powered property title verification platform built for Karnataka. Upload your property documents (Sale Deed, Encumbrance Certificate, etc.) and our AI extracts structured data, builds a title chain, and cross-verifies every field — delivering a clear verdict in minutes, not weeks.',
  },
  {
    question: 'Which documents can I upload?',
    answer:
      'We support Sale Deeds, Gift Deeds, Partition Deeds, Encumbrance Certificates, Property Register Cards, Khata certificates, Property Tax receipts, Mutation records, RTC/Pahani extracts, and more. The platform recognizes 15+ Karnataka-specific document types automatically.',
  },
  {
    question: 'How accurate is the AI verification?',
    answer:
      'Our AI uses Sarvam Vision OCR for high-accuracy Kannada + English text extraction, followed by Gemini 2.5 Flash for structured field extraction and cross-document verification. Every field comparison is explainable — you see exactly what matched, what didn\'t, and why.',
  },
  {
    question: 'Is my data safe?',
    answer:
      'Your documents are processed securely and stored encrypted. We do not share your data with third parties. Guest cases are anonymous until you sign in and link them to your account. All API keys and credentials are stored in encrypted environment variables.',
  },
  {
    question: 'Can I re-run verification after uploading more documents?',
    answer:
      'Yes. You can add more documents to an existing case, replace failed documents, or re-trigger the verification pass at any time. The title chain and cross-document verification will re-run with the updated document set.',
  },
  {
    question: 'What does the verification report show?',
    answer:
      'The report includes a title chain timeline (showing every ownership transfer from the EC ledger), a field-by-field cross-check between your Sale Deed and EC, red flags with severity levels, and a final VERIFIED / NOT_VERIFIED verdict with a plain-language summary.',
  },
  {
    question: 'How much does it cost?',
    answer:
      'Each verification run costs approximately ₹3–10 in AI processing fees (varies by document size and Kannada text volume). This covers OCR, field extraction, title chain construction, and cross-document verification.',
  },
  {
    question: 'Do I need to be a lawyer to use clearTitle?',
    answer:
      'Not at all. clearTitle is designed for property buyers, lawyers, banks, and anyone involved in property due diligence. The results are presented in plain English with clear explanations — no legal jargon.',
  },
];
