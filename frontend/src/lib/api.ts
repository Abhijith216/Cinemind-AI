/**
 * Typed client for the CineMind backend (Phase 10 API surface).
 *
 * Types mirror the backend Pydantic response models one-to-one, so a
 * generated client can later replace the hand-written ones without touching
 * call sites. Base URL: NEXT_PUBLIC_API_BASE_URL (see .env.example).
 */

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

let authToken: string | null = null;

/** Store a JWT for authenticated calls (register/login set this). */
export function setAuthToken(token: string | null): void {
  authToken = token;
}

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((init?.headers as Record<string, string>) ?? {}),
  };
  if (authToken) headers.Authorization = `Bearer ${authToken}`;

  const response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });
  if (!response.ok) {
    let detail = `API error ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* non-JSON error body — keep the generic message */
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

// --- schemas mirroring backend/app/schemas -------------------------------------------

export interface HealthResponse {
  status: string;
  version: string;
  database: "up" | "down";
}

/** schemas/auth.py */
export interface UserOut {
  id: string;
  email: string;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: "bearer";
  user: UserOut;
}

/** schemas/common.py */
export interface MoviePersonalityOut {
  emotion: number;
  mind_blowing: number;
  darkness: number;
  humor: number;
  violence: number;
  romance: number;
  hopefulness: number;
  plot_complexity: number;
  rewatchability: number;
}

export interface MovieOut {
  id: string;
  tmdb_id: number;
  title: string;
  overview: string | null;
  release_year: number | null;
  runtime: number | null;
  genres: string[];
  keywords: string[];
  language: string | null;
  poster_path: string | null;
  vote_average: number | null;
  vote_count: number | null;
  popularity: number | null;
  personality: MoviePersonalityOut | null;
}

/** schemas/retrieval.py */
export interface SearchFilters {
  genres: string[];
  languages: string[];
  min_rating: number | null;
  min_release_year: number | null;
  max_release_year: number | null;
}

export interface ComponentScores {
  semantic_similarity: number;
  user_history_match: number;
  genre_similarity: number;
  normalized_rating: number;
  normalized_popularity: number;
}

export interface RankedMovieOut {
  movie: MovieOut;
  final_score: number;
  components: ComponentScores;
}

export interface SearchResponse {
  query: string;
  results: RankedMovieOut[];
  applied_weights: Record<string, number>;
}

export interface SearchRequest {
  query: string;
  filters?: Partial<SearchFilters>;
  user_id?: string | null;
  limit?: number;
}

/** schemas/explanation.py */
export interface MatchedAttributes {
  genres: string[];
  themes: string[];
  personality_traits: string[];
  intent_matches: string[];
  loved_movie_overlaps: { kind: string; label: string; detail: string | null }[];
}

/** schemas/chat.py */
export interface ChatMovieOut {
  movie: MovieOut;
  final_score: number;
  explanation: string;
  matched_attributes: MatchedAttributes;
}

export interface ChatMessageRequest {
  message: string;
  session_id?: string | null;
  user_id?: string | null;
  result_limit?: number;
}

export interface ChatTurnResponse {
  session_id: string;
  reply: string;
  asked_clarifying_question: boolean;
  intent: Record<string, unknown> | null;
  results: ChatMovieOut[];
}

export interface ChatStoredMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  intent: Record<string, unknown> | null;
  result_movie_ids: string[] | null;
  created_at: string;
}

export interface ChatSessionOut {
  id: string;
  user_id: string | null;
  created_at: string | null;
  messages: ChatStoredMessage[];
}

/** schemas/taste.py */
export interface RatingCreate {
  user_id: string;
  movie_id: string;
  score: number; // 1-10
}

export interface RatingOut {
  id: string;
  user_id: string;
  movie_id: string;
  score: number;
  rated_at: string;
  created: boolean;
}

export interface TasteProfileOut {
  user_id: string;
  likes: string[];
  dislikes: string[];
  favorite_themes: string[];
  updated_at: string | null;
}

export interface TasteSnapshotOut {
  user_id: string;
  month: string; // "2026-09"
  dominant_genres: string[];
  dominant_themes: string[];
  created_at: string | null;
}

/** schemas/graph.py */
export interface GraphMovie {
  id: string;
  title: string;
  release_year: number | null;
  poster_path: string | null;
  score: number | null;
}

export interface GraphEdge {
  to_movie_id: string;
  shared_genres: string[];
  shared_keywords: string[];
}

export interface RecommendationGraph {
  movie: GraphMovie;
  rated_movies: GraphMovie[];
  edges: GraphEdge[];
  note: string | null;
}

// --- endpoint wrappers ---------------------------------------------------------------

export const api = {
  health: () => request<HealthResponse>("/health"),

  auth: {
    register: (email: string, password: string) =>
      request<TokenResponse>("/api/auth/register", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      }),
    login: (email: string, password: string) =>
      request<TokenResponse>("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      }),
  },

  movies: {
    get: (movieId: string) =>
      request<MovieOut>(`/api/movies/${movieId}`),
    recommendationGraph: (movieId: string, userId?: string | null) =>
      request<RecommendationGraph>(
        `/api/movies/${movieId}/recommendation-graph${
          userId ? `?user_id=${encodeURIComponent(userId)}` : ""
        }`,
      ),
  },

  search: {
    hybrid: (payload: SearchRequest) =>
      request<SearchResponse>("/api/search/hybrid", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
  },

  chat: {
    sendMessage: (payload: ChatMessageRequest) =>
      request<ChatTurnResponse>("/api/chat/message", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    getSession: (sessionId: string) =>
      request<ChatSessionOut>(`/api/chat/sessions/${sessionId}`),
  },

  ratings: {
    create: (payload: RatingCreate) =>
      request<RatingOut>("/api/ratings", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
  },

  users: {
    tasteProfile: (userId: string) =>
      request<TasteProfileOut>(`/api/users/${userId}/taste-profile`),
    tasteEvolution: (userId: string) =>
      request<TasteSnapshotOut[]>(`/api/users/${userId}/taste-evolution`),
  },
};
