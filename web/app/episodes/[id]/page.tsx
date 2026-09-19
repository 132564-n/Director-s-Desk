import { EpisodeWorkspace } from "@/components/episode-workspace";

export default async function EpisodePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <EpisodeWorkspace episodeId={id} />;
}
