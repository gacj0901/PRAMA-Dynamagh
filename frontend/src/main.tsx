import React from "react";
import { createRoot } from "react-dom/client";

const App = () => (
  <main>
    <h1>PRAMA-Dynamagh</h1>
    <p>Phase 0 vertical slice is bootstrapping.</p>
  </main>
);

createRoot(document.getElementById("root")!).render(<React.StrictMode><App /></React.StrictMode>);

