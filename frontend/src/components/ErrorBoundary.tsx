"use client";

import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/**
 * A real error boundary (class component, `getDerivedStateFromError` +
 * `componentDidCatch`) around the whole app shell. Function components cannot catch
 * render errors in their children; this is why an error boundary must be a class.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("ReadyTrader dashboard crashed:", error, info.componentStack);
  }

  private reset = (): void => {
    this.setState({ error: null });
  };

  render(): ReactNode {
    if (this.state.error) {
      return (
        <div className="error-boundary" role="alert">
          <h1>Something went wrong</h1>
          <p>The dashboard hit an unexpected error and stopped rendering this part of the page.</p>
          <p className="error-boundary__detail">{this.state.error.message}</p>
          <button type="button" onClick={this.reset}>
            Try again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
