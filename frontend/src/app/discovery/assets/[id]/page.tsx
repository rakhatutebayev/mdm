export const dynamic = 'force-dynamic';
import { type DiscoveredAsset } from '@/lib/api';
import AssetDetailClient from './AssetDetailClient';

type PageProps = {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ agent?: string; customer?: string }>;
};

async function loadAsset(id: string): Promise<{ asset: DiscoveredAsset | null; error: string | null }> {
  const backend = process.env.API_URL ?? 'http://localhost:8000';
  try {
    const response = await fetch(`${backend}/api/v1/discovery/assets/${encodeURIComponent(id)}`, {
      cache: 'no-store',
    });
    if (response.status === 404) {
      return { asset: null, error: 'Asset not found.' };
    }
    if (!response.ok) {
      return { asset: null, error: `Could not load discovered asset details (${response.status}).` };
    }
    const asset = await response.json() as DiscoveredAsset;
    return { asset, error: null };
  } catch {
    return { asset: null, error: 'Could not load discovered asset details.' };
  }
}

export default async function DiscoveredAssetDetailPage({ params, searchParams }: PageProps) {
  const { id } = await params;
  const query = await searchParams;
  const initial = await loadAsset(id);

  return (
    <AssetDetailClient
      assetId={id}
      agentId={query.agent ?? ''}
      customer={query.customer ?? ''}
      initialAsset={initial.asset}
      initialError={initial.error}
    />
  );
}
