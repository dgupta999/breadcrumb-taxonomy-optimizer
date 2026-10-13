import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "./index.css";
import Layout from "./components/Layout";
import AuthGate from "./components/AuthGate";
import { ProjectProvider } from "./lib/project";
import Dashboard from "./pages/Dashboard";
import Projects from "./pages/Projects";
import UploadPage from "./pages/Upload";
import SrpMapping from "./pages/SrpMapping";
import AuditPage from "./pages/Audit";
import CrawlPage from "./pages/Crawl";
import CompetitorTaxonomy from "./pages/CompetitorTaxonomy";
import CompetitorMappingPage from "./pages/CompetitorMapping";
import GapsPage from "./pages/Gaps";
import ParentChildGaps from "./pages/ParentChild";
import SynonymsPage from "./pages/Synonyms";
import RulesPage from "./pages/Rules";
import ReviewQueue from "./pages/ReviewQueue";
import ExportsPage from "./pages/Exports";
import HistoryPage from "./pages/History";

const qc = new QueryClient({ defaultOptions: { queries: { refetchOnWindowFocus: false, retry: 1 } } });

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={qc}>
      <AuthGate>
      <ProjectProvider>
        <BrowserRouter>
          <Routes>
            <Route element={<Layout />}>
              <Route index element={<Dashboard />} />
              <Route path="projects" element={<Projects />} />
              <Route path="upload" element={<UploadPage />} />
              <Route path="srp" element={<SrpMapping />} />
              <Route path="audit" element={<AuditPage />} />
              <Route path="crawl" element={<CrawlPage />} />
              <Route path="competitor-taxonomy" element={<CompetitorTaxonomy />} />
              <Route path="competitor-mapping" element={<CompetitorMappingPage />} />
              <Route path="gaps" element={<GapsPage />} />
              <Route path="parent-child" element={<ParentChildGaps />} />
              <Route path="synonyms" element={<SynonymsPage />} />
              <Route path="rules" element={<RulesPage />} />
              <Route path="review" element={<ReviewQueue />} />
              <Route path="exports" element={<ExportsPage />} />
              <Route path="history" element={<HistoryPage />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </ProjectProvider>
      </AuthGate>
    </QueryClientProvider>
  </React.StrictMode>,
);
