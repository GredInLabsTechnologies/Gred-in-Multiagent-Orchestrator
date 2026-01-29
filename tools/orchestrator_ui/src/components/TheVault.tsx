import React from 'react';
import { X, Sparkles, Download, ExternalLink, Activity } from 'lucide-react';

interface AssetVaultProps {
    assets: string[];
    onClose: () => void;
    onSelectAsset: (filename: string) => void;
    apiBase: string;
}

export const TheVault: React.FC<AssetVaultProps> = ({ assets, onClose, onSelectAsset, apiBase }) => {
    return (
        <div className="fixed inset-0 z-[60] flex items-center justify-center p-8 animate-fade-in">
            {/* Backdrop with heavy blur */}
            <div className="absolute inset-0 bg-black/40 backdrop-blur-[80px]" onClick={onClose} />

            <div className="glass-panel w-full max-w-7xl h-full rounded-[3rem] p-10 flex flex-col relative shadow-[0_0_100px_rgba(0,0,0,0.5)] overflow-hidden border border-white/10">
                {/* Header */}
                <div className="flex items-center justify-between mb-10 z-10">
                    <div className="flex items-center space-x-6">
                        <div className="w-16 h-16 bg-gradient-to-br from-accent-primary to-accent-secondary rounded-2xl flex items-center justify-center shadow-[0_0_30px_rgba(124,58,237,0.5)]">
                            <Sparkles className="w-8 h-8 text-white" />
                        </div>
                        <div>
                            <h2 className="text-3xl font-bold text-white tracking-tighter">THE <span className="text-accent-primary">VAULT</span></h2>
                            <p className="text-[10px] text-slate-400 uppercase tracking-[0.3em] font-black mt-1">Gred In Labs Asset Repository v2.1</p>
                        </div>
                    </div>

                    <div className="flex items-center space-x-4">
                        <div className="flex bg-black/20 p-1 rounded-xl border border-white/5 backdrop-blur-md">
                            <button className="px-6 py-2 rounded-lg text-[10px] font-bold text-white bg-accent-primary shadow-lg">ALL ASSETS</button>
                            <button className="px-6 py-2 rounded-lg text-[10px] font-bold text-slate-500 hover:text-white transition-all">ANIMATED</button>
                            <button className="px-6 py-2 rounded-lg text-[10px] font-bold text-slate-500 hover:text-white transition-all">SPRITES</button>
                        </div>
                        <button
                            onClick={onClose}
                            className="p-4 hover:bg-white/10 rounded-full transition-all text-slate-400 hover:text-white"
                        >
                            <X className="w-6 h-6" />
                        </button>
                    </div>
                </div>

                {/* Main Content Area */}
                <div className="flex-1 overflow-y-auto pr-4 custom-scrollbar z-10">
                    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-6">
                        {assets.map((asset, idx) => (
                            <div
                                key={idx}
                                className="group relative aspect-square rounded-[2rem] bg-black/40 border border-white/5 overflow-hidden transition-all hover:border-accent-primary/40 hover:scale-[1.02] cursor-pointer"
                                onClick={() => onSelectAsset(asset)}
                            >
                                <img
                                    src={`${apiBase}/outputs/${asset}`}
                                    alt={asset}
                                    className="w-full h-full object-contain p-6 opacity-80 group-hover:opacity-100 transition-opacity"
                                    style={{ imageRendering: 'pixelated' }}
                                />

                                {/* Overlay Controls */}
                                <div className="absolute inset-0 bg-gradient-to-t from-black/90 via-black/20 to-transparent opacity-0 group-hover:opacity-100 transition-all p-5 flex flex-col justify-end transform translate-y-4 group-hover:translate-y-0">
                                    <div className="flex items-center justify-between">
                                        <div>
                                            <p className="text-[9px] font-black text-accent-primary uppercase tracking-tighter">Class: SPRITE</p>
                                            <p className="text-[11px] font-bold text-white truncate max-w-[120px]">{asset.replace('.png', '')}</p>
                                        </div>
                                        <div className="flex space-x-2">
                                            <div className="p-2 bg-white/10 rounded-lg backdrop-blur-md border border-white/10 hover:bg-accent-primary transition-colors">
                                                <ExternalLink className="w-3 h-3 text-white" />
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>

                {/* Footer / Stats */}
                <div className="mt-10 pt-6 border-t border-white/5 flex items-center justify-between text-slate-500 z-10">
                    <div className="flex items-center space-x-8 text-[10px] font-bold uppercase tracking-widest">
                        <div className="flex items-center">
                            <Activity className="w-4 h-4 mr-2 text-emerald-500" />
                            <span>Total Storage: {assets.length} Units</span>
                        </div>
                        <div className="flex items-center">
                            <Download className="w-4 h-4 mr-2 text-blue-500" />
                            <span>DNA Integrity: 100% Verified</span>
                        </div>
                    </div>
                    <div className="text-[9px] font-mono opacity-30 italic">
                        SECURE HUB CHANNEL ID: GRED-VAULT-{(Math.random() * 1000).toFixed(0)}
                    </div>
                </div>

                {/* Decorative BG elements */}
                <div className="absolute top-[-10%] left-[-10%] w-[40%] h-[40%] bg-accent-primary/5 rounded-full blur-[120px] pointer-events-none" />
                <div className="absolute bottom-[-10%] right-[-10%] w-[40%] h-[40%] bg-accent-secondary/5 rounded-full blur-[120px] pointer-events-none" />
            </div>
        </div>
    );
};
