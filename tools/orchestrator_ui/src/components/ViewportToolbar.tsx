/*
COMPONENT: ViewportToolbar
ROLE: Floating toolbar above the central sprite viewport
CONTEXT: Quick actions for current asset (Play, Export, Edit)
LAST_MODIFIED: 2026-01-21
*/

import React from 'react';
import { Play, Upload, Pencil } from 'lucide-react';

interface ViewportToolbarProps {
    onPlayAnimation?: () => void;
    onExport?: () => void;
    onEdit?: () => void;
    hasAsset: boolean;
}

export const ViewportToolbar: React.FC<ViewportToolbarProps> = ({
    onPlayAnimation,
    onExport,
    onEdit,
    hasAsset
}) => {
    const actions = [
        { id: 'play', icon: Play, label: 'Play Animation', onClick: onPlayAnimation },
        { id: 'export', icon: Upload, label: 'Export', onClick: onExport },
        { id: 'edit', icon: Pencil, label: 'Edit', onClick: onEdit },
    ];

    return (
        <div className="absolute top-6 left-1/2 -translate-x-1/2 z-40">
            <div className="flex items-center space-x-1 px-2 py-2 bg-white/[0.03] backdrop-blur-2xl border border-white/10 rounded-2xl shadow-2xl">
                {actions.map((action, idx) => {
                    const Icon = action.icon;
                    return (
                        <React.Fragment key={action.id}>
                            {idx > 0 && <div className="w-px h-6 bg-white/10" />}
                            <button
                                onClick={action.onClick}
                                disabled={!hasAsset}
                                className={`
                                    flex items-center space-x-2 px-4 py-2 rounded-xl
                                    transition-all duration-200
                                    ${hasAsset
                                        ? 'text-slate-300 hover:text-white hover:bg-white/10 active:scale-95'
                                        : 'text-slate-600 cursor-not-allowed opacity-50'
                                    }
                                `}
                            >
                                <Icon className="w-4 h-4" />
                                <span className="text-[11px] font-bold uppercase tracking-wider">{action.label}</span>
                            </button>
                        </React.Fragment>
                    );
                })}
            </div>
        </div>
    );
};
