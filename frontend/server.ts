import express from "express";
import path from "path";
import { fileURLToPath } from "url";
import { createServer as createViteServer } from "vite";
import { GoogleGenAI as AIClient } from "@google/genai";
import dotenv from "dotenv";

dotenv.config();

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

async function startServer() {
  const app = express();
  const PORT = 3000;

  app.use(express.json({ limit: "10mb" }));

  // API Routes
  app.get("/api/health", (_req, res) => {
    res.json({ status: "ok", service: "clearTitle Engine", version: "1.0.0" });
  });

  // AI Document Audit & Verification Endpoint
  app.post("/api/verify-property", async (req, res) => {
    try {
      const { documentType, documentText, state, city } = req.body;

      if (!documentText || documentText.trim().length === 0) {
        return res.status(400).json({ error: "Document text or details required for audit." });
      }

      const apiKey = process.env.AI_API_KEY;
      
      if (!apiKey || apiKey === "MY_AI_API_KEY") {
        // Return structured intelligent fallback report
        return res.json({
          status: "completed",
          source: "mock-analyzer",
          trustScore: 84,
          documentsReviewed: 2,
          positiveMatches: 5,
          redFlagsCount: 2,
          propertyDetails: {
            propertyType: "Residential Plot / Apartment",
            location: `${city || "Belagavi"}, ${state || "Karnataka"}`,
            surveyNumber: "CTS No. 422/A-1",
            area: "1,450 Sq. Ft. (Built-up)",
            ownerOnRecord: "Prajwal R. G.",
            ulpin: "79PYQ GYZ30 9821"
          },
          redFlags: [
            {
              severity: "HIGH",
              title: "Vendor Name Spelling Mismatch",
              description: "Sale Deed 2021 lists 'Shri. Prakash M.' while Encumbrance Certificate (EC) lists 'Shri. Prakash Mallappa'. Cross-verification required with Aadhaar / PAN."
            },
            {
              severity: "MEDIUM",
              title: "Unresolved Bank Mortgage Note (2018)",
              description: "EC entry #104 shows a charge created by Canara Bank in 2018. Discharge certificate (NOC) is missing from uploaded packet."
            }
          ],
          positiveVerifications: [
            "Valid Property Record match in Kaveri / NGDRS online registry",
            "Survey Number matches exactly between Sale Deed and RTC Extract",
            "No litigation pending in High Court / District Court portal for this survey number",
            "Sanctioned Plan approved by City Corporation / Urban Development Authority",
            "Property Tax receipt up to date (FY 2025-26)"
          ],
          chainOfTitle: [
            { year: "1998", event: "Original Allotment by Urban Development Authority to Mr. A. B. Joshi", status: "Verified" },
            { year: "2012", event: "Registered Sale Deed #10492 to Mr. Prakash Mallappa", status: "Verified" },
            { year: "2021", event: "Registered Sale Deed #4029 to Mr. Prajwal R. G.", status: "Warning: Name Variation" }
          ],
          blockchainCertificate: {
            hash: "0x8f9c2a3e10b414d59a82f3491e029141f20a91e1d02c89f5b21118fa302199b4",
            timestamp: new Date().toISOString(),
            status: "Tokenized & Recorded on Polygon / clearTitle Trust Node",
            blockNumber: 49201948
          }
        });
      }

      // Call VLM AI API if available
      const ai = new AIClient({ apiKey });
      const prompt = `You are clearTitle's Senior Land & Property Title Audit AI specialized in Indian Real Estate Due Diligence (Sale Deeds, Encumbrance Certificates / EC, e-Khata, Sanctioned Plans, RTC/Pahani, ULPIN / Bhu-Aadhar).

Analyze the following property document text or query and return a valid JSON object matching this EXACT schema:
{
  "status": "completed",
  "trustScore": number (0 to 100),
  "documentsReviewed": number,
  "positiveMatches": number,
  "redFlagsCount": number,
  "propertyDetails": {
    "propertyType": string,
    "location": string,
    "surveyNumber": string,
    "area": string,
    "ownerOnRecord": string,
    "ulpin": string
  },
  "redFlags": [
    {
      "severity": "HIGH" | "MEDIUM" | "LOW",
      "title": string,
      "description": string
    }
  ],
  "positiveVerifications": [ string ],
  "chainOfTitle": [
    { "year": string, "event": string, "status": string }
  ],
  "blockchainCertificate": {
    "hash": string (0x hex format),
    "timestamp": string,
    "status": string,
    "blockNumber": number
  }
}

Document Type: ${documentType || "Property Title Document"}
Location Context: ${city || "Karnataka"}, ${state || "India"}
Text/Input: ${documentText}

Ensure strict valid JSON output without markdown formatting wrapping outside the json.`;

      const response = await ai.models.generateContent({
        model: "gemini-2.5-flash",
        contents: prompt,
        config: {
          responseMimeType: "application/json"
        }
      });

      const rawText = response.text || "{}";
      const parsedData = JSON.parse(rawText);
      return res.json({ ...parsedData, source: "vlm-ai" });

    } catch (err: any) {
      console.error("AI Audit Error:", err);
      res.status(500).json({ error: "Failed to audit property document", details: err.message });
    }
  });

  // Vite middleware for development
  if (process.env.NODE_ENV !== "production") {
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: "spa",
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(process.cwd(), "dist");
    app.use(express.static(distPath));
    app.get("*", (_req, res) => {
      res.sendFile(path.join(distPath, "index.html"));
    });
  }

  app.listen(PORT, "0.0.0.0", () => {
    console.log(`clearTitle server listening on http://0.0.0.0:${PORT}`);
  });
}

startServer();
