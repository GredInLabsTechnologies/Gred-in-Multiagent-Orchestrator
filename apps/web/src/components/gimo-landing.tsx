"use client";

import { useState } from "react";
import {
    Activity,
    ArrowRight,
    Box,
    CheckCircle2,
    Circle,
    Cpu,
    GitMerge,
    Layers,
    Menu,
    Shield,
    Users,
    X,
} from "lucide-react";
import Link from "next/link";

import type { LandingData } from "@/lib/default-content";
import { GoogleAuthButton } from "@/components/google-auth-button";

type GimoLandingProps = {
    data: LandingData;
};

const accentClasses: Record<string, { bg: string; icon: string; hover: string }> = {
    indigo: { bg: "bg-indigo-500/10", icon: "text-indigo-400", hover: "group-hover:bg-indigo-500/20" },
    purple: { bg: "bg-purple-500/10", icon: "text-purple-400", hover: "group-hover:bg-purple-500/20" },
    emerald: { bg: "bg-emerald-500/10", icon: "text-emerald-400", hover: "group-hover:bg-emerald-500/20" },
    amber: { bg: "bg-amber-500/10", icon: "text-amber-400", hover: "group-hover:bg-amber-500/20" },
    rose: { bg: "bg-rose-500/10", icon: "text-rose-400", hover: "group-hover:bg-rose-500/20" },
    blue: { bg: "bg-blue-500/10", icon: "text-blue-400", hover: "group-hover:bg-blue-500/20" },
};

const iconMap = {
    GitMerge,
    Activity,
    Users,
    Shield,
    Cpu,
    Box,
};

