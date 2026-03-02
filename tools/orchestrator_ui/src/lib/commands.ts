import { useAppStore } from '../stores/appStore';
import { syncMcpTools } from './mcp';

type CommandHandler = () => void | Promise<void>;

/**
 * Map of command palette action IDs to handlers.
 * Uses store.navigate() which auto-routes to sidebar tabs or overlays.
 */
export function getCommandHandlers(
    addToast: (msg: string, type: 'success' | 'error' | 'info') => void,
): Record<string, CommandHandler> {
    const nav = (target: string) => () => useAppStore.getState().navigate(target);

    return {
        new_plan: nav('plans'),
        open_draft_modal: nav('plans'),
        goto_graph: nav('graph'),
        goto_plans: nav('plans'),
        goto_evals: nav('evals'),
        goto_metrics: nav('metrics'),
        goto_security: nav('security'),
        goto_operations: nav('operations'),
        goto_analytics: nav('metrics'),
        goto_settings: nav('settings'),
        goto_mastery: nav('mastery'),
        search_repo: nav('operations'),
        view_runs: nav('operations'),
        view_plan: nav('plans'),

        mcp_sync: async () => {
            try {
                const result = await syncMcpTools();
                addToast(result.message, result.success ? 'success' : 'info');
                if (result.success) useAppStore.getState().navigate('settings');
            } catch {
                addToast('Falló MCP Sync. Revisa configuración de server en Settings.', 'error');
            }
        },
    };
}
