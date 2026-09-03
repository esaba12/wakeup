import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { AppStoreProvider } from "./store/AppStore";
import { registerServiceWorker } from "./registerSW";
import "./theme.css";

const root = document.getElementById("root");
if (root === null) throw new Error("missing #root element");

createRoot(root).render(
  <StrictMode>
    <AppStoreProvider>
      <App />
    </AppStoreProvider>
  </StrictMode>
);

registerServiceWorker();
