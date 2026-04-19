# Dev Mesh — SOTA Analysis & Innovation Map

**Date**: 2026-04-10  
**Purpose**: State of the art review + innovation opportunities for Dev Mesh  
**Companion to**: `DEV_MESH_EXPERIMENT_PLAN.md` (v2 frozen)  

---

## 1. State of the Art — What Exists Today

### 1.1 Distributed Inference on Consumer Devices

| Project | What It Does | Maturity | Relevance |
|---------|-------------|----------|-----------|
| **Prima.cpp** (ICLR 2026) | Runs 30-70B LLMs on heterogeneous home clusters. Works on Linux, macOS, **Android via Termux**, HarmonyOS. 5-17x faster than exo. | Experimental, paper accepted | **Very high** — validates our core thesis on recycled devices |
| **exo** (14k+ GitHub stars) | P2P distributed inference. No master-worker — ring topology. Each device runs layers proportional to RAM. | Production-ready | High — but P2P conflicts with our single-orchestrator invariant |
| **Distributed Llama** | Splits LLM layers across home devices. Simpler than exo. | Working | Medium — simpler model but less flexible |
| **ExecuTorch** (Meta, 1.0 GA Oct 2025) | On-device inference, 50KB footprint, 12+ hardware backends. Used in Instagram/WhatsApp at billion-user scale. | **Production** | High — proven ARM inference runtime |
| **PocketPal AI** | Android app built on llama.cpp, supports models up to 3.8B | Working | High — proves stock Android inference works |
| **SwiftLM** | Native MLX inference server on Apple Silicon with OpenAI-compatible API. SSD streaming for 100B+ MoE models. | Working | Medium — Apple-only |

**Key benchmark**: Llama 3.2 3B achieves ~20 tok/s on Cortex-X925 (latest ARM). Snapdragon 855 (S10) estimated at **1-3 tok/s on 1B Q4** — viable for batch work, not interactive chat.

### 1.2 Phone Compute Clusters / Device Recycling

| Project | What They Did | Key Learning |
|---------|--------------|--------------|
| **University of Tartu "Tiny Data Centers" (2025)** | 4 old Nexus phones, $8/device, ran image recognition "with unexpected ease" | Removed batteries, used external power to avoid degradation |
| **UMass "PhoneStacks"** | Android phone clusters for facial recognition + language processing | Proved phones can form viable compute clusters |
| **Samsung Galaxy Upcycling** | Pivoted to IoT sensors (childcare monitors, pet sensors), **not compute** | Consumer interest exists but Samsung missed the compute angle |
| **PostmarketOS** | 723 device models supported, generic mainline kernel | Full Linux on old phones is production-ready |

**Environmental data**: 5.3 billion phones discarded annually. 62M tonnes e-waste in 2022, only 22.3% recycled. Extending phone life by 1 year = 4.6M fewer tonnes of e-waste.

### 1.3 Thermal Management for Mobile Inference

| Finding | Source | Impact |
|---------|--------|--------|
| Thermal, not compute, is the binding constraint for sustained mobile inference | arXiv 2603.23640 (2026) | Validates our hardware protection invariant |
| `getThermalHeadroom(seconds)` predicts time to throttle | Android 12+ API | Direct hook for pre-task thermal check |
| INT4 vs FP16: 30-50% less power draw | Community benchmarks | Quantization as thermal management tool |
| 1-3B Q4 sustains 15-30 min before throttle (phone) | llama.cpp community | Defines real task window per device |
| 7B Q4 throttles in 2-4 min on Snapdragon 8 Gen 3 | Community benchmarks | Confirms mesh should target ≤3B on phones |
| Phone sustained power without fan: 3-5W | ARM reference | Hard physical limit |
| Battery at 40°C: 2x degradation rate | Dahn group (Dalhousie) | Justifies aggressive thermal lockout |
| Battery at 45°C: 3-4x degradation rate | Dahn group | Justifies our 45°C lockout threshold |
| 8h/day inference: battery to 80% health in 8-14 months | Extrapolated | Battery is the weakest link |
| Bypass charging at 50-60%: minimal degradation | Battery research | Critical for "server mode" devices |
| Duty cycling 70/30: can sustain indefinite inference | Thermal engineering | Design pattern for long-running nodes |

