import type { UIMessage } from 'ai';
import { parseArtifact, type PreviewValidators } from './schemas';
import type { ArtifactState } from './types';
export type { ArtifactState } from './types';

/** Full snapshots make replay idempotent: a newer revision always wins. */
export function reduceArtifact(
  state: ArtifactState,
  input: unknown,
  validators?: PreviewValidators
): ArtifactState {
  const artifact = parseArtifact(input, validators);
  if (!artifact) return state;
  const previous = Object.prototype.hasOwnProperty.call(state, artifact.id)
    ? state[artifact.id]
    : undefined;
  if (previous && (artifact.revision <= previous.revision || artifact.kind !== previous.kind)) {
    return state;
  }
  return { ...state, [artifact.id]: artifact };
}

/** Use onData + reduceArtifact while streaming; use this to hydrate persisted history. */
export function collectArtifacts(
  messages: readonly UIMessage[],
  validators?: PreviewValidators
): ArtifactState {
  return messages.reduce<ArtifactState>((state, message) => {
    if (message.role !== 'assistant') return state;
    return message.parts.reduce((current, part) => {
      if (part.type !== 'data-artifact') return current;
      return reduceArtifact(current, part.data, validators);
    }, state);
  }, {});
}
