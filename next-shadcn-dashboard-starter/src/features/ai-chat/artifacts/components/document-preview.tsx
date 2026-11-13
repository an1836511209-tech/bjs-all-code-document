import { ChatMarkdown } from '../../components/chat-markdown';
import type { Artifact, DocumentPreview } from '../types';

interface DocumentPreviewProps {
  data: DocumentPreview;
  artifact: Artifact;
}

export function DocumentArtifactPreview({
  data,
  artifact
}: DocumentPreviewProps): React.JSX.Element {
  return (
    <div className='p-4 sm:p-6 lg:p-8' data-testid='document-preview'>
      <article
        aria-label={artifact.title}
        className='mx-auto min-h-[32rem] max-w-3xl rounded-sm border bg-card px-6 py-10 text-card-foreground shadow-sm sm:px-10 sm:py-12'
      >
        <div className='mb-8 flex items-center justify-between gap-3 border-b pb-4 text-[10px] font-medium tracking-[0.15em] text-muted-foreground uppercase'>
          <span>工作文档</span>
          <span>V{artifact.revision.toString().padStart(2, '0')}</span>
        </div>
        <ChatMarkdown content={data.markdown} />
        <div className='mt-12 border-t pt-4 text-xs text-muted-foreground'>{artifact.title}</div>
      </article>
    </div>
  );
}