### 1.4 Learned Model Routing

| System | Approach | Key Result |
|--------|----------|------------|
| **RouteLLM** (UC Berkeley, 2024) | Matrix Factorization router trained on preference data | 50%+ cost reduction, <5ms latency, 1MB model |
| **FrugalGPT** (Stanford, 2023) | Cascade: try cheap first, escalate if needed | Up to 98% cost reduction on specific benchmarks |
| **AutoMix** (CMU/NAACL 2024) | Model self-assesses confidence, escalates if unsure | No external router needed |
| **Semantic Router** (Aurelio Labs) | Embedding-based fast classification, sub-ms routing | 5k+ GitHub stars, production-ready |
| **Thompson Sampling** for model selection | Beta distributions per (task_cluster, model) | Most validated bandit approach for this problem |
| **HDBSCAN** for task clustering | Density-based, no pre-specified cluster count | Works with UMAP dimensionality reduction |
| **PFRL-DM** (ICPP 2025) | Personalized Federated RL for heterogeneous scheduling | Validates per-device learned routing |

### 1.5 Running Servers on Stock Android

| Method | Root Required | Viability |
|--------|--------------|-----------|
| **Termux** (F-Droid) | No | **Best option** — Python, Node, nginx, llama.cpp, Prima.cpp all confirmed |
| **UserLAnd** | No | Heavier than Termux, uses PRoot for full Linux distros |
| **Foreground Service** | No | Prevents Android from killing the process |
| **Battery optimization bypass** | No | `REQUEST_IGNORE_BATTERY_OPTIMIZATIONS` + OEM whitelist |
| **dontkillmyapp.com** | No | Documents per-manufacturer workarounds for background killing |

---

## 2. What GIMO Dev Mesh Does Differently

### 2.1 vs Prima.cpp / exo

| Feature | Prima.cpp / exo | GIMO Dev Mesh |
|---------|----------------|---------------|
| Architecture | P2P ring / layer splitting | **Single orchestrator + workers** (preserves GIMO invariant) |
| Task granularity | Splits ONE model across devices | **Different tasks to different devices with different models** |
| Intelligence | Static scheduling (Halda) | **GICS learned patterns** — routing improves over time |
| Thermal protection | None documented | **Three-phase non-bypassable lockout** with GICS feedback loop |
| Device autonomy | Device participates or doesn't | **Bilateral consent** — device can refuse mid-session |
| Governance | None | **SAGP evaluation** on every dispatch |
| Auditability | Minimal logging | **Full audit trail** — every event, receipt, thermal event |
| Human oversight | None | **GICS pattern CRUD** — operator sees and controls routing |
| Device health | Not tracked | **Thermal profiles** per device feed future routing |
| Sustainability angle | Not addressed | **Core mission** — extend device life, monitor degradation |

**Key differentiator**: Prima.cpp and exo solve "how to run ONE big model across devices." GIMO Dev Mesh solves "how to route MANY different tasks to the RIGHT device with the RIGHT model, safely, with learned intelligence."

### 2.2 vs RouteLLM / FrugalGPT

| Feature | RouteLLM / FrugalGPT | GIMO Dev Mesh + GICS |
|---------|---------------------|----------------------|
| Routing target | Cloud APIs (GPT-4 vs Mixtral) | **Cloud + local + mesh devices** |
| Task understanding | Prompt-level (monolithic) | **Sub-task level** (plan decomposition) |
| Learning signal | Quality score per response | **Per-sub-task outcome + thermal impact + device health** |
| Personalization | None (global router) | **Per-installation evolution** |
| Hardware awareness | None | **Thermal profiles, battery health, max_model_params_b** |
| Cost optimization | API cost only | **API cost + device wear + energy + battery degradation** |
| Transparency | Router weights (opaque) | **CRUD on patterns + nearest-neighbor explanations** |

