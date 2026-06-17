import type { SourceMaterial } from "../shared/types";
import { runMaterialResearch } from "./researchSkill";

export async function collectSources(topic: string, userSources: SourceMaterial[], searchEnabled: boolean) {
  const normalizedUserSources = userSources.map((source, index) => ({
    ...source,
    id: source.id || `user-${index + 1}`,
    origin: "user" as const
  }));

  if (!searchEnabled) {
    return normalizedUserSources;
  }

  const webSources = await searchWeb(topic);
  return [...normalizedUserSources, ...webSources];
}

async function searchWeb(topic: string): Promise<SourceMaterial[]> {
  return runMaterialResearch(topic);
}
