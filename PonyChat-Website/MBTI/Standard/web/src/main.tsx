import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { SiteConfigProvider } from "@common/config/SiteConfigContext";
import App from "@common/App";
import siteConfig from "./config";
import "@common/index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <SiteConfigProvider config={siteConfig}>
      <App />
    </SiteConfigProvider>
  </StrictMode>
);
