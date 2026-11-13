import type { Conversation, ConversationHistory, ConversationSnapshot } from './types';

export const MAX_CONVERSATIONS = 50;
export const MAX_TITLE_LENGTH = 80;

export function createConversation(): Conversation {
  const now = new Date().toISOString();
  return {
    id: crypto.randomUUID(),
    title: '新对话',
    titleSource: 'automatic',
    createdAt: now,
    updatedAt: now,
    messages: [],
    artifacts: {},
    draft: '',
    scenario: 'document'
  };
}

export function createHistory(): ConversationHistory {
  const conversation = createConversation();
  return { schemaVersion: 1, activeId: conversation.id, conversations: [conversation] };
}

/** Only canonical SDK messages are saved; display/typewriter messages never enter history. */
export function updateConversation(
  history: ConversationHistory,
  id: string,
  snapshot: ConversationSnapshot
): ConversationHistory {
  const previous = history.conversations.find((item) => item.id === id);
  if (
    !previous ||
    (previous.messages === snapshot.messages &&
      previous.artifacts === snapshot.artifacts &&
      previous.draft === snapshot.draft &&
      previous.draftAttachments === snapshot.draftAttachments &&
      previous.scenario === snapshot.scenario)
  )
    return history;
  const firstUser = snapshot.messages.find((message) => message.role === 'user');
  const textTitle = firstUser?.parts
    .filter((part) => part.type === 'text')
    .map((part) => part.text)
    .join(' ')
    .trim();
  const title = textTitle || firstUser?.parts.find((part) => part.type === 'file')?.filename;
  return {
    ...history,
    conversations: history.conversations.map((item) =>
      item.id !== id
        ? item
        : {
            ...item,
            ...snapshot,
            title:
              item.titleSource === 'automatic' && title
                ? title.slice(0, MAX_TITLE_LENGTH)
                : item.title,
            updatedAt:
              previous.messages === snapshot.messages ? item.updatedAt : new Date().toISOString()
          }
    )
  };
}

export function removeConversation(history: ConversationHistory, id: string): ConversationHistory {
  const conversations = history.conversations.filter((item) => item.id !== id);
  if (!conversations.length) return createHistory();
  return {
    ...history,
    conversations,
    activeId: history.activeId === id ? conversations[0].id : history.activeId
  };
}
