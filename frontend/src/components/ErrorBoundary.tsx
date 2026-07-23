import { Component, type ErrorInfo, type ReactNode } from "react";
import { api } from "../api/client";

type ErrorBoundaryState = {
  error: Error | null;
};

export class ErrorBoundary extends Component<
  { children: ReactNode; fallbackTitle?: string; compact?: boolean },
  ErrorBoundaryState
> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Uncaught UI error", error, info.componentStack);
  }

  private recover = () => {
    this.setState({ error: null });
  };

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    const compact = Boolean(this.props.compact);

    return (
      <main className={`grid place-items-center bg-base p-4 text-ui ${compact ? "min-h-0 flex-1 overflow-y-auto" : "min-h-dvh"}`}>
        <section
          role="alert"
          className="w-full max-w-lg rounded-lg border border-error-border bg-surface p-5 shadow-popover"
        >
          <h1 className="text-lg font-semibold text-ui-strong">
            {this.props.fallbackTitle ?? "HFabric hit a UI error"}
          </h1>
          <p className="mt-2 text-sm leading-6 text-ui-muted">
            Your data is safe. Try reopening this workspace, or reload the app if the problem persists.
          </p>
          <details className="mt-3 rounded-md border border-line bg-control p-3 text-xs text-ui-subtle">
            <summary className="cursor-pointer text-ui-muted">Error details</summary>
            <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap break-words">{error.message}</pre>
          </details>
          <div className="mt-4 flex flex-wrap justify-end gap-2">
            <a
              href={api.assetUrl("/api/diagnostics/export")}
              download
              className="ui-button rounded-md px-3 py-2 text-sm"
            >
              Download diagnostics
            </a>
            <button onClick={this.recover} className="ui-button rounded-md px-3 py-2 text-sm">
              Try again
            </button>
            <button
              onClick={() => window.location.reload()}
              className="ui-button-primary rounded-md px-3 py-2 text-sm"
            >
              Reload app
            </button>
          </div>
        </section>
      </main>
    );
  }
}
