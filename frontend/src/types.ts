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

export interface FaqItem {
  question: string;
  answer: string;
}
