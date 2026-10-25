import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { applyStoredAccent } from "./accent";
import { I18nProvider } from "./i18n";
import "./styles.css";

applyStoredAccent();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <I18nProvider>
      <App />
    </I18nProvider>
  </StrictMode>,
);