**Key differentiator**: RouteLLM optimizes cost/quality tradeoff between APIs. GICS optimizes cost/quality/device-health tradeoff across a heterogeneous ecosystem that includes physical device sustainability.

### 2.3 vs Samsung Upcycling

Samsung proved consumer interest in device reuse but pivoted to IoT sensors. GIMO Dev Mesh fills the gap Samsung left: **using old phones for actual compute**, not just as IoT endpoints.

The sustainability framing is the same, but the execution is fundamentally different: Samsung wanted consumer-friendly IoT. We want developer-facing distributed compute with governance.

---

## 3. Innovation Opportunities

### 3.1 Thermal-Predictive Routing (Novel)

**No existing system does this.** Before dispatching a task, GICS checks:

```
1. Task estimated duration (from pattern history)
2. Device thermal headroom (from getThermalHeadroom or sensor read)
3. Device thermal profile (from lockout history)
→ Decision: "This task takes ~6 min. This S10 historically throttles at 8 min.
   Margin too thin. Route to desktop or split into 2x3 min chunks."
```

This goes beyond reactive protection (throttle when hot) to **predictive routing** (avoid sending tasks that will cause thermal stress). GICS builds this intelligence automatically from lockout events.

**Why nobody does this yet**: Prima.cpp and exo don't track thermal history. Cloud routing (RouteLLM) doesn't deal with hardware. Game engines do reactive thermal management but don't do predictive task routing.

### 3.2 Device Health as Routing Dimension (Novel)

GICS can track a composite **Device Health Score** that degrades over time:

```
health_score = f(battery_capacity_retention, thermal_event_frequency,
                 inference_hours_total, thermal_cycling_count,
                 avg_operating_temperature)
```

Routing rules:
- Health score > 80%: full workload eligible
- Health score 60-80%: reduced duty cycle (50% instead of 70%)
- Health score < 60%: light tasks only (classification, extraction — short bursts)
- Health score < 40%: retire device from mesh, notify operator

**Why this is novel**: No inference framework considers device longevity. They all optimize for throughput/latency. GIMO Dev Mesh optimizes for **sustainable throughput** — maximum useful work over the device's remaining lifetime, not maximum work right now.

### 3.3 Quantization as Thermal Management (Actionable)

From the SOTA: INT4 uses 30-50% less power than FP16. This means quantization isn't just a size/quality tradeoff — it's a **thermal management tool**.

GICS can learn: "On this S10, qwen2.5:1.5b-Q4 sustains 20 min before warning. qwen2.5:1.5b-Q8 only sustains 8 min." If the device is already warm, GICS can recommend the Q4 variant even if Q8 would produce slightly better output.

This is a novel use of quantization as a device-health-preserving strategy.

### 3.4 Duty Cycle Scheduling (Actionable)

Instead of run-until-hot-then-stop, schedule work in cycles:

```
Device profile: "S10 can sustain 6 min inference, needs 3 min cooldown"
GICS routing: Send 2 tasks of ~5 min each with 3 min gap
Result: Device never reaches warning threshold, can work indefinitely
```

This pattern is known in thermal engineering but has **never been applied to LLM inference routing**. The duty cycle parameters are learned per-device from thermal history.

### 3.5 Battery Lifecycle Optimization (Novel)

For devices used as fixed compute nodes:

1. **Charge limiting**: Hold battery at 50-60% (Android 14+ supports this on some OEMs)
2. **Bypass charging detection**: If device supports it (ASUS ROG, some Xperia), prefer wall power directly to SoC
3. **Battery health tracking**: Monitor capacity retention over weeks/months via GICS
4. **Retirement prediction**: "At current usage rate, this battery will reach 80% health in ~10 months. Consider replacement or reduced duty cycle."

**Why this matters for the recycling angle**: An old phone with a healthy battery is a compute node. An old phone with a dead battery is e-waste. Extending battery life = extending compute utility = reducing e-waste.

### 3.6 Server Mode Without OS Replacement (Practical)

Your S10 doesn't need Linux. Termux on stock Android can run:

- **llama.cpp** for inference (confirmed by Prima.cpp team)
- **Python FastAPI** for the device agent API
- **Foreground service** to prevent Android from killing it
- **Battery optimization bypass** via system settings

