import { useAppStore, SidebarTab } from '../stores/appStore';
import { syncMcpTools } from './mcp';

type CommandHandler = () => void | Promise<void>;

/**
 * Map of command palette action IDs to handlers.
 * Each handler mutates the store or triggers side effects.
 */
export function getCommandHandlers(addToast: (msg: string, type: 'success' | 'error' | 'info') => void): Record<string, CommandHandler> {
    const store = useAppStore.getState;

    const goTo = (tab: SidebarTab) => () => store().setActiveTab(tab);

    return {
        new_plan: goTo('plans'),
        open_draft_modal: goTo('plans'),
        goto_graph: goTo('graph'),
        goto_plans: goTo('plans'),
        goto_evals: goTo('evals'),
        goto_metrics: goTo('metrics'),
        goto_security: goTo('security'),
        goto_operations: goTo('operations'),
        goto_analytics: goTo('analytics'),
        goto_settings: goTo('settings'),
        goto_mastery: goTo('mastery'),
        search_repo: goTo('operations'),
        view_runs: goTo('operations'),
        view_plan: goTo('plans'),

        mcp_sync: async () => {
            try {
                const result = await syncMcpTools();
                addToast(result.message, result.success ? 'success' : 'info');
                if (result.success) store().setActiveTab('settings');
            } catch {
                addToast('Falló MCP Sync. Revisa configuración de server en Settings.', 'error');
            }
        },
    };
}
