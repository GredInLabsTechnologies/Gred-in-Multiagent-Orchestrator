export type NavItem = { label: string; href: string };
export type CtaButton = { label: string; href: string; variant: "primary" | "secondary" };
export type FeatureItem = {
    title: string;
    description: string;
    icon: "GitMerge" | "Activity" | "Users" | "Box" | "Shield" | "Cpu";
    accent: "indigo" | "purple" | "emerald" | "amber" | "rose" | "blue";
};
export type WorkflowStep = { step: string; title: string; description: string };
export type IntegrationItem = { name: string; description: string };
export type DifferentiationItem = { title: string; description: string };
export type StatusItem = { label: string; status: "completed" | "in_development" | "experimental" };

export type SiteSettings = {
    siteName: string;
    navItems: NavItem[];
    signInLabel: string;
    footerCopyright: string;
};

export type LandingPageContent = {
    // Hero
    heroBadge: string;
    heroTitle: string;
    heroDescription: string;
    heroCtas: CtaButton[];

    // Authority
    authorityText: string;

    // Why GIMO Exists (Problem)
    problemTitle: string;
    problemDescription: string[];
    problemConclusion: string;

    // Workflow
    workflowTitle: string;
    workflowDescription: string;
    workflowSteps: WorkflowStep[];

    // Integrations
    integrationsTitle: string;
    integrationsDescription: string;
    integrations: IntegrationItem[];

    // Differentiation
    differentiationTitle: string;
    differentiationDescription: string;
    differentiationPoints: DifferentiationItem[];

    // Built by engineers
    builtByTitle: string;
    builtByDescription: string;
    builtByPoints: string[];

    // Design Principles
    principlesTitle: string;
    principles: FeatureItem[];

    // Project Status
    statusTitle: string;
    statusStage: string;
    statusItems: StatusItem[];
    statusFooter: string;

    // Final CTA
    finalCtaTitle: string;
    finalCtaDescription: string;
    finalCtas: CtaButton[];
};

export type LandingData = {
    siteSettings: SiteSettings;
    landingPage: LandingPageContent;
};

