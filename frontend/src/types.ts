export interface PropertyAuditDetails {
  propertyType: string;
  location: string;
  surveyNumber: string;
  area: string;
  ownerOnRecord: string;
  ulpin: string;
}

export interface RedFlagItem {
  severity: 'HIGH' | 'MEDIUM' | 'LOW';
  title: string;
  description: string;
}

export interface ChainOfTitleEvent {
  year: string;
  event: string;
  status: string;
}

export interface BlockchainCertificate {
  hash: string;
  timestamp: string;
  status: string;
  blockNumber: number;
}

export interface PropertyAuditResult {
  status: string;
  source?: string;
  trustScore: number;
  documentsReviewed: number;
  positiveMatches: number;
  redFlagsCount: number;
  propertyDetails: PropertyAuditDetails;
  redFlags: RedFlagItem[];
  positiveVerifications: string[];
  chainOfTitle: ChainOfTitleEvent[];
  blockchainCertificate: BlockchainCertificate;
}

export interface PricingPlan {
  id: string;
  name: string;
  badge?: string;
  price: string;
  unit: string;
  description: string;
  features: string[];
  cta: string;
  isPopular?: boolean;
}

export interface MarketSegment {
  id: string;
  number: string;
  title: string;
  subtitle: string;
  audience: string;
}

export interface CompetitorItem {
  name: string;
  x: number; // 0 to 100 (Slow to Fast)
  y: number; // 0 to 100 (Basic to Full Title)
  isClearTitle?: boolean;
  category: string;
}

export interface FaqItem {
  question: string;
  answer: string;
}
