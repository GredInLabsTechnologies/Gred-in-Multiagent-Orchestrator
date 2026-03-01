import { PlansPanel } from '../components/PlansPanel';
import { usePlanEngine } from '../hooks/usePlanEngine';
import { PlanCreateRequest } from '../types';

export default function PlansView() {
    const { currentPlan, loading, createPlan, approvePlan, setCurrentPlan } = usePlanEngine();

    return (
        <PlansPanel
            currentPlan={currentPlan}
            loading={loading}
            onCreatePlan={async (req: PlanCreateRequest) => { await createPlan(req); }}
            onApprovePlan={async () => { if (currentPlan) await approvePlan(currentPlan.id); }}
            onDiscardPlan={() => setCurrentPlan(null)}
        />
    );
}
