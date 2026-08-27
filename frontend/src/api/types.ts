import type { z } from "zod";

import type {
  confirmRequestSchema,
  conversationMessageRequestSchema,
  conversationResponseSchema,
  partialTripRequirementsSchema,
  streamBusinessEventSchema,
  threadStateResponseSchema,
  travelPlanSchema,
} from "./schemas";

export type PartialTripRequirements = z.infer<typeof partialTripRequirementsSchema>;
export type ConversationResponse = z.infer<typeof conversationResponseSchema>;
export type ConversationMessageRequest = z.infer<typeof conversationMessageRequestSchema>;
export type ConfirmRequest = z.infer<typeof confirmRequestSchema>;
export type TravelPlan = z.infer<typeof travelPlanSchema>;
export type StreamBusinessEvent = z.infer<typeof streamBusinessEventSchema>;
export type ThreadStateResponse = z.infer<typeof threadStateResponseSchema>;
export type SearchKind = "flights" | "hotels" | "attractions" | "weather" | "route";

export interface PublicReview {
  reviewRound: number;
  decision: "accept" | "revise" | "forced_finalize";
  scores: {
    completeness: number;
    feasibility: number;
    personalization: number;
    budget_fit: number;
    overall_score: number;
  };
  critique: string;
}
