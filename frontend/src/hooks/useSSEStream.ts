"use client";
import { useCallback, useRef, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface StreamEvent {
  type: string;
  delta?: string;
  chunk_count?: number;
  sources?: string[];
  citations?: Array<{ source: string; chunk_id: string; document: string; page?: number }>;
  run_id?: string;
  message?: string;
}

interface UseSSEStreamResult {
  tokens: string;
  events: StreamEvent[];
  isStreaming: boolean;
  isDone: boolean;
  error: string | null;
  startStream: (runId: string) => void;
  reset: () => void;
}

export function useSSEStream(): UseSSEStreamResult {
  const [tokens, setTokens] = useState("");
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [isDone, setIsDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const esRef = useRef<EventSource | null>(null);

  const reset = useCallback(() => {
    esRef.current?.close();
    setTokens("");
    setEvents([]);
    setIsStreaming(false);
    setIsDone(false);
    setError(null);
  }, []);

  const startStream = useCallback((runId: string) => {
    reset();
    const token = typeof window !== "undefined" ? localStorage.getItem("neuroflow_token") : "";
    const url = `${API_BASE}/query/${runId}/stream`;
    const es = new EventSource(url);
    esRef.current = es;
    setIsStreaming(true);

    es.onmessage = (e) => {
      try {
        const data: StreamEvent = JSON.parse(e.data);
        setEvents((prev) => [...prev, data]);

        if (data.type === "token" && data.delta) {
          setTokens((prev) => prev + data.delta);
        }
        if (data.type === "done") {
          setIsStreaming(false);
          setIsDone(true);
          es.close();
        }
        if (data.type === "error") {
          setError(data.message || "Stream error");
          setIsStreaming(false);
          es.close();
        }
      } catch {}
    };

    es.onerror = () => {
      setError("Connection error");
      setIsStreaming(false);
      es.close();
    };
  }, [reset]);

  return { tokens, events, isStreaming, isDone, error, startStream, reset };
}
