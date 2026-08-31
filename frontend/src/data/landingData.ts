export const PROBLEM_METRICS = [
  {
    value: '47%',
    label: 'Title disputes in Indian courts',
    description: 'Nearly half of all civil litigation in India stems from unclear or disputed property titles.',
  },
{
    value: '20+ years',
    label: 'Ownership history traced per property',
    description:
      'Every ownership transfer and encumbrance entry is traced back across decades of records, not just the last sale deed.',
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
      'clearTitle is an AI-powered property title verification platform built for Karnataka. Upload your property documents — Sale Deed, Encumbrance Certificate, and more — and get a clear verdict on whether the title is clean, in minutes instead of weeks.',
  },
  {
    question: 'Which documents can I upload?',
    answer:
      'Sale Deeds, Gift Deeds, Partition Deeds, Encumbrance Certificates, RTC/Pahani extracts, Khata certificates, Property Tax receipts, Mutation records and more — read automatically in Kannada and English.',
  },
  {
    question: 'How accurate is the AI verification?',
    answer:
      'Every document is read and cross-checked against your others, with the reasoning behind every verdict shown in plain language. clearTitle accelerates the process and flags issues far faster than manual review — but a final manual check is still needed before you act on the outcome.',
  },
  {
    question: 'Is my data safe?',
    answer:
      'Yes. Your documents are encrypted in transit and at rest, and never shared with third parties. Guest audits stay anonymous until you sign in.',
  },
  {
    question: 'Can I re-run verification after uploading more documents?',
    answer:
      'Yes. Add documents, replace one, or re-run the verification any time — the entire audit re-checks against the updated set.',
  },
  {
    question: 'What does the verification report show?',
    answer:
      'A full title chain showing every ownership transfer, a document-by-document cross-check, red flags ranked by severity, and a final verdict in plain language.',
  },
  {
    question: 'How much does it cost?',
    answer:
      'Simple pay-per-audit pricing — no subscription, no surprise fees. You only pay when you run a verification.',
    link: { label: 'See pricing plans', to: '/pricing' },
  },
  {
    question: 'Do I need to be a lawyer to use clearTitle?',
    answer:
      'Not at all. It\'s built for property buyers, lawyers, banks and anyone doing property due diligence. Results are delivered in plain English.',
  },
];
