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
