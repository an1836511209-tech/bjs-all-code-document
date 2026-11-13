---
name: ai-chat-artifacts
description: Extend this template's AI chat, conversation history, streaming reasoning, tool-call display, artifact previews, or backend contract. Use for /dashboard/ai-chat and src/features/ai-chat; ordinary CRUD and person-to-person messaging follow their existing feature patterns.
---

# AI Chat and Artifacts

Read [the maintained contract](../../../docs/aichat/artifacts.md) before changing message types, a renderer, or backend integration. Source of truth is `src/features/ai-chat/artifacts/{types,schemas,state}.ts`; registered UI renderers live in `registry.tsx`.

Keep the guide focused on using/configuring the template and integrating a backend. Update it in place; do not commit implementation plans, test-result records, task recaps or model-speed research. Report completed checks in chat; generated browser evidence stays in ignored `coverage/`.

## Conversation history

Read [history and backend integration](../../../docs/aichat/history.md) for session changes; all AI Chat guides live under `docs/aichat/` with an index in `README.md`.

- `AiChatWorkspace` owns history loading/persistence; keyed `AiChatSession` owns one `useChat` instance. Use the same stable conversation ID for React key, SDK ID and request body. Disable session-changing actions throughout transport and presentation activity; stop first to switch. Never let an old response update a different session.
- Keep local persistence behind `history/service.ts`, with explicit schema version, validation, size limits and visible storage failure. Failed reads must not overwrite the original data. Do not silently evict sessions to meet quotas. Coalesce writes; do not serialize full history on each streamed token.
- Preserve canonical message parts, draft, scenario and independent authoritative artifact snapshots. Restore via `collectArtifacts` plus revision merging; never save typewriter-truncated text or auto-open restored artifacts. Interrupted artifacts must not remain spinning or be relabeled as successful.
- New conversation preserves existing history; deleting requires confirmation, manual titles survive future turns, and the last deletion must leave a valid empty conversation. Keep search/navigation keyboard accessible and use the existing Sheet/Dialog/form primitives.
- History uses a flat sidebar with a compact single-line recent list, subtle selection and a per-row more menu. Avoid per-row dates/counts and permanent edit/delete buttons. Keep the menu discoverable on hover, keyboard focus and touch; preserve a centered readable conversation/composer width. Do not add nonfunctional navigation copied from a reference product.
- The local adapter is a browser demo, without identity isolation or multi-tab conflict resolution. For server-backed CRUD use the repository's types/service/queries/mutations pattern; keep token streaming in `useChat`. Document proposed endpoints separately from implemented routes and require backend ownership checks, concurrency and idempotency.
- Update README, AGENTS, related skill links and `scripts/cleanup.js` when moving docs or adding scripts. Run `bun run test:ai-chat:history` in addition to existing AI Chat checks.

## Input images and attachments

Read [input attachments and backend integration](../../../docs/aichat/attachments.md) for composer uploads, clipboard/drop handlers, file parts, or file storage. Input files are distinct from generated artifacts.

- Reuse Attachment primitives and the feature upload queue/service. Keep multi-select, native image paste, plain text paste, drop, attachment-only send, remove/cancel, per-file retry, accessible feedback and mobile layout. Block send until all selected files are ready; block session changes during uploads and release blob URLs/abort requests on removal or unmount.
- Share limits, accepted extensions/MIME and runtime DTO schemas in attachments/types.ts. Enforce actual request body size server-side, validate content and resolve server-owned IDs before generation; do not trust browser MIME/filename/URL. Never forward arbitrary client URLs to a model or file downloader.
- Send standard FileUIPart references only after upload; never persist File, blob URLs or Base64 in canonical messages or history. Preserve ready draft references and backward-compatible history; expired historical files must not erase the transcript or prevent later text-only turns.
- The Node temporary filesystem adapter is a working demo with 24-hour expiry, not authenticated durable storage, document parsing or model comprehension. Document ownership, stable IDs versus signed URLs, retention, content processing and model capability requirements when adapting it.
- Run `bun run test:ai-chat:attachments`, contract tests and history/browser checks. Keep guides, this skill/navigation, AGENTS/README and cleanup script references synchronized.

## Theme integration

Read [the theme contract](../../../docs/aichat/theming.md) for surface or renderer changes. Use the existing data-theme/next-themes providers; do not add a feature-local theme or branch on brand names.

- Pair surface and foreground tokens explicitly, including mobile Sheets and portals. Secondary table headers use secondary-foreground; document/slide canvases use card/card-foreground. User messages can reuse Bubble's paired secondary variant.
- History surfaces and navigation states use sidebar tokens, including sidebar-accent-foreground for selected/hovered actions. Keep the feature-scoped Button extension in conversation-history.module.css; do not patch shared UI primitives or add fixed dark-mode color overrides.
- BI series and legend use chart tokens; reserve primary for actions and destructive for defined negative/error semantics. Artifact payloads carry business data, not CSS or theme instructions.
- Font variables must be on html alongside theme aliases. Do not reset inherited font aliases to initial or rely on body-only variables referenced from html.
- Run `bun run test:ai-chat:themes` across every registered theme and both modes, desktop/mobile, all four previews and portalled surfaces. Compare computed colors with tokens and verify key text contrast, not just class names or one default-theme screenshot. Keep generated evidence in coverage/. Update cleanup when adding a regression script.

