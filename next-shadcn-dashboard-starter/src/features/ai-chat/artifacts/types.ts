/** Version 1 of our application contract, transported in an AI SDK data-artifact part. */
export interface Artifact {
  schemaVersion: 1;
  id: string;
  /** Monotonically increases for every complete snapshot, including status changes. */
  revision: number;
  status: 'generating' | 'ready' | 'error';
  kind: 'document' | 'spreadsheet' | 'presentation' | 'custom';
  title: string;
  description?: string;
  preview?: ArtifactPreview;
  /** A real server-owned file, not a promise that a preview is an Office binary. */
  file?: ArtifactFile;
  error?: string;
  /** A hint applied once per newly delivered artifact; later updates must not steal focus. */
  autoOpen?: boolean;
}

export interface ArtifactPreview {
  renderer: string;
  version: number;
  data: unknown;
}

export interface ArtifactFile {
  url: string;
  name: string;
  mimeType: string;
  sizeBytes?: number;
}

export interface DocumentPreview {
  markdown: string;
}

export interface SpreadsheetPreview {
  sheets: {
    name: string;
    columns: string[];
    rows: (string | number | boolean | null)[][];
  }[];
}

export interface PresentationPreview {
  slides: {
    id: string;
    title: string;
    subtitle?: string;
    bullets: string[];
    note?: string;
  }[];
}

export interface DashboardPreview {
  title: string;
  period: string;
  kpis: { label: string; value: string; change?: string }[];
  series: { label: string; value: number }[];
  highlights: string[];
}

export type ArtifactState = Record<string, Artifact>;

export type DemoScenarioId = 'document' | 'spreadsheet' | 'presentation' | 'dashboard' | 'long';

export interface DemoScenario {
  id: DemoScenarioId;
  label: string;
  prompt: string;
  description: string;
}