The Dev Mesh agent package should include a **one-command Termux installer**:

```bash
pkg install python clang cmake && pip install gimo-mesh-agent && gimo-mesh-agent start
```

This is massively simpler than flashing PostmarketOS or Droidian, and it works on ANY Android phone without root.

### 3.7 Hierarchical Bayesian Pattern Sharing (Future)

Each GIMO installation builds its own GICS patterns. But some patterns are universally useful:

- "qwen2.5:0.5b is good at text classification regardless of whose device it runs on"
- "Snapdragon 855 throttles after ~11 min of sustained 1B inference"

A future feature could allow **opt-in anonymous pattern sharing**:

```
Installation A: "Pattern P47: review_python → qwen2.5:0.5b, 91% success, 142 runs"
Installation B: "Pattern P47: review_python → qwen2.5:0.5b, 87% success, 58 runs"
Aggregate: "P47 globally: qwen2.5:0.5b, 90% success, 200 runs — high confidence"
```

New installations inherit the global prior, then evolve locally. This is the Hierarchical Bayesian model validated in recommendation systems literature.

Privacy is preserved because only aggregate (pattern_label, model, success_rate, count) is shared — no prompts, no outputs, no user data.

### 3.8 Non-Inference Device Roles (Your Insight)

Not every device needs to run a model. A device too old or too weak for inference can still serve as:

| Role | What It Does | Minimum Device |
|------|-------------|----------------|
| **Storage node** | Cache files, artifacts, intermediate results | Any device with storage |
| **Relay node** | Forward messages between Core and remote devices | Any device with network |
| **Monitoring node** | Run lightweight validators/checkers on outputs | Any device with Python |
| **Preprocessing node** | Clean/tokenize/chunk text before inference | Any device with Python |
| **GIMO cloud endpoint** | Run a lightweight GIMO API server for remote access | Termux + FastAPI |

A Galaxy S5 (2014) with 2GB RAM can't run any useful model, but it CAN run a Python script that validates JSON, counts tokens, or serves as a network relay. That's still useful life instead of a landfill.

GICS can learn these roles too: "This device has max_model_params_b = 0 (too little RAM for any model), but it successfully ran 500 preprocessing tasks with 99% success rate."

---

## 4. Consolidated Innovation Stack

```
Layer 5 — Human Control
├── GICS Pattern CRUD (view/edit/create/delete learned patterns)
├── Device health dashboard (battery, thermal, lifecycle prediction)
├── Nearest-neighbor explanations ("routed here because 87 similar tasks succeeded")
└── Manual overrides ("always use model X for SQL tasks")

Layer 4 — Intelligent Routing (GICS)
├── Task fingerprinting (embedding + structural features)
├── Pattern matching (HDBSCAN clustering + cosine similarity)
├── Thompson Sampling per (pattern, model) for exploration/exploitation
├── Thermal-predictive routing (check headroom BEFORE dispatch)
├── Device health as routing constraint
├── Quantization-aware thermal optimization
└── Cascade fallback (mesh → local → remote API)

Layer 3 — Plan Decomposition (GIMO Core)
├── Plan Decomposer (orchestrator plan → sub-tasks with fingerprints)
├── Sub-task dependency graph (some tasks depend on others)
├── Complexity estimation (trivial/simple/moderate/complex)
└── Context requirement estimation (how much KB the task needs)

Layer 2 — Device Management (GIMO Core + Agent)
├── Bilateral consent (Core approves + device accepts)
├── Hardware protection (warn → throttle → lockout, non-bypassable)
├── Duty cycle scheduling (work/rest cycles per thermal profile)
├── Battery lifecycle management (charge limiting, health tracking)
├── Device health score (composite, degrades over time)
├── Multi-role support (inference, preprocessing, storage, relay)
└── Termux-based agent (stock Android, no root, no OS replacement)

Layer 1 — Execution (Device Agent)
├── llama.cpp / ExecuTorch for inference
├── Python for preprocessing/validation tasks
├── Structured output with schema validation
├── Receipt generation (proof of execution)
├── Thermal sensor monitoring (getThermalHeadroom + /sys/class/thermal/)
└── Automatic model unload on lockout

Layer 0 — Hardware (Physical Device)
├── CPU/GPU/NPU detection (desktop + mobile SoCs)
├── Battery monitoring (capacity, temp, charging, health)
├── Thermal zone monitoring (all available sensors)
├── max_model_params_b estimation (RAM / 2 for Q4 GGUF)
├── device_class detection (desktop/laptop/smartphone/tablet)
└── SoC identification (Snapdragon, Exynos, Apple, MediaTek)
```

