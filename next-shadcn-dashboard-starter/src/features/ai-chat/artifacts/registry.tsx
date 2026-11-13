'use client';

import type { ComponentType, ReactNode } from 'react';
import type { z } from 'zod';
import {
  dashboardPreviewSchema,
  documentPreviewSchema,
  presentationPreviewSchema,
  spreadsheetPreviewSchema
} from './schemas';
import type { Artifact } from './types';
import { DashboardArtifactPreview } from './components/dashboard-preview';
import { DocumentArtifactPreview } from './components/document-preview';
import { PresentationArtifactPreview } from './components/presentation-preview';
import { SpreadsheetArtifactPreview } from './components/spreadsheet-preview';

export interface ArtifactRendererProps<T> {
  data: T;
  artifact: Artifact;
}

interface ArtifactRendererDefinition<T> {
  id: string;
  version: number;
  label: string;
  schema: z.ZodType<T>;
  component: ComponentType<ArtifactRendererProps<T>>;
}

export interface RegisteredArtifactRenderer {
  id: string;
  version: number;
  label: string;
  render: (artifact: Artifact) => { success: true; content: ReactNode } | { success: false };
}

/** Register trusted, compiled React components. Streamed data can never supply code. */
export function defineArtifactRenderer<T>({
  id,
  version,
  label,
  schema,
  component: Renderer
}: ArtifactRendererDefinition<T>): RegisteredArtifactRenderer {
  return {
    id,
    version,
    label,
    render(artifact) {
      const parsed = schema.safeParse(artifact.preview?.data);
      if (!parsed.success) return { success: false };
      return {
        success: true,
        content: <Renderer data={parsed.data} artifact={artifact} />
      };
    }
  };
}

/** Add a schema + a trusted renderer here to introduce a new artifact format. */
export const artifactRenderers: readonly RegisteredArtifactRenderer[] = [
  defineArtifactRenderer({
    id: 'document',
    version: 1,
    label: '文档预览',
    schema: documentPreviewSchema,
    component: DocumentArtifactPreview
  }),
  defineArtifactRenderer({
    id: 'spreadsheet',
    version: 1,
    label: '表格预览',
    schema: spreadsheetPreviewSchema,
    component: SpreadsheetArtifactPreview
  }),
  defineArtifactRenderer({
    id: 'presentation',
    version: 1,
    label: '演示预览',
    schema: presentationPreviewSchema,
    component: PresentationArtifactPreview
  }),
  defineArtifactRenderer({
    id: 'bi-dashboard',
    version: 1,
    label: '业务看板',
    schema: dashboardPreviewSchema,
    component: DashboardArtifactPreview
  })
];

export function getArtifactRenderer(
  id: string,
  version: number
): RegisteredArtifactRenderer | undefined {
  return artifactRenderers.find((renderer) => renderer.id === id && renderer.version === version);
}
