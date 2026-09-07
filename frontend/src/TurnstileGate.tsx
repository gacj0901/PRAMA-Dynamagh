import { useEffect, useRef } from "react";

declare global {
  interface Window {
    turnstile?: {
      render: (element: HTMLElement, options: Record<string, unknown>) => string;
      remove: (id: string) => void;
    };
  }
}

export function TurnstileGate({ siteKey, hash, onToken, onError }: {
  siteKey: string; hash: string; onToken: (token: string) => void; onError: () => void;
}) {
  const container = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let widget: string | undefined;
    let active = true;
    function render() {
      if (!active || !container.current || !window.turnstile || widget !== undefined) return;
      widget = window.turnstile.render(container.current, {
        sitekey: siteKey, action: "titular_check", cData: hash, theme: "dark", size: "flexible",
        callback: onToken, "error-callback": onError, "expired-callback": onError,
      });
    }
    let script = document.querySelector<HTMLScriptElement>("script[data-titular-turnstile]");
    if (!script) {
      script = document.createElement("script");
      script.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
      script.async = true;
      script.dataset.titularTurnstile = "true";
      document.head.appendChild(script);
    }
    script.addEventListener("load", render);
    script.addEventListener("error", onError);
    render();
    return () => {
      active = false;
      script?.removeEventListener("load", render);
      script?.removeEventListener("error", onError);
      if (widget !== undefined) window.turnstile?.remove(widget);
    };
  }, [siteKey, hash, onToken, onError]);
  return <div className="tc-challenge"><p>Complete the human-presence check to access this receipt.</p><div ref={container} /><p className="tc-note">Human presence does not establish your identity or approve an operation.</p></div>;
}
