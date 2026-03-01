import { MaintenanceIsland } from '../islands/system/MaintenanceIsland';

export default function MaintenanceView() {
    return (
        <div className="h-full overflow-y-auto custom-scrollbar p-6 bg-surface-0">
            <MaintenanceIsland />
        </div>
    );
}