export const defaultLandingData: LandingData = {
    siteSettings: {
        siteName: "GIMO",
        navItems: [
            { label: "Why", href: "#problem" },
            { label: "How It Works", href: "#workflow" },
            { label: "Principles", href: "#principles" },
            { label: "Integrations", href: "#integrations" },
            { label: "Differentiation", href: "#differentiation" },
            { label: "Built by Engineers", href: "#built-by-engineers" },
            { label: "Status", href: "#status" },
        ],
        signInLabel: "Sign In",
        footerCopyright: "© 2024 GIMO Inc. Built by engineers.",
    },
    landingPage: {
        heroBadge: "AI agents should not execute actions unsupervised.",
        heroTitle: "Control your AI agents before they control your infrastructure.",
        heroDescription:
            "Local-first orchestration system for multi-agent workflows with human approval, token control and deterministic execution.",
        heroCtas: [
            { label: "Join Early Access", href: "#", variant: "primary" },
            { label: "Read Architecture", href: "#", variant: "secondary" },
        ],
        authorityText: "Built for real production environments. Designed for deterministic multi-agent execution.",
        problemTitle: "Why GIMO exists",
        problemDescription: [
            "AI agents are incredibly powerful, but dangerous.",
            "Most systems let them execute actions directly. That is not acceptable for real infrastructure.",
            "GIMO separates generation from execution."
        ],
        problemConclusion: "Agents propose. Humans approve. Systems remain under control.",
        workflowTitle: "How GIMO works",
        workflowDescription: "A deterministic control layer between autonomous generation and real-world execution.",
        workflowSteps: [
            {
                step: "01",
                title: "Agents propose",
                description: "Agents generate draft actions and execution plans with full context and cost estimates.",
            },
            {
                step: "02",
                title: "Humans approve",
                description: "Critical actions pause in an approval queue. Operators can inspect, edit, reject or approve.",
            },
            {
                step: "03",
                title: "Systems stay under control",
                description: "Only approved actions execute. Every transition is logged for auditing and reproducibility.",
            },
        ],
        integrationsTitle: "Integrations",
        integrationsDescription: "Compatible with production AI stacks out of the box.",
        integrations: [
            {
                name: "MCP",
                description: "Model Context Protocol support to orchestrate tools and agent resources safely.",
            },
            {
                name: "Provider abstraction",
                description: "Switch between OpenAI, Anthropic, Ollama and future providers without rewriting control logic.",
            },
            {
                name: "Local runtime",
                description: "Run local models and keep governance decisions close to your infrastructure boundary.",
            },
        ],
        differentiationTitle: "Why GIMO is different",
        differentiationDescription: "Most frameworks optimize for agent autonomy. GIMO optimizes for controlled execution.",
        differentiationPoints: [
            {
                title: "Control plane, not another framework",
                description: "GIMO sits between generation and execution to enforce policy before impact.",
            },
            {
                title: "Governance is native",
                description: "Approval gates, token governance and audit trails are first-class, not bolted-on scripts.",
            },
            {
                title: "Built for infrastructure reality",
                description: "Deterministic multi-agent execution for environments where mistakes are expensive.",
            },
        ],
        builtByTitle: "Built by engineers",
        builtByDescription: "We built GIMO after watching autonomous agents bypass review and execute directly against real systems.",
        builtByPoints: [
            "We separate generation from execution by design.",
            "Human approval is a default safety boundary, not an add-on.",
            "Governance, observability and determinism come before autonomy hype.",
        ],
        principlesTitle: "Design Principles",
        principles: [
            {
                title: "Human-in-the-loop by default",
                description: "Agents never execute critical actions without approval.",
                icon: "Users",
                accent: "emerald",
            },
            {
                title: "Deterministic execution",
                description: "Every action is recorded, auditable and reproducible.",
                icon: "GitMerge",
                accent: "indigo",
            },
            {
                title: "Local-first architecture",
                description: "Your data, secrets and tokens never leave your environment.",
                icon: "Shield",
                accent: "rose",
            },
            {
                title: "Provider-agnostic",
                description: "Works seamlessly with OpenAI, Anthropic, Ollama and future LLMs.",
                icon: "Cpu",
                accent: "blue",
            },
        ],
        statusTitle: "Project status",
        statusStage: "Private alpha",
        statusItems: [
            { label: "Core engine", status: "completed" },
            { label: "Orchestrator API", status: "in_development" },
            { label: "Control Panel UI", status: "experimental" },
        ],
        statusFooter: "Early access coming soon.",
        finalCtaTitle: "Build multi-agent systems that don't go rogue.",
        finalCtaDescription: "GIMO introduces a controlled execution layer between agents and your infrastructure.",
        finalCtas: [
            { label: "Request Access", href: "#", variant: "primary" },
            { label: "Join Early Access", href: "#", variant: "secondary" },
        ],
    },
};

export function mergeLandingData(input?: Partial<LandingData> | null): LandingData {
    if (!input) return defaultLandingData;

    return {
        siteSettings: {
            ...defaultLandingData.siteSettings,
            ...input.siteSettings,
            navItems: input.siteSettings?.navItems?.length ? input.siteSettings.navItems : defaultLandingData.siteSettings.navItems,
        },
        landingPage: {
            ...defaultLandingData.landingPage,
            ...input.landingPage,
            heroCtas: input.landingPage?.heroCtas?.length ? input.landingPage.heroCtas : defaultLandingData.landingPage.heroCtas,
            problemDescription: input.landingPage?.problemDescription?.length
                ? input.landingPage.problemDescription
                : defaultLandingData.landingPage.problemDescription,
            workflowSteps: input.landingPage?.workflowSteps?.length
                ? input.landingPage.workflowSteps
                : defaultLandingData.landingPage.workflowSteps,
            integrations: input.landingPage?.integrations?.length
                ? input.landingPage.integrations
                : defaultLandingData.landingPage.integrations,
            differentiationPoints: input.landingPage?.differentiationPoints?.length
                ? input.landingPage.differentiationPoints
                : defaultLandingData.landingPage.differentiationPoints,
            builtByPoints: input.landingPage?.builtByPoints?.length
                ? input.landingPage.builtByPoints
                : defaultLandingData.landingPage.builtByPoints,
            principles: input.landingPage?.principles?.length ? input.landingPage.principles : defaultLandingData.landingPage.principles,
            statusItems: input.landingPage?.statusItems?.length ? input.landingPage.statusItems : defaultLandingData.landingPage.statusItems,
            finalCtas: input.landingPage?.finalCtas?.length ? input.landingPage.finalCtas : defaultLandingData.landingPage.finalCtas,
        },
    };
}
