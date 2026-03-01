import { API_BASE } from '../types';

interface McpSyncResult {
    success: boolean;
    message: string;
}

/**
 * Sync MCP tools from the first enabled MCP server.
 */
export async function syncMcpTools(): Promise<McpSyncResult> {
    const listRes = await fetch(`${API_BASE}/ops/config/mcp`, {
        credentials: 'include',
    });

    if (!listRes.ok) throw new Error(`HTTP ${listRes.status}`);

    const listData = (await listRes.json()) as {
        servers?: Array<{ name: string; enabled?: boolean }>;
    };

    const servers = Array.isArray(listData.servers) ? listData.servers : [];
    const candidate = servers.find((s) => s.enabled !== false) ?? servers[0];

    if (!candidate?.name) {
        return {
            success: false,
            message: 'No hay servidores MCP configurados para sincronizar.',
        };
    }

    const syncRes = await fetch(`${API_BASE}/ops/config/mcp/sync`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ server_name: candidate.name }),
    });

    if (!syncRes.ok) throw new Error(`HTTP ${syncRes.status}`);

    const payload = (await syncRes.json()) as {
        tools_discovered?: number;
        server?: string;
    };

    return {
        success: true,
        message: `MCP Sync OK (${payload.server || candidate.name}): ${payload.tools_discovered ?? 0} tools`,
    };
}
