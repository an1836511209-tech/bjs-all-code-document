import PageContainer from '@/components/layout/page-container';
import { AiChatWorkspace } from '@/features/ai-chat/components/ai-chat-workspace';

export const metadata = {
  title: 'Dashboard: AI Chat'
};

export default function Page() {
  return (
    <PageContainer>
      <AiChatWorkspace />
    </PageContainer>
  );
}
