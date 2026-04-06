"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Upload, FileText, Image, Table, Globe, CheckCircle, Loader2, AlertCircle } from "lucide-react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type DocStatus = "queued" | "processing" | "complete" | "error";

interface Document {
  id: string;
  filename: string;
  source_type: string;
  status: DocStatus;
  chunk_count: number | null;
  created_at: string;
}

const TYPE_ICON: Record<string, React.ReactNode> = {
  pdf: <FileText size={16} className="text-red-400" />,
  docx: <FileText size={16} className="text-blue-400" />,
  image: <Image size={16} className="text-purple-400" />,
  csv: <Table size={16} className="text-green-400" />,
  url: <Globe size={16} className="text-yellow-400" />,
};

const STATUS_BADGE: Record<DocStatus, string> = {
  queued: "bg-yellow-900/40 text-yellow-300",
  processing: "bg-blue-900/40 text-blue-300",
  complete: "bg-green-900/40 text-green-300",
  error: "bg-red-900/40 text-red-300",
};

function useToken() {
  if (typeof window === "undefined") return "";
  return localStorage.getItem("nf_token") ?? "";
}

export default function DocumentsPage() {
  const [docs, setDocs] = useState<Document[]>([]);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [urlInput, setUrlInput] = useState("");
  const [error, setError] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const token = useToken();

  const fetchDocs = useCallback(async () => {
    try {
      const res = await fetch(`${API}/documents`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const data = await res.json();
        setDocs(data);
      }
    } catch {
      // ignore
    }
  }, [token]);

  useEffect(() => {
    fetchDocs();
    // Poll every 5s to update statuses
    const id = setInterval(fetchDocs, 5000);
    return () => clearInterval(id);
  }, [fetchDocs]);

  const uploadFile = async (file: File) => {
    setUploading(true);
    setError("");
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await fetch(`${API}/ingest`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: form,
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail ?? "Upload failed");
      }
      await fetchDocs();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  const uploadUrl = async () => {
    if (!urlInput.trim()) return;
    setUploading(true);
    setError("");
    try {
      const res = await fetch(`${API}/ingest/url`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ url: urlInput }),
      });
      if (!res.ok) throw new Error("URL ingest failed");
      setUrlInput("");
      await fetchDocs();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "URL ingest failed");
    } finally {
      setUploading(false);
    }
  };

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      Array.from(e.dataTransfer.files).forEach(uploadFile);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [token]
  );

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      <h1 className="text-2xl font-bold text-white">Documents</h1>

      {/* Upload Zone */}
      <div
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        onClick={() => fileInputRef.current?.click()}
        className={`border-2 border-dashed rounded-xl p-10 text-center cursor-pointer transition-colors
          ${dragging ? "border-sky-400 bg-sky-900/20" : "border-slate-600 hover:border-slate-400"}`}
      >
        <input
          ref={fileInputRef}
          type="file"
          className="hidden"
          accept=".pdf,.docx,.csv,.txt,.jpg,.jpeg,.png,.webp"
          multiple
          onChange={(e) => Array.from(e.target.files ?? []).forEach(uploadFile)}
        />
        {uploading ? (
          <Loader2 className="mx-auto animate-spin text-sky-400" size={32} />
        ) : (
          <Upload className="mx-auto text-slate-400 mb-2" size={32} />
        )}
        <p className="text-slate-300 mt-2">
          {uploading ? "Uploading…" : "Drop files here or click to upload"}
        </p>
        <p className="text-slate-500 text-sm mt-1">PDF, DOCX, CSV, Images — max 100MB</p>
      </div>

      {/* URL Ingest */}
      <div className="flex gap-2">
        <input
          value={urlInput}
          onChange={(e) => setUrlInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && uploadUrl()}
          placeholder="https://example.com/article"
          className="flex-1 bg-slate-800 border border-slate-700 rounded-lg px-4 py-2 text-white placeholder-slate-500 focus:outline-none focus:border-sky-500"
        />
        <button
          onClick={uploadUrl}
          disabled={uploading || !urlInput}
          className="px-4 py-2 bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-white rounded-lg font-medium transition-colors"
        >
          Ingest URL
        </button>
      </div>

      {error && (
        <div className="flex items-center gap-2 text-red-400 bg-red-900/20 border border-red-800 rounded-lg px-4 py-3">
          <AlertCircle size={16} />
          <span className="text-sm">{error}</span>
        </div>
      )}

      {/* Document List */}
      <div className="bg-slate-800/50 border border-slate-700 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-700">
              <th className="text-left px-4 py-3 text-slate-400 font-medium">File</th>
              <th className="text-left px-4 py-3 text-slate-400 font-medium">Type</th>
              <th className="text-left px-4 py-3 text-slate-400 font-medium">Status</th>
              <th className="text-right px-4 py-3 text-slate-400 font-medium">Chunks</th>
              <th className="text-right px-4 py-3 text-slate-400 font-medium">Ingested</th>
            </tr>
          </thead>
          <tbody>
            {docs.length === 0 ? (
              <tr>
                <td colSpan={5} className="text-center py-12 text-slate-500">
                  No documents yet — upload one above
                </td>
              </tr>
            ) : (
              docs.map((doc) => (
                <tr key={doc.id} className="border-b border-slate-700/50 hover:bg-slate-700/30 transition-colors">
                  <td className="px-4 py-3 text-white font-mono text-xs">{doc.filename}</td>
                  <td className="px-4 py-3">
                    <span className="flex items-center gap-1 text-slate-400">
                      {TYPE_ICON[doc.source_type] ?? <FileText size={16} />}
                      {doc.source_type}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[doc.status]}`}>
                      {doc.status === "processing" && (
                        <span className="inline-block w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse" />
                      )}
                      {doc.status === "complete" && <CheckCircle size={11} />}
                      {doc.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right text-slate-400">
                    {doc.chunk_count ?? "—"}
                  </td>
                  <td className="px-4 py-3 text-right text-slate-500 text-xs">
                    {new Date(doc.created_at).toLocaleDateString()}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
