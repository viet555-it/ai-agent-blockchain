"use client";

import React, { useState } from "react";
import { Navbar } from "@/components/Navbar";
import { ChatInterface } from "@/components/ChatInterface";
import { WalletOverview } from "@/components/WalletOverview";
import { QuickActions } from "@/components/QuickActions";
import { GuardrailPanel } from "@/components/GuardrailPanel";
import { SettingsModal } from "@/components/SettingsModal";
import { RAGKnowledgeModal } from "@/components/RAGKnowledgeModal";
import { ShieldCheck, Database, FileText, UserCheck } from "lucide-react";

export default function Home() {
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isRAGModalOpen, setIsRAGModalOpen] = useState(false);
  const [selectedPrompt, setSelectedPrompt] = useState<string | undefined>(undefined);
  const [sidebarTab, setSidebarTab] = useState<"wallet" | "guardrail">("wallet");

  const handleQuickAction = (prompt: string) => {
    setSelectedPrompt(prompt);
  };

  return (
    <div className="min-h-screen flex flex-col bg-background text-gray-100">
      <Navbar onOpenSettings={() => setIsSettingsOpen(true)} />

      <main className="flex-1 max-w-7xl w-full mx-auto p-4 sm:p-6 lg:p-8">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
          {/* Main Chat Hub (Left 7 or 8 cols) */}
          <div className="lg:col-span-8">
            <ChatInterface
              externalPrompt={selectedPrompt}
              onClearExternalPrompt={() => setSelectedPrompt(undefined)}
              onOpenRAG={() => setIsRAGModalOpen(true)}
            />
          </div>

          {/* Sidebar Tools & Overview (Right 4 cols) */}
          <div className="lg:col-span-4 space-y-4">
            {/* Sidebar Tab Switcher */}
            <div className="flex bg-card rounded-xl p-1 border border-border">
              <button
                onClick={() => setSidebarTab("wallet")}
                className={`flex-1 py-1.5 rounded-lg text-xs font-medium transition-all ${
                  sidebarTab === "wallet"
                    ? "bg-indigo-600 text-white shadow"
                    : "text-gray-400 hover:text-gray-200"
                }`}
              >
                Ví & Thao tác
              </button>
              <button
                onClick={() => setSidebarTab("guardrail")}
                className={`flex-1 py-1.5 rounded-lg text-xs font-medium transition-all ${
                  sidebarTab === "guardrail"
                    ? "bg-indigo-600 text-white shadow"
                    : "text-gray-400 hover:text-gray-200"
                }`}
              >
                Guardrail & Logs
              </button>
            </div>

            {sidebarTab === "wallet" ? (
              <>
                {/* Wallet Info */}
                <WalletOverview />

                {/* Quick Action prompts */}
                <QuickActions onSelectAction={handleQuickAction} />
              </>
            ) : (
              /* Guardrail Policy & Audit Logs Panel */
              <GuardrailPanel />
            )}

            {/* Project & Role Info (Section 1 in Report) */}
            <div className="p-4 rounded-2xl bg-card border border-border text-xs space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 text-indigo-400 font-semibold">
                  <UserCheck className="h-4 w-4" />
                  <span>Đặng Phương Nam (2301040129)</span>
                </div>
                <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-indigo-500/10 text-indigo-300 border border-indigo-500/20">
                  Backend + Frontend
                </span>
              </div>
              <p className="text-gray-400 leading-relaxed text-[11px]">
                Xây dựng toàn bộ hệ thống <strong>FastAPI Backend</strong> + <strong>Next.js Frontend</strong> tích hợp <strong>Web3 Tool Calling</strong>, <strong>Guardrail Policy Engine</strong> và <strong>RAG Knowledge Context</strong> theo đúng đặc tả báo cáo tiến độ giữa kỳ ATI.
              </p>
              <div className="pt-2 border-t border-border/60 flex items-center justify-between text-[10px] text-gray-500 font-mono">
                <button
                  onClick={() => setIsRAGModalOpen(true)}
                  className="text-indigo-400 hover:underline flex items-center gap-1"
                >
                  <Database className="h-3 w-3" />
                  <span>Tra cứu RAG ABI Docs</span>
                </button>
                <span>ATI Final 2026</span>
              </div>
            </div>
          </div>
        </div>
      </main>

      <SettingsModal isOpen={isSettingsOpen} onClose={() => setIsSettingsOpen(false)} />
      <RAGKnowledgeModal isOpen={isRAGModalOpen} onClose={() => setIsRAGModalOpen(false)} />
    </div>
  );
}