---

## 5. What GIMO Should NOT Copy

| Approach | Why Not |
|----------|---------|
| exo's P2P ring topology | Violates single-orchestrator invariant |
| Prima.cpp's layer splitting | We route whole tasks, not model layers |
| Samsung Upcycling's IoT pivot | We want compute, not sensors |
| KubeEdge's heavy runtime | Too much overhead for old phones |
| RouteLLM's global router | We need per-installation personalization |
| Full OS replacement (PostmarketOS) | Barrier too high for most users; Termux is sufficient |
| FrugalGPT's blind cascade | We have GICS intelligence; cascade is fallback, not primary strategy |

---

## 6. Priority Innovations for v1 Experimental

| Priority | Innovation | Effort | Impact |
|----------|-----------|--------|--------|
| **P0** | Termux-based agent on stock Android | Medium | Enables the entire recycling thesis |
| **P0** | Three-phase hardware protection with GICS feedback | Medium | Safety invariant, non-negotiable |
| **P1** | GICS task pattern learning (Thompson Sampling) | High | Core intelligence differentiator |
| **P1** | Thermal-predictive routing | Medium | Novel, no competitor does this |
| **P1** | Plan decomposer (monolithic → sub-tasks) | High | Enables fine-grained routing |
| **P2** | Device health score + lifecycle prediction | Medium | Sustainability differentiator |
| **P2** | Duty cycle scheduling from thermal profiles | Low | Extends effective device uptime |
| **P2** | Quantization as thermal tool | Low | Novel use of existing capability |
| **P3** | Non-inference device roles (preprocessing, relay) | Low | Extends recycling to very old devices |
| **P3** | Battery lifecycle optimization | Medium | Extends compute lifespan |
| **Future** | Hierarchical Bayesian pattern sharing | High | Network effects across installations |

---

## 7. References

### Academic
- Prima.cpp: arXiv 2504.08791 (ICLR 2026 poster)
- RouteLLM: Ong et al., July 2024 (UC Berkeley)
- FrugalGPT: Chen et al., 2023 (Stanford)
- AutoMix: NAACL 2024 (CMU/Contextual AI)
- PFRL-DM: ICPP 2025 (Personalized Federated RL)
- Thermal-aware DNN on mobile: IEEE TMC 2024 (10478860)
- LLM inference at edge — thermal binding: arXiv 2603.23640 (2026)
- MNN-AECS adaptive core selection: arXiv 2506.19884 (2025/2026)

### Projects
- exo: github.com/exo-explore/exo (14k+ stars)
- Prima.cpp: github.com/Lizonghang/prima.cpp
- ExecuTorch: executorch.ai (Meta, 1.0 GA)
- Semantic Router: github.com/aurelio-labs/semantic-router (5k+ stars)
- PostmarketOS: postmarketos.org (723 devices)
- Akri: github.com/project-akri/akri (CNCF)
- PocketPal AI: Android app (llama.cpp based)
- SwiftLM: github.com/AugustDev/SwiftLM (Apple MLX)

### Data
- UNITAR Global E-Waste Monitor 2024
- Battery degradation: Jeff Dahn group (Dalhousie University)
- Android Thermal API: developer.android.com/games/optimize/adpf/thermal
- dontkillmyapp.com (OEM battery optimization workarounds)
- University of Tartu "Tiny Data Centers": IEEE Spectrum, June 2025
- Arm LLM benchmarks: newsroom.arm.com (Cortex-X925 + KleidiAI)
