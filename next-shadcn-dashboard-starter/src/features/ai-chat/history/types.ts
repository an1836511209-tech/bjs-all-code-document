import type { UploadedAttachment } from '../attachments/types';
import type { DemoUIMessage } from '../chat';
import type { ArtifactState } from '../artifacts/types';

export interface ConversationSnapshot {
  messages: DemoUIMessage[];
  artifacts: ArtifactState;
  draft: string;
  draftAttachments?: UploadedAttachment[];
  scenario: string;
}

export interface Conversation extends ConversationSnapshot {
  id: string;
  title: string;
  titleSource: 'automatic' | 'manual';
  createdAt: string;
  updatedAt: string;
}

export interface ConversationHistory {
  schemaVersion: 1;
  activeId: string;
  conversations: Conversation[];
}
