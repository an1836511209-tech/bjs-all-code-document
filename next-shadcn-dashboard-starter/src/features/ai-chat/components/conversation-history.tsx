'use client';

import { useState } from 'react';
import { z } from 'zod';
import { Icons } from '@/components/icons';
import { Button } from '@/components/ui/button';
import { InputGroup, InputGroupAddon, InputGroupInput } from '@/components/ui/input-group';
import { Empty, EmptyHeader, EmptyTitle, EmptyDescription } from '@/components/ui/empty';
import {
  Dialog,
  DialogContent,
  DialogTitle,
  DialogDescription,
  DialogFooter
} from '@/components/ui/dialog';
import { FieldGroup } from '@/components/ui/field';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu';
import { useAppForm } from '@/lib/form';
import { cn } from '@/lib/utils';
import styles from './conversation-history.module.css';
import { MAX_TITLE_LENGTH } from '../history/state';
import type { Conversation } from '../history/types';

interface ConversationHistoryProps {
  conversations: Conversation[];
  activeId: string;
  busy: boolean;
  onSelect: (id: string) => void;
  onCreate: () => void;
  onRename: (id: string, title: string) => void;
  onDelete: (id: string) => void;
  onClose: () => void;
}

export function ConversationHistory({
  conversations,
  activeId,
  busy,
  onSelect,
  onCreate,
  onRename,
  onDelete,
  onClose
}: ConversationHistoryProps) {
  const [search, setSearch] = useState('');
  const [action, setAction] = useState<{
    kind: 'rename' | 'delete';
    conversation: Conversation;
  } | null>(null);
  const filtered = conversations
    .filter((item) => item.title.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()))
    .toSorted((a, b) => b.updatedAt.localeCompare(a.updatedAt));
  return (
    <div
      className='flex h-full min-h-0 flex-col gap-5 px-3 py-4'
      data-testid='conversation-history'
    >
      <div className='flex h-8 items-center justify-between gap-2 px-2'>
        <span className='flex items-center gap-2.5 text-base font-semibold tracking-tight'>
          <Icons.sparkles className='size-5 text-sidebar-foreground/70' />
          AI 工作空间
        </span>
        <Button
          variant='ghost'
          size='icon-sm'
          className={styles.action}
          aria-label='收起历史会话'
          onClick={onClose}
        >
          <Icons.panelLeft />
        </Button>
      </div>
      <div className='flex flex-col gap-2'>
        <InputGroup className='bg-background text-foreground shadow-none'>
          <InputGroupAddon>
            <Icons.search />
          </InputGroupAddon>
          <InputGroupInput
            aria-label='搜索历史会话'
            placeholder='搜索会话标题…'
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </InputGroup>
        <Button
          variant='ghost'
          className={cn(styles.action, 'h-10 justify-start gap-3 px-3')}
          disabled={busy}
          onClick={onCreate}
          data-testid='new-conversation'
        >
          <Icons.edit data-icon='inline-start' />
          新建对话
        </Button>
      </div>
      <div className='flex min-h-0 flex-1 flex-col gap-2'>
        <h2 className='px-3 text-xs font-medium text-sidebar-foreground/70'>最近对话</h2>
        <nav aria-label='历史会话列表' className='min-h-0 flex-1 overflow-y-auto'>
          {filtered.length ? (
            <ul className='flex flex-col gap-1'>
              {filtered.map((item) => (
                <li
                  key={item.id}
                  className='group/history relative min-w-0'
                  data-testid='conversation-row'
                >
                  <Button
                    variant='ghost'
                    className={cn(
                      styles.action,
                      'h-10 w-full min-w-0 justify-start pr-10 pl-3 focus-visible:ring-sidebar-ring'
                    )}
                    disabled={busy}
                    aria-current={activeId === item.id ? 'page' : undefined}
                    title={item.title}
                    onClick={() => onSelect(item.id)}
                    data-testid='select-conversation'
                  >
                    <span className='truncate'>{item.title}</span>
                  </Button>
                  <DropdownMenu>
                    <DropdownMenuTrigger
                      render={<Button variant='ghost' size='icon-sm' />}
                      className={cn(
                        styles.action,
                        'absolute top-1 right-1 opacity-0 group-hover/history:opacity-100 group-focus-within/history:opacity-100 data-popup-open:opacity-100 [@media(hover:none)]:opacity-100'
                      )}
                      aria-label={`会话操作：${item.title}`}
                      disabled={busy}
                    >
                      <Icons.ellipsis />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align='start' side='right' className='w-40'>
                      <DropdownMenuGroup>
                        <DropdownMenuItem
                          onClick={() => setAction({ kind: 'rename', conversation: item })}
                        >
                          <Icons.edit />
                          重命名
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          variant='destructive'
                          onClick={() => setAction({ kind: 'delete', conversation: item })}
                        >
                          <Icons.trash />
                          删除会话
                        </DropdownMenuItem>
                      </DropdownMenuGroup>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </li>
              ))}
            </ul>
          ) : (
            <Empty>
              <EmptyHeader>
                <EmptyTitle>没有匹配的会话</EmptyTitle>
                <EmptyDescription>试试其他标题关键词。</EmptyDescription>
              </EmptyHeader>
            </Empty>
          )}
        </nav>
      </div>
      <p className='px-3 text-[11px] leading-5 text-sidebar-foreground/70' role='status'>
        {busy ? '请先停止生成，再切换对话' : '对话仅保存在此浏览器'}
      </p>
      <Dialog
        open={action !== null}
        onOpenChange={(open) => {
          if (!open) setAction(null);
        }}
      >
        <DialogContent>
          <DialogTitle>{action?.kind === 'rename' ? '重命名会话' : '删除会话'}</DialogTitle>
          <DialogDescription>
            {action?.kind === 'rename'
              ? '为这段对话设置一个便于查找的标题。'
              : `确定删除“${action?.conversation.title ?? ''}”？消息和成果预览将一并移除，无法撤销。`}
          </DialogDescription>
          {action?.kind === 'rename' ? (
            <RenameConversation
              key={action.conversation.id}
              conversation={action.conversation}
              onCancel={() => setAction(null)}
              onSave={(title) => {
                onRename(action.conversation.id, title);
                setAction(null);
              }}
            />
          ) : (
            <DialogFooter>
              <Button variant='outline' onClick={() => setAction(null)}>
                取消
              </Button>
              <Button
                variant='destructive'
                disabled={busy}
                onClick={() => {
                  if (action) onDelete(action.conversation.id);
                  setAction(null);
                }}
              >
                确认删除
              </Button>
            </DialogFooter>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

function RenameConversation({
  conversation,
  onSave,
  onCancel
}: {
  conversation: Conversation;
  onSave: (title: string) => void;
  onCancel: () => void;
}) {
  const form = useAppForm({
    defaultValues: { title: conversation.title },
    validators: {
      onSubmit: z.object({
        title: z.string().trim().min(1, '请输入会话标题').max(MAX_TITLE_LENGTH)
      })
    },
    onSubmit: ({ value }) => onSave(value.title.trim())
  });
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        event.stopPropagation();
        void form.handleSubmit();
      }}
      className='flex flex-col gap-4'
    >
      <FieldGroup>
        <form.AppField
          name='title'
          children={(field) => (
            <field.TextField label='会话标题' maxLength={MAX_TITLE_LENGTH} autoFocus required />
          )}
        />
      </FieldGroup>
      <DialogFooter>
        <Button type='button' variant='outline' onClick={onCancel}>
          取消
        </Button>
        <Button type='submit'>保存标题</Button>
      </DialogFooter>
    </form>
  );
}
