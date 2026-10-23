import React, { Component, ErrorInfo, ReactNode } from 'react';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null,
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('Uncaught error in UI component:', error, errorInfo);
  }

  public render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }
      return (
        <div style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          minHeight: '100vh',
          background: 'var(--bg-primary)',
          color: 'var(--text-primary)',
          padding: '2rem',
          textAlign: 'center',
          fontFamily: 'var(--font-body)'
        }}>
          <p style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '0.6rem',
            letterSpacing: '0.12em',
            textTransform: 'uppercase',
            color: 'var(--accent-primary)',
            marginBottom: '12px'
          }}>
            Globe News Atlas
          </p>
          <h2 style={{
            fontFamily: 'var(--font-display)',
            fontSize: '1.8rem',
            fontWeight: 600,
            marginBottom: '0.9rem'
          }}>
            Recovered into table view
          </h2>
          <p style={{ maxWidth: '500px', color: 'var(--text-muted)', marginBottom: '1.5rem', lineHeight: 1.5 }}>
            A graphics context issue occurred. The atlas has safely recovered into accessible mode.
          </p>
          <button
            onClick={() => window.location.reload()}
            style={{
              padding: '0.55rem 1.1rem',
              background: 'var(--text-primary)',
              color: 'var(--bg-primary)',
              border: 'none',
              borderRadius: '2px',
              fontFamily: 'var(--font-mono)',
              fontSize: '0.65rem',
              letterSpacing: '0.05em',
              textTransform: 'uppercase',
              cursor: 'pointer'
            }}
          >
            Reload the atlas
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
