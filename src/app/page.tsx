import { GimoLanding } from "@/components/gimo-landing";
import { defaultLandingData } from "@/lib/default-content";

export default async function Home() {
  return <GimoLanding data={defaultLandingData} />;
}
