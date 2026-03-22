import { Component, type ErrorInfo, type ReactNode } from 'react';
import i18n from '../i18n';

interface Props {
    children: ReactNode;
}

interface State {
    hasError: boolean;
    error: Error | null;
    errorInfo: ErrorInfo | null;
}

export class ErrorBoundary extends Component<Props, State> {
    state: State = { hasError: false, error: null, errorInfo: null };

    static getDerivedStateFromError(error: Error): Partial<State> {
        return { hasError: true, error };
    }

    componentDidCatch(error: Error, errorInfo: ErrorInfo) {
        this.setState({ errorInfo });
        console.error('[ErrorBoundary]', error, errorInfo);
    }

    handleReload = () => window.location.reload();

    handleDismiss = () => this.setState({ hasError: false, error: null, errorInfo: null });

    render() {
        if (!this.state.hasError) return this.props.children;
        const t = i18n.t.bind(i18n);

        return (
            <div className="min-h-screen bg-surface-2 flex items-center justify-center p-6">
                <div className="max-w-xl w-full bg-surface-3 rounded-2xl border border-surface-3 p-8 space-y-4">
                    <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-full bg-red-500/20 flex items-center justify-center">
                            <span className="text-red-400 text-xl">!</span>
                        </div>
                        <h1 className="text-xl font-semibold text-white">{t('error.appCrash')}</h1>
                    </div>

                    <p className="text-text-secondary text-sm">
                        {t('error.crashMessage')}
                    </p>

                    {this.state.error && (
                        <div className="bg-surface-2 rounded-lg p-4 border border-surface-3">
                            <p className="text-red-400 text-sm font-mono break-all">
                                {this.state.error.message}
                            </p>
                        </div>
                    )}

                    {this.state.errorInfo && (
                        <details className="text-xs text-text-tertiary">
                            <summary className="cursor-pointer hover:text-text-secondary transition-colors">
                                Stack trace
                            </summary>
                            <pre className="mt-2 bg-surface-2 rounded-lg p-3 border border-surface-3 overflow-auto max-h-48 font-mono text-[10px]">
                                {this.state.errorInfo.componentStack}
                            </pre>
                        </details>
                    )}

                    <div className="flex gap-3 pt-2">
                        <button
                            onClick={this.handleReload}
                            className="px-4 py-2 bg-accent-primary text-white text-sm rounded-lg hover:bg-accent-primary/80 transition-colors"
                        >
                            {t('error.reload')}
                        </button>
                        <button
                            onClick={this.handleDismiss}
                            className="px-4 py-2 bg-surface-3 text-white text-sm rounded-lg hover:bg-[#48484a] transition-colors"
                        >
                            {t('common.close')}
                        </button>
                    </div>
                </div>
            </div>
        );
    }
}
