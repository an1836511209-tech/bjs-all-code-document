'use client';

/* oxlint-disable jsx-a11y/no-noninteractive-tabindex -- Keyboard users need to focus and scroll the data region to reach every column. */

import { Icons } from '@/components/icons';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import type { Artifact, SpreadsheetPreview } from '../types';

interface SpreadsheetPreviewProps {
  data: SpreadsheetPreview;
  artifact: Artifact;
}

function columnLabel(index: number): string {
  let remaining = index + 1;
  let label = '';
  while (remaining > 0) {
    remaining -= 1;
    label = String.fromCharCode(65 + (remaining % 26)) + label;
    remaining = Math.floor(remaining / 26);
  }
  return label;
}

export function SpreadsheetArtifactPreview({
  data,
  artifact
}: SpreadsheetPreviewProps): React.JSX.Element {
  return (
    <div className='p-4 sm:p-6' data-testid='spreadsheet-preview'>
      <div className='mb-5 flex items-center gap-3'>
        <span className='flex size-10 shrink-0 items-center justify-center rounded-xl border bg-background'>
          <Icons.fileTypeXls className='size-5 text-muted-foreground' aria-hidden='true' />
        </span>
        <div className='min-w-0'>
          <h3 className='truncate text-base font-semibold'>{artifact.title}</h3>
          <p className='mt-1 text-xs text-muted-foreground'>
            {data.sheets.length} 个工作表 · 数据预览
          </p>
        </div>
      </div>
      <Tabs defaultValue='0' className='gap-0 overflow-hidden rounded-xl border bg-background'>
        {data.sheets.map((sheet, sheetIndex) => (
          <TabsContent key={sheetIndex} value={String(sheetIndex)} className='min-w-0'>
            <div
              className='max-h-[65dvh] overflow-auto overscroll-contain'
              tabIndex={0}
              role='region'
              aria-label={`${sheet.name} 数据表，可滚动查看`}
            >
              <table className='w-full border-collapse text-left text-sm tabular-nums'>
                <caption className='sr-only'>
                  {sheet.name}，{sheet.rows.length} 行，{sheet.columns.length} 列
                </caption>
                <thead className='sticky top-0 z-10 bg-muted'>
                  <tr className='text-center text-[11px] font-normal text-muted-foreground'>
                    <th className='w-10 min-w-10 border-r border-b p-2' aria-label='行号' />
                    {sheet.columns.map((_, index) => (
                      <th
                        key={index}
                        className='min-w-28 border-r border-b px-3 py-1.5 font-normal'
                      >
                        {columnLabel(index)}
                      </th>
                    ))}
                  </tr>
                  <tr
                    className='bg-secondary text-xs text-secondary-foreground'
                    data-testid='spreadsheet-column-header'
                  >
                    <th className='border-r border-b p-2 text-center font-normal text-secondary-foreground/70'>
                      1
                    </th>
                    {sheet.columns.map((column, index) => (
                      <th
                        key={index}
                        scope='col'
                        className='border-r border-b px-4 py-3 font-semibold whitespace-nowrap'
                      >
                        {column}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {sheet.rows.map((row, rowIndex) => (
                    <tr key={rowIndex} className='transition-colors hover:bg-muted/40'>
                      <th
                        scope='row'
                        className='border-r border-b bg-muted/40 p-2 text-center text-[11px] font-normal text-muted-foreground'
                      >
                        {rowIndex + 2}
                      </th>
                      {sheet.columns.map((_, columnIndex) => (
                        <td
                          key={columnIndex}
                          className='max-w-80 min-w-28 border-r border-b px-4 py-3 align-top break-words'
                        >
                          {row[columnIndex] == null ? '—' : String(row[columnIndex])}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
              {sheet.rows.length === 0 && (
                <p className='p-8 text-center text-sm text-muted-foreground'>此工作表暂无数据。</p>
              )}
            </div>
            <div className='flex justify-end border-t px-4 py-2 text-[11px] text-muted-foreground'>
              {sheet.rows.length} 行 × {sheet.columns.length} 列
            </div>
          </TabsContent>
        ))}
        <div className='overflow-x-auto border-t bg-muted/30 px-2 py-2'>
          <TabsList aria-label='工作表' className='h-8 bg-transparent'>
            {data.sheets.map((sheet, index) => (
              <TabsTrigger key={index} value={String(index)} className='px-3 text-xs'>
                <Icons.fileTypeXls className='size-3.5' aria-hidden='true' />
                {sheet.name}
              </TabsTrigger>
            ))}
          </TabsList>
        </div>
      </Tabs>
    </div>
  );
}
