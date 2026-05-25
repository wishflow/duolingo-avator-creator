/// <reference types="vite/client" />

declare global {
  interface Window {
    avatarBackend?: unknown;
    __TEST_TURNSTILE_TOKEN__?: string;
    __avatarTestHooks?: unknown;
    turnstile?: {
      render: (container: Element, options: Record<string, unknown>) => number;
      reset: (widgetId: number) => void;
    };
  }
}

export {};
