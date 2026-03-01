import { TrustSettings } from '../components/TrustSettings';

export default function TrustSettingsView() {
    return (
        <div className="h-full overflow-y-auto custom-scrollbar p-6 bg-surface-0">
            <div className="max-w-6xl mx-auto">
                <TrustSettings />
            </div>
        </div>
    );
}
