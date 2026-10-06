"use client";

import React, { useState, useEffect } from "react";
import { X, BookOpen, Database, Sparkles, Layers } from "lucide-react";
import { RAGChunk, fetchRAGDocs } from "@/services/api";

interface RAGKnowledgeModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const RAGKnowledgeModal: React.FC<RAGKnowledgeModalProps> = ({ isOpen, onClose }) => {
  const [docs, setDocs] = useState<RAGChunk[]>([]);
  const [selectedDoc, setSelectedDoc] = useState<RAGChunk | null>(null);

  useEffect(() => {
    if (isOpen) {
      fetchRAGDocs()
        .then((res) => {
          setDocs(res.documents);
          if (res.documents.length > 0) setSelectedDoc(res.documents[0]);
        })
        .catch(console.error);
    }
  }, [isOpen]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-in fade-in duration-150">
      <div className="relative w-full max-w-2xl rounded-2xl bg-card border border-border p-6 shadow-2xl flex flex-col max-h-[85vh]">
        {/* Header */}
        <div className="flex items-center justify-between pb-4 border-b border-border">
          <div className="flex items-center gap-2">
            <div className="p-1.5 rounded-lg bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
              <Database className="h-5 w-5" />
            </div>
            <div>
              <h3 className="text-base font-semibold text-white">RAG Knowledge Base & Context Layer</h3>
              <p className="text-xs text-gray-400">Indexed Smart Contract ABIs, Solidity Specs & Guardrail Rules</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-lg text-gray-400 hover:text-white hover:bg-cardHover transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Content Body */}
        <div className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-4 flex-1 overflow-hidden">
          {/* List */}
          <div className="space-y-2 overflow-y-auto pr-1">
            <span className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider block">Tài liệu đã nạp</span>
            {docs.map((d) => (
              <button
                key={d.id}
                onClick={() => setSelectedDoc(d)}
                className={`w-full text-left p-2.5 rounded-xl border text-xs transition-all ${
                  selectedDoc?.id === d.id
                    ? "bg-indigo-600/20 border-indigo-500 text-white"
                    : "bg-background border-border text-gray-400 hover:text-gray-200"
                }`}
              >
                <div className="font-medium truncate">{d.title}</div>
                <div className="text-[10px] text-indigo-400 mt-0.5">{d.category}</div>
              </button>
            ))}
          </div>

          {/* Details */}
          <div className="md:col-span-2 p-4 rounded-xl bg-background border border-border overflow-y-auto">
            {selectedDoc ? (
              <div className="space-y-3">
                <div className="flex items-center justify-between border-b border-border/80 pb-2">
                  <h4 className="text-sm font-semibold text-white">{selectedDoc.title}</h4>
                  <span className="px-2 py-0.5 rounded-full bg-indigo-500/10 text-indigo-400 text-[10px] font-mono border border-indigo-500/20">
                    {selectedDoc.category}
                  </span>
                </div>
                <pre className="text-xs font-mono text-gray-300 whitespace-pre-wrap leading-relaxed">
                  {selectedDoc.content}
                </pre>
              </div>
            ) : (
              <div className="text-center py-12 text-gray-500 text-xs">Chọn tài liệu để xem nội dung chi tiết.</div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="mt-4 pt-3 border-t border-border flex items-center justify-between text-[11px] text-gray-400">
          <span>Hệ thống tự động nhúng ngữ cảnh RAG vào mỗi truy vấn của AI Agent</span>
          <button
            onClick={onClose}
            className="px-4 py-1.5 rounded-xl bg-card hover:bg-cardHover border border-border text-gray-200 text-xs transition-colors"
          >
            Đóng
          </button>
        </div>
      </div>
    </div>
  );
};