## Preserve the interaction

- Keep conversations on the page background, without message avatars or a surrounding card. Use Message/MessageContent and ghost Bubble for assistant prose.
- Current assistant prose/reasoning uses `streaming/use-typewriter-messages.ts`, a display-only queue (~90 graphemes/sec, adaptive catch-up, <=800ms completion tail). Never write its truncated messages back to useChat, persistence, or the backend. Preserve Unicode graphemes, reduced-motion/background handling, immediate stop/error flush and RAF cleanup. No show-all/speed controls; keep tuning in `TYPEWRITER_CONFIG`.
- Keep historical Markdown and the artifact panel stable during animation. Tool/artifact data is never animated or delayed at the event boundary. Run `bun run test:ai-chat:typewriter` for large-chunk display changes as well as the normal browser regression.
- Reuse `ChatMarkdown` (Streamdown) for prose and document previews. Streamdown owns incomplete Markdown repair, GFM and block memoization; keep the official CJK plugin for Chinese punctuation/emphasis and its Tailwind source directive in globals.css; do not add another Markdown parser or repair layer. Keep component/plugin identities stable. Use Streamdown's built-in 120ms character fade (no movement/blur, no additional stagger); honor reduced motion and release animation spans when complete. Do not hand-build character animation DOM. The display queue controls pacing only, releases whole Latin words and punctuation-safe grapheme boundaries to avoid line-end rewrapping, and never changes canonical data. Keep streaming block structure stable at completion.
- Preserve the Markdown boundary: omit Streamdown's raw-HTML plugin while retaining its sanitize/harden plugins, skip HTML, render remote images as placeholders and keep unsafe URLs disabled. Do not enable executable diagrams/HTML from model output. Extra plugins (code/math/diagrams) are opt-in product choices, not template defaults. Validate line geometry across frames, completed block identity and hostile Markdown in the browser when changing this adapter.
- Set `MessageScrollerProvider autoScroll` explicitly; the primitive defaults to false. Keep stable message/tool/artifact IDs. Do not force every update to scroll to the bottom.
- Use the feature's `ChatScrollViewport` wrapper: it delegates End to the primitive `scrollToEnd`, so a growing response cannot leave keyboard navigation at an outdated bottom offset.
- `ChatScrollViewport` composes Base UI ScrollArea onto the **same DOM viewport** as MessageScroller. MessageScroller remains the only follow/anchor owner; ScrollArea measures and drags the sibling thumb. Never nest a second scroll viewport or add another follow hook. Keep native scrollbars and scroll-linked viewport masks disabled in this wrapper. Thumb color/opacity must not depend on hover or `data-autoscrolling`; interpolate height over 120ms and pin its lower edge while the viewport reports `data-scrollable="start"` (the live edge), leaving position updates immediate when browsing history, disable transitions during dragging and reduced motion, and retain forced-colors visibility. A thumb appears only for real overflow; its proportional size must still reflect content growth.
- Thinking has its own bounded scroller. Stop nested wheel, touch and key propagation so reading thinking does not affect conversation following. Verify behavior during streamed growth, not only after completion.
- Tools start collapsed. Show both input and output, including pending, failure and interruption. Running state applies only to the active response; old stopped tools must stay stopped.
- Preview opens beside the conversation on desktop and in an accessible Sheet on narrow screens. Closing a preview must survive later revisions of that same artifact.

## Extend the contract

- AI Chat uses `useChat` + `DefaultChatTransport` + a streaming route; it is an explicit exception to CRUD React Query conventions. The route currently emits scripted data, not real model responses.
- Only validated `data-artifact` parts create/update artifacts. Never infer artifacts from prose, links, filenames or code fences.
- Preserve the v1 envelope, full snapshots and increasing revision. Ignore duplicates/stale revisions. Do not silently change `kind` for an existing ID. Protocol and renderer versions have different responsibilities.
- Add custom data schemas and trusted compiled renderers through the registry. Model data cannot supply executable code. Keep unknown renderer and malformed payload fallbacks.
- Distinguish structured Office previews from real DOCX/XLSX/PPTX files. Show download only for an actual server-owned file. No disguised JSON/HTML downloads with Office extensions.
- Restore history with `collectArtifacts`, and persist full message parts plus authoritative artifact snapshots. The demo has browser-local persistence, without server persistence or authentication.
- Stop/error must end local busy indicators without fabricating a successful result or a server revision. Real background cancellation requires a separate backend contract.

## Validate changes

Run typecheck, lint, contract tests, and the relevant browser regression (`bun run test:ai-chat:browser`, with the dev server running). Browser evidence is saved under ignored `coverage/ai-chat/`. Check desktop/mobile, actual streamed growth, scroll pause/resume, request/result disclosure, preview close/reopen, cancellation and new renderer fallback. For scrollbar changes sample actual thumb geometry/visibility across animation frames in both reasoning and conversation; a stable computed native scrollbar color alone does not establish visual stability. Verify dragging, End, reduced motion and layout resizing. Update the contract document when changing its behavior.

When removing AI Chat from a derived project, use the feature cleanup command so its API route, demo tests, docs and skill are removed with its UI. Do not leave a route importing deleted feature files.