export function GimoLanding({ data }: GimoLandingProps) {
    const [isMenuOpen, setIsMenuOpen] = useState(false);
    const { siteSettings, landingPage } = data;

    return (
        <div className="min-h-screen bg-[#020617] text-slate-300 font-sans selection:bg-indigo-500/30 selection:text-indigo-200 overflow-x-hidden">
            <nav className="fixed w-full z-50 border-b border-white/5 bg-[#020617]/80 backdrop-blur-md">
                <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
                    <div className="flex items-center gap-2">
                        <div className="w-8 h-8 rounded-lg bg-indigo-600 flex items-center justify-center text-white">
                            <Layers size={18} />
                        </div>
                        <span className="font-semibold text-lg text-white tracking-tight">{siteSettings.siteName}</span>
                    </div>

                    <div className="hidden md:flex items-center gap-8 text-sm font-medium text-slate-400">
                        {siteSettings.navItems.map((item) => (
                            <a key={`${item.label}-${item.href}`} href={item.href} className="hover:text-white transition-colors">
                                {item.label}
                            </a>
                        ))}
                    </div>

                    <div className="hidden md:flex items-center gap-4">
                        <GoogleAuthButton className="mr-1" />
                        <Link
                            href="#"
                            className="text-sm font-medium px-4 py-2 rounded-lg bg-white text-black hover:bg-slate-200 transition-colors"
                        >
                            Join Early Access
                        </Link>
                    </div>

                    <button className="md:hidden text-slate-400" onClick={() => setIsMenuOpen((prev) => !prev)} aria-label="Abrir menú">
                        {isMenuOpen ? <X /> : <Menu />}
                    </button>
                </div>

                {isMenuOpen && (
                    <div className="md:hidden border-t border-white/10 bg-[#020617] px-6 py-4 space-y-3">
                        {siteSettings.navItems.map((item) => (
                            <a key={`mobile-${item.label}`} href={item.href} className="block text-slate-300 hover:text-white">
                                {item.label}
                            </a>
                        ))}
                        <GoogleAuthButton />
                        <Link
                            href="#"
                            className="inline-flex text-sm font-medium px-4 py-2 rounded-lg bg-white text-black hover:bg-slate-200 transition-colors"
                        >
                            Join Early Access
                        </Link>
                    </div>
                )}
            </nav>

            <section className="relative pt-32 pb-24 lg:pt-44 lg:pb-28 overflow-hidden">
                <div className="absolute inset-0 bg-grid-slate opacity-20 -z-10" />
                <div className="absolute top-20 left-1/2 -translate-x-1/2 w-[800px] h-[400px] bg-indigo-600/20 blur-[120px] rounded-full pointer-events-none" />

                <div className="max-w-7xl mx-auto px-6 text-center relative z-10">
                    <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-indigo-500/10 border border-indigo-500/20 mb-8">
                        <span className="text-xs font-medium text-indigo-300">{landingPage.heroBadge}</span>
                        <ArrowRight size={12} className="text-indigo-400" />
                    </div>

                    <h1 className="text-5xl md:text-7xl font-bold tracking-tight text-white mb-6 leading-[1.1]">{landingPage.heroTitle}</h1>

                    <p className="text-lg md:text-xl text-slate-400 max-w-2xl mx-auto mb-10 leading-relaxed">{landingPage.heroDescription}</p>

                    <div className="flex flex-col sm:flex-row gap-4 justify-center items-center mb-16">
                        {landingPage.heroCtas.map((cta, i) => (
                            <Link
                                key={`${cta.label}-${i}`}
                                href={cta.href}
                                className={
                                    cta.variant === "primary"
                                        ? "h-12 px-8 rounded-lg bg-white text-black hover:bg-slate-200 font-medium transition-all flex items-center gap-2 shadow-lg shadow-white/10"
                                        : "h-12 px-8 rounded-lg bg-slate-800/50 hover:bg-slate-800 border border-slate-700 text-white font-medium transition-all flex items-center gap-2"
                                }
                            >
                                {cta.label}
                            </Link>
                        ))}
                    </div>

                    <div className="relative max-w-5xl mx-auto">
                        <div className="rounded-2xl border border-slate-700/60 bg-[#0b1120] shadow-2xl overflow-hidden text-left">
                            <div className="h-11 border-b border-slate-700/50 bg-[#111827] flex items-center justify-between px-4">
                                <div className="flex gap-2">
                                    <div className="w-2.5 h-2.5 rounded-full bg-slate-500" />
                                    <div className="w-2.5 h-2.5 rounded-full bg-slate-500" />
                                    <div className="w-2.5 h-2.5 rounded-full bg-slate-500" />
                                </div>
                                <div className="text-xs font-mono text-slate-400">gimo-control-plane / execution-panel</div>
                                <span className="text-[10px] font-medium text-amber-300 bg-amber-500/15 border border-amber-500/30 px-2 py-0.5 rounded-full">
                                    awaiting_approval
                                </span>
                            </div>

                            <div className="grid lg:grid-cols-[1.2fr_1fr] gap-0">
                                <div className="border-b lg:border-b-0 lg:border-r border-slate-700/50 p-5 md:p-6">
                                    <div className="text-xs text-slate-500 uppercase tracking-wider mb-3">Action draft</div>
                                    <div className="rounded-xl border border-slate-700 bg-[#020617] p-4">
                                        <div className="flex items-center justify-between mb-3">
                                            <p className="font-mono text-xs text-slate-400">intent: deploy_service_patch</p>
                                            <span className="text-[10px] text-indigo-300 bg-indigo-500/15 px-2 py-0.5 rounded">risk: medium</span>
                                        </div>
                                        <p className="text-sm text-slate-300 leading-relaxed">
                                            Agent proposes updating production gateway policy and rotating affected keys after validation.
                                        </p>
                                        <div className="mt-4 grid sm:grid-cols-3 gap-3">
                                            <div className="rounded-lg bg-slate-900/70 border border-slate-800 p-2">
                                                <div className="text-[10px] uppercase text-slate-500">provider</div>
                                                <div className="text-xs font-mono text-slate-300">OpenAI + Ollama</div>
                                            </div>
                                            <div className="rounded-lg bg-slate-900/70 border border-slate-800 p-2">
                                                <div className="text-[10px] uppercase text-slate-500">tokens</div>
                                                <div className="text-xs font-mono text-slate-300">1,832 est.</div>
                                            </div>
                                            <div className="rounded-lg bg-slate-900/70 border border-slate-800 p-2">
                                                <div className="text-[10px] uppercase text-slate-500">latency</div>
                                                <div className="text-xs font-mono text-slate-300">1.4s</div>
                                            </div>
                                        </div>
                                    </div>
                                </div>

                                <div className="p-5 md:p-6 bg-[#0b1221]">
                                    <div className="text-xs text-slate-500 uppercase tracking-wider mb-3">Approval queue</div>
                                    <div className="space-y-3">
                                        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3">
                                            <p className="text-sm font-medium text-amber-200">Pending human approval</p>
                                            <p className="text-xs text-amber-100/80 mt-1">No execution will happen until an operator approves this draft.</p>
                                        </div>
                                        <div className="rounded-lg border border-slate-700 bg-slate-900/70 p-3">
                                            <p className="text-xs text-slate-500 uppercase">Execution policy</p>
                                            <p className="text-sm text-slate-300 mt-1">critical_actions.requireApproval = true</p>
                                        </div>
                                        <div className="flex gap-2 pt-1">
                                            <button className="px-3 py-2 rounded-lg text-xs font-medium border border-slate-600 text-slate-300 hover:bg-slate-800 transition-colors">
                                                Reject
                                            </button>
                                            <button className="px-3 py-2 rounded-lg text-xs font-medium border border-indigo-500/40 bg-indigo-500/20 text-indigo-200 hover:bg-indigo-500/30 transition-colors">
                                                Approve execution
                                            </button>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </section>

            <section className="py-10 border-y border-white/5 bg-[#0b1221]">
                <div className="max-w-6xl mx-auto px-6 text-center">
                    <p className="text-sm md:text-base text-slate-300 font-medium">{landingPage.authorityText}</p>
                </div>
            </section>

            <section id="problem" className="py-24 bg-[#020617] border-b border-white/5">
                <div className="max-w-4xl mx-auto px-6 text-center">
                    <h2 className="text-3xl md:text-4xl font-bold text-white mb-8">{landingPage.problemTitle}</h2>
                    <div className="space-y-4">
                        {landingPage.problemDescription.map((line) => (
                            <p key={line} className="text-lg text-slate-300 leading-relaxed">
                                {line}
                            </p>
                        ))}
                    </div>
                    <p className="mt-8 text-xl font-semibold text-indigo-300">{landingPage.problemConclusion}</p>
                </div>
            </section>

            <section id="workflow" className="py-24 bg-[#020617]">
                <div className="max-w-7xl mx-auto px-6">
                    <div className="mb-14 text-center">
                        <h2 className="text-3xl font-bold text-white mb-4">{landingPage.workflowTitle}</h2>
                        <p className="text-slate-400 max-w-3xl mx-auto text-lg">{landingPage.workflowDescription}</p>
                    </div>

                    <div className="grid md:grid-cols-3 gap-6">
                        {landingPage.workflowSteps.map((step) => (
                            <div key={step.step} className="rounded-2xl border border-slate-700/60 bg-[#0b1221] p-6">
                                <div className="text-xs font-mono text-indigo-300 mb-3">STEP {step.step}</div>
                                <h3 className="text-xl font-semibold text-white mb-3">{step.title}</h3>
                                <p className="text-slate-400 leading-relaxed">{step.description}</p>
                            </div>
                        ))}
                    </div>
                </div>
            </section>

            <section id="integrations" className="py-20 border-t border-white/5 bg-[#020617]">
                <div className="max-w-7xl mx-auto px-6">
                    <h2 className="text-3xl font-bold text-white mb-4">{landingPage.integrationsTitle}</h2>
                    <p className="text-slate-400 mb-10 max-w-3xl">{landingPage.integrationsDescription}</p>
                    <div className="grid md:grid-cols-3 gap-6">
                        {landingPage.integrations.map((integration) => (
                            <div key={integration.name} className="rounded-xl border border-slate-700/60 bg-[#0b1221] p-5">
                                <p className="text-white font-semibold mb-2">{integration.name}</p>
                                <p className="text-sm text-slate-400 leading-relaxed">{integration.description}</p>
                            </div>
                        ))}
                    </div>
                </div>
            </section>

            <section id="differentiation" className="py-20 border-t border-white/5 bg-[#020617]">
                <div className="max-w-7xl mx-auto px-6">
                    <h2 className="text-3xl font-bold text-white mb-4">{landingPage.differentiationTitle}</h2>
                    <p className="text-slate-400 mb-10 max-w-3xl">{landingPage.differentiationDescription}</p>
                    <div className="grid md:grid-cols-3 gap-6">
                        {landingPage.differentiationPoints.map((point) => (
                            <div key={point.title} className="rounded-xl border border-slate-700/60 bg-[#0b1221] p-5">
                                <p className="text-white font-semibold mb-2">{point.title}</p>
                                <p className="text-sm text-slate-400 leading-relaxed">{point.description}</p>
                            </div>
                        ))}
                    </div>
                </div>
            </section>

            <section id="built-by-engineers" className="py-20 border-t border-white/5 bg-[#020617]">
                <div className="max-w-7xl mx-auto px-6 grid lg:grid-cols-2 gap-10 items-start">
                    <div>
                        <h2 className="text-3xl font-bold text-white mb-4">{landingPage.builtByTitle}</h2>
                        <p className="text-slate-400 text-lg leading-relaxed">{landingPage.builtByDescription}</p>
                    </div>
                    <div className="rounded-2xl border border-slate-700/60 bg-[#0b1221] p-6">
                        <ul className="space-y-3">
                            {landingPage.builtByPoints.map((point) => (
                                <li key={point} className="text-slate-300 text-sm leading-relaxed flex gap-3">
                                    <span className="mt-1 h-1.5 w-1.5 rounded-full bg-indigo-400" />
                                    <span>{point}</span>
                                </li>
                            ))}
                        </ul>
                    </div>
                </div>
            </section>

            <section id="principles" className="py-24 border-t border-white/5 bg-[#020617]">
                <div className="max-w-7xl mx-auto px-6">
                    <div className="mb-12">
                        <h2 className="text-3xl font-bold text-white">{landingPage.principlesTitle}</h2>
                    </div>

                    <div className="grid md:grid-cols-2 xl:grid-cols-4 gap-6">
                        {landingPage.principles.map((feature) => {
                            const Icon = iconMap[feature.icon] ?? GitMerge;
                            const accent = accentClasses[feature.accent] ?? accentClasses.indigo;

                            return (
                                <div key={feature.title} className="glass-card p-6 rounded-2xl group transition-all">
                                    <div className={`w-12 h-12 rounded-lg ${accent.bg} flex items-center justify-center mb-5 ${accent.hover} transition-colors`}>
                                        <Icon className={accent.icon} size={20} />
                                    </div>
                                    <h3 className="text-lg font-semibold text-white mb-3">{feature.title}</h3>
                                    <p className="text-slate-400 leading-relaxed">{feature.description}</p>
                                </div>
                            );
                        })}
                    </div>
                </div>
            </section>

            <section id="status" className="py-24 border-t border-white/5 relative">
                <div className="max-w-7xl mx-auto px-6 grid lg:grid-cols-2 gap-14 items-center">
                    <div>
                        <h2 className="text-3xl font-bold text-white mb-4">{landingPage.statusTitle}</h2>
                        <p className="text-slate-400 text-lg mb-8">
                            Current stage: <span className="text-white font-semibold">{landingPage.statusStage}</span>
                        </p>

                        <div className="space-y-4">
                            {landingPage.statusItems.map((item) => {
                                const done = item.status === "completed";
                                const inProgress = item.status === "in_development";

                                return (
                                    <div key={item.label} className="flex items-center gap-3 text-sm">
                                        {done ? <CheckCircle2 size={16} className="text-emerald-400" /> : <Circle size={16} className={inProgress ? "text-amber-400" : "text-indigo-400"} />}
                                        <span className="text-slate-300">{item.label}</span>
                                        <span className="text-xs uppercase tracking-wide text-slate-500">{item.status.replace("_", " ")}</span>
                                    </div>
                                );
                            })}
                        </div>
                        <p className="mt-6 text-slate-400">{landingPage.statusFooter}</p>
                    </div>

                    <div className="rounded-xl bg-[#0f172a] border border-slate-700 p-6 font-mono text-sm shadow-2xl relative text-slate-300">
                        <div className="absolute -top-4 -right-4 bg-indigo-600 text-white text-xs font-bold px-3 py-1 rounded shadow-lg">status.log</div>
                        <pre className="whitespace-pre-wrap">{`[gimo-control-plane]
stage = private_alpha
approval_mode = strict

core_engine       : completed
orchestrator_api  : in_development
control_panel_ui  : experimental

next: early_access_rollout`}</pre>
                    </div>
                </div>
            </section>

            <footer className="border-t border-white/5 bg-[#020617] pt-20 pb-10">
                <div className="max-w-7xl mx-auto px-6 text-center">
                    <h2 className="text-3xl font-bold text-white mb-6">{landingPage.finalCtaTitle}</h2>
                    <p className="text-slate-400 max-w-2xl mx-auto mb-8">{landingPage.finalCtaDescription}</p>
                    <div className="flex justify-center gap-4 mb-12 flex-wrap">
                        {landingPage.finalCtas.map((cta, i) => (
                            <Link
                                key={`final-${cta.label}-${i}`}
                                href={cta.href}
                                className={
                                    cta.variant === "primary"
                                        ? "px-8 py-3 rounded-lg bg-white text-black font-semibold hover:bg-slate-200 transition-colors"
                                        : "px-8 py-3 rounded-lg border border-slate-700 text-white font-semibold hover:bg-slate-800 transition-colors"
                                }
                            >
                                {cta.label}
                            </Link>
                        ))}
                    </div>
                    <p className="text-slate-600 text-sm">{siteSettings.footerCopyright}</p>
                </div>
            </footer>
        </div>
    );
}
