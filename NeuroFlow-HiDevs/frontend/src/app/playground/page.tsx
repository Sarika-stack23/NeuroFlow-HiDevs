"use client";
import { useState, useEffect } from "react";
import { Send, ThumbsUp, ThumbsDown, ChevronRight } from "lucide-react";
import { getPipelines, submitQuery, patchRating } from "@/lib/api";
import { useSSEStream } from "@/hooks/useSSEStream";

export default function PlaygroundPage() {
  const [pipelines, setPipelines] = useState<any[]>([]);
  const [selectedPipeline, setSelectedPipeline] = useState("");
  const [query, setQuery] = useState("");
  const [runId, setRunId] = useState<string | null>(null);
  const [sources, setSources] = useState<string[]>([]);
  const [citations, setCitations] = useState<any[]>([]);
  const [selectedChunk, setSelectedChunk] = useState<any>(null);
  const { tokens, events, isStreaming, isDone, error, startStream, reset } = useSSEStream();

  useEffect(() => {
    getPipelines().then((data) => {
      setPipelines(data);
      if (data.length > 0) setSelectedPipeline(data[0].id);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    for (const event of events) {
      if (event.type === "retrieval_complete") setSources(event.sources || []);
      if (event.type === "done") setCitations(event.citations || []);
    }
  }, [events]);

  const handleSubmit = async () => {
    if (!query.trim() || !selectedPipeline) return;
    reset();
    setSources([]);
    setCitations([]);
    setRunId(null);
    try {
      const data = await submitQuery(query, selectedPipeline);
      setRunId(data.run_id);
      startStream(data.run_id);
    } catch (e: any) {
      console.error(e);
    }
  };

  const handleRate = async (rating: number) => {
    if (runId) await patchRating(runId, rating).catch(() => {});
  };

  return (
    <div className="flex h-full">
      {/* Main panel */}
      <div className="flex-1 flex flex-col p-6 gap-4 max-w-3xl">
        <h1 className="text-2xl font-bold text-white">Query Playground</h1>

        {/* Pipeline selector */}
        <div className="flex gap-3 items-center">
          <label className="text-sm text-gray-400 shrink-0">Pipeline</label>
          <select
            value={selectedPipeline}
            onChange={(e) => setSelectedPipeline(e.target.value)}
            className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:border-indigo-500"
          >
            {pipelines.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name} {p.avg_score ? `(${Number(p.avg_score).toFixed(2)})` : ""}
              </option>
            ))}
            {pipelines.length === 0 && <option value="">No pipelines — create one first</option>}
          </select>
        </div>

        {/* Query input */}
        <div className="relative">
          <textarea
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && e.metaKey) handleSubmit(); }}
            placeholder="Ask a question about your documents… (⌘+Enter to submit)"
            rows={3}
            className="w-full bg-gray-800 border border-gray-700 rounded-xl px-4 py-3 text-sm text-white resize-none focus:outline-none focus:border-indigo-500 pr-12"
          />
          <button
            onClick={handleSubmit}
            disabled={isStreaming || !selectedPipeline}
            className="absolute bottom-3 right-3 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-white rounded-lg p-2 transition-colors"
          >
            <Send size={15} />
          </button>
        </div>

        {/* Sources */}
        {sources.length > 0 && (
          <div className="flex flex-wrap gap-2">
            <span className="text-xs text-gray-500">Sources:</span>
            {sources.map((s, i) => (
              <span key={i} className="bg-gray-800 border border-gray-700 rounded px-2 py-0.5 text-xs text-indigo-300">
                {s}
              </span>
            ))}
          </div>
        )}

        {/* Response */}
        {(tokens || isStreaming) && (
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 text-sm text-gray-100 leading-relaxed whitespace-pre-wrap min-h-[100px]">
            {tokens}
            {isStreaming && <span className="animate-pulse text-indigo-400">▍</span>}
          </div>
        )}

        {error && (
          <div className="bg-red-950 border border-red-800 rounded-xl p-4 text-sm text-red-300">{error}</div>
        )}

        {/* Citations */}
        {isDone && citations.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {citations.map((c, i) => (
              <button
                key={i}
                onClick={() => setSelectedChunk(c)}
                className="bg-indigo-950 hover:bg-indigo-900 border border-indigo-800 text-indigo-300 text-xs rounded-lg px-3 py-1 flex items-center gap-1 transition-colors"
              >
                {c.source} <ChevronRight size={12} />
              </button>
            ))}
          </div>
        )}

        {/* Feedback */}
        {isDone && runId && (
          <div className="flex gap-2 items-center">
            <span className="text-xs text-gray-500">Was this helpful?</span>
            <button onClick={() => handleRate(5)} className="text-gray-400 hover:text-green-400 transition-colors">
              <ThumbsUp size={16} />
            </button>
            <button onClick={() => handleRate(1)} className="text-gray-400 hover:text-red-400 transition-colors">
              <ThumbsDown size={16} />
            </button>
          </div>
        )}
      </div>

      {/* Citation drawer */}
      {selectedChunk && (
        <div className="w-80 bg-gray-900 border-l border-gray-800 p-5 overflow-auto">
          <div className="flex justify-between items-center mb-3">
            <h3 className="text-sm font-semibold text-white">{selectedChunk.source}</h3>
            <button onClick={() => setSelectedChunk(null)} className="text-gray-500 hover:text-white text-lg">×</button>
          </div>
          <div className="text-xs text-gray-400 mb-2">{selectedChunk.document}{selectedChunk.page ? ` · Page ${selectedChunk.page}` : ""}</div>
          <div className="text-xs text-gray-300 leading-relaxed">
            {selectedChunk.content_preview || "Click to load chunk content."}
          </div>
        </div>
      )}
    </div>
  );
}
