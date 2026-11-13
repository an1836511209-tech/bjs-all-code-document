import { z } from 'zod';
import type { Artifact } from './types';

export function isSafeDownloadUrl(value: string): boolean {
  if (
    /[\s\\]/.test(value) ||
    Array.from(value).some((character) => {
      const code = character.charCodeAt(0);
      return code < 32 || code === 127;
    })
  )
    return false;
  if (value.startsWith('/') && !value.startsWith('//')) return true;
  try {
    const url = new URL(value);
    return (
      (url.protocol === 'https:' || url.protocol === 'http:') && !url.username && !url.password
    );
  } catch {
    return false;
  }
}

export const documentPreviewSchema = z.object({
  markdown: z.string().max(200_000)
});

export const spreadsheetPreviewSchema = z.object({
  sheets: z
    .array(
      z
        .object({
          name: z.string().min(1).max(100),
          columns: z.array(z.string().max(200)).min(1).max(100),
          rows: z
            .array(z.array(z.union([z.string(), z.number(), z.boolean(), z.null()])))
            .max(5_000)
        })
        .refine(
          (sheet) => sheet.rows.every((row) => row.length === sheet.columns.length),
          'Each row must match the column count'
        )
    )
    .min(1)
    .max(20)
});

export const presentationPreviewSchema = z.object({
  slides: z
    .array(
      z.object({
        id: z.string().min(1),
        title: z.string().min(1).max(300),
        subtitle: z.string().max(1_000).optional(),
        bullets: z.array(z.string().max(2_000)).max(20),
        note: z.string().max(5_000).optional()
      })
    )
    .min(1)
    .max(100)
    .refine(
      (slides) => new Set(slides.map((slide) => slide.id)).size === slides.length,
      'Slide ids must be unique'
    )
});

export const dashboardPreviewSchema = z.object({
  title: z.string().min(1).max(300),
  period: z.string().max(100),
  kpis: z
    .array(
      z.object({
        label: z.string(),
        value: z.string(),
        change: z.string().optional()
      })
    )
    .min(1)
    .max(20),
  series: z.array(z.object({ label: z.string(), value: z.number() })).max(1_000),
  highlights: z.array(z.string()).max(30)
});

/** Extension keys include renderer version, e.g. 'company.capacity:1'. */
export type PreviewValidators = Readonly<Record<string, z.ZodType>>;

export const builtinPreviewValidators: PreviewValidators = {
  'document:1': documentPreviewSchema,
  'spreadsheet:1': spreadsheetPreviewSchema,
  'presentation:1': presentationPreviewSchema,
  'bi-dashboard:1': dashboardPreviewSchema
};

export const artifactSchema = z
  .object({
    schemaVersion: z.literal(1),
    id: z.string().min(1).max(200),
    revision: z.number().int().positive(),
    status: z.enum(['generating', 'ready', 'error']),
    kind: z.enum(['document', 'spreadsheet', 'presentation', 'custom']),
    title: z.string().min(1).max(300),
    description: z.string().max(2_000).optional(),
    preview: z
      .object({
        renderer: z.string().min(1).max(100),
        version: z.number().int().positive(),
        data: z.json()
      })
      .optional(),
    file: z
      .object({
        url: z.string().max(4_000).refine(isSafeDownloadUrl, 'Unsafe download URL'),
        name: z.string().min(1).max(300),
        mimeType: z.string().min(1).max(150),
        sizeBytes: z.number().int().nonnegative().optional()
      })
      .optional(),
    error: z.string().min(1).max(2_000).optional(),
    autoOpen: z.boolean().optional()
  })
  .superRefine((artifact, ctx) => {
    if (artifact.status === 'ready' && !artifact.preview && !artifact.file) {
      ctx.addIssue({ code: 'custom', message: 'Ready requires a preview or file' });
    }
    if (artifact.status === 'error' && !artifact.error) {
      ctx.addIssue({ code: 'custom', message: 'Error requires a readable message' });
    }
  });

/** Validate the envelope and known renderer payloads; unknown renderers use a safe UI fallback. */
export function parseArtifact(
  input: unknown,
  validators: PreviewValidators = builtinPreviewValidators
): Artifact | null {
  const result = artifactSchema.safeParse(input);
  if (!result.success) return null;
  const artifact = result.data;
  if (artifact.preview) {
    const key = `${artifact.preview.renderer}:${artifact.preview.version}`;
    const validator = Object.prototype.hasOwnProperty.call(validators, key)
      ? validators[key]
      : undefined;
    if (validator && !validator.safeParse(artifact.preview.data).success) {
      return null;
    }
  }
  return artifact;
}
