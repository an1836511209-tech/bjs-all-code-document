import { DefaultChatTransport, type UIMessage } from 'ai';
import type { Artifact } from './artifacts/types';

type DemoTools = {
  getRevenue: {
    input: { period: string; currency: string; groupBy: string };
    output: {
      period: string;
      currency: string;
      revenue: number;
      previousRevenue: number;
      changePct: number;
      topDriver: string;
      newCustomers: number;
      newCustomerChangePct: number;
      retentionRate: number;
      source: string;
    };
  };
  createArtifact: {
    input: { kind: string; source: string; format: string };
    output: { artifactId: string; status: string; previewOnly: boolean };
  };
};

export type DemoUIMessage = UIMessage<unknown, { artifact: Artifact }, DemoTools>;

/** Real HTTP/SSE integration; the route uses deterministic data and needs no model key. */
export const chatTransport = new DefaultChatTransport<DemoUIMessage>({
  api: '/api/ai-chat'
});

export const initialMessages: DemoUIMessage[] = [];

export { demoScenarios, DEMO_SCENARIOS, LONG_DEMO_PROMPT } from './artifacts/demo-data';
export type { DemoScenario, DemoScenarioId } from './artifacts/types';
